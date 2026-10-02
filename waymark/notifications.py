"""Per-user notification clock and a durable outbox with preview, SMTP, and Resend transports."""
from datetime import timedelta
from email.message import EmailMessage
from email.utils import formataddr
import hashlib
import logging
import smtplib
import ssl
from zoneinfo import ZoneInfo
import httpx
from sqlalchemy import select
from waymark.auth import ACCOUNT_EMAIL_KINDS
from waymark.brand import NAME
from waymark.models import Delivery, DeliveryEvent, Match, RuntimeState, Target, User, uid
from waymark.services import preferences, utc

logger = logging.getLogger(__name__)
RESEND_URL = "https://api.resend.com/emails"
RESEND_MAX_ATTEMPTS = 3
CLEARED_BODY = "This email held a one-time link. Its text was cleared after sending."


class ResendRejected(Exception):
    """Resend refused the message outright (a 4xx other than 429); retrying will not help."""
    def __init__(self, status):
        super().__init__(status)
        self.status = status


def eligible(match, target, timestamp):
    if not target or target.monitoring_status != "monitoring" or match.closed:
        return False
    if match.status in {"applied", "dismissed"}:
        return False
    if match.status == "snoozed" and (not match.snoozed_until or utc(match.snoozed_until) > timestamp):
        return False
    return match.notify_eligible


def quiet(preferences, timestamp):
    if preferences.quiet_start is None or preferences.quiet_start == preferences.quiet_end:
        return False
    hour = timestamp.astimezone(ZoneInfo(preferences.timezone)).hour
    start, end = preferences.quiet_start, preferences.quiet_end
    return start <= hour < end if start < end else hour >= start or hour < end


def digest_slot(preferences, timestamp):
    local = timestamp.astimezone(ZoneInfo(preferences.timezone))
    slot = local.replace(hour=preferences.digest_hour, minute=0, second=0, microsecond=0)
    if slot > local:
        slot -= timedelta(days=1)
    if preferences.email_mode == "weekly":
        slot -= timedelta(days=(slot.weekday() - preferences.digest_weekday) % 7)
    # Calendar identity avoids sending twice during the repeated DST hour.
    return f"{slot.date().isoformat()}T{preferences.digest_hour:02}:00[{preferences.timezone}]"


def email_subject(matches, kind):
    # The sender's name is already the product's, so the subject names the role.
    if len(matches) == 1:
        role = f"{matches[0].title} at {matches[0].company}"
        return f"Reminder: {role}" if kind == "reminder" else f"Now open: {role}"
    return f"Reminder: {len(matches)} openings to apply to" if kind == "reminder" else f"{len(matches)} new openings on your watchlist"


def email_body(matches, kind, base_url):
    if kind == "reminder":
        intro = "Still open, and not marked applied yet."
    else:
        intro = "A role you're watching just opened." if len(matches) == 1 else f"{len(matches)} roles you're watching just opened."
    lines = [intro, ""]
    for match in matches:
        lines.extend([f"{match.title}, {match.company}", match.location or "Location not stated", f"Apply: {match.url}"])
        # A clean match needs no explanation; the matcher's note matters only when it is unsure.
        if match.reason.startswith("Needs review"):
            lines.append("Check before applying: " + match.reason.removeprefix("Needs review").lstrip(": "))
        lines.append("")
    if kind != "reminder":
        # Discovery time is not the opening date, so say so without claiming more.
        lines.extend(["Found on the careers page; it may have been posted a little earlier.", ""])
    lines.append(f"Mark it applied or dismissed to stop reminders: {base_url}/app")
    return "\n".join(lines)


def sender(settings):
    # Inboxes show the product's name rather than a bare address, unless
    # EMAIL_FROM already carries a display name.
    return settings.email_from if "<" in settings.email_from else formataddr((NAME, settings.email_from))


def daily_count(session, user_id, prefs, timestamp):
    # The cap counts alerts only; account emails never use up a user's alert allowance.
    local_day = timestamp.astimezone(ZoneInfo(prefs.timezone)).date()
    deliveries = session.scalars(select(Delivery).where(Delivery.user_id == user_id, Delivery.kind.not_in(ACCOUNT_EMAIL_KINDS),
                                                        Delivery.status.in_(["sent", "preview", "sending", "uncertain"]))).all()
    return sum(utc(d.sent_at or d.created_at).astimezone(ZoneInfo(prefs.timezone)).date() == local_day for d in deliveries)


def plan_deliveries(session, settings, timestamp):
    created = []
    # Only verified accounts get alerts; an unverified address may not be the user's.
    owners = session.scalars(select(User).where(User.email_verified_at.is_not(None), User.id.in_(
        select(Target.user_id).where(Target.monitoring_status == "monitoring")))).all()
    for user in owners:
        created.extend(plan_user_deliveries(session, settings, user, timestamp))
    return created


