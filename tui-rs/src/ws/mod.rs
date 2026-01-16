//! WebSocket module for backend communication.

mod client;
mod messages;

pub use client::WsClient;
pub use messages::{ClientMessage, Entity, ServerMessage};
