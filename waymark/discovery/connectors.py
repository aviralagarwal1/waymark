"""Documented public ATS APIs and JobPosting JSON-LD, with explicit completeness."""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import html
import json
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .errors import DiscoveryError
from .safety import public_url, safe_fetch

CONNECTORS = {"auto", "greenhouse", "lever", "ashby", "jsonld", "demo"}
MAX_POSTINGS = 5000
LEVER_PAGE_SIZE = 100
MAX_PAGES = 20


def text_content(value) -> str:
    return BeautifulSoup(html.unescape(str(value or "")), "html.parser").get_text(" ", strip=True)[:100_000]


def iso_date(value) -> str | None:
    if not isinstance(value, str) or not re.match(r"^\d{4}-\d{2}-\d{2}(?:$|T)", value):
        return None
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
        return value
    except ValueError:
        return None


def validate_source_url(url: str, connector: str = "auto") -> dict:
    if connector not in CONNECTORS:
        raise DiscoveryError("Unsupported connector.", code="unsupported_connector")
    if connector == "demo":
        if not re.fullmatch(r"https://demo\.example/[a-z0-9-]{1,80}/?", url or ""):
            raise DiscoveryError("Demo sources use https://demo.example/company-slug.", code="unsafe_url")
        return {"connector": "demo", "url": url.rstrip("/"), "board": urlsplit(url).path.strip("/")}
    url, _ = public_url(url)
    parsed = urlsplit(url)
    host = parsed.hostname
    segments = [x for x in parsed.path.split("/") if x]
    inferred, board, canonical = "jsonld", host + parsed.path, url
    if host in {"boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io"}:
        board = parse_qs(parsed.query).get("for", [None])[0] if segments and segments[0] == "embed" else (segments[0] if segments else None)
        inferred = "greenhouse"
        canonical = f"https://{'job-boards.eu.greenhouse.io' if '.eu.' in host else 'job-boards.greenhouse.io'}/{board}"
    elif host in {"boards-api.greenhouse.io", "boards-api.eu.greenhouse.io"} and len(segments) >= 3 and segments[:2] == ["v1", "boards"]:
        inferred, board = "greenhouse", segments[2]
        canonical = f"https://{'job-boards.eu.greenhouse.io' if '.eu.' in host else 'job-boards.greenhouse.io'}/{board}"
    elif host in {"jobs.lever.co", "jobs.eu.lever.co"}:
        inferred, board = "lever", (segments[0] if segments else None)
        canonical = f"https://{host}/{board}"
    elif host in {"api.lever.co", "api.eu.lever.co"} and len(segments) >= 3 and segments[:2] == ["v0", "postings"]:
        inferred, board = "lever", segments[2]
        canonical = f"https://{'jobs.eu.lever.co' if '.eu.' in host else 'jobs.lever.co'}/{board}"
    elif host == "jobs.ashbyhq.com":
        inferred, board = "ashby", (segments[0] if segments else None)
        canonical = f"https://jobs.ashbyhq.com/{board}"
    elif host == "api.ashbyhq.com" and len(segments) >= 3 and segments[:2] == ["posting-api", "job-board"]:
        inferred, board = "ashby", segments[2]
        canonical = f"https://jobs.ashbyhq.com/{board}"
    if inferred != "jsonld" and (not board or not re.fullmatch(r"[A-Za-z0-9_-]{1,100}", board)):
        raise DiscoveryError("The ATS URL must identify an employer board.", code="invalid_board")
    if connector not in {"auto", inferred}:
        raise DiscoveryError("The selected connector does not match the source hostname.", code="connector_mismatch")
    return {"connector": inferred, "url": canonical, "board": board}


def _job(connector, board, source_url, native_id, title, url, **fields):
    if native_id in {None, ""} or not isinstance(title, str) or not title.strip() or not isinstance(url, str):
        raise DiscoveryError("A posting is missing its identity, title, or URL.", code="invalid_response")
    public_url(url, resolve=False)
    defaults = {"company": "", "location": "", "description": "", "employment_type": "", "published_at": None, "updated_at": None, "date_meaning": "unknown"}
    defaults.update(fields)
    return {"external_id": f"{connector}:{board}:{native_id}", "title": title[:500], "url": url, "source_url": source_url, **defaults}


