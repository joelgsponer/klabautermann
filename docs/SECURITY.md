# Security Guide

This document covers security best practices for deploying and developing Klabautermann.

## Table of Contents

- [Threat Model](#threat-model)
- [API Key Management](#api-key-management)
- [Database Security](#database-security)
- [Input Validation](#input-validation)
- [LLM Output Validation](#llm-output-validation)
- [Network Security](#network-security)
- [Authentication](#authentication)
- [Audit Logging](#audit-logging)
- [Security Checklist](#security-checklist)

---

## Threat Model

### Assets to Protect

1. **API Keys**: Anthropic, OpenAI, Google OAuth credentials
2. **Personal Data**: Emails, calendar events, contacts stored in knowledge graph
3. **Conversation History**: Thread content, summaries, journal entries
4. **System Access**: Neo4j database, MCP tool execution

### Threat Categories

| Threat | Risk | Mitigation |
|--------|------|------------|
| API key exposure | High | Environment variables, never in code |
| Injection attacks | High | Parametrized queries, Pydantic validation |
| Unauthorized access | Medium | Network isolation, authentication |
| Data exfiltration | Medium | Access controls, audit logging |
| LLM manipulation | Low | Output validation, action confirmation |

---

## API Key Management

### Environment Variables

All secrets are stored in environment variables, never in code.

```bash
# Required keys
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-...
NEO4J_PASSWORD=...

# Optional integrations
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...
TELEGRAM_BOT_TOKEN=...
```

### Best Practices

1. **Never commit `.env` files** - Included in `.gitignore`
2. **Rotate keys periodically** - Especially after suspected exposure
3. **Use minimal permissions** - Request only required OAuth scopes
4. **Separate environments** - Different keys for dev/staging/production

### Docker Secrets (Production)

For production deployments, use Docker secrets instead of environment variables:

```yaml
# docker-compose.prod.yml
services:
  app:
    secrets:
      - anthropic_api_key
      - neo4j_password

secrets:
  anthropic_api_key:
    external: true
  neo4j_password:
    external: true
```

Create secrets:

```bash
echo "sk-ant-api03-..." | docker secret create anthropic_api_key -
echo "secure-password" | docker secret create neo4j_password -
```

### Key Rotation Procedure

1. Generate new API key from provider console
2. Update environment/secrets with new key
3. Restart application services
4. Verify functionality with new key
5. Revoke old key from provider console

---

## Database Security

### Neo4j Configuration

#### Authentication

Always use strong passwords in production:

```bash
# .env
NEO4J_PASSWORD=<32+ character random password>
```

Generate secure passwords:

```bash
openssl rand -base64 32
```

#### Network Exposure

Neo4j exposes three ports:

| Port | Protocol | Recommendation |
|------|----------|----------------|
| 7474 | HTTP Browser | Block external access |
| 7687 | Bolt | Internal network only |
| 7473 | HTTPS Browser | Block or restrict |

```yaml
# docker-compose.prod.yml
services:
  neo4j:
    ports:
      - "127.0.0.1:7687:7687"  # Bolt - localhost only
    # Do NOT expose 7474/7473 in production
```

### Query Security

All Cypher queries are parametrized to prevent injection attacks.

```python
# GOOD - Parametrized query
query = """
MATCH (p:Person {name: $name})
RETURN p
"""
await client.execute_query(query, {"name": user_input})

# BAD - String interpolation (NEVER do this)
query = f"MATCH (p:Person {{name: '{user_input}'}})"  # Vulnerable!
```

Key files enforcing this pattern:
- `src/klabautermann/memory/queries.py`
- `src/klabautermann/memory/analytics.py`
- `src/klabautermann/memory/context_queries.py`

---

## Input Validation

### Pydantic Models

All external inputs are validated through Pydantic models before processing.

```python
from pydantic import BaseModel, Field, field_validator

class UserMessage(BaseModel):
    content: str = Field(..., min_length=1, max_length=10000)
    channel: str = Field(..., pattern=r"^(cli|telegram|api)$")

    @field_validator("content")
    @classmethod
    def sanitize_content(cls, v: str) -> str:
        # Remove null bytes and control characters
        return v.replace("\x00", "").strip()
```

### Channel-Specific Validation

Each communication channel validates inputs:

- **CLI**: Basic string validation
- **Telegram**: Message size limits, user ID verification
- **API**: Request body schema validation

### File Path Validation

When handling file operations via MCP:

```python
from pathlib import Path

def validate_path(user_path: str, allowed_base: Path) -> Path:
    """Ensure path is within allowed directory."""
    resolved = (allowed_base / user_path).resolve()
    if not resolved.is_relative_to(allowed_base):
        raise ValueError("Path traversal attempt blocked")
    return resolved
```

---

## LLM Output Validation

### Trust Boundary

LLM outputs are untrusted until validated. The system enforces this through:

1. **Structured Output Parsing**: JSON responses parsed through Pydantic
2. **Action Confirmation**: Destructive actions require explicit approval
3. **Output Sanitization**: Responses cleaned before display

### Structured Output Example

```python
class IntentClassification(BaseModel):
    """Validated LLM response for intent detection."""
    intent: str = Field(..., pattern=r"^(question|action|note|meta)$")
    confidence: float = Field(..., ge=0.0, le=1.0)
    entities: list[str] = Field(default_factory=list)

# Parse and validate LLM response
try:
    result = IntentClassification.model_validate_json(llm_response)
except ValidationError as e:
    logger.error(f"Invalid LLM response: {e}")
    # Fall back to safe default
```

### Action Safety Levels

Actions are categorized by risk:

| Level | Examples | Confirmation |
|-------|----------|--------------|
| Read | Search emails, list calendar | None |
| Write | Send email, create event | User confirmation |
| Delete | Delete email, cancel event | Explicit confirmation |
| System | File operations | Restricted scope |

---

## Network Security

### Firewall Rules

Recommended iptables rules for production:

```bash
# Allow SSH from trusted IPs only
iptables -A INPUT -p tcp --dport 22 -s TRUSTED_IP -j ACCEPT
iptables -A INPUT -p tcp --dport 22 -j DROP

# Allow API access (if exposed)
iptables -A INPUT -p tcp --dport 8765 -j ACCEPT

# Block Neo4j browser
iptables -A INPUT -p tcp --dport 7474 -j DROP
iptables -A INPUT -p tcp --dport 7473 -j DROP
```

### TLS Configuration

For production deployments:

1. Use a reverse proxy (nginx, Caddy) for TLS termination
2. Configure HTTPS for all external endpoints
3. Use strong cipher suites

Example nginx configuration:

```nginx
server {
    listen 443 ssl http2;
    server_name klabautermann.example.com;

    ssl_certificate /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Docker Network Isolation

```yaml
# docker-compose.prod.yml
networks:
  internal:
    driver: bridge
    internal: true  # No external access
  external:
    driver: bridge

services:
  neo4j:
    networks:
      - internal  # Database only on internal network

  app:
    networks:
      - internal
      - external  # App can reach internet for APIs
```

---

## Authentication

### Google OAuth

OAuth tokens grant access to user's Gmail and Calendar. Secure handling:

1. **Minimal Scopes**: Request only required permissions
   ```python
   SCOPES = [
       "https://www.googleapis.com/auth/gmail.readonly",
       "https://www.googleapis.com/auth/gmail.send",
       "https://www.googleapis.com/auth/calendar.events",
   ]
   ```

2. **Token Storage**: Store refresh tokens securely (encrypted at rest)

3. **Token Refresh**: Automatic refresh with error handling

### Telegram Bot

Bot tokens should be treated as secrets:

1. Create bot via @BotFather
2. Store token in environment variables
3. Restrict bot to known user IDs (optional)

```python
ALLOWED_USER_IDS = {123456789, 987654321}  # Configure in .env

def is_authorized(user_id: int) -> bool:
    if not ALLOWED_USER_IDS:
        return True  # No restriction
    return user_id in ALLOWED_USER_IDS
```

---

## Audit Logging

### What to Log

- Authentication events (success/failure)
- Tool executions (email send, calendar create)
- Database modifications
- Configuration changes
- Error conditions

### Log Format

Structured JSON logging for easy analysis:

```json
{
  "timestamp": "2026-01-20T10:30:00Z",
  "level": "INFO",
  "event": "tool_executed",
  "tool": "gmail_send",
  "user_id": "cli-user",
  "trace_id": "abc-123",
  "success": true,
  "metadata": {
    "recipient": "john@example.com",
    "subject": "Meeting follow-up"
  }
}
```

### Log Retention

- **Development**: 7 days
- **Production**: 90 days minimum
- **Security Events**: 1 year

### Log Storage

Do not log sensitive data:

```python
# GOOD - Log action without sensitive content
logger.info("Email sent", extra={
    "recipient": email.to,
    "subject_length": len(email.subject),
})

# BAD - Logging email content
logger.info(f"Email sent: {email.body}")  # Never do this!
```

---

## Security Checklist

### Development

- [ ] Never commit `.env` or credentials
- [ ] Use parametrized queries for all database access
- [ ] Validate all LLM outputs through Pydantic
- [ ] Run `make check` before committing

### Deployment

- [ ] Strong `NEO4J_PASSWORD` set (32+ characters)
- [ ] API keys stored as Docker secrets or env vars
- [ ] Neo4j browser (7474) not exposed externally
- [ ] HTTPS/TLS configured for API endpoints
- [ ] Firewall rules restrict access
- [ ] Log rotation configured
- [ ] Backup encryption enabled

### Operations

- [ ] Regular security updates applied
- [ ] API keys rotated quarterly
- [ ] Access logs reviewed weekly
- [ ] Backup restore tested monthly
- [ ] OAuth token scope audited

### Incident Response

1. **Detect**: Monitor logs for anomalies
2. **Contain**: Revoke compromised credentials immediately
3. **Investigate**: Review logs to determine scope
4. **Remediate**: Rotate all potentially affected secrets
5. **Document**: Record incident and lessons learned

---

## Reporting Security Issues

If you discover a security vulnerability:

1. **Do not** open a public GitHub issue
2. Email security concerns to the maintainer directly
3. Include steps to reproduce the issue
4. Allow reasonable time for a fix before disclosure

We aim to respond to security reports within 48 hours.
