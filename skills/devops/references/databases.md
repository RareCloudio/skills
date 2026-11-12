# Running a database on your own server

Read this when an app needs Postgres or MySQL/MariaDB on a server you look after, on the same
machine as the app or on a neighbour over a private network, and when Redis comes along. It
covers installing, keeping the port off the internet, roles, connection limits, memory,
migrations that do not take the site down, finding a slow query, major upgrades, and when a
managed database is the better answer. Dumps, off-server copies and restore tests are in
[backups.md](backups.md).

## Install it

- **The distribution's package.** Security fixes arrive with the OS updates. Debian 12 ships
  Postgres 15 and MariaDB 10.11; Ubuntu 24.04 ships Postgres 16, MariaDB 10.11 and MySQL 8.0.
  Debian has no `mysql-server` package; `default-mysql-server` installs MariaDB.
- **The vendor's repository,** when the app needs a newer major version. For Postgres on Debian
  and Ubuntu, the distribution's own `postgresql-common` package sets up the PGDG repository
  with its signing key:
  ```
  apt install -y postgresql-common
  /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  apt install -y postgresql-18
  ```
  On Alma and Rocky 9 the default `postgresql-server` is 13; newer majors come as module
  streams (`dnf module list postgresql` shows 15, 16 and 18 on Alma 9) or from the vendor's RPM
  repository, and the config sits with the data in `/var/lib/pgsql/data`, not in `/etc`.
- **A container,** when the app already runs in Compose. Use the official image with its major
  version in the tag (`postgres:18-trixie`, `mariadb:11.8`), never `latest`: a new major version
  cannot open the old one's data folder, so an unplanned pull of a new major leaves the
  database down, while the major's own tag is rebuilt with fixes (the tag rule is in
  [first-deploy.md](first-deploy.md)). Keep the data in a named volume. Since Postgres 18 the image keeps its data
  in `/var/lib/postgresql/18/docker`, so mount the volume at `/var/lib/postgresql`; with the
  old `/var/lib/postgresql/data` mount the 18 image refuses to start and says why.
  ```yaml
  services:
    db:
      image: postgres:18-trixie
      restart: unless-stopped
      environment:
        POSTGRES_DB: app
        POSTGRES_USER: app
        POSTGRES_PASSWORD_FILE: /run/secrets/db_password
      secrets: [db_password]
      volumes: [db-data:/var/lib/postgresql]
      # No ports: the app reaches it as db:5432 on the Compose network.
  volumes: {db-data: {}}
  secrets: {db_password: {file: ./db_password.txt}}
  ```
  Check it with `config -q`, then `up -d`, run as [first-deploy.md](first-deploy.md) runs Compose:
  `sudo -u deploy docker compose --project-directory /srv/shop <command>`.

## Keep the port off the internet

Scanners sweep every public address for 5432, 3306 and 6379 all day. An exposed database gets
password guessing within hours, and a weak or default password is found. Nothing outside the
app's own servers needs to reach it.

- The Debian packages listen on localhost by default (`listen_addresses` commented out at its
  default, `bind-address = 127.0.0.1`). Keep it that way when the app is on the same machine.
  On Alma 9, MariaDB 10.5 listens on every interface out of the box: set
  `bind-address = 127.0.0.1` in `/etc/my.cnf.d/mariadb-server.cnf`.
- The official images listen on every interface inside the container, which is fine, because
  the container is not reachable until you publish a port. `ports: ["5432:5432"]` publishes on
  every interface of the host, and Docker adds its own firewall rules for it, which ufw does
  not see ([firewall.md](firewall.md) explains). Publish nothing, or `127.0.0.1:5432:5432` when a tool on
  the host needs it.
- For a database on a second server, listen on the private address only
  (`listen_addresses = 'localhost,10.0.0.5'`, which needs a restart), allow the app server in
  `pg_hba.conf` (`host  app  app  10.0.0.0/24  scram-sha-256`, then reload), and allow only that
  address in the firewall. For MariaDB, set `bind-address` to the private address.
- To reach it yourself, use an SSH tunnel: `ssh -L 5432:localhost:5432 <SERVER>`.

