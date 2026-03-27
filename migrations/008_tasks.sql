CREATE TABLE tasks (
    id            TEXT PRIMARY KEY NOT NULL,
    user_id       TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    entry_id      TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
    status        TEXT NOT NULL DEFAULT 'open'
                  CHECK(status IN ('open', 'done', 'snoozed', 'cancelled')),
    snoozed_until TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
    updated_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
CREATE INDEX idx_tasks_user_status ON tasks(user_id, status);
CREATE UNIQUE INDEX idx_tasks_entry ON tasks(entry_id);
