# Keeping a server patched

Read this when you set up updates on a server, find one that has not been patched in a while,
need to plan a reboot, rebuild container images for security fixes, or move to a new release of
the distribution or a language runtime. It covers what can update itself, what still needs a
person, and where to read end-of-life dates. The first hour on a new server is
[server-hardening.md](server-hardening.md); deploying a new version of the app is [docker.md](docker.md) or [systemd.md](systemd.md).

## Security updates on their own

Most break-ins use holes that already had a fix, so updates go on automatically. On Debian and
Ubuntu that is `unattended-upgrades`, turned on with
[templates/52unattended-upgrades-local](../templates/52unattended-upgrades-local) as
[server-hardening.md](server-hardening.md) shows, so there is one place to read the setting and
the reboot switch. To check a server, whoever set it up:

```
apt-config dump | grep -E 'APT::Periodic::(Update-Package-Lists|Unattended-Upgrade)'
unattended-upgrade --dry-run -d 2>&1 | grep -E 'Allowed origins|Packages that will be upgraded|No packages'
```

Both values should be `"1"`. Two systemd timers drive it: `apt-daily.timer` fetches
lists at 06:00 and 18:00 with up to 12 hours of random delay, `apt-daily-upgrade.timer` installs
at 06:00 with up to an hour of delay. The log is
`/var/log/unattended-upgrades/unattended-upgrades.log`. Some images ship it installed and on and
others do not, so check rather than assume.

What it installs differs by distribution, which people get wrong. In our test the default
`Allowed origins` were:

- Debian 12: the security archive and the release's own label (`label=Debian`), so stable point
  releases arrive automatically too, not only security fixes.
- Ubuntu 24.04: `noble` and `noble-security`, plus the ESM (Expanded Security Maintenance)
  archives if the machine is attached to Ubuntu Pro; `noble-updates` (bug fixes) is not on.

On AlmaLinux and Rocky the tool is `dnf-automatic`. Its default is to download only
(`apply_updates = no`), and `upgrade_type = default` means every update, not only security:

```
dnf install dnf-automatic
sed -i -e 's/^upgrade_type = default/upgrade_type = security/' \
       -e 's/^apply_updates = no/apply_updates = yes/' /etc/dnf/automatic.conf
systemctl enable --now dnf-automatic.timer
systemctl list-timers dnf-automatic.timer
dnf updateinfo list --security          # what it would install now
```

The timer runs at 06:00 plus a random delay. `dnf-automatic-install.timer` is the alternative
that installs whatever `apply_updates` says. Its log is `journalctl -u dnf-automatic`.

What still needs a person, and is worth saying in the hand-over:

- **Reboots.** A new kernel, or a new C library, does nothing until the machine restarts.
  Neither tool reboots by default (`Automatic-Reboot "false"` in Debian's
  `50unattended-upgrades`; `reboot = never` in `automatic.conf`).
