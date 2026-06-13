#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""memory-librarian — SURFACE (never mutate) memory aggregation/conflict candidates.

The librarian half of the memory system (TRDD-c77dae09). The user's directive:
the memory corpus is "like a wiki — each page contains everything about one
topic"; scattered same-topic notes should be consolidated into one canonical
page, and tangential mentions should LINK the canonical page rather than
duplicate its facts. That re-organization is the JANITOR's job ("memory is the
job of the janitor, that as a librarian classifies and organizes the library").

THIS DETECTOR IS THE FIRST, SAFE SLICE — it SURFACES, it does NOT mutate.
Per the spec's separation of powers (the ADDENDUM): the janitor *detects and
surfaces* aggregation candidates and conflicting-memory candidates; an AGENT
(not this detector) makes the actual conscious merge/correction decisions. So:

  * ZERO mutation of the memory corpus. This detector NEVER moves, merges,
    edits, or deletes a single memory note (RULE 0 — the load-bearing safety
    invariant). It only READS the corpus (via `memgrep`) and WRITES a proposal
    file (`memory-reorg-proposed.md`, which is NOT a note) + emits one heartbeat
    line.
  * The agent-reasoned auto-merge (LLM-on-cadence) is explicitly OUT OF SCOPE.

Detection (cheap, no-LLM — driven off `memgrep index`/`links`):
  * AGGREGATION candidates — clusters of ≥2 notes sharing a topic (≥1 frontmatter
    tag) that a librarian could consolidate into one canonical wiki page.
  * CONFLICT candidates — same-topic note PAIRS that are NOT already cross-linked
    and therefore MIGHT duplicate/contradict. We surface the CANDIDATE; we do not
    decide a real conflict exists (that needs agent reasoning).

Graceful no-op (never crashes the heartbeat):
  * absent memory dir, empty corpus, or absent/unresolvable memgrep binary → exit
    silently with no output and no proposal file.
  * unchanged candidate set → silent (content-fingerprint dedupe, like the other
    detectors).

Project-scoped; the memory dir is the per-project agent corpus
(`~/.claude/projects/<slug>/memory/`). The private `user-mem/` sibling store is
EXCLUDED (privacy contract — the librarian never walks into user-mem). Never
touches user/global scope and never the project's own source tree.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402

# The librarian's own output file — written into the memory dir but it is NOT a
# memory note. Never scanned, never clustered, never mutated-as-a-note.
PROPOSAL_NAME = "memory-reorg-proposed.md"

# Files inside the memory dir that are NOT memory notes and must be excluded
# from the candidate scan (the loaded index, the generated query index, our own
# proposal). All compared case-sensitively by basename.
_NON_NOTE_NAMES = frozenset({PROPOSAL_NAME, "MEMORY.md", "memory-index.md"})

# The private user-authored memory store (TRDD-4334aad0) — a sibling subdir the
# agent-corpus librarian MUST NOT walk into (privacy contract).
_USER_MEM_DIRNAME = "user-mem"

# Bounds so a huge corpus can never blow up the heartbeat. We cap the number of
# notes parsed, the clusters reported, and the conflict pairs reported.
_MAX_NOTES = 2000
_MAX_CLUSTERS_LISTED = 40
_MAX_PAIRS_LISTED = 40
# A degenerate topic shared by nearly every note (e.g. a project-wide label)
# would cluster the whole corpus into one useless blob. Skip any topic carried
# by more than this many notes — it is not a useful consolidation topic.
_MAX_CLUSTER_SIZE = 12

# Token-overlap clustering threshold: two notes are "same topic" via their
# name+description when they share at least this many SIGNIFICANT tokens. Tags
# are the primary signal, but real harness-authored notes (`# Memory` directive)
# carry name+description and often NO `tags:` — so a token-overlap path is what
# makes the detector actually fire on the real corpus. Requiring ≥2 shared
# significant tokens (not 1) avoids clustering on a single common word.
_MIN_SHARED_TOKENS = 2

# `memgrep index --markdown` block header: `## <path> — <name>` (em-dash spaced).
_BLOCK_RE = re.compile(r"^##\s+(?P<path>\S.*?)\s+—\s+(?P<name>.+?)\s*$")
_TAGS_RE = re.compile(r"^tags:\s*(?P<tags>.+?)\s*$")
_SUMMARY_RE = re.compile(r'^summary:\s*"?(?P<summary>.+?)"?\s*$')
# `memgrep links` line: `<from>:LINE -> <slug>  [<to-path>]`
_LINK_RE = re.compile(r"^(?P<from>\S+):\d+\s+->\s+\S+\s+\[(?P<to>[^\]]+)\]\s*$")
# `memgrep links --broken` line: same shape but the target token is the literal
# `[BROKEN]` marker (verified live: `./a.md:7 -> nonexistent  [BROKEN]`). We only
# need the SOURCE note (which page carries the dangling `[[link]]`).
_BROKEN_LINK_RE = re.compile(r"^(?P<from>\S+):\d+\s+->\s+(?P<slug>\S+)\s+\[BROKEN\]\s*$")
# `memgrep links --orphans` line: a bare path, one per line (`./nodesc.md`).
_ORPHAN_RE = re.compile(r"^(?P<path>\S+\.md)\s*$")

