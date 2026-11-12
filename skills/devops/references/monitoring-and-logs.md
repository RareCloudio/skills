# Monitoring and logs

Read this when you set up monitoring for a server or an app that one person looks after, or when
you need to read logs to find out what happened. It covers the outside check, a short list of
alerts, the options from a script on a timer to Prometheus, and the log recipes that find the
first error. Working through a live outage is [outage.md](outage.md); a slow server is
[performance.md](performance.md); checking that backups run is [backups.md](backups.md).

## The one check every setup gets

An uptime check from somewhere other than the server. A server cannot report that it is dead,
that its network is gone or that its certificate expired, because whatever would send the alert
is on the broken side. Every setup gets this one, even when the person wants nothing else:

- it requests the real public URL over HTTPS, the way a visitor does, every one to five minutes;
- it alerts after two failures in a row, so one dropped packet does not wake anyone;
- it alerts to something the person reads on their phone (mail, a push app, a chat channel);
- it runs from a hosted uptime service or from a small monitor (Uptime Kuma, Gatus) on a
  different machine with a different provider, never on the server it watches.

Point it at a page that proves the app works, not only that the proxy answers: a `/health`
endpoint that makes one cheap query to the database is a good target. Then prove the alert
reaches the person: point the check at a path that returns 404, wait for the alert, and point it
back. An alert path that was never tested is the one that fails when it matters.

## Alert on what the person will feel

An alert is worth having when it means "act now" and says what to do. A dozen alerts that fire
weekly teach people to ignore all of them, including the one that matters. Five cover most
small setups:

| Alert | Fires when | Why this one |
|---|---|---|
| Site down | two outside checks in a row fail | it is what visitors feel |
| Disk nearly full | space or inodes at 85 percent | time to act before writes fail |
| Memory | the kernel killed a process for memory | "90 percent used" is mostly cache |
| Certificate | fewer than 14 days left | renewal normally happens earlier |
| Backup | no successful run in 26 hours | a stopped backup is found too late |

