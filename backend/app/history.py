"""Where and when one species was recorded.

Unowned rows are the public atlas, including the seeded demo set.
A signed-in member also sees the sightings they own.
Another member's rows stay out of this list and out of its dive details.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import psycopg
from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import optional_user
from app.config import REPO_ROOT
from app.db import dump, get_conn
from app.files import is_stored_key

router = APIRouter(tags=["history"])

_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_GUIDE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,160}\.(?:jpe?g|png|gif|webp)$", re.IGNORECASE)

_VISIBLE = """
(
    s.user_id IS NULL
    OR (%s::uuid IS NOT NULL AND s.user_id = %s::uuid)
)
"""


def guide_name(image: str) -> str:
    """Return a safe file name from a catalog image path, or an empty string."""
    name = (image or "").strip().replace("\\", "/")
    if name.startswith("img/"):
        name = name[4:]
    if not name or "/" in name or not _GUIDE_RE.fullmatch(name):
        return ""
    return name


def guide_file(root: Path, image: str) -> Path | None:
    name = guide_name(image)
    if not name:
        return None
    base = (root / "docs" / "img").resolve()
    path = (base / name).resolve()
    if path.parent != base or not path.is_file():
        return None
    return path


def with_guide_image(item: dict[str, Any], root: Path) -> dict[str, Any]:
    image = item.get("image") or ""
    path = guide_file(root, image)
    item["image_url"] = f"/guide/{path.name}" if path is not None else ""
    return item


def _same(row_user: Any, user: dict[str, Any] | None) -> bool:
    return user is not None and row_user is not None and str(row_user) == str(user["id"])


def can_read_media(row: dict[str, Any] | None, user: dict[str, Any] | None) -> bool:
    """Own photos stay private. Unowned photos on unowned parents are atlas-public."""
    if not row:
        return False
    if _same(row.get("user_id"), user) or _same(row.get("sighting_user_id"), user) or _same(row.get("dive_user_id"), user):
        return True
    if row.get("user_id") is not None:
        return False
    if row.get("sighting_id") and row.get("sighting_user_id") is not None:
        return False
    if row.get("dive_id") and row.get("dive_user_id") is not None:
        return False
    return bool(row.get("sighting_id") or row.get("dive_id"))


def _viewer_param(user: dict[str, Any] | None) -> str | None:
    if not user:
        return None
    return str(user["id"])


def shape_history_row(
    row: dict[str, Any],
    media: list[dict[str, Any]],
    user: dict[str, Any] | None,
) -> dict[str, Any]:
    """One history row. Private dive notes stay off a public sighting."""
    mine = _same(row.get("user_id"), user)
    public = row.get("user_id") is None
    dive = _shape_dive(row, user)
    return dump(
        {
            "id": row["id"],
            "observed_on": row.get("observed_on"),
            "start_time": dive["start_time"] if dive else None,
            "site_id": row.get("site_id"),
            "site_hebrew": row.get("site_hebrew") or "",
            "site_english": row.get("site_english") or "",
            "lat": row.get("lat"),
            "lng": row.get("lng"),
            "count": row.get("count"),
            "depth_m": row.get("depth_m"),
            "sea": row.get("sea"),
            "method": row.get("method") or "",
            "kind": row.get("kind") or "",
            "notes": row.get("notes") or "",
            "observer": (row.get("observer") or "") if (public or mine) else "",
            "mine": mine,
            "public": public,
            "dive": dive,
            "media": media,
        }
    )


def _shape_dive(row: dict[str, Any], user: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row.get("dive_id"):
        return None
    dive_public = row.get("dive_user_id") is None
    dive_mine = _same(row.get("dive_user_id"), user)
    if not dive_public and not dive_mine:
        return None
    return dump(
        {
            "id": row["dive_id"],
            "site_id": row.get("dive_site_id") or row.get("site_id"),
            "site_hebrew": row.get("dive_site_hebrew") or row.get("site_hebrew") or "",
            "site_english": row.get("dive_site_english") or row.get("site_english") or "",
            "dive_date": row.get("dive_date"),
            "start_time": row.get("dive_start_time"),
            "duration_min": row.get("dive_duration_min"),
            "max_depth_m": row.get("dive_max_depth_m"),
            "method": row.get("dive_method") or "",
            "notes": row.get("dive_notes") or "",
            "observer": row.get("dive_observer") or "",
            "mine": dive_mine,
            "public": dive_public,
        }
    )


def _media_views(row: dict[str, Any], photos: list[dict[str, Any]], user: dict[str, Any] | None) -> list[dict[str, Any]]:
    public = row.get("user_id") is None
    mine = _same(row.get("user_id"), user)
    views: list[dict[str, Any]] = []
    for photo in photos:
        if photo.get("sighting_id") != row["id"]:
            continue
        if not is_stored_key(photo.get("storage_key") or ""):
            continue
        if public:
            if photo.get("user_id") is not None:
                continue
        elif mine:
            if photo.get("user_id") is not None and not _same(photo.get("user_id"), user):
                continue
        else:
            continue
        views.append(
            {
                "id": str(photo["id"]),
                "content_url": f"/media/{photo['id']}/content",
                "content_type": photo.get("content_type") or "",
            }
        )
    return views


def _species_or_404(conn: psycopg.Connection, species_id: str) -> dict[str, Any]:
    if not _ID_RE.fullmatch(species_id or ""):
        raise HTTPException(status_code=404, detail="Species not found")
    row = conn.execute(
        """
        SELECT id, latin, hebrew, english, sea, sea_hebrew, sea_english,
               family_latin, family_hebrew, family_english, image
        FROM species
        WHERE id = %s
        """,
        (species_id,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Species not found")
    return row


@router.get("/species/{species_id}/sightings")
def species_sightings(
    species_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0, le=10000),
    user: dict[str, Any] | None = Depends(optional_user),
    conn: psycopg.Connection = Depends(get_conn),
) -> dict[str, Any]:
    species = _species_or_404(conn, species_id)
    viewer = _viewer_param(user)
    totals = conn.execute(
        f"""
        SELECT COUNT(*) AS total,
               COUNT(DISTINCT s.site_id) AS site_count,
               MIN(s.observed_on) AS first_seen,
               MAX(s.observed_on) AS last_seen
        FROM sightings s
        WHERE s.species_id = %s AND {_VISIBLE}
        """,
        (species["id"], viewer, viewer),
    ).fetchone()
    rows = conn.execute(
        f"""
        SELECT s.id, s.user_id, s.dive_id, s.site_id, s.observed_on, s.count, s.depth_m,
               s.lat, s.lng, s.sea, s.method, s.kind, s.notes, s.observer, s.created_at,
               si.hebrew AS site_hebrew, si.english AS site_english,
               d.user_id AS dive_user_id,
               d.site_id AS dive_site_id,
               d.dive_date,
               d.start_time AS dive_start_time,
               d.duration_min AS dive_duration_min,
               d.max_depth_m AS dive_max_depth_m,
               d.method AS dive_method,
               d.notes AS dive_notes,
               d.observer AS dive_observer,
               dsi.hebrew AS dive_site_hebrew,
               dsi.english AS dive_site_english
        FROM sightings s
        LEFT JOIN sites si ON si.id = s.site_id
        LEFT JOIN dives d ON d.id = s.dive_id
        LEFT JOIN sites dsi ON dsi.id = d.site_id
        WHERE s.species_id = %s AND {_VISIBLE}
        ORDER BY s.observed_on DESC, d.start_time DESC NULLS LAST, s.created_at DESC
        LIMIT %s OFFSET %s
        """,
        (species["id"], viewer, viewer, limit, offset),
    ).fetchall()
    photos: list[dict[str, Any]] = []
    sighting_ids = [row["id"] for row in rows]
    if sighting_ids:
        photos = conn.execute(
            """
            SELECT id, sighting_id, user_id, storage_key, content_type
            FROM media
            WHERE sighting_id = ANY(%s)
            ORDER BY created_at
            """,
            (sighting_ids,),
        ).fetchall()
    species_view = with_guide_image(dump(species), REPO_ROOT)
    items = [shape_history_row(row, _media_views(row, photos, user), user) for row in rows]
    summary = dump(totals)
    return {
        "species": species_view,
        "total": summary["total"],
        "site_count": summary["site_count"],
        "first_seen": summary["first_seen"],
        "last_seen": summary["last_seen"],
        "limit": limit,
        "offset": offset,
        "items": items,
    }
