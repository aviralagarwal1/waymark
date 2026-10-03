"""Conservative matching: missing eligibility yields review, never an AI default yes."""
from __future__ import annotations

import re
import unicodedata


def normalize(value) -> str:
    value = unicodedata.normalize("NFKC", str(value or "")).casefold()
    value = re.sub(r"\bu\.?s\.?a?\.?\b|\bunited states(?: of america)?\b", " united states ", value)
    value = re.sub(r"\bu\.?k\.?\b|\bgreat britain\b", " united kingdom ", value)
    return " ".join(re.findall(r"[^\W_]+", value, flags=re.UNICODE))


# Words that give a title's rank but not its field. Sharing only these does not
# make two titles related: "Product Manager" and "Customer Success Manager"
# share "manager" alone. "Engineer" is left out on purpose, so a "Software
# Engineer" target still sees "Full Stack Engineer" for review.
GENERIC_TITLE_WORDS = {"manager", "senior", "sr", "staff", "lead", "principal", "associate", "junior", "intern", "director", "head", "ii", "iii", "iv"}


def _role(value) -> set[str]:
    value = normalize(value)
    aliases = {"apm": "associate product manager", "pm": "product manager", "swe": "software engineer", "sde": "software engineer", "developer": "engineer", "internship": "intern", "internships": "intern", "engineering": "engineer"}
    words = " ".join(aliases.get(word, word) for word in value.split()).split()
    return set(words) - {"a", "an", "the", "and", "or", "of", "for", "program", "programme", "role", "position", "i"}


def _company(value) -> str:
    return " ".join(word for word in normalize(value).split() if word not in {"inc", "incorporated", "corporation", "corp", "llc", "ltd", "limited", "company", "co"})


def _employment(value) -> set[str]:
    value = re.sub(r"[^a-z]", "", str(value or "").lower())
    kinds = set()
    for token, kind in [("intern", "intern"), ("fulltime", "fulltime"), ("parttime", "parttime"), ("contract", "contract"), ("temporary", "temporary")]:
        if token in value:
            kinds.add(kind)
    return kinds


COUNTRIES = {"united states", "united kingdom", "canada", "germany", "france", "india", "australia", "singapore", "japan", "brazil", "ireland", "netherlands", "spain"}
CITY_COUNTRIES = {"london": "united kingdom", "berlin": "germany", "paris": "france", "toronto": "canada", "vancouver": "canada", "sydney": "australia", "tokyo": "japan", "dublin": "ireland", "amsterdam": "netherlands", "chicago": "united states", "new york": "united states", "san francisco": "united states", "seattle": "united states", "boston": "united states", "austin": "united states"}


def _contains(phrase, text):
    return f" {phrase} " in f" {text} "


def _countries(location):
    found = {country for country in COUNTRIES if _contains(country, location)}
    found.update(country for city, country in CITY_COUNTRIES.items() if _contains(city, location))
    return found


