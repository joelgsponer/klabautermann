use anyhow::{Context, Result};

#[derive(Clone)]
pub struct Config {
    pub database_url: String,
    pub cookie_secret: Vec<u8>,
    pub openai_api_key: String,
    pub listen_addr: String,
    pub media_dir: String,
    pub gemini_api_key: Option<String>,
    pub secure_cookies: bool,
}

impl Config {
    pub fn from_env() -> Result<Self> {
        dotenvy::dotenv().ok();

        let cookie_secret_hex =
            std::env::var("COOKIE_SECRET").context("COOKIE_SECRET must be set")?;
        let cookie_secret =
            hex::decode(&cookie_secret_hex).unwrap_or_else(|_| cookie_secret_hex.into_bytes());

        Ok(Self {
            database_url: std::env::var("DATABASE_URL")
                .unwrap_or_else(|_| "sqlite:klabautermann.db?mode=rwc".into()),
            cookie_secret,
            openai_api_key: std::env::var("OPENAI_API_KEY").unwrap_or_default(),
            listen_addr: std::env::var("LISTEN_ADDR").unwrap_or_else(|_| "0.0.0.0:3000".into()),
            media_dir: std::env::var("MEDIA_DIR").unwrap_or_else(|_| "media".into()),
            gemini_api_key: std::env::var("GEMINI_API_KEY").ok(),
            secure_cookies: std::env::var("SECURE_COOKIES")
                .map(|v| v != "false")
                .unwrap_or(true),
        })
    }
}
