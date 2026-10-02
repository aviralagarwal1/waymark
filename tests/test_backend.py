from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import select

from waymark.api import create_app
from waymark.database import init_db
from waymark.demo import seed_demo
from waymark.discovery.connectors import _demo
from waymark.discovery.matching import match_posting
from waymark import auth
from waymark.models import Delivery, DeliveryEvent, Match, Preference, Target, Task, User
from waymark.notifications import deliver_pending, plan_deliveries, quiet
from waymark.schemas import Preferences
from waymark.services import enqueue, preferences, target_dict
from waymark.settings import Settings
from waymark.worker import apply_source_result, claim_task, execute_task, recover_leases, run_once

AT = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)


OWNER = "owner@example.com"


@pytest.fixture
def env(tmp_path):
    settings = Settings(mode="demo", data_dir=str(tmp_path))
    db = init_db(settings)
    with db.session.begin() as session:
        auth.create_user(session, OWNER, "correct horse battery", AT, verified=True)
    yield db, settings
    db.engine.dispose()


def owner_id(db, email=OWNER):
    with db.session() as session:
        return session.scalar(select(User.id).where(User.email == email))


def set_prefs(session, db, **changes):
    uid_ = owner_id(db)
    session.get(Preference, uid_).data = preferences(session, uid_).model_copy(update=changes).model_dump()


def target(db, **kwargs):
    user_id = owner_id(db)
    with db.session.begin() as session:
        row = Target(user_id=user_id, company="Example", role="Engineer", source_url="https://demo.example/example", connector="demo",
                     monitoring_status="monitoring", **kwargs)
        session.add(row)
        session.flush()
        return row.id


def sign_up(client, email, password="correct horse battery"):
    response = client.post("/api/auth/signup", json={"email": email, "password": password})
    assert response.status_code == 202, response.text
    return response


def posting(identifier="1"):
    return {"external_id": identifier, "title": "Engineer", "url": f"https://demo.example/example/{identifier}",
            "location": "London", "published_at": None, "date_meaning": "unknown"}


def source(*postings, status="ok", complete=True):
    return {"status": status, "complete": complete, "postings": list(postings), "error": "Blocked" if status != "ok" else ""}


def match_all(*_):
    return {"status": "match", "reason": "Role and eligibility match"}


def test_baseline_dedupe_new_annual_posting_and_confirmed_closure(env):
    db, settings = env
    tid = target(db)
    with db.session.begin() as session:
        row = session.get(Target, tid)
        apply_source_result(session, row, source(posting()), AT, match_all)
        session.flush()
        initial = session.scalar(select(Match))
        assert not initial.notify_eligible
        apply_source_result(session, row, source(posting(), posting("new-cycle")), AT + timedelta(hours=6), match_all)
        session.flush()
        assert len(session.scalars(select(Match)).all()) == 2
        assert session.scalar(select(Match).where(Match.id != initial.id)).notify_eligible
        apply_source_result(session, row, source(status="failed", complete=False), AT + timedelta(hours=12), match_all)
        assert initial.missing_checks == 0
        assert row.source_health == "failed"
        apply_source_result(session, row, source(), AT + timedelta(hours=18), match_all)
        assert not initial.closed
        apply_source_result(session, row, source(), AT + timedelta(hours=24), match_all)
        assert initial.closed


def test_shared_fetch_and_restart_do_not_duplicate_alerts(env):
    db, settings = env
    target(db, include_existing=True)
    target(db, include_existing=True)
    calls = []
    def fetcher(*args, **kwargs):
        calls.append(args)
        return source(posting())
    first = run_once(db, settings, AT, fetcher=fetcher, matcher=match_all)
    assert len(calls) == 1
    assert first["deliveries_sent"] == 1
    db.engine.dispose()
    db = init_db(settings)
    second = run_once(db, settings, AT + timedelta(seconds=10), fetcher=fetcher, matcher=match_all)
    assert second["deliveries_sent"] == 0
    with db.session() as session:
        assert len(session.scalars(select(Delivery)).all()) == 1
        assert all(match.initial_notified_at for match in session.scalars(select(Match)))


