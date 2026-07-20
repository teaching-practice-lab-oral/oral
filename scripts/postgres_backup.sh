#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

BACKUP_DIR="${BACKUP_DIR:-/backups}"
BACKUP_RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-7}"
BACKUP_TIME="${BACKUP_TIME:-03:00}"

PGHOST="${PGHOST:-db}"
PGPORT="${PGPORT:-5432}"
PGUSER="${PGUSER:-${POSTGRES_USER:-meet}}"
PGDATABASE="${PGDATABASE:-${POSTGRES_DB:-meetdb}}"
export PGHOST PGPORT PGUSER PGDATABASE
export PGPASSWORD="${PGPASSWORD:-${POSTGRES_PASSWORD:-}}"

log() {
  printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %Z')" "$*"
}

wait_for_postgres() {
  until pg_isready -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d "$PGDATABASE" >/dev/null 2>&1; do
    log "Waiting for PostgreSQL at ${PGHOST}:${PGPORT}/${PGDATABASE}..."
    sleep 5
  done
}

cleanup_old_backups() {
  find "$BACKUP_DIR" -type f -name "${PGDATABASE}_*.dump" -mtime +"$BACKUP_RETENTION_DAYS" -print -delete
  find "$BACKUP_DIR" -type f -name "${PGDATABASE}_*.dump.tmp" -mtime +1 -print -delete
}

run_backup() {
  local timestamp target tmp_target

  timestamp="$(date '+%Y%m%d_%H%M%S')"
  target="${BACKUP_DIR}/${PGDATABASE}_${timestamp}.dump"
  tmp_target="${target}.tmp"

  log "Starting PostgreSQL backup to ${target}"
  pg_dump --format=custom --no-owner --no-acl --file="$tmp_target" "$PGDATABASE"
  mv "$tmp_target" "$target"
  log "Backup completed: ${target}"

  cleanup_old_backups
}

seconds_until_next_backup() {
  local now target today

  now="$(date +%s)"
  today="$(date +%F)"
  target="$(date -d "${today} ${BACKUP_TIME}" +%s)"

  if [ "$now" -ge "$target" ]; then
    target="$(date -d "tomorrow ${BACKUP_TIME}" +%s)"
  fi

  printf '%s\n' "$((target - now))"
}

main() {
  mkdir -p "$BACKUP_DIR"
  cleanup_old_backups

  log "PostgreSQL backup scheduler started; time=${BACKUP_TIME}, retention=${BACKUP_RETENTION_DAYS} days, dir=${BACKUP_DIR}"

  while true; do
    local sleep_seconds

    sleep_seconds="$(seconds_until_next_backup)"
    log "Next backup in ${sleep_seconds} seconds"
    sleep "$sleep_seconds"

    wait_for_postgres
    run_backup
  done
}

main "$@"
