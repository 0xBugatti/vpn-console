"""Run a stored profile as a systemd tunnel on this server (owner request, 2026-10-12).

Pure logic, no I/O: how a profile maps to a unit and an interface, which of its lines are
refused, need a typed confirmation or are removed, how the installed copy is rendered, and
how routes read from /proc/net are checked once the tunnel is up. The host adapter does the
file and systemd work; server/tunnelctl.py orchestrates it.

The installed copy is "tunnel-only": it never replaces the server's default route and never
touches DNS, so SSH, nginx and Tailscale keep working whatever the VPN pushes.
"""
from __future__ import annotations

import ipaddress
import re
import shlex
import socket
import struct
from dataclasses import dataclass, field
from typing import Any

MARKER = "# vpn-console-managed profile="
IFACE_PREFIX = "vc-"

# Lines that run commands or load code as root when the tunnel comes up.
SCRIPT_DIRECTIVES = frozenset({
    "up", "down", "route-up", "route-pre-down", "ipchange", "tls-verify",
    "auth-user-pass-verify", "client-connect", "client-disconnect", "learn-address", "plugin",
})
# Lines that write files, daemonize or open a control port. Removed from the installed copy.
STRIP_DIRECTIVES = frozenset({
    "log", "log-append", "writepid", "status", "status-version", "daemon", "syslog", "inetd",
    "chroot", "cd", "tmp-dir", "ifconfig-pool-persist", "setcon", "dev-node",
    "management", "management-client", "management-query-passwords", "management-hold",
    "management-signal", "management-forget-disconnect", "management-log-cache",
    "management-up-down", "management-client-auth", "management-client-pf",
    "management-client-user", "management-client-group", "management-external-key",
    "management-external-cert",
})
# Options that name a file on this server. The tunnel service cannot read /root or /home.
FILE_DIRECTIVES = frozenset({
    "ca", "cert", "key", "dh", "extra-certs", "pkcs12", "tls-auth", "tls-crypt", "tls-crypt-v2",
    "secret", "crl-verify", "askpass", "config", "http-proxy-user-pass",
})

_TAG = re.compile(r"^<(/?)([A-Za-z0-9_-]+)>$")
_INSTANCE_BAD = re.compile(r"[^A-Za-z0-9_.-]+")
_PROTECTED = (ipaddress.ip_network("100.64.0.0/10"),)  # Tailscale: policy-routed, not in the main table


# ---------------------------------------------------------------- names

def instance_name(profile_name: str) -> str:
    """systemd instance for a profile: its name, reduced to characters safe in a unit name."""
    cleaned = _INSTANCE_BAD.sub("-", profile_name).strip("-.")[:40]
    return cleaned or "profile"


def unit_name(instance: str) -> str:
    return f"openvpn-client@{instance}.service"


def iface_name(profile_id: str) -> str:
    """A name of our own (never tunN), so a console tunnel cannot clash with a tunnel
    started by hand. Linux limits interface names to 15 characters."""
    return IFACE_PREFIX + re.sub(r"[^A-Za-z0-9_-]", "", profile_id)[:12]


def marker_line(profile_id: str) -> str:
    return f"{MARKER}{profile_id}"


def owner_of(conf_text: str) -> str | None:
    """Profile id in the first line of an installed copy; None if it is not ours."""
    first = conf_text.split("\n", 1)[0].strip()
    return first[len(MARKER):].strip() if first.startswith(MARKER) else None


# ---------------------------------------------------------------- reading a profile

@dataclass(frozen=True)
class Finding:
    line_no: int
    text: str
    directive: str
    kind: str   # "refuse" | "script" | "strip" | "default_route"
    why: str


@dataclass
class Analysis:
    findings: list[Finding] = field(default_factory=list)
    inline_blocks: set[str] = field(default_factory=set)
    dev: str = "tun"

    def of(self, kind: str) -> list[Finding]:
        return [f for f in self.findings if f.kind == kind]

    @property
    def refused(self) -> list[Finding]:
        return self.of("refuse")

    @property
    def scripts(self) -> list[Finding]:
        return self.of("script")

    @property
    def stripped(self) -> list[Finding]:
        return self.of("strip")

    @property
    def default_route_lines(self) -> list[Finding]:
        return self.of("default_route")


