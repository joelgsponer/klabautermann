# Create Python Dockerfile

## Metadata
- **ID**: T002
- **Priority**: P0
- **Category**: deployment
- **Effort**: S
- **Status**: pending
- **Assignee**: @devops-engineer

## Specs
- Primary: [DEPLOYMENT.md](../../specs/infrastructure/DEPLOYMENT.md)
- Related: [CODING_STANDARDS.md](../../specs/quality/CODING_STANDARDS.md)

## Dependencies
- [ ] T001 - Docker Compose configuration (for integration)

## Context
The Dockerfile defines the Python runtime environment for Klabautermann. It must support both development (with hot-reload) and production deployment, while maintaining security best practices.

## Requirements
- [ ] Create `Dockerfile` in project root
- [ ] Use Python 3.11+ base image
- [ ] Install system dependencies for:
  - Neo4j driver (requires libssl)
  - Async networking
- [ ] Set up dependency management (pip + requirements.txt or Poetry)
- [ ] Configure non-root user for security
- [ ] Set working directory to `/app`
- [ ] Copy application code
- [ ] Define entrypoint for CLI mode

## Acceptance Criteria
- [ ] `docker build -t klabautermann .` completes without errors
- [ ] Container runs as non-root user
- [ ] Python version is 3.11+
- [ ] All dependencies install correctly
- [ ] Application starts when container runs

## Implementation Notes

Recommended structure:
```dockerfile
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 klabautermann
USER klabautermann

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY --chown=klabautermann:klabautermann . .

ENTRYPOINT ["python", "main.py"]
```

Consider:
- Multi-stage build for smaller production image
- .dockerignore to exclude unnecessary files
- Build arguments for development vs production