Prove it: `ss -ltn | grep -E ':(5432|3306|6379)\b'` shows `127.0.0.1` or the private address,
and from outside, `scripts/check_site.py` with `--expect-closed 5432,3306,6379` (see
[proving-it-works.md](proving-it-works.md)). After a change to `pg_hba.conf`, `SELECT * FROM
pg_hba_file_rules WHERE error IS NOT NULL;` shows lines Postgres could not read.

## A role and a database per app

One login per app, owning one database, so a leaked app password reaches one app's data only.

```
CREATE ROLE app LOGIN CONNECTION LIMIT 20;
\password app
CREATE DATABASE app OWNER app;
REVOKE CONNECT ON DATABASE app FROM PUBLIC;
```

`\password` in `psql` prompts for the password, which keeps it out of shell history and the
server log. Generate it with `openssl rand -hex 24`: hex needs no escaping in a connection URL,
where `@`, `/` or `#` otherwise break the parsing. Since Postgres 15 the `public` schema no
longer lets every role create tables; it belongs to the database owner, so the owning app role
can still run its migrations. Every role can still connect to a database whose `CONNECT` has
not been revoked from `PUBLIC`, hence the `REVOKE`.

For a stricter split, migrations run as the owner and the app runs as a role that can only
read and write rows:

```
CREATE ROLE app_rw LOGIN;
GRANT CONNECT ON DATABASE app TO app_rw;
GRANT USAGE ON SCHEMA public TO app_rw;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_rw;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO app_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE app IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_rw;
ALTER DEFAULT PRIVILEGES FOR ROLE app IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO app_rw;
```

The default privileges cover tables the owner creates later. Check it: as `app_rw`, an
`INSERT` works and `CREATE TABLE` fails with "permission denied for schema public".

MySQL and MariaDB:

```
CREATE DATABASE app CHARACTER SET utf8mb4;
CREATE USER 'app'@'localhost' IDENTIFIED BY '<DB_PASSWORD>';
GRANT ALL PRIVILEGES ON app.* TO 'app'@'localhost';
SHOW GRANTS FOR 'app'@'localhost';
```

The host part is matched against where the connection comes from. An app in a container
connects from its Docker network address, not from `localhost`, and gets "Access denied for
user 'app'@'172.23.0.6'". Create the user for that subnet (`'app'@'172.23.0.%'`) or for the
private network, rather than for `'%'`.

## Connections against the app's pool

Postgres allows 100 connections by default and keeps 3 for superusers; MySQL and MariaDB allow
151. Each Postgres connection is a separate process with its own memory. Add up what can
connect at once: app processes times their pool size, plus workers, a migration, a backup and
you in `psql`, and keep it under the limit with room to spare. When the app outgrows that, run
fewer processes with bigger pools or put PgBouncer in front; `max_connections` in the thousands
costs memory a small machine does not have.

