#!/usr/bin/env python3
"""A read-only look at the Linux server this runs on: facts, findings and what was not checked.

What it does: reads the distribution, pending updates and a pending reboot (Debian and Ubuntu,
and the RHEL family), the SSH settings that matter (from sshd -T when it is allowed, else from the
config files with the first value winning), the firewall (ufw, firewalld, nftables, iptables;
IPv4 and IPv6 apart, and without root the ruleset /etc/nftables.conf loads),
listening sockets (database and cache ports bound to all addresses are flagged), failed systemd
units, disk and inode use, memory and swap, time sync, Docker containers publishing ports on all
addresses, and whether automatic security updates are set up. Each finding has a severity, the
fact and the command that shows it. Whatever needs root and could not be read is listed as not
checked, with the command to run instead.
What it never does: change anything (as root, dnf's own log files go to a temporary folder that
is removed), refresh package lists, ask for sudo or a password, use the network, or print host
names, IP addresses, user names or key material (they are replaced with placeholders). Printed
as they are: ports, well-known mount points, and the names of failed units and of containers,
since you need them to act, limited to the characters such names can hold; they may name the
person's project. The distribution's name is built from its ID and version, never copied from
the free text of /etc/os-release. Whether the release is still supported is not judged: no
end-of-life dates are built in.
It works when read from standard input, with Python 3.9 and nothing installed:
    ssh <host> python3 - < server_audit.py
    ssh <host> python3 - --json < server_audit.py

Usage: python server_audit.py [--json]
"""
from __future__ import annotations

import argparse
import glob as globbing
import json
import os
import platform
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tempfile

MAX_OUTPUT = 1024 * 1024
SBIN_DIRS = ["/usr/sbin", "/sbin", "/usr/local/sbin"]
AREAS = ["updates", "reboot", "ssh", "firewall", "listening", "failed_units", "disk", "memory", "time", "docker",
         "auto_updates"]
SEVERITIES = ("high", "medium", "low")

CMD = {
    "apt": ["apt-get", "-s", "-o", "Debug::NoLocking=1", "upgrade"],
    "dnf_updates": ["dnf", "-C", "-q", "check-update"],
    "dnf_security": ["dnf", "-C", "-q", "updateinfo", "list", "--security"],
    "needs_restarting": ["needs-restarting", "-r"],
    "sshd_T": ["sshd", "-T"],
    "ufw": ["ufw", "status"],
    "firewalld": ["firewall-cmd", "--state"],
    "nft": ["nft", "list", "ruleset"],
    "iptables": ["iptables", "-S"],
    "ip6tables": ["ip6tables", "-S"],
    "ss": ["ss", "-H", "-tuln"],
    "failed": ["systemctl", "--failed", "--no-legend", "--plain"],
    "timedatectl": ["timedatectl", "show", "-p", "NTPSynchronized", "--value"],
    "timedatectl_status": ["timedatectl", "status"],
    "chronyc": ["chronyc", "tracking"],
    "docker": ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
    "dpkg_uu": ["dpkg-query", "-W", "-f", "${Status}", "unattended-upgrades"],
    "apt_config": ["apt-config", "dump"],
    "rpm_dnf_automatic": ["rpm", "-q", "dnf-automatic"],
    "rpm_dnf5_automatic": ["rpm", "-q", "dnf5-plugin-automatic"],
}

DB_PORTS = {
    3306: "MySQL or MariaDB", 5432: "PostgreSQL", 6379: "Redis", 6380: "Redis", 27017: "MongoDB",
    11211: "Memcached", 9200: "Elasticsearch or OpenSearch", 9300: "Elasticsearch cluster", 5984: "CouchDB",
    9042: "Cassandra", 8086: "InfluxDB", 26257: "CockroachDB", 1433: "SQL Server", 1521: "Oracle",
    2379: "etcd", 5672: "RabbitMQ", 15672: "RabbitMQ management", 8123: "ClickHouse", 7474: "Neo4j",
    28015: "RethinkDB", 6333: "Qdrant", 19530: "Milvus",
}
WEB_PORTS = {80, 443}
REAL_FILESYSTEMS = {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs", "vfat", "exfat",
                    "ntfs", "ntfs3", "bcachefs", "nilfs2"}
# Mount points printed as they are; any other is named only by a number, since a path can hold a name.
KNOWN_MOUNTS = {"/", "/boot", "/boot/efi", "/var", "/var/lib", "/var/lib/docker", "/var/lib/containerd",
                "/var/lib/mysql", "/var/lib/postgresql", "/var/log", "/srv", "/opt", "/tmp", "/usr", "/data",
                "/mnt", "/backup", "/backups", "/" + "home"}
SSHD_DEFAULTS = {"permitrootlogin": "prohibit-password", "passwordauthentication": "yes",
                 "kbdinteractiveauthentication": "yes", "permitemptypasswords": "no", "usepam": "no",
                 "pubkeyauthentication": "yes", "port": "22"}
SSHD_NAMES = {"permitrootlogin": "PermitRootLogin", "passwordauthentication": "PasswordAuthentication",
              "kbdinteractiveauthentication": "KbdInteractiveAuthentication",
              "permitemptypasswords": "PermitEmptyPasswords", "usepam": "UsePAM",
              "pubkeyauthentication": "PubkeyAuthentication", "port": "Port"}
SSH_COMMAND = "sudo sshd -T | grep -Ei 'permitrootlogin|passwordauthentication|kbdinteractive|emptypasswords|usepam'"

EPILOG = """\
Areas: updates, reboot, ssh, firewall, listening, failed_units, disk, memory, time, docker,
auto_updates. Each area is "checked" (with facts) or "not checked" (with the reason and the
command that would show it, usually with sudo). Findings carry a severity (high, medium, low),
the fact and the command that shows it.
Package counts come from the package lists and cache as they are on the server; nothing is
refreshed, so they can be out of date. SSH settings read from files follow sshd's own rule (the
first value read wins, Include files are read where the Include line stands) and leave out Match
blocks.
Host names, IP addresses, user names, e-mail addresses and keys are replaced with placeholders.
Exit codes: 0 no findings, 1 findings, 2 no findings but most areas could not be checked (run
it again as root for a full picture), also for bad usage.
Needs Python 3.9 or newer, standard library only.
"""


