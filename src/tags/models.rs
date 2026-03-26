use std::collections::HashMap;

use sqlx::SqlitePool;

use crate::entries::models::Entry;

#[derive(Debug, Clone, sqlx::FromRow)]
pub struct Tag {
    pub id: String,
    pub user_id: String,
    pub name: String,
    pub tag_type: String, // "tag" or "person"
    pub created_at: String,
}

/// Extract #tags and @person mentions from text.
/// Returns deduplicated (name, type) pairs, lowercased.
pub fn parse_tags_from_text(text: &str) -> Vec<(String, String)> {
    let mut results: Vec<(String, String)> = Vec::new();
    let mut seen = std::collections::HashSet::new();
    let chars: Vec<char> = text.chars().collect();

    for (i, &ch) in chars.iter().enumerate() {
        if ch != '#' && ch != '@' {
            continue;
        }
        // Must be at start or preceded by whitespace/open-paren
        if i > 0 {
            let prev = chars[i - 1];
            if !prev.is_whitespace() && prev != '(' {
                continue;
            }
        }
        // Collect word chars after the sigil
        let tag_type = if ch == '#' { "tag" } else { "person" };
        let mut name = String::new();
        for &c in &chars[i + 1..] {
            if c.is_alphanumeric() || c == '-' || c == '_' {
                name.push(c);
            } else {
                break;
            }
        }
        if name.is_empty() {
            continue;
        }
        let name = name.to_lowercase();
        let key = (name.clone(), tag_type.to_string());
        if seen.insert(key.clone()) {
            results.push(key);
        }
    }

    results
}

pub async fn get_or_create_tag(
    pool: &SqlitePool,
    user_id: &str,
    name: &str,
    tag_type: &str,
) -> Result<Tag, sqlx::Error> {
    let id = uuid::Uuid::new_v4().to_string();
    sqlx::query(
        "INSERT OR IGNORE INTO tags (id, user_id, name, tag_type) VALUES (?, ?, ?, ?)",
    )
    .bind(&id)
    .bind(user_id)
    .bind(name)
    .bind(tag_type)
    .execute(pool)
    .await?;

    sqlx::query_as::<_, Tag>(
        "SELECT * FROM tags WHERE user_id = ? AND name = ? AND tag_type = ?",
    )
    .bind(user_id)
    .bind(name)
    .bind(tag_type)
    .fetch_one(pool)
    .await
}

pub async fn link_entry_tags(
    pool: &SqlitePool,
    entry_id: &str,
    tag_ids: &[String],
) -> Result<(), sqlx::Error> {
    for tag_id in tag_ids {
        sqlx::query("INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) VALUES (?, ?)")
            .bind(entry_id)
            .bind(tag_id)
            .execute(pool)
            .await?;
    }
    Ok(())
}

pub async fn unlink_entry_tags(
    pool: &SqlitePool,
    entry_id: &str,
) -> Result<(), sqlx::Error> {
    sqlx::query("DELETE FROM entry_tags WHERE entry_id = ?")
        .bind(entry_id)
        .execute(pool)
        .await?;
    Ok(())
}

pub async fn get_tags_for_entry(
    pool: &SqlitePool,
    entry_id: &str,
) -> Result<Vec<Tag>, sqlx::Error> {
    sqlx::query_as::<_, Tag>(
        r#"SELECT t.* FROM tags t
           JOIN entry_tags et ON et.tag_id = t.id
           WHERE et.entry_id = ?
           ORDER BY t.tag_type, t.name"#,
    )
    .bind(entry_id)
    .fetch_all(pool)
    .await
}

pub async fn get_tags_for_entries(
    pool: &SqlitePool,
    entry_ids: &[String],
) -> Result<HashMap<String, Vec<Tag>>, sqlx::Error> {
    if entry_ids.is_empty() {
        return Ok(HashMap::new());
    }

    // Build placeholders for IN clause
    let placeholders: Vec<&str> = entry_ids.iter().map(|_| "?").collect();
    let sql = format!(
        r#"SELECT et.entry_id, t.id, t.user_id, t.name, t.tag_type, t.created_at
           FROM tags t
           JOIN entry_tags et ON et.tag_id = t.id
           WHERE et.entry_id IN ({})
           ORDER BY t.tag_type, t.name"#,
        placeholders.join(", ")
    );

    let mut query = sqlx::query_as::<_, (String, String, String, String, String, String)>(&sql);
    for id in entry_ids {
        query = query.bind(id);
    }

    let rows = query.fetch_all(pool).await?;

    let mut map: HashMap<String, Vec<Tag>> = HashMap::new();
    for (entry_id, id, user_id, name, tag_type, created_at) in rows {
        map.entry(entry_id).or_default().push(Tag {
            id,
            user_id,
            name,
            tag_type,
            created_at,
        });
    }

    Ok(map)
}

