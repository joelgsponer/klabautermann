# Klabautermann Logging & Observability

**Version**: 1.0
**Purpose**: The Captain's Log - comprehensive logging and monitoring directive

---

## Overview

In an agentic system where multiple AI agents work in parallel, logging is the **only way** to trace why a decision was made or which agent "dropped the compass." This directive establishes the Klabautermann logging standards.

---

## 1. The Nautical Log Levels

Standard Python logging levels are mapped to Klabautermann's nautical branding:

| Level | Nautical Name | Numeric | Usage |
|-------|---------------|---------|-------|
| DEBUG | `[WHISPER]` | 10 | Internal state, raw LLM prompts, ship "creaks" |
| INFO | `[CHART]` | 20 | Navigational progress, agent delegation |
| SUCCESS | `[BEACON]` | 25 | Successful tool execution, goal completion |
| WARNING | `[SWELL]` | 30 | Recoverable issues, API retry, slow response |
| ERROR | `[STORM]` | 40 | Failed actions, MCP tool errors |
| CRITICAL | `[SHIPWRECK]` | 50 | System-level failures, Neo4j down |

---

## 2. Logger Implementation

### 2.1 Custom Logger

```python
# klabautermann/core/logger.py
import logging
import sys
import json
from datetime import datetime
from typing import Optional, Dict, Any
from pathlib import Path

# Add custom SUCCESS level
SUCCESS = 25
logging.addLevelName(SUCCESS, "SUCCESS")

class KlabautermannLogger(logging.Logger):
    """Custom logger with nautical levels and structured output"""

    def success(self, msg: str, *args, **kwargs):
        """Log successful operations"""
        if self.isEnabledFor(SUCCESS):
            self._log(SUCCESS, msg, args, **kwargs)

    def whisper(self, msg: str, *args, **kwargs):
        """Log debug-level internal state"""
        self.debug(msg, *args, **kwargs)

    def chart(self, msg: str, *args, **kwargs):
        """Log navigational progress"""
        self.info(msg, *args, **kwargs)

    def beacon(self, msg: str, *args, **kwargs):
        """Log successful completions"""
        self.success(msg, *args, **kwargs)

    def swell(self, msg: str, *args, **kwargs):
        """Log recoverable issues"""
        self.warning(msg, *args, **kwargs)

    def storm(self, msg: str, *args, **kwargs):
        """Log errors"""
        self.error(msg, *args, **kwargs)

    def shipwreck(self, msg: str, *args, **kwargs):
        """Log critical failures"""
        self.critical(msg, *args, **kwargs)


class NauticalFormatter(logging.Formatter):
    """Formatter that converts levels to nautical names"""

    LEVEL_MAP = {
        "DEBUG": "[WHISPER]",
        "INFO": "[CHART]",
        "SUCCESS": "[BEACON]",
        "WARNING": "[SWELL]",
        "ERROR": "[STORM]",
        "CRITICAL": "[SHIPWRECK]"
    }

    def format(self, record: logging.LogRecord) -> str:
        # Map level to nautical name
        nautical_level = self.LEVEL_MAP.get(record.levelname, record.levelname)

        # Build message
        timestamp = datetime.fromtimestamp(record.created).isoformat()
        trace_id = getattr(record, 'trace_id', '-')
        agent_name = getattr(record, 'agent_name', '-')

        # Format: timestamp | trace_id | agent | level | message
        base_msg = f"{timestamp} | {trace_id} | {agent_name} | {nautical_level} | {record.getMessage()}"

        # Add exception info if present
        if record.exc_info:
            base_msg += f"\n{self.formatException(record.exc_info)}"

        return base_msg


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured log aggregation"""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "nautical_level": NauticalFormatter.LEVEL_MAP.get(record.levelname, record.levelname),
            "logger": record.name,
            "message": record.getMessage(),
            "trace_id": getattr(record, 'trace_id', None),
            "agent_name": getattr(record, 'agent_name', None),
        }

        # Add extra fields
        for key in ['user_id', 'thread_id', 'tool_name', 'latency_ms']:
            if hasattr(record, key):
                log_entry[key] = getattr(record, key)

        # Add exception info
        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def setup_logger(
    name: str = "klabautermann",
    level: str = "INFO",
    log_file: Optional[Path] = None,
    json_output: bool = False
) -> KlabautermannLogger:
    """
    Configure and return the Klabautermann logger.

    Args:
        name: Logger name
        level: Log level (DEBUG, INFO, etc.)
        log_file: Optional file path for log output
        json_output: Use JSON format (for log aggregation)

    Returns:
        Configured logger instance
    """
    # Register custom logger class
    logging.setLoggerClass(KlabautermannLogger)

    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    logger.handlers.clear()

    # Choose formatter
    if json_output:
        formatter = JSONFormatter()
    else:
        formatter = NauticalFormatter()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

    # File handler (if specified)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(JSONFormatter())  # Always JSON for files
        logger.addHandler(file_handler)

    return logger


# Global logger instance
logger = setup_logger(
    level=os.getenv("LOG_LEVEL", "INFO"),
    log_file=Path("logs/ship_ledger.jsonl") if os.getenv("LOG_TO_FILE") else None,
    json_output=os.getenv("LOG_FORMAT") == "json"
)
```

