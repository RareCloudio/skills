#!/usr/bin/env python3
"""Check a website from the outside: name resolution, HTTP and HTTPS, certificate, ports.

What it does: resolves the host, requests the URL and follows up to five redirects by hand,
checks whether plain HTTP sends visitors to HTTPS, reads the certificate (trust against the
system store, host name match, days left, issuer) and tries a plain TCP connect to each port
listed with --expect-open or --expect-closed. It prints one JSON object; anything it could
not find out is listed under "not_determined" and anything wrong under "problems".
What it never does: send anything but plain GET requests, read a response body, write a
file, run longer than --timeout seconds in total (every connect and read is bounded by
what is left of that time), print the user name, password or query string of a URL, or
follow a redirect from a public site into a loopback, private, link-local, reserved or
multicast address.

Usage: python check_site.py https://example.com [--expect-open 80,443] [--expect-closed 22,3306,5432]
"""
from __future__ import annotations

import argparse
import http.client
import ipaddress
import json
import math
import os
import re
import socket
import ssl
import sys
import threading
import time
from urllib.parse import urljoin, urlsplit

MAX_REDIRECTS = 5
MAX_PORTS = 64
EXPIRY_WARNING_DAYS = 14
REDIRECT_CODES = {301, 302, 303, 307, 308}
DEFAULT_PORTS = {"http": 80, "https": 443}
USER_AGENT = "ship-it-check-site/1"
# OpenSSL's X509_V_FLAG_NO_CHECK_TIME: lets an expired certificate be decoded for its details.
NO_CHECK_TIME = 0x200000
# OpenSSL's X509_V_FLAG_PARTIAL_CHAIN; the ssl module names it only from Python 3.10.
PARTIAL_CHAIN = getattr(ssl, "VERIFY_X509_PARTIAL_CHAIN", 0x80000)
HOSTNAME_MISMATCH = 62
IP_ADDRESS_MISMATCH = 64
MISMATCH_CODES = {HOSTNAME_MISMATCH, IP_ADDRESS_MISMATCH}
NO_LOCAL_ISSUER = 20

EPILOG = """\
Output keys: url, resolved, http {status, final_url, redirected_to_https, seconds},
tls {valid, matches_host, days_left, issuer}, ports {open, closed, unexpected_open,
unexpected_closed}, problems, not_determined. A value that could not be found out is null.
A public site answering plain HTTP on its own port with no HTTPS is a problem.
"valid" means the certificate chain is trusted and in date; "matches_host" says whether it
names the host. The tls keys describe the start host (or, for a plain HTTP start, the HTTPS
address it ends on); the certificate of every other HTTPS host and port the redirects pass
through is checked too, and its problems name it. A port that refuses or never answers
counts as closed. Printed URLs carry no user name, password or query string.
Redirects are followed by hand, at most five. When the site resolves to public addresses,
a redirect to an internal address (loopback, private, link-local, reserved, multicast) is
not followed and is reported. When the site itself is internal (a local test or a private
staging host), redirects are followed on the same host and port (or between its standard
HTTP and HTTPS ports) and to public addresses only.
Exit codes: 0 no problems, 1 problems found, 2 bad usage.
Needs Python 3.9 or newer, standard library only.
--ca-file trusts the certificates in that PEM file instead of the system store; it is meant
for testing against a server with a private or self-signed certificate.
"""


class Parser(argparse.ArgumentParser):
    """argparse that reports a usage error as one line on stderr and exits 2."""

    def error(self, message):
        print(f"usage error: {message} (see --help)", file=sys.stderr)
        sys.exit(2)


class Deadline:
    """One shared time budget; each network operation gets what is left of it."""

    def __init__(self, seconds: float):
        self.end = time.monotonic() + seconds

    def left(self) -> float:
        return self.end - time.monotonic()

    def budget(self) -> float:
        left = self.left()
        if left <= 0:
            raise TimeoutError("the time limit was reached")
        return left


def _host_for_url(host: str) -> str:
    return f"[{host}]" if ":" in host else host


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


class UrlProblem(ValueError):
    """An address that cannot be used; .text is a fixed message that quotes no part of it."""

    def __init__(self, text: str):
        super().__init__(text)
        self.text = text


def _split(url: str):
    """urlsplit that never repeats the address in an error: for some host names urlsplit raises a
    ValueError whose message quotes the whole address, user name and password included."""
    try:
        return urlsplit(url)
    except ValueError:
        raise UrlProblem("the address could not be read") from None


