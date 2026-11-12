# A slow server or a slow app

Read this when a site or an API is up but slow, a server feels sluggish, or someone asks whether
they need a bigger machine. It covers finding where the time goes, reading the handful of
commands that name the limiting resource, slow endpoints and queries, quick wins at the proxy,
and deciding between tuning and resizing. A site that is down or returning errors is
[outage.md](outage.md); keeping graphs over time is
[monitoring-and-logs.md](monitoring-and-logs.md).

## Where does the time go

Measure one slow request from outside before guessing, split into its phases:

```
curl -s -o /dev/null https://example.com/report -w 'dns %{time_namelookup} connect %{time_connect}
  tls %{time_appconnect} first byte %{time_starttransfer} total %{time_total}\n'
```

Each number is seconds since the start, so read the gaps. A large `dns` is the resolver. A large
gap from `dns` to `connect` is the network or the distance. `tls` is the handshake. The gap from
`tls` (or `connect` for plain HTTP) to `first byte` is the server thinking: proxy, app and
database together, and usually where the time is. A large gap from `first byte` to `total` is
the transfer: a big page, no compression, a slow link. In our test a slow endpoint read
`connect 0.000163 ... first byte 0.807678 total 0.807818`: all of it on the server.

Then ask whether everything is slow or only some pages. Only some pages points at the app or the
database for those pages. Everything slow, static files included, points at the host or the
network. A static file served by the proxy is a good control: if it is fast, the host is fine.

## Which resource is the limit

Run these on the server while it is slow. Each takes seconds and none changes anything.

```
nproc; uptime
vmstat 1 5
free -h
cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io
top -b -n 1 -o %CPU | head -15
iostat -xz 1 3            # from the sysstat package
```

How to read them:

- **Load against cores.** The three load numbers are the average count of tasks running or
  waiting over 1, 5 and 15 minutes. On Linux that includes tasks waiting for the disk, so a load
  of 8 on 4 cores with idle CPU means I/O, not CPU. Compare with `nproc`.
- **`vmstat`**, ignoring its first line (an average since boot). `r` above the core count:
  CPU-bound. `b` above zero for several seconds: tasks blocked on I/O. `si` and `so` above zero
  for several seconds: the machine is swapping, and that alone can make everything slow. `wa`
  is CPU time spent waiting for I/O; `st` is steal, time your virtual CPUs waited for the host.
- **Memory.** In `free -h`, `available` is what new work can use; `buff/cache` is mostly file
  cache the kernel gives back on demand. A box with little `free` and plenty `available` is
  healthy. In our test, reading a 300 MB file grew the cache while `available` stayed the same.
- **Pressure.** `/proc/pressure/*` (PSI, pressure stall information) gives the share of time
  tasks were stalled on that resource: `some avg10=17.44` means at least one task waited 17
  percent of the last ten seconds. `full` above zero on memory means everything stalled at once,
  real memory trouble. It is the most direct answer to "is this resource the bottleneck". It was
  there on our test kernel; RHEL-family kernels may ship it switched off until booted with
  `psi=1` (we could not check a RHEL kernel in a container).
- **Disk.** In `iostat -xz`, `%util` near 100 with `r_await` or `w_await` in the tens of
  milliseconds means the disk is saturated. On a virtual machine with network storage that is
  often the plan's I/O limit rather than the hardware.
- **Steal.** A steady double-figure `st` means the host is short of CPU, or the plan's burst
  allowance ran out. Nothing inside the machine fixes it; a different plan or host does.

**Inside a container the usual commands mislead.** With `--cpus=2` on an 8-core host, `nproc`
said 8, `free` showed the host's memory, and the load average was the host's. The container's
own limits and how often it hit them are in its cgroup:

```
cat /sys/fs/cgroup/cpu.max             # "200000 100000": two CPUs' worth per period
grep throttled /sys/fs/cgroup/cpu.stat # nr_throttled 30 of nr_periods 34: starved by its limit
cat /sys/fs/cgroup/memory.max /sys/fs/cgroup/memory.current
docker stats --no-stream
```

A container throttled most periods is limited by its own `cpus` setting, not by the machine.

Then find who is using it: `ps -eo pid,user,comm,%cpu,%mem,rss --sort=-%cpu | head`, or
`pidstat 1 5` (sysstat) for per-process CPU and I/O over a few seconds.

## Slow endpoints

Make the proxy log how long each request took. In nginx:

```
log_format timed '$remote_addr [$time_local] "$request" $status $body_bytes_sent '
                 'rt=$request_time urt=$upstream_response_time';
access_log /var/log/nginx/access.log timed;
```

`rt` is the whole request as nginx saw it, `urt` the part spent waiting for the app. Close
together: the app is slow. `rt` much larger: the client is slow to send or receive. Then average
and worst case per path, from that format:

```
awk '{split($5,u,"?"); for(i=1;i<=NF;i++) if($i ~ /^rt=/){t=substr($i,4); n[u[1]]++;
  s[u[1]]+=t; if(t>m[u[1]]) m[u[1]]=t}} END{for(p in n) printf "%-30s n=%-5d avg=%.3f max=%.3f\n",
  p, n[p], s[p]/n[p], m[p]}' /var/log/nginx/access.log | sort -t= -k3 -rn | head
```

