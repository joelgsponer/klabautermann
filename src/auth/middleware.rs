use axum::{
    extract::FromRequestParts,
    http::{request::Parts, StatusCode},
    response::{IntoResponse, Redirect, Response},
};
use axum::extract::FromRef;
use axum_extra::extract::cookie::Key;
use axum_extra::extract::cookie::SignedCookieJar;

use crate::state::AppState;

/// Authenticated user extracted from the session cookie.
#[derive(Debug, Clone)]
pub struct AuthUser {
    pub id: String,
    pub username: String,
}

impl<S> FromRequestParts<S> for AuthUser
where
    S: Send + Sync,
    AppState: FromRef<S>,
    Key: FromRef<S>,
{
    type Rejection = Response;

    async fn from_request_parts(parts: &mut Parts, state: &S) -> Result<Self, Self::Rejection> {
        let app_state = AppState::from_ref(state);
        let jar = SignedCookieJar::from_headers(&parts.headers, Key::from_ref(state));

        let session_id = jar
            .get("session_id")
            .map(|c| c.value().to_string())
            .ok_or_else(|| Redirect::to("/login").into_response())?;

        let row = sqlx::query_as::<_, (String, String)>(
            r#"SELECT u.id, u.username
               FROM sessions s
               JOIN users u ON u.id = s.user_id
               WHERE s.id = ? AND s.expires_at > strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"#,
        )
        .bind(&session_id)
        .fetch_optional(&app_state.db)
        .await
        .map_err(|_| {
            (StatusCode::INTERNAL_SERVER_ERROR, "Database error").into_response()
        })?
        .ok_or_else(|| Redirect::to("/login").into_response())?;

        Ok(AuthUser {
            id: row.0,
            username: row.1,
        })
    }
}