def split_lines(text: str) -> list[str]:
    """Split the way OpenVPN does (on newlines only), so line numbers agree everywhere."""
    return text.replace("\r\n", "\n").split("\n")


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line, comments=True, posix=True)
    except ValueError:
        return line.split()


def analyze(text: str) -> Analysis:
    out = Analysis()
    block: str | None = None
    for no, raw in enumerate(split_lines(text), 1):
        stripped = raw.strip()
        tag = _TAG.match(stripped)
        if tag:
            closing, name = tag.group(1) == "/", tag.group(2)
            if name == "connection":  # holds ordinary directives, so it is not skipped
                continue
            if closing:
                block = None
            else:
                block = name
                out.inline_blocks.add(name)
            continue
        if block or not stripped or stripped[0] in "#;":
            continue
        tokens = _tokens(stripped)
        if not tokens:
            continue
        d = tokens[0][2:] if tokens[0].startswith("--") else tokens[0]
        args = tokens[1:]

        def add(kind: str, why: str) -> None:
            out.findings.append(Finding(no, stripped, d, kind, why))

        if d == "dev" and args:
            out.dev = args[0]
        elif d == "dev-type" and args:
            out.dev = args[0]
        if d == "script-security":
            if args and args[0].isdigit() and int(args[0]) >= 2:
                add("script", "allows scripts to run")
        elif d in SCRIPT_DIRECTIVES:
            add("script", "runs a command or plugin as root")
        elif d in STRIP_DIRECTIVES:
            add("strip", "writes a file or opens a control port")
        elif d == "auth-user-pass":
            if "auth-user-pass" not in out.inline_blocks:
                add("refuse", "needs a username and password, and a tunnel started at boot has nobody to type them")
        elif d in FILE_DIRECTIVES:
            inline_ref = bool(args) and args[0] == "[inline]"
            if args and not inline_ref and not (d == "dh" and args[0] == "none"):
                add("refuse", "points at a file on the server, which the tunnel service cannot read")
        elif d == "redirect-gateway":
            add("default_route", "would replace the server's default route")
        elif d == "route" and args and args[0] in ("0.0.0.0", "128.0.0.0"):
            add("default_route", "would replace the server's default route")
        elif d == "route-ipv6" and args and args[0] in ("::/0", "::/1", "8000::/1"):
            add("default_route", "would replace the server's default route")
    return out


# ---------------------------------------------------------------- the installed copy

def render(text: str, profile_id: str, analysis: Analysis | None = None) -> tuple[str, list[str]]:
    """The tunnel-only copy written to the server, plus the notices to show about it."""
    analysis = analysis or analyze(text)
    iface = iface_name(profile_id)
    removed = {f.line_no: f for f in analysis.stripped + analysis.default_route_lines}
    out = [marker_line(profile_id),
           "# Rewritten whenever the profile is enabled or edited in vpn-console. Do not edit here."]
    for no, line in enumerate(split_lines(text), 1):
        if no in removed:
            out.append(f"# [vpn-console] removed ({removed[no].kind}): {line.strip()}")
        else:
            out.append(line)
    while out and out[-1] == "":
        out.pop()
    dev_type = "tap" if analysis.dev.startswith("tap") else "tun"
    out += [
        "# --- vpn-console tunnel-only settings ---",
        f"dev {iface}",
        f"dev-type {dev_type}",
        'pull-filter ignore "redirect-gateway"',
        'pull-filter ignore "route 0.0.0.0"',
        'pull-filter ignore "route 128.0.0.0"',
        'pull-filter ignore "route-ipv6 ::/0"',
        'pull-filter ignore "route-ipv6 8000::/1"',
        'pull-filter ignore "dhcp-option"',
    ]
    if not analysis.scripts:
        out.append("script-security 1")  # belt and braces: no user script can run
    notices = ["Tunnel-only: a pushed default route or DNS setting is ignored, so SSH, nginx and Tailscale keep working."]
    if analysis.default_route_lines:
        notices.append("Default-route lines were commented out of the installed copy: "
                       + "; ".join(f.text for f in analysis.default_route_lines[:3]) + ".")
    if analysis.stripped:
        notices.append("Removed from the installed copy (your stored profile is unchanged): "
                       + "; ".join(f.text for f in analysis.stripped[:4]) + ".")
    return "\n".join(out) + "\n", notices


