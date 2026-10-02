"""Accounts, sessions, one-time links, rate limits, isolation, and the Resend transport."""
from datetime import datetime, timedelta, timezone
import re

from fastapi.testclient import TestClient
import httpx
import pytest
from sqlalchemy import delete, func, select

from waymark import auth
from waymark.api import create_app
from waymark.models import AuthAttempt, AuthSession, AuthToken, Delivery, DeliveryEvent, Evidence, Match, Posting, Preference, ResearchUsage, RuntimeState, Target, Task, User
from waymark.notifications import CLEARED_BODY, deliver_pending, send_resend
from waymark.settings import Settings
from waymark.worker import apply_source_result

PASSWORD = "correct horse battery"
AT = datetime(2026, 9, 20, 15, tzinfo=timezone.utc)


def live_client(tmp_path, **settings):
    app = create_app(Settings(mode="live", data_dir=str(tmp_path), **settings))
    return app, TestClient(app)


def link_token(app, email, kind):
    with app.state.db.session() as session:
        user = session.scalar(select(User).where(User.email == email))
        body = session.scalars(select(Delivery).where(Delivery.user_id == user.id, Delivery.kind == kind).order_by(Delivery.created_at.desc())).first().plain_body
    return re.search(r"token=([\w-]+)", body).group(1)


def test_signup_needs_verification_then_signs_in_and_out(tmp_path):
    app, client = live_client(tmp_path)
    with client:
        assert client.post("/api/auth/signup", json={"email": " Person@Example.com ", "password": PASSWORD}).json() == {"status": "check_email"}
        assert "waymark_session" not in client.cookies
        assert client.post("/api/auth/login", json={"email": "person@example.com", "password": PASSWORD}).status_code == 403
        token = link_token(app, "person@example.com", "verify")
        assert client.post("/api/auth/verify", json={"token": token}).status_code == 200
        assert client.get("/api/auth/me").json() == {"email": "person@example.com"}
        assert client.post("/api/auth/verify", json={"token": token}).status_code == 400  # one use only
        client.post("/api/auth/logout")
        assert client.get("/api/auth/me").status_code == 401
        assert client.post("/api/auth/login", json={"email": "person@example.com", "password": "wrong password!"}).status_code == 401
        assert client.post("/api/auth/login", json={"email": "PERSON@example.com", "password": PASSWORD}).status_code == 200
        assert client.get("/api/targets").status_code == 200


def test_signup_and_forgot_do_not_reveal_whether_an_email_is_registered(tmp_path):
    app, client = live_client(tmp_path)
    with client:
        with app.state.db.session.begin() as session:
            auth.create_user(session, "taken@example.com", PASSWORD, AT, verified=True)
        first = client.post("/api/auth/signup", json={"email": "taken@example.com", "password": "another password"})
        second = client.post("/api/auth/signup", json={"email": "new@example.com", "password": PASSWORD})
        assert first.status_code == second.status_code == 202 and first.json() == second.json()
        assert client.post("/api/auth/forgot", json={"email": "nobody@example.com"}).json() == client.post("/api/auth/forgot", json={"email": "taken@example.com"}).json()
        with app.state.db.session() as session:
            kinds = {d.kind for d in session.scalars(select(Delivery).join(User, Delivery.user_id == User.id).where(User.email == "taken@example.com"))}
            assert kinds == {"account_exists", "reset"}
            # The existing account's password was not replaced by the second sign-up.
            assert auth.password_matches(session.scalar(select(User).where(User.email == "taken@example.com")), PASSWORD)


