use tracing::error;

/// Call the Google Gemini API to generate text content.
pub async fn call_gemini_api(api_key: &str, prompt: &str) -> anyhow::Result<String> {
    let client = reqwest::Client::new();

    let url = format!(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={}",
        api_key
    );

    let body = serde_json::json!({
        "contents": [{
            "parts": [{
                "text": prompt
            }]
        }]
    });

    let response = client
        .post(&url)
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

/// Build a prompt from the day's entries.
pub fn build_summary_prompt(entries: &[(String, String, Option<String>, Option<String>)]) -> String {
    let mut prompt = String::from(
        "You are a personal journal summariser. Below are all the log entries for a single day. \
         Write a concise, reflective daily summary in 2-4 paragraphs. Highlight key themes, \
         activities, and any notable patterns. Write in second person (\"you\"). \
         Do not include a title or heading — just the summary text.\n\n\
         ---\n\n"
    );

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