def test_reminders_follow_delivery_cancel_applied_and_consolidate_overdue(env):
    db, settings = env
    tid = target(db, include_existing=True)
    run_once(db, settings, AT, fetcher=lambda *_args, **_kwargs: source(posting()), matcher=match_all)
    with db.session.begin() as session:
        row = session.get(Target, tid)
        row.next_check_at = AT + timedelta(days=30)
        plan_deliveries(session, settings, AT + timedelta(days=4))
    assert deliver_pending(db, settings, AT + timedelta(days=4)) == 1
    with db.session.begin() as session:
        assert len(session.scalars(select(Delivery)).all()) == 2
        reminder = session.scalar(select(Delivery).where(Delivery.kind == "reminder"))
        assert len(session.scalars(select(DeliveryEvent).where(DeliveryEvent.delivery_id == reminder.id)).all()) == 2
        session.scalar(select(Match)).status = "applied"
        set_prefs(session, db, reminder_days=[1, 3, 5])
        assert plan_deliveries(session, settings, AT + timedelta(days=6)) == []


def test_pause_between_outbox_and_send_cancels_delivery(env):
    db, settings = env
    tid = target(db, include_existing=True)
    with db.session.begin() as session:
        row = session.get(Target, tid)
        apply_source_result(session, row, source(posting()), AT, match_all)
        session.flush()
        plan_deliveries(session, settings, AT)
        row.monitoring_status = "paused"
    assert deliver_pending(db, settings, AT) == 0
    with db.session() as session:
        assert session.scalar(select(Delivery)).status == "canceled"


def test_smtp_ambiguous_outcome_is_not_retried(env):
    db, settings = env
    tid = target(db, include_existing=True)
    settings = Settings(mode="live", data_dir=settings.data_dir, email_transport="smtp", smtp_host="smtp.example", email_from="bot@example.com")
    with db.session.begin() as session:
        row = session.get(Target, tid)
        apply_source_result(session, row, source(posting()), AT, match_all)
        session.flush()
        plan_deliveries(session, settings, AT)
    attempts = []
    def ambiguous(*_):
        attempts.append(True)
        raise OSError("Connection lost after DATA")
    deliver_pending(db, settings, AT, sender=ambiguous)
    deliver_pending(db, settings, AT + timedelta(minutes=5), sender=ambiguous)
    assert len(attempts) == 1
    with db.session() as session:
        assert session.scalar(select(Delivery)).status == "uncertain"
        assert session.scalar(select(Match)).initial_notified_at is None


def test_stale_research_does_not_overwrite_user_correction(env):
    db, settings = env
    tid = target(db)
    with db.session.begin() as session:
        task = enqueue(session, "research", session.get(Target, tid), at=AT)
        task_id = task.id
    claim_task(db, AT)
    def research(snapshot, **kwargs):
        with db.session.begin() as session:
            row = session.get(Target, tid)
            row.company, row.historical_date, row.version = "Corrected employer", "2025-08", row.version + 1
        return {"status": "ready", "historical_date": "1900-01-01", "proposed_source_url": "https://demo.example/wrong", "evidence": []}
    execute_task(db, settings, task_id, AT, researcher=research)
    with db.session() as session:
        row = session.get(Target, tid)
        assert row.company == "Corrected employer"
        assert row.historical_date == "2025-08"
        assert row.proposed_source_url == ""
        assert session.get(Task, task_id).status == "stale"


def test_expired_check_recovers_but_paid_research_needs_explicit_retry(env):
    db, settings = env
    tid = target(db)
    with db.session.begin() as session:
        row = session.get(Target, tid)
        for kind in ("check", "research"):
            task = enqueue(session, kind, row, at=AT)
            task.status, task.lease_until = "running", AT - timedelta(minutes=1)
        session.flush()
        recover_leases(session, AT)
        results = {task.kind: task.status for task in session.scalars(select(Task))}
        assert results == {"check": "queued", "research": "failed"}


def test_daily_digest_quiet_hours_timezone_and_cap(env):
    db, settings = env
    tid = target(db, include_existing=True)
    with db.session.begin() as session:
        row = session.get(Target, tid)
        apply_source_result(session, row, source(posting()), AT, match_all)
        session.flush()
        set_prefs(session, db, email_mode="daily", digest_hour=9, daily_email_cap=1)
        assert plan_deliveries(session, settings, AT.replace(hour=12)) == []  # 07:00 Chicago
        assert len(plan_deliveries(session, settings, AT)) == 1
    assert deliver_pending(db, settings, AT) == 1
    with db.session.begin() as session:
        row = session.get(Target, tid)
        apply_source_result(session, row, source(posting(), posting("2")), AT, match_all)
        session.flush()
        assert plan_deliveries(session, settings, AT + timedelta(hours=1)) == []
        assert len(plan_deliveries(session, settings, AT + timedelta(days=1))) == 2  # digest + reminder
    assert deliver_pending(db, settings, AT + timedelta(days=1)) == 1
    prefs = Preferences(quiet_start=22, quiet_end=8)
    assert quiet(prefs, AT.replace(hour=4))  # previous date 23:00 local
    assert not quiet(prefs, AT)


