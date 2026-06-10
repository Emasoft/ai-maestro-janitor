#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""UserPromptSubmit hook — OPT-IN automatic memory recall (issue #16, item 2).

When enabled, every ordinary user prompt is run through `memgrep recall` against
the AGENT memory corpus (`~/.claude/projects/<slug>/memory/`), and the top notes
are injected into the agent context via `additionalContext` — so the agent is
reminded of "have we hit this before?" WITHOUT having to call recall by hand.

Design contract (load-bearing — keep all of these):

  - OFF BY DEFAULT. A no-op (instant `exit 0`, empty stdout) unless
    `CLAUDE_PLUGIN_OPTION_MEMORY_AUTORECALL` is truthy. The default is off
    because this fires on EVERY prompt and shells out to a binary; opt-in keeps
    the common install cost at one env read + one startswith.

  - AGENT corpus only — PRIVACY BOUNDARY. It searches the agent-visible notes in
    `~/.claude/projects/<slug>/memory/`. It MUST NOT search the PRIVATE user-mem
    store (`…/memory/user-mem/`), which is deliberately agent-invisible: surfacing
    a user memory into agent context would breach the user-mem privacy boundary.
    `memgrep recall` walks a directory RECURSIVELY and has no exclude flag, so
    pointing it at `memory/` WOULD descend into `user-mem/` and leak a private
    note (verified). Instead we enumerate ONLY the top-level `*.md` files of
    `memory/` and pass them to recall as explicit file arguments — recall takes
    file paths verbatim and only walks DIRECTORIES, so the private subtree is
    never traversed. The exclusion is structural, not a flag.

  - Never blocks, never crashes. Cron `[janitor-…]` prompts and slash commands
    (`/…`) are skipped (they are not user questions). Malformed stdin, a missing
    memgrep binary, an empty corpus, a recall timeout, or ANY exception → the
    hook silently no-ops (exit 0, empty stdout) so the user's turn always
    proceeds. The injection is advisory; failure to recall is never fatal.

  - additionalContext is the ONLY channel used (the documented field that
    reaches the model). It is set only on a genuine hit; on no hit nothing is
    emitted, so an empty corpus is indistinguishable from the hook being off.
