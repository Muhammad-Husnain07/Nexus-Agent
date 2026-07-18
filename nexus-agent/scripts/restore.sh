#!/usr/bin/env bash
# ============================================================================
# restore.sh — Nexus Agent Database Restore
# ============================================================================
# Restores a nexus database from a pg_dump custom-format archive.
#
# Usage:
#   ./scripts/restore.sh /path/to/nexus_20260717_120000.dump
#
# Environment:
#   DATABASE_URL    PostgreSQL connection string for the TARGET database
#                   e.g. postgresql://nexus:pass@localhost:5433/nexus
#
# WARNING: This will DROP and recreate the target database!
#          Use --confirm flag to acknowledge.
# ============================================================================

set -euo pipefail

# ---- Config ---------------------------------------------------------------
RESTORE_FILE="${1:-}"

# ---- Validate ------------------------------------------------------------
if [ -z "${RESTORE_FILE}" ]; then
    echo "ERROR: No backup file specified."
    echo "Usage: $0 /path/to/nexus_20260717_120000.dump"
    echo ""
    echo "Available backups:"
    ls -lh ./backups/nexus_*.dump 2>/dev/null || echo "  (no local backups found)"
    exit 1
fi

if [ ! -f "${RESTORE_FILE}" ]; then
    echo "ERROR: Backup file not found: ${RESTORE_FILE}"
    exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
    echo "ERROR: DATABASE_URL is not set."
    echo "Usage: DATABASE_URL=postgresql://user:pass@host:port/dbname $0 <backup-file>"
    exit 1
fi

if [ "${2:-}" != "--confirm" ]; then
    echo ""
    echo "WARNING: This will DROP and recreate the database!"
    echo "  Backup: ${RESTORE_FILE}"
    echo "  Target: ${DATABASE_URL}"
    echo ""
    echo "To proceed, run: $0 ${RESTORE_FILE} --confirm"
    exit 1
fi

# Parse DATABASE_URL
PG_HOST=$(echo "${DATABASE_URL}" | sed -n 's|.*://[^:]*:[^@]*@\([^:]*\).*|\1|p')
PG_PORT=$(echo "${DATABASE_URL}" | sed -n 's|.*://[^:]*:[^@]*@[^:]*:\([^/]*\).*|\1|p')
PG_USER=$(echo "${DATABASE_URL}" | sed -n 's|.*://\([^:]*\):.*|\1|p')
PG_PASS=$(echo "${DATABASE_URL}" | sed -n 's|.*://[^:]*:\([^@]*\)@.*|\1|p')
PG_DB=$(echo "${DATABASE_URL}" | sed -n 's|.*/\([^?]*\)|\1|p')

export PGPASSWORD="${PG_PASS}"

# ---- Disconnect all sessions and drop/recreate DB -------------------------
echo "=== Dropping target database: ${PG_DB} ==="
psql -h "${PG_HOST}" -p "${PG_PORT:-5432}" -U "${PG_USER}" -d postgres <<SQL
SELECT pg_terminate_backend(pg_stat_activity.pid)
FROM pg_stat_activity
WHERE pg_stat_activity.datname = '${PG_DB}'
  AND pid <> pg_backend_pid();
DROP DATABASE IF EXISTS "${PG_DB}";
CREATE DATABASE "${PG_DB}";
SQL

echo "=== Enabling extensions ==="
psql -h "${PG_HOST}" -p "${PG_PORT:-5432}" -U "${PG_USER}" -d "${PG_DB}" <<SQL
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
SQL

# ---- Restore --------------------------------------------------------------
echo "=== Restoring from: ${RESTORE_FILE} ==="
pg_restore \
    -h "${PG_HOST}" \
    -p "${PG_PORT:-5432}" \
    -U "${PG_USER}" \
    -d "${PG_DB}" \
    -F c \
    --clean \
    --if-exists \
    -v \
    "${RESTORE_FILE}"

echo "=== Restore complete ==="

# ---- Verify ---------------------------------------------------------------
echo "=== Verifying restore ==="
psql -h "${PG_HOST}" -p "${PG_PORT:-5432}" -U "${PG_USER}" -d "${PG_DB}" \
    -c "SELECT count(*) AS tables FROM information_schema.tables WHERE table_schema = 'public';"
psql -h "${PG_HOST}" -p "${PG_PORT:-5432}" -U "${PG_USER}" -d "${PG_DB}" \
    -c "SELECT extension_name, extension_version FROM pg_extension ORDER BY extension_name;"

echo "=== Done ==="
