#!/usr/bin/env bash
# ============================================================================
# backup.sh — Nexus Agent Database Backup
# ============================================================================
# Creates a timestamped pg_dump of the nexus database (includes pgvector
# columns, checkpoint tables, Store tables).
#
# Usage:
#   ./scripts/backup.sh                          # dump to local ./backups/
#   AWS_S3_BUCKET=my-bucket ./scripts/backup.sh   # dump + upload to S3
#
# Environment:
#   DATABASE_URL    PostgreSQL connection string (required)
#                   e.g. postgresql://nexus:pass@localhost:5433/nexus
#   BACKUP_DIR      Local backup directory (default: ./backups)
#   AWS_S3_BUCKET   S3 bucket name for offsite backup (optional)
#   AWS_PROFILE     AWS CLI profile (optional, default: default)
#
# RPO: 1 hour (run via cron every hour)
# RTO: ~30 min for a 10 GB database (pg_restore)
# ============================================================================

set -euo pipefail

# ---- Config ---------------------------------------------------------------
BACKUP_DIR="${BACKUP_DIR:-./backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/nexus_${TIMESTAMP}.dump"
LATEST_LINK="${BACKUP_DIR}/nexus_latest.dump"

mkdir -p "${BACKUP_DIR}"

# ---- Validate ------------------------------------------------------------
if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL is not set."
    echo "Usage: DATABASE_URL=postgresql://user:pass@host:port/dbname ./scripts/backup.sh"
    exit 1
fi

# Parse DATABASE_URL into pg_dump arguments
# Supports: postgresql://user:pass@host:port/dbname
PG_HOST=$(echo "${DATABASE_URL}" | sed -n 's|.*://[^:]*:[^@]*@\([^:]*\).*|\1|p')
PG_PORT=$(echo "${DATABASE_URL}" | sed -n 's|.*://[^:]*:[^@]*@[^:]*:\([^/]*\).*|\1|p')
PG_USER=$(echo "${DATABASE_URL}" | sed -n 's|.*://\([^:]*\):.*|\1|p')
PG_PASS=$(echo "${DATABASE_URL}" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p')
PG_DB=$(echo "${DATABASE_URL}" | sed -n 's|.*/\([^?]*\)|\1|p')

if [ -z "${PG_HOST}" ] || [ -z "${PG_DB}" ]; then
    echo "ERROR: Could not parse DATABASE_URL. Expected format: postgresql://user:pass@host:port/dbname"
    exit 1
fi

export PGPASSWORD="${PG_PASS}"

# ---- Backup --------------------------------------------------------------
echo "=== Starting backup: ${BACKUP_FILE} ==="
echo "  Host: ${PG_HOST}:${PG_PORT:-5432}"
echo "  Database: ${PG_DB}"
echo "  User: ${PG_USER}"

pg_dump \
    -h "${PG_HOST}" \
    -p "${PG_PORT:-5432}" \
    -U "${PG_USER}" \
    -d "${PG_DB}" \
    -F c \
    -v \
    -f "${BACKUP_FILE}"

echo "=== Backup complete: $(du -h "${BACKUP_FILE}" | cut -f1) ==="

# Update latest symlink
ln -sf "${BACKUP_FILE}" "${LATEST_LINK}"

# ---- S3 upload -----------------------------------------------------------
if [ -n "${AWS_S3_BUCKET:-}" ]; then
    echo "=== Uploading to S3: s3://${AWS_S3_BUCKET}/nexus/ ==="
    aws s3 cp "${BACKUP_FILE}" "s3://${AWS_S3_BUCKET}/nexus/backup_${TIMESTAMP}.dump" \
        --profile "${AWS_PROFILE:-default}"
    aws s3 cp "${BACKUP_FILE}" "s3://${AWS_S3_BUCKET}/nexus/latest.dump" \
        --profile "${AWS_PROFILE:-default}"
    echo "=== S3 upload complete ==="
fi

# ---- Retention: keep last 30 daily backups --------------------------------
find "${BACKUP_DIR}" -name "nexus_*.dump" -mtime +30 -delete

echo "=== Done ==="
