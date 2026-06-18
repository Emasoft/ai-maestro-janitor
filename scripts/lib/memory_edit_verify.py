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


def parse_frontmatter(text: str) -> dict:
    """Flatten a wikimem note's YAML frontmatter into one dict (top-level keys +
    the `metadata:` sub-keys hoisted to the top level). Returns {} when there is
    no leading `---` block. Intentionally tiny — not a YAML engine."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: dict = {}
    in_meta = False
    for raw in lines[1:]:
        if raw.strip() == "---":
            break
        if not raw.strip():
            continue
        indented = raw[:1].isspace()
        s = raw.strip()
        if s == "metadata:":
            in_meta = True
            continue
        if ":" not in s:
            continue
        key, _, val = s.partition(":")
        key = key.strip()
        if indented and in_meta:
            fm[key] = _parse_scalar_or_list(val)
        elif not indented:
            in_meta = False
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
    body = re.sub(r"^\s*\[ocd:[^\]]*\]\s*", "", body)
    body = re.sub(r"\s+", " ", body)
    return body.strip()


def extract_lessons(text: str) -> list[str]:
    """Return the normalized body of every `[^N]: …` footnote definition in `text`
    (multi-line continuations folded in). Order-preserving; numbers ignored."""
    # Footnote def = `[^id]:` at line start, body runs until the next def or EOF.
    out: list[str] = []
    for m in re.finditer(r"(?ms)^\[\^[^\]]+\]:.*?(?=^\[\^[^\]]+\]:|\Z)", text):
        norm = _normalize_lesson(m.group(0))
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
# duplicate detection (a merge must REMOVE redundancy, never ADD it)
# --------------------------------------------------------------------------- #

def no_new_duplicate_lines(result: str, min_len: int = 24) -> tuple[bool, list[str]]:
    """No substantive content line (length ≥ `min_len`, not a heading/list marker)
    appears more than once in `result`. Catches a naive union that re-introduced
    the very duplication the merge was meant to remove."""
    seen: dict[str, int] = {}
    for raw in result.splitlines():
        s = raw.strip()
        if len(s) < min_len or s.startswith("#") or s.startswith("```"):
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


def is_legal_split(meta: dict, body: str, min_sections: int = 2) -> tuple[bool, str]:
    """Refuse a structurally-illegal split. Per the wikimem model "one element =
    one page", a `component` is a single element and is NEVER fragmented (an
    oversized component is flagged for a human and links UP to aspects instead);
    only `hub`s (→ sub-hubs) and broad `aspect`s (→ sub-aspects) split. And a page
    is splittable only if its body (excluding the mandatory `## Notes and lessons
    learned` section) carries at least `min_sections` distinct `##` content
    sections — otherwise it is one atomic note over the size cap, left intact."""
    if meta.get("tier") == "component":
        return (False, "a component is one element (one element = one page) — never fragmented")
    sections = 0
    for raw in body.splitlines():
        s = raw.strip()
        if s.startswith("## ") and s != _LESSONS_HEADING:
            sections += 1
    if sections < min_sections:
        return (False, f"un-splittable: {sections} content section(s) < {min_sections} (atomic element)")
    return (True, "ok")


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
        for g in (globs or []):
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
