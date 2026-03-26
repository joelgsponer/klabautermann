use askama::Template;
use askama_web::WebTemplate;
use axum::{
    extract::{Multipart, Path, Query, State},
    http::{header, StatusCode},
    response::{IntoResponse, Response},
};
use serde::Deserialize;

use crate::auth::middleware::AuthUser;
use crate::entries::models::{self, Entry};
use crate::error::AppError;
use crate::media;
use crate::state::AppState;

const PAGE_SIZE: i64 = 20;

// ── Templates ──────────────────────────────────────────────

#[derive(Template, WebTemplate)]
#[template(path = "timeline.html")]
struct TimelineTemplate {
    username: String,
    entries: Vec<Entry>,
    has_more: bool,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/entry.html")]
struct EntryCollapsedTemplate {
    entry: Entry,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/entry_expanded.html")]
struct EntryExpandedTemplate {
    entry: Entry,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/timeline_page.html")]
struct TimelinePageTemplate {
    entries: Vec<Entry>,
    has_more: bool,
}

// ── Handlers ──────────────────────────────────────────────

/// GET / — full page timeline
pub async fn timeline(
    user: AuthUser,
    State(state): State<AppState>,
) -> Result<impl IntoResponse, AppError> {
    let entries = models::list_entries(&state.db, &user.id, None, PAGE_SIZE + 1).await?;
    let has_more = entries.len() > PAGE_SIZE as usize;
    let entries: Vec<Entry> = entries.into_iter().take(PAGE_SIZE as usize).collect();

    Ok(TimelineTemplate {
        username: user.username,
        entries,
        has_more,
    })
}

/// GET /entries/page?before={ts} — infinite scroll page
#[derive(Deserialize)]
pub struct PageQuery {
    before: Option<String>,
}

pub async fn timeline_page(
    user: AuthUser,
    State(state): State<AppState>,
    Query(query): Query<PageQuery>,
) -> Result<impl IntoResponse, AppError> {
    let entries =
        models::list_entries(&state.db, &user.id, query.before.as_deref(), PAGE_SIZE + 1).await?;
    let has_more = entries.len() > PAGE_SIZE as usize;
    let entries: Vec<Entry> = entries.into_iter().take(PAGE_SIZE as usize).collect();

    Ok(TimelinePageTemplate { entries, has_more })
}

/// POST /entries — create entry (text or multipart media)
pub async fn create_entry(
    user: AuthUser,
    State(state): State<AppState>,
    mut multipart: Multipart,
) -> Result<Response, AppError> {
    let mut content: Option<String> = None;
    let mut media_data: Option<(Vec<u8>, String, String)> = None; // (bytes, filename, mime)

    while let Some(field) = multipart.next_field().await? {
        let name = field.name().unwrap_or("").to_string();
        match name.as_str() {
            "content" => {
                content = Some(field.text().await?);
            }
            "media" => {
                let mime = field
                    .content_type()
                    .unwrap_or("application/octet-stream")
                    .to_string();
                let filename = field
                    .file_name()
                    .unwrap_or("recording.webm")
                    .to_string();
                let bytes = field.bytes().await?.to_vec();
                if !bytes.is_empty() {
                    media_data = Some((bytes, filename, mime));
                }
            }
            _ => {}
        }
    }

    let entry = if let Some((bytes, filename, mime)) = media_data {
        // Media entry
        let file_id = uuid::Uuid::new_v4().to_string();
        let default_ext = if mime.starts_with("image/") { "png" } else { "webm" };
        let ext = filename
            .rsplit('.')
            .next()
            .unwrap_or(default_ext);
        let entry_type = if mime.starts_with("image/") {
            "image"
        } else if mime.starts_with("video/") {
            "video"
        } else {
            "audio"
        };

        let relative_path =
            media::save_media(&state.config.media_dir, &user.id, &file_id, ext, &bytes).await?;

        let entry = models::create_media_entry(
            &state.db,
            &user.id,
            entry_type,
            &relative_path,
            &mime,
            bytes.len() as i64,
        )
        .await?;

        // Enqueue for transcription (only audio/video, not images)
        if entry_type != "image" {
            let _ = state.transcription_tx.send(entry.id.clone()).await;
        }

        entry
    } else if let Some(text) = content {
        let text = text.trim().to_string();
        if text.is_empty() {
            return Ok(StatusCode::BAD_REQUEST.into_response());
        }
        models::create_text_entry(&state.db, &user.id, &text).await?
    } else {
        return Ok(StatusCode::BAD_REQUEST.into_response());
    };

    Ok(EntryCollapsedTemplate { entry }.into_response())
}

/// GET /entries/:id/expand
pub async fn expand_entry(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, AppError> {
    let entry = models::get_entry(&state.db, &id)
        .await?
        .filter(|e| e.user_id == user.id)
        .ok_or_else(|| anyhow::anyhow!("Entry not found"))?;

    Ok(EntryExpandedTemplate { entry }.into_response())
}

/// GET /entries/:id/collapse
pub async fn collapse_entry(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, AppError> {
    let entry = models::get_entry(&state.db, &id)
        .await?
        .filter(|e| e.user_id == user.id)
        .ok_or_else(|| anyhow::anyhow!("Entry not found"))?;

    Ok(EntryCollapsedTemplate { entry }.into_response())
}

/// GET /entries/:id — single entry (used for transcription polling)
pub async fn get_entry(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, AppError> {
    let entry = models::get_entry(&state.db, &id)
        .await?
        .filter(|e| e.user_id == user.id)
        .ok_or_else(|| anyhow::anyhow!("Entry not found"))?;

    Ok(EntryCollapsedTemplate { entry }.into_response())
}

/// DELETE /entries/:id
pub async fn delete_entry(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, AppError> {
    // Get entry to delete media file if present
    if let Some(entry) = models::get_entry(&state.db, &id).await? {
        if entry.user_id == user.id {
            if let Some(ref path) = entry.media_path {
                let _ = media::delete_media(&state.config.media_dir, path).await;
            }
        }
    }

    models::delete_entry(&state.db, &id, &user.id).await?;
    Ok(StatusCode::OK.into_response())
}

/// GET /media/:user_id/:filename — serve stored media
pub async fn serve_media(
    _user: AuthUser,
    State(state): State<AppState>,
    Path((user_id, filename)): Path<(String, String)>,
) -> Result<Response, AppError> {
    let path = std::path::Path::new(&state.config.media_dir)
        .join(&user_id)
        .join(&filename);

    if !path.exists() {
        return Ok(StatusCode::NOT_FOUND.into_response());
    }

    let bytes = tokio::fs::read(&path).await?;

    // Guess MIME from extension
    let mime = match path.extension().and_then(|e| e.to_str()) {
        Some("webm") => "video/webm",
        Some("mp4") => "video/mp4",
        Some("ogg") => "audio/ogg",
        Some("wav") => "audio/wav",
        Some("png") => "image/png",
        Some("jpg") | Some("jpeg") => "image/jpeg",
        Some("gif") => "image/gif",
        Some("webp") => "image/webp",
        Some("svg") => "image/svg+xml",
        _ => "application/octet-stream",
    };

    Ok(([(header::CONTENT_TYPE, mime)], bytes).into_response())
}
