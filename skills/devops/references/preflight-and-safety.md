# Preflight and safety

Read this when you are about to change a server that someone else owns: before the first
command that writes anything, and again before any change to SSH, the firewall or the network.
It covers what to find out first, how to tell whether the server serves people right now, what
counts as a way back, and the lockout guard (how to change access settings without locking
anyone out, and what to do when it happens anyway). The hardening steps themselves are in
[server-hardening.md](server-hardening.md), firewall rules in [firewall.md](firewall.md), and
checking the result from outside in [proving-it-works.md](proving-it-works.md).

## Know the box before you touch it

Spend two minutes reading before writing. Everything below is read-only.

```
cat /etc/os-release                 # distribution and version decide every later command
ps -p 1 -o comm=                    # the init system; systemd on every mainstream image
systemd-detect-virt                 # kvm, microsoft, ...; "docker" means you are in a container
id; echo "$SSH_CONNECTION"          # who you are, and the address you came in from
sudo -n true && echo "sudo works without a password"
df -h /; free -h; uptime
```

How you logged in matters for what you may change. The SSH log says it in one line:

```
sudo journalctl -u ssh -u sshd -o cat | grep Accepted | tail -n 3
# Accepted publickey for admin from 198.51.100.7 port 50514 ssh2: ED25519 SHA256:...
```

If that says `password`, turning passwords off would lock out whoever logs in that way, perhaps
the owner. The address is the one to keep off ban lists and, if it is fixed, to allow in the
firewall. The unit is `ssh` on Debian and Ubuntu and `sshd` on the RHEL family; naming both is
harmless.

What already runs, and what already guards it:

```
sudo ss -tulpn                      # every listening socket, its address and its process
systemctl --failed                  # broken units: know them before you are blamed for them
systemctl list-timers               # scheduled jobs (backups, renewals, updates)
ls /etc/cron.d; sudo ls /var/spool/cron/crontabs /var/spool/cron 2>/dev/null
sudo docker ps 2>/dev/null; sudo podman ps 2>/dev/null
sudo ufw status verbose 2>/dev/null; sudo firewall-cmd --list-all 2>/dev/null
sudo nft list ruleset | head -n 40  # everything, whichever tool wrote it
sudo sshd -T | grep -E '^(port|permitrootlogin|passwordauthentication|authenticationmethods) '
```

Reading `ss`: a socket on `0.0.0.0` or `[::]` answers from the internet unless something
filters it; one on `127.0.0.1` or `[::1]` answers only locally. A `docker-proxy` process means
a published container port, which the host firewall may not cover (see
[firewall.md](firewall.md)).

Write what you found in a few lines: it is the baseline you compare against after the change,
and the start of the hand-over.

## Does it serve people right now?

The answer changes how you work, so find it out rather than assume it. Signs that it does:

```
ss -Htn state established '( sport = :80 or sport = :443 )' | wc -l   # visitors connected now
sudo tail -n 5 /var/log/nginx/access.log 2>/dev/null                  # or the app's own log
dig +short example.com; ip -br addr                                    # does the name point here?
```

Fresh requests in the log, open connections on the web ports, or the domain resolving to this
server's address all mean live. When the signs are unclear, ask the person, and treat it as
live until they answer.

On a live server, anything that restarts the web server, enables or changes a firewall,
changes SSH, or reboots can take the service down. Say what the step does and how long it
interrupts, and get the person's yes for that step and its timing. On a new, empty server the
only thing to lose is access, so you can move faster, but the lockout guard below still
applies.

## A way back

Know which of these exists before the first risky change, and name it to the person.

1. **A second session that stays open.** The cheapest way back. An established SSH connection
   survives an sshd reload, a restart of Ubuntu's `ssh.socket` and `ufw enable` without an SSH
   rule (all three tried: the old session kept working while a new one was refused or timed
   out). It covers mistakes in sshd, sudo, PAM and the firewall, as long as you notice before
   you close it.
2. **The provider's console** (a web terminal, VNC or serial console in the provider's panel).
   It works when the network is broken, but it is a local login: it needs a password for some
   user. A server with keys only and no passwords has no console login, so set a password for
   the admin user before the first risky change (it is also what `sudo` asks for).
3. **Rescue mode.** The provider boots the server from a rescue system; you mount its disk and
   undo the file that broke access. Slower, and it needs the person in their panel.
