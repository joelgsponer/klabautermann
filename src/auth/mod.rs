pub mod handlers;
pub mod middleware;
pub mod password;

/// Returns whether the given user has granted AI processing consent.
///
/// Used by summary, tag report, and transcription handlers to enforce
/// the consent requirement before calling any external AI API.
pub async fn check_ai_consent(
    pool: &sqlx::SqlitePool,
    user_id: &str,
) -> Result<bool, sqlx::Error> {
    sqlx::query_scalar::<_, bool>("SELECT ai_consent FROM users WHERE id = ?")
        .bind(user_id)
        .fetch_one(pool)
        .await
}
