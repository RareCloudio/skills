#!/usr/bin/env python3
"""Check config files with the real tool for their kind, and say what was not checked.

What it does: works out what each file is from its name and its content (Dockerfile, Compose
file, Caddyfile, nginx config, systemd unit or timer, Kubernetes manifest, GitHub Actions
workflow, sshd config or drop-in, shell script), runs the checker for that kind and prints, per
file, the kind and how it was recognised, the checker and its version, and the findings. A file
that matches no rule is reported as unknown, never guessed.
Two classes of checker. A parser (hadolint, kubeconform, actionlint, ShellCheck, bash -n) only
reads the file's text, so the one installed here runs, or its pinned image with --allow-docker.
An interpreter (nginx -t, caddy validate, docker compose config, sshd -t, systemd-analyze
verify) acts on what the file says, as the service would: it can load modules, follow includes,
expand placeholders, read files and environment variables and fetch remote includes. It runs
only in its pinned image with --allow-docker: a private copy of the one file, no network, a
read-only root, no capabilities, not as root, memory and time limits. --i-wrote-this-file runs
the interpreter installed here instead, for a file written in this session; without either, the
file is reported as not checked, with both ways to check it.
What it never does: install anything, write to a checked file, ask for sudo, or print a value it
takes for a secret. Wherever a tool quotes them, these are replaced with <hidden>: values of
secret-named keys, of capitalised (environment) variables and of Kubernetes data blocks, URL
passwords, key material and token-shaped strings from the file (for a Compose file, also from its
.env and env_file files and from the environment variables it names). A tool line that repeats a
whole line of the file is not shown.
Residual: a value under an ordinary lower-case key (a port, an image name, a path) prints when a
tool quotes it.

Usage: python check_config.py <file> [<file> ...] [--allow-docker] [--i-wrote-this-file] [--json]
       [--kind KIND]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile

MAX_BYTES = 2 * 1024 * 1024
MAX_OUTPUT = 1024 * 1024
MAX_FINDINGS = 100
MAX_MESSAGE = 300
MAX_REASON = 700
MIN_SECRET = 4
SBIN_DIRS = ["/usr/sbin", "/sbin", "/usr/local/sbin"]
HIDDEN = "<hidden>"
BOX_MEMORY = "512m"
BOX_PIDS = "256"
NOBODY = 65534          # the user a container runs as when this script runs as root


class Checker:
    def __init__(self, label, tool, image=None, image_version=None, hint="", network=False, no_image=None,
                 interpreter=False):
        self.label = label          # what the kind is called in the output
        self.tool = tool            # the program that checks it
        self.image = image          # official image with a pinned tag, or None
        self.image_version = image_version  # the tool's own version inside that image
        self.hint = hint            # the command to run it by hand
        self.network = network      # True when the tool needs the network inside its container
        self.no_image = no_image    # why there is no image to fall back to
        self.interpreter = interpreter  # acts on what the file says: runs only in its container


# Pinned images: an exact release tag and the digest it had on 2026-11-12, so a moved tag cannot
# swap the code that runs. Move both together, on purpose.
CHECKERS = {
    "dockerfile": Checker("Dockerfile", "hadolint", "hadolint/hadolint:v2.14.0@sha256:"
                          "27086352fd5e1907ea2b934eb1023f217c5ae087992eb59fde121dce9c9ff21e", "2.14.0",
                          "hadolint FILE"),
    "compose": Checker("Compose file", "docker compose", "docker:29.9.3-cli@sha256:"
                       "2357639ad1ea7d0194134bf3292622fd4e562483966ed674e5d7c945b5f3b28d", "5.7.0",
                       "docker compose config --quiet (in the app folder, on the server where it already runs)",
                       interpreter=True),
    "caddyfile": Checker("Caddyfile", "caddy", "caddy:2.11.9-alpine@sha256:"
                         "0bbb055bda6793c999bde78b1b5ce3e89f829fb031af2cf50056ea1246559fee", "2.11.9",
                         "sudo caddy validate --config FILE --adapter caddyfile (on the server where it already "
                         "runs)", interpreter=True),
    "nginx": Checker("nginx config", "nginx", "nginx:1.30.6@sha256:"
                     "42c68eab6f7e22611786a9fe1d1c019e275c50185bd54b8f75dc2b9184322703", "1.30.6",
                     "sudo nginx -t (on the server where it already runs)", interpreter=True),
    "systemd": Checker("systemd unit", "systemd-analyze", "almalinux:9.5@sha256:"
                       "e9bc8f598ddfe585b2bcf6402e1f4dae7eb689c8c9361877fcdd1efc86c18799", "252",
                       "systemd-analyze verify FILE (on the server where it already runs)", interpreter=True),
    "kubernetes": Checker("Kubernetes manifest", "kubeconform", "ghcr.io/yannh/kubeconform:v0.8.0@sha256:"
                          "faffaf43f95aa6425306e1ab8d6fcad72acb9049158f38e574c085ea1ec0f64e", "0.8.0",
                          "kubeconform -strict -summary FILE", network=True),
    "github-actions": Checker("GitHub Actions workflow", "actionlint", "rhysd/actionlint:1.7.12@sha256:"
                              "b1934ee5f1c509618f2508e6eb47ee0d3520686341fec936f3b79331f9315667", "1.7.12",
                              "actionlint FILE"),
    "sshd": Checker("sshd config", "sshd", None, None, "sudo sshd -t (on the server where it already runs)",
                    no_image="no official image ships sshd", interpreter=True),
    "shell": Checker("shell script", "shellcheck", "koalaman/shellcheck:v0.11.0@sha256:"
                     "61862eba1fcf09a484ebcc6feea46f1782532571a34ed51fedf90dd25f925a8d", "0.11.0",
                     "shellcheck FILE"),
}

VERSION_ARGS = {
    "hadolint": ["--version"], "caddy": ["version"], "nginx": ["-v"], "systemd-analyze": ["--version"],
    "kubeconform": ["-v"], "actionlint": ["--version"], "sshd": ["-V"], "shellcheck": ["--version"],
    "bash": ["--version"], "sh": ["--version"],
}

EPILOG = """\
Kinds (--kind): dockerfile, compose, caddyfile, nginx, systemd, kubernetes, github-actions, sshd,
shell. The kind comes from the file name first (Dockerfile, compose.yaml, Caddyfile, *.service,
.github/workflows/*.yml, sshd_config, *.sh) and then from the content (apiVersion and kind,
a services mapping, server blocks, sshd keywords, a #! line). A file that matches no rule, or
more than one, is reported as unknown; name its kind with --kind.

Parsers only read the file's text: hadolint, kubeconform -strict, actionlint, shellcheck (falling
back to bash -n, a syntax check only). The one installed here runs; with --allow-docker a missing
one runs from its image. To keep them to the file: ShellCheck, hadolint and actionlint run on a
private copy (ShellCheck with --norc; hadolint away from any .hadolint.yaml and HADOLINT_ settings,
as in its image; actionlint away from the repository and without its ShellCheck step, which would
read the files a run: step sources, so the local actions a workflow names are not read, and a note
says so), and kubeconform first reads the kinds with no schemas, refuses a kind or apiVersion that
is not a plain name, then downloads the published schemas for those kinds (the one check that uses
the network). A symbolic link to a file outside its own folder is not read.

Interpreters act on what the file says, as the service would: nginx -t loads modules and engines,
reads includes and certificates and creates log files and temporary folders; caddy validate
expands {$VAR} placeholders and reads imports; docker compose config reads env files and local
includes and fetches remote ones; sshd -t reads included files; systemd-analyze verify loads the
unit. So nginx, Caddyfile, Compose, systemd and sshd files run only in their pinned image, with
--allow-docker: only a private copy of the one file is mounted, read-only, with no network, a
read-only root, no capabilities, not as root, 512 MB of memory and the time limit. Inside it, a
module or a read of /etc/shadow reaches nothing of yours. Compose runs there with
--no-interpolate, as no .env goes in. sshd has no image. A site file is included unchanged in a
minimal main config, and upstream host names map to a local address.

--i-wrote-this-file runs the interpreter installed here when the container cannot be used; with
--allow-docker and Docker answering, the container is used anyway. That checker will act on what
the file says, and the flag applies to every file named on the command line, so give it only for
files you wrote in this session, never for a file from a project you were given. Without Docker
and without it, the file is reported as not checked, with the ways to check it. A line such as load_module or a remote
include is pointed out as a warning, but nothing depends on spotting it. The script never installs
anything and never asks for sudo.

Statuses: clean, findings, incomplete (the tool ran but could not check everything here, for
example a certificate file or a host name that exists only on the server), skipped (no checker
could run), unknown, missing. A note is something the tool printed while passing, or a check
that depends on the machine it runs on.

Secret-looking values from the file are printed as <hidden> wherever a tool quotes them.
Exit codes: 0 every file checked and clean, 1 findings in at least one file, 2 nothing wrong found
but at least one file was not fully checked (also for bad usage).
Needs Python 3.9 or newer, standard library only.
"""


class Parser(argparse.ArgumentParser):
    """argparse that reports a usage error as one line on stderr and exits 2."""

    def error(self, message):
        print(f"usage error: {' '.join(message.split())} (see --help)", file=sys.stderr)
        sys.exit(2)


# ------------------------------------------------------------------ running programs (tests replace these)

def which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(name, path=os.pathsep.join(SBIN_DIRS))


def run_command(argv: list[str], cwd: str | None = None, timeout: float = 120.0,
                env: dict | None = None) -> tuple:
    """(exit code, stdout, stderr); the exit code is None when the program did not finish in time."""
    try:
        proc = subprocess.run(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True,
                              timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", ""
    except OSError:
        return 127, "", "the program could not be started"
    out = proc.stdout[:MAX_OUTPUT].decode("utf-8", "replace")
    return proc.returncode, out, proc.stderr[:MAX_OUTPUT].decode("utf-8", "replace")


# ------------------------------------------------------------------ hiding secret values

SECRET_NAME_RE = re.compile(
    r"(?i)pass|pwd|secret|token|api[_.-]?key|apikey|access[_.-]?key|private|signing|auth|credential|cred"
    r"|salt|dsn|cookie|session|bearer|licen[cs]e|webhook|jwt|cert|key")
ENV_NAME_RE = re.compile(r"[A-Z_][A-Z0-9_]*")
BORING = {"true", "false", "yes", "no", "on", "off", "null", "none", "nil", "|", ">", "|-", ">-", "[]", "{}"}
LINE_ASSIGN_RE = re.compile(r"""^\s*(?:-\s+)?(?:export\s+)?["']?(?P<key>[A-Za-z_][A-Za-z0-9_.-]*)["']?"""
                            r"""\s*(?P<sep>=|:(?=\s|$))\s*(?P<value>.*)$""")
QUOTED_PAIR_RE = re.compile(r"""["']([A-Za-z_][\w.-]*)["']\s*:\s*["']([^"']*)["']""")
URL_CREDENTIALS_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)([^\s/@:]*):([^\s/@]+)@")
HEADER_RE = re.compile(r"(?i)(?:authorization|x-api-key|api-key|x-auth-token|private-token)[\"']?\s*[:=]?\s*[\"']?"
                       r"(?:(?:bearer|basic|token)\s+)?([^\s\"';,]+)")
DATA_BLOCK_RE = re.compile(r"^(?P<indent>\s*)(?:-\s+)?(?:data|stringData|secrets?|credentials|env|environment)\s*:\s*$")
BLOCK_SCALAR_RE = re.compile(r"^[|>][+-]?\d*$")
TOKEN_RES = [
    re.compile(r"(?<![A-Za-z0-9])(?=[A-Za-z0-9]*\d)(?=[A-Za-z0-9]*[A-Za-z])[A-Za-z0-9]{16,}"),
    re.compile(r"(?<![A-Za-z0-9+/])(?=[A-Za-z0-9+/]*[+/])(?=[A-Za-z0-9+/]*\d)(?=[A-Za-z0-9+/]*[A-Z])"
               r"(?=[A-Za-z0-9+/]*[a-z])[A-Za-z0-9+/]{24,}={0,2}"),
    re.compile(r"(?:gh[pousr]|github_pat|glpat|xox[abprs]|sk|rk|pk|npm|SG)[_.-][A-Za-z0-9_.-]{12,}"),
    re.compile(r"eyJ[\w-]{8,}\.[\w-]{8,}\.[\w-]{8,}"),
    re.compile(r"\$2[aby]?\$\d\d\$[./A-Za-z0-9]{40,}"),
]
PEM_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*-----[\s\S]*?(?:-----END [A-Z0-9 ]*-----|$)")
OUTPUT_KEY_RE = re.compile(r"(?i)([\w.-]*(?:pass(?:word|wd|phrase)?|pwd|secret|token|api[_-]?key|private[_-]?key"
                           r"|access[_-]?key|credential)[\w.-]*)([\"']?\s*[:=]\s*[\"']?)([^\s\"',;}<]+)")
OUTPUT_SCHEME_RE = re.compile(r"(?i)\b(bearer|basic)(\s+)([A-Za-z0-9._~+/=-]{8,})")


def _clean_value(raw: str) -> list[str]:
    """The forms a value may take when a tool quotes it: as written, unquoted, without a trailing comment."""
    value = raw.strip().rstrip(";").strip()
    forms = {value}
    for quote in ("'", '"', "`"):
        if len(value) >= 2 and value[0] == quote and value[-1] == quote:
            forms.add(value[1:-1])
    if " #" in value:
        forms.add(value.split(" #", 1)[0].strip())
    try:
        forms.update(shlex.split(value))
    except ValueError:
        pass
    out = []
    for form in forms:
        form = form.strip()
        if (len(form) < MIN_SECRET or form.lower() in BORING or re.fullmatch(r"\d{1,5}", form)
                or re.fullmatch(r"\$\{?[A-Za-z_]\w*\}?", form)):
            continue
        out.append(form)
        out.extend(word for word in form.split() if len(word) >= 8)
    return out


def _wanted(key: str, every: bool) -> bool:
    return every or bool(SECRET_NAME_RE.search(key)) or bool(ENV_NAME_RE.fullmatch(key))


def collect_values(text: str, every: bool = False) -> set:
    """Values in a config file that may be secrets. With every=True (an env file) all values count."""
    found: set = set()
    block_indent = None     # inside a data:, env: or similar block, every value counts
    scalar_indent = None    # inside a multi-line value of a wanted key
    in_pem = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())
        if "-----BEGIN " in line:
            in_pem = True
        if in_pem:
            found.update(part for part in re.findall(r"[A-Za-z0-9+/=]{8,}", line))
            if "-----END " in line:
                in_pem = False
            continue
        if scalar_indent is not None:
            if stripped and indent <= scalar_indent:
                scalar_indent = None
            else:
                if stripped:
                    found.update(_clean_value(stripped))
                continue
        if block_indent is not None and stripped and indent <= block_indent and not stripped.startswith("#"):
            block_indent = None
        if DATA_BLOCK_RE.match(line):
            block_indent = len(DATA_BLOCK_RE.match(line).group("indent"))
            continue
        if not stripped or stripped.startswith("#"):
            continue
        in_block = block_indent is not None
        words = stripped.split(None, 1)
        if words[0].upper() in ("ENV", "ARG") and len(words) == 2:  # Dockerfile
            body = words[1]
            first = body.split(None, 1)
            if "=" not in first[0] and len(first) == 2:
                found.update(_clean_value(first[1]))
            else:
                for token in _split(body):
                    if "=" in token:
                        found.update(_clean_value(token.split("=", 1)[1]))
            continue
        m = LINE_ASSIGN_RE.match(line)
        if m:
            key, value = m.group("key"), m.group("value")
            if key.lower() == "environment" and m.group("sep") == "=":  # systemd Environment=
                for token in _split(value):
                    if "=" in token:
                        found.update(_clean_value(token.split("=", 1)[1]))
                continue
            if _wanted(key, every or in_block):
                if BLOCK_SCALAR_RE.match(value.strip()):
                    scalar_indent = indent
                else:
                    found.update(_clean_value(value))
        for token in _split(stripped):
            key, eq, value = token.lstrip("-").partition("=")
            if eq and key and _wanted(key, every or in_block):
                found.update(_clean_value(value))
        tokens = _split(stripped)
        for i, token in enumerate(tokens[:-1]):
            if token.startswith("-") and SECRET_NAME_RE.search(token) and not tokens[i + 1].startswith("-"):
                found.update(_clean_value(tokens[i + 1]))
        for key, value in QUOTED_PAIR_RE.findall(line):
            if _wanted(key, every or in_block):
                found.update(_clean_value(value))
        for match in URL_CREDENTIALS_RE.finditer(line):
            found.update(_clean_value(match.group(3)))
        for match in HEADER_RE.finditer(line):
            found.update(_clean_value(match.group(1)))
    for pattern in TOKEN_RES:
        found.update(m.group(0) for m in pattern.finditer(text))
    return {value for value in found if len(value) >= MIN_SECRET}


def _split(text: str) -> list[str]:
    try:
        return shlex.split(text, comments=False)
    except ValueError:
        return text.split()


class Masker:
    """Turns tool output into text safe to print: see the module docstring."""

    def __init__(self, text: str, extra_env_texts=(), extra_values=(), paths=()):
        values = collect_values(text)
        for env_text in extra_env_texts:
            values |= collect_values(env_text, every=True)
        values |= {v for v in extra_values if v and len(v) >= MIN_SECRET}
        self.values = sorted(values, key=len, reverse=True)
        self.lines = {line.strip() for line in text.splitlines()[:5000] if len(line.strip()) >= 12}
        self.paths = sorted(((old, new) for old, new in paths if old), key=lambda p: len(p[0]), reverse=True)

    def __call__(self, text: str) -> str:
        text = str(text)
        # The pinned image names are the script's own, never the file's: keep them whole.
        kept = [c.image for c in CHECKERS.values() if c.image and c.image in text]
        for i, image in enumerate(kept):
            text = text.replace(image, f"\x00{i}\x00")
        text = self._mask(text)
        for i, image in enumerate(kept):
            text = text.replace(f"\x00{i}\x00", image)
        return text

    def _mask(self, text: str) -> str:
        for old, new in self.paths:
            text = text.replace(old, new)
        lines = []
        for line in text.split("\n"):
            if line.strip() in self.lines:
                lines.append("<a line of the file, not shown>")
                continue
            for file_line in self.lines:
                if file_line in line:
                    line = line.replace(file_line, "<a line of the file>")
            lines.append(line)
        text = "\n".join(lines)
        text = PEM_RE.sub("<hidden key>", text)
        for value in self.values:
            text = text.replace(value, HIDDEN)
        text = URL_CREDENTIALS_RE.sub(lambda m: m.group(1) + HIDDEN + "@", text)
        text = OUTPUT_SCHEME_RE.sub(lambda m: m.group(1) + m.group(2) + HIDDEN, text)
        text = OUTPUT_KEY_RE.sub(lambda m: m.group(1) + m.group(2) + HIDDEN, text)
        for pattern in TOKEN_RES:
            text = pattern.sub(HIDDEN, text)
        return text


# ------------------------------------------------------------------ what kind of file is it

UNIT_SUFFIXES = (".service", ".timer", ".socket", ".path", ".mount", ".automount", ".target", ".slice", ".swap")
SECTION_RE = re.compile(r"^\[(?:Unit|Service|Timer|Socket|Path|Mount|Automount|Install|Slice|Swap)\]\s*$", re.M)
COMPOSE_NAME_RE = re.compile(r"(?:docker-)?compose(?:\.[\w-]+)*\.ya?ml")
CHECKED_SHELLS = {"sh", "bash", "dash", "ksh", "mksh"}
OTHER_SHELLS = {"zsh", "fish", "csh", "tcsh", "nu", "pwsh", "elvish"}
NGINX_BLOCK_RE = re.compile(r"^\s*(?:server|http|events|upstream|location|map|stream)\b[^;{}\n]*\{", re.M)
NGINX_DIRECTIVE_RE = re.compile(r"^\s*(?:listen|server_name|proxy_pass|root|try_files|ssl_certificate|return|"
                                r"fastcgi_pass|add_header|client_max_body_size)\s+[^\n]*;\s*(?:#.*)?$", re.M)
SSHD_KEYWORDS = {
    "permitrootlogin", "passwordauthentication", "pubkeyauthentication", "kbdinteractiveauthentication",
    "challengeresponseauthentication", "permitemptypasswords", "allowusers", "allowgroups", "denyusers",
    "denygroups", "port", "listenaddress", "authorizedkeysfile", "usepam", "x11forwarding", "subsystem",
    "maxauthtries", "clientaliveinterval", "clientalivecountmax", "logingracetime", "match", "include",
    "hostkey", "authenticationmethods", "allowtcpforwarding", "allowagentforwarding", "maxsessions",
    "maxstartups", "loglevel", "printmotd", "acceptenv", "usedns", "ciphers", "macs", "kexalgorithms",
    "hostkeyalgorithms", "pubkeyacceptedalgorithms", "permittunnel", "gatewayports", "banner",
}
YAML_TOP_KEY_RE = re.compile(r"""^["']?([A-Za-z_][\w.-]*)["']?\s*:(?:\s|$)""")


def _shebang(text: str) -> str | None:
    if not text.startswith("#!"):
        return None
    words = text[2:].split("\n", 1)[0].split()
    if not words:
        return None
    program = words[0].rsplit("/", 1)[-1]
    if program == "env":
        rest = [w for w in words[1:] if not w.startswith("-")]
        program = rest[0].rsplit("/", 1)[-1] if rest else ""
    return program or None


def _yaml_documents(text: str) -> list[list[str]]:
    docs, current = [], []
    for line in text.splitlines():
        if re.match(r"^---(?:\s|$)", line):
            docs.append(current)
            current = []
        else:
            current.append(line)
    docs.append(current)
    return [d for d in docs if any(line.strip() and not line.lstrip().startswith("#") for line in d)]


def _top_keys(lines: list[str]) -> list[str]:
    return [m.group(1) for m in (YAML_TOP_KEY_RE.match(line) for line in lines) if m]


def _compose_like(lines: list[str]) -> bool:
    for i, line in enumerate(lines):
        if re.match(r"^services\s*:\s*(?:#.*)?$", line):
            for following in lines[i + 1:]:
                if not following.strip() or following.lstrip().startswith("#"):
                    continue
                return bool(re.match(r"^\s+[^\s#-][^:]*:(?:\s|$)", following))
    return False


def _sshd_like(text: str) -> bool:
    keywords = 0
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.endswith((";", "{", "}")) or stripped.startswith("["):
            return False
        word = re.split(r"[\s=]", stripped, maxsplit=1)[0].lower()
        if word in SSHD_KEYWORDS:
            keywords += 1
        elif not re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", word):
            return False
    return keywords > 0


def detect_kind(path: str, text: str) -> tuple:
    """(kind, how it was recognised), or (None, why it is unknown)."""
    name = os.path.basename(path)
    lower = name.lower()
    parts = [p.lower() for p in os.path.normpath(os.path.abspath(path)).split(os.sep)]
    parent = parts[-2] if len(parts) > 1 else ""
    suffix = os.path.splitext(lower)[1]
    if "\0" in text:
        return None, "a binary file"
    if parent.endswith(".d") and parent[:-2].endswith(UNIT_SUFFIXES):
        return None, ("a systemd drop-in; it is checked together with the unit it belongs to "
                      "(systemd-analyze verify on that unit, on the server)")
    if (lower in ("dockerfile", "containerfile") or lower.startswith(("dockerfile.", "dockerfile-", "dockerfile_",
                                                                      "containerfile.")) or suffix == ".dockerfile"):
        return "dockerfile", "by file name"
    if COMPOSE_NAME_RE.fullmatch(lower):
        return "compose", "by file name"
    if lower == "caddyfile" or lower.startswith("caddyfile.") or suffix in (".caddyfile", ".caddy"):
        return "caddyfile", "by file name"
    if suffix in (".yml", ".yaml") and parts[-3:-1] == [".github", "workflows"]:
        return "github-actions", "by place: .github/workflows"
    if lower.startswith("sshd_config") or parent == "sshd_config.d":
        return "sshd", "by file name"
    if suffix in (".service", ".timer", ".socket"):
        return "systemd", "by file name"
    if suffix in UNIT_SUFFIXES and SECTION_RE.search(text):
        return "systemd", "by file name and [Section] headers"
    if lower in ("kustomization.yaml", "kustomization.yml", "kustomization"):
        return None, ("a kustomization; render it with kubectl kustomize, save the output and check that "
                      "as a Kubernetes manifest")
    if lower == "nginx.conf" or suffix == ".nginx":
        return "nginx", "by file name"
    shell = _shebang(text)
    if shell in OTHER_SHELLS or suffix in (".zsh", ".fish"):
        return None, f"a {shell or suffix[1:]} script; shellcheck checks sh, bash, dash and ksh only"
    if shell in CHECKED_SHELLS:
        return "shell", f"by its #! line ({shell})"
    if suffix in (".sh", ".bash", ".ksh", ".dash"):
        return "shell", "by file name"

    found = []
    if suffix in (".yml", ".yaml") or not suffix:
        docs = _yaml_documents(text)
        keys = [set(_top_keys(d)) for d in docs]
        if any({"apiVersion", "kind"} <= k for k in keys):
            if "{{" in text:
                return None, ("a Helm template; render it with helm template, save the output and check that "
                              "as a Kubernetes manifest")
            found.append(("kubernetes", "by content: apiVersion and kind"))
        if any(_compose_like(d) for d in docs):
            found.append(("compose", "by content: a services mapping"))
        if any("jobs" in k and ({"on", "true"} & k) for k in keys):
            found.append(("github-actions", "by content: on and jobs"))
    if SECTION_RE.search(text) and not found:
        return None, ("it looks like a systemd unit, but systemd-analyze needs the unit's real name "
                      "(.service, .timer, .socket); check it under that name")
    nginx_hits = len(NGINX_BLOCK_RE.findall(text)) + len(NGINX_DIRECTIVE_RE.findall(text))
    if nginx_hits >= 2 or (nginx_hits and parent in ("nginx", "sites-available", "sites-enabled", "conf.d")):
        found.append(("nginx", "by content: nginx blocks and directives"))
    elif _sshd_like(text):
        found.append(("sshd", "by content: sshd keywords"))
    if len(found) == 1:
        return found[0]
    if len(found) > 1:
        return None, "it looks like more than one kind (" + " and ".join(k for k, _ in found) + ")"
    return None, "no rule matched its name or its content"


# ------------------------------------------------------------------ one file

class Docker:
    """Whether Docker can be used, found out once and only when a check needs it."""

    def __init__(self, allowed: bool):
        self.allowed = allowed
        self._state = None

    def state(self) -> tuple:
        if self._state is None:
            path = which("docker")
            if not path:
                self._state = (None, "Docker is not available (not installed)")
            else:
                rc, _, _ = run_command([path, "version", "--format", "{{.Server.Version}}"], timeout=30)
                self._state = (path, None) if rc == 0 else (None, "Docker is not available (its daemon did not answer)")
        return self._state


class Job:
    def __init__(self, given: str, path: str, text: str, kind: str, docker: Docker, timeout: float,
                 data: bytes = b"", mode: int = 0o600, trusted: bool = False):
        self.given, self.path, self.text, self.kind = given, path, text, kind
        self.trusted = trusted      # --i-wrote-this-file: an interpreter may run from this machine
        self.dir, self.base = os.path.dirname(path), os.path.basename(path)
        self.data, self.mode = data or text.encode("utf-8"), mode
        self.checker = CHECKERS[kind]
        self.docker, self.timeout = docker, timeout
        self.findings, self.notes, self.incomplete = [], [], []
        self.route = None           # ("local", program path) or ("docker", image)
        self.temp_dirs = []
        self.masker = None
        self.wrapper = None

    def temp(self) -> str:
        folder = tempfile.mkdtemp(prefix="check-config-")
        self.temp_dirs.append(folder)
        return folder

    def private_copy(self, rel: str | None = None) -> tuple:
        """(folder, path): the bytes that were read, alone in a new folder only this user can open. A checker
        in a container is given this folder, never the one the file sits in."""
        folder = self.temp()
        target = os.path.join(folder, *(rel or self.base).split("/"))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        handle = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, self.mode)
        with os.fdopen(handle, "wb") as out:
            out.write(self.data)
        self.masker.paths = sorted(self.masker.paths + [(target, self.base), (folder + os.sep, "")],
                                   key=lambda p: len(p[0]), reverse=True)
        if _as_root():
            # The container runs as nobody, never as root: give the copy, and only it, to that user.
            for dirpath, dirnames, filenames in os.walk(folder):
                for name in [dirpath] + [os.path.join(dirpath, n) for n in dirnames + filenames]:
                    os.chown(name, NOBODY, NOBODY)
        return folder, target

    def add_to_copy(self, folder: str, name: str, text: str) -> str:
        """A file of this script's own (the nginx wrapper) beside the private copy, in the one mount."""
        target = os.path.join(folder, name)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(text)
        if _as_root():
            os.chown(target, NOBODY, NOBODY)
        return target

    def finding(self, message, line=None, column=None, level="error", code=None):
        if len(self.findings) >= MAX_FINDINGS:
            return
        self.findings.append({"line": _int(line), "column": _int(column), "level": str(level or "error"),
                              "code": None if code is None else self.say(code), "message": self.say(message)})

    def note(self, message):
        text = self.say(message)
        if text not in self.notes:
            self.notes.append(text)

    def stop(self, message):
        self.incomplete.append(self.say(message))

    def say(self, text, limit: int = MAX_MESSAGE) -> str:
        text = " ".join(self.masker(str(text)).split())
        return text if len(text) <= limit else text[:limit - 3] + "..."

    def failed(self, rc, output):
        first = next((line for line in str(output).splitlines() if line.strip()), "")
        self.stop(f"the checker failed (exit code {rc})" + (f": {first}" if first else ""))

    def run(self, local_args, docker_args, cwd=None, mount=None, workdir=None, entrypoint=None, extra=(), env=None,
            network=None):
        """Run the checker by the chosen route; None when it did not give a usable result. In Docker, mount is
        the one folder the container sees (a private copy, at /work); network=None takes the checker's own need."""
        if self.route[0] == "local":
            rc, out, stderr = run_command([self.route[1]] + list(local_args), cwd=cwd, timeout=self.timeout, env=env)
        else:
            docker_path = self.docker.state()[0]
            if mount and (":" in mount or "," in mount):
                self.stop("the temporary folder path holds a colon or a comma, which a Docker mount cannot take")
                return None
            name = "check-config-" + os.urandom(6).hex()
            argv = [docker_path, "run", "--rm", "--name", name]
            if not (self.checker.network if network is None else network):
                argv += ["--network", "none"]
            argv += ["--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                     "--memory", BOX_MEMORY, "--pids-limit", BOX_PIDS,
                     "--tmpfs", "/tmp:mode=1777", "--tmpfs", "/run:mode=1777"]
            if hasattr(os, "getuid"):
                # Never root in the box: as the caller, who can read the private copy, or as nobody for root.
                argv += ["--user", f"{NOBODY}:{NOBODY}" if _as_root() else f"{os.getuid()}:{os.getgid()}"]
            argv += list(extra)
            if mount:
                argv += ["-v", f"{mount}:/work:ro"]
            if workdir:
                argv += ["-w", workdir]
            if entrypoint:
                argv += ["--entrypoint", entrypoint]
            rc, out, stderr = run_command(argv + [self.route[1]] + list(docker_args), timeout=self.timeout)
            stderr = DOCKER_PULL_RE.sub("", DOCKER_WARNING_RE.sub("", stderr))
            if rc is None:
                run_command([docker_path, "rm", "-f", name], timeout=30)
            elif rc in (125, 126, 127) and re.search(r"docker|daemon|image|container", stderr, re.I):
                self.stop(f"Docker could not run the image {self.route[1]}: {_docker_problem(rc, stderr)}")
                return None
        if rc is None:
            self.stop(f"the checker did not finish within {self.timeout:g} seconds")
            return None
        return rc, out, stderr


# What Docker itself prints about the host, not about the file.
DOCKER_WARNING_RE = re.compile(r"(?m)^WARNING: (?:Your kernel does not support|The requested image's platform)[^\n]*\n?")


# What Docker prints while it downloads an image the first time: progress, not a word about the file.
DOCKER_PULL_RE = re.compile(
    r"(?m)^(?:Unable to find image '[^'\n]*' locally"
    r"|[^\s:]+(?:[:@][^\s]*)?: Pulling from [^\n]*"
    r"|[0-9a-f]{12}: (?:Pulling fs layer|Waiting|Downloading|Verifying Checksum|Download complete"
    r"|Extracting|Pull complete|Already exists)[^\n]*"
    r"|Digest: sha256:[0-9a-f]{64}"
    r"|Status: (?:Downloaded newer image|Image is up to date) for [^\n]*)[ \t]*\n?")


def _as_root() -> bool:
    return hasattr(os, "geteuid") and os.geteuid() == 0


def _mount(job: Job):
    """The folder a checker in Docker sees: a private copy of the file alone, at /work."""
    if job.route[0] != "docker":
        return None
    folder, _ = job.private_copy()
    return folder


def _int(value):
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _docker_problem(rc: int, stderr: str) -> str:
    if re.search(r"429|toomanyrequests|too many requests|rate limit", stderr, re.I):
        return "the registry refused the download (rate limit); try again later or pull the image yourself"
    if re.search(r"pull access denied|manifest unknown|not found", stderr, re.I):
        return "the image could not be found or downloaded"
    if re.search(r"cannot connect to the docker daemon", stderr, re.I):
        return "the Docker daemon is not running"
    if re.search(r"permission denied", stderr, re.I):
        return "no permission to use Docker"
    return f"docker run failed with exit code {rc}"


def _version(program_path: str, name: str) -> str | None:
    args = VERSION_ARGS.get(name)
    if not args:
        return None
    rc, out, stderr = run_command([program_path] + args, timeout=30)
    text = f"{out}\n{stderr}"
    match = (re.search(r"^systemd (\d+)\b", text, re.M) or re.search(r"(\d+(?:\.\d+)+(?:p\d+)?)", text)
             or re.search(r"\b(\d{2,4})\b", text))
    return match.group(1) if match and rc is not None else None


def _version_tuple(version: str | None) -> tuple:
    return tuple(int(n) for n in re.findall(r"\d+", version or "")[:3])


# ------------------------------------------------------------------ the checkers

def check_dockerfile(job: Job) -> None:
    # A private copy, run from its own folder with HOME there and no HADOLINT_ variables: hadolint reads
    # .hadolint.yaml from the current folder and the user's config, and a project's `ignored:` and
    # `no-fail:` would hide findings the container route reports.
    folder, copy = job.private_copy()
    env = {k: v for k, v in os.environ.items() if not k.startswith("HADOLINT_")}
    env.update(HOME=folder, XDG_CONFIG_HOME=folder)
    result = job.run(["--no-color", "-f", "json", copy], ["--no-color", "-f", "json", "/work/" + job.base],
                     cwd=folder, mount=folder if job.route[0] == "docker" else None, workdir="/work",
                     entrypoint="hadolint", env=env)
    if result is None:
        return
    rc, out, stderr = result
    try:
        items = json.loads(out.strip() or "[]")
    except ValueError:
        items = None
    if not isinstance(items, list) or not all(isinstance(i, dict) for i in items):
        job.failed(rc, stderr or out)
        return
    for item in items:
        job.finding(item.get("message", ""), item.get("line"), item.get("column"), item.get("level"), item.get("code"))
    if rc not in (0, 1) or (rc == 1 and not items):
        job.failed(rc, stderr)


COMPOSE_LOG_RE = re.compile(r'level=(\w+)\s+msg="((?:[^"\\]|\\.)*)"')
# In the container only the one file exists and there is no network: what it includes or fetches is not there.
COMPOSE_BOX_ONLY_RE = re.compile(r"no such file or directory|failed to (?:access|pull|resolve|fetch|load)|"
                                 r"remote|repository|oci://|git@|dial tcp|lookup |network is unreachable", re.I)


def check_compose(job: Job) -> None:
    if job.route[0] == "docker":
        job.note("checked in the container with --no-interpolate, from this file alone: variables were not filled "
                 "in and no .env or env_file was read; on the server, docker compose config --quiet in the app "
                 "folder checks them")
        result = job.run([], ["compose", "-f", "/work/" + job.base, "config", "--quiet", "--no-interpolate",
                              "--no-env-resolution"], mount=_mount(job), workdir="/work", entrypoint="docker",
                         extra=["-e", "HOME=/tmp", "-e", "DOCKER_CONFIG=/tmp/.docker"])
        if result is None:
            return
        rc, out, stderr = result
    else:
        rc, out, stderr = run_command(job.route[1] + ["-f", job.path, "config", "--quiet"], cwd=job.dir,
                                      timeout=job.timeout)
    if rc is None:
        job.stop(f"the checker did not finish within {job.timeout:g} seconds")
        return
    problems = []
    for line in f"{out}\n{stderr}".splitlines():
        match = COMPOSE_LOG_RE.search(line)
        if match:
            level, message = match.group(1), match.group(2).replace('\\"', '"')
            if "variable is not set" in message:
                job.note(message + " (fine if the server's environment or .env sets it)")
            elif level in ("warning", "warn", "info"):
                job.note(message)
            else:
                problems.append(message)
        elif line.strip():
            problems.append(line.strip())
    if rc == 0:
        for problem in problems:
            job.note(problem)
    elif problems and job.route[0] == "docker" and COMPOSE_BOX_ONLY_RE.search(" ".join(problems)):
        job.stop("docker compose stopped at a file or address the container does not have (an include, an "
                 "extends file or a remote include), so the rest was not checked: " + " ".join(problems))
    elif problems:
        text = " ".join(problems)
        number = re.search(r"\bline (\d+)", text)
        job.finding(text, number.group(1) if number else None)
    else:
        job.failed(rc, stderr)


# In the container only the one file exists, the root is read-only and there is no network.
CADDY_BOX_ONLY_RE = re.compile(r"File to import not found|no such file or directory|read-only file system|"
                               r"permission denied|dial tcp|lookup |no such host|network is unreachable", re.I)


def check_caddyfile(job: Job) -> None:
    home = job.temp()
    env = dict(os.environ, XDG_DATA_HOME=home, XDG_CONFIG_HOME=home)
    result = job.run(["validate", "--config", job.path, "--adapter", "caddyfile"],
                     ["validate", "--config", "/work/" + job.base, "--adapter", "caddyfile"],
                     cwd=job.dir, mount=_mount(job), workdir="/work", entrypoint="caddy",
                     extra=["-e", "XDG_DATA_HOME=/tmp", "-e", "XDG_CONFIG_HOME=/tmp"], env=env)
    if result is None:
        return
    rc, out, stderr = result
    for line in f"{out}\n{stderr}".splitlines():
        line = line.strip()
        record = None
        if line.startswith("{"):
            try:
                record = json.loads(line)
            except ValueError:
                record = None
        if isinstance(record, dict):
            level, message = str(record.get("level", "")), str(record.get("msg", ""))
            if level in ("warn", "warning"):
                job.note(message)
            elif level in ("error", "fatal", "panic"):
                _caddy_problem(job, message, None)
        elif line.startswith("Error:"):
            number = re.search(r":(\d+)\b", line)
            _caddy_problem(job, line[len("Error:"):].strip(), number.group(1) if number else None)
    if rc != 0 and not job.findings and not job.incomplete:
        job.failed(rc, stderr or out)


def _caddy_problem(job: Job, message: str, line) -> None:
    if CADDY_BOX_ONLY_RE.search(message):
        where = f" (line {line})" if line else ""
        job.stop(f"caddy stopped at something {'the container' if job.route[0] == 'docker' else 'this machine'} "
                 f"does not have, so the rest was not checked: {message}{where}; run the check on the server where it "
                 "already runs")
    else:
        job.finding(message, line)


NGINX_MAIN_ONLY = {"stream", "mail", "load_module", "worker_processes", "user", "daemon", "worker_rlimit_nofile",
                   "worker_cpu_affinity", "pcre_jit", "thread_pool", "master_process", "working_directory"}
NGINX_HTTP_BLOCKS = {"server", "upstream", "map", "geo", "split_clients"}
NGINX_LINE_RE = re.compile(r"\[(emerg|alert|crit|error|warn|notice|info)\]\s+(?:\d+#\d+:\s+(?:\*\d+\s+)?)?(.*)")
NGINX_PLACE_RE = re.compile(r"\s+in\s+(\S+):(\d+)\s*$")
NGINX_HERE_ONLY_RE = re.compile(
    r"host not found|cannot load certificate|BIO_new_file|No such file or directory|Permission denied|"
    r"getpwnam|getgrnam|Address family not supported|Read-only file system|mkdir\(\) .* failed|"
    r"could not open error log|no resolver defined", re.I)
NGINX_PASS_RE = re.compile(r"\b(?:proxy|fastcgi|uwsgi|scgi|grpc|memcached)_pass\s+(?:[a-z]+://)?"
                           r"([A-Za-z0-9][A-Za-z0-9.-]*)")
NGINX_UPSTREAM_SERVER_RE = re.compile(r"(?:^|[;{])\s*server\s+([A-Za-z0-9][A-Za-z0-9.-]*)(?::\d+)?\s*[;\s]", re.M)
NGINX_UPSTREAM_NAME_RE = re.compile(r"\bupstream\s+([A-Za-z0-9_.-]+)\s*\{")


def nginx_top_level(text: str) -> set:
    """Names of the directives and blocks at the top level of an nginx file."""
    names, depth, current, quote, comment = set(), 0, [], None, False
    for ch in text:
        if comment:
            comment = ch != "\n"
            continue
        if quote:
            quote = None if ch == quote else quote
            if depth == 0:
                current.append(ch)
            continue
        if ch == "#":
            comment = True
        elif ch in "\"'":
            quote = ch
            if depth == 0:
                current.append(ch)
        elif ch == "{":
            if depth == 0 and "".join(current).split():
                names.add("".join(current).split()[0])
            depth, current = depth + 1, []
        elif ch == "}":
            depth, current = max(0, depth - 1), []
        elif ch == ";":
            if depth == 0 and "".join(current).split():
                names.add("".join(current).split()[0])
            current = []
        elif depth == 0:
            current.append(ch)
    return names


def nginx_shape(text: str) -> str:
    top = nginx_top_level(text)
    if top & {"events", "http"}:
        return "main"
    if top & NGINX_MAIN_ONLY:
        return "main-fragment"
    if "location" in top and not top & NGINX_HTTP_BLOCKS:
        return "snippet"
    return "site"


def nginx_wrapper(shape: str, include: str, temp: str, temp_paths: bool = True) -> str:
    """temp_paths: point nginx's temporary folders at temp, so nginx -t can create them without root."""
    lines = ["# Written by check_config.py: a minimal main config that includes the checked file unchanged.",
             f"pid {temp}/nginx.pid;", "error_log stderr;", "events {}"]
    if shape == "main-fragment":
        lines.append(f"include {include};")
    lines += ["http {", "    access_log off;"]
    if temp_paths:
        lines += [f"    {name}_temp_path {temp}/{name};" for name in ("client_body", "proxy", "fastcgi", "uwsgi",
                                                                       "scgi")]
    if shape == "site":
        lines.append(f"    include {include};")
    elif shape == "snippet":
        lines += ["    server {", "        listen 127.0.0.1:8080;", f"        include {include};", "    }"]
    lines.append("}")
    return "\n".join(lines) + "\n"


def nginx_hosts(text: str) -> list[str]:
    upstreams = set(NGINX_UPSTREAM_NAME_RE.findall(text))
    hosts = set(NGINX_PASS_RE.findall(text)) | set(NGINX_UPSTREAM_SERVER_RE.findall(text))
    keep = []
    for host in sorted(hosts):
        if host in upstreams or host in ("localhost", "unix") or re.fullmatch(r"[\d.]+", host):
            continue
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.-]{0,252}", host):
            keep.append(host)
    return keep[:50]


NGINX_WRAPPER = ".check-config-nginx.conf"


def check_nginx(job: Job) -> None:
    shape = nginx_shape(job.text)
    local = job.route[0] == "local"
    version = _version(job.route[1], "nginx") if local else None
    stderr_flag = ["-e", "stderr"] if not local or _version_tuple(version) >= (1, 19, 5) else []
    extra = []
    copy_dir = copy_path = None
    config_local = config_docker = None
    if shape == "main" or not local:
        # A complete config runs as a copy, so its relative includes resolve in the check's own folder;
        # in Docker the copy is all the container sees.
        copy_dir, copy_path = job.private_copy()
    if shape == "main":
        config_local, config_docker = copy_path, "/work/" + job.base
        job.wrapper = copy_path
    elif local:
        temp = job.temp()
        config_local = job.add_to_copy(temp, "nginx.conf", nginx_wrapper(shape, job.path, temp, temp_paths=True))
    else:
        config_local = job.add_to_copy(copy_dir, NGINX_WRAPPER, nginx_wrapper(shape, "/work/" + job.base, "/tmp"))
        config_docker = "/work/" + NGINX_WRAPPER
    if shape != "main":
        job.wrapper = config_local
        job.masker.paths = sorted(job.masker.paths + [(config_local, "the generated wrapper")]
                                  + ([(config_docker, "the generated wrapper")] if config_docker else []),
                                  key=lambda p: len(p[0]), reverse=True)
    if not local:
        # nginx -t needs no root; room for its pid and cache on a read-only root.
        extra += ["--tmpfs", "/var/cache/nginx:mode=1777"]
        hosts = nginx_hosts(job.text)
        for host in hosts:
            extra += ["--add-host", f"{host}:127.0.0.1"]
        if hosts:
            job.note("upstream host names (" + ", ".join(hosts) + ") were mapped to a local address for the check; "
                     "whether they resolve on the server was not checked")
    result = job.run(["-t", "-c", config_local] + stderr_flag, ["-t", "-c", str(config_docker)] + stderr_flag,
                     cwd=job.dir, mount=None if local else copy_dir, entrypoint="nginx", extra=extra)
    if result is None:
        return
    rc, out, stderr = result
    checked = {job.path, os.path.realpath(job.path), "/work/" + job.base} | ({copy_path} if copy_path else set())
    for line in f"{out}\n{stderr}".splitlines():
        match = NGINX_LINE_RE.search(line)
        if not match:
            continue
        level, message = match.group(1), match.group(2).strip()
        number = None
        place = NGINX_PLACE_RE.search(message)
        if place and place.group(1) in checked:
            number, message = place.group(2), message[:place.start()]
        elif place and place.group(1) in (config_local, config_docker) and shape != "main":
            message = message[:place.start()] + " (in the generated wrapper)"
        if level in ("emerg", "crit", "error"):
            if NGINX_HERE_ONLY_RE.search(message):
                where = f" (line {number})" if number else ""
                here = "the container" if not local else "this machine"
                job.stop(f"nginx stopped at something {here} does not have, so the lines after it were not "
                         f"checked: {message}{where}; run sudo nginx -t on the server where it already runs")
            else:
                job.finding(message, number, level=level)
        else:
            job.note(message + (f" (line {number})" if number else ""))
    if rc != 0 and not job.findings and not job.incomplete:
        job.failed(rc, stderr)


SYSTEMD_NOISE_RE = re.compile(r"Failed to (?:bind private socket|connect to bus|create bus connection)", re.I)
SYSTEMD_HERE_ONLY_RE = re.compile(
    r"is not executable: No such file or directory|Failed to resolve (?:user|group)|"
    r"to trigger not loaded|Unit \S+ not found|Failed to look up (?:user|group)", re.I)
SYSTEMD_PLACE_RE = re.compile(r"^(?P<file>\S+?):(?P<line>\d+):\s*(?P<message>.*)$")


def check_systemd(job: Job) -> None:
    version = _version(job.route[1], "systemd-analyze") if job.route[0] == "local" else None
    recursive = ["--recursive-errors=no"] if job.route[0] != "local" or _version_tuple(version) >= (250,) else []
    result = job.run(["verify", "--man=no"] + recursive + [job.path],
                     ["verify", "--man=no"] + recursive + ["/work/" + job.base],
                     cwd=job.dir, mount=_mount(job), entrypoint="systemd-analyze")
    if result is None:
        return
    rc, out, stderr = result
    checked = {job.path, os.path.realpath(job.path), "/work/" + job.base}
    for line in f"{out}\n{stderr}".splitlines():
        line = line.strip()
        if not line or SYSTEMD_NOISE_RE.search(line):
            continue
        if SYSTEMD_HERE_ONLY_RE.search(line):
            job.note(line + " (depends on the machine; on the server this would be a real problem)")
            continue
        place = SYSTEMD_PLACE_RE.match(line)
        if place and place.group("file") in checked:
            job.finding(place.group("message"), place.group("line"))
        elif place:
            job.finding(f"in {os.path.basename(place.group('file'))} line {place.group('line')}: "
                        f"{place.group('message')}")
        else:
            job.finding(line)
    if rc != 0 and not job.findings and not job.notes:
        job.failed(rc, stderr)


# The kind and apiVersion become part of the schema's address; only plain names may.
KUBE_KIND_RE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,62}")
KUBE_API_RE = re.compile(r"(?:[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?/)?v[0-9]+(?:(?:alpha|beta)[0-9]+)?")
# A schema place that holds no file and no part of the manifest: the first run only reads the kinds.
KUBE_NO_SCHEMAS = "/dev/null/{{ .NormalizedKubernetesVersion }}.json"


def _kubeconform_report(job: Job, rc, out, stderr):
    try:
        report = json.loads(out.strip() or "{}")
        resources = report.get("resources") or []
        if not isinstance(resources, list):
            raise ValueError
        return resources
    except (ValueError, AttributeError):
        job.failed(rc, stderr or out)
        return None


def check_kubernetes(job: Job) -> None:
    # kubeconform builds each schema's address from the manifest's kind and apiVersion, and a schema it
    # downloads may point at other files and addresses. So it first reads the kinds with no schemas and no
    # network, from a private copy; only plain kind names go on to the download of the published schemas.
    folder, copy = job.private_copy()
    mount = folder if job.route[0] == "docker" else None
    probe = ["-summary", "-verbose", "-output", "json", "-schema-location", KUBE_NO_SCHEMAS]
    result = job.run(probe + [copy], probe + ["/work/" + job.base], cwd=folder, mount=mount, network=False)
    if result is None:
        return
    resources = _kubeconform_report(job, *result)
    if resources is None:
        return
    odd = []
    for item in resources:
        if not isinstance(item, dict):
            continue
        kind, version = str(item.get("kind") or ""), str(item.get("version") or "")
        if (kind and not KUBE_KIND_RE.fullmatch(kind)) or (version and not KUBE_API_RE.fullmatch(version)):
            odd.append(f"kind {kind!r} with apiVersion {version!r}")
    if odd:
        for what in odd[:MAX_FINDINGS]:
            job.finding(f"{what} is not a Kubernetes kind and apiVersion, so no schema was downloaded for this "
                        "file")
        return
    args = ["-strict", "-summary", "-verbose", "-output", "json", "-ignore-missing-schemas"]
    job.note("kubeconform downloads the Kubernetes schemas, so this check used the network")
    result = job.run(args + [copy], args + ["/work/" + job.base], cwd=folder, mount=mount)
    if result is None:
        return
    rc, out, stderr = result
    resources = _kubeconform_report(job, rc, out, stderr)
    if resources is None:
        return
    skipped = 0
    for item in resources:
        if not isinstance(item, dict):
            continue
        what = f"{item.get('kind') or 'resource'} {item.get('name') or '(no name)'}"
        status, message = item.get("status"), str(item.get("msg") or "")
        if status == "statusInvalid":
            errors = [e for e in item.get("validationErrors") or [] if isinstance(e, dict)]
            for e_item in errors:
                job.finding(f"{what}: {e_item.get('path', '')}: {e_item.get('msg', '')}")
            if not errors:
                job.finding(f"{what}: {message}")
        elif status == "statusError":
            if re.search(r"schema", message, re.I) and re.search(r"download|could not find|failed", message, re.I):
                job.stop(f"{what}: its schema could not be downloaded")
            else:
                job.finding(f"{what}: {message}")
        elif status == "statusSkipped":
            skipped += 1
            job.note(f"{what}: no schema for this kind (a custom resource?), so it was not checked")
    if skipped:
        job.stop(f"{skipped} resource(s) had no schema and were not checked")
    if rc not in (0, 1) or (rc == 1 and not job.findings and not job.incomplete):
        job.failed(rc, stderr)


def _in_a_repository(folder: str) -> bool:
    here = os.path.abspath(folder)
    while True:
        if os.path.exists(os.path.join(here, ".git")):
            return True
        parent = os.path.dirname(here)
        if parent == here:
            return False
        here = parent


LOCAL_USES_RE = re.compile(r"""^\s*(?:-\s+)?uses\s*:\s*["']?\./""", re.M)


def check_github_actions(job: Job) -> None:
    # Only the workflow, at the place actionlint expects it, in a folder of its own: in a repository actionlint
    # reads the local actions and reusable workflows a file names, wherever their paths lead.
    folder, _ = job.private_copy(".github/workflows/" + job.base)
    if _in_a_repository(folder):
        job.stop("the temporary folder is inside a git repository, where actionlint would read the files a "
                 "workflow names; set TMPDIR to a folder outside any repository and check again")
        return
    rel = os.path.join(".github", "workflows", job.base)
    args = ["-no-color", "-format", "{{json .}}"]
    local_args = args
    if job.route[0] == "local":
        # actionlint runs ShellCheck with -x, which reads the files a run: step sources.
        local_args = args + ["-shellcheck="]
        job.note("ShellCheck was not run on the run: steps, because it would read the files they source; "
                 "with --allow-docker and actionlint not installed, the container runs it")
    if LOCAL_USES_RE.search(job.text):
        job.note("the workflow names local actions or reusable workflows (uses: ./...); they were not read, "
                 "so their inputs and outputs were not checked")
    mount = folder if job.route[0] == "docker" else None
    result = job.run(local_args + [rel], args + [rel.replace(os.sep, "/")], cwd=folder, mount=mount, workdir="/work")
    if result is None:
        return
    rc, out, stderr = result
    try:
        items = json.loads(out.strip() or "[]")
    except ValueError:
        items = None
    if not isinstance(items, list):
        job.failed(rc, stderr or out)
        return
    for item in items:
        if isinstance(item, dict):  # the snippet field quotes the file and is never printed
            job.finding(item.get("message", ""), item.get("line"), item.get("column"), code=item.get("kind"))
    if rc not in (0, 1) or (rc == 1 and not job.findings):
        job.failed(rc, stderr)


SSHD_HERE_ONLY_RE = re.compile(
    r"no hostkeys available|privilege separation|Unable to load host key|Could not load host key|"
    r"re-exec requires|must be owned by root|bad ownership or modes", re.I)


def check_sshd(job: Job) -> None:
    host_key = []
    keygen = which("ssh-keygen")
    if keygen:
        key = os.path.join(job.temp(), "throwaway_host_key")
        rc, _, _ = run_command([keygen, "-q", "-t", "ed25519", "-N", "", "-f", key], timeout=30)
        if rc == 0:
            host_key = ["-h", key]
    if re.search(r"^\s*Include\s", job.text, re.M | re.I):
        job.note("the Include lines were read from this machine's paths, not the server's")
    if job.base != "sshd_config":
        job.note("checked on its own; on the server, sudo sshd -t checks it with the main config and "
                 "sudo sshd -T shows the values that win (the first value read wins)")
    result = job.run(["-t", "-f", job.path] + host_key, [], cwd=job.dir)
    if result is None:
        return
    rc, out, stderr = result
    for line in f"{out}\n{stderr}".splitlines():
        line = line.strip()
        if not line or re.search(r"terminating, \d+ bad configuration options", line):
            continue
        if SSHD_HERE_ONLY_RE.search(line):
            job.note("sshd stopped at a check of this machine after reading the config: " + line)
            continue
        place = re.match(r"^(?P<file>.+?):? line (?P<line>\d+): (?P<message>.*)$", line)
        if place:
            job.finding(place.group("message"), place.group("line"))
        elif rc != 0:
            job.finding(line)


def check_shell(job: Job) -> None:
    # A private copy, away from any .shellcheckrc beside the script, which can tell ShellCheck to read the
    # files the script sources.
    folder, copy = job.private_copy()
    env = {k: v for k, v in os.environ.items() if k not in ("BASH_ENV", "ENV")}
    env.update(HOME=folder, XDG_CONFIG_HOME=folder)
    if job.route[0] in ("local", "docker"):
        norc = ["--norc"] if job.route[0] == "docker" or _version_tuple(job.version) >= (0, 7) else []
        result = job.run(norc + ["-f", "json1", copy], ["--norc", "-f", "json1", "/work/" + job.base], cwd=folder,
                         mount=folder if job.route[0] == "docker" else None, env=env)
        if result is None:
            return
        rc, out, stderr = result
        try:
            comments = json.loads(out.strip() or '{"comments": []}').get("comments")
        except (ValueError, AttributeError):
            comments = None
        if not isinstance(comments, list) or rc not in (0, 1):
            job.failed(rc, stderr or out)
            return
        for item in comments:
            if isinstance(item, dict):
                job.finding(item.get("message", ""), item.get("line"), item.get("column"), item.get("level"),
                            f"SC{item.get('code')}")
        return
    rc, out, stderr = run_command([job.route[1], "-n", copy], cwd=folder, timeout=job.timeout, env=env)
    if rc is None:
        job.stop(f"the checker did not finish within {job.timeout:g} seconds")
        return
    for line in f"{out}\n{stderr}".splitlines():
        place = re.search(r"line (\d+): (.*)$", line)
        if place:
            job.finding(place.group(2), place.group(1))
        elif line.strip() and rc != 0:
            job.finding(line.strip())
    if rc == 0:
        image = CHECKERS["shell"].image
        job.stop(f"only the syntax was checked with {job.checker_name}; shellcheck was not available (install it, "
                 f"or give --allow-docker to run {image})")


RUNNERS = {
    "dockerfile": check_dockerfile, "compose": check_compose, "caddyfile": check_caddyfile, "nginx": check_nginx,
    "systemd": check_systemd, "kubernetes": check_kubernetes, "github-actions": check_github_actions,
    "sshd": check_sshd, "shell": check_shell,
}


# ------------------------------------------------------------------ warnings about what a file asks of its checker
#
# A best effort to point out, in the output, a file that loads code, reads or writes beyond itself or fetches
# something. Nothing depends on it: an interpreter never runs here without --i-wrote-this-file, whatever this
# finds or misses.

NGINX_CODE_DIRECTIVES = {"load_module", "perl_modules", "perl_require", "perl_set", "perl", "js_import",
                         "js_include", "js_path", "js_preload_object", "ssl_engine"}


def nginx_directives(text: str) -> list:
    """(line, name, arguments) of every directive and block, at any depth, outside comments and quotes."""
    found, words, word, quote, comment, line, start = [], [], [], None, False, 1, None
    for ch in text:
        if ch == "\n":
            line += 1
        if comment:
            comment = ch != "\n"
            continue
        if quote:
            if ch == quote:
                quote = None
            else:
                word.append(ch)
            continue
        if ch in "\"'":
            quote = ch
            start = start or line
            continue
        if ch == "#" and not word:
            comment = True
            continue
        if ch.isspace() or ch in ";{}":
            if word:
                words.append("".join(word))
                word = []
            if ch in ";{" and words:
                found.append((start or line, words[0], words[1:]))
            if ch in ";{}":
                words, start = [], None
            continue
        start = start or line
        word.append(ch)
    return found


def _outside_include(arg: str) -> bool:
    return arg.startswith(("/", "~")) or ".." in arg.replace("\\", "/").split("/")


def nginx_reach(text: str) -> list:
    reasons = []
    for line, name, args in nginx_directives(text):
        if name in NGINX_CODE_DIRECTIVES or "lua" in name:
            reasons.append(f"{name} (line {line}) makes nginx -t load and run code")
        elif name == "include" and args and _outside_include(args[0]):
            reasons.append(f"an include of a file outside the check's own folder (line {line})")
    return reasons


CADDY_SNIPPET_RE = re.compile(r"^\s*\(([^()\s]+)\)\s*\{?\s*$", re.M)


def caddy_reach(text: str) -> list:
    snippets = set(CADDY_SNIPPET_RE.findall(text))
    reasons = []
    for number, raw in enumerate(text.splitlines(), 1):
        words = []
        for word in _split(raw):
            if word.startswith("#"):
                break
            words.append(word)
        if not words:
            continue
        if words[0] == "import" and len(words) > 1 and words[1] not in snippets:
            reasons.append(f"an import of another file (line {number})")
        elif words[0] == "storage":
            reasons.append(f"storage (line {number}) makes caddy validate write where it names")
        elif words[0] == "output" and len(words) > 1 and words[1] in ("file", "net"):
            reasons.append(f"output {words[1]} (line {number}) makes caddy validate open that "
                           + ("file" if words[1] == "file" else "network address"))
    return reasons


REMOTE_RE = re.compile(r"(?:^|[\s\[,'\"])(?:[a-z][a-z0-9+.-]*://|git@)", re.I)


def compose_reach(text: str) -> list:
    reasons, block = [], None
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        top = YAML_TOP_KEY_RE.match(line)
        if top:
            block = top.group(1)
            rest = line[top.end():]
        elif re.match(r"^\s+(?:-\s*)?(?:extends|file)\s*:", line):
            rest = line
        else:
            rest = line if block == "include" else ""
        if (block == "include" or "extends" in line or "file:" in line) and REMOTE_RE.search(rest):
            reasons.append(f"a remote include (line {number}), which docker compose config would download")
    return reasons


def reaches_outside(kind: str, text: str) -> list:
    """What the file asks its checker to do beyond reading it, as far as these patterns see: a warning only."""
    if kind == "nginx":
        return nginx_reach(text)
    if kind == "caddyfile":
        return caddy_reach(text)
    if kind == "compose":
        return compose_reach(text)
    return []


# ------------------------------------------------------------------ choosing the route

def _docker_offer(checker: Checker) -> str:
    """Without --allow-docker: whether the pinned image could run here, and how to get the full check. Only the
    PATH is read; Docker itself is not started without the flag."""
    if which("docker"):
        return (f"Docker is installed here: rerun with --allow-docker to run it in the image {checker.image}, "
                f"with no network and only a copy of this file")
    return f"Docker is not available here (not installed), so the image {checker.image} cannot run either"


def _skip_reason(checker: Checker, docker: Docker, tool_missing: str) -> str:
    hint = checker.hint.replace("FILE", "<file>")
    if checker.image is None:
        return f"{tool_missing}, and {checker.no_image}; run it where the tool is: {hint}"
    if not docker.allowed:
        return f"{tool_missing}. {_docker_offer(checker)}; or run: {hint}"
    return f"{tool_missing} and {docker.state()[1]}; run: {hint}"


def _local_route(job: Job) -> str | None:
    """Use the checker installed here; returns why it cannot."""
    checker = job.checker
    if job.kind == "compose":
        docker_path = which("docker")
        if docker_path:
            rc, out, _ = run_command([docker_path, "compose", "version", "--short"], timeout=30)
            if rc == 0:
                job.route, job.version, job.via = ("compose", [docker_path, "compose"]), out.strip() or None, "installed"
                return None
        standalone = which("docker-compose")
        if standalone:
            job.checker_name = "docker-compose"
            job.route, job.version, job.via = ("compose", [standalone]), _version(standalone, "bash"), "installed"
            return None
        return "docker is not installed" if not docker_path else "the docker compose plugin is not installed"
    local = which(checker.tool)
    if local:
        job.route, job.version, job.via = ("local", local), _version(local, checker.tool), "installed"
        return None
    return f"{checker.tool} is not installed"


def _docker_route(job: Job) -> bool:
    checker = job.checker
    if checker.image and job.docker.allowed and job.docker.state()[0]:
        job.route, job.via = ("docker", checker.image), f"docker image {checker.image}"
        job.version = checker.image_version
        return True
    return False


def _interpreter_route(job: Job, warnings: list) -> str | None:
    """nginx, Caddy, Compose, sshd, systemd: the container, or this machine's tool only for a file the caller wrote."""
    checker = job.checker
    said = "; ".join(warnings)
    if _docker_route(job):
        if said:
            job.note(f"the file has {said}; that ran only inside the container")
        return None
    if job.trusted:
        missing = _local_route(job)
        if missing is None:
            if said:
                job.note(f"the file has {said}, and {checker.tool} installed here acted on it (--i-wrote-this-file)")
            return None
        box = (_docker_offer(checker) if checker.image and not job.docker.allowed
               else (job.docker.state()[1] if checker.image else checker.no_image))
        return f"{missing}, and {box}; or run: {checker.hint.replace('FILE', '<file>')}"
    if said:
        job.note(f"the file has {said}")
    if not checker.image:
        box = f"there is no container for it ({checker.no_image})"
    elif not job.docker.allowed:
        box = _docker_offer(checker)
    else:
        box = f"--allow-docker was given, but {job.docker.state()[1]}"
    return (f"not run here, because {checker.tool} acts on what the file says (it can load modules, follow "
            f"includes, read files and environment variables), so it runs only in its container: {box}. For a "
            f"file you wrote in this session, --i-wrote-this-file runs the {checker.tool} installed here. Or check "
            f"it on the server: {checker.hint.replace('FILE', '<file>')}")


def choose_route(job: Job) -> str | None:
    """Sets job.route and the checker's name and version; returns the reason when nothing can run."""
    checker = job.checker
    job.checker_name, job.version, job.via = checker.tool, None, None
    if checker.interpreter:
        return _interpreter_route(job, reaches_outside(job.kind, job.text)[:5])
    # A parser only reads the file: the one installed here, else its image.
    missing = _local_route(job)
    if missing is None or _docker_route(job):
        return None
    if job.kind == "shell":
        shell = _shebang(job.text)
        for name in (["sh", "bash"] if shell in ("sh", "dash") else ["bash", "sh"]):
            path = which(name)
            if path:
                job.checker_name = f"{name} -n"
                job.route, job.version, job.via = ("syntax", path), _version(path, name), "installed"
                return None
    return _skip_reason(checker, job.docker, missing)


# ------------------------------------------------------------------ one file, start to end

def _compose_extras(job: Job) -> tuple:
    texts, values = [], []
    names = [".env"]
    lines = job.text.splitlines()
    for i, line in enumerate(lines):
        match = re.match(r"^(\s*)env_file\s*:\s*(.*)$", line)
        if not match:
            continue
        inline = match.group(2).strip()
        if inline:
            names += [p for p in re.split(r"[\s,\[\]\"']+", inline) if p]
        for following in lines[i + 1:]:
            item = re.match(r"^\s*-\s+(?:path\s*:\s*)?[\"']?([^\"'#\s]+)", following)
            if not item:
                if following.strip() and not following.strip().startswith(("required", "format")):
                    break
                continue
            names.append(item.group(1))
    for name in names[:20]:
        path = os.path.join(job.dir, name)
        try:
            if os.path.isfile(path) and os.path.getsize(path) <= MAX_BYTES:
                with open(path, encoding="utf-8", errors="replace") as handle:
                    texts.append(handle.read())
        except OSError:
            continue
    for name in set(re.findall(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)", job.text)):
        if os.environ.get(name):
            values.append(os.environ[name])
    return texts, values


def check_file(given: str, kind_override: str | None, docker: Docker, timeout: float, trusted: bool = False) -> dict:
    entry = {"file": given, "kind": None, "kind_label": None, "detected_by": None, "checker": None,
             "checker_version": None, "via": None, "status": None, "reason": None, "findings": [], "notes": []}
    path = os.path.abspath(given)
    if not os.path.lexists(path):
        entry.update(status="missing", reason="the file does not exist")
        return entry
    if not os.path.isfile(path):
        entry.update(status="missing", reason="not a regular file")
        return entry
    if os.path.islink(path):
        folder = os.path.realpath(os.path.dirname(path))
        if os.path.commonpath([folder, os.path.realpath(path)]) != folder:
            entry.update(status="skipped", reason="a symbolic link to a file outside its own folder, so it was not "
                                                  "read; name the file it points to if you mean to check that file")
            return entry
    try:
        if os.path.getsize(path) > MAX_BYTES:
            entry.update(status="skipped", reason=f"the file is larger than {MAX_BYTES // (1024 * 1024)} MB")
            return entry
        with open(path, "rb") as handle:
            data = handle.read(MAX_BYTES + 1)
    except OSError:
        entry.update(status="missing", reason="the file could not be read")
        return entry
    text = data.decode("utf-8", "replace").lstrip("﻿")
    if kind_override:
        kind, how = kind_override, "named with --kind"
    else:
        kind, how = detect_kind(path, text)
    if kind is None:
        entry.update(status="unknown", reason=f"{how}; name its kind with --kind if you know it")
        return entry
    entry.update(kind=kind, kind_label=CHECKERS[kind].label, detected_by=how)
    try:
        mode = (os.stat(path).st_mode & 0o644) | 0o400
    except OSError:
        mode = 0o600
    job = Job(given, path, text, kind, docker, timeout, data=data[:MAX_BYTES], mode=mode, trusted=trusted)
    extra_texts, extra_values = _compose_extras(job) if kind == "compose" else ([], [])
    job.masker = Masker(text, extra_texts, extra_values,
                        paths=[(path, job.base), (os.path.realpath(path), job.base), ("/work/" + job.base, job.base),
                               (job.dir + os.sep, ""), ("/work/", "")])
    digest = hashlib.sha256(data).hexdigest()
    try:
        reason = choose_route(job)
        entry.update(checker=job.checker_name, checker_version=job.version, via=job.via)
        if reason:
            entry.update(status="skipped", reason=job.say(reason, MAX_REASON), notes=job.notes)
            return entry
        RUNNERS[kind](job)
    finally:
        for folder in job.temp_dirs:
            shutil.rmtree(folder, ignore_errors=True)
    try:
        with open(path, "rb") as handle:
            if hashlib.sha256(handle.read(MAX_BYTES + 1)).hexdigest() != digest:
                job.stop("the file changed while it was being checked; check it again")
    except OSError:
        job.stop("the file could not be read again after the check")
    entry.update(checker=job.checker_name, checker_version=job.version, via=job.via,
                 findings=job.findings, notes=job.notes)
    if job.findings:
        entry["status"] = "findings"
        if job.incomplete:
            entry["reason"] = "; ".join(job.incomplete)
    elif job.incomplete:
        entry.update(status="incomplete", reason="; ".join(job.incomplete))
    else:
        entry["status"] = "clean"
    return entry


# ------------------------------------------------------------------ output

def render_text(report: dict) -> str:
    out = []
    for entry in report["files"]:
        head = f"{entry['file']}: "
        if entry["kind"]:
            head += f"{entry['kind_label']} ({entry['detected_by']})"
            if entry["checker"]:
                version = f" {entry['checker_version']}" if entry["checker_version"] else ""
                head += f", {entry['checker']}{version} ({entry['via'] or 'not run'})"
        else:
            head += entry["status"]
        words = {"clean": "clean", "findings": f"{len(entry['findings'])} finding(s)",
                 "incomplete": "not fully checked", "skipped": "not checked", "unknown": "not checked",
                 "missing": "not checked"}
        out.append(f"{head}: {words[entry['status']]}")
        for item in entry["findings"]:
            where = f"line {item['line']}" if item["line"] else "file"
            label = " ".join(x for x in (item["level"], item["code"]) if x)
            out.append(f"  {where} [{label}] {item['message']}")
        if entry["reason"]:
            out.append(f"  reason: {entry['reason']}")
        for note in entry["notes"]:
            out.append(f"  note: {note}")
    s = report["summary"]
    out.append(f"Summary: {s['files']} file(s), {s['clean']} clean, {s['findings']} with findings, "
               f"{s['not_checked']} not fully checked.")
    return "\n".join(out)


def _timeout(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a number of seconds") from None
    if not 0 < value <= 3600 or value != value:
        raise argparse.ArgumentTypeError("the timeout must be more than 0 and at most 3600 seconds")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog="check_config.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                    description="Check config files with the real tool for their kind, read-only.", epilog=EPILOG)
    parser.add_argument("files", nargs="+", metavar="FILE", help="the files to check")
    parser.add_argument("--allow-docker", action="store_true",
                        help="run nginx, Caddy, Compose and systemd checks, and a missing parser, in the pinned "
                             "official image (a copy of the file only, no network)")
    parser.add_argument("--i-wrote-this-file", dest="trusted", action="store_true",
                        help="when the container cannot be used, run the nginx, Caddy, Compose, sshd or systemd "
                             "checker installed here; it will act on what the file says. It applies to every file "
                             "named on the command line, so name only files whose every line you wrote in this "
                             "session; a file you edited, or one from a project you were given, is a given file. "
                             "With --allow-docker and Docker answering, the container is used anyway")
    parser.add_argument("--json", action="store_true", help="print one JSON object instead of text")
    parser.add_argument("--kind", choices=sorted(CHECKERS), help="treat every file given as this kind")
    parser.add_argument("--timeout", type=_timeout, default=120.0, metavar="SECONDS",
                        help="time limit for each check (default 120; the first Docker run may download an image)")
    args = parser.parse_args(argv)
    docker = Docker(args.allow_docker)
    files = [check_file(given, args.kind, docker, args.timeout, args.trusted) for given in args.files]
    counts = {"files": len(files), "clean": sum(f["status"] == "clean" for f in files),
              "findings": sum(f["status"] == "findings" for f in files)}
    counts["not_checked"] = counts["files"] - counts["clean"] - counts["findings"]
    report = {"files": files, "summary": counts, "docker_allowed": args.allow_docker}
    print(json.dumps(report, indent=2) if args.json else render_text(report))
    if counts["findings"]:
        return 1
    return 2 if counts["not_checked"] else 0


if __name__ == "__main__":
    sys.exit(main())
