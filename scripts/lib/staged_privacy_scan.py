"""Staged-diff privacy-leak scanner (TRDD-FWDZDB7W, step 1).

Scans ONLY the ADDED lines of the staged diff (`git diff --cached -U0`) so a
commit-time run stays well under a second, and reuses the existing pattern
modules instead of owning new regexes:

  * personal e-mails + allow-list  -> publish.py's G1b lint (TRDD-QW7K3M2V),
    re-pointed at HEAD: an address the file already holds at HEAD is not a NEW
    disclosure (per-file semantics, same owner ruling as the push gate).
  * home paths / machine identity  -> scripts/lib/private_path_patterns.py.
  * PII shapes (SSN / card / IBAN / passport / phone) -> scripts/lib/
    privacy_patterns.PII_SHAPES (email deliberately excluded — G1b owns it).
  * this host's username and hostname -> literal tokens (the 2026-09-24
    incidents: trddgrep stamped $USER into card frontmatter and approval
    logs). Skipped when the token already exists in the file at HEAD, so
    editing a card the owner already accepted (K0PMVRN6) is not re-blocked.

Every reported value is MASKED — the block output must never echo the full
PII (it can land in a log), same rule as G1b's own output.

Exit codes: 0 clean, 1 findings (block), 2 scanner error (also blocks —
no silent bypass: if git itself fails we refuse the commit rather than
wave it through).

CLI: `uv run python scripts/lib/staged_privacy_scan.py` from anywhere inside
the repo; resolves the toplevel itself. Wired into git-hooks/pre-commit.
"""

from __future__ import annotations

import getpass
import re
import socket
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

# The pattern libraries live beside this file (scripts/lib/) and publish.py in
# scripts/. Insert both so the imports resolve whether we are imported as a
# module or run via the CLI — idempotent (sys.path dedupes by membership).
# Same idiom as scripts/lib/memory_migrate.py.
_LIB_DIR = str(Path(__file__).resolve().parent)
_SCRIPTS_DIR = str(Path(__file__).resolve().parents[1])
for _p in (_LIB_DIR, _SCRIPTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import privacy_patterns as privacy  # noqa: E402
import private_path_patterns as ppp  # noqa: E402
import publish  # noqa: E402


class ScannerError(RuntimeError):
    """git itself failed — the caller must block, never pass silently."""


# Machine-generated lines whose PII/path shapes were suppressed by the last
# scan_staged() run — disclosed in main()'s summary so the bypass is never
# silent (single-threaded CLI, one writer per run).
_LAST_SUPPRESSED = 0


class StagedHit(NamedTuple):
    """One privacy finding on a staged added line."""

    path: str
    line: int
    rule: str
    masked: str


# Word-boundary guard for host-identity tokens: a username inside a longer
# identifier (an e-mail local part, a path segment) is the EMAIL/path rule's
# business, not a bare host-identity leak.
def _token_regex(token: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9_])" + re.escape(token) + r"(?![A-Za-z0-9_])", re.IGNORECASE)


def _mask(s: str) -> str:
    """MASKED echo of a non-email match — never the full value."""
    return (s[:2] if len(s) > 2 else s[:1]) + "***"


# ---- Machine-generated-line suppression (issues #316/#314) ----------------
#
# Dependency bumps make the gate unusable: `pii-us_ssn` matches 9-digit runs
# inside Cargo.lock `checksum = "…"` hex (the SSN regex's separators are
# optional, so a hex digest reads as an SSN — issue #316 main body), and any
# `integrity = "sha512-…"`/`resolved = "…#…"` line trips the shape rules the
# same way. These files are MACHINE-GENERATED: the shapes are meaningless
# there. The shape rules (PII + home/path) are skipped for such lines — but
# the host-identity token check (block 4) STAYS ON for every line: a
# machine-generated file is not human-written, but a human COULD have pasted
# a secret/username into one, and the token check is a real-token match, not
# a shape guess, so suppressing it would be a silent bypass.
#
# Two detection halves, BOTH conservative (fail toward BLOCKING when unsure):
#   1. File-name fast path — named lockfiles/manifests. The bare
#      long-hex-run shape is allowed ONLY here: a hand-pasted hex secret in
#      an ordinary file must still flag.
#   2. Line-shape fallback for OTHER files — suppressed only on exact
#      generated-manifest assignment keys (`checksum = "…"`,
#      `integrity = "sha512-…"`, `resolved = "https://…#/…"`). Key-name-gated,
#      never "any line with a long hex run" — that variant would suppress a
#      hand-pasted real secret that happens to look hex.
#
# The count of suppressed lines is returned/disclosed in the summary output —
# a bypass that cannot be seen is a bypass (no silent suppression).

