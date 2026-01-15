# Klabautermann MCP Integration Guide

**Version**: 1.0
**Purpose**: Model Context Protocol implementation for tool integration

---

## Overview

The **Model Context Protocol (MCP)** provides a standardized way for AI agents to interact with external tools and services. Instead of writing custom API wrappers for Gmail, Calendar, and other services, Klabautermann uses MCP servers that expose tools in a consistent format.

```
┌─────────────────────┐     ┌─────────────────────┐
│  Klabautermann      │     │    MCP Servers      │
│  (MCP Client)       │     │                     │
│                     │     │ ┌─────────────────┐ │
│  ┌───────────────┐  │     │ │ Google Workspace│ │
│  │   Executor    │◄─┼─────┼─┤ gmail_send      │ │
│  │   Agent       │  │     │ │ calendar_create │ │
│  └───────────────┘  │     │ └─────────────────┘ │
│                     │     │                     │
│  ┌───────────────┐  │     │ ┌─────────────────┐ │
│  │   Ingestor    │◄─┼─────┼─┤ Filesystem      │ │
│  │   Agent       │  │     │ │ read_file       │ │
│  └───────────────┘  │     │ │ write_file      │ │
│                     │     │ └─────────────────┘ │
└─────────────────────┘     └─────────────────────┘
```

---

## 1. MCP Architecture

### 1.1 What is MCP?

MCP is a **bidirectional protocol** that standardizes how AI models interact with external systems:

- **Tools**: Functions the AI can call (e.g., `gmail_send_message`)
- **Resources**: Data the AI can read (e.g., file contents)
- **Prompts**: Pre-defined prompt templates

### 1.2 Transport Methods

| Method | Use Case | Connection |
|--------|----------|------------|
| **stdio** | Local servers | stdin/stdout communication |
| **SSE** | Remote servers | Server-Sent Events over HTTP |

Klabautermann uses **stdio** for local development and Docker deployment.

### 1.3 MCP Servers Used

| Server | Package | Tools Provided |
|--------|---------|----------------|
| Google Workspace | `@anthropic-ai/mcp-server-google-workspace` | Gmail, Calendar, Drive |
| Filesystem | `@modelcontextprotocol/server-filesystem` | File read/write/list |
| Neo4j (Custom) | `klabautermann-mcp-neo4j` | Cypher queries |

---

## 2. MCP Client Implementation

### 2.1 Generic MCP Client

```python
# klabautermann/mcp/client.py
import asyncio
import os
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from pydantic import BaseModel
from typing import Dict, Any, List

class ToolInvocationContext(BaseModel):
    trace_id: str
    agent_name: str
    user_intent: str
    graph_context: Dict[str, Any] = {}

class MCPClient:
    def __init__(self, server_configs: Dict[str, List[str]]):
        """
        server_configs: {
            "google_workspace": ["npx", "-y", "@anthropic-ai/mcp-server-google-workspace"],
            "filesystem": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/app/data"]
        }
        """
        self.server_configs = server_configs
        self.sessions: Dict[str, ClientSession] = {}

    async def connect(self, server_name: str):
        """Establish connection to MCP server"""
        config = self.server_configs[server_name]
        params = StdioServerParameters(
            command=config[0],
            args=config[1:],
            env={**os.environ}
        )

        read, write = await stdio_client(params).__aenter__()
        session = ClientSession(read, write)
        await session.__aenter__()
        await session.initialize()

        self.sessions[server_name] = session
        return session

    async def list_tools(self, server_name: str) -> List[Dict]:
        """Discover available tools from server"""
        session = self.sessions.get(server_name)
        if not session:
            session = await self.connect(server_name)

        tools = await session.list_tools()
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "input_schema": tool.inputSchema
            }
            for tool in tools.tools
        ]

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: Dict[str, Any],
        context: ToolInvocationContext
    ) -> Dict[str, Any]:
        """Execute a tool with full observability"""
        from klabautermann.core.logger import logger
        import time

        session = self.sessions.get(server_name)
        if not session:
            session = await self.connect(server_name)

        logger.info(
            f"[CHART] {context.trace_id} | {context.agent_name} | "
            f"Calling {server_name}.{tool_name}",
            extra={"arguments": arguments}
        )

        start_time = time.time()

        try:
            result = await session.call_tool(tool_name, arguments)
            latency = time.time() - start_time

            logger.info(
                f"[BEACON] {context.trace_id} | {context.agent_name} | "
                f"Tool {tool_name} succeeded [{latency:.2f}s]"
            )

            return {
                "success": True,
                "content": result.content,
                "latency_ms": latency * 1000
            }

        except Exception as e:
            latency = time.time() - start_time
            logger.error(
                f"[STORM] {context.trace_id} | {context.agent_name} | "
                f"Tool {tool_name} failed: {e}"
            )

            return {
                "success": False,
                "error": str(e),
                "latency_ms": latency * 1000
            }

    async def disconnect_all(self):
        """Close all MCP sessions"""
        for session in self.sessions.values():
            await session.__aexit__(None, None, None)
        self.sessions.clear()
```