Past the limit, new connections fail. In Postgres 18 a normal role sees "remaining connection
slots are reserved for roles with the SUPERUSER attribute"; a role over its own `CONNECTION
LIMIT` sees "too many connections for role". See who holds them:

```
SELECT usename, state, count(*) FROM pg_stat_activity GROUP BY 1, 2 ORDER BY 3 DESC;
SHOW STATUS LIKE 'Max_used_connections';      -- MySQL and MariaDB: the high-water mark
```

Many `idle in transaction` sessions mean the app forgets open transactions, which hold locks.

## Memory on a small machine

The defaults suit a tiny machine and are rarely the problem; a database tuned for more memory
than the server has, next to the app, is what the kernel kills when memory runs out. These are
starting points for a server that also runs the app, not measured results; watch memory after.

- `shared_buffers` (default 128MB): Postgres's own cache. About a quarter of RAM on a dedicated
  server, less beside the app: 256MB to 512MB on 2 GB. Needs a restart.
- `effective_cache_size` (default 4GB): a planner hint about the OS cache; allocates nothing.
  Half to three quarters of RAM.
- `work_mem` (default 4MB): per sort or hash, per query step, per connection, so it multiplies.
  Raise it a little only when the slow log shows sorts spilling to disk.
- `maintenance_work_mem` (default 64MB): index builds and vacuum; 128MB to 256MB is fine.

On Debian, put them in `/etc/postgresql/<VERSION>/main/conf.d/app.conf`, which the main file
includes. `ALTER SYSTEM SET ...` writes `postgresql.auto.conf` instead, and in a container
`command: ["postgres", "-c", "shared_buffers=512MB"]` does it. Check what is active and what
waits for a restart:

```
SELECT name, setting, unit, pending_restart, sourcefile FROM pg_settings
WHERE name IN ('shared_buffers', 'work_mem', 'effective_cache_size', 'max_connections');
```

MySQL and MariaDB: `innodb_buffer_pool_size` (default 128MB) is the one that matters, about a
third of RAM beside the app, up to 70% on a dedicated server. It can change at run time
(`SET GLOBAL innodb_buffer_pool_size = 512*1024*1024;`) and belongs in a drop-in such as
`/etc/mysql/mariadb.conf.d/60-app.cnf`; `mariadbd --print-defaults` shows what it will start
with, a quick check for typos:

```
[mariadbd]
bind-address            = 127.0.0.1
max_connections         = 50
innodb_buffer_pool_size = 512M
```

## Change the schema without taking the site down

Take a dump first and check it reads back ([backups.md](backups.md), "Before a risky change").
The way back is that dump, or a down migration that was tested, decided before you start.

The trap is the lock queue. A Postgres `ALTER TABLE` needs an exclusive lock. If a long query
or an idle transaction is reading the table, the `ALTER` waits, and every plain `SELECT` that
arrives after it waits behind the `ALTER`. A change that would take a millisecond then hangs
the site for as long as that old transaction lives. MariaDB does the same with its metadata
lock, even for `ALGORITHM=INPLACE, LOCK=NONE`. Make the migration give up instead, and retry:

```
SET lock_timeout = '5s';            -- Postgres: "canceling statement due to lock timeout"
SET SESSION lock_wait_timeout = 5;  -- MySQL/MariaDB: "Lock wait timeout exceeded"
```

What is cheap and what is not, in Postgres:

- Adding a column, even `NOT NULL` with a constant default, only touches the catalogue. A
  volatile default (`random()`, `clock_timestamp()`) rewrites the whole table under the lock.
- Changing a column's type usually rewrites the table.
- `CREATE INDEX` blocks writes while it builds; `CREATE INDEX CONCURRENTLY` does not, but cannot
  run inside a transaction ("cannot run inside a transaction block"), and many migration tools
  wrap each migration in one. Use the tool's switch for a non-transactional migration.
- MariaDB and MySQL: ask for `ALGORITHM=INPLACE, LOCK=NONE`; the statement fails rather than
  falling back to a blocking copy when it cannot do that.

For a rename or a removal, change in steps that both the old and the new code can live with:
add the new column, deploy code that writes both, backfill, switch reads, and drop the old one
in a later release. Run migrations once per deploy, not from every app container at start.

## Find a slow query

Postgres. Log what is slow, then rank by total time:

```
ALTER SYSTEM SET log_min_duration_statement = '500ms';    -- takes effect on reload
ALTER SYSTEM SET shared_preload_libraries = 'pg_stat_statements';   -- needs a restart
```

After the restart, a superuser runs `CREATE EXTENSION pg_stat_statements;` in the app's
database (the app role cannot), and `GRANT pg_read_all_stats TO app;` lets the app role see
other roles' query text. Then:

```
SELECT calls, round(mean_exec_time::numeric, 1) AS mean_ms,
       round(total_exec_time::numeric) AS total_ms, left(query, 80)
