"""Same-origin API with accounts, and the production static frontend."""
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from html import escape
import json
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pydantic import ValidationError
from sqlalchemy import func, select
from starlette.middleware.trustedhost import TrustedHostMiddleware
from waymark import auth
from waymark.brand import NAME
from waymark.database import Database
from waymark.demo import bootstrap, reset_demo, seed_demo
from waymark.models import Delivery, Evidence, Match, Preference, RuntimeState, Target, Task, User, now, uid
from waymark.schemas import Approval, Credentials, EmailRequest, ImportCommit, MatchPatch, PasswordConfirm, PasswordReset, Preferences, TargetInput, TargetPatch, TokenRequest
from waymark.services import create_target, edit_target, enqueue, get_target, preferences, serialize, target_dict
from waymark.settings import Settings


def create_app(settings=None):
    settings = settings or Settings.from_env()
    db = Database(settings)
    base = urlsplit(settings.base_url)
    local_hosts = {"localhost", "127.0.0.1", "::1", "testserver"}

    @asynccontextmanager
    async def lifespan(app):
        db.initialize()
        bootstrap(db, settings)
        yield
        db.engine.dispose()

    app = FastAPI(title=NAME, version="0.1.0", lifespan=lifespan)
    app.state.db, app.state.settings = db, settings
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=sorted(local_hosts | {base.hostname or "localhost"}))

    @app.middleware("http")
    async def security(request, call_next):
        # Session cookies are SameSite=Lax, and every write must also come from
        # this origin, so a foreign page cannot act as a signed-in user.
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            host_origin = f"{request.url.scheme}://{request.headers.get('host', '')}"
            if origin and origin.rstrip("/") not in {settings.base_url, host_origin}:
                return JSONResponse(status_code=403, content={"detail": "Cross-origin writes are not allowed"})
            if request.headers.get("sec-fetch-site") == "cross-site":
                return JSONResponse(status_code=403, content={"detail": "Cross-site writes are not allowed"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path.startswith("/api"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(ValidationError)
    async def validation_error(request, exc):
        return JSONResponse(status_code=422, content={"detail": [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]})

    def current_user(request: Request):
        with db.session.begin() as session:
            user = auth.user_for_session(session, request.cookies.get(auth.SESSION_COOKIE), now())
            if not user:
                raise HTTPException(401, "Sign in to continue")
            return user.id

    def client_ip(request):
        # Each trusted proxy appends the address it received the request from,
        # so the client is that many entries from the right. Entries further
        # left were sent by the client and can be forged.
        hops = settings.trusted_proxy_hops
        forwarded = [part.strip() for part in request.headers.get("x-forwarded-for", "").split(",") if part.strip()]
        if hops and len(forwarded) >= hops:
            return forwarded[-hops]
        return request.client.host if request.client else "unknown"

    def set_session_cookie(response, token):
        response.set_cookie(auth.SESSION_COOKIE, token, max_age=auth.SESSION_DAYS * 86400, httponly=True,
                            secure=settings.secure_cookies, samesite="lax", path="/")

    # Accounts. Sign-up, resend, and forgot answer the same way whether or not
    # the email has an account, so the responses never confirm who is registered.

    @app.post("/api/auth/signup", status_code=202)
    def signup(data: Credentials, request: Request, response: Response):
        email = auth.normalize_email(data.email)
        auth.check_password_rules(data.password)
        timestamp = now()
        with db.session.begin() as session:
            auth.rate_limit(session, "email_request", email, client_ip(request), timestamp)
            existing = session.scalar(select(User).where(User.email == email))
            if existing:
                if existing.email_verified_at:
                    auth.queue_account_email(session, existing, "account_exists", settings.base_url, timestamp)
                else:
                    token = auth.issue_token(session, existing, "verify", timestamp)
                    auth.queue_account_email(session, existing, "verify", settings.base_url, timestamp, token)
                return {"status": "check_email"}
            if settings.mode == "demo":
                # Demo mode sends no email, so demo accounts start verified,
                # signed in, and seeded with the example targets.
                user = auth.create_user(session, email, data.password, timestamp, verified=True)
                seed_demo(session, user.id)
                set_session_cookie(response, auth.start_session(session, user, timestamp))
                return {"status": "signed_in", "email": user.email}
            user = auth.create_user(session, email, data.password, timestamp)
            token = auth.issue_token(session, user, "verify", timestamp)
            auth.queue_account_email(session, user, "verify", settings.base_url, timestamp, token)
        return {"status": "check_email"}

    @app.post("/api/auth/verify")
    def verify(data: TokenRequest, response: Response):
        timestamp = now()
        with db.session.begin() as session:
            user = auth.redeem_token(session, data.token, "verify", timestamp)
            user.email_verified_at = user.email_verified_at or timestamp
            set_session_cookie(response, auth.start_session(session, user, timestamp))
            return {"email": user.email}

    @app.post("/api/auth/login")
    def login(data: Credentials, request: Request, response: Response):
        email = (data.email or "").strip().lower()
        timestamp = now()
        with db.session.begin() as session:
            auth.rate_limit(session, "login_failure", email, client_ip(request), timestamp)
            user = session.scalar(select(User).where(User.email == email))
            if not auth.password_matches(user, data.password):
                # The attempt recorded by rate_limit stays as a failure.
                raise_after = HTTPException(401, "That email and password don't match an account")
            elif not user.email_verified_at:
                raise_after = HTTPException(403, "Confirm your email first. Check your inbox, or request a new link.")
            else:
                auth.clear_attempts(session, "login_failure", email)
                set_session_cookie(response, auth.start_session(session, user, timestamp))
                return {"email": user.email}
        raise raise_after

    @app.post("/api/auth/resend", status_code=202)
    def resend(data: EmailRequest, request: Request):
        email = auth.normalize_email(data.email)
        timestamp = now()
        with db.session.begin() as session:
            auth.rate_limit(session, "email_request", email, client_ip(request), timestamp)
            user = session.scalar(select(User).where(User.email == email))
            if user and not user.email_verified_at:
                token = auth.issue_token(session, user, "verify", timestamp)
                auth.queue_account_email(session, user, "verify", settings.base_url, timestamp, token)
        return {"status": "check_email"}

    @app.post("/api/auth/forgot", status_code=202)
    def forgot(data: EmailRequest, request: Request):
        email = auth.normalize_email(data.email)
        timestamp = now()
        with db.session.begin() as session:
            auth.rate_limit(session, "email_request", email, client_ip(request), timestamp)
            user = session.scalar(select(User).where(User.email == email))
            if user:
                token = auth.issue_token(session, user, "reset", timestamp)
                auth.queue_account_email(session, user, "reset", settings.base_url, timestamp, token)
        return {"status": "check_email"}

    @app.post("/api/auth/reset")
    def reset_password(data: PasswordReset, response: Response):
        auth.check_password_rules(data.password)
        timestamp = now()
        with db.session.begin() as session:
            user = auth.redeem_token(session, data.token, "reset", timestamp)
            user.password_hash = auth.hash_password(data.password)
            # Receiving the reset email proves control of the address.
            user.email_verified_at = user.email_verified_at or timestamp
            auth.end_all_sessions(session, user)
            set_session_cookie(response, auth.start_session(session, user, timestamp))
            return {"email": user.email}

    @app.post("/api/auth/logout", status_code=204)
    def logout(request: Request):
        with db.session.begin() as session:
            auth.end_session(session, request.cookies.get(auth.SESSION_COOKIE))
        response = Response(status_code=204)
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response

    @app.post("/api/auth/delete", status_code=204)
    def delete_account(data: PasswordConfirm, request: Request, user_id: str = Depends(current_user)):
        # The password is asked again so a borrowed or stolen session cannot
        # erase the account; failures count toward the sign-in limit.
        timestamp = now()
        with db.session.begin() as session:
            user = session.get(User, user_id)
            auth.rate_limit(session, "login_failure", user.email, client_ip(request), timestamp)
            confirmed = auth.password_matches(user, data.password)
            if confirmed:
                auth.delete_account(session, user)
        if not confirmed:
            raise HTTPException(403, "That password is wrong")
        response = Response(status_code=204)
        response.delete_cookie(auth.SESSION_COOKIE, path="/")
        return response

    @app.get("/api/auth/me")
    def me(user_id: str = Depends(current_user)):
        with db.session() as session:
            return {"email": session.get(User, user_id).email}

    # The workspace. Every route below is scoped to the signed-in user.

    @app.get("/api/health")
    def health(user_id: str = Depends(current_user)):
        with db.session.begin() as session:
            heartbeat = session.get(RuntimeState, "worker_heartbeat")
            targets = list(session.scalars(select(Target).where(Target.user_id == user_id)))
            target_ids = [t.id for t in targets]
            last_seen = heartbeat.value.get("at") if heartbeat else None
            healthy_worker = bool(last_seen and datetime.fromisoformat(last_seen) > now() - timedelta(minutes=settings.worker_stale_minutes))
            return {"status": "ok" if healthy_worker else "worker_missing", "mode": settings.mode,
                    "worker_last_seen": last_seen,
                    "counts": {"targets": len(targets), "monitoring": sum(t.monitoring_status == "monitoring" for t in targets),
                               "matches": session.scalar(select(func.count()).select_from(Match).where(Match.target_id.in_(target_ids))),
                               "pending_tasks": session.scalar(select(func.count()).select_from(Task).where(Task.target_id.in_(target_ids), Task.status.in_(["queued", "running"])))},
                    "configuration": {"ai": bool(settings.anthropic_api_key), "email": email_configured(),
                                      "email_transport": settings.email_transport},
                    "source_errors": [{"target_id": t.id, "company": t.company, "error": t.source_error} for t in targets if t.source_error]}

    def email_configured():
        if settings.email_transport == "smtp":
            return bool(settings.smtp_host and settings.email_from)
        if settings.email_transport == "resend":
            return bool(settings.resend_api_key and settings.email_from)
        return True

    @app.get("/api/targets")
    def list_targets(user_id: str = Depends(current_user)):
        with db.session() as session:
            return [target_dict(row) for row in session.scalars(select(Target).where(Target.user_id == user_id).order_by(Target.created_at))]

    @app.post("/api/targets", status_code=201)
    def add_target(data: TargetInput, user_id: str = Depends(current_user)):
        with db.session.begin() as session:
            return target_dict(create_target(session, data, user_id, demo=settings.mode == "demo"))

    @app.patch("/api/targets/{target_id}")
    def patch_target(target_id: str, data: TargetPatch, user_id: str = Depends(current_user)):
        with db.session.begin() as session:
            row = get_target(session, target_id, user_id)
            values = data.model_dump(mode="json", exclude_unset=True, exclude={"version"})
            return target_dict(edit_target(session, row, values, data.version, demo=settings.mode == "demo"))

    @app.delete("/api/targets/{target_id}", status_code=204)
    def delete_target(target_id: str, user_id: str = Depends(current_user)):
        with db.session.begin() as session:
            session.delete(get_target(session, target_id, user_id))
        return Response(status_code=204)

    @app.post("/api/targets/{target_id}/research")
    def research(target_id: str, user_id: str = Depends(current_user)):
        with db.session.begin() as session:
            row = get_target(session, target_id, user_id)
            task = enqueue(session, "research", row)
            return {"task_id": task.id}

    @app.post("/api/targets/{target_id}/check")
    def check(target_id: str, user_id: str = Depends(current_user)):
        with db.session.begin() as session:
            row = get_target(session, target_id, user_id)
            if not row.source_url:
                raise HTTPException(422, "Add and approve a source URL before checking")
            return {"task_id": enqueue(session, "check", row).id}

    @app.post("/api/targets/{target_id}/approve")
    def approve(target_id: str, data: Approval = Approval(), user_id: str = Depends(current_user)):
        from waymark.discovery import fetch_source, validate_source_url
        from waymark.worker import apply_source_result
        with db.session() as session:
            row = get_target(session, target_id, user_id)
            # Explicit manual corrections take precedence over research proposals.
            source = row.source_url or row.proposed_source_url
            connector = row.connector if row.source_url else row.proposed_connector
            version = row.version
        if not source:
            raise HTTPException(422, "Research or enter a source URL first")
        try:
            if not (settings.mode == "demo" and source.startswith("https://demo.example/")):
                validated = validate_source_url(source, connector)
                source, connector = validated["url"], validated["connector"]
            result = fetch_source(source, connector, demo=settings.mode == "demo")
        except Exception as exc:
            raise HTTPException(422, f"Source validation failed ({type(exc).__name__}). Check its URL and supported connector.") from exc
        with db.session.begin() as session:
            row = get_target(session, target_id, user_id)
            if row.version != version:
                raise HTTPException(409, "This row changed during source validation; review and approve it again")
            if result.get("status") != "ok" or not result.get("complete", False):
                row.source_health = "unsupported" if result.get("status") == "unsupported" else "failed"
                row.source_error = str(result.get("error") or "Source returned an incomplete result")[:1000]
                response = {"detail": row.source_error}
            else:
                if (row.source_url, row.connector) != (source, connector):
                    row.baseline_complete = False
                row.source_url, row.connector = source, connector
                row.include_existing, row.monitoring_status = data.include_existing, "monitoring"
                row.version += 1
                apply_source_result(session, row, result, now())
                response = target_dict(row)
        if "detail" in response:
            raise HTTPException(422, response["detail"])
        return response

    @app.get("/api/targets/{target_id}/evidence")
    def evidence(target_id: str, user_id: str = Depends(current_user)):
        with db.session() as session:
            get_target(session, target_id, user_id)
            return [serialize(row) for row in session.scalars(select(Evidence).where(Evidence.target_id == target_id))]

    @app.get("/api/matches")
    def matches(user_id: str = Depends(current_user)):
        with db.session() as session:
            owned = select(Target.id).where(Target.user_id == user_id)
            return [serialize(row) for row in session.scalars(select(Match).where(Match.target_id.in_(owned)).order_by(Match.first_seen_at.desc()))]

    @app.patch("/api/matches/{match_id}")
    def patch_match(match_id: str, data: MatchPatch, user_id: str = Depends(current_user)):
        with db.session.begin() as session:
            match = session.get(Match, match_id)
            if not match or session.get(Target, match.target_id).user_id != user_id:
                raise HTTPException(404, "Match not found")
            match.status = data.status
            match.snoozed_until = data.snoozed_until if data.status == "snoozed" else None
            return serialize(match)

    @app.get("/api/settings")
    def get_preferences(user_id: str = Depends(current_user)):
        with db.session.begin() as session:
            return preferences(session, user_id).model_dump()

    @app.put("/api/settings")
    def set_preferences(data: Preferences, user_id: str = Depends(current_user)):
        with db.session.begin() as session:
            preferences(session, user_id)
            session.get(Preference, user_id).data = data.model_dump()
            return data.model_dump()

    @app.get("/api/deliveries")
    def deliveries(user_id: str = Depends(current_user)):
        with db.session() as session:
            return [serialize(row) for row in session.scalars(select(Delivery).where(Delivery.user_id == user_id).order_by(Delivery.created_at.desc()).limit(500))]

    @app.post("/api/email/test")
    def test_email(user_id: str = Depends(current_user)):
        if not email_configured():
            raise HTTPException(422, "Configure EMAIL_FROM and the email transport's credentials first")
        with db.session.begin() as session:
            user = session.get(User, user_id)
            delivery = Delivery(id=uid(), user_id=user_id, dedupe_key=uid(), kind="test", recipient=user.email,
                                subject="Test email", plain_body=f"Your {NAME} email transport is ready.\nThis test contains no real job posting.")
            session.add(delivery)
            session.flush()
            delivery_id = delivery.id
        # Only the worker owns transport. Sending here would race the worker
        # and could dispatch unrelated pending alerts from a test-email request.
        return {"status": "pending", "delivery_id": delivery_id}

    @app.get("/api/tasks")
    def tasks(user_id: str = Depends(current_user)):
        with db.session() as session:
            owned = select(Target.id).where(Target.user_id == user_id)
            return [{key: value for key, value in serialize(row).items() if key not in {"payload", "result", "dedupe_key"}}
                    for row in session.scalars(select(Task).where(Task.target_id.in_(owned)).order_by(Task.created_at.desc()).limit(200))]

    @app.post("/api/demo/reset")
    def demo_reset(user_id: str = Depends(current_user)):
        if settings.mode != "demo":
            raise HTTPException(403, "Demo reset is unavailable in live mode")
        with db.session.begin() as session:
            reset_demo(session, settings, user_id)
        return {"status": "reset"}

    @app.post("/api/imports/preview")
    async def import_preview(file: UploadFile = File(...), mapping: str | None = Form(None), user_id: str = Depends(current_user)):
        from waymark.portability import MAX_BYTES, preview_import
        data = await file.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise HTTPException(413, "Import files must be at most 5 MB")
        try:
            parsed_mapping = json.loads(mapping) if mapping else None
            if parsed_mapping is not None and not isinstance(parsed_mapping, dict):
                raise ValueError("Column mapping must be a JSON object")
            result = preview_import(file.filename or "upload.csv", data, parsed_mapping)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        with db.session() as session:
            ids = set(session.scalars(select(Target.id).where(Target.user_id == user_id)))
            result["existing_ids"] = [str(row["id"]) for row in result["rows"] if row.get("id") in ids]
        return result

    @app.post("/api/imports/commit")
    def import_commit(data: ImportCommit, user_id: str = Depends(current_user)):
        created, updated, errors = 0, 0, []
        with db.session.begin() as session:
            for index, row in enumerate(data.rows):
                try:
                    with session.begin_nested():
                        if row.id and data.merge:
                            existing = session.get(Target, row.id)
                            # Another user's ID is treated as unknown and imported as new.
                            if existing and existing.user_id == user_id:
                                if row.version is None:
                                    raise HTTPException(409, "Merge updates require the exported row version")
                                changes = row.model_dump(mode="json", exclude={"id", "version"}, exclude_unset=True)
                                # Exported monitoring rows retain state only when their source remains verified.
                                edit_target(session, existing, changes, row.version, demo=settings.mode == "demo")
                                updated += 1
                                continue
                        values = row.model_copy(update={"monitoring_status": "draft"})
                        create_target(session, values, user_id, demo=settings.mode == "demo", preserve_history=True)
                        created += 1
                except (HTTPException, ValidationError) as exc:
                    errors.append({"row": index + 2, "message": str(exc.detail) if isinstance(exc, HTTPException) else str(exc)})
        return {"created": created, "updated": updated, "errors": errors}

    @app.get("/api/exports/targets")
    def export(format: str = "csv", user_id: str = Depends(current_user)):
        from waymark.portability import export_targets
        if format not in {"csv", "xlsx"}:
            raise HTTPException(422, "Export format must be csv or xlsx")
        with db.session() as session:
            owned = list(session.scalars(select(Target).where(Target.user_id == user_id)))
            rows = [target_dict(row) for row in owned]
            records = [serialize(row) for row in session.scalars(select(Evidence).where(Evidence.target_id.in_([t.id for t in owned])))]
        payload, mime, filename = export_targets(rows, records, format)
        return Response(payload, media_type=mime, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "API route not found")
        static_root = Path(settings.static_dir).resolve()
        requested, index = (static_root / path).resolve(), static_root / "index.html"
        if requested.is_relative_to(static_root) and requested.is_file() and requested != index:
            return FileResponse(requested)
        if index.is_file():
            # Link previews need absolute URLs, and only the server knows
            # this install's public origin.
            page = index.read_text(encoding="utf-8").replace("__APP_BASE_URL__", escape(settings.base_url.rstrip("/")))
            return HTMLResponse(page)
        return JSONResponse({"detail": "Frontend not built. Run the documented web build, then reload.", "api": "/docs"})

    return app


app = create_app()
