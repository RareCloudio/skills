# Moving between setups

Read this when an app has outgrown where it runs, or someone wants it to: when one server is
still the right answer, what has to change before an app can run on several servers or on
Kubernetes, and how to move a live app without taking it down. Picking the first setup, and the
ladder of setups, is in [choosing.md](choosing.md); running an app on a cluster once it is there
is in [kubernetes.md](kubernetes.md).

## When one server is still the right answer

One well-sized server runs more than people expect: a typical web app with its database, a
cache and a reverse proxy, for thousands of daily users. It has one bill, one machine to patch,
one place to look when something breaks, and a person can understand all of it. Before moving
anything, find what is actually short, because the fix is often smaller than a new setup:

- CPU busy all day in the app process: a profile, a cache, a slow query fixed, then a bigger
  server (a resize is usually a restart of a few minutes);
- memory: what grows (the database's cache, workers, a leak) decides whether more memory helps;
- disk waits (`iostat -x 5` shows high `%util` and `await`): the database wants faster disks or
  more memory for its cache, not more servers;
- the database itself: the slow query log first; ten app servers in front of one slow query make
  it slower.

One server stays right while an hour of downtime during a resize or a host failure is
survivable, the busy hours fit on the biggest size that is still sensible, and one person looks
after it. Things worth doing on it anyway, because they make every later step smaller: settings
from the environment rather than files edited on the box, uploads in object storage, database
backups off the server with a restore done, a health endpoint, deploys from a built image or a
release folder rather than edits in place.

## The signs that it no longer is

- The app must stay up while a machine is down, for kernel updates or a failed host. That needs
  two of everything that serves requests, which is the step below.
- The busy hours no longer fit the biggest sensible size, or the quiet hours waste most of it.
- Background work starves the web requests, and splitting them onto separate machines would fix
  it.
- Several services, often looked after by different people, deploy on their own schedules.

Name the sign you saw, with the measurement, when you propose the move. "Peak CPU has been above
85% for three weeks on the largest size" is a reason; "we will need to scale" is not.

## Several servers behind a load balancer: what has to leave the server first

A load balancer sends each request to whichever server it likes. Anything the app keeps on one
server's disk or in one process's memory becomes wrong half the time. Move these out first,
while the app still runs on one server, and check each before adding the second:

- **Sessions.** Kept in memory or in files, a user is logged out whenever the next request lands
  on the other server. Keep them in the database or a shared cache, or in signed cookies. Sticky
  sessions (the balancer pinning a user to one server) hide the problem until that server goes,
  and load spreads unevenly.
- **Uploads and generated files.** On local disk, a file uploaded through one server is a 404
  from the other. Put them in object storage. A shared network file system works but becomes the
  next single point of failure and is slow for many small files.
- **Scheduled jobs that must run once.** Cron copied onto every server sends every e-mail twice
  and bills every customer twice. Run the schedule on exactly one machine, or take a lock in the
  database (in Postgres, `pg_try_advisory_lock`) so only one copy does the work.
- **The database.** Off the app servers, onto its own server or a managed service. The app
  servers then hold nothing that cannot be rebuilt, which is the whole point.
- **Migrations.** They run once per release, from one place, not from every server's start-up.
  During a rolling deploy old and new code run side by side, so a migration has to work with
  both: add the new column first, ship the code that uses it, drop the old one a release later.
- **Certificates.** If each server gets its own certificate with an HTTP-01 challenge, the
  authority's check can land on the other server, which does not have the token, and issuance
  fails at random. End TLS at the load balancer, or use the DNS-01 challenge, or issue on one
  machine and copy the certificate.
- **Logs and local caches.** Logs go somewhere central, or debugging means logging into every
  box. A per-process cache is fine when stale data for a minute does no harm; otherwise use a
  shared one.

The balancer's health check should call the app's ready endpoint, not only open the port. Deploy
one server at a time: take it out of the balancer, update it, check it, put it back.

## The step to Kubernetes

Everything in the previous section applies, because pods are servers that come and go even more
often. Kubernetes also stops and replaces pods on every deploy, every node upgrade and every
scale-down, so the app has to start fast, answer a readiness probe, and finish its in-flight
requests when it gets SIGTERM, within the grace period (30 seconds by default). Long jobs belong
in a queue with workers that can be interrupted and retried, not in a web request.

What it costs a single person, honestly:

- **A fixed floor.** Some providers bill the control plane; anything resembling high
  availability means at least two or three nodes; traffic in usually means a billed load
  balancer. The add-ons take their share of the nodes: on the test cluster used for these files,
  a gateway, cert-manager and metrics-server reserved about a third of a CPU and 1 GiB of memory
  before the app ran.
- **Upgrades on someone else's schedule.** Kubernetes ships about three minor versions a year and
  patches each for about a year (as of 2026-11-11, 1.35 to 1.37 are supported upstream). Managed
  providers upgrade the control plane when a version reaches its end, so node pools, add-ons and
  any removed APIs in your manifests have to keep up, several times a year.
- **More to know when it breaks.** A 502 can sit in the app, the probe, the Service, the route,
  the gateway, the certificate or the node. The person either learns it or depends on whoever
  set it up. [kubernetes-debugging.md](kubernetes-debugging.md) is the map.

What it buys: deploys, rollbacks and scaling become routine; many services share machines; a
failed node is replaced on its own; node pools grow and shrink with the work. For one app on one
or two servers, those gains rarely pay for the floor. A single-node distribution such as k3s on
one server gives the Kubernetes API without its resilience: worth it to learn or to keep the same
manifests as a bigger cluster, not to make one app more reliable than Compose would.

## Moving a live app without downtime

The order matters more than the tools. Write the plan down with the person, including the moment
of the switch and the way back, before step one.

**1. Lower the DNS TTL days ahead.** The TTL (time to live) is how long resolvers may keep the
old address. Lower it on the records you will change, to 300 seconds for example, at least one
old TTL before the switch, or resolvers keep sending visitors to the old place for hours after
it. Read the TTL from the domain's own nameserver, where the second column is the configured
value (a public resolver shows a countdown instead):

```
dig +short NS example.com
dig +noall +answer app.example.com A @<NAMESERVER>
```

**2. Build the new setup next to the old one** and give it a copy of the data. Test it before any
visitor can reach it, by its real name pointed at the new address only on your side:

```
curl -sS --resolve app.example.com:443:<NEW_ADDRESS> https://app.example.com/
```

A certificate for the real name can only be issued with HTTP-01 once DNS points at the new
place; use DNS-01 or copy the current certificate if HTTPS must work before the switch.

**3. Move the database.** It is the one part that cannot run in two places at once, and the
write freeze is the window when nothing writes anywhere: the old app is stopped or in a
maintenance mode, so no order or sign-up lands in the old database after the copy is taken and
is lost. Two ways, chosen by size and by how long a freeze the person accepts:

- **Dump and restore during the freeze.** Simple and complete. The freeze lasts as long as the
  dump plus the restore, so time a rehearsal on a copy first. For Postgres, `pg_dump -Fc` then
  `pg_restore`; for MySQL, `mysqldump --single-transaction --routines --triggers`.
- **Replicate, then a short freeze.** The new database follows the old one until the switch. With
  Postgres logical replication (the old server needs `wal_level = logical`): copy the schema
  with `pg_dump --schema-only`, `CREATE PUBLICATION` on the old one, `CREATE SUBSCRIPTION` on the
  new one, and watch it catch up. At the switch: freeze writes, check the replication slot on the
  old server shows no lag, then copy the sequences. Logical replication does not copy sequence
  values: in a test with Postgres 18.6 the rows arrived but the new side's sequence stood at 1,
  and the first insert failed with `duplicate key value violates unique constraint`. This sets
  each sequence on the new side from the old one:

  ```
  psql -h <OLD> -U <USER> -d <DB> -tAc "select format('select setval(%L, %s, true);',
    format('%I.%I', schemaname, sequencename), last_value) from pg_sequences
    where last_value is not null" \
    | psql -h <NEW> -U <USER> -d <DB>
  ```

  Then point the app at the new database, end the freeze, and `DROP SUBSCRIPTION` on the new
  side, which also removes the slot on the old server (a forgotten slot keeps WAL and fills the
  old server's disk).

Files go the same way: `rsync -a` ahead of time, then a last `rsync -a --delete` during the
freeze, which copies only what changed.

**4. Switch.** Change the DNS record (or the load balancer's target). For as long as the old TTL,
some visitors still reach the old servers. Those must not write to the old database: point the
old app at the new database if it can reach it privately, or turn the old web server into a
reverse proxy to the new address, so latecomers are served by the new setup. Scheduled jobs and
queue workers run in one place only: stopped on the old side at the freeze, started on the new
side after the switch.

**5. Keep the old setup until the new one has proved itself**, through at least one busy period
and one round of backups with a restore. Going back is easy until the first write lands in the
new database; after that, a way back means copying the new data back or replicating in the other
direction, so say plainly to the person that the switch is a one-way door once writes start.
Removing the old servers deletes data and stops a bill, and needs the person's yes. Raise the
TTL again once things are settled.

## What a move does to the bill and to the work

Read prices live when you compare, as in [choosing.md](choosing.md). In shape:

- **One server:** one machine billed; patching, backups and monitoring for one box; downtime
  whenever it restarts.
- **Several servers and a balancer:** the servers, the balancer, a database server or a managed
  one, object storage. Patching N machines wants automation (an image you rebuild, or a
  configuration tool), and deploys become rolling.
- **Kubernetes:** the control plane where billed, two or three nodes at the least, the load
  balancer, volumes, the add-ons' share of the nodes; cluster and add-on upgrades several times a
  year; in exchange, scaling and deploys that look after themselves.

Each step up costs more every month whether the load comes or not. Put the trigger that
justified it in the hand-over, so the next person can tell whether it still holds.

## Traps

- **Moving to fix a slow query.** The query is just as slow on the new setup, and now spread
  across more machines. Measure first.
- **Cron on every server.** Duplicate e-mails and charges the day the second server goes live.
- **The TTL lowered on the day of the move.** Resolvers keep the old, long TTL; visitors reach
  the old servers for hours.
- **The old app still writing after the switch.** Orders land in a database nobody reads any
  more. Freeze, then point stragglers at the new side.
- **Sequences forgotten after logical replication.** The first insert on the new database fails.
- **The old setup deleted on switch day.** The way back is gone exactly when a problem shows up.

## Done means

The app answers from outside on its real name from the new setup, checked as in
[proving-it-works.md](proving-it-works.md); the authoritative nameserver returns the new address;
the old database has received no writes since the freeze; scheduled jobs run once, on the new
side; a backup of the new setup was restored once; the TTL is back to its usual value; and the
old setup is either kept with a date to remove it, or removed with the person's yes.

Checked against: postgres:18.6 (dump and restore, logical replication, sequence copy, advisory
lock), mysql:8.4.13 (mysqldump), debian:12 with dig 9.18, kind v0.33.0 with Envoy Gateway v1.9.3,
cert-manager v1.21.3 and metrics-server 0.9.0 (add-on requests), the Kubernetes releases page,
2026-11-11.
