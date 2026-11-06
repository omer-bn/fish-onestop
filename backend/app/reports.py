"""Own dives, sightings, photos, and the personal map."""

from __future__ import annotations

import re
import uuid
from datetime import date, time
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, field_validator

from app.auth import require_user, same_user
from app.db import dump, get_conn
from app.files import MAX_BYTES, resolve_key, save_image, unlink_key

router = APIRouter(tags=["reports"])

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_KINDS = {"", "sighting", "catch"}


def _check_id(value: str, label: str) -> str:
    value = (value or "").strip()
    if not _ID_RE.fullmatch(value):
        raise HTTPException(status_code=422, detail=f"Invalid {label}")
    return value


def _optional_int(value: str, label: str) -> int | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = int(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{label} must be a whole number") from exc
    if number < 0 or number > 1_000_000:
        raise HTTPException(status_code=422, detail=f"{label} is out of range")
    return number


def _optional_float(value: str, label: str) -> float | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        number = float(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{label} must be a number") from exc
    if number < 0 or number > 1000:
        raise HTTPException(status_code=422, detail=f"{label} is out of range")
    return number


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Date must be YYYY-MM-DD") from exc


def _parse_time(value: str) -> time | None:
    value = (value or "").strip()
    if not value:
        return None
    try:
        return time.fromisoformat(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Time must be HH:MM") from exc


def _clean_text(value: str, limit: int) -> str:
    value = (value or "").strip()
    if len(value) > limit:
        raise HTTPException(status_code=422, detail="Text is too long")
    return value


def _form_bool(value: str) -> bool:
    return (value or "").strip().lower() in {"1", "true", "yes", "on"}


def _observer(user: dict[str, Any]) -> str:
    return (user.get("display_name") or user["username"] or "").strip() or user["username"]


def _allocate(conn: psycopg.Connection, table: str) -> str:
    prefix = {"dives": "dive", "sightings": "obs"}[table]
    for _ in range(5):
        candidate = f"{prefix}-{uuid.uuid4().hex[:12]}"
        if conn.execute(f"SELECT 1 FROM {table} WHERE id = %s", (candidate,)).fetchone() is None:
            return candidate
    raise HTTPException(status_code=500, detail="Could not allocate id")


def _species(conn: psycopg.Connection, species_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT id, sea FROM species WHERE id = %s", (_check_id(species_id, "species"),)).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail="Unknown species")
    return row


def _site(conn: psycopg.Connection, site_id: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT id, sea, lat, lng, hebrew, english FROM sites WHERE id = %s",
        (_check_id(site_id, "site"),),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=400, detail="Unknown site")
    return row


def _owned_dive(conn: psycopg.Connection, dive_id: str, user: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM dives WHERE id = %s", (_check_id(dive_id, "dive"),)).fetchone()
    if row is None or not same_user(row["user_id"], user):
        raise HTTPException(status_code=400, detail="Unknown dive")
    return row


def _owned_sighting(conn: psycopg.Connection, sighting_id: str, user: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM sightings WHERE id = %s", (_check_id(sighting_id, "sighting"),)).fetchone()
    if row is None or not same_user(row["user_id"], user):
        raise HTTPException(status_code=404, detail="Sighting not found")
    return row


def _media_view(row: dict[str, Any]) -> dict[str, Any]:
    item = dump(row)
    item["content_url"] = f"/media/{item['id']}/content"
    return item


def _refresh_count(conn: psycopg.Connection, dive_id: str | None) -> None:
    if not dive_id:
        return
    conn.execute(
        """
        UPDATE dives
        SET species_count = (
            SELECT COUNT(DISTINCT species_id) FROM sightings WHERE dive_id = %s
        )
        WHERE id = %s
        """,
        (dive_id, dive_id),
    )


def _insert_sighting(
    conn: psycopg.Connection,
    *,
    user: dict[str, Any],
    species_id: str,
    site: dict[str, Any] | None,
    dive_id: str | None,
    observed_on: date,
    count: int | None,
    depth_m: float | None,
    method: str,
    kind: str,
    notes: str,
    sea: str | None,
) -> str:
    sighting_id = _allocate(conn, "sightings")
    conn.execute(
        """
        INSERT INTO sightings (
            id, user_id, dive_id, species_id, site_id, observed_on, count, depth_m,
            lat, lng, sea, method, kind, notes, observer, is_demo
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE)
        """,
        (
            sighting_id,
            user["id"],
            dive_id,
            species_id,
            site["id"] if site else None,
            observed_on,
            count,
            depth_m,
            site["lat"] if site else None,
            site["lng"] if site else None,
            sea,
            method,
            kind,
            notes,
            _observer(user),
        ),
    )
    return sighting_id


def _attach_photo(
    conn: psycopg.Connection,
    request: Request,
    user: dict[str, Any],
    *,
    sighting_id: str | None,
    dive_id: str | None,
    upload: UploadFile | None,
) -> dict[str, Any] | None:
    if upload is None or not (upload.filename or "").strip():
        return None
    data = upload.file.read(MAX_BYTES + 1)
    if not data:
        return None
    root = request.app.state.settings.media_root
    key, kind = save_image(root, data)
    try:
        row = conn.execute(
            """
            INSERT INTO media (sighting_id, dive_id, user_id, storage_key, content_type, byte_size)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id, sighting_id, dive_id, content_type, byte_size, caption, created_at
            """,
            (sighting_id, dive_id, user["id"], key, kind, len(data)),
        ).fetchone()
    except Exception:
        unlink_key(root, key)
        raise
    return _media_view(row)


def _sighting_detail(conn: psycopg.Connection, sighting_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT s.id, s.user_id, s.dive_id, s.species_id, s.site_id, s.observed_on, s.count,
               s.depth_m, s.lat, s.lng, s.sea, s.method, s.kind, s.notes, s.observer,
               s.is_demo, s.created_at,
               sp.latin AS species_latin, sp.hebrew AS species_hebrew, sp.english AS species_english,
               si.hebrew AS site_hebrew, si.english AS site_english
        FROM sightings s
        JOIN species sp ON sp.id = s.species_id
        LEFT JOIN sites si ON si.id = s.site_id
        WHERE s.id = %s
        """,
        (sighting_id,),
    ).fetchone()
    item = dump(row)
    media = conn.execute(
        """
        SELECT id, sighting_id, dive_id, content_type, byte_size, caption, created_at
        FROM media WHERE sighting_id = %s ORDER BY created_at
        """,
        (sighting_id,),
    ).fetchall()
    item["media"] = [_media_view(row) for row in media]
    return item


def _dive_detail(conn: psycopg.Connection, dive_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT d.id, d.user_id, d.site_id, d.sea, d.lat, d.lng, d.dive_date, d.start_time,
               d.duration_min, d.max_depth_m, d.observer, d.method, d.kind, d.notes,
               d.species_count, d.is_demo, d.created_at,
               si.hebrew AS site_hebrew, si.english AS site_english
        FROM dives d
        LEFT JOIN sites si ON si.id = d.site_id
        WHERE d.id = %s
        """,
        (dive_id,),
    ).fetchone()
    return dump(row)


class SightingPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    species_id: str | None = None
    site_id: str | None = None
    dive_id: str | None = None
    observed_on: date | None = None
    count: int | None = None
    depth_m: float | None = None
    method: str | None = None
    kind: str | None = None
    notes: str | None = None

    @field_validator("count")
    @classmethod
    def _count(cls, value: int | None) -> int | None:
        if value is not None and (value < 0 or value > 1_000_000):
            raise ValueError("count is out of range")
        return value

    @field_validator("depth_m")
    @classmethod
    def _depth(cls, value: float | None) -> float | None:
        if value is not None and (value < 0 or value > 1000):
            raise ValueError("depth is out of range")
        return value


class DivePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    site_id: str | None = None
    dive_date: date | None = None
    start_time: time | None = None
    duration_min: int | None = None
    max_depth_m: float | None = None
    method: str | None = None
    kind: str | None = None
    notes: str | None = None

    @field_validator("duration_min")
    @classmethod
    def _duration(cls, value: int | None) -> int | None:
        if value is not None and (value < 0 or value > 10_000):
            raise ValueError("duration is out of range")
        return value


@router.get("/me/observations")
def my_observations(
    user: dict[str, Any] = Depends(require_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> dict[str, Any]:
    dives = conn.execute(
        """
        SELECT d.id, d.user_id, d.site_id, d.sea, d.lat, d.lng, d.dive_date, d.start_time,
               d.duration_min, d.max_depth_m, d.observer, d.method, d.kind, d.notes,
               d.species_count, d.is_demo, d.created_at,
               si.hebrew AS site_hebrew, si.english AS site_english
        FROM dives d
        LEFT JOIN sites si ON si.id = d.site_id
        WHERE d.user_id = %s
        ORDER BY d.dive_date DESC, d.created_at DESC
        """,
        (user["id"],),
    ).fetchall()
    sightings = conn.execute(
        """
        SELECT s.id, s.user_id, s.dive_id, s.species_id, s.site_id, s.observed_on, s.count,
               s.depth_m, s.lat, s.lng, s.sea, s.method, s.kind, s.notes, s.observer,
               s.is_demo, s.created_at,
               sp.latin AS species_latin, sp.hebrew AS species_hebrew, sp.english AS species_english,
               si.hebrew AS site_hebrew, si.english AS site_english
        FROM sightings s
        JOIN species sp ON sp.id = s.species_id
        LEFT JOIN sites si ON si.id = s.site_id
        WHERE s.user_id = %s
        ORDER BY s.observed_on DESC, s.created_at DESC
        """,
        (user["id"],),
    ).fetchall()
    sighting_ids = [row["id"] for row in sightings]
    dive_ids = [row["id"] for row in dives]
    media: list[dict[str, Any]] = []
    if sighting_ids or dive_ids:
        media = conn.execute(
            """
            SELECT id, sighting_id, dive_id, content_type, byte_size, caption, created_at
            FROM media
            WHERE sighting_id = ANY(%s) OR dive_id = ANY(%s)
            ORDER BY created_at
            """,
            (sighting_ids or [""], dive_ids or [""]),
        ).fetchall()
    by_sighting: dict[str, list] = {}
    by_dive: dict[str, list] = {}
    for row in media:
        view = _media_view(row)
        if row["sighting_id"]:
            by_sighting.setdefault(row["sighting_id"], []).append(view)
        elif row["dive_id"]:
            by_dive.setdefault(row["dive_id"], []).append(view)
    dive_items = []
    for row in dives:
        item = dump(row)
        item["media"] = by_dive.get(row["id"], [])
        dive_items.append(item)
    sighting_items = []
    for row in sightings:
        item = dump(row)
        item["media"] = by_sighting.get(row["id"], [])
        sighting_items.append(item)
    return {"dives": dive_items, "sightings": sighting_items}


@router.get("/me/map")
def my_map(
    user: dict[str, Any] = Depends(require_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> dict[str, Any]:
    sites = conn.execute(
        """
        SELECT id, hebrew, english, sea, lat, lng
        FROM sites
        WHERE id IN (
            SELECT site_id FROM sightings WHERE user_id = %s AND site_id IS NOT NULL
            UNION
            SELECT site_id FROM dives WHERE user_id = %s AND site_id IS NOT NULL
        )
        ORDER BY english
        """,
        (user["id"], user["id"]),
    ).fetchall()
    species_rows = conn.execute(
        """
        SELECT s.site_id, sp.id, sp.latin, sp.hebrew, sp.english,
               SUM(COALESCE(s.count, 1)) AS count_sum,
               MAX(s.observed_on) AS last_seen,
               COUNT(*) AS reports
        FROM sightings s
        JOIN species sp ON sp.id = s.species_id
        WHERE s.user_id = %s AND s.site_id IS NOT NULL
        GROUP BY s.site_id, sp.id
        ORDER BY sp.latin
        """,
        (user["id"],),
    ).fetchall()
    grouped: dict[str, list] = {}
    seen: dict[str, dict[str, Any]] = {}
    for row in species_rows:
        item = dump(row)
        site_id = item.pop("site_id")
        grouped.setdefault(site_id, []).append(item)
        seen[row["id"]] = item
    site_items = []
    for row in sites:
        item = dump(row)
        species = grouped.get(row["id"], [])
        item["species"] = species
        item["sighting_count"] = sum(int(entry["reports"]) for entry in species)
        site_items.append(item)
    totals = conn.execute(
        """
        SELECT
            (SELECT COUNT(*) FROM sightings WHERE user_id = %s) AS sightings,
            (SELECT COUNT(*) FROM dives WHERE user_id = %s) AS dives
        """,
        (user["id"], user["id"]),
    ).fetchone()
    return {
        "sites": site_items,
        "species_count": len(seen),
        "sighting_count": totals["sightings"],
        "dive_count": totals["dives"],
    }


@router.post("/me/reports", status_code=201)
def create_report(
    request: Request,
    species_id: str = Form(...),
    observed_on: str = Form(...),
    site_id: str = Form(""),
    dive_id: str = Form(""),
    count: str = Form(""),
    depth_m: str = Form(""),
    method: str = Form(""),
    kind: str = Form(""),
    notes: str = Form(""),
    log_dive: str = Form(""),
    start_time: str = Form(""),
    duration_min: str = Form(""),
    max_depth_m: str = Form(""),
    dive_notes: str = Form(""),
    photo: UploadFile | None = File(None),
    user: dict[str, Any] = Depends(require_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> dict[str, Any]:
    species = _species(conn, species_id)
    when = _parse_date(observed_on)
    method_text = _clean_text(method, 40)
    kind_text = _clean_text(kind, 40)
    if kind_text not in _KINDS:
        raise HTTPException(status_code=422, detail="kind must be sighting or catch")
    notes_text = _clean_text(notes, 4000)
    count_n = _optional_int(count, "count")
    depth_n = _optional_float(depth_m, "depth")
    dive = None
    site = None
    new_dive_id = None
    if dive_id.strip():
        dive = _owned_dive(conn, dive_id, user)
        if site_id.strip() and site_id.strip() != dive["site_id"]:
            raise HTTPException(status_code=400, detail="site does not match the dive")
        site = _site(conn, dive["site_id"]) if dive["site_id"] else None
        new_dive_id = dive["id"]
    else:
        if not site_id.strip():
            raise HTTPException(status_code=422, detail="Choose a site")
        site = _site(conn, site_id)
        if _form_bool(log_dive):
            new_dive_id = _allocate(conn, "dives")
            conn.execute(
                """
                INSERT INTO dives (
                    id, user_id, site_id, sea, lat, lng, dive_date, start_time,
                    duration_min, max_depth_m, observer, method, kind, notes, species_count, is_demo
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 0, FALSE)
                """,
                (
                    new_dive_id,
                    user["id"],
                    site["id"],
                    site["sea"],
                    site["lat"],
                    site["lng"],
                    when,
                    _parse_time(start_time),
                    _optional_int(duration_min, "duration"),
                    _optional_float(max_depth_m, "max depth"),
                    _observer(user),
                    method_text,
                    kind_text,
                    _clean_text(dive_notes, 4000) or notes_text,
                ),
            )
    sea = (site or {}).get("sea") or species["sea"]
    sighting_id = _insert_sighting(
        conn,
        user=user,
        species_id=species["id"],
        site=site,
        dive_id=new_dive_id,
        observed_on=when,
        count=count_n,
        depth_m=depth_n,
        method=method_text,
        kind=kind_text,
        notes=notes_text,
        sea=sea,
    )
    _refresh_count(conn, new_dive_id)
    media = _attach_photo(conn, request, user, sighting_id=sighting_id, dive_id=None, upload=photo)
    conn.commit()
    payload = {"sighting": _sighting_detail(conn, sighting_id), "dive": None}
    if media and media["id"] not in {item["id"] for item in payload["sighting"]["media"]}:
        payload["sighting"]["media"].append(media)
    if new_dive_id:
        payload["dive"] = _dive_detail(conn, new_dive_id)
    return payload


@router.patch("/sightings/{sighting_id}")
def update_sighting(
    sighting_id: str,
    body: SightingPatch,
    user: dict[str, Any] = Depends(require_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> dict[str, Any]:
    current = _owned_sighting(conn, sighting_id, user)
    fields = body.model_fields_set
    species_id = current["species_id"]
    if "species_id" in fields and body.species_id:
        species_id = _species(conn, body.species_id)["id"]
    site = None
    site_id = current["site_id"]
    if "site_id" in fields and body.site_id:
        site = _site(conn, body.site_id)
        site_id = site["id"]
    dive_id = current["dive_id"]
    if "dive_id" in fields:
        if body.dive_id:
            dive = _owned_dive(conn, body.dive_id, user)
            if site_id and dive["site_id"] and site_id != dive["site_id"]:
                raise HTTPException(status_code=400, detail="site does not match the dive")
            dive_id = dive["id"]
            if site is None and dive["site_id"]:
                site = _site(conn, dive["site_id"])
                site_id = site["id"]
        else:
            dive_id = None
    if "kind" in fields and (body.kind or "") not in _KINDS:
        raise HTTPException(status_code=422, detail="kind must be sighting or catch")
    method = _clean_text(body.method, 40) if "method" in fields and body.method is not None else current["method"]
    notes = _clean_text(body.notes, 4000) if "notes" in fields and body.notes is not None else current["notes"]
    kind = body.kind if "kind" in fields and body.kind is not None else current["kind"]
    observed = body.observed_on if "observed_on" in fields and body.observed_on else current["observed_on"]
    count = body.count if "count" in fields else current["count"]
    depth = body.depth_m if "depth_m" in fields else current["depth_m"]
    sea = site["sea"] if site else current["sea"]
    lat = site["lat"] if site else current["lat"]
    lng = site["lng"] if site else current["lng"]
    conn.execute(
        """
        UPDATE sightings
        SET species_id = %s, site_id = %s, dive_id = %s, observed_on = %s, count = %s,
            depth_m = %s, lat = %s, lng = %s, sea = %s, method = %s, kind = %s, notes = %s
        WHERE id = %s AND user_id = %s
        """,
        (
            species_id,
            site_id,
            dive_id,
            observed,
            count,
            depth,
            lat,
            lng,
            sea,
            method,
            kind or "",
            notes or "",
            current["id"],
            user["id"],
        ),
    )
    _refresh_count(conn, current["dive_id"])
    if dive_id != current["dive_id"]:
        _refresh_count(conn, dive_id)
    conn.commit()
    return _sighting_detail(conn, current["id"])


@router.delete("/sightings/{sighting_id}", status_code=204)
def delete_sighting(
    sighting_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> None:
    current = _owned_sighting(conn, sighting_id, user)
    keys = [
        row["storage_key"]
        for row in conn.execute("SELECT storage_key FROM media WHERE sighting_id = %s", (current["id"],)).fetchall()
    ]
    conn.execute("DELETE FROM sightings WHERE id = %s AND user_id = %s", (current["id"], user["id"]))
    _refresh_count(conn, current["dive_id"])
    conn.commit()
    root = request.app.state.settings.media_root
    for key in keys:
        unlink_key(root, key)


@router.patch("/dives/{dive_id}")
def update_dive(
    dive_id: str,
    body: DivePatch,
    user: dict[str, Any] = Depends(require_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> dict[str, Any]:
    current = conn.execute("SELECT * FROM dives WHERE id = %s", (_check_id(dive_id, "dive"),)).fetchone()
    if current is None or not same_user(current["user_id"], user):
        raise HTTPException(status_code=404, detail="Dive not found")
    fields = body.model_fields_set
    site = _site(conn, body.site_id) if "site_id" in fields and body.site_id else None
    if "kind" in fields and (body.kind or "") not in _KINDS:
        raise HTTPException(status_code=422, detail="kind must be sighting or catch")
    conn.execute(
        """
        UPDATE dives
        SET site_id = %s, sea = %s, lat = %s, lng = %s, dive_date = %s, start_time = %s,
            duration_min = %s, max_depth_m = %s, method = %s, kind = %s, notes = %s
        WHERE id = %s AND user_id = %s
        """,
        (
            site["id"] if site else current["site_id"],
            site["sea"] if site else current["sea"],
            site["lat"] if site else current["lat"],
            site["lng"] if site else current["lng"],
            body.dive_date if "dive_date" in fields and body.dive_date else current["dive_date"],
            body.start_time if "start_time" in fields else current["start_time"],
            body.duration_min if "duration_min" in fields else current["duration_min"],
            body.max_depth_m if "max_depth_m" in fields else current["max_depth_m"],
            _clean_text(body.method, 40) if "method" in fields and body.method is not None else current["method"],
            body.kind if "kind" in fields and body.kind is not None else current["kind"],
            _clean_text(body.notes, 4000) if "notes" in fields and body.notes is not None else current["notes"],
            current["id"],
            user["id"],
        ),
    )
    conn.commit()
    return _dive_detail(conn, current["id"])


@router.delete("/dives/{dive_id}", status_code=204)
def delete_dive(
    dive_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> None:
    dive_id = _check_id(dive_id, "dive")
    current = conn.execute("SELECT id, user_id FROM dives WHERE id = %s", (dive_id,)).fetchone()
    if current is None or not same_user(current["user_id"], user):
        raise HTTPException(status_code=404, detail="Dive not found")
    sighting_ids = [
        row["id"]
        for row in conn.execute(
            "SELECT id FROM sightings WHERE dive_id = %s AND user_id = %s",
            (dive_id, user["id"]),
        ).fetchall()
    ]
    keys = [
        row["storage_key"]
        for row in conn.execute(
            """
            SELECT storage_key FROM media
            WHERE dive_id = %s OR sighting_id = ANY(%s)
            """,
            (dive_id, sighting_ids or [""]),
        ).fetchall()
    ]
    if sighting_ids:
        conn.execute("DELETE FROM sightings WHERE id = ANY(%s) AND user_id = %s", (sighting_ids, user["id"]))
    conn.execute("DELETE FROM media WHERE dive_id = %s", (dive_id,))
    conn.execute("DELETE FROM dives WHERE id = %s AND user_id = %s", (dive_id, user["id"]))
    conn.commit()
    root = request.app.state.settings.media_root
    for key in keys:
        unlink_key(root, key)


@router.post("/media", status_code=201)
def add_media(
    request: Request,
    sighting_id: str = Form(""),
    dive_id: str = Form(""),
    photo: UploadFile = File(...),
    user: dict[str, Any] = Depends(require_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> dict[str, Any]:
    if not sighting_id.strip() and not dive_id.strip():
        raise HTTPException(status_code=422, detail="Choose a sighting or a dive")
    if sighting_id.strip():
        _owned_sighting(conn, sighting_id, user)
    if dive_id.strip():
        _owned_dive(conn, dive_id, user)
    media = _attach_photo(
        conn,
        request,
        user,
        sighting_id=sighting_id.strip() or None,
        dive_id=dive_id.strip() or None,
        upload=photo,
    )
    if media is None:
        raise HTTPException(status_code=400, detail="Photo is empty")
    conn.commit()
    return media


@router.delete("/media/{media_id}", status_code=204)
def delete_media(
    media_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> None:
    row = conn.execute(
        "SELECT id, user_id, storage_key FROM media WHERE id = %s",
        (media_id,),
    ).fetchone()
    if row is None or not same_user(row["user_id"], user):
        raise HTTPException(status_code=404, detail="Photo not found")
    conn.execute("DELETE FROM media WHERE id = %s AND user_id = %s", (row["id"], user["id"]))
    conn.commit()
    unlink_key(request.app.state.settings.media_root, row["storage_key"])


@router.get("/media/{media_id}/content")
def media_content(
    media_id: str,
    request: Request,
    user: dict[str, Any] = Depends(require_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> FileResponse:
    row = conn.execute(
        """
        SELECT m.storage_key, m.content_type, m.user_id,
               s.user_id AS sighting_user_id, d.user_id AS dive_user_id
        FROM media m
        LEFT JOIN sightings s ON s.id = m.sighting_id
        LEFT JOIN dives d ON d.id = m.dive_id
        WHERE m.id = %s
        """,
        (media_id,),
    ).fetchone()
    if row is None or not (
        same_user(row["user_id"], user)
        or same_user(row["sighting_user_id"], user)
        or same_user(row["dive_user_id"], user)
    ):
        raise HTTPException(status_code=404, detail="Photo not found")
    path = resolve_key(request.app.state.settings.media_root, row["storage_key"])
    return FileResponse(
        path,
        media_type=row["content_type"] or "application/octet-stream",
        headers={"Cache-Control": "private, max-age=3600"},
    )
