"""Failures safe to expose to the local UI (never include provider keys)."""


class DiscoveryError(ValueError):
    def __init__(self, message: str, *, code: str = "discovery_failed", usage: dict | None = None):
        super().__init__(message)
        self.code = code
        self.usage = usage or {}
