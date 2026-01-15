# Klabautermann Coding Standards

**Version**: 1.0
**Purpose**: Engineering excellence guidelines for consistent, maintainable code

---

## Overview

Developing for AI agents requires more than clean syntax—it demands **deterministic handling of non-deterministic outputs**. This guide establishes the "Klabautermann Way" of writing code.

---

## 1. Core Principles

### 1.1 The Klabautermann Creed

1. **Validate Everything**: LLM outputs are untrusted until parsed through Pydantic
2. **Never Block**: Use async/await; never use `time.sleep()`
3. **Parametrize Queries**: Never use f-strings for Cypher; prevent injection
4. **Log Extensively**: Every agent action, every tool call, every error
5. **Fail Gracefully**: Inform the user; don't crash the system

### 1.2 Language & Runtime

| Aspect | Standard |
|--------|----------|
| Python Version | 3.11+ |
| Type Hints | Required on all functions |
| Async | asyncio for all I/O |
| Formatting | Ruff (replaces Black, Flake8, isort) |
| Type Checking | Mypy (strict mode) |

---

## 2. Type Safety & Data Modeling

### 2.1 Pydantic for Everything

All data structures must be Pydantic models:

```python
# GOOD: Explicit and validated
from pydantic import BaseModel, Field
from typing import Optional, List

class PersonNode(BaseModel):
    uuid: str
    name: str
    email: Optional[str] = None
    bio: Optional[str] = None
    created_at: float
    updated_at: float

class EntityExtraction(BaseModel):
    """LLM extraction output - validated before use"""
    name: str
    label: str = Field(pattern="^(Person|Organization|Location|Project)$")
    properties: dict = {}

# BAD: Untyped dictionaries
def process_data(data: dict):
    name = data.get("name")  # Dangerous - could be None, wrong type, etc.
```

### 2.2 Validating LLM Output

Never trust raw LLM JSON:

```python
import json
from pydantic import ValidationError

async def parse_llm_response(response: str) -> EntityExtraction:
    """Safely parse LLM output into validated model"""
    try:
        # Parse JSON
        data = json.loads(response)

        # Validate through Pydantic
        return EntityExtraction(**data)

    except json.JSONDecodeError as e:
        logger.error(f"[STORM] Invalid JSON from LLM: {e}")
        raise ValueError("LLM returned invalid JSON")

    except ValidationError as e:
        logger.error(f"[STORM] LLM output failed validation: {e}")
        raise ValueError(f"LLM output doesn't match schema: {e}")
```

### 2.3 Type Hints

Always use type hints:

```python
# GOOD
async def search_memory(
    query: str,
    limit: int = 10,
    include_expired: bool = False
) -> List[SearchResult]:
    ...

# BAD
async def search_memory(query, limit=10, include_expired=False):
    ...
```

---

## 3. Asynchronous Programming

### 3.1 Non-Blocking Code

Klabautermann is highly I/O bound. Never block:

```python
# GOOD: Non-blocking sleep
await asyncio.sleep(1)

# BAD: Blocks entire event loop
import time
time.sleep(1)  # NEVER DO THIS
```

### 3.2 Concurrent Execution

Use `asyncio.gather()` for parallel operations:

```python
# GOOD: Run multiple searches in parallel
async def search_all(queries: List[str]) -> List[SearchResult]:
    tasks = [graphiti.search(q) for q in queries]
    results = await asyncio.gather(*tasks)
    return [r for sublist in results for r in sublist]

# BAD: Sequential (slow)
async def search_all_slow(queries: List[str]) -> List[SearchResult]:
    results = []
    for q in queries:
        result = await graphiti.search(q)
        results.extend(result)
    return results
```

### 3.3 Background Tasks

Use `asyncio.create_task()` for fire-and-forget operations:

```python
# Fire-and-forget ingestion (don't make user wait)
asyncio.create_task(
    self._dispatch_to_agent("ingestor", intent, text, trace_id)
)

# User gets immediate response while ingestion happens in background
return await self._generate_response(...)
```

### 3.4 Timeouts

Always set timeouts for external calls:

```python
try:
    result = await asyncio.wait_for(
        external_api_call(),
        timeout=30.0
    )
except asyncio.TimeoutError:
    logger.error("[STORM] External API timed out")
    raise
```

---

## 4. Database & Graph Best Practices

### 4.1 Parametrized Queries

**CRITICAL**: Never use f-strings for Cypher. This prevents Cypher injection:

```python
# GOOD: Parametrized (safe)
query = "MATCH (p:Person {name: $name}) RETURN p"
await session.run(query, name=user_input)

# BAD: String interpolation (DANGEROUS - Cypher injection!)
query = f"MATCH (p:Person {{name: '{user_input}'}}) RETURN p"  # NEVER DO THIS
```