def plan_user_deliveries(session, settings, user, timestamp):
    prefs = preferences(session, user.id)
    if prefs.email_mode == "off" or quiet(prefs, timestamp):
        return []
    if daily_count(session, user.id, prefs, timestamp) >= prefs.daily_email_cap:
        return []
    targets = {target.id: target for target in session.scalars(select(Target).where(Target.user_id == user.id))}
    matches = session.scalars(select(Match).where(Match.target_id.in_(list(targets)))).all()
    existing_events = set(session.scalars(select(DeliveryEvent.event_key).where(DeliveryEvent.match_id.in_([m.id for m in matches]))))
    initial, reminders = [], []
    for match in matches:
        if not eligible(match, targets.get(match.target_id), timestamp):
            continue
        if match.initial_notified_at is None:
            event_key = f"initial:{match.id}"
            if event_key not in existing_events:
                initial.append((match, event_key, None))
        else:
            due = [day for day in prefs.reminder_days if utc(match.initial_notified_at) + timedelta(days=day) <= timestamp and f"reminder:{match.id}:{day}" not in existing_events]
            if due:
                # A single catch-up email covers all overdue offsets.
                reminders.extend((match, f"reminder:{match.id}:{day}", day) for day in due)
    if prefs.email_mode in {"daily", "weekly"}:
        slot = digest_slot(prefs, timestamp)
        state_key = f"digest_slot:{user.id}"
        state = session.get(RuntimeState, state_key)
        same_slot = bool(state and state.value.get("slot") == slot and state.value.get("mode") == prefs.email_mode)
        if same_slot:
            initial = []
        # Before the first configured slot today, don't deliver an immediate digest
        # just because no prior slot exists. Existing missed slots are recovered.
        first_slot_pending = not state and timestamp.astimezone(ZoneInfo(prefs.timezone)).hour < prefs.digest_hour
        if first_slot_pending:
            initial = []
        if not state and prefs.email_mode == "weekly" and timestamp.astimezone(ZoneInfo(prefs.timezone)).weekday() != prefs.digest_weekday:
            initial = []
            first_slot_pending = True
        if not same_slot and not first_slot_pending:
            # Empty digest slots are still consumed. A match discovered after an
            # uneventful digest belongs in the next scheduled digest.
            if state:
                state.value = {"slot": slot, "mode": prefs.email_mode}
            else:
                session.add(RuntimeState(key=state_key, value={"slot": slot, "mode": prefs.email_mode}))
    groups = []
    if prefs.email_mode == "immediate":
        groups.extend(("initial", [event]) for event in initial)
    elif initial:
        groups.append(("initial", initial))
    if reminders:
        groups.append(("reminder", reminders))
    created = []
    for kind, events in groups:
        identities = sorted(event[1] for event in events)
        key = hashlib.sha256("|".join(identities).encode()).hexdigest()
        if session.scalar(select(Delivery).where(Delivery.dedupe_key == key)):
            continue
        unique_matches = list({event[0].id: event[0] for event in events}.values())
        delivery = Delivery(id=uid(), user_id=user.id, dedupe_key=key, kind=kind, status="pending",
                            subject=email_subject(unique_matches, kind),
                            plain_body=email_body(unique_matches, kind, settings.base_url), recipient=user.email, created_at=timestamp)
        session.add(delivery)
        session.flush()
        for match, event_key, offset in events:
            session.add(DeliveryEvent(event_key=event_key, delivery_id=delivery.id, match_id=match.id, kind=kind, offset_days=offset))
        created.append(delivery.id)
    return created


def send_smtp(settings, recipient, subject, body, delivery_id):
    if not settings.smtp_host or not settings.email_from or not recipient:
        raise ValueError("SMTP_HOST, EMAIL_FROM, and a recipient must be configured")
    message = EmailMessage()
    message["From"] = sender(settings)
    message["To"] = recipient
    message["Subject"] = subject
    message["Message-ID"] = f"<{delivery_id}@waymark.local>"
    message.set_content(body)
    context = ssl.create_default_context()
    smtp_class = smtplib.SMTP_SSL if settings.smtp_ssl else smtplib.SMTP
    kwargs = {"host": settings.smtp_host, "port": settings.smtp_port, "timeout": 30}
    if settings.smtp_ssl:
        kwargs["context"] = context
    with smtp_class(**kwargs) as client:
        if settings.smtp_starttls and not settings.smtp_ssl:
            client.starttls(context=context)
        if settings.smtp_user:
            client.login(settings.smtp_user, settings.smtp_password)
        client.send_message(message)


def send_resend(settings, recipient, subject, body, delivery_id):
    # The delivery ID is the idempotency key, so a retry after an ambiguous
    # failure cannot produce a second email; Resend keeps keys for 24 hours.
    response = httpx.post(RESEND_URL, timeout=30, headers={"Authorization": f"Bearer {settings.resend_api_key}", "Idempotency-Key": delivery_id},
                          json={"from": sender(settings), "to": [recipient], "subject": subject, "text": body})
    if response.status_code == 429 or response.status_code >= 500:
        raise httpx.HTTPStatusError("Temporary Resend failure", request=response.request, response=response)
    if response.status_code >= 400:
        raise ResendRejected(response.status_code)


