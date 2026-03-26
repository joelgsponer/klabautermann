use sqlx::SqlitePool;

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct Entry {
    pub id: String,
    pub user_id: String,
    pub entry_type: String,
    pub content: Option<String>,
    pub media_path: Option<String>,
    pub media_mime: Option<String>,
    pub media_size: Option<i64>,
    pub media_duration_secs: Option<f64>,
    pub transcript: Option<String>,
    pub transcription_status: String,
    pub transcription_error: Option<String>,
    pub created_at: String,
    pub updated_at: String,
}

impl Entry {
    /// Display text: content for text entries, transcript for media entries.
    pub fn display_text(&self) -> Option<&str> {
        match self.entry_type.as_str() {
            "text" => self.content.as_deref(),
            _ => self.transcript.as_deref().or(self.content.as_deref()),
        }
    }

    /// Whether the entry should appear collapsed (long text or has media).
    pub fn is_collapsible(&self) -> bool {
        if self.entry_type != "text" {
            return true;
        }
        self.content
            .as_ref()
            .map(|c| c.len() > 280)
            .unwrap_or(false)
    }

    /// Collapsed preview text (first ~140 chars).
    pub fn preview_text(&self) -> String {
        let text = self.display_text().unwrap_or("");
        if text.len() <= 140 {
            text.to_string()
        } else {
            let truncated: String = text.chars().take(140).collect();
            format!("{}…", truncated.trim_end())
        }
    }

    /// Format created_at for display.
    pub fn formatted_time(&self) -> String {
        // Parse ISO-8601 and format as "HH:MM"
        chrono::NaiveDateTime::parse_from_str(&self.created_at, "%Y-%m-%dT%H:%M:%S%.fZ")
            .map(|dt| dt.format("%H:%M").to_string())
            .unwrap_or_else(|_| self.created_at.clone())
    }

    /// Format created_at as date header "March 25, 2026"
    pub fn formatted_date(&self) -> String {
        chrono::NaiveDateTime::parse_from_str(&self.created_at, "%Y-%m-%dT%H:%M:%S%.fZ")
            .map(|dt| dt.format("%B %-d, %Y").to_string())
            .unwrap_or_else(|_| self.created_at.clone())
    }
}

pub async fn create_text_entry(
    pool: &SqlitePool,
    user_id: &str,
    content: &str,
) -> Result<Entry, sqlx::Error> {
    let id = uuid::Uuid::new_v4().to_string();
    sqlx::query(
        "INSERT INTO entries (id, user_id, entry_type, content) VALUES (?, ?, 'text', ?)",
    )
    .bind(&id)
    .bind(user_id)
    .bind(content)
    .execute(pool)
    .await?;

    get_entry(pool, &id).await.map(|e| e.unwrap())
}

pub async fn create_media_entry(
    pool: &SqlitePool,
    user_id: &str,
    entry_type: &str,
    media_path: &str,
    media_mime: &str,
    media_size: i64,
    content: Option<&str>,
) -> Result<Entry, sqlx::Error> {
    let id = uuid::Uuid::new_v4().to_string();
    let transcription_status = if entry_type == "image" { "none" } else { "pending" };
    sqlx::query(
        r#"INSERT INTO entries (id, user_id, entry_type, content, media_path, media_mime, media_size, transcription_status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)"#,
    )
    .bind(&id)
    .bind(user_id)
    .bind(entry_type)
    .bind(content)
    .bind(media_path)
    .bind(media_mime)
    .bind(media_size)
    .bind(transcription_status)
    .execute(pool)
    .await?;

    get_entry(pool, &id).await.map(|e| e.unwrap())
}

pub async fn update_entry(
    pool: &SqlitePool,
    id: &str,
    user_id: &str,
    content: &str,
) -> Result<Option<Entry>, sqlx::Error> {
    let result = sqlx::query(
        r#"UPDATE entries SET content = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
           WHERE id = ? AND user_id = ?"#,
    )
    .bind(content)
    .bind(id)
    .bind(user_id)
    .execute(pool)
    .await?;
    if result.rows_affected() == 0 {
        return Ok(None);
    }
    get_entry(pool, id).await
}

pub async fn get_entry(pool: &SqlitePool, id: &str) -> Result<Option<Entry>, sqlx::Error> {
    sqlx::query_as::<_, Entry>("SELECT * FROM entries WHERE id = ?")
        .bind(id)
        .fetch_optional(pool)
        .await
}

pub async fn list_entries(
    pool: &SqlitePool,
    user_id: &str,
    before: Option<&str>,
    limit: i64,
) -> Result<Vec<Entry>, sqlx::Error> {
    match before {
        Some(before_ts) => {
            sqlx::query_as::<_, Entry>(
                r#"SELECT * FROM entries
                   WHERE user_id = ? AND created_at < ?
                   ORDER BY created_at DESC
                   LIMIT ?"#,
            )
            .bind(user_id)
            .bind(before_ts)
            .bind(limit)
            .fetch_all(pool)
            .await
        }
        None => {
            sqlx::query_as::<_, Entry>(
                r#"SELECT * FROM entries
                   WHERE user_id = ?
                   ORDER BY created_at DESC
                   LIMIT ?"#,
            )
            .bind(user_id)
            .bind(limit)
            .fetch_all(pool)
            .await
        }
    }
}

pub async fn delete_entry(pool: &SqlitePool, id: &str, user_id: &str) -> Result<bool, sqlx::Error> {
    let result =
        sqlx::query("DELETE FROM entries WHERE id = ? AND user_id = ?")
            .bind(id)
            .bind(user_id)
            .execute(pool)
            .await?;
    Ok(result.rows_affected() > 0)
}

pub async fn get_pending_transcriptions(pool: &SqlitePool) -> Result<Vec<String>, sqlx::Error> {
    sqlx::query_scalar::<_, String>(
        "SELECT id FROM entries WHERE transcription_status IN ('pending', 'processing')",
    )
    .fetch_all(pool)
    .await
}
