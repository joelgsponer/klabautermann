mod auth;
mod config;
mod entries;
mod error;
mod media;
mod routes;
mod state;

use axum_extra::extract::cookie::Key;
use sqlx::sqlite::SqlitePoolOptions;
use tokio::sync::mpsc;
use tracing::info;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "klabautermann=debug,tower_http=debug".into()),
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

    // Build state
    let cookie_key = Key::from(&config.cookie_secret);
    let state = state::AppState {
        db: pool.clone(),
        config: config.clone(),
        cookie_key,
        transcription_tx: tx.clone(),
    };

    // Spawn transcription worker
    entries::transcription::spawn_worker(pool.clone(), config.clone(), rx);

    // Re-enqueue pending transcriptions from crash recovery
    entries::transcription::recover_pending(&pool, &tx).await;

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
    ];

    for (name, sql) in migration_files {
        let applied: bool = sqlx::query_scalar("SELECT COUNT(*) > 0 FROM _migrations WHERE name = ?")
            .bind(name)
            .fetch_one(pool)
            .await?;

        if !applied {
            info!(migration = name, "Applying migration");
            // Execute each statement separately
            for statement in sql.split(';') {
                let stmt = statement.trim();
                if !stmt.is_empty() {
                    sqlx::query(stmt).execute(pool).await?;
                }
            }
            sqlx::query("INSERT INTO _migrations (name) VALUES (?)")
                .bind(name)
                .execute(pool)
                .await?;
        }
    }

    Ok(())
}
