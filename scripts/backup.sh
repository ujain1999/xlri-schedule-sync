#!/usr/bin/env bash
# Daily Postgres backup. Intended to run from cron on the server, inside the copy
# quick-deploy syncs to ~/.qd/apps/<name>/src:
#   0 3 * * * ~/.qd/apps/<name>/src/scripts/backup.sh >> ~/.qd/apps/<name>/src/backups/backup.log 2>&1
set -euo pipefail
cd "$(dirname "$0")/.."

set -a
source .env
set +a

# qd runs the stack as compose project "qd-<name>", where <name> is the directory
# above src/. Override with COMPOSE_PROJECT if running from somewhere else.
PROJECT="${COMPOSE_PROJECT:-qd-$(basename "$(dirname "$PWD")")}"

BACKUP_DIR="backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
mkdir -p "$BACKUP_DIR"

docker compose -p "$PROJECT" exec -T db pg_dump -U "${POSTGRES_USER}" -Fc "${POSTGRES_DB}" > "$BACKUP_DIR/db_${TIMESTAMP}.dump"

# Keep 14 days of local backups.
find "$BACKUP_DIR" -name 'db_*.dump' -mtime +14 -delete

echo "Backup written to $BACKUP_DIR/db_${TIMESTAMP}.dump"
echo "Remember: ENCRYPTION_KEY must be backed up SEPARATELY from this file -- see SECURITY.md."
