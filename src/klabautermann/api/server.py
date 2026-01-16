"""
FastAPI WebSocket server for Klabautermann.

Provides WebSocket endpoint for TUI clients to communicate with the orchestrator.
"""

import json
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect


app = FastAPI(title="Klabautermann API", version="0.1.0")

# Global orchestrator instance (set by start_api.py)
_orchestrator = None


def set_orchestrator(orchestrator: Any) -> None:
    """Set the global orchestrator instance."""
    global _orchestrator
    _orchestrator = orchestrator


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for chat communication."""
    await websocket.accept()

    try:
        while True:
            # Receive message from client
            data = await websocket.receive_text()

            try:
                message = json.loads(data)
                msg_type = message.get("type", "")

                if msg_type == "chat":
                    await handle_chat_message(websocket, message)
                elif msg_type == "ping":
                    await websocket.send_json({"type": "pong"})
                elif msg_type == "get_entities":
                    await handle_get_entities(websocket)
                else:
                    await websocket.send_json(
                        {"type": "error", "content": f"Unknown message type: {msg_type}"}
                    )

            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "content": "Invalid JSON"})

    except WebSocketDisconnect:
        pass


async def handle_chat_message(websocket: WebSocket, message: dict[str, Any]) -> None:
    """Handle incoming chat message."""
    content = message.get("content", "")
    thread_id = message.get("thread_id")

    if not content.strip():
        await websocket.send_json({"type": "error", "content": "Empty message"})
        return

    # Send status update
    await websocket.send_json({"type": "status", "content": "Processing your request..."})

    try:
        if _orchestrator is None:
            await websocket.send_json({"type": "error", "content": "Orchestrator not initialized"})
            return

        # Process through orchestrator
        response = await _orchestrator.handle_user_input_v2(
            text=content,
            thread_uuid=thread_id or "default",
        )

        # Send response
        await websocket.send_json({"type": "response", "content": response})

        # Send updated entities
        await handle_get_entities(websocket)

    except Exception as e:
        await websocket.send_json({"type": "error", "content": str(e)})


async def handle_get_entities(websocket: WebSocket) -> None:
    """Handle request for recent entities."""
    try:
        entities = await get_recent_entities()
        await websocket.send_json({"type": "entities", "content": entities})
    except Exception:
        # Silently fail - entities are optional
        await websocket.send_json({"type": "entities", "content": []})


async def get_recent_entities() -> list[dict[str, str]]:
    """Get recent entities from the knowledge graph."""
    if _orchestrator is None or _orchestrator.graphiti is None:
        return []

    try:
        # Try to get recent entities from Graphiti
        graphiti = _orchestrator.graphiti

        # Use search to find recent entities
        if hasattr(graphiti, "search"):
            results = await graphiti.search("*", limit=10)
            entities = []
            for node in results.get("nodes", [])[:5]:
                entities.append(
                    {
                        "uuid": node.get("uuid", ""),
                        "name": node.get("name", "Unknown"),
                        "type": node.get("labels", ["Entity"])[0]
                        if node.get("labels")
                        else "Entity",
                    }
                )
            return entities
    except Exception:
        pass

    return []
