"""Load species, sites, dives, and sightings from the JSON catalog.

Prefers species.json, sites.json, and observations.json at the repo root.
The published repo stores the built copies under docs/data/ (catalog.json is
the species document), and those are used when the root files are absent.
"""

from __future__ import annotations

import argparse
import json
from datetime import date, time
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from app.config import REPO_ROOT, load_settings

ROOT = REPO_ROOT


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _resolve(explicit: Path | None, candidates: list[Path]) -> Path:
    if explicit is not None:
        path = explicit if explicit.is_absolute() else ROOT / explicit
        if not path.is_file():
            raise SystemExit(f"Not found: {path}")
        return path
    for path in candidates:
        if path.is_file():
            return path
    joined = "\n".join(f"  - {path}" for path in candidates)
    raise SystemExit(f"Could not find a catalog file. Looked for:\n{joined}")


def _as_list(document: Any, key: str, path: Path) -> list[dict[str, Any]]:
    if isinstance(document, list):
        rows = document
    elif isinstance(document, dict) and isinstance(document.get(key), list):
        rows = document[key]
    else:
        raise SystemExit(f"{path} must be a list or an object with '{key}'")
    if not all(isinstance(row, dict) for row in rows):
        raise SystemExit(f"{path} contains a non-object {key} row")
    return rows


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def _float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def _int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _date(value: Any, row_id: str) -> date:
    if not value:
        raise SystemExit(f"{row_id} is missing a date")
    return date.fromisoformat(str(value)[:10])


def _time(value: Any) -> time | None:
    if value is None or str(value).strip() == "":
        return None
    return time.fromisoformat(str(value).strip())


def _tags(value: Any) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        return [value]
    return [str(item) for item in value]


def _sea(value: Any, row_id: str) -> str:
    sea = _text(value)
    if sea not in {"red", "mediterranean"}:
        raise SystemExit(f"{row_id} has unsupported sea '{sea}'")
    return sea


def _photo_key(record: dict[str, Any]) -> str | None:
    for key in ("photo", "image", "storageKey", "storage_key"):
        value = record.get(key)
        if isinstance(value, str):
            value = value.strip()
            if value and not value.startswith("data:") and len(value) <= 512:
                return value
    return None


