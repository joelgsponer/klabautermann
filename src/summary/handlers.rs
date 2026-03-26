use askama::Template;
use askama_web::WebTemplate;
use axum::{
    extract::State,
    http::StatusCode,
    response::{IntoResponse, Response},
};
use chrono::Utc;

use crate::auth::middleware::AuthUser;
use crate::error::AppError;
use crate::state::AppState;
use super::models::{self, DailySummary};
use super::scheduler;

// ── Templates ──────────────────────────────────────────────

#[derive(Template, WebTemplate)]
#[template(path = "partials/summary.html")]
struct SummaryTemplate {
    summary: Option<DailySummary>,
    has_gemini_key: bool,
}

// ── Handlers ──────────────────────────────────────────────

/// GET /summary/today — returns the summary panel partial
pub async fn summary_today(
    user: AuthUser,
    State(state): State<AppState>,
) -> Result<impl IntoResponse, AppError> {
    let today = Utc::now().format("%Y-%m-%d").to_string();
    let summary = models::get_summary_for_date(&state.db, &user.id, &today).await?;
    let has_gemini_key = state.config.gemini_api_key.as_ref().is_some_and(|k| !k.is_empty());

    Ok(SummaryTemplate {
        summary,
        has_gemini_key,
    })
}

/// POST /summary/generate — generate (or regenerate) today's summary
pub async fn generate_summary(
    user: AuthUser,
    State(state): State<AppState>,
) -> Result<Response, AppError> {
    let api_key = match &state.config.gemini_api_key {
        Some(key) if !key.is_empty() => key.clone(),
        _ => {
            return Ok(StatusCode::SERVICE_UNAVAILABLE.into_response());
        }
    };

    // Check AI consent before calling Gemini
    let has_consent: bool = sqlx::query_scalar("SELECT ai_consent FROM users WHERE id = ?")
        .bind(&user.id)
        .fetch_one(&state.db)
        .await
        .map_err(|e| AppError::from(anyhow::anyhow!(e)))?;
    if !has_consent {
        return Ok((
            StatusCode::FORBIDDEN,
            "AI processing requires consent. Enable it in account settings.",
        )
            .into_response());
    }

    let today = Utc::now().format("%Y-%m-%d").to_string();

    if let Err(e) = scheduler::generate_for_user(&state.db, &api_key, &user.id, &today).await {
        tracing::error!(error = %e, "On-demand summary generation failed");
        return Ok((
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("Summary generation failed: {}", e),
        )
            .into_response());
    }

    let summary = models::get_summary_for_date(&state.db, &user.id, &today).await?;

    Ok(SummaryTemplate {
        summary,
        has_gemini_key: true,
    }
    .into_response())
}
