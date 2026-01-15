# Klabautermann Deployment Guide

**Version**: 1.0
**Purpose**: Docker-based deployment and infrastructure setup

---

## Overview

Klabautermann is deployed as a containerized application using **Docker Compose**. The system consists of:

1. **klabautermann-app**: The main Python application (agents, channels, MCP clients)
2. **neo4j**: Graph database for the knowledge graph

```
┌─────────────────────────────────────────────────────────────┐
│                    Docker Compose                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────┐    ┌─────────────────────┐        │
│  │  klabautermann-app  │───▶│       neo4j         │        │
│  │                     │    │                     │        │
│  │  • Orchestrator     │    │  • Graph Database   │        │
│  │  • Sub-agents       │    │  • Vector Index     │        │
│  │  • CLI Driver       │    │  • Bolt: 7687       │        │
│  │  • Telegram Bot     │    │  • Browser: 7474    │        │
│  └─────────────────────┘    └─────────────────────┘        │
│           │                          │                      │
│           ▼                          ▼                      │
│     ./logs:/app/logs          neo4j_data:/data             │
│     ./data:/app/data                                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

---

## 1. Prerequisites

### 1.1 System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| CPU | 2 cores | 4 cores |
| RAM | 4 GB | 8 GB |
| Disk | 20 GB | 50 GB |
| OS | Linux, macOS, Windows (WSL2) | Linux |

### 1.2 Software Requirements

| Software | Version | Purpose |
|----------|---------|---------|
| Docker | 24.0+ | Containerization |
| Docker Compose | 2.20+ | Service orchestration |
| Node.js | 18+ | MCP servers (npx) |
| Python | 3.11+ | Local development |

### 1.3 Required Credentials

| Credential | How to Obtain |
|------------|---------------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `OPENAI_API_KEY` | [platform.openai.com](https://platform.openai.com) |
| `GOOGLE_CLIENT_ID` | [Google Cloud Console](https://console.cloud.google.com/apis/credentials) |
| `GOOGLE_CLIENT_SECRET` | Google Cloud Console (same as above) |
| `GOOGLE_REFRESH_TOKEN` | Run `scripts/bootstrap_auth.py` |
| `TELEGRAM_BOT_TOKEN` | [@BotFather](https://t.me/botfather) on Telegram |

---

## 2. Project Structure

```
klabautermann/
├── .env                        # YOUR SECRETS (never commit!)
├── .env.example                # Template for developers
├── .gitignore                  # Excludes .env, logs, data
├── docker-compose.yml          # Service orchestration
├── Dockerfile                  # App container definition
├── pyproject.toml              # Python dependencies & tools
├── requirements.txt            # Pinned dependencies
│
├── klabautermann/              # Main Python package
│   ├── __init__.py
│   ├── main.py                 # Entry point
│   ├── agents/                 # AI agents
│   ├── channels/               # Communication drivers
│   ├── core/                   # Models, ontology, logger
│   ├── memory/                 # Graph clients
│   ├── mcp/                    # MCP integration
│   ├── persona/                # Personality engine
│   └── utils/                  # Utilities
│
├── config/                     # Configuration files
│   ├── agents/                 # Agent configs (YAML)
│   └── personality.yaml        # Branding config
│
├── scripts/                    # Operational scripts
│   ├── bootstrap_auth.py       # Google OAuth setup
│   └── init_database.py        # Neo4j schema setup
│
├── tests/                      # Test suite
├── data/                       # Persistent data (mounted)
└── logs/                       # Log files (mounted)
```

---

## 3. Environment Configuration

### 3.1 Create .env File

```bash
# Copy the template
cp .env.example .env

# Edit with your credentials
nano .env
```

### 3.2 .env.example Template

```bash
# ===========================================
# Klabautermann Environment Configuration
# ===========================================

# --- LLM Configuration ---
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# --- Database ---
NEO4J_URI=bolt://neo4j:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=your-secure-password-here

# --- Google Workspace (OAuth2) ---
GOOGLE_CLIENT_ID=123456789.apps.googleusercontent.com
GOOGLE_CLIENT_SECRET=GOCSPX-...
GOOGLE_REFRESH_TOKEN=1//0e...

# --- Telegram ---
TELEGRAM_BOT_TOKEN=123456789:ABC...

# --- Channel Configuration ---
ENABLE_CLI=true
ENABLE_TELEGRAM=false

# --- Optional ---
LOG_LEVEL=INFO
PERSONALITY_INTENSITY=0.6
```

---

## 4. Docker Configuration

### 4.1 docker-compose.yml

```yaml
version: '3.8'

