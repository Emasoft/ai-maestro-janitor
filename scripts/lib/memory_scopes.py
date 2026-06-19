"""Shared three-scope memory-root resolution — the SINGLE SOURCE OF TRUTH.

The wikimem corpus is layered across three scopes (TRDD-c77dae09):

- **LOCAL**   ``~/.claude/projects/<slug>/memory/`` — per-project, per-machine,
              never pushed (the harness ``# Memory`` directive writes here).
- **PROJECT** ``<git-root>/.claude/project/memory/`` — in-repo, git-tracked +
              PUSHED, shared with every contributor. Namespaced under ``.claude/``
              because a bare ``memory/`` collides with the very common GitHub
              root-folder name; ``.claude/project/memory`` is collision-free.
- **USER**    ``~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/``
              — the janitor's FIXED plugin-DATA dir, cross-project.

Every consumer (the memory-maintenance scheduler, the memory-librarian, and the
memorize-nudge detector) MUST resolve scopes through this module so they agree
byte-for-byte on what a scope is. Before this module the resolvers were
copy-pasted into each detector with an "IDENTICAL to ..." comment — a latent
divergence bug the moment one copy was touched. Extracting them here is
priority #2 of the memory-curation mission (TRDD-87935f21: fix memory-helper
script issues — eliminate the duplicated source of truth).

Stdlib only — importable from any detector that has ``scripts/lib`` on sys.path.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

# The janitor's FIXED plugin-DATA directory name (NOT a marketplace id). The
# USER memory scope lives under it; see resolve_user_dir for why it is hard-coded
# rather than read from ${CLAUDE_PLUGIN_DATA}.
_JANITOR_DATA_DIR_NAME = "ai-maestro-janitor-ai-maestro-plugins"


def project_slug(project_dir: str) -> str:
    """Harness per-project slug: the absolute path with every separator dashed.

    Mirrors ``user_mem_lib._project_slug`` and the directory the harness creates
    under ``~/.claude/projects/``. Do NOT resolve symlinks — the harness keys on
    the literal launch path, so resolving could diverge from the real dir name.
    """
    p = project_dir.replace(os.sep, "-")
    if os.altsep:
        p = p.replace(os.altsep, "-")
    return p


def _project_dir() -> str:
    """The current project directory (``CLAUDE_PROJECT_DIR`` or cwd), stripped."""
    return (os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).strip()


def resolve_local_dir() -> Path:
    """The per-project LOCAL agent-memory dir (parent of ``user-mem``). Not created.

    LOCAL scope of the three-scope wiki: per-project, per-machine, never pushed.
    """
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    return home / ".claude" / "projects" / project_slug(_project_dir()) / "memory"


def resolve_project_dir() -> Path | None:
    """The PROJECT scope memory root ``<git-root>/.claude/project/memory/``, or
    ``None`` when the cwd is not in a git repo. Resolved via
    ``git rev-parse --show-toplevel`` so a worktree / sub-directory cwd still
    finds the repo root (TRDD-c77dae09)."""
    proj = _project_dir() or None
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=proj, capture_output=True, text=True, timeout=10, check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    top = proc.stdout.strip()
    return (Path(top) / ".claude" / "project" / "memory") if top else None


def resolve_user_dir() -> Path:
    """The USER scope (global) memory root: the janitor's FIXED plugin-DATA dir
    ``~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/``.

    Resolved by this EXPLICIT hard-coded path, NEVER via ``${CLAUDE_PLUGIN_DATA}``:
    that env var holds the *currently-running* plugin's data dir, which at
    heartbeat time is whatever plugin owns the turn — verified to be some other
    plugin, not the janitor — so reading it would route USER recall/write to the
    wrong plugin's dir. The fixed dir also survives plugin updates + a
    ``--keep-data`` uninstall (NOT a ``~/.claude/<custom>/`` folder a cleanup
    pass could wipe). Not created.
    """
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    return home / ".claude" / "plugins" / "data" / _JANITOR_DATA_DIR_NAME / "memory"


def resolve_scope_dirs() -> list[tuple[str, Path]]:
    """The three-scope roots that EXIST, most-specific first: LOCAL → PROJECT → USER.

    De-duplicated by resolved path so a root that resolves twice (overlapping
    roots) is returned once; a scope whose dir does not exist is omitted. This is
    the SSOT the scheduler, the librarian, and the memorize-nudge all share, so
    they agree on what a scope is and which scopes are in play.
    """
    out: list[tuple[str, Path]] = []
    seen: set[Path] = set()

    def _add(label: str, d: Path | None) -> None:
        if d is None:
            return
        try:
            resolved = d.resolve()
        except OSError:
            resolved = d
        if resolved in seen or not d.is_dir():
            return
        seen.add(resolved)
        out.append((label, d))

    _add("LOCAL", resolve_local_dir())
    _add("PROJECT", resolve_project_dir())
    _add("USER", resolve_user_dir())
    return out
