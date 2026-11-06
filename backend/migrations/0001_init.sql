-- fish-onestop initial schema.
-- Observation photos live in object storage; media.storage_key is that key.
-- File bytes are never stored in Postgres (no BYTEA payload column).

CREATE EXTENSION IF NOT EXISTS citext;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    username CITEXT NOT NULL,
    email CITEXT,
    -- Google "sub" claim. Null until the account signs in with Google.
    google_sub TEXT,
    display_name TEXT NOT NULL DEFAULT '',
    -- Argon2id PHC string when the account has a password. Null for Google-only accounts.
    password_hash TEXT,
    role TEXT NOT NULL DEFAULT 'member',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_login_at TIMESTAMPTZ,
    CONSTRAINT users_username_key UNIQUE (username),
    CONSTRAINT users_email_key UNIQUE (email),
    CONSTRAINT users_google_sub_key UNIQUE (google_sub),
    CONSTRAINT users_username_len CHECK (char_length(username::text) BETWEEN 3 AND 64),
    CONSTRAINT users_email_not_blank CHECK (email IS NULL OR char_length(btrim(email::text)) > 0),
    CONSTRAINT users_google_sub_len CHECK (google_sub IS NULL OR char_length(google_sub) BETWEEN 1 AND 255),
    CONSTRAINT users_password_hash_not_blank CHECK (password_hash IS NULL OR char_length(password_hash) > 0),
    CONSTRAINT users_has_credential CHECK (password_hash IS NOT NULL OR google_sub IS NOT NULL),
    CONSTRAINT users_role_chk CHECK (role IN ('member', 'admin'))
);

CREATE TABLE sites (
    id TEXT PRIMARY KEY,
    sea TEXT NOT NULL,
    hebrew TEXT NOT NULL DEFAULT '',
    english TEXT NOT NULL DEFAULT '',
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sites_sea_chk CHECK (sea IN ('red', 'mediterranean')),
    CONSTRAINT sites_lat_chk CHECK (lat IS NULL OR (lat >= -90 AND lat <= 90)),
    CONSTRAINT sites_lng_chk CHECK (lng IS NULL OR (lng >= -180 AND lng <= 180))
);

-- Species ids stay the existing catalog strings (red-amphiprion-bicinctus, …).
-- The same Latin name can appear twice, once per sea, so latin is not unique.
CREATE TABLE species (
    id TEXT PRIMARY KEY,
    sea TEXT NOT NULL,
    sea_hebrew TEXT NOT NULL DEFAULT '',
    sea_english TEXT NOT NULL DEFAULT '',
    family_id TEXT NOT NULL DEFAULT '',
    family_latin TEXT NOT NULL DEFAULT '',
    family_hebrew TEXT NOT NULL DEFAULT '',
    family_english TEXT NOT NULL DEFAULT '',
    family_hebrew_source TEXT NOT NULL DEFAULT '',
    family_english_source TEXT NOT NULL DEFAULT '',
    latin TEXT NOT NULL DEFAULT '',
    hebrew TEXT NOT NULL DEFAULT '',
    english TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT '',
    section TEXT NOT NULL DEFAULT '',
    tags TEXT[] NOT NULL DEFAULT '{}',
    -- Guide image path from the catalog (for example img/red-….jpg). Not observation media.
    image TEXT NOT NULL DEFAULT '',
    image_credit JSONB NOT NULL DEFAULT '{}'::jsonb,
    slide INTEGER,
    provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT species_sea_chk CHECK (sea IN ('red', 'mediterranean'))
);

CREATE INDEX species_sea_idx ON species (sea);
CREATE INDEX species_latin_idx ON species (latin);