FROM pg_stat_statements ORDER BY total_exec_time DESC LIMIT 10;
```

A fast query called a million times can cost more than one slow report. Take the worst to
`EXPLAIN (ANALYZE, BUFFERS)`, which runs the query for real, so wrap an `UPDATE` or `DELETE` in
`BEGIN; ... ROLLBACK;`. A `Seq Scan` with "Rows Removed by Filter" in the hundred thousands on
a selective filter means a missing index: in one test, adding it with `CREATE INDEX
CONCURRENTLY` took a lookup from 29 ms to 0.07 ms.

MySQL and MariaDB: turn on the slow log (`SET GLOBAL log_slow_query = 1; SET GLOBAL
log_slow_query_time = 0.5;`), read it, then `EXPLAIN` the query (`type: ALL` is a full scan).
These are the MariaDB 10.11 names; `slow_query_log` and `long_query_time` still work and are
the names MySQL uses. `SET GLOBAL` applies to new connections, not to the session you typed it
in, so test from a new one. Put the same settings in the drop-in so they survive a restart.

## Major version upgrades

A major version changes the on-disk format, so the new server cannot open the old data folder.
The ways across are a dump and restore (simple, downtime grows with the size, fine for a few
GB), or `pg_upgrade` with both versions installed (fast; Debian wraps it as
`pg_upgradecluster`, not run here). For a container, that means a dump from the old image and a
restore into a new volume with the new one. MariaDB upgrades in place and then runs
`mariadb-upgrade` for its system tables (not run here). Whatever the route: a fresh dump
first, a rehearsal on a copy with the app's tests run against it, and the person's yes for the
downtime window. Read the release notes for removed settings and changed defaults before.

## When a managed database is the better answer

Say so when it fits: nobody will apply updates, watch the disk or repeat restore tests; losing
more than a few minutes of writes is not acceptable (point-in-time recovery is built in); the
app needs automatic failover to a standby; or the data is outgrowing the server. A managed
database costs more per GB, adds network latency and limits extensions and settings. For a
small app with nightly dumps and a tested restore, a database next to the app is a sound
choice. Which providers fit is in [choosing.md](choosing.md).

## Redis

Redis is a cache that can be lost, or a queue or session store that cannot. Decide which first.

- **Not exposed.** The Debian package binds `127.0.0.1 -::1` with protected mode on. The
  official image binds every interface with protected mode off, so a published port is an open
  Redis that anyone can read, wipe or abuse. Publish nothing.
- **A password,** in a file only Redis reads: `requirepass` in an included config file. Clients
  use `REDISCLI_AUTH` or the app's URL (`redis://:<REDIS_PASSWORD>@localhost:6379/0`). Without
  it, `redis-cli ping` answers "NOAUTH Authentication required."
- **Persistence.** By default Redis saves a snapshot at intervals
  (`save 3600 1 300 100 60 10000`) with the append-only file off, so a crash loses the last
  minutes of writes. For a queue or sessions, set `appendonly yes`; a cache can stay as it is.
- **A memory cap.** Without `maxmemory`, Redis grows until the kernel kills something. A cache:
  `maxmemory 256mb`, `maxmemory-policy allkeys-lru`. A queue keeps the default `noeviction`
  (a full Redis refuses writes rather than drop jobs); watch its size.

## Traps

- **A published container port is public** whatever ufw says. Check from outside.
- **`latest` as the image tag** pulls a new major one day; it does not start on the old data.
- **`'app'@'localhost'` for an app in a container** is refused: it connects from the network.
- **An `ALTER TABLE` behind an idle transaction** stops every read of that table.
- **`EXPLAIN ANALYZE` on an `UPDATE`** changes the data unless you roll it back.
- **More app workers after a scale-up** can exhaust the connections; add up the pools first.

## Done means

- It listens only on localhost or the private address; a check from outside shows it closed.
- The app has its own role and database; its password lives where [secrets.md](secrets.md) says.
- The pools add up to less than `max_connections`; memory settings are written down with why.
- The slow log is on, and this database's backups were restored once ([backups.md](backups.md)).
- The hand-over names the version, where the config lives, and how to upgrade it.

Checked against: Postgres 18.6 and 16 (official images), Postgres 15.19, MariaDB 10.11 and Redis
7.0.15 (Debian 12 packages), MariaDB 10.5 (AlmaLinux 9 package), MariaDB 11.8.9,
MySQL 8.4.13 and Redis 7.4 (official images), Docker Compose 5.6.0, 2026-11-12.
