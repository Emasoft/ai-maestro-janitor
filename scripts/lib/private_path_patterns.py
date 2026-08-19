"""Local / machine-private path + identity patterns (the PROJECT-scope leak lib).

The memory system has THREE scopes (TRDD-c77dae09 — USER / PROJECT / LOCAL).
The PROJECT scope (`<git-root>/memory/`) is git-tracked and PUSHED, so it must
NEVER carry machine- or user-private material: an absolute home path with a
username, a Windows user path, an ssh `user@host`, a machine hostname
(`box.local` / `box.lan`), or a `$HOME`-expanded string that leaked a username.
Such material belongs in the LOCAL scope (per-machine, never pushed). This
module is the detector vocabulary for that leak class.

It is the missing companion to `privacy_patterns.py` (PII: email/phone/SSN/…)
and the credential libs (`cloud_credential_patterns`, `cicd_secret_leak_patterns`,
…): those cover *secrets* and *PII*; this covers *local paths + machine
identity*. The `memory-scope-leak` detector runs all of them over a
would-be-pushed PROJECT `memory/` page and proposes "demote to LOCAL scope".

Public surface (mirrors `privacy_patterns.py` so a uniform scanner consumes
both):

  * Finding(rule_id, line, column, matched_text, severity, description, kind)
                                  — single match record (NamedTuple).
  * Rule(id, name, severity, description, pattern, kind)
                                  — rule definition; patterns PRE-COMPILED.
  * RULES                         — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
                                  — run every rule, return findings sorted by
                                    (line, column). Allowlist-aware: generic /
                                    shared paths and documentation hostnames are
                                    suppressed at the match level.

Severity strings: "CRITICAL", "HIGH", "MAJOR", "MEDIUM", "LOW" — the janitor
convention. `kind` is a short class label (`local-path`, `machine-host`) so a
finding can be rendered/grouped without re-deriving it from the rule id.

Design constraints (same as the sibling pattern libs): deterministic regex only
— no LLM, no non-Anthropic helper; every quantifier bounded; no unanchored
`.*`. Each rule carries a per-match `_ALLOW` predicate so the well-known
generic/shared/documentation forms (`/Users/Shared/`, `/home/runner/`,
`C:\\Users\\Public\\`, bare `~/`, symbolic `$HOME`, `localhost`, `example.com`,
`*.test`) never fire — those carry no identity and are portable.
"""

from __future__ import annotations

import re
from typing import Callable, NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same field order as privacy_patterns.Finding,
    with `kind` replacing `owasp_asi` (this is not an OWASP axis; it is a
    local-path / machine-identity class label)."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    kind: str


class Rule(NamedTuple):
    """A rule definition. `pattern` is PRE-COMPILED at module load; `allow` is
    an optional per-match predicate (given the full matched substring) that, when
    it returns True, SUPPRESSES the match — this is how the generic/shared forms
    (`/Users/Shared/`, `localhost`, …) are excluded without a second regex."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern  # noqa: UP006 - keep stdlib name
    kind: str
    allow: Callable[[str], bool] | None


# ---- Allowlists ---------------------------------------------------------
#
# Username components that name a SHARED / SYSTEM / CI account, not a person.
# A home path whose user segment is one of these carries no personal identity
# and is portable across machines (every GitHub Actions runner is
# `/home/runner/...`; `/Users/Shared/` is the macOS multi-user location).
_GENERIC_USER_SEGMENTS = frozenset({
    # macOS shared / system
    "shared", "public", "guest",
    # Linux CI / cloud / system service accounts
    "runner", "ubuntu", "ec2-user", "root", "admin", "user", "www-data",
    "nobody", "daemon", "build", "ci", "vagrant", "docker", "node", "app",
    "appuser", "jenkins", "actions", "azureuser", "circleci", "travis",
    # Windows shared / system
    "default", "all users", "defaultaccount",
})

# Hostname labels / suffixes that are documentation, loopback, or reserved —
# NOT a real machine on someone's LAN. RFC 2606 / RFC 6761 reserve
# example.{com,net,org}, .test, .example, .invalid, .localhost; `localhost`
# and `localhost.localdomain` are loopback.
_GENERIC_HOST_TOKENS = frozenset({
    "localhost", "localhost.localdomain",
})
_GENERIC_HOST_SUFFIXES = (
    ".test", ".example", ".invalid", ".localhost",
    ".example.com", ".example.net", ".example.org",
    "example.com", "example.net", "example.org",
)


def _user_segment_is_generic(seg: str) -> bool:
    """True iff a path's user segment names a shared/system/CI account."""
    return seg.strip().lower() in _GENERIC_USER_SEGMENTS