pub async fn list_tags_by_type(
    pool: &SqlitePool,
    user_id: &str,
    tag_type: &str,
) -> Result<Vec<Tag>, sqlx::Error> {
    sqlx::query_as::<_, Tag>(
        r#"SELECT * FROM tags
           WHERE user_id = ? AND tag_type = ?
           ORDER BY name
           LIMIT 10"#,
    )
    .bind(user_id)
    .bind(tag_type)
    .fetch_all(pool)
    .await
}

pub async fn search_tags(
    pool: &SqlitePool,
    user_id: &str,
    query: &str,
    tag_type: &str,
) -> Result<Vec<Tag>, sqlx::Error> {
    let pattern = format!("{}%", query.to_lowercase());
    sqlx::query_as::<_, Tag>(
        r#"SELECT * FROM tags
           WHERE user_id = ? AND tag_type = ? AND name LIKE ?
           ORDER BY name
           LIMIT 10"#,
    )
    .bind(user_id)
    .bind(tag_type)
    .bind(&pattern)
    .fetch_all(pool)
    .await
}

pub async fn list_tags(
    pool: &SqlitePool,
    user_id: &str,
) -> Result<Vec<Tag>, sqlx::Error> {
    sqlx::query_as::<_, Tag>(
        "SELECT * FROM tags WHERE user_id = ? ORDER BY tag_type, name",
    )
    .bind(user_id)
    .fetch_all(pool)
    .await
}

pub async fn rename_tag(
    pool: &SqlitePool,
    tag_id: &str,
    user_id: &str,
    new_name: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        "UPDATE tags SET name = ? WHERE id = ? AND user_id = ?",
    )
    .bind(new_name)
    .bind(tag_id)
    .bind(user_id)
    .execute(pool)
    .await?;
    Ok(result.rows_affected() > 0)
}

pub async fn delete_tag(
    pool: &SqlitePool,
    tag_id: &str,
    user_id: &str,
) -> Result<bool, sqlx::Error> {
    let result = sqlx::query(
        "DELETE FROM tags WHERE id = ? AND user_id = ?",
    )
    .bind(tag_id)
    .bind(user_id)
    .execute(pool)
    .await?;
    Ok(result.rows_affected() > 0)
}

/// Fetch a tag by ID, enforcing ownership. Returns `None` when the tag does not
/// exist or belongs to a different user, preventing IDOR information leakage.
pub async fn get_tag(
    pool: &SqlitePool,
    tag_id: &str,
    user_id: &str,
) -> Result<Option<Tag>, sqlx::Error> {
    sqlx::query_as::<_, Tag>("SELECT * FROM tags WHERE id = ? AND user_id = ?")
        .bind(tag_id)
        .bind(user_id)
        .fetch_optional(pool)
        .await
}

pub async fn list_entries_for_tag(
    pool: &SqlitePool,
    tag_id: &str,
    user_id: &str,
    before: Option<&str>,
    limit: i64,
) -> Result<Vec<Entry>, sqlx::Error> {
    match before {
        Some(before_ts) => {
            sqlx::query_as::<_, Entry>(
                r#"SELECT e.* FROM entries e
                   JOIN entry_tags et ON et.entry_id = e.id
                   WHERE et.tag_id = ? AND e.user_id = ? AND e.created_at < ?
                   ORDER BY e.created_at DESC
                   LIMIT ?"#,
            )
            .bind(tag_id)
            .bind(user_id)
            .bind(before_ts)
            .bind(limit)
            .fetch_all(pool)
            .await
        }
        None => {
            sqlx::query_as::<_, Entry>(
                r#"SELECT e.* FROM entries e
                   JOIN entry_tags et ON et.entry_id = e.id
                   WHERE et.tag_id = ? AND e.user_id = ?
                   ORDER BY e.created_at DESC
                   LIMIT ?"#,
            )
            .bind(tag_id)
            .bind(user_id)
            .bind(limit)
            .fetch_all(pool)
            .await
        }
    }
}
