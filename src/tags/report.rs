use sqlx::SqlitePool;

use crate::entries::models::Entry;

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct TagReport {
    pub id: String,
    pub tag_id: String,
    pub user_id: String,
    pub report: String,
    pub entry_count: i32,
    pub generated_at: String,
}

pub async fn get_tag_report(
    pool: &SqlitePool,
    tag_id: &str,
    user_id: &str,
) -> Result<Option<TagReport>, sqlx::Error> {
    sqlx::query_as::<_, TagReport>(
        "SELECT * FROM tag_reports WHERE tag_id = ? AND user_id = ?",
    )
    .bind(tag_id)
    .bind(user_id)
    .fetch_optional(pool)
    .await
}

pub async fn upsert_tag_report(
    pool: &SqlitePool,
    tag_id: &str,
    user_id: &str,
    report: &str,
    entry_count: i32,
) -> Result<TagReport, sqlx::Error> {
    let id = uuid::Uuid::new_v4().to_string();
    sqlx::query(
        r#"INSERT INTO tag_reports (id, tag_id, user_id, report, entry_count)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(tag_id, user_id) DO UPDATE SET
               report = excluded.report,
               entry_count = excluded.entry_count,
               generated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"#,
    )
    .bind(&id)
    .bind(tag_id)
    .bind(user_id)
    .bind(report)
    .bind(entry_count)
    .execute(pool)
    .await?;

    get_tag_report(pool, tag_id, user_id)
        .await
        .and_then(|opt| opt.ok_or(sqlx::Error::RowNotFound))
}

pub fn build_tag_report_prompt(
    tag_name: &str,
    tag_type: &str,
    entries: &[Entry],
    existing_report: Option<&str>,
) -> String {
    let sigil = if tag_type == "person" { "@" } else { "#" };
    let mut prompt = format!(
        "You maintain a cumulative knowledge report for the tag `{}{name}` in a personal log. \
         Update the existing report by integrating the new entries below. \
         Preserve prior knowledge, resolve contradictions, and synthesise everything into a \
         single coherent document. Do not include a title or heading — just the report text.\n\n",
        sigil,
        name = tag_name,
    );

    if let Some(existing) = existing_report {
        prompt.push_str("Current report:\n");
        prompt.push_str(existing);
        prompt.push_str("\n\n---\n\n");
    }

    prompt.push_str("Entries:\n\n");
    for entry in entries {
        let text = entry.display_text().unwrap_or("[no text]");
        let text = text.char_indices().nth(1000).map_or(text, |(i, _)| &text[..i]);
        prompt.push_str(&format!("[{}] {}\n\n", entry.created_at, text));
    }

    prompt
}

pub async fn generate_tag_report(
    pool: &SqlitePool,
    api_key: &str,
    tag_id: &str,
    user_id: &str,
) -> anyhow::Result<TagReport> {
    // 1. Fetch the tag — get_tag enforces ownership via user_id filter
    let tag = super::models::get_tag(pool, tag_id, user_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Tag not found"))?;

    // 2. Fetch all entries for this tag (up to 500)
    let entries = super::models::list_entries_for_tag(pool, tag_id, user_id, None, 500).await?;

    if entries.is_empty() {
        anyhow::bail!("No entries found for this tag");
    }

    // 4. Get existing report
    let existing = get_tag_report(pool, tag_id, user_id).await?;
    let existing_text = existing.as_ref().map(|r| r.report.as_str());

    // 5. Build prompt
    let prompt = build_tag_report_prompt(&tag.name, &tag.tag_type, &entries, existing_text);

    // 6. Call Gemini
    let report_text = crate::summary::gemini::call_gemini_api(api_key, &prompt).await?;

    // 7. Upsert and return
    let report = upsert_tag_report(pool, tag_id, user_id, &report_text, entries.len() as i32).await?;

    Ok(report)
}