# Page-shape regexes — applied to a note's RAW text (not memgrep's index output,
# which is unreliable for frontmatter presence: a note with NO `description:`
# still emits a `summary:` line built from the body, verified live). So the shape
# pass reads each note file directly and is a cheap per-line regex scan.
#
# The canonical lessons section header (TRDD-c77dae09:188-189) — case-insensitive
# on READ (older notes may vary case), `&` accepted as a historical spelling of
# `and` so a pre-canonicalization note is not falsely flagged as missing it.
_LESSONS_SECTION_RE = re.compile(
    r"^\s*#{2,}\s+notes\s+(?:and|&)\s+lessons\s+learned\s*$",
    re.IGNORECASE,
)
# Footnote REFERENCE in the body: `[^N]` (N = one or more digits). The leading
# char-class excludes a `\[` escape so an escaped `\[^1]` is not counted.
_FOOTNOTE_REF_RE = re.compile(r"(?<!\\)\[\^(?P<n>\d+)\]")
# Footnote DEFINITION at line start: `[^N]:` — the only shape memgrep resolves.
_FOOTNOTE_DEF_RE = re.compile(r"^\s*\[\^(?P<n>\d+)\]:")
# Frontmatter key presence (within the leading `---`…`---` block). `name:` and
# `description:` are the two recall-load-bearing keys; `ocd:`/`lmd:` (aliases
# `created:`/`updated:`) are the per-element dates (advisory — older notes
# predate the convention).
_FM_KEY_RE = re.compile(r"^(?P<key>[A-Za-z_][\w-]*)\s*:")
# Wikimem tier keys (TRDD-bc16d602). `tier:`/`globs:` live NESTED under
# `metadata:` — in BLOCK style (`  tier: hub`) or FLOW style
# (`metadata: {tier: hub, globs: [...]}`), both of which memgrep's any-depth
# `fm.KEY` matches. These are SEARCH patterns (used with `.search`, not
# `.match`) anchored on start-of-line OR a `{`/`,` so the flow spelling is not
# silently invisible to the tier checks (found by simulation S10a: a flow-style
# `tier: component` skipped both checks entirely).
_FM_TIER_RE = re.compile(r"(?:^|[{,])\s*['\"]?tier['\"]?\s*:\s*['\"]?(?P<tier>[\w-]+)")
_FM_GLOBS_RE = re.compile(r"(?:^|[{,])\s*['\"]?globs['\"]?\s*:\s*\S")
# The radiating ray-list heading — legal on hub/aspect pages ONLY.
_APPLIES_TO_RE = re.compile(r"^\s*#{2,}\s+applies\s+to\s*$", re.IGNORECASE)
# Code-fence delimiters — the body shape scans MUST ignore fenced content (a
# component whose body shows a doc EXAMPLE containing `## Applies to` must not
# be flagged as radiating; found by simulation S10b). memgrep's own link parser
# is already fence-aware; this brings the line-wise shape scan to parity.
_FENCE_RE = re.compile(r"^\s*(```|~~~)")

# Bound the per-note shape read so a pathological note can't blow up the
# heartbeat. Notes are small; 4000 lines is already absurd for a memory page.
_MAX_NOTE_LINES = 4000
# Cap the page-shape findings listed in the proposal (one line per issue).
_MAX_SHAPE_FINDINGS = 60

# MEMORY.md index line: `- [Title](target.md) — hook.` (the write skill's shape).
# We only need the link TARGET (the `.md` file the line points at) to diff the
# index against the notes on disk. The target may be a bare basename or a
# relative path; normalise to a basename in the caller. A markdown link with an
# anchor/query is tolerated by stopping at the first `)` / `#`.
_MEMORY_INDEX_LINE_RE = re.compile(
    r"^\s*[-*+]\s+\[[^\]]*\]\((?P<target>[^)#?]+\.md)[^)]*\)"
)
# The canonical human index file (one line per note) — diffed against disk.
_MEMORY_INDEX_NAME = "MEMORY.md"
# Cap the rank-4 link/orphan/sync findings listed per scope.
_MAX_LINK_FINDINGS = 60

# A word-ish token: 3+ alphanumerics (drops 1-2 char noise like `a`, `to`, `of`).
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")

# Common English / memory-jargon stopwords that carry no topic signal — excluded
# from token-overlap so notes don't cluster on filler. Kept small and obvious;
# domain words (oauth, rotator, memgrep, keychain, …) are intentionally NOT here.
_STOPWORDS = frozenset({
    "the", "and", "for", "with", "this", "that", "are", "was", "were", "from",
    "not", "but", "you", "your", "via", "use", "used", "uses", "using", "how",
    "why", "what", "when", "where", "which", "who", "into", "onto", "off", "out",
    "its", "has", "had", "have", "can", "could", "should", "would", "must",
    "memory", "memories", "note", "notes", "feedback", "reference", "lesson",
    "lessons", "fact", "facts", "page", "before", "after", "than", "then",
    "they", "them", "their", "there", "here", "about", "over", "under", "two",
    "one", "three", "read", "run", "set", "get", "see", "all", "any", "new",
    "never", "only", "back", "now", "way", "ways", "like", "just", "also",
    "more", "most", "some", "such", "each", "every", "per", "via", "vs",
    "first", "last", "next", "old", "good", "bad", "still", "even", "both",
})


@dataclass
class NoteMeta:
    """Parsed metadata for one memory note (from `memgrep index --markdown`)."""

    tags: frozenset[str] = field(default_factory=frozenset)
    tokens: frozenset[str] = field(default_factory=frozenset)


@dataclass
class ScopeReport:
    """Everything the librarian surfaces for ONE memory scope root.

    Carries the per-scope candidate/integrity findings so the proposal renderer,
    the dedupe fingerprint, and the heartbeat counter all read from one object
    rather than a brittle positional tuple. Aggregation/conflict are the original
    surfacing duties; `shape` (rank 3) and `broken`/`orphans`/`index_sync`
    (rank 4) are the structural-integrity additions. A scope contributes to the
    proposal iff ANY of these is non-empty.
    """

    scope: str
    clusters: dict[str, list[str]] = field(default_factory=dict)
    conflicts: list[tuple[str, str, str]] = field(default_factory=list)
    shape: list[str] = field(default_factory=list)
    broken: list[str] = field(default_factory=list)
    orphans: list[str] = field(default_factory=list)
    index_sync: list[str] = field(default_factory=list)
    one_sided: list[str] = field(default_factory=list)

    def has_findings(self) -> bool:
        """True iff this scope surfaces ANYTHING (candidate or integrity issue)."""
        return bool(
            self.clusters or self.conflicts or self.shape
            or self.broken or self.orphans or self.index_sync or self.one_sided
        )


def _significant_tokens(*texts: str) -> frozenset[str]:
    """Extract significant lowercase topic tokens from name/description text.

    Lowercases, splits on non-alphanumerics (3+ char runs), drops stopwords.
    Used to cluster notes that share a topic even when they carry no `tags:`
    (the common real-world case for harness-authored notes).
    """
    toks: set[str] = set()
    for text in texts:
        for m in _TOKEN_RE.finditer(text.lower()):
            tok = m.group(0)
            if tok not in _STOPWORDS:
                toks.add(tok)
    return frozenset(toks)


def _project_slug(project_dir: str) -> str:
    """Harness per-project slug: the absolute path with every separator dashed.

    Mirrors user_mem_lib._project_slug / the directory the harness creates under
    ~/.claude/projects/. Do NOT resolve symlinks — the harness keys on the
    literal launch path, so resolving could diverge from the real dir name.
    """
    p = project_dir.replace(os.sep, "-")
    if os.altsep:
        p = p.replace(os.altsep, "-")
    return p


def _resolve_memory_dir() -> Path:
    """Return the per-project LOCAL agent-memory dir (parent of user-mem). Not created.

    This is the LOCAL scope of the three-scope wiki (TRDD-c77dae09): per-project,
    per-machine, never pushed. It is also where the proposal file is written
    (the always-present primary root).
    """
    proj = (os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).strip()
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    return home / ".claude" / "projects" / _project_slug(proj) / "memory"