### 2.2 Usage Example

```python
# Example: Executor agent using MCP
mcp = MCPClient({
    "google_workspace": ["npx", "-y", "@anthropic-ai/mcp-server-google-workspace"],
})

context = ToolInvocationContext(
    trace_id="abc123",
    agent_name="executor",
    user_intent="send email to Sarah"
)

result = await mcp.call_tool(
    server_name="google_workspace",
    tool_name="gmail_send_message",
    arguments={
        "to": "sarah@acme.com",
        "subject": "Budget Update",
        "body": "Hi Sarah, attached is the Q1 budget..."
    },
    context=context
)

if result["success"]:
    print(f"Email sent in {result['latency_ms']:.0f}ms")
else:
    print(f"Failed: {result['error']}")
```

---

## 3. Google Workspace Integration

### 3.1 Prerequisites

1. **Google Cloud Project** with Gmail and Calendar APIs enabled
2. **OAuth 2.0 Credentials** (Client ID, Client Secret)
3. **Refresh Token** obtained via bootstrap script

### 3.2 OAuth2 Bootstrap Script

```python
# scripts/bootstrap_auth.py
import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

SCOPES = [
    'https://www.googleapis.com/auth/gmail.modify',      # Read, send, label emails
    'https://www.googleapis.com/auth/calendar.events',   # Read, create, modify events
]

def bootstrap_google_auth():
    """Run interactive OAuth2 flow to obtain refresh token"""

    print("=" * 50)
    print("Klabautermann Google Workspace Authentication")
    print("=" * 50)

    # Check for existing token
    token_path = os.getenv("GOOGLE_TOKEN_PATH", ".google_token.json")
    if os.path.exists(token_path):
        print(f"Found existing token at {token_path}")
        with open(token_path, 'r') as f:
            token_data = json.load(f)
        print(f"Refresh token exists: {'refresh_token' in token_data}")
        return token_data.get('refresh_token')

    # Need client credentials
    client_id = os.getenv("GOOGLE_CLIENT_ID")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET")

    if not client_id or not client_secret:
        print("\nERROR: Missing GOOGLE_CLIENT_ID or GOOGLE_CLIENT_SECRET in .env")
        print("\nTo obtain these:")
        print("1. Go to https://console.cloud.google.com/apis/credentials")
        print("2. Create OAuth 2.0 Client ID (Desktop application)")
        print("3. Add to .env file")
        return None

    # Create temporary client_secrets format
    client_config = {
        "installed": {
            "client_id": client_id,
            "client_secret": client_secret,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"]
        }
    }

    # Run OAuth flow
    print("\nOpening browser for Google authentication...")
    print("Please log in and grant the requested permissions.")

    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    credentials = flow.run_local_server(port=8080)

    # Save token
    token_data = {
        "token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_uri": credentials.token_uri,
        "client_id": credentials.client_id,
        "client_secret": credentials.client_secret,
        "scopes": credentials.scopes
    }

    with open(token_path, 'w') as f:
        json.dump(token_data, f, indent=2)

    print(f"\nSuccess! Token saved to {token_path}")
    print(f"\nAdd this to your .env file:")
    print(f"GOOGLE_REFRESH_TOKEN={credentials.refresh_token}")

    return credentials.refresh_token

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    bootstrap_google_auth()
```

### 3.3 Available Gmail Tools

| Tool | Description | Arguments |
|------|-------------|-----------|
| `gmail_send_message` | Send an email | `to`, `subject`, `body`, `cc?`, `bcc?` |
| `gmail_create_draft` | Create email draft | `to`, `subject`, `body` |
| `gmail_search_messages` | Search inbox | `query`, `max_results?` |
| `gmail_get_message` | Get message by ID | `message_id` |
| `gmail_list_labels` | List all labels | - |