def transport_ready(settings):
    if settings.email_transport == "smtp":
        return bool(settings.smtp_host and settings.email_from)
    if settings.email_transport == "resend":
        return bool(settings.resend_api_key and settings.email_from)
    return True


def deliver_pending(db, settings, timestamp, sender=None):
    """Reserve locally before network I/O. Ambiguous SMTP outcomes never retry;
    Resend outcomes retry a few times under the same idempotency key."""
    sent = 0
    with db.session.begin() as session:
        for item in session.scalars(select(Delivery).where(Delivery.status == "sending", Delivery.lease_until < timestamp)):
            if settings.email_transport == "resend":
                item.status, item.lease_until = "pending", None
            else:
                item.status = "uncertain"
                item.error = "Worker stopped while sending; check your mailbox before manually retrying."
        ids = list(session.scalars(select(Delivery.id).where(Delivery.status == "pending").order_by(Delivery.created_at)))
    for delivery_id in ids:
        with db.session.begin() as session:
            delivery = session.get(Delivery, delivery_id)
            if not delivery or delivery.status != "pending":
                continue
            user = session.get(User, delivery.user_id)
            account_email = delivery.kind in ACCOUNT_EMAIL_KINDS
            permitted = []
            if not account_email:
                prefs = preferences(session, delivery.user_id)
                if prefs.email_mode == "off" and delivery.kind != "test":
                    continue
                if quiet(prefs, timestamp) or daily_count(session, delivery.user_id, prefs, timestamp) >= prefs.daily_email_cap:
                    continue
                events = session.scalars(select(DeliveryEvent).where(DeliveryEvent.delivery_id == delivery_id)).all()
                excluded_events = []
                for event in events:
                    match = session.get(Match, event.match_id)
                    if match and eligible(match, session.get(Target, match.target_id), timestamp):
                        if event.kind == "reminder" and event.offset_days not in prefs.reminder_days:
                            excluded_events.append(event)
                            continue
                        permitted.append(match)
                    else:
                        excluded_events.append(event)
                if delivery.kind != "test" and not permitted:
                    # Snoozes defer a pending message; terminal states cancel it.
                    deferred = any((match := session.get(Match, e.match_id)) is not None and match.status == "snoozed" and match.snoozed_until and utc(match.snoozed_until) > timestamp for e in events)
                    if not deferred:
                        delivery.status = "canceled"
                    continue
                if permitted:
                    permitted = list({match.id: match for match in permitted}.values())
                    delivery.subject = email_subject(permitted, delivery.kind)
                    delivery.plain_body = email_body(permitted, delivery.kind, settings.base_url)
                    # A snoozed match excluded from a grouped email must remain
                    # eligible for its own alert after the snooze expires.
                    for event in excluded_events:
                        session.delete(event)
            delivery.recipient = user.email
            if not transport_ready(settings):
                delivery.error = "Configure EMAIL_FROM and the email transport's credentials, or use preview transport."
                continue
            delivery.status = "sending"
            delivery.attempts += 1
            delivery.lease_until = timestamp + timedelta(minutes=3)
            args = (settings, delivery.recipient, delivery.subject, delivery.plain_body, delivery.id)
            attempts, permitted_ids = delivery.attempts, {match.id for match in permitted}
        error = ""
        try:
            if settings.email_transport == "smtp":
                (sender or send_smtp)(*args)
            elif settings.email_transport == "resend":
                (sender or send_resend)(*args)
            elif account_email:
                # Preview sends nothing; printing account emails lets a local
                # developer follow verification and reset links.
                logger.info("Preview email to %s: %s\n%s", args[1], args[2], args[3])
            result = "preview" if settings.email_transport == "preview" else "sent"
        except ResendRejected as exc:
            result, error = "failed", f"Resend refused the message (HTTP {exc.status}). Check EMAIL_FROM and the sending domain."
        except Exception:
            # Never expose credentials or provider response bodies in API-visible errors.
            if settings.email_transport == "resend" and attempts < RESEND_MAX_ATTEMPTS:
                result, error = "pending", "Temporary send failure; retrying with the same idempotency key."
            elif settings.email_transport == "resend":
                result, error = "failed", "Resend could not be reached after several attempts."
            else:
                # Even a disconnect may occur after remote acceptance.
                result, error = "uncertain", "SMTP delivery outcome is uncertain. Verify the recipient mailbox before retrying."
        with db.session.begin() as session:
            delivery = session.get(Delivery, delivery_id)
            if not delivery:
                continue
            delivery.status, delivery.error, delivery.lease_until = result, error, None
            if account_email and result != "pending":
                # The body held a one-time link; don't keep a working copy at rest.
                delivery.plain_body = CLEARED_BODY
            if result in {"sent", "preview"}:
                delivery.sent_at = timestamp
                for event in session.scalars(select(DeliveryEvent).where(DeliveryEvent.delivery_id == delivery_id, DeliveryEvent.kind == "initial")):
                    match = session.get(Match, event.match_id)
                    if match and match.id in permitted_ids and match.initial_notified_at is None:
                        match.initial_notified_at = timestamp
                sent += 1
    return sent
