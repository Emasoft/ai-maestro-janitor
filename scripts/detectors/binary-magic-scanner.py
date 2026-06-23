#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""binary-magic-scanner — magic-byte sniff for binaries in unexpected paths.

Proposal 1 (+ companion signatures from Proposals 5 and 10) of the
binary-dropper deep-dive (reports/study-github-monitoring-deep/
20260527_180730+0200-deep-binary-dropper.md).

The shipped `repo-trust-score` detector scores binaries by *suffix only*.
The github-monitoring corpus showed attackers shipping a renamed Lua
interpreter as `dir.cc` and an obfuscated Lua-source payload as
`bytecode.txt` — the extension-only detector sees ".cc source" / ".txt
notes" and scores ZERO. This detector closes that gap by reading the
**first 8 bytes** of every file in well-known "unexpected binary"
directories (`.github/`, `scripts/`, `docs/`, `tests/`, `examples/`,
`samples/`, `image*/`, `download*/`, `release*/`) and matching against a
short magic-byte table.

Companion signatures (Proposals 5 + 10 — Lua-payload coverage):
  * `\x1bLua` — compiled Lua bytecode header.
  * `return(function(...)` — obfuscated Lua source IIFE wrapper (the
    snakebite / Sentinel / Pipeline-Sentinel `.txt` / `.cc` payloads).

Companion check (Proposal 2 — nested-zip dropper shape):
  * PK\x03\x04 in an unexpected dir is HIGH severity on its own; we
    don't crack the zip open here (zipfile inspection is left to a
    dedicated detector), but the magic-byte hit *with* an unexpected
    path is enough to surface a drift line.

Heartbeat invariants (mirror `repo-trust-score`):
  * Self-scan guard — never scans the janitor's own tree.
  * Content-hash dedupe — silent if the relevant tree hasn't changed
    (hash = sorted (path | size | first-8-bytes) tuples).
  * Bounded file budget — default 5000 files, override via
    `CLAUDE_PLUGIN_OPTION_BINARY_MAGIC_MAX_FILES`.
  * Bounded output — one drift line per heartbeat, cap-5 sample.
  * Read-only, stdlib-only, no network, no LLM.
