#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""repomap_generate — generate/refresh the project map in the root PROJECT_MAP.md.

The user-facing entry point of the auto-maintained project map
(TRDD-e247a349; moved out of CLAUDE.md into its own file by TRDD-FADYLSQB).
Drives the tested `lib/repomap` package (extractor + renderer + markers)
end-to-end:

  uv run scripts/repomap_generate.py [--root DIR]      # write/refresh PROJECT_MAP.md
  uv run scripts/repomap_generate.py --check           # freshness probe (no write)
  uv run scripts/repomap_generate.py --remove          # delete the generated map
  uv run scripts/repomap_generate.py --stdout          # print the file, touch nothing

Exit codes: 0 = fresh / written / removed; 1 = --check found the map STALE
(structure changed); 2 = --check found NO PROJECT_MAP.md; 3 = error (no
generated header on --check/--remove, PROJECT_MAP.md tracked or not ignorable,
oversize map, lock held, a failed or unverified write, a malformed legacy fence,
CLAUDE.md being actively edited during the legacy strip).

THE MAP FILE is generated, machine-local and git-ignored: nobody co-edits it, so
its write is a plain atomic replace under a project-scoped flock, with no
splice/merge machinery. Its first line is a single-line HTML-comment header
(`schema`, `sha`, `methods`, `digest`, `generated`; see lib/repomap/renderer.py).
`ensure_excluded` adds `/PROJECT_MAP.md` to the file `git rev-parse --git-path
info/exclude` names (correct in a linked worktree too), so the map never dirties the
tree and never ships; it refuses (exit 3) when the file is already tracked, and a
post-write `git check-ignore` must pass or the run fails — no silent fallback.

THE LEGACY STRIP is the only code that still edits CLAUDE.md, which is co-owned by
the human and the session's Claude, so the janitor must NEVER corrupt or silently
discard their edits. An older generator wrote a fenced REPO-MAP block into CLAUDE.md;
once PROJECT_MAP.md is written AND re-read with a header `sha` equal to the in-memory
`map_sha` (never before: a failed or unverified write must not delete the only copy of
the map), that fence is removed once:

  1. WRITER LOCK — a project-scoped flock (`.janitor/state/repomap.lock`)
     serializes generator instances across sessions. Non-blocking: a second
     instance SKIPS (exit 3) instead of queueing.
  2. LOST-UPDATE GUARD — read → strip → re-stat → replace. The file's
     (mtime_ns, size) signature is captured WITH the read and `os.replace` only
     fires if it is UNCHANGED at the last instant; otherwise re-read and re-strip
     against THEIR text. Bounded retries, then give up safely (exit 3) — never
     last-writer-wins over a human edit.
  3. BYTE-PRESERVATION INVARIANT — before the replace, every byte outside the
     fenced span is verified to survive (only newlines at the seam may differ).
  4. ROLLING BACKUP — the pre-strip CLAUDE.md is copied to
     `.janitor/state/CLAUDE.md.pre-repomap.bak` before the replace.
  5. ATOMIC REPLACE — tmp file in the SAME directory + `os.replace`.

NEVER FROM THE HEARTBEAT — but for CO-OWNERSHIP of CLAUDE.md, not for cache cost.
The `project-map-drift` detector only NUDGES; a human/agent runs this script, and
may run it AT ANY TIME.

     The old text here also claimed a mid-session rewrite "busts the context
     cache (TRDD-e247a349 §5)", and told the reader to wait for a cache-cheap
     moment. MEASURED NEGLIGIBLE 2026-08-26 (TRDD-LFSWY0C6): across 307 turns that
     immediately followed a CLAUDE.md Edit/Write, max cache_creation was
     65,923 tokens and the median 1,525 — versus 598,351 max across the other
     108,303 turns. The 598k-scale rewrite is real but never followed a CLAUDE.md edit in that sample;
     the cache-bust on the turns right after an edit, in the same session, is negligible, and it is not why this script never runs from the heartbeat. Kept as a correction, because the
     old claim is what made agents defer the refresh for days.

