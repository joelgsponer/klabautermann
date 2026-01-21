//! Main application state for Klabautermann TUI.

use arboard::Clipboard;
use chrono::{DateTime, Utc};
use serde::Serialize;
use std::fs;
use std::io::Write;
use std::path::PathBuf;
use std::process::Command;
use std::time::Instant;
use tui_textarea::TextArea;

use crate::commands::{CommandResult, CopyFormat};
use crate::theme::LOADING_MESSAGES;
use crate::ws::Entity;

/// Connection state for WebSocket.
#[derive(Debug, Clone, PartialEq)]
pub enum ConnectionState {
    Connecting,
    Connected,
    Disconnected,
    Error(String),
}

/// Vim-style input mode.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum InputMode {
    /// Normal mode: scroll, navigate (Esc or kj to enter)
    Normal,
    /// Insert mode: type messages (i to enter)
    Insert,
}

/// A chat message in the history.
#[derive(Debug, Clone, Serialize)]
pub struct ChatMessage {
    /// True if this is a user message, false for bot
    pub is_user: bool,
    /// Message content
    pub content: String,
    /// When the message was received
    pub timestamp: DateTime<Utc>,
}

/// JSON-serializable message format for export.
#[derive(Debug, Serialize)]
struct ExportMessage {
    role: String,
    content: String,
    timestamp: String,
}

/// Main application state.
pub struct App {
    // Connection state
    pub ws_url: String,
    pub connection_state: ConnectionState,

    // Terminal dimensions
    pub width: u16,
    pub height: u16,

    // UI state flags
    pub ready: bool,
    pub quitting: bool,
    pub waiting: bool,

    // Chat state
    pub messages: Vec<ChatMessage>,
    pub input: TextArea<'static>,
    pub scroll_offset: usize,
    pub auto_scroll: bool,
    pub total_lines: usize,
    pub viewport_height: usize,

    // Vim mode
    pub input_mode: InputMode,
    pub last_key: Option<char>,
    pub last_key_time: Option<Instant>,

    // Entity state
    pub entities: Vec<Entity>,
    pub show_entities: bool,

    // Loading animation
    pub loading_message: String,
    pub loading_index: usize,
    pub spinner_frame: usize,

    // Thread ID for conversation
    pub thread_id: String,
}

impl App {
    /// Create a new App with the given WebSocket URL.
    pub fn new(ws_url: String) -> Self {
        let mut input = TextArea::default();
        input.set_placeholder_text("Type your message...");

        let thread_id = format!("tui-{}", uuid::Uuid::new_v4());

        Self {
            ws_url,
            connection_state: ConnectionState::Connecting,
            width: 80,
            height: 24,
            ready: false,
            quitting: false,
            waiting: false,
            messages: Vec::new(),
            input,
            scroll_offset: 0,
            auto_scroll: true,
            total_lines: 0,
            viewport_height: 10,
            input_mode: InputMode::Insert,
            last_key: None,
            last_key_time: None,
            entities: Vec::new(),
            show_entities: true,
            loading_message: LOADING_MESSAGES[0].to_string(),
            loading_index: 0,
            spinner_frame: 0,
            thread_id,
        }
    }

    /// Add a user message to the chat.
    pub fn add_user_message(&mut self, content: String) {
        self.messages.push(ChatMessage {
            is_user: true,
            content,
            timestamp: Utc::now(),
        });
    }

    /// Add a bot message to the chat.
    pub fn add_bot_message(&mut self, content: String) {
        self.messages.push(ChatMessage {
            is_user: false,
            content,
            timestamp: Utc::now(),
        });
    }

    /// Clear the chat history.
    pub fn clear_messages(&mut self) {
        self.messages.clear();
        self.scroll_offset = 0;
        self.auto_scroll = true;
    }

    /// Scroll up by n lines.
    pub fn scroll_up(&mut self, lines: usize) {
        self.scroll_offset = self.scroll_offset.saturating_sub(lines);
        self.auto_scroll = false;
    }

    /// Scroll down by n lines.
    pub fn scroll_down(&mut self, lines: usize) {
        let max_scroll = self.total_lines.saturating_sub(self.viewport_height);
        self.scroll_offset = (self.scroll_offset + lines).min(max_scroll);
        // Re-enable auto-scroll if at bottom
        if self.scroll_offset >= max_scroll {
            self.auto_scroll = true;
        }
    }

