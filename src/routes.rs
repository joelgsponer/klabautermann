use axum::{
    extract::DefaultBodyLimit,
    http::{HeaderName, HeaderValue},
    routing::{delete, get, post, put},
    Router,
};
use tower_http::{services::ServeDir, set_header::SetResponseHeaderLayer};

use crate::auth::handlers as auth;
use crate::entries::handlers as entries;
use crate::state::AppState;
use crate::summary::handlers as summary;
use crate::tags::handlers as tags;

/// Maximum allowed request body size (50 MB).
pub const MAX_BODY_BYTES: usize = 50 * 1024 * 1024;

pub fn build_router(state: AppState) -> Router {
    Router::new()
        // Timeline
        .route("/", get(entries::timeline))
        // Auth
        .route("/login", get(auth::login_page).post(auth::login_submit))
        .route(
            "/register",
            get(auth::register_page).post(auth::register_submit),
        )
        .route("/logout", post(auth::logout))
        // Account management
        .route("/account", delete(auth::delete_account))
        .route("/account/ai-consent", post(auth::set_ai_consent))
        .route("/account/export", get(auth::export_data))
        // Entries
        .route("/entries", post(entries::create_entry))
        .route("/entries/page", get(entries::timeline_page))
        .route("/entries/{id}", get(entries::get_entry).delete(entries::delete_entry))
        .route("/entries/{id}/expand", get(entries::expand_entry))
        .route("/entries/{id}/collapse", get(entries::collapse_entry))
        .route("/entries/{id}/edit", get(entries::edit_entry_form).patch(entries::update_entry))
        // Summary
        .route("/summary/today", get(summary::summary_today))
        .route("/summary/generate", post(summary::generate_summary))
        // Tags
        .route("/tags", get(tags::tags_page))
        .route("/tags/autocomplete", get(tags::autocomplete))
        .route("/tags/{id}", put(tags::rename_tag).delete(tags::delete_tag))
        .route("/tags/{id}/entries", get(tags::tag_entries))
        .route("/tags/{id}/report", get(tags::tag_report))
        .route("/tags/{id}/report/generate", post(tags::generate_tag_report_handler))
        // Version
        .route("/version", get(|| async { env!("GIT_HASH") }))
        // Media
        .route("/media/{user_id}/{filename}", get(entries::serve_media))
        // Static files
        .nest_service("/static", ServeDir::new("static"))
        .with_state(state)
        // Enforce a 50 MB request body limit across all routes
        .layer(DefaultBodyLimit::max(MAX_BODY_BYTES))
        // Security response headers
        .layer(SetResponseHeaderLayer::if_not_present(
            HeaderName::from_static("x-content-type-options"),
            HeaderValue::from_static("nosniff"),
        ))
        .layer(SetResponseHeaderLayer::if_not_present(
            HeaderName::from_static("x-frame-options"),
            HeaderValue::from_static("DENY"),
        ))
        .layer(SetResponseHeaderLayer::if_not_present(
            HeaderName::from_static("referrer-policy"),
            HeaderValue::from_static("strict-origin-when-cross-origin"),
        ))
}