def _address(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "; ".join(filter(None, (_address(item) for item in value)))
    if isinstance(value, dict):
        if "address" in value:
            return _address(value["address"])
        if "postalAddress" in value:
            return _address(value["postalAddress"])
        return ", ".join(str(value.get(field) or "") for field in ("addressLocality", "addressRegion", "addressCountry") if value.get(field))
    return ""


def _fetch_board(ats, url, board):
    # A 404 from an ATS API means no board has that name, almost always a typo
    # in the careers page address, so say that rather than an HTTP status.
    try:
        return safe_fetch(url)
    except DiscoveryError as exc:
        if exc.code == "not_found":
            raise DiscoveryError(f"{ats} has no board named {board}; check the careers page address.", code="not_found") from None
        raise


def _greenhouse(config):
    api = "boards-api.eu.greenhouse.io" if ".eu." in config["url"] else "boards-api.greenhouse.io"
    payload = _fetch_board("Greenhouse", f"https://{api}/v1/boards/{config['board']}/jobs?content=true", config["board"]).json()
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise DiscoveryError("Greenhouse returned an unexpected job-list format.")
    jobs = payload["jobs"]
    postings = []
    for item in jobs[:MAX_POSTINGS]:
        first = iso_date(item.get("first_published"))
        updated = iso_date(item.get("updated_at"))
        postings.append(_job("greenhouse", api + "/" + config["board"], config["url"], item.get("id"), item.get("title"), item.get("absolute_url"), company=item.get("company_name") or "", location=(item.get("location") or {}).get("name", ""), description=text_content(item.get("content")), published_at=first, updated_at=updated, date_meaning="original_posted" if first else ("updated" if updated else "unknown")))
    total = (payload.get("meta") or {}).get("total", len(jobs))
    complete = len(jobs) <= MAX_POSTINGS and total == len(jobs)
    return postings, complete, "" if complete else "Greenhouse result count is incomplete or exceeds the local cap."


def _lever(config):
    api = "api.eu.lever.co" if ".eu." in config["url"] else "api.lever.co"
    postings, seen = [], set()
    for page in range(MAX_PAGES):
        try:
            jobs = _fetch_board("Lever", f"https://{api}/v0/postings/{config['board']}?mode=json&limit={LEVER_PAGE_SIZE}&skip={page * LEVER_PAGE_SIZE}", config["board"]).json()
            if not isinstance(jobs, list):
                raise DiscoveryError("Lever returned an unexpected job-list format.")
            for item in jobs[:LEVER_PAGE_SIZE]:
                native_id = item.get("id")
                if native_id in seen:
                    return postings, False, "Lever repeated a posting across pages; pagination could not be confirmed."
                categories = item.get("categories") or {}
                extra = " ".join(text_content(entry.get("text")) + " " + text_content(entry.get("content")) for entry in item.get("lists", []))
                postings.append(_job("lever", api + "/" + config["board"], config["url"], native_id, item.get("text"), item.get("hostedUrl"), company=item.get("company") or "", location=categories.get("location", ""), description=(text_content(item.get("descriptionPlain") or item.get("description")) + " " + extra + " " + text_content(item.get("additionalPlain") or item.get("additional")))[:100_000], employment_type=categories.get("commitment", "")))
                seen.add(native_id)
            if len(jobs) > LEVER_PAGE_SIZE:
                return postings, False, "Lever exceeded the requested page size; pagination could not be confirmed."
            if len(jobs) < LEVER_PAGE_SIZE:
                return postings, True, ""
        except (DiscoveryError, TypeError, AttributeError, KeyError) as exc:
            if postings:
                return postings, False, str(exc) if isinstance(exc, DiscoveryError) else "A Lever posting had an invalid format."
            # Keep the reason (no such board, timeout, too large) rather than
            # one message for every first-page failure.
            if isinstance(exc, DiscoveryError):
                raise
            raise DiscoveryError("Lever could not return a complete first page.") from None
    return postings, False, "Lever pagination reached the local page cap."


def _ashby(config):
    payload = _fetch_board("Ashby", f"https://api.ashbyhq.com/posting-api/job-board/{config['board']}", config["board"]).json()
    if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
        raise DiscoveryError("Ashby returned an unexpected job-list format.")
    jobs = payload["jobs"]
    postings = []
    for item in jobs[:MAX_POSTINGS]:
        if item.get("isListed") is False:
            continue
        url = item.get("jobUrl")
        native_id = item.get("id") or (urlsplit(url).path.rstrip("/").split("/")[-1] if isinstance(url, str) else None)
        published = iso_date(item.get("publishedAt"))
        location = "; ".join(filter(None, [item.get("location", ""), _address(item.get("address")), *[loc.get("location", "") for loc in item.get("secondaryLocations", [])]]))
        if item.get("isRemote"):
            location += "; Remote"
        postings.append(_job("ashby", config["board"], config["url"], native_id, item.get("title"), url, company=item.get("companyName", ""), location=location, description=text_content(item.get("descriptionPlain") or item.get("descriptionHtml")), employment_type=item.get("employmentType", ""), published_at=published, date_meaning="last_published" if published else "unknown"))
    complete = len(jobs) <= MAX_POSTINGS
    return postings, complete, "" if complete else "Ashby result count exceeds the local cap."


def jsonld_jobs(document):
    """Return postings and parser completeness; no markup != an empty board."""
    soup = BeautifulSoup(document.text, "html.parser")
    nodes, malformed = [], False
    for script in soup.find_all("script", attrs={"type": re.compile(r"^application/ld\+json", re.I)}):
        try:
            nodes.append(json.loads(script.string or script.get_text()))
        except (ValueError, RecursionError):
            malformed = True
    jobs = []
    visited = 0
    while nodes:
        node = nodes.pop()
        visited += 1
        if visited > 30_000:
            malformed = True
            break
        if isinstance(node, list):
            nodes.extend(node)
        elif isinstance(node, dict):
            types = node.get("@type", [])
            if types == "JobPosting" or (isinstance(types, list) and "JobPosting" in types):
                jobs.append(node)
            else:
                nodes.extend(v for v in node.values() if isinstance(v, (list, dict)))
    postings = []
    for item in jobs[:MAX_POSTINGS]:
        try:
            url = urljoin(document.url, item.get("url") or document.url)
            identifier = item.get("identifier")
            if isinstance(identifier, dict):
                identifier = identifier.get("value")
            if not isinstance(identifier, (str, int)):
                identifier = sha256(url.encode()).hexdigest()[:24]
            company = item.get("hiringOrganization") or {}
            if isinstance(company, dict):
                company = company.get("name", "")
            published = iso_date(item.get("datePosted"))
            kind = item.get("employmentType") or ""
            if isinstance(kind, list):
                kind = ", ".join(kind)
            location = _address(item.get("jobLocation"))
            if item.get("jobLocationType") == "TELECOMMUTE":
                location += "; Remote"
            postings.append(_job("jsonld", urlsplit(document.url).hostname, document.url, identifier, item.get("title"), url, company=company, location=location, description=text_content(item.get("description")), employment_type=kind, published_at=published, date_meaning="original_posted" if published else "unknown"))
        except (DiscoveryError, TypeError, AttributeError):
            malformed = True
    return postings, not malformed and len(jobs) <= MAX_POSTINGS


def demo_start_year(today: date | None = None) -> int:
    """The start cohort the demo is recruiting for: next year's.

    The seeded demo targets and the demo board both use this, because the demo
    only produces matches when their start cohorts agree. Last cycle's opening
    is September two years before the start, one cycle earlier.
    """
    return (today or datetime.now(timezone.utc).date()).year + 1


def _demo(config, today: date | None = None):
    board = config["board"]
    company = {"northstar": "Northstar Labs", "harbor": "Harbor Robotics", "cedar": "Cedar Research"}.get(board, board.replace("-", " ").title())
    start = demo_start_year(today)
    # Synthetic fixtures; never claim these came from a real employer. The
    # cohort year rolls forward with the date so the demo never goes stale.
    fixtures = [
        (f"product-{start}", "Associate Product Manager", "Chicago, United States", "FullTime", f"Entry level rotation. Start in Summer {start}. Applications are open."),
        (f"engineering-{start}", "Software Engineer", "London, United Kingdom", "FullTime", f"New graduate engineering role. Start in September {start}."),
        (f"research-{start}", "Research Intern", "London, United Kingdom", "Intern", f"Research internship for Summer {start}. Current students welcome."),
        (f"design-{start}", "Product Designer", "Berlin, Germany", "FullTime", f"Junior design program starting Summer {start}."),
    ]
    return [{"external_id": f"demo:{board}:{native}", "company": company, "title": title, "url": f"https://demo.example/{board}/{native}", "location": location, "description": description, "employment_type": employment_type, "published_at": None, "updated_at": None, "date_meaning": "unknown", "source_url": config["url"]} for native, title, location, employment_type, description in fixtures]


def fetch_source(url: str, connector: str = "auto", *, demo: bool = False) -> dict:
    result = {"status": "failed", "postings": [], "error": "", "source_url": url, "connector": connector, "complete": False}
    try:
        if demo and connector != "demo":
            raise DiscoveryError("Demo mode only reads synthetic demo sources.")
        config = validate_source_url(url, connector)
        result.update(source_url=config["url"], connector=config["connector"])
        if config["connector"] == "demo":
            if not demo:
                raise DiscoveryError("Demo sources are disabled in live mode.")
            return {**result, "status": "ok", "postings": _demo(config), "complete": True}
        if demo:
            raise DiscoveryError("Demo mode only reads synthetic demo sources.")
        if config["connector"] == "jsonld":
            document = safe_fetch(config["url"])
            postings, complete = jsonld_jobs(document)
            if not postings:
                return {**result, "status": "unsupported", "error": "No readable JobPosting structured data was found; dynamic pages need a supported ATS source."}
            error = "" if complete else "Some structured data could not be read."
        else:
            postings, complete, error = {"greenhouse": _greenhouse, "lever": _lever, "ashby": _ashby}[config["connector"]](config)
        identities = [posting["external_id"] for posting in postings]
        if len(set(identities)) != len(identities):
            complete, error = False, "Source repeated posting identities."
        return {**result, "status": "ok" if complete else "partial", "postings": postings, "error": error, "complete": complete}
    except (DiscoveryError, TypeError, AttributeError, KeyError, ValueError) as exc:
        return {**result, "error": str(exc) if isinstance(exc, DiscoveryError) else "Source returned an invalid posting format."}
