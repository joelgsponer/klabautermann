//! WebSocket client for backend communication.

use futures_util::{SinkExt, StreamExt};
use tokio::sync::mpsc;
use tokio_tungstenite::{connect_async, tungstenite::Message};

use super::messages::{ClientMessage, ServerMessage};

/// WebSocket client handle.
#[derive(Clone)]
pub struct WsClient {
    tx: mpsc::Sender<ClientMessage>,
}

/// Error type for WebSocket operations.
#[derive(Debug)]
pub struct WsError(String);

impl std::fmt::Display for WsError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "WebSocket error: {}", self.0)
    }
}

impl std::error::Error for WsError {}

impl WsClient {
    /// Connect to WebSocket server and spawn message handling tasks.
    pub async fn connect(
        url: &str,
        msg_tx: mpsc::Sender<ServerMessage>,
    ) -> Result<Self, WsError> {
        let (ws_stream, _) = connect_async(url)
            .await
            .map_err(|e| WsError(e.to_string()))?;

        let (mut write, mut read) = ws_stream.split();

        // Channel for outgoing messages
        let (tx, mut rx) = mpsc::channel::<ClientMessage>(100);

        // Spawn task to send messages
        tokio::spawn(async move {
            while let Some(msg) = rx.recv().await {
                let json = match serde_json::to_string(&msg) {
                    Ok(j) => j,
                    Err(_) => continue,
                };
                if write.send(Message::Text(json.into())).await.is_err() {
                    break;
                }
            }
        });

        // Spawn task to receive messages
        tokio::spawn(async move {
            while let Some(Ok(msg)) = read.next().await {
                if let Message::Text(text) = msg {
                    if let Ok(server_msg) = serde_json::from_str::<ServerMessage>(&text) {
                        if msg_tx.send(server_msg).await.is_err() {
                            break;
                        }
                    }
                }
            }
        });

        Ok(Self { tx })
    }

    /// Send a chat message.
    pub async fn send_chat(&self, content: String, thread_id: Option<String>) {
        let msg = ClientMessage::Chat { content, thread_id };
        let _ = self.tx.send(msg).await;
    }

    /// Send a ping message.
    pub async fn send_ping(&self) {
        let _ = self.tx.send(ClientMessage::Ping).await;
    }

    /// Request entity list.
    pub async fn send_get_entities(&self) {
        let _ = self.tx.send(ClientMessage::GetEntities).await;
    }
}
