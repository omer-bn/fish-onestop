"""Google OAuth sign-in linked to the same users table.

The browser is sent to Google and returns to /auth/google/callback.
The client secret stays on the server. A missing configuration disables the
button; username and password login keep working.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import urllib.error
import urllib.parse
import urllib.request
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from psycopg.errors import UniqueViolation

from app.auth import fetch_user, set_session_cookie, start_session
from app.db import get_conn

log = logging.getLogger("fish.auth")

router = APIRouter(tags=["auth"])

STATE_COOKIE = "fish_oauth_state"
NONCE_COOKIE = "fish_oauth_nonce"
GOOGLE_AUTH = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN = "https://oauth2.googleapis.com/token"
SCOPES = "openid email profile"
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")


class GoogleLinkError(Exception):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


def slug_username(email: str) -> str:
    local = email.split("@", 1)[0].lower()
    cleaned = re.sub(r"[^a-z0-9._-]", "", local).strip("._-")
    if not cleaned or not cleaned[0].isalnum():
        cleaned = "g" + cleaned
    if len(cleaned) < 3:
        cleaned = (cleaned + "user")[:32]
    cleaned = cleaned[:32]
    if not USERNAME_RE.fullmatch(cleaned):
        cleaned = ("user" + re.sub(r"[^a-z0-9]", "", cleaned) + "user")[:32]
    return cleaned


def username_candidates(email: str):
    base = slug_username(email)
    yield base
    for number in range(2, 80):
        suffix = f"-{number}"
        trimmed = base[: 32 - len(suffix)].rstrip(".-")
        if len(trimmed) < 2:
            trimmed = "user"
        candidate = trimmed + suffix
        if USERNAME_RE.fullmatch(candidate):
            yield candidate


def authorization_url(settings: Any, state: str, nonce: str) -> str:
    query = urllib.parse.urlencode(
        {
            "client_id": settings.google_client_id,
            "redirect_uri": settings.google_redirect_uri,
            "response_type": "code",
            "scope": SCOPES,
            "state": state,
            "nonce": nonce,
            "prompt": "select_account",
            "access_type": "online",
        }
    )
    return f"{GOOGLE_AUTH}?{query}"


def exchange_and_verify(settings: Any, code: str, nonce: str) -> dict[str, str]:
    body = urllib.parse.urlencode(
        {
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        }
    ).encode()
    request = urllib.request.Request(GOOGLE_TOKEN, data=body, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        log.warning("Google token exchange failed: %s", exc.__class__.__name__)
        raise GoogleLinkError("google") from exc
    raw_token = payload.get("id_token")
    if not raw_token:
        raise GoogleLinkError("google")
    try:
        from google.auth.transport import requests as google_requests
        from google.oauth2 import id_token

        claims = id_token.verify_oauth2_token(
            raw_token,
            google_requests.Request(),
            settings.google_client_id,
        )
    except Exception as exc:
        log.warning("Google id token rejected: %s", exc.__class__.__name__)
        raise GoogleLinkError("google") from exc
    claim_nonce = str(claims.get("nonce") or "")
    if not secrets.compare_digest(claim_nonce, nonce):
        raise GoogleLinkError("state")
    if claims.get("email_verified") is not True:
        raise GoogleLinkError("unverified")
    email = str(claims.get("email") or "").strip()
    sub = str(claims.get("sub") or "").strip()
    if not email or not sub or len(sub) > 255:
        raise GoogleLinkError("google")
    name = str(claims.get("name") or "").strip()[:80]
    return {"sub": sub, "email": email, "name": name}


def _by_sub(conn: psycopg.Connection, sub: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id, google_sub, display_name FROM users WHERE google_sub = %s",
        (sub,),
    ).fetchone()


def _by_email(conn: psycopg.Connection, email: str) -> dict[str, Any] | None:
    return conn.execute(
        "SELECT id, google_sub, display_name FROM users WHERE email = %s",
        (email,),
    ).fetchone()


def _touch(conn: psycopg.Connection, user_id: Any, sub: str | None, name: str, display_name: str) -> dict[str, Any]:
    if sub:
        conn.execute(
            """
            UPDATE users
            SET google_sub = COALESCE(google_sub, %s),
                display_name = CASE WHEN btrim(display_name) = '' THEN %s ELSE display_name END,
                last_login_at = now()
            WHERE id = %s
            """,
            (sub, name or display_name, user_id),
        )
    else:
        conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))
    return fetch_user(conn, user_id)


def link_google_user(conn: psycopg.Connection, *, sub: str, email: str, name: str) -> dict[str, Any]:
    """Find or create the user for a verified Google identity.

    Matching order: google_sub, then the same email. An email that already
    belongs to a different Google subject is left untouched.
    """
    existing = _by_sub(conn, sub)
    if existing:
        return _touch(conn, existing["id"], None, name, existing["display_name"] or "")
    by_email = _by_email(conn, email)
    if by_email:
        current = by_email["google_sub"]
        if current and current != sub:
            raise GoogleLinkError("email")
        return _touch(conn, by_email["id"], sub, name, by_email["display_name"] or "")
    display = (name or email.split("@", 1)[0])[:80]
    for candidate in username_candidates(email):
        try:
            with conn.transaction():
                created = conn.execute(
                    """
                    INSERT INTO users (
                        username, email, google_sub, display_name, password_hash, role, last_login_at
                    )
                    VALUES (%s, %s, %s, %s, NULL, 'member', now())
                    RETURNING id
                    """,
                    (candidate, email, sub, display),
                ).fetchone()
            return fetch_user(conn, created["id"])
        except UniqueViolation as exc:
            constraint = exc.diag.constraint_name or ""
            if constraint == "users_username_key":
                continue
            if constraint == "users_email_key":
                again = _by_email(conn, email)
                if again and (not again["google_sub"] or again["google_sub"] == sub):
                    return _touch(conn, again["id"], sub, name, again["display_name"] or "")
            raise GoogleLinkError("email") from exc
    raise GoogleLinkError("username")


def _cookie_kwargs(settings: Any, max_age: int) -> dict[str, Any]:
    return {
        "max_age": max_age,
        "httponly": True,
        "secure": settings.cookie_secure,
        "samesite": "lax",
        "path": "/",
    }


def _clear_oauth(response: RedirectResponse, settings: Any) -> None:
    blank = _cookie_kwargs(settings, 0)
    response.delete_cookie(STATE_COOKIE, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax")
    response.delete_cookie(NONCE_COOKIE, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax")
    return blank


def _fail(settings: Any, code: str) -> RedirectResponse:
    response = RedirectResponse(f"/?auth_error={code}", status_code=302)
    _clear_oauth(response, settings)
    return response


@router.get("/auth/google")
def google_start(request: Request) -> RedirectResponse:
    settings = request.app.state.settings
    if not settings.google_enabled:
        raise HTTPException(status_code=503, detail="Google sign-in is not configured")
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)
    response = RedirectResponse(authorization_url(settings, state, nonce), status_code=302)
    response.set_cookie(STATE_COOKIE, state, **_cookie_kwargs(settings, 600))
    response.set_cookie(NONCE_COOKIE, nonce, **_cookie_kwargs(settings, 600))
    return response


@router.get("/auth/google/callback")
def google_callback(
    request: Request,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    conn: psycopg.Connection = Depends(get_conn),
    fish_oauth_state: Annotated[str | None, Cookie(alias=STATE_COOKIE)] = None,
    fish_oauth_nonce: Annotated[str | None, Cookie(alias=NONCE_COOKIE)] = None,
) -> RedirectResponse:
    settings = request.app.state.settings
    if not settings.google_enabled:
        return _fail(settings, "config")
    if error:
        return _fail(settings, "cancelled" if error == "access_denied" else "google")
    if not code or not state or not fish_oauth_state or not fish_oauth_nonce:
        return _fail(settings, "state")
    try:
        state_ok = secrets.compare_digest(state, fish_oauth_state)
    except ValueError:
        state_ok = False
    if not state_ok:
        return _fail(settings, "state")
    try:
        identity = exchange_and_verify(settings, code, fish_oauth_nonce)
        user = link_google_user(conn, sub=identity["sub"], email=identity["email"], name=identity["name"])
        token = start_session(conn, user["id"], settings)
        conn.commit()
    except GoogleLinkError as exc:
        return _fail(settings, exc.code)
    response = RedirectResponse("/", status_code=302)
    set_session_cookie(response, token, settings)
    _clear_oauth(response, settings)
    return response
