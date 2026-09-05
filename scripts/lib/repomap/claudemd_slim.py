"""Slim janitor-managed CLAUDE.md — the wikimem-index half (TRDD-H12K9JYX).

Owner directive 2026-08-02: a janitor-managed CLAUDE.md contains ONLY a concise project
description, the repo URLs, the basic lint/build/test/publish instructions, the janitor
project map, and a topic-ordered index of the PROJECT-scope wikimem pages. Everything
else lives in wikimem pages, where it is RECALLED by symptom instead of PAID on every
turn (CLAUDE.md rides the prompt prefix of every session).

This module is the PURE half: scan the PROJECT memory corpus, render the fenced index
block, check the slim contract, and prove a migration lost nothing. All I/O beyond
reading page files stays in the CLI (`scripts/claudemd_slim.py`); all EDITORIAL judgment
(which narrative becomes which page) stays in the `janitor-project-cld-md-optimizer` skill. The
split matters: the proofs must be deterministic so the skill cannot talk itself into a
lossy migration.

Fence surgery is shared with the repo map via the parameterized `markers` functions —
one implementation, because two splicers that drift apart is how one eats the other's
block.
"""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from .markers import _fence_span
from .renderer import FENCE_END as MAP_FENCE_END
from .renderer import FENCE_START as MAP_FENCE_START

WIKIMEM_FENCE_START = "<+-+-JANITOR-WIKIMEM-INDEX-START-(do-not-modify)-+-+>"
WIKIMEM_FENCE_END = "<+-+-JANITOR-WIKIMEM-INDEX-END-(do-not-modify)-+-+>"
_SCHEMA = "v1"

# Byte cap on the NARRATIVE (everything outside both fences). 8 KiB fits the allowed
# content — description, URLs, build instructions — with headroom; a narrative past it
# means content that belongs in wikimem pages is still riding every turn.
NARRATIVE_MAX_BYTES_ENV = "CLAUDE_PLUGIN_OPTION_CLAUDEMD_NARRATIVE_MAX_BYTES"
_NARRATIVE_MAX_BYTES_DEFAULT = 8 * 1024

# One index entry's description budget. The index is paid on every turn of every
# session, so entries are one line each; the full symptom-string description stays on
# the page itself, one hop away.
_DESC_MAX_CHARS = 110

_WIKILINK_RE = re.compile(r"\[\[([A-Za-z0-9_-]+)\]\]")


def narrative_max_bytes() -> int:
    raw = os.environ.get(NARRATIVE_MAX_BYTES_ENV, "")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return _NARRATIVE_MAX_BYTES_DEFAULT
    return value if value > 0 else _NARRATIVE_MAX_BYTES_DEFAULT


@dataclass
class PageInfo:
    """One PROJECT wikimem page, as the index needs it. Parsed from frontmatter only —
    no memgrep dependency, so the index still builds on a host whose memgrep binary is
    stale (a real, recurring condition per the memory-system page)."""

    name: str
    filename: str  # basename, e.g. "janitor-architecture.md"
    description: str
    tier: str  # hub | aspect | component | "" when undeclared
    lmd: str
    wikilinks: list[str] = field(default_factory=list)
    # TRDD-KI0H9C8N / janitor#299: `metadata.topic:` — a flat, closed vocabulary a page
    # opts into independently of the hub/wikilink graph. "" when undeclared (the hub
    # grouping stays the fallback — see `_render_body`).
    topic: str = ""

    @property
    def is_overview(self) -> bool:
        return self.name.endswith("-overview")


