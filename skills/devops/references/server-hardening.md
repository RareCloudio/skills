# Server hardening: the first hour

Read this when a server is new, or has never been hardened, and you are setting up how people log in
and how it keeps itself patched: an admin user with a key, SSH through a drop-in file, automatic
updates and the reboot decision, fail2ban, time sync and swap, and what is not worth the
bother on one small server. The lockout guard used at every step (second session, config test, timed
revert) is explained in [preflight-and-safety.md](preflight-and-safety.md); the firewall is in
[firewall.md](firewall.md).

## The order, and why

1. Look first ([preflight-and-safety.md](preflight-and-safety.md)): distribution, how you are
   logged in, whether it serves people.
2. Bring packages up to date, and reboot now if a new kernel came in, while nobody depends on
   the server.
3. Create the admin user and log in as it with a key, in a new session, and run `sudo`.
4. Only then turn off root login and passwords, through a drop-in, with a second session open.
5. Enable the firewall, with SSH allowed first ([firewall.md](firewall.md)).
6. Automatic updates, fail2ban, time sync, swap.

Each step relies on access that the step before proved. Root login goes off after its
replacement has worked from a new connection, not before.

## Bring the system up to date

```
sudo apt update && sudo apt full-upgrade -y
cat /var/run/reboot-required.pkgs 2>/dev/null        # listed packages want a reboot
```

On the RHEL family (Alma, Rocky): `sudo dnf upgrade -y`, then `sudo dnf needs-restarting -r`
(from `dnf-plugins-core`), which says whether a reboot is needed. On a new server, reboot now.

If the download crawls or fails, check the mirror within minutes rather than waiting on it
([updates.md](updates.md) shows how to tell a slow mirror from a slow network, and switch).

## An admin user with a key, tested before root goes away

Many cloud images create a sudo user already. Check before adding another:
`getent group sudo wheel`. If one exists and the person uses it, keep it.

```
sudo useradd -m -s /bin/bash -G sudo admin       # RHEL family: -G wheel
sudo passwd admin                                # for sudo, and for the provider's console
sudo install -d -m 700 -o admin -g admin ~admin/.ssh
echo '<the person's public key line>' | sudo tee ~admin/.ssh/authorized_keys >/dev/null
sudo chown admin:admin ~admin/.ssh/authorized_keys
sudo chmod 600 ~admin/.ssh/authorized_keys
```

The name is the person's choice. If you copy root's `authorized_keys` instead, read it first:
on some cloud images root's lines start with options such as `command="echo 'Please login
as...'"` (cloud-init does this when it disables root; not reproduced here), and those
options would follow the key into the new account.

Verify from a new terminal on your side, not from the session you are in:

```
ssh -o IdentitiesOnly=yes -i ~/.ssh/<key> admin@203.0.113.10 'id -un'
ssh -t admin@203.0.113.10 'sudo -v && echo sudo-ok'
```

**Passwordless sudo** lets an agent work without someone typing a password, but it also means
the SSH key alone is root. Decide it with the person. If they want it, write a file whose name
has no dot, because sudo silently skips names with a dot (tested: `visudo -cf` printed
`parsed OK` for `/etc/sudoers.d/admin.conf` and sudo still asked for a password):

```
echo 'admin ALL=(ALL) NOPASSWD:ALL' | sudo tee /etc/sudoers.d/90-admin >/dev/null
sudo chmod 440 /etc/sudoers.d/90-admin
sudo visudo -cf /etc/sudoers.d/90-admin && sudo -l -U admin   # shows "(ALL) NOPASSWD: ALL"
```

## SSH: a drop-in, read back, then reload

Use [templates/sshd-hardening.conf](../templates/sshd-hardening.conf): no root login, keys only,
`AuthenticationMethods publickey`. Install it as a drop-in instead of editing `sshd_config`,
so package updates do not conflict with your edit and the change is one file to remove.

Keep a second session open; a mistake here shows only when the next connection is refused.

```
grep -n '^Include' /etc/ssh/sshd_config      # Debian 12, Ubuntu 24.04, Alma 9: first line read
ls /etc/ssh/sshd_config.d/                   # files already there, and their names
sudo install -m 644 sshd-hardening.conf /etc/ssh/sshd_config.d/00-hardening.conf
sudo sshd -t                                 # silent and exit 0 when the syntax is fine
sudo sshd -T | grep -E '^(permitrootlogin|passwordauthentication|authenticationmethods) '
sudo systemctl reload ssh                    # RHEL family: sshd
```