def _join(base: str, location: str) -> str:
    try:
        return urljoin(base, location)
    except ValueError:
        raise UrlProblem("the address could not be read") from None


def _display(url: str) -> str:
    """A URL safe to print: scheme, host, port and path; no user name, password, query or fragment."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "(an unreadable address)"
    if not parts.hostname:
        return f"(a {parts.scheme or 'relative'} address)"
    netloc = _host_for_url(parts.hostname) + (f":{port}" if port else "")
    path = parts.path or "/"
    return f"{parts.scheme}://{netloc}{path[:200]}"


def address_is_public(host: str, ip: str) -> bool:
    """True for a globally routable unicast address. The host name is unused here; tests replace
    this function to count a local test server as public."""
    try:
        addr = ipaddress.ip_address(ip.split("%", 1)[0])
    except ValueError:
        return False
    if addr.version == 6:
        # An IPv6 form that carries an IPv4 address is judged by that IPv4 address.
        if addr.ipv4_mapped:
            addr = addr.ipv4_mapped
        elif addr in NAT64 or int(addr) >> 32 == 0:  # NAT64, or IPv4-compatible (::a.b.c.d)
            addr = ipaddress.IPv4Address(int(addr) & 0xFFFFFFFF)
        elif addr.sixtofour:
            addr = addr.sixtofour
        elif addr.teredo:
            addr = addr.teredo[1]
    return addr.is_global and not addr.is_multicast


def _resolve_raw(host: str) -> list[str] | None:
    """Test hook: return addresses for a host to skip the system lookup; None means use the system."""
    return None


def _reason(exc: BaseException) -> str:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return "no answer within the time limit"
    if isinstance(exc, ConnectionRefusedError):
        return "connection refused"
    if isinstance(exc, ssl.SSLCertVerificationError):
        return exc.verify_message or "certificate not trusted"
    if isinstance(exc, ssl.SSLError):
        return f"TLS error ({exc.reason or exc.__class__.__name__})"
    if isinstance(exc, OSError) and exc.strerror:
        return exc.strerror.lower()
    # Never str(exc): URL and request-building errors quote the address, query string included.
    if isinstance(exc, http.client.HTTPException):
        return HTTP_ERRORS.get(type(exc).__name__, f"the response could not be read ({type(exc).__name__})")
    if isinstance(exc, UrlProblem):
        return exc.text
    if isinstance(exc, (ValueError, UnicodeError)):
        return "the address could not be used"
    if isinstance(exc, LookupError):
        return "the name does not resolve"
    if isinstance(exc, OSError):
        return f"a network error ({type(exc).__name__})"
    return f"an unexpected error ({type(exc).__name__})"


HTTP_ERRORS = {
    "InvalidURL": "the address could not be used",
    "LineTooLong": "a response line was too long",
    "RemoteDisconnected": "the server closed the connection without answering",
    "BadStatusLine": "the server did not answer with HTTP",
    "IncompleteRead": "the response ended early",
    "HTTPException": "the response could not be read (too many headers or a malformed header)",
}
UNSAFE_URL_CHARS = re.compile(r"[\x00-\x20\x7f]")
NAT64 = ipaddress.ip_network("64:ff9b::/96")


class Resolver:
    """Name lookups bounded by the deadline (getaddrinfo itself has no timeout).

    The first answer for a name is the only one ever used. Checks run in parallel, so two lookups
    of one name can overlap and get different answers; if a later answer replaced an earlier one, a
    connection could go to an address the redirect guard never saw.
    """

    def __init__(self, deadline: Deadline):
        self.deadline = deadline
        self.cache: dict[str, list[str]] = {}
        self.lock = threading.Lock()

    def _keep_first(self, host: str, ips: list[str]) -> list[str]:
        with self.lock:
            return self.cache.setdefault(host, ips)

    def __call__(self, host: str) -> list[str]:
        if _is_ip(host):
            return [host]
        with self.lock:
            if host in self.cache:
                return self.cache[host]
        forced = _resolve_raw(host)
        if forced is not None:
            return self._keep_first(host, list(forced))
        box: dict = {}

        def work():
            try:
                infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
                box["ips"] = list(dict.fromkeys(info[4][0] for info in infos))
            except (OSError, UnicodeError) as exc:
                box["error"] = exc

        thread = threading.Thread(target=work, daemon=True)
        thread.start()
        thread.join(max(0.0, self.deadline.left()))
        if thread.is_alive():
            raise TimeoutError(f"looking up {host} did not finish within the time limit")
        if "error" in box:
            raise LookupError(f"the name {host} does not resolve ({_reason(box['error'])})")
        if not box["ips"]:
            raise LookupError(f"the name {host} has no address")
        return self._keep_first(host, box["ips"])


def connect(ips: list[str], port: int, deadline: Deadline) -> socket.socket:
    """TCP connect to the first address that answers, splitting the time left between them."""
    last: BaseException | None = None
    for i, ip in enumerate(ips):
        share = deadline.budget() / (len(ips) - i)
        try:
            return socket.create_connection((ip, port), timeout=share)
        except OSError as exc:
            last = exc
    raise last if last else OSError("no address to connect to")


def request(url: str, resolve: Resolver, deadline: Deadline) -> tuple[int, str | None]:
    """One GET without reading the body. Certificates are not checked here; tls_check does that."""
    parts = _split(url)
    host, scheme = parts.hostname, parts.scheme
    port = parts.port or DEFAULT_PORTS[scheme]
    sock = connect(resolve(host), port, deadline)
    try:
        if scheme == "https":
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            sock.settimeout(deadline.budget())
            sock = ctx.wrap_socket(sock, server_hostname=host)
            conn = http.client.HTTPSConnection(host, port, timeout=deadline.budget())
        else:
            conn = http.client.HTTPConnection(host, port, timeout=deadline.budget())
        conn.sock = sock
        path = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
        sock.settimeout(deadline.budget())
        conn.request("GET", path, headers={"User-Agent": USER_AGENT, "Accept": "*/*", "Connection": "close"})
        sock.settimeout(deadline.budget())
        response = conn.getresponse()
        return response.status, response.getheader("Location")
    finally:
        sock.close()


def _port_of(parts) -> int:
    return parts.port or DEFAULT_PORTS[parts.scheme]


def redirect_refusal(start_url: str, start_public: bool, target_url: str, resolve: Resolver) -> bool:
    """True when a redirect to target_url must not be followed (it leads to an internal address)."""
    target = _split(target_url)
    ips = resolve(target.hostname)
    if all(address_is_public(target.hostname, ip) for ip in ips):
        return False
    if start_public:
        return True
    start = _split(start_url)
    same_host = target.hostname == start.hostname
    same_port = _port_of(target) == _port_of(start)
    standard_ports = _port_of(start) == DEFAULT_PORTS[start.scheme] and _port_of(target) == DEFAULT_PORTS[target.scheme]
    return not (same_host and (same_port or standard_ports))


def follow(url: str, resolve: Resolver, deadline: Deadline) -> dict:
    """Request url and follow redirects by hand, at most MAX_REDIRECTS of them.

    "final_url" and "error" are already safe to print; "final_raw" and "visited" (every address
    that answered, each one past the redirect guard) are for internal use only.
    """
    start = time.monotonic()
    out = {"status": None, "final_url": None, "final_raw": None, "error": None, "visited": []}
    current = url
    try:
        host = _split(url).hostname
        start_public = all(address_is_public(host, ip) for ip in resolve(host))
        for hop in range(MAX_REDIRECTS + 1):
            status, location = request(current, resolve, deadline)
            out["status"], out["final_raw"] = status, current
            out["visited"].append(current)
            if status not in REDIRECT_CODES or not location:
                break
            if UNSAFE_URL_CHARS.search(location.strip()):
                out["error"] = (f"{_display(current)} redirects to an address with spaces or control "
                                "characters; not followed")
                break
            try:
                nxt = _join(current, location.strip())
                nparts = _split(nxt)
            except UrlProblem:
                out["error"] = f"{_display(current)} redirects to an address that could not be read; not followed"
                break
            try:
                nparts.port
            except ValueError:
                out["error"] = f"{_display(current)} redirects to an address with an invalid port; not followed"
                break
            if nparts.scheme not in DEFAULT_PORTS or not nparts.hostname:
                what = "no host name" if nparts.scheme in DEFAULT_PORTS else "an unsupported scheme"
                out["error"] = (f"{_display(current)} redirects to something that is not a web address "
                                f"({what}); not followed")
                break
            if hop == MAX_REDIRECTS:
                out["error"] = f"more than {MAX_REDIRECTS} redirects starting at {_display(url)}; stopped following"
                break
            try:
                refused = redirect_refusal(url, start_public, nxt, resolve)
            except TimeoutError:
                out["error"] = (f"{_display(current)}: looking up the redirect target did not finish within the "
                                "time limit; not followed")
                break
            except LookupError:
                out["error"] = f"{_display(current)}: the redirect target does not resolve; not followed"
                break
            if refused:
                out["error"] = f"{_display(current)} redirects to an internal address (not followed)"
                break
            current = nxt
    except (OSError, LookupError, http.client.HTTPException, ValueError) as exc:
        out["error"] = f"the request to {_display(current)} failed: {_reason(exc)}"
        out["status"] = None
        out["final_raw"] = None
    out["final_url"] = _display(out["final_raw"]) if out["final_raw"] else None
    out["seconds"] = round(time.monotonic() - start, 3)
    return out


def _handshake(ctx: ssl.SSLContext, host: str, ips: list[str], port: int, deadline: Deadline):
    sock = connect(ips, port, deadline)
    try:
        sock.settimeout(deadline.budget())
        with ctx.wrap_socket(sock, server_hostname=host) as tls:
            return tls.getpeercert(), tls.getpeercert(binary_form=True)
    finally:
        sock.close()


def _trust_store_found() -> bool:
    if sys.platform == "win32":
        return True
    paths = ssl.get_default_verify_paths()
    if paths.cafile and os.path.isfile(paths.cafile):
        return True
    try:
        return bool(paths.capath and os.path.isdir(paths.capath) and os.listdir(paths.capath))
    except OSError:
        return False


def _dns_match(pattern: str, host: str) -> bool:
    if pattern == host:
        return True
    if pattern.startswith("*.") and "." in host:
        first, rest = host.split(".", 1)
        return bool(first) and rest == pattern[2:]
    return False


def matches_host(cert: dict, host: str) -> bool:
    host = host.lower().rstrip(".")
    sans = cert.get("subjectAltName", ())
    if _is_ip(host):
        want = ipaddress.ip_address(host)
        for kind, value in sans:
            if kind == "IP Address":
                try:
                    if ipaddress.ip_address(value.strip()) == want:
                        return True
                except ValueError:
                    continue
        return False
    return any(kind == "DNS" and _dns_match(value.lower().rstrip("."), host) for kind, value in sans)


def _issuer(cert: dict) -> str | None:
    fields = {k: v for rdn in cert.get("issuer", ()) for k, v in rdn}
    org, cn = fields.get("organizationName"), fields.get("commonName")
    if org and cn and org != cn:
        return f"{org} ({cn})"
    return org or cn


def tls_check(host: str, port: int, resolve: Resolver, deadline: Deadline, ca_file: str | None) -> dict:
    out = {"valid": None, "matches_host": None, "days_left": None, "issuer": None,
           "error": None, "note": None, "target": f"{_host_for_url(host)}:{port}"}
    try:
        ips = resolve(host)
        strict = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
        cert = None
        try:
            cert, _ = _handshake(strict, host, ips, port, deadline)
            out["valid"], out["matches_host"] = True, True
        except ssl.SSLCertVerificationError as exc:
            if exc.verify_code in MISMATCH_CODES:
                loose = ssl.create_default_context(cafile=ca_file) if ca_file else ssl.create_default_context()
                loose.check_hostname = False
                cert, _ = _handshake(loose, host, ips, port, deadline)
                out["valid"], out["matches_host"] = True, False
            else:
                if exc.verify_code == NO_LOCAL_ISSUER and not ca_file and not _trust_store_found():
                    out["note"] = ("this Python found no system certificate store, so whether the "
                                   "certificate is trusted was not determined")
                else:
                    out["valid"] = False
                    out["error"] = f"the certificate is not trusted: {exc.verify_message}"
                cert = _decode_untrusted(host, ips, port, deadline)
                if cert:
                    out["matches_host"] = matches_host(cert, host)
        if cert:
            out["issuer"] = _issuer(cert)
            if cert.get("notAfter"):
                remaining = ssl.cert_time_to_seconds(cert["notAfter"]) - time.time()
                out["days_left"] = math.floor(remaining / 86400)
        elif out["valid"] is not None or out["note"]:
            out["note"] = (out["note"] + "; " if out["note"] else "") + "the certificate details could not be read"
    except ssl.SSLError as exc:
        out["valid"] = False
        out["error"] = f"HTTPS did not work on {out['target']}: {_reason(exc)}"
    except (OSError, LookupError, ValueError) as exc:
        out["error"] = f"HTTPS did not work on {out['target']}: {_reason(exc)}"
    return out


def _decode_untrusted(host: str, ips: list[str], port: int, deadline: Deadline) -> dict | None:
    """Read the fields of a certificate that failed verification: fetch it, then trust only it."""
    try:
        blind = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        blind.check_hostname = False
        blind.verify_mode = ssl.CERT_NONE
        _, der = _handshake(blind, host, ips, port, deadline)
        if not der:
            return None
        pinned = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        pinned.check_hostname = False
        pinned.load_verify_locations(cadata=der)
        try:
            pinned.verify_flags = pinned.verify_flags | PARTIAL_CHAIN | NO_CHECK_TIME
        except (ValueError, ssl.SSLError, AttributeError):
            pass
        cert, _ = _handshake(pinned, host, ips, port, deadline)
        return cert
    except (OSError, LookupError, ValueError):
        return None


def _tls_findings(tls: dict, problems: list[str], unknown: list[str], named: bool) -> None:
    """Turn one certificate check into problems; `named` puts the target in every line."""
    where = f" on {tls['target']}" if named else ""
    message = tls["error"]  # a fixed sentence built by tls_check, never an exception's text
    if message:
        problems.append(message if not named or tls["target"] in message else f"{tls['target']}: {message}")
    if tls["note"]:
        unknown.append(f"{tls['target']}: {tls['note']}" if named else tls["note"])
    if tls["matches_host"] is False:
        problems.append(f"the certificate on {tls['target']} is for another name")
    days = tls["days_left"]
    if days is not None and days < 0:
        problems.append(f"the certificate{where} expired {-days} days ago")
    elif days is not None and days < EXPIRY_WARNING_DAYS:
        problems.append(f"the certificate{where} expires in {days} days")


def port_state(ips: list[str], port: int, deadline: Deadline) -> str:
    try:
        connect(ips, port, deadline).close()
        return "open"
    except (OSError, ValueError):
        return "closed"


def _run_parallel(jobs: dict, end: float) -> dict:
    """Run each job in a daemon thread; collect what finished before `end`."""
    results: dict = {}

    def wrap(name, fn):
        try:
            results[name] = fn()
        except Exception as exc:  # a bug in one check must not hide the others
            results[name] = {"crashed": exc.__class__.__name__}

    threads = [threading.Thread(target=wrap, args=(name, fn), daemon=True) for name, fn in jobs.items()]
    for t in threads:
        t.start()
    for t in threads:
        t.join(max(0.0, end - time.monotonic()))
    return dict(results)


def _https_hops(visited: list[str]) -> list[tuple[str, int]]:
    """The distinct HTTPS (host, port) pairs of a redirect chain, in order."""
    parts = [_split(url) for url in visited]
    return list(dict.fromkeys((p.hostname, _port_of(p)) for p in parts if p.scheme == "https"))


def check(url: str, expect_open: list[int], expect_closed: list[int], timeout: float,
          ca_file: str | None) -> dict:
    hard_end = time.monotonic() + timeout
    deadline = Deadline(timeout - min(0.5, timeout * 0.1))
    resolve = Resolver(deadline)
    parts = _split(url)
    host, scheme = parts.hostname, parts.scheme
    custom_port = parts.port is not None and parts.port != DEFAULT_PORTS[scheme]
    problems: list[str] = []
    unknown: list[str] = []
    report = {"url": _display(url), "resolved": [],
              "http": {"status": None, "final_url": None, "redirected_to_https": None, "seconds": None},
              "tls": {"valid": None, "matches_host": None, "days_left": None, "issuer": None},
              "ports": {"open": [], "closed": [], "unexpected_open": [], "unexpected_closed": []},
              "problems": problems, "not_determined": unknown}

    try:
        ips = resolve(host)
        report["resolved"] = ips
        site_public = all(address_is_public(host, ip) for ip in ips)
    except TimeoutError:
        problems.append(f"looking up {host} did not finish within the time limit")
        unknown.append("HTTP, HTTPS and ports were not checked because the name did not resolve")
        return report
    except LookupError:
        problems.append(f"the name {host} does not resolve")
        unknown.append("HTTP, HTTPS and ports were not checked because the name did not resolve")
        return report

    start = (host, parts.port or DEFAULT_PORTS[scheme])

    def main_chain():
        result = follow(url, resolve, deadline)
        final = result.get("final_raw") or ""
        if scheme == "http" and _split(final).scheme == "https":
            fparts = _split(final)
            target = (fparts.hostname, fparts.port or 443)
        elif scheme == "http" and not custom_port:
            target = (host, 443)
        elif scheme == "https":
            target = None  # the start host is checked in parallel by the tls job
        else:
            target = False
        result["tls_target"] = target
        # A browser stops at a bad certificate anywhere in the chain, so each other HTTPS hop counts.
        covered = {target, start if scheme == "https" else None}
        hops = [hop for hop in _https_hops(result["visited"]) if hop not in covered]
        wanted = hops + ([target] if target else [])
        # Stop waiting a little before hard_end, so this chain's own result still arrives in time.
        checks = _run_parallel({hop: (lambda h=hop: tls_check(h[0], h[1], resolve, deadline, ca_file))
                                for hop in wanted}, (deadline.end + hard_end) / 2)
        if target and "crashed" not in checks.get(target, {"crashed": None}):
            result["tls"] = checks[target]
        result["hop_tls"] = [(f"{_host_for_url(hop[0])}:{hop[1]}", checks.get(hop)) for hop in hops]
        return result

    jobs = {"main": main_chain}
    if scheme == "https":
        jobs["tls"] = lambda: tls_check(host, parts.port or 443, resolve, deadline, ca_file)
        if not custom_port:
            plain = f"http://{_host_for_url(host)}{parts.path or '/'}" + (f"?{parts.query}" if parts.query else "")
            jobs["plain"] = lambda: follow(plain, resolve, deadline)
    for port in sorted(set(expect_open) | set(expect_closed)):
        jobs[f"port:{port}"] = (lambda p=port: port_state(ips, p, deadline))
    done = _run_parallel(jobs, hard_end)

    def unfinished(name, what):
        if name not in done:
            problems.append(f"the {what} did not finish within {timeout:g} seconds")
            return True
        if isinstance(done[name], dict) and "crashed" in done[name]:
            problems.append(f"the {what} failed unexpectedly ({done[name]['crashed']})")
            return True
        return False

    # HTTP
    main = None if unfinished("main", f"request to {_display(url)}") else done["main"]
    if main:
        report["http"].update(status=main["status"], final_url=main["final_url"], seconds=main["seconds"])
        if main["error"]:
            problems.append(main["error"])
        elif main["status"] is not None and main["status"] >= 400:
            problems.append(f"{main['final_url']} answered with status {main['status']}")
        if scheme == "http" and main["final_raw"]:
            report["http"]["redirected_to_https"] = _split(main["final_raw"]).scheme == "https"

    # Plain HTTP to HTTPS
    if scheme == "https" and custom_port:
        unknown.append("whether plain HTTP redirects to HTTPS: the URL names its own port, so there is "
                       "no standard plain HTTP address to try")
    elif scheme == "https" and not unfinished("plain", "plain HTTP check"):
        plain = done["plain"]
        if plain["final_raw"] is None:
            unknown.append(f"whether plain HTTP redirects to HTTPS: {plain['error'] or 'no answer'}")
        else:
            report["http"]["redirected_to_https"] = _split(plain["final_raw"]).scheme == "https"
            if plain["error"]:
                problems.append(f"plain HTTP: {plain['error']}")
    # On a URL with its own plain HTTP port there is no standard HTTPS address to send visitors to.
    # For a public site that is a problem of its own; a local or private target is left alone.
    if report["http"]["redirected_to_https"] is False and not (scheme == "http" and custom_port):
        problems.append("plain HTTP answers without redirecting to HTTPS")
    elif report["http"]["redirected_to_https"] is False and site_public:
        problems.append("served over plain HTTP; no HTTPS found on this address")

    # TLS
    tls = None
    if scheme == "https":
        tls = None if unfinished("tls", "certificate check") else done["tls"]
    elif main is not None:
        if main.get("tls_target") is False:
            unknown.append("the certificate: the URL is plain HTTP on its own port, so there is no "
                           "standard HTTPS address to check")
        else:
            tls = main.get("tls")
            if tls is None:
                unknown.append("the certificate: the time limit was reached before it was checked")
    if tls:
        for key in ("valid", "matches_host", "days_left", "issuer"):
            report["tls"][key] = tls[key]
        _tls_findings(tls, problems, unknown, named=False)
    # Every other HTTPS host and port the redirects passed through.
    for name, hop_tls in (main.get("hop_tls", []) if main is not None else []):
        if hop_tls is None or "crashed" in hop_tls:
            unknown.append(f"the certificate on {name}: the check did not finish within the time limit")
        else:
            _tls_findings(hop_tls, problems, unknown, named=True)

    # Ports
    ports = report["ports"]
    for port in sorted(set(expect_open) | set(expect_closed)):
        name = f"port:{port}"
        if name not in done or not isinstance(done[name], str):
            unknown.append(f"port {port}: the connect did not finish within the time limit")
            continue
        ports[done[name]].append(port)
    ports["unexpected_open"] = [p for p in ports["open"] if p in expect_closed]
    ports["unexpected_closed"] = [p for p in ports["closed"] if p in expect_open]
    for p in ports["unexpected_open"]:
        problems.append(f"port {p} is open but was expected to be closed")
    for p in ports["unexpected_closed"]:
        problems.append(f"port {p} is closed or does not answer but was expected to be open")
    return report


def _ports(text: str) -> list[int]:
    out = []
    for piece in filter(None, (p.strip() for p in text.split(","))):
        if not piece.isdigit() or not 1 <= int(piece) <= 65535:
            raise argparse.ArgumentTypeError(f"'{piece}' is not a port number (1 to 65535)")
        out.append(int(piece))
    if len(set(out)) > MAX_PORTS:
        raise argparse.ArgumentTypeError(f"at most {MAX_PORTS} ports")
    return sorted(set(out))


def _timeout(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"'{text}' is not a number of seconds") from None
    if not 0 < value <= 300 or math.isnan(value):
        raise argparse.ArgumentTypeError("the timeout must be more than 0 and at most 300 seconds")
    return value


def _normalise_url(raw: str) -> str:
    """Messages here are fixed: they never quote the address, whose query may hold a token."""
    if UNSAFE_URL_CHARS.search(raw):
        raise UrlProblem("the URL contains a space or a control character")
    text = raw
    if "://" not in text:
        text = "https://" + text
    parts = _split(text)
    if parts.scheme.lower() not in DEFAULT_PORTS:
        raise UrlProblem("the URL must start with http:// or https://")
    try:
        if not parts.hostname:
            raise UrlProblem("the URL has no host name")
        port = parts.port
    except UrlProblem:
        raise
    except ValueError:
        raise UrlProblem("the URL has an invalid port or host") from None
    netloc = _host_for_url(parts.hostname) + (f":{port}" if port else "")
    query = f"?{parts.query}" if parts.query else ""
    return f"{parts.scheme.lower()}://{netloc}{parts.path or '/'}{query}"


def main(argv: list[str] | None = None) -> int:
    parser = Parser(prog="check_site.py", formatter_class=argparse.RawDescriptionHelpFormatter,
                    description="Check a website from the outside and print one JSON object.",
                    epilog=EPILOG)
    parser.add_argument("url", help="the address to check; https:// is assumed when no scheme is given")
    parser.add_argument("--expect-open", type=_ports, default=[], metavar="PORTS",
                        help="comma-separated ports that should accept connections, for example 80,443")
    parser.add_argument("--expect-closed", type=_ports, default=[], metavar="PORTS",
                        help="comma-separated ports that should not accept connections, for example 22,3306,5432")
    parser.add_argument("--timeout", type=_timeout, default=10.0, metavar="SECONDS",
                        help="total time budget for the whole check (default 10)")
    parser.add_argument("--ca-file", metavar="PEM",
                        help="trust these certificates instead of the system store (for testing)")
    args = parser.parse_args(argv)
    try:
        url = _normalise_url(args.url)
    except UrlProblem as problem:
        parser.error(problem.text)
    if args.ca_file and not os.path.isfile(args.ca_file):
        parser.error(f"--ca-file {args.ca_file} is not a readable file")
    both = set(args.expect_open) & set(args.expect_closed)
    if both:
        parser.error(f"ports listed as both open and closed: {sorted(both)}")
    report = check(url, args.expect_open, args.expect_closed, args.timeout, args.ca_file)
    print(json.dumps(report, indent=2))
    sys.stdout.flush()
    return 1 if report["problems"] else 0


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    os._exit(code)  # leave at once even if a lookup thread is still waiting on the resolver
