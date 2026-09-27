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
    """
    lines = _staged_added_lines(root)
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
        # 3. Home paths / machine-identity shapes.
        for f in ppp.scan_text(text):
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
        return 0
    print("BLOCKED: privacy leak in the staged diff (values are MASKED):")
    for h in hits:
        print(f"  {h.path}:{h.line}  [{h.rule}]  {h.masked}")
    print(
        "Redact before committing: replace personal values with the github "
        "username or 'User' — @users.noreply.github.com addresses are exempt. "
        "A value the file already holds at HEAD is not re-flagged."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
