import json
from unittest.mock import patch

import pytest

from waymark.discovery import DiscoveryError, fetch_source, research_target, validate_source_url
from waymark.discovery.connectors import jsonld_jobs
from waymark.discovery.safety import Document, public_url, safe_fetch


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))])
    monkeypatch.setattr("socket.create_connection", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Tests must never connect to live websites")))


@pytest.mark.parametrize("url", ["http://127.0.0.1", "http://169.254.169.254/latest", "http://10.0.0.1", "http://172.16.4.5", "http://192.168.1.9", "http://localhost", "http://[::1]", "file:///etc/passwd", "https://u:p@careers.example.org", "https://careers.example.org:8080", "https://careers.example.org\\@evil.org", "https://careers.example.org\nHost:evil.org", "http://224.0.0.1", "http://100.64.0.1"])
def test_rejects_unsafe_urls(url):
    with pytest.raises(DiscoveryError):
        public_url(url)


def test_rejects_mixed_public_private_dns(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443)), (2, 1, 6, "", ("127.0.0.1", 443))])
    with pytest.raises(DiscoveryError, match="non-public"):
        public_url("https://careers.example.org")


@pytest.mark.parametrize("url,connector,board", [
    ("https://boards.greenhouse.io/acme/jobs/123", "greenhouse", "acme"),
    ("https://boards-api.greenhouse.io/v1/boards/acme/jobs", "greenhouse", "acme"),
    ("https://boards.greenhouse.io/embed/job_app?for=acme&token=123", "greenhouse", "acme"),
    ("https://jobs.eu.lever.co/acme/123", "lever", "acme"),
    ("https://jobs.ashbyhq.com/acme/123", "ashby", "acme"),
])
def test_extracts_real_board_mapping(url, connector, board):
    result = validate_source_url(url)
    assert result["connector"] == connector
    assert result["board"] == board


def test_connector_cannot_be_spoofed():
    with pytest.raises(DiscoveryError):
        validate_source_url("https://jobs.lever.co.evil.org/acme", "lever")


def test_greenhouse_update_is_not_publication(monkeypatch):
    payload = {"jobs": [{"id": 1, "title": "Engineer", "absolute_url": "https://careers.example.org/1", "updated_at": "2026-08-01T00:00:00Z", "content": "A full description", "location": {"name": "Berlin"}}], "meta": {"total": 1}}
    monkeypatch.setattr("waymark.discovery.connectors.safe_fetch", lambda url: Document(url, json.dumps(payload), "application/json"))
    result = fetch_source("https://job-boards.greenhouse.io/acme")
    assert result["complete"]
    job = result["postings"][0]
    assert job["published_at"] is None and job["date_meaning"] == "updated"
    assert job["external_id"] == "greenhouse:boards-api.greenhouse.io/acme:1"


def test_greenhouse_mismatched_total_is_partial(monkeypatch):
    monkeypatch.setattr("waymark.discovery.connectors.safe_fetch", lambda url: Document(url, '{"jobs":[],"meta":{"total":1}}', "application/json"))
    result = fetch_source("https://job-boards.greenhouse.io/acme")
    assert result["status"] == "partial" and not result["complete"]


def _lever_job(index):
    return {"id": str(index), "text": "Engineer", "hostedUrl": f"https://jobs.lever.co/acme/{index}", "categories": {"location": "London", "commitment": "Full-time"}, "createdAt": 1_700_000_000_000}


def test_lever_paginates_and_does_not_invent_creation_date(monkeypatch):
    calls = []
    def fetch(url):
        calls.append(url)
        jobs = [_lever_job(n) for n in range(100)] if "skip=0" in url else [_lever_job(100)]
        return Document(url, json.dumps(jobs), "application/json")
    monkeypatch.setattr("waymark.discovery.connectors.safe_fetch", fetch)
    result = fetch_source("https://jobs.lever.co/acme")
    assert len(calls) == 2 and "skip=100" in calls[1]
    assert result["status"] == "ok" and len(result["postings"]) == 101
    assert all(job["published_at"] is None for job in result["postings"])


def test_lever_failure_after_first_page_is_partial(monkeypatch):
    def fetch(url):
        if "skip=0" not in url:
            raise DiscoveryError("Rate limited")
        return Document(url, json.dumps([_lever_job(n) for n in range(100)]), "application/json")
    monkeypatch.setattr("waymark.discovery.connectors.safe_fetch", fetch)
    result = fetch_source("https://jobs.lever.co/acme")
    assert result["status"] == "partial" and len(result["postings"]) == 100


def test_lever_repeated_page_cannot_be_complete(monkeypatch):
    monkeypatch.setattr("waymark.discovery.connectors.safe_fetch", lambda url: Document(url, json.dumps([_lever_job(n) for n in range(100)]), "application/json"))
    result = fetch_source("https://jobs.lever.co/acme")
    assert result["status"] == "partial" and "repeated" in result["error"]


def test_source_native_ids_are_scoped_to_employer(monkeypatch):
    monkeypatch.setattr("waymark.discovery.connectors.safe_fetch", lambda url: Document(url, json.dumps([_lever_job(1)]), "application/json"))
    one = fetch_source("https://jobs.lever.co/acme")["postings"][0]
    two = fetch_source("https://jobs.lever.co/other")["postings"][0]
    assert one["external_id"] != two["external_id"]


def test_ashby_last_publication_and_unlisted_posts(monkeypatch):
    jobs = [{"id": "one", "title": "Engineer", "jobUrl": "https://jobs.ashbyhq.com/acme/one", "publishedAt": "2026-08-01T00:00:00Z", "isListed": True}, {"id": "secret", "isListed": False}]
    monkeypatch.setattr("waymark.discovery.connectors.safe_fetch", lambda url: Document(url, json.dumps({"jobs": jobs}), "application/json"))
    result = fetch_source("https://jobs.ashbyhq.com/acme")
    assert result["status"] == "ok" and len(result["postings"]) == 1
    assert result["postings"][0]["date_meaning"] == "last_published"


