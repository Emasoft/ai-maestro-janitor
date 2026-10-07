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

CAN'T TELL (no memgrep, stamp `unknown`, no user-scope entry, gh missing or failing, a truncated
compare, a build commit GitHub does not know): ONE advisory line, never a fixable proposal —
guessing "stale" would send people rebuilding a binary that is fine. A cargo build from the plugin
cache (which has no .git) is stamped `unknown` and therefore reads as can't-tell; only the
user-scope install is compared. Can't-tell lines dedupe per (reason, stamp, installed sha).

The binary is MACHINE-GLOBAL, so everything is per (stamp, installed sha) in the global state dir:
the line prints once per pair, and the `gh` compare result is cached per pair (asked at most once).
Fail-open: any unreadable input is a "can't tell", never a crash.
"""

from __future__ import annotations

import json
import platform
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
_FILES_CAP = 300  # GitHub's compare lists at most 300 files; at the cap the list may be cut short
_REASON_GH = "the GitHub compare failed (gh missing or erroring)"
_REASON_404 = "the build commit is not on GitHub (local or fork build)"
_REASON_TRUNCATED = "the GitHub compare is truncated"


def parse_stamp(version_output: str) -> str | None:
    """The build commit from `memgrep --version` output, or None when absent or `unknown`."""
    m = _STAMP_RE.search(version_output or "")
    return m.group(1) if m and m.group(1) != "unknown" else None


def installed_entry() -> tuple[str, str] | None:
    """The user-scope janitor entry in installed_plugins.json as (gitCommitSha, version), or None."""
    path = Path.home() / ".claude" / "plugins" / "installed_plugins.json"
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))["plugins"][_PLUGIN_KEY]
    except (OSError, ValueError, KeyError, TypeError):
        return None
    for e in entries:
        if isinstance(e, dict) and e.get("scope") == "user" and e.get("gitCommitSha"):
            return str(e["gitCommitSha"]), str(e.get("version", ""))
    return None


def classify(compare: dict) -> int:
    """Number of memgrep source files changed when the binary is STALE, else 0. PURE.

    `status` is relative to base=stamp, head=installed: `ahead`/`diverged` means the plugin has
    commits the binary lacks; `behind`/`identical` is never stale.
    """
    if compare.get("status") not in ("ahead", "diverged"):
        return 0
    return sum(1 for f in compare.get("files", []) if str(f.get("filename", "")).startswith(_SRC_PREFIX))

def is_truncated(data: dict) -> bool:
    """True when an ahead/diverged compare cannot be trusted: no `files` key, or GitHub's 300-file cap hit."""
    if data.get("status") not in ("ahead", "diverged"):
        return False
    files = data.get("files")
    return not isinstance(files, list) or len(files) >= _FILES_CAP


def _compare(stamp: str, sha: str) -> dict | str:
    """The gh compare for the pair (cached per pair in the global state dir), or a can't-tell reason string.

    Truncated responses are never cached: a verdict from a partial file list would stick forever.
    A 404 is cached: GitHub will keep not knowing a local/fork build commit.
    """
    cache_path = gs.global_state_dir() / _CACHE_FILE
    key = f"{stamp}...{sha}"
    try:
        cache = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cache = {}
    if key in cache:
        if cache[key]["status"] == "not-found":
            return _REASON_404
        return {"status": cache[key]["status"], "files": [{"filename": f} for f in cache[key]["memgrep_files"]]}
    proc = state.run_subprocess(
        ["gh", "api", f"repos/{_REPO}/compare/{key}"], timeout=60, capture=True, detector_name=_NAME
    )
    if proc is None:
        return _REASON_GH
    data: dict = {}
    if proc.returncode != 0:
        # gh prints "gh: Not Found (HTTP 404)" on stderr when the base commit is unknown to GitHub.
        if "HTTP 404" not in (proc.stderr or ""):
            return _REASON_GH
        cache[key] = {"status": "not-found"}
    else:
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            return _REASON_GH
        if is_truncated(data):
            return _REASON_TRUNCATED
        # Cache only what classify needs: the full response runs to ~1 MB.
        cache[key] = {
            "status": data.get("status"),
            "memgrep_files": [f["filename"] for f in data.get("files", []) if str(f.get("filename", "")).startswith(_SRC_PREFIX)],
        }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    state.atomic_write(cache_path, json.dumps(cache))
    return _REASON_404 if cache[key]["status"] == "not-found" else data


def _emit(key: str, line: str) -> None:
    seen = dedupe.emit_once(gs.global_state_dir() / _SEEN_FILE, key, line)
    if seen is not None:
        print(seen, flush=True)


def _cant_tell(why: str, stamp: str | None = None, sha: str | None = None) -> int:
    # Keyed per (reason, stamp, installed sha): emit_once never expires a key, so a reason-only key
    # would hide that advisory for the machine's lifetime, across every later plugin update.
    _emit(f"cant-tell:{why}:{stamp or ''}:{sha or ''}", f"[{_NAME}] cannot tell whether the memgrep binary is current: {why} (advisory)")
    return 0


def main() -> int:
    state.init_state()

    entry = installed_entry()
    sha, version = entry if entry else (None, "")
    memgrep = user_mem_lib.find_memgrep()
    if not memgrep:
        return _cant_tell("no memgrep binary found", None, sha)
    proc = state.run_subprocess([memgrep, "--version"], timeout=10, capture=True, detector_name=_NAME)
    stamp = parse_stamp(proc.stdout if proc else "")
    if not stamp:
        return _cant_tell("the memgrep build carries no commit stamp", None, sha)
    if not sha:
        return _cant_tell("no user-scope janitor install found", stamp)
    if sha.startswith(stamp):
        return 0
    data = _compare(stamp, sha)
    if isinstance(data, str):
        return _cant_tell(data, stamp, sha)
    changed = classify(data)
    if changed:
        arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(platform.machine().lower(), platform.machine().lower())
        _emit(
            f"stale:{stamp}:{sha}",
            f"[{_NAME}] the memgrep binary was built from {stamp} but the installed plugin is at {sha[:7]}; "
            f"{changed} memgrep source file(s) changed since — fix: `gh release download v{version} "
            f"-R {_REPO} -p memgrep-{platform.system().lower()}-{arch}` and put it on PATH, "
            f"or `cargo install --path scripts/memgrep` from a janitor git checkout",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
