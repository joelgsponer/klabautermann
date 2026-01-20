# Troubleshooting Guide

Solutions for common issues with Klabautermann.

## Installation Issues

### uv Not Found

**Symptom**: `command not found: uv`

**Solution**:
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Restart shell or source profile
source ~/.bashrc  # or ~/.zshrc
```

### Dependency Conflicts

**Symptom**: `uv sync` fails with version conflicts

**Solution**:
```bash
# Clear cache and reinstall
uv cache clean
rm -rf .venv
uv sync --frozen
```

### Python Version Mismatch

**Symptom**: `Python 3.11+ required`

**Solution**:
```bash
# Check Python version
python --version

# Use pyenv to install 3.11+
pyenv install 3.11.8
pyenv local 3.11.8
```

## Neo4j Connection Issues

### Connection Refused

**Symptom**: `Connection refused to bolt://localhost:7687`

**Solution**:
```bash
# Check if Neo4j is running
docker ps | grep neo4j

# Start Neo4j
docker compose up -d neo4j

# Wait for it to be ready
docker compose logs -f neo4j
```

### Authentication Failed

**Symptom**: `Neo4j authentication failed`

**Solution**:
1. Verify credentials in `.env`:
   ```bash
   NEO4J_URI=bolt://localhost:7687
   NEO4J_USER=neo4j
   NEO4J_PASSWORD=your-password
   ```

2. Reset password via browser at http://localhost:7474

### Database Locked

**Symptom**: `Database locked by another process`

**Solution**:
```bash
# Stop all containers
docker compose down

# Remove data volume (WARNING: deletes data)
docker volume rm klabautermann_neo4j_data

# Restart
docker compose up -d
```

## API Key Issues

### Invalid API Key

**Symptom**: `Invalid API key provided` or `401 Unauthorized`

**Solution**:
1. Verify key in `.env`:
   ```bash
   ANTHROPIC_API_KEY=sk-ant-...
   ```

2. Check key is valid:
   ```bash
   curl https://api.anthropic.com/v1/messages \
     -H "x-api-key: $ANTHROPIC_API_KEY" \
     -H "anthropic-version: 2023-06-01"
   ```

### Rate Limited

**Symptom**: `Rate limit exceeded`

**Solution**:
- Wait and retry
- Upgrade API tier
- Configure rate limits in `.env`:
  ```bash
  RATE_LIMIT_REQUESTS=30
  RATE_LIMIT_TOKENS=50000
  ```

### Missing API Key

**Symptom**: `ANTHROPIC_API_KEY not set`

**Solution**:
```bash
# Ensure .env exists
cp .env.example .env

# Set the key
echo "ANTHROPIC_API_KEY=your-key" >> .env
```

## Memory/Performance Issues

### Out of Memory

**Symptom**: Process killed or `MemoryError`

**Solution**:
```bash
# Increase Docker memory limit
# In docker-compose.yml:
services:
  neo4j:
    deploy:
      resources:
        limits:
          memory: 4G
```

### Slow Queries

**Symptom**: Searches take >10 seconds

**Solution**:
1. Check Neo4j indexes:
   ```cypher
   SHOW INDEXES
   ```

2. Create missing indexes:
   ```cypher
   CREATE INDEX person_name FOR (p:Person) ON (p.name)
   CREATE INDEX org_name FOR (o:Organization) ON (o.name)
   ```

3. Increase Neo4j heap:
   ```yaml
   NEO4J_server_memory_heap_initial__size: 2G
   NEO4J_server_memory_heap_max__size: 4G
   ```

### High CPU Usage

**Symptom**: Constant 100% CPU

**Solution**:
- Check for runaway processes: `htop`
- Reduce embedding batch size
- Enable caching in settings

## MCP Server Issues

### Server Not Starting

**Symptom**: `MCP server failed to initialize`

**Solution**:
1. Check server installation:
   ```bash
   npx @anthropic/mcp-google-workspace --version
   ```

2. Verify credentials:
   ```bash
   ls ~/.config/mcp/google-workspace/
   ```

### Tool Call Failed

**Symptom**: `Tool execution failed`

**Solution**:
1. Check MCP server logs:
   ```bash
   LOG_LEVEL=DEBUG uv run python -m klabautermann
   ```

2. Test tool directly:
   ```bash
   npx @anthropic/mcp-google-workspace send-email \
     --to "test@example.com" \
     --subject "Test"
   ```

### OAuth Token Expired

**Symptom**: `Invalid credentials` for Gmail/Calendar

**Solution**:
```bash
# Re-authenticate
npx @anthropic/mcp-google-workspace auth

# Remove old token
rm ~/.config/mcp/google-workspace/token.json
```

## Telegram Issues

### Bot Not Responding

**Symptom**: Messages sent, no response

**Solution**:
1. Check whitelist:
   ```bash
   TELEGRAM_ALLOWED_USERS=your-user-id
   ```

2. Verify token:
   ```bash
   curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/getMe"
   ```

3. Check logs for errors:
   ```bash
   LOG_LEVEL=DEBUG uv run python -m klabautermann --channel telegram
   ```

### Webhook Not Working

**Symptom**: Webhook mode fails silently

**Solution**:
1. Verify HTTPS certificate
2. Check webhook URL is accessible
3. Test webhook endpoint:
   ```bash
   curl -X POST https://your-domain.com/telegram/webhook \
     -H "Content-Type: application/json" \
     -d '{"test": true}'
   ```

## Logging & Debugging

### Enable Debug Logs

```bash
LOG_LEVEL=DEBUG uv run python -m klabautermann
```

### View Specific Agent Logs

```bash
# Filter by trace ID
grep "trace_id=abc-123" logs/klabautermann.log

# Filter by agent
grep "agent_name=orchestrator" logs/klabautermann.log
```

### Neo4j Query Logging

```bash
# In Neo4j
CALL dbms.setConfigValue('db.logs.query.enabled', 'true')
```

## Getting Help

### Diagnostic Information

Collect this info when reporting issues:

```bash
# System info
uname -a
python --version
uv --version

# Klabautermann version
cat pyproject.toml | grep version

# Docker status
docker --version
docker compose version
docker ps

# Neo4j status
curl http://localhost:7474/db/neo4j/cluster/available
```

### Where to Get Help

1. **GitHub Issues**: [Report bugs](https://github.com/joelgsponer/klabautermann/issues)
2. **Discussions**: Community help
3. **Contributing Guide**: Development setup

## Quick Fixes Checklist

- [ ] Is `.env` configured with required keys?
- [ ] Is Neo4j running (`docker ps`)?
- [ ] Are API keys valid?
- [ ] Is Python 3.11+ installed?
- [ ] Did you run `uv sync`?
- [ ] Are ports 7474 and 7687 available?
- [ ] Is your Telegram user ID whitelisted?
