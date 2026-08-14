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
import time
from pathlib import Path

import state

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
# harness BUFFER (MEMORY.md + raw notes, harness-owned); ``memory/wikimem/`` holds the
# janitor's CURATED wiki pages. Harvest mirrors raw buffer notes into ``wikimem/`` as
# SEPARATE curated copies — it never modifies the buffer. memgrep recall recurses
# the scope root, so it covers both halves with no change.
WIKI_SUBDIR = "wikimem"  # USER decision 2026-07-08: curated pages live in <scope_root>/wikimem/ (renamed from "wiki"; no legacy fallback)

# Frontmatter keys the wikimem skills write but the harness ``# Memory`` directive
# never does (it writes only ``name`` / ``description`` / ``metadata.type``).
# Presence of ANY one marks a page CURATED; absence marks a RAW buffer note. The
# discriminator (is_curated_wiki_page) is by CONTENT SHAPE, not path.
_WIKIMEM_ONLY_FM_KEYS = ("node_type", "tier")

# A wikimem-only key spelled INSIDE a flow-style ``metadata: {node_type: memory, tier:
# hub}`` mapping (janitor#212) — the per-line key scan in is_curated_wiki_page only ever
# sees the line's own leading key ("metadata"), so a key packed inside the braces on that
# SAME line was invisible to it. This is the exact shape SessionStart writes for every
# freshly-bootstrapped scope's ``*-overview.md`` stub — ``metadata: {node_type: memory,
# tier: hub, type: overview}`` — so unfixed it misclassified EVERY such stub as a RAW
# buffer note — harvest then tried (and could never succeed) to "mirror" an already-
# curated page forever, the load-bearing cause of the reported harvest re-fire. Matches a
# listed key immediately after ``{`` or ``,`` (not merely appearing as a substring of some
# other value). memory_edit_verify.parse_frontmatter already handles flow-style metadata
# for its OWN (separate, fuller) parser — TRDD-87935f21 Finding 1 — this is the same bug
# class in this module's smaller, dependency-free scanner.
_FLOW_METADATA_KEY_RE = re.compile(
    r"(?:^|[{,])\s*(?:" + "|".join(re.escape(k) for k in _WIKIMEM_ONLY_FM_KEYS) + r")\s*:"
)

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
# Where the mirror parks a page that canonical deleted and that is PROVABLY
# superseded (janitor#146/#156). Not a delete: the page keeps existing, it just
# stops being part of the corpus — so it can no longer collide on atom ids, and a
# restore can no longer resurrect it. Listed in EXCLUDED_DIRNAMES below, which is
# what makes it invisible to every scan site at once (lint, recall, the librarian,
# the content-precheck) instead of each having to learn about it.
SUPERSEDED_DIRNAME = ".superseded"

# Non-note sub-dirs inside a memory dir, never walked into: the private store,
# memgrep's SQLite sidecar cache, the transaction staging dir (a staged copy
# mid-edit is not a committed note), and the mirror's superseded attic.
EXCLUDED_DIRNAMES: frozenset[str] = frozenset(
    {USER_MEM_DIRNAME, ".memgrep", ".maint-staging", SUPERSEDED_DIRNAME}
)

# An atom marker: `^<id>` at the start of a line, followed by whitespace or its
# `[props]` block. The lookahead is load-bearing — without it a bare `^` opening a
# regex in prose ("^foo matches...") would register as an atom id and could make an
# orphan page look superseded by a page that never defined it.
_ATOM_MARKER_RE = re.compile(r"^\^([A-Za-z0-9_-]+)(?=[ \t\[])", re.MULTILINE)

# Fenced blocks are stripped before parsing. janitor#152 is the same lesson from the
# other direction: markdown code can contain text that LOOKS like corpus syntax and
# is not. A doc page showing `^example-atom [desc: ...]` in a fence must not be
# credited with defining that atom — here that mistake would let a fence in some
# canonical page vouch for an orphan and quarantine real knowledge.
_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)


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
            p for p in root.rglob("*.md")
            if p.is_file() and is_note_file(p) and not escapes_root(p, root)
        )
    except OSError:
        return []


