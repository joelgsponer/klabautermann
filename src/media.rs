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
pub async fn delete_user_media_dir(media_dir: &str, user_id: &str) -> Result<()> {
    let user_dir = PathBuf::from(media_dir).join(user_id);
    if user_dir.exists() {
        fs::remove_dir_all(&user_dir).await?;
    }
    Ok(())
}