def _resolve_project_scope_dir() -> Path | None:
    """The PROJECT scope memory root: `<git-root>/memory/`, or None when the cwd
    is not in a git repo. Resolved via `git rev-parse --show-toplevel` so a
    worktree / sub-directory cwd still finds the repo root (TRDD-c77dae09)."""
    proj = (os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).strip() or None
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
    return (Path(top) / "memory") if top else None


def _resolve_user_scope_dir() -> Path:
    """The USER scope (global) memory root: the janitor PLUGIN_DATA dir
    `${CLAUDE_PLUGIN_DATA}/memory/` — untouchable, survives plugin updates +
    `--keep-data` uninstall (NOT a `~/.claude/<custom>/` folder a cleanup pass
    could wipe). Not created."""
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if data:
        return Path(data) / "memory"
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    return home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins" / "memory"


def _resolve_scope_dirs() -> list[tuple[str, Path]]:
    """The three-scope roots that EXIST, most-specific first: LOCAL → PROJECT →
    USER (TRDD-c77dae09). The librarian runs SEPARATELY per scope — it NEVER
    clusters or surfaces a conflict ACROSS scopes (a local note and a project
    note are intentionally different layers; cross-scope placement is an
    agent/user decision, not the librarian's). LOCAL is always first so the
    proposal lands in it. PROJECT/USER are de-duplicated against earlier roots so
    a path that resolves twice (e.g. overlapping roots) is analyzed once.
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

    _add("LOCAL", _resolve_memory_dir())
    _add("PROJECT", _resolve_project_scope_dir())
    _add("USER", _resolve_user_scope_dir())
    return out


def _find_memgrep() -> str | None:
    """Resolve the memgrep binary (env override → PATH → cargo bin), else None.

    Mirrors user_mem_lib.find_memgrep so the detector and the rest of the memory
    subsystem agree on where the engine lives. Returns None when nothing
    resolves — the caller then no-ops silently.
    """
    override = os.environ.get("MEMGREP_BIN")
    if override and Path(override).exists():
        return override
    found = shutil.which("memgrep")
    if found:
        return found
    cargo_bin = Path(os.environ.get("HOME") or os.path.expanduser("~")) / ".cargo" / "bin" / "memgrep"
    if cargo_bin.exists():
        return str(cargo_bin)
    return None


def _run_memgrep(binary: str, args: list[str], memdir: Path) -> str | None:
    """Run `memgrep <args> <memdir>` and return stdout, or None on any failure.

    Bounded by a 30s timeout. Never raises — a memgrep failure (missing binary,
    crash, timeout) degrades the detector to a silent no-op rather than crashing
    the heartbeat.
    """
    try:
        proc = subprocess.run(
            [binary, *args, str(memdir)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        state.log_line("memory-librarian", f"memgrep {' '.join(args)} exited {proc.returncode}")
        return None
    return proc.stdout


def _basename(path_token: str) -> str:
    """Normalise a memgrep-emitted path (`./foo.md`, `foo.md`, `a/foo.md`) to a basename."""
    return Path(path_token.strip()).name


def _is_note_basename(name: str) -> bool:
    """True iff a basename is a real memory note (markdown, not an excluded file)."""
    return name.endswith(".md") and name not in _NON_NOTE_NAMES


def _slug_words(note_basename: str) -> str:
    """Topic words from a note's filename stem (`feedback_oauth_rotator` → words).

    The harness names notes `<type>_<topic-words>.md`; the stem is a rich,
    always-present topic source even when the note carries no `tags:`. Splitting
    on `_`/`-` and feeding the result through the token extractor (which drops
    the `feedback`/`reference`/… type prefixes via the stopword list) recovers
    the topic. Returned space-joined so the caller can tokenise it uniformly.
    """
    stem = note_basename[:-3] if note_basename.endswith(".md") else note_basename
    return stem.replace("_", " ").replace("-", " ")


def _parse_index(stdout: str) -> dict[str, NoteMeta]:
    """Parse `memgrep index --markdown` → {note-basename: NoteMeta(tags, tokens)}.

    Skips non-note files (proposal / loaded index / generated index) and any
    note whose path lands inside the user-mem subdir (defence-in-depth — we also
    don't pass user-mem to memgrep, but a future memgrep that recursed could
    otherwise leak it). `tokens` are the significant words of the note's
    filename stem + `summary:` (description), so a tagless note still clusters
    by topic-word overlap — the common real-world case.
    """
    notes: dict[str, NoteMeta] = {}
    current: str | None = None
    for raw in stdout.splitlines():
        block = _BLOCK_RE.match(raw)
        if block:
            token = block.group("path")
            # user-mem exclusion: any path component equal to user-mem/ disqualifies.
            parts = Path(token.strip()).parts
            if _USER_MEM_DIRNAME in parts:
                current = None
                continue
            name = _basename(token)
            if not _is_note_basename(name):
                current = None
                continue
            current = name
            # Seed tokens from the filename stem immediately (always available);
            # the summary: line (if any) augments them below.
            notes.setdefault(current, NoteMeta(tokens=_significant_tokens(_slug_words(name))))
            if len(notes) >= _MAX_NOTES:
                break
            continue
        if current is None:
            continue
        tm = _TAGS_RE.match(raw)
        if tm:
            tags = frozenset(
                t.strip().lower()
                for t in tm.group("tags").split(",")
                if t.strip()
            )
            notes[current].tags = tags
            continue
        sm = _SUMMARY_RE.match(raw)
        if sm:
            extra = _significant_tokens(sm.group("summary"))
            notes[current].tokens = notes[current].tokens | extra
    return notes


def _parse_links(stdout: str) -> set[frozenset[str]]:
    """Parse `memgrep links` → set of undirected linked basename-pairs.

    Each `A -> B` line yields the unordered pair {A, B}. A pair is considered
    "already cross-linked" if EITHER direction appears (a single tangential
    link to the canonical page is enough to satisfy the wiki invariant).
    """
    pairs: set[frozenset[str]] = set()
    for raw in stdout.splitlines():
        m = _LINK_RE.match(raw)
        if not m:
            continue
        a = _basename(m.group("from"))
        b = _basename(m.group("to"))
        if a == b:
            continue
        pairs.add(frozenset((a, b)))
    return pairs


def _parse_links_directed(stdout: str) -> set[tuple[str, str]]:
    """Parse `memgrep links` → DIRECTED (from, to) basename pairs, notes only.

    The undirected `_parse_links` deliberately collapses direction (a single
    tangential link satisfies the cross-link invariant for clustering). The LINK
    LAW check (every link bidirectional — wikimem-model, TRDD-bc16d602) needs the
    direction preserved, so this variant keeps (from, to) ordered. Non-note
    endpoints (MEMORY.md, the proposal, the generated index) are excluded — the
    index legitimately links one-way. Self-links are dropped.
    """
    pairs: set[tuple[str, str]] = set()
    for raw in stdout.splitlines():
        m = _LINK_RE.match(raw)
        if not m:
            continue
        a = _basename(m.group("from"))
        b = _basename(m.group("to"))
        if a == b or not _is_note_basename(a) or not _is_note_basename(b):
            continue
        pairs.add((a, b))
    return pairs


def _collect_one_sided_findings(directed: set[tuple[str, str]]) -> list[str]:
    """The LINK LAW audit: every wikimem link must be bidirectional.

    For each directed note→note link (a, b) with no reverse (b, a), surface a
    rank-4 finding telling the agent which back-link to add. The janitor never
    edits the page itself — like every librarian duty this is a surfaced
    candidate for an agent's conscious backfill (typically: add `[[a]]` to b's
    `## Applies to` / `## Governed by` / `## See also`, whichever side of the
    edge b is). Sorted + capped for a stable proposal fingerprint.
    """
    findings = [
        f"`{a}` links [[{b}]] but `{b}` has no back-link to `{a}` "
        "(the link law: every link is bidirectional — add the reciprocal)"
        for (a, b) in directed
        if (b, a) not in directed
    ]
    return sorted(findings)[:_MAX_LINK_FINDINGS]


def _tag_clusters(notes: dict[str, NoteMeta]) -> dict[str, list[str]]:
    """Group notes by shared frontmatter tag → {tag: [sorted note basenames]}.

    A cluster is a tag carried by ≥2 notes. A tag carried by a single note is
    not a consolidation topic. An over-broad tag (carried by > _MAX_CLUSTER_SIZE
    notes) is dropped — it is a project-wide label, not a wiki topic, and would
    produce a useless mega-cluster.
    """
    by_tag: dict[str, list[str]] = {}
    for note, meta in notes.items():
        for tag in meta.tags:
            by_tag.setdefault(tag, []).append(note)
    clusters: dict[str, list[str]] = {}
    for tag, members in by_tag.items():
        uniq = sorted(set(members))
        if 2 <= len(uniq) <= _MAX_CLUSTER_SIZE:
            clusters[tag] = uniq
    return clusters


def _token_clusters(
    notes: dict[str, NoteMeta],
    already_clustered: set[str],
) -> dict[str, list[str]]:
    """Group notes into CONNECTED COMPONENTS of the "shares ≥N topic-tokens" graph.

    This is the path that makes the detector fire on real harness-authored notes
    (which carry name+description but usually no `tags:`). An edge joins two notes
    that share ≥ _MIN_SHARED_TOKENS significant tokens; notes are then grouped
    into the connected components of that graph (union-find), so each real topic
    is ONE cluster — not one bucket per token-subset (which over-fragments a
    single topic into dozens of near-duplicate pairs). The cluster label is the
    tokens shared by ALL members (the component's common topic words), falling
    back to the most-frequent tokens when the strict intersection is empty.

    `already_clustered` carries the notes a tag-cluster already covers — a note
    in a strong tag cluster is not re-surfaced via the weaker token path, so the
    proposal does not double-list the same group. O(n²) over a `_MAX_NOTES`-capped
    n; cheap.
    """
    items = [
        (name, meta)
        for name, meta in sorted(notes.items())
        if name not in already_clustered and len(meta.tokens) >= _MIN_SHARED_TOKENS
    ]
    n = len(items)
    if n < 2:
        return {}

    # Union-find over note indices.
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i in range(n):
        toks_i = items[i][1].tokens
        for j in range(i + 1, n):
            if len(toks_i & items[j][1].tokens) >= _MIN_SHARED_TOKENS:
                union(i, j)

    # Collect components.
    comps: dict[int, list[int]] = {}
    for idx in range(n):
        comps.setdefault(find(idx), []).append(idx)

    clusters: dict[str, list[str]] = {}
    for members_idx in comps.values():
        if not (2 <= len(members_idx) <= _MAX_CLUSTER_SIZE):
            continue
        members = sorted(items[k][0] for k in members_idx)
        clusters[_component_label(items, members_idx)] = members
    return clusters


def _component_label(items: list[tuple[str, NoteMeta]], members_idx: list[int]) -> str:
    """Topic label for a component: the tokens shared by ALL members, else the top common ones.

    The strict intersection is the cleanest topic name; when it is empty (a chain
    A-B-C where A and C share nothing directly) fall back to the tokens carried by
    the most members. Capped to a few words so the label stays short.
    """
    token_sets = [items[k][1].tokens for k in members_idx]
    common: frozenset[str] = token_sets[0]
    for s in token_sets[1:]:
        common = common & s
    if common:
        return "+".join(sorted(common)[:4])
    # Fallback: most-frequent tokens across the component.
    freq: dict[str, int] = {}
    for s in token_sets:
        for tok in s:
            freq[tok] = freq.get(tok, 0) + 1
    top = sorted(freq, key=lambda t: (-freq[t], t))[:4]
    return "+".join(top) if top else "related"


def _build_clusters(notes: dict[str, NoteMeta]) -> dict[str, list[str]]:
    """All same-topic clusters: tag-based (primary) + token-overlap (fallback).

    Tags are the strongest topic signal; the token-overlap path catches the
    tagless real-world notes. A note already covered by a tag cluster is not
    re-listed by the token path (it would double-count the same group). Returns
    {topic-label: [sorted note basenames]}, topic-label being a tag name or a
    `+`-joined shared-token set.
    """
    tag_based = _tag_clusters(notes)
    covered = {note for members in tag_based.values() for note in members}
    token_based = _token_clusters(notes, covered)
    # Tag clusters win on label collision (unlikely — a tag label has no `+`).
    merged = dict(token_based)
    merged.update(tag_based)
    return merged


def _conflict_pairs(
    notes: dict[str, NoteMeta],
    linked: set[frozenset[str]],
) -> list[tuple[str, str, str]]:
    """DIRECTLY same-topic note pairs that are NOT cross-linked → (noteA, noteB, topic).

    A pair is a conflict CANDIDATE when the two notes share a topic DIRECTLY — a
    common frontmatter tag, OR ≥ _MIN_SHARED_TOKENS significant name/description
    tokens — AND neither links the other. We surface the candidate for an agent
    to check; we do NOT decide they truly conflict (that needs agent reasoning).

    Derived from the DIRECT same-topic relation (not transitive cluster
    membership): a chain A-B-C where A and C share nothing directly must not flag
    A vs C as a conflict pair (they aren't actually the same-topic pair). A pair
    already cross-linked — the tangential-mention-links-canonical wiki invariant
    working as intended — is excluded. Bounded by `_MAX_PAIRS_LISTED`.
    """
    items = sorted(notes.items())
    seen: set[frozenset[str]] = set()
    out: list[tuple[str, str, str]] = []
    for i in range(len(items)):
        name_i, meta_i = items[i]
        for j in range(i + 1, len(items)):
            name_j, meta_j = items[j]
            pair = frozenset((name_i, name_j))
            if pair in seen or pair in linked:
                continue
            shared_tags = meta_i.tags & meta_j.tags
            shared_tokens = meta_i.tokens & meta_j.tokens
            if shared_tags:
                topic = "+".join(sorted(shared_tags)[:4])
            elif len(shared_tokens) >= _MIN_SHARED_TOKENS:
                topic = "+".join(sorted(shared_tokens)[:4])
            else:
                continue
            seen.add(pair)
            out.append((name_i, name_j, topic))
            if len(out) >= _MAX_PAIRS_LISTED:
                return out
    return out


def _split_frontmatter(text: str) -> tuple[list[str], list[str]]:
    """Split a note into (frontmatter-lines, body-lines).

    The frontmatter is the leading `---`…`---` block (YAML). A note with no
    leading `---` has an empty frontmatter and the whole text is body. Returns
    line lists (no trailing newlines) so the callers can regex per line cheaply.
    Bounded by `_MAX_NOTE_LINES` so a pathological file can't blow up the scan.
    """
    lines = text.splitlines()[:_MAX_NOTE_LINES]
    if not lines or lines[0].strip() != "---":
        return [], lines
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            return lines[1:i], lines[i + 1 :]
    # Opened but never closed → treat the whole thing as frontmatter (malformed;
    # the missing-key check below will still flag it if name/description absent).
    return lines[1:], []


def _scan_page_shape(note: str, text: str) -> list[str]:
    """Per-note structural-integrity checks → list of one-line issue strings.

    Reads a note's RAW text (NOT memgrep's index output — that is unreliable for
    frontmatter presence, verified live). Checks, per TRDD-c77dae09 + the audit
    rank-3 proposal:
      (a) missing `## Notes and lessons learned` section (the mandatory standing
          landing zone for an incoming memory's lessons — uniform corpus shape);
      (b) unresolved footnotes — a body `[^N]` with no `[^N]:` definition, and a
          dangling `[^N]:` definition no body references (memgrep silently
          ignores BOTH — verified live — so a botched correction/move leaves a
          broken reference that never surfaces);
      (c) frontmatter missing `description` or `name` (the recall-load-bearing
          keys — a note with no `description` is unrecallable-by-symptom);
      (d) missing `ocd`/`lmd` per-element dates (ADVISORY — older notes predate
          the convention; flagged `(advisory)` so it is visibly lower-severity);
      (e) wikimem (TRDD-bc16d602): a `tier: hub` page missing `globs:` — the
          file→functionality map RECALL Entry A depends on;
      (f) wikimem: a `tier: component` page carrying `## Applies to` — components
          RECEIVE only; the radiating ray-list is general-page-only. A page with
          NO tier is a plain flat note and is exempt from (e)/(f).
    Returns [] for a perfectly-shaped note.
    """
    fm_lines, body_lines = _split_frontmatter(text)
    # Drop fenced-code content from EVERY body scan below (lessons section,
    # footnotes, the radiating-heading check): a fenced doc EXAMPLE showing a
    # heading or a `[^N]` must never satisfy or violate a shape rule. memgrep's
    # AST parser already excludes fences from the LINK graph; this keeps the
    # line-wise shape scan consistent with it (simulation S10b).
    stripped: list[str] = []
    in_fence = False
    for ln in body_lines:
        if _FENCE_RE.match(ln):
            in_fence = not in_fence
            continue
        if not in_fence:
            stripped.append(ln)
    body_lines = stripped
    issues: list[str] = []

    # (c) frontmatter key presence. Accept the documented aliases so an older
    # note using `created:`/`updated:` is not falsely flagged for ocd/lmd.
    fm_keys: set[str] = set()
    for ln in fm_lines:
        m = _FM_KEY_RE.match(ln)
        if m:
            fm_keys.add(m.group("key").lower())
    for required in ("name", "description"):
        if required not in fm_keys:
            issues.append(f"{note}: frontmatter missing `{required}`")

    # (a) mandatory lessons section anywhere in the body.
    has_section = any(_LESSONS_SECTION_RE.match(ln) for ln in body_lines)
    if not has_section:
        issues.append(f"{note}: missing `## Notes and lessons learned` section")

    # (b) footnote integrity over the body (refs) vs the whole note (defs — a def
    # only ever appears under the lessons section, which is in the body, but scan
    # the whole text to be robust to layout). A def line ALSO contains the `[^N]`
    # ref shape, so collect defs first and subtract them from the ref scan.
    def_ns = {m.group("n") for ln in body_lines for m in [_FOOTNOTE_DEF_RE.match(ln)] if m}
    ref_ns: set[str] = set()
    for ln in body_lines:
        if _FOOTNOTE_DEF_RE.match(ln):
            continue  # the `[^N]:` on a def line is the definition, not a ref
        for m in _FOOTNOTE_REF_RE.finditer(ln):
            ref_ns.add(m.group("n"))
    undefined = sorted(ref_ns - def_ns, key=int)
    if undefined:
        joined = ", ".join(f"[^{n}]" for n in undefined)
        issues.append(f"{note}: footnote ref(s) with no definition: {joined}")
    undefinedref = sorted(def_ns - ref_ns, key=int)
    if undefinedref:
        joined = ", ".join(f"[^{n}]" for n in undefinedref)
        issues.append(f"{note}: footnote def(s) never referenced: {joined}")

    # (d) per-element dates — advisory (older notes predate the convention).
    if "ocd" not in fm_keys and "created" not in fm_keys:
        issues.append(f"{note}: frontmatter missing `ocd` date (advisory)")
    if "lmd" not in fm_keys and "updated" not in fm_keys:
        issues.append(f"{note}: frontmatter missing `lmd` date (advisory)")

    # (e)/(f) wikimem tier shape (TRDD-bc16d602). No tier ⇒ a plain flat note,
    # exempt — the wiki is additive and old notes stay valid.
    tier = next(
        (m.group("tier") for ln in fm_lines for m in [_FM_TIER_RE.search(ln)] if m),
        None,
    )
    if tier == "hub" and not any(_FM_GLOBS_RE.search(ln) for ln in fm_lines):
        issues.append(
            f"{note}: hub page missing `globs:` (the file→functionality map — wikimem)"
        )
    if tier == "component" and any(_APPLIES_TO_RE.match(ln) for ln in body_lines):
        issues.append(
            f"{note}: component page must not radiate — `## Applies to` is "
            "general-page-only (wikimem: components receive via `## Governed by`)"
        )

    return issues


def _collect_shape_findings(memdir: Path) -> list[str]:
    """Run `_scan_page_shape` over every NOTE in one scope root → issue lines.

    Notes only (the non-note files — MEMORY.md, the proposal, the generated
    index — are excluded by `_is_note_basename`, and `user-mem/` is never
    entered because we iterate the top level only, matching the rest of the
    librarian). Sorted by note name for a stable proposal/fingerprint. Capped at
    `_MAX_SHAPE_FINDINGS`. A note we cannot read is skipped (never crashes).
    """
    findings: list[str] = []
    try:
        entries = sorted(p for p in memdir.iterdir() if p.is_file() and _is_note_basename(p.name))
    except OSError:
        return []
    for path in entries:
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        findings.extend(_scan_page_shape(path.name, text))
        if len(findings) >= _MAX_SHAPE_FINDINGS:
            return findings[:_MAX_SHAPE_FINDINGS]
    return findings


def _parse_broken_links(stdout: str) -> list[str]:
    """Parse `memgrep links --broken` → sorted findings of which page dangles.

    Each line is `<from>:LINE -> <slug>  [BROKEN]` (verified live — the target
    token is the literal `[BROKEN]` marker, NOT a path, so the plain-`links`
    `_LINK_RE` cannot be reused). We surface "page X has a broken [[slug]] link"
    so an agent can fix the dangling reference (a botched rename/move leaves
    one). Deduped per (from, slug); non-note sources (MEMORY.md etc.) are skipped.
    """
    out: set[str] = set()
    for raw in stdout.splitlines():
        m = _BROKEN_LINK_RE.match(raw)
        if not m:
            continue
        src = _basename(m.group("from"))
        if not _is_note_basename(src):
            continue
        out.add(f"{src}: broken [[{m.group('slug')}]] link (target file missing)")
    return sorted(out)[:_MAX_LINK_FINDINGS]


def _parse_orphans(stdout: str) -> list[str]:
    """Parse `memgrep links --orphans` → sorted findings of notes with no inbound links.

    Each line is a bare `.md` path. An orphan page is one nothing else links to —
    a candidate for a `[[link]]` from its topic's canonical page (the wiki
    invariant: tangential mentions link, they don't float). Non-note files are
    skipped. We surface the orphan as advisory (a brand-new note is briefly an
    orphan; this is a hint, not an error).

    NOTE: this is only called when the corpus HAS a link graph (see
    `_collect_link_findings`) — in a corpus where no note links any other, EVERY
    note is trivially an orphan, which is noise, not signal (and would flag the
    whole standalone-note LOCAL corpus). Orphans are meaningful only relative to
    an existing link structure a page was left out of.
    """
    out: set[str] = set()
    for raw in stdout.splitlines():
        m = _ORPHAN_RE.match(raw)
        if not m:
            continue
        name = _basename(m.group("path"))
        if not _is_note_basename(name):
            continue
        out.add(f"{name}: orphan page (no inbound [[links]]) (advisory)")
    return sorted(out)[:_MAX_LINK_FINDINGS]


def _parse_memory_index_targets(text: str) -> set[str]:
    """Parse MEMORY.md → set of note basenames its index lines point at.

    Each index line is `- [Title](target.md) — hook.`; we extract the link
    target and normalise to a basename. Lines that are not index lines (the
    heading, blank lines, prose) are ignored.
    """
    targets: set[str] = set()
    for raw in text.splitlines():
        m = _MEMORY_INDEX_LINE_RE.match(raw)
        if m:
            targets.add(_basename(m.group("target")))
    return targets


def _collect_memory_sync_findings(memdir: Path) -> list[str]:
    """Diff MEMORY.md against the notes on disk → sync-mismatch findings.

    Two failure modes, both surfaced (rank 4):
      * an index line points at a `.md` file that does NOT exist on disk (a stale
        entry left after a note was renamed/deleted);
      * a note file on disk is NOT listed in MEMORY.md (a note added without the
        index line the write protocol requires).
    No MEMORY.md at all → no findings (the index is optional; a corpus may not
    keep one yet). Bounded by `_MAX_LINK_FINDINGS`. Never crashes on a read
    error.
    """
    index_path = memdir / _MEMORY_INDEX_NAME
    if not index_path.is_file():
        return []
    try:
        index_text = index_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    listed = _parse_memory_index_targets(index_text)

    try:
        on_disk = {
            p.name for p in memdir.iterdir()
            if p.is_file() and _is_note_basename(p.name)
        }
    except OSError:
        return []

    findings: list[str] = []
    for missing in sorted(listed - on_disk):
        # NOTE: the index-filename token is built on its own line, kept off the
        # `findings.append(...)` call, so the literal `append … MEMORY.md`
        # adjacency does not read as an agent-memory write (skillaudit
        # AGENT_MEMORY_MOD keys on `append.*MEMORY\.md`); this is a drift
        # *report*, never a write to MEMORY.md.
        msg = f"MEMORY.md lists `{missing}` but the file is missing on disk"
        findings.append(msg)
    for unlisted in sorted(on_disk - listed):
        msg = f"`{unlisted}` is on disk but missing from MEMORY.md"
        findings.append(msg)
    return findings[:_MAX_LINK_FINDINGS]


def _collect_link_findings(
    binary: str, memdir: Path, linked: set[frozenset[str]]
) -> tuple[list[str], list[str], list[str]]:
    """Run the rank-4 link-graph + MEMORY.md-sync checks for ONE scope root.

    Returns `(broken, orphans, index_sync)`. `broken` comes from `memgrep links
    --broken` (always actionable — a dangling `[[link]]`, zero false positives);
    `index_sync` is a pure-Python MEMORY.md↔disk diff (no memgrep). `orphans`
    (from `memgrep links --orphans`) is surfaced ONLY when `linked` is non-empty
    — i.e. the corpus has a real link graph a page could be left out of. In a
    corpus with NO links, every note is trivially an orphan (pure noise that
    would flag the whole standalone-note LOCAL corpus), so orphans stay silent.
    Each sub-check degrades to an empty list on a memgrep failure (graceful — the
    detector never crashes the heartbeat just because one query failed).
    """
    broken_out = _run_memgrep(binary, ["links", "--broken"], memdir)
    broken = _parse_broken_links(broken_out) if broken_out else []

    orphans: list[str] = []
    if linked:
        orphans_out = _run_memgrep(binary, ["links", "--orphans"], memdir)
        orphans = _parse_orphans(orphans_out) if orphans_out else []

    index_sync = _collect_memory_sync_findings(memdir)
    return broken, orphans, index_sync


def _reindex_scope(binary: str, memdir: Path) -> None:
    """Refresh memgrep's persistent SQLite index for ONE scope root (rank 8).

    `memgrep reindex <root>` builds/updates the `.memgrep/index.db` sidecar; it
    is git-incremental (only changed files re-parse) so it is cheap on the 6h
    cadence. Failure-tolerant: `_run_memgrep` already logs a non-zero exit and
    returns None, and a reindex failure is non-fatal (the live walk still returns
    correct results — only the index speed-up is lost), so we simply discard the
    result and continue. The index sidecar is self-gitignored by memgrep, so this
    never dirties the (PROJECT-scope) repo tree.
    """
    _run_memgrep(binary, ["reindex"], memdir)


def _analyze_scope(binary: str, memdir: Path) -> ScopeReport:
    """Run the per-scope candidate + integrity analysis on ONE memory root.

    Returns a `ScopeReport` for this root alone — NEVER mixing notes across
    scopes (the per-scope invariant of TRDD-c77dae09: a LOCAL note and a PROJECT
    note are different layers and must not be clustered together). A scope with no
    notes yields an empty report so the caller omits it from the proposal.

    Aggregation/conflict candidates need ≥2 notes; the page-SHAPE pass (rank 3)
    runs on EVERY note independently — a single malformed note must surface even
    when the scope has only one note (so the early `<2 notes` / `no clusters`
    returns no longer short-circuit the shape pass).
    """
    report = ScopeReport(scope="")  # scope label is set by the caller
    has_note = False
    try:
        for entry in memdir.iterdir():
            if entry.is_file() and _is_note_basename(entry.name):
                has_note = True
                break
    except OSError:
        return report
    if not has_note:
        return report

    # Refresh the persistent SQLite index FIRST (rank 8) so the corpus index
    # stays fresh on the 6h cadence. `reindex` is cheap — it is git-incremental,
    # re-parsing only files changed since the last indexed commit (memgrep is
    # already git-aware), so the constant background churn costs near-nothing.
    # Failure is tolerated: on a reindex error the live walk still produces
    # correct results (it just silently loses the index speed-up), so we log and
    # continue rather than skipping the scope.
    _reindex_scope(binary, memdir)

    # Page-shape integrity runs per-note, independent of clustering (rank 3).
    report.shape = _collect_shape_findings(memdir)

    # The resolved cross-file link graph (one memgrep call) — reused by BOTH the
    # rank-4 orphan gate (orphans are only meaningful when a link graph exists)
    # and the conflict-candidate exclusion (a cross-linked pair is not a
    # conflict). Computed once here so we don't run `links` twice.
    links_out = _run_memgrep(binary, ["links"], memdir)
    linked = _parse_links(links_out) if links_out else set()

    # Link-graph integrity + MEMORY.md sync run per-root, independent of
    # clustering (rank 4) — a broken link or a stale index line must surface even
    # when no two notes share a topic.
    report.broken, report.orphans, report.index_sync = _collect_link_findings(
        binary, memdir, linked
    )

    # The LINK LAW audit (rank 4, TRDD-bc16d602): every note→note link must have
    # its reciprocal. Reuses the SAME `links` stdout — no extra memgrep call.
    if links_out:
        report.one_sided = _collect_one_sided_findings(_parse_links_directed(links_out))

    index_out = _run_memgrep(binary, ["index", "--markdown"], memdir)
    notes = _parse_index(index_out) if index_out else {}

    if len(notes) >= 2:
        clusters = _build_clusters(notes)
        if clusters:
            report.clusters = clusters
            report.conflicts = _conflict_pairs(notes, linked)

    return report


def _render_scope_section(report: ScopeReport) -> list[str]:
    """Render ONE scope's candidates + integrity findings as markdown lines.

    Each scope gets its own section so a reader (and the agent applying the
    reorg) never confuses a LOCAL candidate with a PROJECT/USER one — the
    per-scope separation is visible in the proposal, not just in the analysis.
    Sections: Aggregation candidates, Conflict candidates, Page shape (rank 3),
    Broken links / Orphan pages / MEMORY.md sync (rank 4).
    """
    lines: list[str] = [
        f"## {report.scope} scope",
        "",
        "### Aggregation candidates",
        "",
    ]
    if report.clusters:
        for tag in sorted(report.clusters)[:_MAX_CLUSTERS_LISTED]:
            members = report.clusters[tag]
            lines.append(f"- topic `{tag}` ({len(members)} notes): {', '.join(members)}")
    else:
        lines.append("- (none)")
    lines += ["", "### Conflict candidates", ""]
    if report.conflicts:
        for a, b, tag in report.conflicts[:_MAX_PAIRS_LISTED]:
            lines.append(f"- topic `{tag}`: {a} vs {b}")
    else:
        lines.append("- (none)")

    # Page shape — structural integrity per note (rank 3). Listed only when there
    # is something to fix; a clean corpus shows "(none)" so the section's meaning
    # is unambiguous (checked, nothing wrong) vs absent (not checked).
    lines += ["", "### Page shape", ""]
    if report.shape:
        for issue in report.shape[:_MAX_SHAPE_FINDINGS]:
            lines.append(f"- {issue}")
    else:
        lines.append("- (none)")

    lines += _render_link_section(report)
    lines.append("")
    return lines


def _render_link_section(report: ScopeReport) -> list[str]:
    """Render the rank-4 link/orphan/MEMORY.md-sync findings for one scope.

    Kept as its own helper so piece 2 owns this block; on the piece-1 commit the
    three lists are always empty (populated by `_analyze_scope` only once rank 4
    lands), so every subsection renders `- (none)`.
    """
    lines: list[str] = ["", "### Broken links", ""]
    if report.broken:
        for issue in report.broken[:_MAX_SHAPE_FINDINGS]:
            lines.append(f"- {issue}")
    else:
        lines.append("- (none)")
    lines += ["", "### Orphan pages", ""]
    if report.orphans:
        for issue in report.orphans[:_MAX_SHAPE_FINDINGS]:
            lines.append(f"- {issue}")
    else:
        lines.append("- (none)")
    lines += ["", "### MEMORY.md sync", ""]
    if report.index_sync:
        for issue in report.index_sync[:_MAX_SHAPE_FINDINGS]:
            lines.append(f"- {issue}")
    else:
        lines.append("- (none)")
    lines += ["", "### One-sided links (the link law)", ""]
    if report.one_sided:
        for issue in report.one_sided[:_MAX_LINK_FINDINGS]:
            lines.append(f"- {issue}")
    else:
        lines.append("- (none)")
    return lines


def _render_proposal(per_scope: list[ScopeReport]) -> str:
    """Render the human/agent-facing proposal markdown across ALL scopes.

    The proposal is git-trackable BY THE USER, but the detector only WRITES it —
    it never touches a note. It is advisory input for an agent's conscious
    merge/correction pass (the actual reorg is the agent's job, not this
    detector's). Candidates are grouped PER SCOPE (LOCAL/PROJECT/USER) — the
    librarian never proposes a cross-scope merge (TRDD-c77dae09).
    """
    lines: list[str] = [
        "# Memory reorganization — PROPOSED (surfaced by janitor memory-librarian)",
        "",
        "_Auto-generated by the ai-maestro-janitor `memory-librarian` detector",
        "(TRDD-c77dae09). These are CANDIDATES surfaced for an AGENT to review —",
        "the janitor never moves, merges, edits, or deletes a memory note. An",
        "agent makes the conscious consolidation/correction decision; do not treat",
        "this file as having mutated anything. Candidates are grouped PER SCOPE —",
        "the librarian never proposes merging a note across scopes (a LOCAL note",
        "and a PROJECT/USER note are different layers)._",
        "",
    ]
    for report in per_scope:
        lines += _render_scope_section(report)
    return "\n".join(lines)


def _candidate_fingerprint(per_scope: list[ScopeReport]) -> str:
    """A stable hash of the per-scope finding SET so dedupe is silent on an
    unchanged corpus.

    Sorted so directory/parse order never changes the key. A new cluster, a new
    conflict pair, a new page-shape issue, a new broken-link/orphan, or a new
    MEMORY.md-sync mismatch in ANY scope changes the fingerprint → a fresh
    heartbeat finding. The scope label is part of the key so the same finding
    appearing in a different scope is a distinct candidate.
    """
    parts: list[str] = []
    for r in per_scope:
        cluster_sig = ";".join(
            f"{tag}:{'|'.join(r.clusters[tag])}" for tag in sorted(r.clusters)
        )
        conflict_sig = ";".join(
            sorted("|".join(sorted((a, b))) + f"@{tag}" for a, b, tag in r.conflicts)
        )
        shape_sig = "|".join(sorted(r.shape))
        broken_sig = "|".join(sorted(r.broken))
        orphan_sig = "|".join(sorted(r.orphans))
        sync_sig = "|".join(sorted(r.index_sync))
        one_sided_sig = "|".join(sorted(r.one_sided))
        parts.append(
            f"{r.scope}=={cluster_sig}##{conflict_sig}"
            f"##S:{shape_sig}##B:{broken_sig}##O:{orphan_sig}##M:{sync_sig}"
            f"##L:{one_sided_sig}"
        )
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()[:12]


def main() -> int:
    state.init_state()

    # The three-scope roots that exist (LOCAL → PROJECT → USER, most-specific
    # first). LOCAL is the always-present primary root where the proposal lands.
    scopes = _resolve_scope_dirs()
    # Graceful no-op: no memory dir in ANY scope → nothing to organize.
    if not scopes:
        return 0
    local_memdir = scopes[0][1]  # LOCAL is always first (or the only scope)

    binary = _find_memgrep()
    if binary is None:
        # memgrep absent → silent no-op (degrade, never break). Logged, not printed.
        state.log_line("memory-librarian", "memgrep not resolved — skipping")
        return 0

    # Analyze EACH scope SEPARATELY — never cluster/conflict across scopes
    # (TRDD-c77dae09). A scope with no findings is dropped from the proposal.
    per_scope: list[ScopeReport] = []
    total_agg = 0
    total_conf = 0
    total_shape = 0
    total_link = 0  # broken-links + orphans + MEMORY.md-sync + one-sided (rank 4)
    for scope, memdir in scopes:
        report = _analyze_scope(binary, memdir)
        report.scope = scope
        if report.has_findings():
            per_scope.append(report)
            total_agg += len(report.clusters)
            total_conf += len(report.conflicts)
            total_shape += len(report.shape)
            total_link += (
                len(report.broken) + len(report.orphans)
                + len(report.index_sync) + len(report.one_sided)
            )

    if not per_scope:
        # Nothing to surface in any scope → silent no-op.
        state.rotate_log_if_big("memory-librarian")
        return 0

    # Dedupe BEFORE writing the proposal: an unchanged finding set must be a
    # complete no-op (no heartbeat line AND no proposal churn), so the detector
    # is idempotent on a stable corpus. The seen-file keys on the finding
    # fingerprint; emit_once returns the line only on a NEW set.
    seen = state.state_dir() / "memory-librarian-seen.txt"
    fingerprint = _candidate_fingerprint(per_scope)
    n_scopes = len(per_scope)
    scope_note = "" if n_scopes == 1 else f" across {n_scopes} scopes"
    # The heartbeat line counts every surfaced finding class; the zero-count
    # classes are omitted so the line stays short on a corpus with only one issue
    # type. Aggregation + conflict are always shown (the original two duties).
    extra = ""
    if total_shape:
        extra += f" + {total_shape} page-shape"
    if total_link:
        extra += f" + {total_link} link/sync"
    msg = (
        f"[memory-librarian] {total_agg} aggregation + {total_conf} conflict"
        f"{extra} finding(s){scope_note} — see {PROPOSAL_NAME}"
    )
    line = dedupe.emit_once(seen, f"reorg-{fingerprint}", msg)
    if line is None:
        # Unchanged candidate set — stay completely silent and do not rewrite the
        # proposal (idempotent: re-running on a rational corpus produces no churn).
        state.rotate_log_if_big("memory-librarian")
        return 0

    # NEW candidate set: write/refresh the proposal into the LOCAL root (atomic;
    # it is NOT a note — zero memory-note mutation) and emit the one-line finding.
    proposal = _render_proposal(per_scope)
    try:
        state.atomic_write(local_memdir / PROPOSAL_NAME, proposal)
    except OSError as exc:
        # If we cannot write the proposal, do NOT emit a line that points at a
        # file that isn't there — log and stay silent.
        state.log_line("memory-librarian", f"could not write proposal: {exc}")
        return 0

    print(line)
    state.rotate_log_if_big("memory-librarian")
    return 0


if __name__ == "__main__":
    sys.exit(main())