def escapes_root(path: Path, root: Path) -> bool:
    """True iff ``path`` resolves OUTSIDE ``root`` — i.e. it is a symlink into another scope.

    janitor#249: four USER-scope pages on one host are symlinks into a different repo's
    git-tracked PROJECT memory. `memory_txn`'s M-10 guard refuses them at commit time, and
    correctly so — a scope's transaction must not write outside its own root. But
    `is_note_file` is deliberately path-only ("no I/O"), so they still counted as CANDIDATES:
    the scheduler saw work, dispatched an agent, and the agent hit the guard. Every cadence,
    forever, for pages that can never be written from here.

    Excluding them at the lister makes the two layers agree. It is not a loss of knowledge and
    NOTHING is deleted: the target file is a real page in its own scope, where its own chores
    maintain it and where recall still finds it — reading a symlink works fine; only WRITING
    across the boundary is refused. A page is maintained in exactly one scope, which is the
    same "one element = one page" rule the wiki already runs on.

    Deliberately not the caller's job to remember: the escape is a property of the path, so a
    future lister that forgets this check is the bug, not the symlink.
    """
    try:
        return not path.resolve().is_relative_to(root.resolve())
    except (OSError, ValueError):
        return True  # unresolvable ⇒ treat as escaping; never hand a chore a path we can't pin


def iter_escaping_note_files(memdir: str | os.PathLike[str]) -> list[Path]:
    """Every real memory NOTE under ``memdir`` that ``iter_note_files`` silently drops
    because it ESCAPES the scope root — the STRUCTURAL half of janitor#249.

    `iter_note_files` correctly excludes these from a chore's candidate list (a scope's
    transaction cannot write outside its own root, M-10). But excluding them from the
    lister and never reporting them anywhere are two different things: the page is
    real, `is_note_file` says so, and it can NEVER become eligible from here — no
    future content change clears a symlink escape. That is a STRUCTURAL refusal, not
    the TRANSIENT "unchanged since last look" kind the dispatch fingerprint already
    dedupes: it deserves exactly one countable finding, not permanent silence.

    Same recursive `rglob` + `is_note_file` filter as `iter_note_files`; the only
    difference is the `escapes_root` polarity. Returns ``[]`` for a missing/unreadable
    root — mirrors `iter_note_files`, never raises.
    """
    root = Path(memdir)
    if not root.is_dir():
        return []
    try:
        return sorted(
            p for p in root.rglob("*.md")
            if p.is_file() and is_note_file(p) and escapes_root(p, root)
        )
    except OSError:
        return []


def is_published_globally(path: Path) -> bool:
    """True iff ``path`` is a SANCTIONED `publish-globally:` symlink, not a stray escape.

    A PROJECT-scope page may carry `publish-globally: true` and be symlinked into the USER
    memory dir so recall reaches it from every project. That link ESCAPES the USER root by
    construction, so `escapes_root` flags it — correctly, for the CANDIDATE question (M-10: a
    USER chore still cannot write across into a PROJECT file). It is wrong for the REPORTING
    question: the state is the intended one, and the escape line's remediation advice ("move
    the page, or re-point the link the other way") would UNDO the mechanism. This predicate is
    what lets the reporter tell the two apart.

    SSOT for the four states is Rust — `memgrep/src/memory.rs::classify_publish_globally` —
    which both `memgrep lint` and every write verb's normalizer route through. This is a
    deliberate ~10-line duplicate of only the CONFORMANT arm (field true + symlink present),
    NOT a re-implementation of the state machine: shelling out to `memgrep` would couple a
    never-crash detector to a cargo-installed binary that is not guaranteed present. Value
    parsing matches the Rust side's case-insensitive compare. Everything else — a `false` flag
    with a symlink (the CONFLICT a human must resolve), a missing field, an unreadable target —
    stays a defect here, which is why this FAILS TOWARD REPORTING on any error, mirroring
    `escapes_root`'s "unresolvable ⇒ escaping".
    """
    if not path.is_symlink():
        return False
    try:
        text = path.resolve().read_text(encoding="utf-8", errors="replace")
    except (OSError, ValueError):
        return False  # unreadable ⇒ NOT sanctioned; a report is cheaper than a silent hole
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return False
    for ln in lines[1:]:
        if ln.strip() == "---":
            return False  # end of frontmatter, field never seen
        key, sep, value = ln.partition(":")
        if sep and key.strip() == "publish-globally":
            return value.strip().strip("\"'").casefold() == "true"
    return False  # no closing fence ⇒ malformed frontmatter ⇒ not sanctioned


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


