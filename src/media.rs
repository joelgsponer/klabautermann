use anyhow::{bail, Result};
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
///
/// Path traversal protection: the resolved absolute path must remain within
/// `media_dir`. Any attempt to escape via `..` components is rejected.
pub async fn delete_media(media_dir: &str, relative_path: &str) -> Result<()> {
    let media_base = Path::new(media_dir);
    let full_path = media_base.join(relative_path);

    // Only proceed if the media_dir itself exists (skip if not yet created)
    if !media_base.exists() {
        return Ok(());
    }

    let canonical_base = fs::canonicalize(media_base).await?;

    // The target file may not exist yet; build its canonical form manually by
    // canonicalizing the parent directory and appending the filename.
    let canonical_path = if full_path.exists() {
        fs::canonicalize(&full_path).await?
    } else {
        // File does not exist — nothing to delete
        return Ok(());
    };

    if !canonical_path.starts_with(&canonical_base) {
        bail!("Attempted path traversal in delete_media: {}", relative_path);
    }

    fs::remove_file(&canonical_path).await?;
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
