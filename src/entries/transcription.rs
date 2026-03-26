use sqlx::SqlitePool;
use tokio::sync::mpsc;
use tracing::{error, info, warn};

use crate::config::Config;

/// Spawn the background transcription worker.
pub fn spawn_worker(pool: SqlitePool, config: Config, mut rx: mpsc::Receiver<String>) {
    tokio::spawn(async move {
        info!("Transcription worker started");
        while let Some(entry_id) = rx.recv().await {
            info!(entry_id = %entry_id, "Processing transcription");
            if let Err(e) = process_transcription(&pool, &config, &entry_id).await {
                error!(entry_id = %entry_id, error = %e, "Transcription failed");
                let _ = sqlx::query(
                    "UPDATE entries SET transcription_status = 'failed', transcription_error = ?, updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
                )
                .bind(e.to_string())
                .bind(&entry_id)
                .execute(&pool)
                .await;
            }
        }
    });
}

/// Re-enqueue any entries stuck in pending/processing state (crash recovery).
pub async fn recover_pending(pool: &SqlitePool, tx: &mpsc::Sender<String>) {
    match super::models::get_pending_transcriptions(pool).await {
        Ok(ids) => {
            if !ids.is_empty() {
                info!(count = ids.len(), "Re-enqueuing incomplete transcriptions");
            }
            for id in ids {
                if tx.send(id).await.is_err() {
                    warn!("Transcription channel closed during recovery");
                    break;
                }
            }
        }
        Err(e) => error!(error = %e, "Failed to query pending transcriptions"),
    }
}

async fn process_transcription(
    pool: &SqlitePool,
    config: &Config,
    entry_id: &str,
) -> anyhow::Result<()> {
    // Mark as processing
    sqlx::query(
        "UPDATE entries SET transcription_status = 'processing', updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now') WHERE id = ?",
    )
    .bind(entry_id)
    .execute(pool)
    .await?;

    // Fetch entry to get media path
    let entry = super::models::get_entry(pool, entry_id)
        .await?
        .ok_or_else(|| anyhow::anyhow!("Entry not found"))?;

    let media_path = entry
        .media_path
        .ok_or_else(|| anyhow::anyhow!("No media path"))?;

    let full_path = std::path::Path::new(&config.media_dir).join(&media_path);
    let file_bytes = tokio::fs::read(&full_path).await?;

    // Determine filename for the API
    let filename = full_path
        .file_name()
        .unwrap_or_default()
        .to_string_lossy()
        .to_string();

    let mime_type = entry.media_mime.unwrap_or_else(|| "audio/webm".into());

    // Call OpenAI Whisper API
    let transcript = call_whisper_api(&config.openai_api_key, file_bytes, &filename, &mime_type).await?;

    // Update entry with transcript
    sqlx::query(
        r#"UPDATE entries
           SET transcript = ?, transcription_status = 'completed',
               updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
           WHERE id = ?"#,
    )
    .bind(&transcript)
    .bind(entry_id)
    .execute(pool)
    .await?;

    info!(entry_id = %entry_id, "Transcription completed");
    Ok(())
}

async fn call_whisper_api(
    api_key: &str,
    file_bytes: Vec<u8>,
    filename: &str,
    mime_type: &str,
) -> anyhow::Result<String> {
    let client = reqwest::Client::new();

    let file_part = reqwest::multipart::Part::bytes(file_bytes)
        .file_name(filename.to_string())
        .mime_str(mime_type)?;

    let form = reqwest::multipart::Form::new()
        .text("model", "whisper-1")
        .part("file", file_part);

    let response = client
        .post("https://api.openai.com/v1/audio/transcriptions")
        .bearer_auth(api_key)
        .multipart(form)
        .send()
        .await?;

    if !response.status().is_success() {
        let status = response.status();
        let body = response.text().await.unwrap_or_default();
        anyhow::bail!("Whisper API error {}: {}", status, body);
    }

    #[derive(serde::Deserialize)]
    struct WhisperResponse {
        text: String,
    }

    let resp: WhisperResponse = response.json().await?;
    Ok(resp.text)
}
