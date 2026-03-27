use sqlx::SqlitePool;

use crate::entries::models::Entry;

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct Task {
    pub id: String,
    pub user_id: String,
    pub entry_id: String,
    pub status: String,
    pub snoozed_until: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

pub struct TaskWithEntry {
    pub task: Task,
    pub entry: Entry,
}

/// Row shape for the JOIN query — all columns flattened with aliases.
#[derive(sqlx::FromRow)]
struct TaskEntryRow {
    // task fields
    task_id: String,
    task_user_id: String,
    task_entry_id: String,
    task_status: String,
    task_snoozed_until: Option<String>,
    task_created_at: String,
    task_updated_at: String,
    // entry fields
    entry_id: String,
    entry_user_id: String,
    entry_type: String,
    content: Option<String>,
    media_path: Option<String>,
    media_mime: Option<String>,
    media_size: Option<i64>,
    media_duration_secs: Option<f64>,
    transcript: Option<String>,
    transcription_status: String,
    transcription_error: Option<String>,
    entry_created_at: String,
    entry_updated_at: String,
}

impl From<TaskEntryRow> for TaskWithEntry {
    fn from(r: TaskEntryRow) -> Self {
        TaskWithEntry {
            task: Task {
                id: r.task_id,
                user_id: r.task_user_id,
                entry_id: r.task_entry_id,
                status: r.task_status,
                snoozed_until: r.task_snoozed_until,
                created_at: r.task_created_at,
                updated_at: r.task_updated_at,
            },
            entry: Entry {
                id: r.entry_id,
                user_id: r.entry_user_id,
                entry_type: r.entry_type,
                content: r.content,
                media_path: r.media_path,
                media_mime: r.media_mime,
                media_size: r.media_size,
                media_duration_secs: r.media_duration_secs,
                transcript: r.transcript,
                transcription_status: r.transcription_status,
                transcription_error: r.transcription_error,
                created_at: r.entry_created_at,
                updated_at: r.entry_updated_at,
            },
        }
    }
}

const SELECT_TASK_WITH_ENTRY: &str = r#"
    SELECT
        t.id            AS task_id,
        t.user_id       AS task_user_id,
        t.entry_id      AS task_entry_id,
        t.status        AS task_status,
        t.snoozed_until AS task_snoozed_until,
        t.created_at    AS task_created_at,
        t.updated_at    AS task_updated_at,
        e.id            AS entry_id,
        e.user_id       AS entry_user_id,
        e.entry_type    AS entry_type,
        e.content,
        e.media_path,
        e.media_mime,
        e.media_size,
        e.media_duration_secs,
        e.transcript,
        e.transcription_status,
        e.transcription_error,
        e.created_at    AS entry_created_at,
        e.updated_at    AS entry_updated_at
    FROM tasks t
    JOIN entries e ON e.id = t.entry_id
"#;

/// Create a task for an entry if one doesn't already exist (idempotent via UNIQUE index).
pub async fn create_task_if_not_exists(
    pool: &SqlitePool,
    user_id: &str,
    entry_id: &str,
) -> Result<(), sqlx::Error> {
    let id = uuid::Uuid::new_v4().to_string();
    sqlx::query("INSERT OR IGNORE INTO tasks (id, user_id, entry_id) VALUES (?, ?, ?)")
        .bind(&id)
        .bind(user_id)
        .bind(entry_id)
        .execute(pool)
        .await?;
    Ok(())
}

/// Delete the task associated with an entry (when #task tag is removed on edit).
pub async fn delete_task_for_entry(
    pool: &SqlitePool,
    entry_id: &str,
) -> Result<(), sqlx::Error> {
    sqlx::query("DELETE FROM tasks WHERE entry_id = ?")
        .bind(entry_id)
        .execute(pool)
        .await?;
    Ok(())
}

/// List active tasks: open + snoozed-until-expired, joined with their entries.
pub async fn list_active_tasks_with_entries(
    pool: &SqlitePool,
    user_id: &str,
) -> Result<Vec<TaskWithEntry>, sqlx::Error> {
    let query = format!(
        "{} WHERE t.user_id = ? AND (t.status = 'open' OR (t.status = 'snoozed' AND t.snoozed_until <= date('now'))) ORDER BY t.created_at DESC",
        SELECT_TASK_WITH_ENTRY
    );
    let rows = sqlx::query_as::<_, TaskEntryRow>(&query)
        .bind(user_id)
        .fetch_all(pool)
        .await?;
    Ok(rows.into_iter().map(TaskWithEntry::from).collect())
}

/// List all tasks regardless of status.
pub async fn list_all_tasks_with_entries(
    pool: &SqlitePool,
    user_id: &str,
) -> Result<Vec<TaskWithEntry>, sqlx::Error> {
    let query = format!(
        "{} WHERE t.user_id = ? ORDER BY t.created_at DESC",
        SELECT_TASK_WITH_ENTRY
    );
    let rows = sqlx::query_as::<_, TaskEntryRow>(&query)
        .bind(user_id)
        .fetch_all(pool)
        .await?;
    Ok(rows.into_iter().map(TaskWithEntry::from).collect())
}

/// Update task status with ownership check. Returns the updated task if found.
pub async fn update_task_status(
    pool: &SqlitePool,
    task_id: &str,
    user_id: &str,
    status: &str,
    snoozed_until: Option<&str>,
) -> Result<Option<TaskWithEntry>, sqlx::Error> {
    let result = sqlx::query(
        r#"UPDATE tasks SET status = ?, snoozed_until = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
           WHERE id = ? AND user_id = ?"#,
    )
    .bind(status)
    .bind(snoozed_until)
    .bind(task_id)
    .bind(user_id)
    .execute(pool)
    .await?;

    if result.rows_affected() == 0 {
        return Ok(None);
    }

    let query = format!("{} WHERE t.id = ?", SELECT_TASK_WITH_ENTRY);
    let row = sqlx::query_as::<_, TaskEntryRow>(&query)
        .bind(task_id)
        .fetch_optional(pool)
        .await?;
    Ok(row.map(TaskWithEntry::from))
}
