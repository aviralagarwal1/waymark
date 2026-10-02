"""Accounts, persistent intent, evidence, observations, jobs, and delivery records."""
from datetime import datetime, timezone
import uuid
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def now():
    return datetime.now(timezone.utc)


def uid():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    # Stored lowercased and trimmed so one address cannot hold two accounts.
    email: Mapped[str] = mapped_column(String, unique=True)
    password_hash: Mapped[str] = mapped_column(String)
    email_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    # The SHA-256 of the cookie value; the cookie itself is never stored.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuthToken(Base):
    __tablename__ = "auth_tokens"
    # The SHA-256 of a one-time link token for email verification or reset.
    id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    purpose: Mapped[str] = mapped_column(String)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuthAttempt(Base):
    __tablename__ = "auth_attempts"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    key: Mapped[str] = mapped_column(String, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, index=True)


class Target(Base):
    __tablename__ = "targets"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    company: Mapped[str] = mapped_column(String)
    role: Mapped[str] = mapped_column(String)
    location: Mapped[str] = mapped_column(String, default="")
    employment_type: Mapped[str] = mapped_column(String, default="FullTime")
    level: Mapped[str] = mapped_column(String, default="entry")
    start_period: Mapped[str] = mapped_column(String, default="")
    watch_from: Mapped[str | None] = mapped_column(String, nullable=True)
    watch_until: Mapped[str | None] = mapped_column(String, nullable=True)
    notes: Mapped[str] = mapped_column(Text, default="")
    reference_url: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str] = mapped_column(Text, default="")
    connector: Mapped[str] = mapped_column(String, default="auto")
    check_interval_hours: Mapped[float] = mapped_column(Float, default=6)
    monitoring_status: Mapped[str] = mapped_column(String, default="draft")
    research_status: Mapped[str] = mapped_column(String, default="idle")
    source_health: Mapped[str] = mapped_column(String, default="unknown")
    source_error: Mapped[str] = mapped_column(Text, default="")
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    historical_date: Mapped[str | None] = mapped_column(String, nullable=True)
    historical_date_precision: Mapped[str] = mapped_column(String, default="unknown")
    historical_date_meaning: Mapped[str] = mapped_column(String, default="unknown")
    research_summary: Mapped[str] = mapped_column(Text, default="")
    proposed_source_url: Mapped[str] = mapped_column(Text, default="")
    proposed_connector: Mapped[str] = mapped_column(String, default="auto")
    baseline_complete: Mapped[bool] = mapped_column(Boolean, default=False)
    include_existing: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Evidence(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str] = mapped_column(Text, default="")
    retrieved_at: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String, default="historical")
    date_value: Mapped[str | None] = mapped_column(String, nullable=True)
    date_precision: Mapped[str] = mapped_column(String, default="unknown")
    date_meaning: Mapped[str] = mapped_column(String, default="unknown")
    match_status: Mapped[str] = mapped_column(String, default="unresolved")
    explanation: Mapped[str] = mapped_column(Text, default="")


class Posting(Base):
    __tablename__ = "postings"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    identity: Mapped[str] = mapped_column(String, unique=True)
    data: Mapped[dict] = mapped_column(JSON)


class Match(Base):
    __tablename__ = "matches"
    __table_args__ = (UniqueConstraint("target_id", "posting_id"),)
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    target_id: Mapped[str] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), index=True)
    posting_id: Mapped[str] = mapped_column(ForeignKey("postings.id"))
    company: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    url: Mapped[str] = mapped_column(Text)
    location: Mapped[str] = mapped_column(String, default="")
    status: Mapped[str] = mapped_column(String, default="new")
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    published_at: Mapped[str | None] = mapped_column(String, nullable=True)
    date_meaning: Mapped[str] = mapped_column(String, default="unknown")
    reason: Mapped[str] = mapped_column(Text, default="")
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed: Mapped[bool] = mapped_column(Boolean, default=False)
    missing_checks: Mapped[int] = mapped_column(Integer, default=0)
    notify_eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    initial_notified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Preference(Base):
    __tablename__ = "preferences"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)


class Task(Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    dedupe_key: Mapped[str] = mapped_column(String, unique=True)
    active_key: Mapped[str | None] = mapped_column(String, unique=True, nullable=True)
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="queued", index=True)
    target_id: Mapped[str | None] = mapped_column(ForeignKey("targets.id", ondelete="CASCADE"), nullable=True)
    target_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)


class Delivery(Base):
    __tablename__ = "deliveries"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    dedupe_key: Mapped[str] = mapped_column(String, unique=True)
    kind: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    subject: Mapped[str] = mapped_column(String)
    plain_body: Mapped[str] = mapped_column(Text)
    recipient: Mapped[str] = mapped_column(String, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class DeliveryEvent(Base):
    __tablename__ = "delivery_events"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    event_key: Mapped[str] = mapped_column(String, unique=True)
    delivery_id: Mapped[str] = mapped_column(ForeignKey("deliveries.id", ondelete="CASCADE"))
    match_id: Mapped[str] = mapped_column(ForeignKey("matches.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(String)
    offset_days: Mapped[int | None] = mapped_column(Integer, nullable=True)


class RuntimeState(Base):
    __tablename__ = "runtime_state"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[dict] = mapped_column(JSON)


class ResearchUsage(Base):
    __tablename__ = "research_usage"
    id: Mapped[str] = mapped_column(String, primary_key=True, default=uid)
    task_id: Mapped[str] = mapped_column(String, unique=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    month: Mapped[str] = mapped_column(String, index=True)
    reserved_usd: Mapped[float] = mapped_column(Float)
    estimated_cost_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