### 2.2 Usage Examples

```python
from klabautermann.core.logger import logger

# Basic logging
logger.chart("Processing user request")
logger.beacon("Email sent successfully")
logger.storm("MCP tool failed", exc_info=True)

# With context
logger.info(
    "[CHART] Delegating to Researcher",
    extra={
        "trace_id": "abc-123",
        "agent_name": "orchestrator",
        "target_agent": "researcher"
    }
)

# Using nautical methods
logger.whisper("Raw LLM prompt: ...")
logger.swell("API retry attempt 2/3")
logger.shipwreck("Neo4j connection lost!")
```

---

## 3. Trace ID Propagation

### 3.1 Request Tracing

Every user request generates a unique trace ID that follows it through all agents:

```python
import uuid

async def handle_user_input(self, thread_id: str, text: str) -> str:
    # Generate trace ID at entry point
    trace_id = str(uuid.uuid4())[:8]  # Short UUID for readability

    logger.info(
        f"[CHART] New request received",
        extra={"trace_id": trace_id, "thread_id": thread_id}
    )

    # Pass trace_id through all operations
    intent = await self._classify_intent(text, trace_id)
    response = await self._dispatch_to_agent("researcher", intent, trace_id)

    logger.info(
        f"[BEACON] Request completed",
        extra={"trace_id": trace_id, "latency_ms": elapsed_ms}
    )

    return response
```

### 3.2 Agent Message Tracing

```python
class AgentMessage(BaseModel):
    trace_id: str  # Always required
    source_agent: str
    target_agent: str
    intent: str
    payload: dict
    timestamp: float

# When dispatching to sub-agent
await researcher.inbox.put(AgentMessage(
    trace_id=trace_id,  # Propagate trace ID
    source_agent="orchestrator",
    target_agent="researcher",
    intent="search",
    payload={"query": text},
    timestamp=time.time()
))
```

### 3.3 Example Log Trace

```
2025-01-15T10:00:01 | f47ac10b | orchestrator | [CHART] | New request: "Who is Sarah?"
2025-01-15T10:00:01 | f47ac10b | orchestrator | [CHART] | Intent classified: search
2025-01-15T10:00:01 | f47ac10b | orchestrator | [CHART] | Delegating to researcher
2025-01-15T10:00:02 | f47ac10b | researcher   | [CHART] | Executing vector search
2025-01-15T10:00:02 | f47ac10b | researcher   | [BEACON] | Found 3 results
2025-01-15T10:00:02 | f47ac10b | orchestrator | [BEACON] | Response generated [1.2s]
2025-01-15T10:00:02 | f47ac10b | ingestor     | [CHART] | Background ingestion started
```

---

## 4. What to Log

### 4.1 Always Log

| Event | Level | Details |
|-------|-------|---------|
| Request received | INFO | trace_id, thread_id, channel_type |
| Intent classified | INFO | trace_id, intent_type, confidence |
| Agent delegation | INFO | trace_id, source, target, intent |
| MCP tool call | INFO | trace_id, server, tool, arguments (sanitized) |
| MCP tool result | SUCCESS/ERROR | trace_id, tool, success, latency_ms |
| Graph write | INFO | trace_id, operation, node_type |
| Response sent | SUCCESS | trace_id, latency_ms |
| Error occurred | ERROR | trace_id, error_type, message, stack trace |

