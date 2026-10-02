from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Connector = Literal["auto", "greenhouse", "lever", "ashby", "jsonld", "demo"]
Precision = Literal["day", "month", "range", "unknown"]
Meaning = Literal["original_posted", "last_published", "updated", "archive_observed", "announced_expected", "user_supplied", "unknown"]


class TargetInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    company: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=300)
    location: str = Field(default="", max_length=500)
    employment_type: str = Field(default="FullTime", max_length=80)
    level: str = Field(default="entry", max_length=100)
    start_period: str = Field(default="", max_length=200)
    watch_from: date | None = None
    watch_until: date | None = None
    notes: str = Field(default="", max_length=10000)
    reference_url: str = Field(default="", max_length=4000)
    source_url: str = Field(default="", max_length=4000)
    connector: Connector = "auto"
    check_interval_hours: float = Field(default=6, ge=0.25, le=8760)
    monitoring_status: Literal["draft", "monitoring", "paused"] = "draft"
    historical_date: str | None = Field(default=None, max_length=100)
    historical_date_precision: Precision = "unknown"
    historical_date_meaning: Meaning = "unknown"
    id: str | None = None
    version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def ordered_dates(self):
        if self.watch_from and self.watch_until and self.watch_until < self.watch_from:
            raise ValueError("Watch end must follow watch start")
        return self


class TargetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(ge=1)
    company: str | None = None
    role: str | None = None
    location: str | None = None
    employment_type: str | None = None
    level: str | None = None
    start_period: str | None = None
    watch_from: date | None = None
    watch_until: date | None = None
    notes: str | None = None
    reference_url: str | None = None
    source_url: str | None = None
    connector: Connector | None = None
    check_interval_hours: float | None = None
    monitoring_status: Literal["draft", "monitoring", "paused"] | None = None
    historical_date: str | None = None
    historical_date_precision: Precision | None = None
    historical_date_meaning: Meaning | None = None


class Preferences(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: str = "America/Chicago"
    check_interval_hours: float = Field(default=6, ge=0.25, le=8760)
    email_mode: Literal["scan", "immediate", "daily", "weekly", "off"] = "scan"
    digest_hour: int = Field(default=9, ge=0, le=23)
    digest_weekday: int = Field(default=0, ge=0, le=6)
    reminder_days: list[int] = Field(default_factory=lambda: [1, 3], max_length=12)
    quiet_start: int | None = Field(default=None, ge=0, le=23)
    quiet_end: int | None = Field(default=None, ge=0, le=23)
    daily_email_cap: int = Field(default=10, ge=1, le=100)
    default_role: str = Field(default="", max_length=300)
    default_location: str = Field(default="", max_length=500)
    default_start_period: str = Field(default="", max_length=200)
    default_employment_type: str = Field(default="FullTime", max_length=80)
    research_monthly_budget_usd: float = Field(default=10, ge=0, le=1000)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError("Unknown timezone") from exc
        return value

    @field_validator("reminder_days")
    @classmethod
    def valid_reminders(cls, value):
        if any(day < 1 or day > 365 for day in value):
            raise ValueError("Reminder offsets must be 1–365 days")
        return sorted(set(value))

    @model_validator(mode="after")
    def quiet_pair(self):
        if (self.quiet_start is None) != (self.quiet_end is None):
            raise ValueError("Set both quiet-hour endpoints, or neither")
        return self


class MatchPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["new", "applied", "dismissed", "snoozed"]
    snoozed_until: datetime | None = None

    @model_validator(mode="after")
    def snooze_date(self):
        if self.status == "snoozed" and (not self.snoozed_until or not self.snoozed_until.tzinfo):
            raise ValueError("Snoozing requires a timestamp with timezone")
        return self


class Approval(BaseModel):
    include_existing: bool = False


class ImportCommit(BaseModel):
    rows: list[TargetInput] = Field(max_length=5000)
    merge: bool = False


class Credentials(BaseModel):
    model_config = ConfigDict(extra="forbid")
    # Lengths are bounded here; format and password rules live in auth.py.
    email: str = Field(max_length=320)
    password: str = Field(max_length=1024)


class EmailRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(max_length=320)


class TokenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(max_length=200)


class PasswordConfirm(BaseModel):
    model_config = ConfigDict(extra="forbid")
    password: str = Field(max_length=1024)


class PasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(max_length=200)
    password: str = Field(max_length=1024)