def _hostname_is_generic(host: str) -> bool:
    """True iff a hostname is a documentation/loopback/reserved name (no real
    machine identity). Compared case-insensitively."""
    h = host.strip().lower().rstrip(".")
    if not h:
        return True
    if h in _GENERIC_HOST_TOKENS:
        return True
    return any(h == suf.lstrip(".") or h.endswith(suf) for suf in _GENERIC_HOST_SUFFIXES)


# ---- Per-rule allow predicates -----------------------------------------


def _allow_unix_home(matched: str) -> bool:
    """Suppress a `/Users/<seg>/` or `/home/<seg>/` match whose <seg> is a
    generic/shared/CI account. The matched text is the whole `/root/<seg>` (or
    with a trailing `/`); the user segment is the third path component."""
    parts = [p for p in matched.split("/") if p != ""]
    # parts == ["Users", "<seg>", ...] or ["home", "<seg>", ...]
    if len(parts) < 2:
        return False
    return _user_segment_is_generic(parts[1])


def _allow_windows_home(matched: str) -> bool:
    r"""Suppress a `C:\Users\<seg>\` match whose <seg> is a shared/system
    account (`Public`, `Default`, `All Users`, `Administrator`-style)."""
    # Normalise separators and split off the user segment after "Users".
    norm = matched.replace("/", "\\")
    segs = [s for s in norm.split("\\") if s != ""]
    # segs == ["C:", "Users", "<seg>", ...]
    if len(segs) < 3:
        return False
    return _user_segment_is_generic(segs[2])


def _allow_ssh_host(matched: str) -> bool:
    """Suppress an `user@host` match whose host is a generic/documentation name
    or whose right side looks like an email domain (a dotted TLD with no LAN
    suffix is handled by privacy_patterns' email rule; we don't double-fire)."""
    at = matched.rfind("@")
    if at < 0:
        return True
    host = matched[at + 1 :]
    # GitHub Action SHA-pin (issue #53): `owner/action@<7-40 hex>` —
    # e.g. `astral-sh/setup-uv@d4b2f3b6…` — superficially matches `user@host`,
    # but the right side is a git commit SHA, not a machine. A pure-hex token of
    # 7-40 chars is a SHA (short..full), never a real ssh target, so documenting
    # a SHA-pin decision in a shareable note must not read as machine-private.
    if 7 <= len(host) <= 40 and all(c in "0123456789abcdefABCDEF" for c in host):
        return True
    if _hostname_is_generic(host):
        return True
    # An email address (user@domain.tld with a public-looking TLD and NO
    # `.local`/`.lan`) is PII, not an ssh target — privacy_patterns owns it.
    # ssh hosts we care about are bare names or `.local`/`.lan` mDNS/LAN names.
    low = host.lower()
    if low.endswith(".local") or low.endswith(".lan"):
        return False
    # A dotted host that is NOT a LAN suffix → treat as an email domain → allow
    # (suppress) so we never misread `someone@example.com` as ssh.
    return "." in host


def _allow_local_hostname(matched: str) -> bool:
    """Suppress a `<host>.local` / `<host>.lan` match that is actually a
    reserved/documentation name (`localhost.localdomain`, `*.example`)."""
    return _hostname_is_generic(matched)


# ---- Compiled patterns --------------------------------------------------
#
# macOS home: `/Users/<user>/...`. The user segment is 1+ chars excluding `/`.
# A trailing `/` is required so `/Users/Shared` (a directory) and a real home
# `/Users/alice/...` both match with the user segment captured; the allow
# predicate drops the shared/system ones.
_MACOS_HOME = re.compile(r"/Users/[^/\s]+/")

# Linux home: `/home/<user>/...`. Same shape; allow predicate drops CI/system.
_LINUX_HOME = re.compile(r"/home/[^/\s]+/")

# Windows home: `C:\Users\<user>\...` (drive letter A-Z, back- or forward
# slashes tolerated). Bounded segments; allow predicate drops Public/Default.
_WINDOWS_HOME = re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s]+[\\/]")

# ~username/ — another user's home by name (NOT bare `~/`, which is portable).
# Require at least one name char after `~` and a following `/`. The negative
# lookahead `(?!/)` after `~` ensures `~/foo` (bare home) is NOT matched.
_TILDE_HOME = re.compile(r"(?<![\w/])~(?!/)[A-Za-z_][A-Za-z0-9_\-]*/")

# ssh user@host — `<user>@<host>` where host is a bare name or dotted name.
# The user is 1+ word chars; host is letters/digits/dots/hyphens. The allow
# predicate distinguishes a real ssh target from an email address.
_SSH_USER_HOST = re.compile(r"(?<![\w.])[A-Za-z0-9_][A-Za-z0-9_.\-]*@[A-Za-z0-9][A-Za-z0-9.\-]+")

