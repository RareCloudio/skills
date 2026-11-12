# Firewall

Read this when you set up or change the firewall of a server that serves the web: ufw on Debian
and Ubuntu, firewalld on the RHEL family (Alma, Rocky), plain nftables, IPv6, the provider's
cloud firewall next to the host's, and the trap that catches most Docker hosts (published
container ports bypass ufw and firewalld). How to change it without locking anyone out (second
session, timed revert) is in [preflight-and-safety.md](preflight-and-safety.md), SSH itself in
[server-hardening.md](server-hardening.md), and the outside check of the finished site in
[proving-it-works.md](proving-it-works.md).

## Two layers: the provider's firewall and the host's

A cloud firewall (security group) filters before traffic reaches the server. It keeps working
when the host's rules are wrong, when Docker writes around them, or when someone runs
`ufw disable`. The host firewall travels with the server, works where the provider has no
firewall, and also filters traffic on a private network between servers, which a provider's
firewall often does not see.

Use both, with the same intent: SSH (from the admin's fixed address if there is one), 80 and
443, nothing else. When a port times out in a test, either layer can be the cause, so check
both. The provider's firewall lives in the person's account: change it through their panel or
an API you were given, with their yes when the server is live.

Use one tool per host. ufw and firewalld both write nftables rules underneath (ufw through
`iptables-nft`: `iptables -V` prints `nf_tables` on Debian 12 and Ubuntu 24.04), and two
managers overwrite each other.

## ufw for a web server (Debian, Ubuntu)

Arm the timed revert and keep a second session open first: enabling a firewall that lacks the
SSH rule leaves the session you are in working (established connections are allowed) and
times out every new one, which is what happened in the test. On a live server this step needs
the person's yes.

```
sudo ufw status verbose                 # "Status: inactive" on a fresh install
sudo ufw default deny incoming
sudo ufw default allow outgoing
sudo ufw allow OpenSSH                  # or the port sshd really uses: sudo ufw allow 2222/tcp
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw --force enable                 # without --force it asks for y/n
sudo ufw status verbose
```

Then open a new SSH connection from your side, and cancel the revert. If the web server is set
up to offer HTTP/3, also allow `443/udp`; without it, browsers fall back to TCP.

Variations:

- **SSH from known addresses only,** when the person has a fixed one:
  `sudo ufw allow from 198.51.100.7 to any port 22 proto tcp`, then delete the open rule
  (`sudo ufw status numbered`, `sudo ufw delete <n>`). With a changing home address, rely on
  keys and fail2ban instead; an allowlist that goes stale is a lockout.
- **`ufw limit OpenSSH`** refuses a sixth connection from one address within 30 seconds
  (tested: five logins went through, the next three were refused). An agent that opens one SSH
  connection per command hits it. Use `allow` together with fail2ban, or reuse one connection
  (`ControlMaster`, see [preflight-and-safety.md](preflight-and-safety.md)).

**IPv6.** `/etc/default/ufw` has `IPV6=yes` by default, and every rule gets a `(v6)` twin in
`ufw status`. Leave it on. With `IPV6=no`, ufw 0.36.2 does not leave IPv6 open, as is often
assumed: it sets the IPv6 input policy to drop and allows only loopback, so the site and SSH
stop answering over IPv6 while the domain's AAAA record still sends visitors there (tested: SSH
on IPv4 answered, SSH on IPv6 did not).

If you are locked out and reach the disk from rescue mode, `ENABLED=no` in
`/etc/ufw/ufw.conf` keeps ufw off at the next boot.

## firewalld (RHEL family)

```
sudo systemctl enable --now firewalld
sudo firewall-cmd --get-active-zones; sudo firewall-cmd --list-all
sudo firewall-cmd --add-service=http --add-service=https    # runtime only, for now
# test from outside, then keep it:
sudo firewall-cmd --runtime-to-permanent
sudo firewall-cmd --permanent --list-services
```

A change without `--permanent` lives until the next `--reload` or reboot. That is a built-in
way back: make the change at runtime, test it with a new connection, and only then write it
with `--runtime-to-permanent`. An interface not assigned to a zone falls into the default zone
(`public`).

The `public` zone on almalinux:9 allows `cockpit dhcpv6-client ssh`. The `cockpit` service is
port 9090/tcp, open to the internet whether or not Cockpit (a web admin console) is used. In
the test, an unrelated program listening on 9090 answered from outside through that rule. If
nobody uses Cockpit, close it:
`sudo firewall-cmd --permanent --remove-service=cockpit && sudo firewall-cmd --reload`.

`--timeout=5m` on a runtime rule removes it on its own, but with firewalld 1.3.4 a
`firewall-cmd --reload` while such a rule was pending failed with `dictionary changed size
during iteration`, and firewalld then answered `INVALID_ZONE: public` until
`systemctl restart firewalld`. Let a timed rule expire, or remove it, before reloading.