**Query Syntax for `gmail_search_messages`**:
```
from:sarah@acme.com          # From specific sender
subject:budget               # Subject contains "budget"
after:2025/01/01             # After date
is:unread                    # Unread only
has:attachment               # Has attachment
newer_than:7d                # Within last 7 days
```

### 3.4 Available Calendar Tools

| Tool | Description | Arguments |
|------|-------------|-----------|
| `calendar_create_event` | Create event | `summary`, `start`, `end`, `attendees?`, `description?` |
| `calendar_list_events` | List upcoming events | `time_min?`, `time_max?`, `max_results?` |
| `calendar_get_event` | Get event by ID | `event_id` |
| `calendar_delete_event` | Delete event | `event_id` |
| `calendar_update_event` | Modify event | `event_id`, `updates` |

**Date Format**: ISO 8601 (e.g., `2025-01-15T14:00:00Z`)

### 3.5 Google Workspace MCP Wrapper

```python
# klabautermann/mcp/google_workspace.py
from klabautermann.mcp.client import MCPClient, ToolInvocationContext
from typing import List, Dict, Any, Optional
from datetime import datetime

class GoogleWorkspaceClient:
    def __init__(self, mcp: MCPClient):
        self.mcp = mcp
        self.server = "google_workspace"

    async def send_email(
        self,
        to: str,
        subject: str,
        body: str,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        context: Optional[ToolInvocationContext] = None
    ) -> Dict[str, Any]:
        """Send an email via Gmail"""
        arguments = {
            "to": to,
            "subject": subject,
            "body": body
        }
        if cc:
            arguments["cc"] = cc
        if bcc:
            arguments["bcc"] = bcc

        return await self.mcp.call_tool(
            self.server,
            "gmail_send_message",
            arguments,
            context or ToolInvocationContext(trace_id="unknown", agent_name="unknown", user_intent="send_email")
        )

    async def search_emails(
        self,
        query: str,
        max_results: int = 10,
        context: Optional[ToolInvocationContext] = None
    ) -> Dict[str, Any]:
        """Search Gmail inbox"""
        return await self.mcp.call_tool(
            self.server,
            "gmail_search_messages",
            {"query": query, "max_results": max_results},
            context or ToolInvocationContext(trace_id="unknown", agent_name="unknown", user_intent="search_emails")
        )

    async def create_event(
        self,
        summary: str,
        start: datetime,
        end: datetime,
        attendees: Optional[List[str]] = None,
        description: Optional[str] = None,
        context: Optional[ToolInvocationContext] = None
    ) -> Dict[str, Any]:
        """Create a calendar event"""
        arguments = {
            "summary": summary,
            "start": start.isoformat(),
            "end": end.isoformat()
        }
        if attendees:
            arguments["attendees"] = attendees
        if description:
            arguments["description"] = description

        return await self.mcp.call_tool(
            self.server,
            "calendar_create_event",
            arguments,
            context or ToolInvocationContext(trace_id="unknown", agent_name="unknown", user_intent="create_event")
        )

    async def list_events(
        self,
        time_min: Optional[datetime] = None,
        time_max: Optional[datetime] = None,
        max_results: int = 10,
        context: Optional[ToolInvocationContext] = None
    ) -> Dict[str, Any]:
        """List upcoming calendar events"""
        arguments = {"max_results": max_results}
        if time_min:
            arguments["time_min"] = time_min.isoformat()
        if time_max:
            arguments["time_max"] = time_max.isoformat()

        return await self.mcp.call_tool(
            self.server,
            "calendar_list_events",
            arguments,
            context or ToolInvocationContext(trace_id="unknown", agent_name="unknown", user_intent="list_events")
        )
```

---

## 4. Filesystem MCP

### 4.1 Configuration

```python
mcp_config = {
    "filesystem": [
        "npx", "-y",
        "@modelcontextprotocol/server-filesystem",
        "/app/data"  # Allowed directory
    ]
}
```

### 4.2 Available Tools

| Tool | Description | Arguments |
|------|-------------|-----------|
| `read_file` | Read file contents | `path` |
| `write_file` | Write/overwrite file | `path`, `content` |
| `list_directory` | List directory contents | `path` |
| `create_directory` | Create directory | `path` |

### 4.3 Usage for Notes

```python
# Save a note to filesystem (Obsidian-compatible)
await mcp.call_tool(
    "filesystem",
    "write_file",
    {
        "path": "/app/data/notes/2025-01-15-meeting-sarah.md",
        "content": """---
date: 2025-01-15
tags: [meeting, budget, acme]
---

# Meeting with Sarah

Discussed Q1 budget allocation...
"""
    },
    context
)
```

