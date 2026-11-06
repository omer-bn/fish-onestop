"""Fish Onestop API and phone-first web app."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import psycopg
from fastapi import Depends, FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.auth import router as auth_router
from app.catalog import router as catalog_router
from app.config import WEB_ROOT, load_settings
from app.db import get_conn, make_pool
from app.google_auth import router as google_router
from app.reports import router as reports_router

log = logging.getLogger("fish")
logging.basicConfig(level=logging.INFO)

NO_CACHE = {"Cache-Control": "no-cache"}


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = load_settings()
    settings.media_root.mkdir(parents=True, exist_ok=True)
    pool = make_pool(settings.database_url)
    pool.open()
    try:
        pool.wait(timeout=15)
    except Exception as exc:
        pool.close()
        raise RuntimeError(
            "Postgres is not reachable. Check DATABASE_URL and run: docker compose up -d"
        ) from exc
    app.state.settings = settings
    app.state.pool = pool
    log.info("google sign-in %s", "enabled" if settings.google_enabled else "disabled")
    yield
    pool.close()


app = FastAPI(title="Fish Onestop", version="0.1.0", lifespan=lifespan)
app.include_router(auth_router)
app.include_router(google_router)
app.include_router(catalog_router)
app.include_router(reports_router)


@app.get("/health")
def health(conn: psycopg.Connection = Depends(get_conn)) -> dict[str, bool]:
    conn.execute("SELECT 1")
    return {"ok": True}


def _web_file(request: Request, name: str) -> FileResponse:
    path = request.app.state.settings.web_root / name
    if not path.is_file():
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Not found")
    media = "application/javascript" if name.endswith(".js") else None
    if name.endswith(".webmanifest"):
        media = "application/manifest+json"
    return FileResponse(path, media_type=media, headers=NO_CACHE)


@app.get("/")
def index(request: Request) -> FileResponse:
    return _web_file(request, "index.html")


@app.get("/sw.js")
def service_worker(request: Request) -> FileResponse:
    return _web_file(request, "sw.js")


@app.get("/manifest.webmanifest")
def manifest(request: Request) -> FileResponse:
    return _web_file(request, "manifest.webmanifest")


_assets = WEB_ROOT / "assets"
_assets.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=_assets), name="assets")
