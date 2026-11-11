import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from threading import BoundedSemaphore
from urllib.parse import urlparse

from fastapi import HTTPException, Request, Response
from pwdlib import PasswordHash

from .database import connect

password_hash = PasswordHash.recommended()
_dummy_hash = password_hash.hash(secrets.token_urlsafe(32))
_hash_slots = BoundedSemaphore(2)
SESSION_SECONDS = 8 * 60 * 60


def origin():
    value = os.getenv("CRM_ORIGIN", "")
    parsed = urlparse(value)
    insecure = os.getenv("CRM_ALLOW_INSECURE_HTTP") == "1"
    if insecure:
        valid = parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost")
    else:
        valid = parsed.scheme == "https"
    if not valid or not parsed.netloc or parsed.path or parsed.query or parsed.fragment:
        raise HTTPException(503, "crm_origin_not_configured")
    return value


def secure_cookies():
    origin()
    return os.getenv("CRM_ALLOW_INSECURE_HTTP") != "1"


def cookie_name():
    return "__Host-jardines_session" if secure_cookies() else "jardines_session"


def require_origin(request: Request):
    if request.headers.get("origin") != origin():
        raise HTTPException(403, "invalid_origin")


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def session(request: Request):
    # Reject anonymous access before opening a database connection or reading configuration.
    token = request.cookies.get("__Host-jardines_session") or request.cookies.get(
        "jardines_session"
    )
    if not token or len(token) > 128:
        raise HTTPException(401, "authentication_required")
    token = request.cookies.get(cookie_name())
    if not token:
        raise HTTPException(401, "authentication_required")
    with connect() as db:
        record = db.execute(
            """UPDATE crm.sessions s SET last_seen = now() FROM crm.users u
               WHERE s.token_hash = %s AND s.user_id = u.id AND u.enabled
                 AND u.role = 'admin' AND s.expires_at > now()
                 AND s.last_seen > now() - interval '30 minutes'
               RETURNING u.id, u.username, u.role, s.csrf_token, s.token_hash""",
            (digest(token),),
        ).fetchone()
    if not record:
        raise HTTPException(401, "authentication_required")
    if request.method not in ("GET", "HEAD", "OPTIONS"):
        require_origin(request)
        if not hmac.compare_digest(
            request.headers.get("x-csrf-token", "").encode(), record["csrf_token"].encode()
        ):
            raise HTTPException(403, "invalid_csrf")
    return record


def authenticate(username, password):
    username = username.lower()
    with connect() as db:
        db.execute(
            "DELETE FROM crm.login_limits WHERE window_start < now() - interval '15 minutes'"
        )
        for key, maximum in (("global", 100), ("user:" + username, 5)):
            attempts = db.execute(
                """INSERT INTO crm.login_limits(key) VALUES (%s)
                   ON CONFLICT (key) DO UPDATE SET attempts = crm.login_limits.attempts + 1
                   RETURNING attempts""",
                (key,),
            ).fetchone()["attempts"]
            if attempts > maximum:
                # Commit the counter before reporting throttling; no password work is performed.
                db.commit()
                raise HTTPException(429, "login_throttled", headers={"Retry-After": "900"})
        user = db.execute("SELECT * FROM crm.users WHERE username = %s", (username,)).fetchone()
    if not _hash_slots.acquire(blocking=False):
        raise HTTPException(429, "login_busy", headers={"Retry-After": "3"})
    try:
        valid = password_hash.verify(password, user["password_hash"] if user else _dummy_hash)
    finally:
        _hash_slots.release()
    if not user or not valid or not user["enabled"] or user["role"] != "admin":
        raise HTTPException(401, "invalid_credentials")
    with connect() as db:
        db.execute("DELETE FROM crm.login_limits WHERE key = %s", ("user:" + username,))
    return user


def create_session(user, request: Request, response: Response):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with connect() as db:
        db.execute("DELETE FROM crm.sessions WHERE expires_at < now()")
        previous = request.cookies.get(cookie_name())
        if previous:
            db.execute("DELETE FROM crm.sessions WHERE token_hash = %s", (digest(previous),))
        db.execute(
            "INSERT INTO crm.sessions(token_hash, user_id, csrf_token, expires_at) VALUES (%s,%s,%s,%s)",
            (
                digest(token),
                user["id"],
                csrf,
                datetime.now(UTC) + timedelta(seconds=SESSION_SECONDS),
            ),
        )
    response.set_cookie(
        cookie_name(),
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=secure_cookies(),
        samesite="lax",
        path="/",
    )
    return {"user": {"username": user["username"], "role": user["role"]}, "csrf_token": csrf}
