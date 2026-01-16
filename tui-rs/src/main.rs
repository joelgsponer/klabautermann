//! Klabautermann TUI - Nautical-themed terminal chat client.
//!
//! A Rust/Ratatui implementation with full parity to the Go/Bubble Tea version.

use clap::Parser;
use crossterm::{
    event::{
        DisableMouseCapture, EnableMouseCapture, KeyCode, KeyModifiers, MouseEventKind,
    },
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{backend::CrosstermBackend, Terminal};
use std::io;
use std::time::Duration;
use tokio::sync::mpsc;

mod app;
mod event;
mod theme;
mod ui;
mod ws;

use app::{App, ConnectionState};
use event::{AppEvent, EventHandler};
use ws::{ServerMessage, WsClient};

/// Klabautermann TUI - Nautical-themed PKM chat client.
#[derive(Parser)]
#[command(name = "klabautermann")]
#[command(version = "0.1.0")]
#[command(about = "Nautical-themed TUI for Klabautermann PKM")]
struct Cli {
    /// WebSocket URL of the backend
    #[arg(short, long, default_value = "ws://localhost:8765/ws/chat")]
    url: String,
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let cli = Cli::parse();

    // Setup terminal
    enable_raw_mode()?;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;

    // Run the application
    let result = run_app(&mut terminal, cli.url).await;

    // Restore terminal
    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        LeaveAlternateScreen,
        DisableMouseCapture
    )?;
    terminal.show_cursor()?;

    // Print farewell message
    println!("Fair winds and following seas, Captain!");

    result
}

/// Main application loop.
async fn run_app<B: ratatui::backend::Backend>(
    terminal: &mut Terminal<B>,
    ws_url: String,
) -> Result<(), Box<dyn std::error::Error>> {
    let mut app = App::new(ws_url.clone());

    // Setup event handler with 100ms tick rate
    let (mut events, event_tx) = EventHandler::new(Duration::from_millis(100));

    // Channel for WebSocket messages
    let (ws_msg_tx, mut ws_msg_rx) = mpsc::channel::<ServerMessage>(100);

    // Spawn WebSocket connection task
    let ws_event_tx = event_tx.clone();
    let ws_url_clone = ws_url.clone();
    let (client_tx, mut client_rx) = mpsc::channel::<WsClient>(1);

    tokio::spawn(async move {
        match WsClient::connect(&ws_url_clone, ws_msg_tx).await {
            Ok(client) => {
                let _ = ws_event_tx.send(AppEvent::Connected).await;
                let _ = client_tx.send(client).await;
            }
            Err(e) => {
                let _ = ws_event_tx.send(AppEvent::WsError(e.to_string())).await;
            }
        }
    });

    // Forward WebSocket messages to event channel
    let ws_forward_tx = event_tx.clone();
    tokio::spawn(async move {
        while let Some(msg) = ws_msg_rx.recv().await {
            if ws_forward_tx.send(AppEvent::WsMessage(msg)).await.is_err() {
                break;
            }
        }
        let _ = ws_forward_tx.send(AppEvent::Disconnected).await;
    });

    // Store WebSocket client when connected
    let mut ws_client: Option<WsClient> = None;

    // Main event loop
    loop {
        // Render the UI
        terminal.draw(|frame| ui::render(frame, &mut app))?;

        // Check for WebSocket client
        if ws_client.is_none() {
            if let Ok(client) = client_rx.try_recv() {
                ws_client = Some(client);
            }
        }

        // Handle events
        if let Some(event) = events.next().await {
            match event {
                AppEvent::Key(key) => {
                    // Global shortcuts (work in any mode)
                    match (key.modifiers, key.code) {
                        // Ctrl+C: Quit
                        (KeyModifiers::CONTROL, KeyCode::Char('c')) => {
                            app.quitting = true;
                            break;
                        }
                        // Ctrl+E: Toggle entity panel
                        (KeyModifiers::CONTROL, KeyCode::Char('e')) => {
                            app.toggle_entities();
                        }
                        // Ctrl+L: Clear chat
                        (KeyModifiers::CONTROL, KeyCode::Char('l')) => {
                            app.clear_messages();
                        }
                        _ => {
                            // Mode-specific key handling
                            match app.input_mode {
                                app::InputMode::Normal => {
                                    handle_normal_mode_key(&mut app, key);
                                }
                                app::InputMode::Insert => {
                                    handle_insert_mode_key(&mut app, key, &ws_client).await;
                                }
                            }
                        }
                    }
                }
                AppEvent::Mouse(mouse) => {
                    match mouse.kind {
                        MouseEventKind::ScrollUp => {
                            app.scroll_up(3);
                        }
                        MouseEventKind::ScrollDown => {
                            app.scroll_down(3);
                        }
                        _ => {}
                    }
                }
                AppEvent::Resize(w, h) => {
                    app.width = w;
                    app.height = h;
                    app.ready = true;
                }
                AppEvent::WsMessage(msg) => {
                    handle_ws_message(&mut app, msg);
                }
                AppEvent::Connected => {
                    app.connection_state = ConnectionState::Connected;
                    app.ready = true;
                }
                AppEvent::WsError(e) => {
                    app.connection_state = ConnectionState::Error(e);
                    app.ready = true;
                }
                AppEvent::Disconnected => {
                    app.connection_state = ConnectionState::Disconnected;
                }
                AppEvent::Tick => {
                    if app.waiting {
                        app.tick_loading();
                    }
                }
            }
        }

        if app.quitting {
            break;
        }
    }

    Ok(())
}