# Directory NAMES a downward scan for `resolve_project_dir`'s fallback never descends
# into — build/vendor dirs that can be huge and are never a repo root worth finding.
# `.git` itself is excluded too (nothing useful nests below it). A trailing `_dev` dir
# is excluded via a separate suffix check below (the project's own `*_dev` convention).
_DOWNWARD_SCAN_SKIP_NAMES = frozenset({"node_modules", ".venv", ".git", "target", "_corpus_dev"})


def _bounded_downward_dirs_with(start: Path, predicate, *, max_depth: int = 4) -> list[Path]:
    """Breadth-first, depth-bounded downward search from ``start`` for directories
    where ``predicate(d)`` is true. Skips ``_DOWNWARD_SCAN_SKIP_NAMES`` and any
    ``*_dev`` directory, and stops at ``max_depth`` so a huge tree cannot hang a
    heartbeat (janitor#263). Never raises — an unreadable directory is just skipped."""
    hits: list[Path] = []
    queue: list[tuple[Path, int]] = [(start, 0)]
    while queue:
        d, depth = queue.pop(0)
        try:
            if predicate(d):
                hits.append(d)
        except OSError:
            pass
        if depth >= max_depth:
            continue
        try:
            children = sorted(p for p in d.iterdir() if p.is_dir())
        except OSError:
            continue
        for c in children:
            if c.name in _DOWNWARD_SCAN_SKIP_NAMES or c.name.endswith("_dev"):
                continue
            queue.append((c, depth + 1))
    return hits


def resolve_project_dir() -> Path | None:
    """The PROJECT scope memory root ``<git-root>/.claude/project/memory/``, or
    ``None`` when no repo can be resolved. Resolved via ``git rev-parse
    --show-toplevel`` so a worktree / sub-directory cwd still finds the repo root
    (TRDD-c77dae09).

    ``git rev-parse`` only searches UPWARD. When the Claude project dir instead
    CONTAINS one or more git repos as subdirectories (a workspace folder holding
    checkouts — common on this machine), rev-parse finds nothing and PROJECT scope
    used to vanish silently — the worst scope to lose quietly, since it is the
    git-tracked, pushed, shared-with-every-contributor one (janitor#263). On that
    failure we search DOWNWARD instead, bounded and cautious: an existing
    ``.claude/project/memory/`` wins outright (it is already this project's own
    scope), else a lone ``.git`` dir is used. A blind downward pick is unsafe with
    multiple repos below — writing PROJECT memory into the wrong one is a real
    cross-project leak — so more than one candidate refuses to guess and logs the
    ambiguity instead of disappearing without a trace.
    """
    proj = _project_dir() or None
    try:
        # Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock
        # and collides with a concurrent `publish.py` commit (janitor#245).
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            cwd=proj, capture_output=True, text=True, timeout=10, check=False,
            env=git_env,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode == 0:
        top = proc.stdout.strip()
        return (Path(top) / ".claude" / "project" / "memory") if top else None

    start = Path(proj) if proj else None
    if start is None or not start.is_dir():
        return None

    mem_hits = _bounded_downward_dirs_with(
        start, lambda d: (d / ".claude" / "project" / "memory").is_dir()
    )
    if len(mem_hits) == 1:
        return mem_hits[0] / ".claude" / "project" / "memory"
    if len(mem_hits) > 1:
        state.log_line(
            "memory-scopes",
            f"resolve_project_dir: ambiguous PROJECT scope — {len(mem_hits)} existing "
            f".claude/project/memory dirs found below {start} (git rev-parse found no "
            "repo upward); refusing to guess, returning None",
        )
        return None

    git_hits = _bounded_downward_dirs_with(start, lambda d: (d / ".git").exists())
    if len(git_hits) == 1:
        return git_hits[0] / ".claude" / "project" / "memory"
    if len(git_hits) > 1:
        state.log_line(
            "memory-scopes",
            f"resolve_project_dir: ambiguous PROJECT scope — {len(git_hits)} repos "
            f"(.git) found below {start} (git rev-parse found no repo upward); "
            "refusing to guess, returning None",
        )
    return None


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
    """True iff ``d`` exists and holds at least one real corpus entry — KNOWLEDGE: a ``*.md``
    note, the ``user-mem`` private store, or the curated ``wiki``. An empty or missing dir →
    False.

    The ``.memgrep`` index deliberately does NOT count (F10, audit 2026-07-13). It is derived
    state, regeneratable from the notes at any time — but this predicate is what decides the
    sync DIRECTION, so counting it was a restore-blocking hazard: after a plain uninstall
    wiped the data dir, anything that recreated a bare ``.memgrep/`` in the primary would make
    this return True, the sync would take the primary→mirror branch, and the user's ONLY
    surviving copy of their memory would never be restored. An index is not a memory."""
    if not d.is_dir():
        return False
    for child in d.iterdir():
        name = child.name
        if name.endswith(".md") or name in ("user-mem", WIKI_SUBDIR):
            return True
    return False


