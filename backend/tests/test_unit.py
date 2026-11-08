"""Fast checks that do not need Postgres."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password, verify_password
from app.google_auth import slug_username, username_candidates
from app.history import can_read_media, guide_name, shape_history_row
from app.migrate import split_sql


def test_password_is_argon2id() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password("correct horse battery", hashed)
    assert not verify_password("nope", hashed)


def test_google_username_slug() -> None:
    assert slug_username("Omer.Ben@gmail.com") == "omer.ben"
    assert slug_username("ab@gmail.com") == "abuser"
    assert slug_username("עומר@gmail.com") == "guser"
    names = list(username_candidates("omer@gmail.com"))
    assert names[0] == "omer"
    assert names[1] == "omer-2"
    assert all(len(name) <= 32 for name in names)


def test_guide_name_rejects_paths() -> None:
    assert guide_name("img/red-sphyraena-barracuda.jpg") == "red-sphyraena-barracuda.jpg"
    assert guide_name("red-sphyraena-barracuda.jpg") == "red-sphyraena-barracuda.jpg"
    assert guide_name("img/../../etc/passwd") == ""
    assert guide_name("img/nested/fish.jpg") == ""
    assert guide_name("") == ""


def test_media_visibility() -> None:
    public = {"user_id": None, "sighting_id": "obs-1", "sighting_user_id": None, "dive_id": None, "dive_user_id": None}
    private = {"user_id": "user-a", "sighting_id": "obs-2", "sighting_user_id": "user-a", "dive_id": None, "dive_user_id": None}
    owner = {"id": "user-a"}
    other = {"id": "user-b"}
    assert can_read_media(public, None)
    assert can_read_media(public, other)
    assert not can_read_media(private, None)
    assert not can_read_media(private, other)
    assert can_read_media(private, owner)
    hidden_on_public = dict(public, user_id="user-a")
    assert not can_read_media(hidden_on_public, other)
    assert can_read_media(hidden_on_public, owner)


def test_history_row_hides_someone_elses_dive() -> None:
    row = {
        "id": "obs-1",
        "user_id": None,
        "observed_on": "2026-10-01",
        "site_id": "iui",
        "site_hebrew": "מכון",
        "site_english": "IUI",
        "lat": 1.0,
        "lng": 2.0,
        "count": 3,
        "depth_m": 4,
        "sea": "red",
        "method": "scuba",
        "kind": "",
        "notes": "on the reef",
        "observer": "Atlas Diver",
        "dive_id": "dive-secret",
        "dive_user_id": "user-b",
        "dive_notes": "bob-secret-dive",
        "dive_observer": "Bob",
        "dive_start_time": "09:00:00",
        "dive_date": "2026-10-01",
        "dive_site_id": "iui",
        "dive_site_hebrew": "מכון",
        "dive_site_english": "IUI",
        "dive_method": "scuba",
        "dive_duration_min": 40,
        "dive_max_depth_m": 12,
    }
    item = shape_history_row(row, [], None)
    assert item["public"] is True
    assert item["mine"] is False
    assert item["observer"] == "Atlas Diver"
    assert item["dive"] is None
    assert item["start_time"] is None
    assert "bob-secret-dive" not in str(item)

    owned = dict(row, user_id="user-a", dive_user_id="user-a")
    mine = shape_history_row(owned, [], {"id": "user-a"})
    assert mine["mine"] is True
    assert mine["dive"]["notes"] == "bob-secret-dive"
    assert mine["dive"]["mine"] is True
    assert mine["start_time"] == "09:00:00"


def test_migration_splits() -> None:
    sql = Path(__file__).resolve().parents[1].joinpath("migrations", "0001_init.sql").read_text()
    parts = split_sql(sql)
    assert len(parts) > 10
    assert any("CREATE TABLE users" in part and "google_sub" in part for part in parts)
    assert any(part.strip().startswith("CREATE INDEX sightings_observed_on_idx") for part in parts)


if __name__ == "__main__":
    test_password_is_argon2id()
    test_google_username_slug()
    test_guide_name_rejects_paths()
    test_media_visibility()
    test_history_row_hides_someone_elses_dive()
    test_migration_splits()
    print("unit ok")
