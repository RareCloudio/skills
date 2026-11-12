# Running an app with systemd

Read this when an app should run directly on the server, without containers: a Node, Python,
PHP worker, Go or Java process kept alive by systemd, deployed as release folders, with its
scheduled jobs as timers. Running it in containers is in [docker.md](docker.md); the proxy in front is in
[web-and-https.md](web-and-https.md).

Running without containers is a fine choice on one server: one process, one unit file, the journal for
logs, nothing between the app and the kernel. The price is that the runtime (Node, Python) is
installed on the host and updated with it, so pin it the way you would pin a base image.

## Prepare the user, the folders and the env file

The app gets its own system user with no shell and no home, so a hole in the app is not a
login. Code lives in `/srv/<app>`, owned by root so the app cannot rewrite it; settings in
`/etc/<app>/env`; data the app writes in `/var/lib/<app>`, which systemd creates (below).

```
useradd --system --no-create-home --shell /usr/sbin/nologin shop
install -d -m 0755 /srv/shop/releases
install -d -m 0750 -g shop /etc/shop
install -m 0640 -g shop /dev/null /etc/shop/env
getent passwd shop && ls -l /etc/shop/env
```

`/usr/sbin/nologin` exists on Debian, Ubuntu and the RHEL family alike. Put the runtime
somewhere every user can read (`/usr/bin/node` from a package, or `/opt/node-<version>`), and
write its absolute path in the unit. A runtime installed with nvm or pyenv under someone's home
is invisible to the service: systemd does not read login shells' `PATH`, and the sandboxing below
hides home folders entirely.

## Write the env file

`/etc/shop/env` holds `NAME=value` lines. systemd's parser is not a shell, and not Compose
either. The same file, read by both, was checked line by line:

| Line in the file | systemd sees | Compose sees |
|---|---|---|
| `A="quoted value"` | `quoted value` | `quoted value` |
| `C=plain # note` | `plain # note` | `plain` |
| `D=pa$word` | `pa$word` | `pa` (and a warning) |
| `E=pa$$word` | `pa$$word` | `pa$word` |
| `export F=x` | ignored, `F` unset (warning in the journal) | `x` |

So: no `export`, no comments at the end of a line, and a value with `$`, `#` or spaces in single
quotes or generated without them (`openssl rand -hex 32`). After writing it, read back what the
service really received rather than what the file says (shown once the unit runs):
`tr '\0' '\n' < /proc/$(systemctl show -P MainPID shop)/environ | cut -d= -f1`. That prints the
names only; leave the values out of the chat.

## Write the unit

Start from [templates/app.service](../templates/app.service) and fill its three placeholders;
the comments in it explain each line. Install it as `/etc/systemd/system/shop.service`, then:

```
systemd-analyze verify /etc/systemd/system/shop.service
systemctl daemon-reload
systemctl enable --now shop
systemctl is-active shop && curl -fsS http://127.0.0.1:3000/healthz
```

`verify` catches misspelled directives, values it cannot parse and a missing executable, and
prints nothing when the unit is fine. It does not notice a user that does not exist; `getent`
above does. Edits to a unit take effect after `daemon-reload` and a restart;
`systemctl cat shop` shows what systemd actually loaded, drop-ins included. For a change to a
packaged unit, use `systemctl edit <unit>` (a drop-in) rather than editing the file under
`/usr/lib/systemd`, which the next package update overwrites.

Choosing `Type=`:

- `exec` for a program that stays in the foreground, which is almost every app server. Unlike
  `simple`, it makes `systemctl start` fail when the program cannot be executed: with a wrong
  path, `simple` returns 0 and the failure is only in the journal.
- `notify` only when the program reports readiness through `sd_notify` (some do: check its
  documentation). One that does not is killed when `TimeoutStartSec` runs out, and the unit
  fails with result `timeout`.
- `forking` only for a daemon that backgrounds itself and cannot be told not to. Better to
  run it in the foreground (most have a flag) and use `exec`.
- `oneshot` for jobs that run and end, such as the timer's service below.

Restart behaviour: `Restart=on-failure` with `RestartSec=5s`. The start limit decides what
happens in a crash loop. With the defaults (5 starts in 10 seconds) and `RestartSec=5s`, the limit
is never reached and a broken app restarts forever without anyone noticing. The template sets
5 starts in 10 minutes, so a crash loop ends within about half a minute as `failed`, which
`systemctl --failed` and monitoring can see. Every start counts, manual ones too, which matters
for deploys (next section).