def _parse_frontmatter_and_links(text: str) -> tuple[dict[str, str], list[str]]:
    """(flat frontmatter fields incl. nested metadata keys, body wikilinks). Line-based
    on purpose: the corpus' frontmatter is machine-written one-field-per-line (the
    wikimem write verbs emit it), and a YAML dependency here would be the only one in
    the repomap package."""
    fields: dict[str, str] = {}
    lines = text.splitlines()
    body_start = 0
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                body_start = i + 1
                break
            raw = lines[i]
            stripped = raw.strip()
            if ":" not in stripped:
                continue
            key, _, val = stripped.partition(":")
            key, val = key.strip(), val.strip()
            if not val:
                continue  # a nesting parent like `metadata:` — children carry the values
            if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
                val = val[1:-1]
            fields.setdefault(key, val)  # top-level wins over a nested duplicate
    body = "\n".join(lines[body_start:])
    links = list(dict.fromkeys(_WIKILINK_RE.findall(body)))  # deduped, order kept
    return fields, links


def scan_pages(memdir: Path) -> list[PageInfo]:
    """Every real PROJECT wikimem page under `memdir`, sorted by name.

    Note filtering mirrors `memory_scopes.is_note_file`'s intent without importing it
    (this package must stay importable with only its own directory on sys.path): a
    real page is a `*.md` regular file that is not the harness index (MEMORY.md) nor a
    maintenance artifact (`memory-reorg-proposed.md`, dotfiles)."""
    pages: list[PageInfo] = []
    if not memdir.is_dir():
        return pages
    for p in sorted(memdir.rglob("*.md")):
        if not p.is_file() or p.name.startswith("."):
            continue
        if p.name in ("MEMORY.md", "memory-reorg-proposed.md"):
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        fields, links = _parse_frontmatter_and_links(text)
        name = fields.get("name") or p.stem
        pages.append(
            PageInfo(
                name=name,
                filename=str(p.relative_to(memdir)),
                description=fields.get("description", ""),
                tier=fields.get("tier", ""),
                lmd=fields.get("lmd", ""),
                wikilinks=links,
                topic=fields.get("topic", ""),
            )
        )
    return pages


def _digest_of(body: str) -> str:
    """12-hex sha256 prefix of a rendered index BODY — the one place `render_index` and
    `corpus_digest` compute the digest, so they cannot drift apart the way the
    hand-picked-field digest drifted from `_render_body` before TRDD-Q3WSQ9M5."""
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def corpus_digest(pages: list[PageInfo], memdir_rel: str = ".claude/project/memory") -> str:
    """12-hex digest over the RENDERED index body (TRDD-Q3WSQ9M5 / janitor#298) — the
    cheap freshness probe deciding whether `CLAUDE.md`'s wikimem index gets rewritten.

    Previously hashed a hand-picked `(name, description)` pair, hand-synced with what
    `render_index` -> `_entry` actually emits (`name`, `filename`, `_short_desc`, `tier`,
    `wikilinks`). That sync drifted: a `description:` edit past the first ` / ` segment
    flipped the digest with a byte-identical rendered body (over-fires, cache-busts the
    prompt prefix every turn), while a page rename or `tier:` change left the digest
    untouched despite changing the rendered body (under-fires — `index_is_stale` never
    returns True again). Hashing `_render_body`'s own output makes drift between the
    digest and the renderer structurally impossible instead of a maintained field list."""
    body = _render_body(pages, memdir_rel)
    return _digest_of(body)


def _short_desc(desc: str) -> str:
    """First symptom segment, capped. Descriptions are recall surfaces — long ' / '
    separated symptom lists; the index shows just enough to pick a page."""
    head = desc.split(" / ")[0].strip()
    if len(head) > _DESC_MAX_CHARS:
        head = head[: _DESC_MAX_CHARS - 1].rstrip() + "…"
    return head


def _entry(page: PageInfo, memdir_rel: str) -> str:
    desc = _short_desc(page.description)
    link = f"[{page.name}]({memdir_rel}/{page.filename})"
    return f"- {link} — {desc}" if desc else f"- {link}"


