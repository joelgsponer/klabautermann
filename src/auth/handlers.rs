use askama::Template;
use askama_web::WebTemplate;
use axum::{
    extract::State,
    response::{IntoResponse, Redirect, Response},
    Form,
};
use axum_extra::extract::cookie::{Cookie, SignedCookieJar};
use serde::Deserialize;
use time::Duration;

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
