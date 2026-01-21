//! Command parsing and handling for slash commands.
//!
//! Supports local commands like /copy, /clear, /help that are processed
//! client-side without being sent to the backend.

use regex::Regex;
use std::sync::LazyLock;

/// Output format for the /copy command.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub enum CopyFormat {
    #[default]
    Markdown,
    Plain,
    Json,
}

impl CopyFormat {
    /// Parse format from string, defaulting to Markdown.
    pub fn from_str(s: &str) -> Self {
        match s.to_lowercase().as_str() {
            "plain" | "text" | "txt" => Self::Plain,
            "json" => Self::Json,
            _ => Self::Markdown,
        }
    }

    /// Get file extension for this format.
    pub fn extension(&self) -> &'static str {
        match self {
            Self::Markdown => ".md",
            Self::Plain => ".txt",
            Self::Json => ".json",
        }
    }
}

/// Result of executing a command.
#[derive(Debug, Clone)]
pub enum CommandResult {
    /// Command succeeded with a message to display
    Success(String),
    /// Command failed with an error message
    Error(String),
    /// No action needed (e.g., help displayed)
    None,
}

/// Parsed command from user input.
#[derive(Debug, Clone, PartialEq)]
pub enum Command {
    /// Copy last N messages with optional format
    Copy { count: usize, format: CopyFormat },
    /// Clear chat history
    Clear,
    /// Show help
    Help,
    /// Show status
    Status,
    /// Not a command - should be sent to backend
    NotACommand,
}

// Regex for parsing /copy command
static COPY_REGEX: LazyLock<Regex> = LazyLock::new(|| {
    Regex::new(r"^/(?:copy|export)(?:\s+(\d+))?(?:\s+--format=(\w+))?$").unwrap()
});

impl Command {
    /// Parse a command from user input.
    ///
    /// Returns `Command::NotACommand` if the input is not a recognized command.
    pub fn parse(input: &str) -> Self {
        let trimmed = input.trim();
        let lower = trimmed.to_lowercase();

        // Check for simple commands first
        match lower.as_str() {
            "/clear" | "clear" => return Self::Clear,
            "/help" | "help" | "?" => return Self::Help,
            "/status" | "status" => return Self::Status,
            _ => {}
        }

        // Check for /copy command with optional arguments
        if let Some(caps) = COPY_REGEX.captures(&lower) {
            let count = caps
                .get(1)
                .map(|m| m.as_str().parse().unwrap_or(1))
                .unwrap_or(1);
            let format = caps
                .get(2)
                .map(|m| CopyFormat::from_str(m.as_str()))
                .unwrap_or_default();

            // Validate count
            let count = count.clamp(1, 1000);

            return Self::Copy { count, format };
        }

        // Check if it looks like a command but wasn't recognized
        if trimmed.starts_with('/') {
            // Could provide helpful error, but for now treat as not a command
            // This allows custom slash commands to be sent to backend
        }

        Self::NotACommand
    }

    /// Check if this is a local command (not to be sent to backend).
    pub fn is_local(&self) -> bool {
        !matches!(self, Self::NotACommand)
    }
}

/// Generate help text for available commands.
pub fn help_text() -> String {
    r#"Available Commands:
  /copy [N] [--format=TYPE]  Copy last N messages (default: 1)
                             Formats: markdown (default), plain, json
  /clear                     Clear chat history
  /status                    Show connection status
  /help                      Show this help

Keyboard Shortcuts:
  Ctrl+C    Quit
  Ctrl+E    Toggle entity panel
  Ctrl+L    Clear chat
  Esc / kj  Enter normal mode (for scrolling)
  i         Enter insert mode (for typing)

Navigation (Normal Mode):
  j/k       Scroll down/up
  g/G       Jump to top/bottom
  Ctrl+D/U  Page down/up"#
        .to_string()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_copy_basic() {
        assert_eq!(
            Command::parse("/copy"),
            Command::Copy {
                count: 1,
                format: CopyFormat::Markdown
            }
        );
    }

    #[test]
    fn test_parse_copy_with_count() {
        assert_eq!(
            Command::parse("/copy 5"),
            Command::Copy {
                count: 5,
                format: CopyFormat::Markdown
            }
        );
    }

    #[test]
    fn test_parse_copy_with_format() {
        assert_eq!(
            Command::parse("/copy --format=json"),
            Command::Copy {
                count: 1,
                format: CopyFormat::Json
            }
        );
    }

    #[test]
    fn test_parse_copy_full() {
        assert_eq!(
            Command::parse("/copy 10 --format=plain"),
            Command::Copy {
                count: 10,
                format: CopyFormat::Plain
            }
        );
    }

    #[test]
    fn test_parse_export_alias() {
        assert_eq!(
            Command::parse("/export 3"),
            Command::Copy {
                count: 3,
                format: CopyFormat::Markdown
            }
        );
    }

    #[test]
    fn test_parse_clear() {
        assert_eq!(Command::parse("/clear"), Command::Clear);
        assert_eq!(Command::parse("clear"), Command::Clear);
    }

    #[test]
    fn test_parse_help() {
        assert_eq!(Command::parse("/help"), Command::Help);
        assert_eq!(Command::parse("help"), Command::Help);
        assert_eq!(Command::parse("?"), Command::Help);
    }

    #[test]
    fn test_parse_status() {
        assert_eq!(Command::parse("/status"), Command::Status);
    }

    #[test]
    fn test_parse_not_a_command() {
        assert_eq!(Command::parse("hello world"), Command::NotACommand);
        assert_eq!(Command::parse(""), Command::NotACommand);
    }

    #[test]
    fn test_parse_case_insensitive() {
        assert_eq!(
            Command::parse("/COPY 5"),
            Command::Copy {
                count: 5,
                format: CopyFormat::Markdown
            }
        );
        assert_eq!(Command::parse("/CLEAR"), Command::Clear);
    }

    #[test]
    fn test_count_clamped() {
        // Very large count should be clamped to 1000
        let cmd = Command::parse("/copy 999999");
        assert_eq!(
            cmd,
            Command::Copy {
                count: 1000,
                format: CopyFormat::Markdown
            }
        );
    }

    #[test]
    fn test_format_extension() {
        assert_eq!(CopyFormat::Markdown.extension(), ".md");
        assert_eq!(CopyFormat::Plain.extension(), ".txt");
        assert_eq!(CopyFormat::Json.extension(), ".json");
    }

    #[test]
    fn test_is_local() {
        assert!(Command::Copy {
            count: 1,
            format: CopyFormat::Markdown
        }
        .is_local());
        assert!(Command::Clear.is_local());
        assert!(Command::Help.is_local());
        assert!(!Command::NotACommand.is_local());
    }
}
