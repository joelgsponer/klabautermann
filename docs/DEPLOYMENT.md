# Deployment Guide

This document covers deploying Klabautermann to production environments.

## Table of Contents

- [Docker Deployment](#docker-deployment)
- [Environment Setup](#environment-setup)
- [Scaling](#scaling)
- [Monitoring](#monitoring)
- [Backup & Recovery](#backup--recovery)
- [Troubleshooting](#troubleshooting)

---

## Docker Deployment

### Prerequisites

- Docker Engine 20.10+
- Docker Compose v2+
- Minimum 8GB RAM available
- 20GB disk space

### Quick Start

```bash
# Clone repository
git clone https://github.com/joelgsponer/klabautermann.git
cd klabautermann

# Create environment file
cp .env.example .env
# Edit .env with production values (see Environment Setup)

# Start production stack
docker-compose -f docker-compose.prod.yml up -d

# Check status
docker-compose -f docker-compose.prod.yml ps

# View logs
docker-compose -f docker-compose.prod.yml logs -f
```

### Production Configuration

The `docker-compose.prod.yml` includes:

- **Neo4j**: Graph database with production memory settings
- **klabautermann-app**: Application container
- **Resource limits**: CPU and memory constraints
- **Health checks**: Automatic container restarts
- **Log rotation**: Prevents disk exhaustion

### Building Custom Images

```bash
# Build production image
docker build -t klabautermann:latest --target production .

# Tag for registry
docker tag klabautermann:latest your-registry/klabautermann:v1.0.0

# Push to registry
docker push your-registry/klabautermann:v1.0.0
```

### Volume Mounts

| Volume | Purpose | Persistence |
|--------|---------|-------------|
| `neo4j_data` | Graph database | Required |
| `neo4j_logs` | Database logs | Recommended |
| `neo4j_plugins` | APOC plugins | Required |
| `app_data` | Application data | Required |
| `app_logs` | Application logs | Recommended |
| `./backups` | Backup storage | Required |

---

## Environment Setup

### Required Variables

```bash
# API Keys (required)
ANTHROPIC_API_KEY=sk-ant-api03-...
OPENAI_API_KEY=sk-...

# Database (required)
NEO4J_PASSWORD=your-secure-password-here
NEO4J_URI=bolt://neo4j:7687
NEO4J_USERNAME=neo4j
```

### Optional Variables

```bash
# Logging
LOG_LEVEL=INFO               # DEBUG, INFO, WARNING, ERROR
LOG_FORMAT=json              # json for production, text for development

# Google Workspace (optional)
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REFRESH_TOKEN=...

# Telegram (optional)
TELEGRAM_BOT_TOKEN=...
```

### Secret Management

**Never commit secrets to version control.**

Best practices:
1. Use Docker secrets or environment files
2. Consider HashiCorp Vault for enterprise deployments
3. Rotate API keys periodically
4. Use read-only filesystem where possible

```bash
# Using Docker secrets
echo "sk-ant-api03-..." | docker secret create anthropic_api_key -

# Reference in compose file
services:
  app:
    secrets:
      - anthropic_api_key
```

### Google OAuth Setup (Production)

1. Create a project in [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Gmail API and Calendar API
3. Create OAuth 2.0 credentials (Web application type for production)
4. Set redirect URI to your production domain
5. Run authentication flow:

```bash
# On a machine with browser access
python scripts/bootstrap_auth.py

# Copy GOOGLE_REFRESH_TOKEN to production .env
```

---

## Scaling

### Memory Requirements

| Component | Minimum | Recommended | High Traffic |
|-----------|---------|-------------|--------------|
| Neo4j | 4GB | 6GB | 16GB+ |
| Application | 1GB | 2GB | 4GB |
| Total | 6GB | 8GB | 20GB+ |

### CPU Recommendations

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| Neo4j | 1 core | 2 cores |
| Application | 0.5 cores | 1 core |

### Horizontal Scaling

Klabautermann is designed for single-instance deployment. For high availability:

1. **Neo4j**: Use Neo4j Cluster (Enterprise) or Aura (managed)
2. **Application**: Run behind load balancer with sticky sessions
3. **API**: The FastAPI server supports multiple workers

```bash
# Multiple API workers
uvicorn klabautermann.api:app --workers 4 --host 0.0.0.0 --port 8765
```

### Neo4j Clustering

For enterprise deployments requiring HA:

```yaml
# docker-compose.cluster.yml (example)
services:
  neo4j-core1:
    image: neo4j:5.26-enterprise
    environment:
      - NEO4J_ACCEPT_LICENSE_AGREEMENT=yes
      - NEO4J_causal__clustering_minimum__core__cluster__size__at__formation=3
      # ... additional cluster config
```

---

## Monitoring

### Health Checks

Both containers include health checks:

```bash
# Check Neo4j health
curl -f http://localhost:7474 || echo "Neo4j unhealthy"

# Check application (via API)
curl -f http://localhost:8765/health || echo "App unhealthy"
```

### Log Aggregation

Logs are JSON-formatted for easy parsing:

```bash
# View recent logs
docker-compose -f docker-compose.prod.yml logs --tail=100

# Stream logs to external system
docker-compose -f docker-compose.prod.yml logs -f | your-log-shipper
```

Recommended log aggregation tools:
- Loki + Grafana
- ELK Stack (Elasticsearch, Logstash, Kibana)
- CloudWatch Logs (AWS)

### Metrics to Monitor

| Metric | Warning | Critical |
|--------|---------|----------|
| Neo4j heap usage | > 80% | > 95% |
| Neo4j page cache hits | < 90% | < 70% |
| Container memory | > 80% | > 95% |
| API response time | > 2s | > 5s |
| Error rate | > 1% | > 5% |

### Alerting

Configure alerts for:
- Container restarts
- Health check failures
- High memory usage
- API error rates
- Database connection failures

---

## Backup & Recovery

### Neo4j Backup

```bash
# Create backup
docker exec klabautermann-neo4j-prod neo4j-admin database dump neo4j --to-path=/backups/

# List backups
ls -la backups/

# Backup is stored in ./backups/ (mounted volume)
```

### Automated Backups

Add to crontab:

```bash
# Daily backup at 2 AM
0 2 * * * docker exec klabautermann-neo4j-prod neo4j-admin database dump neo4j --to-path=/backups/backup-$(date +\%Y\%m\%d).dump
```

### Restore Procedure

```bash
# Stop application
docker-compose -f docker-compose.prod.yml stop klabautermann-app

# Stop Neo4j
docker-compose -f docker-compose.prod.yml stop neo4j

# Restore from backup
docker run --rm \
  -v klabautermann-neo4j-data-prod:/data \
  -v $(pwd)/backups:/backups \
  neo4j:5.26-community \
  neo4j-admin database load neo4j --from-path=/backups/backup-20260120.dump --overwrite-destination

# Start services
docker-compose -f docker-compose.prod.yml up -d
```

### Disaster Recovery

1. **Regular backups**: Daily automated backups
2. **Off-site storage**: Copy backups to cloud storage (S3, GCS)
3. **Test restores**: Monthly restore tests
4. **Documentation**: Keep recovery procedures updated

---

## Troubleshooting

### Container Won't Start

```bash
# Check logs
docker-compose -f docker-compose.prod.yml logs neo4j
docker-compose -f docker-compose.prod.yml logs klabautermann-app

# Check resource usage
docker stats

# Verify environment
docker-compose -f docker-compose.prod.yml config
```

### Neo4j Connection Issues

```bash
# Test connection from app container
docker exec klabautermann-app-prod \
  python -c "from neo4j import GraphDatabase; d = GraphDatabase.driver('bolt://neo4j:7687', auth=('neo4j', 'password')); d.verify_connectivity()"
```

### Memory Issues

```bash
# Check Neo4j heap
docker exec klabautermann-neo4j-prod \
  curl -s http://localhost:7474/db/system/tx/commit \
  -H "Content-Type: application/json" \
  -d '{"statements":[{"statement":"CALL dbms.listConfig() YIELD name, value WHERE name CONTAINS \"memory\" RETURN name, value"}]}'

# Increase limits in docker-compose.prod.yml if needed
```

### Reset Everything

```bash
# WARNING: This deletes all data!
docker-compose -f docker-compose.prod.yml down -v
docker-compose -f docker-compose.prod.yml up -d
```

---

## Security Checklist

- [ ] Strong NEO4J_PASSWORD set
- [ ] API keys stored securely
- [ ] Neo4j browser (7474) not exposed externally
- [ ] HTTPS/TLS configured for API
- [ ] Firewall rules restrict access
- [ ] Regular security updates applied
- [ ] Backup encryption enabled
- [ ] Access logs reviewed regularly
