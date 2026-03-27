use askama::Template;
use askama_web::WebTemplate;
use axum::{
    extract::{Path, Query, State},
    http::StatusCode,
    response::{IntoResponse, Response},
    Form,
};
use serde::Deserialize;

use crate::auth::middleware::AuthUser;
use crate::error::AppError;
use crate::state::AppState;
use crate::tasks::models::{self, TaskWithEntry};

// ── Templates ──────────────────────────────────────────────

#[derive(Template, WebTemplate)]
#[template(path = "tasks.html")]
struct TasksTemplate {
    username: String,
    tasks: Vec<TaskWithEntry>,
    show_all: bool,
}

#[derive(Template, WebTemplate)]
#[template(path = "partials/task_row.html")]
struct TaskRowTemplate {
    tw: TaskWithEntry,
}

// ── Handlers ──────────────────────────────────────────────

#[derive(Deserialize)]
pub struct TasksQuery {
    all: Option<bool>,
}

/// GET /tasks — render task list page
pub async fn tasks_page(
    user: AuthUser,
    State(state): State<AppState>,
    Query(query): Query<TasksQuery>,
) -> Result<impl IntoResponse, AppError> {
    let show_all = query.all.unwrap_or(false);
    let tasks = if show_all {
        models::list_all_tasks_with_entries(&state.db, &user.id).await?
    } else {
        models::list_active_tasks_with_entries(&state.db, &user.id).await?
    };

    Ok(TasksTemplate {
        username: user.username,
        tasks,
        show_all,
    })
}

/// PATCH /tasks/:id/done — mark task done
pub async fn task_done(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, AppError> {
    let tw = models::update_task_status(&state.db, &id, &user.id, "done", None)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Task not found"))?;
    Ok(TaskRowTemplate { tw }.into_response())
}

/// PATCH /tasks/:id/snooze — snooze task to a future date
#[derive(Deserialize)]
pub struct SnoozeForm {
    pub date: String,
}

pub async fn task_snooze(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
    Form(form): Form<SnoozeForm>,
) -> Result<Response, AppError> {
    if form.date.is_empty() {
        return Ok(StatusCode::BAD_REQUEST.into_response());
    }
    let tw = models::update_task_status(&state.db, &id, &user.id, "snoozed", Some(&form.date))
        .await?
        .ok_or_else(|| anyhow::anyhow!("Task not found"))?;
    Ok(TaskRowTemplate { tw }.into_response())
}

/// PATCH /tasks/:id/cancel — cancel a task
pub async fn task_cancel(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, AppError> {
    let tw = models::update_task_status(&state.db, &id, &user.id, "cancelled", None)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Task not found"))?;
    Ok(TaskRowTemplate { tw }.into_response())
}

/// PATCH /tasks/:id/reopen — reopen a done/cancelled/snoozed task
pub async fn task_reopen(
    user: AuthUser,
    State(state): State<AppState>,
    Path(id): Path<String>,
) -> Result<Response, AppError> {
    let tw = models::update_task_status(&state.db, &id, &user.id, "open", None)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Task not found"))?;
    Ok(TaskRowTemplate { tw }.into_response())
}
