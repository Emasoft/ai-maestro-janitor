#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""repomap_generate — generate/refresh the fenced project map in CLAUDE.md.

The user-facing entry point of the auto-maintained project map
(TRDD-e247a349). Drives the tested `lib/repomap` package (extractor +
renderer + markers) end-to-end:

  uv run scripts/repomap_generate.py [--root DIR]      # insert-or-refresh the map
  uv run scripts/repomap_generate.py --check           # freshness probe (no write)
  uv run scripts/repomap_generate.py --remove          # splice the block out
  uv run scripts/repomap_generate.py --stdout          # print block, touch nothing

Exit codes: 0 = fresh / written / removed; 1 = --check found the map STALE
(structure changed); 2 = --check found NO map block; 3 = error (malformed
fences, no CLAUDE.md on --check/--remove, lock held, splice gave up).

CONCURRENCY / ANTI-CORRUPTION CONTRACT (the load-bearing part — CLAUDE.md is
co-owned by the human and the session's Claude; the janitor must NEVER corrupt
or silently discard their edits):

  1. WRITER LOCK — a project-scoped flock (`.janitor/state/repomap.lock`)
     serializes generator instances across sessions. Non-blocking: a second
     instance SKIPS (exit 3) instead of queueing, so two heartbeat-armed
     sessions can never interleave writes.
  2. LOST-UPDATE GUARD — extraction (slow, seconds) happens BEFORE the write
     section. The write itself is a tight read → splice → re-stat → replace
     loop: the file's (mtime_ns, size) signature is captured WITH the read,
     and `os.replace` only fires if the signature is UNCHANGED at the last
     instant. If Claude/the human wrote CLAUDE.md in between, we re-read and
     re-splice against THEIR text (their edit is preserved; only the fenced
     block changes). Bounded retries, then give up safely (exit 3) — never
     last-writer-wins over a human edit.
  3. BYTE-PRESERVATION INVARIANT — before every replace, the candidate text is
     verified to (a) contain EXACTLY one START and one END fence in order, and
     (b) be byte-identical to the just-read text outside the fenced span. Any
     violation aborts the write. This is belt-and-suspenders over markers.py's
     construction guarantees: even a future logic bug cannot eat narrative.
  4. ROLLING BACKUP — the pre-write CLAUDE.md is copied to
     `.janitor/state/CLAUDE.md.pre-repomap.bak` before the first replace of a
     run, so a bad write is one `cp` away from undone (RULE-0 spirit).
  5. ATOMIC REPLACE — tmp file in the SAME directory + `os.replace`: readers
     (including a mid-turn Claude) see the old or the new file, never a torn
     one.
  6. NEVER FROM THE HEARTBEAT — but for CO-OWNERSHIP, not for cache cost.
     CLAUDE.md is co-owned by the human and the session's Claude, and a
     background writer racing their edits is the corruption class this guard
     exists for. The `project-map-drift` detector only NUDGES; a human/agent
     runs this script, and may run it AT ANY TIME.

     The old text here also claimed a mid-session rewrite "busts the context
     cache (TRDD-e247a349 §5)", and told the reader to wait for a cache-cheap
     moment. MEASURED FALSE 2026-08-26 (TRDD-LFSWY0C6): across 307 turns that
     immediately followed a CLAUDE.md Edit/Write, max cache_creation was
     65,923 tokens and the median 1,525 — versus 598,351 max across the other
     108,303 turns. The catastrophic rewrite is real but never follows a
     CLAUDE.md edit. Kept as a correction rather than deleted, because the
     false claim is what made agents defer the refresh for days.

Freshness is two-tier, cheapest first: the repo-change `digest=` (git HEAD +
porcelain-status hash) is compared BEFORE any extraction; only a digest
mismatch pays for extraction, and a `sha=` (structure-hash) match after
extraction still skips the write — a comment-only edit changes the digest but
not the structure, and must not churn CLAUDE.md (AC2).

