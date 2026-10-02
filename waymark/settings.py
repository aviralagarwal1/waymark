"""Explicit environment configuration; never reads a .env file."""
from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    data_dir: str = "data"
    base_url: str = "http://localhost:8000"
    database_url: str = ""
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-sonnet-4-6"
    email_transport: str = "preview"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_starttls: bool = True
    smtp_ssl: bool = False
    email_from: str = ""
    resend_api_key: str = ""
    static_dir: str = "web/dist"
    # Proxies between the internet and the API (Cloud Run: 1). Rate limits read
    # the client address from X-Forwarded-For only when this is set.
    trusted_proxy_hops: int = 0
    # How old the worker's heartbeat may be before the app reports it stopped.
    # A worker started on a schedule needs more than one interval of slack.
    worker_stale_minutes: int = 5

    @property
    def secure_cookies(self):
        return self.base_url.startswith("https://")

    @property
    def db_url(self):
        if not self.database_url:
            return f"sqlite:///{Path(self.data_dir).resolve().as_posix()}/waymark.db"
        # Hosts such as Neon hand out postgres:// or postgresql:// URLs; route
        # both to the psycopg 3 driver the package installs.
        for prefix in ("postgres://", "postgresql://"):
            if self.database_url.startswith(prefix):
                return "postgresql+psycopg://" + self.database_url.removeprefix(prefix)
        return self.database_url

    @classmethod
    def from_env(cls):
        def flag(name, default):
            return os.getenv(name, str(default)).lower() in {"true", "1", "yes"}
        result = cls(
            mode=os.getenv("APP_MODE", "demo"), data_dir=os.getenv("DATA_DIR", "data"),
            base_url=os.getenv("APP_BASE_URL", "http://localhost:8000").rstrip("/"),
            database_url=os.getenv("DATABASE_URL", ""),
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            anthropic_model=os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"),
            email_transport=os.getenv("EMAIL_TRANSPORT", "preview"),
            smtp_host=os.getenv("SMTP_HOST", ""), smtp_port=int(os.getenv("SMTP_PORT", "587")),
            smtp_user=os.getenv("SMTP_USER", ""), smtp_password=os.getenv("SMTP_PASSWORD", ""),
            smtp_starttls=flag("SMTP_STARTTLS", True), smtp_ssl=flag("SMTP_SSL", False),
            email_from=os.getenv("EMAIL_FROM", ""), resend_api_key=os.getenv("RESEND_API_KEY", ""),
            static_dir=os.getenv("STATIC_DIR", "web/dist"),
            trusted_proxy_hops=int(os.getenv("TRUSTED_PROXY_HOPS", "0")),
            worker_stale_minutes=int(os.getenv("WORKER_STALE_MINUTES", "5")),
        )
        if result.mode not in {"demo", "live"}:
            raise ValueError("APP_MODE must be demo or live")
        if result.email_transport not in {"preview", "smtp", "resend"}:
            raise ValueError("EMAIL_TRANSPORT must be preview, smtp, or resend")
        if not 1 <= result.worker_stale_minutes <= 1440:
            raise ValueError("WORKER_STALE_MINUTES must be from 1 to 1440")
        if not 0 <= result.trusted_proxy_hops <= 5:
            raise ValueError("TRUSTED_PROXY_HOPS must be from 0 to 5")
        if result.mode == "demo" and result.email_transport != "preview":
            raise ValueError("Demo mode requires EMAIL_TRANSPORT=preview")
        return result
