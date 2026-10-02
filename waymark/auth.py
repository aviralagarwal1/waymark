"""Accounts: password hashing, sessions, one-time email links, and rate limits.

Secrets never touch the database in usable form: session cookies and link
tokens are stored as SHA-256 digests, and passwords as Argon2id hashes. Account
emails go through the delivery outbox like every other email, so the worker is
still the only process that sends.
"""
from datetime import timedelta
import hashlib
import re
import secrets
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException
from sqlalchemy import delete, func, select
from waymark.brand import NAME
from waymark.models import AuthAttempt, AuthSession, AuthToken, Delivery, Preference, RuntimeState, User, uid
from waymark.schemas import Preferences

SESSION_COOKIE = "waymark_session"
SESSION_DAYS = 30
TOKEN_LIFETIMES = {"verify": timedelta(hours=24), "reset": timedelta(hours=1)}
# Account emails are transactional: they ignore quiet hours, digests, and the
# daily alert cap, and their bodies are blanked once sent (see notifications).
ACCOUNT_EMAIL_KINDS = {"verify", "reset", "account_exists"}
PASSWORD_MIN, PASSWORD_MAX = 10, 256
# (window, allowed) per kind of attempt; keyed separately by email and by IP.
LIMITS = {"login_failure": (timedelta(minutes=15), 10), "email_request": (timedelta(hours=1), 5)}
IP_MULTIPLIER = 5

_hasher = PasswordHasher()
_EMAIL = re.compile(r"^[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+$")
# A hash checked when no account matches, so a missing email costs the same
# time as a wrong password and response timing does not reveal which it was.
_DUMMY_HASH = _hasher.hash(secrets.token_hex(16))


def digest(secret):
    return hashlib.sha256(secret.encode()).hexdigest()


def normalize_email(value):
    email = (value or "").strip().lower()
    if len(email) > 320 or not _EMAIL.match(email):
        raise HTTPException(422, "Enter a valid email address")
    return email


def check_password_rules(password):
    if not PASSWORD_MIN <= len(password or "") <= PASSWORD_MAX:
        raise HTTPException(422, f"Use a password of {PASSWORD_MIN} to {PASSWORD_MAX} characters")


def hash_password(password):
    return _hasher.hash(password)


def password_matches(user, password):
    try:
        return _hasher.verify(user.password_hash if user else _DUMMY_HASH, password) and user is not None
    except (VerificationError, InvalidHashError):
        return False


def rate_limit(session, kind, email, ip, timestamp):
    """Refuse when this email or address has used up its window; else record."""
    window, allowed = LIMITS[kind]
    keys = [(f"{kind}:email:{email}", allowed), (f"{kind}:ip:{ip}", allowed * IP_MULTIPLIER)]
    for key, limit in keys:
        recent = session.scalar(select(func.count()).select_from(AuthAttempt).where(AuthAttempt.key == key, AuthAttempt.created_at > timestamp - window))
        if recent >= limit:
            raise HTTPException(429, "Too many attempts. Wait a few minutes and try again.")
    for key, _ in keys:
        session.add(AuthAttempt(key=key, created_at=timestamp))


def clear_attempts(session, kind, email):
    session.execute(delete(AuthAttempt).where(AuthAttempt.key == f"{kind}:email:{email}"))


def create_user(session, email, password, timestamp, verified=False):
    user = User(id=uid(), email=email, password_hash=hash_password(password), created_at=timestamp,
                email_verified_at=timestamp if verified else None)
    session.add(user)
    # Flush first: without ORM relationships, one flush may insert the
    # preferences row before the user it references.
    session.flush()
    session.add(Preference(user_id=user.id, data=Preferences().model_dump()))
    session.flush()
    return user


def start_session(session, user, timestamp):
    """Create a session and return the cookie value, which is never stored."""
    token = secrets.token_urlsafe(32)
    session.add(AuthSession(id=digest(token), user_id=user.id, created_at=timestamp, expires_at=timestamp + timedelta(days=SESSION_DAYS)))
    return token


def user_for_session(session, token, timestamp):
    if not token:
        return None
    record = session.get(AuthSession, digest(token))
    if not record:
        return None
    from waymark.services import utc
    if utc(record.expires_at) <= timestamp:
        session.delete(record)
        return None
    return session.get(User, record.user_id)


def end_session(session, token):
    if token:
        session.execute(delete(AuthSession).where(AuthSession.id == digest(token)))


def end_all_sessions(session, user):
    session.execute(delete(AuthSession).where(AuthSession.user_id == user.id))


def delete_account(session, user):
    """Delete the account and everything it owns.

    Foreign keys cascade from users to sessions, links, targets (with their
    evidence, matches, and tasks), preferences, deliveries, and research usage.
    Rate-limit rows and the digest slot are keyed by text, so they go here.
    Postings stay: they are shared board data, not anything the user wrote.
    """
    session.execute(delete(AuthAttempt).where(AuthAttempt.key.in_([f"{kind}:email:{user.email}" for kind in LIMITS])))
    session.execute(delete(RuntimeState).where(RuntimeState.key == f"digest_slot:{user.id}"))
    session.execute(delete(User).where(User.id == user.id))


def issue_token(session, user, purpose, timestamp):
    """Create a one-time link token; earlier unused ones of the same purpose stop working."""
    session.execute(delete(AuthToken).where(AuthToken.user_id == user.id, AuthToken.purpose == purpose, AuthToken.used_at.is_(None)))
    token = secrets.token_urlsafe(32)
    session.add(AuthToken(id=digest(token), user_id=user.id, purpose=purpose, expires_at=timestamp + TOKEN_LIFETIMES[purpose]))
    return token


def redeem_token(session, token, purpose, timestamp):
    from waymark.services import utc
    record = session.get(AuthToken, digest(token or ""))
    if not record or record.purpose != purpose or record.used_at is not None or utc(record.expires_at) <= timestamp:
        raise HTTPException(400, "This link has expired or was already used. Request a new one.")
    record.used_at = timestamp
    return session.get(User, record.user_id)


def queue_account_email(session, user, kind, base_url, timestamp, token=None):
    subjects = {"verify": "Confirm your email", "reset": "Reset your password",
                "account_exists": "You already have an account"}
    bodies = {
        "verify": f"Confirm your email to finish creating your {NAME} account:\n\n{base_url}/verify?token={token}\n\nThis link works once and expires in 24 hours. If you did not create an account, ignore this email.",
        "reset": f"Reset your {NAME} password:\n\n{base_url}/reset?token={token}\n\nThis link works once and expires in 1 hour. Resetting signs you out everywhere. If you did not ask for this, ignore this email; your password is unchanged.",
        "account_exists": f"Someone tried to create a {NAME} account with this email, but you already have one.\n\nSign in: {base_url}/signin\nForgot your password? {base_url}/forgot\n\nIf this was not you, no action is needed.",
    }
    session.add(Delivery(id=uid(), user_id=user.id, dedupe_key=uid(), kind=kind, subject=subjects[kind],
                         plain_body=bodies[kind], recipient=user.email, created_at=timestamp))