---

## 5. Custom Neo4j MCP Server

For complex graph queries, we provide a custom MCP server.

### 5.1 Server Implementation

```python
# klabautermann/mcp/graph_server.py
from mcp.server import Server
from mcp.types import Tool
from neo4j import AsyncGraphDatabase
import json

app = Server("klabautermann-graph")

driver = None

@app.list_tools()
async def list_tools():
    return [
        Tool(
            name="execute_cypher",
            description="Execute a Cypher query on the knowledge graph",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Cypher query to execute"
                    },
                    "parameters": {
                        "type": "object",
                        "description": "Query parameters"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="get_node_by_uuid",
            description="Get a node by its UUID",
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {"type": "string"},
                    "label": {"type": "string"}
                },
                "required": ["uuid"]
            }
        )
    ]

@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "execute_cypher":
        query = arguments["query"]
        params = arguments.get("parameters", {})

        # Security: Only allow read queries from this tool
        if any(keyword in query.upper() for keyword in ["CREATE", "DELETE", "SET", "MERGE", "REMOVE"]):
            return {"error": "Write operations not allowed via MCP. Use Graphiti for writes."}

        async with driver.session() as session:
            result = await session.run(query, params)
            records = [dict(record) for record in await result.data()]
            return {"records": records, "count": len(records)}

    elif name == "get_node_by_uuid":
        uuid = arguments["uuid"]
        label = arguments.get("label", "")

        query = f"MATCH (n{':' + label if label else ''} {{uuid: $uuid}}) RETURN n"
        async with driver.session() as session:
            result = await session.run(query, {"uuid": uuid})
            record = await result.single()
            if record:
                return {"node": dict(record["n"])}
            return {"error": "Node not found"}

async def main():
    global driver
    driver = AsyncGraphDatabase.driver(
        os.getenv("NEO4J_URI"),
        auth=(os.getenv("NEO4J_USER"), os.getenv("NEO4J_PASSWORD"))
    )

    from mcp.server.stdio import stdio_server
    async with stdio_server() as (read, write):
        await app.run(read, write, app.create_initialization_options())

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
```

### 5.2 Running the Custom Server

```yaml
# In docker-compose.yml
services:
  mcp-graph:
    build:
      context: .
      dockerfile: Dockerfile.mcp-graph
    environment:
      - NEO4J_URI=bolt://neo4j:7687
      - NEO4J_USER=neo4j
      - NEO4J_PASSWORD=${NEO4J_PASSWORD}
```

---

## 6. Security & Access Control

### 6.1 Agent Tool Permissions

| Agent | Gmail Read | Gmail Write | Calendar Read | Calendar Write | Filesystem | Neo4j |
|-------|------------|-------------|---------------|----------------|------------|-------|
| **Ingestor** | Yes | No | Yes | No | No | Write (via Graphiti) |
| **Researcher** | No | No | No | No | No | Read |
| **Executor** | Yes | Yes | Yes | Yes | Yes | Read |
| **Archivist** | No | No | No | No | No | Read/Write |
| **Scribe** | No | No | No | No | Yes (journals) | Read |

### 6.2 Permission Enforcement

```python
class SecureExecutor(BaseAgent):
    ALLOWED_TOOLS = {
        "google_workspace": ["gmail_send_message", "gmail_search_messages", "calendar_create_event", "calendar_list_events"],
        "filesystem": ["write_file", "read_file"]
    }

    async def call_tool(self, server: str, tool: str, args: dict, context):
        if server not in self.ALLOWED_TOOLS:
            raise PermissionError(f"Server {server} not allowed for Executor")
        if tool not in self.ALLOWED_TOOLS[server]:
            raise PermissionError(f"Tool {tool} not allowed for Executor")

        return await self.mcp.call_tool(server, tool, args, context)
```

### 6.3 Audit Logging

Every MCP tool call is logged to the graph for security auditing:

```python
async def _audit_tool_call(self, context, server, tool, args, result):
    """Log tool usage to graph for audit trail"""
    await self.graph.execute("""
        CREATE (a:AuditLog {
            uuid: $uuid,
            trace_id: $trace_id,
            agent_name: $agent,
            server: $server,
            tool: $tool,
            arguments_hash: $args_hash,
            success: $success,
            timestamp: timestamp()
        })
    """, {
        "uuid": str(uuid.uuid4()),
        "trace_id": context.trace_id,
        "agent": context.agent_name,
        "server": server,
        "tool": tool,
        "args_hash": hashlib.sha256(json.dumps(args).encode()).hexdigest(),
        "success": result.get("success", False)
    })
```

