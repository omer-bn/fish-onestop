"""Postgres pool and JSON-friendly row conversion."""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from typing import Any, Iterator
from uuid import UUID

import psycopg
from fastapi import HTTPException, Request
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


def make_pool(url: str) -> ConnectionPool:
    return ConnectionPool(
        url,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row},
        open=False,
        timeout=15,
    )


def get_conn(request: Request) -> Iterator[psycopg.Connection]:
    pool: ConnectionPool | None = getattr(request.app.state, "pool", None)
    if pool is None:
        raise HTTPException(status_code=503, detail="Database is not ready")
    with pool.connection() as conn:
        yield conn


def dump(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: dump(item) for key, item in value.items()}
    if isinstance(value, list):
        return [dump(item) for item in value]
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, time):
        return value.isoformat()
    return value
