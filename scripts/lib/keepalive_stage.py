"""Stage daemon.py's import closure into the persistent DATA dir (TRDD-71ABD7V7).

SHAPE 2's L0 keepalive launches a thin entry (`daemon_keepalive_entry.py`) at a FIXED
path under the plugin DATA dir; that entry does a static `import daemon`, so the daemon
AND its whole transitive import closure must sit BESIDE it at that path — copied
VERBATIM (byte-identical to the CPV-scanned repo files, never generated or edited). This
module computes that closure and copies it.

Why a closure and not the whole `scripts/` tree: the daemon imports only its core
`lib/` + `oauth_rotator/` modules, NEVER the ~200 `*_patterns.py` detector libs — so the
stage is ~16 small files, not the whole tree. The closure is BFS over the entry's +
daemon's ABSOLUTE imports (resolved against the daemon's runtime sys.path roots:
`scripts/`, `scripts/lib/`, `scripts/oauth_rotator/`). Completeness is not trusted to
this static analysis: the guard test stages the closure to a temp tree and runs a REAL
subprocess `import daemon` from it — so an under-computed closure fails the build, never
the running daemon.
"""

from __future__ import annotations

import ast
import os
import shutil
from pathlib import Path

# The daemon inserts these onto sys.path itself (from its own __file__); we resolve
# closure imports against the same roots so the stage layout matches what it expects.
_SUBDIRS = ("lib", "oauth_rotator")
# Closure seeds: the launched entry plus the daemon it statically imports.
_SEEDS = ("daemon_keepalive_entry.py", "daemon.py")


def _search_dirs(scripts_dir: Path) -> list[Path]:
    return [scripts_dir, *(scripts_dir / d for d in _SUBDIRS)]


def _resolve(top: str, search: list[Path]) -> Path | None:
    """Resolve a top-level module name to an in-tree .py, or None (a stdlib / third-party
    name is not under the search dirs, so it is supplied by the system python, not staged)."""
    for d in search:
        mod = d / f"{top}.py"
        if mod.is_file():
            return mod
        pkg = d / top / "__init__.py"
        if pkg.is_file():
            return pkg
    return None


def _imports_of(path: Path) -> set[str]:
    """Top-level module names imported by `path`. `ast.walk` so a function-local
    `import x` (e.g. supervisor.py's lazy `import rotator`) is caught too. Relative
    imports are intentionally not followed — verified absent from the daemon's closure;
    the real-import guard test would catch it if that ever changed."""
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            names.add(node.module.split(".")[0])
    return names


def daemon_closure(scripts_dir: Path) -> list[Path]:
    """Every in-tree .py the L0 daemon needs (the verbatim DATA stage list), absolute
    and sorted. BFS from the entry + daemon over their absolute imports."""
    search = _search_dirs(scripts_dir)
    seeds = [scripts_dir / name for name in _SEEDS]
    seen: set[Path] = set(seeds)
    queue: list[Path] = [s for s in seeds if s.is_file()]
    closure: set[Path] = set()
    while queue:
        current = queue.pop()
        closure.add(current)
        for name in _imports_of(current):
            nxt = _resolve(name, search)
            if nxt is not None and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return sorted(closure)


class UnsafeStageDestination(Exception):
    """The stage destination is a plugin SOURCE checkout, not the DATA dir."""


def is_plugin_source_checkout(path: Path) -> bool:
    """True iff `path` sits inside a plugin SOURCE repo — a git work tree whose ROOT also
    carries `.claude-plugin/plugin.json`.

    Both conditions are required, and the second is what makes this safe. "Inside any git
    repo" would be wrong: plenty of people keep `~` or `~/.claude` in a dotfiles repo, and
    the real DATA dir lives under `~/.claude/plugins/data/…` — so a bare git test would
    refuse the LEGITIMATE production stage and silently kill the L0 keepalive. A plugin
    manifest at the repo root, by contrast, is present in a plugin checkout and never in
    the DATA dir.

    A plain filesystem walk, not `git rev-parse`: no subprocess, no PATH dependency, and it
    works for a destination that does not exist yet (we walk its ancestors). A `.git` FILE
    (a worktree/submodule pointer) counts exactly like a `.git` dir.
    """
    p = path if path.is_absolute() else path.resolve()
    for candidate in (p, *p.parents):
        if (candidate / ".git").exists():
            return (candidate / ".claude-plugin" / "plugin.json").is_file()
    return False


def stage_closure(scripts_dir: Path, dest_scripts_dir: Path) -> list[Path]:
    """Verbatim-copy the closure into `dest_scripts_dir`, preserving the relative layout
    (so the staged daemon's `_HERE/"lib"` + `_HERE/"oauth_rotator"` resolve). Each copy is
    byte-identical (`shutil.copyfile` — never edited/templated) and lands atomically
    (tmp + `os.replace`). The launched entry is made executable. Returns the staged paths.

    REFUSES a destination inside a plugin SOURCE checkout (TRDD-RYZCVVKA). The closure is
    only ever staged into the plugin DATA dir, so a source-repo destination is ALWAYS a bug
    — and a DESTRUCTIVE one: it overwrites a developer's files with the installed plugin's
    older, published copies, silently reverting committed work and clearing exec bits. That
    happened on 2026-07-11: this repo's entire closure was reverted to the v0.39.0 release,
    and it surfaced only because the lost +x bit broke 22 tests. The same class caused
    TRDD-ZNN0UK5K (tests restaging the REAL closure → a 39 GB fseventsd runaway). Guarding
    the WRITE makes the class impossible rather than merely detectable, which is worth more
    than knowing which caller got the path wrong.
    """
    if is_plugin_source_checkout(dest_scripts_dir):
        raise UnsafeStageDestination(
            f"refusing to stage the daemon closure into {dest_scripts_dir}: it is inside a "
            "plugin SOURCE checkout. The closure belongs in the plugin DATA dir; staging it "
            "over a source tree overwrites a developer's files with the installed plugin's "
            "older copies. See TRDD-RYZCVVKA."
        )
    staged: list[Path] = []
    for src in daemon_closure(scripts_dir):
        dst = dest_scripts_dir / src.relative_to(scripts_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_name(f"{dst.name}.tmp.{os.getpid()}")
        shutil.copyfile(src, tmp)  # byte-identical copy of the CPV-scanned file
        if src.name == "daemon_keepalive_entry.py":
            os.chmod(tmp, 0o755)  # nosec B103 -- launchd/systemd exec this staged script directly via its shebang; 0o755 is intended
        os.replace(tmp, dst)
        staged.append(dst)
    return staged
