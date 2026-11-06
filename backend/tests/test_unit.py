"""Fast checks that do not need Postgres."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.auth import hash_password, verify_password
from app.google_auth import slug_username, username_candidates
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


def test_migration_splits() -> None:
    sql = Path(__file__).resolve().parents[1].joinpath("migrations", "0001_init.sql").read_text()
    parts = split_sql(sql)
    assert len(parts) > 10
    assert any("CREATE TABLE users" in part and "google_sub" in part for part in parts)
    assert any(part.strip().startswith("CREATE INDEX sightings_observed_on_idx") for part in parts)


if __name__ == "__main__":
    test_password_is_argon2id()
    test_google_username_slug()
    test_migration_splits()
    print("unit ok")