def test_api_optimistic_edit_origin_validation_and_reset(tmp_path):
    app = create_app(Settings(data_dir=str(tmp_path)))
    with TestClient(app) as client:
        sign_up(client, "person@example.com")
        row = client.post("/api/targets", json={"company": "My company", "role": "Researcher"}).json()
        assert row["version"] == 1
        changed = client.patch(f"/api/targets/{row['id']}", json={"version": 1, "notes": "User correction"})
        assert changed.status_code == 200
        stale = client.patch(f"/api/targets/{row['id']}", json={"version": 1, "notes": "Wrong"})
        assert stale.status_code == 409
        assert client.post("/api/targets", json={"company": "x", "role": "y"}, headers={"Origin": "https://attacker.example"}).status_code == 403
        assert client.post("/api/targets", json={"company": "x", "role": "y", "source_url": "http://127.0.0.1/secret"}).status_code == 422
        assert client.get("/api/health").json()["status"] == "worker_missing"
        assert "anthropic_api_key" not in client.get("/api/settings").text
        assert client.delete(f"/api/targets/{row['id']}").status_code == 204
        assert client.post("/api/demo/reset").status_code == 200
        assert len(client.get("/api/targets").json()) == 3


def test_link_previews_name_the_install_own_origin(tmp_path):
    static = tmp_path / "dist"
    static.mkdir()
    (static / "index.html").write_text('<meta property="og:image" content="__APP_BASE_URL__/og.png">', encoding="utf-8")
    (static / "og.png").write_bytes(b"png")
    app = create_app(Settings(data_dir=str(tmp_path), static_dir=str(static), base_url="https://waymark.example/"))
    with TestClient(app, base_url="https://waymark.example") as client:
        for path in ["/", "/signin", "/index.html"]:
            assert client.get(path).text == '<meta property="og:image" content="https://waymark.example/og.png">'
        assert client.get("/og.png").content == b"png"


def test_live_mode_requires_separate_data_and_prevents_demo_reset(tmp_path):
    settings = Settings(mode="live", data_dir=str(tmp_path))
    app = create_app(settings)
    with TestClient(app) as client:
        with app.state.db.session.begin() as session:
            auth.create_user(session, "live@example.com", "correct horse battery", AT, verified=True)
        assert client.post("/api/auth/login", json={"email": "live@example.com", "password": "correct horse battery"}).status_code == 200
        assert client.get("/api/targets").json() == []
        assert client.post("/api/demo/reset").status_code == 403
    with pytest.raises(RuntimeError, match="different APP_MODE"):
        with TestClient(create_app(Settings(mode="demo", data_dir=str(tmp_path)))):
            pass


def test_monthly_budget_is_reserved_before_research_and_enforced(env):
    db, settings = env
    settings = Settings(mode="live", data_dir=settings.data_dir, anthropic_api_key="test-not-a-real-key")
    tid = target(db)
    with db.session.begin() as session:
        set_prefs(session, db, research_monthly_budget_usd=0)
        task_id = enqueue(session, "research", session.get(Target, tid), at=AT).id
    claim_task(db, AT)
    execute_task(db, settings, task_id, AT, researcher=lambda *args, **kwargs: pytest.fail("Budget must block the provider call"))
    with db.session() as session:
        assert session.get(Task, task_id).status == "failed"
        assert "budget" in session.get(Task, task_id).error


def test_task_enqueue_is_coalesced_by_target(env):
    db, settings = env
    tid = target(db)
    with db.session.begin() as session:
        row = session.get(Target, tid)
        first = enqueue(session, "check", row)
        second = enqueue(session, "check", row)
        assert first.id == second.id


def test_check_does_not_apply_results_after_target_edit(env):
    db, settings = env
    tid = target(db, include_existing=True)
    with db.session.begin() as session:
        task_id = enqueue(session, "check", session.get(Target, tid), at=AT).id
    claim_task(db, AT)

    def fetcher(*args, **kwargs):
        with db.session.begin() as session:
            row = session.get(Target, tid)
            row.role, row.version = "Designer", row.version + 1
        return source(posting())

    execute_task(db, settings, task_id, AT, fetcher=fetcher, matcher=match_all)
    with db.session() as session:
        assert session.get(Task, task_id).status == "stale"
        assert session.get(Target, tid).last_checked_at is None
        assert session.scalar(select(Match)) is None