# F10 (audit 2026-07-13): the mirror must carry NOTES, and nothing else. The USER scope
# ROOT is also where `memory_txn` puts `.maint-staging/` and memgrep puts `.memgrep/`, and
# a blind copytree took both:
#   - `.maint-staging/` holds a live txn's staged page COPIES and its journal. memgrep has
#     no staging exclusion (only `iter_note_files` does), so restoring those copies makes
#     the agent RECALL superseded, half-edited pages as if they were memories — and a
#     restored `committing` journal is a live roll-forward instruction that `resume_pending`
#     would execute against a corpus months out of step with the hashes it recorded.
#   - `.memgrep/index.db` is a SQLite file that may be mid-write, so it lands torn — and it
#     is regeneratable anyway (`memgrep reindex`), so backing it up buys nothing.
_MIRROR_IGNORE = shutil.ignore_patterns(
    ".maint-staging", ".memgrep", SUPERSEDED_DIRNAME
)


def page_atom_ids(text: str) -> set[str]:
    """Every atom id DEFINED by a page. Pure; fenced code is not a definition."""
    return set(_ATOM_MARKER_RE.findall(_FENCE_RE.sub("", text)))


def classify_mirror_orphans(
    orphan_texts: dict[str, str], canonical_ids: set[str]
) -> tuple[list[str], list[str]]:
    """Split mirror-only pages into ``(superseded, unknown)``. PURE — no I/O.

    A page that exists in the MIRROR but not in CANONICAL is one of two very
    different things, and the whole safety of pruning rests on telling them apart
    (janitor#156 states this requirement itself):

    * **superseded** — canonical deleted it because a consolidation folded it into a
      successor. Provable, not guessed: every atom id the page defines is still
      defined somewhere in canonical, so the knowledge survives under the successor
      and the orphan is a pure duplicate. Duplicates are not harmless — they collide
      on atom id, so `recall <id>` cannot resolve which page was meant.
    * **unknown** — canonical lost it for a reason nobody recorded, and no canonical
      page covers it. This is the mirror doing exactly its job: holding the only
      surviving copy. NEVER prune it.

    Two deliberate asymmetries, both erring toward keeping memory:

    * A page defining ZERO atom ids is **unknown**, never superseded. `set() <= X` is
      vacuously True, so the natural subset test would silently classify every
      atom-less page as safe to prune — the exact shape of bug that deletes the
      knowledge this mirror exists to protect. It is spelled out rather than relying
      on the reader to notice the empty case.
    * The test is on the page's OWN ids, not on prose similarity. A page whose text
      merely resembles a canonical page is unknown.
    """
    superseded: list[str] = []
    unknown: list[str] = []
    for name in sorted(orphan_texts):
        ids = page_atom_ids(orphan_texts[name])
        if ids and ids <= canonical_ids:
            superseded.append(name)
        else:
            unknown.append(name)
    return superseded, unknown