fail2ban on the RHEL family bans through firewalld when `fail2ban-firewalld` is installed.

## Plain nftables

When neither ufw nor firewalld is wanted, one nftables file is easy to read. The stock Debian
`/etc/nftables.conf` starts with `flush ruleset`, which removes every table on the host,
whoever wrote it. On a Debian 12 host running Docker and ufw, `systemctl start nftables` with
the stock file erased ufw's rules and Docker's NAT rules at once: the host was left with no
filtering, and the published container port still answered. Replace only a table of your own
instead:

```
#!/usr/sbin/nft -f
table inet host_filter
delete table inet host_filter

table inet host_filter {
	chain input {
		type filter hook input priority filter; policy drop;
		ct state established,related accept
		ct state invalid drop
		iif "lo" accept
		meta l4proto { icmp, ipv6-icmp } accept
		ip6 saddr fe80::/10 udp sport 547 udp dport 546 accept
		tcp dport { 22, 80, 443 } accept
	}
}
```

The first two lines make the file safe to load again: the table is created if missing, then
deleted and rebuilt, and nothing else is touched (tested: loaded twice, Docker's tables
intact; a listener on another port stopped answering from outside, and answered again once the
table was deleted). Accept ICMPv6: IPv6 finds its neighbours and routers through it, so
dropping it breaks IPv6. The `udp dport 546` line lets in DHCPv6 replies from a router on the link:
connection tracking does not pair them with the multicast request, so without it a server that
gets its IPv6 address by DHCPv6 loses it at renewal (ufw and firewalld allow the same by
default; whether a given provider uses DHCPv6 or router advertisements varies). Check with `sudo nft -c -f /etc/nftables.conf`, load with
`sudo nft -f`, and `sudo systemctl enable nftables` to load it at boot.

Apply a changed file with `sudo systemctl reload nftables` (which runs `nft -f` on it), never with
`restart` or `stop`. Debian's unit stops with `nft flush ruleset`, whatever the file says, so
a restart wipes Docker's NAT and forwarding tables and fail2ban's bans along with yours:
published containers stop answering and lose their outbound traffic until Docker is
restarted, which on a live server is an outage. On a host where other tools write rules, make
the stop remove only your table, so a restart or a shutdown by someone else is safe too:

```
sudo mkdir -p /etc/systemd/system/nftables.service.d
printf '[Service]\nExecStop=\nExecStop=/usr/sbin/nft delete table inet host_filter\n' |
  sudo tee /etc/systemd/system/nftables.service.d/keep-other-tables.conf
sudo systemctl daemon-reload
systemctl cat nftables | grep ExecStop     # the empty line clears the flush, then yours
```

## Docker publishes ports past the host firewall

What you see: ufw is active with `deny (incoming)`, `ufw status` lists only 22, 80 and 443, and
yet the database or app port of a container answers from the internet.

Why: `-p 8080:80` (or `ports: ["8080:80"]` in Compose) makes Docker add a DNAT rule in the nat
table's PREROUTING chain that rewrites the destination to the container's address. The packet
is then forwarded, not delivered to the host, so it goes through the FORWARD chain and never
through INPUT, where ufw's rules live. In FORWARD, Docker's jumps come first:

```
-A FORWARD -j DOCKER-USER
-A FORWARD -j DOCKER-FORWARD
-A FORWARD -j ufw-before-logging-forward
...
```

Tested with Docker Engine 29.9.3 and ufw 0.36.2 on Debian 12: a program on the host listening
on a port that ufw did not allow was unreachable, while a container published on 8080 answered
from another machine. On AlmaLinux 9 with firewalld 1.3.4 the result was the same: Docker puts
its bridge in a `docker` zone with target `ACCEPT` and adds a `docker-forwarding` policy from
any zone.

IPv6 depends on the Docker network. On the default bridge, which has no IPv6, Docker answers
IPv6 for a published port with its userland proxy, a local process, so the traffic passes
INPUT and ufw blocked it. On a network created with IPv6 enabled, Docker writes ip6tables NAT
rules and the port bypassed ufw over IPv6 as well.

**Fix 1, the simple one: publish on loopback.** Put a reverse proxy (Caddy or nginx) in front
and let only it face the internet:

```
ports:
  - "127.0.0.1:8080:80"
```

Tested: closed from outside (IPv4 and IPv6 on Debian 12, IPv4 on AlmaLinux 9), open on the
server itself. A
container that only the proxy container talks to on the same Compose network needs no `ports:`
at all. The Docker 29 host also dropped packets that a neighbour routed straight to a
container's private address (rules in the raw table); older engines were not tested here.

