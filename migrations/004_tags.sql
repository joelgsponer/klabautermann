CREATE TABLE tags (
    id         TEXT PRIMARY KEY NOT NULL,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    tag_type   TEXT NOT NULL CHECK(tag_type IN ('tag', 'person')),
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    UNIQUE(user_id, name, tag_type)
);
CREATE INDEX idx_tags_user ON tags(user_id, tag_type);

CREATE TABLE entry_tags (
    entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    tag_id   TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
    PRIMARY KEY (entry_id, tag_id)
);
CREATE INDEX idx_entry_tags_tag ON entry_tags(tag_id);