def test_jsonld_graph_and_invalid_date():
    payload = {"@graph": [{"@type": "JobPosting", "title": "Research Intern", "url": "/jobs/1", "identifier": {"value": "one"}, "datePosted": "2026-99-99", "hiringOrganization": {"name": "Example Lab"}, "employmentType": ["INTERN"], "jobLocation": {"address": {"addressLocality": "London", "addressCountry": "UK"}}}]}
    doc = Document("https://careers.example.org/jobs", '<script type="application/ld+json">' + json.dumps(payload) + '</script>', "text/html")
    postings, complete = jsonld_jobs(doc)
    assert complete and postings[0]["published_at"] is None
    assert postings[0]["url"] == "https://careers.example.org/jobs/1"


def test_missing_jsonld_is_unsupported_not_success(monkeypatch):
    monkeypatch.setattr("waymark.discovery.connectors.safe_fetch", lambda url: Document(url, "<h1>Access denied</h1>", "text/html"))
    result = fetch_source("https://careers.example.org")
    assert result["status"] == "unsupported" and not result["complete"]


def test_demo_never_resolves_or_fetches_network(monkeypatch):
    monkeypatch.setattr("socket.getaddrinfo", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("Demo must not resolve DNS")))
    assert fetch_source("https://demo.example/northstar", "demo", demo=True)["status"] == "ok"
    assert fetch_source("https://jobs.lever.co/acme", demo=True)["status"] == "failed"
    assert research_target({"company": "Northstar Labs", "role": "Engineer"}, demo=True)["usage"]["estimated_cost_usd"] == 0
    assert fetch_source("https://demo.example/northstar", "demo")["status"] == "failed"


def test_manual_source_needs_no_ai_key(monkeypatch):
    monkeypatch.setattr("waymark.discovery.connectors.safe_fetch", lambda url: Document(url, '{"jobs":[]}', "application/json"))
    result = research_target({"company": "Acme", "role": "Engineer", "source_url": "https://jobs.ashbyhq.com/acme"})
    assert result["status"] == "ready" and result["historical_date"] is None


def test_missing_key_is_reviewable():
    assert research_target({"company": "Acme", "role": "Engineer"})["status"] == "needs_review"


class FakeResponse:
    status = 302
    def getheader(self, key, default=None):
        return "http://169.254.169.254/latest" if key == "Location" else default


def test_redirect_to_metadata_is_blocked_before_connection(monkeypatch):
    class Conn:
        def __init__(self, *a, **kw):
            self.sock = None
        def request(self, *a, **kw):
            pass
        def getresponse(self):
            return FakeResponse()
        def close(self):
            pass
    monkeypatch.setattr("waymark.discovery.safety._PinnedHTTP", Conn)
    with pytest.raises(DiscoveryError, match="Non-public"):
        safe_fetch("https://careers.example.org")


class BodyResponse:
    def __init__(self, status, body=b"", location=None):
        self.status, self.body, self.location = status, body, location
    def getheader(self, key, default=None):
        return {"Location": self.location, "Content-Type": "application/json"}.get(key) or default
    def read1(self, size):
        chunk, self.body = self.body[:size], self.body[size:]
        return chunk


def serve(monkeypatch, responses):
    """Answer each request from responses[hostname], with no network."""
    class Conn:
        def __init__(self, host, *a, **kw):
            self.host, self.sock = host, None
        def request(self, *a, **kw):
            pass
        def getresponse(self):
            return responses[self.host]()
        def close(self):
            pass
    monkeypatch.setattr("waymark.discovery.safety._PinnedHTTP", Conn)


def test_ats_apis_may_return_whole_boards_but_other_hosts_keep_the_general_cap(monkeypatch):
    body = b'{"jobs":[],"pad":"' + b"x" * 5_000_000 + b'"}'
    serve(monkeypatch, {
        "api.ashbyhq.com": lambda: BodyResponse(200, body),
        "careers.example.org": lambda: BodyResponse(200, body),
        "api.lever.co": lambda: BodyResponse(302, location="https://careers.example.org/jobs"),
    })
    assert fetch_source("https://jobs.ashbyhq.com/acme")["status"] == "ok"
    with pytest.raises(DiscoveryError, match="size limit"):
        safe_fetch("https://careers.example.org/jobs")
    with pytest.raises(DiscoveryError, match="size limit"):
        safe_fetch("https://api.lever.co/v0/postings/acme")


@pytest.mark.parametrize("url,ats,host", [
    ("https://job-boards.greenhouse.io/acme", "Greenhouse", "boards-api.greenhouse.io"),
    ("https://jobs.lever.co/acme", "Lever", "api.lever.co"),
    ("https://jobs.ashbyhq.com/acme", "Ashby", "api.ashbyhq.com"),
])
def test_missing_board_is_named_rather_than_an_http_status(monkeypatch, url, ats, host):
    serve(monkeypatch, {host: lambda: BodyResponse(404, b'{"ok":false}')})
    result = fetch_source(url)
    assert result["status"] == "failed"
    assert result["error"] == f"{ats} has no board named acme; check the careers page address."


def test_pinned_connection_uses_prevalidated_ip(monkeypatch):
    from waymark.discovery.safety import _PinnedHTTP
    with patch("socket.create_connection") as connect:
        conn = _PinnedHTTP("careers.example.org", "93.184.216.34", 80, 10, False)
        conn.connect()
        connect.assert_called_once_with(("93.184.216.34", 80), 10)