services:
  klabautermann-app:
    build:
      context: .
      dockerfile: Dockerfile
    container_name: klabautermann-app
    env_file: .env
    environment:
      - NEO4J_URI=bolt://neo4j:7687
    depends_on:
      neo4j:
        condition: service_healthy
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs
      - ./config:/app/config:ro
    stdin_open: true    # Required for CLI
    tty: true           # Required for CLI
    restart: unless-stopped
    networks:
      - klabautermann-network

  neo4j:
    image: neo4j:5.26-community
    container_name: klabautermann-neo4j
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
      - NEO4J_PLUGINS=["apoc"]
      - NEO4J_dbms_security_procedures_unrestricted=apoc.*
      - NEO4J_dbms_memory_heap_initial__size=512m
      - NEO4J_dbms_memory_heap_max__size=1G
    ports:
      - "7474:7474"   # Browser UI
      - "7687:7687"   # Bolt protocol
    volumes:
      - neo4j_data:/data
      - neo4j_logs:/logs
    healthcheck:
      test: ["CMD", "neo4j", "status"]
      interval: 10s
      timeout: 5s
      retries: 5
    restart: unless-stopped
    networks:
      - klabautermann-network

volumes:
  neo4j_data:
  neo4j_logs:

networks:
  klabautermann-network:
    driver: bridge