/// Handle incoming WebSocket messages.
fn handle_ws_message(app: &mut App, msg: ServerMessage) {
    match msg {
        ServerMessage::Status { content } => {
            app.loading_message = content;
        }
        ServerMessage::Response { content } => {
            app.add_bot_message(content);
            app.waiting = false;
        }
        ServerMessage::Entities { content } => {
            app.entities = content;
        }
        ServerMessage::Pong => {
            // Keep-alive acknowledgment
        }
        ServerMessage::Error { content } => {
            app.add_bot_message(format!("Error: {}", content));
            app.waiting = false;
        }
    }
}

/// Handle key events in Normal mode (vim-style navigation).
fn handle_normal_mode_key(app: &mut App, key: crossterm::event::KeyEvent) {
    use KeyCode::*;

    match key.code {
        // 'i' enters Insert mode
        Char('i') => {
            app.enter_insert_mode();
        }
        // Vim-style navigation
        Char('j') | Down => {
            app.scroll_down(1);
        }
        Char('k') | Up => {
            app.scroll_up(1);
        }
        // Page navigation
        Char('d') if key.modifiers == KeyModifiers::CONTROL => {
            app.scroll_down(10);
        }
        Char('u') if key.modifiers == KeyModifiers::CONTROL => {
            app.scroll_up(10);
        }
        PageDown => {
            app.scroll_down(10);
        }
        PageUp => {
            app.scroll_up(10);
        }
        // Jump to top/bottom
        Char('g') => {
            app.scroll_offset = 0;
            app.auto_scroll = false;
        }
        Char('G') => {
            app.scroll_to_bottom();
        }
        Home => {
            app.scroll_offset = 0;
            app.auto_scroll = false;
        }
        End => {
            app.scroll_to_bottom();
        }
        _ => {}
    }
}

/// Handle key events in Insert mode.
async fn handle_insert_mode_key(
    app: &mut App,
    key: crossterm::event::KeyEvent,
    ws_client: &Option<WsClient>,
) {
    use KeyCode::*;

    match key.code {
        // Escape enters Normal mode
        Esc => {
            app.enter_normal_mode();
            app.clear_kj_state();
        }
        // Check for 'kj' escape sequence
        Char(c) => {
            if app.check_kj_escape(c) {
                // 'kj' detected - enter normal mode and remove trailing 'k' from input
                app.enter_normal_mode();
                // Delete the 'k' that was just typed
                app.input.delete_char();
            } else {
                // Normal character input
                app.input.input(key);
            }
        }
        // Enter: Send message (if not waiting)
        Enter if !app.waiting => {
            let content = app.take_input();
            if !content.trim().is_empty() {
                app.add_user_message(content.clone());
                app.waiting = true;
                app.loading_index = 0;
                app.loading_message = theme::LOADING_MESSAGES[0].to_string();

                // Send via WebSocket
                if let Some(ref client) = ws_client {
                    client.send_chat(content, Some(app.thread_id.clone())).await;
                }
            }
        }
        // Other keys: pass to text input
        _ => {
            app.input.input(key);
        }
    }
}
