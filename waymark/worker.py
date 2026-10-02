"""Single-host durable worker. Network I/O never holds a SQLite transaction."""
from datetime import timedelta
import hashlib
import logging
import signal
import sys
import time
from zoneinfo import ZoneInfo
from sqlalchemy import func, select, text, update
from waymark.database import init_db
from waymark.models import Evidence, Match, Posting, Preference, ResearchUsage, RuntimeState, Target, Task, now
from waymark.notifications import deliver_pending, plan_deliveries
from waymark.services import enqueue, preferences, target_dict, utc
from waymark.settings import Settings

logger = logging.getLogger(__name__)


def apply_source_result(session, target, result, timestamp, matcher=None):
    from waymark.discovery import match_posting
    matcher = matcher or match_posting
    target.next_check_at = timestamp + timedelta(hours=target.check_interval_hours)
    if result.get("status") != "ok" or not result.get("complete", False):
        target.source_health = "unsupported" if result.get("status") == "unsupported" else "failed"
        target.source_error = str(result.get("error") or "The source response was incomplete; no closures inferred.")[:1000]
        return
    target.source_health, target.source_error = "healthy", ""
    target.last_checked_at = timestamp
    previous = {match.posting_id: match for match in session.scalars(select(Match).where(Match.target_id == target.id))}
    observed = set()
    for data in result.get("postings", []):
        native = str(data.get("external_id") or data.get("url") or "")
        if not native:
            continue
        identity = hashlib.sha256(f"{target.connector}|{target.source_url}|{native}".encode()).hexdigest()
        posting = session.scalar(select(Posting).where(Posting.identity == identity))
        if not posting:
            posting = Posting(identity=identity, data=data)
            session.add(posting)
            session.flush()
        else:
            posting.data = data
        finding = matcher(target_dict(target), data)
        if finding.get("status") not in {"match", "review"}:
            continue
        observed.add(posting.id)
        match = previous.get(posting.id)
        if match:
            match.closed, match.missing_checks = False, 0
            match.title, match.url = data.get("title", match.title), data.get("url", match.url)
            match.reason = ("Needs review: " if finding["status"] == "review" else "") + finding.get("reason", "")
            match.notify_eligible = finding["status"] == "match" and (match.notify_eligible or target.include_existing)
            continue
        match = Match(target_id=target.id, posting_id=posting.id, company=target.company,
                      title=data.get("title", "Untitled opening"), url=data.get("url", ""),
                      location=data.get("location", ""), published_at=data.get("published_at"),
                      date_meaning=data.get("date_meaning", "unknown"), reason=finding.get("reason", ""),
                      notify_eligible=finding["status"] == "match" and (target.baseline_complete or target.include_existing),
                      first_seen_at=timestamp)
        if finding["status"] == "review":
            match.reason = "Needs review: " + match.reason
        session.add(match)
    for posting_id, match in previous.items():
        if posting_id not in observed:
            match.missing_checks += 1
            if match.missing_checks >= 2:
                match.closed = True
    target.baseline_complete = True


def schedule_due(session, timestamp):
    # Watch windows are calendar dates in each owner's own timezone.
    today_for = {}
    for target in session.scalars(select(Target).where(Target.monitoring_status == "monitoring")):
        if target.user_id not in today_for:
            today_for[target.user_id] = timestamp.astimezone(ZoneInfo(preferences(session, target.user_id).timezone)).date().isoformat()
        today = today_for[target.user_id]
        if (target.watch_from and target.watch_from > today) or (target.watch_until and target.watch_until < today):
            continue
        if target.next_check_at is None or utc(target.next_check_at) <= timestamp:
            enqueue(session, "check", target, at=timestamp)


def recover_leases(session, timestamp):
    for task in session.scalars(select(Task).where(Task.status == "running", Task.lease_until < timestamp)):
        task.lease_until = None
        task.updated_at = timestamp
        if task.kind == "research":
            task.status = "failed"
            task.active_key = None
            task.error = "Research was interrupted. Spend may have occurred; rerun explicitly after review."
            target = session.get(Target, task.target_id)
            if target:
                target.research_status = "failed"
        else:
            task.status = "queued"
            task.run_after = timestamp


