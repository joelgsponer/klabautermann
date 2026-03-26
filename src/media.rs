use anyhow::Result;
use std::path::{Path, PathBuf};
use tokio::fs;

/// Save uploaded media bytes to disk. Returns the relative path from media_dir.
pub async fn save_media(
    media_dir: &str,
    user_id: &str,
    file_id: &str,
    extension: &str,
    data: &[u8],
) -> Result<String> {
    let user_dir = PathBuf::from(media_dir).join(user_id);
    fs::create_dir_all(&user_dir).await?;

    let filename = format!("{}.{}", file_id, extension);
    let full_path = user_dir.join(&filename);
    fs::write(&full_path, data).await?;

    // Return path relative to media_dir: "{user_id}/{file_id}.ext"
    Ok(format!("{}/{}", user_id, filename))
}

/// Delete a media file given its relative path.
pub async fn delete_media(media_dir: &str, relative_path: &str) -> Result<()> {
    let full_path = Path::new(media_dir).join(relative_path);
    if full_path.exists() {
        fs::remove_file(&full_path).await?;
    }
    Ok(())
}

/// Delete the entire media directory for a user (used when deleting an account).
///
/// Validates the user_id and canonicalizes the constructed path to prevent
/// directory traversal attacks.
pub async fn delete_user_media_dir(media_dir: &str, user_id: &str) -> Result<()> {
    // Reject user_ids containing path traversal sequences or separators
    if user_id.contains("..") || user_id.contains('/') || user_id.contains('\\') {
        anyhow::bail!("Invalid user_id: contains path traversal characters");
    }

    let media_base = PathBuf::from(media_dir);
    let user_dir = media_base.join(user_id);

    // Only attempt canonicalization if the directory exists; if it doesn't,
    // verify the constructed (non-canonical) path is still within media_dir.
    if user_dir.exists() {
        let canonical_user_dir = user_dir.canonicalize()?;
        let canonical_media_dir = media_base.canonicalize()?;
        if !canonical_user_dir.starts_with(&canonical_media_dir) {
            anyhow::bail!("Path traversal detected: user directory escapes media_dir");
        }
        fs::remove_dir_all(&canonical_user_dir).await?;
    }
    Ok(())
}