## Sandbox it, and know what each line costs

The template's sandboxing takes `systemd-analyze security shop` from 9.6 (UNSAFE) for a bare
unit to 1.5 (OK) on Debian 13, and a plain Node web app ran under it unchanged. Each line still
takes something away, and when an app breaks the error usually names it. What each removes, and how it shows:

- `ProtectSystem=strict`: the whole file system is read-only to the app. A write into its code
  folder fails with `EROFS: read-only file system`. Give writable places by name:
  `StateDirectory=` (`/var/lib/<app>`), `CacheDirectory=`, `LogsDirectory=`, or `ReadWritePaths=`
  for a path that exists already.
- `ProtectHome=yes`: `/home`, `/root` and `/run/user` look empty. An executable there fails with
  status 203/EXEC and `Unable to locate executable`.
- `PrivateTmp=yes`: the app gets its own `/tmp`, emptied when it stops. A Unix socket placed in
  `/tmp` for another service to use is not visible to it; use `RuntimeDirectory=` instead.
- `NoNewPrivileges=yes`, `CapabilityBoundingSet=`: no setuid helpers, no root powers. A port
  below 1024 needs `AmbientCapabilities=CAP_NET_BIND_SERVICE` plus that capability in the bounding
  set; a proxy in front on 80 and 443 avoids it.
- `RestrictAddressFamilies=`: Node's `os.networkInterfaces()` throws
  `uv_interface_addresses returned Unknown system error 97` without `AF_NETLINK`, which is why
  the template keeps it.
- `SystemCallFilter=@system-service` with `SystemCallErrorNumber=EPERM`: a refused call returns
  an error the app can log, instead of the process being killed outright.
- `MemoryDenyWriteExecute=yes` is left out of the template: V8 aborts at start with
  `Fatal error` and the unit fails with `status=5/TRAP`. The same goes for other JIT runtimes.
  Add it for Go, Rust and C.

When the app fails only under the sandbox, find the one line responsible from the journal and
relax that one; do not drop the whole block.

## Deploy as releases with a `current` symlink

Each version goes into its own folder, `/srv/shop/releases/<id>` (a timestamp or a commit),
with its dependencies installed or its build copied in. The unit runs from `/srv/shop/current`,
a symlink. Switching is changing the link and restarting; rolling back is pointing it back.
Shared data stays outside the releases, in `/var/lib/shop`.

A deploy script along these lines was run against a release that crashes on start; it rolled
back, twice in a row, and on a first deploy (no `current` yet) it switched, or said why not:

```
#!/bin/bash
# deploy.sh <release-id>: switch to /srv/shop/releases/<release-id>, check, roll back on failure
set -euo pipefail
app=shop; base=/srv/$app; rel=$1
health=http://127.0.0.1:3000/healthz
prev=$(readlink "$base/current" || true)        # empty on the first deploy
ln -sfn "releases/$rel" "$base/current"
systemctl reset-failed "$app"; systemctl restart "$app"
if ! curl -fsS --retry 10 --retry-delay 2 --retry-all-errors --max-time 5 "$health"; then
  [ -n "$prev" ] || { echo "health check failed; first deploy, nothing to roll back to" >&2; exit 1; }
  echo "health check failed, rolling back to $prev" >&2
  ln -sfn "$prev" "$base/current"
  systemctl reset-failed "$app"; systemctl restart "$app"
  exit 1
fi
# keep the five newest releases, never the one in use
keep=$(readlink -f "$base/current")
ls -1d "$base"/releases/*/ | sort | head -n -5 | while read -r old; do
  [ "$(readlink -f "$old")" = "$keep" ] || rm -rf -- "$old"
done
```

Why it is written this way:

- **`reset-failed` before each restart.** The broken release used up the start limit while
  the health check waited, and without it the rollback's restart was refused with `Start request
  repeated too quickly`, leaving the app down on the old code. Five ordinary deploys within ten
  minutes would hit the same limit.
- **A restart after the switch.** A running process keeps the files it already loaded; changing
  the link alone changes nothing until the restart.
- **The health check retries.** The app needs a moment to listen; one immediate request fails
  even on a good release.
- **`ln -sfn` is atomic with GNU coreutils** (8.32 to 9.7 were traced: it creates a temporary
  link and renames it over the old one), so nothing ever sees a missing `current`. On BusyBox or
  BSD, create the new link under a temporary name and `mv -T` it into place.

The restart is a few seconds without the app. On one server that is usually acceptable; say so
in the hand-over. Avoiding it means two instances behind the proxy, switched one at a time.
Rolling back the code does not roll back database migrations, so a migration that removes or
renames something needs a backup taken just before it and its own plan.

## Read the journal

```
journalctl -u shop -n 100 --no-pager          # the last lines, newest at the bottom
journalctl -u shop -f                         # follow while you test
journalctl -u shop --since "-15min" --no-pager # the last quarter hour, every priority
systemctl status shop --no-pager              # state, main PID, the last few lines
systemctl --failed                            # every unit that gave up
```

Read the unit's log without `-p`: journald stores everything a service prints on stdout and
stderr at priority info, so `-p warning` hides the app's own errors and leaves only systemd's
lines (checked on Debian 12, systemd 252; see [monitoring-and-logs.md](monitoring-and-logs.md)).
systemd's own lines (`Main process exited, code=exited, status=1/FAILURE`, `Start request
repeated too quickly`) sit between the app's lines and usually say more than the app does. If
`/var/log/journal` does not exist, the journal is kept in memory and lost at reboot (the case on
some minimal images); `mkdir -p /var/log/journal && systemctl restart systemd-journald` makes it
persistent, capped by default at a share of the disk.

## Scheduled jobs: timers instead of cron

Use [templates/app-job.service](../templates/app-job.service) and
[templates/app-job.timer](../templates/app-job.timer), installed under the same name
(`shop-cleanup.service` and `shop-cleanup.timer`). Compared with a crontab line, the job runs
with the app's user, env file and sandbox, its output lands in the journal with its exit status,
a run still going is not started twice, and `Persistent=true` catches up a run the server missed
while it was off.

```
systemd-analyze calendar '*-*-* 03:15:00'       # prints the next times it fires
systemd-analyze verify /etc/systemd/system/shop-cleanup.{service,timer}
systemctl daemon-reload && systemctl enable --now shop-cleanup.timer
systemctl start shop-cleanup.service            # one run now, by hand
systemctl show -P Result shop-cleanup.service   # success
systemctl list-timers shop-cleanup.timer
```

Enable the timer, not the service. Calendar times are in the server's time zone unless one is
written at the end (`*-*-* 03:15:00 UTC`).

## Traps

- **A crash loop nobody sees.** `RestartSec=5s` with the default start limit restarts forever.
  The template's limit turns it into a visible `failed` state.
- **A deploy that cannot roll back.** The failed release used up the start limit; the restart
  of the good release is refused. `systemctl reset-failed` first.
- **`Type=simple` hides a bad path,** and `Type=notify` on an app that never notifies is
  killed at the start timeout.
- **The env file read like a shell script:** `export` lines are dropped and a trailing comment
  becomes part of the value. Check the names that arrived, as above.
- **An app that writes into its own folder** fails under `ProtectSystem=strict`; uploads and
  caches belong in `StateDirectory=` or `CacheDirectory=`, which also survive a release switch.
- **Editing the unit without `daemon-reload`.** systemd keeps running the old definition and
  `systemctl status` warns that the file changed on disk.

## Done means

- `systemd-analyze verify` prints nothing for each unit, and `systemd-analyze security` rates the
  app's unit OK or explains each line that was relaxed.
- `systemctl is-enabled shop` says `enabled`, `systemctl is-active shop` says `active`, and the
  health endpoint answers on the loopback address.
- A deploy of a deliberately broken release rolled back by itself, or the person chose to skip
  that test and the hand-over says so.
- Each timer appears in `systemctl list-timers` with its next run, and one run by hand ended in
  `success`.
- The app comes back after a reboot, tried once before it serves people (later, a reboot needs
  the person's yes).

Checked against: systemd 257 (Debian 13, booted in a container), 255 (Ubuntu 24.04) and 252
(AlmaLinux 9) for verify and security, Node.js 20.19 from Debian, GNU coreutils 8.32 to 9.7,
2026-11-12.