def test_password_rules_and_link_secrets_are_not_stored(tmp_path):
    app, client = live_client(tmp_path)
    with client:
        assert client.post("/api/auth/signup", json={"email": "person@example.com", "password": "short"}).status_code == 422
        assert client.post("/api/auth/signup", json={"email": "not-an-email", "password": PASSWORD}).status_code == 422
        client.post("/api/auth/signup", json={"email": "person@example.com", "password": PASSWORD})
        token = link_token(app, "person@example.com", "verify")
        with app.state.db.session() as session:
            user = session.scalar(select(User))
            assert PASSWORD not in user.password_hash and user.password_hash.startswith("$argon2id$")
            assert session.get(AuthToken, token) is None and session.get(AuthToken, auth.digest(token))


def test_reset_signs_out_everywhere_and_links_expire(tmp_path):
    app, client = live_client(tmp_path)
    with client, TestClient(app) as other_device:
        with app.state.db.session.begin() as session:
            auth.create_user(session, "person@example.com", PASSWORD, AT, verified=True)
        assert other_device.post("/api/auth/login", json={"email": "person@example.com", "password": PASSWORD}).status_code == 200
        client.post("/api/auth/forgot", json={"email": "person@example.com"})
        token = link_token(app, "person@example.com", "reset")
        assert client.post("/api/auth/reset", json={"token": token, "password": "a brand new password"}).status_code == 200
        assert other_device.get("/api/auth/me").status_code == 401
        assert client.get("/api/auth/me").status_code == 200
        assert client.post("/api/auth/login", json={"email": "person@example.com", "password": PASSWORD}).status_code == 401
        client.post("/api/auth/forgot", json={"email": "person@example.com"})
        token = link_token(app, "person@example.com", "reset")
        with app.state.db.session.begin() as session:
            session.get(AuthToken, auth.digest(token)).expires_at = AT
        assert client.post("/api/auth/reset", json={"token": token, "password": "yet another password"}).status_code == 400


def test_failed_sign_ins_are_rate_limited(tmp_path):
    app, client = live_client(tmp_path)
    with client:
        with app.state.db.session.begin() as session:
            auth.create_user(session, "person@example.com", PASSWORD, AT, verified=True)
        codes = [client.post("/api/auth/login", json={"email": "person@example.com", "password": "wrong password!"}).status_code for _ in range(11)]
        assert codes[:10] == [401] * 10 and codes[10] == 429
        # The limit holds even for the right password until the window passes.
        assert client.post("/api/auth/login", json={"email": "person@example.com", "password": PASSWORD}).status_code == 429


def test_rate_limits_key_on_the_client_behind_trusted_proxies_only(tmp_path):
    def ip_keys(hops, forwarded):
        app, client = live_client(tmp_path / str(hops), trusted_proxy_hops=hops)
        with client:
            client.post("/api/auth/login", json={"email": "person@example.com", "password": "wrong password!"}, headers={"X-Forwarded-For": forwarded})
            with app.state.db.session.begin() as session:
                keys = {key for key in session.scalars(select(AuthAttempt.key)) if ":ip:" in key}
                # Each round starts empty, even when the rounds share one database.
                session.execute(delete(AuthAttempt))
                return keys
    # Without trusted proxies the header is ignored; with one, a forged entry
    # to the left of the proxy's own does not change the key.
    assert ip_keys(0, "203.0.113.9") == {"login_failure:ip:testclient"}
    assert ip_keys(1, "198.51.100.1, 203.0.113.9") == {"login_failure:ip:203.0.113.9"}
    assert ip_keys(2, "198.51.100.1, 203.0.113.9, 10.0.0.2") == {"login_failure:ip:203.0.113.9"}


