#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""gitignore-fix — the remedy path for `gitignore-coverage` findings. D5 of TRDD-6WM4BFKF.

Read-only by default: prints the proposed `.gitignore` diff (missing canonical patterns
appended at the end, nothing reordered, no negation line touched) plus the exact
`git rm --cached <path>` lines for tracked private files. `--apply` writes ONLY the
`.gitignore` append; it never runs `git rm` — untracking is the caller's decision, made
after reading the printed command, never this script's.

ONE source of truth: `scripts/lib/gitignore_coverage.py` owns the private-class table and
the protected-prefix allowlist (`design/**`, `.claude/project/memory/**`). This script adds
no second pattern list — it only decides WHAT git says is (un)covered, via `git check-ignore`,
same as the `gitignore-coverage` detector.

Exit code: 0 whenever git answered (a report, not a gate — "nothing to do" is 0 too);
1 when git itself failed (the answer is UNKNOWN, so nothing is proposed and nothing is
written); 2 on wrong usage.
"""
from __future__ import annotations

import argparse
import difflib
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import gitignore_coverage as gc  # noqa: E402


def _repo_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    git_env = dict(os.environ)
    git_env["GIT_OPTIONAL_LOCKS"] = "0"  # read-only call — never contend for .git/index.lock (janitor#245)
    proc = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=False, env=git_env,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        print("error: not inside a git repo (pass --repo <path>)", file=sys.stderr)
        sys.exit(2)
    return Path(proc.stdout.strip()).resolve()


def _check_ignore_verdicts(root: Path, paths: list[str]) -> dict[str, str]:
    """Git's own verdict per path: {path: "ignored" | "negated" | "unmatched"}.

    Same `-v -n -z --no-index --stdin` shape as the `gitignore-coverage` detector, so this
    tool and the finding it remedies never disagree about what "covered" means.
    """
    if not paths:
        return {}
    git_env = dict(os.environ)
    git_env["GIT_OPTIONAL_LOCKS"] = "0"  # read-only call — never contend for .git/index.lock (janitor#245)
    proc = subprocess.run(
        ["git", "-C", str(root), "check-ignore", "-v", "-n", "-z", "--no-index", "--stdin"],
        capture_output=True, text=True, check=False, input="\0".join(paths) + "\0", env=git_env,
    )
    if proc.returncode not in (0, 1):
        # Fail fast: an empty verdict map would read as "nothing is ignored", and with
        # --apply that appends EVERY class pattern on a git error. Exit 1 means "the answer
        # is unknown", never "the answer is none" — a report can be wrong silently, a write
        # cannot.
        sys.exit(f"error: git check-ignore failed (rc={proc.returncode}): {proc.stderr.strip()}")
    fields = proc.stdout.split("\0")
    verdicts: dict[str, str] = {}
    for i in range(0, len(fields) - 3, 4):
        pattern, path = fields[i + 2], fields[i + 3]
        verdicts[path] = (
            "negated" if pattern.startswith("!") else "ignored" if pattern else "unmatched"
        )
    return verdicts


def _tracked_files(root: Path) -> list[str]:
    git_env = dict(os.environ)
    git_env["GIT_OPTIONAL_LOCKS"] = "0"  # read-only call — never contend for .git/index.lock (janitor#245)
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True, text=True, check=False, env=git_env,
    )
    if proc.returncode != 0:
        # Same reason as _check_ignore_verdicts: an empty tracked list hides every
        # contamination offender behind a git error. Unknown is not "none".
        sys.exit(f"error: git ls-files failed (rc={proc.returncode}): {proc.stderr.strip()}")
    return [p for p in proc.stdout.split("\0") if p]


def main() -> int:
    parser = argparse.ArgumentParser(add_help=True)
    parser.add_argument("--repo", default=None, help="repo root (default: cwd's git root)")
    parser.add_argument("--apply", action="store_true", help="append the missing patterns")
    args = parser.parse_args()

    root = _repo_root(args.repo)
    tracked = _tracked_files(root)
    probes = [c.probe for c in gc.PRIVATE_CLASSES]
    verdicts = _check_ignore_verdicts(root, probes + tracked)

    uncovered = gc.uncovered_classes(lambda p: verdicts.get(p) == "ignored")
    offenders = gc.tracked_offenders(tracked, lambda p: verdicts.get(p) == "negated")

    gitignore = root / ".gitignore"
    # newline="" on BOTH the read and the write: universal-newline mode would silently turn
    # CRLF into LF on read, and the append would then rewrite every existing line ending.
    current_text = (
        gitignore.open(encoding="utf-8", newline="").read() if gitignore.is_file() else ""
    )
    new_patterns = [c.pattern for c in uncovered]
    # APPEND, never re-join: the existing bytes are kept verbatim (CRLF endings, a missing
    # final newline, trailing blank lines — all as found), and the new lines go after them.
    # Splitting into lines and re-joining would "normalise" the file and break the card's
    # byte-identical guarantee for everything the user already had.
    separator = "" if not current_text or current_text.endswith("\n") else "\n"
    proposed_text = current_text + separator + "".join(p + "\n" for p in new_patterns)

    if not new_patterns and not offenders:
        print("[gitignore-fix] up to date — no missing coverage, no tracked private files.")
        return 0

    if new_patterns:
        diff = difflib.unified_diff(
            current_text.splitlines(keepends=True),
            proposed_text.splitlines(keepends=True),
            fromfile=".gitignore",
            tofile=".gitignore (proposed)",
            lineterm="",
        )
        print("".join(diff))
    else:
        print("[gitignore-fix] .gitignore already covers every private class.")

    if offenders:
        print()
        print("[gitignore-fix] tracked private files — a rule does not untrack them:")
        for path in offenders:
            print(f"  git rm --cached {path}")

    if args.apply:
        if not new_patterns:
            print("\n[gitignore-fix] --apply: nothing to append.")
            return 0
        tmp = gitignore.with_suffix(gitignore.suffix + f".tmp.{os.getpid()}")
        tmp.write_text(proposed_text, encoding="utf-8", newline="")
        os.replace(tmp, gitignore)
        print(f"\n[gitignore-fix] appended {len(new_patterns)} pattern(s) to .gitignore.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
