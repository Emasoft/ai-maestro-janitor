# Wikimem edit verifier (TRDD-b92a9dd0) — the oracle that proves an editorial
# pass LOST NOTHING before its transaction commits. The agent does the merge/split
# (semantic judgment a script can't make); these functions prove the structural
# invariants a script CAN and MUST guarantee.
#
# Design rule (the user's split of powers): scripts verify, agents judge. So the
# strict, machine-checkable invariant is LESSON PRESERVATION — every `[^N]`
# lesson (the compounding history / the WHY) from every source must survive into
# the result, by BODY text, not by footnote number (renumbering is allowed;
# dropping or rewording a lesson is NOT). Facts may be deduped/reworded by the
# agent — that is the editorial job — so a verbatim "every fact line" check would
# false-fail on every real merge; the lessons are the sacred, never-lost layer.
#
# The lesson check is deliberately PARSER-INDEPENDENT of the editor's own parser
# (it works on normalized raw text), so a shared frontmatter-parser bug cannot
# hide a dropped lesson from both the editor and its verifier (the tautology trap).

from __future__ import annotations

import re

_LESSONS_HEADING = "## Notes and lessons learned"


# --------------------------------------------------------------------------- #
# minimal frontmatter parsing (the SMALL, metadata-only concern — kept separate
# from the parser-independent lesson check on purpose)
# --------------------------------------------------------------------------- #


def _parse_scalar_or_list(val: str):
    val = val.strip()
    if val.startswith("[") and val.endswith("]"):
        inner = val[1:-1].strip()
        if not inner:
            return []
        return [item.strip().strip('"').strip("'") for item in inner.split(",") if item.strip()]
    return val.strip().strip('"').strip("'")


def _split_top_level(inner: str) -> list[str]:
    """Split a flow-map body on commas that are NOT inside [] or {} brackets, so
    `tier: component, globs: ["a", "b"]` splits into two pairs and NOT on the comma
    between the two globs."""
    parts: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in inner:
        if ch in "[{":
            depth += 1
        elif ch in "]}":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        parts.append("".join(buf))
    return [p for p in (seg.strip() for seg in parts) if p]