- **Long-running services** keep the old library in memory until they restart.
- **Third-party repositories** (Docker's, a Node.js or PHP vendor repository, a PPA) are outside
  the allowed origins by default, so their updates wait for `apt upgrade` by hand, or for an
  origin you add to `Unattended-Upgrade::Origins-Pattern` on purpose.
- **Container images, language runtimes and the app's dependencies,** which apt and dnf never see.
- **Major versions** of the distribution, the database, the runtime.

## When package downloads crawl

A mirror can fail for a day while the network is fine: in one trial `apt` sat on 503s and a few
kilobytes a second for over an hour before anyone looked at the mirror. When package downloads
run far below what the server's network should give, or `apt` prints `Err:` lines, look at the
mirror in the first minutes instead of waiting.

**Mirror or network?** Fetch the same small file from the configured mirror and from the
distribution's main archive, with the downloader apt itself uses (no curl needed):

```
grep -rhE '^(URIs:|deb )' /etc/apt/sources.list /etc/apt/sources.list.d/   # the mirror in use
/usr/lib/apt/apt-helper download-file http://<mirror-host>/ubuntu/dists/noble/InRelease /tmp/t
/usr/lib/apt/apt-helper download-file http://archive.ubuntu.com/ubuntu/dists/noble/InRelease /tmp/t
```

Each prints a line like `Fetched 256 kB in 1s (296 kB/s)`, or `E: Download Failed`. The
configured mirror slow or failing and the main archive fast: switch. Both slow: the network or
DNS (`getent hosts archive.ubuntu.com`), and another mirror will not help.

**Switch, keeping the original.** Replace only the mirror's host, so the security entry and the
suites stay as they were:

```
sudo cp /etc/apt/sources.list.d/ubuntu.sources /root/ubuntu.sources.bak
sudo sed -i 's|http://<mirror-host>/|http://archive.ubuntu.com/|' \
  /etc/apt/sources.list.d/ubuntu.sources
sudo apt update                                  # no Err: lines
```

Debian 12 keeps it in `/etc/apt/sources.list.d/debian.sources`, with `deb.debian.org` as the
distribution's default host; older releases and some images use `/etc/apt/sources.list`, which
the `grep` above shows. Ubuntu on arm64 uses `ports.ubuntu.com/ubuntu-ports/`. Say in the
hand-over which file you changed and where the original is.

On the RHEL family, dnf reads a list of mirrors (`mirrorlist=` or `metalink=` in
`/etc/yum.repos.d/*.repo`) and moves to the next one on errors; `dnf repoinfo baseos` shows the
one in use (`Repo-baseurl`). For a slow one, add `fastestmirror=True` to `/etc/dnf/dnf.conf`
(`dnf -v makecache` then prints `determining the fastest mirror`) and run
`sudo dnf clean all && sudo dnf makecache`.

Name a mirror by the host in the file. The name does not say who runs it; say who does only
when the file, its comments or the mirror's own page says so.

## Know when a reboot or restart is pending

```
cat /var/run/reboot-required.pkgs 2>/dev/null   # Debian, Ubuntu: which packages asked for it
needrestart -r l                                # Debian, Ubuntu: list services on old libraries
dnf needs-restarting -r; echo $?                # Alma, Rocky: exit 1 means reboot
dnf needs-restarting -s                         # Alma, Rocky: services to restart
uname -r; ls /boot/vmlinuz-* | sort -V | tail -1  # running kernel against the newest installed
```

After `dnf-automatic` installed a new glibc in our test, `dnf needs-restarting -r` printed
`Core libraries or services have been updated since boot-up: * glibc ... Reboot is required`
and exited 1.

On Debian, `/var/run/reboot-required` is written by a kernel hook that ships with
`unattended-upgrades` (`/etc/kernel/postinst.d/unattended-upgrades`), so on a Debian server
without that package a kernel update leaves no flag at all. Ubuntu also writes it from library
updates through `update-notifier-common`. Compare `uname -r` with the newest kernel in `/boot`
rather than trusting the flag alone.

**Automatic or by hand is the person's call.** Security updates install on their own by default;
the reboot does not. Offer the automatic one with a quiet hour: `Automatic-Reboot "true"` with
`Automatic-Reboot-Time "04:00"` in the template, or `reboot = when-needed` in `automatic.conf`,
and tell them the site blinks at that hour. If they say no, every kernel fix waits as a pending
reboot that someone has to do, so agree who looks for it (the commands above) and how often.

**Doing it at a chosen moment.** A reboot of a single server is an outage of a few minutes, so it
needs the person's yes and a time they pick. Before it, check that every service that should come
back is enabled (`systemctl is-enabled app`, `restart: unless-stopped` in Compose); after it, check
from outside as in [proving-it-works.md](proving-it-works.md) and look at `systemctl --failed`. A
service restart is lighter than a reboot but still drops connections; restart services one at a time
and check each.

## Container base images and dependencies

An image does not change after it is built. Security fixes in the base image reach you only
when you rebuild your image, or pull a rebuilt one, and recreate the container:

```
docker build --pull -t app:2026-11-12 .          # --pull fetches the newest base image
sudo -u deploy docker compose --project-directory /srv/shop pull    # images you run as they are
sudo -u deploy docker compose --project-directory /srv/shop up -d   # (postgres, caddy)
docker image inspect -f '{{.Created}}' nginx:stable
trivy image --ignore-unfixed --quiet app:2026-11-12
```

`--ignore-unfixed` limits the scan to findings that have a fix today, which is the list you can
act on. Rebuild on a schedule (weekly is common) as well as when the app changes, because a busy
team rebuilds often while a finished app may not be rebuilt for a year.

**A tag can stop being rebuilt.** Pinning `nginx:1.28` looks careful, but once that branch left
support the tag was frozen: in our test `nginx:1.28` was last built on 2026-04-07 and the scanner
found 166 fixable high or critical problems in it, while `nginx:stable` (1.30.6, built
2026-11-05) had 2. Pin to a line that is still maintained (`stable`, a supported major like
`postgres:18-trixie`, a distribution codename), and check the image's `Created` date now and
then. The rule for every image, your own app's included, is in [first-deploy.md](first-deploy.md).

**A database major version is not an image tag change.** Moving a container from `postgres:16`
to `postgres:17` on the same data volume fails to start, with `FATAL: database files are
incompatible with server` and `The data directory was initialized by PostgreSQL version 16`.
It needs a dump and restore or `pg_upgrade`, after a tested backup; [databases.md](databases.md) covers it.

The app's own dependencies follow the same rule: a lockfile, the ecosystem's audit tool (see
[before-it-goes-public.md](before-it-goes-public.md)), and a bot such as Dependabot or Renovate
that opens a pull request for each update so the tests run before anything ships.

## A distribution release upgrade

Plan one before the release reaches end of life, not after. The sequence:

1. **Snapshot or back up first,** and know the way back: a provider snapshot of the disk, or a
   backup you have restored once. Taking a snapshot may cost money; ask.
2. **Read the release notes** for the new version, the part about upgrading in particular
   (Debian's "Issues to be aware of", Ubuntu's release notes). They list removed packages,
   changed defaults and the order of steps.
3. **Expect these to break:** the language runtime's major version (Debian 12 ships Python 3.11
   and PHP 8.2; Ubuntu 24.04 ships Python 3.12 and PHP 8.3), a database major version from the
   distribution's packages, third-party repositories that have no build for the new release yet,
   config files you edited (the upgrade asks whether to keep yours), and anything built against
   the old libraries.
