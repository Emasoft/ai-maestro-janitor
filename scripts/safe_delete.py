#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""safe-delete — Python port of safe-delete.sh.

Recoverable alternative to `rm` for agents that can't (or shouldn't)
call destructive commands. Each invocation moves the given paths into
<project_root>/.trashcan/<timestamp>/, mirroring the original relative
layout, and writes a sibling <timestamp>.txt manifest listing the
original paths. Nothing is deleted: a misjudged disposal is one `mv`
away from recovery, on any platform.

Persistence guarantees for the .trashcan/ directory:
  The trashcan is gitignored (its contents must never leak into commits)
  but must NOT vanish on `git clean -fdx`, on a fresh clone, or any
  other 'wipe ignored files' sweep. We resolve the apparent
  contradiction by:
    a) Ignoring everything inside the directory (`/.trashcan/*`)
    b) Un-ignoring two marker files (`.gitkeep`, `README.txt`) so the
       directory itself is tracked via those markers
    c) Tracked files survive `git clean -fdx` and re-appear on clone

Refusals (always):
  - paths outside the project root (resolved canonically — symlink
    tricks don't slip past)
  - the project root itself
  - .git, .claude, .claude-plugin (critical infrastructure)
  - anything already inside .trashcan/

Exit code:
  0 — at least one path moved successfully
  1 — every path failed (e.g. all refused or all missing)
  2 — usage error
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

# state.py is optional — script runs out-of-tree without logging.
try:
    import state as _state_mod  # noqa: E402
except Exception:  # pragma: no cover - defensive
    _state_mod = None


_USAGE = """\
safe-delete — recoverable alternative to `rm`. Moves paths into
<project_root>/.trashcan/<timestamp>/ instead of deleting them, and writes a
manifest <timestamp>.txt next to it.

Usage:
  uv run --script safe_delete.py [-n|--dry-run] <path>...

Flags:
  -n, --dry-run    Print what would be moved without touching anything.
  -h, --help       Show this help.

Each invocation creates one timestamped subfolder under .trashcan/ plus an
identically-named .txt manifest file with the original paths (one per line,
project-relative, prefixed with ./). The timestamp uses local time + GMT
offset (compact ±HHMM form), collision-free at second granularity.
"""


def _log(msg: str) -> None:
    if _state_mod is not None:
        try:
            _state_mod.init_state()
            _state_mod.log_line("safe-delete", msg)
        except OSError:
            pass


def _resolve_project_root() -> Path:
    """Prefer $CLAUDE_PROJECT_DIR — same behaviour as the bash port.

    Slash commands always see the project root, but a hook running from
    a subdirectory would otherwise pin the trashcan to the wrong place.
    """
    explicit = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if explicit and Path(explicit).is_dir():
        return Path(explicit).resolve()
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return Path(proc.stdout.strip()).resolve()
    return Path.cwd().resolve()


def _canonicalize(p: Path) -> Optional[Path]:
    """Resolve a user-supplied path to absolute canonical form.

    Follows symlinks in the parent dir but NOT a symlink that IS the
    path itself (we want to trash the symlink, not its target).
    Returns None if the path does not exist.
    """
    if p.is_dir() and not p.is_symlink():
        try:
            return p.resolve(strict=True)
        except (FileNotFoundError, OSError):
            return None
    if p.exists() or p.is_symlink():
        parent = p.parent
        try:
            return parent.resolve(strict=True) / p.name
        except (FileNotFoundError, OSError):
            return None
    return None


def _safe_to_trash(path: Path, project_root: Path, trash_dir: Path) -> Optional[str]:
    """Return None when path is safe; else a refusal reason string."""
    # Strip a single trailing slash for consistent comparison.
    s = str(path).rstrip("/") or str(path)
    p = Path(s)

    if p == project_root:
        return f"refuse: {p} is the project root"

    try:
        p.relative_to(project_root)
    except ValueError:
        return f"refuse: {p} is outside the project root ({project_root})"

    blocked = [
        (project_root / ".git", ".git"),
        (project_root / ".claude", ".claude"),
        (project_root / ".claude-plugin", ".claude-plugin"),
        (trash_dir, ".trashcan/"),
    ]
    for blocked_root, label in blocked:
        try:
            p.relative_to(blocked_root)
            return f"refuse: {p} is inside {label}"
        except ValueError:
            pass

    return None


_TRASHCAN_README = """\
# .trashcan/ — project-local recoverable trash

Anything in this directory was put here by the ai-maestro-janitor's
safe-delete skill (or its `safe-delete.sh` script) instead of being
permanently deleted. Each subfolder is one disposal batch:

    .trashcan/
      20260503_181523+0200/    ← mirrored contents of trashed paths
      20260503_181523+0200.txt ← manifest, one original path per line

To restore a batch (any platform):

    # Whole batch — overwrites if names collide at the destination:
    cp -R .trashcan/<timestamp>/. ./

    # Selective, manifest-driven:
    while IFS= read -r p; do
      [ -z "$p" ] || [ "${p#\\#}" != "$p" ] && continue
      mv ".trashcan/<timestamp>/${p#./}" "$p"
    done < ".trashcan/<timestamp>.txt"

To purge a batch permanently:

    rm -rf .trashcan/<timestamp>/ .trashcan/<timestamp>.txt

DO NOT delete this directory itself. It is gitignored (so trash never
leaks into commits) but the directory must persist across `git clean -fdx`
sweeps and fresh clones. We achieve that by tracking two marker files
(.gitkeep and README.txt) — they are excluded from .gitignore so git keeps
them under version control, which in turn keeps the directory alive.

The first time safe-delete creates these markers, run:

    git add .trashcan/.gitkeep .trashcan/README.txt
    git commit -m "track .trashcan markers so the trashcan survives clones"

After that, the trashcan is permanent project infrastructure.
"""


def _ensure_gitignore_and_markers(
    project_root: Path,
    trash_dir: Path,
    gitkeep: Path,
    readme: Path,
) -> bool:
    """Make .trashcan/ both gitignored AND survivable via two tracked markers.

    Returns True if any rule or marker had to be created on this call,
    so the caller can print the one-time 'git add' hint. Mirrors the
    NEW_MARKERS=1 sentinel from the bash port.
    """
    new_markers = False
    gitignore = project_root / ".gitignore"
    rules = [
        "/.trashcan/*",
        "!/.trashcan/.gitkeep",
        "!/.trashcan/README.txt",
    ]

    existing_lines: list[str] = []
    if gitignore.is_file():
        try:
            existing_lines = gitignore.read_text().splitlines()
        except OSError:
            existing_lines = []

    for rule in rules:
        if rule in existing_lines:
            continue
        # Ensure the file ends with a newline before appending — a file
        # without a trailing newline would otherwise glue the rule to
        # the previous line.
        try:
            if gitignore.is_file() and gitignore.stat().st_size > 0:
                with gitignore.open("rb") as f:
                    f.seek(-1, 2)
                    last = f.read(1)
                if last not in (b"\n", b""):
                    with gitignore.open("a", encoding="utf-8") as f:
                        f.write("\n")
            with gitignore.open("a", encoding="utf-8") as f:
                f.write(rule + "\n")
            existing_lines.append(rule)
            _log(f"added '{rule}' to .gitignore")
            new_markers = True
        except OSError as exc:
            print(f"warn: could not update {gitignore}: {exc}", file=sys.stderr)

    if not gitkeep.is_file():
        gitkeep.touch()
        new_markers = True
    if not readme.is_file():
        readme.write_text(_TRASHCAN_README, encoding="utf-8")
        new_markers = True

    return new_markers


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("-n", "--dry-run", action="store_true", dest="dry_run")
    parser.add_argument("-h", "--help", action="store_true", dest="help")
    parser.add_argument("paths", nargs="*")
    args = parser.parse_args()

    if args.help:
        print(_USAGE)
        return 2
    if not args.paths:
        print(_USAGE, file=sys.stderr)
        return 2

    project_root = _resolve_project_root()
    trash_dir = project_root / ".trashcan"
    gitkeep = trash_dir / ".gitkeep"
    readme = trash_dir / "README.txt"

    # Local time + GMT offset, compact ±HHMM (filesystem-safe).
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S%z")
    dest = trash_dir / timestamp
    manifest = trash_dir / f"{timestamp}.txt"

    moved = 0
    failed = 0
    moved_lines: list[str] = []
    manifest_lines: list[str] = []
    trash_dir_created = False
    new_markers = False

    for arg in args.paths:
        p = Path(arg)
        abs_p = _canonicalize(p)
        if abs_p is None:
            print(f"skip: {arg} (does not exist)", file=sys.stderr)
            failed += 1
            continue

        reason = _safe_to_trash(abs_p, project_root, trash_dir)
        if reason is not None:
            print(reason, file=sys.stderr)
            failed += 1
            continue

        rel = abs_p.relative_to(project_root)
        target = dest / rel

        if args.dry_run:
            moved_lines.append(f"[dry-run] would move {rel} -> .trashcan/{timestamp}/{rel}")
            moved += 1
            continue

        # Lazily create destination + ensure markers, so an all-failed
        # batch leaves no empty timestamp dir behind. We still want the
        # markers + the gitignore rules to land on the very first
        # success — but only if this batch actually moves at least one
        # item.
        if not trash_dir_created:
            dest.mkdir(parents=True, exist_ok=True)
            new_markers = _ensure_gitignore_and_markers(project_root, trash_dir, gitkeep, readme)
            trash_dir_created = True

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(abs_p), str(target))
        except OSError as exc:
            print(f"failed: could not move {abs_p}: {exc}", file=sys.stderr)
            failed += 1
            continue
        moved_lines.append(f"{rel} -> .trashcan/{timestamp}/{rel}")
        manifest_lines.append(f"./{rel}")
        moved += 1
        _log(f"trashed {rel}")

    # Manifest. Written once after the loop so a partial failure still
    # leaves a coherent manifest covering exactly what landed in the
    # subfolder. Header doc-lines start with `#` so manifest-driven
    # restore loops can skip them.
    if not args.dry_run and moved > 0:
        body = [
            f"# safe-delete manifest — batch {timestamp}",
            "# format: one project-relative path per line (./prefix), one entry per trashed item",
            f"# stored under: .trashcan/{timestamp}/",
            *manifest_lines,
        ]
        tmp = manifest.with_suffix(manifest.suffix + f".tmp.{os.getpid()}")
        tmp.write_text("\n".join(body) + "\n", encoding="utf-8")
        os.replace(tmp, manifest)

    if moved > 0:
        if args.dry_run:
            print(f"[safe-delete] dry-run: {moved} item(s) would move into .trashcan/{timestamp}/:")
        else:
            print(f"[safe-delete] Trashed {moved} item(s) into .trashcan/{timestamp}/:")
        for line in moved_lines:
            print(f"  {line}")
        if not args.dry_run:
            print()
            print("Manifest:")
            print(f"  .trashcan/{timestamp}.txt")
            print("Restore (whole batch — overwrites if names collide):")
            print(f"  cp -R {shlex.quote(str(dest))}/. {shlex.quote(str(project_root))}")
            print("Restore (manifest-driven, selective):")
            print(
                f'  while IFS= read -r p; do [ -z "$p" ] || [ "${{p#\\#}}" != "$p" ] && continue; '
                f'mv ".trashcan/{timestamp}/${{p#./}}" "$p"; done < .trashcan/{timestamp}.txt'
            )
            print("Purge permanently:")
            print(f"  rm -rf {shlex.quote(str(dest))} {shlex.quote(str(manifest))}")
            if new_markers:
                print()
                print("NOTE: first-time setup of .trashcan/ — commit the markers so the")
                print("directory survives `git clean -fdx` and fresh clones:")
                print("  git add .gitignore .trashcan/.gitkeep .trashcan/README.txt")
                print('  git commit -m "track .trashcan markers"')

    if failed > 0 and moved == 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
