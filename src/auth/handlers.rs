use askama::Template;
use askama_web::WebTemplate;
use axum::{
    extract::State,
    http::header,
    response::{IntoResponse, Redirect, Response},
    Form, Json,
};
use axum_extra::extract::cookie::{Cookie, SignedCookieJar};
use serde::{Deserialize, Serialize};
use time::Duration;

use crate::auth::middleware::AuthUser;
use crate::auth::password::{hash_password, verify_password};
use crate::error::AppError;
use crate::state::AppState;

#[derive(Template, WebTemplate)]
#[template(path = "login.html")]
struct LoginTemplate {
    error: Option<String>,
}

#[derive(Template, WebTemplate)]
#[template(path = "register.html")]
struct RegisterTemplate {
    error: Option<String>,
}

#[derive(Deserialize)]
pub struct LoginForm {
    username: String,
    password: String,
}

#[derive(Deserialize)]
pub struct RegisterForm {
    username: String,
    password: String,
    password_confirm: String,
}

pub async fn login_page() -> impl IntoResponse {
    LoginTemplate { error: None }
}

pub async fn login_submit(
    State(state): State<AppState>,
    jar: SignedCookieJar,
    Form(form): Form<LoginForm>,
) -> Result<Response, AppError> {
    let user = sqlx::query_as::<_, (String, String)>(
        "SELECT id, password_hash FROM users WHERE username = ?",
    )
    .bind(&form.username)
    .fetch_optional(&state.db)
    .await?;

    let Some((user_id, password_hash)) = user else {
        return Ok(LoginTemplate {
            error: Some("Invalid credentials".into()),
        }
        .into_response());
    };

    if !verify_password(&form.password, &password_hash)? {
        return Ok(LoginTemplate {
            error: Some("Invalid credentials".into()),
        }
        .into_response());
    }

    let session_id = uuid::Uuid::new_v4().to_string();
    let expires_at = chrono::Utc::now() + chrono::Duration::days(30);

    sqlx::query("INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)")
        .bind(&session_id)
        .bind(&user_id)
        .bind(expires_at.format("%Y-%m-%dT%H:%M:%S%.3fZ").to_string())
        .execute(&state.db)
        .await?;

    let cookie = Cookie::build(("session_id", session_id))
        .path("/")
        .http_only(true)
        .secure(state.config.secure_cookies)
        .max_age(Duration::days(30))
        .same_site(axum_extra::extract::cookie::SameSite::Lax);

    Ok((jar.add(cookie), Redirect::to("/")).into_response())
}

pub async fn register_page() -> impl IntoResponse {
    RegisterTemplate { error: None }
}

pub async fn register_submit(
    State(state): State<AppState>,
    jar: SignedCookieJar,
    Form(form): Form<RegisterForm>,
) -> Result<Response, AppError> {
    if form.username.trim().is_empty() || form.password.is_empty() {
        return Ok(RegisterTemplate {
            error: Some("Username and password are required".into()),
        }
        .into_response());
    }

    if form.password != form.password_confirm {
        return Ok(RegisterTemplate {
            error: Some("Passwords do not match".into()),
        }
        .into_response());
    }

    if form.password.len() < 8 {
        return Ok(RegisterTemplate {
            error: Some("Password must be at least 8 characters".into()),
        }
        .into_response());
    }

    // Check for existing username
    let exists = sqlx::query_scalar::<_, i64>("SELECT COUNT(*) FROM users WHERE username = ?")
        .bind(&form.username)
        .fetch_one(&state.db)
        .await?;

    if exists > 0 {
        return Ok(RegisterTemplate {
            error: Some("Username already taken".into()),
        }
        .into_response());
    }

    let user_id = uuid::Uuid::new_v4().to_string();
    let password_hash = hash_password(&form.password)?;

    sqlx::query("INSERT INTO users (id, username, password_hash) VALUES (?, ?, ?)")
        .bind(&user_id)
        .bind(&form.username)
        .bind(&password_hash)
        .execute(&state.db)
        .await?;

    // Auto-login after register
    let session_id = uuid::Uuid::new_v4().to_string();
    let expires_at = chrono::Utc::now() + chrono::Duration::days(30);

    sqlx::query("INSERT INTO sessions (id, user_id, expires_at) VALUES (?, ?, ?)")
        .bind(&session_id)
        .bind(&user_id)
        .bind(expires_at.format("%Y-%m-%dT%H:%M:%S%.3fZ").to_string())
        .execute(&state.db)
        .await?;

    let cookie = Cookie::build(("session_id", session_id))
        .path("/")
        .http_only(true)
        .secure(state.config.secure_cookies)
        .max_age(Duration::days(30))
        .same_site(axum_extra::extract::cookie::SameSite::Lax);

    Ok((jar.add(cookie), Redirect::to("/")).into_response())
}

