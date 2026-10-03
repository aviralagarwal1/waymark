"""Bounded public-web requests with DNS pinning and redirect revalidation.

No proxy environment variables, cookies, authentication, JavaScript, or code
execution are used. DNS is resolved once per hop and the approved IP is the
actual connection destination; HTTPS still verifies the original hostname.
"""
from __future__ import annotations

import http.client
import ipaddress
import json
import re
import socket
import ssl
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

from ..brand import BRAND
from .errors import DiscoveryError

MAX_BYTES = 4_000_000
# The ATS job-board APIs return every posting with its full description in one
# response, and a large employer's board runs well past 4 MB: on 2026-10-02
# OpenAI's Ashby board was 13.9 MB and Databricks' Greenhouse board 9.7 MB, so
# the general cap made them fail every check. These hosts are fixed rather than
# user-supplied, and parsing the 13.9 MB board peaked at 71 MB of memory, well
# inside the 512 MiB the service and worker have. Any other host, including one
# an ATS redirects to, keeps the general cap.
ATS_API_HOSTS = frozenset({"boards-api.greenhouse.io", "boards-api.eu.greenhouse.io", "api.lever.co", "api.eu.lever.co", "api.ashbyhq.com"})
ATS_MAX_BYTES = 32_000_000
MAX_URL = 2048
USER_AGENT = f"{BRAND['name']}/0.1 (+{BRAND['repoUrl']}; public job monitoring)"
_limits = ContextVar("discovery_fetch_limits", default=None)


@contextmanager
def request_limits(max_fetches: int, seconds: float):
    token = _limits.set({"remaining": max_fetches, "deadline": time.monotonic() + seconds})
    try:
        yield
    finally:
        _limits.reset(token)


def public_url(url: str, *, resolve: bool = True) -> tuple[str, str | None]:
    if not isinstance(url, str) or not url or len(url) > MAX_URL:
        raise DiscoveryError("A public HTTP(S) URL of at most 2048 characters is required.", code="unsafe_url")
    if re.search(r"[\x00-\x20\x7f\\]", url):
        raise DiscoveryError("URL contains unsupported characters.", code="unsafe_url")
    try:
        parsed = urlsplit(url)
        host = (parsed.hostname or "").encode("idna").decode("ascii").lower().rstrip(".")
        port = parsed.port
    except (ValueError, UnicodeError):
        raise DiscoveryError("Invalid URL.", code="unsafe_url") from None
    if parsed.scheme not in {"http", "https"} or not host or parsed.username is not None or parsed.password is not None:
        raise DiscoveryError("Use a public HTTP(S) URL without credentials.", code="unsafe_url")
    if port not in {None, 80, 443}:
        raise DiscoveryError("Only HTTP(S) service ports are supported.", code="unsafe_url")
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal", ".test", ".invalid", ".example")) or "." not in host:
        raise DiscoveryError("Local and reserved destinations are not allowed.", code="unsafe_url")
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None and (not literal.is_global or literal.is_multicast):
        raise DiscoveryError("Non-public network addresses are not allowed.", code="unsafe_url")
    # IPv6 literals are intentionally unsupported: public IPv6 DNS answers work.
    if ":" in host:
        raise DiscoveryError("Use a public hostname instead of an IPv6 literal.", code="unsafe_url")
    authority = host + (f":{port}" if port else "")
    normalized = urlunsplit((parsed.scheme, authority, parsed.path or "/", parsed.query, ""))
    if not resolve:
        return normalized, None
    try:
        answers = socket.getaddrinfo(host, port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError:
        raise DiscoveryError("The source hostname could not be resolved.", code="dns_failed") from None
    addresses = list(dict.fromkeys(answer[4][0] for answer in answers))
    if not addresses or any(not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast for ip in addresses):
        raise DiscoveryError("DNS resolved to a non-public network address.", code="unsafe_url")
    return normalized, addresses[0]


class _PinnedHTTP(http.client.HTTPConnection):
    def __init__(self, host: str, ip: str, port: int, timeout: float, secure: bool):
        super().__init__(host, port=port, timeout=timeout)
        self.ip = ip
        self.secure = secure

    def connect(self):
        self.sock = socket.create_connection((self.ip, self.port), self.timeout)
        if self.secure:
            self.sock = ssl.create_default_context().wrap_socket(self.sock, server_hostname=self.host)


@dataclass
class Document:
    url: str
    text: str
    content_type: str

    def json(self):
        try:
            return json.loads(self.text)
        except (ValueError, RecursionError):
            raise DiscoveryError("Source returned invalid JSON.", code="invalid_response") from None


def safe_fetch(url: str, *, max_bytes: int | None = None, timeout: float = 15) -> Document:
    deadline = time.monotonic() + timeout
    limits = _limits.get()
    if limits:
        deadline = min(deadline, limits["deadline"])
    for _ in range(4):
        if limits:
            if limits["remaining"] <= 0 or time.monotonic() >= limits["deadline"]:
                raise DiscoveryError("Research reached its page-fetch or time limit.", code="fetch_limit")
            limits["remaining"] -= 1
        url, ip = public_url(url)
        parsed = urlsplit(url)
        limit = max_bytes or (ATS_MAX_BYTES if parsed.hostname in ATS_API_HOSTS else MAX_BYTES)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise DiscoveryError("Source request timed out.", code="timeout")
        conn = _PinnedHTTP(parsed.hostname, ip, parsed.port or (443 if parsed.scheme == "https" else 80), remaining, parsed.scheme == "https")
        try:
            conn.request("GET", urlunsplit(("", "", parsed.path, parsed.query, "")), headers={"User-Agent": USER_AGENT, "Accept": "application/json,text/html;q=0.9", "Accept-Encoding": "identity"})
            response = conn.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location:
                    raise DiscoveryError("Source returned a redirect without a destination.")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise DiscoveryError(f"Source returned HTTP {response.status}.", code="not_found" if response.status == 404 else "http_error")
            if response.getheader("Content-Encoding", "identity").lower() not in {"", "identity"}:
                raise DiscoveryError("Unexpected compressed response.", code="invalid_response")
            body = bytearray()
            while len(body) <= limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise DiscoveryError("Source request timed out.", code="timeout")
                if conn.sock:
                    conn.sock.settimeout(remaining)
                chunk = response.read1(min(65536, limit + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
            if len(body) > limit:
                raise DiscoveryError("Source exceeds the response size limit.", code="response_too_large")
            content_type = response.getheader("Content-Type", "").lower()
            if content_type and not any(kind in content_type for kind in ("json", "html", "text/plain")):
                raise DiscoveryError("Only HTML, JSON and plain text sources are supported.", code="unsupported_content")
            return Document(url, bytes(body).decode("utf-8", errors="replace"), content_type)
        except (OSError, http.client.HTTPException):
            raise DiscoveryError("Source connection failed or timed out.", code="network_failed") from None
        finally:
            conn.close()
    raise DiscoveryError("Source redirected too many times.", code="redirect_limit")
