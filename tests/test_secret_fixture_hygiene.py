"""Regression guard: no contiguous, real-format credential literal may exist
at rest anywhere in the tracked source.

This repo is a secret scanner; its fixtures are secret-shaped by necessity.
The convention (see tests/README.md) is that every secret-shaped fixture is
assembled at runtime from fragments, so a secret scanner (GitHub
push-protection, gitleaks, GitGuardian) never matches the project's OWN
test corpus. This test enforces that convention forever — the publish
pipeline runs the suite, so a reintroduced literal cannot ship.

If this test fails, fragment the offending literal per tests/README.md
(split the vendor prefix into a `_CONST = "xx" + "yy"` and interpolate it),
or, for a genuinely prefix-less high-entropy blob, annotate the line with
`# gitleaks:allow  pragma: allowlist secret`.
"""

from __future__ import annotations

import base64
import re
import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent

# Files that legitimately contain these patterns as *documentation / regex
# source* rather than as fixtures, and are therefore exempt from the scan.
_EXEMPT_NAMES = {
    "test_secret_fixture_hygiene.py",  # this file (holds the patterns below)
    "README.md",                        # tests/README.md (worked examples)
    "_fake_secrets.py",                 # the generator (f-string DSN templates)
}

# AWS's official docs example key — universally allowlisted, self-documenting.
_AWS_CANONICAL = "AKIAIOSFODNN7EXAMPLE"

