"""Shared three-scope memory-root resolution — the SINGLE SOURCE OF TRUTH.

The wikimem corpus is layered across three scopes (TRDD-c77dae09):

- **LOCAL**   ``~/.claude/projects/<slug>/memory/`` — per-project, per-machine,
              never pushed (the harness ``# Memory`` directive writes here).
- **PROJECT** ``<git-root>/.claude/project/memory/`` — in-repo, git-tracked +
              PUSHED, shared with every contributor. Namespaced under ``.claude/``
              because a bare ``memory/`` collides with the very common GitHub
              root-folder name; ``.claude/project/memory`` is collision-free.
- **USER**    ``~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/``
              — the janitor's FIXED plugin-DATA dir, cross-project (canonical). A synced
              backup MIRROR at ``~/.claude/ai-maestro-janitor-memory/`` survives an
              uninstall so memory is never lost (TRDD-GFT33HT9).

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
import re
import shutil
import subprocess
from pathlib import Path

# The janitor's FIXED plugin-DATA directory name (NOT a marketplace id). The CANONICAL
# USER memory scope lives under it; see resolve_user_dir for why it is hard-coded rather
# than read from ${CLAUDE_PLUGIN_DATA}. A ``--keep-data`` uninstall preserves it directly.
# PUBLIC (M-11, wikimem audit 2026-07-07): every module that needs the data-dir name
# (memory_settings.settings_dir, fleet_status, …) imports THIS constant — two literals
# that must never drift cannot be maintained independently.
JANITOR_DATA_DIR_NAME = "ai-maestro-janitor-ai-maestro-plugins"

# The USER-memory MIRROR dir name under ``~/.claude/`` (TRDD-GFT33HT9). The canonical USER
# corpus lives in the plugin DATA dir (above), which ``claude plugin uninstall`` DELETES
# unless ``--keep-data``. This is a SYNCED BACKUP MIRROR kept OUTSIDE the data dir so it
# survives an uninstall and the memory is never lost: SessionStart syncs primary→mirror,
# and on a fresh install whose primary is empty it RESTORES mirror→primary. The mirror is
# a backup, NOT the canonical store — every read/write still resolves to the data dir.
_USER_MEMORY_MIRROR_DIR_NAME = "ai-maestro-janitor-memory"

# The CURATED-wiki sub-namespace within every scope. The coexistence model
# (TRDD-ab232dbd, USER decision 2026-06-23): a scope's root ``memory/`` holds the
# harness BUFFER (MEMORY.md + raw notes, harness-owned); ``memory/wiki/`` holds the
# janitor's CURATED wiki pages. Harvest mirrors raw buffer notes into ``wiki/`` as
# SEPARATE curated copies — it never modifies the buffer. memgrep recall recurses
# the scope root, so it covers both halves with no change.
WIKI_SUBDIR = "wiki"

# Frontmatter keys the wikimem skills write but the harness ``# Memory`` directive
# never does (it writes only ``name`` / ``description`` / ``metadata.type``).
# Presence of ANY one marks a page CURATED; absence marks a RAW buffer note. The
# discriminator (is_curated_wiki_page) is by CONTENT SHAPE, not path.
_WIKIMEM_ONLY_FM_KEYS = ("node_type", "tier")

# --------------------------------------------------------------------------- #
# What is and is not a real NOTE in a memory dir — the SINGLE SOURCE OF TRUTH
# (TRDD-87935f21 mandate #3). Before this, every editor/librarian scan site
# (memory-librarian, memory_migrate, memorize-nudge, the memory-maintenance
# content-precheck) carried its OWN copy of "exclude the generated/index files +
# the detector-proposal artifacts + the PRIVATE user-mem store", with "mirrors
# the librarian's _NON_NOTE_NAMES" comments — a latent divergence bug (and an
# actual privacy gap: the consolidate skill's memgrep scan never excluded
# user-mem). is_note_file / iter_note_files below are that SSOT.
#
# NOTE the deliberate non-consumer: the `memory-scope-leak` SECURITY detector
# keeps its OWN, narrower filter on purpose. It scans the PUSHED PROJECT scope
# for leaked secrets, where a leak is a leak regardless of which subdir it sits
# in — so it must NOT skip user-mem/ or .maint-staging/. Routing it through this
# editor SSOT would silently weaken the leak scan; it is intentionally excluded.
# --------------------------------------------------------------------------- #

# Generated / index files written INTO a memory dir that are NOT notes. The
# MEMORY.md stub + memgrep's optional human-readable ``memory-index.md`` doc.
# Compared by basename, case-sensitively (the names are always written exactly so).
NON_NOTE_BASENAMES: frozenset[str] = frozenset({"MEMORY.md", "memory-index.md"})

# The detector-output family: the memory detectors drop plain-markdown REPORTS
# named ``<detector>-proposed.md`` into the scanned memory dir (the librarian's
# ``memory-reorg-proposed.md``, the scope-leak detector's
# ``memory-scope-leak-proposed.md``, any future sibling). None carry frontmatter,
# none are notes. A SUFFIX match excludes the WHOLE family — so a new detector's
# output never re-introduces the collision (issue #54).
DETECTOR_OUTPUT_SUFFIX = "-proposed.md"

# The PRIVATE user-authored store (TRDD-4334aad0) — a sibling subdir the agent
# corpus tooling MUST NOT walk into (privacy contract: it is agent-invisible by
# design). Excluding it here is the load-bearing fix of mandate #3.
USER_MEM_DIRNAME = "user-mem"

# Non-note sub-dirs inside a memory dir, never walked into: the private store,
# memgrep's SQLite sidecar cache, and the transaction staging dir (a staged copy
# mid-edit is not a committed note).
EXCLUDED_DIRNAMES: frozenset[str] = frozenset(
    {USER_MEM_DIRNAME, ".memgrep", ".maint-staging"}
)


def is_note_file(path: str | os.PathLike[str]) -> bool:
    """True iff ``path`` is a real memory NOTE — the SSOT discriminator.

    A real note is a ``*.md`` file that is NOT a generated/index file
    (``NON_NOTE_BASENAMES``), NOT a detector-proposal report (``-proposed.md``
    suffix), and does NOT live under any excluded sub-dir (``EXCLUDED_DIRNAMES``
    — most importantly the PRIVATE ``user-mem/`` store). Purely path-based; no I/O.
    """
    p = Path(path)
    name = p.name
    if not name.endswith(".md"):
        return False
    if name in NON_NOTE_BASENAMES or name.endswith(DETECTOR_OUTPUT_SUFFIX):
        return False
    # Any path component naming an excluded dir disqualifies (defence-in-depth:
    # even a memgrep result path that recursed into user-mem is filtered here).
    return not any(part in EXCLUDED_DIRNAMES for part in p.parts)


def iter_note_files(memdir: str | os.PathLike[str]) -> list[Path]:
    """Every real memory NOTE under ``memdir`` (recursive), filtered by ``is_note_file``.

    Recursive ``rglob`` matches the existing scan behavior of every editor/librarian
    site this SSOT replaces (the librarian, memory_migrate, memorize-nudge, and the
    content-precheck all recursed). Returns sorted for deterministic output; ``[]``
    when ``memdir`` is missing or unreadable (silent, never raises).
    """
    root = Path(memdir)
    if not root.is_dir():
        return []
    try:
        return sorted(
            p for p in root.rglob("*.md") if p.is_file() and is_note_file(p)
        )
    except OSError:
        return []


def project_slug(project_dir: str) -> str:
    """Harness per-project slug: the absolute path with every NON-ALPHANUMERIC char dashed.

    THE definition every janitor module must route through (user_mem_lib and fleet_scan
    delegate here). The harness dashes more than separators — verified on disk:
    ``…/perfect-skill-suggester/2.2.2`` → ``…-perfect-skill-suggester-2-2-2`` and
    ``…/4vmcr_496…`` → ``…-4vmcr-496…`` — so a separators-only translation resolved a
    NONEXISTENT dir for any dotted/underscored project path, silently emptying the whole
    LOCAL memory subsystem (recall, librarian, harvest, user-mem) and blinding
    fleet_scan.transcript_age for such projects. Do NOT resolve symlinks — the harness
    keys on the literal launch path, so resolving could diverge from the real dir name.
    """
    return re.sub(r"[^A-Za-z0-9]", "-", project_dir)


def _project_dir() -> str:
    """The current project directory (``CLAUDE_PROJECT_DIR`` or cwd), stripped."""
    return (os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).strip()


def resolve_local_dir_for(project_dir: str) -> Path:
    """The LOCAL agent-memory dir of an EXPLICIT project path (M-11 — the SSOT
    export for callers like fleet_status that resolve LOCAL roots for OTHER
    projects, not the current one). Uses the harness slug rules (`project_slug`:
    dash every non-alphanumeric char, never resolve symlinks). Not created."""
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    return home / ".claude" / "projects" / project_slug(project_dir) / "memory"


def resolve_local_dir() -> Path:
    """The per-project LOCAL agent-memory dir (parent of ``user-mem``). Not created.

    LOCAL scope of the three-scope wiki: per-project, per-machine, never pushed.
    """
    return resolve_local_dir_for(_project_dir())


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


def _home() -> Path:
    return Path(os.environ.get("HOME") or os.path.expanduser("~"))


def resolve_user_dir() -> Path:
    """The USER scope (global) memory root: the janitor's FIXED plugin-DATA dir
    ``~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory/`` (CANONICAL).

    Resolved by this EXPLICIT hard-coded path, NEVER via ``${CLAUDE_PLUGIN_DATA}``:
    that env var holds the *currently-running* plugin's data dir, which at heartbeat
    time is whatever plugin owns the turn — verified to be some other plugin, not the
    janitor — so reading it would route USER recall/write to the wrong plugin's dir.

    This is the CANONICAL store every read/write resolves to. It survives plugin updates
    and a ``--keep-data`` uninstall. A plain ``claude plugin uninstall`` DELETES it, so a
    synced backup MIRROR (``resolve_user_mirror_dir``) OUTSIDE the data dir guarantees the
    memory is never lost (TRDD-GFT33HT9). Not created.
    """
    return _home() / ".claude" / "plugins" / "data" / JANITOR_DATA_DIR_NAME / "memory"


def resolve_user_mirror_dir() -> Path:
    """The USER-memory BACKUP MIRROR ``~/.claude/ai-maestro-janitor-memory/`` (TRDD-GFT33HT9).

    A synced copy of the canonical USER corpus, kept OUTSIDE the plugin data dir so it
    survives ``claude plugin uninstall`` (which deletes the data dir unless ``--keep-data``).
    It is a backup only — never the store consumers resolve to. ``sync_user_memory_mirror``
    keeps it fresh and restores from it after a data-dir loss. Not created.
    """
    return _home() / ".claude" / _USER_MEMORY_MIRROR_DIR_NAME


def _dir_has_memory(d: Path) -> bool:
    """True iff ``d`` exists and holds at least one real corpus entry (a ``*.md`` note,
    the ``user-mem`` private store, the ``.memgrep`` index, or the curated ``wiki``). An
    empty or missing dir → False."""
    if not d.is_dir():
        return False
    for child in d.iterdir():
        name = child.name
        if name.endswith(".md") or name in ("user-mem", ".memgrep", WIKI_SUBDIR):
            return True
    return False


def sync_user_memory_mirror() -> str | None:
    """Keep the uninstall-surviving USER-memory MIRROR in step with the canonical store
    (TRDD-GFT33HT9). Returns ``"mirrored"`` / ``"restored"`` when it acted, else None.

    Two directions, decided by which side holds memory:
    - **primary has memory** → SYNC primary→mirror (refresh the backup). Steady state.
    - **primary EMPTY but mirror has memory** → RESTORE mirror→primary. This is the
      recovery path: a plain uninstall deleted the data dir, and on the next (re)install
      the mirror repopulates the canonical store so nothing is lost.
    - **neither has memory** → nothing to do (fresh install).

    The copy is ADDITIVE (``copytree(dirs_exist_ok=True)`` — overwrites changed files,
    keeps files the other side lacks): it NEVER deletes a note from either side, erring
    toward keeping memory. Best-effort — any OSError is swallowed so a mirror hiccup can
    never break session start. Cheap: the USER corpus is small markdown + a regeneratable
    index.
    """
    primary = resolve_user_dir()
    mirror = resolve_user_mirror_dir()
    try:
        if _dir_has_memory(primary):
            mirror.mkdir(parents=True, exist_ok=True)
            shutil.copytree(primary, mirror, dirs_exist_ok=True)
            return "mirrored"
        if _dir_has_memory(mirror):
            primary.mkdir(parents=True, exist_ok=True)
            shutil.copytree(mirror, primary, dirs_exist_ok=True)
            return "restored"
    except OSError:
        return None  # a backup hiccup must never break session start
    return None


def resolve_wiki_dir(scope_root: Path) -> Path:
    """The curated WIKI sub-namespace of a memory scope: ``<scope_root>/wiki``.

    The coexistence model (TRDD-ab232dbd): the harness BUFFER (MEMORY.md + raw
    notes) lives at the scope root; the janitor's CURATED wiki lives here. Harvest
    mirrors raw buffer notes into this dir as separate curated pages and NEVER
    modifies the buffer. memgrep recall recurses the scope root, so it naturally
    covers both. Not created — the caller (bootstrap / harvest) mkdirs it.
    """
    return scope_root / WIKI_SUBDIR


def is_curated_wiki_page(text: str) -> bool:
    """True iff ``text`` is a CURATED wikimem page; False iff a RAW harness buffer note.

    The coexistence discriminator (TRDD-ab232dbd): harvest mirrors only RAW buffer
    notes into the wiki and must SKIP pages that are already curated. The harness
    ``# Memory`` directive writes a MINIMAL frontmatter (``name`` / ``description`` /
    ``metadata.type``); the wikimem skills add keys the harness never writes —
    ``node_type: memory`` and ``tier`` (see ``_WIKIMEM_ONLY_FM_KEYS``). So the test
    is by CONTENT SHAPE — the presence of a wikimem-only key anywhere in the leading
    ``---`` frontmatter block — not by path. Cheap line scan; no YAML parse, no deps.
    A file with no well-formed frontmatter block is treated as RAW (not curated).
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    closed = False
    fm_lines: list[str] = []
    for ln in lines[1:]:
        if ln.strip() == "---":
            closed = True
            break
        fm_lines.append(ln)
    if not closed:
        # No closing fence → malformed / absent frontmatter → treat as RAW.
        return False
    for ln in fm_lines:
        # key = text before the first ':' (after stripping indent + any '-' list
        # marker), so nested ``  node_type: memory`` and top-level ``tier:`` match.
        key = ln.split(":", 1)[0].strip().lstrip("-").strip()
        if key in _WIKIMEM_ONLY_FM_KEYS:
            return True
    return False


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