**The first value wins, and file names decide the order.** For most keywords sshd keeps the
first value it reads. The `Include` sits at the top of `sshd_config`, and the drop-ins are read
in name order. So a file named `99-hardening.conf` loses to anything earlier. Tested with
`sshd -T` on all three images:

| Files present | Effective |
|---|---|
| `50-cloud-init.conf` (`PasswordAuthentication yes`) + `99-hardening.conf` (`no`) | `yes` |
| the same two, ours renamed `00-hardening.conf` | `no` |
| almalinux:9's `25-permitrootlogin.conf` (`PermitRootLogin yes`) + ours as `99-` | `yes` |

Cloud images and installers write files like these: cloud-init can write `50-cloud-init.conf`
with password login on (in the test that file was written by hand), and the almalinux:9 image
ships an unowned `25-permitrootlogin.conf`. Name yours `00-` and, more importantly, read the
result back with `sshd -T`, since the next image may use another name.
`AuthenticationMethods publickey` in the template is the second line of defence: with an
earlier file forcing `PasswordAuthentication yes`, a password login was still refused
(`Permission denied (publickey)`).

Verify from your side, each in a new connection:

```
ssh admin@203.0.113.10 true && echo key-ok
ssh -o PubkeyAuthentication=no -o PreferredAuthentications=password admin@203.0.113.10
#   -> Permission denied (publickey).
ssh root@203.0.113.10                         # -> Permission denied
```

These refused logins count toward fail2ban; set it up as below so they do not ban you.

**Changing the SSH port** cuts log noise, not risk; with keys only it is optional. If the
person wants it, open the new port in both firewalls first, set `port =` in the fail2ban jail,
and on Ubuntu 24.04 know that SSH is socket-activated: systemd, not sshd, holds port 22. A
generator turns `Port` in the sshd configuration into the socket's port, but only after:

```
sudo systemctl daemon-reload
sudo systemctl restart ssh.socket
ss -tlnp | grep ssh                           # the new port; port 22 is gone
```

Tested: with `Port 2222` in a drop-in, `systemctl restart ssh.service` left it on 22; the two
commands above moved it, and an open session survived. `systemctl is-enabled ssh.socket` tells
you whether this applies (Debian 12 has no socket unit; Debian 13 ships one, not tested). On the
RHEL family SELinux also has to allow the port (`sudo semanage port -a -t ssh_port_t -p tcp
<port>`); not exercised here, since SELinux is off in containers.

## Security updates on their own

Most break-ins use holes that already had a fix. Debian and Ubuntu use `unattended-upgrades`:

```
sudo apt install unattended-upgrades
sudo install -m 644 52unattended-upgrades-local /etc/apt/apt.conf.d/52unattended-upgrades-local
apt-config dump | grep -E 'APT::Periodic::(Update-Package-Lists|Unattended-Upgrade)|Reboot'
sudo unattended-upgrade --dry-run --debug 2>&1 | grep -E '^(Allowed origins|Packages that)'
systemctl list-timers 'apt-daily*'
```