class Parser(argparse.ArgumentParser):
    """argparse that reports a usage error as one line on stderr and exits 2."""

    def error(self, message):
        print(f"usage error: {' '.join(message.split())} (see --help)", file=sys.stderr)
        sys.exit(2)


# ------------------------------------------------------------------ the machine (tests replace this)

class System:
    """Everything the audit reads from the machine. Nothing here writes."""

    def __init__(self):
        self.env = dict(os.environ, LC_ALL="C", LANG="C")
        self.path = os.pathsep.join([os.environ.get("PATH", "")] + SBIN_DIRS)

    def which(self, name: str) -> bool:
        return shutil.which(name, path=self.path) is not None

    def run(self, argv: list[str], timeout: float = 30.0) -> tuple:
        """(exit code, stdout, stderr); exit code None when the program is missing or did not finish."""
        program = shutil.which(argv[0], path=self.path)
        if not program:
            return None, "", ""
        try:
            proc = subprocess.run([program] + list(argv[1:]), stdin=subprocess.DEVNULL, capture_output=True,
                                  timeout=timeout, env=self.env)
        except (subprocess.TimeoutExpired, OSError):
            return None, "", ""
        return (proc.returncode, proc.stdout[:MAX_OUTPUT].decode("utf-8", "replace"),
                proc.stderr[:MAX_OUTPUT].decode("utf-8", "replace"))

    def read(self, path: str) -> str:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read(MAX_OUTPUT)

    def exists(self, path: str) -> bool:
        return os.path.exists(path)

    def glob(self, pattern: str) -> list[str]:
        return sorted(globbing.glob(pattern))

    def statvfs(self, path: str):
        return os.statvfs(path)

    def euid(self) -> int:
        return os.geteuid() if hasattr(os, "geteuid") else -1

    def kernel(self) -> str:
        return platform.release()

    def platform(self) -> str:
        return platform.system()

    def identities(self) -> list[str]:
        names = {socket.gethostname()}
        try:
            names.add(os.uname().nodename)
        except AttributeError:
            pass
        try:
            names.add(self.read("/etc/hostname").strip())
        except OSError:
            pass
        names |= {n.split(".")[0] for n in names}
        for var in ("USER", "LOGNAME", "SUDO_USER"):
            names.add(os.environ.get(var, ""))
        try:
            import pwd
            names.add(pwd.getpwuid(os.getuid()).pw_name)
        except (ImportError, KeyError, AttributeError):
            pass
        return sorted(n for n in names if n)


# ------------------------------------------------------------------ results

class Area:
    def __init__(self, name: str):
        self.name = name
        self.status = "checked"
        self.facts: list[str] = []
        self.findings: list[dict] = []
        self.reason = None
        self.command = None

    def fact(self, text: str) -> None:
        self.facts.append(text)

    def finding(self, severity: str, fact: str, command: str) -> None:
        self.findings.append({"severity": severity, "area": self.name, "fact": fact, "command": command})

    def skip(self, reason: str, command: str) -> "Area":
        self.status, self.reason, self.command = "not checked", reason, command
        return self

    def as_dict(self) -> dict:
        return {"status": self.status, "facts": self.facts, "reason": self.reason, "command": self.command}


def _first_line(text: str) -> str:
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def _pct(part: float, whole: float) -> int:
    return int(round(100.0 * part / whole)) if whole else 0


def _natural(text: str) -> list:
    return [int(p) if p.isdigit() else p for p in re.split(r"(\d+)", text)]


# ------------------------------------------------------------------ the system

def read_os(s) -> dict:
    info = {"name": "unknown", "id": None, "version": None, "family": "unknown", "kernel": None}
    try:
        info["kernel"] = s.kernel()
    except OSError:
        pass
    try:
        text = s.read("/etc/os-release")
    except OSError:
        if s.platform() != "Linux":
            info["name"] = f"not Linux ({s.platform()})"
        return info
    fields = {}
    for line in text.splitlines():
        key, eq, value = line.partition("=")
        if eq:
            try:
                fields[key.strip()] = " ".join(shlex.split(value)) if value.strip() else ""
            except ValueError:
                fields[key.strip()] = value.strip().strip("\"'")
    info["id"], info["version"] = fields.get("ID"), fields.get("VERSION_ID")
    # The name is built from known parts, never copied from PRETTY_NAME or NAME: those are free text
    # that anyone with root on the server could set, and the report is read by an agent.
    version = info["version"] if re.fullmatch(r"[0-9][0-9.]{0,15}", info["version"] or "") else None
    codename = fields.get("VERSION_CODENAME", "")
    known = DISTRO_NAMES.get((info["id"] or "").lower())
    if known:
        info["name"] = known + (f" {version}" if version else "") + \
            (f" ({codename})" if re.fullmatch(r"[a-z]{2,20}", codename) else "")
    else:
        info["name"] = "an unrecognised distribution"
    kin = set((fields.get("ID", "") + " " + fields.get("ID_LIKE", "")).lower().split())
    if kin & {"debian", "ubuntu"}:
        info["family"] = "debian"
    elif kin & {"rhel", "fedora", "centos", "almalinux", "rocky", "ol", "amzn"}:
        info["family"] = "rhel"
    return info


DISTRO_NAMES = {"debian": "Debian GNU/Linux", "ubuntu": "Ubuntu", "almalinux": "AlmaLinux", "rocky": "Rocky Linux",
                "rhel": "Red Hat Enterprise Linux", "centos": "CentOS Stream", "fedora": "Fedora Linux",
                "ol": "Oracle Linux", "amzn": "Amazon Linux", "linuxmint": "Linux Mint", "raspbian": "Raspbian",
                "opensuse-leap": "openSUSE Leap", "sles": "SUSE Linux Enterprise Server", "alpine": "Alpine Linux",
                "arch": "Arch Linux"}


def _unsupported(area: Area, info: dict, command: str) -> Area:
    return area.skip(f"the distribution family was not recognised ({info['name']}); only Debian and Ubuntu and the "
                     "RHEL family are covered", command)


