use anyhow::{Context, Result};

#[derive(Clone)]
pub struct Config {
    pub database_url: String,
    pub cookie_secret: Vec<u8>,
    pub openai_api_key: String,
    pub listen_addr: String,
    pub media_dir: String,
    pub gemini_api_key: Option<String>,
    /// Whether to set the Secure flag on session cookies (default: true).
    /// Set SECURE_COOKIES=false only in development without TLS.
    pub secure_cookies: bool,
    /// Whether new user registration is permitted (default: false).
    /// Set ALLOW_REGISTRATION=true to enable open registration.
    pub allow_registration: bool,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        dotenvy::dotenv().ok();

        let cookie_secret_hex =
            std::env::var("COOKIE_SECRET").context("COOKIE_SECRET must be set")?;
        let cookie_secret =
            hex::decode(&cookie_secret_hex).context("COOKIE_SECRET must be valid hex")?;
        if cookie_secret.len() < 32 {
            anyhow::bail!("COOKIE_SECRET must decode to at least 32 bytes");
        }

        let openai_api_key = std::env::var("OPENAI_API_KEY").unwrap_or_default();
        if openai_api_key.is_empty() {
            tracing::warn!("OPENAI_API_KEY not set — transcription will be unavailable");
        }

        let secure_cookies = std::env::var("SECURE_COOKIES")
            .map(|v| v.to_lowercase() != "false")
            .unwrap_or(true);

        let allow_registration = std::env::var("ALLOW_REGISTRATION")
            .map(|v| v.to_lowercase() == "true")
            .unwrap_or(false);

        Ok(Self {
            database_url: std::env::var("DATABASE_URL")
                .unwrap_or_else(|_| "sqlite:klabautermann.db?mode=rwc".into()),
            cookie_secret,
            openai_api_key,
            listen_addr: std::env::var("LISTEN_ADDR").unwrap_or_else(|_| "0.0.0.0:3000".into()),
            media_dir: std::env::var("MEDIA_DIR").unwrap_or_else(|_| "media".into()),
            gemini_api_key: std::env::var("GEMINI_API_KEY").ok(),
            secure_cookies,
            allow_registration,
        })
    }
}