def parse_frontmatter(text: str) -> dict:
    """Flatten a wikimem note's YAML frontmatter into one dict (top-level keys +
    the `metadata:` sub-keys hoisted to the top level). Returns {} when there is
    no leading `---` block. Intentionally tiny — not a YAML engine."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict = {}
    in_meta = False
    # M-4 (wikimem audit 2026-07-07): a key whose BLOCK-style list is being
    # collected (`globs:` followed by indented `- item` lines). Block style is
    # what a generic YAML-writing agent naturally emits; skipping the no-colon
    # item lines made a hub's block-style `globs:` read as empty and the split
    # globs-partition check vacuous — the same bug class as the flow-style hole
    # (audit Finding 1) in a third spelling.
    pending_list_key: str | None = None
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        if not raw.strip():
            continue
        indented = raw[:1].isspace()
        s = raw.strip()
        if s == "metadata:":
            in_meta = True
            pending_list_key = None
            continue
        if pending_list_key is not None and indented and (s == "-" or s.startswith("- ")):
            item = s[1:].strip().strip('"').strip("'")
            if item:
                fm[pending_list_key].append(item)
            continue
        pending_list_key = None
        if ":" not in s:
            continue
        key, _, val = s.partition(":")
        key = key.strip()
        # Flow-style metadata: `metadata: {tier: hub, globs: ["a","b"]}` — hoist the
        # inner k:v pairs to the top level exactly like the block-style branch, so the
        # verify guards (is_legal_merge/is_legal_split, the hub globs-partition) see
        # tier/type/globs. Without this a flow-style hub split that DROPS a glob
        # committed clean (memory-helpers audit Finding 1, TRDD-87935f21). Split
        # bracket-aware so a list value's internal commas don't break the pairs.
        if key == "metadata" and not indented and val.strip().startswith("{"):
            in_meta = False
            for pair in _split_top_level(val.strip().lstrip("{").rstrip("}")):
                if ":" in pair:
                    k2, _, v2 = pair.partition(":")
                    fm[k2.strip()] = _parse_scalar_or_list(v2)
            continue
        if indented and in_meta:
            if not val.strip():
                fm[key] = []  # a block list opens here; items follow
                pending_list_key = key
            else:
                fm[key] = _parse_scalar_or_list(val)
        elif not indented:
            in_meta = False
            if not val.strip():
                fm[key] = []
                pending_list_key = key
            else:
                fm[key] = _parse_scalar_or_list(val)
    return fm


# --------------------------------------------------------------------------- #
# lesson preservation — the STRICT, parser-independent anti-data-loss check
# --------------------------------------------------------------------------- #


def _normalize_lesson(body: str) -> str:
    """Reduce a lesson to its substantive text for drop/reword detection: strip
    the `[^N]:` footnote marker and a leading `[ocd:… lmd:…]` metadata prefix
    (both legitimately mutate — renumber, date-bump — without changing meaning),
    then collapse whitespace. What remains is the claim; if THAT changes, it was
    reworded; if it vanishes, it was dropped."""
    body = re.sub(r"^\s*\[\^[^\]]+\]:\s*", "", body)
    # Strip a leading metadata prefix in ANY spelling — `[ocd:… lmd:…]` (canonical),
    # `[lmd:…]` alone, or two separate `[ocd:…] [lmd:…]` brackets — so a legal
    # metadata-format change is not misread as a reworded lesson (audit Finding 2).
    body = re.sub(r"^\s*(?:\[(?:ocd|lmd):[^\]]*\]\s*)+", "", body)
    body = re.sub(r"\s+", " ", body)
    return body.strip()


def extract_lessons(text: str) -> list[str]:
    """Return the normalized body of every `[^N]: …` footnote definition in `text`
    (multi-line continuations folded in). Order-preserving; numbers ignored."""
    # Footnote def = `[^id]:` at line start, body runs until the next def, the
    # next full-line heading, or EOF. The heading stop is L-2 (wikimem audit
    # 2026-07-07): without it a trailing section after the lessons pool (e.g.
    # `## See also`) is swallowed into the LAST lesson's body, contaminating
    # lessons_preserved's comparison and false-failing edits that legitimately
    # move that section.
    #
    # F11 (audit 2026-07-13): but `^#{1,6}\s` also matched a SHELL COMMENT at column 0
    # inside a lesson that quotes a command (`# never use git add -A`) — truncating the
    # lesson there. The truncation is applied to source AND result alike, so it cannot
    # false-fail; that is exactly the problem. Everything past that line silently fell
    # OUTSIDE the sacred never-lost layer, and an editorial pass could drop it and still
    # pass a check that advertises itself as STRICT. A real markdown section heading is
    # followed by a capital or a bracket (`## Notes…`, `## [Link]…`); `# never use …` is
    # not. Fenced code is masked first, so a `# comment` inside a ``` block cannot stop a
    # lesson either.
    scan = _mask_code_fences(text)  # offset-preserving, so spans index `text` too
    out: list[str] = []
    for m in re.finditer(r"(?ms)^\[\^[^\]]+\]:.*?(?=^\[\^[^\]]+\]:|^#{1,6} [A-Z(\[]|\Z)", scan):
        # Slice the ORIGINAL text: the mask exists only to stop a `#`/`[^id]` INSIDE a fence
        # from being read as a boundary — the lesson's real content (code included) is what
        # must be compared.
        norm = _normalize_lesson(text[m.start() : m.end()])
        if norm:
            out.append(norm)
    return out


def lessons_preserved(sources: list[str], result: str) -> tuple[bool, list[str]]:
    """STRICT: every source lesson's substantive body must survive into `result`.

    A lesson is preserved iff its normalized body is a SUBSTRING of the result's
    normalized lessons blob — substring (not equality) so the agent may COMPOUND a
    lesson (append later history) without false-failing, while a DROP (body absent)
    or a REWORD (body text changed) is caught. Returns (ok, [missing bodies])."""
    result_blob = " ␟ ".join(extract_lessons(result))
    missing: list[str] = []
    for src in sources:
        for body in extract_lessons(src):
            if body not in result_blob:
                missing.append(body)
    return (not missing, missing)


# --------------------------------------------------------------------------- #
# body-fact fidelity (issue #48 — an editor pass must never paraphrase/drop a FACT)
# --------------------------------------------------------------------------- #


def _strip_frontmatter(text: str) -> str:
    """The note minus its leading `--- … ---` YAML frontmatter block (the body + lessons section
    that follow it). Frontmatter changes — e.g. an `lmd:` bump — are validated by their own checks,
    so a body-shape comparison must exclude them."""
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            return parts[2]
    return text


def _body_minus_lessons(text: str) -> str:
    """The note's BODY: frontmatter stripped, and the `## Notes and lessons learned`
    section stripped (lessons are guarded separately by lessons_preserved)."""
    body = _strip_frontmatter(text)
    # L-3 (wikimem audit 2026-07-07): match the heading as a FULL LINE, never a
    # substring — meta-pages about the memory system mention `## Notes and
    # lessons learned` inline, and a find() on the raw string truncated the body
    # at that mention, leaving later facts unchecked in sources and false-failing
    # results.
    m = re.search(rf"(?m)^{re.escape(_LESSONS_HEADING)}\s*$", body)
    if m:
        body = body[: m.start()]
    return body


def _norm_page_blob(text: str) -> str:
    """Whitespace-collapsed, lowercased WHOLE-PAGE blob: frontmatter stripped, lessons
    KEPT. The haystack every fact-preservation check searches — a source fact line must
    be a SUBSTRING of it. Collapsing newlines means a fact merely reflowed or moved to
    another section still matches (its words stay contiguous).

    Two reasons it is the page and not the body (audit 2026-07-13):

    1. A fact DEMOTED into a `[^N]` lesson has MOVED, not vanished — that is precisely
       what the correction protocol mandates ("clean the body to the current truth AND
       demote the old statement to a dated `[^N]` lesson"). Only text absent from the
       WHOLE page is lost. Searching a lessons-stripped body declared every sanctioned
       correction a "dropped fact".
    2. `_body_minus_lessons` truncates at the FIRST `## Notes and lessons learned`
       heading — fatal when the haystack is a CONCATENATION of pages (a split's
       sub-pages, a harvest's wiki corpus), because every curated page mandatorily
       carries that heading, so the blob collapsed to page #1's body and every fact
       living in a later page read as missing."""
    return re.sub(r"\s+", " ", _strip_frontmatter(text)).strip().lower()


def _substantive_body_lines(text: str, min_len: int = 24) -> list[str]:
    """The substantive FACT lines of a body (normalized, lowercased, leading list
    marker stripped): non-blank, non-heading lines whose normalized length ≥ min_len.
    Short/structural lines (headings, markers, blanks, dividers) are not facts."""
    out: list[str] = []
    for raw in _body_minus_lessons(text).splitlines():
        s = raw.strip()
        if not s or s.startswith("#"):
            continue
        norm = re.sub(r"^[-*+]\s+", "", re.sub(r"\s+", " ", s).strip()).lower()
        if len(norm) >= min_len:
            out.append(norm)
    return out


def body_facts_preserved(sources: list[str], result: str, min_len: int = 24) -> tuple[bool, list[str]]:
    """STRICT anti-corruption (issue #48): every substantive body FACT line of every
    source must survive into `result` — as a SUBSTRING of the result's normalized body
    blob. Mirrors lessons_preserved, applied to the body. ALLOWS reorganization, an
    added lead, and dedup (a deduped/identical fact still appears once → still a
    substring); CATCHES a DROPPED or PARAPHRASED fact (its text is no longer a
    contiguous substring of the result). The substring (not line-equality) basis is why
    a reflow / section-move does not false-fail. A fact demoted into a `[^N]` lesson
    counts as PRESERVED — the haystack is the whole page (see `_norm_page_blob`), because
    demoting a superseded fact to a dated lesson is the correction protocol's mandated
    move, not a loss. Returns (ok, [missing facts, ≤8])."""
    haystack = _norm_page_blob(result)
    missing: list[str] = []
    for src in sources:
        for fact in _substantive_body_lines(src, min_len):
            if fact not in haystack:
                missing.append(fact)
    return (not missing, missing[:8])


# --------------------------------------------------------------------------- #
# harvest preservation (TRDD-a5780c23 Part C — never stub MEMORY.md while a memory
# it held is not yet in the wiki)
# --------------------------------------------------------------------------- #

_POINTER_RE = re.compile(r"^\s*[-*+]\s*\[[^\]]+\]\(([^)]+)\)")  # `- [Title](target.md) — hook`


def harvest_preservation_ok(memory_md_text: str, corpus_text: str, note_filenames) -> tuple[bool, list[str]]:
    """Prove a HARVEST lost nothing BEFORE MEMORY.md is reduced to the stub: every memory
    the old MEMORY.md held now lives in the wiki. A POINTER line (`- [T](target.md) — hook`)
    is preserved iff its target file is among `note_filenames` (the note IS the memory). A
    non-pointer substantive content line (≥24 chars) is preserved iff it is a SUBSTRING of
    `corpus_text` (the union of wikimem page bodies, whitespace-normalized) — i.e. the
    content was harvested into a page. Structural lines (headings, blanks, the deprecation
    stub notice, bare list markers) are not memories. Returns (ok, [unconfirmed, ≤8])."""
    names = set(note_filenames)
    haystack = re.sub(r"\s+", " ", corpus_text).strip().lower()
    unconfirmed: list[str] = []
    for raw in memory_md_text.splitlines():
        s = raw.strip()
        if not s or s.startswith("#") or s.startswith("⚠") or "index retired" in s.lower():
            continue
        m = _POINTER_RE.match(raw)
        if m:
            target = m.group(1).split("#")[0].split("/")[-1].strip()
            if target and target not in names:
                unconfirmed.append(f"pointer -> {target} (target note missing from the wiki)")
            continue
        norm = re.sub(r"^[-*+]\s+", "", re.sub(r"\s+", " ", s).strip()).lower()
        if len(norm) >= 24 and norm not in haystack:
            unconfirmed.append(norm)
    return (not unconfirmed, unconfirmed[:8])


# --------------------------------------------------------------------------- #
# mirror preservation (TRDD-ab232dbd — the COEXISTENCE gate)
#
# The coexistence model REVERSES the stub-reduction: harvest no longer touches the
# harness BUFFER (MEMORY.md + raw notes at the scope root). It MIRRORS each raw
# buffer note into a SEPARATE curated wiki page under `memory/wikimem/`. The invariant
# this proves is the OPPOSITE direction of harvest_preservation_ok: not "is every
# MEMORY.md memory in the wiki before we stub MEMORY.md", but "is every RAW BUFFER
# NOTE's content now present in the wiki" — with the buffer left 100% intact, so a
# failure means "mirror more", never "do not stub" (there is no stub step any more).
# --------------------------------------------------------------------------- #


def mirror_preservation_ok(buffer_notes, wiki_corpus: str, min_len: int = 24) -> tuple[bool, list[str]]:
    """Prove a coexistence HARVEST mirrored every raw buffer note into the wiki.

    `buffer_notes` is an iterable of ``(name, text)`` pairs — the RAW harness buffer
    notes (minimal/no wikimem frontmatter) the harvest was asked to mirror. `wiki_corpus`
    is the union of the curated wiki page bodies (the mirror target). A buffer note is
    MIRRORED iff every substantive BODY fact line of it (≥ `min_len` chars, frontmatter
    + headings + `[^N]` lessons excluded — those are not memories) is a SUBSTRING of the
    normalized wiki body blob. The substring (not line-equality) basis lets the agent
    reorganize / add a lead in the curated copy without false-failing; a DROPPED or
    paraphrased fact still fails. The buffer is NEVER modified, so a failure means the
    agent must mirror more — it never gates a reduction of the buffer.

    Returns ``(ok, [unmirrored, ≤8])`` where each entry NAMES the note plus the first
    missing fact, so the agent knows WHICH note to (re)mirror. An empty buffer (the
    dormant-corpus case — every note already curated) is trivially ``(True, [])``.

    The haystack is the whole-page blob (audit 2026-07-13): `wiki_corpus` is a
    CONCATENATION of every curated page, and the old body-only blob truncated it at the
    first page's mandatory `## Notes and lessons learned` heading — so the gate saw only
    page #1 and ABSTAINed on any note mirrored into a later page, forever."""
    haystack = _norm_page_blob(wiki_corpus)
    unmirrored: list[str] = []
    for name, text in buffer_notes:
        for fact in _substantive_body_lines(text, min_len):
            if fact not in haystack:
                unmirrored.append(f"{name}: {fact}")
                break  # one missing fact is enough to flag the note; mirror the whole note
    return (not unmirrored, unmirrored[:8])


# --------------------------------------------------------------------------- #
# duplicate detection (a merge must REMOVE redundancy, never ADD it)
# --------------------------------------------------------------------------- #


def no_new_duplicate_lines(result: str, min_len: int = 24) -> tuple[bool, list[str]]:
    """No substantive content line (length ≥ `min_len`, not a heading/list marker)
    appears more than once in `result`. Catches a naive union that re-introduced
    the very duplication the merge was meant to remove."""
    seen: dict[str, int] = {}
    in_fence = False
    for raw in result.splitlines():
        s = raw.strip()
        # L-6 (wikimem audit 2026-07-07): track fence STATE, don't just skip the
        # ``` line itself — the same ≥min_len command legitimately appears in two
        # code examples, and counting fence contents false-failed those merges.
        if s.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence or len(s) < min_len or s.startswith("#"):
            continue
        norm = re.sub(r"\s+", " ", s)
        seen[norm] = seen.get(norm, 0) + 1
    dups = [k for k, n in seen.items() if n > 1]
    return (not dups, dups)


# --------------------------------------------------------------------------- #
# dangling-link / connectedness check (THE LINK LAW)
# --------------------------------------------------------------------------- #


def _wikilinks(text: str) -> set[str]:
    return set(re.findall(r"\[\[([^\]]+)\]\]", text))


def canonicalize_retired_links(text: str, retired_slugs, survivor_slug: str) -> str:
    """Rewrite every `[[retired]]` wikilink to `[[survivor]]` — the redirect a merge MANDATES.

    This exists to resolve a deadlock between two invariants that were each correct alone and
    contradictory together (TRDD-MQBV844P):

    - `no_dangling_refs` REQUIRES that, once a slug retires, no surviving page still links to it —
      so the merged page's `[[retired]]` pointer MUST be redirected.
    - `body_facts_preserved` / `lessons_preserved` REQUIRE that every body line and every lesson
      survive as a BYTE-IDENTICAL substring — so that same line MUST NOT change.

    No merge output can satisfy both: keeping the pointer fails the first, editing or deleting it
    fails the second. And this is not an edge case — the wikimem LINK LAW mandates bidirectional
    links, so any two pages related enough to be merge candidates are GUARANTEED to cross-link.
    CONSOLIDATE could therefore never merge the very pages it exists to merge, and it failed
    SILENTLY, by abstaining, on every attempt.

    The resolution is to compare MODULO the mandated redirect: canonicalize the retired links on
    BOTH sides before matching, so the two oracles finally agree on what a merge *is*. This does not
    weaken the anti-corruption guarantee (issue #48) — every OTHER character of every line must still
    survive verbatim, and a genuinely dropped or paraphrased fact still fails. The ONLY edit it
    permits is the one the other invariant already demands.

    Alias links (`[[slug|shown text]]`) keep their alias; only the target is rewritten.
    """
    out = text
    for slug in retired_slugs:
        if not slug or slug == survivor_slug:
            continue
        out = re.sub(
            r"\[\[" + re.escape(str(slug)) + r"(\|[^\]]*)?\]\]",
            lambda m: f"[[{survivor_slug}{m.group(1) or ''}]]",
            out,
        )
    return out


def no_dangling_refs(live_pages: dict, retired_slugs) -> tuple[bool, list[str]]:
    """After a merge/split removes some slugs, NO surviving page may still
    `[[link]]` to a retired slug. `live_pages` is {slug_or_path: text}; returns
    (ok, ["holder -> retired", …]). This is the verify half of the LINK-LAW
    redirect the executor performs; a non-empty result means a redirect was missed."""
    retired = set(retired_slugs)
    dangling: list[str] = []
    for holder, text in live_pages.items():
        for target in _wikilinks(text):
            if target in retired:
                dangling.append(f"{holder} -> [[{target}]]")
    return (not dangling, dangling)


# --------------------------------------------------------------------------- #
# footnote-ref resolution (THE SHARED-FOOTNOTE MOVE-RULE) — TRDD-3b9b2040 g3
# --------------------------------------------------------------------------- #
#
# A page's notes / lessons / see-also live in a bottom footnote POOL (`[^N]: …`
# defs) and are cited inline by `[^N]`. ONE def can be SHARED by several atoms on
# the page, which is exactly why the defs are pooled at the bottom. When a
# split/merge MOVES an atom between pages, its `[^N]` refs travel with it — and a
# shared def must travel (be duplicated) onto every page that still cites it. The
# user's load-bearing move-rule: "do not delete a `[^N]` def from the source if
# another atom there still references it." Break it two ways and you get a
# DANGLING footnote ref — silent knowledge loss, because the note/lesson the
# footnote held becomes unreachable: (a) the def is dropped from the source while
# a sibling atom there still cites it, or (b) a ref moves to a new page without
# its def. This is the verify half of that rule.

_FN_DEF_RE = re.compile(r"(?m)^\[\^([^\]]+)\]:")  # a footnote DEFINITION: line-start `[^id]:`
_FN_ANY_RE = re.compile(r"\[\^([^\]]+)\]")  # ANY `[^id]` occurrence (refs + def markers)


def _mask_code_fences(text: str) -> str:
    """`text` with every fenced-code line blanked to SPACES (line structure AND character
    offsets preserved).
    L-4 (wikimem audit 2026-07-07): a page DOCUMENTING footnote syntax inside a
    ``` fence read as having a dangling `[^id]` ref, permanently failing every
    merge/split/repair that touched it — fence contents are examples, not refs.

    Offsets are preserved (F11) because `extract_lessons` scans the MASKED text to find each
    lesson's boundaries but must slice the ORIGINAL text to keep the lesson's real content —
    including any code it quotes. Blanking to same-length spaces makes span(masked) ==
    span(original)."""
    out: list[str] = []
    in_fence = False
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        nl = line[len(stripped) :]
        if stripped.lstrip().startswith("```"):
            in_fence = not in_fence
            out.append(" " * len(stripped) + nl)
            continue
        out.append((" " * len(stripped) + nl) if in_fence else line)
    return "".join(out)


def footnote_refs_resolve(text: str) -> tuple[bool, list[str]]:
    """Every `[^id]` REFERENCE in `text` must resolve to a `[^id]:` DEFINITION on
    the SAME page. Returns (no unresolved refs, sorted unresolved ids).

    A page is self-consistent iff every footnote it cites is also defined on it. A
    def WITHOUT a ref (an orphan def) is allowed — only a ref without a def is a
    dangling footnote. Computed by id: the def line `[^id]:` itself contains the
    marker `[^id]`, so `all_ids - def_ids` is exactly the set of referenced-but-
    undefined ids (an orphan def cancels itself out and is never flagged)."""
    # L-4: scan with fences masked — `[^id]` tokens inside code examples are
    # documentation, not references (and a def shown only in a fence is not a def).
    masked = _mask_code_fences(text)
    defs = set(_FN_DEF_RE.findall(masked))
    unresolved = sorted(set(_FN_ANY_RE.findall(masked)) - defs)
    return (not unresolved, unresolved)


def no_new_dangling_footnote_refs(source_texts: list[str], result_texts: list[str]) -> tuple[bool, list[str]]:
    """A split/merge must not INTRODUCE a dangling footnote ref. Compare per-ID
    sets, not counts (L-5, wikimem audit 2026-07-07): the count form let "fixed
    one dangling ref" buy a licence to orphan a DIFFERENT id in the same op. A
    result-side unresolved id is tolerated ONLY if that same id was already
    unresolved in a source (carried forward, not introduced); a renumbered lesson
    stays guarded by the body-text lessons_preserved check. This enforces the
    shared-footnote move-rule (a def is never dropped while an atom still cites
    it, and a moved ref carries its def). Returns (ok, sorted NEW offenders)."""
    src_unresolved: set[str] = set()
    for t in source_texts:
        src_unresolved.update(footnote_refs_resolve(t)[1])
    new_ids: set[str] = set()
    for t in result_texts:
        new_ids.update(i for i in footnote_refs_resolve(t)[1] if i not in src_unresolved)
    return (not new_ids, sorted(f"[^{i}]" for i in new_ids))


# --------------------------------------------------------------------------- #
# metadata invariants (ocd/lmd through a merge)
# --------------------------------------------------------------------------- #


def ocd_lmd_ok_merge(source_metas: list[dict], result_meta: dict) -> tuple[bool, str]:
    """The survivor of a merge keeps the OLDEST origin date and a fresh modify
    date: `ocd == min(source ocds)` (origin is never lost) and `lmd >=
    max(source lmds)` (the edit advanced it). ISO `YYYY-MM-DD` sorts lexically."""
    src_ocds = [str(m["ocd"]) for m in source_metas if m.get("ocd")]
    src_lmds = [str(m["lmd"]) for m in source_metas if m.get("lmd")]
    r_ocd = str(result_meta["ocd"]) if result_meta.get("ocd") else None
    r_lmd = str(result_meta["lmd"]) if result_meta.get("lmd") else None
    if not src_ocds or not r_ocd:
        return (False, "missing ocd on a source or the result")
    if r_ocd != min(src_ocds):
        return (False, f"result ocd {r_ocd} != min(sources) {min(src_ocds)}")
    if src_lmds and r_lmd and r_lmd < max(src_lmds):
        return (False, f"result lmd {r_lmd} regressed below max(sources) {max(src_lmds)}")
    return (True, "ok")


# --------------------------------------------------------------------------- #
# legality predicates (which merges/splits are STRUCTURALLY illegal → refuse)
# --------------------------------------------------------------------------- #

_MERGEABLE_TIERS = {"aspect", "component"}


def is_legal_merge(meta_a: dict, meta_b: dict) -> tuple[bool, str]:
    """Refuse a structurally-illegal merge (the agent still decides SUBJECT
    sameness; this only blocks merges that violate the wikimem model):
    - both tiers must be equal AND in {aspect, component} — never mix an `aspect`
      (a radiating rule) with a `component` (a terminal element), and never merge
      two `hub`s (a hub is a functionality's single overview, not a mergeable leaf);
    - both `metadata.type` must match (a `project` note and a `reference` note are
      different kinds even if they share words).
    The caller guarantees both pages are in the SAME scope (the txn is per-scope)."""
    ta, tb = meta_a.get("tier"), meta_b.get("tier")
    if ta != tb:
        return (False, f"cross-tier merge refused: {ta} vs {tb}")
    if ta not in _MERGEABLE_TIERS:
        return (False, f"tier {ta!r} is not mergeable (hubs are overviews, not leaves)")
    if meta_a.get("type") != meta_b.get("type"):
        return (False, f"cross-type merge refused: {meta_a.get('type')} vs {meta_b.get('type')}")
    return (True, "ok")


def is_legal_split(meta: dict, body: str, min_sections: int = 2, oversized: bool = False) -> tuple[bool, str]:
    """Decide whether a page may be split. Per the wikimem model "one element =
    one page", a `component` is a single element and is NEVER fragmented (an
    oversized component is a MIS-TIER — surfaced for re-tiering + linking UP to
    aspects, never silently abstained); only `hub`s (→ sub-hubs) and broad
    `aspect`s (→ sub-aspects) split.

    A hub/aspect with >= `min_sections` distinct `##` content sections (excluding
    the mandatory `## Notes and lessons learned`) splits at its natural seams.

    A SEAMLESS hub/aspect (fewer sections) is FAIL-SAFE splittable when it is
    `oversized` (issue #57/#58): the splitter SYNTHESIZES seams — paragraph- or
    line-chunking with every line copied verbatim — so an over-cap page ALWAYS
    converges instead of abstaining every cycle forever. `verify_split` proves
    the synthesized split lost nothing (it checks output invariants, not the
    source's seam count, so a synthesized split is already legal there). A
    seamless page that is NOT oversized has nothing to gain from fragmenting, so
    it is left intact."""
    if meta.get("tier") == "component":
        return (False, "a component is one element (one element = one page) — never fragmented")
    sections = 0
    for raw in body.splitlines():
        s = raw.strip()
        if s.startswith("## ") and s != _LESSONS_HEADING:
            sections += 1
    if sections >= min_sections:
        return (True, "ok")
    # Seamless body: fail-safe seam synthesis only makes sense for an over-cap
    # page (an under-cap seamless page is fine as one element — don't fragment it).
    if oversized:
        return (True, "ok: synthesize seams (seamless oversized page)")
    return (False, f"un-splittable: {sections} content section(s) < {min_sections} (not oversized)")


# --------------------------------------------------------------------------- #
# split-specific structural checks
# --------------------------------------------------------------------------- #


def split_globs_partition_ok(parent_globs, subpage_globs_list) -> tuple[bool, str]:
    """When a `hub` splits, its `globs:` ownership must PARTITION across the
    sub-pages: their union equals the parent's set (no pattern dropped) and no
    pattern appears in more than one sub-page (no overlap → no ambiguous owner)."""
    parent = set(parent_globs or [])
    union: set = set()
    seen: set = set()
    overlap: set = set()
    for globs in subpage_globs_list:
        for g in globs or []:
            if g in seen:
                overlap.add(g)
            seen.add(g)
            union.add(g)
    if overlap:
        return (False, f"globs overlap across sub-pages: {sorted(overlap)}")
    if union != parent:
        missing = parent - union
        extra = union - parent
        return (False, f"globs not a partition (missing={sorted(missing)} extra={sorted(extra)})")
    return (True, "ok")


def split_converged(page_sizes: dict, max_bytes: int, unsplittable=None) -> tuple[bool, list[str]]:
    """Every output page is within the size cap, OR explicitly flagged
    un-splittable (a single atomic note over the cap, left for a human). A page
    over the cap that is NOT flagged means the split GAVE UP without converging —
    that is a failure, distinct from a clean convergence."""
    flagged = set(unsplittable or set())
    oversized = [p for p, n in page_sizes.items() if n > max_bytes and p not in flagged]
    return (not oversized, oversized)


# --------------------------------------------------------------------------- #
# composite verifiers — the ONE call each executor (merge / split) runs before
# its transaction commits. Each composes the primitives above into a single
# (ok, reasons) verdict; a non-empty `reasons` list aborts the txn.
# --------------------------------------------------------------------------- #


def verify_merge(
    source_texts: list[str],
    source_metas: list[dict],
    result_text: str,
    result_meta: dict,
    retired_slugs,
    other_live_pages: dict,
    fact_source_texts: list[str] | None = None,
) -> tuple[bool, list[str]]:
    """Prove a MERGE lost nothing before its transaction commits.

    Composes the four merge invariants into one verdict:
    - LESSON PRESERVATION — every `[^N]` lesson from every source survives into
      the merged page (the sacred never-lost layer; reword/drop FAILS).
    - OCD/LMD — the survivor keeps the oldest origin date + a fresh modify date.
    - NO NEW DUPLICATES — a merge REMOVES redundancy; a naive union that
      re-introduced a duplicate content line FAILS.
    - NO DANGLING REFS — the LINK LAW: after the source slugs retire, NO surviving
      page (the merged page itself OR any OTHER live page) may still `[[link]]` a
      retired slug — that means a backlink redirect was missed.

    `other_live_pages` is {slug_or_path: text} of every page in the scope OTHER
    than the merged result; the dangling check unions it with the result so a
    missed redirect anywhere in the corpus is caught.

    `fact_source_texts` (default: all sources) narrows WHICH sources the body-fact
    oracle demands survive. Only the CONFLICT pass passes it, with the SURVIVING
    sources alone: a conflict resolution exists to SUPERSEDE the retired page's claim
    (conflict-protocol Stage 4 — the survivor's body becomes the CURRENT truth and the
    obsolete claim is reworded into a `[^N]` lesson), so demanding that claim survive
    verbatim in the body is self-contradictory and refused every conflict verdict there
    has ever been. Narrowing (rather than disabling) the oracle keeps the survivor's own
    body sacred, which is exactly the page a conflict pass rewrites. The retired page's
    lessons are still guarded, strictly, by `lessons_preserved` below.

    Returns (ok, [reasons])."""
    reasons: list[str] = []

    # Compare the preservation oracles MODULO the retired→survivor link redirect that
    # `no_dangling_refs` (below) MANDATES. Without this the two invariants are mutually
    # unsatisfiable for any cross-linked pair — and the LINK LAW guarantees every merge candidate IS
    # cross-linked, so CONSOLIDATE could never merge anything and abstained silently forever
    # (TRDD-MQBV844P). See `canonicalize_retired_links`: it permits ONLY the edit the other invariant
    # demands; every other character must still survive byte-for-byte, so a genuinely dropped or
    # paraphrased fact still fails exactly as before.
    #
    # `no_dangling_refs` deliberately keeps checking the RAW result, so a merge that FORGOT to
    # redirect is still caught — we normalize for the *comparison*, never for the link law itself.
    survivor = str(result_meta.get("name") or "").strip()
    retired = [s for s in retired_slugs if s]
    if survivor and retired:

        def _canon(t: str) -> str:
            return canonicalize_retired_links(t, retired, survivor)
    else:

        def _canon(t: str) -> str:
            return t

    result_cmp = _canon(result_text)

    ok, missing = lessons_preserved([_canon(t) for t in source_texts], result_cmp)
    if not ok:
        reasons.append("dropped/reworded lesson(s): " + "; ".join(missing))

    fact_sources = source_texts if fact_source_texts is None else fact_source_texts
    ok, missing_facts = body_facts_preserved([_canon(t) for t in fact_sources], result_cmp)
    if not ok:
        reasons.append("dropped/paraphrased body fact(s): " + "; ".join(missing_facts))

    ok, why = ocd_lmd_ok_merge(source_metas, result_meta)
    if not ok:
        reasons.append("ocd/lmd: " + why)

    ok, dups = no_new_duplicate_lines(result_text)
    if not ok:
        reasons.append("duplicate content line(s) re-introduced: " + "; ".join(dups))

    live_after = dict(other_live_pages or {})
    live_after["__merged_result__"] = result_text
    ok, dangling = no_dangling_refs(live_after, retired_slugs)
    if not ok:
        reasons.append("dangling refs to retired slug(s): " + "; ".join(dangling))

    ok, fn = no_new_dangling_footnote_refs(source_texts, [result_text])
    if not ok:
        reasons.append("orphaned shared footnote ref(s) introduced: " + ", ".join(fn))

    return (not reasons, reasons)


def verify_split(
    source_text: str,
    source_meta: dict,
    subpage_texts: list[str],
    subpage_metas: list[dict],
    overview_text: str,
    page_sizes: dict,
    max_bytes: int,
    unsplittable=None,
    retired_slugs=None,
    other_live_pages: dict | None = None,
) -> tuple[bool, list[str]]:
    """Prove a SPLIT lost nothing before its transaction commits.

    Composes the split invariants into one verdict:
    - LESSON PRESERVATION — every lesson of the SOURCE page survives SOMEWHERE
      across the sub-pages (checked over the concatenated sub-page bodies; the
      overview is a map of summaries, so lessons live in the leaves it points to).
    - GLOBS PARTITION — only when the SOURCE is a `hub`: its `globs:` ownership
      must partition across the sub-pages (union == parent, no overlap). A
      non-hub source has no `globs` ownership to partition, so the check is skipped.
    - CONVERGENCE — every output page is within the size cap or flagged
      un-splittable (an atomic leaf over the cap, left intact); an unflagged
      over-cap page means the split gave up.
    - NO DANGLING REFS — after the source slug retires, no surviving page (the
      overview, the sub-pages, or any OTHER live page) `[[link]]`s the retired slug.

    `page_sizes` is {page_path: byte_len} for every output (overview + sub-pages).
    `retired_slugs` defaults to empty (a split that keeps the source slug as the
    overview retires nothing); pass the source slug when it is replaced. Returns
    (ok, [reasons])."""
    reasons: list[str] = []

    # The overview is part of the output and may itself carry a stray lesson; fold
    # it into the concatenation so a lesson placed there is still counted preserved.
    concatenated = "\n".join([*subpage_texts, overview_text])
    ok, missing = lessons_preserved([source_text], concatenated)
    if not ok:
        reasons.append("source lesson(s) lost across sub-pages: " + "; ".join(missing))

    # The haystack is the raw concatenation: body_facts_preserved now searches the
    # WHOLE page (`_norm_page_blob`), which neither truncates at a lessons heading nor
    # loses a fact the split legitimately moved into a sub-page's lessons section. The
    # old workaround pre-stripped each page's lessons to dodge that truncation.
    ok, missing_facts = body_facts_preserved([source_text], concatenated)
    if not ok:
        reasons.append("source body fact(s) lost/paraphrased across sub-pages: " + "; ".join(missing_facts))

    if source_meta.get("tier") == "hub":
        ok, why = split_globs_partition_ok(source_meta.get("globs"), [m.get("globs") for m in subpage_metas])
        if not ok:
            reasons.append("globs: " + why)

    ok, oversized = split_converged(page_sizes, max_bytes, unsplittable)
    if not ok:
        reasons.append("un-converged over-cap page(s): " + ", ".join(oversized))

    live_after = dict(other_live_pages or {})
    live_after["__overview__"] = overview_text
    for i, txt in enumerate(subpage_texts):
        live_after[f"__subpage_{i}__"] = txt
    ok, dangling = no_dangling_refs(live_after, retired_slugs or set())
    if not ok:
        reasons.append("dangling refs to retired slug(s): " + "; ".join(dangling))

    ok, fn = no_new_dangling_footnote_refs([source_text], [overview_text, *subpage_texts])
    if not ok:
        reasons.append("orphaned shared footnote ref(s) introduced: " + ", ".join(fn))

    return (not reasons, reasons)


# --------------------------------------------------------------------------- #
# repair — single-page in-place page-shape / metadata backfill (TRDD-87935f21)
# --------------------------------------------------------------------------- #

# Every wikimem page MUST carry these. The repair pass backfills them; verify_repair
# refuses a "repair" that still lacks any (it didn't finish) or that DROPPED one.
# `tier` is deliberately NOT here (issue #68 P3, TRDD-UENXDA8P): the model says
# "absent ⇒ treat as component" (wikimem-model.md), so a tier-less page is VALID and a
# minimal repair of one must pass. An EXPLICIT tier is still validated against
# _VALID_TIERS below; the repair skill still INFERS a tier when it completes a page.
_REQUIRED_FM_KEYS = ("name", "description", "ocd", "lmd", "node_type", "type")
_VALID_TIERS = ("hub", "aspect", "component")


def verify_repair(
    source_text: str,
    source_meta: dict,
    result_text: str,
    result_meta: dict,
) -> tuple[bool, list[str]]:
    """Prove an in-place page REPAIR lost nothing AND actually completed the page.

    Repair is additive structural maintenance of ONE page — backfill missing
    metadata, add the Notes section, set/correct the tier, fix a tier/edge
    inversion — NOT a merge or split, so it produces exactly ONE write at the SAME
    path, zero deletes (the CLI enforces that shape). The verifier guarantees:

    - LESSON PRESERVATION — every `[^N]` lesson of the source survives (sacred, the
      same parser-independent check merge/split use).
    - COMPLETENESS — the result carries every REQUIRED frontmatter key with a
      non-empty value; a `tier`, WHEN PRESENT, must be from the legal set (absent
      is valid — the model reads it as `component`).
    - NO METADATA LOSS — repair never DROPS a frontmatter key the source had.
    - ORIGIN PRESERVED — `ocd` is unchanged when the source already had one (a
      repair must never rewrite a page's birth date); `lmd` is not regressed.
    - NOTES SECTION — the standing `## Notes and lessons learned` section is present.

    Returns (ok, [reasons])."""
    reasons: list[str] = []

    ok, missing = lessons_preserved([source_text], result_text)
    if not ok:
        reasons.append("lesson(s) lost in repair: " + "; ".join(missing))

    absent = [k for k in _REQUIRED_FM_KEYS if not str(result_meta.get(k, "")).strip()]
    if absent:
        reasons.append("frontmatter still missing required key(s): " + ", ".join(absent))

    tier = result_meta.get("tier")
    if tier and tier not in _VALID_TIERS:
        reasons.append(f"invalid tier {tier!r} (must be one of {', '.join(_VALID_TIERS)})")

    dropped = [k for k in source_meta if k not in result_meta]
    if dropped:
        reasons.append("repair dropped frontmatter key(s): " + ", ".join(sorted(dropped)))

    s_ocd, r_ocd = source_meta.get("ocd"), result_meta.get("ocd")
    if s_ocd and r_ocd and str(s_ocd) != str(r_ocd):
        reasons.append(f"ocd must not change in repair: {s_ocd} -> {r_ocd}")

    s_lmd, r_lmd = source_meta.get("lmd"), result_meta.get("lmd")
    if s_lmd and r_lmd and str(r_lmd) < str(s_lmd):
        reasons.append(f"lmd regressed in repair: {s_lmd} -> {r_lmd}")

    if _LESSONS_HEADING not in result_text:
        reasons.append(f"missing '{_LESSONS_HEADING}' section")

    return (not reasons, reasons)


# An atom block-property marker on its own line: `^<id> [<props>]` (TRDD-3b9b2040). The atomize pass
# adds markers on dedicated lines so every existing FACT line stays byte-identical — the regex matches
# exactly that shape (optional indent, kebab id, optional space, a bracketed props blob).
_ATOM_MARKER_RE = re.compile(r"^\s*\^[A-Za-z0-9_-]+\s*\[.*\]\s*$")


def verify_atomize(
    source_text: str,
    source_meta: dict,
    result_text: str,
    result_meta: dict,
) -> tuple[bool, list[str]]:
    """Prove an ATOMIZE pass (TRDD-3b9b2040) ONLY added `^id [keywords:…]` markers and lost nothing.

    Atomize segments a free-prose page body into first-class atoms by appending a block-property
    marker on its OWN line after each fact — purely ADDITIVE, so every existing fact line stays
    byte-identical. The verifier guarantees, STRICTLY (this mutates the live corpus — RULE 0):

    - LESSON PRESERVATION — every `[^N]` lesson of the source survives (sacred, parser-independent).
    - BODY-FACT FIDELITY — every substantive source body fact survives as a contiguous substring
      (the strict anti-corruption check; an atomize must NEVER drop or reword a fact).
    - METADATA UNTOUCHED — no frontmatter key dropped, `ocd` unchanged, `lmd` not regressed.
    - ATOMIZATION HAPPENED — the result carries at least one atom marker (a no-op must not commit).
    - ADDITIVE-MARKERS-ONLY — every NEW non-blank line (one not present in the source) is an atom
      marker line; atomize adds markers and nothing else (so it cannot smuggle in a body change).

    Returns (ok, [reasons])."""
    reasons: list[str] = []

    ok, missing = lessons_preserved([source_text], result_text)
    if not ok:
        reasons.append("lesson(s) lost in atomize: " + "; ".join(missing))

    ok, dropped_facts = body_facts_preserved([source_text], result_text)
    if not ok:
        reasons.append("body fact(s) dropped/reworded in atomize: " + "; ".join(dropped_facts))

    dropped = [k for k in source_meta if k not in result_meta]
    if dropped:
        reasons.append("atomize dropped frontmatter key(s): " + ", ".join(sorted(dropped)))

    s_ocd, r_ocd = source_meta.get("ocd"), result_meta.get("ocd")
    if s_ocd and r_ocd and str(s_ocd) != str(r_ocd):
        reasons.append(f"ocd must not change in atomize: {s_ocd} -> {r_ocd}")

    s_lmd, r_lmd = source_meta.get("lmd"), result_meta.get("lmd")
    if s_lmd and r_lmd and str(r_lmd) < str(s_lmd):
        reasons.append(f"lmd regressed in atomize: {s_lmd} -> {r_lmd}")

    markers = [ln for ln in result_text.splitlines() if _ATOM_MARKER_RE.match(ln)]
    if not markers:
        reasons.append("no atom markers in the result — atomize must add at least one `^id [keywords:…]`")

    # Every BODY line that is NOT in the source must be a marker line (atomize is additive-only). The
    # FRONTMATTER is excluded — atomize legitimately bumps `lmd` there (guarded above); the additive
    # guarantee is about the body, where the facts + the new markers live.
    src_lines = {ln.rstrip() for ln in _strip_frontmatter(source_text).splitlines()}
    for ln in _strip_frontmatter(result_text).splitlines():
        r = ln.rstrip()
        if r and r not in src_lines and not _ATOM_MARKER_RE.match(r):
            reasons.append(f"atomize added a non-marker line (only `^id [..]` markers may be added): {r[:80]!r}")
            break

    return (not reasons, reasons)