### 4.2 Connection Management

Always use context managers:

```python
# GOOD: Connection properly closed
async with driver.session() as session:
    result = await session.run(query, params)
    records = await result.data()

# BAD: Connection may leak
session = driver.session()
result = await session.run(query, params)
# Forgot to close!
```

### 4.3 Transaction Handling

Use transactions for multi-statement operations:

```python
async def update_employment(person_uuid: str, new_org_uuid: str, title: str):
    """Atomic update: expire old relationship, create new one"""
    async with driver.session() as session:
        async with session.begin_transaction() as tx:
            try:
                # Expire old
                await tx.run("""
                    MATCH (p:Person {uuid: $person_uuid})-[r:WORKS_AT]->(o)
                    WHERE r.expired_at IS NULL
                    SET r.expired_at = timestamp()
                """, person_uuid=person_uuid)

                # Create new
                await tx.run("""
                    MATCH (p:Person {uuid: $person_uuid})
                    MATCH (o:Organization {uuid: $org_uuid})
                    CREATE (p)-[:WORKS_AT {created_at: timestamp(), title: $title}]->(o)
                """, person_uuid=person_uuid, org_uuid=new_org_uuid, title=title)

                await tx.commit()
            except Exception:
                await tx.rollback()
                raise
```

---

## 5. Error Handling & Resilience

### 5.1 Exponential Backoff

All external API calls must implement retry with backoff:

```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16)
)
async def call_anthropic(prompt: str) -> str:
    """Call Claude with automatic retry on failure"""
    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        messages=[{"role": "user", "content": prompt}]
    )
    return response.content[0].text
```

### 5.2 Graceful Degradation

Never crash the user experience:

```python
async def handle_user_input(self, text: str) -> str:
    try:
        response = await self._process_with_agents(text)
        return response
    except ExternalServiceError as e:
        logger.error(f"[STORM] External service failed: {e}")
        return "I'm having trouble accessing external services right now. Please try again in a moment."
    except GraphConnectionError as e:
        logger.error(f"[SHIPWRECK] Graph connection lost: {e}")
        return "I've lost connection to The Locker. Working on getting it back..."
    except Exception as e:
        logger.error(f"[SHIPWRECK] Unexpected error: {e}", exc_info=True)
        return "Something unexpected happened. I've logged the issue."
```

### 5.3 Circuit Breaker Pattern

Prevent cascading failures:

```python
from datetime import datetime, timedelta
from collections import deque

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout: timedelta = timedelta(minutes=5)):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures: deque = deque(maxlen=failure_threshold)
        self.state = "closed"  # closed, open, half_open

    async def call(self, func, *args, **kwargs):
        if self.state == "open":
            if datetime.now() - self.failures[-1] > self.timeout:
                self.state = "half_open"
            else:
                raise CircuitOpenError("Service unavailable - circuit breaker open")

        try:
            result = await func(*args, **kwargs)
            if self.state == "half_open":
                self.state = "closed"
                self.failures.clear()
            return result
        except Exception as e:
            self.failures.append(datetime.now())
            if len(self.failures) >= self.failure_threshold:
                self.state = "open"
                logger.error(f"[SHIPWRECK] Circuit breaker opened for {func.__name__}")
            raise
```

---

## 6. Logging Standards

### 6.1 Use Logger, Not Print

```python
# GOOD
from klabautermann.core.logger import logger

logger.info("[CHART] Processing user request", extra={"trace_id": trace_id})

# BAD
print("Processing user request")  # NEVER use print for operational output
```

### 6.2 Structured Logging

Always include context:

```python
logger.info(
    f"[CHART] {trace_id} | {agent_name} | Delegating to {target_agent}",
    extra={
        "trace_id": trace_id,
        "agent": agent_name,
        "target": target_agent,
        "intent": intent
    }
)
```

### 6.3 Log Levels

| Level | Nautical | Usage |
|-------|----------|-------|
| DEBUG | [WHISPER] | Internal state, raw LLM prompts |
| INFO | [CHART] | Navigational progress |
| SUCCESS | [BEACON] | Successful operations |
| WARNING | [SWELL] | Recoverable issues |
| ERROR | [STORM] | Failed actions |
| CRITICAL | [SHIPWRECK] | System-level failures |

---

## 7. Code Organization

### 7.1 Module Structure

