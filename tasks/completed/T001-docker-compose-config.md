# Create Docker Compose Configuration

## Metadata
- **ID**: T001
- **Priority**: P0
- **Category**: deployment
- **Effort**: M
- **Status**: pending
- **Assignee**: @devops-engineer

## Specs
- Primary: [DEPLOYMENT.md](../../specs/infrastructure/DEPLOYMENT.md)
- Related: [PRD.md](../../specs/PRD.md) Section 9

## Dependencies
- None (foundational task)

## Context
Docker Compose is the foundation of our development and deployment environment. This configuration must support both local development and production deployment, with Neo4j 5.26+ as the graph database backing the temporal knowledge graph.

## Requirements
- [ ] Create `docker-compose.yml` in project root
- [ ] Configure Neo4j 5.26+ service with:
  - Browser port 7474 exposed
  - Bolt port 7687 exposed
  - Persistent volume for data
  - Environment-based authentication
  - Memory configuration suitable for development
- [ ] Configure Python application service with:
  - Build from local Dockerfile
  - Environment file loading
  - Depends on Neo4j health check
  - Volume mounts for code (development), data, and logs
- [ ] Create shared network for service communication
- [ ] Add health checks for both services

## Acceptance Criteria
- [ ] `docker-compose up -d` starts both containers
- [ ] `docker-compose ps` shows both services healthy
- [ ] Neo4j Browser accessible at http://localhost:7474
- [ ] Python container can connect to Neo4j via `neo4j://neo4j:7687`
- [ ] Data persists across `docker-compose down` and `up`
- [ ] Logs directory populated with output

## Implementation Notes

Reference structure from PRD:
```yaml
services:
  klabautermann-app:
    build: .
    env_file: .env
    depends_on:
      - neo4j
    volumes:
      - ./data:/app/data
      - ./logs:/app/logs

  neo4j:
    image: neo4j:5.26
    ports:
      - "7474:7474"
      - "7687:7687"
    environment:
      - NEO4J_AUTH=neo4j/${NEO4J_PASSWORD}
```

Consider adding:
- Memory limits for Neo4j (pagecache, heap)
- Restart policies
- Docker network with explicit name
- Health check commands

Neo4j plugins to enable:
- APOC (for utility procedures)
- GDS (for future community detection in Phase 3)