_GENERATED_FILE_NAMES = frozenset({
    "cargo.lock", "package-lock.json", "pnpm-lock.yaml", "poetry.lock",
    "uv.lock", "yarn.lock", "composer.lock", "gemfile.lock", "go.sum",
    "pipfile.lock", "bun.lockb", "bun.lock",
})

# The scanner's own test suite: its fixtures deliberately carry the exact
# shapes the negative controls exist to catch (a real SSN line, real ssh
# targets, real tilde homes). Flagging the TEST that proves the rule fires
# would make the rule uncommittable — the self-scan false-positives on its
# own documentation is the known detector-validity trap. These rule-suite
# test files are exempt (the local-hostname and privacy-pattern suites joined
# 2026-09-29); a fixture directory is not, so fixtures stay gated.
_SELF_TEST_FILES = frozenset({
    "test_staged_privacy_scan.py",
    "test_private_path_patterns.py",
    "test_privacy_patterns.py",
})


def _is_generated_file(path: str) -> bool:
    name = Path(path).name.lower()
    if name in _GENERATED_FILE_NAMES:
        return True
    return name.endswith(".lock") or name.endswith(".sum")


# Generated-manifest assignment keys whose values are dependency hashes/URLs.
_GENSUM_KEY = re.compile(
    r'^\s*(?:checksum|integrity|resolved)\s*=\s*"[^"]*"\s*,?\s*$'
)


def _is_machine_generated_line(text: str, generated_file: bool) -> bool:
    """True iff this line is machine-generated dependency metadata where the
    PII/path shapes are meaningless. In a named lockfile every line
    qualifies; elsewhere only exact generated-manifest key assignments do."""
    if generated_file:
        return True
    return _GENSUM_KEY.match(text) is not None


# trddgrep's governance author token (issue #314): `main-agent@<project-id>`
# in TRDD frontmatter matches the `user-at-host` ssh shape, but the user segment
# is a ROLE NAME from the harness vocabulary, and the host is a dotless
# hyphenated project id — not a machine. CLOSED SET of roles plus the
# `*-agent` suffix convention; a lowercase-hyphenated personal username
# (`dev-alice`) is NOT in the set, so a real ssh-shaped target
# (`deploy-at-web-1`, dotless) still fires. Host must contain no dot (a real
# ssh host is a domain or dotted name; project ids are hyphenated words).
_ROLE_TOKENS = frozenset({
    "main-agent", "chief-of-staff", "manager", "orchestrator",
    "maintainer", "integrator", "architect",
})


def _is_governance_author_token(matched: str) -> bool:
    """Suppress `user-at-host` ssh-shape matches that are trddgrep governance
    author tokens `<role> at <project-id>`. Conservative: suppress ONLY the
    closed role set (plus `*-agent` suffix tokens whose HOST is digit-free —
    a service-account convention like deploy-agent at web-1 is a REAL ssh
    target, and web-1/runner-1 style hostnames carry digits; project-ids
    like ai-maestro-janitor do not), with a dotless host — anything
    ambiguous blocks."""
    if matched.count("@") != 1:
        return False
    user, host = matched.split("@", 1)
    if user in _ROLE_TOKENS:
        return "." not in host and host != ""
    is_agent_token = (
        user.endswith("-agent") and user[:-len("-agent")].isalnum()
        and "_" not in user and user != "-agent"
    )
    if not is_agent_token:
        return False
    host_has_digit = any(c.isdigit() for c in host)
    return "." not in host and host != "" and not host_has_digit