Freshness is two-tier, cheapest first: the repo-change `digest=` (git HEAD +
porcelain-status hash) is compared BEFORE any extraction; only a digest
mismatch pays for extraction, and a `sha=` match after extraction still counts
as fresh and skips the write — a comment-only edit changes the digest but not
the structure, and must not churn the file. `--check` hashes with the
`methods=` value the header names, never with a hardcoded default.

File discovery is `git ls-files` scoped to the extractor REGISTRY's extensions
(today just `*.py`; adding a language is one registry entry, see EXTRACTORS in
lib/repomap/extractor.py) — tracked files only, so .gitignore'd trees
(reports/, *_dev/, .venv) can never leak into the map. Outside a git repo it
falls back to a bounded rglob with the same exclusions.

Only a Python extractor exists today. On a repo whose tracked source is
overwhelmingly another language, the rendered map carries an explicit
coverage disclaimer instead of silently looking complete (janitor#175) — see
`coverage_note()`.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import time
from fnmatch import fnmatch
from pathlib import Path
from typing import Literal, TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from exe_path import exe  # noqa: E402
from repomap import (  # noqa: E402
    EXTRACTORS,
    FileMap,
    MalformedFences,
    has_map_block,
    map_sha,
    read_header,
    remove_map_block,
    render_file,
)
from repomap.markers import _fence_span  # noqa: E402  (the strip invariant needs the span)

# rglob fallback exclusions (non-git roots only; git discovery needs none of
# this because tracked-files-only already excludes them via .gitignore).
_EXCLUDE_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".trashcan",
        "reports",
        "reports_dev",
        "docs_dev",
        "scripts_dev",
        "samples_dev",
        "examples_dev",
        "tests_dev",
        "downloads_dev",
        "libs_dev",
        "builds_dev",
        "INPUT_DEV",
        "target",
        "build",
        "dist",
    }
)

# The generated map file, in the project root (TRDD-FADYLSQB).
MAP_NAME = "PROJECT_MAP.md"

# Lost-update guard: how many read→strip→verify→replace attempts before the
# generator gives up (someone is actively editing CLAUDE.md — let them win).
_SPLICE_ATTEMPTS = 5

# Settle delay for the retry loops (this strip loop, and the splice loops of
# scripts/claudemd_slim.py, which import it as rg._SPLICE_SETTLE_S). Sized to comfortably outlast a writer's
# truncate-to-write window (sub-millisecond for the read-modify-write an editor
# does), while staying far below any cadence this generator runs on. It is what
# makes a torn read DETECTABLE for the splice loops that need it; here it is only a backoff.
_SPLICE_SETTLE_S = 0.05