def test_users_cannot_reach_each_others_data(tmp_path):
    app = create_app(Settings(data_dir=str(tmp_path)))
    with TestClient(app) as alice, TestClient(app) as bob:
        alice.post("/api/auth/signup", json={"email": "alice@example.com", "password": PASSWORD})
        bob.post("/api/auth/signup", json={"email": "bob@example.com", "password": PASSWORD})
        mine = alice.post("/api/targets", json={"company": "Alice Co", "role": "Analyst"}).json()
        tid = mine["id"]
        with app.state.db.session.begin() as session:
            row = session.get(Target, tid)
            row.monitoring_status, row.source_url, row.connector = "monitoring", "https://demo.example/alice", "demo"
            apply_source_result(session, row, {"status": "ok", "complete": True, "postings": [{"external_id": "1", "title": "Analyst", "url": "https://demo.example/alice/1"}]}, AT, lambda *_: {"status": "match", "reason": "Test"})
            session.flush()
            match_id = session.scalar(select(Match.id))
        assert all(t["company"] != "Alice Co" for t in bob.get("/api/targets").json())
        assert bob.get(f"/api/targets/{tid}/evidence").status_code == 404
        assert bob.patch(f"/api/targets/{tid}", json={"version": 1, "notes": "Bob was here"}).status_code == 404
        assert bob.post(f"/api/targets/{tid}/research").status_code == 404
        assert bob.post(f"/api/targets/{tid}/check").status_code == 404
        assert bob.post(f"/api/targets/{tid}/approve").status_code == 404
        assert bob.delete(f"/api/targets/{tid}").status_code == 404
        assert bob.patch(f"/api/matches/{match_id}", json={"status": "dismissed"}).status_code == 404
        assert all(m["id"] != match_id for m in bob.get("/api/matches").json())
        assert b"Alice Co" not in bob.get("/api/exports/targets").content
        merged = bob.post("/api/imports/commit", json={"merge": True, "rows": [{"id": tid, "version": 1, "company": "Hijacked", "role": "x"}]}).json()
        assert merged["updated"] == 0 and merged["created"] == 1
        assert bob.post("/api/demo/reset").status_code == 200
        with app.state.db.session() as session:
            assert session.get(Target, tid).company == "Alice Co"
            assert session.get(Match, match_id).status == "new"


def test_deleting_an_account_needs_the_password_and_removes_everything_it_owns(tmp_path):
    app = create_app(Settings(data_dir=str(tmp_path)))
    with TestClient(app) as alice, TestClient(app) as bob:
        alice.post("/api/auth/signup", json={"email": "alice@example.com", "password": PASSWORD})
        bob.post("/api/auth/signup", json={"email": "bob@example.com", "password": PASSWORD})
        with app.state.db.session() as session:
            alice_id = session.scalar(select(User.id).where(User.email == "alice@example.com"))
            bob_targets = session.scalar(select(func.count()).select_from(Target).join(User, Target.user_id == User.id).where(User.email == "bob@example.com"))
        tid = alice.post("/api/targets", json={"company": "Alice Co", "role": "Analyst"}).json()["id"]
        alice.post(f"/api/targets/{tid}/research")
        alice.post("/api/email/test")
        with app.state.db.session.begin() as session:
            row = session.get(Target, tid)
            row.monitoring_status, row.source_url, row.connector = "monitoring", "https://demo.example/alice", "demo"
            apply_source_result(session, row, {"status": "ok", "complete": True, "postings": [{"external_id": "1", "title": "Analyst", "url": "https://demo.example/alice/1"}]}, AT, lambda *_: {"status": "match", "reason": "Test"})
            session.add(RuntimeState(key=f"digest_slot:{alice_id}", value={"slot": "x"}))
        assert alice.post("/api/auth/delete", json={"password": "wrong password!"}).status_code == 403
        assert alice.get("/api/auth/me").status_code == 200
        response = alice.post("/api/auth/delete", json={"password": PASSWORD})
        assert response.status_code == 204 and "waymark_session" in response.headers["set-cookie"]
        assert alice.get("/api/targets").status_code == 401
        with app.state.db.session() as session:
            assert session.get(User, alice_id) is None
            assert session.get(Preference, alice_id) is None and session.get(RuntimeState, f"digest_slot:{alice_id}") is None
            for model in (Target, Delivery, ResearchUsage, AuthSession, AuthToken):
                assert not session.scalars(select(model).where(model.user_id == alice_id)).first(), model
            for model in (Evidence, Match, Task):
                assert not session.scalars(select(model).where(model.target_id == tid)).first(), model
            assert not session.scalars(select(DeliveryEvent)).first()
            assert not session.scalars(select(AuthAttempt).where(AuthAttempt.key.contains("alice@example.com"))).first()
            # Shared board data stays, and so does every other account.
            assert session.scalars(select(Posting)).first()
            assert session.scalar(select(func.count()).select_from(Target).join(User, Target.user_id == User.id).where(User.email == "bob@example.com")) == bob_targets
        assert bob.get("/api/auth/me").json() == {"email": "bob@example.com"}
        # The address is free again.
        assert alice.post("/api/auth/signup", json={"email": "alice@example.com", "password": PASSWORD}).json()["status"] == "signed_in"


