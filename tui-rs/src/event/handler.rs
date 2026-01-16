//! Event handler for terminal and application events.

use crossterm::event::{Event, EventStream, KeyEvent, MouseEvent};
use futures_util::StreamExt;
use std::time::Duration;
use tokio::sync::mpsc;
use tokio::time::interval;

use crate::ws::ServerMessage;

/// Application events.
#[derive(Debug)]
pub enum AppEvent {
    /// Keyboard input
    Key(KeyEvent),
    /// Mouse input
    Mouse(MouseEvent),
    /// Terminal resize
    Resize(u16, u16),
    /// WebSocket message received
    WsMessage(ServerMessage),
    /// WebSocket connected
    Connected,
    /// WebSocket error
    WsError(String),
    /// WebSocket disconnected
    Disconnected,
    /// Tick for animations
    Tick,
}

/// Event handler that merges terminal and async events.
pub struct EventHandler {
    rx: mpsc::Receiver<AppEvent>,
}

impl EventHandler {
    /// Create a new event handler with the given tick rate.
    pub fn new(tick_rate: Duration) -> (Self, mpsc::Sender<AppEvent>) {
        let (tx, rx) = mpsc::channel(100);

        // Spawn terminal event reader
        let term_tx = tx.clone();
        tokio::spawn(async move {
            let mut reader = EventStream::new();
            while let Some(Ok(event)) = reader.next().await {
                let app_event = match event {
                    Event::Key(key) => AppEvent::Key(key),
                    Event::Mouse(mouse) => AppEvent::Mouse(mouse),
                    Event::Resize(w, h) => AppEvent::Resize(w, h),
                    _ => continue,
                };
                if term_tx.send(app_event).await.is_err() {
                    break;
                }
            }
        });

        // Spawn tick timer
        let tick_tx = tx.clone();
        tokio::spawn(async move {
            let mut ticker = interval(tick_rate);
            loop {
                ticker.tick().await;
                if tick_tx.send(AppEvent::Tick).await.is_err() {
                    break;
                }
            }
        });

        (Self { rx }, tx)
    }

    /// Get the next event.
    pub async fn next(&mut self) -> Option<AppEvent> {
        self.rx.recv().await
    }
}