```python
# klabautermann/agents/researcher.py

"""
Researcher Agent - The Librarian of The Locker

Performs hybrid search (vector + graph traversal) to answer queries.
"""

from __future__ import annotations  # Enable forward references

# Standard library
import asyncio
from typing import Optional, List, Dict, Any

# Third-party
from pydantic import BaseModel

# Local
from klabautermann.agents.base_agent import BaseAgent
from klabautermann.core.models import AgentMessage, SearchResult
from klabautermann.core.logger import logger


class ResearcherConfig(BaseModel):
    """Configuration for Researcher agent"""
    model: str = "claude-3-haiku-20240307"
    search_depth: int = 2
    max_results: int = 10


class Researcher(BaseAgent):
    """
    The Researcher agent performs hybrid search across the knowledge graph.

    Search Strategy:
    1. Vector search for semantic similarity
    2. Graph traversal for structural queries
    3. Temporal filtering for time-aware results
    """

    def __init__(self, config: ResearcherConfig, graph_client, mcp_clients: dict):
        super().__init__(config, graph_client, mcp_clients)
        self.config = config

    async def process_message(self, msg: AgentMessage) -> Optional[AgentMessage]:
        """Process search request from Orchestrator"""
        # Implementation...
```

### 7.2 Import Order

1. Standard library
2. Third-party packages
3. Local imports

Use `isort` (or Ruff) to enforce automatically.

### 7.3 Docstrings

Use Google-style docstrings:

```python
async def search_memory(
    self,
    query: str,
    limit: int = 10,
    include_expired: bool = False
) -> List[SearchResult]:
    """
    Search the knowledge graph using hybrid vector + graph traversal.

    Args:
        query: Natural language search query
        limit: Maximum number of results to return
        include_expired: Whether to include historical (expired) facts

    Returns:
        List of SearchResult objects with facts and metadata

    Raises:
        GraphConnectionError: If connection to Neo4j is lost
        ValueError: If query is empty

    Example:
        >>> results = await researcher.search_memory("Who is Sarah?")
        >>> print(results[0].fact)
        "Sarah Chen is a PM at Acme Corp"
    """
```

---

## 8. Security

### 8.1 Secrets Management

```python
# GOOD: Use environment variables
import os
api_key = os.getenv("ANTHROPIC_API_KEY")

# BAD: Hardcoded secrets
api_key = "sk-ant-..."  # NEVER commit secrets!
```

### 8.2 .gitignore

Always exclude:
```
.env
*.pem
*.key
credentials.json
.google_token.json
logs/
data/
__pycache__/
.pytest_cache/
```

### 8.3 Input Sanitization

```python
def sanitize_user_input(content: str) -> str:
    """Basic input sanitization"""
    # Limit length
    max_length = 4000
    if len(content) > max_length:
        content = content[:max_length]

    # Remove potential code blocks that might confuse the LLM
    content = content.replace("```", "")

    return content.strip()
```

---

## 9. Tooling Configuration

### 9.1 pyproject.toml

```toml
[project]
name = "klabautermann"
version = "0.1.0"
requires-python = ">=3.11"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = [
    "E",    # pycodestyle errors
    "W",    # pycodestyle warnings
    "F",    # Pyflakes
    "I",    # isort
    "B",    # flake8-bugbear
    "C4",   # flake8-comprehensions
    "UP",   # pyupgrade
]
ignore = [
    "E501",  # line too long (handled by formatter)
]

[tool.ruff.lint.isort]
known-first-party = ["klabautermann"]

[tool.mypy]
python_version = "3.11"
warn_return_any = true
warn_unused_ignores = true
disallow_untyped_defs = true
ignore_missing_imports = true

[[tool.mypy.overrides]]
module = "tests.*"
disallow_untyped_defs = false
```

### 9.2 Pre-commit Configuration

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.5.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
      - id: check-yaml
      - id: check-added-large-files
      - id: check-toml

  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.1.6
    hooks:
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]
      - id: ruff-format

  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.7.1
    hooks:
      - id: mypy
        additional_dependencies: [pydantic, types-requests]
        args: [--ignore-missing-imports]
```

### 9.3 Running Checks

```bash
# Install pre-commit
pip install pre-commit
pre-commit install

# Run all checks manually
pre-commit run --all-files

# Run specific check
ruff check .
mypy klabautermann/
```

---

## 10. Quick Reference

### 10.1 Do's

- Use Pydantic for all data models
- Use `async`/`await` for I/O operations
- Parametrize all database queries
- Log with trace IDs
- Handle errors gracefully
- Write type hints
- Use context managers for resources

### 10.2 Don'ts

- Don't use `print()` for logging
- Don't use f-strings in Cypher queries
- Don't use `time.sleep()`
- Don't commit secrets
- Don't trust LLM output without validation
- Don't catch bare `Exception` without re-raising
- Don't leave connections open

---

*"Clean code is like a well-maintained ship—it sails smoothly through any storm."* - Klabautermann