# Contiguous, real-format credential markers. Each requires enough trailing
# entropy that an obvious short placeholder does not match, but a realistic
# committed credential does.
_MARKERS = [
    re.compile(r"sk_live_[A-Za-z0-9]{12,}"),
    re.compile(r"rk_live_[A-Za-z0-9]{12,}"),
    re.compile(r"pk_live_[A-Za-z0-9]{12,}"),
    re.compile(r"whsec_[A-Za-z0-9]{20,}"),
    re.compile(r"sq0a[tc][pb]-[A-Za-z0-9]{15,}"),
    re.compile(r"ghp_[A-Za-z0-9]{16,}"),
    re.compile(r"gho_[A-Za-z0-9]{16,}"),
    re.compile(r"ghs_[A-Za-z0-9]{16,}"),
    re.compile(r"github_pat_[A-Za-z0-9_]{16,}"),
    re.compile(r"glpat-[A-Za-z0-9_-]{15,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    # Tailscale auth/API/OAuth-client keys. Added after GitHub secret-scanning
    # alert #1 fired on a contiguous `tskey-auth-…` literal in a fixture:
    # the marker list is what stops that class from ever being re-introduced.
    re.compile(r"tskey-(?:auth|api|client)-[A-Za-z0-9_-]{12,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"xox[bp]-[0-9]{8,}"),
    re.compile(r"AIza[A-Za-z0-9_-]{30,}"),
]

# Connection strings with embedded credentials — scheme://user:password@host —
# for ANY scheme (postgres, mysql, mssql, mongodb, redis, amqp, ftp, sip, rtsp,
# rtmp, …). The USER class `[A-Za-z0-9_.-]` and the literal `:` rule out detector
# regexes (which use `[^@]+@` right after `://`) and the runtime-gen f-string
# templates (`://{user}:{pw}@`). A captured password that is an OBVIOUS
# placeholder (below) is allowed — those are intentional weak/default-cred or
# suppression-test fixtures that no scanner flags.
_CONN_RE = re.compile(
    r"[a-z][a-z0-9+.-]{1,12}://[A-Za-z0-9_.-]{1,40}:"
    r"(?P<pw>[A-Za-z0-9!_%+.~$^*-]{3,80})@[A-Za-z0-9._-]"
)
_PLACEHOLDER_PW = frozenset({
    "pass", "password", "passwd", "pwd", "admin", "root", "user", "username",
    "changeme", "secret", "example", "test", "redacted", "placeholder",
    "xxx", "xxxx", "none", "empty",
})

# Generic (un-prefixed) secret literal: a secret-NAMED variable assigned a
# realistic high-entropy value, e.g. `CLIENT_SECRET = "xK9mP2qR7nL4vB8w"`.
# Neither TruffleHog (no structure) nor the prefix markers catch these.
# No leading word-boundary: the secret keyword is often the SUFFIX of a longer
# identifier (LOOKER_CLIENT_SECRET, VERCEL_…_SECRET, wgDBpassword, STRIPE_SECRET).
_SECRET_NAME_RE = re.compile(
    r"(?i)(?:client[_-]?secret|api[_-]?key|access[_-]?key|auth[_-]?token|"
    r"private[_-]?key|secret|password|passwd|token|bearer|apikey|credential)"
    r"\b[\"']?\s*[=:]\s*[\"'](?P<val>[A-Za-z0-9+/=_-]{16,})[\"']"
)
# Words that mark a value as an intentional placeholder/test-vector (allowed).
_PLACEHOLDER_MARKERS = (
    "example", "test", "xxx", "placeholder", "redacted", "changeme", "your",
    "sample", "dummy", "fake", "none", "null", "todo", "here", "value",
    "replace", "leak", "notreal", "fixture", "synthetic", "demo", "foobar",
)


def _looks_like_real_secret(val: str) -> bool:
    """True for a realistic high-entropy secret value; False for obvious
    placeholders / low-entropy test vectors (pure hex, single char-class)."""
    low = val.lower()
    if any(m in low for m in _PLACEHOLDER_MARKERS):
        return False
    if re.fullmatch(r"[0-9a-f]+", val):  # pure lowercase hex = crypto test vector
        return False
    classes = (
        bool(re.search(r"[a-z]", val))
        + bool(re.search(r"[A-Z]", val))
        + bool(re.search(r"[0-9]", val))
    )
    return classes >= 2 and len(val) >= 16


# Base64-WRAPPED secrets — a blob that decodes to a recognizable token prefix
# (the "smart scanner decodes base64" case). Low false-positive: only flags when
# the DECODED text contains a real vendor token prefix.
_B64_BLOB_RE = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")
_DECODED_TOKEN_RE = re.compile(
    r"(?:gh[pousr]_|github_pat_|sk_live_|rk_live_|xox[bp]-|glpat-)[A-Za-z0-9_]{12,}"
)


def _b64_wraps_secret(blob: str) -> bool:
    try:
        raw = base64.b64decode(blob + "=" * (-len(blob) % 4), validate=False)
        dec = raw.decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    if not dec or sum(c.isprintable() for c in dec) < 0.85 * len(dec):
        return False
    return bool(_DECODED_TOKEN_RE.search(dec))

# Directories whose tracked source ships or is published. (`git ls-files`
# already excludes gitignored caches / venvs / reports / downloads_dev.)
_SCAN_PREFIXES = ("tests/", "scripts/", "skills/", "commands/", "hooks/", ".claude-plugin/")
_SCAN_ROOT_SUFFIXES = (".py", ".sh", ".md", ".yml", ".yaml", ".json", ".toml")
_BINARY_SUFFIXES = (".png", ".jpg", ".jpeg", ".gif", ".ico", ".pyc", ".woff", ".woff2", ".ttf")


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    files: list[Path] = []
    for rel in out.splitlines():
        if not rel:
            continue
        if rel.endswith(_BINARY_SUFFIXES):
            continue
        if "__pycache__" in rel:
            continue
        in_scan_dir = rel.startswith(_SCAN_PREFIXES)
        is_root_text = ("/" not in rel) and rel.endswith(_SCAN_ROOT_SUFFIXES)
        if in_scan_dir or is_root_text:
            files.append(_REPO_ROOT / rel)
    return files


def test_no_contiguous_secret_literals_in_tracked_source() -> None:
    """Tracked source contains no contiguous, real-format credential literal."""
    violations: list[str] = []
    for path in _tracked_files():
        if path.name in _EXEMPT_NAMES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            if _AWS_CANONICAL in line:
                continue  # universally-allowlisted AWS docs example
            matched = False
            for marker in _MARKERS:
                m = marker.search(line)
                if m:
                    rel = path.relative_to(_REPO_ROOT)
                    violations.append(f"{rel}:{lineno}: {m.group(0)[:24]}…")
                    matched = True
                    break
            if matched:
                continue
            cm = _CONN_RE.search(line)
            if cm and cm.group("pw").lower() not in _PLACEHOLDER_PW:
                rel = path.relative_to(_REPO_ROOT)
                violations.append(f"{rel}:{lineno}: {cm.group(0)[:30]}… (conn-string cred)")
                continue
            gm = _SECRET_NAME_RE.search(line)
            if gm and _looks_like_real_secret(gm.group("val")):
                rel = path.relative_to(_REPO_ROOT)
                violations.append(f"{rel}:{lineno}: {gm.group(0)[:34]}… (generic secret)")
                continue
            for bm in _B64_BLOB_RE.finditer(line):
                if _b64_wraps_secret(bm.group(0)):
                    rel = path.relative_to(_REPO_ROOT)
                    violations.append(f"{rel}:{lineno}: {bm.group(0)[:24]}… (base64-wrapped token)")
                    break
    assert not violations, (
        "Contiguous credential literal(s) found in tracked source — fragment "
        "them per tests/README.md:\n  " + "\n  ".join(violations)
    )


def test_scan_actually_covers_the_corpus() -> None:
    """Sanity: the scanner sees a non-trivial number of source files."""
    files = _tracked_files()
    # The fixture corpus alone is dozens of files; guard against a silently
    # empty scan (e.g. git ls-files failing or prefixes drifting).
    assert len(files) >= 50, f"scan covered only {len(files)} files — too few"