def area_updates(s, info) -> Area:
    a = Area("updates")
    if info["family"] == "debian":
        rc, out, _ = s.run(CMD["apt"], timeout=120)
        if rc is None or rc != 0:
            return a.skip("apt-get -s upgrade did not run here", "apt list --upgradable")
        lines = [line for line in out.splitlines() if line.startswith("Inst ")]
        security = [line for line in lines if "security" in line.lower()]
        a.fact(f"{len(lines)} packages can be upgraded, {len(security)} of them from a security source "
               "(from the package lists as last downloaded; nothing was refreshed)")
        command = "apt list --upgradable"
    elif info["family"] == "rhel":
        tool = "dnf" if s.which("dnf") else "yum"
        # As root, dnf writes its own log files under /var/log; point them at a folder removed below,
        # so the audit changes nothing at all.
        logdir = tempfile.mkdtemp(prefix="server-audit-") if tool == "dnf" and s.euid() == 0 else None
        opts = [f"--setopt=logdir={logdir}"] if logdir else []
        try:
            rc, out, _ = s.run([tool] + opts + CMD["dnf_updates"][1:], timeout=120)
            rc_sec, out_sec, _ = s.run([tool] + opts + CMD["dnf_security"][1:], timeout=120)
        finally:
            if logdir:
                shutil.rmtree(logdir, ignore_errors=True)
        if rc is None or rc not in (0, 100):
            who = "" if s.euid() == 0 else " readable by this user"
            return a.skip(f"{tool} found no package cache{who} (nothing was refreshed, so nothing was counted)",
                          f"sudo {tool} check-update")
        packages = []
        for line in out.splitlines():
            if line.startswith(("Obsoleting", "Security:", "Last metadata")):
                if line.startswith("Obsoleting"):
                    break
                continue
            parts = line.split()
            if len(parts) == 3 and "." in parts[0]:
                packages.append(parts[0])
        security = {p.split()[2] for p in out_sec.splitlines() if len(p.split()) >= 3} if rc_sec == 0 else set()
        known = "" if rc_sec == 0 else " (security advisories could not be read)"
        a.fact(f"{len(packages)} packages can be upgraded; {len(security)} have a security advisory{known} "
               "(from the package cache as it is; nothing was refreshed)")
        lines = packages
        command = f"{tool} check-update; {tool} updateinfo list --security"
    else:
        return _unsupported(a, info, "apt list --upgradable, or dnf check-update")
    if security:
        a.finding("high", f"{len(security)} security update(s) are waiting to be installed", command)
    elif lines:
        a.finding("low", f"{len(lines)} update(s) are waiting to be installed", command)
    return a


def _kernel_check(s, a: Area, info: dict) -> bool:
    kernels = [os.path.basename(p)[len("vmlinuz-"):] for p in s.glob("/boot/vmlinuz-*")]
    kernels = [k for k in kernels if "rescue" not in k]
    running = info.get("kernel")
    if not kernels or not running:
        return False
    newest = max(kernels, key=_natural)
    if newest != running and _natural(newest) > _natural(running):
        a.finding("medium", f"a newer kernel ({newest}) is installed than the one running ({running}); "
                            "a reboot loads it", "uname -r; ls /boot")
    else:
        a.fact(f"the running kernel ({running}) is the newest installed")
    return True


def area_reboot(s, info) -> Area:
    a = Area("reboot")
    if info["family"] == "debian":
        flag = next((p for p in ("/run/reboot-required", "/var/run/reboot-required") if s.exists(p)), None)
        if flag:
            try:
                count = len([x for x in s.read(flag + ".pkgs").splitlines() if x.strip()])
                why = f" ({count} package(s) asked for it)"
            except OSError:
                why = ""
            a.finding("medium", f"a reboot is pending{why}", "cat /run/reboot-required.pkgs")
            return a
        a.fact("no reboot is flagged in /run/reboot-required")
        _kernel_check(s, a, info)
        return a
    if info["family"] == "rhel":
        rc, out, _ = s.run(CMD["needs_restarting"], timeout=60)
        if rc == 1:
            a.finding("medium", "a reboot is pending (needs-restarting -r says core libraries or the kernel "
                                "were updated since boot)", "needs-restarting -r")
            return a
        if rc == 0:
            a.fact("needs-restarting -r reports no reboot needed")
            return a
        if _kernel_check(s, a, info):
            return a
        return a.skip("needs-restarting is not installed and the installed kernels could not be read",
                      "needs-restarting -r (from dnf-utils), or compare uname -r with rpm -q kernel")
    return _unsupported(a, info, "ls /run/reboot-required, or needs-restarting -r")


# ------------------------------------------------------------------ SSH

def _sshd_line(line: str):
    line = line.split("#", 1)[0].strip()
    if not line:
        return None, None
    parts = re.split(r"\s*=\s*|\s+", line, maxsplit=1)
    return parts[0].lower(), (parts[1].strip() if len(parts) > 1 else "")


def sshd_from_files(s, main: str = "/etc/ssh/sshd_config") -> tuple:
    """(values, the file each value came from, notes) as sshd reads them: the first value wins, an Include is
    read where it stands, and everything after a Match line belongs to that Match block. Raises
    PermissionError when a file cannot be read."""
    values, sources, notes = {}, {}, []

    def read(path: str, depth: int) -> None:
        if depth > 8:
            return
        text = s.read(path)
        for raw in text.splitlines():
            key, value = _sshd_line(raw)
            if key is None:
                continue
            if key == "match":
                notes.append(f"{path} has Match blocks; the values inside them were not evaluated")
                return
            if key == "include":
                try:
                    patterns = shlex.split(value)
                except ValueError:
                    patterns = value.split()
                for pattern in patterns:
                    if not pattern.startswith("/"):
                        pattern = "/etc/ssh/" + pattern
                    for found in s.glob(pattern):
                        read(found, depth + 1)
                continue
            if key == "challengeresponseauthentication":
                key = "kbdinteractiveauthentication"
            if key not in values and value:
                values[key] = value.split()[0].lower()
                sources[key] = path

    read(main, 0)
    return values, sources, notes


