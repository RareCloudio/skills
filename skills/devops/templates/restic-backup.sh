#!/usr/bin/env bash
# restic-backup: dump the app's database to a local file, then back up that dump and the app's
# files to a restic repository, apply the retention policy and check the repository.
#
# Install as /usr/local/sbin/restic-backup (root:root, mode 0755). It holds no placeholders: it
# is configured by environment variables, normally from the EnvironmentFile of
# restic-backup.service (see restic-backup.env.example). To run it by hand with the same settings:
#   sudo bash -c 'set -a; . /etc/restic-backup/shop.env; set +a; /usr/local/sbin/restic-backup'
#
# Required:
#   RESTIC_REPOSITORY      the repository, e.g. s3:https://s3.example.com/shop-backups/web-01
#   RESTIC_PASSWORD_FILE   file holding the repository password (keep a copy off the server)
#   BACKUP_TAG             tag for this app's snapshots; retention only touches this tag
#   DUMP_DIR               local folder for the database dump; it is backed up with the files
#   DB_KIND                postgres, mysql (MySQL or MariaDB), sqlite or none
# Optional:
#   BACKUP_PATHS           space-separated files and folders to back up besides the dump
#   DB_NAME                the database to dump (postgres, mysql)
#   DB_CONTAINER           container name when the database runs in Docker; dumps via docker exec
#   DB_USER                the database user to dump as inside that container (postgres): the
#                          POSTGRES_USER the container was created with, which the official
#                          image makes the only role, so there is no "postgres" role to fall back on
#   SQLITE_PATH            the SQLite database file, as seen from the host (sqlite)
#   KEEP_DAILY KEEP_WEEKLY KEEP_MONTHLY   retention, default 7, 4 and 6
#   CHECK_READ_DATA_SUBSET also read back this share of the stored data each run, e.g. 5%
#   HEALTHCHECK_URL        fetched after a fully successful run, so a run that failed or never
#                          started shows up as a missed check-in in your monitoring
#
# Exit status is 0 only when the dump, the backup, the retention and the check all worked, so a
# failure marks the systemd unit as failed.

set -Eeuo pipefail
umask 077

log() { printf '%s\n' "$*" >&2; }
die() { log "error: $*"; exit 1; }
trap 'log "error: the command on line $LINENO failed"' ERR

: "${RESTIC_REPOSITORY:?set RESTIC_REPOSITORY}"
: "${RESTIC_PASSWORD_FILE:?set RESTIC_PASSWORD_FILE}"
: "${BACKUP_TAG:?set BACKUP_TAG}"
: "${DUMP_DIR:?set DUMP_DIR}"
: "${DB_KIND:?set DB_KIND to postgres, mysql, sqlite or none}"
export RESTIC_REPOSITORY RESTIC_PASSWORD_FILE

[ -r "$RESTIC_PASSWORD_FILE" ] || die "cannot read $RESTIC_PASSWORD_FILE"
command -v restic >/dev/null || die "restic is not installed"
mkdir -p "$DUMP_DIR"

# Paths with spaces are not supported in BACKUP_PATHS.
read -r -a extra_paths <<<"${BACKUP_PATHS:-}"
for p in "${extra_paths[@]}"; do
  [ -e "$p" ] || die "backup path $p does not exist"
done

# Fail early, before a long dump, when the repository cannot be opened.
restic cat config >/dev/null ||
  die "cannot open the repository: not initialised (run 'restic init' once), wrong password," \
    "or unreachable"

# Run a command inside the database container. No -t, because a TTY corrupts binary output, and
# no -i, which would swallow the stdin of whatever runs this script.
in_db() {
  docker exec "$DB_CONTAINER" "$@"
}

dump_postgres() {
  local out=$1
  : "${DB_NAME:?set DB_NAME}"
  # Custom format (-Fc) so pg_restore can restore one table or run in parallel. -Z 0 leaves it
  # uncompressed: restic compresses it, and finds the unchanged parts of yesterday's dump.
  if [ -n "${DB_CONTAINER:-}" ]; then
    : "${DB_USER:?set DB_USER to the POSTGRES_USER of the database container}"
    in_db pg_dump -U "$DB_USER" -Fc -Z 0 -d "$DB_NAME" >"$out"
  else
    # A Postgres installed from the distribution: its superuser logs in over the local socket as
    # the system account of the same name, so no password and no DB_USER are needed.
    runuser -u postgres -- pg_dump -Fc -Z 0 -d "$DB_NAME" >"$out"
  fi
  [ "$(head -c 5 "$out")" = "PGDMP" ] || die "the Postgres dump has no archive header"
}

