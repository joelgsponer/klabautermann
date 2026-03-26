use askama::Template;
use askama_web::WebTemplate;
use axum::{
    extract::{Form, Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
};
use serde::Deserialize;

use crate::auth::middleware::AuthUser;
use crate::entries::handlers::EntryWithTags;
use crate::error::AppError;
use crate::state::AppState;
use crate::tags::models::{self, Tag};
use super::report::{self, TagReport};

const PAGE_SIZE: i64 = 20;

// ── Templates ──────────────────────────────────────────────

#[derive(Template, WebTemplate)]
#[template(path = "tag_report.html")]
struct TagReportPageTemplate {
    username: String,
    tag: Tag,
    report: Option<TagReport>,
    has_gemini_key: bool,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/tag_report_panel.html")]
struct TagReportPanelTemplate {
    tag: Tag,
    report: Option<TagReport>,
    has_gemini_key: bool,
}

#[derive(Template, WebTemplate)]
#[template(path = "tags.html")]
struct TagsPageTemplate {
    username: String,
    tags: Vec<Tag>,
    people: Vec<Tag>,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/tag_autocomplete.html")]
struct TagAutocompleteTemplate {
    tags: Vec<Tag>,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/tag_row.html")]
struct TagRowTemplate {
    tag: Tag,
}

#[derive(Template, WebTemplate)]
#[template(path = "tag_entries.html")]
struct TagEntriesPageTemplate {
    username: String,
    tag: Tag,
    entries: Vec<EntryWithTags>,
    has_more: bool,
}

// ── Handlers ──────────────────────────────────────────────

/// GET /tags — management page
pub async fn tags_page(
    user: AuthUser,
    State(state): State<AppState>,
) -> Result<impl IntoResponse, AppError> {
    let all_tags = models::list_tags(&state.db, &user.id).await?;
    let (tags, people): (Vec<Tag>, Vec<Tag>) =
        all_tags.into_iter().partition(|t| t.tag_type == "tag");

    Ok(TagsPageTemplate {
        username: user.username,
        tags,
        people,
    })
}

/// GET /tags/autocomplete?q=...&type=tag|person
#[derive(Deserialize)]
pub struct AutocompleteQuery {
    q: Option<String>,
    r#type: Option<String>,
}

pub async fn autocomplete(
    user: AuthUser,
    State(state): State<AppState>,
    Query(query): Query<AutocompleteQuery>,
) -> Result<impl IntoResponse, AppError> {
    let q = query.q.unwrap_or_default();
    let tag_type = query.r#type.unwrap_or_else(|| "tag".to_string());

    if q.is_empty() {
        return Ok(TagAutocompleteTemplate { tags: vec![] });
    }

    let tags = models::search_tags(&state.db, &user.id, &q, &tag_type).await?;
    Ok(TagAutocompleteTemplate { tags })
}

/// PUT /tags/{id} — rename tag
#[derive(Deserialize)]
pub struct RenameForm {
    name: String,
}

pub async fn rename_tag(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
    Form(form): Form<RenameForm>,
) -> Result<Response, AppError> {
    let new_name = form.name.trim().to_lowercase();
    if new_name.is_empty() {
        return Ok(StatusCode::BAD_REQUEST.into_response());
    }

    models::rename_tag(&state.db, &id, &user.id, &new_name).await?;

    let tag = models::get_tag(&state.db, &id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Tag not found"))?;

    Ok(TagRowTemplate { tag }.into_response())
}

/// DELETE /tags/{id}
pub async fn delete_tag(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, AppError> {
    models::delete_tag(&state.db, &id, &user.id).await?;
    Ok(StatusCode::OK.into_response())
}

/// GET /tags/{id}/entries — entries filtered by tag
#[derive(Deserialize)]
pub struct TagEntriesQuery {
    before: Option<String>,
}

pub async fn tag_entries(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
    Query(query): Query<TagEntriesQuery>,
) -> Result<impl IntoResponse, AppError> {
    let tag = models::get_tag(&state.db, &id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Tag not found"))?;

    let raw_entries = models::list_entries_for_tag(
        &state.db,
        &id,
        &user.id,
        query.before.as_deref(),
        PAGE_SIZE + 1,
    )
    .await?;

    let has_more = raw_entries.len() > PAGE_SIZE as usize;
    let raw_entries: Vec<_> = raw_entries.into_iter().take(PAGE_SIZE as usize).collect();

    let entry_ids: Vec<String> = raw_entries.iter().map(|e| e.id.clone()).collect();
    let tags_map = models::get_tags_for_entries(&state.db, &entry_ids).await?;

    let entries: Vec<EntryWithTags> = raw_entries
        .into_iter()
        .map(|entry| {
            let tags = tags_map.get(&entry.id).cloned().unwrap_or_default();
            EntryWithTags { entry, tags }
        })
        .collect();

    Ok(TagEntriesPageTemplate {
        username: user.username,
        tag,
        entries,
        has_more,
    })
}

/// GET /tags/{id}/report
pub async fn tag_report(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<impl IntoResponse, AppError> {
    let tag = models::get_tag(&state.db, &id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Tag not found"))?;
    // Ownership check
    if tag.user_id != user.id {
        return Err(anyhow::anyhow!("Tag not found").into());
    }
    let report = report::get_tag_report(&state.db, &id, &user.id).await?;
    let has_gemini_key = state.config.gemini_api_key.as_ref().is_some_and(|k| !k.is_empty());

    Ok(TagReportPageTemplate {
        username: user.username,
        tag,
        report,
        has_gemini_key,
    })
}

/// POST /tags/{id}/report/generate
pub async fn generate_tag_report_handler(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, AppError> {
    let api_key = match &state.config.gemini_api_key {
        Some(key) if !key.is_empty() => key.clone(),
        _ => return Ok(StatusCode::SERVICE_UNAVAILABLE.into_response()),
    };

    let tag = models::get_tag(&state.db, &id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Tag not found"))?;
    if tag.user_id != user.id {
        return Err(anyhow::anyhow!("Tag not found").into());
    }

    match report::generate_tag_report(&state.db, &api_key, &id, &user.id).await {
        Ok(_) => {},
        Err(e) => {
            tracing::error!(error = %e, "Tag report generation failed");
            return Ok((StatusCode::INTERNAL_SERVER_ERROR, format!("Report generation failed: {}", e)).into_response());
        }
    }

    let report = report::get_tag_report(&state.db, &id, &user.id).await?;
    Ok(TagReportPanelTemplate {
        tag,
        report,
        has_gemini_key: true,
    }.into_response())
}
