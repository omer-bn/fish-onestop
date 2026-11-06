"""Species history visibility against Postgres.

Uses the local database from DATABASE_URL. Rows are removed at the end.
"""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("DATABASE_URL", "postgresql://fish:fish@127.0.0.1:5432/fish_onestop")

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_species_history_splits_public_and_own() -> None:
    import psycopg
    from fastapi.testclient import TestClient

    from app.files import save_image
    from app.main import app
    from app.migrate import apply

    url = os.environ["DATABASE_URL"]
    media = Path(os.environ.setdefault("MEDIA_ROOT", "/tmp/fish-history-media"))
    media.mkdir(parents=True, exist_ok=True)
    apply(url)

    suffix = uuid.uuid4().hex[:8]
    species_id = f"test-history-{suffix}"
    site_id = f"test-site-{suffix}"
    public_id = f"obs-public-{suffix}"
    linked_id = f"obs-linked-{suffix}"
    dive_id = f"dive-public-{suffix}"
    alice_name = f"hista{suffix}"
    bob_name = f"histb{suffix}"
    password = "history-pass-1"
    created_users: list[str] = []

    def connect():
        return psycopg.connect(url)

    with connect() as conn:
        conn.execute(
            """
            INSERT INTO sites (id, sea, hebrew, english, lat, lng)
            VALUES (%s, 'red', 'אתר בדיקה', 'History test site', 29.5, 34.9)
            """,
            (site_id,),
        )
        conn.execute(
            """
            INSERT INTO species (id, sea, latin, hebrew, english)
            VALUES (%s, 'red', 'Testus historyi', 'דג בדיקה', 'History test fish')
            """,
            (species_id,),
        )
        conn.execute(
            """
            INSERT INTO dives (
                id, site_id, sea, lat, lng, dive_date, start_time, observer, method, notes, is_demo
            )
            VALUES (%s, %s, 'red', 29.5, 34.9, '2026-10-01', '07:45', 'Atlas Diver', 'scuba', 'public dive note', TRUE)
            """,
            (dive_id, site_id),
        )
        conn.execute(
            """
            INSERT INTO sightings (
                id, dive_id, species_id, site_id, observed_on, count, depth_m, lat, lng, sea,
                method, notes, observer, is_demo
            )
            VALUES (%s, %s, %s, %s, '2026-10-01', 4, 12, 29.5, 34.9, 'red', 'scuba', 'public note', 'Atlas Diver', TRUE)
            """,
            (public_id, dive_id, species_id, site_id),
        )
        conn.commit()

    try:
        with TestClient(app) as client:
            alice = client.post(
                "/auth/register",
                json={"username": alice_name, "password": password, "display_name": "Alice Diver"},
            )
            assert alice.status_code == 201, alice.text
            created_users.append(alice_name)
            reported = client.post(
                "/me/reports",
                data={
                    "species_id": species_id,
                    "observed_on": "2026-01-02",
                    "site_id": site_id,
                    "count": "2",
                    "notes": "alice-secret",
                    "method": "snorkel",
                    "kind": "sighting",
                },
                files={"photo": ("fish.png", PNG, "image/png")},
            )
            assert reported.status_code == 201, reported.text
            alice_sighting = reported.json()["sighting"]["id"]
            alice_media = reported.json()["sighting"]["media"][0]["id"]
            client.post("/auth/logout")

            bob = client.post(
                "/auth/register",
                json={"username": bob_name, "password": password, "display_name": "Bob Diver"},
            )
            assert bob.status_code == 201, bob.text
            created_users.append(bob_name)
            bob_report = client.post(
                "/me/reports",
                data={
                    "species_id": species_id,
                    "observed_on": "2026-05-05",
                    "site_id": site_id,
                    "notes": "bob-secret-sighting",
                    "method": "scuba",
                    "kind": "sighting",
                    "log_dive": "true",
                    "start_time": "11:15",
                    "dive_notes": "bob-secret-dive",
                },
            )
            assert bob_report.status_code == 201, bob_report.text
            bob_body = bob_report.json()
            bob_sighting = bob_body["sighting"]["id"]
            bob_dive = bob_body["dive"]["id"]
            client.post("/auth/logout")

            key, kind = save_image(media, PNG)
            with connect() as conn:
                conn.execute(
                    """
                    INSERT INTO sightings (
                        id, dive_id, species_id, site_id, observed_on, count, sea, method, notes, observer, is_demo
                    )
                    VALUES (%s, %s, %s, %s, '2026-08-01', 1, 'red', 'snorkel', 'linked public note', 'Atlas Diver', TRUE)
                    """,
                    (linked_id, bob_dive, species_id, site_id),
                )
                conn.execute(
                    """
                    INSERT INTO media (sighting_id, storage_key, content_type, byte_size)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (public_id, key, kind, len(PNG)),
                )
                conn.commit()

            anon = client.get(f"/species/{species_id}/sightings")
            assert anon.status_code == 200, anon.text
            anon_body = anon.json()
            anon_ids = [item["id"] for item in anon_body["items"]]
            assert anon_ids == [public_id, linked_id]
            assert anon_body["total"] == 2
            assert anon_body["species"]["english"] == "History test fish"
            public = anon_body["items"][0]
            assert public["observer"] == "Atlas Diver"
            assert public["start_time"].startswith("07:45")
            assert public["site_english"] == "History test site"
            assert public["dive"]["id"] == dive_id
            assert public["dive"]["notes"] == "public dive note"
            assert public["public"] is True
            assert public["mine"] is False
            assert public["media"][0]["content_url"].endswith("/content")
            linked = anon_body["items"][1]
            assert linked["dive"] is None
            assert linked["start_time"] is None
            blob = anon.text
            assert "alice-secret" not in blob
            assert "bob-secret" not in blob

            page = client.get(f"/species/{species_id}/sightings?limit=1&offset=1")
            assert [item["id"] for item in page.json()["items"]] == [linked_id]
            assert page.json()["total"] == 2

            missing = client.get("/species/no-such-species/sightings")
            assert missing.status_code == 404
            assert client.get("/species/not~valid/sightings").status_code == 404

            public_photo = client.get(public["media"][0]["content_url"])
            assert public_photo.status_code == 200
            assert public_photo.content.startswith(b"\x89PNG")
            assert client.get(f"/media/{alice_media}/content").status_code == 404

            logged_alice = client.post("/auth/login", json={"username": alice_name, "password": password})
            assert logged_alice.status_code == 200
            as_alice = client.get(f"/species/{species_id}/sightings").json()
            alice_ids = [item["id"] for item in as_alice["items"]]
            assert alice_ids == [public_id, linked_id, alice_sighting]
            assert as_alice["total"] == 3
            own = as_alice["items"][-1]
            assert own["mine"] is True
            assert own["notes"] == "alice-secret"
            assert own["media"][0]["id"] == alice_media
            assert bob_sighting not in alice_ids
            own_photo = client.get(own["media"][0]["content_url"])
            assert own_photo.status_code == 200
            assert "bob-secret" not in client.get(f"/species/{species_id}/sightings").text

            patched = client.patch(f"/sightings/{alice_sighting}", json={"notes": "alice-edited"})
            assert patched.status_code == 200
            again = client.get(f"/species/{species_id}/sightings").json()
            assert again["items"][-1]["notes"] == "alice-edited"
            client.post("/auth/logout")

            logged_bob = client.post("/auth/login", json={"username": bob_name, "password": password})
            assert logged_bob.status_code == 200
            as_bob = client.get(f"/species/{species_id}/sightings").json()
            bob_ids = [item["id"] for item in as_bob["items"]]
            assert public_id in bob_ids and linked_id in bob_ids and bob_sighting in bob_ids
            assert alice_sighting not in bob_ids
            assert "alice-secret" not in client.get(f"/species/{species_id}/sightings").text
            assert "alice-edited" not in client.get(f"/species/{species_id}/sightings").text
            bob_row = next(item for item in as_bob["items"] if item["id"] == bob_sighting)
            assert bob_row["mine"] is True
            assert bob_row["dive"]["mine"] is True
            assert bob_row["dive"]["notes"] == "bob-secret-dive"
            assert bob_row["start_time"].startswith("11:15")
            linked_for_bob = next(item for item in as_bob["items"] if item["id"] == linked_id)
            assert linked_for_bob["dive"]["id"] == bob_dive
            assert linked_for_bob["start_time"].startswith("11:15")
            assert client.get(f"/media/{alice_media}/content").status_code == 404
            mine = client.get("/me/observations")
            assert mine.status_code == 200
            assert bob_sighting in {item["id"] for item in mine.json()["sightings"]}
            assert alice_sighting not in {item["id"] for item in mine.json()["sightings"]}
    finally:
        with connect() as conn:
            conn.execute(
                "DELETE FROM sightings WHERE species_id = %s OR id = ANY(%s)",
                (species_id, [public_id, linked_id, locals().get("alice_sighting", ""), locals().get("bob_sighting", "")]),
            )
            conn.execute("DELETE FROM dives WHERE id = ANY(%s) OR site_id = %s", ([dive_id, locals().get("bob_dive", "")], site_id))
            conn.execute("DELETE FROM species WHERE id = %s", (species_id,))
            conn.execute("DELETE FROM sites WHERE id = %s", (site_id,))
            if created_users:
                conn.execute("DELETE FROM users WHERE username = ANY(%s)", (created_users,))
            conn.commit()


if __name__ == "__main__":
    test_species_history_splits_public_and_own()
    print("history ok")