dump_mysql() {
  local out=$1
  : "${DB_NAME:?set DB_NAME}"
  # --single-transaction gives a consistent copy of InnoDB tables without locking them.
  if [ -n "${DB_CONTAINER:-}" ]; then
    # The root password is read from the container's own environment and handed over in
    # MYSQL_PWD, not as -p: a process's arguments are visible to every user of the host in ps,
    # its environment only to root and that user. It never appears in this script or its
    # environment file either.
    # shellcheck disable=SC2016
    in_db sh -c 'export MYSQL_PWD="${MARIADB_ROOT_PASSWORD:-${MYSQL_ROOT_PASSWORD:-}}"
      exec "$(command -v mariadb-dump || command -v mysqldump)" -uroot --single-transaction \
      --routines --triggers --no-tablespaces "$1"' sh "$DB_NAME" >"$out"
  else
    # On Debian and Ubuntu, root logs in over the local socket without a password.
    "$(command -v mariadb-dump || command -v mysqldump)" --single-transaction \
      --routines --triggers --no-tablespaces "$DB_NAME" >"$out"
  fi
  tail -n 1 "$out" | grep -q '^-- Dump completed' || die "the MySQL dump did not complete"
}

dump_sqlite() {
  local out=$1
  : "${SQLITE_PATH:?set SQLITE_PATH}"
  # .backup uses SQLite's online backup API: a consistent copy even while the app writes, and
  # one that includes what still sits in the -wal file. A plain cp does not. It runs on the
  # host, so for an app in a container point SQLITE_PATH at the file on its bind mount or volume.
  sqlite3 "$SQLITE_PATH" ".backup '$out'"
  [ "$(sqlite3 "$out" 'PRAGMA integrity_check')" = "ok" ] || die "the SQLite copy is damaged"
}

case "$DB_KIND" in
  postgres) dump_file="$DUMP_DIR/$BACKUP_TAG.pgdump" ;;
  mysql) dump_file="$DUMP_DIR/$BACKUP_TAG.sql" ;;
  sqlite) dump_file="$DUMP_DIR/$BACKUP_TAG.sqlite3" ;;
  none) dump_file="" ;;
  *) die "unknown DB_KIND '$DB_KIND'" ;;
esac

if [ -n "$dump_file" ]; then
  # Write to a temporary name and rename only after the checks pass, so a failed dump never
  # replaces the last good one.
  tmp="$dump_file.partial"
  rm -f "$tmp"
  log "dumping the $DB_KIND database"
  "dump_$DB_KIND" "$tmp"
  mv -f "$tmp" "$dump_file"
fi

status=0
log "backing up to $RESTIC_REPOSITORY"
restic backup --tag "$BACKUP_TAG" "$DUMP_DIR" "${extra_paths[@]}" || status=$?
case "$status" in
  0) ;;
  3) log "warning: some files could not be read; the snapshot was saved without them" ;;
  *) die "restic backup failed with status $status" ;;
esac

log "applying retention"
restic forget --tag "$BACKUP_TAG" --group-by host,tags \
  --keep-daily "${KEEP_DAILY:-7}" --keep-weekly "${KEEP_WEEKLY:-4}" \
  --keep-monthly "${KEEP_MONTHLY:-6}" --prune

log "checking the repository"
if [ -n "${CHECK_READ_DATA_SUBSET:-}" ]; then
  restic check --read-data-subset="$CHECK_READ_DATA_SUBSET"
else
  restic check
fi

[ "$status" -eq 0 ] || exit "$status"

if [ -n "${HEALTHCHECK_URL:-}" ]; then
  curl -fsS -m 10 --retry 3 -o /dev/null "$HEALTHCHECK_URL" ||
    log "warning: the health check ping failed"
fi
log "backup finished"
