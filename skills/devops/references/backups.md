# Backups you can restore from

Read this when you set up backups for an app on a server, check whether existing backups would
actually save the person, or are about to make a risky change. It covers what to back up,
consistent database dumps, restic to S3-compatible object storage, scheduling with systemd, the
restore test, and how to say how far a backup is verified. Running the database itself (access,
memory, migrations, upgrades) is in [databases.md](databases.md).

## Decide what has to be backed up

Ask: if this server disappeared now, what would be needed to have the app back, and what could
not be recreated from somewhere else? Usually:

- **The database,** as a dump (below), never as a copy of its data folder while it runs.
- **Files the app or its users wrote:** uploads, generated documents, a SQLite file, anything in
  a Docker volume that is not a cache.
- **What it takes to rebuild:** the app's environment file and secrets, the reverse proxy
  config, systemd units, the Compose file and crontab if they are not in git. Without the
  secrets, a restored database may be unreadable to the app (encrypted columns, signed sessions).

Usually not: code that is in git, images that a Dockerfile rebuilds, OS packages, caches,
`node_modules`, certificates that renew on their own. One exception: an image that lives only in
a registry the person does not control is worth a `docker save` or a rebuild path. Write the
final list in the hand-over, so the next person knows what is and is not covered.

## Keep a copy away from the server

A copy on the same server is not a backup. A failed disk, a deleted server, an intruder with
root, a wrong `rm -rf` or a closed provider account takes the copy along with the original.

A provider snapshot is half of one. It is quick to take and quick to roll back, which makes it
the right tool before a risky change. But it lives with the same provider and account, often
on the same storage system, is often deleted together with the server, and restores the whole
disk rather than the one table someone dropped yesterday. It is also only crash-consistent: the
database comes back as after a power cut, which Postgres and InnoDB recover from, but a dump is
what you can trust.

The baseline: a nightly dump plus the files, encrypted, in object storage at a different
provider or at least a different account, with retention, and one restore that was tested.

An intruder with root on the server also has the storage key. If that key can delete, the
backups can go with the server. Where the storage supports it, versioning or object lock with
a retention period limits that damage; this file does not cover setting it up (not verified
here), so raise it with the person when the data matters that much.

## Dump the database so the copy is consistent

**Postgres.** `pg_dump` takes a consistent snapshot without stopping the app.

```
runuser -u postgres -- pg_dump -Fc -Z 0 -d app > /var/backups/app/app.pgdump
pg_restore --list /var/backups/app/app.pgdump > /dev/null && echo readable
```

- `-Fc` (custom format) is read by `pg_restore`, which can restore one table (`-t users`) or run
  in parallel (`-j 4`, from a file, not from stdin). Plain SQL (`-Fp`) is readable and loads
  with `psql`, but all or nothing. `-Fd` (a directory) can also dump in parallel.
- `-Z 0` leaves the dump uncompressed for restic, which compresses it and stores only the parts
  that changed since yesterday. A compressed dump changes everywhere when a few rows change. In
  a test with a few hundred new rows, the uncompressed dump added about half as much to the
  repository as the compressed one.
- Roles and their passwords are not in `pg_dump`. Take them with
  `pg_dumpall --roles-only > roles.sql`; it holds password hashes, so treat it as a secret.
- A dump loads into the same major version or a newer one. Postgres 16's `pg_restore` refuses an
  18 dump with "unsupported version (1.16) in file header".

To restore, create an empty database and load the dump. `--no-owner` makes everything belong to
the user running the restore, which is what you want when the original roles do not exist:

```
runuser -u postgres -- createdb app_restore_test
runuser -u postgres -- pg_restore -d app_restore_test --no-owner --exit-on-error < app.pgdump
```

Without `--exit-on-error`, `pg_restore` carries on past errors, prints "errors ignored on
restore: N" at the end and exits with 1. Read that line; a restore with ignored errors is
incomplete.

**MySQL and MariaDB.** `--single-transaction` gives a consistent dump of InnoDB tables without
locking them (MyISAM tables get no such guarantee).

```
mariadb-dump --single-transaction --routines --triggers --no-tablespaces app > app.sql
tail -n 1 app.sql        # "-- Dump completed on ..." means it finished
mariadb app_restore_test < app.sql     # create the database first
```

The MariaDB 11 images ship `mariadb-dump` and `mariadb` only; `mysqldump` and `mysql` are not
there. A Debian 12 server still has both names. On MySQL 8.4, a user without the PROCESS
privilege gets "Access denied; you need (at least one of) the PROCESS privilege(s)" but the dump
still completes with status 0; `--no-tablespaces` removes the noise. A MariaDB 11.8 dump does
not load into MySQL 8.4 ("Unknown collation: 'utf8mb4_uca1400_ai_ci'"): moving between the two
is a migration, not a restore.

**SQLite.** Copying the file of a live database is not safe. In WAL mode the newest writes sit
in the `-wal` file: a plain `cp` of a database with 10,000 freshly written rows held 0 of them.
Use the online backup instead, which is consistent while the app writes:

