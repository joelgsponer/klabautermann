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
use crate::summary::models::{self as summary_models, DailySummary};
use crate::tags::models::{self as tag_models, Tag};

const PAGE_SIZE: i64 = 20;

/// Maximum allowed upload size (50 MB). Matched by the DefaultBodyLimit layer.
const MAX_UPLOAD_SIZE: usize = 50 * 1024 * 1024;

/// Maximum length of a text entry (100 000 characters).
const MAX_TEXT_LENGTH: usize = 100_000;

/// Permitted file extensions for uploaded media (lowercase, no dot).
const ALLOWED_EXTENSIONS: &[&str] = &[
    "webm", "mp4", "ogg", "wav", "png", "jpg", "jpeg", "gif", "webp",
];

pub struct EntryWithTags {
    pub entry: Entry,
    pub tags: Vec<Tag>,
}

// ── Templates ──────────────────────────────────────────────

#[derive(Template, WebTemplate)]
#[template(path = "timeline.html")]
struct TimelineTemplate {
    username: String,
    entries: Vec<EntryWithTags>,
    has_more: bool,
    summary: Option<DailySummary>,
    has_gemini_key: bool,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/entry.html")]
struct EntryCollapsedTemplate {
    entry: Entry,
    tags: Vec<Tag>,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/entry_expanded.html")]
struct EntryExpandedTemplate {
    entry: Entry,
    tags: Vec<Tag>,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/timeline_page.html")]
struct TimelinePageTemplate {
    entries: Vec<EntryWithTags>,
    has_more: bool,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/entry_edit.html")]
struct EntryEditTemplate {
    entry: Entry,
}

// ── Handlers ──────────────────────────────────────────────

/// GET / — full page timeline
pub async fn timeline(
    user: AuthUser,
    State(state): State<AppState>,
) -> Result<impl IntoResponse, AppError> {
    let raw_entries = models::list_entries(&state.db, &user.id, None, PAGE_SIZE + 1).await?;
    let has_more = raw_entries.len() > PAGE_SIZE as usize;
    let raw_entries: Vec<Entry> = raw_entries.into_iter().take(PAGE_SIZE as usize).collect();

    let entry_ids: Vec<String> = raw_entries.iter().map(|e| e.id.clone()).collect();
    let tags_map = tag_models::get_tags_for_entries(&state.db, &entry_ids).await?;
    let entries: Vec<EntryWithTags> = raw_entries
        .into_iter()
        .map(|entry| {
            let tags = tags_map.get(&entry.id).cloned().unwrap_or_default();
            EntryWithTags { entry, tags }
        })
        .collect();

    let today = chrono::Utc::now().format("%Y-%m-%d").to_string();
    let summary = summary_models::get_summary_for_date(&state.db, &user.id, &today).await?;
    let has_gemini_key = state.config.gemini_api_key.as_ref().is_some_and(|k| !k.is_empty());

    Ok(TimelineTemplate {
        username: user.username,
        entries,
        has_more,
        summary,
        has_gemini_key,
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
    let raw_entries =
        models::list_entries(&state.db, &user.id, query.before.as_deref(), PAGE_SIZE + 1).await?;
    let has_more = raw_entries.len() > PAGE_SIZE as usize;
    let raw_entries: Vec<Entry> = raw_entries.into_iter().take(PAGE_SIZE as usize).collect();

    let entry_ids: Vec<String> = raw_entries.iter().map(|e| e.id.clone()).collect();
    let tags_map = tag_models::get_tags_for_entries(&state.db, &entry_ids).await?;
    let entries: Vec<EntryWithTags> = raw_entries
        .into_iter()
        .map(|entry| {
            let tags = tags_map.get(&entry.id).cloned().unwrap_or_default();
            EntryWithTags { entry, tags }
        })
        .collect();

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
        // Enforce upload size limit (belt-and-suspenders alongside DefaultBodyLimit)
        if bytes.len() > MAX_UPLOAD_SIZE {
            return Ok(StatusCode::PAYLOAD_TOO_LARGE.into_response());
        }

        let file_id = uuid::Uuid::new_v4().to_string();
        let default_ext = if mime.starts_with("image/") { "png" } else { "webm" };
        let ext = filename
            .rsplit('.')
            .next()
            .unwrap_or(default_ext)
            .to_lowercase();

        // Allowlist check — reject extensions not on the approved list
        if !ALLOWED_EXTENSIONS.contains(&ext.as_str()) {
            return Ok(StatusCode::BAD_REQUEST.into_response());
        }

        // Detect actual MIME type via magic bytes; fall back to client-supplied value
        let detected_mime = infer::get(&bytes)
            .map(|t| t.mime_type().to_string())
            .unwrap_or_else(|| mime.clone());

        let entry_type = if detected_mime.starts_with("image/") {
            "image"
        } else if detected_mime.starts_with("video/") {
            "video"
        } else {
            "audio"
        };

        let relative_path =
            media::save_media(&state.config.media_dir, &user.id, &file_id, &ext, &bytes).await?;

        // Trim content and enforce length limit; treat empty as None
        let trimmed_content = content
            .map(|c| c.trim().to_string())
            .filter(|c| !c.is_empty());
        if let Some(ref text) = trimmed_content {
            if text.len() > MAX_TEXT_LENGTH {
                return Ok(StatusCode::PAYLOAD_TOO_LARGE.into_response());
            }
        }

        let entry = models::create_media_entry(
            &state.db,
            &user.id,
            entry_type,
            &relative_path,
            &detected_mime,
            bytes.len() as i64,
            trimmed_content.as_deref(),
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
        // Enforce text entry length limit
        if text.len() > MAX_TEXT_LENGTH {
            return Ok(StatusCode::PAYLOAD_TOO_LARGE.into_response());
        }
        models::create_text_entry(&state.db, &user.id, &text).await?
    } else {
        return Ok(StatusCode::BAD_REQUEST.into_response());
    };

    // Parse and link tags from content text (for both text and media entries with content)
    let tag_text = entry.content.as_deref().unwrap_or("");
    let parsed = tag_models::parse_tags_from_text(tag_text);
    let mut tag_ids = Vec::new();
    for (name, tag_type) in &parsed {
        let tag = tag_models::get_or_create_tag(&state.db, &user.id, name, tag_type).await?;
        tag_ids.push(tag.id);
    }
    if !tag_ids.is_empty() {
        tag_models::link_entry_tags(&state.db, &entry.id, &tag_ids).await?;
    }
    let tags = tag_models::get_tags_for_entry(&state.db, &entry.id).await?;

    Ok(EntryCollapsedTemplate { entry, tags }.into_response())
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
    let tags = tag_models::get_tags_for_entry(&state.db, &entry.id).await?;

    Ok(EntryExpandedTemplate { entry, tags }.into_response())
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
    let tags = tag_models::get_tags_for_entry(&state.db, &entry.id).await?;

    Ok(EntryCollapsedTemplate { entry, tags }.into_response())
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
    let tags = tag_models::get_tags_for_entry(&state.db, &entry.id).await?;

    Ok(EntryCollapsedTemplate { entry, tags }.into_response())
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

/// GET /entries/:id/edit — inline edit form
pub async fn edit_entry_form(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, AppError> {
    let entry = models::get_entry(&state.db, &id)
        .await?
        .filter(|e| e.user_id == user.id)
        .ok_or_else(|| anyhow::anyhow!("Entry not found"))?;

    Ok(EntryEditTemplate { entry }.into_response())
}

/// PATCH /entries/:id/edit — update entry content
pub async fn update_entry(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
    mut multipart: Multipart,
) -> Result<Response, AppError> {
    let mut content: Option<String> = None;
    while let Some(field) = multipart.next_field().await? {
        if field.name() == Some("content") {
            content = Some(field.text().await?);
        }
    }

    let new_content = content
        .map(|c| c.trim().to_string())
        .filter(|c| !c.is_empty())
        .ok_or_else(|| anyhow::anyhow!("Content cannot be empty"))?;

    let entry = models::update_entry(&state.db, &id, &user.id, &new_content)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Entry not found"))?;

    // Re-link tags: clear old, parse new
    tag_models::unlink_entry_tags(&state.db, &entry.id).await?;
    let parsed = tag_models::parse_tags_from_text(&new_content);
    let mut tag_ids = Vec::new();
    for (name, tag_type) in &parsed {
        let tag = tag_models::get_or_create_tag(&state.db, &user.id, name, tag_type).await?;
        tag_ids.push(tag.id);
    }
    if !tag_ids.is_empty() {
        tag_models::link_entry_tags(&state.db, &entry.id, &tag_ids).await?;
    }
    let tags = tag_models::get_tags_for_entry(&state.db, &entry.id).await?;

    Ok(EntryCollapsedTemplate { entry, tags }.into_response())
}

/// GET /media/:user_id/:filename — serve stored media
///
/// Access control: the authenticated user must own the media (user_id path segment
/// must match the session user). Returns 404 for missing files and unauthorized requests
/// to avoid leaking existence information.
pub async fn serve_media(
    user: AuthUser,
    State(state): State<AppState>,
    Path((user_id, filename)): Path<(String, String)>,
) -> Result<Response, AppError> {
    // IDOR guard: only the owning user may access their media
    if user_id != user.id {
        return Ok(StatusCode::NOT_FOUND.into_response());
    }

    let media_base = std::path::Path::new(&state.config.media_dir);
    let requested = media_base.join(&user_id).join(&filename);

    // Path traversal protection: canonicalize both paths and verify the requested
    // path is still within the media directory.
    let canonical_base = match tokio::fs::canonicalize(media_base).await {
        Ok(p) => p,
        Err(_) => return Ok(StatusCode::NOT_FOUND.into_response()),
    };
    let canonical_path = match tokio::fs::canonicalize(&requested).await {
        Ok(p) => p,
        Err(_) => return Ok(StatusCode::NOT_FOUND.into_response()),
    };
    if !canonical_path.starts_with(&canonical_base) {
        return Ok(StatusCode::NOT_FOUND.into_response());
    }

    let bytes = tokio::fs::read(&canonical_path).await?;

    // Determine MIME from allowed extensions only (no SVG to prevent XSS)
    let mime = match canonical_path.extension().and_then(|e| e.to_str()) {
        Some("webm") => "video/webm",
        Some("mp4") => "video/mp4",
        Some("ogg") => "audio/ogg",
        Some("wav") => "audio/wav",
        Some("png") => "image/png",
        Some("jpg") | Some("jpeg") => "image/jpeg",
        Some("gif") => "image/gif",
        Some("webp") => "image/webp",
        _ => "application/octet-stream",
    };

    Ok(([(header::CONTENT_TYPE, mime)], bytes).into_response())
}
