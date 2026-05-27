#!/bin/bash
# Nightly backup of authored schemas in the matrikkel database.
#
# Dumps `ops`, `changeset`, and `stiflyt` schemas (the irreplaceable data —
# everything else can be re-imported from Kartverket/turrutebasen) in
# pg_dump custom format, then rotates files older than $KEEP_DAYS days.
#
# Restore example:
#   pg_restore -d matrikkel --clean --if-exists matrikkel-ops-20260526.dump

set -euo pipefail

DB_NAME="${DB_NAME:-matrikkel}"
SCHEMAS=("${OP_SCHEMA:-ops}" "changeset" "stiflyt")
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups/stiflyt}"
KEEP_DAYS="${KEEP_DAYS:-30}"

mkdir -p "$BACKUP_DIR"

timestamp=$(date +%Y%m%d-%H%M%S)
outfile="$BACKUP_DIR/matrikkel-ops-${timestamp}.dump"
logfile="$BACKUP_DIR/backup.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$logfile"
}

schema_args=()
for s in "${SCHEMAS[@]}"; do
    schema_args+=(-n "$s")
done

log "Starting pg_dump of $DB_NAME schemas: ${SCHEMAS[*]}"

if ! pg_dump -d "$DB_NAME" "${schema_args[@]}" -Fc -f "$outfile" 2>>"$logfile"; then
    log "ERROR: pg_dump failed; removing partial file"
    rm -f "$outfile"
    exit 1
fi

# Verify the archive is readable (catches truncation / corruption early).
if ! pg_restore -l "$outfile" >/dev/null 2>>"$logfile"; then
    log "ERROR: pg_restore -l rejected $outfile; removing"
    rm -f "$outfile"
    exit 1
fi

size=$(du -h "$outfile" | cut -f1)
log "Wrote $outfile ($size)"

# Rotation: delete dumps older than KEEP_DAYS.
deleted=$(find "$BACKUP_DIR" -maxdepth 1 -name 'matrikkel-ops-*.dump' -mtime "+$KEEP_DAYS" -print -delete | wc -l)
if [ "$deleted" -gt 0 ]; then
    log "Rotated out $deleted dump(s) older than ${KEEP_DAYS}d"
fi

log "Done."