File discovery is `git ls-files` scoped to the extractor REGISTRY's extensions
(today just `*.py`; adding a language is one registry entry, see EXTRACTORS in
lib/repomap/extractor.py) — tracked files only, so .gitignore'd trees
(reports/, *_dev/, .venv) can never leak into the map. Outside a git repo it
falls back to a bounded rglob with the same exclusions.

Only a Python extractor exists today. On a repo whose tracked source is
overwhelmingly another language, the rendered block carries an explicit
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
from typing import TextIO

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

from repomap import (  # noqa: E402
    EXTRACTORS,
    FileMap,
    MalformedFences,
    has_map_block,
    insert_map_block,
    read_fence_header,
    remove_map_block,
    render_block,
    replace_map_block,
    structure_hash,
)
from repomap.markers import _fence_span  # noqa: E402  (invariant check needs the span)

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

# Lost-update guard: how many read→splice→verify→replace attempts before the
# generator gives up (someone is actively editing CLAUDE.md — let them win).
_SPLICE_ATTEMPTS = 5

# Settle delay for the splice retry loop. Sized to comfortably outlast a writer's
# truncate-to-write window (sub-millisecond for the read-modify-write an editor
# does), while staying far below any cadence this generator runs on. It is what
# makes a torn read DETECTABLE — see the long note in splice_with_verify.
_SPLICE_SETTLE_S = 0.05


def _resolve_root(arg: str | None) -> Path:
    if arg:
        return Path(arg).resolve()
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env).resolve()
    return Path.cwd().resolve()


