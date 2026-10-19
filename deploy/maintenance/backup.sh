#!/bin/bash
# Daily WAL-safe database backup (compressed, retains 7 days)
set -e
DB=/opt/aquavir-kb/deploy/data/crustacean_virus_core.db
BACKUP_DIR=/opt/aquavir-kb/deploy/data/backups
RETENTION=7
mkdir -p "$BACKUP_DIR" /var/log/aquavir
STAMP=$(date +%Y%m%d_%H%M%S)
OUT="$BACKUP_DIR/crustacean_virus_core_$STAMP.db"
sqlite3 "$DB" ".backup '$OUT'"
gzip -f "$OUT"
echo "$(date +%F_%T) backup -> $OUT.gz" >> /var/log/aquavir/backup.log
find "$BACKUP_DIR" -name '*.db.gz' -mtime +"$RETENTION" -delete