def area_ssh(s, info) -> Area:
    a = Area("ssh")
    has_sshd = s.which("sshd")
    if not has_sshd and not s.exists("/etc/ssh/sshd_config"):
        a.fact("no SSH server (sshd) is installed")
        return a
    rc, out, _ = s.run(CMD["sshd_T"], timeout=30)
    sources: dict = {}
    if rc == 0 and out.strip():
        values = {}
        for line in out.splitlines():
            key, value = _sshd_line(line)
            if key and value and key not in values:
                values[key] = value.split()[0].lower()
        a.fact("settings from sshd -T (the values sshd uses)")
    else:
        try:
            values, sources, notes = sshd_from_files(s)
        except PermissionError:
            return a.skip("the sshd config can be read only by root here", SSH_COMMAND)
        except OSError:
            return a.skip("the sshd config file was not found and sshd -T did not run", SSH_COMMAND)
        a.fact("settings from the config files, because sshd -T did not answer (it needs root and the host keys): "
               "the first value read wins, Include files are read where they stand")
        for note in notes:
            a.fact(note)

    def get(key: str) -> tuple:
        if key in values:
            where = sources.get(key)
            return values[key], f" (set in {where})" if where else ""
        return SSHD_DEFAULTS[key], " (the default; nothing sets it)"

    shown = []
    for key in ("port", "permitrootlogin", "passwordauthentication", "kbdinteractiveauthentication", "usepam",
                "permitemptypasswords"):
        value, where = get(key)
        shown.append(f"{SSHD_NAMES[key]} {value}{where}")
    a.fact("; ".join(shown))
    value, where = get("permitrootlogin")
    if value == "yes":
        a.finding("high", f"PermitRootLogin yes{where}: root can log in over SSH, with a password too when password "
                          "login is on", SSH_COMMAND)
    value, where = get("passwordauthentication")
    if value == "yes":
        a.finding("medium", f"PasswordAuthentication yes{where}: SSH accepts passwords, so the server is open to "
                            "password guessing", SSH_COMMAND)
    kbd, kbd_where = get("kbdinteractiveauthentication")
    pam, _ = get("usepam")
    if kbd == "yes" and pam == "yes":
        a.finding("medium", f"KbdInteractiveAuthentication yes{kbd_where} with UsePAM yes: PAM can ask for a "
                            "password this way even when PasswordAuthentication is no", SSH_COMMAND)
    value, where = get("permitemptypasswords")
    if value == "yes":
        a.finding("high", f"PermitEmptyPasswords yes{where}: an account with an empty password can log in",
                  SSH_COMMAND)
    return a


# ------------------------------------------------------------------ network

def _service(s, name: str) -> str:
    rc, out, _ = s.run(["systemctl", "is-active", name], timeout=15)
    word = out.strip().splitlines()[0] if out.strip() else ""
    if rc is not None and word in ("active", "reloading", "activating"):
        return "active"
    if rc is not None and word in ("inactive", "failed", "deactivating"):
        return "inactive"
    return "unknown"


NFT_COUNTER_RE = re.compile(r"\bcounter(?:\s+packets\s+\d+\s+bytes\s+\d+)?\s*")
NFT_DENY_RE = re.compile(r'^(?:log(?:\s+(?:prefix\s+"[^"]*"|level\s+\w+|flags\s+\S+|group\s+\d+))*\s+)?'
                         r"(?:drop|reject(?:\s+with\s+.+)?)$")
IPT_DENY_RE = re.compile(r"^-A INPUT(?:\s+-m comment --comment (?:\"[^\"]*\"|\S+))?\s+-j (?:DROP|REJECT)\b")


def _fail2ban(name: str) -> bool:
    return name.lower().startswith(("f2b", "fail2ban"))


NFT_FAMILIES = {"ip": ("ip", "inet"), "ip6": ("ip6", "inet")}


def nft_input_verdict(text: str, family: str | None = None) -> str:
    """'deny' when a base chain on the input hook drops by default (policy drop, or an unconditional drop or
    reject as its last rule), 'fail2ban' when the only input chains are fail2ban's, 'rules' when input chains
    exist without a default deny, 'none' when there is no input chain. fail2ban's tables and chains only ban
    listed addresses, so they never count as a firewall. family "ip" or "ip6" counts only the tables that
    filter that protocol (an inet table filters both); None counts every table."""
    stack, chains, current = [], [], None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("{"):
            words = line[:-1].split()
            if words[:1] == ["table"] and len(words) >= 2:
                # "table inet filter", or "table filter", whose family is ip.
                stack.append(("table", (words[1] if len(words) >= 3 else "ip", words[-1])))
            elif words[:1] == ["chain"] and len(words) >= 2:
                fam, table = next((n for k, n in reversed(stack) if k == "table"), ("ip", ""))
                current = {"table": table, "family": fam, "name": words[1], "input": False, "policy": None,
                           "rules": []}
                stack.append(("chain", words[1]))
            else:
                stack.append(("block", ""))
            continue
        if line == "}":
            if stack and stack.pop()[0] == "chain" and current is not None:
                chains.append(current)
                current = None
            continue
        if current is None or (stack and stack[-1][0] != "chain"):
            continue
        hook = re.match(r"type\s+filter\s+hook\s+input\b", line)
        if hook:
            current["input"] = True
            policy = re.search(r"\bpolicy\s+(\w+)", line)
            current["policy"] = policy.group(1) if policy else "accept"
            continue
        current["rules"].append(" ".join(NFT_COUNTER_RE.sub("", line).split()))
    inputs = [c for c in chains if c["input"] and (family is None or c["family"] in NFT_FAMILIES[family])]
    if not inputs:
        return "none"
    own = [c for c in inputs if not (_fail2ban(c["table"]) or _fail2ban(c["name"]))]
    for chain in own:
        rules = [r for r in chain["rules"] if r]
        if chain["policy"] in ("drop", "reject") or (rules and NFT_DENY_RE.match(rules[-1])):
            return "deny"
    if all(not c["rules"] or all("f2b" in r for r in c["rules"]) for c in own):
        return "fail2ban" if len(own) < len(inputs) or any(c["rules"] for c in own) else "none"
    return "rules"


def iptables_input_verdict(text: str) -> str:
    """The same answer for iptables -S: 'deny', 'fail2ban', 'rules' or 'none'."""
    if re.search(r"^-P INPUT (?:DROP|REJECT)\b", text, re.M):
        return "deny"
    rules = [line.strip() for line in text.splitlines() if line.startswith("-A INPUT ")]
    if not rules:
        return "none"
    if IPT_DENY_RE.match(rules[-1]):
        return "deny"
    if all(re.search(r"-j f2b-", r) for r in rules):
        return "fail2ban"
    return "rules"


