from datetime import datetime, timezone
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from waymark.models import Preference, Target, Task, now, uid
from waymark.schemas import Preferences, TargetInput


def utc(value):
    if value is None:
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def serialize(row):
    result = {}
    for col in row.__table__.columns:
        value = getattr(row, col.name)
        result[col.name] = utc(value).isoformat() if isinstance(value, datetime) else value
    return result


def target_dict(row):
    return {key: value for key, value in serialize(row).items() if key not in {"baseline_complete", "include_existing", "user_id"}}


def preferences(session, user_id):
    record = session.get(Preference, user_id)
    if not record:
        record = Preference(user_id=user_id, data=Preferences().model_dump())
        session.add(record)
        session.flush()
    return Preferences.model_validate(record.data)


def get_target(session, target_id, user_id):
    # Another user's target is reported exactly like a missing one, so IDs
    # cannot be probed across accounts.
    target = session.get(Target, target_id)
    if not target or target.user_id != user_id:
        raise HTTPException(404, "Target not found")
    return target


def validate_target_urls(data, demo):
    from waymark.discovery import validate_source_url
    for field in ("source_url", "reference_url"):
        url = data.get(field, "")
        if not url:
            continue
        if demo and url.startswith("https://demo.example/"):
            continue
        try:
            # Reference pages need public-destination validation, not an ATS mapping.
            validate_source_url(url, data.get("connector", "auto") if field == "source_url" else "auto")
        except Exception as exc:
            raise HTTPException(422, f"Invalid {field}: {str(exc)[:300]}") from exc
    if data.get("connector") == "demo" and not demo:
        raise HTTPException(422, "The demo connector is only available in demo mode")


def create_target(session, data, user_id, demo=False, preserve_history=False):
    values = data.model_dump(mode="json", exclude={"id", "version"})
    validate_target_urls(values, demo)
    if values["monitoring_status"] == "monitoring":
        raise HTTPException(422, "Create a draft, then validate and approve its source")
    if values.get("historical_date") and not preserve_history:
        values["historical_date_meaning"] = "user_supplied"
    target = Target(**values, user_id=user_id)
    session.add(target)
    session.flush()
    return target


def edit_target(session, target, changes, expected_version, demo=False):
    if target.version != expected_version:
        raise HTTPException(409, "This row changed. Refresh it before saving your edits.")
    original = target_dict(target)
    input_fields = set(TargetInput.model_fields) - {"id", "version"}
    merged = {key: original[key] for key in input_fields}
    merged.update(changes)
    validated = TargetInput.model_validate(merged).model_dump(mode="json", exclude={"id", "version"})
    validate_target_urls(validated, demo)
    source_changed = any(validated[key] != original[key] for key in ("source_url", "connector"))
    if validated["monitoring_status"] == "monitoring" and (target.source_health != "healthy" or source_changed):
        raise HTTPException(422, "Validate and approve the source before monitoring")
    if source_changed:
        validated.update(source_health="unknown", baseline_complete=False, next_check_at=None)
    if any(key in changes and changes[key] != original[key] for key in ("historical_date", "historical_date_precision", "historical_date_meaning")):
        validated["historical_date_meaning"] = "user_supplied" if validated.get("historical_date") else "unknown"
    validated["version"] = expected_version + 1
    if validated["monitoring_status"] == "monitoring" and original["monitoring_status"] != "monitoring":
        validated["next_check_at"] = now()
    result = session.execute(update(Target).where(Target.id == target.id, Target.version == expected_version).values(**validated))
    if result.rowcount != 1:
        raise HTTPException(409, "This row changed. Refresh it before saving your edits.")
    session.flush()
    session.expire(target)
    return target


def enqueue(session, kind, target=None, payload=None, at=None):
    target_id = target.id if target else None
    query = select(Task).where(Task.kind == kind, Task.target_id == target_id, Task.status.in_(["queued", "running"]))
    if target and kind == "research":
        query = query.where(Task.target_version == target.version)
    previous = session.scalar(query)
    if previous:
        return previous
    active_key = f"{kind}:{target_id}:{target.version if target and kind == 'research' else ''}"
    task = Task(id=uid(), dedupe_key=uid(), active_key=active_key, kind=kind, target_id=target_id,
                target_version=target.version if target else None,
                payload=payload or {}, run_after=at or now())
    try:
        with session.begin_nested():
            session.add(task)
            session.flush()
    except IntegrityError:
        return session.scalar(select(Task).where(Task.active_key == active_key))
    if target and kind == "research":
        target.research_status = "queued"
    session.flush()
    return task
