# My site is down

Read this when someone says the site is down, broken, or throwing errors, on a server they run
(plain systemd or Docker Compose behind nginx or Caddy), with a short section for an app on
Kubernetes. It covers the order to look in, getting the site serving again, and finding the
cause. A site that is up but slow is [performance.md](performance.md); setting up the checks that
would have caught this is [monitoring-and-logs.md](monitoring-and-logs.md).

## The first minute

Reproduce it from outside before you touch anything, because "down" means different things:

```
curl -sS -o /dev/null -w '%{http_code} %{time_total}s\n' https://example.com/
```

A number back (502, 500, 404) means the request reached something; a curl error means it did not.
Run it from your side, not from the server, where localhost skips DNS, the firewall and the
certificate. Then ask the person three things, since the answers often save an hour:

- **What changed?** A deploy, an update, a DNS or firewall edit, a renewed domain, a resized
  server, a card that expired at the provider. "Nothing" usually means "nothing I did".
- **Since when, and for whom?** Everyone, or some visitors (one country, IPv6, mobile)?
- **Is anyone using it right now?** That decides how careful each step has to be.

Open a notes file now (`/root/incident-YYYY-MM-DD.md` on the server, or one on your side) and
write a timestamped line for each thing you check and what it showed. It becomes the account at
the end and stops you checking the same thing twice.

## Stabilise first, then find the cause

The person wants the site back; the cause can wait an hour. If something changed just before it
broke (a deploy, a config edit), rolling it back is usually the fastest way to serve again. A
rollback or a restart is a change to a live service, so say what you will do and wait for the
person's yes. Before you do it, keep what the fix would destroy:

```
mkdir -p /root/incident
journalctl -u app --since "2 hours ago" --no-pager > /root/incident/app.journal
sudo -u deploy docker compose --project-directory /srv/shop logs --timestamps --no-color \
  > /root/incident/compose.log 2>&1        # the app folder and its owner (first-deploy.md)
docker inspect shop-app-1 > /root/incident/app.inspect.json
```

Removing or recreating a container deletes its logs with it, and Compose's `up -d` after a
config change recreates it. To keep the broken container itself, `docker rename` it out of the
way instead of removing it. A restart also hides slow causes (a memory leak starts from zero
again), which is why the evidence comes first. Copy a core file too if the system kept one.

## Look from the outside in

Go layer by layer and stop at the first one that fails: everything behind a failing layer looks
broken too, and fixing it there is wasted work.

### 1. The name: does it resolve, and to what

```
dig +short example.com A
dig +short example.com AAAA
dig +short NS example.com
dig @<one of those nameservers> example.com A
```

Healthy: the server's address, the same from a public resolver and from the domain's own
nameserver. In the full output (without `+short`), `status: NXDOMAIN` means the name does not
exist (a deleted record, an expired domain, the wrong zone); `NOERROR` with no answer means it
exists without a record of that type. An old address means the change has not reached that
resolver yet, or was made at a DNS host that is no longer in charge (compare with the `NS`
answer). An `AAAA` record pointing where nothing listens breaks the site for IPv6 visitors only,
while your test over IPv4 works. On the server, `getent hosts example.com` shows what the box
itself resolves, `/etc/hosts` included. Records and propagation are in [dns-and-email.md](dns-and-email.md).

### 2. The port: does anything answer

```
nc -zv -w 5 example.com 443
```

Three answers, three meanings (`curl -v` prints the same distinction):

- `succeeded`: something listens. Go to the certificate.
- `Connection refused`: the host answered and nothing listens on that port, or a firewall
  rejects. On the server, `ss -tlnp` should show the proxy on `0.0.0.0:443` or `[::]:443`,
  not only on `127.0.0.1`.
- `timed out`: packets are dropped on the way: a host or cloud firewall, the wrong address, or
  a host that is down. A firewall change from yesterday is the usual one; [firewall.md](firewall.md) covers
  reading the rules without locking yourself out.

### 3. The certificate

```
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null \
  | openssl x509 -noout -subject -issuer -enddate
curl -sS -o /dev/null https://example.com/
```

Healthy: the right name, a public issuer, a `notAfter` date in the future, and curl silent.
What the failures print:

- `curl: (60) SSL certificate problem: certificate has expired`: renewal has been failing for
  weeks. Find out why before renewing by hand, in the renewal timer or the proxy's log
  (`systemctl list-timers`, `journalctl -u certbot`, `journalctl -u caddy`). A closed port 80
  or a DNS record moved elsewhere are the usual reasons; renewal itself was not exercised in
  our tests, and [web-and-https.md](web-and-https.md) covers it.
- `self-signed certificate`: the proxy is serving a fallback because it could not get a real
  one, or the request reached a different server than you think.
- `no alternative certificate subject name matches target host name`: the certificate is for
  another name; often a new subdomain that was never added.

### 4. The proxy, and what it says about the upstream

The status code tells you which side of the proxy to look at, and the proxy's error log says
why: `/var/log/nginx/error.log` for Debian's nginx, `journalctl -u caddy` for Caddy,
`logs caddy` in Compose, run as below.