---

## 7. Error Handling

### 7.1 Retry with Backoff

```python
from klabautermann.utils.retry import with_retry

class MCPClient:
    @with_retry(max_attempts=3, base_delay=1.0)
    async def call_tool(self, server, tool, args, context):
        # ... implementation
```

### 7.2 Circuit Breaker

```python
class MCPClientWithCircuitBreaker:
    def __init__(self):
        self.breakers = {
            "google_workspace": CircuitBreaker(failure_threshold=5, timeout=timedelta(minutes=5)),
            "filesystem": CircuitBreaker(failure_threshold=3, timeout=timedelta(minutes=1))
        }

    async def call_tool(self, server, tool, args, context):
        breaker = self.breakers.get(server)
        if breaker:
            return await breaker.call(self._call_tool_impl, server, tool, args, context)
        return await self._call_tool_impl(server, tool, args, context)
```

### 7.3 Graceful Degradation

```python
async def send_email_with_fallback(self, to, subject, body, context):
    result = await self.call_tool("google_workspace", "gmail_send_message", {...}, context)

    if not result["success"]:
        # Log the failure
        logger.error(f"[STORM] Email send failed: {result['error']}")

        # Save as draft in filesystem as fallback
        draft_path = f"/app/data/drafts/{context.trace_id}.json"
        await self.call_tool("filesystem", "write_file", {
            "path": draft_path,
            "content": json.dumps({"to": to, "subject": subject, "body": body})
        }, context)

        return {"success": False, "fallback": "saved_as_draft", "path": draft_path}

    return result
```

---

## 8. Testing MCP Integration

### 8.1 MCP Inspector

Use the MCP Inspector to test servers interactively:

```bash
# Install inspector
npm install -g @modelcontextprotocol/inspector

# Test Google Workspace server
mcp-inspector npx -y @anthropic-ai/mcp-server-google-workspace

# Opens web UI at http://localhost:5173
# Can test tools, view schemas, execute calls
```

### 8.2 Integration Tests

```python
@pytest.mark.asyncio
async def test_gmail_search():
    mcp = MCPClient({
        "google_workspace": ["npx", "-y", "@anthropic-ai/mcp-server-google-workspace"]
    })

    context = ToolInvocationContext(
        trace_id="test-123",
        agent_name="test",
        user_intent="search emails"
    )

    result = await mcp.call_tool(
        "google_workspace",
        "gmail_search_messages",
        {"query": "is:unread", "max_results": 5},
        context
    )

    assert result["success"]
    assert "content" in result

@pytest.mark.asyncio
async def test_calendar_list():
    mcp = MCPClient({...})

    result = await mcp.call_tool(
        "google_workspace",
        "calendar_list_events",
        {"max_results": 10},
        context
    )

    assert result["success"]
```

---

## 9. Configuration Reference

### 9.1 Environment Variables

| Variable | Description | Example |
|----------|-------------|---------|
| `GOOGLE_CLIENT_ID` | OAuth2 client ID | `123456789.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | OAuth2 client secret | `GOCSPX-...` |
| `GOOGLE_REFRESH_TOKEN` | OAuth2 refresh token | `1//0e...` |
| `GOOGLE_TOKEN_PATH` | Path to token file | `.google_token.json` |
| `MCP_FILESYSTEM_ROOT` | Allowed directory for filesystem MCP | `/app/data` |

### 9.2 MCP Server Configuration

```python
# config/mcp_servers.py
MCP_SERVERS = {
    "google_workspace": {
        "command": ["npx", "-y", "@anthropic-ai/mcp-server-google-workspace"],
        "env": {
            "GOOGLE_CLIENT_ID": os.getenv("GOOGLE_CLIENT_ID"),
            "GOOGLE_CLIENT_SECRET": os.getenv("GOOGLE_CLIENT_SECRET"),
            "GOOGLE_REFRESH_TOKEN": os.getenv("GOOGLE_REFRESH_TOKEN")
        }
    },
    "filesystem": {
        "command": ["npx", "-y", "@modelcontextprotocol/server-filesystem", "/app/data"],
        "env": {}
    }
}
```

---

*"The Protocol connects our ship to the ports of the world."* - Klabautermann