### 4.2 Conditional Logging

| Event | Condition | Level |
|-------|-----------|-------|
| Raw LLM prompt | LOG_LEVEL=DEBUG | DEBUG |
| Full LLM response | LOG_LEVEL=DEBUG | DEBUG |
| Graph query execution | LOG_LEVEL=DEBUG | DEBUG |
| Config reload | Always | INFO |
| Rate limit hit | Always | WARNING |

### 4.3 Never Log

- API keys or secrets
- Full email content (log subject only)
- Personal data without consent
- Passwords or tokens

---

## 5. Log Aggregation

### 5.1 JSON Log Format

For production log aggregation (ELK, Loki, etc.), use JSON format:

```json
{
  "timestamp": "2025-01-15T10:00:01.234567",
  "level": "INFO",
  "nautical_level": "[CHART]",
  "logger": "klabautermann",
  "message": "Delegating to researcher",
  "trace_id": "f47ac10b",
  "agent_name": "orchestrator",
  "target_agent": "researcher",
  "intent": "search"
}
```

### 5.2 Log Rotation

```python
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    "logs/ship_ledger.jsonl",
    maxBytes=10_000_000,  # 10MB
    backupCount=5
)
```

### 5.3 Docker Logging

```yaml
# docker-compose.yml
services:
  klabautermann-app:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

---

## 6. Performance Metrics

### 6.1 Timing Decorator

```python
import time
from functools import wraps