# Machine hostname — `<label>` suffixed by a conventional internal/LAN TLD
# (mDNS `.local`/`.lan`, or the internal-network conventions `.internal`,
# `.intranet`, `.corp`, `.home`). The label is a DNS label (letters/digits/
# hyphens). The allow predicate drops reserved names. A leading boundary
# keeps it out of the middle of a longer token.
#
# IN scope (TRDD-UWBXNJ76 gap 1): suffix-anchored hostname —
#   `.local .lan .internal .intranet .corp .home` — plus the `user@host`
#   ssh position, already covered separately by `_SSH_USER_HOST`.
# OUT of scope: a bare SUFFIXLESS hostname token (e.g. `emasofts-mac-mini`)
#   — matching any hyphenated word is the FP minefield this rule exists to
#   avoid; the only corroborating position that matters (`user@host`) is
#   already convicted by `_SSH_USER_HOST`.
# Sibling gap (short high-entropy ids, `_ENTROPY_MIN_LEN` in
# `memory-scope-leak.py`) is a MEASURED REFUSAL — see TRDD-UWBXNJ76.
#
# The trailing `(?!\()` excludes API method-call syntax (`Path.home()`,
# `Locale.local()`) — `home`/`local`/`corp` are common Python/JS method names,
# and a call site is never a hostname (measured FP on this repo's own memory
# corpus, TRDD-UWBXNJ76: `Path.home()` in prose matched before this guard).
_LOCAL_HOSTNAME = re.compile(
    r"(?<![\w.@])[A-Za-z0-9][A-Za-z0-9\-]*\.(?:local|lan|internal|intranet|corp|home)\b(?!\()"
)


# ---- The rule catalogue -------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="private-path.macos-user-home",
        name="macOS user home path",
        severity="HIGH",
        description="absolute macOS home path with a username (/Users/<name>/) — machine-local, do not push",
        pattern=_MACOS_HOME,
        kind="local-path",
        allow=_allow_unix_home,
    ),
    Rule(
        id="private-path.linux-user-home",
        name="Linux user home path",
        severity="HIGH",
        description="absolute Linux home path with a username (/home/<name>/) — machine-local, do not push",
        pattern=_LINUX_HOME,
        kind="local-path",
        allow=_allow_unix_home,
    ),
    Rule(
        id="private-path.windows-user-home",
        name="Windows user home path",
        severity="HIGH",
        description=r"absolute Windows home path with a username (C:\Users\<name>\) — machine-local, do not push",
        pattern=_WINDOWS_HOME,
        kind="local-path",
        allow=_allow_windows_home,
    ),
    Rule(
        id="private-path.tilde-user-home",
        name="tilde-expanded named home",
        severity="MEDIUM",
        description="another user's home by name (~<name>/) — carries a username; bare ~/ is fine",
        pattern=_TILDE_HOME,
        kind="local-path",
        allow=None,
    ),
    Rule(
        id="private-path.ssh-user-host",
        name="ssh user@host",
        severity="MEDIUM",
        description="ssh user@host target — names a real account+machine; an email is NOT this (it is PII)",
        pattern=_SSH_USER_HOST,
        kind="machine-host",
        allow=_allow_ssh_host,
    ),
    Rule(
        id="private-path.local-hostname",
        name="LAN/mDNS hostname",
        severity="MEDIUM",
        description="a <host>.local / <host>.lan machine name — a real LAN device, not a documentation host",
        pattern=_LOCAL_HOSTNAME,
        kind="machine-host",
        allow=_allow_local_hostname,
    ),
)


# ---- The composed scanner ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column).

    Identical to privacy_patterns._line_col so findings from both libs share
    coordinate semantics when a detector merges them.
    """
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def scan_text(text: str) -> list[Finding]:
    """Run every private-path / machine-identity rule against `text`.

    Returns findings sorted by (line, column) for stable rendering. Each match
    is filtered through its rule's `allow` predicate so the well-known generic /
    shared / documentation forms never fire. Deduped by (rule_id, line, column).
    A match longer than 200 chars is truncated in the report (the pattern is
    bounded, but a pathological hostname run is still capped defensively).
    """
    if not text:
        return []
    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()
    for rule in RULES:
        for m in rule.pattern.finditer(text):
            matched = m.group(0)
            if rule.allow is not None and rule.allow(matched):
                continue
            line, col = _line_col(text, m.start())
            key = (rule.id, line, col)
            if key in seen:
                continue
            seen.add(key)
            if len(matched) > 200:
                matched = matched[:200] + "…"
            findings.append(Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=matched,
                severity=rule.severity,
                description=rule.description,
                kind=rule.kind,
            ))
    findings.sort(key=lambda f: (f.line, f.column))
    return findings
