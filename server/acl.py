"""Tailnet policy (HuJSON) handling (US7, research D14: text is canonical).

The applied file moves as bytes and is never re-serialized. This module only
*reads* it: a same-length blanking pass strips comments and trailing commas
(offsets — therefore line numbers — survive), json.loads parses the result,
and semantic checks reference the original text for line numbers.
"""
from __future__ import annotations

import json
import re

# Top-level keys of the current Tailscale policy file (grants + ipsets are
# what the default policy now ships with; acls is the legacy syntax).
_KNOWN_SECTIONS = {
    "acls", "grants", "groups", "tagOwners", "hosts", "ipsets", "nodeAttrs",
    "tests", "sshTests", "ssh", "autoApprovers", "postures", "defaultSrcPosture",
    "derpMap", "disableIPv4", "OneCGNATRoute", "randomizeClientPort",
    "attrConfig", "dnsConfig", "ipPrefixRules",
}

_COMMENT_RE = re.compile(r"//[^\n]*|/\*.*?\*/", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


def blank_hujson(text: str) -> str:
    """Same-length text: comments → spaces, trailing commas removed.
    Offsets are preserved so JSON error positions map onto the original."""

    def blank(m: re.Match) -> str:
        return "".join(" " if ch != "\n" else "\n" for ch in m.group(0))

    out = _COMMENT_RE.sub(blank, text)
    # trailing commas: replace the comma with a space (still same length)
    return _TRAILING_COMMA_RE.sub(lambda m: " " + m.group(1), out)


def _line_of(text: str, needle: str) -> int:
    pos = text.find(needle)
    if pos < 0:
        return 1
    return text.count("\n", 0, pos) + 1


def parse(text: str) -> tuple[dict | None, list[dict]]:
    """-> (parsed|None, [{line, message}]). Syntax errors stop here."""
    try:
        return json.loads(blank_hujson(text)), []
    except json.JSONDecodeError as exc:
        return None, [{"line": exc.lineno, "message": f"Syntax error: {exc.msg}"}]


_AUTOGRUP = re.compile(r"^autogroup:[a-z0-9:]+$")
_TAG = re.compile(r"^tag:[\w-]+$")
_GROUP = re.compile(r"^group:[\w-]+$")
_HOSTNAME = re.compile(r"^[\w-]+$")
_IP = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
_CIDR = re.compile(r"^\d{1,3}(\.\d{1,3}){3}/\d{1,2}$")
_IPV6 = re.compile(r"^[0-9a-f:]+$")


def _known_principals(parsed: dict) -> set[str]:
    known = {"*"}
    known.update(parsed.get("groups") or {})
    known.update(parsed.get("tagOwners") or {})
    known.update(parsed.get("hosts") or {})
    for section in ("acls",):
        for rule in parsed.get(section) or []:
            for src in rule.get("src") or []:
                if _IP.match(src) or _CIDR.match(src) or _IPV6.match(src):
                    known.add(src)
                if _AUTOGRUP.match(src):
                    known.add(src)
    known.update({"autogroup:member", "autogroup:admin", "autogroup:tagged"})
    return known


def _check_dst(target: str, hosts: dict) -> str | None:
    """dst entries look like '<host|tag|group|ip>:<ports>'."""
    if ":" not in target:
        return f'dst "{target}" is missing a port part ("host:ports")'
    host, _, ports = target.rpartition(":")
    if not host:
        return f'dst "{target}" has an empty target'
    if not (_TAG.match(host) or _GROUP.match(host) or host in hosts
            or _IP.match(host) or _CIDR.match(host) or _IPV6.match(host)
            or _AUTOGRUP.match(host) or host == "*"):
        return f'dst target "{host}" is not a known host, tag, group or IP'
    for part in ports.split(","):
        if part != "*" and not part.isdigit():
            return f'dst "{target}" has a non-numeric port "{part}"'
    return None


def validate(text: str) -> list[dict]:
    """Full check: syntax + structure + reference resolution (FR-040)."""
    parsed, errors = parse(text)
    if parsed is None:
        return errors
    if not isinstance(parsed, dict):
        return [{"line": 1, "message": "Policy must be a JSON object."}]

    for key in parsed:
        if key not in _KNOWN_SECTIONS:
            errors.append({"line": _line_of(text, f'"{key}"'),
                           "message": f'Unknown section "{key}".'})

    groups = parsed.get("groups") or {}
    if not isinstance(groups, dict):
        errors.append({"line": _line_of(text, '"groups"'),
                       "message": '"groups" must be an object.'})
        groups = {}
    for name, members in groups.items():
        if not _GROUP.match(name):
            errors.append({"line": _line_of(text, f'"{name}"'),
                           "message": f'Group name "{name}" must look like "group:name".'})
        if not isinstance(members, list) or not members:
            errors.append({"line": _line_of(text, f'"{name}"'),
                           "message": f'Group "{name}" needs a non-empty member list.'})

    tags = parsed.get("tagOwners") or {}
    for tag, owners in tags.items():
        if not _TAG.match(tag):
            errors.append({"line": _line_of(text, f'"{tag}"'),
                           "message": f'Tag "{tag}" must look like "tag:name".'})
        if not isinstance(owners, list) or not owners:
            errors.append({"line": _line_of(text, f'"{tag}"'),
                           "message": f'Tag "{tag}" needs at least one owner.'})

    hosts = parsed.get("hosts") or {}
    for name, address in hosts.items():
        if not (_IP.match(str(address)) or _IPV6.match(str(address))):
            errors.append({"line": _line_of(text, f'"{name}"'),
                           "message": f'Host "{name}" must map to an IP address.'})

    known = _known_principals(parsed)
    for i, rule in enumerate(parsed.get("acls") or []):
        if not isinstance(rule, dict):
            errors.append({"line": _line_of(text, '"acls"'),
                           "message": f"ACL rule #{i + 1} is not an object."})
            continue
        for src in rule.get("src") or []:
            if src not in known:
                errors.append({"line": _line_of(text, str(src)),
                               "message": f'src references unknown principal "{src}".'})
        for dst in rule.get("dst") or []:
            problem = _check_dst(str(dst), hosts)
            if problem:
                errors.append({"line": _line_of(text, str(dst)), "message": problem})
        if rule.get("action") not in ("accept", None):
            errors.append({"line": _line_of(text, str(rule.get("action"))),
                           "message": f'Unsupported action "{rule.get("action")}" (only "accept").'})

    return errors


def structured(parsed: dict) -> list[dict]:
    """Read-only structured view (FR-041) — generated, the file stays truth."""
    out: list[dict] = []
    for name, members in (parsed.get("groups") or {}).items():
        out.append({"kind": "groups", "name": name, "items": list(members)})
    for tag, owners in (parsed.get("tagOwners") or {}).items():
        out.append({"kind": "tagOwners", "name": tag, "items": list(owners)})
    for name, address in (parsed.get("hosts") or {}).items():
        out.append({"kind": "hosts", "name": name, "items": [str(address)]})
    for name, members in (parsed.get("ipsets") or {}).items():
        out.append({"kind": "ipsets", "name": name, "items": [str(m) for m in members]})
    for rule in parsed.get("grants") or []:
        reach = [str(x) for x in (rule.get("ip") or [])] + list((rule.get("app") or {}).keys())
        out.append({"kind": "grants", "name": ", ".join(rule.get("src") or []),
                    "items": [f"{d} ({', '.join(reach) or 'any'})" for d in rule.get("dst") or []]})
    for rule in parsed.get("acls") or []:
        out.append({"kind": "acls", "name": ", ".join(rule.get("src") or []),
                    "items": list(rule.get("dst") or [])})
    for attr in parsed.get("nodeAttrs") or []:
        out.append({"kind": "nodeAttrs",
                    "name": ", ".join(attr.get("target") or []),
                    "items": list(attr.get("attr") or [])})
    return out


def normalize_rule(rule: dict) -> str:
    """One readable line per ACL rule — the unit of diffing."""
    src = ", ".join(rule.get("src") or [])
    dst = ", ".join(rule.get("dst") or [])
    return f"{src} → {dst}"


def diff(old_text: str, new_text: str) -> dict:
    """Rule-level set diff of the `acls` section (research D14)."""
    old_parsed, _ = parse(old_text)
    new_parsed, _ = parse(new_text)
    old_rules = {normalize_rule(r) for r in (old_parsed or {}).get("acls") or []}
    new_rules = {normalize_rule(r) for r in (new_parsed or {}).get("acls") or []}
    return {
        "added": sorted(new_rules - old_rules),
        "removed": sorted(old_rules - new_rules),
    }