4. **Upgrade in a maintenance window,** with the person's yes, from a console or a session that
   survives a dropped SSH connection (`tmux`, or the provider's web console).
5. **Check** from outside, `systemctl --failed`, the app's logs, and the backups still running.

Debian 12 to 13 is a codename change in the apt sources and two upgrade passes. It ran cleanly in
a `debian:12` container (no kernel or boot in a container, so that part was not tested):

```
grep -rl bookworm /etc/apt/sources.list /etc/apt/sources.list.d/
sed -i 's/bookworm/trixie/g' /etc/apt/sources.list.d/debian.sources   # and any file found above
apt update && apt upgrade --without-new-pkgs && apt full-upgrade
cat /etc/debian_version                                                 # 13.x
```

On Ubuntu, `do-release-upgrade` does the work and moves between LTS releases (the default
`Prompt=lts` in `/etc/update-manager/release-upgrades`). `do-release-upgrade -c` only checks; on
24.04 it reported `New release '26.04.1 LTS' available`. On AlmaLinux and Rocky there is no
in-place path supported by the distribution between major versions; the ELevate project offers
one, which we did not run.

**When rebuilding is safer.** Build a new server on the new release and move to it when the old
one was configured by hand over years, when it is two releases behind, when the app already runs
in containers, or when the person cannot afford a failed upgrade. Deploy to the new server, test
it, switch DNS, and keep the old one for a week as the way back. It costs a second server for a
while and buys a rollback that is a DNS change.

## Language runtimes

The distribution's runtime gets security fixes for the life of the release, but its major
version is frozen: Node.js 18 on both Debian 12 and Ubuntu 24.04, which upstream no longer
supports, while AlmaLinux 9 offers newer streams (`dnf module list nodejs` listed 18 to 24). For
an app that needs a current runtime, prefer the language's official container image
(`node:22-slim`, `python:3.12-slim`) and rebuild it as above, or the vendor's signed repository,
remembering that such a repository is outside the automatic origins. Leave the system Python
alone; the distribution's own tools depend on it. A runtime major upgrade goes like any other
change: bump the version in one place (the `FROM` line, `.nvmrc`, `.python-version`), run the
tests, deploy, and keep the previous image to roll back to.

## End-of-life dates, and where to read them today

Dates move and memory is out of date, so read them at the time:

```
debian-distro-info --supported --fullname     # package distro-info; the data ships offline
ubuntu-distro-info --supported --fullname
cat /usr/share/distro-info/debian.csv         # columns: release, eol, eol-lts, eol-elts
grep SUPPORT_END /etc/os-release              # present on AlmaLinux 9, not on Debian or Ubuntu
```

What that data said on 2026-11-12: Debian 12's regular security support ended on 2026-07-11 and
its LTS (a volunteer team covering fewer packages and architectures) runs to 2028-06-30; Debian
13 has been out since 2025-08-09. Ubuntu 24.04's standard support runs to 2029-05-31, and 26.04
LTS came out on 2026-04-23. AlmaLinux 9 reports `SUPPORT_END=2032-06-01`. For runtimes,
databases and everything else, the vendor's own page or endoflife.date
(`https://endoflife.date/nodejs`, `/python`, `/postgresql`) lists the dates in one place.

## Traps

- **"Unattended upgrades are on" without looking.** Read `20auto-upgrades` and run the dry run;
  the timers can be disabled or the package missing.
- **Updates installed, never applied.** The kernel, glibc and OpenSSL are fixed only after a
  reboot or a restart of what uses them. Check for a pending reboot, not only for updates.
- **The reboot flag on Debian.** Without `unattended-upgrades` nothing writes it; compare the
  kernels instead.
- **A frozen tag.** A version tag for a branch out of support is never rebuilt again; scan it
  and check its date.
- **Upgrading the distribution over SSH alone.** A dropped connection mid-upgrade leaves dpkg
  half-done. Use `tmux` or the provider's console.
- **Waiting on a broken mirror.** An hour of `apt` at a few kB/s is a mirror problem more often
  than a network one; compare it with the main archive and switch.
- **Upgrading after end of life.** Mirrors move old releases to archives and the upgrade path
  gets harder each month. Put the date in the hand-over.

## Done means

- Security updates install on their own, shown by the dry run or `systemctl list-timers` and a
  line in the log.
- Pending reboots are visible and done at a time the person chose, with the site checked after.
- Images are rebuilt on a schedule and scanned, and nothing runs on a frozen tag.
- The distribution's and runtime's end-of-life dates are in the hand-over, with the plan for
  the next upgrade.

Checked against: unattended-upgrades 2.9.1 and needrestart 3.6 on debian:12 and ubuntu:24.04,
dnf 4.14.0 with dnf-automatic on almalinux:9 (9.8), distro-info-data 0.58+deb12u7 and
2026.10.12, Trivy 0.68.1, PostgreSQL 16 and 17.7 images; the mirror switch on ubuntu:24.04
(arm64, `ports.ubuntu.com`) and debian:12, dnf `fastestmirror` on almalinux:9, 2026-11-12.