VERDICT_WORDS = {"deny": "active", "none": "inactive",
                 "fail2ban": "only fail2ban's ban rules (they block listed addresses, not a firewall)",
                 "rules": "input rules, but no default deny"}


def _public_ipv6(s) -> bool | None:
    """Whether an interface has a global IPv6 address (scope 00 in /proc/net/if_inet6); None when unreadable."""
    try:
        text = s.read("/proc/net/if_inet6")
    except OSError:
        return None
    return any(len(f) >= 4 and f[3] == "00" for f in (line.split() for line in text.splitlines()))


def _nft_file(s) -> tuple:
    """(IPv4 word, IPv6 word) for the ruleset /etc/nftables.conf loads, which anyone may read; unknown when it
    includes other files."""
    try:
        text = s.read("/etc/nftables.conf")
    except OSError:
        return "unknown", "unknown"
    if re.search(r"^\s*include\s", text, re.M):
        return "unknown", "unknown"
    words = []
    for fam in ("ip", "ip6"):
        verdict = nft_input_verdict(text, fam)
        words.append("active" if verdict == "deny" else
                     "the nftables service runs, but /etc/nftables.conf drops nothing by default")
    return tuple(words)


def area_firewall(s, info) -> Area:
    a = Area("firewall")
    root = s.euid() == 0
    states = {}     # tool -> (IPv4 state, IPv6 state)
    if s.which("ufw"):
        if root:
            rc, out, _ = s.run(CMD["ufw"])
            word = ("active" if "Status: active" in out else "inactive" if "Status: inactive" in out else "unknown")
        else:
            try:
                enabled = re.search(r"^\s*ENABLED\s*=\s*(\w+)", s.read("/etc/ufw/ufw.conf"), re.M)
                word = "active" if enabled and enabled.group(1).lower() == "yes" else "inactive"
            except OSError:
                word = "unknown"
        states["ufw"] = (word, word)
    if s.which("firewall-cmd"):
        rc, out, _ = s.run(CMD["firewalld"])
        out = out.strip()
        word = "active" if out == "running" else "inactive" if out == "not running" else "unknown"
        states["firewalld"] = (word, word)
    if s.which("nft"):
        if root:
            rc, out, _ = s.run(CMD["nft"])
            states["nftables"] = ((VERDICT_WORDS[nft_input_verdict(out, "ip")],
                                   VERDICT_WORDS[nft_input_verdict(out, "ip6")]) if rc == 0 else ("unknown",) * 2)
        else:
            service = _service(s, "nftables")
            states["nftables"] = _nft_file(s) if service == "active" else (service, service)
    if s.which("iptables") and root:
        rc, out, _ = s.run(CMD["iptables"])
        v4 = VERDICT_WORDS[iptables_input_verdict(out)] if rc == 0 else "unknown"
        v6 = "unknown"
        if s.which("ip6tables"):
            rc, out, _ = s.run(CMD["ip6tables"])
            v6 = VERDICT_WORDS[iptables_input_verdict(out)] if rc == 0 else "unknown"
        states["iptables"] = (v4, v6)
    for tool, (v4, v6) in sorted(states.items()):
        a.fact(f"{tool}: {v4}" if v4 == v6 else f"{tool}: {v4} (IPv4); {v6} (IPv6)")
    command = "sudo ufw status verbose; sudo firewall-cmd --state; sudo nft list ruleset"
    if any(v4 == "active" for v4, _ in states.values()):
        if not any(v6 == "active" for _, v6 in states.values()):
            public = _public_ipv6(s)
            if public:
                a.finding("medium", "IPv4 is filtered but IPv6 is not: no IPv6 input chain drops what is not "
                          "allowed, and this server has a public IPv6 address", "sudo ip6tables -S; sudo nft list "
                          "ruleset")
            elif public is False:
                a.fact("IPv6: not filtered, and the server has no public IPv6 address now")
            else:
                a.fact("IPv6: not filtered; whether the server has a public IPv6 address could not be read")
        return a
    v4_states = {tool: v4 for tool, (v4, _) in states.items()}
    if not root and (not states or "unknown" in v4_states.values() or s.which("iptables")
                     or "nftables" in states):
        return a.skip("no firewall service was found active, but rules set by other means can be read only as root",
                      command)
    if "unknown" in v4_states.values():
        return a.skip("the state of " + ", ".join(k for k, v in v4_states.items() if v == "unknown") +
                      " could not be read", command)
    a.finding("medium", "no host firewall is active: no input chain drops what is not allowed (" +
              (", ".join(sorted(states)) or "no firewall tool installed") +
              "); only a provider firewall, if there is one, filters traffic", command)
    return a


def _scope(address: str) -> str:
    address = address.strip("[]").split("%", 1)[0].lower()
    if address in ("0.0.0.0", "*", "::", ""):
        return "all addresses"
    if address.startswith("127.") or address in ("::1", "localhost") or address.startswith("::ffff:127."):
        return "this machine only"
    return "a specific address"


def _hex_address(text: str) -> str:
    """An address from /proc/net (little-endian hex words) as text; only its scope is ever printed."""
    if len(text) == 8:
        return ".".join(str(int(text[i:i + 2], 16)) for i in (6, 4, 2, 0))
    words = [text[i:i + 8] for i in range(0, 32, 8)]
    raw = "".join("".join(w[j:j + 2] for j in (6, 4, 2, 0)) for w in words)
    groups = [raw[i:i + 4] for i in range(0, 32, 4)]
    if raw == "0" * 32:
        return "::"
    if raw == "0" * 31 + "1":
        return "::1"
    if raw.startswith("0" * 20 + "ffff"):
        tail = raw[24:]
        return "::ffff:" + ".".join(str(int(tail[i:i + 2], 16)) for i in (0, 2, 4, 6))
    return ":".join(groups)


