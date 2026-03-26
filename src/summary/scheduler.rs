use chrono::{Timelike, Utc};
use sqlx::SqlitePool;
use tracing::{error, info};

use crate::config::Config;
use super::gemini;
use super::models;

/// Spawn a background task that generates daily summaries at 04:00 UTC.
pub fn spawn_scheduler(pool: SqlitePool, config: Config) {
    tokio::spawn(async move {
        info!("Daily summary scheduler started");
        loop {
            let now = Utc::now();
            // Calculate seconds until next 04:00 UTC
            let target_hour = 4u32;
            let secs_until = if now.hour() < target_hour {
                // Today at 04:00
                (target_hour - now.hour() - 1) as u64 * 3600
                    + (59 - now.minute()) as u64 * 60
                    + (60 - now.second()) as u64
            } else {
                // Tomorrow at 04:00
                (24 + target_hour - now.hour() - 1) as u64 * 3600
                    + (59 - now.minute()) as u64 * 60
                    + (60 - now.second()) as u64
            };

            info!(seconds = secs_until, "Sleeping until next 04:00 UTC");
            tokio::time::sleep(std::time::Duration::from_secs(secs_until)).await;

            // Generate for yesterday (the day that just ended at 04:00)
            let yesterday = (Utc::now() - chrono::Duration::days(1))
                .format("%Y-%m-%d")
                .to_string();

            if let Err(e) = generate_for_all_users(&pool, &config, &yesterday).await {
                error!(error = %e, "Scheduled summary generation failed");
            }
        }
    });
}

/// Generate summaries for all users who have entries on the given date.
pub async fn generate_for_all_users(
    pool: &SqlitePool,
    config: &Config,
    date: &str,
) -> anyhow::Result<()> {
    let api_key = match &config.gemini_api_key {
        Some(key) if !key.is_empty() => key.clone(),
        _ => {
            info!("Skipping summary generation: no Gemini API key configured");
            return Ok(());
        }
    };

    let user_ids = models::users_with_entries_on_date(pool, date).await?;
    info!(date = date, users = user_ids.len(), "Generating daily summaries");

    for user_id in &user_ids {
        if let Err(e) = generate_for_user(pool, &api_key, user_id, date).await {
            error!(user_id = %user_id, date = date, error = %e, "Summary generation failed for user");
        }
    }

    Ok(())
}

/// Generate a daily summary for a single user on a given date.
pub async fn generate_for_user(
    pool: &SqlitePool,
    api_key: &str,
    user_id: &str,
    date: &str,
) -> anyhow::Result<()> {
    let entries = models::get_entries_for_date(pool, user_id, date).await?;
    if entries.is_empty() {
        return Ok(());
    }

    let tags = models::get_tags_for_date(pool, user_id, date).await?;
    let prompt = gemini::build_summary_prompt(&entries, &tags);
    let summary = gemini::call_gemini_api(api_key, &prompt).await?;
    models::upsert_summary(pool, user_id, date, &summary).await?;

    info!(user_id = %user_id, date = date, "Daily summary generated");
    Ok(())
}