pub async fn logout(
    State(state): State<AppState>,
    jar: SignedCookieJar,
) -> Result<Response, AppError> {
    if let Some(cookie) = jar.get("session_id") {
        sqlx::query("DELETE FROM sessions WHERE id = ?")
            .bind(cookie.value())
            .execute(&state.db)
            .await?;
    }

    let jar = jar.remove(Cookie::from("session_id"));
    Ok((jar, Redirect::to("/login")).into_response())
}

#[derive(Deserialize)]
pub struct AiConsentBody {
    ai_consent: bool,
}

#[derive(Serialize)]
struct AiConsentResponse {
    ai_consent: bool,
}

/// POST /account/ai-consent — set AI processing consent for the authenticated user.
///
/// Accepts a JSON body `{"ai_consent": true|false}` and returns the resulting
/// consent state as `{"ai_consent": true|false}`. Idempotent: calling with the
/// same value multiple times has no additional effect.
pub async fn set_ai_consent(
    user: AuthUser,
    State(state): State<AppState>,
    Json(body): Json<AiConsentBody>,
) -> Result<Response, AppError> {
    sqlx::query("UPDATE users SET ai_consent = ? WHERE id = ?")
        .bind(body.ai_consent)
        .bind(&user.id)
        .execute(&state.db)
        .await?;
    Ok(Json(AiConsentResponse { ai_consent: body.ai_consent }).into_response())
}

/// DELETE /account — permanently delete the authenticated user's account and all data
pub async fn delete_account(
    user: AuthUser,
    State(state): State<AppState>,
    jar: SignedCookieJar,
) -> Result<Response, AppError> {
    // Delete user (CASCADE handles entries, tags, sessions, summaries)
    sqlx::query("DELETE FROM users WHERE id = ?")
        .bind(&user.id)
        .execute(&state.db)
        .await?;

    // Clean up media files; log on failure so orphaned directories can be identified
    if let Err(e) = crate::media::delete_user_media_dir(&state.config.media_dir, &user.id).await {
        tracing::warn!(user_id = %user.id, error = %e, "Failed to delete user media directory during account deletion");
    }

    // Remove session cookie
    let jar = jar.remove(Cookie::from("session_id"));
    Ok((jar, Redirect::to("/login")).into_response())
}

/// GET /account/export — export all user data as JSON
pub async fn export_data(
    user: AuthUser,
    State(state): State<AppState>,
) -> Result<Response, AppError> {
    // Fetch all entries
    let entries = sqlx::query_as::<_, crate::entries::models::Entry>(
        "SELECT * FROM entries WHERE user_id = ? ORDER BY created_at DESC",
    )
    .bind(&user.id)
    .fetch_all(&state.db)
    .await?;

    // Fetch all tags
    let tags = crate::tags::models::list_tags(&state.db, &user.id).await?;

    // Fetch all daily summaries
    let daily_summaries = sqlx::query_as::<_, crate::summary::models::DailySummary>(
        "SELECT * FROM daily_summaries WHERE user_id = ? ORDER BY date DESC",
    )
    .bind(&user.id)
    .fetch_all(&state.db)
    .await?;

    // Fetch all tag reports
    let tag_reports = sqlx::query_as::<_, crate::tags::report::TagReport>(
        "SELECT * FROM tag_reports WHERE user_id = ? ORDER BY generated_at DESC",
    )
    .bind(&user.id)
    .fetch_all(&state.db)
    .await?;

    // Build export
    let export = serde_json::json!({
        "user": {
            "id": user.id,
            "username": user.username,
        },
        "entries": entries.iter().map(|e| serde_json::json!({
            "id": e.id,
            "entry_type": e.entry_type,
            "content": e.content,
            "media_path": e.media_path,
            "media_mime": e.media_mime,
            "transcript": e.transcript,
            "created_at": e.created_at,
            "updated_at": e.updated_at,
        })).collect::<Vec<_>>(),
        "tags": tags.iter().map(|t| serde_json::json!({
            "id": t.id,
            "name": t.name,
            "tag_type": t.tag_type,
            "created_at": t.created_at,
        })).collect::<Vec<_>>(),
        "daily_summaries": daily_summaries.iter().map(|s| serde_json::json!({
            "id": s.id,
            "date": s.date,
            "summary": s.summary,
            "generated_at": s.generated_at,
        })).collect::<Vec<_>>(),
        "tag_reports": tag_reports.iter().map(|r| serde_json::json!({
            "id": r.id,
            "tag_id": r.tag_id,
            "report": r.report,
            "entry_count": r.entry_count,
            "generated_at": r.generated_at,
        })).collect::<Vec<_>>(),
    });

    Ok((
        [
            (header::CONTENT_TYPE, "application/json"),
            (
                header::CONTENT_DISPOSITION,
                "attachment; filename=\"klabautermann-export.json\"",
            ),
        ],
        serde_json::to_string_pretty(&export)?,
    )
        .into_response())
}
