"""
FastAPI server for Klabautermann.

Provides:
- WebSocket endpoint for TUI clients to communicate with the orchestrator.
- Server-rendered web UI (timeline / captain's log) using Jinja2 templates.
- REST endpoint for tag autocomplete suggestions.
- Prometheus metrics at /metrics endpoint.
"""

import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Query, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from klabautermann.core.logger import logger
from klabautermann.core.metrics import (
    decrement_websocket_connections,
    get_metrics,
    increment_websocket_connections,
    record_api_latency,
    record_api_request,
)


# Resolve paths relative to the repository root so the server works regardless
# of the current working directory when launched.
# __file__ = src/klabautermann/api/server.py → 4 parents up = repo root
_REPO_ROOT = Path(__file__).parent.parent.parent.parent
_STATIC_DIR = _REPO_ROOT / "static"
_TEMPLATES_DIR = _REPO_ROOT / "templates"

app = FastAPI(title="Klabautermann API", version="0.1.0")

# Static assets (CSS, JS)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

# Jinja2 templates
templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

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


@app.get("/", response_class=HTMLResponse)
async def timeline_page(request: Request) -> HTMLResponse:
    """Render the Captain's Log timeline web UI."""
    return templates.TemplateResponse(request, "timeline.html")


@app.get("/api/tags/suggestions")
async def tag_suggestions(q: str = Query(default="", min_length=1)) -> list[str]:
    """Return tag name suggestions matching the prefix query.

    Queries the knowledge graph for entity names that start with the given
    prefix.  Falls back to an empty list when the graph is unavailable so
    the UI degrades gracefully.
    """
    if not q:
        return []

    if _orchestrator is None or _orchestrator.graphiti is None:
        return []

    try:
        graphiti = _orchestrator.graphiti
        if hasattr(graphiti, "search"):
            results = await graphiti.search(q, limit=10)
            names: list[str] = []
            for node in results.get("nodes", []):
                name = node.get("name", "")
                if name and name.lower().startswith(q.lower()):
                    names.append(name)
            return names[:8]
    except Exception:
        logger.exception("[STORM] tag_suggestions: error querying graphiti for prefix %r", q)

    return []


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