[templates/52unattended-upgrades-local](../templates/52unattended-upgrades-local) turns the
daily run on, which is the default to set up, and carries the automatic reboot switched off
until the person decides (below). What it installs is the distribution's default set, which on
Debian includes the stable point releases as well as security fixes
([updates.md](updates.md) lists both distributions' origins). Two facts that differ from
sshd: in apt's configuration the last value read wins, so a file sorting after
`50unattended-upgrades` overrides it without editing it; and apt ignores a file in
`apt.conf.d` whose name has an extension other than `.conf` (it prints `Ignoring file ... as it
has an invalid filename extension`). The reboot trigger, `/var/run/reboot-required`, is written
by a kernel hook that the `unattended-upgrades` package itself installs.

On the RHEL family, `dnf-automatic` is installed with its timer off and set to download only:

```
sudo dnf install dnf-automatic
sudo sed -i -e 's/^upgrade_type = .*/upgrade_type = security/' \
  -e 's/^apply_updates = .*/apply_updates = yes/' /etc/dnf/automatic.conf
grep -E '^(upgrade_type|apply_updates|reboot) ' /etc/dnf/automatic.conf
sudo systemctl enable --now dnf-automatic.timer
systemctl list-timers dnf-automatic.timer
```

Running `sudo dnf-automatic` once by hand applied the pending security updates in the test.
The `reboot` line stays at its default, `never`.

**The automatic reboot is the person's decision.** A kernel fix only protects the server once it
runs, which takes a reboot, and a reboot takes the service down for a minute or two. Offer it
with a quiet hour (04:00 server time is a good default; check the zone in `timedatectl`) and say
what a no means: the updates still install, but each new kernel waits for someone to reboot by
hand, and `/var/run/reboot-required` (or `dnf needs-restarting -r`) shows one is pending. On a
yes, set `Automatic-Reboot "true"` and the hour in the template, or `reboot = when-needed` in
`automatic.conf` (accepted by dnf-automatic 4.14; not seen to trigger a reboot in the test). On
a no, say in the hand-over who reboots, and when ([updates.md](updates.md)).

## Brute-force protection with fail2ban

With passwords off, guessing cannot succeed, so fail2ban mostly cuts log noise and slows
scanners; it is cheap and worth having. Exempt the address you work from first
([templates/fail2ban-exempt.sh](../templates/fail2ban-exempt.sh), why below), write
[templates/fail2ban-sshd.local](../templates/fail2ban-sshd.local) before the package, then start
it and read back what is in force:

```
ssh <server> 'sh -s add' < fail2ban-exempt.sh  # from your side; stops if it finds no address
sudo install -m 644 fail2ban-sshd.local /etc/fail2ban/jail.d/sshd.local
sudo apt install fail2ban python3-systemd    # RHEL: epel-release, then fail2ban fail2ban-firewalld
sudo fail2ban-client -t                      # "OK: configuration test is successful"
sudo systemctl enable fail2ban && sudo systemctl restart fail2ban   # AlmaLinux ships it off
sleep 2                                      # its socket takes a moment after a restart
sudo fail2ban-client get sshd bantime        # 3600 with the template: the value in force
sudo fail2ban-client status sshd             # "Journal matches: ..." means it reads the journal
sudo fail2ban-client get sshd ignoreip       # loopback and your address
sudo fail2ban-client set sshd banip 192.0.2.50 && sudo fail2ban-client set sshd unbanip 192.0.2.50
```

The last line proves the ban action works without locking anyone out. In the test, six failed
logins from another container got that address banned on all three images.

**Quote the value `get` prints, not the file.** Debian and Ubuntu start fail2ban with their
defaults as the package installs, and a jail written after that is read only at the next start
or `fail2ban-client reload`; `systemctl enable --now` leaves a running service alone. Tested on
ubuntu:24.04: jail written after the install, `enable --now`, and `bantime` stayed 600 until the
restart made it 3600. Writing the jail first makes the package's own start use it.

**Your own refusal checks count as an attack.** The logins that prove root and passwords are
refused come from your address, and a refused root login with a valid key logged three failures
in the test, so two such checks reach the template's five. Running them before fail2ban does
not help: when it starts it reads back the last `findtime` (ten minutes) of the journal. A ban
rejects every packet from that address to port 22, so the session you kept open freezes too.
The script puts the address in a drop-in of its own, with a systemd timer that deletes it two
hours later even if your session ends, and stops rather than write an empty entry when `sudo
-i`, `su` or the console has cleared `SSH_CONNECTION` (its header has the details). Take it back
yourself when you finish, since that address is often shared (a carrier's, a cloud runner's):
`ssh <server> 'sh -s remove' < fail2ban-exempt.sh` cancels the timer, deletes the file, reloads
and prints the list, which should hold no working address. Tested on debian:12 and ubuntu:24.04:
the exempt client stayed in while another was banned; without `remove` the timer took the
address out and the next checks banned it; `remove` left neither file nor timer. Locked out
anyway: the provider's console, then `sudo fail2ban-client set sshd unbanip <address>`. Tell the
person in the hand-over that a few mistyped logins shut them out for the ban time, how to get
back in, and which address was exempt while you worked.

**Debian 12 has no `/var/log/auth.log`** unless rsyslog is installed, and its packaged fail2ban
reads that file. Installed as shipped, the service failed: `Have not found any log file for
sshd jail`. The template sets `backend = systemd`, which reads the journal instead. Ubuntu
24.04 and Debian 13 already ship that setting, and AlmaLinux's defaults use the journal too, so
the template changes nothing there. On Debian, `python3-systemd` is only a recommendation of
fail2ban; if packages were installed without recommends, the journal backend has no library.

If the SSH port changes, set `port = <port>` in the jail, or the ban blocks the old port.

## Time

TLS, one-time codes and log correlation need a correct clock. Check:

```
timedatectl            # "System clock synchronized: yes" and "NTP service: active"
chronyc tracking       # RHEL family (chronyd); "Leap status : Normal"
```

Debian and Ubuntu run `systemd-timesyncd` or `chrony` (`sudo apt install systemd-timesyncd`
when neither is there); the RHEL family runs `chronyd`. `systemd-timesyncd` refuses to run in
a container, so synchronization was observed only with chronyd on AlmaLinux. Keep servers on
UTC unless the person wants otherwise; the unattended reboot hour follows the server's clock,
so check the zone in `timedatectl` when you pick it.

## Swap on a small machine

Below about 2 GB of memory, a package upgrade or a build can wake the kernel's out-of-memory
killer, which kills the biggest process, usually the app or the database. A swap file turns
that into slowness:

```
sudo fallocate -l 1G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
swapon --show; free -h
```

`swapon` fails with `Invalid argument` on a filesystem that cannot hold swap (tried on
overlayfs); on ext4 it worked. Swap is a cushion, not memory: if `free -h` shows
it in steady use, the server needs more memory.

## What is not worth doing on one small server

- **A low `MaxAuthTries`.** An SSH client offers its keys one by one; with `MaxAuthTries 2` and
  four keys, the right key came fourth and the login failed with `Too many authentication
  failures`. The default and fail2ban are enough.
- **Disabling IPv6** "for security". Filter it in the firewall instead; turning it off breaks
  things that expect it.
- **Two-factor SSH on a server an agent or a CI job manages.** It blocks the automation you are
  setting up; keys and a short user list do the job.
- **Long sysctl lists, rootkit scanners or file integrity tools** that nobody will read. Updates,
  keys only, a firewall and tested backups cover what matters here.
- **Turning off SELinux** on the RHEL family to make something work. Find the denial
  (`sudo ausearch -m avc -ts recent`) and fix the label or the boolean.

`AllowUsers admin deploy` in the drop-in is worth it when the person agrees, with a known cost:
every new account that needs SSH later (a CI deploy user) must be added there, or it is refused.

## Traps

- **A drop-in that never takes effect.** Another file sorts first. `sshd -t` does not warn;
  `sshd -T` shows it.
- **Root's keys copied with their `command=` option,** so the new user is told to log in as
  someone else and disconnected.
- **A sudoers file with a dot in its name,** passing `visudo -cf` and ignored by sudo.
- **fail2ban "installed" but failed** on Debian 12; check `systemctl is-active fail2ban`, not
  the install log.
- **A port change on Ubuntu 24.04 that does nothing** until `daemon-reload` and a restart of
  `ssh.socket`.
- **A jail that says one hour while ten minutes is in force,** because fail2ban was already
  running when the file was written. `fail2ban-client get sshd bantime` shows what applies.
- **The person banned by their own checks,** the open session with them; exempt the address first.

## Done means

- From a new connection: the admin user logs in with a key and `sudo` works; a password login
  and a root login are both refused.
- `sudo sshd -T` shows `permitrootlogin no`, `passwordauthentication no` and
  `authenticationmethods publickey`.
- Automatic updates are on and the reboot policy is agreed: `apt-config dump` or
  `/etc/dnf/automatic.conf` shows it, and the timer is listed.
- `fail2ban-client status sshd` answers, `get sshd bantime` matches the jail, and `get sshd
  ignoreip` lists no working address, only loopback and any fixed one the person chose;
  `timedatectl` shows a synchronized clock; on a small machine `swapon --show` lists the swap.
- The hand-over says who reboots and when, that keys are the way in, and which address was exempt.

Checked against: OpenSSH 9.2p1, fail2ban 1.0.2, unattended-upgrades 2.9.1, sudo 1.9.13p3 on
debian:12; OpenSSH 9.6p1, fail2ban 1.0.2, systemd 255 on ubuntu:24.04; OpenSSH 9.9p1,
fail2ban 1.1.0, dnf-automatic 4.14.0, chrony 4.8, sudo 1.9.17p2 on almalinux:9 (9.8); fail2ban
1.1.0 and OpenSSH 10.0p1 on debian:13, 2026-11-12.