**502 Bad Gateway**: the proxy reached for the upstream (the app behind it) and got nothing
usable. nginx logs one of these, and Caddy says `dial tcp 127.0.0.1:8080: connect: connection
refused`:

```
connect() failed (111: Connection refused) while connecting to upstream, ... upstream: "http://..."
upstream prematurely closed connection while reading response header from upstream
```

Refused: the app is not running, or listens on another port or address. Closed early: the app
crashed during the request. Go to step 5.

**503 Service Unavailable**: the proxy had nothing to send the request to, or chose not to.
Caddy with active health checks answers 503 with `no upstreams available` when every upstream
fails its check. nginx answers 503 by default when `limit_req` rejects a request (`limiting
requests, excess` in the error log). Many apps return 503 themselves in maintenance mode or when
a dependency is down, so check whether the proxy logged an error for it at all.

**504 Gateway Timeout**: the upstream did not answer in time.

```
upstream timed out (110: Connection timed out) while reading response header from upstream
upstream timed out (110: Connection timed out) while connecting to upstream
```

"Reading response header" means the app took the request and is stuck: a slow query, a lock, a
full worker pool, a call to another service that hangs. Look at the database and at what the app
waits on. "While connecting" means the address does not answer at all. This one surprises
people: in our test a stopped app container on a Docker network gave a 504 after nginx's connect
timeout (60 seconds by default), not a 502, because its address simply vanished.

To prove a request reaches this server at all, send a marker and look for it:
`curl -s -o /dev/null 'https://example.com/?probe=7f3a'`, then `grep 7f3a` in the access log.

### 5. The app process: is it up, and what did it log first

```
systemctl status app --no-pager                       # systemd
journalctl -u app --since "1 hour ago" --no-pager | head -50
sudo -u deploy docker compose --project-directory /srv/shop ps -a            # Docker Compose
sudo -u deploy docker compose --project-directory /srv/shop logs --tail 50 --timestamps app
docker inspect shop-app-1 -f \
  '{{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} restarts={{.RestartCount}}'
```

What the failures look like:

- `Restarting (1) Less than a second ago` in Compose, with `restarts=` climbing: a crash loop.
  The cause is in the first lines of a run (`FATAL: DATABASE_URL is not set`), not the last.
- `app.service: Start request repeated too quickly.` systemd stopped retrying after five quick
  failures. Once the cause is fixed, run `systemctl reset-failed app` before starting it.
- `exit=137 oom=true`, or `Failed with result 'oom-kill'` from systemd: killed for memory.
  Go to step 7.

Read the first error after the last start, not the loudest: one refused database connection can
cause a hundred stack traces below it. Search the text for it (`journalctl -u app -b | grep -m1
-iE 'error|fatal|exception'`); the Traps say why `journalctl -p err` misses it.

### 6. The database: can the app reach it

```
pg_isready -h 127.0.0.1 -p 5432
```

`accepting connections` (exit 0) is healthy; `no response` (exit 2) means it is down, on another
port or address, or firewalled. For MySQL or MariaDB, `mysqladmin ping` does the same job (not
run in our tests). Check the host and port the app really uses (its `DATABASE_URL`, read without
printing the password). A database that answers but refuses the app is often out of connections
or out of disk; [databases.md](databases.md) goes further.

### 7. The host itself, when the app dies for no reason of its own

**Disk full.** Writes fail with `No space left on device`.

```
df -h
df -i
du -xh -d1 / 2>/dev/null | sort -h | tail
```

`df -i` matters: a filesystem out of inodes (millions of small files in a session or cache
folder) gives the same error while `df -h` shows it nearly empty. If `df` says full and `du`
finds nothing, a process holds a deleted file open, and the space comes back only when it lets go:

```
find /proc/[0-9]*/fd -lname '*(deleted)' -printf '%p -> %l\n' 2>/dev/null
```

Restart that process, or empty the file through its descriptor (`: > /proc/<pid>/fd/<n>`).
Freeing space is the fix, but a deletion cannot be undone: compress or move old logs first, use
`journalctl --vacuum-size=500M` for the journal and `docker system df` to see what Docker holds,
and ask before removing images, volumes or anything you did not create.

**Out of memory.** The kernel's OOM killer (the part of Linux that kills a process when memory
runs out) logs every kill:

```
journalctl -k -b --no-pager | grep -i -E 'out of memory|killed process'
journalctl -k -b -1 --no-pager | grep -i 'killed process'    # the boot before, if it rebooted
```

`Memory cgroup out of memory: Killed process 71812 (python3)` means a limit on that service or
container was hit; `Out of memory: Killed process` without "cgroup" means the whole machine ran
out. In `free -h`, read the `available` column, not `free`.

**CPU steal.** On a virtual machine, the `st` column of `vmstat 1 5` (and `st` in `top`) is time
your CPUs waited for the host. A few percent is normal; a steady double figure means the host is
busy or your plan's burst allowance ran out, and nothing you change inside fixes it. (A container
cannot produce steal, so this reading rule is from experience, not from our tests.)

