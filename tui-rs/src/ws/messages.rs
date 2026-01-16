//! WebSocket message types.

use serde::{Deserialize, Serialize};

/// Messages sent from client to server.
#[derive(Debug, Clone, Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    /// Chat message
    Chat {
        content: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        thread_id: Option<String>,
    },
    /// Ping for keep-alive
    Ping,
    /// Request entity list
    GetEntities,
}

/// Messages received from server.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    /// Status update during processing
    Status { content: String },
    /// Final response
    Response { content: String },
    /// Entity list update
    Entities { content: Vec<Entity> },
    /// Pong response to ping
    Pong,
    /// Error message
    Error { content: String },
}

/// Entity from knowledge graph.
#[derive(Debug, Clone, Deserialize)]
pub struct Entity {
    /// Unique identifier
    pub uuid: String,
    /// Entity name
    pub name: String,
    /// Entity type (Person, Organization, etc.)
    #[serde(rename = "type")]
    pub entity_type: String,
}