4. **A snapshot** of the disk, taken through the provider. Take one, with the person's yes since
   it usually costs storage while kept, before the first hardening of a server that already
   holds data, before a distribution upgrade, before disk or partition changes, and before
   anything you cannot undo by editing a file. A fresh empty server does not need one;
   reinstalling is quicker. Restoring a snapshot throws away everything written since, so that
   is the person's decision.

Before editing a configuration, copy it outside the directory its program reads, for example
`sudo cp -a /etc/ssh/sshd_config.d /root/sshd_config.d.$(date +%F)`. A backup left inside a
drop-in directory can be read as configuration (anything ending in `.conf` in
`sshd_config.d`), or can make a check pass for the wrong file.

## The lockout guard

Things that lock people out: the sshd configuration, the host firewall, the provider's
firewall, network configuration (addresses, routes, netplan), fail2ban or `ufw limit` banning
your own address, and changes to users, keys, sudo or PAM. For each of those changes:

**1. Keep a second session open** for the whole change, and test with a new connection, never
with the session you are in: that one proves nothing about the next login.

**2. Test the configuration before reloading, then read back the effective state.** A syntax
check is necessary but not enough, because each of these passes its check and still does not do
what you meant (all three reproduced on Debian 12 and AlmaLinux 9):

- an sshd drop-in is overridden by another file read before it (`sshd -t` is silent);
- a sudoers file named `/etc/sudoers.d/admin.conf` is ignored because sudo skips names with a
  dot, while `visudo -cf` prints `parsed OK`;
- an apt file named `52local.local` is skipped with only a notice from apt.

So pair each check with a read-back. When sshd has `Match` blocks, read the values for one
connection with `sudo sshd -T -C user=admin,host=client.example.com,addr=192.0.2.1`.

| Change | Check before reload | Effective state |
|---|---|---|
| sshd | `sudo sshd -t` | `sudo sshd -T` |
| sudo | `sudo visudo -cf <file>` | `sudo -l -U admin` |
| fail2ban | `sudo fail2ban-client -t` | `sudo fail2ban-client status sshd` |
| nftables | `sudo nft -c -f <file>` | `sudo nft list ruleset` |
| ufw's iptables files | `sudo iptables-restore --test --noflush < <file>` | `sudo iptables -S` |

**3. Allow SSH before enabling a firewall,** in the host firewall and in the provider's, and on
the port sshd really listens on (`ss -tlnp | grep ssh`).

**4. Arm a timed automatic revert for firewall and network changes,** so that if you lose access
the server undoes the change on its own:

```
sudo systemd-run --on-active=5min --timer-property=AccuracySec=1s \
  --unit=fw-revert /usr/sbin/ufw --force disable
systemctl list-timers fw-revert.timer         # armed
# ... make the change, then open a NEW connection from your side ...
sudo systemctl stop fw-revert.timer           # cancel once the new connection works
```

Why this works: `systemd-run` creates a transient timer owned by systemd, not by your shell, so
it fires after your connection is gone. Details found while testing it on Debian 12 (systemd
252) and Ubuntu 24.04 (systemd 255):

- Without `AccuracySec=1s` a timer may fire up to a minute late (the default accuracy); a 15
  second timer fired after 21 seconds.
- The unit name is taken while the timer is armed (`Unit fw-revert.timer was already loaded`),
  so cancel the old one or use a new name. After it fires, the name is free again.
- A transient timer does not survive a reboot.
- `ufw disable` takes two or three seconds to finish after the timer fires.

The revert command should be the smallest step that restores access: disable the firewall,
move a drop-in away and reload. The SSH unit is `ssh` on Debian and Ubuntu and `sshd` on the
RHEL family, with no alias there, so a revert that names the wrong one moves the file, fails
to reload, and leaves the running sshd on the config that locked you out. This one reloads
whichever is running, and fails loudly when neither is:

```
sudo systemd-run --on-active=5min --timer-property=AccuracySec=1s --unit=ssh-revert \
  sh -c 'mv /etc/ssh/sshd_config.d/00-hardening.conf /root/ &&
    for u in ssh sshd; do systemctl is-active --quiet "$u" && exec systemctl reload "$u"; done;
    echo "ssh-revert: no running ssh or sshd unit to reload" >&2; exit 1'
systemctl is-active ssh sshd                  # one says active: the unit the revert reloads
```

After it fires, `systemctl status ssh-revert.service` says whether it worked. On Ubuntu with
socket activation, a stopped `ssh.service` has nothing to reload; the next connection starts
sshd with the restored file.