CREATE TABLE dives (
    id TEXT PRIMARY KEY,
    user_id UUID REFERENCES users (id) ON DELETE SET NULL,
    site_id TEXT REFERENCES sites (id) ON DELETE RESTRICT,
    sea TEXT,
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    dive_date DATE NOT NULL,
    start_time TIME,
    duration_min INTEGER,
    max_depth_m NUMERIC(6, 2),
    observer TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    species_count INTEGER,
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT dives_sea_chk CHECK (sea IS NULL OR sea IN ('red', 'mediterranean')),
    CONSTRAINT dives_duration_chk CHECK (duration_min IS NULL OR duration_min >= 0),
    CONSTRAINT dives_depth_chk CHECK (max_depth_m IS NULL OR max_depth_m >= 0),
    CONSTRAINT dives_species_count_chk CHECK (species_count IS NULL OR species_count >= 0)
);

CREATE INDEX dives_dive_date_idx ON dives (dive_date);
CREATE INDEX dives_site_id_idx ON dives (site_id);
CREATE INDEX dives_user_id_idx ON dives (user_id);

CREATE TABLE sightings (
    id TEXT PRIMARY KEY,
    user_id UUID REFERENCES users (id) ON DELETE SET NULL,
    dive_id TEXT REFERENCES dives (id) ON DELETE SET NULL,
    species_id TEXT NOT NULL REFERENCES species (id) ON DELETE RESTRICT,
    site_id TEXT REFERENCES sites (id) ON DELETE RESTRICT,
    observed_on DATE NOT NULL,
    count INTEGER,
    depth_m NUMERIC(6, 2),
    lat DOUBLE PRECISION,
    lng DOUBLE PRECISION,
    sea TEXT,
    method TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    observer TEXT NOT NULL DEFAULT '',
    is_demo BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sightings_sea_chk CHECK (sea IS NULL OR sea IN ('red', 'mediterranean')),
    CONSTRAINT sightings_count_chk CHECK (count IS NULL OR count >= 0),
    CONSTRAINT sightings_depth_chk CHECK (depth_m IS NULL OR depth_m >= 0)
);

CREATE INDEX sightings_observed_on_idx ON sightings (observed_on);
CREATE INDEX sightings_species_id_idx ON sightings (species_id);
CREATE INDEX sightings_site_id_idx ON sightings (site_id);
CREATE INDEX sightings_user_id_idx ON sightings (user_id);
CREATE INDEX sightings_dive_id_idx ON sightings (dive_id);

CREATE TABLE media (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    sighting_id TEXT REFERENCES sightings (id) ON DELETE CASCADE,
    dive_id TEXT REFERENCES dives (id) ON DELETE CASCADE,
    user_id UUID REFERENCES users (id) ON DELETE SET NULL,
    storage_key TEXT NOT NULL,
    content_type TEXT NOT NULL DEFAULT '',
    byte_size BIGINT,
    caption TEXT NOT NULL DEFAULT '',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT media_has_parent CHECK (sighting_id IS NOT NULL OR dive_id IS NOT NULL),
    CONSTRAINT media_storage_key_not_blank CHECK (char_length(btrim(storage_key)) > 0),
    CONSTRAINT media_byte_size_chk CHECK (byte_size IS NULL OR byte_size >= 0)
);

CREATE INDEX media_sighting_id_idx ON media (sighting_id);
CREATE INDEX media_dive_id_idx ON media (dive_id);
CREATE INDEX media_storage_key_idx ON media (storage_key);
CREATE UNIQUE INDEX media_sighting_storage_key_idx
    ON media (sighting_id, storage_key)
    WHERE sighting_id IS NOT NULL;
CREATE UNIQUE INDEX media_dive_storage_key_idx
    ON media (dive_id, storage_key)
    WHERE dive_id IS NOT NULL;

-- Server-side sessions. The cookie holds the raw token; the database stores its SHA-256 hash.
CREATE TABLE sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    token_hash TEXT NOT NULL,
    user_id UUID NOT NULL REFERENCES users (id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT sessions_token_hash_key UNIQUE (token_hash)
);

CREATE INDEX sessions_user_id_idx ON sessions (user_id);
CREATE INDEX sessions_expires_at_idx ON sessions (expires_at);

COMMENT ON COLUMN media.storage_key IS
    'Object-storage key (S3, GCS, or similar). The object bytes are not stored in Postgres.';