def _git(root: Path, *args: str) -> str | None:
    """Run a git command in `root`; None on any failure (non-repo, no git).

    Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock and
    collides with a concurrent `publish.py` commit (janitor#245).
    """
    try:
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        res = subprocess.run(
            ["git", *args],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            env=git_env,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return res.stdout if res.returncode == 0 else None


def _excludes_file(root: Path) -> Path:
    """The exclude list — a TRACKED root dotfile, matching the `.tldrignore` precedent.

    It MUST be tracked. The map it governs is spliced into CLAUDE.md, which is committed
    AND injected into every turn of every session, so the committed file's content cannot
    be allowed to depend on machine-local state. It previously lived in
    `.janitor/state/`, which is gitignored and purgeable: on 2026-07-26 that list was
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
        "# Exclude globs for the CLAUDE.md project map (scripts/repomap_generate.py).\n# TRACKED on purpose: the map is committed and rides every turn's context, so\n# what it contains must not depend on machine-local state. See _excludes_file().\n" + "".join(g + "\n" for g in globs),
        encoding="utf-8",
    )


# Absolute ceiling on the spliced map block. This is the backstop that does NOT depend on
# knowing the cause: the excludes file is one way the map can balloon, but any future
# change (a new tracked language, a vendored tree, a bad glob) is another, and the failure
# mode is identical and silent — CLAUDE.md is committed and re-read on every turn of every
# session, so a 4x map is a permanent 4x tax nobody notices until the bill arrives. The
# current map is ~130KB; 256KB leaves real headroom while still catching a balloon.
MAX_BLOCK_BYTES_ENV = "CLAUDE_PLUGIN_OPTION_REPOMAP_MAX_BLOCK_BYTES"
_MAX_BLOCK_BYTES_DEFAULT = 256 * 1024


def max_block_bytes() -> int:
    raw = os.environ.get(MAX_BLOCK_BYTES_ENV, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _MAX_BLOCK_BYTES_DEFAULT
    return value if value > 0 else _MAX_BLOCK_BYTES_DEFAULT


def oversize_report(block: str, maps: list[FileMap], root: Path) -> str | None:
    """None when the block fits; otherwise a message naming the top directories.

    Naming the contributors is the difference between an error someone can act on and one
    they work around with --force.
    """
    cap = max_block_bytes()
    size = len(block.encode("utf-8"))
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
        f"repomap: REFUSING to write — the map block is {size // 1024}KB, over the "
        f"{cap // 1024}KB cap, and CLAUDE.md is injected into every turn of every session.\n"
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

    CLAUDE.md itself and `.janitor/` are EXCLUDED from the porcelain hash —
    the map tracks SOURCE structure, and writing the map dirties CLAUDE.md;
    without the exclusion every generate would change the very digest it just
    recorded and instantly report itself stale (a perpetual nudge loop,
    caught by test_detector_nudges_only_when_opted_in_and_stale)."""
    head = _git(root, "rev-parse", "HEAD")
    if head is not None:
        status = _git(root, "status", "--porcelain") or ""
        kept = [ln for ln in status.splitlines() if ln[3:] not in ("CLAUDE.md",) and not ln[3:].startswith(".janitor/")]
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


def _verified_candidate(current: str, block: str) -> str:
    """Splice `block` into `current` and PROVE the result is safe to write:
    exactly one fence pair, and the narrative byte-identical to `current`'s.
    Raises MalformedFences on any violation (caller aborts the write)."""
    candidate = replace_map_block(current, block) if has_map_block(current) else insert_map_block(current, block)
    if candidate.count("<+-+-JANITOR-REPO-MAP-START-") != 1 or candidate.count("<+-+-JANITOR-REPO-MAP-END-") != 1:
        raise MalformedFences("candidate does not contain exactly one fence pair")
    # The insert path adds separator newlines to the narrative's tail; compare
    # modulo trailing whitespace, byte-strict everywhere else.
    if _outside_fences(candidate).rstrip("\n") != _outside_fences(current).rstrip("\n"):
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


def splice_with_verify(claude_md: Path, block: str, attempts: int = _SPLICE_ATTEMPTS) -> bool:
    """The anti-corruption write: read+signature → splice+invariant-verify →
    re-stat → replace ONLY if untouched since the read. A concurrent edit (by
    the session's Claude or the human) triggers a re-read and re-splice
    against THEIR latest text — their narrative always survives; only the
    fenced block is replaced. Returns False after `attempts` collisions (an
    active editor wins; the generator retires gracefully)."""
    for attempt in range(attempts):
        if attempt:
            # Back off between attempts. Without this the retries spin instantly
            # and ALL of them can land inside the SAME writer's truncate window,
            # so the collision check re-samples an identical torn state every
            # time and "3 attempts" buys no independence at all.
            time.sleep(_SPLICE_SETTLE_S)
        sig_before = _stat_sig(claude_md)
        current = claude_md.read_text(encoding="utf-8") if sig_before is not None else ""
        if sig_before is not None and not current.strip():
            # TORN READ. `Path.write_text` — what Claude's Edit tool and most
            # editors do — truncates first and writes after, so a read landing in
            # that window sees 0 bytes. The stat signature is STABLE across it
            # (the writer has not written yet), so the check below cannot catch
            # it, and splicing this would persist a block-only CLAUDE.md,
            # DESTROYING the human narrative the fences exist to protect. The
            # writer then loses its own write too: our atomic rename swaps the
            # inode under its open fd.
            #
            # A truncate window is sub-millisecond, so sleeping past it and
            # re-reading distinguishes torn from genuinely-empty EMPIRICALLY
            # instead of by assumption — and it makes the race observable to the
            # stat check below, which then does its job. A file that is still
            # empty after settling really is empty, and splicing it destroys
            # nothing, so we fall through rather than refuse (an empty CLAUDE.md
            # must still be able to receive its first map).
            time.sleep(_SPLICE_SETTLE_S)
            current = claude_md.read_text(encoding="utf-8")
        candidate = _verified_candidate(current, block)
        if _stat_sig(claude_md) != sig_before:
            continue  # changed while we spliced (ms window) — re-read their text
        _atomic_replace(claude_md, candidate)
        return True
    return False


def cmd_check(root: Path) -> int:
    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file():
        print("repomap: no CLAUDE.md")
        return 3
    text = claude_md.read_text(encoding="utf-8")
    header = read_fence_header(text)
    if header is None:
        print("repomap: no map block (run repomap_generate.py to insert one)")
        return 2
    if header.get("digest") == repo_digest(root):
        print("repomap: fresh (digest match)")
        return 0
    # Digest moved — only now pay for extraction (with the SAME persisted
    # excludes the map was generated with); a structure match still counts as
    # fresh (comment-only change), but report it distinctly.
    excludes = load_excludes(root)
    maps = extract_all(root, excludes)
    sha = structure_hash(maps, coverage_note=coverage_note(root, maps, excludes))
    if header.get("sha") == sha:
        print("repomap: structure unchanged (digest moved; refresh optional)")
        return 0
    print("repomap: STALE — structure changed; refresh with repomap_generate.py")
    return 1


def cmd_remove(root: Path) -> int:
    claude_md = root / "CLAUDE.md"
    if not claude_md.is_file():
        print("repomap: no CLAUDE.md")
        return 3
    lock = _GenLock(root)
    if not lock.acquire():
        print("repomap: another generator holds the lock — skipping")
        return 3
    try:
        text = claude_md.read_text(encoding="utf-8")
        if not has_map_block(text):
            print("repomap: no map block to remove")
            return 0
        _backup(claude_md)
        _atomic_replace(claude_md, remove_map_block(text))
        print("repomap: map block removed (narrative untouched)")
        return 0
    finally:
        lock.release()


def cmd_generate(root: Path, *, to_stdout: bool, excludes: list[str] | None = None) -> int:
    # CLI excludes win and are PERSISTED (so later --check / the drift detector compare
    # the same file set); absent → reuse the persisted set. Persistence is DEFERRED until
    # the block passes the size guard below: a refused run that has already rewritten the
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
    block = render_block(maps, generated_iso=generated, digest=repo_digest(root), coverage_note=note)
    # Check the cap BEFORE --stdout returns too: a caller piping the block somewhere is
    # just as capable of committing an oversized map as the splice path is.
    oversize = oversize_report(block, maps, root)
    if oversize is not None:
        print(oversize)
        return 3
    if cli_excludes is not None:
        save_excludes(root, cli_excludes)
    if to_stdout:
        sys.stdout.write(block)
        return 0

    claude_md = root / "CLAUDE.md"
    lock = _GenLock(root)
    if not lock.acquire():
        print("repomap: another generator holds the lock — skipping")
        return 3
    try:
        text = claude_md.read_text(encoding="utf-8") if claude_md.is_file() else ""
        header = read_fence_header(text)
        if header is not None and header.get("sha") == structure_hash(maps, coverage_note=note):
            print("repomap: already current (structure hash match) — no write")
            return 0
        _backup(claude_md)
        if not splice_with_verify(claude_md, block):
            print("repomap: CLAUDE.md is being actively edited — giving up safely (retry later)")
            return 3
        n_lines = block.count("\n")
        print(f"repomap: wrote {n_lines}-line map block into {claude_md} ({len(maps)} files)")
        return 0
    finally:
        lock.release()


def main() -> int:
    ap = argparse.ArgumentParser(description="Generate/refresh the fenced CLAUDE.md project map")
    ap.add_argument("--root", help="project root (default: $CLAUDE_PROJECT_DIR or cwd)")
    ap.add_argument(
        "--exclude",
        action="append",
        metavar="GLOB",
        help="exclude root-relative paths matching GLOB (repeatable; persisted to the TRACKED .repomapignore so --check stays consistent)",
    )
    mode = ap.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="freshness probe only (no write)")
    mode.add_argument("--remove", action="store_true", help="splice the map block out")
    mode.add_argument("--stdout", action="store_true", help="print the block; touch nothing")
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
