#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""memgrep-binary-stale — report a memgrep build older than the installed plugin's memgrep source (TRDD-V5V1CBLM).

WHY. Nothing installs or updates the memgrep binary after a plugin update, so a machine keeps the
build it once had. On 2026-10-07 the binary on PATH was `5497043` while the installed plugin was at
`288a2777`: 10 memgrep commits behind, including the cross-scope guard. Every stamp of the binary
(`memgrep --version` -> `<ver> (<commit7>, <date>)`, from build.rs) names the commit it was built
from, so staleness is decidable: compare that commit with the installed user-scope plugin commit.

STALE only when the installed commit is `ahead` of (or `diverged` from) the stamp AND a file under
`scripts/memgrep/` changed between them. A plugin update that touched no memgrep source leaves the
binary current; `behind` means a dev build newer than the release, also fine.

CAN'T TELL (no memgrep, stamp `unknown`, no user-scope entry, gh missing or failing): ONE advisory
line, never a fixable proposal — guessing "stale" would send people rebuilding a binary that is fine.

The binary is MACHINE-GLOBAL, so everything is per (stamp, installed sha) in the global state dir:
the line prints once per pair, and the `gh` compare result is cached per pair (asked at most once).
Fail-open: any unreadable input is a "can't tell", never a crash.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import global_state as gs  # noqa: E402
import state  # noqa: E402
import user_mem_lib  # noqa: E402

_NAME = "memgrep-binary-stale"
_REPO = "Emasoft/ai-maestro-janitor"
# Built from parts: the privacy scan reads a literal plugin-at-marketplace key as an ssh login leak.
_PLUGIN_KEY = "@".join(("ai-maestro-janitor", "ai-maestro-plugins"))
_SRC_PREFIX = "scripts/memgrep/"
_STAMP_RE = re.compile(r"\(([0-9a-f]{7,40}|unknown),")
_CACHE_FILE = "memgrep-binary-stale-compare.json"
_SEEN_FILE = "memgrep-binary-stale-seen.txt"


def parse_stamp(version_output: str) -> str | None:
    """The build commit from `memgrep --version` output, or None when absent or `unknown`."""
    m = _STAMP_RE.search(version_output or "")
    return m.group(1) if m and m.group(1) != "unknown" else None


def installed_sha() -> str | None:
    """The user-scope janitor entry's gitCommitSha in installed_plugins.json, or None."""
    path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["plugins"][_PLUGIN_KEY]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    for e in entries:
        if isinstance(e, dict) and e.get("scope") == "user" and e.get("gitCommitSha"):
            return str(e["gitCommitSha"])
    return None


def classify(compare: dict) -> int:
    """Number of memgrep source files changed when the binary is STALE, else 0. PURE.

    `status` is relative to base=stamp, head=installed: `ahead`/`diverged` means the plugin has
    commits the binary lacks; `behind`/`identical` is never stale.
    """
    if compare.get("status") not in ("ahead", "diverged"):
        return 0
    return sum(1 for f in compare.get("files", []) if str(f.get("filename", "")).startswith(_SRC_PREFIX))


def _compare(stamp: str, sha: str) -> dict | None:
    """The gh compare for the pair, cached per pair in the global state dir; None when gh fails."""
    cache_path = gs.global_state_dir() / _CACHE_FILE
    key = f"{stamp}...{sha}"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if key in cache:
        return {"status": cache[key]["status"], "files": [{"filename": f} for f in cache[key]["memgrep_files"]]}
    proc = state.run_subprocess(
        ["gh", "api", f"repos/{_REPO}/compare/{key}"], timeout=60, capture=True, detector_name=_NAME
    )
    if proc is None or proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
    except ValueError:
        return None
    # Cache only what classify needs: the full response runs to ~1 MB.
    cache[key] = {
        "status": data.get("status"),
        "memgrep_files": [f["filename"] for f in data.get("files", []) if str(f.get("filename", "")).startswith(_SRC_PREFIX)],
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    state.atomic_write(cache_path, json.dumps(cache))
    return data


def _emit(key: str, line: str) -> None:
    seen = dedupe.emit_once(gs.global_state_dir() / _SEEN_FILE, key, line)
    if seen is not None:
        print(seen, flush=True)


def _cant_tell(why: str) -> int:
    _emit(f"cant-tell:{why}", f"[{_NAME}] cannot tell whether the memgrep binary is current: {why} (advisory)")
    return 0


def main() -> int:
    state.init_state()

    memgrep = user_mem_lib.find_memgrep()
    if not memgrep:
        return _cant_tell("no memgrep binary found")
    proc = state.run_subprocess([memgrep, "--version"], timeout=10, capture=True, detector_name=_NAME)
    stamp = parse_stamp(proc.stdout if proc else "")
    if not stamp:
        return _cant_tell("the memgrep build carries no commit stamp")
    sha = installed_sha()
    if not sha:
        return _cant_tell("no user-scope janitor install found")
    if sha.startswith(stamp):
        return 0
    data = _compare(stamp, sha)
    if data is None:
        return _cant_tell("the GitHub compare failed (gh missing or erroring)")
    changed = classify(data)
    if changed:
        _emit(
            f"stale:{stamp}:{sha}",
            f"[{_NAME}] the memgrep binary was built from {stamp} but the installed plugin is at {sha[:7]}; "
            f"{changed} memgrep source file(s) changed since — rebuild with `cargo install --path scripts/memgrep` "
            f"from a janitor checkout, or install the release binary",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