"""

from __future__ import annotations

import json
import os
import subprocess  # memgrep is invoked with a fixed argv (shell=False); no untrusted command string
import sys
from pathlib import Path

# How many notes to inject, and how long to let recall run. Recall over a local
# SQLite index is sub-second; the timeout only guards a pathological corpus so a
# slow recall degrades to "no recall this turn" instead of stalling the prompt.
_TOP = 3
_TIMEOUT_S = 4.0
# Hard cap on the injected text so a corpus of very long descriptions can't bloat
# the agent context; recall prints one `path — description` line per note.
_MAX_CHARS = 1200

# Non-page files inside a PROJECT/USER memory root that must NOT be recalled
# (loaded index, generated query index, the memory detectors' proposal files).
# The LOCAL corpus uses `_agent_notes` (top-level *.md), which never reaches
# these by depth; the PROJECT/USER walk is recursive, so it excludes them by name.
_NON_PAGE_NAMES = frozenset({
    "MEMORY.md",
    "memory-index.md",
    "memory-reorg-proposed.md",
    "memory-scope-leak-proposed.md",
})


def _load_libs():
    """Import `user_mem_lib` (for find_memgrep + the agent-memdir resolution) and
    `state` (for is_truthy_env), whether running via the plugin (CLAUDE_PLUGIN_ROOT
    set) or directly (tests). Returns (user_mem_lib, state) or (None, None) when
    the libs cannot be found — in which case the hook becomes a no-op rather than
    crashing the session."""
    candidates: list[Path] = []
    plugin_root = os.environ.get("CLAUDE_PLUGIN_ROOT", "").strip()
    if plugin_root:
        candidates.append(Path(plugin_root) / "scripts" / "lib")
    # Fallback: resolve relative to this file (scripts/hooks/ → scripts/lib/).
    candidates.append(Path(__file__).resolve().parent.parent / "lib")
    for lib_dir in candidates:
        if (lib_dir / "user_mem_lib.py").is_file() and (lib_dir / "state.py").is_file():
            sys.path.insert(0, str(lib_dir))
            try:
                import state  # noqa: E402  -- local module, not PyPI
                import user_mem_lib  # noqa: E402  -- local module, not PyPI

                return user_mem_lib, state
            except Exception:  # pragma: no cover - defensive
                return None, None
    return None, None


def _agent_memdir(um, project_dir: str | None) -> Path:
    """The AGENT memory corpus dir: `~/.claude/projects/<slug>/memory/`.

    Derived as the PARENT of the user-mem store so the slug/HOME resolution stays
    in ONE place (user_mem_lib.resolve_user_mem_dir) — the agent corpus is the
    sibling of, and never includes, the private `user-mem/` subtree.
    """
    return um.resolve_user_mem_dir(project_dir=project_dir).parent


def _agent_notes(memdir: Path) -> list[str]:
    """The top-level `*.md` files of the agent corpus — the search set.

    ONLY the direct children of `memdir`; never the `user-mem/` subdirectory.
    Returns absolute paths sorted for determinism. An unreadable dir yields []
    (the caller then no-ops). This is the structural privacy boundary: by handing
    recall explicit FILE paths we guarantee the recursive walk never reaches the
    private user-mem subtree (recall walks directories, not files).
    """
    try:
        return sorted(str(p) for p in memdir.glob("*.md") if p.is_file())
    except OSError:  # pragma: no cover - defensive
        return []


def _scope_pages(root: Path) -> list[str]:
    """The recallable `*.md` pages of a PROJECT or USER memory root.

    The memory system has THREE scopes (TRDD-c77dae09): LOCAL (the agent corpus,
    handled by `_agent_notes` with its user-mem exclusion), PROJECT
    (`<git-root>/memory/`, git-tracked + pushed), and USER (`~/.claude/memory/`,
    global). PROJECT/USER pages may live in subdirectories, so we walk
    recursively — but EXCLUDE the tool's generated `.memgrep/` index sidecar and
    the detector proposal/index files (not pages). Returns absolute file paths
    sorted for determinism; an unreadable/absent root yields [].

    Note: PROJECT/USER scopes never contain a private `user-mem/` subtree (that
    is LOCAL-only by construction), so there is no privacy subtree to exclude
    here — but skipping `.memgrep/` keeps generated cache out of the recall set.
    """
    if not root.is_dir():
        return []
    try:
        pages = [
            str(p)
            for p in root.rglob("*.md")
            if p.is_file()
            and ".memgrep" not in p.parts
            and p.name not in _NON_PAGE_NAMES
        ]
    except OSError:  # pragma: no cover - defensive
        return []
    return sorted(pages)


def _project_memdir(project_dir: str | None) -> Path | None:
    """The PROJECT-scope memory root: `<git-root>/memory/`, or None when the cwd
    is not in a git repo. Resolved via `git rev-parse --show-toplevel` so a
    worktree / sub-directory cwd still finds the repo root."""
    cwd = (project_dir or os.getcwd()).strip() or None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None
    if proc.returncode != 0:
        return None
    top = proc.stdout.strip()
    return (Path(top) / "memory") if top else None


def _user_memdir() -> Path:
    """The USER-scope (global) memory root: `~/.claude/memory/`. Not created."""
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    return home / ".claude" / "memory"


def _recall(memgrep: str, query: str, note_paths: list[str]) -> str:
    """Run `memgrep recall <query> <note-files…> --top N --use-index` and return
    its stdout (the `path — description` lines) — or "" on any failure/timeout/
    no-hit. `note_paths` are explicit top-level FILES (never the dir), so recall
    never descends into the private user-mem subtree. Fixed argv, no shell.
    """
    argv = [
        memgrep,
        "recall",
        query,
        *note_paths,
        "--top",
        str(_TOP),
        "--use-index",
    ]
    try:
        # Fixed argv, shell=False: `memgrep` is a resolved binary path and the
        # query/paths are positional args (never a shell string), so neither the
        # user prompt nor the note paths can inject a command.
        proc = subprocess.run(
            argv,
            input="",
            capture_output=True,
            text=True,
            timeout=_TIMEOUT_S,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout


def _format_context(recall_out: str) -> str | None:
    """Turn recall's `path — description` lines into a compact additionalContext
    block, or None when there are no usable lines. Caps total length so a few
    very long descriptions cannot bloat the agent context.
    """
    lines = [ln.rstrip() for ln in recall_out.splitlines() if ln.strip()]
    if not lines:
        return None
    body = "\n".join(lines)[:_MAX_CHARS]
    return (
        "[janitor-memory] Possibly-relevant notes from your memory corpus "
        "(recall before acting; read a note's body for the answer):\n" + body
    )


def main() -> int:
    # OFF BY DEFAULT — the first thing we do, before reading stdin or importing
    # libs, so a disabled install costs exactly one env read.
    if os.environ.get("CLAUDE_PLUGIN_OPTION_MEMORY_AUTORECALL", "").strip() == "":
        # Unset/empty → use the documented default (off) WITHOUT importing state.
        return 0

    try:
        raw = sys.stdin.read()
    except Exception:  # pragma: no cover - stdin closed
        return 0
    if not raw or not raw.strip():
        return 0
    try:
        payload = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return 0
    if not isinstance(payload, dict):
        return 0

    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    um, state = _load_libs()
    if um is None or state is None:
        return 0

    # Now honour the env var via the shared spelling-of-false rules. The bare
    # presence check above already returned for unset/empty; a value of
    # `false`/`0`/`no`/`off` disables the hook here.
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_MEMORY_AUTORECALL", default=False):
        return 0

    stripped = prompt.strip()
    # Skip our own cron heartbeats (`[janitor-…]`) and any slash command — neither
    # is a user question, and recalling on them would inject noise every tick.
    if stripped.startswith("[janitor-") or stripped.startswith("/"):
        return 0

    memgrep = um.find_memgrep()
    if not memgrep:
        # No binary → cannot recall; stay a silent no-op (issue #16: "no-op when
        # memgrep is absent").
        return 0

    project_dir = (os.environ.get("CLAUDE_PROJECT_DIR") or payload.get("cwd") or "").strip() or None

    # Compose ALL THREE memory scopes into ONE recall (TRDD-c77dae09): LOCAL (the
    # agent corpus, with its structural user-mem exclusion) → PROJECT
    # (`<git-root>/memory/`) → USER (`~/.claude/memory/`). recall takes explicit
    # FILE paths and only walks DIRECTORIES, so passing files keeps the private
    # `user-mem/` subtree untraversed AND lets one invocation rank across all
    # roots. Ordering is most-specific-first so that, all else equal, a local note
    # precedes a project/user note in the input order. A scope whose dir is absent
    # contributes nothing.
    local_dir = _agent_memdir(um, project_dir)
    note_paths: list[str] = []
    if local_dir.is_dir():
        note_paths.extend(_agent_notes(local_dir))  # top-level *.md only (user-mem excluded)
    project_dir_mem = _project_memdir(project_dir)
    if project_dir_mem is not None:
        note_paths.extend(_scope_pages(project_dir_mem))
    note_paths.extend(_scope_pages(_user_memdir()))
    # De-duplicate while preserving most-specific-first order (a path could in
    # principle appear via two roots if they overlap; keep the first occurrence).
    seen_paths: set[str] = set()
    deduped: list[str] = []
    for pth in note_paths:
        if pth not in seen_paths:
            seen_paths.add(pth)
            deduped.append(pth)
    note_paths = deduped

    if not note_paths:
        # No notes in any scope (empty/absent corpora, or only the private
        # user-mem store) → nothing the agent may recall.
        return 0

    recall_out = _recall(memgrep, stripped, note_paths)
    context = _format_context(recall_out)
    if context is None:
        return 0

    sys.stdout.write(
        json.dumps(
            {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }
        )
    )
    return 0


if __name__ == "__main__":
    # Bare main() so the module is importable without side effects; the hook
    # always exits 0 (any internal failure degrades to a no-op, never aborting
    # the user's turn).
    main()
