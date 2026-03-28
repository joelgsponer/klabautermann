use tracing::error;

/// Call the Google Gemini API to generate text content.
pub async fn call_gemini_api(api_key: &str, prompt: &str) -> anyhow::Result<String> {
    let client = reqwest::Client::new();

    let url = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent";

    let body = serde_json::json!({
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    });

    let response = client
        .post(url)
        .header("x-goog-api-key", api_key)
        .json(&body)
        .send()
        .await?;

    if !response.status().is_success() {
        let status = response.status();
        let body = response.text().await.unwrap_or_default();
        error!(status = %status, "Gemini API error");
        anyhow::bail!("Gemini API error {}: {}", status, body);
    }

    #[derive(serde::Deserialize)]
    struct GeminiResponse {
        candidates: Vec<Candidate>,
    }

    #[derive(serde::Deserialize)]
    struct Candidate {
        content: Content,
    }

    #[derive(serde::Deserialize)]
    struct Content {
        parts: Vec<Part>,
    }

    #[derive(serde::Deserialize)]
    struct Part {
        text: String,
    }

    let resp: GeminiResponse = response.json().await?;
    let text = resp
        .candidates
        .first()
        .and_then(|c| c.content.parts.first())
        .map(|p| p.text.clone())
        .ok_or_else(|| anyhow::anyhow!("Empty response from Gemini"))?;

    Ok(text)
}

/// Build a prompt from the day's entries and their associated tags.
pub fn build_summary_prompt(
    entries: &[(String, String, Option<String>, Option<String>)],
    tags: &[(String, String)],
) -> String {
    let mut prompt = String::from(
        "You are a personal journal summariser. Below are all the log entries for a single day. \
         Write a concise, reflective daily summary in 2-4 paragraphs. Highlight key themes, \
         activities, and any notable patterns. Write in second person (\"you\"). \
         Do not include a title or heading — just the summary text.\n\n\
         IMPORTANT: Preserve ALL specific names, @mentions, #tags, project names, places, \
         and concrete details exactly as they appear. Never generalise a named person into \
         \"a colleague\" or \"someone\" — use their actual name or @mention. Never generalise \
         a named project into \"a project\" — use its actual name. Specific details are what \
         make a journal entry valuable.\n\n"
    );

    if !tags.is_empty() {
        prompt.push_str("Entities referenced today:\n");
        for (name, tag_type) in tags {
            let sigil = if tag_type == "person" { "@" } else { "#" };
            prompt.push_str(&format!("- {}{}\n", sigil, name));
        }
        prompt.push_str("\nMake sure all of these entities appear in the summary where relevant.\n\n");
    }

    prompt.push_str("---\n\n");

    for (entry_type, created_at, content, transcript) in entries {
        // Extract time portion
        let time = created_at
            .get(11..16)
            .unwrap_or(created_at.as_str());

        let text = match entry_type.as_str() {
            "text" => content.as_deref().unwrap_or(""),
            _ => transcript
                .as_deref()
                .or(content.as_deref())
                .unwrap_or("[no text]"),
        };

        // Truncate very long entries to keep prompt manageable
        let text = if text.len() > 1000 {
            &text[..1000]
        } else {
            text
        };

        prompt.push_str(&format!("[{} — {}] {}\n\n", time, entry_type, text));
    }

    prompt
}