def _staged_added_lines(root: Path) -> list[tuple[str, int, str]]:
    """The staged (index vs HEAD) added lines as (path, new_line_no, text).

    Hand-parses `git diff --cached -U0` — the same stable hunk-header format
    publish._added_lines_since parses for the push gate. New files, binary
    skips and line numbers behave identically. Raises ScannerError on a git
    failure: an unscannable diff must block, not pass.
    """
    try:
        r = subprocess.run(
            ["git", "diff", "--cached", "--unified=0", "--no-color"],
            capture_output=True, text=True, cwd=str(root), timeout=30,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScannerError(f"git diff --cached failed: {exc}") from exc
    if r.returncode != 0:
        raise ScannerError(f"git diff --cached failed: {r.stderr.strip()}")
    out: list[tuple[str, int, str]] = []
    current_path: str | None = None
    next_line_no = 0
    for line in r.stdout.splitlines():
        if line.startswith("+++ "):
            fpath = line[len("+++ "):]
            current_path = None if fpath == "/dev/null" else fpath.removeprefix("b/")
            continue
        if line.startswith("Binary files"):
            current_path = None
            continue
        if line.startswith("@@"):
            m = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
            if m:
                next_line_no = int(m.group(1))
            continue
        if current_path is None or line.startswith("---"):
            continue
        if line.startswith("+"):
            out.append((current_path, next_line_no, line[1:]))
            next_line_no += 1
    return out


def _host_identity_tokens() -> list[str]:
    """This host's username and hostname label, when they carry identity.

    A shared/system/CI username (`runner`, `root`, …) or a documentation
    hostname names nobody — reuse private_path_patterns' generic filters so
    the commit gate never flags the word `user` on a CI machine.
    """
    tokens: list[str] = []
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001 - getuser raises KeyError on odd uids
        user = ""
    if user and not ppp._user_segment_is_generic(user):
        tokens.append(user)
    host = socket.gethostname().strip().split(".")[0].lower()
    if host and not ppp._hostname_is_generic(host):
        tokens.append(host)
    return tokens


def _head_blob(root: Path, cache: dict[str, str], path: str) -> str:
    """The file's content as of HEAD ('' for a new file). Cached per path.

    A git hiccup degrades to '' — the token then looks NOT grandfathered, so
    the scan errs toward FLAGGING, never toward waving a leak through.
    """
    if path not in cache:
        try:
            r = subprocess.run(
                ["git", "show", f"HEAD:{path}"],
                capture_output=True, text=True, cwd=str(root), timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            r = None
        cache[path] = r.stdout if r is not None and r.returncode == 0 else ""
    return cache[path]


def scan_staged(root: Path) -> list[StagedHit]:
    """Scan the staged diff of the repo at `root`; return MASKED findings.

    Empty list = clean. Raises ScannerError when git fails (caller blocks).
    The number of machine-generated lines whose PII/path shapes were
    suppressed is left in `_LAST_SUPPRESSED` (module-level; single-threaded
    CLI, one writer) so main()'s summary can disclose it — a suppression
    bypass is never silent.
    """
    lines = _staged_added_lines(root)
    global _LAST_SUPPRESSED
    _LAST_SUPPRESSED = 0
    if not lines:
        return []

    # Grandfathering data, per file, read from HEAD once: addresses the file
    # already held (G1b per-file semantics) and host-identity tokens already
    # present (an owner-accepted card is edited, not re-disclosed).
    blob_cache: dict[str, str] = {}

    def known_emails(path: str) -> frozenset[str]:
        return frozenset(publish._base_ref_email_addresses(root, "HEAD", path))

    paths = sorted({p for p, _, _ in lines})
    known_map = {p: known_emails(p) for p in paths}
    head_blobs = {p: _head_blob(root, blob_cache, p) for p in paths}

    hits: list[StagedHit] = []
    seen: set[tuple[str, int, str, str]] = set()

    def add(path: str, lineno: int, rule: str, masked: str) -> None:
        key = (path, lineno, rule, masked)
        if key not in seen:
            seen.add(key)
            hits.append(StagedHit(path, lineno, rule, masked))

    # 1. Personal e-mails — publish's G1b hit logic verbatim (mask included).
    for path, lineno, masked in publish._personal_email_hits(lines, lambda p: known_map[p]):
        add(path, lineno, "personal-email", masked)

    host_tokens = _host_identity_tokens()
    token_res = [(t, _token_regex(t)) for t in host_tokens]

    for path, lineno, text in lines:
        blob_l = head_blobs[path].lower()
        if Path(path).name.lower() in _SELF_TEST_FILES:
            # The scanner's own negative-control tests (see _SELF_TEST_FILES).
            continue
        generated = _is_generated_file(path)
        if _is_machine_generated_line(text, generated):
            # Machine-generated dependency metadata (issue #316): the PII
            # and home/path shapes are meaningless here — skip the SHAPE
            # rules. The host-identity token check (below) still runs: not
            # human-written, but a human could have pasted a secret into a
            # generated file, and it is a real-token check, not a shape.
            _LAST_SUPPRESSED += 1
            for token, treg in token_res:
                if treg.search(text) and token.lower() not in blob_l:
                    add(path, lineno, "host-identity", _mask(token))
            continue
        # 2. PII shapes minus email (G1b owns email): one hit per shape/line.
        for name, pat in privacy.PII_SHAPES.items():
            if name == "email":
                continue
            m = pat.search(text)
            if m is None:
                continue
            if name == "credit_card" and not privacy.luhn_valid(m.group(0)):
                continue
            add(path, lineno, f"pii-{name}", _mask(m.group(0)))
        # 3. Home paths / machine-identity shapes — governance author tokens
        # (<role>@<project-id>, issue #314) suppressed per-match.
        for f in ppp.scan_text(text):
            if f.rule_id == "private-path.ssh-user-host" and _is_governance_author_token(f.matched_text):
                continue
            add(path, lineno, f.rule_id, _mask(f.matched_text))
        # 4. This host's username / hostname — unless already in the file at HEAD.
        for token, treg in token_res:
            if treg.search(text) and token.lower() not in blob_l:
                add(path, lineno, "host-identity", _mask(token))

    hits.sort(key=lambda h: (h.path, h.line, h.rule))
    return hits


def _repo_root() -> Path:
    """The enclosing git toplevel, or a ScannerError naming the failure."""
    try:
        r = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise ScannerError(f"not inside a git repository: {exc}") from exc
    if r.returncode != 0:
        raise ScannerError(f"not inside a git repository: {r.stderr.strip()}")
    return Path(r.stdout.strip())


def main(argv: list[str] | None = None) -> int:
    try:
        root = _repo_root()
        hits = scan_staged(root)
    except ScannerError as exc:
        # Fail closed: an unscannable state blocks the commit with the reason.
        print(f"BLOCKED: staged privacy scan could not run — {exc}")
        return 2
    if not hits:
        if _LAST_SUPPRESSED:
            print(
                f"clean · {_LAST_SUPPRESSED} machine-generated lines "
                "suppressed (lockfile/manifest shapes — issue #316/#314)"
            )
        return 0
    print("BLOCKED: privacy leak in the staged diff (values are MASKED):")
    for h in hits:
        print(f"  {h.path}:{h.line}  [{h.rule}]  {h.masked}")
    if _LAST_SUPPRESSED:
        print(f"  · {_LAST_SUPPRESSED} machine-generated lines suppressed")
    print(
        "Redact before committing: replace personal values with the github "
        "username or 'User' — @users.noreply.github.com addresses are exempt. "
        "A value the file already holds at HEAD is not re-flagged."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
