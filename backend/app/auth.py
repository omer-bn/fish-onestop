"""Username/password accounts and HttpOnly session cookies."""

from __future__ import annotations

import hashlib
import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

import psycopg
from argon2 import PasswordHasher, Type
from argon2.exceptions import VerificationError
from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response
from psycopg.errors import UniqueViolation
from pydantic import BaseModel, Field, field_validator

from app.db import dump, get_conn

COOKIE_NAME = "fish_session"
USERNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,31}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65536,
    parallelism=4,
    hash_len=32,
    salt_len=16,
    type=Type.ID,
)
_DUMMY_HASH: str | None = None

PUBLIC_COLS = """
u.id, u.username::text AS username, u.email::text AS email, u.display_name, u.role,
u.created_at, u.last_login_at,
(u.password_hash IS NOT NULL) AS has_password,
(u.google_sub IS NOT NULL) AS has_google
"""

router = APIRouter(tags=["auth"])


def hash_password(password: str) -> str:
    hashed = _HASHER.hash(password)
    if not hashed.startswith("$argon2id$"):
        raise RuntimeError("password hasher is not Argon2id")
    return hashed


def dummy_hash() -> str:
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = hash_password("not-a-real-password")
    return _DUMMY_HASH


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bool(_HASHER.verify(password_hash, password))
    except VerificationError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_username(value: str) -> str:
    value = value.strip()
    if not USERNAME_RE.fullmatch(value):
        raise ValueError("username must be 3-32 characters: letters, digits, dot, underscore, hyphen")
    return value


def normalize_email(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    if len(value) > 254 or not EMAIL_RE.fullmatch(value):
        raise ValueError("invalid email")
    return value


class RegisterIn(BaseModel):
    username: str
    password: str = Field(min_length=8, max_length=128)
    email: str | None = None
    display_name: str | None = None

    @field_validator("username")
    @classmethod
    def _username(cls, value: str) -> str:
        return normalize_username(value)

    @field_validator("email")
    @classmethod
    def _email(cls, value: str | None) -> str | None:
        return normalize_email(value)

    @field_validator("display_name")
    @classmethod
    def _display(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if len(value) > 80:
            raise ValueError("display_name is too long")
        return value or None


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


def fetch_user(conn: psycopg.Connection, user_id: Any) -> dict[str, Any]:
    row = conn.execute(f"SELECT {PUBLIC_COLS} FROM users u WHERE u.id = %s", (user_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return row


def same_user(row_user: Any, user: dict[str, Any]) -> bool:
    return row_user is not None and str(row_user) == str(user["id"])


def set_session_cookie(response: Response, token: str, settings: Any) -> None:
    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=settings.session_days * 86400,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, settings: Any) -> None:
    response.delete_cookie(
        key=COOKIE_NAME,
        path="/",
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
    )


def start_session(conn: psycopg.Connection, user_id: Any, settings: Any) -> str:
    conn.execute("DELETE FROM sessions WHERE expires_at <= now()")
    conn.execute("UPDATE users SET last_login_at = now() WHERE id = %s", (user_id,))
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=settings.session_days)
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (%s, %s, %s)",
        (hash_token(token), user_id, expires),
    )
    return token


def require_user(
    request: Request,
    conn: psycopg.Connection = Depends(get_conn),
    fish_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> dict[str, Any]:
    if not fish_session:
        raise HTTPException(status_code=401, detail="Not authenticated")
    row = conn.execute(
        f"""
        SELECT {PUBLIC_COLS}
        FROM sessions s
        JOIN users u ON u.id = s.user_id
        WHERE s.token_hash = %s AND s.expires_at > now()
        """,
        (hash_token(fish_session),),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return row


def _settings(request: Request) -> Any:
    return request.app.state.settings


@router.get("/auth/providers")
def providers(request: Request) -> dict[str, bool]:
    settings = _settings(request)
    return {"password": True, "google": bool(settings.google_enabled)}


@router.post("/auth/register", status_code=201)
def register(
    body: RegisterIn,
    request: Request,
    response: Response,
    conn: psycopg.Connection = Depends(get_conn),
) -> dict[str, Any]:
    settings = _settings(request)
    try:
        created = conn.execute(
            """
            INSERT INTO users (username, email, display_name, password_hash, role)
            VALUES (%s, %s, %s, %s, 'member')
            RETURNING id
            """,
            (
                body.username,
                body.email,
                body.display_name or body.username,
                hash_password(body.password),
            ),
        ).fetchone()
    except UniqueViolation as exc:
        constraint = exc.diag.constraint_name or ""
        if constraint == "users_email_key":
            raise HTTPException(status_code=409, detail="Email already registered") from exc
        raise HTTPException(status_code=409, detail="Username already registered") from exc
    token = start_session(conn, created["id"], settings)
    user = fetch_user(conn, created["id"])
    conn.commit()
    set_session_cookie(response, token, settings)
    return dump(user)


@router.post("/auth/login")
def login(
    body: LoginIn,
    request: Request,
    response: Response,
    conn: psycopg.Connection = Depends(get_conn),
) -> dict[str, Any]:
    settings = _settings(request)
    username = body.username.strip()
    row = conn.execute(
        "SELECT id, password_hash FROM users WHERE username = %s",
        (username,),
    ).fetchone()
    password_hash = row["password_hash"] if row else None
    if not password_hash:
        verify_password(body.password, dummy_hash())
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if not verify_password(body.password, password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")
    if _HASHER.check_needs_rehash(password_hash):
        conn.execute(
            "UPDATE users SET password_hash = %s WHERE id = %s",
            (hash_password(body.password), row["id"]),
        )
    token = start_session(conn, row["id"], settings)
    user = fetch_user(conn, row["id"])
    conn.commit()
    set_session_cookie(response, token, settings)
    return dump(user)


@router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    conn: psycopg.Connection = Depends(get_conn),
    fish_session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
) -> dict[str, bool]:
    if fish_session:
        conn.execute("DELETE FROM sessions WHERE token_hash = %s", (hash_token(fish_session),))
        conn.commit()
    clear_session_cookie(response, _settings(request))
    return {"ok": True}


@router.get("/auth/me")
def me(user: dict[str, Any] = Depends(require_user)) -> dict[str, Any]:
    return dump(user)
