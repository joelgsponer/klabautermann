//! Nautical theme colors and styles.

use ratatui::style::{Color, Modifier, Style};

/// Nautical color palette.
pub mod colors {
    use ratatui::style::Color;

    pub const DEEP_SEA: Color = Color::Rgb(10, 22, 40);
    pub const WAVE_BLUE: Color = Color::Rgb(52, 152, 219);
    pub const SEAFOAM: Color = Color::Rgb(26, 188, 156);
    pub const CORAL: Color = Color::Rgb(231, 76, 60);
    pub const AMBER: Color = Color::Rgb(243, 156, 18);
    pub const SAND: Color = Color::Rgb(245, 245, 220);
    pub const MIST: Color = Color::Rgb(189, 195, 199);
}

/// Pre-built styles for UI elements.
pub struct Styles;

impl Styles {
    /// Style for user message labels.
    pub fn user_label() -> Style {
        Style::default()
            .fg(colors::SEAFOAM)
            .add_modifier(Modifier::BOLD)
    }

    /// Style for bot message labels.
    pub fn bot_label() -> Style {
        Style::default()
            .fg(colors::WAVE_BLUE)
            .add_modifier(Modifier::BOLD)
    }

    /// Style for message content.
    pub fn message() -> Style {
        Style::default().fg(colors::SAND)
    }

    /// Style for help text.
    pub fn help() -> Style {
        Style::default().fg(colors::MIST)
    }

    /// Style for error messages.
    pub fn error() -> Style {
        Style::default()
            .fg(colors::CORAL)
            .add_modifier(Modifier::BOLD)
    }

    /// Style for loading spinner.
    pub fn spinner() -> Style {
        Style::default()
            .fg(colors::AMBER)
            .add_modifier(Modifier::BOLD)
    }

    /// Style for loading text.
    pub fn loading() -> Style {
        Style::default().fg(colors::MIST)
    }

    /// Style for dividers.
    pub fn divider() -> Style {
        Style::default().fg(colors::WAVE_BLUE)
    }

    /// Style for input prompt.
    pub fn input_prompt() -> Style {
        Style::default()
            .fg(colors::SEAFOAM)
            .add_modifier(Modifier::BOLD)
    }

    /// Style for connection status - connected.
    pub fn status_connected() -> Style {
        Style::default().fg(colors::SEAFOAM)
    }

    /// Style for connection status - disconnected/error.
    pub fn status_error() -> Style {
        Style::default().fg(colors::CORAL)
    }

    /// Style for entity icons.
    pub fn entity_icon() -> Style {
        Style::default().fg(colors::AMBER)
    }
}

/// Spinner animation frames.
pub const SPINNER_FRAMES: &[&str] = &["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

/// Rotating loading messages.
pub const LOADING_MESSAGES: &[&str] = &[
    "Charting course...",
    "Consulting the compass...",
    "Scanning the horizon...",
    "Checking the rigging...",
    "Reading the stars...",
    "Adjusting the sails...",
    "Plotting coordinates...",
    "Measuring the depths...",
];

/// Entity type icons.
pub mod icons {
    pub const PERSON: &str = "👤";
    pub const ORGANIZATION: &str = "🏢";
    pub const PROJECT: &str = "📋";
    pub const CONCEPT: &str = "💡";
    pub const LOCATION: &str = "📍";
    pub const EVENT: &str = "📅";
    pub const DEFAULT: &str = "📌";
}

/// Get icon for entity type.
pub fn entity_icon(entity_type: &str) -> &'static str {
    match entity_type.to_lowercase().as_str() {
        "person" => icons::PERSON,
        "organization" | "org" | "company" => icons::ORGANIZATION,
        "project" => icons::PROJECT,
        "concept" | "idea" => icons::CONCEPT,
        "location" | "place" => icons::LOCATION,
        "event" => icons::EVENT,
        _ => icons::DEFAULT,
    }
}