**Fix 2: filter in the DOCKER-USER chain,** when a container has to publish on all addresses
and only some ports may be reachable. Docker 29 created DOCKER-USER empty and left rules there
alone across restarts.
[templates/ufw-docker-user.rules](../templates/ufw-docker-user.rules) is a block for the end of
`/etc/ufw/after.rules` and `/etc/ufw/after6.rules`, so ufw loads it on every start. It lets in
the listed published ports from the public interface and drops other new connections to
containers from there. The match uses `--ctorigdstport`, the port the client asked for,
because after DNAT the packet's destination port is the container's.

Tested on Debian 12 with Docker 29.9.3: the listed port answered, another published port did
not, over IPv4 and IPv6; containers kept their outbound access; the rules survived
`systemctl restart docker` and a restart of ufw with Docker stopped and started again around
it.

On a firewalld host, use fix 1. Loading DOCKER-USER rules through firewalld's direct interface
failed in the test (the chain did not exist when firewalld loaded them) and the reload left
Docker's own rules missing until Docker was restarted.

Setting `"iptables": false` in Docker's `daemon.json`, often suggested, makes Docker write no
rules at all (tested: no MASQUERADE, no DNAT; the published port was served by the userland
proxy instead). Containers on a bridge then depend on NAT rules you write yourself to reach
the internet. Fix 1 is simpler and keeps Docker's networking whole.

## Test from outside that only the intended ports answer

From a machine that is not the server and not on any allowlist:

```
nmap -Pn -p 22,80,443,3306,5432,6379,8080 203.0.113.10
nmap -6 -Pn -p 22,80,443,3306,5432,6379,8080 2001:db8::10
nc -vz -w3 203.0.113.10 5432
```

Choose the ports from `sudo ss -tulpn` on the server: every socket not on `127.0.0.1` or `[::1]` is
either meant to be public or must show as `filtered`. nmap reports three states: `open` (something
answers), `closed` (the probe got a refusal: nothing listens, as with 80 and 443 before the web
server runs, or a rule rejects with a TCP reset) and `filtered` (dropped, or rejected with an ICMP
message). For a port that has to stay private, `closed` is a warning, not a pass: when nothing
listens, nothing stops the next program that listens there. A check that reports only reachable or
not cannot tell `closed` from `filtered`; `nc -vz` can, by its message: a timeout means dropped
(ufw's default deny), `No route to host` means rejected by firewalld's default, and `Connection
refused` means either that nothing listens or that a rule such as `ufw reject 5432/tcp` rejects
(tested: nc and nmap print the same for both). On the server, `sudo ss -tlnp` tells the two apart:
when it lists something listening on that port, the refusal comes from a firewall rule; when it does
not, the port is simply closed.

For the site as a whole, [scripts/check_site.py](../scripts/check_site.py) takes
`--expect-closed` with the same ports (see [proving-it-works.md](proving-it-works.md)). When
your own network blocks outbound ports, an unreachable port proves nothing; say so instead of
claiming it.

## Traps

- **Testing from the server itself.** Everything answers on localhost and the firewall is
  invisible. Test from outside.
- **A new published port added after the firewall was checked.** Re-test after each Compose
  change, or use fix 1 so new ports start private.
- **The provider's firewall forgotten,** either blocking what the host allows or allowing what
  the host was meant to block.
- **`flush ruleset` in an nftables file** on a host where Docker, ufw or fail2ban also write
  rules.
- **`systemctl restart nftables` on Debian** after editing the file: the stop half flushes the
  whole ruleset, Docker's and fail2ban's included. Reload instead, or install the drop-in above.
- **`IPV6=no` in ufw,** which blocks IPv6 entirely instead of leaving it alone.
- **Cockpit's 9090 open by default** in the RHEL family's `public` zone.

## Done means

- The host firewall is enabled on boot (`ufw status verbose`, `firewall-cmd --state` or
  `systemctl is-enabled nftables`) and lists only the intended ports, IPv6 included.
- The provider's firewall, where there is one, allows the same set.
- No container port is published on all addresses unless it is meant to be public, or the
  DOCKER-USER rules cover it.
- A scan from outside, over IPv4 and IPv6, shows the intended ports open and everything that
  listens elsewhere filtered; ports that could not be checked are listed as not verified.

Checked against: ufw 0.36.2 with iptables 1.8.9 (nf_tables) and nftables 1.0.6 on debian:12,
ufw 0.36.2 with iptables 1.8.10 on ubuntu:24.04, firewalld 1.3.4 on almalinux:9 (9.8), Docker
Engine 29.9.3 from Docker's repository on debian:12 and almalinux:9, nmap 7.93 and
netcat-openbsd on debian:12; nftables.service under booted systemd 252 on debian:12 (restart
dropped a NAT and a fail2ban table, reload and the drop-in kept them), 2026-11-12.
