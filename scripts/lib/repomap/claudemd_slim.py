"""Slim janitor-managed CLAUDE.md — the wikimem-index half (TRDD-H12K9JYX).

Owner directive 2026-08-02: a janitor-managed CLAUDE.md contains ONLY a concise project
description, the repo URLs, the basic lint/build/test/publish instructions, the janitor
project map, and a topic-ordered index of the PROJECT-scope wikimem pages. Everything
else lives in wikimem pages, where it is RECALLED by symptom instead of PAID on every
turn (CLAUDE.md rides the prompt prefix of every session).

This module is the PURE half: scan the PROJECT memory corpus, render the fenced index
block, check the slim contract, and prove a migration lost nothing. All I/O beyond
reading page files stays in the CLI (`scripts/claudemd_slim.py`); all EDITORIAL judgment
(which narrative becomes which page) stays in the `janitor-claude-md-slim` skill. The
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
            )
        )
    return pages


def corpus_digest(pages: list[PageInfo]) -> str:
    """12-hex digest over (name, lmd, description) — the cheap freshness probe. lmd is
    in the mix so an updated page re-renders its (possibly changed) description; file
    CONTENT beyond that deliberately is not, or every atom edit would churn CLAUDE.md
    (the cache-bust the nudge-only discipline exists to avoid)."""
    mix = "\n".join(f"{p.name}\t{p.lmd}\t{p.description}" for p in sorted(pages, key=lambda p: p.name))
    return hashlib.sha256(mix.encode("utf-8")).hexdigest()[:12]


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


def render_index(pages: list[PageInfo], *, generated_iso: str, memdir_rel: str = ".claude/project/memory") -> str:
    """The full fenced index block, trailing newline included.

    Topic order: the overview first (the entry point), then each HUB as a topic group
    listing the pages its body `[[links]]` to, then everything unclaimed under "Other".
    A page linked by two hubs appears under the FIRST (alphabetical) hub only — the
    index is a table of contents, not the link graph; the full graph lives in the wiki
    itself.
    """
    by_name = {p.name: p for p in pages}
    overview = next((p for p in sorted(pages, key=lambda p: p.name) if p.is_overview), None)
    hubs = sorted((p for p in pages if p.tier == "hub" and not p.is_overview), key=lambda p: p.name)

    claimed: set[str] = set()
    if overview:
        claimed.add(overview.name)
    for h in hubs:
        claimed.add(h.name)

    lines: list[str] = []
    lines.append("## Wikimem index (PROJECT scope) — recall by symptom, read on demand")
    lines.append("")
    lines.append(f"Deep knowledge lives in these pages, not in this file. Search: `memgrep recall \"<symptom>\" {memdir_rel}`.")
    lines.append("")
    if overview:
        lines.append(_entry(overview, memdir_rel))
        lines.append("")
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
    body = "\n".join(lines).rstrip("\n")
    start = f"{WIKIMEM_FENCE_START} {_SCHEMA} digest={corpus_digest(pages)} generated={generated_iso}"
    return f"{start}\n{body}\n{WIKIMEM_FENCE_END}\n"


def narrative_outside_fences(text: str) -> str:
    """Everything OUTSIDE both janitor-owned fenced regions — the human/agent narrative
    the slim contract budgets. Malformed fences raise (never guess)."""
    for start, end in ((MAP_FENCE_START, MAP_FENCE_END), (WIKIMEM_FENCE_START, WIKIMEM_FENCE_END)):
        span = _fence_span(text, start, end)
        if span is not None:
            text = text[: span[0]] + text[span[1] :]
    return text


def slim_violations(text: str) -> list[str]:
    """The slim-contract check — an ADVISORY list, one string per violation, empty when
    conforming. The detector nudges on it; nothing auto-rewrites CLAUDE.md (it sits in
    the cached prompt prefix — TRDD-e247a349 §5's nudge-only discipline applies)."""
    violations: list[str] = []
    if _fence_span(text, MAP_FENCE_START, MAP_FENCE_END) is None:
        violations.append("no project-map fence (run scripts/repomap_generate.py)")
    if _fence_span(text, WIKIMEM_FENCE_START, WIKIMEM_FENCE_END) is None:
        violations.append("no wikimem-index fence (run scripts/claudemd_slim.py index)")
    narrative = narrative_outside_fences(text)
    size = len(narrative.encode("utf-8"))
    cap = narrative_max_bytes()
    if size > cap:
        violations.append(
            f"narrative is {size} bytes (cap {cap}) — content beyond description/urls/"
            "build-instructions belongs in wikimem pages (/janitor-claude-md-slim)"
        )
    if "github.com/" not in narrative:
        violations.append("no github repo url in the narrative")
    return violations


def index_is_stale(text: str, pages: list[PageInfo]) -> bool:
    """True iff the spliced index's digest no longer matches the corpus (or there is no
    index at all). Cheap: no extraction, just the header line vs a hash of scan_pages
    output."""
    span = _fence_span(text, WIKIMEM_FENCE_START, WIKIMEM_FENCE_END)
    if span is None:
        return True
    header = text[span[0] : span[1]].splitlines()[0]
    m = re.search(r"digest=([0-9a-f]{12})", header)
    return m is None or m.group(1) != corpus_digest(pages)
