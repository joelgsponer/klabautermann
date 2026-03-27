use chrono::{NaiveTime, Timelike, Utc};
use chrono_tz::Tz;
use sqlx::SqlitePool;
use std::time::Duration;
use tracing::{error, info, warn};

use crate::config::Config;
use super::gemini;
use super::models;

/// Spawn a background task that checks every 60 seconds whether any user's
/// configured summary time has arrived in their local timezone.
pub fn spawn_scheduler(pool: SqlitePool, config: Config) {
    tokio::spawn(async move {
        info!("Daily summary scheduler started (60s interval)");
        let mut interval = tokio::time::interval(Duration::from_secs(60));
        loop {
            interval.tick().await;
            if let Err(e) = check_and_generate(&pool, &config).await {
                error!(error = %e, "Summary scheduler tick failed");
            }
        }
    });
}

/// Check all users' schedules and generate summaries where due.
async fn check_and_generate(pool: &SqlitePool, config: &Config) -> anyhow::Result<()> {
    let api_key = match &config.gemini_api_key {
        Some(key) if !key.is_empty() => key.clone(),
        _ => return Ok(()),
    };

    let schedules = models::get_all_user_schedules(pool).await?;
    let now_utc = Utc::now();

    for schedule in &schedules {
        let tz: Tz = match schedule.summary_timezone.parse() {
            Ok(tz) => tz,
            Err(_) => {
                warn!(user_id = %schedule.id, tz = %schedule.summary_timezone, "Invalid timezone, skipping");
                continue;
            }
        };

        let target_time = match NaiveTime::parse_from_str(&schedule.summary_time, "%H:%M") {
            Ok(t) => t,
            Err(_) => {
                warn!(user_id = %schedule.id, time = %schedule.summary_time, "Invalid summary time, skipping");
                continue;
            }
        };

        let local_now = now_utc.with_timezone(&tz);
        let local_time = local_now.time();

        // Check if we're past the target time and within a 2-hour window
        let minutes_past = (local_time.num_seconds_from_midnight() as i64)
            - (target_time.num_seconds_from_midnight() as i64);

        if minutes_past < 0 || minutes_past > 7200 {
            continue;
        }

        // Compute "yesterday" in the user's timezone
        let yesterday = (local_now - chrono::Duration::days(1))
            .format("%Y-%m-%d")
            .to_string();

        // Skip if summary already exists for that date
        if let Ok(Some(_)) = models::get_summary_for_date(pool, &schedule.id, &yesterday).await {
            continue;
        }

        // Skip if no AI consent
        if let Ok(false) | Err(_) = crate::auth::check_ai_consent(pool, &schedule.id).await {
            continue;
        }

        info!(user_id = %schedule.id, date = %yesterday, tz = %schedule.summary_timezone, "Generating scheduled summary");
        if let Err(e) = generate_for_user(pool, &api_key, &schedule.id, &yesterday).await {
            error!(user_id = %schedule.id, date = %yesterday, error = %e, "Scheduled summary generation failed for user");
        }
    }

    Ok(())
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