**A port already taken.** The proxy does not start after a reboot or an update:
`nginx: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)`. Then
`ss -ltnp 'sport = :80'` names the process holding it: often a second web server pulled in by a
package, or a container publishing the same port.

## Ask the machine what changed

The person may not know, so look:

```
grep -h -E ' (install|upgrade) ' /var/log/dpkg.log | tail -20      # Debian, Ubuntu
dnf history list | head                                              # Alma, Rocky
find /etc -xdev -type f -newermt '2 days ago'
journalctl --list-boots --no-pager | tail -3                         # an unexpected reboot
docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.CreatedAt}}\t{{.Status}}'
git -C /srv/app log --oneline -5
```

Outside the server, look at the provider's firewall and the DNS host's change history, if they
keep one.

## After three fixes that did not work

Stop changing things. Three failed fixes usually mean one of your assumptions is wrong, and each
new change makes the picture harder to read. Write the assumptions down ("the request reaches
this server", "this is the config nginx loaded", "the app reads this env file") and prove the
one you are surest of from scratch: the marker in the access log, `nginx -T` for the loaded
configuration, `tr '\0' '\n' < /proc/<pid>/environ | cut -d= -f1` for the names of the variables
the process really has (values stay off the screen). Undo the changes that did not help,
unless they fixed something else, so the next person is not debugging your experiments.

## The account afterwards

Give the person five lines, in the conversation and in the notes file:

```
What broke: from 09:12 to 09:47 UTC visitors got 502 on every page.
Why: the 09:10 deploy added a setting the app needs; the server's env file did not have it.
What fixed it: rolled back at 09:31, then added the setting and redeployed at 09:45.
What would have caught it earlier: a start check in the deploy that fails when the app exits.
Still open: the uptime alert took 20 minutes; it now checks every 5 minutes.
```

Plain words, no blame, and say what is still unknown if the cause was not found.

## On Kubernetes

The same order, outside in, with other commands; [kubernetes-debugging.md](kubernetes-debugging.md) has the detail.

```
kubectl get ingress -A                                   # the address the name should point at
kubectl get certificate -A                               # if cert-manager issues them
kubectl get endpointslices -l kubernetes.io/service-name=web \
  -o jsonpath='{range .items[*].endpoints[*]}{.addresses[0]} ready={.conditions.ready}{"\n"}{end}'
kubectl get pods -l app=web
kubectl describe pod <pod>                               # Last State, Reason, Exit Code, Events
kubectl logs <pod> --previous                            # the run that crashed
kubectl get events --sort-by=.lastTimestamp | tail -20
```

In our test cluster a crashing pod showed `Error`, a climbing restart count and a `Back-off
restarting failed container` event; `--previous` sometimes could not retrieve the logs, and plain
`kubectl logs <pod>` between restarts showed the failed run. A pod over its memory limit showed
`OOMKilled` with exit code 137. The EndpointSlice still listed the crashing pod with
`ready=false`, so "the Service has an endpoint" does not mean anything can serve, and a request
to that Service from inside the cluster was refused. What the ingress controller answers visitors
in that state is in its own log (we ran no ingress controller in the test).

## Traps

- **Testing from the server.** `curl localhost` succeeds while the world gets a timeout,
  because it skips DNS, the firewall and the certificate. Test from outside first.
- **`journalctl -p err` to find app errors.** A service's stderr is stored at priority 6 (info),
  the same as its stdout, unless the app writes syslog priorities; we checked, and the filter
  hid exactly the line we wanted. Search the text. Python under systemd also buffers stdout and
  not stderr, so their lines can land out of order; `PYTHONUNBUFFERED=1` fixes that.
- **nginx naming a container that is not running.** With `proxy_pass http://app:8080;`, nginx
  refuses to start (`host not found in upstream "app"`) until that container exists, so after a
  reboot the proxy can stay down. With `resolver 127.0.0.11 valid=10s;` (Docker's built-in DNS)
  and `set $upstream http://app:8080; proxy_pass $upstream;`, nginx starts anyway, answers 502
  until the app is back, and looks the name up again every ten seconds.
- **Restarting the whole server first.** It may clear the symptom and erase the evidence: the
  memory state, and the journal too if it is not kept on disk. Collect, then restart, with a yes.

## Done means

- The site answers from outside with the expected status and a valid certificate, checked the
  way [proving-it-works.md](proving-it-works.md) describes.
- The cause is named, or stated plainly as not found, with what was ruled out.
- What a fix would have destroyed was kept until the cause was known.
- The person has the five-line account and a follow-up for the check that would have caught it.

Checked against: nginx 1.28.3 and 1.30.6, Caddy 2.10.2, curl 7.88.1, OpenSSL 3.0, dig 9.18,
pg_isready 17.7, systemd 252 (debian:12), Docker 29.8 with Compose 5.6, kind 0.33 with Kubernetes
1.37, 2026-11-12.
