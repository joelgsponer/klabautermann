mod auth;
mod config;
mod entries;
mod error;
mod media;
mod routes;
mod state;
mod summary;
mod tags;
mod tasks;

use axum_extra::extract::cookie::Key;
use sqlx::sqlite::SqlitePoolOptions;
use tokio::sync::mpsc;
use tracing::info;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "klabautermann=info,tower_http=info".into()),
        )
        .init();

    let config = config::Config::from_env()?;

    // Ensure media directory exists
    tokio::fs::create_dir_all(&config.media_dir).await?;

    // Database
    let pool = SqlitePoolOptions::new()
        .max_connections(5)
        .connect(&config.database_url)
        .await?;

    // Run migrations manually (sequential SQL files)
    run_migrations(&pool).await?;

    // Transcription channel
    let (tx, rx) = mpsc::channel::<String>(100);

    // Shared HTTP client (connection pool reused across all requests)
    let http_client = reqwest::Client::new();

    // Build state
    let cookie_key = Key::from(&config.cookie_secret);
    let state = state::AppState {
        db: pool.clone(),
        config: config.clone(),
        cookie_key,
        transcription_tx: tx.clone(),
        http_client: http_client.clone(),
    };

    // Spawn transcription worker
    entries::transcription::spawn_worker(pool.clone(), config.clone(), http_client, rx);

    // Re-enqueue pending transcriptions from crash recovery
    entries::transcription::recover_pending(&pool, &tx).await;

    // Spawn daily summary scheduler
    summary::scheduler::spawn_scheduler(pool.clone(), config.clone());

    // Spawn periodic session cleanup (runs every hour)
    {
        let pool = pool.clone();
        tokio::spawn(async move {
            let mut interval =
                tokio::time::interval(std::time::Duration::from_secs(3600));
            loop {
                interval.tick().await;
                let result = sqlx::query(
                    "DELETE FROM sessions WHERE expires_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now')",
                )
                .execute(&pool)
                .await;
                if let Err(e) = result {
                    tracing::warn!(error = %e, "Session cleanup failed");
                }
            }
        });
    }

    // Build router
    let app = routes::build_router(state);

    let listener = tokio::net::TcpListener::bind(&config.listen_addr).await?;
    info!("Klabautermann listening on {}", config.listen_addr);
    axum::serve(listener, app).await?;

    Ok(())
}

async fn run_migrations(pool: &sqlx::SqlitePool) -> anyhow::Result<()> {
    // Enable WAL mode and foreign keys
    sqlx::query("PRAGMA journal_mode=WAL")
        .execute(pool)
        .await?;
    sqlx::query("PRAGMA foreign_keys=ON")
        .execute(pool)
        .await?;

    // Simple migration tracking
    sqlx::query(
        "CREATE TABLE IF NOT EXISTS _migrations (
            name TEXT PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
        )",
    )
    .execute(pool)
    .await?;

    let migration_files = [
        ("001_initial_schema", include_str!("../migrations/001_initial_schema.sql")),
        ("002_sessions", include_str!("../migrations/002_sessions.sql")),
        ("003_add_image_type", include_str!("../migrations/003_add_image_type.sql")),
        ("004_tags", include_str!("../migrations/004_tags.sql")),
        ("005_daily_summaries", include_str!("../migrations/005_daily_summaries.sql")),
        ("006_tag_reports", include_str!("../migrations/006_tag_reports.sql")),
        ("007_ai_consent", include_str!("../migrations/007_ai_consent.sql")),
        ("008_tasks", include_str!("../migrations/008_tasks.sql")),
        ("009_user_summary_schedule", include_str!("../migrations/009_user_summary_schedule.sql")),
    ];

    // Recover from partial migration 003 run (entries_new exists, entries dropped)
    let has_entries_new: bool = sqlx::query_scalar(
        "SELECT COUNT(*) > 0 FROM sqlite_master WHERE type='table' AND name='entries_new'"
    ).fetch_one(pool).await?;
    let has_entries: bool = sqlx::query_scalar(
        "SELECT COUNT(*) > 0 FROM sqlite_master WHERE type='table' AND name='entries'"
    ).fetch_one(pool).await?;
    if has_entries_new && !has_entries {
        info!("Recovering from partial migration: renaming entries_new to entries");
        sqlx::query("ALTER TABLE entries_new RENAME TO entries").execute(pool).await?;
        sqlx::query("CREATE INDEX IF NOT EXISTS idx_entries_user_created ON entries(user_id, created_at DESC)")
            .execute(pool).await?;
        sqlx::query("CREATE INDEX IF NOT EXISTS idx_entries_transcription ON entries(transcription_status) WHERE transcription_status IN ('pending', 'processing')")
            .execute(pool).await?;
        sqlx::query("INSERT OR IGNORE INTO _migrations (name) VALUES ('003_add_image_type')")
            .execute(pool).await?;
    }

    for (name, sql) in migration_files {
        let applied: bool = sqlx::query_scalar("SELECT COUNT(*) > 0 FROM _migrations WHERE name = ?")
            .bind(name)
            .fetch_one(pool)
            .await?;

        if !applied {
            info!(migration = name, "Applying migration");
            // Run all statements in a single transaction (same connection)
            // to ensure DDL visibility across statements
            let mut tx = pool.begin().await?;
            for statement in sql.split(';') {
                let stmt = statement.trim();
                if !stmt.is_empty() {
                    sqlx::query(stmt).execute(&mut *tx).await?;
                }
            }
            sqlx::query("INSERT INTO _migrations (name) VALUES (?)")
                .bind(name)
                .execute(&mut *tx)
                .await?;
            tx.commit().await?;
        }
    }

    Ok(())
}
