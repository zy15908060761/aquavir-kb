#!/bin/bash
# Rebuild the BLAST databases when the database has changed since the last build.
# Cheap when nothing changed: compares mtimes, exits immediately.
# Runs from cron; see /var/log/aquavir/blast_rebuild.log for its history.
set -e
DB=/opt/aquavir-kb/deploy/data/crustacean_virus_core.db
VERSION_FILE=/opt/aquavir-kb/deploy/data/blastdb/VERSION
LOCK=/tmp/aquavir_rebuild_blast.lock
LOG=/var/log/aquavir/blast_rebuild.log

mkdir -p /var/log/aquavir

# Only one rebuild at a time.
exec 9>"$LOCK"
flock -n 9 || exit 0

# The index already newer than the database -> nothing to do.
if [ -f "$VERSION_FILE" ] && [ "$VERSION_FILE" -nt "$DB" ]; then
    exit 0
fi

echo "$(date +%F_%T) database is newer than the BLAST index, rebuilding" >> "$LOG"
if python3 /opt/aquavir-kb/rebuild_blast.py >> "$LOG" 2>&1; then
    echo "$(date +%F_%T) rebuild OK: $(cat "$VERSION_FILE")" >> "$LOG"
else
    echo "$(date +%F_%T) rebuild FAILED (details above)" >> "$LOG"
    exit 1
fi
