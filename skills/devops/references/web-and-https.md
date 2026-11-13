# Web and HTTPS

Read this when an app on a server needs a reverse proxy in front of it and HTTPS that renews by
itself: choosing Caddy or nginx, what has to be true before a certificate can be issued,
renewals, what the app needs from the proxy, HSTS, several apps on one server, and the case with
no domain yet. The DNS records themselves and mail are in [dns-and-email.md](dns-and-email.md);
opening ports is in [firewall.md](firewall.md); the final outside check and the hand-over are in
[proving-it-works.md](proving-it-works.md). On Kubernetes, an ingress controller and
cert-manager do this job ([kubernetes.md](kubernetes.md)).

## Choose Caddy or nginx

Pick **Caddy** on a fresh server, or when nobody already runs nginx there. It gets and renews
certificates on its own, redirects HTTP to HTTPS, sets the forwarded headers and passes
WebSockets without being told, so the whole config for one app is a dozen lines and there is no
renewal job to break. Template: [Caddyfile](../templates/Caddyfile).

Pick **nginx with certbot** when nginx is already serving and the person or their team knows its
config, or when you need what nginx does better: request rate limits (`limit_req`), caching,
complicated rewrites, or a config other tools already generate. The cost is moving parts: the
certificate, the renewal timer and the reload hook are three separate things that each have to
work. Templates: [nginx-site.conf](../templates/nginx-site.conf) and
[certbot-deploy-hook.sh](../templates/certbot-deploy-hook.sh).

Packaged versions matter here. Debian 12 and 13, Ubuntu 24.04 and EPEL all ship Caddy 2.6,
released in 2022 and 2023; install Caddy from its own signed repository instead:

```
apt install -y curl gpg
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key \
  | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
  > /etc/apt/sources.list.d/caddy-stable.list
apt update && apt install -y caddy && caddy version
```

On Alma or Rocky: `dnf install -y 'dnf-command(copr)' && dnf copr enable -y @caddy/caddy &&
dnf install -y caddy`. The package runs Caddy as the `caddy` user from `/etc/caddy/Caddyfile`
and keeps certificates under `/var/lib/caddy/.local/share/caddy`.

The packaged certbot (Debian 12: 2.1, Ubuntu 24.04: 2.9, Debian 13: 4.0, EPEL 9: 3.1) is fine
for certificates on names. Certificates for a bare IP address need certbot 5.3 or later, which
in practice means the snap the certbot project publishes.

## Before asking for a certificate

The certificate authority (CA) checks that you control the name by fetching a file from it over
the internet. Each failed check counts against a rate limit, so check these first, in order:

1. **The name points here, on A and AAAA.** Ask the domain's own nameservers, not a cache:
   `dig +short NS example.com`, then `dig +short A app.example.com @<one of them>` and the same
   for `AAAA`. Compare with the server's addresses (`ip -br addr`; on providers that NAT the
   public IPv4, the provider's panel). An AAAA record that points anywhere else is the most
   common silent failure: the CA tries IPv6 first and falls back to IPv4 only when the IPv6
   connection times out, not when something else answers there. Make the proxy listen on IPv6
   too, or delete the AAAA record.
2. **Ports 80 and 443 reach this server from outside.** On the server,
   `ss -tlnp '( sport = :80 or sport = :443 )'` shows something listening; from your own
   machine, `curl -sv http://app.example.com/` shows the connection reaching it. A provider
   firewall or security group drops traffic before the server sees it, so check from outside.
   The CA validates from several networks at once, so a country block or an address allowlist on
   port 80 makes issuance fail even when it works from your desk.
3. **No CAA record forbids the CA.** `dig +short CAA example.com`: empty means any CA may issue;
   otherwise the CA you use has to be listed (see [dns-and-email.md](dns-and-email.md)).

Port 80 stays open for good. HTTP-01 renewals arrive on it, so closing it "because the site is
HTTPS now" breaks the next renewal, weeks later, when nobody connects the two.

## Test against the staging CA first

Let's Encrypt allows 5 certificates for the same set of names per 7 days and 5 failed
validations per name per hour, and grants no exceptions to either. A loop of failed attempts or
a container that requests a new certificate on every start runs into them and leaves the site
without HTTPS for days. The staging CA has much higher limits and issues certificates browsers
do not trust, which is exactly what you want while testing.

- Caddy: uncomment the `acme_ca` line in the template's global block, reload, watch
  `journalctl -u caddy -f` until it logs that the certificate was obtained, then comment it out
  and reload. Caddy files certificates per CA, so it then requests a production one.
- certbot: add `--dry-run` to `certbot certonly`. It runs the whole validation against staging
  and saves nothing, so the real run afterwards starts clean.

## Put Caddy in front of the app

