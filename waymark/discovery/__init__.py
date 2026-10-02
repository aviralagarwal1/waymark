"""Public, synchronous discovery contract; no import-time keys or network calls."""
from .connectors import fetch_source, validate_source_url
from .errors import DiscoveryError
from .matching import match_posting
from .research import research_target

__all__ = ["DiscoveryError", "fetch_source", "validate_source_url", "match_posting", "research_target"]