def _render_by_hub(pages: list[PageInfo], memdir_rel: str, overview: PageInfo | None) -> list[str]:
    """The pre-KI0H9C8N grouping: each HUB is a topic group listing the pages its body
    `[[links]]` to, everything unclaimed falls under "Other topics". A page linked by two
    hubs appears under the FIRST (alphabetical) hub only — the index is a table of
    contents, not the link graph; the full graph lives in the wiki itself. This is the
    fallback used whenever no page in the corpus carries `metadata.topic:` (janitor#299
    acceptance box 1: byte-identical to the pre-change output)."""
    by_name = {p.name: p for p in pages}
    hubs = sorted((p for p in pages if p.tier == "hub" and not p.is_overview), key=lambda p: p.name)

    claimed: set[str] = set()
    if overview:
        claimed.add(overview.name)
    for h in hubs:
        claimed.add(h.name)

    lines: list[str] = []
    for h in hubs:
        lines.append(f"**{h.name}** — {_short_desc(h.description)}" if h.description else f"**{h.name}**")
        lines.append(_entry(h, memdir_rel))
        for linked_name in h.wikilinks:
            child = by_name.get(linked_name)
            if child is None or child.name in claimed:
                continue
            claimed.add(child.name)
            lines.append("  " + _entry(child, memdir_rel))
        lines.append("")
    others = sorted((p for p in pages if p.name not in claimed), key=lambda p: p.name)
    if others:
        lines.append("**Other topics**")
        for p in others:
            lines.append(_entry(p, memdir_rel))
        lines.append("")
    return lines


def _render_by_topic(pages: list[PageInfo], memdir_rel: str, overview: PageInfo | None) -> list[str]:
    """TRDD-KI0H9C8N / janitor#299: group by `metadata.topic:` instead of the hub/wikilink
    graph. `topic` is a flat, closed vocabulary a page opts into independently, so unlike
    hub count it does not degenerate to a near-flat list as the corpus grows. Untopiced
    pages fall under the same "Other topics" heading the hub grouping uses. Groups sort
    alphabetically by topic name; pages within a group sort by name."""
    claimed: set[str] = set()
    if overview:
        claimed.add(overview.name)
    groups: dict[str, list[PageInfo]] = {}
    for p in pages:
        if p.name in claimed or not p.topic:
            continue
        groups.setdefault(p.topic, []).append(p)

    lines: list[str] = []
    for topic in sorted(groups):
        lines.append(f"**{topic}**")
        for p in sorted(groups[topic], key=lambda p: p.name):
            lines.append(_entry(p, memdir_rel))
            claimed.add(p.name)
        lines.append("")
    others = sorted((p for p in pages if p.name not in claimed), key=lambda p: p.name)
    if others:
        lines.append("**Other topics**")
        for p in others:
            lines.append(_entry(p, memdir_rel))
        lines.append("")
    return lines


def _render_body(pages: list[PageInfo], memdir_rel: str) -> str:
    """The index body — everything between the fence header and `WIKIMEM_FENCE_END` — as
    its own function so `corpus_digest` can hash exactly what gets rendered instead of a
    hand-picked field subset (TRDD-Q3WSQ9M5). `render_index` calls this once and embeds
    `corpus_digest`'s hash of the SAME output in its header; hashing `render_index`'s own
    output would be circular since the header embeds the digest.

    Grouping mode (TRDD-KI0H9C8N / janitor#299): if any non-overview page carries
    `metadata.topic:`, group by topic (`_render_by_topic`); otherwise fall back to the
    hub/wikilink grouping (`_render_by_hub`) so a corpus with no `topic:` anywhere renders
    byte-identically to the pre-change output. The overview page is always first.
    """
    overview = next((p for p in sorted(pages, key=lambda p: p.name) if p.is_overview), None)
    has_topics = any(p.topic for p in pages if not p.is_overview)

    lines: list[str] = []
    lines.append("## Wikimem index (PROJECT scope) — recall by symptom, read on demand")
    lines.append("")
    lines.append(f"Deep knowledge lives in these pages, not in this file. Search: `memgrep recall \"<symptom>\" {memdir_rel}`.")
    lines.append("")
    if overview:
        lines.append(_entry(overview, memdir_rel))
        lines.append("")
    lines.extend(_render_by_topic(pages, memdir_rel, overview) if has_topics else _render_by_hub(pages, memdir_rel, overview))
    return "\n".join(lines).rstrip("\n")


