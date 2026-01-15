# Klabautermann Dockerfile
# Multi-agent PKM system with temporal knowledge graph
#
# Build: docker build -t klabautermann .
# Run:   docker run -it --env-file .env klabautermann

FROM python:3.11-slim AS base

# Prevent Python from writing pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # Required for neo4j driver
    libssl-dev \
    # For healthchecks
    curl \
    && rm -rf /var/lib/apt/lists/*

# ===========================================================================
# Production Stage
# ===========================================================================
FROM base AS production

# Create non-root user for security
RUN groupadd --gid 1000 klabautermann && \
    useradd --uid 1000 --gid klabautermann --shell /bin/bash --create-home klabautermann

WORKDIR /app

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY --chown=klabautermann:klabautermann src/ ./src/
COPY --chown=klabautermann:klabautermann scripts/ ./scripts/
COPY --chown=klabautermann:klabautermann config/ ./config/
COPY --chown=klabautermann:klabautermann main.py .

# Create data directories
RUN mkdir -p /app/data /app/logs && \
    chown -R klabautermann:klabautermann /app/data /app/logs

# Switch to non-root user
USER klabautermann

# Default command - run CLI
ENTRYPOINT ["python", "main.py"]

# ===========================================================================
# Development Stage
# ===========================================================================
FROM base AS development

# Development has root for debugging convenience
WORKDIR /app

# Install dependencies including dev tools
COPY requirements.txt requirements-dev.txt* ./
RUN pip install --no-cache-dir -r requirements.txt && \
    if [ -f requirements-dev.txt ]; then pip install --no-cache-dir -r requirements-dev.txt; fi

# Source will be mounted as volume in development
ENTRYPOINT ["python", "main.py"]
