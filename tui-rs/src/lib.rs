//! Klabautermann TUI library.
//!
//! This module exports the core components for testing.

pub mod app;
pub mod commands;
pub mod event;
pub mod theme;
pub mod ui;
pub mod ws;

pub use app::{App, ChatMessage, ConnectionState, InputMode};
pub use commands::{Command, CommandResult, CopyFormat};