def render_index(pages: list[PageInfo], *, generated_iso: str, memdir_rel: str = ".claude/project/memory") -> str:
    """The full fenced index block, trailing newline included."""
    body = _render_body(pages, memdir_rel)
    digest = _digest_of(body)
    start = f"{WIKIMEM_FENCE_START} {_SCHEMA} digest={digest} generated={generated_iso}"
    return f"{start}\n{body}\n{WIKIMEM_FENCE_END}\n"


def narrative_outside_fences(text: str) -> str:
    """Everything OUTSIDE both janitor-owned fenced regions — the human/agent narrative
    the slim contract budgets. Malformed fences raise (never guess)."""
    for start, end in ((MAP_FENCE_START, MAP_FENCE_END), (WIKIMEM_FENCE_START, WIKIMEM_FENCE_END)):
        span = _fence_span(text, start, end)
        if span is not None:
            text = text[: span[0]] + text[span[1] :]
    return text


def slim_violations(text: str, *, require_map: bool = False) -> list[str]:
    """The slim-contract check — an ADVISORY list, one string per violation, empty when
    conforming. The detector nudges on it; nothing auto-rewrites CLAUDE.md (it sits in
    the cached prompt prefix — TRDD-e247a349 §5's nudge-only discipline applies).

    `require_map` DEFAULTS TO FALSE because the project map is OPT-IN
    (`/janitor-auto-repomap-on`), and an absent fence is the NORMAL state for every
    project that never opted in — or that deliberately opted out. Demanding it
    unconditionally was circular: this module's own detector documents the fence as
    the thing that "opted it in", so requiring it flagged exactly the files that had
    correctly declined. It fired for real here on 2026-08-14, after the map was removed
    from this repo's CLAUDE.md to stop paying ~46k tokens per turn: the removal was
    correct and left this check demanding the map back, forever.

    Callers that KNOW the project opted in (the flag at
    `.janitor/state/repomap-opt-in.flag`) pass `require_map=True` to get a stale/missing
    fence reported — that is a real defect for an opted-in project.
    """
    violations: list[str] = []
    if require_map and _fence_span(text, MAP_FENCE_START, MAP_FENCE_END) is None:
        violations.append("no project-map fence (run scripts/repomap_generate.py)")
    if _fence_span(text, WIKIMEM_FENCE_START, WIKIMEM_FENCE_END) is None:
        violations.append("no wikimem-index fence (run scripts/claudemd_slim.py index)")
    narrative = narrative_outside_fences(text)
    size = len(narrative.encode("utf-8"))
    cap = narrative_max_bytes()
    if size > cap:
        violations.append(
            f"narrative is {size} bytes (cap {cap}) — content beyond description/urls/"
            "build-instructions belongs in wikimem pages (/janitor-project-cld-md-optimizer)"
        )
    if "github.com/" not in narrative:
        violations.append("no github repo url in the narrative")
    return violations


def index_is_stale(text: str, pages: list[PageInfo], memdir_rel: str = ".claude/project/memory") -> bool:
    """True iff the spliced index's digest no longer matches the corpus (or there is no
    index at all). Cheap: no extraction, just the header line vs a hash of scan_pages
    output."""
    span = _fence_span(text, WIKIMEM_FENCE_START, WIKIMEM_FENCE_END)
    if span is None:
        return True
    header = text[span[0] : span[1]].splitlines()[0]
    m = re.search(r"digest=([0-9a-f]{12})", header)
    return m is None or m.group(1) != corpus_digest(pages, memdir_rel)
