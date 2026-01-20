#!/bin/bash
# Klabautermann Neo4j Restore Script
#
# Restores a Neo4j database from a backup file.
# WARNING: This will overwrite the current database!
#
# Usage:
#   ./scripts/restore.sh ./backups/backup_20240101_120000.dump
#   ./scripts/restore.sh ./backups/backup_20240101_120000.tar.gz
#
# Requirements:
#   - Docker and docker-compose installed
#   - Backup file exists

set -euo pipefail

# Configuration
CONTAINER_NAME="${NEO4J_CONTAINER:-klabautermann-neo4j}"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check arguments
if [ $# -lt 1 ]; then
    log_error "Usage: $0 <backup_file>"
    echo ""
    echo "Available backups:"
    ls -lh ./backups/*.dump ./backups/*.tar.gz 2>/dev/null || echo "  No backups found"
    exit 1
fi

BACKUP_FILE="$1"

# Verify backup file exists
if [ ! -f "${BACKUP_FILE}" ]; then
    log_error "Backup file not found: ${BACKUP_FILE}"
    exit 1
fi

log_warn "This will OVERWRITE the current Neo4j database!"
echo ""
echo "Backup file: ${BACKUP_FILE}"
echo "Backup size: $(du -h "${BACKUP_FILE}" | cut -f1)"
echo ""
read -p "Are you sure you want to continue? (yes/no): " confirm

if [ "${confirm}" != "yes" ]; then
    log_info "Restore cancelled."
    exit 0
fi

log_info "Starting restore process..."

# Stop the Neo4j container
log_info "Stopping Neo4j container..."
docker-compose -f "${COMPOSE_FILE}" stop neo4j || docker stop "${CONTAINER_NAME}"

# Determine backup type and restore
if [[ "${BACKUP_FILE}" == *.dump ]]; then
    # neo4j-admin dump format
    log_info "Restoring from dump file..."

    # Copy backup to container
    docker cp "${BACKUP_FILE}" "${CONTAINER_NAME}:/backups/restore.dump"

    # Restore using neo4j-admin
    docker-compose -f "${COMPOSE_FILE}" run --rm neo4j \
        neo4j-admin database load --from-path=/backups neo4j --overwrite-destination

elif [[ "${BACKUP_FILE}" == *.tar.gz ]]; then
    # Tar archive format
    log_info "Restoring from tar archive..."

    # Get volume name
    DATA_VOLUME=$(docker volume ls --format '{{.Name}}' | grep -E 'neo4j.*data' | head -1)

    if [ -z "${DATA_VOLUME}" ]; then
        log_error "Could not find Neo4j data volume!"
        exit 1
    fi

    # Extract to a temp location and copy to volume
    TEMP_DIR=$(mktemp -d)
    tar -xzf "${BACKUP_FILE}" -C "${TEMP_DIR}"

    # Copy data to volume using a temporary container
    docker run --rm \
        -v "${DATA_VOLUME}:/data" \
        -v "${TEMP_DIR}:/backup:ro" \
        alpine sh -c "rm -rf /data/* && cp -r /backup/data/* /data/"

    rm -rf "${TEMP_DIR}"
else
    log_error "Unknown backup format: ${BACKUP_FILE}"
    log_error "Expected .dump or .tar.gz"
    exit 1
fi

# Start Neo4j container
log_info "Starting Neo4j container..."
docker-compose -f "${COMPOSE_FILE}" start neo4j || docker start "${CONTAINER_NAME}"

# Wait for Neo4j to be ready
log_info "Waiting for Neo4j to be ready..."
for i in {1..30}; do
    if docker exec "${CONTAINER_NAME}" wget -q --spider http://localhost:7474 2>/dev/null; then
        break
    fi
    echo -n "."
    sleep 2
done
echo ""

# Verify restore
if docker exec "${CONTAINER_NAME}" wget -q --spider http://localhost:7474 2>/dev/null; then
    log_info "Neo4j is ready!"

    # Count nodes to verify data
    NODE_COUNT=$(docker exec "${CONTAINER_NAME}" cypher-shell -u neo4j -p "${NEO4J_PASSWORD:-klabautermann}" \
        "MATCH (n) RETURN count(n) as count" 2>/dev/null | tail -1 || echo "unknown")

    log_info "Restore complete!"
    log_info "  Node count: ${NODE_COUNT}"
else
    log_error "Neo4j did not start properly after restore!"
    log_error "Check logs: docker-compose logs neo4j"
    exit 1
fi