def claim_task(db, timestamp):
    with db.session.begin() as session:
        task = session.scalar(select(Task).where(Task.status == "queued", Task.run_after <= timestamp).order_by(Task.created_at).limit(1))
        if not task:
            return None
        claimed = session.execute(update(Task).where(Task.id == task.id, Task.status == "queued").values(
            status="running", attempts=Task.attempts + 1, lease_until=timestamp + timedelta(minutes=15), updated_at=timestamp))
        return task.id if claimed.rowcount else None


def reserve_research(db, task_id, user_id, timestamp, settings):
    if settings.mode == "demo" or not settings.anthropic_api_key:
        return 0.0
    with db.session() as session:
        # Two workers must not both spend the last of a user's budget. SQLite
        # serializes the whole transaction; Postgres locks the user's
        # preferences row, which every reservation for that user reads.
        if db.dialect == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            session.execute(select(Preference.user_id).where(Preference.user_id == user_id).with_for_update())
        prior = session.scalar(select(ResearchUsage).where(ResearchUsage.task_id == task_id))
        if prior:
            session.rollback()
            raise RuntimeError("This research task already reserved spend; explicit rerun required")
        prefs = preferences(session, user_id)
        month = timestamp.strftime("%Y-%m")
        used = session.scalar(select(func.coalesce(func.sum(func.coalesce(ResearchUsage.estimated_cost_usd, ResearchUsage.reserved_usd)), 0)).where(ResearchUsage.month == month, ResearchUsage.user_id == user_id))
        reservation = min(0.50, round(prefs.research_monthly_budget_usd - used, 6))
        if reservation < 0.10:
            session.rollback()
            raise RuntimeError("The monthly research budget is exhausted; increase it or use a manual source")
        session.add(ResearchUsage(task_id=task_id, user_id=user_id, month=month, reserved_usd=reservation))
        session.commit()
        return reservation


def execute_task(db, settings, task_id, timestamp, source_cache=None, researcher=None, fetcher=None, matcher=None):
    from waymark.discovery import fetch_source, research_target
    researcher, fetcher = researcher or research_target, fetcher or fetch_source
    source_cache = source_cache if source_cache is not None else {}
    with db.session.begin() as session:
        task = session.get(Task, task_id)
        if not task:
            return
        target = session.get(Target, task.target_id)
        if not target:
            task.status, task.error, task.active_key = "canceled", "Target was deleted", None
            return
        snapshot, kind, version, owner = target_dict(target), task.kind, task.target_version, target.user_id
        if kind == "research":
            if target.version != version:
                task.status, task.error, task.active_key, task.lease_until = "stale", "Target was edited before research began; enqueue research for its current version.", None, None
                return
            target.research_status = "researching"
    try:
        if kind == "research":
            budget = reserve_research(db, task_id, owner, timestamp, settings)
            result = researcher(snapshot, api_key=settings.anthropic_api_key, model=settings.anthropic_model,
                                demo=settings.mode == "demo", budget_usd=budget or 0.50)
        elif kind == "check":
            if not snapshot["source_url"]:
                raise ValueError("Add and approve a source URL before checking")
            key = (snapshot["source_url"], snapshot["connector"])
            if key not in source_cache:
                source_cache[key] = fetcher(*key, demo=settings.mode == "demo")
            result = source_cache[key]
        else:
            raise ValueError("Unsupported task kind")
        with db.session.begin() as session:
            task, target = session.get(Task, task_id), session.get(Target, snapshot["id"])
            if not task or not target:
                return
            if kind == "research":
                usage = session.scalar(select(ResearchUsage).where(ResearchUsage.task_id == task_id))
                if usage:
                    usage.usage = result.get("usage", {})
                    usage.estimated_cost_usd = max(0, float(usage.usage.get("estimated_cost_usd", usage.reserved_usd)))
                task.result = result
                if target.version != version:
                    task.status, task.error = "stale", "Research finished after this row was edited; current values were preserved."
                    target.research_status = "needs_review"
                else:
                    for record in result.get("evidence", []):
                        allowed = {key: record[key] for key in ("url", "excerpt", "retrieved_at", "kind", "date_value", "date_precision", "date_meaning", "match_status", "explanation") if key in record}
                        allowed.setdefault("retrieved_at", timestamp.isoformat())
                        session.add(Evidence(target_id=target.id, **allowed))
                    target.research_status = result.get("status", "needs_review")
                    target.research_summary = result.get("summary", "")
                    target.proposed_source_url = result.get("proposed_source_url", "")
                    target.proposed_connector = result.get("proposed_connector", "auto")
                    # Research always proposes source changes, and never overwrites
                    # an existing historical correction made by the user.
                    if not target.historical_date:
                        target.historical_date = result.get("historical_date")
                        target.historical_date_precision = result.get("historical_date_precision", "unknown")
                        target.historical_date_meaning = result.get("historical_date_meaning", "unknown")
                    target.version += 1
                    task.status = "done"
            else:
                if target.version != snapshot["version"]:
                    task.status, task.error = "stale", "The target changed while this check was running"
                else:
                    apply_source_result(session, target, result, timestamp, matcher=matcher)
                    task.result = {"status": result.get("status"), "count": len(result.get("postings", []))}
                    task.status = "done" if target.source_health == "healthy" else "failed"
                    task.error = target.source_error
            task.lease_until, task.updated_at, task.active_key = None, timestamp, None
    except Exception as exc:
        # Whitelisted local errors are actionable; provider exception text can
        # contain credentials or full HTTP responses and must not reach the UI.
        safe_error = str(exc)[:500] if type(exc) in {ValueError, RuntimeError} else f"{kind.title()} failed ({type(exc).__name__}); review configuration and source availability."
        with db.session.begin() as session:
            task = session.get(Task, task_id)
            if task:
                task.status, task.error, task.lease_until, task.updated_at = "failed", safe_error, None, timestamp
                task.active_key = None
                target = session.get(Target, task.target_id)
                if target:
                    if kind == "research":
                        target.research_status, target.research_summary = "failed", safe_error
                    else:
                        target.source_health, target.source_error = "failed", safe_error
                        target.next_check_at = timestamp + timedelta(hours=target.check_interval_hours)


