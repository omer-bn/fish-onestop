# Fish Onestop

Field guide and observation log for the Belmaker Lab (Red Sea and Mediterranean).

GitHub Pages serves `docs/` as a **read-only** catalog: species, sites, and the demo atlas. That static site does not write anywhere. Accounts, new sightings, photos, and each person’s map go through the Postgres API and the phone UI in this repo.

## Static site (GitHub Pages)

`docs/` is the Pages artifact (`.github/workflows/pages.yml`). It is built from the catalog JSON by `static_site/build.py` and does not talk to Postgres. Publishing the API does not change that mirror.

Clicking a species on that static site opens a detail view in the same pages: a map, the latest published field records (date and place), and a note on seasonality. Rows with `demo: true` stay on the observations atlas as examples and are not plotted on the species page as field records. A marker is drawn only when that record has coordinates. The species catalog has no season field. A month-by-month chart appears only when published field records cover at least two months and at least four records, and the chart is labeled as reporting frequency, not as the easiest season to see the fish. Otherwise the page says there is not enough data. The page does not read the signed-in app or anyone's private reports.

## Local Postgres

`docker-compose.yml` starts Postgres 16 for development. The database password there (`fish` / `fish`) is only for that local database. Use a different password anywhere else, and keep real credentials out of git. Copy `.env.example` to `.env` if you want the commands below to pick up `DATABASE_URL` (`.env` is gitignored).

```bash
docker compose up -d
export DATABASE_URL=postgresql://fish:fish@localhost:5432/fish_onestop
python3 -m venv .venv
source .venv/bin/activate
pip install -r backend/requirements.txt
PYTHONPATH=backend python -m app.migrate
PYTHONPATH=backend python -m app.seed
```

Migrations are plain SQL in `backend/migrations/`, applied in filename order and recorded in `schema_migrations`. Running migrate again skips files that already ran.

The seed reads `species.json`, `sites.json`, and `observations.json` from the repo root when those source files are present. This checkout publishes the built catalog under `docs/data/` (`catalog.json` is the species file), and the seed uses that when the root files are absent. Running it again updates rows by id. It does not create passwords or user accounts. Demo dives and sightings stay unowned, so they remain on the public atlas and do not show up in anyone’s “Mine” list.

## Phone UI and API

```bash
PYTHONPATH=backend uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open <http://127.0.0.1:8000> on a phone, or in a narrow browser window. The same app widens into a side navigation on a desktop. It is a small installable web app (manifest, service worker, home-screen icon). Add it to the home screen from the browser once it is served over HTTPS, or from localhost while developing. There is no native App Store build.

The home tab is a large “report a sighting” form: species search, site, count, depth, and a camera button (`capture` on the photo input). Photos are stored on disk under `var/media/` (or `MEDIA_ROOT`). Postgres keeps `media.storage_key` only, not the file bytes.

Signed-in people can open **Mine** to view, edit, and delete their own dives and sightings, including photos. **Map** shows the sites and species they have recorded. **Atlas** searches the species catalog. Opening a species — from Atlas, from a species name in Mine, from a species chip or map popup, or from the fish selected on Report — shows that species’ sighting history: newest first, with the date, the dive start time when the sighting belongs to a dive, the site, and count, depth, and method. A photo thumbnail shows when that sighting has one. Public atlas rows are the unowned ones (including the seeded demo) and name the reporter. Your own rows are marked so edit and delete use the same actions as Mine. Other people’s reports stay private and are left out of the list.

```bash
curl -b /tmp/fish.cookies \
  http://127.0.0.1:8000/species/red-amphiprion-bicinctus/sightings
```

After signing in, search Atlas for `clownfish` or `שושנון` and open the history. The same screen is reachable on a phone-width window and on the wide layout.

`COOKIE_SECURE=1` marks the session cookie Secure. Leave it unset for local HTTP. A Secure cookie is not stored on an `http://` page, which also breaks the Google return trip.

API reference for the same process: <http://127.0.0.1:8000/docs>.

### Username and password

```bash
curl -c /tmp/fish.cookies -H 'content-type: application/json' \
  -d '{"username":"diver","password":"choose-a-long-password","display_name":"Diver"}' \
  http://127.0.0.1:8000/auth/register

curl -b /tmp/fish.cookies -c /tmp/fish.cookies -H 'content-type: application/json' \
  -d '{"username":"diver","password":"choose-a-long-password"}' \
  http://127.0.0.1:8000/auth/login

curl -b /tmp/fish.cookies http://127.0.0.1:8000/auth/me
```

Passwords are hashed with Argon2id. The `fish_session` cookie is HttpOnly. Its raw value is not stored; the database keeps a SHA-256 hash in `sessions`. There is no application `SECRET_KEY` in the repo.

Public registration always creates `role=member`. To grant admin later:

```sql
UPDATE users SET role = 'admin' WHERE username = 'diver';
```

### Sign in with Google

Google is optional and sits beside the password form. When it is not configured, the button stays hidden and password login still works.

Create an OAuth client in Google Cloud Console:

1. APIs & Services → OAuth consent screen. External is fine for a lab app. Add the scopes `openid`, `email`, and `profile`. While the app is in testing, add the Google accounts that should be allowed to sign in.
2. APIs & Services → Credentials → Create credentials → OAuth client ID → **Web application**.
3. Authorized redirect URI: exactly the value of `GOOGLE_REDIRECT_URI` below.
4. Put the client id and client secret in the environment or in `.env`. Do not commit the secret.

```bash
GOOGLE_CLIENT_ID=your-id.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=your-client-secret
GOOGLE_REDIRECT_URI=http://127.0.0.1:8000/auth/google/callback
```

`GOOGLE_REDIRECT_URI` defaults to `http://127.0.0.1:8000/auth/google/callback` (or `PUBLIC_BASE_URL` + `/auth/google/callback`). The host in the browser, the redirect URI, and the cookie host have to be the same (`127.0.0.1` and `localhost` are different).

The server sends the browser to Google and handles `/auth/google/callback`. The client secret never goes to the page. Google’s `sub` is stored on `users.google_sub`. A verified email that already belongs to a password account is linked to that same row, so either sign-in works afterward. A new Google user gets an account with no password; a username is derived from the email. `GET /auth/providers` reports whether the button should show.

## Schema

| Table | What it holds |
| --- | --- |
| `users` | UUID id, citext `username`, nullable citext `email`, nullable `google_sub`, Argon2id `password_hash` (null for Google-only accounts), `role` `member` or `admin` |
| `sites`, `species` | Existing string ids (`iui`, `red-amphiprion-bicinctus`, …) |
| `dives`, `sightings` | String ids from the JSON catalog, or new `dive-` / `obs-` ids. `user_id` is set when a member creates the row |
| `media` | `storage_key` for the photo. Bytes are not stored in Postgres |
| `sessions` | Server-side login sessions |

Every user row has a password hash, a Google subject, or both.

Indexes: `sightings(observed_on)`, `sightings(species_id)`, `sightings(site_id)`, `sightings(user_id)`, `dives(dive_date)`.
