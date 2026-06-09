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
    """Return the per-project agent-memory dir (parent of user-mem). Not created."""
    proj = (os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()).strip()
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    return home / ".claude" / "projects" / _project_slug(proj) / "memory"


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


def _render_proposal(
    clusters: dict[str, list[str]],
    conflicts: list[tuple[str, str, str]],
) -> str:
    """Render the human/agent-facing proposal markdown.

    The proposal is git-trackable BY THE USER, but the detector only WRITES it —
    it never touches a note. It is advisory input for an agent's conscious
    merge/correction pass (the actual reorg is the agent's job, not this
    detector's).
    """
    lines: list[str] = [
        "# Memory reorganization — PROPOSED (surfaced by janitor memory-librarian)",
        "",
        "_Auto-generated by the ai-maestro-janitor `memory-librarian` detector",
        "(TRDD-c77dae09). These are CANDIDATES surfaced for an AGENT to review —",
        "the janitor never moves, merges, edits, or deletes a memory note. An",
        "agent makes the conscious consolidation/correction decision; do not treat",
        "this file as having mutated anything._",
        "",
        "## Aggregation candidates",
        "",
        "_Clusters of notes sharing a topic (a common frontmatter tag, or",
        "overlapping name/description topic words) that could be consolidated into",
        "one canonical wiki page, with tangential mentions linking it rather than",
        "duplicating its facts. The topic label is the shared tag(s) or token(s)._",
        "",
    ]
    if clusters:
        for tag in sorted(clusters)[:_MAX_CLUSTERS_LISTED]:
            members = clusters[tag]
            joined = ", ".join(members)
            lines.append(f"- topic `{tag}` ({len(members)} notes): {joined}")
    else:
        lines.append("- (none)")
    lines += [
        "",
        "## Conflict candidates",
        "",
        "_Same-topic note pairs that do NOT cross-link and therefore MIGHT",
        "duplicate or contradict. These are CANDIDATES only — an agent must read",
        "both notes to decide whether a real conflict exists and reconcile it",
        "(non-destructively, per the correction protocol)._",
        "",
    ]
    if conflicts:
        for a, b, tag in conflicts[:_MAX_PAIRS_LISTED]:
            lines.append(f"- topic `{tag}`: {a} vs {b}")
    else:
        lines.append("- (none)")
    lines.append("")
    return "\n".join(lines)


def _candidate_fingerprint(
    clusters: dict[str, list[str]],
    conflicts: list[tuple[str, str, str]],
) -> str:
    """A stable hash of the candidate SET so dedupe is silent on an unchanged corpus.

    Sorted so directory/parse order never changes the key. A new cluster or a new
    conflict pair changes the fingerprint → a fresh heartbeat finding.
    """
    cluster_sig = ";".join(
        f"{tag}:{'|'.join(clusters[tag])}" for tag in sorted(clusters)
    )
    conflict_sig = ";".join(
        sorted("|".join(sorted((a, b))) + f"@{tag}" for a, b, tag in conflicts)
    )
    return hashlib.sha256(f"{cluster_sig}##{conflict_sig}".encode("utf-8")).hexdigest()[:12]


def main() -> int:
    state.init_state()

    memdir = _resolve_memory_dir()
    # Graceful no-op: no per-project memory dir → nothing to organize.
    if not memdir.is_dir():
        return 0

    # Are there any agent NOTES at all (excluding the non-note files + user-mem)?
    # Cheap pre-check so an empty/near-empty corpus skips the memgrep spawn.
    has_note = False
    try:
        for entry in memdir.iterdir():
            if entry.is_file() and _is_note_basename(entry.name):
                has_note = True
                break
    except OSError:
        return 0
    if not has_note:
        return 0

    binary = _find_memgrep()
    if binary is None:
        # memgrep absent → silent no-op (degrade, never break). Logged, not printed.
        state.log_line("memory-librarian", "memgrep not resolved — skipping")
        return 0

    index_out = _run_memgrep(binary, ["index", "--markdown"], memdir)
    if not index_out:
        return 0
    notes = _parse_index(index_out)
    if len(notes) < 2:
        return 0

    clusters = _build_clusters(notes)
    if not clusters:
        # No two notes share a topic → nothing to aggregate, nothing to flag.
        return 0

    links_out = _run_memgrep(binary, ["links"], memdir)
    linked = _parse_links(links_out) if links_out else set()

    conflicts = _conflict_pairs(notes, linked)

    # Dedupe BEFORE writing the proposal: an unchanged candidate set must be a
    # complete no-op (no heartbeat line AND no proposal churn), so the detector
    # is idempotent on a stable corpus. The seen-file keys on the candidate
    # fingerprint; emit_once returns the line only on a NEW set.
    seen = state.state_dir() / "memory-librarian-seen.txt"
    fingerprint = _candidate_fingerprint(clusters, conflicts)
    n_agg = len(clusters)
    m_conf = len(conflicts)
    msg = (
        f"[memory-librarian] {n_agg} aggregation + {m_conf} conflict candidate(s) "
        f"— see {PROPOSAL_NAME}"
    )
    line = dedupe.emit_once(seen, f"reorg-{fingerprint}", msg)
    if line is None:
        # Unchanged candidate set — stay completely silent and do not rewrite the
        # proposal (idempotent: re-running on a rational corpus produces no churn).
        state.rotate_log_if_big("memory-librarian")
        return 0

    # NEW candidate set: write/refresh the proposal (atomic; it is NOT a note —
    # zero memory-note mutation) and emit the one-line finding.
    proposal = _render_proposal(clusters, conflicts)
    try:
        state.atomic_write(memdir / PROPOSAL_NAME, proposal)
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