def test_test_email_only_queues_and_worker_delivers(tmp_path):
    settings = Settings(data_dir=str(tmp_path))
    app = create_app(settings)
    with TestClient(app) as client:
        sign_up(client, "person@example.com")
        with app.state.db.session.begin() as session:
            user_id = session.scalar(select(User.id))
            unrelated = Delivery(user_id=user_id, dedupe_key="unrelated", kind="test", subject="Already queued", plain_body="Preview")
            session.add(unrelated)
            session.flush()
            unrelated_id = unrelated.id
        response = client.post("/api/email/test")
        assert response.status_code == 200
        assert response.json()["status"] == "pending"
        with app.state.db.session() as session:
            assert session.get(Delivery, unrelated_id).status == "pending"
            assert session.get(Delivery, response.json()["delivery_id"]).status == "pending"
        assert deliver_pending(app.state.db, settings, AT) == 2


def test_signed_out_requests_host_and_import_size_controls(tmp_path):
    with TestClient(create_app(Settings(data_dir=str(tmp_path)))) as client:
        assert client.get("/api/targets").status_code == 401
        sign_up(client, "person@example.com")
        assert client.get("/api/targets").status_code == 200
        assert client.get("/api/targets", headers={"Host": "attacker.example"}).status_code == 400
        assert client.post("/api/email/test", headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
        from waymark.portability import MAX_BYTES
        response = client.post("/api/imports/preview", files={"file": ("targets.csv", b"a" * (MAX_BYTES + 1), "text/csv")})
        assert response.status_code == 413


def test_real_demo_research_approval_and_email_preview_vertical_flow(tmp_path):
    settings = Settings(data_dir=str(tmp_path))
    app = create_app(settings)
    with TestClient(app) as client:
        sign_up(client, "person@example.com")
        row = client.post("/api/targets", json={
            "company": "Demo Research", "role": "Research Intern", "location": "London",
            "employment_type": "Intern", "level": "", "start_period": "Summer 2027",
        }).json()
        tid = row["id"]
        assert client.post(f"/api/targets/{tid}/research").status_code == 200
        run_once(app.state.db, settings)
        refreshed = next(item for item in client.get("/api/targets").json() if item["id"] == tid)
        assert refreshed["research_status"] == "ready"
        assert refreshed["historical_date"] is None
        assert len(client.get(f"/api/targets/{tid}/evidence").json()) == 1
        approved = client.post(f"/api/targets/{tid}/approve", json={"include_existing": True})
        assert approved.status_code == 200, approved.text
        assert approved.json()["source_health"] == "healthy"
        run_once(app.state.db, settings)
        matches = [item for item in client.get("/api/matches").json() if item["target_id"] == tid]
        assert len(matches) == 1
        assert matches[0]["initial_notified_at"]
        assert any(item["status"] == "preview" for item in client.get("/api/deliveries").json())
        assert client.patch(f"/api/matches/{matches[0]['id']}", json={"status": "applied"}).status_code == 200


@pytest.mark.parametrize("today", [date(2026, 9, 30), date(2027, 1, 2), date(2031, 6, 15)])
def test_demo_targets_and_board_share_a_cohort_on_any_date(tmp_path, today):
    # The demo only produces matches when the seeded targets and the demo board
    # agree on the start cohort, and both roll forward with the date.
    settings = Settings(mode="demo", data_dir=str(tmp_path))
    db = init_db(settings)
    with db.session.begin() as session:
        user = auth.create_user(session, OWNER, "correct horse battery", AT, verified=True)
        seed_demo(session, user.id, today=today)
    with db.session() as session:
        northstar = session.scalars(select(Target).where(Target.company == "Northstar Labs")).one()
        seeded = target_dict(northstar)
    db.engine.dispose()
    board = _demo({"board": "northstar", "url": "https://demo.example/northstar"}, today)
    posting = next(p for p in board if p["title"] == "Associate Product Manager")
    assert seeded["start_period"] == f"Summer {today.year + 1}"
    assert seeded["historical_date"] == f"{today.year - 1}-09"
    assert match_posting(seeded, posting)["status"] == "match"
