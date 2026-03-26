use axum::{
    routing::{get, post},
    Router,
};
use tower_http::services::ServeDir;

use crate::auth::handlers as auth;
use crate::entries::handlers as entries;
use crate::state::AppState;

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
        // Entries
        .route("/entries", post(entries::create_entry))
        .route("/entries/page", get(entries::timeline_page))
        .route("/entries/{id}", get(entries::get_entry).delete(entries::delete_entry))
        .route("/entries/{id}/expand", get(entries::expand_entry))
        .route("/entries/{id}/collapse", get(entries::collapse_entry))
        // Media
        .route("/media/{user_id}/{filename}", get(entries::serve_media))
        // Static files
        .nest_service("/static", ServeDir::new("static"))
        .with_state(state)
}