`at` does the same where it is installed; list jobs with `atq`, cancel with `sudo atrm <job>`.
`systemd-run` needs no extra package.

```
echo '/usr/sbin/ufw --force disable' | sudo at now + 5 minutes
```

firewalld and netplan have reverts of their own: a firewalld change made without
`--permanent` disappears on `firewall-cmd --reload` or a reboot (see
[firewall.md](firewall.md)), and `netplan try` rolls a network change back unless you confirm
it (not exercised here).

**5. One change at a time.** Change, test with a new connection, cancel the revert, then go on.
When two changes go in together and access breaks, you do not know which one to undo.

## When the session drops anyway

Stop reconnecting in a loop. fail2ban bans an address after five failures in ten minutes by
default, and `ufw limit` refuses the sixth connection within 30 seconds (both tried), so
retries can turn a small mistake into a ban. If a revert is armed, wait for it.

Then find out which layer refuses, from your side:

```
nc -vz -w3 203.0.113.10 22
ssh -v admin@203.0.113.10
```

- `Connection refused`: the server answered and nothing listens on that port. sshd is down,
  or listens on another port (a port change on Ubuntu that only half took effect). A fail2ban
  ban looks the same on Ubuntu 24.04, whose nftables action rejects (tested).
- `Connection timed out`: something drops the packets. The host firewall (ufw's default
  deny drops), the provider's firewall, or a ban on your address. Trying from another network
  tells a ban apart from a rule.
- `No route to host`: often a firewall rejecting (firewalld's default reject looks like this),
  or a network problem.
- `Permission denied (publickey)`: sshd is up and refuses your key, or passwords are off for
  a user who only had a password.

With the provider's console (the person's panel, or an API you were given), undo the last
change: `sudo ufw disable`, move the sshd drop-in out and `sudo systemctl reload ssh` (`sshd` on
the RHEL family),
`sudo fail2ban-client set sshd unbanip 198.51.100.7`, or `sudo firewall-cmd --reload` to drop
runtime firewalld changes. From rescue mode, with the server's disk mounted at `/mnt`: set
`ENABLED=no` in `/mnt/etc/ufw/ufw.conf`, or move the drop-in out of
`/mnt/etc/ssh/sshd_config.d/`, then boot normally.

Tell the person what happened, what you tried, and the one thing they need to do in their panel
(open the console, enable rescue, fix the provider's firewall). Restoring a snapshot comes last,
with their yes, because it loses what was written since it was taken.

## Traps

- **Testing in the session you are in.** It was authenticated before the change. The only test
  that counts is a new connection, from outside, with the account the person will use.
- **Many SSH connections from an agent.** Running each command as its own `ssh` call trips
  `ufw limit` and can trip fail2ban. Reuse one connection:
  `ssh -o ControlMaster=auto -o ControlPath=~/.ssh/cm-%C -o ControlPersist=10m admin@host`.
- **Two firewalls, one forgotten.** A port can be open on the host and closed at the provider,
  or the other way round. When a test times out, check both.
- **A ban on your own address.** The checks that prove root and passwords are refused count as
  failed logins, and a ban cuts the session you kept open as well. Exempt the address you work
  from while you set up, with the timed drop-in in [server-hardening.md](server-hardening.md),
  and take it back when you finish; a ban later is lifted from the console.
- **A revert that does more than needed.** Restoring a whole configuration from a backup can
  undo other people's changes made in the meantime. Revert the one thing you changed.

## Done means

- The baseline is written down: distribution, how you log in, what listens, what was already
  failing.
- Whether the server is live is known, and the person agreed to each disruptive step.
- A way back exists and is named: an open session at least, and a console login or a snapshot
  where the change warrants one.
- For each access change: the check passed, the effective state was read back, a new
  connection from outside worked, and no revert timer is left armed
  (`systemctl list-timers --all | grep revert` prints nothing).

Checked against: systemd 252 and OpenSSH 9.2p1 on debian:12, systemd 255 and OpenSSH 9.6p1 on
ubuntu:24.04, firewalld 1.3.4 and OpenSSH 9.9p1 on almalinux:9 (AlmaLinux 9.8), ufw 0.36.2,
fail2ban 1.0.2 and 1.1.0, sudo 1.9.13p3 and 1.9.17p2; the timed sshd revert fired under booted
systemd on all three and reloaded `ssh` (Debian, Ubuntu) or `sshd` (Alma), 2026-11-12.