    /// Scroll to bottom and enable auto-scroll.
    pub fn scroll_to_bottom(&mut self) {
        let max_scroll = self.total_lines.saturating_sub(self.viewport_height);
        self.scroll_offset = max_scroll;
        self.auto_scroll = true;
    }

    /// Update scroll state based on content.
    pub fn update_scroll(&mut self, total_lines: usize, viewport_height: usize) {
        self.total_lines = total_lines;
        self.viewport_height = viewport_height;
        if self.auto_scroll {
            self.scroll_offset = total_lines.saturating_sub(viewport_height);
        }
    }

    /// Toggle the entity panel visibility.
    pub fn toggle_entities(&mut self) {
        self.show_entities = !self.show_entities;
    }

    /// Enter normal mode (for scrolling/navigation).
    pub fn enter_normal_mode(&mut self) {
        self.input_mode = InputMode::Normal;
    }

    /// Enter insert mode (for typing).
    pub fn enter_insert_mode(&mut self) {
        self.input_mode = InputMode::Insert;
        self.scroll_to_bottom();
    }

    /// Check if 'k' followed quickly by 'j' was pressed (vim escape).
    /// Returns true if we should enter normal mode.
    pub fn check_kj_escape(&mut self, key: char) -> bool {
        let now = Instant::now();

        if key == 'j' {
            if let (Some('k'), Some(time)) = (self.last_key, self.last_key_time) {
                // Check if 'k' was pressed within 200ms
                if now.duration_since(time).as_millis() < 200 {
                    self.last_key = None;
                    self.last_key_time = None;
                    return true;
                }
            }
        }

        self.last_key = Some(key);
        self.last_key_time = Some(now);
        false
    }

    /// Clear the kj tracking state.
    pub fn clear_kj_state(&mut self) {
        self.last_key = None;
        self.last_key_time = None;
    }

    /// Update loading animation state.
    pub fn tick_loading(&mut self) {
        self.spinner_frame = (self.spinner_frame + 1) % crate::theme::SPINNER_FRAMES.len();

        // Rotate loading message every ~20 ticks (2 seconds at 100ms tick rate)
        if self.spinner_frame % 20 == 0 {
            self.loading_index = (self.loading_index + 1) % LOADING_MESSAGES.len();
            self.loading_message = LOADING_MESSAGES[self.loading_index].to_string();
        }
    }

    /// Get the current input text and clear the input.
    pub fn take_input(&mut self) -> String {
        let lines: Vec<String> = self.input.lines().iter().map(|s| s.to_string()).collect();
        let content = lines.join("\n");
        // Clear the input
        self.input.select_all();
        self.input.delete_char();
        content
    }

    // =========================================================================
    // Copy Command Handlers
    // =========================================================================

    /// Handle the /copy command to export messages.
    pub fn handle_copy_command(&self, count: usize, format: CopyFormat) -> CommandResult {
        if self.messages.is_empty() {
            return CommandResult::Error("No messages to copy.".to_string());
        }

        // Get last N messages
        let start = self.messages.len().saturating_sub(count);
        let messages = &self.messages[start..];
        let actual_count = messages.len();

        // Format messages
        let content = self.format_messages(messages, format);

        // Try export destinations in order: clipboard -> neovim -> file
        if self.try_clipboard(&content) {
            return CommandResult::Success(format!(
                "Copied {} message(s) to clipboard",
                actual_count
            ));
        }

        if let Some(path) = self.try_neovim(&content, format) {
            return CommandResult::Success(format!(
                "Exported {} message(s) to neovim: {}",
                actual_count, path
            ));
        }

        match self.export_to_file(&content, format) {
            Ok(path) => CommandResult::Success(format!(
                "Exported {} message(s) to {}",
                actual_count, path
            )),
            Err(e) => CommandResult::Error(format!("Failed to export: {}", e)),
        }
    }

    /// Format messages according to the specified format.
    fn format_messages(&self, messages: &[ChatMessage], format: CopyFormat) -> String {
        match format {
            CopyFormat::Markdown => self.format_markdown(messages),
            CopyFormat::Plain => self.format_plain(messages),
            CopyFormat::Json => self.format_json(messages),
        }
    }