```

### 4.2 Dockerfile

```dockerfile
# Klabautermann Application Dockerfile
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gnupg \
    && rm -rf /var/lib/apt/lists/*

# Install Node.js (for MCP servers)
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs

# Copy requirements first (for caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY klabautermann/ ./klabautermann/
COPY config/ ./config/
COPY scripts/ ./scripts/

# Create directories for volumes
RUN mkdir -p /app/data /app/logs

# Set Python path
ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1

# Default command (CLI mode)
CMD ["python", "-m", "klabautermann.main"]
```

### 4.3 requirements.txt

```
# Core LLM
anthropic>=0.40.0
openai>=1.54.0

# Graph & Memory
graphiti-core>=0.3.0
neo4j>=5.26.0

# MCP
mcp>=1.0.0

# Communication Channels
python-telegram-bot>=21.0

# Google Workspace
google-auth>=2.35.0
google-auth-oauthlib>=1.2.0
google-api-python-client>=2.149.0

# Data Validation
pydantic>=2.10.0
pydantic-settings>=2.0.0

# Configuration
python-dotenv>=1.0.0
pyyaml>=6.0
watchdog>=5.0.0

# Async
aiohttp>=3.10.0
aioschedule>=0.5.2

# Logging
structlog>=24.1.0
python-json-logger>=3.1.0

# Utilities
tenacity>=8.2.0
```

---

## 5. Deployment Steps

### 5.1 First-Time Setup

```bash
# 1. Clone repository
git clone https://github.com/your-org/klabautermann.git
cd klabautermann

# 2. Create environment file
cp .env.example .env
# Edit .env with your credentials

# 3. Start Neo4j first (let it initialize)
docker-compose up -d neo4j

# 4. Wait for Neo4j to be healthy (30-60 seconds)
docker-compose logs -f neo4j
# Look for: "Started."

# 5. Initialize database schema
docker-compose run --rm klabautermann-app python scripts/init_database.py

# 6. Verify Neo4j setup
# Open http://localhost:7474
# Login: neo4j / <your NEO4J_PASSWORD>
# Run: SHOW CONSTRAINTS
# Run: SHOW INDEXES
```

### 5.2 Google OAuth Bootstrap

```bash
# Run locally (needs browser)
python scripts/bootstrap_auth.py

# Follow prompts to authorize
# Copy the GOOGLE_REFRESH_TOKEN to .env
```

### 5.3 Start Full System

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f klabautermann-app

# Attach to CLI
docker attach klabautermann-app

# Detach from CLI (without stopping)
# Press: Ctrl+P, Ctrl+Q
```

### 5.4 Enable Telegram

```bash
# 1. Get bot token from @BotFather
# 2. Add to .env: TELEGRAM_BOT_TOKEN=...
# 3. Set ENABLE_TELEGRAM=true in .env
# 4. Restart
docker-compose restart klabautermann-app
```

---

## 6. Verification Checklist

### 6.1 Infrastructure Verification

```bash
# Check all containers are running
docker-compose ps
# Expected: Both services "Up (healthy)"

# Check Neo4j connectivity
docker-compose exec neo4j cypher-shell -u neo4j -p <password> "RETURN 1"
# Expected: 1

# Check logs for errors
docker-compose logs --tail=100 klabautermann-app | grep -i error
# Expected: No critical errors
```

### 6.2 Functional Verification

```bash
# 1. Attach to CLI
docker attach klabautermann-app

# 2. Test basic conversation
You > Hello, Klabautermann!
# Expected: Greeting response

# 3. Test ingestion
You > I met Sarah from Acme Corp today
# Expected: Acknowledgment

# 4. Test retrieval
You > Who is Sarah?
# Expected: "Sarah... Acme Corp..."

# 5. Verify in Neo4j
# Open http://localhost:7474
# Run: MATCH (p:Person {name: 'Sarah'}) RETURN p
# Expected: Node found
```

---

## 7. Configuration Options

### 7.1 Docker Compose Profiles

```yaml
# Add profiles for different deployment modes
services:
  klabautermann-app:
    profiles: ["cli", "full"]
    # ...

  telegram-bot:
    profiles: ["telegram", "full"]
    # Separate service for Telegram (if needed)
```

```bash
# Start only CLI
docker-compose --profile cli up -d

# Start everything
docker-compose --profile full up -d
```

### 7.2 Resource Limits

```yaml
services:
  klabautermann-app:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M

  neo4j:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
```

### 7.3 Logging Configuration

```yaml
services:
  klabautermann-app:
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

---

## 8. Operations

### 8.1 Common Commands

```bash
# Start services
docker-compose up -d

# Stop services
docker-compose down

# Restart specific service
docker-compose restart klabautermann-app

# View logs
docker-compose logs -f klabautermann-app

# Execute command in container
docker-compose exec klabautermann-app python -c "print('Hello')"

# Access Neo4j shell
docker-compose exec neo4j cypher-shell -u neo4j -p <password>
```

### 8.2 Backup & Restore

```bash
# Backup Neo4j data
docker-compose exec neo4j neo4j-admin database dump neo4j --to-path=/backups
docker cp klabautermann-neo4j:/backups/neo4j.dump ./backups/

# Restore Neo4j data
docker cp ./backups/neo4j.dump klabautermann-neo4j:/backups/
docker-compose exec neo4j neo4j-admin database load neo4j --from-path=/backups/neo4j.dump
```

### 8.3 Monitoring

```bash
# Container stats
docker stats klabautermann-app klabautermann-neo4j

# Neo4j metrics
# Open http://localhost:7474
# Run: CALL dbms.queryJmx('org.neo4j:*')
```

---

## 9. Troubleshooting

### 9.1 Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Neo4j won't start | Password not set | Check `NEO4J_PASSWORD` in .env |
| App can't connect to Neo4j | Wrong URI | Use `bolt://neo4j:7687` (Docker network) |
| MCP tools fail | Node.js not installed | Ensure Node.js 18+ in Dockerfile |
| Telegram bot not responding | Token invalid | Regenerate via @BotFather |
| Out of memory | Neo4j heap | Increase `NEO4J_dbms_memory_heap_max__size` |

### 9.2 Debug Mode

```bash
# Run with debug logging
docker-compose run --rm -e LOG_LEVEL=DEBUG klabautermann-app

# Check Neo4j connectivity from app container
docker-compose exec klabautermann-app python -c "
from neo4j import GraphDatabase
driver = GraphDatabase.driver('bolt://neo4j:7687', auth=('neo4j', 'password'))
with driver.session() as session:
    result = session.run('RETURN 1 as test')
    print(result.single()['test'])
"
```

### 9.3 Reset Everything

```bash
# Stop and remove everything (including volumes!)
docker-compose down -v

# Remove images
docker rmi klabautermann-app

# Fresh start
docker-compose up -d --build
```

---

## 10. Production Considerations

### 10.1 Security

- [ ] Use strong `NEO4J_PASSWORD` (16+ characters)
- [ ] Restrict Neo4j ports (don't expose 7474/7687 publicly)
- [ ] Use secrets management (Docker secrets or Vault) for production
- [ ] Enable TLS for Neo4j connections
- [ ] Restrict Telegram bot to allowed user IDs

### 10.2 High Availability

For production deployments:
- Use Neo4j Cluster (Enterprise) or Aura
- Deploy app behind load balancer
- Implement health checks and auto-restart

### 10.3 Monitoring & Alerting

- Set up log aggregation (ELK, Loki)
- Configure alerts for:
  - Container restarts
  - Neo4j connection failures
  - API rate limits hit
  - Disk space warnings

---

## 11. Quick Reference

### 11.1 URLs

| Service | URL | Purpose |
|---------|-----|---------|
| Neo4j Browser | http://localhost:7474 | Graph visualization |
| Neo4j Bolt | bolt://localhost:7687 | Database connection |

### 11.2 Environment Variables

| Variable | Required | Default |
|----------|----------|---------|
| `ANTHROPIC_API_KEY` | Yes | - |
| `OPENAI_API_KEY` | Yes | - |
| `NEO4J_PASSWORD` | Yes | - |
| `GOOGLE_REFRESH_TOKEN` | For Gmail/Calendar | - |
| `TELEGRAM_BOT_TOKEN` | For Telegram | - |
| `ENABLE_CLI` | No | `true` |
| `ENABLE_TELEGRAM` | No | `false` |
| `LOG_LEVEL` | No | `INFO` |

### 11.3 Default Ports

| Port | Service | Protocol |
|------|---------|----------|
| 7474 | Neo4j Browser | HTTP |
| 7687 | Neo4j Bolt | TCP |

---

*"A well-rigged ship sails smoothly through any storm."* - Klabautermann
