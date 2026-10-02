"""Synthetic first-run data. No real employer, inbox, or API credentials needed."""
from sqlalchemy import delete, select, text
from waymark.database import SCHEMA_LOCK
from waymark.discovery.connectors import demo_start_year
from waymark.models import Delivery, Evidence, Preference, ResearchUsage, RuntimeState, Target, now, uid
from waymark.schemas import Preferences


def bind_dataset_mode(session, settings):
    state = session.get(RuntimeState, "dataset_mode")
    if state and state.value.get("mode") != settings.mode:
        raise RuntimeError("This data directory belongs to a different APP_MODE. Choose a separate DATA_DIR.")
    if not state:
        session.add(RuntimeState(key="dataset_mode", value={"mode": settings.mode}))


def seed_demo(session, user_id, today=None):
    """Give one demo account the synthetic example targets."""
    timestamp = now()
    start = demo_start_year(today)
    last_opening = f"{start - 2}-09"
    samples = [
        ("Northstar Labs", "Associate Product Manager", "United States", "FullTime", "northstar", "ready", last_opening, "month", "announced_expected"),
        ("Harbor Robotics", "Software Engineer", "London", "FullTime", "harbor", "needs_review", None, "unknown", "unknown"),
        ("Cedar Research", "Research Intern", "London", "Intern", "cedar", "idle", None, "unknown", "unknown"),
    ]
    for index, (company, role, location, employment, board, status, historic, precision, meaning) in enumerate(samples):
        target = Target(id=uid(), user_id=user_id, company=company, role=role, location=location, employment_type=employment,
                        level="" if employment == "Intern" else "entry", start_period=f"September {start}" if board == "harbor" else f"Summer {start}", notes="Synthetic demo example. Edit any field or add your own target.",
                        reference_url=f"https://demo.example/{board}/previous-cycle",
                        source_url=f"https://demo.example/{board}", connector="demo", check_interval_hours=6,
                        research_status=status, historical_date=historic, historical_date_precision=precision,
                        historical_date_meaning=meaning, proposed_source_url=f"https://demo.example/{board}",
                        proposed_connector="demo", monitoring_status="monitoring" if index == 0 else "draft",
                        source_health="healthy" if index == 0 else "unknown", baseline_complete=index == 0,
                        include_existing=True, next_check_at=timestamp,
                        research_summary="Synthetic evidence illustrates a month-level program announcement." if index == 0 else "Research or inspect the source before approving monitoring.")
        session.add(target)
        session.flush()
        if index == 0:
            session.add(Evidence(target_id=target.id, url=f"https://demo.example/{board}/program",
                                 excerpt=f"Applications for the previous cycle are expected in September {start - 2}.",
                                 retrieved_at=timestamp.isoformat(), kind="historical", date_value=last_opening,
                                 date_precision="month", date_meaning="announced_expected", match_status="exact program",
                                 explanation="Synthetic month-level announcement. It does not establish an exact opening day."))


def bootstrap(db, settings):
    with db.session() as session:
        # The API and the worker both bind the mode on start; only one may write it.
        if db.dialect == "sqlite":
            session.execute(text("BEGIN IMMEDIATE"))
        else:
            session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": SCHEMA_LOCK})
        bind_dataset_mode(session, settings)
        session.commit()


def reset_demo(session, settings, user_id):
    """Restore one demo account to the example targets; other accounts are untouched."""
    if settings.mode != "demo":
        raise ValueError("Demo reset is unavailable in live mode")
    # Matches, evidence, tasks, and delivery events go with their targets and deliveries.
    for target in session.scalars(select(Target).where(Target.user_id == user_id)):
        session.delete(target)
    session.execute(delete(Delivery).where(Delivery.user_id == user_id))
    session.execute(delete(ResearchUsage).where(ResearchUsage.user_id == user_id))
    session.get(Preference, user_id).data = Preferences().model_dump()
    session.flush()
    seed_demo(session, user_id)
