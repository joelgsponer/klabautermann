# API Documentation

Klabautermann's internal API for programmatic integration.

## Overview

Klabautermann provides:
- **Python API** - Direct import and use
- **Channel Protocol** - Interface for custom channels
- **MCP Integration** - Tool calling via Model Context Protocol

## Python API

### Orchestrator

The main entry point for interactions:

```python
from klabautermann.agents.orchestrator import Orchestrator
from klabautermann.core.config import get_settings

# Initialize
settings = get_settings()
orchestrator = Orchestrator(settings)
await orchestrator.initialize()

# Process a message
response = await orchestrator.process(
    message="Who is Sarah?",
    channel_id="api",
    user_id="user-123",
    thread_id="thread-456",  # Optional
)

print(response.text)
```

### Response Model

```python
from klabautermann.core.models import OrchestratorResponse

# Response structure
class OrchestratorResponse:
    text: str                    # Response text
    intent: IntentType          # Classified intent
    confidence: float           # Classification confidence
    thread_id: str | None       # Thread for context
    entities_created: list[str] # New entities added
    trace_id: str               # Request trace ID
```

### Intent Classification

```python
from klabautermann.core.models import IntentType

class IntentType(str, Enum):
    SEARCH = "search"           # Knowledge retrieval
    ACTION = "action"           # External action (email, calendar)
    INGESTION = "ingestion"     # Store new information
    CONVERSATION = "conversation"  # General chat
```

### Intent Classification Result

```python
from klabautermann.core.models import IntentClassification

class IntentClassification:
    type: IntentType
    confidence: float           # 0.0 to 1.0
    query: str | None          # For SEARCH intents
    action: str | None         # For ACTION intents
    entities: list[str]        # Detected entities
```

## Agent APIs

### Researcher

Query the knowledge graph:

```python
from klabautermann.agents.researcher import Researcher

researcher = Researcher(settings)
await researcher.initialize()

# Search for entities
results = await researcher.search(
    query="What do I know about Sarah?",
    trace_id="trace-123",
)

for result in results:
    print(f"{result.entity_type}: {result.name}")
    print(f"  Summary: {result.summary}")
```

### Ingestor

Add information to the graph:

```python
from klabautermann.agents.ingestor import Ingestor

ingestor = Ingestor(settings)
await ingestor.initialize()

# Ingest a message
entities = await ingestor.ingest(
    text="I met John from Acme Corp today.",
    source_channel="api",
    trace_id="trace-123",
)

for entity in entities:
    print(f"Created: {entity.type} - {entity.name}")
```

### Executor

Perform external actions:

```python
from klabautermann.agents.executor import Executor

executor = Executor(settings)
await executor.initialize()

# Execute an action
result = await executor.execute(
    action="send_email",
    params={
        "to": "john@example.com",
        "subject": "Hello",
        "body": "Hi John!",
    },
    trace_id="trace-123",
)
```

## Channel Protocol

Implement custom channels by extending `BaseChannel`:

```python
from klabautermann.channels.base import BaseChannel

class MyChannel(BaseChannel):
    """Custom channel implementation."""

    async def connect(self) -> None:
        """Establish connection."""
        pass

    async def disconnect(self) -> None:
        """Clean up connection."""
        pass

    async def receive(self) -> Message:
        """Receive next message."""
        pass

    async def send(self, response: OrchestratorResponse) -> None:
        """Send response to user."""
        pass

    async def run(self) -> None:
        """Main event loop."""
        while self.running:
            message = await self.receive()
            response = await self.orchestrator.process(
                message=message.text,
                channel_id=self.channel_id,
                user_id=message.user_id,
            )
            await self.send(response)
```

## MCP Tool Integration

Klabautermann uses MCP for external service integration:

### Available Tools

| Tool | Description |
|------|-------------|
| `gmail.send_email` | Send email via Gmail |
| `gmail.search_emails` | Search inbox |
| `calendar.create_event` | Create calendar event |
| `calendar.list_events` | List upcoming events |

### Tool Call Format

```python
from klabautermann.mcp.client import MCPClient

mcp = MCPClient()
await mcp.initialize()

# Call a tool
result = await mcp.call_tool(
    server="google-workspace",
    tool="gmail.send_email",
    arguments={
        "to": "john@example.com",
        "subject": "Hello",
        "body": "Hi John!",
    },
)
```

## Error Handling

### Exception Types

```python
from klabautermann.core.exceptions import (
    KlabautermannError,      # Base exception
    ConfigurationError,      # Invalid config
    AgentError,              # Agent failure
    MCPError,                # MCP tool error
    GraphError,              # Neo4j error
)
```

### Error Response

```python
try:
    response = await orchestrator.process(message)
except AgentError as e:
    print(f"Agent error: {e.agent_name} - {e.message}")
    print(f"Trace ID: {e.trace_id}")
```

## Logging

Klabautermann uses structured logging with trace IDs:

```python
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

# Logs include trace_id for request tracking
# [CHART] Agent initialized
# [WHISPER] Processing message trace_id=abc-123
# [BEACON] Intent classified type=search confidence=0.95
```

### Log Levels (Nautical Theme)

| Level | Name | Use |
|-------|------|-----|
| DEBUG | WHISPER | Internal details |
| INFO | CHART | Normal operations |
| WARNING | SWELL | Recoverable issues |
| ERROR | STORM | Failures |
| CRITICAL | MAELSTROM | Fatal errors |

## Rate Limiting

The API has built-in rate limiting:

```python
# Default limits
MAX_REQUESTS_PER_MINUTE = 60
MAX_TOKENS_PER_MINUTE = 100000
```

Configure in settings:
```bash
RATE_LIMIT_REQUESTS=60
RATE_LIMIT_TOKENS=100000
```

## Next Steps

- [Quickstart](QUICKSTART.md) - Get started
- [Architecture](../specs/architecture/AGENTS.md) - System design
- [Contributing](../CONTRIBUTING.md) - Development guide