    /// Format messages as Markdown.
    fn format_markdown(&self, messages: &[ChatMessage]) -> String {
        messages
            .iter()
            .map(|msg| {
                let role = if msg.is_user { "User" } else { "Assistant" };
                let timestamp = msg.timestamp.format("%Y-%m-%d %H:%M:%S");
                format!("## {} ({})\n\n{}", role, timestamp, msg.content)
            })
            .collect::<Vec<_>>()
            .join("\n\n---\n\n")
    }

    /// Format messages as plain text.
    fn format_plain(&self, messages: &[ChatMessage]) -> String {
        messages
            .iter()
            .map(|msg| {
                let label = if msg.is_user {
                    "You"
                } else {
                    "Klabautermann"
                };
                format!("[{}] {}", label, msg.content)
            })
            .collect::<Vec<_>>()
            .join("\n\n")
    }

    /// Format messages as JSON.
    fn format_json(&self, messages: &[ChatMessage]) -> String {
        let export_messages: Vec<ExportMessage> = messages
            .iter()
            .map(|msg| ExportMessage {
                role: if msg.is_user {
                    "user".to_string()
                } else {
                    "assistant".to_string()
                },
                content: msg.content.clone(),
                timestamp: msg.timestamp.to_rfc3339(),
            })
            .collect();

        serde_json::to_string_pretty(&export_messages).unwrap_or_else(|_| "[]".to_string())
    }

    /// Try to copy content to system clipboard.
    fn try_clipboard(&self, content: &str) -> bool {
        match Clipboard::new() {
            Ok(mut clipboard) => clipboard.set_text(content).is_ok(),
            Err(_) => false,
        }
    }

    /// Try to export to neovim buffer via temp file.
    fn try_neovim(&self, content: &str, format: CopyFormat) -> Option<String> {
        // Check if nvim is available
        if Command::new("which")
            .arg("nvim")
            .output()
            .map(|o| o.status.success())
            .unwrap_or(false)
        {
            // Create temp file
            let ext = format.extension();
            let temp_path = std::env::temp_dir().join(format!(
                "klabautermann_export_{}{}",
                uuid::Uuid::new_v4(),
                ext
            ));

            if let Ok(mut file) = fs::File::create(&temp_path) {
                if file.write_all(content.as_bytes()).is_ok() {
                    // Open in nvim (non-blocking)
                    let path_str = temp_path.to_string_lossy().to_string();
                    if Command::new("nvim").arg(&path_str).spawn().is_ok() {
                        return Some(path_str);
                    }
                }
            }
        }
        None
    }

    /// Export content to a file in the exports directory.
    fn export_to_file(&self, content: &str, format: CopyFormat) -> Result<String, String> {
        // Get export directory
        let export_dir = self.get_export_dir()?;

        // Create filename with timestamp
        let timestamp = Utc::now().format("%Y%m%d_%H%M%S");
        let ext = format.extension();
        let filename = format!("conversation_{}{}", timestamp, ext);
        let filepath = export_dir.join(filename);

        // Write file
        fs::write(&filepath, content).map_err(|e| format!("Write failed: {}", e))?;

        Ok(filepath.to_string_lossy().to_string())
    }

    /// Get or create the exports directory.
    fn get_export_dir(&self) -> Result<PathBuf, String> {
        let export_dir = dirs::home_dir()
            .ok_or("Could not find home directory")?
            .join(".klabautermann")
            .join("exports");

        fs::create_dir_all(&export_dir).map_err(|e| format!("Could not create export dir: {}", e))?;

        Ok(export_dir)
    }

    /// Get connection status as a formatted string.
    pub fn status_text(&self) -> String {
        let conn_status = match &self.connection_state {
            ConnectionState::Connecting => "Connecting...".to_string(),
            ConnectionState::Connected => "Connected".to_string(),
            ConnectionState::Disconnected => "Disconnected".to_string(),
            ConnectionState::Error(e) => format!("Error: {}", e),
        };

        format!(
            "Connection: {}\nThread ID: {}\nMessages: {}\nEntities: {}",
            conn_status,
            self.thread_id,
            self.messages.len(),
            self.entities.len()
        )
    }
}