```
sqlite3 /srv/app/data/app.db ".backup /var/backups/app/app.sqlite3"
sqlite3 /var/backups/app/app.sqlite3 "PRAGMA integrity_check"     # prints ok
```

`VACUUM INTO '/var/backups/app/app.sqlite3'` does the same and compacts the copy.

**A database in a container.** Run the dump inside it, as the user and database the container
was created with, and redirect on the host. Take both from the backup's environment file
(`DB_USER` and `DB_NAME`, set to the Compose file's `POSTGRES_USER` and `POSTGRES_DB`) rather
than writing `postgres`: when `POSTGRES_USER` names another user, the official image creates no
`postgres` role, and the dump fails with `role "postgres" does not exist`.
`docker exec shop-db-1 pg_dump -U "$DB_USER" -Fc -Z 0 -d "$DB_NAME" > shop.pgdump`, or with
Compose, as the folder's owner ([first-deploy.md](first-deploy.md)),
`sudo -u deploy docker compose --project-directory /srv/shop exec -T db pg_dump ...`. The backup
job runs as root and uses `docker exec`. Leave out `-t`, and pass `-T` to Compose, which
otherwise allocates a terminal when you run it from one: a terminal rewrites line endings, and
a dump taken with `docker exec -t` was unreadable to `pg_restore`.

## Send it off the server with restic

restic encrypts, deduplicates and compresses, and writes to S3-compatible storage, SFTP or a
local folder. Install it from the distribution (Debian 12 ships 0.14, Ubuntu 24.04 ships 0.16)
or as the release binary from the project's GitHub releases, checked against its published
checksums; the commands below work on both, but newer releases have better exit codes.

Ask the person for a bucket used only for backups and a key limited to that bucket. Then fill
[templates/restic-backup.env.example](../templates/restic-backup.env.example) into
`/etc/restic-backup/shop.env` (mode 0600; the values that join it to the Compose file are in
[first-deploy.md](first-deploy.md), step 8) and make the repository password:

```
install -d -m 0700 /etc/restic-backup
(umask 077 && openssl rand -base64 32 > /etc/restic-backup/shop.password)
set -a; . /etc/restic-backup/shop.env; set +a
restic init
```

The password is the encryption key. Without it nobody can read the backups, the person
included; restic says so when it creates the repository, and nobody can reset it. A copy kept
only on the server is lost with the server. Ask the person to store it in their password
manager and to tell you they have, before you call the backups done.

Useful commands, with the same environment loaded:

```
restic cat config > /dev/null        # can we open it? 10 = no repository, 12 = wrong password
restic backup --tag app /var/backups/app /srv/app/uploads /etc/app
restic snapshots
restic forget --tag app --group-by host,tags --keep-daily 7 --keep-weekly 4 --keep-monthly 6 \
  --prune --dry-run
restic check                         # structure; add --read-data-subset=5% to read data back
```

`forget` removes snapshot records and `--prune` deletes the data nobody needs any more; run it
with `--dry-run` first and read what it would remove. Those exit codes (10, 12) are from restic
0.18; older versions return 1 for both.

Borg is the established alternative, also deduplicating and encrypted (`borg create`,
`borg prune`, `borg compact`). Borg 1.x has no S3 backend: it needs SSH access to a machine or a
storage service that runs borg. Prefer it when that is what the person already has.

## Schedule it and know when it failed

The templates do this together: [templates/restic-backup.sh](../templates/restic-backup.sh)
dumps Postgres, MySQL/MariaDB or SQLite (on the host or in a container), checks the dump, backs
it up with the files, applies retention and checks the repository;
[templates/restic-backup.service](../templates/restic-backup.service) and
[templates/restic-backup.timer](../templates/restic-backup.timer) run it daily. Change the
environment file, not the script.

```
install -m 0755 restic-backup.sh /usr/local/sbin/restic-backup
cp restic-backup.service /etc/systemd/system/restic-backup-shop.service  # <APP> filled in
cp restic-backup.timer /etc/systemd/system/restic-backup-shop.timer
systemd-analyze verify /etc/systemd/system/restic-backup-shop.*
systemctl daemon-reload
systemctl start restic-backup-shop.service       # the first run by hand, watched
journalctl -u restic-backup-shop.service -n 50
systemctl enable --now restic-backup-shop.timer
systemctl list-timers restic-backup-shop.timer
```

A failed run leaves the unit `failed` (`systemctl is-failed restic-backup-shop.service`,
`systemctl --failed`), and the journal names the step. Nobody reads that on their own, so add
one way of being told: `HEALTHCHECK_URL` in the environment file, a check-in URL from an uptime
monitor that alerts when no check-in arrives in time, or `OnFailure=` on the service pointing
at a unit that sends a message. The check-in also catches the case that matters most: the timer
was disabled or the server was off, and nothing ran at all. Note that `list-timers` shows only
runs the timer started; a run you started by hand does not appear under LAST.

## Prove a restore works, as part of the setup

A backup nobody has restored is a hope. Do this once before you call it done, and agree with
the person how often to repeat it (monthly is a reasonable default), with the date written down.

1. One file, compared with the original:
   ```
   restic restore latest --tag app --target /tmp/restore-test --include /srv/app/uploads/<FILE>
   cmp /tmp/restore-test/srv/app/uploads/<FILE> /srv/app/uploads/<FILE> && echo same
   ```
2. The dump, loaded into a throwaway database and compared with the live one. On the same
   server, straight from the repository:
   ```
   runuser -u postgres -- createdb app_restore_test
   restic dump --tag app latest /var/backups/app/app.pgdump |
     runuser -u postgres -- pg_restore -d app_restore_test --no-owner --exit-on-error
   ```
   Compare row counts of the main tables, or a checksum on a table that has not changed since
   the dump: `SELECT count(*), md5(string_agg(t::text, ',' ORDER BY id)) FROM users t;` in both
   databases. Then `dropdb app_restore_test` and remove `/tmp/restore-test`. Elsewhere, a
   throwaway container of the same or a newer major version does the job; wait for it with
   `pg_isready -h 127.0.0.1`, because the image's first start runs a temporary server on the
   socket only, then restarts it.
3. Write down the date, what was restored and what matched.

`latest` is the newest snapshot of any host; pass `--host` when several servers share a
repository. On a new server after a disaster, restore into a separate folder first and move
things into place, rather than restoring over a running app.

## Say how far it is verified

Report the highest step reached, with its date:

1. A job exists: the timer is enabled and shows a next run.
2. It ran: a run finished with status 0, and when.
3. The data is off the server: `restic snapshots` lists today's snapshot in the remote
   repository.
4. A restore was tested: one file compared and the dump loaded with matching counts, on a date.
5. The restore test repeats on a schedule, and the last one is recent.

"Backups: nightly to the bucket app-backups, kept 7 daily, 4 weekly, 6 monthly; restore tested
on 2026-11-11 (step 4)" is a statement the person can rely on. "Backups are set up" is not.

## Point-in-time recovery

A nightly dump can lose up to a day of writes. Point-in-time recovery keeps a base copy plus
the database's continuous change log (Postgres WAL archiving, with tools such as pgBackRest,
WAL-G or Barman; binary logs for MySQL and MariaDB) so you can restore to a chosen second, for
example just before a bad `DELETE`. It is worth it when hours of lost orders or payments would
hurt, or when the database is too large to dump nightly. It is one more system to run and to
restore-test, and it is included in most managed databases, which is often the reason to
choose one. For a small app, a nightly dump with a tested restore is the right first step.

