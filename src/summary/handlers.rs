use askama::Template;
use askama_web::WebTemplate;
use axum::{
    extract::{Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use chrono::Utc;
use serde::Deserialize;

use crate::auth::middleware::AuthUser;
use crate::error::AppError;
use crate::state::AppState;
use super::models::{self, DailySummary};
use super::scheduler;

// ── Templates ──────────────────────────────────────────────

#[derive(Template, WebTemplate)]
#[template(path = "partials/day_separator.html")]
pub struct DaySeparatorTemplate {
    pub date: String,
    pub formatted_date: String,
    pub summary: Option<DailySummary>,
    pub has_gemini_key: bool,
}

// ── Handlers ──────────────────────────────────────────────

#[derive(Deserialize)]
pub struct GenerateQuery {
    date: Option<String>,
}

/// GET /summary/today — returns a day separator partial for today
pub async fn summary_today(
    user: AuthUser,
    State(state): State<AppState>,
) -> Result<impl IntoResponse, AppError> {
    let today = Utc::now().format("%Y-%m-%d").to_string();
    let summary = models::get_summary_for_date(&state.db, &user.id, &today).await?;
    let has_gemini_key = state.config.gemini_api_key.as_ref().is_some_and(|k| !k.is_empty());

    Ok(DaySeparatorTemplate {
        formatted_date: format_date(&today),
        date: today,
        summary,
        has_gemini_key,
    })
}

/// POST /summary/generate?date=YYYY-MM-DD — generate (or regenerate) a summary
pub async fn generate_summary(
    user: AuthUser,
    State(state): State<AppState>,
    Query(query): Query<GenerateQuery>,
) -> Result<Response, AppError> {
    let api_key = match &state.config.gemini_api_key {
        Some(key) if !key.is_empty() => key.clone(),
        _ => {
            return Ok(StatusCode::SERVICE_UNAVAILABLE.into_response());
        }
    };

    // Check AI consent before calling Gemini
    let has_consent = crate::auth::check_ai_consent(&state.db, &user.id)
        .await
        .map_err(|e| AppError::from(anyhow::anyhow!(e)))?;
    if !has_consent {
        return Ok((
            StatusCode::FORBIDDEN,
            "AI processing requires consent. Enable it in account settings.",
        )
            .into_response());
    }

    let date = query
        .date
        .unwrap_or_else(|| Utc::now().format("%Y-%m-%d").to_string());

    // Validate date format
    if chrono::NaiveDate::parse_from_str(&date, "%Y-%m-%d").is_err() {
        return Ok((StatusCode::BAD_REQUEST, "Invalid date format").into_response());
    }

    if let Err(e) = scheduler::generate_for_user(&state.db, &api_key, &user.id, &date).await {
        tracing::error!(error = %e, "On-demand summary generation failed");
        return Ok((
            StatusCode::INTERNAL_SERVER_ERROR,
            format!("Summary generation failed: {}", e),
        )
            .into_response());
    }

    let summary = models::get_summary_for_date(&state.db, &user.id, &date).await?;

    Ok(DaySeparatorTemplate {
        formatted_date: format_date(&date),
        date,
        summary,
        has_gemini_key: true,
    }
    .into_response())
}

/// Format "2026-03-26" into "March 26, 2026"
pub fn format_date(date_str: &str) -> String {
    chrono::NaiveDate::parse_from_str(date_str, "%Y-%m-%d")
        .map(|d| d.format("%B %-d, %Y").to_string())
        .unwrap_or_else(|_| date_str.to_string())
}