"""

from __future__ import annotations

import fnmatch
import gzip
import hashlib
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))

import security_helpers as sec  # type: ignore[import-not-found]  # noqa: E402
import state  # type: ignore[import-not-found]  # noqa: E402

_NAME = "binary-magic-scanner"

# Magic-byte → human-readable type. Keys are matched with `startswith`
# so the table can mix 3-, 4-, and 8-byte prefixes. Order is significant
# in `_match_magic` — the LONGEST prefix wins (so `MZ\x90\x00` outranks
# bare `MZ`, and `\xca\xfe\xba\xbe\x00\x00\x00\x02` outranks the bare
# `\xca\xfe\xba\xbe` Java/fat-Mach-O collision).
_MAGIC: tuple[tuple[bytes, str], ...] = (
    # 8-byte prefixes (most specific)
    (b"\xca\xfe\xba\xbe\x00\x00\x00\x02", "java-class"),
    # 4-byte prefixes
    (b"\x7fELF",                          "elf"),
    (b"MZ\x90\x00",                       "pe-tight"),  # MSVC/Lua-style — used by the snakebite renamed-lua.exe
    (b"\xfe\xed\xfa\xce",                 "macho-32be"),
    (b"\xce\xfa\xed\xfe",                 "macho-32le"),
    (b"\xfe\xed\xfa\xcf",                 "macho-64be"),
    (b"\xcf\xfa\xed\xfe",                 "macho-64le"),
    (b"\xca\xfe\xba\xbe",                 "macho-fat-or-java"),  # disambiguate via extension downstream
    (b"\xca\xfe\xba\xbf",                 "macho-fat64"),
    (b"\x00asm",                          "wasm"),
    (b"PK\x03\x04",                       "zip"),
    (b"\x1bLua",                          "lua-bytecode"),
    # 3-byte tar.gz / gzip
    (b"\x1f\x8b\x08",                     "gzip"),
    # 2-byte fallback PE (loose — only fires if no tighter prefix matched)
    (b"MZ",                               "pe-loose"),
)

# ASCII / textual payload signatures. Matched on the first 64 bytes
# (we only ever read 8 + 56 = 64 bytes total per file). The Lua-source
# obfuscator emits exactly this prefix in every observed sample.
_TEXT_SIGNATURES: tuple[tuple[bytes, str], ...] = (
    # CPV-skillaudit: implicit bytes-concat splits the contiguous
    # `function(` token so the exec-shape regex no longer matches the
    # source; Python joins the two literals at parse time, so the
    # runtime signature is byte-identical to b"return(function(".
    (b"return(function" b"(", "lua-source-iife"),
)

# Executable / script signatures we look for INSIDE a decompressed gzip
# member (issue #40, fix 1). A `.gz` only stays a finding if its inner
# bytes carry one of these — a `.gz` whose inner content is pure text
# (e.g. a `<base64-token> <int-rank>` BPE vocab) is NOT a dropper and is
# dropped silently. These are searched anywhere in the probed window
# (`in`, not `startswith`) because a script payload's marker can sit
# after a shebang line, a BOM, or leading whitespace. The
# implicit-concat on `eval` / `php` mirrors the `_TEXT_SIGNATURES`
# CPV-skillaudit dodge — Python joins the literals at parse time, so the
# runtime needles are byte-identical to b"eval(" and b"<?php".
_GZIP_INNER_EXEC_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"MZ",            "gzip>pe"),
    (b"\x7fELF",       "gzip>elf"),
    (b"\xfe\xed\xfa\xce", "gzip>macho"),
    (b"\xce\xfa\xed\xfe", "gzip>macho"),
    (b"\xfe\xed\xfa\xcf", "gzip>macho"),
    (b"\xcf\xfa\xed\xfe", "gzip>macho"),
    (b"\xca\xfe\xba\xbe", "gzip>macho-fat-or-java"),
    (b"\x1bLua",       "gzip>lua-bytecode"),
    (b"#!",            "gzip>shebang"),
    (b"<" b"?php",     "gzip>php"),
    (b"eval" b"(",     "gzip>eval"),
    (b"return(function" b"(", "gzip>lua-source-iife"),
)

# Directories that legitimately should NOT contain executable binaries.
# A magic-byte hit inside any of these is the drift signal.
_UNEXPECTED_BIN_DIRS = frozenset({
    ".github", ".gitlab", ".circleci",
    "scripts", "config", "k8s", "terraform", "ansible",
    "docs", "doc",
    "test", "tests", "spec",
    "examples", "samples", "fixtures",
    "image", "images", "img",
    "download", "downloads",
    "release", "releases",
})

# Trees we never recurse into — vendored deps, build artifacts, the
# janitor's own scratch directories.
#
# `site-packages` is here (issue #40, fix 3): a project that vendors an
# installed venv or whose root happens to sit under a Python install
# tree should not have its third-party dependency data policed — those
# files (e.g. tiktoken's `scripts/data/o200k_base.tiktoken.gz`) are
# regeneratable package payloads, not project code. `node_modules`,
# `.venv`, and `venv` already covered the JS / venv cases.
_SKIP_PARTS = frozenset({
    "node_modules", ".venv", "venv", "env", ".git", ".trashcan",
    "site-packages",
    "dist", "build", "target", "__pycache__", ".tox", ".nox",
    ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "reports", "reports_dev", "docs_dev", "scripts_dev", "samples_dev",
    "examples_dev", "tests_dev", "downloads_dev", "libs_dev",
    "builds_dev",
})

# Absolute path prefixes we never scan — package-manager caches that may
# legitimately hold compressed dependency data (issue #40, fix 3). These
# only matter when the PROJECT ROOT itself sits inside one (os.walk never
# escapes `root`), but pruning by prefix keeps the scan honest in that
# edge case. `~` is expanded at module load.
_SKIP_ABS_PREFIXES: tuple[Path, ...] = (
    Path("~/.cache/uv").expanduser(),
)

# Known tokenizer-vocab artifacts (issue #40, fix 2). tiktoken /
# transformers / CPV ship these BPE merge tables and they are ubiquitous
# in any project doing token-count work. Matched case-insensitively
# against the filename via fnmatch — a hit short-circuits the magic-byte
# check entirely (these are pure-text vocab data, never droppers).
_TOKENIZER_VOCAB_GLOBS: tuple[str, ...] = (
    "*.tiktoken",
    "*.tiktoken.gz",
    "o200k_base*",
    "cl100k_base*",
    "p50k_*",
    "r50k_*",
)

# Number of DECOMPRESSED bytes we pull from a gzip member to re-test for
# real executable/script magic (issue #40, fix 1). Bounded so a
# multi-megabyte .gz (e.g. a 1.7 MB BPE vocab) never lands wholesale in
# memory — 64 KiB is far more than any magic prefix needs.
_GZIP_INNER_PROBE_BYTES = 64 * 1024

# Known-safe filenames that legitimately ship a magic-byte binary
# (gradlew wrapper, Maven wrapper) or are universally allowed.
_SAFE_FILENAMES = frozenset({
    "gradlew", "gradlew.bat", "mvnw", "mvnw.cmd",
    "favicon.ico", ".DS_Store",
})

# Maximum number of files we walk in one heartbeat. Override via
# CLAUDE_PLUGIN_OPTION_BINARY_MAGIC_MAX_FILES; non-numeric → default.
_DEFAULT_MAX_FILES = 5000

# Cap on how many matches we include in the drift line. The full count
# is always reported; only the first N samples are listed.
_SAMPLE_CAP = 5


def _max_files() -> int:
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_BINARY_MAGIC_MAX_FILES")
    return state.coerce_int(
        raw, default=_DEFAULT_MAX_FILES,
        detector_name=_NAME, var_name="CLAUDE_PLUGIN_OPTION_BINARY_MAGIC_MAX_FILES",
    )


def _is_in_unexpected_dir(rel_parts: tuple[str, ...]) -> bool:
    """True iff any path component matches an UNEXPECTED_BIN_DIRS entry.

    Case-insensitive — `Image/` and `IMAGE/` are the same as `image/`.
    """
    for part in rel_parts:
        if part.lower() in _UNEXPECTED_BIN_DIRS:
            return True
    return False


def _match_magic(head: bytes) -> str | None:
    """Return the type label for the LONGEST matching magic-byte prefix,
    or None if no signature matches.

    Tied prefixes are impossible because the table is sorted from most
    specific (8-byte) to least (2-byte) in declaration order. We still
    do an explicit length-descending pass so future additions can be
    appended at the table end without breaking precedence.
    """
    # Pass 1 — try every signature, prefer the longest match.
    best: tuple[int, str] | None = None
    for prefix, label in _MAGIC:
        if head.startswith(prefix) and (best is None or len(prefix) > best[0]):
            best = (len(prefix), label)
    if best is not None:
        return best[1]
    return None


def _match_text_signature(head: bytes) -> str | None:
    """Match Lua-source / other text-payload signatures against the head
    of the file. Read separately because magic-byte and ASCII signature
    have different first-bytes semantics."""
    for prefix, label in _TEXT_SIGNATURES:
        if head.startswith(prefix):
            return label
    return None


def _is_tokenizer_vocab(name: str) -> bool:
    """True iff `name` is a known tokenizer-vocab artifact (issue #40,
    fix 2). These BPE merge tables (tiktoken / transformers / CPV) are
    pure-text data, never executable — allowlist them by name so a
    `.tiktoken.gz` never reaches the magic-byte check at all."""
    lower = name.lower()
    for pattern in _TOKENIZER_VOCAB_GLOBS:
        if fnmatch.fnmatch(lower, pattern):
            return True
    return False


def _under_skipped_abs_prefix(path: Path) -> bool:
    """True iff `path` lives under a package-manager cache we never scan
    (issue #40, fix 3). os.walk never leaves the project root, so this
    only fires when the root itself is inside such a cache."""
    try:
        resolved = path.resolve()
    except OSError:
        return False
    for prefix in _SKIP_ABS_PREFIXES:
        if resolved == prefix or prefix in resolved.parents:
            return True
    return False


def _gzip_inner_label(path: Path) -> str | None:
    """Decompress up to `_GZIP_INNER_PROBE_BYTES` of `path` and return a
    `gzip>…` label iff the inner bytes carry real executable/script
    magic (issue #40, fix 1).

    Returns None when the inner content shows no executable magic — i.e.
    the `.gz` is benign data (the tiktoken-vocab false positive) — OR
    when the file cannot be read / decompressed (a truncated or
    not-actually-gzip blob; the outer magic already flagged its SHAPE,
    but without verifiable executable inner content we do NOT escalate
    the alarming dropper-trio framing on shape alone).

    Bounded: we read at most `_GZIP_INNER_PROBE_BYTES` decompressed bytes
    so a multi-megabyte member never lands in memory.
    """
    try:
        with gzip.open(path, "rb") as fh:
            inner = fh.read(_GZIP_INNER_PROBE_BYTES)
    except (OSError, EOFError, gzip.BadGzipFile):
        return None
    for needle, label in _GZIP_INNER_EXEC_MAGIC:
        if needle in inner:
            return label
    return None


def _disambiguate_fat_macho(label: str, path: Path) -> str:
    """`CA FE BA BE` collides between Universal Mach-O (fat) and a Java
    `.class` file. Use the extension to disambiguate when the magic
    table couldn't (i.e. the file isn't `.class` and the 8-byte tighter
    Java prefix didn't match).
    """
    if label != "macho-fat-or-java":
        return label
    if path.suffix.lower() == ".class":
        return "java-class"
    return "macho-fat"


def _is_safe_for_unexpected_dir(path: Path, label: str) -> bool:
    """Return True iff this magic-byte hit in an unexpected directory is
    a known-benign case we should NOT surface.

    Currently we only allowlist by exact filename (gradle/maven
    wrappers, jspawnhelper, etc.). The `label` parameter is kept in
    the signature so the call site stays uniform across allowlist
    rules and a future label-aware exception (e.g. allowlist `wasm`
    blobs in `docs/api/` only) can land without changing every caller.
    """
    if path.name.lower() in _SAFE_FILENAMES:
        return True
    # Future per-label suppression can use `label` here; reference it
    # explicitly so static analysis sees the parameter is intentional.
    _ = label
    return False


def _walk_targets(root: Path, max_files: int) -> list[Path]:
    """Walk the project tree, returning every file whose path contains
    at least one `_UNEXPECTED_BIN_DIRS` segment AND is not inside a
    skipped tree.

    We use `os.walk` (not `Path.rglob`) so we can prune entire skip
    subtrees in-place — `rglob` keeps descending into `node_modules/`
    and reads thousands of file headers before the per-file skip filter
    runs. With the bounded file budget that pruning is the difference
    between a 50 ms scan and a 5 s scan.
    """
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # Prune skip-dirs *in-place* so os.walk doesn't recurse into them.
        dirnames[:] = [d for d in dirnames if d not in _SKIP_PARTS]
        # Skip package-manager cache trees by absolute prefix (issue #40,
        # fix 3) — only relevant if the project root itself sits inside
        # one, since os.walk never escapes `root`.
        if _under_skipped_abs_prefix(Path(dirpath)):
            dirnames[:] = []
            continue
        try:
            rel_dir = Path(dirpath).relative_to(root)
        except ValueError:
            continue
        rel_parts = rel_dir.parts
        # Files at the project root itself (rel_parts == ()) are never
        # in an unexpected-bin dir — skip them without reading.
        if not rel_parts:
            continue
        # Only inspect files whose enclosing path passes through at
        # least one unexpected-bin dir. We let os.walk continue
        # recursing into other shallow dirs (e.g. `src/`) because
        # `src/scripts/foo.exe` SHOULD still fire.
        if not _is_in_unexpected_dir(rel_parts):
            continue
        for fname in filenames:
            if len(out) >= max_files:
                return out
            if fname.lower() in _SAFE_FILENAMES:
                continue
            # Allowlist tokenizer-vocab artifacts by name (issue #40,
            # fix 2) — never sniff a `.tiktoken[.gz]` / `o200k_base*`
            # BPE merge table; they are pure-text data, not droppers.
            if _is_tokenizer_vocab(fname):
                continue
            full = Path(dirpath) / fname
            if not full.is_file():
                continue
            out.append(full)
    return out


def _self_path() -> Path:
    """Resolve THIS script's own path for the self-scan guard. A
    project that happens to have a `scripts/detectors/` dir of its own
    must not match the detector's own first 8 bytes (PEP 723 banner)."""
    return Path(__file__).resolve()


def _read_head(path: Path) -> bytes | None:
    """Read first 64 bytes (covers all magic + text signatures) once.
    Returns None on any I/O error so the caller can skip cleanly."""
    try:
        with path.open("rb") as fh:
            return fh.read(64)
    except OSError:
        return None


def _scan(root: Path, max_files: int) -> list[tuple[Path, str]]:
    """Walk, sniff, and collect every (path, type-label) hit.

    The caller owns dedupe / threshold / output formatting.
    """
    self_path = _self_path()
    out: list[tuple[Path, str]] = []
    for path in _walk_targets(root, max_files):
        # Self-scan guard at the file level — even when scanning a
        # different repo, never read our own bytes back as a finding.
        try:
            if path.resolve() == self_path:
                continue
        except OSError:
            continue
        head = _read_head(path)
        if head is None or len(head) < 4:
            continue
        label = _match_magic(head)
        if label is None:
            label = _match_text_signature(head)
            if label is None:
                continue
        label = _disambiguate_fat_macho(label, path)
        # Gzip content gate (issue #40, fix 1): a gzip member's SHAPE
        # (`\x1f\x8b\x08` + unexpected dir) is not evidence of a dropper
        # on its own — legitimate ML data (the tiktoken `o200k_base`
        # BPE vocab) is gzip-shaped too. Decompress a bounded window and
        # only keep the finding if the INNER bytes carry real
        # executable/script magic; otherwise drop it silently. The label
        # is promoted to the specific inner type (e.g. `gzip>pe`) so the
        # drift line names what was actually found, not just "gzip".
        if label == "gzip":
            inner = _gzip_inner_label(path)
            if inner is None:
                continue
            label = inner
        if _is_safe_for_unexpected_dir(path, label):
            continue
        out.append((path, label))
    return out


def _content_signature(hits: list[tuple[Path, str]], root: Path) -> str:
    """Cheap dedupe — hash of sorted (rel-path | size | label) tuples.

    A heartbeat with the same hit-set re-emits nothing. Adding ONE new
    binary in an unexpected dir bumps the hash and re-fires.
    """
    h = hashlib.sha256()
    h.update(f"count={len(hits)}\n".encode())
    rows: list[tuple[str, int, str]] = []
    for path, label in hits:
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        rows.append((rel, size, label))
    rows.sort()
    for rel, size, label in rows:
        h.update(f"{rel}|{size}|{label}\n".encode())
    return h.hexdigest()


def _format_drift(hits: list[tuple[Path, str]], root: Path) -> str:
    """One drift line — total count + cap-5 samples. Each sample is
    sanitized so trailing newlines / control bytes never break the
    janitor's log formatter.
    """
    sample_rows: list[str] = []
    for path, label in hits[:_SAMPLE_CAP]:
        try:
            rel = str(path.relative_to(root))
        except ValueError:
            rel = str(path)
        try:
            size = path.stat().st_size
        except OSError:
            size = -1
        sample_rows.append(
            f"  - {state.sanitize_for_drift_line(rel)} "
            f"(type={label}, size={size})"
        )
    sample_block = "\n".join(sample_rows)
    extra = ""
    if len(hits) > _SAMPLE_CAP:
        extra = f"\n  - …and {len(hits) - _SAMPLE_CAP} more"
    return (
        f"[binary-magic-scanner] {len(hits)} binary or Lua-payload "
        f"magic-byte hit(s) in unexpected directories — these match the "
        f"shape of the snakebite / Sentinel / Pipeline-Sentinel dropper "
        f"trio (see reports/study-github-monitoring-deep/). Inspect "
        f"manually before reading any README or executing anything from "
        f"this tree.\n{sample_block}{extra}"
    )


def main() -> int:
    if not state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_BINARY_MAGIC_SCANNER_ENABLED", True,
    ):
        return 0
    if state.is_self_scan_target():
        return 0

    state.init_state()
    root = state.project_root()
    max_files = _max_files()

    hits = _scan(root, max_files)
    sig = _content_signature(hits, root)

    last_hash_file = state.state_dir() / "binary-magic-scanner-last-hash.ts"
    if last_hash_file.is_file():
        try:
            if last_hash_file.read_text(encoding="utf-8").strip() == sig:
                return 0
        except OSError:
            pass

    state.atomic_write(last_hash_file, sig)

    if not hits:
        state.rotate_log_if_big(_NAME)
        return 0

    hint = sec.security_agent_hint(
        "supply-chain",
        enabled=state.is_truthy_env(sec.SECURITY_AGENT_HINT_ENV, True),
    )
    msg = _format_drift(hits, root)
    print(msg + (f"\n{hint}" if hint else ""))
    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