def listening_sockets(s) -> tuple:
    """([(proto, port, scope)], source) from ss, or from /proc/net when ss is missing; None when neither works."""
    rc, out, _ = s.run(CMD["ss"])
    found = []
    if rc == 0:
        for line in out.splitlines():
            parts = line.split()
            if len(parts) < 5 or parts[1] not in ("LISTEN", "UNCONN"):
                continue
            address, _, port = parts[4].rpartition(":")
            if port.isdigit():
                found.append((parts[0], int(port), _scope(address)))
        return sorted(set(found)), "ss -tuln"
    read_any = False
    for proto in ("tcp", "tcp6", "udp", "udp6"):
        try:
            text = s.read(f"/proc/net/{proto}")
        except OSError:
            continue
        read_any = True
        for line in text.splitlines()[1:]:
            parts = line.split()
            if len(parts) < 4 or ":" not in parts[1]:
                continue
            local, remote, state = parts[1], parts[2], parts[3]
            listening = state == "0A" if proto.startswith("tcp") else (state == "07" and remote.endswith(":0000"))
            if not listening:
                continue
            address, port = local.split(":")
            try:
                found.append((proto.rstrip("6"), int(port, 16), _scope(_hex_address(address))))
            except ValueError:
                continue
    if not read_any:
        return None, None
    return sorted(set(found)), "/proc/net (ss is not installed)"


def area_listening(s, info) -> Area:
    a = Area("listening")
    sockets, source = listening_sockets(s)
    if sockets is None:
        return a.skip("neither ss nor /proc/net could be read", "ss -tlnp")
    a.fact(f"read from {source}")
    shown = [f"{proto} {port} ({scope})" for proto, port, scope in sockets]
    a.fact("ports: " + (", ".join(shown[:80]) if shown else "none"))
    flagged = set()
    for proto, port, scope in sockets:
        if scope == "all addresses" and port in DB_PORTS and port not in flagged:
            flagged.add(port)
            a.finding("high", f"{DB_PORTS[port]} (port {port}) listens on all addresses; anyone who can reach the "
                              "server can try to log in to it", f"ss -tlnp | grep ':{port} '")
    return a


def area_failed_units(s, info) -> Area:
    a = Area("failed_units")
    rc, out, stderr = s.run(CMD["failed"])
    if rc is None or rc != 0 or "not been booted with systemd" in stderr:
        return a.skip("systemd is not running here, or systemctl did not answer", "systemctl --failed")
    units = []
    for line in out.splitlines():
        parts = [p for p in line.split() if p not in ("●", "*")]
        if parts and re.fullmatch(r"[\w@.:\\-]+\.(?:service|socket|timer|mount|path|target|scope|slice|swap|"
                                  r"automount|device)", parts[0]):
            units.append(parts[0])
    if units:
        a.finding("medium", f"{len(units)} systemd unit(s) failed: " + ", ".join(units[:20]),
                  "systemctl --failed; journalctl -u <unit> -n 50")
    else:
        a.fact("no failed systemd units")
    return a


# ------------------------------------------------------------------ disk, memory, time

def area_disk(s, info) -> Area:
    a = Area("disk")
    mounts = [("/", "/")]
    try:
        for line in s.read("/proc/mounts").splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[2] in REAL_FILESYSTEMS:
                point = re.sub(r"\\([0-7]{3})", lambda m: chr(int(m.group(1), 8)), parts[1])
                # Files bind-mounted into system folders (a container's /etc/hosts) are not disks of their own.
                if not point.startswith(("/etc/", "/proc/", "/sys/", "/dev/", "/run/")):
                    mounts.append((parts[0], point))
    except OSError:
        pass
    seen_devices, seen_points, seen_fs, other = set(), set(), set(), 0
    measured = 0
    for device, point in mounts:
        if point in seen_points or (device != "/" and device in seen_devices):
            continue
        seen_points.add(point)
        seen_devices.add(device)
        try:
            v = s.statvfs(point)
        except OSError:
            continue
        # A file system mounted twice (a bind mount, a container's own files) is measured once.
        fingerprint = getattr(v, "f_fsid", 0) or (v.f_blocks, v.f_files, v.f_frsize, point)
        if not v.f_blocks or fingerprint in seen_fs:
            continue
        seen_fs.add(fingerprint)
        measured += 1
        if point in KNOWN_MOUNTS:
            label, where = point, point
        else:
            other += 1
            label, where = f"another mount point ({other})", ""
        used = v.f_blocks - v.f_bfree
        space = _pct(used, used + v.f_bavail)
        inodes = _pct(v.f_files - v.f_ffree, v.f_files) if v.f_files else None
        a.fact(f"{label}: {space}% of space used" + (f", {inodes}% of inodes" if inodes is not None else ""))
        if space >= 80:
            a.finding("high" if space >= 90 else "medium", f"{label} is {space}% full", f"df -h {where}".strip())
        if inodes is not None and inodes >= 80:
            a.finding("high" if inodes >= 90 else "medium", f"{inodes}% of the inodes on {label} are used (new "
                                                            "files fail when they run out)", f"df -i {where}".strip())
        if measured >= 30:
            break
    if not measured:
        return a.skip("the file systems could not be measured", "df -h; df -i")
    return a


def area_memory(s, info) -> Area:
    a = Area("memory")
    try:
        text = s.read("/proc/meminfo")
    except OSError:
        return a.skip("/proc/meminfo could not be read", "free -h")
    kb = {}
    for line in text.splitlines():
        m = re.match(r"^(\w+):\s+(\d+)", line)
        if m:
            kb[m.group(1)] = int(m.group(2))
    total = kb.get("MemTotal")
    if not total:
        return a.skip("/proc/meminfo has no total", "free -h")
    available = kb.get("MemAvailable", kb.get("MemFree", 0) + kb.get("Buffers", 0) + kb.get("Cached", 0))
    swap_total, swap_free = kb.get("SwapTotal", 0), kb.get("SwapFree", 0)
    gib = 1024 * 1024
    swap_text = (f"swap {swap_total / gib:.1f} GiB, {_pct(swap_total - swap_free, swap_total)}% used" if swap_total
                 else "no swap")
    a.fact(f"memory {total / gib:.1f} GiB, {_pct(available, total)}% available; {swap_text}")
    if _pct(available, total) < 10:
        a.finding("medium", f"only {_pct(available, total)}% of memory is available", "free -h; ps aux --sort=-rss | head")
    if not swap_total and total < 4 * gib:
        a.finding("low", "no swap on a server with less than 4 GiB of memory: a short spike makes the kernel kill a "
                         "process instead of slowing down", "swapon --show; free -h")
    elif swap_total and _pct(swap_total - swap_free, swap_total) > 50:
        a.finding("low", f"{_pct(swap_total - swap_free, swap_total)}% of swap is in use, so memory is short",
                  "free -h; vmstat 1 5")
    return a


