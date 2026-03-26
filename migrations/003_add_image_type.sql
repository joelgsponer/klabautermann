-- SQLite doesn't support ALTER TABLE to modify CHECK constraints directly.
-- We need to recreate the table with the updated constraint.

-- Clean up from any partial previous run
DROP TABLE IF EXISTS entries_new;

CREATE TABLE entries_new (
    id                    TEXT PRIMARY KEY NOT NULL,
    user_id               TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    entry_type            TEXT NOT NULL CHECK(entry_type IN ('text', 'audio', 'video', 'image')),
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

INSERT INTO entries_new SELECT * FROM entries;
DROP TABLE entries;
ALTER TABLE entries_new RENAME TO entries;

CREATE INDEX idx_entries_user_created ON entries(user_id, created_at DESC);
CREATE INDEX idx_entries_transcription ON entries(transcription_status)
    WHERE transcription_status IN ('pending', 'processing');
