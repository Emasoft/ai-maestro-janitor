"""CLAUDE.md narrative migration PLANNER — the DECISION half only (TRDD-LFSWY0C6).

Per `design/specs/claude-md-canonical-form.md` §CM-2, narrative outside the five permitted
CLAUDE.md elements is a defect the janitor must repair by moving it into the PROJECT
wikimem. This module computes WHAT WOULD MOVE WHERE. It never writes CLAUDE.md, never
creates or edits a memory page, and never removes a line — that is the DELIVERY half, a
separate, later, and separately-risky task (TRDD-LFSWY0C6 "PRE-CHECK" note, 2026-08-13).

Three pure decisions, each independently testable without touching a filesystem:

1. `split_narrative_blocks` — cut the narrative (already extracted by
   `repomap.claudemd_slim.narrative_outside_fences`) into the units a human would judge
   one at a time: a single-line list item, or a blank-line-delimited paragraph.
2. `classify_exemption` — is this block one of the §CM-3 / `G9.1` dev-ops command lines?
   The word list is a LITERAL, CLOSED enumeration lifted verbatim from the spec — never a
   regex pattern that could be "widened by analogy" (e.g. adding `build`/`lint`/`test` stems
   the spec did not list) by a future reader who thinks it obviously belongs.
3. `decide_new_page_scope` — when no owning page exists, is the new page PROJECT- or
   LOCAL-scoped (the memory-scope-routing gate: machine-private content never lands in the
   git-tracked PROJECT store).

The one impure step is the RECALL itself (`recall_top` shells out to `memgrep recall`) —
CM-2 step 2 requires it to find the page that already owns a subject, so a chore (or this
planner) never mints a duplicate page. `plan_migration` wires all four together; callers
inject `roots` explicitly so a caller that wants a hermetic, synthetic-fixture-only search
(every test in this repo) never accidentally recalls against a developer's real LOCAL/USER
memory stores.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from repomap.claudemd_slim import narrative_outside_fences, slim_violations

# ── 1. Narrative block splitting ─────────────────────────────────────────────────────

_LIST_ITEM_RE = re.compile(r"^\s*([-*+]|\d+[.)])\s+")
_HEADING_RE = re.compile(r"^\s*#")


@dataclass(frozen=True)
class NarrativeBlock:
    """One unit of narrative content a human (or the planner) judges as a whole.

    `line_no` is 1-based, counted within the NARRATIVE text passed to
    `split_narrative_blocks` (i.e. after fenced regions are already stripped) — good
    enough for a human-readable plan; it is not a byte-exact offset into the original
    CLAUDE.md, which the DECISION half has no need to compute.
    """

    text: str
    line_no: int


def split_narrative_blocks(narrative: str) -> list[NarrativeBlock]:
    """Cut `narrative` into judgeable units.

    Headings (`#...`) are structure, not content, and are skipped. A list item (`- `, `* `,
    `1. `) is its own one-line block, because a §Commands list mixes exempt dev-ops lines
    with (potentially) migratable ones and each must be judged independently. Everything
    else is a blank-line-delimited paragraph.
    """
    lines = narrative.splitlines()
    blocks: list[NarrativeBlock] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if _HEADING_RE.match(line):
            i += 1
            continue
        if _LIST_ITEM_RE.match(line):
            blocks.append(NarrativeBlock(text=line, line_no=i + 1))
            i += 1
            continue
        start = i
        para_lines = [line]
        i += 1
        while i < n and lines[i].strip() and not _HEADING_RE.match(lines[i]) and not _LIST_ITEM_RE.match(lines[i]):
            para_lines.append(lines[i])
            i += 1
        blocks.append(NarrativeBlock(text="\n".join(para_lines), line_no=start + 1))
    return blocks


# ── 2. The closed dev-ops exemption (`G9.1` / spec §CM-3 / TRDD-LFSWY0C6 §3) ────────────

# LITERAL, CLOSED enumeration — the 13 categories are copied verbatim from the spec's own
# wording (the dict KEYS, returned as the "matched enumeration word"). Do NOT add a 14th
# category, or a synonym for a DIFFERENT concept, by analogy. The spec is explicit: "The
# chore MUST NOT extend the list by analogy — encode it as a literal enumeration so a
# future model cannot reason its way to a wider one." If the category set needs to change,
# that is a PRRD/spec edit, not a code edit.
#
# Each category's VALUE is its own small, explicit, hand-written list of literal surface
# forms (verb / noun / gerund / past tense of THE SAME WORD — e.g. "test", "tests",
# "tested", "testing" are one category, not four). This is still a literal enumeration —
# every string is spelled out, none derived by a stemmer or a fuzzy/similarity match — it
# just recognizes that a real dev-ops command line says "Tests:" or "Lint:", not the
# spec's gerund "testing"/"linting". Recognizing "test"/"tests" as the testing category is
# NOT the widening-by-analogy risk the spec warns about; classifying an unrelated word
# (e.g. "verify", "check", "audit") as testing WOULD be, and no such word is listed here.
DEVOPS_EXEMPTION_FORMS: dict[str, tuple[str, ...]] = {
    "git": ("git",),
    "commit": ("commit", "commits", "committed", "committing"),
    "branching": ("branch", "branches", "branched", "branching"),
    "merging": ("merge", "merges", "merged", "merging"),
    "linting": ("lint", "lints", "linted", "linting"),
    "building": ("build", "builds", "built", "building"),
    "testing": ("test", "tests", "tested", "testing"),
    "tagging": ("tag", "tags", "tagged", "tagging"),
    "pushing": ("push", "pushes", "pushed", "pushing"),
    "CI": ("ci",),
    "publishing": ("publish", "publishes", "published", "publishing"),
    "installing": ("install", "installs", "installed", "installing"),
    "deploying": ("deploy", "deploys", "deployed", "deploying"),
}

# The 13 canonical category labels — what `classify_exemption` reports as the matched word.
DEVOPS_EXEMPTION_WORDS: tuple[str, ...] = tuple(DEVOPS_EXEMPTION_FORMS.keys())

# One compiled alternation over EVERY literal surface form, each tagged back to its
# canonical category via a named group so a single regex pass finds the match AND its
# category — still a literal, closed set (no `\w*` wildcards, no partial-word matching).
_DEVOPS_WORD_RE = re.compile(
    r"\b(?:"
    + "|".join(
        rf"(?P<w{i}>{'|'.join(re.escape(f) for f in forms)})"
        for i, forms in enumerate(DEVOPS_EXEMPTION_FORMS.values())
    )
    + r")\b",
    re.IGNORECASE,
)
_GROUP_TO_CATEGORY = {f"w{i}": word for i, word in enumerate(DEVOPS_EXEMPTION_WORDS)}


def classify_exemption(block_text: str) -> str | None:
    """The matched §CM-3 enumeration word if `block_text` is EXEMPT, else None (MIGRATABLE).

    A block is exempt only when BOTH:
      (a) it is a SINGLE LINE — the spec's own test is "a command an agent runs to operate
          the repo", and architecture/gotcha/rationale prose is multi-sentence by nature;
          the spec is explicit that short prose is still narrative ("however short"), so
          single-line-ness is a STRUCTURAL gate, not a length shortcut for prose;
      (b) it names one of the closed §CM-3 categories via one of that category's literal
          surface forms, as a whole word (case-insensitive).
    Both conditions are mechanical, not semantic — no similarity scoring, no analogy.
    """
    if "\n" in block_text.strip():
        return None
    m = _DEVOPS_WORD_RE.search(block_text)
    if m is None:
        return None
    group_name = m.lastgroup
    if group_name is None:  # defensive — every alternative is a named group
        return None
    return _GROUP_TO_CATEGORY[group_name]


# ── 3. New-page scope routing (memory-scope-routing.md's WRITE gate) ────────────────────

# Red flags that force a new page to LOCAL scope instead of PROJECT (git-tracked, pushed to
# every cloner): a machine-specific absolute path, or phrasing that names "this machine" as
# the subject. Mirrors ~/.claude/rules/memory-scope-routing.md's gate — kept as a small,
# explicit, literal set for the same "no widening by analogy" reason as §CM-3.
_LOCAL_SCOPE_RED_FLAGS: tuple[re.Pattern[str], ...] = (
    re.compile(r"/Users/[A-Za-z0-9_.\-]+"),
    re.compile(r"/home/[A-Za-z0-9_.\-]+"),
    re.compile(r"[Cc]:\\Users\\"),
    re.compile(r"\bon this machine\b", re.IGNORECASE),
    re.compile(r"\bmy setup\b", re.IGNORECASE),
    re.compile(r"\bthe owner decided\b", re.IGNORECASE),
)


def decide_new_page_scope(block_text: str) -> str:
    """"local" if `block_text` carries a machine-private red flag, else "project"."""
    for pattern in _LOCAL_SCOPE_RED_FLAGS:
        if pattern.search(block_text):
            return "local"
    return "project"


# ── Recall query construction ────────────────────────────────────────────────────────

def build_recall_query(block_text: str) -> str:
    """A short symptom-style phrase to hand `memgrep recall` — the block's own words, with
    markdown noise (bullet markers, inline code fences) stripped, capped at 16 words so the
    query stays a phrase rather than a paragraph dump."""
    text = _LIST_ITEM_RE.sub("", block_text, count=1)
    text = text.replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    words = text.split(" ")
    return " ".join(w for w in words[:16] if w)


# ── The RECALL step (the one impure primitive) ───────────────────────────────────────

@dataclass(frozen=True)
class RecallHit:
    page: str          # page stem, e.g. "daemon-page"
    atom: str           # atom id, or "" when the hit is a whole page
    locator: str          # "page" or "page#ATOM1"
    description: str
    score: float


_FULL_HEADER_RE = re.compile(r"^(?P<path>\S+\.md)(?:#(?P<atom>\S+))?\s+—\s+(?P<desc>.*)$")
_FULL_SCORE_RE = re.compile(r"^\s*score:\s*(?P<score>-?\d+(?:\.\d+)?)\s*$")


def parse_recall_full_output(stdout: str) -> list[RecallHit]:
    """Parse `memgrep recall --output full` stdout into ranked `RecallHit`s.

    Only a line matching the anchored `<path>[#atom] — <desc>` header starts a new hit; the
    hit's `score:` line is the first one seen before the next header (there is exactly one
    per result). Any other line (body text, keywords, lessons) is ignored — this parser
    only needs page identity + score, never the atom body.
    """
    hits: list[dict[str, object]] = []
    pending: dict[str, object] | None = None
    for raw in stdout.splitlines():
        m = _FULL_HEADER_RE.match(raw)
        if m:
            if pending is not None:
                hits.append(pending)
            stem = Path(m.group("path")).stem
            atom = m.group("atom") or ""
            pending = {
                "page": stem,
                "atom": atom,
                "locator": f"{stem}#{atom}" if atom else stem,
                "description": m.group("desc"),
                "score": None,
            }
            continue
        if pending is not None and pending["score"] is None:
            sm = _FULL_SCORE_RE.match(raw)
            if sm:
                pending["score"] = float(sm.group("score"))
    if pending is not None:
        hits.append(pending)
    # `hits` is a heterogeneous record dict, so every value widens to `object` and mypy
    # cannot narrow it THROUGH the index — `h["score"] is not None` tells it nothing about
    # the second `h["score"]`. Bind to a local and narrow on the concrete type instead:
    # `score` is only ever assigned from `float(...)` above, so `isinstance(..., float)` is
    # exact rather than defensive, and the un-parsed case keeps its explicit 0.0 default.
    out: list[RecallHit] = []
    for h in hits:
        raw_score = h["score"]
        out.append(
            RecallHit(
                page=str(h["page"]),
                atom=str(h["atom"]),
                locator=str(h["locator"]),
                description=str(h["description"]),
                score=float(raw_score) if isinstance(raw_score, float) else 0.0,
            )
        )
    return out


def find_memgrep() -> str | None:
    """Resolve the memgrep binary: `MEMGREP_BIN` env override -> PATH -> `~/.cargo/bin`.

    Mirrors `wikimem_syntax_lint.find_memgrep` / `user_mem_lib.find_memgrep` (both scripts,
    not importable here without sys.path surgery this lib package must not depend on)."""
    override = os.environ.get("MEMGREP_BIN")
    if override and Path(override).is_file():
        return override
    found = shutil.which("memgrep")
    if found:
        return found
    cargo_bin = Path(os.path.expanduser("~")) / ".cargo" / "bin" / "memgrep"
    return str(cargo_bin) if cargo_bin.is_file() else None


# memgrep's own ranker returns its top-N candidates EVEN when none of them genuinely match
# (e.g. the query shares only structural vocabulary — "description" is a frontmatter FIELD
# NAME present on every page — with no real content overlap), scored 0 in that case.
# Measured directly (2026-08-13): a nonsense query ("flibbertigibbet quokka zephyr") returns
# NO rows at all, but a query containing the bare word "description" returns every page in
# the corpus at score 0. So score 0 is NOT "no match" — it must be filtered out, or the
# planner would FOLD into a random top-N page instead of correctly deciding NEW PAGE.
MIN_RECALL_SCORE = 1.0


def recall_top(
    query: str,
    roots: Sequence[Path],
    *,
    memgrep_bin: str | None = None,
    top: int = 3,
    timeout: int = 60,
) -> list[RecallHit]:
    """Run `memgrep recall <query> <roots...>` and return ranked GENUINE hits (best first,
    `score >= MIN_RECALL_SCORE` only — see that constant's docstring for why 0 must be
    filtered rather than treated as "no candidate").

    Returns `[]` (never raises) when there is no binary, no existing root, an empty query,
    or the process itself fails — a recall the planner cannot perform must fall through to
    "no owning page found" (NEW PAGE), never crash a plan run.
    """
    if not query.strip():
        return []
    binary = memgrep_bin or find_memgrep()
    if binary is None:
        return []
    existing = [str(r) for r in roots if r.is_dir()]
    if not existing:
        return []
    cmd = [binary, "recall", query, *existing, "--top", str(top), "--output", "full"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return []
    hits = parse_recall_full_output(proc.stdout)
    return [h for h in hits if h.score >= MIN_RECALL_SCORE]


# ── The whole-block plan ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class BlockPlan:
    """The planner's verdict for one `NarrativeBlock`. Exactly one of the verdict-specific
    field groups is populated, selected by `verdict`."""

    block: NarrativeBlock
    verdict: str  # "exempt" | "fold" | "new_page"
    exemption_word: str = ""
    query: str = ""
    candidate_page: str = ""
    candidate_locator: str = ""
    candidate_description: str = ""
    candidate_score: float = 0.0
    new_page_scope: str = ""
    new_page_tier: str = ""


def plan_migration(
    claude_md_text: str,
    *,
    roots: Sequence[Path],
    memgrep_bin: str | None = None,
    recall_top_n: int = 3,
    timeout: int = 60,
) -> list[BlockPlan]:
    """The whole DECISION half: narrative -> blocks -> (exempt | fold | new_page) each.

    NEVER writes CLAUDE.md, NEVER writes/creates a memory page — `claude_md_text` and
    `roots` are read-only inputs (roots are read by the `memgrep recall` subprocess only).

    Candidate selection keys on `slim_violations` — the authoritative "does this file
    actually violate the slim contract" check — NOT on `narrative_outside_fences` alone.
    `narrative_outside_fences` returns everything outside the two janitor fences, which
    BY DESIGN also includes the five PERMITTED elements (title, description, project
    URLs, dev-ops commands): treating all of that as migration candidates is exactly the
    2026-08-13 defect (TRDD-LFSWY0C6) — it proposed migrating this project's own title,
    description and `## Links` section, none of which are defects. A file `check` already
    calls conforming (`slim_violations(claude_md_text) == []`) MUST plan to migrate
    nothing; only once the file is diagnosed as non-conforming does per-block candidate
    selection have any defect to locate.
    """
    if not slim_violations(claude_md_text):
        return []
    narrative = narrative_outside_fences(claude_md_text)
    blocks = split_narrative_blocks(narrative)
    binary = memgrep_bin or find_memgrep()
    plans: list[BlockPlan] = []
    for block in blocks:
        word = classify_exemption(block.text)
        if word is not None:
            plans.append(BlockPlan(block=block, verdict="exempt", exemption_word=word))
            continue
        query = build_recall_query(block.text)
        hits = recall_top(query, roots, memgrep_bin=binary, top=recall_top_n, timeout=timeout)
        if hits:
            top = hits[0]
            plans.append(
                BlockPlan(
                    block=block,
                    verdict="fold",
                    query=query,
                    candidate_page=top.page,
                    candidate_locator=top.locator,
                    candidate_description=top.description,
                    candidate_score=top.score,
                )
            )
        else:
            plans.append(
                BlockPlan(
                    block=block,
                    verdict="new_page",
                    query=query,
                    new_page_scope=decide_new_page_scope(block.text),
                    new_page_tier="component",
                )
            )
    return plans


def _preview(text: str, *, cap: int = 100) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= cap else flat[: cap - 1].rstrip() + "…"


def render_plan(plans: list[BlockPlan]) -> str:
    """Human-readable plan, one entry per block. Reused by the CLI; kept pure (no I/O) so
    tests can assert on its text directly."""
    if not plans:
        return "claudemd-migration-plan: no narrative blocks found outside the five permitted elements"
    lines = [f"claudemd-migration-plan: {len(plans)} narrative block(s) found outside the five permitted elements", ""]
    for i, p in enumerate(plans, start=1):
        if p.verdict == "exempt":
            lines.append(f"[{i}] EXEMPT (matched enumeration word: {p.exemption_word!r})")
        elif p.verdict == "fold":
            lines.append(
                f"[{i}] MIGRATABLE -> FOLD into {p.candidate_page!r} "
                f"(locator={p.candidate_locator}, score={p.candidate_score:g})"
            )
            lines.append(f"    recall query: {p.query!r}")
        else:
            lines.append(
                f"[{i}] MIGRATABLE -> NEW PAGE at {p.new_page_scope}/{p.new_page_tier} "
                "(no existing owning page found)"
            )
            lines.append(f"    recall query: {p.query!r}")
        lines.append(f"    block (line {p.block.line_no}): {_preview(p.block.text)!r}")
        lines.append("")
    return "\n".join(lines).rstrip("\n") + "\n"
