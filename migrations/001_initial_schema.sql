CREATE TABLE users (
    id              TEXT PRIMARY KEY NOT NULL,
    username        TEXT NOT NULL UNIQUE,
    email           TEXT UNIQUE,
    password_hash   TEXT,
    display_name    TEXT,
    auth_provider   TEXT NOT NULL DEFAULT 'local',
    auth_provider_id TEXT,
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(auth_provider, auth_provider_id)
);

CREATE TABLE entries (
    id                    TEXT PRIMARY KEY NOT NULL,
    user_id               TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    entry_type            TEXT NOT NULL CHECK(entry_type IN ('text', 'audio', 'video')),
    content               TEXT,
    media_path            TEXT,
    media_mime            TEXT,
    media_size            INTEGER,
    media_duration_secs   REAL,
    transcript            TEXT,
    transcription_status  TEXT NOT NULL DEFAULT 'none'
        CHECK(transcription_status IN ('none', 'pending', 'processing', 'completed', 'failed')),
    transcription_error   TEXT,
    created_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at            TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX idx_entries_user_created ON entries(user_id, created_at DESC);
CREATE INDEX idx_entries_transcription ON entries(transcription_status)
    WHERE transcription_status IN ('pending', 'processing');
