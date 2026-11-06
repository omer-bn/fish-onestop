"""Read-only species and site catalog."""

from __future__ import annotations

import psycopg
from fastapi import APIRouter, Depends, Query

from app.db import dump, get_conn

router = APIRouter(tags=["catalog"])


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


@router.get("/species")
def list_species(
    q: str = "",
    sea: str = "",
    limit: int = Query(20, ge=1, le=1000),
    conn: psycopg.Connection = Depends(get_conn),
) -> dict:
    clauses = ["TRUE"]
    params: list = []
    if sea in {"red", "mediterranean"}:
        clauses.append("sea = %s")
        params.append(sea)
    query = q.strip()
    if query:
        pattern = _like(query)
        clauses.append(
            "(latin ILIKE %s ESCAPE '\\' OR hebrew ILIKE %s ESCAPE '\\' "
            "OR english ILIKE %s ESCAPE '\\' OR id ILIKE %s ESCAPE '\\')"
        )
        params.extend([pattern, pattern, pattern, pattern])
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT id, latin, hebrew, english, sea, family_latin
        FROM species
        WHERE {' AND '.join(clauses)}
        ORDER BY latin
        LIMIT %s
        """,
        params,
    ).fetchall()
    return {"items": dump(rows)}


@router.get("/species/{species_id}")
def get_species(species_id: str, conn: psycopg.Connection = Depends(get_conn)) -> dict:
    row = conn.execute(
        """
        SELECT id, latin, hebrew, english, sea, sea_hebrew, sea_english,
               family_id, family_latin, family_hebrew, family_english,
               description, tags, image
        FROM species WHERE id = %s
        """,
        (species_id,),
    ).fetchone()
    if row is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="Species not found")
    return dump(row)


@router.get("/sites")
def list_sites(conn: psycopg.Connection = Depends(get_conn)) -> dict:
    rows = conn.execute(
        """
        SELECT id, sea, hebrew, english, lat, lng
        FROM sites
        ORDER BY sea, english
        """
    ).fetchall()
    return {"items": dump(rows)}
