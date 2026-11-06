"""Environment configuration. Secrets stay in the environment, never in git."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WEB_ROOT = Path(__file__).resolve().parents[1] / "web"


def load_dotenv() -> None:
    """Load the first .env values that are not already set in the process."""
    for path in (Path.cwd() / ".env", REPO_ROOT / ".env"):
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
                value = value[1:-1]
            if key:
                os.environ.setdefault(key, value)
        return


def _flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    database_url: str
    cookie_secure: bool
    session_days: int
    media_root: Path
    repo_root: Path
    web_root: Path
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str

    @property
    def google_enabled(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret and self.google_redirect_uri)


def load_settings() -> Settings:
    load_dotenv()
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise SystemExit(
            "DATABASE_URL is required. For local docker compose:\n"
            "  export DATABASE_URL=postgresql://fish:fish@localhost:5432/fish_onestop"
        )
    if not url.startswith(("postgres://", "postgresql://")):
        raise SystemExit("DATABASE_URL must start with postgres:// or postgresql://")
    media = os.environ.get("MEDIA_ROOT", "").strip()
    base = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    redirect = os.environ.get("GOOGLE_REDIRECT_URI", "").strip() or f"{base}/auth/google/callback"
    try:
        days = int(os.environ.get("SESSION_DAYS", "14") or "14")
    except ValueError:
        days = 14
    return Settings(
        database_url=url,
        cookie_secure=_flag("COOKIE_SECURE"),
        session_days=max(1, min(days, 90)),
        media_root=Path(media) if media else REPO_ROOT / "var" / "media",
        repo_root=REPO_ROOT,
        web_root=WEB_ROOT,
        google_client_id=os.environ.get("GOOGLE_CLIENT_ID", "").strip(),
        google_client_secret=os.environ.get("GOOGLE_CLIENT_SECRET", "").strip(),
        google_redirect_uri=redirect,
    )