def run_once(db=None, settings=None, timestamp=None, researcher=None, fetcher=None, matcher=None, sender=None, max_tasks=50):
    settings = settings or Settings.from_env()
    db = db or init_db(settings)
    timestamp = utc(timestamp or now())
    with db.session.begin() as session:
        heartbeat = session.get(RuntimeState, "worker_heartbeat")
        if heartbeat:
            heartbeat.value = {"at": timestamp.isoformat()}
        else:
            session.add(RuntimeState(key="worker_heartbeat", value={"at": timestamp.isoformat()}))
        recover_leases(session, timestamp)
        schedule_due(session, timestamp)
    count, cache = 0, {}
    for _ in range(max_tasks):
        task_id = claim_task(db, timestamp)
        if not task_id:
            break
        execute_task(db, settings, task_id, timestamp, cache, researcher, fetcher, matcher)
        count += 1
    with db.session.begin() as session:
        planned = plan_deliveries(session, settings, timestamp)
    sent = deliver_pending(db, settings, timestamp, sender=sender)
    return {"tasks": count, "deliveries_planned": len(planned), "deliveries_sent": sent}


def main(argv=None):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    settings = Settings.from_env()
    db = init_db(settings)
    from waymark.demo import bootstrap
    bootstrap(db, settings)
    if "--once" in (sys.argv[1:] if argv is None else argv):
        # One pass and exit, for a scheduler that starts the worker on a
        # cadence (a Cloud Run job) instead of keeping it running.
        logger.info("Worker pass in %s mode", settings.mode)
        run_once(db, settings)
        return
    stopping = False
    def stop(*_):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    logger.info("Worker started in %s mode", settings.mode)
    while not stopping:
        try:
            run_once(db, settings)
        except Exception as exc:
            logger.error("Worker cycle failed (%s)", type(exc).__name__)
        for _ in range(20):
            if stopping:
                break
            time.sleep(0.5)


if __name__ == "__main__":
    main()