In our test it printed `/report  n=3  avg=0.801 max=0.801` above `/  n=63 avg=0.038`. Caddy's
JSON access log (with a `log` directive) has a `duration` in seconds:
`jq -r 'select(.duration > 0.5) | [.duration, .request.uri] | @tsv'`. Look at the worst cases
and not only the average: a page that takes 40 ms half the time and a second one time in a
hundred feels slow, and an average hides it. Inside the app, the language's own profiler or
tracing shows which call inside the slow endpoint takes the time.

## Slow queries

Most slow endpoints are a slow query or many small ones. Log every statement over a threshold
(`log_min_duration_statement`, a reload applies it; the log then shows
`LOG:  duration: 310.753 ms  statement: SELECT ...`) and rank queries by total time with
`pg_stat_statements`, which finds the many-small-queries case too (a high `calls` count). The
settings, the query that ranks them, `EXPLAIN (ANALYZE, BUFFERS)` and the MySQL and MariaDB
slow log are in [databases.md](databases.md), "Find a slow query". Turning on
`pg_stat_statements` needs a database restart, a short outage on production: ask first.

## Quick wins at the proxy

Cheap, safe, and checked with `nginx -t` or `caddy validate`, then a `curl -I`:

- **Compression.** In nginx, `gzip on;` alone compresses only `text/html`. In our test a
  JavaScript file came back uncompressed until `gzip_types` listed it:
  `gzip_types text/css application/javascript application/json image/svg+xml;`. Debian's
  `nginx.conf` has `gzip on;` with the types line commented out; the official image has gzip
  off. Caddy needs `encode zstd gzip` in the site, and answered our request with zstd.
- **Long caching for fingerprinted files.** Files whose name changes with their content
  (`app.3f9c2a.js`) can be cached for a year:
  `add_header Cache-Control "public, max-age=31536000, immutable";` in nginx, or
  `header /assets/* Cache-Control "public, max-age=31536000, immutable"` in Caddy. Not for HTML
  or files that keep their name, or visitors keep the old version.
- **Static files from the proxy,** with `root` or `file_server`, instead of through the app.
- **Keep-alive to the app.** nginx opens a new connection to the upstream for every request
  unless the upstream block has `keepalive` and the location speaks HTTP/1.1 without a
  `Connection: close` header:

  ```
  upstream app { server 127.0.0.1:8080; keepalive 16; }
  location / { proxy_pass http://app; proxy_http_version 1.1; proxy_set_header Connection ""; }
  ```

  In our test 68 requests reached the app over 8 connections, one per nginx worker. Caddy keeps
  upstream connections open by default (from its documentation; not measured here).
- **HTTP/2 to visitors:** `http2 on;` in the nginx server block (nginx 1.25.1 and later); Caddy
  does it by default with HTTPS.

## Tune, or buy a bigger machine

Say this plainly to the person. A bigger machine is the right answer when one resource is
saturated by honest work (CPU busy serving real traffic, memory full of the working set, disk
busy with real reads), and when a day of tuning costs more than months of the larger plan. It is
the wrong answer when one query lacks an index, a page makes 300 queries, or nothing is cached:
a machine twice the size buys a little time and the problem returns when traffic doubles. Steal
time is fixed only by a different plan or host. Swapping is fixed by more memory or fewer,
smaller workers.

Change one thing at a time and measure again under the same load, or you cannot tell what
helped. To produce that load, `ab -n 200 -c 10 https://example.com/` (apache2-utils) or a
similar tool prints percentiles; ours read `50% 41`, `95% 50`, `99% 1064` (milliseconds),
which is the tail an average hides. Load-test only the person's own servers, outside busy
hours, with their yes, since it can slow or stop the live site. A resize usually means a reboot,
so it also needs the person's yes and a moment they choose. When one machine is no longer enough
even well tuned, [scaling-up.md](scaling-up.md) covers the next step.

## Traps

- **Averages.** They hide the slow tail people complain about. Look at the 95th and 99th
  percentile, or at least the maximum per path.
- **"Memory is full".** `used` plus `buff/cache` near total is normal; act on low `available`,
  swap activity or OOM kills.
- **The first line of `vmstat`.** It is the average since boot; read the lines after it.
- **Numbers from inside a container.** `nproc`, `free` and load describe the host. Read the
  cgroup files.
- **Kernel tuning from a blog post.** Changing `sysctl` values without a measured bottleneck
  rarely helps and is hard to reason about later. Measure first.
- **Testing from the server itself.** It skips the network and TLS that visitors pay for.

## Done means

- The slow part is named with a number: a phase of the request, a resource, an endpoint or a
  query, measured before and after.
- One change at a time, each measured under the same load, and the person told what each did.
- A recommendation on tuning versus resizing, with the reason, and the person's decision on it.

Checked against: curl 8.14.1, nginx 1.30.6, Caddy 2.10.2, PostgreSQL 17.7, procps and sysstat on
debian:12, ab 2.3, Docker 29.8 on an 8-core Linux 7.0 virtual machine, 2026-11-12.