def _quarantine_superseded_orphans(primary: Path, mirror: Path) -> list[str]:
    """Park provably-superseded mirror-only pages in ``<mirror>/.superseded/``.

    RELOCATE, never delete: the page stops being corpus (the attic is in
    EXCLUDED_DIRNAMES, so no scan, lint, recall or restore sees it) while remaining
    on disk and recoverable with one `mv`. That keeps the property the mirror exists
    for — nothing is ever lost — while removing the two harms an orphan causes: the
    atom-id collision, and a restore resurrecting a page canonical deliberately
    consolidated away.

    Returns the names of pages that are mirror-only and NOT provably superseded, so
    the caller can surface them. They are left exactly where they are: an unexplained
    orphan may be the only copy of that knowledge.

    Best-effort — any OSError leaves the mirror untouched. A backup that cannot tidy
    itself is still a working backup; one that raises during session start is not.
    """
    primary_notes = {p.name: p for p in iter_note_files(primary)}
    mirror_notes = {p.name: p for p in iter_note_files(mirror)}
    orphan_names = set(mirror_notes) - set(primary_notes)
    if not orphan_names:
        return []

    try:
        canonical_ids: set[str] = set()
        for p in primary_notes.values():
            canonical_ids |= page_atom_ids(p.read_text(encoding="utf-8", errors="replace"))
        orphan_texts = {
            n: mirror_notes[n].read_text(encoding="utf-8", errors="replace")
            for n in orphan_names
        }
    except OSError:
        return []

    superseded, unknown = classify_mirror_orphans(orphan_texts, canonical_ids)
    if superseded:
        attic = mirror / SUPERSEDED_DIRNAME
        try:
            attic.mkdir(parents=True, exist_ok=True)
            for name in superseded:
                dest = attic / name
                # Never clobber a previously-parked page of the same name: keeping
                # both costs a few KB, and losing the older one would be the very
                # deletion this function is written to avoid.
                if dest.exists():
                    dest = attic / f"{Path(name).stem}.{int(time.time())}.md"
                shutil.move(str(mirror_notes[name]), str(dest))
        except OSError:
            pass  # a partial tidy is fine; the next session start retries
    return unknown


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

    Additive-only had a cost the mirror could not pay (janitor#146/#156): a canonical
    DELETE never propagates, so a page consolidated into a successor stayed here
    forever, duplicating the successor's atom ids — and a restore would then inject
    that ambiguity back into canonical, undoing the consolidation. So the
    primary→mirror branch also RELOCATES (never deletes) the orphans it can PROVE are
    redundant, into ``.superseded/``. See ``_quarantine_superseded_orphans``.

    Only that branch. On RESTORE the mirror is the source of truth and the primary is
    empty, so "not in canonical" describes every page here and means nothing — running
    the same step then would be a mass quarantine of the only surviving corpus. The
    classifier independently refuses that (an empty canonical id-set makes every page
    unknown), but the call site does not rely on that second line of defence.

    It mirrors NOTES only (``_MIRROR_IGNORE``) — never the transaction staging tree, never
    the memgrep index. See that constant for why copying them is actively harmful.
    """
    primary = resolve_user_dir()
    mirror = resolve_user_mirror_dir()
    try:
        if _dir_has_memory(primary):
            mirror.mkdir(parents=True, exist_ok=True)
            shutil.copytree(primary, mirror, dirs_exist_ok=True, ignore=_MIRROR_IGNORE)
            # The copy is additive, so a canonical DELETE never reaches the mirror
            # (janitor#146/#156): the page strands here, collides on atom id, and a
            # later restore resurrects a page that was deliberately consolidated away.
            # Park only the ones proven redundant; anything unexplained stays put.
            _quarantine_superseded_orphans(primary, mirror)
            return "mirrored"
        if _dir_has_memory(mirror):
            primary.mkdir(parents=True, exist_ok=True)
            shutil.copytree(mirror, primary, dirs_exist_ok=True, ignore=_MIRROR_IGNORE)
            return "restored"
    except Exception:  # noqa: BLE001 -- a backup hiccup must never break session start
        # DELIBERATELY broader than OSError. Both mirror calls in on-session-start.py are
        # bare calls with no try/except of their own, so anything escaping here kills
        # SESSION START for every project on this machine — an infinitely worse outcome
        # than a skipped backup. `_early_log`'s docstring writes out the same reasoning: a
        # fault in a best-effort safety net must never become the new way session start
        # breaks. OSError alone left every non-OSError bug (a TypeError on a surprising
        # path shape, a ValueError from a decode) as a session-start killer.
        return None
    return None


# The LOCAL-design mirror dir NAME under the janitor's plugin DATA dir (sibling of the
# USER-memory mirror above, same rationale: a place the harness's own housekeeping never
# reaches). Per-project sub-namespaced by ``project_slug`` — see resolve_local_design_mirror_dir.
_LOCAL_DESIGN_MIRROR_DIRNAME = "local-design-mirror"

# design/ holds exactly these four lifecycle subdirs per the TRDD rules
# (``trdd-approval-tiers.md`` / ``trdd-design-tasks.md``). Naming them explicitly — rather
# than mirroring the whole ``design/`` tree — means only real TRDD ``*.md`` files are ever
# copied, never some unrelated file a future convention drops next to them.
_DESIGN_LIFECYCLE_SUBDIRS = ("proposals", "tasks", "archived", "refused")


def resolve_local_design_dir_for(project_dir: str) -> Path:
    """The LOCAL-scope TRDD ``design/`` dir of an EXPLICIT project path — sibling of
    ``resolve_local_dir_for``'s ``memory/``, same harness slug rules. Not created."""
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    return home / ".claude" / "projects" / project_slug(project_dir) / "design"


def resolve_local_design_dir() -> Path:
    """The current project's LOCAL-scope TRDD ``design/`` dir. Not created."""
    return resolve_local_design_dir_for(_project_dir())


def resolve_local_design_mirror_dir() -> Path:
    """The uninstall/cleanup-surviving MIRROR of the current project's LOCAL ``design/``
    TRDDs: ``<plugin DATA dir>/local-design-mirror/<slug>/``.

    ``~/.claude/projects/<slug>/`` also holds Claude Code's session ``.jsonl`` transcripts
    and is swept by the harness's own ``cleanupPeriodDays`` housekeeping. CC 2.1.228 carved
    ``memory/`` out of that sweep (after it was found deleting files inside it — the reason
    ``resolve_user_mirror_dir``/``sync_user_memory_mirror`` exist), but ``design/`` got no
    such carve-out and has no backup of its own — so a project's LOCAL TRDDs (proposals,
    open tasks, the archive, refusals) are exposed to the exact same silent deletion
    ``memory/`` used to suffer, with nothing protecting them. This mirror applies the same
    pattern to that gap: kept OUTSIDE ``~/.claude/projects/`` (the sweep never reaches it),
    synced on every session start, and used to RESTORE the primary if the sweep (or anything
    else) empties it. Not created.
    """
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    slug = project_slug(_project_dir())
    return (
        home / ".claude" / "plugins" / "data" / JANITOR_DATA_DIR_NAME
        / _LOCAL_DESIGN_MIRROR_DIRNAME / slug
    )


def _dir_has_design_md(d: Path) -> bool:
    """True iff ``d`` (a ``design/`` root) holds at least one ``*.md`` TRDD anywhere under
    its four lifecycle subdirs. Decides the sync DIRECTION (mirrors ``_dir_has_memory``'s
    role for the USER mirror) — an empty scaffold (subdirs exist, no ``.md`` inside) must
    read as "nothing here" or a wipe could never be detected and restored from.
    """
    if not d.is_dir():
        return False
    for sub in _DESIGN_LIFECYCLE_SUBDIRS:
        subdir = d / sub
        if not subdir.is_dir():
            continue
        for p in subdir.rglob("*.md"):
            if p.is_file():
                return True
    return False


def _ignore_non_md(_dirpath: str, names: list[str]) -> list[str]:
    """``shutil.copytree`` ignore-callback: skip every entry that is neither a directory
    (so nested structure under a lifecycle subdir is preserved) nor a ``*.md`` file — the
    design mirror carries TRDDs only, nothing else that might land next to them."""
    skip: list[str] = []
    for name in names:
        full = os.path.join(_dirpath, name)
        if os.path.isdir(full) or name.endswith(".md"):
            continue
        skip.append(name)
    return skip


def _copy_design_subdirs(src_root: Path, dst_root: Path) -> None:
    """Copy each lifecycle subdir present under ``src_root`` into ``dst_root``, ``*.md``
    files only, additive (never removes a file already at the destination — including one
    the destination has that the source lacks)."""
    for sub in _DESIGN_LIFECYCLE_SUBDIRS:
        src = src_root / sub
        if not src.is_dir():
            continue
        dst = dst_root / sub
        dst.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=_ignore_non_md)