## Before a risky change

Before a migration, a major upgrade or anything that rewrites data, take a fresh copy and say
which one you took:

- A dump now, named for the moment, checked as readable, and sent off the server:
  `pg_dump -Fc -Z 0 ... > app-before-<CHANGE>.pgdump`, `pg_restore --list` on it, then
  `restic backup --tag pre-change` on the file.
- A provider snapshot now, if the provider offers one, for a fast rollback of the whole server.
  It may bill while kept; delete it after the change has settled, with the person's yes.

Rolling back with either replaces everything written since, so that step needs the person's yes.

## Traps

- **A pipeline hides a failed dump.** `pg_dump app | gzip > app.sql.gz` reports gzip's status,
  so an empty file looks like success. Use `set -o pipefail`, write to a file and check it, as
  the template does.
- **A failed dump overwrites the last good one.** Write to a temporary name and rename after the
  check; the template keeps the old dump when a new one fails.
- **restic exits 3** when some files could not be read: the snapshot is saved without them. The
  template treats it as a failure.
- **Retention never removes snapshots after the paths change.** `forget` groups by host and
  paths by default, so adding a folder starts a new group and the old group keeps its last
  snapshots for good. Group by `host,tags`.
- **"repository is already locked"** after a run was killed: `restic list locks` shows them and
  `restic unlock` removes stale ones. A running backup holds a lock legitimately.
- **The restic password exists only on the server.** Lose the server, lose the backups.
- **The local dump folder fills the disk.** The template overwrites one dump per app; keep
  history in restic, not in the folder.

## Done means

- The timer is enabled with a next run, and one run started by hand finished with status 0.
- The repository is off the server and `restic snapshots` lists that run.
- One file and the database dump were restored and compared, and the date is recorded.
- The person has the restic password outside the server and said so.
- A failed or missing run reaches someone (a check-in monitor or `OnFailure=`).
- The hand-over says what is covered and what is not, where the backups are, how long they are
  kept, how to restore, and the step reached on the ladder above.

Checked against: restic 0.18.1, Postgres 18.6 and 16 (official images) and 15.19 (Debian 12),
MariaDB 11.8.9 (official image) and 10.11 (Debian 12), MySQL 8.4.13, SQLite 3.40.1, systemd 252
on Debian 12, ShellCheck 0.11.0, an S3-compatible server (SeaweedFS 3.97) in a container,
2026-11-12.