def area_time(s, info) -> Area:
    a = Area("time")
    synced = None
    rc, out, _ = s.run(CMD["timedatectl"])
    if rc == 0 and out.strip() in ("yes", "no"):
        synced, source = out.strip() == "yes", "timedatectl"
    else:
        rc, out, _ = s.run(CMD["timedatectl_status"])
        m = re.search(r"(?:System clock synchronized|NTP synchronized):\s*(yes|no)", out) if rc == 0 else None
        if m:
            synced, source = m.group(1) == "yes", "timedatectl"
        else:
            rc, out, _ = s.run(CMD["chronyc"])
            m = re.search(r"Leap status\s*:\s*(.+)", out) if rc == 0 else None
            if m:
                synced, source = m.group(1).strip().lower() == "normal", "chronyc tracking"
    if synced is None:
        return a.skip("neither timedatectl nor chronyc answered", "timedatectl; chronyc tracking")
    a.fact(f"clock synchronised: {'yes' if synced else 'no'} (from {source})")
    if not synced:
        a.finding("medium", "the clock is not synchronised; certificates, logs, tokens and cron depend on it",
                  "timedatectl; chronyc tracking")
    return a


# ------------------------------------------------------------------ Docker and automatic updates

DOCKER_PORT_RE = re.compile(r"^(?P<addr>\[?[0-9A-Fa-f:.]*\]?):(?P<port>\d+)(?:-\d+)?->(?P<inner>\d+)(?:-\d+)?/"
                            r"(?P<proto>tcp|udp|sctp)$")


def area_docker(s, info) -> Area:
    a = Area("docker")
    if not s.which("docker"):
        a.fact("Docker is not installed")
        return a
    rc, out, stderr = s.run(CMD["docker"])
    if rc is None or rc != 0:
        if "permission denied" in stderr.lower():
            return a.skip("reading Docker needs root or membership of the docker group", "sudo docker ps")
        if "cannot connect" in stderr.lower():
            a.fact("Docker is installed but its daemon is not running")
            return a
        return a.skip("docker ps did not answer", "sudo docker ps")
    containers = 0
    for line in out.splitlines():
        if not line.strip():
            continue
        containers += 1
        name, _, ports = line.partition("\t")
        name = name.strip() if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,62}", name.strip()) else "a container"
        public, specific = set(), set()
        for item in ports.split(","):
            m = DOCKER_PORT_RE.match(item.strip())
            if not m:
                continue
            port, inner = int(m.group("port")), int(m.group("inner"))
            if _scope(m.group("addr")) == "all addresses":
                public.add((port, inner))
            elif _scope(m.group("addr")) == "a specific address":
                specific.add(port)
        if public or specific:
            parts = []
            if public:
                parts.append("on all addresses " + ", ".join(str(p) for p, _ in sorted(public)))
            if specific:
                parts.append("on a specific address " + ", ".join(str(p) for p in sorted(specific)))
            a.fact(f"{name} publishes " + "; ".join(parts))
        for port, inner in sorted(public):
            db = DB_PORTS.get(port) or DB_PORTS.get(inner)
            if db:
                a.finding("high", f"container {name} publishes {db} (port {port}) on all addresses; Docker's own "
                                  "rules let it through even when ufw or firewalld would block it",
                          "docker ps --format '{{.Names}} {{.Ports}}'")
            elif port not in WEB_PORTS:
                a.finding("low", f"container {name} publishes port {port} on all addresses; Docker's rules bypass "
                                 "ufw and firewalld, so bind it to 127.0.0.1 unless it is meant to be public",
                          "docker ps --format '{{.Names}} {{.Ports}}'")
    a.fact(f"{containers} running container(s)")
    return a


def area_auto_updates(s, info) -> Area:
    a = Area("auto_updates")
    if info["family"] == "debian":
        rc, out, _ = s.run(CMD["dpkg_uu"])
        if rc is None:
            return a.skip("dpkg-query did not run", "apt-config dump | grep Periodic")
        if "install ok installed" not in out:
            a.finding("medium", "automatic security updates are not set up: unattended-upgrades is not installed",
                      "dpkg -l unattended-upgrades")
            return a
        rc, out, _ = s.run(CMD["apt_config"])
        if rc != 0:
            out = ""
            for path in s.glob("/etc/apt/apt.conf.d/*"):
                try:
                    out += s.read(path)
                except OSError:
                    continue
        values = re.findall(r'APT::Periodic::Unattended-Upgrade\s+"(\d+)"', out)
        if values and values[-1] != "0":
            a.fact("unattended-upgrades is installed and switched on")
        else:
            a.finding("medium", "unattended-upgrades is installed but not switched on "
                                "(APT::Periodic::Unattended-Upgrade is not 1)", "apt-config dump | grep Periodic")
        return a
    if info["family"] == "rhel":
        rc, out, _ = s.run(CMD["rpm_dnf_automatic"])
        if rc != 0:
            rc5, _, _ = s.run(CMD["rpm_dnf5_automatic"])
            if rc is None and rc5 is None:
                return a.skip("rpm did not run", "rpm -q dnf-automatic")
            if rc5 != 0:
                a.finding("medium", "automatic security updates are not set up: dnf-automatic is not installed",
                          "rpm -q dnf-automatic")
                return a
        timers = {}
        for timer in ("dnf-automatic-install.timer", "dnf-automatic.timer", "dnf5-automatic.timer"):
            rc_t, out_t, _ = s.run(["systemctl", "is-enabled", timer])
            timers[timer] = out_t.strip() if rc_t is not None else "unknown"
        if timers["dnf-automatic-install.timer"] == "enabled":
            a.fact("dnf-automatic-install.timer is enabled: updates are downloaded and applied")
            return a
        if "enabled" in (timers["dnf-automatic.timer"], timers["dnf5-automatic.timer"]):
            try:
                conf = s.read("/etc/dnf/automatic.conf")
            except OSError:
                conf = ""
            apply = re.search(r"^\s*apply_updates\s*=\s*(\w+)", conf, re.M)
            if apply and apply.group(1).lower() in ("yes", "true", "1"):
                a.fact("dnf-automatic is enabled and applies updates")
            else:
                a.finding("medium", "dnf-automatic runs but only downloads updates (apply_updates is not yes)",
                          "grep -E 'apply_updates|upgrade_type' /etc/dnf/automatic.conf")
            return a
        if all(v == "unknown" for v in timers.values()):
            return a.skip("systemctl did not answer", "systemctl list-timers 'dnf*'")
        a.finding("medium", "dnf-automatic is installed but none of its timers is enabled",
                  "systemctl list-timers 'dnf*'")
        return a
    return _unsupported(a, info, "apt-config dump | grep Periodic, or systemctl list-timers 'dnf*'")