def _upsert_sites(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row_id = _text(row.get("id"))
        if not row_id:
            raise SystemExit("a site is missing an id")
        conn.execute(
            """
            INSERT INTO sites (id, sea, hebrew, english, lat, lng)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                sea = EXCLUDED.sea,
                hebrew = EXCLUDED.hebrew,
                english = EXCLUDED.english,
                lat = EXCLUDED.lat,
                lng = EXCLUDED.lng
            """,
            (
                row_id,
                _sea(row.get("sea"), row_id),
                _text(row.get("hebrew")),
                _text(row.get("english")),
                _float(row.get("lat")),
                _float(row.get("lng")),
            ),
        )


def _upsert_species(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row_id = _text(row.get("id"))
        if not row_id:
            raise SystemExit("a species is missing an id")
        family = row.get("family") if isinstance(row.get("family"), dict) else {}
        credit = row.get("imageCredit") if isinstance(row.get("imageCredit"), dict) else {}
        provenance = row.get("provenance") if isinstance(row.get("provenance"), dict) else {}
        conn.execute(
            """
            INSERT INTO species (
                id, sea, sea_hebrew, sea_english, family_id, family_latin, family_hebrew,
                family_english, family_hebrew_source, family_english_source, latin, hebrew,
                english, description, source, priority, section, tags, image, image_credit,
                slide, provenance
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (id) DO UPDATE SET
                sea = EXCLUDED.sea,
                sea_hebrew = EXCLUDED.sea_hebrew,
                sea_english = EXCLUDED.sea_english,
                family_id = EXCLUDED.family_id,
                family_latin = EXCLUDED.family_latin,
                family_hebrew = EXCLUDED.family_hebrew,
                family_english = EXCLUDED.family_english,
                family_hebrew_source = EXCLUDED.family_hebrew_source,
                family_english_source = EXCLUDED.family_english_source,
                latin = EXCLUDED.latin,
                hebrew = EXCLUDED.hebrew,
                english = EXCLUDED.english,
                description = EXCLUDED.description,
                source = EXCLUDED.source,
                priority = EXCLUDED.priority,
                section = EXCLUDED.section,
                tags = EXCLUDED.tags,
                image = EXCLUDED.image,
                image_credit = EXCLUDED.image_credit,
                slide = EXCLUDED.slide,
                provenance = EXCLUDED.provenance
            """,
            (
                row_id,
                _sea(row.get("sea"), row_id),
                _text(row.get("seaHebrew")),
                _text(row.get("seaEnglish")),
                _text(family.get("id")),
                _text(family.get("latin")),
                _text(family.get("hebrew")),
                _text(family.get("english")),
                _text(family.get("hebrewSource")),
                _text(family.get("englishSource")),
                _text(row.get("latin")),
                _text(row.get("hebrew")),
                _text(row.get("english")),
                _text(row.get("description")),
                _text(row.get("source")),
                _text(row.get("priority")),
                _text(row.get("section")),
                _tags(row.get("tags")),
                _text(row.get("image")),
                Jsonb(credit),
                _int(row.get("slide")),
                Jsonb(provenance),
            ),
        )


def _upsert_dives(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row_id = _text(row.get("id"))
        if not row_id:
            raise SystemExit("a dive is missing an id")
        conn.execute(
            """
            INSERT INTO dives (
                id, site_id, sea, lat, lng, dive_date, start_time, duration_min, max_depth_m,
                observer, method, kind, notes, species_count, is_demo
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                site_id = EXCLUDED.site_id,
                sea = EXCLUDED.sea,
                lat = EXCLUDED.lat,
                lng = EXCLUDED.lng,
                dive_date = EXCLUDED.dive_date,
                start_time = EXCLUDED.start_time,
                duration_min = EXCLUDED.duration_min,
                max_depth_m = EXCLUDED.max_depth_m,
                observer = EXCLUDED.observer,
                method = EXCLUDED.method,
                kind = EXCLUDED.kind,
                notes = EXCLUDED.notes,
                species_count = EXCLUDED.species_count,
                is_demo = EXCLUDED.is_demo
            """,
            (
                row_id,
                _text(row.get("siteId")) or None,
                _text(row.get("sea")) or None,
                _float(row.get("lat")),
                _float(row.get("lng")),
                _date(row.get("date"), row_id),
                _time(row.get("startTime")),
                _int(row.get("durationMin")),
                _float(row.get("maxDepthM")),
                _text(row.get("observer")),
                _text(row.get("method")),
                _text(row.get("kind")),
                _text(row.get("notes")),
                _int(row.get("speciesCount")),
                bool(row.get("demo")),
            ),
        )
        photo = _photo_key(row)
        if photo:
            conn.execute(
                """
                INSERT INTO media (dive_id, storage_key)
                VALUES (%s, %s)
                ON CONFLICT (dive_id, storage_key) WHERE dive_id IS NOT NULL DO NOTHING
                """,
                (row_id, photo),
            )


def _upsert_sightings(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        row_id = _text(row.get("id"))
        if not row_id:
            raise SystemExit("a sighting is missing an id")
        dive_id = _text(row.get("diveId")) or None
        conn.execute(
            """
            INSERT INTO sightings (
                id, dive_id, species_id, site_id, observed_on, count, depth_m, lat, lng, sea,
                method, kind, notes, observer, is_demo
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                dive_id = EXCLUDED.dive_id,
                species_id = EXCLUDED.species_id,
                site_id = EXCLUDED.site_id,
                observed_on = EXCLUDED.observed_on,
                count = EXCLUDED.count,
                depth_m = EXCLUDED.depth_m,
                lat = EXCLUDED.lat,
                lng = EXCLUDED.lng,
                sea = EXCLUDED.sea,
                method = EXCLUDED.method,
                kind = EXCLUDED.kind,
                notes = EXCLUDED.notes,
                observer = EXCLUDED.observer,
                is_demo = EXCLUDED.is_demo
            """,
            (
                row_id,
                dive_id,
                _text(row.get("speciesId")),
                _text(row.get("siteId")) or None,
                _date(row.get("date"), row_id),
                _int(row.get("count")),
                _float(row.get("depthM")),
                _float(row.get("lat")),
                _float(row.get("lng")),
                _text(row.get("sea")) or None,
                _text(row.get("method")),
                _text(row.get("kind")),
                _text(row.get("notes")),
                _text(row.get("observer")),
                bool(row.get("demo")),
            ),
        )
        photo = _photo_key(row)
        if photo:
            conn.execute(
                """
                INSERT INTO media (sighting_id, storage_key)
                VALUES (%s, %s)
                ON CONFLICT (sighting_id, storage_key) WHERE sighting_id IS NOT NULL DO NOTHING
                """,
                (row_id, photo),
            )


def seed(database_url: str, species_path: Path, sites_path: Path, observations_path: Path) -> None:
    species = _as_list(_load(species_path), "species", species_path)
    sites = _as_list(_load(sites_path), "sites", sites_path)
    observations = _load(observations_path)
    if not isinstance(observations, dict):
        raise SystemExit(f"{observations_path} must be an object with sightings and dives")
    sightings = _as_list(observations.get("sightings") or [], "sightings", observations_path)
    if isinstance(observations.get("sightings"), list):
        sightings = observations["sightings"]
    dives = observations.get("dives") if isinstance(observations.get("dives"), list) else []
    if not species:
        raise SystemExit(f"{species_path} has no species")
    try:
        connection = psycopg.connect(database_url)
    except psycopg.OperationalError as exc:
        message = str(exc).splitlines()[0]
        if "://" in message or "password" in message.lower():
            message = "connection failed"
        raise SystemExit(f"Could not connect to Postgres: {message}") from None
    with connection:
        with connection.transaction():
            _upsert_sites(connection, sites)
            _upsert_species(connection, species)
            _upsert_dives(connection, dives)
            _upsert_sightings(connection, sightings)
    print(f"species file: {species_path}")
    print(f"sites file: {sites_path}")
    print(f"observations file: {observations_path}")
    print(
        "upserted "
        f"sites={len(sites)} species={len(species)} dives={len(dives)} sightings={len(sightings)}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Import the fish catalog JSON into Postgres")
    parser.add_argument("--species", type=Path)
    parser.add_argument("--sites", type=Path)
    parser.add_argument("--observations", type=Path)
    args = parser.parse_args()
    settings = load_settings()
    seed(
        settings.database_url,
        _resolve(args.species, [ROOT / "species.json", ROOT / "docs" / "data" / "catalog.json"]),
        _resolve(args.sites, [ROOT / "sites.json", ROOT / "docs" / "data" / "sites.json"]),
        _resolve(
            args.observations,
            [ROOT / "observations.json", ROOT / "docs" / "data" / "observations.json"],
        ),
    )


if __name__ == "__main__":
    main()