1. Fill the template and put it at `/etc/caddy/Caddyfile`. Point `<UPSTREAM>` at the app on
   loopback (`127.0.0.1:3000`) so only Caddy reaches it.
2. `caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile` prints
   `Valid configuration`. `caddy fmt --overwrite /etc/caddy/Caddyfile` fixes the formatting
   warning if it shows one; without the path it formats `./Caddyfile` in the current folder.
3. `systemctl reload caddy`, then `journalctl -u caddy --since -5min` shows the certificate
   being obtained, or the exact reason it was not.
4. Check from outside (below).

In Compose ([templates/compose.yaml](../templates/compose.yaml)), Caddy publishes 80, 443 and
443/udp and reaches the app by service name. Its Caddyfile sits in `caddy/` beside the Compose
file, with the folder mounted on `/etc/caddy`, since `sed -i` or an editor replaces the file and a
single-file mount keeps the old one (tested). Apply an edit as the folder's owner, from any folder
([first-deploy.md](first-deploy.md)): `sudo -u deploy docker compose --project-directory /srv/shop
exec caddy caddy validate --config /etc/caddy/Caddyfile`, then the same with `reload`. In the test
no request failed during a reload, while `up -d --force-recreate caddy` failed 60 of 400, and an
inline Caddyfile (`configs:` `content:`) was not reapplied by `up -d` at all. The `/data` volume
holds certificates and the CA account; without it each new container asks again and hits the limit.

## Put nginx and certbot in front of the app

Certificates come from certbot's webroot method, so certbot only writes files and never edits
the nginx config, which stays the way it is in version control. (`certbot --nginx` edits the
server blocks for you; fine for a one-off, but the file then differs from the template.)

1. Put the template's `map` and port 80 `server` in place without the port 443 `server`: the
   certificate files it names do not exist yet, and `nginx -t` refuses a missing file
   (`cannot load certificate ... No such file or directory`). Then
   `mkdir -p /var/www/letsencrypt && nginx -t && systemctl reload nginx`.
2. Prove the challenge path from outside:
   `mkdir -p /var/www/letsencrypt/.well-known/acme-challenge && echo ok >
   /var/www/letsencrypt/.well-known/acme-challenge/probe`, then from your machine
   `curl -s http://app.example.com/.well-known/acme-challenge/probe` prints `ok`. Delete the file.
3. `certbot certonly --webroot -w /var/www/letsencrypt -d app.example.com -m <ACME_EMAIL>
   --agree-tos --dry-run`, and once that succeeds, the same without `--dry-run`.
4. Add the port 443 `server`, then `nginx -t && systemctl reload nginx`.
5. Install the reload hook: `install -D -m 0755 certbot-deploy-hook.sh
   /etc/letsencrypt/renewal-hooks/deploy/reload-nginx`.

## A PHP app behind PHP-FPM

