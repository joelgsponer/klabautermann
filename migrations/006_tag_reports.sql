CREATE TABLE tag_reports (
    id              TEXT PRIMARY KEY NOT NULL,
    tag_id          TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    user_id         TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    report          TEXT NOT NULL,
    entry_count     INTEGER NOT NULL DEFAULT 0,
    generated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(tag_id, user_id)
);
CREATE INDEX idx_tag_reports_user ON tag_reports(user_id);