def test_account_emails_skip_alert_rules_and_are_cleared_after_sending(tmp_path):
    app, client = live_client(tmp_path)
    with client:
        client.post("/api/auth/signup", json={"email": "person@example.com", "password": PASSWORD})
        assert deliver_pending(app.state.db, app.state.settings, AT) == 1
        with app.state.db.session() as session:
            delivery = session.scalar(select(Delivery))
            assert delivery.status == "preview" and delivery.plain_body == CLEARED_BODY


def resend_settings(tmp_path):
    return Settings(mode="live", data_dir=str(tmp_path), email_transport="resend", resend_api_key="re_test_not_real", email_from="waymark@aviralagarwal.com")


def test_resend_retries_under_one_idempotency_key_and_stops_on_rejection(tmp_path):
    settings = resend_settings(tmp_path)
    app = create_app(settings)
    with TestClient(app) as client:
        client.post("/api/auth/signup", json={"email": "person@example.com", "password": PASSWORD})
        keys = []
        def flaky(_settings, recipient, subject, body, delivery_id):
            keys.append(delivery_id)
            if len(keys) == 1:
                raise httpx.ConnectError("connection reset")
        deliver_pending(app.state.db, settings, AT, sender=flaky)
        deliver_pending(app.state.db, settings, AT + timedelta(seconds=10), sender=flaky)
        with app.state.db.session() as session:
            assert session.scalar(select(Delivery)).status == "sent"
        assert len(keys) == 2 and keys[0] == keys[1]

        client.post("/api/auth/resend", json={"email": "person@example.com"})
        from waymark.notifications import ResendRejected
        calls = []
        def rejecting(*args):
            calls.append(args)
            raise ResendRejected(422)
        deliver_pending(app.state.db, settings, AT + timedelta(minutes=1), sender=rejecting)
        deliver_pending(app.state.db, settings, AT + timedelta(minutes=2), sender=rejecting)
        assert len(calls) == 1
        with app.state.db.session() as session:
            failed = session.scalar(select(Delivery).where(Delivery.status == "failed"))
            assert "HTTP 422" in failed.error and failed.plain_body == CLEARED_BODY


def test_resend_request_shape(tmp_path, monkeypatch):
    seen = {}
    def fake_post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return httpx.Response(200, json={"id": "email_1"}, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", fake_post)
    send_resend(resend_settings(tmp_path), "person@example.com", "Subject", "Body", "delivery-123")
    assert seen["headers"]["Idempotency-Key"] == "delivery-123"
    assert seen["headers"]["Authorization"] == "Bearer re_test_not_real"
    assert seen["json"] == {"from": "Waymark <waymark@aviralagarwal.com>", "to": ["person@example.com"], "subject": "Subject", "text": "Body"}
    monkeypatch.setattr(httpx, "post", lambda url, **kw: httpx.Response(503, request=httpx.Request("POST", url)))
    with pytest.raises(httpx.HTTPStatusError):
        send_resend(resend_settings(tmp_path), "person@example.com", "Subject", "Body", "delivery-123")