Laravel, WordPress and Symfony run under PHP-FPM, which nginx talks to over a socket instead of
proxying HTTP. Install the distribution's `php-fpm` and the extensions the app lists, then use
[templates/nginx-php.conf](../templates/nginx-php.conf) inside the port 443 server of
`nginx-site.conf`, in place of its proxy `location`. Point `root` at the public folder only
(Laravel's `public/`), so `.env` and the code are never files the web can ask for, and run
`nginx -t`. From outside, a page answers 200, a made-up `/x.php` 404 and `/.env` 403. Behind a
`current` symlink, `$realpath_root` serves the new release as soon as the link moves.

## Renewal, and how to prove it will happen

Caddy renews by itself and needs nothing scheduled; its log shows each renewal. For certbot, the
Debian and Ubuntu packages install `certbot.timer`, which runs `certbot renew` twice a day with a
random delay; the snap installs its own timer. `certbot renew` renews nothing until a
certificate is due (since certbot 4.0, when a third of its lifetime is left; older versions use
30 days), so running it often is harmless. Prove three things:

- The timer is active: `systemctl list-timers | grep certbot` shows a next run.
- Renewal itself works: `certbot renew --dry-run --run-deploy-hooks`. Without
  `--run-deploy-hooks` a dry run skips deploy hooks, so it says nothing about the reload. The
  certbot 2.1 in Debian 12 has no such flag; run the hook by hand once instead.
- The new certificate is served: nginx reads certificate files only when it starts or reloads,
  so without the hook it serves the old certificate until it expires, while certbot reports a
  successful renewal. After a renewal, compare `certbot certificates` with what `openssl
  s_client` shows from outside.

Lifetimes are getting shorter. Let's Encrypt's default is 90 days today, planned to drop to 64
days in February 2027 and 45 days in February 2028, and its opt-in `tlsserver` profile already
issues 45-day certificates. A cron job that forces a renewal every 60 days, or anything else
that assumes a fixed lifetime, will break; the timer and Caddy adapt on their own.

## What the app behind the proxy needs

- **The real client address.** The app sees the proxy's address and has to read the client's
  from a header, trusting that header only from the proxy. Caddy replaces any `X-Forwarded-For`
  the client sends, and the nginx template overwrites it with `$remote_addr`. The common
  `$proxy_add_x_forwarded_for` appends instead: a client that sends
  `X-Forwarded-For: 192.0.2.66` reaches the app as `192.0.2.66, <real address>`, and an app that
  reads the first entry logs and rate-limits the forged one. Tell the framework to trust one
  proxy hop (Express `trust proxy`, gunicorn `--forwarded-allow-ips`, Django
  `SECURE_PROXY_SSL_HEADER` for the scheme).
- **The scheme.** Without `X-Forwarded-Proto` trusted, an app that forces HTTPS sees plain HTTP
  from the proxy and redirects forever, or builds `http://` links and drops secure cookies.
- **A load balancer or CDN in front of the proxy** makes it the client. In nginx:
  `set_real_ip_from <its address range>; real_ip_header X-Forwarded-For; real_ip_recursive on;`
  in Caddy, the `trusted_proxies` server option. Trust only that range, never `0.0.0.0/0`.
- **WebSockets.** Caddy passes them as is. nginx needs the `Upgrade` and `Connection` headers
  from the template, and closes a socket that stays silent for `proxy_read_timeout` (60 s): a
  chat that drops every minute is this. Raise it in that location, or have the app send pings.
- **Upload size.** nginx refuses bodies over 1 MB by default with `413`; Caddy sets no limit.
  Set it to what the app accepts, in both places.
- **Timeouts.** A request that runs past `proxy_read_timeout` ends in `504` while the app keeps
  working. Raise it for the one slow location, or better, move the slow work to a background
  job and return at once.
- **A health endpoint,** such as `/healthz`: cheap, no login, `200` when the app can serve
  (database reachable with a short timeout). Uptime checks, Compose health checks and deploy
  scripts use it. With one upstream the proxy does not need it; Caddy's `lb_try_duration` in
  the template holds requests for a few seconds while the app restarts instead of answering 502.

## Redirects and HSTS

Caddy redirects HTTP to HTTPS with a `308` on its own; the nginx template sends a `301` and
keeps the ACME challenge path on plain HTTP. Pick one name as canonical (`example.com` or
`www.example.com`) and redirect the other; the Caddyfile template shows how.

HSTS (`Strict-Transport-Security`) tells browsers to use only HTTPS for the name for `max-age`
seconds, and to refuse a click-through on any certificate error. That is the lock-in: if HTTPS
breaks, visitors who saw the header cannot reach the site at all until it is fixed or the time
runs out. `includeSubDomains` extends this to every subdomain, including internal ones that only
speak HTTP. Ramp it: 300 seconds, then a week, then a year once renewals have worked. Submitting
the name to the browsers' preload list is close to permanent (removal takes months) and needs
the person's yes.

## When there is no domain yet

HTTPS does not have to wait for a domain, though people assume it does; say so in your first
answer. A wildcard DNS service maps a name to the address written in it, for example
`203-0-113-10.sslip.io` to `203.0.113.10` (nip.io works the same way), and that name gets an
ordinary certificate from Caddy or certbot with nothing to set up at a registrar; a trial got a
Let's Encrypt certificate this way through Caddy. Two catches: the service's whole domain counts as
one for the CA's rate limits (neither is on the Public Suffix List), so issuance depends on
everyone else's use; and the name resolves only while that service is up. Move to a real domain
before launch.

A certificate for the bare IP address comes only from a public CA. Let's Encrypt has issued
them since January 2026, with conditions: they last about six days (the `shortlived` profile),
only HTTP-01 or TLS-ALPN-01 can prove control, and the client has to ask for that profile. With
certbot 5.3 or later: `certbot certonly --standalone --ip-address 203.0.113.10
--preferred-profile shortlived` (webroot from 5.4). A six-day certificate leaves no slack, so
the renewal timer has to be healthy. Caddy uses its own internal CA for IP addresses, which
browsers do not trust. This path was not tried against the real CA while writing this.

## Several apps on one server

One proxy owns ports 80 and 443; each app listens on its own loopback port or Compose network,
and gets its own site block (Caddy) or file (nginx). Separate certificates per name keep one
failing name from blocking the others; both setups do that by default.

nginx traps with several sites:

- The WebSocket `map` belongs in one file. nginx accepts a second `map` for the same variable
  without a warning and the last one loaded applies to every site.
- A request for a name nginx has no server for, or for the bare IP, goes to the default server,
  which is the first one loaded. Your app then answers for any name pointed at the server and
  for every scanner. Add a catch-all that closes such connections:

```
server {
    listen 80 default_server;
    listen [::]:80 default_server;
    listen 443 ssl default_server;
    listen [::]:443 ssl default_server;
    ssl_reject_handshake on;
    return 444;
}
```

On Debian and Ubuntu, `/etc/nginx/sites-enabled/default` already claims `default_server` on
port 80, and `nginx -t` fails with `a duplicate default server`; remove that link first.

## Test the config before every reload

`nginx -t && systemctl reload nginx`, and `caddy validate ... && systemctl reload caddy`. A reload
with a broken config leaves the old one serving in both (tried: nginx exits 1 and keeps its
workers; Caddy logs the error and keeps the old config). The danger is the next restart or reboot,
which stops the old process and cannot start a new one, so the site goes down at a time nobody is
watching. A `systemctl restart` with a broken config takes it down at once. When the check or the
reload fails, fix the file or put the old one back.

## Check from outside

From your machine, not the server:

```
curl -sI http://app.example.com/ | head -3          # 301 or 308 to https://
curl -sI https://app.example.com/ | head -1         # 200, with no -k
curl -4 -sI https://app.example.com/ | head -1      # once over IPv4
curl -6 -sI https://app.example.com/ | head -1      # once over IPv6, when there is an AAAA
openssl s_client -connect app.example.com:443 -servername app.example.com </dev/null \
  2>/dev/null | openssl x509 -noout -subject -issuer -dates -ext subjectAltName
curl -s -o /dev/null -w '%{http_code}\n' --max-time 3 --http1.1 -H 'Connection: Upgrade' \
  -H 'Upgrade: websocket' -H 'Sec-WebSocket-Version: 13' \
  -H "Sec-WebSocket-Key: $(openssl rand -base64 16)" https://app.example.com/<WS_PATH>
```

The last one prints `101` when WebSockets pass through, then exits 28 at `--max-time` (expected).
An issuer starting `(STAGING)` means the staging switch is still on. To test a new server before
DNS points at it, add `--resolve app.example.com:443:203.0.113.10` to curl. The rest of the
look from outside, DNS and the closed ports, is in [proving-it-works.md](proving-it-works.md).

## Watch certificate expiry

Let's Encrypt stopped sending expiry e-mails in June 2025, so nobody warns the person unless
you set it up. Point an uptime monitor that reads certificates at the site, or run a check from
another machine that fails when fewer than 14 days are left:

```
echo | openssl s_client -connect app.example.com:443 -servername app.example.com 2>/dev/null \
  | openssl x509 -noout -checkend $((14*86400))
```

It prints `Certificate will expire` and exits 1 inside that window. With 90-day certificates
renewed at 30 days left, 14 days means two weeks of failed renewals; shorten it as lifetimes
shrink.

## Traps

- **`ssl_stapling on` from older guides.** Let's Encrypt stopped putting an OCSP address in
  certificates in 2025 and has shut its OCSP service, so nginx logs `"ssl_stapling" ignored, no
  OCSP responder URL in the certificate` on every start. Remove the two stapling lines.
- **Assuming `http2 on;` works.** It needs nginx 1.25.1; Debian 12 (1.22) and Ubuntu 24.04
  (1.24) reject it as an unknown directive. The template uses `listen 443 ssl http2`, which
  works everywhere and only warns on newer versions.
- **Restarting to "pick up" a renewed certificate in Caddy.** Not needed, and a restart in a
  container without the `/data` volume throws the certificate away.
- **A redirect loop after adding the proxy.** The app is not trusting `X-Forwarded-Proto`.
- **The certificate works on the name but not on `www`.** Each name needs its own DNS record
  and has to be on a certificate; add it and reissue.

## Done means

- `http://` redirects to `https://`, and `https://` answers `200` from outside over IPv4, and
  over IPv6 when the name has an AAAA record, with a trusted certificate for every name served.
- A renewal was proven: Caddy's log shows certificate maintenance running, or
  `certbot renew --dry-run --run-deploy-hooks` succeeded and the timer has a next run.
- The app logs real client addresses, WebSockets return `101` if the app uses them, and an
  upload of the largest expected size goes through.
- Something outside the server warns before the certificate expires.
- The config passes `nginx -t` or `caddy validate`, and is saved in the repository.

Checked against: Caddy 2.11.9 (caddy:2 image; 2.11.7 from the COPR on almalinux:9), nginx 1.30.6
(nginx:stable), 1.24 (nginx:1.24) and 1.22.1 (Debian 12 package), certbot 5.10.0
(certbot/certbot image), 4.0.0 (Debian 13), 2.9.0 (Ubuntu 24.04) and 2.1.0 (Debian 12),
OpenSSL 3.5, with a local CA and an echo upstream only, 2026-11-11; the PHP snippet with nginx
1.22.1 and PHP-FPM 8.2.35 on debian:12; the Compose reload as a non-root admin with Compose 5.7.0
in docker:29-dind (29.9.3), 2026-11-12.
