use sqlx::SqlitePool;

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct DailySummary {
    pub id: String,
    pub user_id: String,
    pub date: String,
    pub summary: String,
    pub generated_at: String,
}

pub async fn upsert_summary(
    pool: &SqlitePool,
    user_id: &str,
    date: &str,
    summary: &str,
) -> Result<DailySummary, sqlx::Error> {
    let id = uuid::Uuid::new_v4().to_string();
    sqlx::query(
        r#"INSERT INTO daily_summaries (id, user_id, date, summary)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(user_id, date) DO UPDATE SET
               summary = excluded.summary,
               generated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"#,
    )
    .bind(&id)
    .bind(user_id)
    .bind(date)
    .bind(summary)
    .execute(pool)
    .await?;

    // Fetch the actual row (may have existing id if updated)
    get_summary_for_date(pool, user_id, date)
        .await
        .map(|opt| opt.unwrap())
}

pub async fn get_summary_for_date(
    pool: &SqlitePool,
    user_id: &str,
    date: &str,
) -> Result<Option<DailySummary>, sqlx::Error> {
    sqlx::query_as::<_, DailySummary>(
        "SELECT * FROM daily_summaries WHERE user_id = ? AND date = ?",
    )
    .bind(user_id)
    .bind(date)
    .fetch_optional(pool)
    .await
}

/// Get all user IDs that have entries on a given date.
pub async fn users_with_entries_on_date(
    pool: &SqlitePool,
    date: &str,
) -> Result<Vec<String>, sqlx::Error> {
    sqlx::query_scalar::<_, String>(
        "SELECT DISTINCT user_id FROM entries WHERE date(created_at) = ?",
    )
    .bind(date)
    .fetch_all(pool)
    .await
}

/// Get entry texts for a user on a given date, for building the prompt.
pub async fn get_entries_for_date(
    pool: &SqlitePool,
    user_id: &str,
    date: &str,
) -> Result<Vec<(String, String, Option<String>, Option<String>)>, sqlx::Error> {
    // Returns (entry_type, created_at, content, transcript)
    sqlx::query_as::<_, (String, String, Option<String>, Option<String>)>(
        r#"SELECT entry_type, created_at, content, transcript
           FROM entries
           WHERE user_id = ? AND date(created_at) = ?
           ORDER BY created_at ASC"#,
    )
    .bind(user_id)
    .bind(date)
    .fetch_all(pool)
    .await
}