def log_timing(operation_name: str):
    """Decorator to log operation timing"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            start = time.time()
            trace_id = kwargs.get('trace_id', '-')

            try:
                result = await func(*args, **kwargs)
                elapsed_ms = (time.time() - start) * 1000

                logger.info(
                    f"[BEACON] {operation_name} completed",
                    extra={
                        "trace_id": trace_id,
                        "operation": operation_name,
                        "latency_ms": elapsed_ms
                    }
                )
                return result

            except Exception as e:
                elapsed_ms = (time.time() - start) * 1000
                logger.error(
                    f"[STORM] {operation_name} failed after {elapsed_ms:.0f}ms: {e}",
                    extra={
                        "trace_id": trace_id,
                        "operation": operation_name,
                        "latency_ms": elapsed_ms
                    },
                    exc_info=True
                )
                raise

        return wrapper
    return decorator

# Usage
@log_timing("vector_search")
async def search_memory(self, query: str, trace_id: str):
    ...
```

### 6.2 Agent Metrics

```python
from dataclasses import dataclass, field
from typing import Dict
import time

@dataclass
class AgentMetrics:
    """Track per-agent performance metrics"""
    agent_name: str
    request_count: int = 0
    success_count: int = 0
    error_count: int = 0
    total_latency_ms: float = 0.0
    latencies: list = field(default_factory=list)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / self.request_count if self.request_count > 0 else 0

    @property
    def success_rate(self) -> float:
        return self.success_count / self.request_count if self.request_count > 0 else 0

    @property
    def p95_latency_ms(self) -> float:
        if not self.latencies:
            return 0
        sorted_latencies = sorted(self.latencies)
        idx = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[idx]

    def record(self, success: bool, latency_ms: float):
        self.request_count += 1
        if success:
            self.success_count += 1
        else:
            self.error_count += 1
        self.total_latency_ms += latency_ms
        self.latencies.append(latency_ms)

        # Keep only last 1000 latencies
        if len(self.latencies) > 1000:
            self.latencies = self.latencies[-1000:]


class MetricsCollector:
    """Collect metrics across all agents"""

    def __init__(self):
        self.agents: Dict[str, AgentMetrics] = {}

    def get_agent_metrics(self, agent_name: str) -> AgentMetrics:
        if agent_name not in self.agents:
            self.agents[agent_name] = AgentMetrics(agent_name)
        return self.agents[agent_name]

    def summary(self) -> Dict[str, Dict]:
        return {
            name: {
                "requests": m.request_count,
                "success_rate": f"{m.success_rate:.1%}",
                "avg_latency_ms": f"{m.avg_latency_ms:.0f}",
                "p95_latency_ms": f"{m.p95_latency_ms:.0f}"
            }
            for name, m in self.agents.items()
        }


# Global metrics instance
metrics = MetricsCollector()
```

---

## 7. Error Tracking

### 7.1 Error Context

Always include context with errors:

```python
try:
    result = await mcp.call_tool("gmail", "send_message", args)
except Exception as e:
    logger.error(
        "[STORM] MCP tool call failed",
        extra={
            "trace_id": trace_id,
            "agent_name": "executor",
            "tool_server": "gmail",
            "tool_name": "send_message",
            "error_type": type(e).__name__,
            "error_message": str(e)
        },
        exc_info=True  # Include stack trace
    )
    raise
```

### 7.2 Error Classification

```python
class ErrorClassifier:
    """Classify errors for monitoring and alerting"""

    @staticmethod
    def classify(error: Exception) -> dict:
        error_type = type(error).__name__

        if "timeout" in str(error).lower():
            return {"category": "timeout", "severity": "warning", "retryable": True}
        elif "rate limit" in str(error).lower():
            return {"category": "rate_limit", "severity": "warning", "retryable": True}
        elif "connection" in str(error).lower():
            return {"category": "connection", "severity": "error", "retryable": True}
        elif "auth" in str(error).lower():
            return {"category": "authentication", "severity": "critical", "retryable": False}
        else:
            return {"category": "unknown", "severity": "error", "retryable": False}
```

---

## 8. Audit Logging

### 8.1 Security Audit Trail

Log all sensitive operations to the graph:

```python
async def log_audit_event(
    driver,
    trace_id: str,
    event_type: str,
    agent_name: str,
    details: dict
):
    """Log security-relevant events to graph"""
    async with driver.session() as session:
        await session.run("""
            CREATE (a:AuditLog {
                uuid: $uuid,
                trace_id: $trace_id,
                event_type: $event_type,
                agent_name: $agent_name,
                details: $details,
                timestamp: timestamp()
            })
        """, {
            "uuid": str(uuid.uuid4()),
            "trace_id": trace_id,
            "event_type": event_type,
            "agent_name": agent_name,
            "details": json.dumps(details)
        })

# Usage
await log_audit_event(
    driver,
    trace_id=trace_id,
    event_type="mcp_tool_call",
    agent_name="executor",
    details={
        "tool": "gmail_send_message",
        "recipient_hash": hashlib.sha256(recipient.encode()).hexdigest()
    }
)
```

### 8.2 Audit Query

```cypher
// Find all email sends in last 24 hours
MATCH (a:AuditLog)
WHERE a.event_type = 'mcp_tool_call'
  AND a.timestamp > timestamp() - 24*60*60*1000
  AND a.details CONTAINS 'gmail_send'
RETURN a.timestamp, a.agent_name, a.details
ORDER BY a.timestamp DESC
```

---

## 9. Monitoring Dashboard Queries

### 9.1 Recent Errors

```cypher
MATCH (a:AuditLog)
WHERE a.event_type = 'error'
  AND a.timestamp > timestamp() - 60*60*1000  // Last hour
RETURN a.timestamp, a.agent_name, a.details
ORDER BY a.timestamp DESC
LIMIT 20
```

### 9.2 Agent Performance

```python
def generate_performance_report():
    summary = metrics.summary()
    logger.info(
        "[CHART] Performance Report",
        extra={"metrics": summary}
    )
    return summary
```

### 9.3 Alert Thresholds

| Metric | Warning | Critical |
|--------|---------|----------|
| Error rate | >5% | >20% |
| P95 latency | >5s | >10s |
| Neo4j connection errors | >0 | >3 in 5min |
| MCP failures | >3 in 5min | >10 in 5min |

---

## 10. Quick Reference

### 10.1 Log Format

```
{timestamp} | {trace_id} | {agent_name} | {nautical_level} | {message}
```

### 10.2 Required Fields

| Field | When |
|-------|------|
| `trace_id` | Always |
| `agent_name` | Agent operations |
| `tool_name` | MCP calls |
| `latency_ms` | Timed operations |
| `error_type` | Errors |

### 10.3 Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `LOG_LEVEL` | INFO | Minimum log level |
| `LOG_FORMAT` | text | "text" or "json" |
| `LOG_TO_FILE` | false | Enable file logging |

---

*"Without logs, we sail blind. With them, every wave is charted."* - Klabautermann
