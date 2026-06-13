#!/bin/bash
# AquaVir-KB automated database backup
# Run via cron: 0 3 * * * /opt/deploy/backup.sh >> /var/log/aquavir_backup.log 2>&1

set -euo pipefail

BACKUP_DIR="/opt/backups/aquavir"
RETENTION_DAYS=30
COMPOSE_DIR="/opt/deploy"
TIMESTAMP=$(date +%Y%m%d_%H%M)
BACKUP_FILE="$BACKUP_DIR/aquavir_$TIMESTAMP.dump"

mkdir -p "$BACKUP_DIR"

# Dump PostgreSQL in custom format (compressible, restorable)
docker compose -f "$COMPOSE_DIR/docker-compose.yml" exec -T db \
    pg_dump -U aquavir -Fc aquavir_kb > "$BACKUP_FILE"

# Verify dump is non-empty
if [ ! -s "$BACKUP_FILE" ]; then
    echo "[ERROR] Backup file is empty: $BACKUP_FILE"
    exit 1
fi

echo "[OK] Backup created: $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"

# Clean up old backups
DELETED=$(find "$BACKUP_DIR" -name "aquavir_*.dump" -mtime +$RETENTION_DAYS -delete -print | wc -l)
echo "[ OK ] Cleaned $DELETED old backups (older than $RETENTION_DAYS days)"

# Keep only the 3 most recent backups regardless of age, as safety
ls -t "$BACKUP_DIR"/aquavir_*.dump 2>/dev/null | tail -n +4 | xargs rm -f 2>/dev/null || true

echo "[ OK ] Backup rotation complete. Remaining: $(ls "$BACKUP_DIR"/aquavir_*.dump 2>/dev/null | wc -l) files"