def sync_local_design_mirror() -> str | None:
    """Keep the LOCAL-scope ``design/`` TRDD mirror in step with the current project's
    primary (see ``resolve_local_design_mirror_dir`` for why this exists). Returns
    ``"mirrored"`` / ``"restored"`` when it acted, else None.

    Modelled directly on ``sync_user_memory_mirror`` — same two directions, same
    additive-only / never-delete / fail-open discipline. It differs in scope (per-project
    LOCAL ``design/``, not the cross-project USER memory corpus) and in content shape (TRDD
    ``*.md`` files under four fixed lifecycle subdirs — no atom-id/supersession bookkeeping;
    TRDDs don't have that concept, so there is no orphan-quarantine step here).

    - **primary has TRDDs** -> SYNC primary->mirror (refresh the backup). Steady state.
    - **primary EMPTY but mirror has TRDDs** -> RESTORE mirror->primary. Recovery path: the
      harness swept ``design/`` (or anything else wiped it) and the mirror repopulates it.
    - **neither has TRDDs** -> nothing to do (fresh project, or design/ never used LOCAL).

    Additive (``copytree(dirs_exist_ok=True)``): NEVER deletes a file from either side, even
    one present only on the other side. Best-effort — any OSError is swallowed so a mirror
    hiccup can never break session start.
    """
    primary = resolve_local_design_dir()
    mirror = resolve_local_design_mirror_dir()
    try:
        if _dir_has_design_md(primary):
            _copy_design_subdirs(primary, mirror)
            return "mirrored"
        if _dir_has_design_md(mirror):
            _copy_design_subdirs(mirror, primary)
            return "restored"
    except Exception:  # noqa: BLE001 -- a backup hiccup must never break session start
        # DELIBERATELY broader than OSError. Both mirror calls in on-session-start.py are
        # bare calls with no try/except of their own, so anything escaping here kills
        # SESSION START for every project on this machine — an infinitely worse outcome
        # than a skipped backup. `_early_log`'s docstring writes out the same reasoning: a
        # fault in a best-effort safety net must never become the new way session start
        # breaks. OSError alone left every non-OSError bug (a TypeError on a surprising
        # path shape, a ValueError from a decode) as a session-start killer.
        return None
    return None


def resolve_wiki_dir(scope_root: Path) -> Path:
    """The curated WIKI sub-namespace of a memory scope: ``<scope_root>/wikimem``.

    (The name is ``WIKI_SUBDIR``. This line said ``wiki`` — the pre-2026-07-08 name, kept
    in the prose after the rename landed in the constant. A docstring naming a path that
    does not exist is worse than none: it is the copy a reader trusts without checking.)

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

    Handles BOTH block-style (``tier: hub`` on its own line, nested or top-level) AND
    flow-style (``metadata: {node_type: memory, tier: hub}`` all on one line) —
    see ``_FLOW_METADATA_KEY_RE`` (janitor#212).
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
        # L-1 (wikimem audit): require a ':' — a bare list item ("  - tier") has NO
        # key; without this a raw buffer note tagged `- tier` classified CURATED and
        # harvest silently skipped mirroring it.
        if ":" not in ln:
            continue
        key = ln.split(":", 1)[0].strip().lstrip("-").strip()
        if key in _WIKIMEM_ONLY_FM_KEYS:
            return True
        if key == "metadata" and _FLOW_METADATA_KEY_RE.search(ln.split(":", 1)[1]):
            return True  # flow-style: the wikimem-only key sits INSIDE `metadata: {...}`
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
