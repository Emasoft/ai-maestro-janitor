"""CLAUDE.md narrative migration PLANNER — the DECISION half only (TRDD-LFSWY0C6).

Per `design/specs/claude-md-canonical-form.md` §CM-2, narrative outside the five permitted
CLAUDE.md elements is a defect the janitor must repair by moving it into the PROJECT
wikimem. This module computes WHAT WOULD MOVE WHERE. It never writes CLAUDE.md, never
creates or edits a memory page, and never removes a line — that is the DELIVERY half, a
separate, later, and separately-risky task (TRDD-LFSWY0C6 "PRE-CHECK" note, 2026-08-13).

Four pure decisions, each independently testable without touching a filesystem:

1. `split_narrative_blocks` — cut the narrative (already extracted by
   `repomap.claudemd_slim.narrative_outside_fences`) into the units a human would judge
   one at a time: a single-line list item, or a blank-line-delimited paragraph.
2. `classify_exemption` — is this block one of the §CM-3 / `G9.1` dev-ops command lines?
   The word list is a LITERAL, CLOSED enumeration lifted verbatim from the spec — never a
   regex pattern that could be "widened by analogy" (e.g. adding `build`/`lint`/`test` stems
   the spec did not list) by a future reader who thinks it obviously belongs.
3. `classify_permitted` — is this block ANY of the §CM-1 elements the narrative may hold
   (the description, a project URL, or a dev-ops command), or is it excess to migrate?
   Element 3 delegates to `classify_exemption`; elements 1 and 2 had no recognizer at all
   until 2026-08-13, which is why the planner proposed migrating this project's own
   description and `## Links` section (TRDD-LFSWY0C6).
4. `decide_new_page_scope` — when no owning page exists, is the new page PROJECT- or
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
_HEADING_LEVEL_RE = re.compile(r"^\s*(#{1,6})")


@dataclass(frozen=True)
class NarrativeBlock:
    """One unit of narrative content a human (or the planner) judges as a whole.

    `line_no` is 1-based, counted within the NARRATIVE text passed to
    `split_narrative_blocks` (i.e. after fenced regions are already stripped) — good
    enough for a human-readable plan; it is not a byte-exact offset into the original
    CLAUDE.md, which the DECISION half has no need to compute.

    `in_preamble` is True while the block sits ABOVE the first section heading — the only
    place §CM-1's element 1 (the one-paragraph description) can live. It defaults to True
    so a hand-built block in a unit test needs no boilerplate; `split_narrative_blocks` is
    what sets it truthfully.
    """

    text: str
    line_no: int
    in_preamble: bool = True


def split_narrative_blocks(narrative: str) -> list[NarrativeBlock]:
    """Cut `narrative` into judgeable units.

    Headings (`#...`) are structure, not content, and are skipped. A list item (`- `, `* `,
    `1. `) is its own one-line block, because a §Commands list mixes exempt dev-ops lines
    with (potentially) migratable ones and each must be judged independently. Everything
    else is a blank-line-delimited paragraph.

    A skipped heading still leaves one trace: the LEADING `# Title` is the document title,
    not a section, and §CM-1's description sits directly beneath it — so the first heading,
    when it is an H1, keeps the preamble open. Any deeper heading (or a second H1) opens a
    section and closes it for good.
    """
    lines = narrative.splitlines()
    blocks: list[NarrativeBlock] = []
    i = 0
    n = len(lines)
    headings_seen = 0
    in_preamble = True
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        if _HEADING_RE.match(line):
            m = _HEADING_LEVEL_RE.match(line)
            level = len(m.group(1)) if m else 1
            headings_seen += 1
            if not (headings_seen == 1 and level == 1):
                in_preamble = False
            i += 1
            continue
        if _LIST_ITEM_RE.match(line):
            blocks.append(NarrativeBlock(text=line, line_no=i + 1, in_preamble=in_preamble))
            i += 1
            continue
        start = i
        para_lines = [line]
        i += 1
        while i < n and lines[i].strip() and not _HEADING_RE.match(lines[i]) and not _LIST_ITEM_RE.match(lines[i]):
            para_lines.append(lines[i])
            i += 1
        blocks.append(NarrativeBlock(text="\n".join(para_lines), line_no=start + 1, in_preamble=in_preamble))
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


# ── 3. The permitted-element classifier (spec §CM-1 elements 1 and 2) ──────────────────

# §CM-1 lists FIVE permitted elements, in order. Elements 4 and 5 are the janitor's own
# fenced regions, and `narrative_outside_fences` has already removed them before any block
# reaches here — so exactly THREE can appear in the narrative:
#
#   1. the one-paragraph project description
#   2. the project URLs
#   3. the dev-ops commands  (already recognized by `classify_exemption`, above)
#
# Until 2026-08-13 only element 3 had a recognizer, so the planner proposed migrating this
# project's OWN description and its whole `## Links` section — permitted content, not
# defects (TRDD-LFSWY0C6). `slim_violations` cannot stand in for this and no tightening of
# it ever could: it is four WHOLE-FILE checks (both fences present, a github URL somewhere,
# total narrative bytes under the cap), so it can say the narrative is too big and can
# never say WHICH block is the excess. That is the missing primitive this section supplies.
#
# Every rule below is STRUCTURAL — position, line count, punctuation shape — never a
# judgement about what a block MEANS. Where a rule is uncertain it is biased toward
# PERMITTED, because the two errors are not symmetric: keeping one block too many leaves a
# file slightly over its byte budget and the next run still reports it, while migrating a
# permitted element deletes content the canonical form requires and no later run restores.
PERMITTED_DESCRIPTION = "description"
PERMITTED_URLS = "urls"
PERMITTED_DEVOPS = "devops"
PERMITTED_ELEMENTS: tuple[str, ...] = (PERMITTED_DESCRIPTION, PERMITTED_URLS, PERMITTED_DEVOPS)

# A project-URL line is `<label>: <url>`, where the label is a LABEL ("Repo", "Marketplace
# (`ai-maestro-plugins`)") and never a sentence. This cap is what separates the two, and it
# is why `Note: the daemon polls https://x.example on every fire because …` stays
# migratable while `- Repo: https://github.com/o/r` does not.
_URL_LABEL_MAX_CHARS = 60

_URL_ANYWHERE_RE = re.compile(r"https?://")
_BARE_URL_RE = re.compile(r"https?://\S+")
_MD_LINK_URL_RE = re.compile(r"\[[^\]]*\]\(https?://[^)\s]+\)")
_ANGLE_URL_RE = re.compile(r"<https?://[^>\s]+>")


def is_project_url_line(block_text: str) -> bool:
    """True iff `block_text` is a §CM-1 element-2 project-URL line.

    The shape, and nothing wider: ONE line, an optional list marker, an optional
    `<label>: ` prefix that is short and carries no URL of its own, then a single URL token
    — bare (`https://x`), angle-bracketed (`<https://x>`), or a markdown link
    (`[text](https://x)`). A URL merely mentioned INSIDE prose fails, because prose leaves
    text after the URL, or puts a whole clause where the label belongs.
    """
    stripped = block_text.strip()
    if "\n" in stripped:
        return False
    body = _LIST_ITEM_RE.sub("", stripped, count=1).strip()
    if not body:
        return False
    # rpartition, not partition: a label may legitimately contain its own colon
    # ("Repo (see also: mirrors): https://…"), and only the LAST ": " separates label
    # from URL.
    label, sep, rest = body.rpartition(": ")
    if sep:
        if len(label) > _URL_LABEL_MAX_CHARS or _URL_ANYWHERE_RE.search(label):
            return False
        body = rest.strip()
    return bool(_BARE_URL_RE.fullmatch(body) or _MD_LINK_URL_RE.fullmatch(body) or _ANGLE_URL_RE.fullmatch(body))


def classify_permitted(block: NarrativeBlock, *, index: int) -> str | None:
    """Which of the three narrative-visible §CM-1 elements `block` IS, or None when it is
    excess narrative the chore must migrate.

    - **description** — the FIRST content block, and only when it sits in the preamble
      (above the first section heading) and is not a list item. "One-paragraph" is the
      spec's own wording, so exactly one block can ever hold this role and a second
      preamble paragraph is excess. A narrative that opens under a `## Section` heading has
      no description element at all, and its first block is judged on its own merits.
    - **urls** — `is_project_url_line`.
    - **devops** — `classify_exemption`, the closed §CM-3 enumeration, unchanged.
    """
    if index == 0 and block.in_preamble and not _LIST_ITEM_RE.match(block.text):
        return PERMITTED_DESCRIPTION
    if is_project_url_line(block.text):
        return PERMITTED_URLS
    if classify_exemption(block.text) is not None:
        return PERMITTED_DEVOPS
    return None


# ── 4. New-page scope routing (memory-scope-routing.md's WRITE gate) ────────────────────

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
    verdict: str  # "permitted" | "fold" | "new_page"
    permitted_element: str = ""  # one of PERMITTED_ELEMENTS, when verdict == "permitted"
    exemption_word: str = ""  # the matched §CM-3 category, when permitted_element == devops
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
    """The whole DECISION half: narrative -> blocks -> (permitted | fold | new_page) each.

    NEVER writes CLAUDE.md, NEVER writes/creates a memory page — `claude_md_text` and
    `roots` are read-only inputs (roots are read by the `memgrep recall` subprocess only).

    TWO independent gates, and the distinction matters because conflating them is what
    shipped broken twice on 2026-08-13:

    - **WHETHER to plan at all** — `slim_violations`. A file `check` already calls
      conforming plans nothing. This is a deliberate SCOPE choice, not a correctness
      requirement: §CM-1 says "these five and nothing else", so a small non-permitted block
      under the byte cap is technically a defect this planner will not report. Editing
      CLAUDE.md busts the prompt-cache prefix of every live session (TRDD-e247a349 §5), so
      churning a file the contract check calls fine costs more than the stray block does.
    - **WHICH blocks are the defect** — `classify_permitted`, per block. `slim_violations`
      structurally cannot answer this (it is four whole-file checks), and using it as if it
      could was the `20f226ba` partial fix: it silenced the CONFORMING case and left every
      permitted element wrongly migratable the moment the file went over cap — the only
      case the chore exists for.
    """
    if not slim_violations(claude_md_text):
        return []
    narrative = narrative_outside_fences(claude_md_text)
    blocks = split_narrative_blocks(narrative)
    binary = memgrep_bin or find_memgrep()
    plans: list[BlockPlan] = []
    for index, block in enumerate(blocks):
        element = classify_permitted(block, index=index)
        if element is not None:
            word = classify_exemption(block.text) or "" if element == PERMITTED_DEVOPS else ""
            plans.append(
                BlockPlan(block=block, verdict="permitted", permitted_element=element, exemption_word=word)
            )
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
    migratable = [p for p in plans if p.verdict != "permitted"]
    lines = [
        f"claudemd-migration-plan: {len(migratable)} migratable block(s) of {len(plans)} narrative "
        f"block(s) ({len(plans) - len(migratable)} permitted by spec §CM-1)",
        "",
    ]
    for i, p in enumerate(plans, start=1):
        if p.verdict == "permitted":
            detail = f"§CM-1 element: {p.permitted_element}"
            if p.exemption_word:
                detail += f", matched enumeration word: {p.exemption_word!r}"
            lines.append(f"[{i}] PERMITTED ({detail})")
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