def match_posting(target: dict, posting: dict) -> dict:
    """Evaluate title, employer, type, level, geography and cohort independently.

    Employer may be absent from an ATS response; its already-approved source
    mapping then supplies identity. This matcher does not approve that mapping.
    """
    reasons, unknown = [], []
    title = normalize(posting.get("title"))
    description = normalize(posting.get("description"))
    text = title + " " + description
    company = _company(posting.get("company"))
    desired_company = _company(target.get("company"))
    if company and desired_company and company != desired_company:
        reasons.append("Employer differs from the requested company")
    desired_role, posted_role = _role(target.get("role")), _role(title)
    if not desired_role:
        unknown.append("Desired role is missing")
    elif not desired_role.issubset(posted_role):
        overlap = desired_role & posted_role
        if overlap - GENERIC_TITLE_WORDS and len(overlap) >= len(desired_role) / 2:
            unknown.append("Related title; exact role or program needs review")
        else:
            reasons.append("Title does not match the requested role")
    wanted_type = _employment(target.get("employment_type"))
    posted_type = _employment(posting.get("employment_type"))
    if re.search(r"\bintern(?:ship)?\b", title):
        posted_type.add("intern")
    if wanted_type:
        if posted_type and not wanted_type.intersection(posted_type):
            reasons.append("Employment type differs from the requested type")
        elif "intern" in posted_type and "intern" not in wanted_type:
            reasons.append("Internship does not satisfy a non-internship target")
        elif not posted_type:
            # Greenhouse sends no employment type, so read the description,
            # but only for "full time" and "part time": "internship",
            # "contract", and "temporary" turn up in passing on roles of every
            # type ("prior internship experience" on a new-grad role,
            # "government contracts" on a full-time one).
            described = _employment(" ".join(re.findall(r"\b(?:full time|part time)\b", description)))
            if described and not wanted_type.intersection(described):
                reasons.append("Employment type differs from the requested type")
            elif not described:
                unknown.append("Employment type is not stated")
    level = normalize(target.get("level"))
    if wanted_type == {"intern"} and re.search(r"\b(senior|sr|staff|principal|director|head|lead|manager)\b", title):
        # An internship target is entry level even without a level set.
        reasons.append("Title indicates a more senior role")
    elif level in {"entry", "entry level", "new grad", "graduate", "junior"}:
        if re.search(r"\b(senior|sr|staff|principal|director|head|lead)\b", title):
            reasons.append("Title indicates a more senior role")
        elif re.search(r"\b(?:minimum|at least|requires?) (?:[3-9]|[1-9][0-9]) (?:plus )?years", description) or re.search(r"\b(?:[3-9]|[1-9][0-9]) years of (?:professional|relevant|industry) experience", description):
            reasons.append("Required experience exceeds the requested entry level")
        elif not re.search(r"\b(entry level|new grad|new graduate|graduate|junior|associate|intern|early career|no experience)\b", text):
            unknown.append("Entry-level eligibility is not established")
    elif level and level not in {"any", "all"} and not _contains(level, text):
        unknown.append("Requested experience level is not established")
    wanted_location = normalize(target.get("location"))
    location = normalize(posting.get("location"))
    if wanted_location and wanted_location not in {"any", "anywhere", "worldwide", "global"}:
        options = [normalize(option) for option in re.split(r"[;|]|\s+or\s+", str(target.get("location")), flags=re.I)]
        if not location:
            unknown.append("Work location is not stated")
        elif any(_contains(option, location) for option in options):
            pass
        elif any(option in COUNTRIES and option in _countries(location) for option in options):
            pass
        elif _countries(wanted_location) and _countries(location) and not (_countries(wanted_location) & _countries(location)):
            reasons.append("Work geography differs from the requested location")
        elif wanted_location == "remote" and _contains("onsite", location):
            reasons.append("Role is explicitly on-site")
        else:
            unknown.append("Work geography needs confirmation (remote does not establish country eligibility)")
    wanted_years = set(re.findall(r"\b20\d{2}\b", str(target.get("start_period") or "")))
    if wanted_years:
        # A cohort the title states is the posting's own. A description can
        # name others in passing ("do not apply if you are looking for summer
        # or fall" on a winter internship), so it is read only when the title
        # is silent. Seasons below follow the same rule.
        stated_years = set(re.findall(r"\b20\d{2}\b", title))
        # A graduation requirement, footer year, or publication date is not a start date.
        for clause in [] if stated_years else re.split(r"[.!?;\n]", str(posting.get("description") or "").lower()):
            if re.search(r"\b(start(?:ing|s)?|begin(?:ning|s)?|join|summer|winter|spring|fall|autumn|cohort)\b", clause) and not re.search(r"\b(copyright|posted|published|graduat(?:e|ion|ing))\b", clause):
                stated_years.update(re.findall(r"\b20\d{2}\b", clause))
        if stated_years and not stated_years.intersection(wanted_years):
            reasons.append("Stated start cohort differs from the requested period")
        elif not stated_years:
            unknown.append("Start cohort is not stated")
        desired_seasons = set(re.findall(r"\b(summer|winter|spring|fall|autumn)\b", normalize(target.get("start_period"))))
        stated_seasons = set(re.findall(r"\b(summer|winter|spring|fall|autumn)\b", title))
        if not stated_seasons:
            description_text = str(posting.get("description") or "").lower()
            for clause in re.split(r"[.!?;\n]", description_text):
                if re.search(r"\b(start|starting|starts|begin|beginning|cohort|for)\b", clause):
                    stated_seasons.update(re.findall(r"\b(summer|winter|spring|fall|autumn)\b", clause))
            stated_seasons.update(re.findall(r"\b(summer|winter|spring|fall|autumn)\s+20\d{2}\b", description_text))
        desired_seasons = {"fall" if x == "autumn" else x for x in desired_seasons}
        stated_seasons = {"fall" if x == "autumn" else x for x in stated_seasons}
        if desired_seasons and stated_seasons and not desired_seasons.intersection(stated_seasons):
            reasons.append("Start season differs from the requested period")
        elif desired_seasons and not stated_seasons:
            unknown.append("Start season is not stated")
    if reasons:
        return {"status": "reject", "reason": "; ".join(reasons)}
    if unknown:
        return {"status": "review", "reason": "; ".join(unknown)}
    return {"status": "match", "reason": "Requested role, geography, employment type and stated eligibility agree; source employer mapping requires approval."}