# ---------------------------------------------------------------- routes (safety check)

@dataclass(frozen=True)
class Route:
    dest: ipaddress.IPv4Network | ipaddress.IPv6Network
    iface: str
    gateway: str = ""

    def as_dict(self) -> dict[str, str]:
        return {"dest": str(self.dest), "iface": self.iface, "gateway": self.gateway}


def routes_from_dicts(items: list[dict[str, str]]) -> list[Route]:
    out = []
    for item in items:
        try:
            out.append(Route(ipaddress.ip_network(item["dest"], strict=False), item["iface"], item.get("gateway", "")))
        except (KeyError, ValueError):
            continue
    return out


def parse_proc_net_route(text: str) -> list[Route]:
    """IPv4 main table from /proc/net/route (hex, little-endian)."""
    out = []
    for line in text.splitlines()[1:]:
        f = line.split()
        if len(f) < 8:
            continue
        try:
            if not int(f[3], 16) & 1:  # RTF_UP
                continue
            dest = socket.inet_ntoa(struct.pack("<L", int(f[1], 16)))
            mask = socket.inet_ntoa(struct.pack("<L", int(f[7], 16)))
            gw = socket.inet_ntoa(struct.pack("<L", int(f[2], 16)))
            net = ipaddress.ip_network(f"{dest}/{mask}", strict=False)
        except ValueError:
            continue
        out.append(Route(net, f[0], "" if gw == "0.0.0.0" else gw))
    return out


def parse_proc_net_ipv6_route(text: str) -> list[Route]:
    """IPv6 main table from /proc/net/ipv6_route."""
    out = []
    for line in text.splitlines():
        f = line.split()
        if len(f) < 10 or f[9] == "lo":
            continue
        try:
            net = ipaddress.ip_network((ipaddress.IPv6Address(bytes.fromhex(f[0])), int(f[1], 16)), strict=False)
        except ValueError:
            continue
        out.append(Route(net, f[9]))
    return out


def route_violations(routes: list[Route], iface: str) -> list[str]:
    """Reasons a tunnel's routes are unsafe: it replaces the default route, or overlaps a
    route that already goes somewhere else (this server's network, Docker, Tailscale, another
    tunnel). Empty list = safe."""
    def skip(net: Any) -> bool:
        return net.is_link_local or net.is_multicast or net.is_loopback

    mine = [r for r in routes if r.iface == iface and not skip(r.dest)]
    others = [r for r in routes if r.iface != iface and r.dest.prefixlen > 1 and not skip(r.dest)]
    out: list[str] = []
    for r in mine:
        if r.dest.prefixlen <= 1:
            out.append(f"it replaces the server's default route ({r.dest})")
            continue
        clash = next((o for o in others if o.dest.version == r.dest.version and r.dest.overlaps(o.dest)), None)
        if clash:
            out.append(f"{r.dest} overlaps {clash.dest}, which goes through {clash.iface}")
            continue
        guard = next((p for p in _PROTECTED if r.dest.version == p.version and r.dest.overlaps(p)), None)
        if guard:
            out.append(f"{r.dest} overlaps {guard}, which Tailscale uses")
    return out


# ---------------------------------------------------------------- state

def tunnel_summary(unit: dict[str, Any] | None, conf_installed: bool, unit_id: str,
                   iface: str, ip: str = "") -> dict[str, Any]:
    """One profile's tunnel state from systemd's view of its unit."""
    active = (unit or {}).get("state", "")
    if active in ("active", "running"):
        # OpenVPN tells systemd it is ready before it has connected ("Pre-connection
        # initialization successful"), so an active unit is connected only once its
        # interface has an address.
        state = "connected" if ip else "connecting"
    elif active == "activating":
        state = "connecting"
    elif active == "failed":
        state = "failed"
    elif active == "deactivating":
        state = "stopping"
    else:
        state = "stopped" if conf_installed else "none"
    return {
        "state": state,
        "unit": unit_id,
        "iface": iface,
        "ip": ip if state == "connected" else "",
        "since": (unit or {}).get("since", "") if state != "none" else "",
        "boot": bool((unit or {}).get("enabled_on_boot")),
    }
