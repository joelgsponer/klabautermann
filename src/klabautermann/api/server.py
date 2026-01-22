"""
FastAPI WebSocket server for Klabautermann.

Provides WebSocket endpoint for TUI clients to communicate with the orchestrator.
Exposes Prometheus metrics at /metrics endpoint.
"""

import json
import time
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect

from klabautermann.core.metrics import (
    decrement_websocket_connections,
    get_metrics,
    increment_websocket_connections,
    record_api_latency,
    record_api_request,
)


app = FastAPI(title="Klabautermann API", version="0.1.0")

# Global orchestrator instance (set by start_api.py)
_orchestrator = None


def set_orchestrator(orchestrator: Any) -> None:
    """Set the global orchestrator instance."""
    global _orchestrator
    _orchestrator = orchestrator


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
    """Middleware to record API request metrics."""
    start_time = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - start_time

    # Skip metrics endpoint to avoid recursion
    if request.url.path != "/metrics":
        record_api_request(
            method=request.method,
            endpoint=request.url.path,
            status_code=response.status_code,
        )
        record_api_latency(
            method=request.method,
            endpoint=request.url.path,
            latency_seconds=elapsed,
        )

    return response


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "healthy"}


@app.get("/metrics")
async def metrics_endpoint() -> Response:
    """
    Prometheus metrics endpoint.

    Returns metrics in Prometheus text exposition format.
    """
    return Response(
        content=get_metrics(),
        media_type="text/plain; version=0.0.4; charset=utf-8",
    )


@app.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """WebSocket endpoint for chat communication."""
    await websocket.accept()
    increment_websocket_connections()

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
    finally:
        decrement_websocket_connections()


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

        # Process through orchestrator (handle_user_input creates thread first)
        response = await _orchestrator.handle_user_input(
            thread_id=thread_id or "default",
            text=content,
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