def _resolve_root(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def _git_run(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    """Run a git command in `root`; None when git cannot be launched or times out.

    Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock and
    collides with a concurrent `publish.py` commit (janitor#245).
    """
    try:
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        return subprocess.run(
            [exe("git"), *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            env=git_env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _git(root: Path, *args: str) -> str | None:
    """stdout of a git command in `root`; None on any failure (non-repo, no git)."""
    res = _git_run(root, *args)
    return res.stdout if res is not None and res.returncode == 0 else None


def _excludes_file(root: Path) -> Path:
    """The exclude list — a TRACKED root dotfile, matching the `.tldrignore` precedent.

    It MUST be tracked. The map it governs is generated per clone, so the file set must not
    depend on machine-local state or two clones map different trees. The list previously
    lived in `.janitor/state/`, which is gitignored and purgeable: on 2026-07-26 that list was
    absent, a plain regenerate silently pulled all 450 tracked test files into the map,
    and CLAUDE.md went 1720 -> 6032 lines (180KB -> 724KB). Nothing failed; it was caught
    by eyeballing a line count. A fresh clone hit the same thing, and `--check` reported a
    phantom STALE forever because it extracted a different file set than the generate did.
    """
    return root / ".repomapignore"


def _legacy_excludes_file(root: Path) -> Path:
    """Pre-2026-07-26 location (gitignored). Read-only fallback, migrated on first save."""
    return root / ".janitor" / "state" / "repomap-excludes.txt"


def _parse_excludes(text: str) -> list[str]:
    return [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def load_excludes(root: Path) -> list[str]:
    """The persisted exclude globs (one per line, `#` comments). Persisting
    them keeps `--check` and the drift detector consistent with what was
    actually generated — otherwise a check without the generate-time excludes
    would extract a different file set and report a phantom STALE forever.

    Tracked file first, then the legacy gitignored one so an existing checkout keeps its
    list until the next save migrates it.
    """
    for path in (_excludes_file(root), _legacy_excludes_file(root)):
        try:
            return _parse_excludes(path.read_text(encoding="utf-8"))
        except OSError:
            continue
    return []


def save_excludes(root: Path, globs: list[str]) -> None:
    """Persist to the TRACKED file. Never writes the legacy path back."""
    f = _excludes_file(root)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        "# Exclude globs for the PROJECT_MAP.md project map (scripts/repomap_generate.py).\n# TRACKED on purpose: every clone must map the same file set, or --check reports a\n# phantom STALE forever. See _excludes_file().\n" + "".join(g + "\n" for g in globs),
        encoding="utf-8",
    )


# Absolute ceiling on the generated map file. This is the backstop that does NOT depend on
# knowing the cause: the excludes file is one way the map can balloon, but any future
# change (a new tracked language, a vendored tree, a bad glob) is another, and the failure
# mode is identical and silent — a session that reads the map pays for every byte of it, so a
# 4x map is a permanent 4x tax nobody notices until the bill arrives. 256KB leaves real
# headroom over a names-only map while still catching a balloon.
MAX_BLOCK_BYTES_ENV = "CLAUDE_PLUGIN_OPTION_REPOMAP_MAX_BLOCK_BYTES"
_MAX_BLOCK_BYTES_DEFAULT = 256 * 1024


def max_block_bytes() -> int:
    raw = os.environ.get(MAX_BLOCK_BYTES_ENV, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _MAX_BLOCK_BYTES_DEFAULT
    return value if value > 0 else _MAX_BLOCK_BYTES_DEFAULT


def oversize_report(text: str, maps: list[FileMap], root: Path) -> str | None:
    """None when the map text fits; otherwise a message naming the top directories.

    Naming the contributors is the difference between an error someone can act on and one
    they work around with --force.
    """
    cap = max_block_bytes()
    size = len(text.encode("utf-8"))
    if size <= cap:
        return None
    tally: dict[str, int] = {}
    for fm in maps:
        try:
            rel = Path(fm.path).resolve().relative_to(root.resolve()).as_posix()
        except (ValueError, OSError):
            rel = str(fm.path)
        tally[rel.split("/", 1)[0]] = tally.get(rel.split("/", 1)[0], 0) + 1
    top = ", ".join(f"{d}/ ({n} files)" for d, n in sorted(tally.items(), key=lambda kv: -kv[1])[:5])
    return (
        f"repomap: REFUSING to write — PROJECT_MAP.md would be {size // 1024}KB, over the "
        f"{cap // 1024}KB cap, and every session that reads the map pays for all of it.\n"
        f"  Top contributors: {top}\n"
        f"  Fix the file set, e.g. `--exclude 'tests/**'` (persisted to .repomapignore),\n"
        f"  or raise {MAX_BLOCK_BYTES_ENV} deliberately if the map really must be this big."
    )


def discover_sources(root: Path, excludes: list[str] | None = None) -> list[Path]:
    """Tracked files whose extension the extractor REGISTRY can parse, via git
    (gitignore-respecting); bounded rglob fallback outside a repo. Sorted for
    determinism. `excludes` are fnmatch globs against the root-relative path
    (e.g. `tests/*`).

    Extensions are derived from `EXTRACTORS` (#175) instead of a hardcoded
    `"*.py"` pathspec — discovery follows whatever the registry can actually
    parse, so adding a language extractor is ONE registry entry, not a second
    hardcoded list that can drift out of step with it."""
    exts = sorted(EXTRACTORS)
    if not exts:
        return []
    listing = _git(root, "ls-files", "-z", "--", *(f"*{ext}" for ext in exts))
    if listing is not None:
        rels = [r for r in listing.split("\0") if r]
        paths = sorted((root / r) for r in rels if (root / r).is_file())
    else:
        paths = []
        for p in sorted(root.rglob("*")):
            if p.suffix not in exts or not p.is_file():
                continue
            if any(part in _EXCLUDE_DIRS for part in p.relative_to(root).parts):
                continue
            paths.append(p)
    if excludes:
        paths = [p for p in paths if not any(fnmatch(str(p.relative_to(root)), g) for g in excludes)]
    return paths


# Extensions that commonly hold real application source but the registry has
# no extractor for yet (P3 adds ts/go/rust — see extractor.py's own comment).
# Listed ONLY for the coverage-honesty check below: never extracted, never
# rendered as symbols. #175: a Python-only extractor on an otherwise-TypeScript
# repo produced a "Project map" covering 18 peripheral scripts and ZERO app
# files, presented under a heading that looks complete — a map of the wrong 1%
# presented as authoritative is worse than no map at all.
_OTHER_SOURCE_EXTS = frozenset(
    {
        ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs", ".go", ".rs", ".rb",
        ".java", ".kt", ".swift", ".c", ".cc", ".cpp", ".cs", ".php", ".scala",
        ".m", ".mm",
    }
)


def _other_tracked_source_count(root: Path, excludes: list[str] | None) -> int:
    """Tracked files in a common source language the registry cannot parse,
    after the SAME excludes the map itself honors (an intentionally-excluded
    tree must not trip the honesty check either). Git-only: a non-git root has
    no cheap way to see the whole tree, so it returns 0 rather than guessing."""
    listing = _git(root, "ls-files", "-z")
    if listing is None:
        return 0
    excludes = excludes or []
    count = 0
    for rel in listing.split("\0"):
        if not rel or Path(rel).suffix not in _OTHER_SOURCE_EXTS:
            continue
        if any(fnmatch(rel, g) for g in excludes):
            continue
        count += 1
    return count


def coverage_note(root: Path, maps: list[FileMap], excludes: list[str] | None = None) -> str | None:
    """None when the map is not obviously misrepresenting the repo; else an
    honest one-line disclaimer for the block itself — issue #175's "costs
    nothing" fallback: silence is better than an authoritative-looking partial
    map. Fires only when uncovered common-source files OUTNUMBER what got
    mapped, so a few incidental `.ts` config files next to hundreds of `.py`
    modules do not trip a warning on an ordinary Python repo."""
    other = _other_tracked_source_count(root, excludes)
    covered = len(maps)
    if other == 0 or other <= covered:
        return None
    return (
        f"> ⚠ Python-only extractor: this map covers {covered} file(s); {other} other "
        "tracked source file(s) (.ts/.tsx/.go/.rs/… — no extractor yet) are NOT "
        "represented — do not treat this as a complete project map (janitor#175)."
    )


def repo_digest(root: Path) -> str:
    """Cheap repo-change digest: git HEAD + a hash of the porcelain status
    (so uncommitted edits change the digest too). Non-git → max source mtime,
    the TRDD's documented fallback.

    CLAUDE.md, PROJECT_MAP.md and `.janitor/` are EXCLUDED from the porcelain hash —
    the map tracks SOURCE structure, and the generator dirties CLAUDE.md (the legacy
    strip) and, when its ignore rule failed, PROJECT_MAP.md;
    without the exclusion every generate would change the very digest it just
    recorded and instantly report itself stale (a perpetual nudge loop,
    caught by test_detector_nudges_only_when_opted_in_and_stale)."""
    head = _git(root, "rev-parse", "HEAD")
    if head is not None:
        status = _git(root, "status", "--porcelain") or ""
        kept = [ln for ln in status.splitlines() if ln[3:] not in ("CLAUDE.md", "PROJECT_MAP.md") and not ln[3:].startswith(".janitor/")]
        mix = head.strip() + "\n" + "\n".join(kept)
        return hashlib.sha256(mix.encode("utf-8")).hexdigest()[:12]
    latest = 0
    for p in discover_sources(root):
        try:
            latest = max(latest, int(p.stat().st_mtime))
        except OSError:
            continue
    return f"mtime-{latest}"


def extract_all(root: Path, excludes: list[str] | None = None) -> list[FileMap]:
    """Extract every supported source file. Today the adapter registry holds
    Python only (TRDD P3 adds ts/go/rust); a file the extractor cannot parse
    is skipped — one broken file must not take down the whole map."""
    maps: list[FileMap] = []
    for path in discover_sources(root, excludes):
        extract = EXTRACTORS.get(path.suffix)  # registry is keyed by extension
        if extract is None:
            continue
        try:
            fm = extract(path)
        except (OSError, SyntaxError, ValueError):
            continue
        fm.path = str(path.relative_to(root))
        maps.append(fm)
    return maps


def _stat_sig(path: Path) -> tuple[int, int] | None:
    """(mtime_ns, size) change signature; None when the file is absent."""
    try:
        st = path.stat()
    except OSError:
        return None
    return (st.st_mtime_ns, st.st_size)


def _atomic_replace(path: Path, text: str) -> None:
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".claudemd-tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        # mkstemp creates 0600 and os.replace keeps it, which left CLAUDE.md unreadable to other
        # tools. Keep a mode the user chose (0640, 0444...); heal only the bug's 0600 and new files
        # to 0644. A deliberately-0600 file cannot be told apart from the bug's and is widened
        # (accepted trade-off). No umask read: it is process-global in a threaded daemon.
        try:
            old = os.stat(path).st_mode & 0o777
        except OSError:
            old = None
        os.chmod(tmp, 0o644 if old in (None, 0o600) else old)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _outside_fences(text: str) -> str:
    """The narrative — everything OUTSIDE the fenced span (whole text when no
    block). The byte-preservation invariant compares this before/after."""
    span = _fence_span(text)
    if span is None:
        return text
    return text[: span[0]] + text[span[1] :]


def _strip_candidate(current: str) -> str:
    """Remove the fence from `current` and PROVE the result is safe to write: no fence
    left, and every byte outside the fenced span survives (only newlines at the seam may
    differ — remove_map_block normalises the blank lines around the cut).
    Raises MalformedFences on any violation (caller aborts the write)."""
    candidate = remove_map_block(current)
    if has_map_block(candidate):
        raise MalformedFences("candidate still contains a fence")
    if candidate.replace("\n", "") != _outside_fences(current).replace("\n", ""):
        raise MalformedFences("candidate would alter bytes outside the fences")
    return candidate


class _GenLock:
    """Project-scoped non-blocking flock. Held = another generator is mid-write
    in this project → we SKIP rather than queue (two writers never interleave;
    a skipped run just means the other instance is producing the same map)."""

    def __init__(self, root: Path):
        self._dir = root / ".janitor" / "state"
        self._fh: TextIO | None = None

    def acquire(self) -> bool:
        try:
            self._dir.mkdir(parents=True, exist_ok=True)
            self._fh = open(self._dir / "repomap.lock", "w")
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            if self._fh is not None:
                self._fh.close()
                self._fh = None
            return False

    def release(self) -> None:
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None


def _backup(claude_md: Path) -> None:
    """Rolling pre-write backup (RULE-0 spirit: a bad write is one cp away
    from undone). Best-effort — a backup failure must not block the write,
    but it is reported."""
    if not claude_md.is_file():
        return
    bak_dir = claude_md.parent / ".janitor" / "state"
    try:
        bak_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(claude_md, bak_dir / "CLAUDE.md.pre-repomap.bak")
    except OSError as exc:
        print(f"repomap: WARNING — backup failed ({exc}); continuing")


def strip_legacy_fence(claude_md: Path, attempts: int = _SPLICE_ATTEMPTS) -> Literal["absent", "stripped", "busy"]:
    """Remove the legacy REPO-MAP fence from CLAUDE.md, once, without ever eating a
    concurrent edit: read+signature → strip+invariant-verify → backup → re-stat →
    replace ONLY if untouched since the read. A concurrent edit (by the session's
    Claude or the human) triggers a re-read and re-strip against THEIR latest text.
    "busy" after `attempts` collisions (an active editor wins; retry later).

    No torn-read guard is needed here, unlike a splice-in: a read that lands in a
    writer's truncate-then-write window sees LESS (an empty or partial file), which
    here means "no fence" (nothing is written) or a half fence (MalformedFences, nothing
    is written). It can never make this function write a narrative-less file."""
    for attempt in range(attempts):
        if attempt:
            # Back off so the retries are independent samples, not all inside one
            # writer's window.
            time.sleep(_SPLICE_SETTLE_S)
        sig_before = _stat_sig(claude_md)
        if sig_before is None:
            return "absent"
        current = claude_md.read_text(encoding="utf-8")
        if not has_map_block(current):
            return "absent"
        candidate = _strip_candidate(current)
        # Backup BEFORE the re-stat: if the file moves between the backup and the replace,
        # the re-stat catches it; backing up after it would snapshot a file we did not read.
        _backup(claude_md)
        if _stat_sig(claude_md) != sig_before:
            continue  # changed while we stripped (ms window) — re-read their text
        _atomic_replace(claude_md, candidate)
        return "stripped"
    return "busy"


def _check_ignored(root: Path) -> bool | None:
    """True when git ignores PROJECT_MAP.md, False when it does not (or git failed);
    None when `root` is not in a git work tree."""
    if _git(root, "rev-parse", "--show-prefix") is None:
        return None
    res = _git_run(root, "check-ignore", "-q", "--", MAP_NAME)
    return res is not None and res.returncode == 0


def ensure_excluded(root: Path) -> str | None:
    """Make git ignore PROJECT_MAP.md through the local exclude file (never .gitignore,
    which is tracked and shared). None on success or in a non-git root; otherwise the
    error message (the caller exits 3).

    The exclude file is resolved with `git rev-parse --git-path info/exclude`, never
    `<root>/.git/info/exclude`: in a linked worktree `.git` is a FILE and the exclude list
    lives in the common git dir. The output is relative to `root` or absolute, so it is
    joined to `root` either way. In a subdirectory root the pattern carries the
    `--show-prefix`, because info/exclude patterns anchor at the work-tree top."""
    prefix = _git(root, "rev-parse", "--show-prefix")
    if prefix is None:
        return None
    tracked = _git_run(root, "ls-files", "--error-unmatch", "--", MAP_NAME)
    if tracked is None:
        return "repomap: git could not be run to check whether PROJECT_MAP.md is tracked"
    if tracked.returncode not in (0, 1):
        # rc 1 = "not tracked"; anything else (128: corrupt index, ...) is a git failure, not an answer
        return f"repomap: git ls-files failed ({tracked.returncode}): {tracked.stderr.strip()}"
    if tracked.returncode == 0:
        # A tracked file cannot be ignored, and regenerating it would dirty the tree on every
        # run; the owner must decide (git rm --cached), not the generator.
        return "repomap: REFUSING — PROJECT_MAP.md is tracked by git; `git rm --cached PROJECT_MAP.md` first (the map is generated per clone, never committed)"
    if _check_ignored(root):
        return None
    out = _git(root, "rev-parse", "--git-path", "info/exclude")
    if out is None:
        return "repomap: could not resolve the git exclude file (git rev-parse --git-path info/exclude failed)"
    exclude = root / out.strip()
    exclude.parent.mkdir(parents=True, exist_ok=True)
    existing = exclude.read_text(encoding="utf-8") if exclude.is_file() else ""
    with exclude.open("a", encoding="utf-8") as fh:
        fh.write(("\n" if existing and not existing.endswith("\n") else "") + f"/{prefix.strip()}{MAP_NAME}\n")
    if not _check_ignored(root):
        return f"repomap: REFUSING — PROJECT_MAP.md is still not ignored after writing {exclude}"
    return None


def _map_verified(target: Path, expected_sha: str) -> bool:
    """Re-read `target` from disk: its header must parse and carry `expected_sha`."""
    try:
        header = read_header(target.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError):
        return False
    return header is not None and header["sha"] == expected_sha


def current_map_sha(root: Path, header: dict[str, str]) -> str:
    """The sha the map WOULD carry if regenerated now, judged on the terms its own header
    names. ONE path for `--check` and the drift detector (TRDD-6HFOB5S4): the writer hashes
    the body WITH the coverage note, so a reader that dropped the note never matched and
    nudged STALE forever on a repo that has one. `methods=` comes from the header, so a map
    written with a different default is judged on its own terms, not reported stale."""
    excludes = load_excludes(root)
    maps = extract_all(root, excludes)
    return map_sha(maps, include_methods=header["methods"] == "1", coverage_note=coverage_note(root, maps, excludes))


def cmd_check(root: Path) -> int:
    target = root / MAP_NAME
    if not target.is_file():
        print("repomap: no PROJECT_MAP.md (run repomap_generate.py to write one)")
        return 2
    header = read_header(target.read_text(encoding="utf-8", errors="replace"))
    if header is None:
        print("repomap: PROJECT_MAP.md has no generated-map header — not a map this script wrote")
        return 3
    if header["digest"] == repo_digest(root):
        print("repomap: fresh (digest match)")
        return 0
    # Digest moved — only now pay for extraction; a structure match still counts as
    # fresh (comment-only change), but report it distinctly. current_map_sha is the
    # ONE hash path shared with the drift detector.
    if header["sha"] == current_map_sha(root, header):
        print("repomap: structure unchanged (digest moved; refresh optional)")
        return 0
    print("repomap: STALE — structure changed; refresh with repomap_generate.py")
    return 1


def cmd_remove(root: Path) -> int:
    target = root / MAP_NAME
    lock = _GenLock(root)
    if not lock.acquire():
        print("repomap: another generator holds the lock — skipping")
        return 3
    try:
        if not target.is_file():
            print("repomap: no PROJECT_MAP.md to remove")
            return 0
        # Only a file this script wrote: a hand-written PROJECT_MAP.md has no generated
        # header and must survive (a plain unlink has no trashcan).
        if read_header(target.read_text(encoding="utf-8", errors="replace")) is None:
            print("repomap: REFUSING to remove PROJECT_MAP.md — it has no generated-map header")
            return 3
        target.unlink()
        print("repomap: PROJECT_MAP.md removed (CLAUDE.md untouched)")
        return 0
    finally:
        lock.release()


def _write_map(root: Path, maps: list[FileMap], note: str | None, text: str) -> int:
    """Under the lock: ignore rule → write → re-read verify → ONLY THEN strip the legacy fence."""
    target = root / MAP_NAME
    err = ensure_excluded(root)
    if err is not None:
        print(err)
        return 3
    existing = target.read_text(encoding="utf-8", errors="replace") if target.is_file() else ""
    old = read_header(existing)
    if old is None and target.is_file():
        # Same rule as --remove: a file without a generated header is not ours. ensure_excluded has
        # already made it untracked+ignored, so git could not restore it; overwriting would lose it.
        print(f"repomap: REFUSING to overwrite {target} — it has no generated-map header (move it away first)")
        return 3
    # Current = the file equals what the generator would render with the OLD header's digest and
    # timestamp. Comparing the whole text (not just sha=) also catches a hand-edited body and a
    # map written with another methods= default; a no-op rerun then makes ZERO writes.
    if old is not None and existing == render_file(maps, generated_iso=old["generated"], digest=old["digest"], coverage_note=note):
        print("repomap: already current (structure hash match) — no write")
    else:
        try:
            _atomic_replace(target, text)
        except OSError as exc:
            print(f"repomap: could not write {target}: {exc} — CLAUDE.md untouched")
            return 3
        print(f"repomap: wrote {text.count(chr(10))}-line map into {target} ({len(maps)} files)")
    # D4 ordering: the legacy fence is the only other copy of the map. It is stripped only
    # after the new file is re-read from disk and its header sha equals the in-memory hash;
    # a failed or unverified write must leave the fence in place.
    if not _map_verified(target, map_sha(maps, coverage_note=note)):
        print("repomap: PROJECT_MAP.md failed re-read verification — CLAUDE.md untouched")
        return 3
    if _check_ignored(root) is False:
        print("repomap: REFUSING — PROJECT_MAP.md is not ignored by git after writing; CLAUDE.md untouched")
        return 3
    outcome = strip_legacy_fence(root / "CLAUDE.md")
    if outcome == "busy":
        print("repomap: CLAUDE.md is being actively edited — legacy fence left in place (retry later)")
        return 3
    if outcome == "stripped":
        print("repomap: removed the legacy REPO-MAP fence from CLAUDE.md (backup in .janitor/state)")
    return 0


def cmd_generate(root: Path, *, to_stdout: bool, excludes: list[str] | None = None) -> int:
    # CLI excludes win and are PERSISTED (so later --check / the drift detector compare
    # the same file set); absent → reuse the persisted set. Persistence is DEFERRED until
    # the map passes the size guard below: a refused run that has already rewritten the
    # exclude list leaves the next run reading the very globs that caused the refusal —
    # the refusal would corrupt the state it exists to protect.
    cli_excludes = excludes
    if excludes is None:
        excludes = load_excludes(root)
    maps = extract_all(root, excludes)
    if not maps:
        print("repomap: no supported source files found")
        return 3
    note = coverage_note(root, maps, excludes)
    generated = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    text = render_file(maps, generated_iso=generated, digest=repo_digest(root), coverage_note=note)
    # Check the cap BEFORE --stdout returns too: a caller piping the map somewhere is
    # just as capable of committing an oversized map as the write path is.
    oversize = oversize_report(text, maps, root)
    if oversize is not None:
        print(oversize)
        return 3
    if cli_excludes is not None:
        save_excludes(root, cli_excludes)
    if to_stdout:
        sys.stdout.write(text)
        return 0

    lock = _GenLock(root)
    if not lock.acquire():
        print("repomap: another generator holds the lock — skipping")
        return 3
    try:
        return _write_map(root, maps, note, text)
    finally:
        lock.release()


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate/refresh the root PROJECT_MAP.md project map")
    ap.add_argument("--root", help="project root (default: $CLAUDE_PROJECT_DIR or cwd)")
    ap.add_argument(
        "--exclude",
        action="append",
        metavar="GLOB",
        help="exclude root-relative paths matching GLOB (repeatable; persisted to the TRACKED .repomapignore so --check stays consistent)",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="freshness probe only (no write)")
    mode.add_argument("--remove", action="store_true", help="delete the generated PROJECT_MAP.md")
    mode.add_argument("--stdout", action="store_true", help="print the PROJECT_MAP.md text; touch nothing")
    args = ap.parse_args()

    root = _resolve_root(args.root)
    try:
        if args.check:
            return cmd_check(root)
        if args.remove:
            return cmd_remove(root)
        return cmd_generate(root, to_stdout=args.stdout, excludes=args.exclude)
    except MalformedFences as exc:
        print(f"repomap: refusing to touch CLAUDE.md — {exc}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