Prefer symptoms to causes. "CPU at 95 percent" is not something visitors feel and often means
the machine is doing its job; a slow or failing page is. Put the response time in the outside
check and alert on that, and keep CPU and load as graphs for diagnosis. The certificate
threshold assumes 90-day certificates; if yours live shorter, find out how early they renew and
set the alert below that. For the backup, the job itself pings a heartbeat URL (a "dead man's
switch": a check that alerts when the ping stops) as its last step after a successful upload,
so a crash, a full disk or a deleted timer all show up the same way.

## Pick the smallest setup that does the job

**A script on a systemd timer.** `templates/healthcheck.sh` with `healthcheck.service` and
`healthcheck.timer` checks one URL, disk and inode use on the paths you name, the days left on
the certificate the server really sends, and whether the kernel killed a process for memory
since the last run (the `oom_kill` counter in `/proc/vmstat`). It exits 1 with one line per
problem, so the unit fails and the reason is in the journal, and it POSTs to an optional
`ALERT_URL` only when the set of problems changes, so a long outage sends one alert and one
"recovered". It costs nothing to run and suits one server, alongside the outside check, not
instead of it. Install and prove it:

```
install -m 0755 healthcheck.sh /usr/local/bin/healthcheck.sh
cp healthcheck.service healthcheck.timer /etc/systemd/system/      # placeholders filled in
systemd-analyze verify /etc/systemd/system/healthcheck.service
systemctl daemon-reload && systemctl enable --now healthcheck.timer
systemctl start healthcheck.service; journalctl -u healthcheck -n 5 --no-pager
```

Healthy output is one line, `OK url 200 disk / 23% disk /var 23% cert 89d`. A failure prints
lines such as `PROBLEM cert: app.example.com expires in 4 days (Nov 16 21:29:07 2026 GMT)` or
`PROBLEM inodes /srv: 100% used`, and `systemctl --failed` lists the unit. Test the alert once
by setting `CHECK_URL` to a path that fails, with the person's knowledge that an alert is
coming. `ALERT_URL` often holds a token, so it lives in `/etc/healthcheck.env` (mode 0600), not
in the unit file.

**A hosted uptime service.** The outside check with nothing to run. Worth it for everyone; the
only upkeep is keeping the contact details current.

**node_exporter, Prometheus and Grafana.** node_exporter publishes the host's numbers, Prometheus
stores them and evaluates alert rules, Alertmanager sends the alerts, Grafana draws the graphs.
Worth its upkeep when there are several servers, when you need history to answer "when did this
start" or "when will the disk fill", or when the person already runs it. It is several more
services to update, secure and back up, and it needs its own disk. Run it on another machine,
or at least send its alerts from elsewhere, and keep port 9100 (node_exporter) and 9090
(Prometheus) off the internet: they show the host's internals to anyone who asks. Rules that
match the table above, checked with `promtool check config` and loaded by Prometheus 3.5
scraping node_exporter 1.9:

```
groups:
  - name: server
    rules:
      - alert: TargetDown
        expr: up == 0
        for: 5m
      - alert: DiskWillFillIn24h
        expr: |
          node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"} / node_filesystem_size_bytes < 0.15
          and predict_linear(node_filesystem_avail_bytes{fstype!~"tmpfs|overlay"}[6h], 24 * 3600) < 0
        for: 30m
      - alert: OOMKill
        expr: increase(node_vmstat_oom_kill[15m]) > 0
```

`TargetDown` only says Prometheus lost the host; the outside check still decides whether the
site is down. Prometheus in Kubernetes is its own topic; [kubernetes.md](kubernetes.md) covers what a cluster
needs.

## Logs: find the first error, not the loudest

The journal holds the output of everything systemd starts and the kernel's messages. The
recipes that find things:

```
journalctl -u app --since "30 min ago" --no-pager          # one unit, recent
journalctl -u app --since "2026-11-12 09:00" --until "2026-11-12 09:30"
journalctl -u app -f                                        # follow while you reproduce it
journalctl -u app -b -o short-iso --no-pager                # this boot, sortable timestamps
journalctl -b -1 -p warning --no-pager                      # the boot before a crash or reboot
journalctl -k --no-pager | grep -i -E 'out of memory|killed process'
journalctl -u app --grep 'refused|timeout' -n 20 --no-pager
```

To find the first error rather than the loudest, look for the first line that names a failure
after the last start, then read what came just before it:

```
journalctl -u app -b --no-pager | grep -n -m1 -i -E 'error|fatal|panic|exception|refused'
journalctl -u app -b -o cat --no-pager | sort | uniq -c | sort -rn | head    # the loudest
```

The loudest message is usually the consequence (a hundred "cannot reach database"), while the
first is the cause (one "password authentication failed" ten seconds earlier).

`-p` filters on the priority the sender set. systemd's own lines and programs that log through
syslog carry real priorities, but a service's plain stdout and stderr are both stored at
priority 6 (info), so `-p err` hides an app's errors; we checked with `-o verbose`, which showed
`PRIORITY=6` on the app's stderr line. An app can mark a line by starting it with `<3>`.

**Is the journal kept across reboots?** With `/var/log/journal` present it is. It was there on
Debian 12 and Ubuntu 24.04 once systemd was installed; in the `almalinux:9` image it was not,
and journald said `Runtime Journal (/run/log/journal/...)`, which is lost at reboot. Make it
persistent, then confirm with the line journald prints:

```
mkdir -p /var/log/journal && systemd-tmpfiles --create --prefix /var/log/journal
systemctl restart systemd-journald
journalctl -u systemd-journald -o cat --no-pager | grep 'System Journal' | tail -1
```

**The journal's size.** By default it may use up to 10 percent of its filesystem, capped at
4 GB (journald printed `max 4.0G` on a large disk). On a small disk set a limit you choose:

```
mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nSystemMaxUse=500M\nMaxRetentionSec=1month\n' \
  > /etc/systemd/journald.conf.d/size.conf
systemctl restart systemd-journald
journalctl --disk-usage
```

### The proxy's logs

Debian's nginx package writes `/var/log/nginx/access.log` and `error.log`; the official nginx
image links both to the container's stdout and stderr, so there you use `docker logs`. The
default "combined" access log puts the status in field 9 and the path in field 7:

```
awk '{print $9}' /var/log/nginx/access.log | sort | uniq -c | sort -rn          # status counts
awk '$9 >= 500 {print $9, $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn | head
awk '{print substr($4, 2, 17)}' /var/log/nginx/access.log | uniq -c | tail     # requests a minute
```

The error log explains a 5xx (see the 502, 503 and 504 lines in [outage.md](outage.md)). Caddy
writes its errors to the journal (`journalctl -u caddy`) and writes access logs only for sites
with a `log` directive, as JSON lines; an access entry for a 5xx answer carries
`"level":"error"`. Read them with `jq`:

```
journalctl -u caddy -o cat --no-pager \
  | jq -r 'select(.status >= 500) | [.ts, .status, .request.uri] | @tsv'
```

### Container logs

```
docker logs --since 10m --timestamps shop-app-1    # <project>-<service>-1, as docker ps shows
sudo -u deploy docker compose --project-directory /srv/shop logs -f --tail 100 app
```

Docker keeps each container's output in a file on the host until the container is removed.
Docker documents its default `json-file` driver as keeping that file without a limit, so a
chatty container fills the disk over months (our test daemon was set to another driver, so we
did not watch it happen). [templates/compose.yaml](../templates/compose.yaml) sets a limit for
every service (`max-size: "10m"`, `max-file: "5"`, explained in [docker.md](docker.md)); check a
running container with `docker inspect -f '{{.HostConfig.LogConfig}}' <container>`, which then
shows `{json-file map[max-file:5 max-size:10m]}`.

The same can be set for every container in `/etc/docker/daemon.json` (`"log-driver": "local"`,
which rotates by default, or `json-file` with `log-opts`). That needs a restart of the Docker
daemon, which stops every container unless `live-restore` is set, so it is a change to ask about,
and it only applies to containers created afterwards. Check with
`docker info --format '{{.LoggingDriver}}'`. The daemon-wide change was not run in our tests.

### Log files the app writes itself

When an app writes its own files under `/var/log/<app>/`, give it a logrotate entry:
`templates/logrotate-app`, installed as `/etc/logrotate.d/<app>`. Check it with
`logrotate -d /etc/logrotate.d/<app>`, which prints what it would do and changes nothing, then
force one real run and look at the files:

```
logrotate -f /etc/logrotate.d/<app> && ls -l /var/log/<app>/
```

logrotate runs once a day from `logrotate.timer` on Debian, Ubuntu and Alma, so a size limit in
the entry (`maxsize`) only takes effect at that daily run.

## Traps

- **Monitoring that lives on the monitored server.** When the server dies, so does the alert.
  Keep at least the uptime check elsewhere.
- **An alert that was never seen to arrive.** Mail filters, an old phone number, a muted channel.
  Trigger each alert once on purpose.
- **Alerts on causes.** CPU, load and "memory used" fire on healthy busy machines, and people
  learn to ignore them. Alert on symptoms; graph the causes.
- **A logrotate entry that silently does nothing.** logrotate ignores an entry file not owned by
  root (`the file owner is wrong`), skips a folder a non-root group can write to unless the entry
  has `su` (`parent directory has insecure permissions`), and fails on a root-owned log in an app
  folder (`Permission denied`). `logrotate -d` shows all three.
- **The journal kept only in memory.** Then `journalctl -b -1` after a crash shows nothing.
  Check for `/var/log/journal` before you need it.
- **Rotating what is already rotated.** Logs that go to the journal or to a container's output
  are limited by journald and by Docker; a logrotate entry for them does nothing useful.

## Done means

- An outside check watches the public URL, and the person has received one test alert from it.
- The alerts are few, each with a reason and an action: disk, memory kills and the certificate
  by the timer or Prometheus, backups by a heartbeat, the site by the outside check.
- `systemctl list-timers` shows the health check, and its last run is in the journal.
- The journal is persistent with a size you chose, containers have a log limit, and
  `logrotate -d` runs clean for every app that writes its own files.

Checked against: systemd 252 (debian:12, almalinux:9) and 255 (ubuntu:24.04), logrotate 3.21.0
and 3.18.0, ShellCheck 0.10.0, curl 7.88.1, 8.5.0 and 7.76.1, nginx 1.30.6, Caddy 2.10.2,
Prometheus 3.5.0 with node_exporter 1.9.1, Docker 29.8 with Compose 5.6, 2026-11-12.