CHECKS = {"updates": area_updates, "reboot": area_reboot, "ssh": area_ssh, "firewall": area_firewall,
          "listening": area_listening, "failed_units": area_failed_units, "disk": area_disk, "memory": area_memory,
          "time": area_time, "docker": area_docker, "auto_updates": area_auto_updates}


# ------------------------------------------------------------------ keeping names and addresses out

IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6_RE = re.compile(r"(?<![\w:.])(?=[0-9A-Fa-f:]*:[0-9A-Fa-f:]*:)[0-9A-Fa-f:]{2,39}(?![\w:])")
EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
KEY_RE = re.compile(r"(?:ssh-(?:rsa|ed25519|dss)|ecdsa-sha2-\S+|sk-\S+@openssh\.com)\s+[A-Za-z0-9+/=]{16,}")
LONG_KEY_RE = re.compile(r"[A-Za-z0-9+/]{40,}={0,2}")
HOME_RE = re.compile("/" + "home" + r"/[^/\s]+")
KEEP_ADDRESSES = {"0.0.0.0", "127.0.0.1", "127.0.0.53"}


def _ipv6_ok(text: str) -> bool:
    return text in ("::", "::1") or not re.search(r"[a-fA-F]|::", text)


class Scrubber:
    def __init__(self, names):
        names = sorted({n for n in names if len(n) >= 2 and n.lower() not in ("localhost", "root", "localdomain")},
                       key=len, reverse=True)
        self.names = [re.compile(r"(?i)(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])") for n in names]

    def __call__(self, value):
        if isinstance(value, dict):
            return {k: self(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self(v) for v in value]
        if not isinstance(value, str):
            return value
        text = KEY_RE.sub("<key>", value)
        text = LONG_KEY_RE.sub("<key>", text)
        text = EMAIL_RE.sub("<email>", text)
        text = HOME_RE.sub("<home folder>", text)
        for pattern in self.names:
            text = pattern.sub("<name>", text)
        text = IPV4_RE.sub(lambda m: m.group(0) if m.group(0) in KEEP_ADDRESSES else "<address>", text)
        return IPV6_RE.sub(lambda m: m.group(0) if _ipv6_ok(m.group(0)) else "<address>", text)


# ------------------------------------------------------------------ the report

def audit(s) -> dict:
    info = read_os(s)
    areas = {}
    for name in AREAS:
        try:
            areas[name] = CHECKS[name](s, info)
        except Exception as problem:  # one broken area must not hide the others
            areas[name] = Area(name).skip(f"the check failed unexpectedly ({type(problem).__name__})",
                                          "run the matching command by hand")
    findings = [f for a in areas.values() for f in a.findings]
    findings.sort(key=lambda f: SEVERITIES.index(f["severity"]))
    not_checked = [{"area": n, "reason": a.reason, "command": a.command} for n, a in areas.items()
                   if a.status != "checked"]
    system = dict(info)
    system["support"] = "not judged: compare the release with the distribution's own support dates"
    counts = {"findings": len(findings), "high": sum(f["severity"] == "high" for f in findings),
              "areas": len(areas), "not_checked": len(not_checked)}
    report = {"system": system, "ran_as_root": s.euid() == 0, "changed": "nothing", "findings": findings,
              "areas": {n: a.as_dict() for n, a in areas.items()}, "not_checked": not_checked, "summary": counts}
    try:
        names = s.identities()
    except Exception:  # the audit still prints, with no names to hide beyond the patterns
        names = []
    return Scrubber(names)(report)


def exit_code(report: dict) -> int:
    if report["findings"]:
        return 1
    return 2 if report["summary"]["not_checked"] * 2 > report["summary"]["areas"] else 0


def render_text(report: dict) -> str:
    sysinfo = report["system"]
    out = ["Server audit (read-only; nothing was changed)" + ("" if report["ran_as_root"] else
                                                               ", run as a normal user"),
           f"System: {sysinfo['name']} (family {sysinfo['family']}), kernel {sysinfo['kernel']}. "
           "Whether this release is still supported was not judged."]
    out.append(f"Findings ({len(report['findings'])}):" if report["findings"] else "Findings: none")
    for f in report["findings"]:
        out.append(f"  [{f['severity']}] {f['area']}: {f['fact']}")
        out.append(f"      shown by: {f['command']}")
    out.append("Checked:")
    for name, area in report["areas"].items():
        if area["status"] == "checked":
            for fact in area["facts"]:
                out.append(f"  {name}: {fact}")
    if report["not_checked"]:
        out.append("Not checked:")
        for item in report["not_checked"]:
            out.append(f"  {item['area']}: {item['reason']}; run: {item['command']}")
    s = report["summary"]
    out.append(f"Result: {s['findings']} finding(s), {s['high']} high; {s['not_checked']} of {s['areas']} areas "
               "not checked.")
    return "\n".join(out)


def main(argv: list[str] | None = None, system=None) -> int:
    parser = Parser(prog="server_audit.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                    description="A read-only look at the Linux server this runs on.", epilog=EPILOG)
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    args = parser.parse_args(argv)
    report = audit(system or System())
    print(json.dumps(report, indent=2) if args.json else render_text(report))
    return exit_code(report)


if __name__ == "__main__":
    sys.exit(main())
