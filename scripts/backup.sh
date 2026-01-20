#!/bin/bash
# Klabautermann Neo4j Backup Script
#
# Creates a timestamped backup of the Neo4j database.
# Backups are stored in ./backups/ directory.
#
# Usage:
#   ./scripts/backup.sh                    # Default backup
#   ./scripts/backup.sh my-backup-name     # Named backup
#
# Requirements:
#   - Docker and docker-compose installed
#   - Neo4j container running
#   - ./backups directory exists (created automatically)

set -euo pipefail

# Configuration
CONTAINER_NAME="${NEO4J_CONTAINER:-klabautermann-neo4j}"
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="${1:-backup}_${TIMESTAMP}"

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

# Create backup directory if it doesn't exist
mkdir -p "${BACKUP_DIR}"

# Check if container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    log_error "Neo4j container '${CONTAINER_NAME}' is not running!"
    echo "Start it with: docker-compose up -d neo4j"
    exit 1
fi

log_info "Starting backup: ${BACKUP_NAME}"
log_info "Backup directory: ${BACKUP_DIR}"

# Stop write operations (consistency)
log_info "Preparing for backup..."

# Create backup using neo4j-admin dump
log_info "Creating database dump..."
docker exec "${CONTAINER_NAME}" neo4j-admin database dump neo4j \
    --to-path=/backups 2>/dev/null || {
    # Fallback: copy data directory directly
    log_warn "neo4j-admin dump failed, using file copy method..."
    docker exec "${CONTAINER_NAME}" tar -czf /backups/${BACKUP_NAME}.tar.gz /data
}

# Move backup to timestamped file
if [ -f "${BACKUP_DIR}/neo4j.dump" ]; then
    mv "${BACKUP_DIR}/neo4j.dump" "${BACKUP_DIR}/${BACKUP_NAME}.dump"
    BACKUP_FILE="${BACKUP_DIR}/${BACKUP_NAME}.dump"
elif [ -f "${BACKUP_DIR}/${BACKUP_NAME}.tar.gz" ]; then
    # File was created with tar method inside container
    docker cp "${CONTAINER_NAME}:/backups/${BACKUP_NAME}.tar.gz" "${BACKUP_DIR}/"
    BACKUP_FILE="${BACKUP_DIR}/${BACKUP_NAME}.tar.gz"
else
    log_error "Backup file not found!"
    exit 1
fi

# Calculate backup size
BACKUP_SIZE=$(du -h "${BACKUP_FILE}" | cut -f1)

log_info "Backup complete!"
log_info "  File: ${BACKUP_FILE}"
log_info "  Size: ${BACKUP_SIZE}"

# Clean up old backups (keep last 7)
BACKUP_COUNT=$(ls -1 "${BACKUP_DIR}"/*.dump "${BACKUP_DIR}"/*.tar.gz 2>/dev/null | wc -l)
if [ "${BACKUP_COUNT}" -gt 7 ]; then
    log_info "Cleaning up old backups (keeping last 7)..."
    ls -1t "${BACKUP_DIR}"/*.dump "${BACKUP_DIR}"/*.tar.gz 2>/dev/null | tail -n +8 | xargs rm -f
fi

echo ""
log_info "To restore this backup, run:"
echo "  ./scripts/restore.sh ${BACKUP_FILE}"
