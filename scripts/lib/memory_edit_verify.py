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

# The harness index filename, from the module that OWNS it (`memory_bridge.MEMORY_MD`) rather
# than a second literal — one source of truth, so a rename has a single edit site. Imported
# lazily inside the one function that needs it: this module is imported by hooks on a hot path
# and must not pull in the bridge's dependency chain (memory_txn, state) at import time.
def _memory_md_name() -> str:
    try:
        import memory_bridge  # noqa: PLC0415 - lazy: keeps the hot import path light

        return memory_bridge.MEMORY_MD
    except Exception:  # noqa: BLE001 - a verifier must never fail on a message string
        return "the harness memory index"

# Core shape of an ATOMIZE block-property marker — `^<id> [<props>]` (kebab id, a
# bracketed props blob). Shared so BOTH the atomize verifier (`_ATOM_MARKER_RE`,
# full-line, defined below) AND `extract_lessons`' footnote-capture stop-set key on
# ONE notion of "an atom marker": the atomize pass WRITES these lines, and split's
# lesson capture must STOP at them, or a `[^N]:` footnote followed by atomized fact
# content swallows the whole tail to EOF as one giant "lesson" and false-fails every
# legal split of that page (TRDD-MADJ00KA / issue #97). `[^\n]` (not `.`) bounds the
# props to one line regardless of the DOTALL flag on the surrounding pattern.
_ATOM_MARKER_CORE = r"\^[A-Za-z0-9_-]+\s*\[[^\n]*\]"


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


# The lesson-metadata keys memgrep's `split_note_metadata` recognizes inside the ONE bracket
# it reads after `[^N]:`. Kept as an explicit allow-list rather than "any `[k:v]`" so a lesson
# that legitimately OPENS with bracketed prose keeps that prose in its comparable text.
_LESSON_META_KEYS = r"id|status|keywords|ocd|lmd|desc|supersedes|superseded-by"


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
    #
    # KEYED ON THE WHOLE RECOGNIZED KEY SET, not just ocd/lmd (2026-08-02). Restricting it
    # to those two made the oracle DEADLOCK against memgrep's own grammar, and the deadlock
    # was total — no arrangement could satisfy both. `split_note_metadata` treats ONLY the
    # first bracket after `[^N]:` as metadata, so a stable `id:` MUST go inside that bracket;
    # but a legacy bracket leading with `keywords:` was not stripped here, so adding `id:` to
    # it broke the literal-substring fidelity check and `verify_repair` refused the edit. Put
    # `id:` in a second bracket instead and the parser stops seeing it (trailing) or drops
    # `keywords` from metadata (leading) — all four arrangements were empirically tested
    # against the real binary. Result: three lessons could never be given the stable id the
    # linter demands, and the repair correctly refused rather than corrupt them.
    #
    # FAITHFUL to this function's stated intent, not a loosening of it: the bracket is the
    # lesson's ADDRESS, never its claim. `DO NOT … BECAUSE … DO …` must survive verbatim and
    # is untouched by any metadata edit. Only recognized keys are stripped, so a lesson
    # opening with a markdown link (`[text](url)`) keeps its content.
    body = re.sub(rf"^\s*(?:\[(?:{_LESSON_META_KEYS}):[^\]]*\]\s*)+", "", body)
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
    # MADJ00KA (issue #97): the stop-set ALSO ends a footnote body at an atom-marker
    # line (`^id [keywords: …]`, shared `_ATOM_MARKER_CORE`). Without it, a `[^N]:`
    # lesson followed by atomized fact content with no closing `##` heading swallowed
    # the whole tail to EOF as one giant "lesson", false-failing every legal split of
    # that page. The atom alternative is line-anchored (`^\s*…\s*$` under `(?m)`), so
    # only a WHOLE atom-marker line stops a lesson — never a `^` mid-sentence — and it
    # matches on `scan`, so an atom marker inside a masked code fence cannot stop one.
    stop = (
        r"(?ms)^\[\^[^\]]+\]:.*?"
        r"(?=^\[\^[^\]]+\]:|^#{1,6} [A-Z(\[]|^\s*" + _ATOM_MARKER_CORE + r"\s*$|\Z)"
    )
    for m in re.finditer(stop, scan):
        # Slice the ORIGINAL text: the mask exists only to stop a `#`/`[^id]` INSIDE a fence
        # from being read as a boundary — the lesson's real content (code included) is what
        # must be compared.
        norm = _normalize_lesson(text[m.start() : m.end()])
        if norm:
            out.append(norm)
    return out


# The `keywords:` value inside a lesson's ADDRESS bracket — quoted (canonical) or bare.
# Scanned on the RAW def line, not the normalized body: `_normalize_lesson` strips the
# whole bracket, which is correct for BODY comparison but is exactly why keyword fidelity
# needs its own extraction (the 2026-08-02 widening removed the accidental coverage the
# old narrow strip provided).
_LESSON_DEF_BRACKET_RE = re.compile(r"^\s*\[\^[^\]]+\]:\s*\[([^\]]*)\]", re.MULTILINE)
_KEYWORDS_VALUE_RE = re.compile(r'keywords:\s*(?:"([^"]*)"|([^,\]]*))')


def _lesson_keyword_phrases(text: str) -> set[str]:
    """Every keyword PHRASE carried by any lesson's address bracket in `text`.
    Phrases are the whitespace-separated `underscore_joined` tokens of each
    `keywords:` value. Fences masked (a documented example is not a lesson)."""
    phrases: set[str] = set()
    for bracket in _LESSON_DEF_BRACKET_RE.findall(_mask_code_fences(text)):
        m = _KEYWORDS_VALUE_RE.search(bracket)
        if m:
            phrases.update((m.group(1) or m.group(2) or "").split())
    return phrases


def lessons_preserved(sources: list[str], result: str) -> tuple[bool, list[str]]:
    """STRICT: every source lesson's substantive body must survive into `result`.

    A lesson is preserved iff its normalized body is a SUBSTRING of the result's
    normalized lessons blob — substring (not equality) so the agent may COMPOUND a
    lesson (append later history) without false-failing, while a DROP (body absent)
    or a REWORD (body text changed) is caught.

    ALSO guards the lessons' RECALL SURFACE: every keyword phrase present in a
    source lesson's address bracket must survive somewhere in the result's lesson
    brackets. The bracket's other metadata (id/status/ocd/lmd) legitimately mutates
    — renumber, date-bump, id-backfill — but `keywords:` IS the memory's findability
    (no keywords ⇒ no recall), so the 2026-08-02 metadata-strip widening (needed to
    end the id-grammar deadlock) must not leave keyword DELETION unverified.
    Returns (ok, [missing bodies/keyword phrases])."""
    result_blob = " ␟ ".join(extract_lessons(result))
    missing: list[str] = []
    for src in sources:
        for body in extract_lessons(src):
            if body not in result_blob:
                missing.append(body)
    result_kw = _lesson_keyword_phrases(result)
    for src in sources:
        lost_kw = _lesson_keyword_phrases(src) - result_kw
        if lost_kw:
            missing.append("lesson keyword phrase(s) lost: " + " ".join(sorted(lost_kw)))
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
    """The note's BODY (singular): frontmatter stripped, and the ONE
    `## Notes and lessons learned` section stripped (lessons are guarded separately
    by lessons_preserved).

    Raises ValueError on a SECOND full-line lessons heading (TRDD-842PBES7 / issue
    #88 residual). A curated page mandates exactly one such heading, so two means the
    caller handed a multi-page CONCATENATION (or a malformed page) — and this
    extractor would otherwise SILENTLY truncate at the first, dropping every later
    page's facts from the check: a false PASS (the dangerous direction), since a
    merge/atomize that dropped those facts would be certified. A fail-safe verifier
    must fail LOUD on misuse, not certify silently. Callers that legitimately handle
    concatenations route through `_norm_page_blob` (which never truncates), so none
    needs to change."""
    body = _strip_frontmatter(text)
    # L-3 (wikimem audit 2026-07-07): match the heading as a FULL LINE, never a
    # substring — meta-pages about the memory system mention `## Notes and
    # lessons learned` inline, and a find() on the raw string truncated the body
    # at that mention, leaving later facts unchecked in sources and false-failing
    # results. The multi-heading raise below keys on the SAME full-line anchoring,
    # so an inline mention never trips it (only a genuine second section does).
    # TRDD-W9BWHGS3: match on the FENCE-MASKED body, not the raw one — a page
    # teaching the heading syntax inside a ```yaml example line was counted as a
    # real second section, refusing every consolidate that touched it. Masking
    # preserves offsets (see _mask_code_fences), so the match spans still slice
    # the ORIGINAL body correctly.
    matches = list(
        re.finditer(rf"(?m)^{re.escape(_LESSONS_HEADING)}\s*$", _mask_code_fences(body))
    )
    if len(matches) > 1:
        raise ValueError(
            f"_body_minus_lessons received text with {len(matches)} "
            f"'{_LESSONS_HEADING}' headings — a single-page extractor cannot handle a "
            "multi-page concatenation (it would silently drop pages 2..N's facts, a "
            "false PASS). Route concatenations through _norm_page_blob instead "
            "(TRDD-842PBES7 / issue #88)."
        )
    if matches:
        body = body[: matches[0].start()]
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
# load-bearing token fidelity (issue #91 — a path/constant can be silently
# MUTATED without the whole sentence around it changing enough to trip
# body_facts_preserved)
#
# body_facts_preserved guards whole FACT LINES >= min_len chars — a coarse,
# sentence-shaped net. It already catches a wholesale reworded/dropped sentence
# (any single mutated character breaks the substring match), but it has two
# blind spots by DESIGN, not oversight:
#   1. `_substantive_body_lines` drops any line shorter than `min_len` (24 chars)
#      as "structural" — but a short bullet like "- USER: `~/.claude/mem`" can
#      still carry a load-bearing path.
#   2. `_substantive_body_lines` drops every line starting with "#" as a
#      heading — but a heading like "## PROJECT scope lives at `<repo-root>/…`"
#      can carry the SAME kind of fact.
# Both are proven gaps (not hypothetical): a source page with a scope-root path
# stated only in a short bullet or a heading passes body_facts_preserved clean
# even when that exact path is rewritten to something else on the result side.
# This is precisely the shape of the documented v0.10.0 wrong-scope-root split
# bug (issue #91): the split condensed §5's prose into new, shorter, WRONG
# path bullets, and nothing caught it at gate time.
#
# The fix here is deliberately TOKEN-grained rather than LINE-grained: extract
# the mechanically-recognizable "fact atoms" (paths, URLs, ALL-CAPS env/config
# keys, semver strings, hex ids, numeric constants with units) from a source's
# substantive body (frontmatter and the lessons section excluded, matching how
# body_facts_preserved scopes itself) and assert each survives VERBATIM
# somewhere in the result — regardless of the line length or heading/bullet it
# lived in, and regardless of how much the SURROUNDING prose was legitimately
# reworded. Set containment, not position: a legitimate paraphrase of the
# sentence around an unchanged path never false-fails, only the path itself
# vanishing or mutating does. Deliberately syntactic (exact-token survival),
# not semantic — cheap, deterministic, stdlib `re` only.
# --------------------------------------------------------------------------- #

# Backtick-quoted spans are the near-universal convention this corpus uses for a
# path/env-var reference (`~/.claude/rules/`, `${CLAUDE_PLUGIN_ROOT}`,
# `<repo-root>/.claude/project/memory/`) — capture the span's INNER text (the
# backticks themselves are formatting, not the fact) whenever it looks
# path-like: contains a "/" or opens with "$"/"${" (an env-var expansion).
_BACKTICK_PATH_RE = re.compile(r"`([^`\s]*(?:/|\$\{?[A-Za-z_])[^`\s]*)`")

# Bare (non-backticked) rooted paths: ~/…, $HOME/…, ${VAR}/…, <placeholder-root>/…
# (this project's own convention for a generic root, e.g. `<repo-root>/design/`),
# or an absolute /a/b (2+ segments — a single "/" alone is too weak a signal and
# would match ordinary prose like "and/or").
_BARE_PATH_RE = re.compile(
    r"(?:"
    r"~(?:/[A-Za-z0-9_.<>\-]+)+"
    r"|\$\{?[A-Za-z_][A-Za-z0-9_]*\}?(?:/[A-Za-z0-9_.<>\-]+)+"
    r"|<[A-Za-z0-9_\-]+>(?:/[A-Za-z0-9_.<>\-]+)+"
    r"|(?:/[A-Za-z0-9_.\-]+){2,}"
    r")"
)

_URL_RE = re.compile(r"https?://[^\s)\]\"'`,]+")

# An ALL-CAPS constant with at least one underscore (an env/config key shape like
# `CLAUDE_PLUGIN_ROOT`) — requiring the underscore excludes ordinary all-caps
# English words (RULE, GOLDEN, IMPORTANT) that carry no fact of their own.
_ENV_CONST_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")

_SEMVER_RE = re.compile(r"\bv?\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?\b")

# A hex id (git SHA, HMAC tag, …): 7-40 hex chars with a WORD boundary, requiring
# at least one a-f letter so a plain decimal number (all-digit, e.g. "1234567")
# is never misread as a hex id.
_HEX_ID_RE = re.compile(r"\b(?=[0-9a-fA-F]*[a-fA-F])[0-9a-fA-F]{7,40}\b")

_NUMERIC_UNIT_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s?(?:ms|secs?|s|mins?|hrs?|h|d|days?|weeks?|wks?|years?|yrs?"
    r"|MB|GB|KB|TB|tokens?|%|px|em|rem)\b"
)


def load_bearing_tokens(text: str) -> set[str]:
    """Extract LOAD-BEARING TOKENS from `text`'s substantive body — frontmatter and
    the `## Notes and lessons learned` section (lessons/footnote defs) excluded,
    matching how body_facts_preserved scopes itself (issue #91). A load-bearing token
    is a mechanically-recognizable "fact atom": a filesystem path, a URL, an ALL-CAPS
    env/config key, a semver string, a hex id, or a numeric constant with a unit.

    Deliberately UNFILTERED by line length or heading-ness (unlike
    `_substantive_body_lines`): a short bullet or a markdown heading can carry a
    load-bearing path exactly as easily as a long paragraph, and reusing the 24-char
    line/heading filter here would silently re-open the very gap this function exists
    to close. Fenced code is NOT masked (a bash example quoting a real path is exactly
    the kind of place a load-bearing fact lives), matching body_facts_preserved's own
    fence-inclusive behavior."""
    body = _body_minus_lessons(text)
    tokens: set[str] = set()
    tokens.update(_BACKTICK_PATH_RE.findall(body))
    tokens.update(_BARE_PATH_RE.findall(body))
    tokens.update(_URL_RE.findall(body))
    tokens.update(_ENV_CONST_RE.findall(body))
    tokens.update(_SEMVER_RE.findall(body))
    tokens.update(_HEX_ID_RE.findall(body))
    tokens.update(_NUMERIC_UNIT_RE.findall(body))
    # Normalize each token with the SAME whitespace collapse `_token_haystack` applies
    # to the comparison target. Without this, a numeric-unit phrase that happens to
    # LINE-WRAP between number and unit ("3\ndays") is extracted with a literal
    # newline that no collapsed haystack can ever contain — so `fact_tokens_preserved`
    # fails even on a byte-identical no-op, permanently blocking every atomize/repair
    # commit on that page (found by the WN7M829Y editorial pass, 2026-08-02; the
    # asymmetry, not the content, was the defect).
    return {re.sub(r"\s+", " ", t) for t in tokens}


def _token_haystack(text: str) -> str:
    """Whitespace-collapsed, CASE-PRESERVING whole-page blob for token-fidelity
    comparison: frontmatter stripped, lessons KEPT (mirrors `_norm_page_blob`'s
    demoted-to-lesson rationale — a fact demoted into a dated `[^N]` lesson has MOVED,
    not vanished, so the correction protocol must not be misread as a token loss).
    Case is preserved here, UNLIKE `_norm_page_blob`, because a load-bearing token's
    fidelity is asserted VERBATIM (issue #91) — an env key's or a path's exact casing
    IS the fact, and lowercasing it away would silently accept a casing mutation."""
    return re.sub(r"\s+", " ", _strip_frontmatter(text))


def fact_tokens_preserved(sources: list[str], result: str) -> tuple[bool, list[str]]:
    """STRICT, syntactic anti-corruption check (issue #91): every load-bearing token
    (see `load_bearing_tokens`) extracted from a source's substantive body must
    survive VERBATIM somewhere in `result`. Set containment, not position — a
    legitimate rewording of the sentence around an unchanged token never false-fails.

    Complements `body_facts_preserved` rather than replacing it: that check already
    catches a wholesale reworded/dropped FACT LINE >= 24 chars; this one additionally
    catches a token silently mutated inside a SHORT line or a markdown HEADING, both
    of which `body_facts_preserved` treats as non-fact structure by design (see the
    section comment above). Returns (ok, [missing tokens, ≤8])."""
    haystack = _token_haystack(result)
    missing: list[str] = []
    seen: set[str] = set()
    for src in sources:
        for tok in load_bearing_tokens(src):
            if tok in seen:
                continue
            seen.add(tok)
            if tok not in haystack:
                missing.append(tok)
    missing.sort()
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


def fence_run(line: str) -> tuple[str, int, str] | None:
    """Leading fence-delimiter run of `line` as `(char, run length, info string)`, else None.

    Requires at least three backticks or tildes as the first non-space characters.
    """
    t = line.lstrip()
    if not t or t[0] not in "`~":
        return None
    ch = t[0]
    n = len(t) - len(t.lstrip(ch))
    if n < 3:
        return None
    return ch, n, t[n:]


def is_fence_open(line: str) -> tuple[str, int] | None:
    """The fence this line OPENS, else None.

    CommonMark 4.5: a BACKTICK opener's info string may not contain a backtick, so a line whose
    first non-space characters are ```` ```fence``` ```` opens nothing — it is an inline code span.
    A naive `startswith("```")` reads it as an opener, never finds a closer, and silently masks
    everything below it (janitor#178, #277, #279 — this exact defect, found three separate times
    in three separate places because each one carried its own copy of the rule).

    A TILDE opener carries no such restriction.
    """
    run = fence_run(line)
    if run is None:
        return None
    ch, n, info = run
    if ch == "`" and "`" in info:
        return None
    return ch, n


def fence_closes(line: str, open_fence: tuple[str, int]) -> bool:
    """Does `line` close `open_fence`? Same character, run at least as long, nothing after it."""
    run = fence_run(line)
    if run is None:
        return False
    ch, n, rest = run
    return ch == open_fence[0] and n >= open_fence[1] and not rest.strip()


def fence_step(
    line: str, state: tuple[str, int] | None
) -> tuple[tuple[str, int] | None, bool]:
    """Advance fence state one line: returns `(new state, line-is-a-delimiter)`.

    Returns the new state rather than mutating, because Python has no `&mut`; every caller must
    rebind. This is the SINGLE Python definition of the rule, and it deliberately mirrors the
    memgrep crate's `fence_step` in `src/memory.rs` — janitor#227 and #260 were both this
    precheck and the crate disagreeing about page structure, which left the repair chore
    re-dispatching forever at ~250-300k tokens per no-op run.
    """
    if state is not None:
        if fence_closes(line, state):
            return None, True
        return state, False
    opened = is_fence_open(line)
    if opened is not None:
        return opened, True
    return None, False


def no_new_duplicate_lines(result: str, min_len: int = 24) -> tuple[bool, list[str]]:
    """No substantive content line (length ≥ `min_len`, not a heading/list marker)
    appears more than once in `result`. Catches a naive union that re-introduced
    the very duplication the merge was meant to remove."""
    seen: dict[str, int] = {}
    fence: tuple[str, int] | None = None
    for raw in result.splitlines():
        s = raw.strip()
        # L-6 (wikimem audit 2026-07-07): track fence STATE, don't just skip the
        # ``` line itself — the same ≥min_len command legitimately appears in two
        # code examples, and counting fence contents false-failed those merges.
        fence, is_delim = fence_step(raw, fence)
        if is_delim:
            continue
        if fence is not None or len(s) < min_len or s.startswith("#"):
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


_MD_LINK_RE = re.compile(r"\]\(\s*([A-Za-z0-9._/-]+\.md)\s*\)")


def redirect_memory_md_links(text: str, retired_slugs, survivor_slug: str) -> str:
    """Repoint every `](<retired>.md)` markdown link in MEMORY.md at `<survivor>.md` (janitor#182).

    The harness `MEMORY.md` is a SECOND index, separate from the wikimem `[[wikilink]]` graph, and
    the merge path never touched it: a consolidate pass deleted the merged-away page and redirected
    its wikilinks, while MEMORY.md kept its own line pointing at a file that no longer exists. A
    future session then follows that link, finds nothing, and reads the note as MISSING rather than
    MERGED — the single outcome consolidation exists to make impossible ("never delete knowledge,
    relocate it"). The knowledge WAS relocated; only the pointer rotted.

    This REDIRECTS, it does not curate. Only the link TARGET inside `](…)` changes; the line's
    human-written title and hook survive byte-for-byte, and no line is added, removed, or
    reordered. That is what keeps it compatible with the standing rule that the janitor maintains
    exactly ONE line in MEMORY.md (the wikimem bridge) and touches nothing else — repairing a
    pointer the janitor's own deletion broke is not curation of someone else's index.
    """
    survivor = (survivor_slug or "").strip()
    retired = {s.strip() for s in retired_slugs if s and s.strip()} - {survivor}
    if not survivor or not retired:
        return text

    def _swap(m: re.Match[str]) -> str:
        target = m.group(1)
        stem = target.rsplit("/", 1)[-1][: -len(".md")]
        if stem not in retired:
            return m.group(0)
        prefix = target[: len(target) - len(target.rsplit("/", 1)[-1])]
        return f"]({prefix}{survivor}.md)"

    return _MD_LINK_RE.sub(_swap, text)


def no_dangling_memory_md_refs(
    memory_md_text: str, retired_slugs, survivor_slug: str | None = None
) -> tuple[bool, list[str]]:
    """The verify half of `redirect_memory_md_links` (janitor#182): no MEMORY.md link may still
    point at a retired page. Returns (ok, ["MEMORY.md -> retired.md", …]).

    Deliberately a SEPARATE oracle from `no_dangling_refs` rather than a widening of it: that one
    reads `[[wikilinks]]` in wiki pages, this one reads `](path.md)` in the harness index. Folding
    them together would hide which index is broken in the failure message, and they are repaired by
    different edits.
    """
    survivor = (survivor_slug or "").strip()
    retired = {s.strip() for s in retired_slugs if s and s.strip()} - {survivor}
    dangling = [
        f"MEMORY.md -> {t}"
        for t in _MD_LINK_RE.findall(memory_md_text or "")
        if t.rsplit("/", 1)[-1][: -len(".md")] in retired
    ]
    return (not dangling, dangling)


def no_dangling_refs(
    live_pages: dict, retired_slugs, survivor_slug: str | None = None
) -> tuple[bool, list[str]]:
    """After a merge/split removes some slugs, NO surviving page may still
    `[[link]]` to a retired slug. `live_pages` is {slug_or_path: text}; returns
    (ok, ["holder -> retired", …]). This is the verify half of the LINK-LAW
    redirect the executor performs; a non-empty result means a redirect was missed.

    `survivor_slug` is EXEMPT (janitor#183). The executor half,
    `canonicalize_retired_links`, already skips the survivor — deliberately, since a link to the
    page that survives is the correct end state of a redirect, not a dangling one. This verifier
    had no `survivor_slug` parameter at all, so it could not agree with it, and the two halves of
    the same LINK-LAW check disagreed about the same edge.

    Harmless while the slugs differ; fatal when they COLLIDE — i.e. a same-`name:` DUPLICATE PAIR
    (one slug, two paths), which is the most obvious thing consolidation exists to merge. There
    `retired_slugs` contains the survivor's own slug, so every live backlink `[[that-slug]]` —
    which after the merge correctly resolves to the survivor — was reported dangling, the
    transaction self-aborted per contract, and that whole class of merge could never complete.
    Reported by a peer agent against a real LOCAL corpus; the abort was the fail-safe working
    correctly on a false alarm.

    Optional so every existing caller keeps its meaning; `verify_merge` passes the survivor it
    already computes for `canonicalize_retired_links`, which makes the two halves agree BY
    CONSTRUCTION rather than by coincidence.
    """
    retired = set(retired_slugs) - ({survivor_slug} if survivor_slug else set())
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
    fence: tuple[str, int] | None = None
    for line in text.splitlines(keepends=True):
        stripped = line.rstrip("\n")
        nl = line[len(stripped) :]
        core = stripped.lstrip()
        # Issue #178 found this defect class HERE FIRST and fixed it locally, with the
        # approximation "a delimiter never carries a SECOND ``` later on the same line". That
        # was close but not CommonMark: the real rule is that ANY backtick in a backtick
        # opener's info string disqualifies it, so ```` ```py `x` ```` was still mis-read. More
        # importantly the local fix never propagated — the crate and the precheck each kept
        # their own naive copy and re-lost the same investigation as #277 and #279. Now shared.
        opened = is_fence_open(core)
        if fence is None and opened is not None:
            fence = opened
            out.append(" " * len(stripped) + nl)
            continue
        if fence is not None and fence_closes(core, fence):
            fence = None
            out.append(" " * len(stripped) + nl)
            continue
        out.append((" " * len(stripped) + nl) if fence is not None else line)
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


_ATOM_ID_RE = re.compile(r"^\s*\^([A-Za-z0-9_-]+)\s*\[", re.MULTILINE)


def atom_footnote_citations(text: str) -> dict[str, set[str]]:
    """`{atom_id: set of footnote ids that atom's BODY cites}` for one page.

    An atom's body runs from its `^id [props]` marker to the next atom marker, the lessons
    heading, or EOF — the same span the atomize pass writes. Fences are masked first (L-4):
    a `[^n]` inside a code example documents syntax, it does not cite a lesson.
    """
    masked = _mask_code_fences(_strip_frontmatter(text))
    cut = masked.find(_LESSONS_HEADING)
    if cut != -1:
        masked = masked[:cut]
    marks = list(_ATOM_ID_RE.finditer(masked))
    out: dict[str, set[str]] = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(masked)
        body = masked[m.end() : end]
        # The marker's own props blob is metadata, not a citation — the body starts after it.
        out.setdefault(m.group(1), set()).update(_FN_ANY_RE.findall(body))
    return out


def atom_lessons_travel(source_texts: list[str], result_texts: list[str]) -> tuple[bool, list[str]]:
    """An atom that MOVES between pages must take its lessons with it. Returns
    (ok, sorted offenders as `atom#lesson`).

    THE GAP THIS CLOSES (TRDD-VJCMZ2OP item 1e), and why no existing check catches it: the
    `memgrep migrate` VERB is self-verified, but a HAND-move is not. Move atom `^X` from page A
    to page B and drop its `[^3]` citation on the way, and every current invariant still passes:
    page A keeps a footnote DEFINITION with no reference — an ORPHAN DEF, explicitly legal in
    `footnote_refs_resolve` — and page B holds an atom that cites nothing, so
    `no_new_dangling_footnote_refs` sees no new dangling ref either. The lesson is silently
    orphaned on the page the atom no longer lives on. Nothing dangles, nothing errors, and the
    knowledge is severed from the fact it explains.

    So this check is keyed on the ATOM, not the page: for every atom present in BOTH the source
    and result corpora, the footnote ids its body cited must still be cited. Losing one is the
    defect, wherever the atom now lives. A *renumbered* footnote is a different id and would
    read as loss — which is correct here: `migrate` renumbers on collision and re-cites under
    the new id, so a genuine renumber keeps the citation COUNT and shows up as a lost id ONLY
    when the atom really stopped citing anything. Callers doing a deliberate renumber pass the
    post-renumber source text.
    """
    src: dict[str, set[str]] = {}
    for t in source_texts:
        for atom, fns in atom_footnote_citations(t).items():
            src.setdefault(atom, set()).update(fns)
    res: dict[str, set[str]] = {}
    for t in result_texts:
        for atom, fns in atom_footnote_citations(t).items():
            res.setdefault(atom, set()).update(fns)
    lost: list[str] = []
    for atom, fns in src.items():
        if atom not in res:
            continue  # the atom itself is gone — that is lessons_preserved's concern, not ours
        for fn in sorted(fns - res[atom]):
            lost.append(f"^{atom}#[^{fn}]")
    return (not lost, sorted(lost))


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
    memory_md_text: str | None = None,
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

    # issue #91 — token-grained sibling of the line-grained check above: catches a
    # path/constant mutated inside a SHORT line or a HEADING, both of which
    # body_facts_preserved's 24-char/heading-exclusion filters treat as non-fact
    # structure. Same _canon() modulo-redirect comparison as the check above.
    ok, missing_tokens = fact_tokens_preserved([_canon(t) for t in fact_sources], result_cmp)
    if not ok:
        reasons.append("dropped/mutated load-bearing token(s): " + "; ".join(missing_tokens))

    ok, why = ocd_lmd_ok_merge(source_metas, result_meta)
    if not ok:
        reasons.append("ocd/lmd: " + why)

    ok, dups = no_new_duplicate_lines(result_text)
    if not ok:
        reasons.append("duplicate content line(s) re-introduced: " + "; ".join(dups))

    live_after = dict(other_live_pages or {})
    live_after["__merged_result__"] = result_text
    # `survivor` (computed above for canonicalize_retired_links) is passed here too, so the
    # executor and verifier halves of the LINK LAW agree by construction — see janitor#183.
    ok, dangling = no_dangling_refs(live_after, retired_slugs, survivor_slug=survivor or None)
    if not ok:
        reasons.append("dangling refs to retired slug(s): " + "; ".join(dangling))

    # janitor#182 — the SECOND index. Opt-in: a caller that does not hand us MEMORY.md is not
    # asserting anything about it, so absence stays silent rather than becoming a phantom pass.
    # When it IS supplied, a pointer left aimed at a page this merge deleted fails the merge, the
    # same way a missed wikilink redirect does.
    if memory_md_text is not None:
        ok, md_dangling = no_dangling_memory_md_refs(
            memory_md_text, retired_slugs, survivor_slug=survivor or None
        )
        if not ok:
            # Name the harness index via the constant that OWNS it (memory_bridge.MEMORY_MD)
            # rather than a second literal — one source of truth (janitor#182 follow-up).
            reasons.append(f"dangling {_memory_md_name()} pointer(s): " + "; ".join(md_dangling))

    ok, fn = no_new_dangling_footnote_refs(source_texts, [result_text])
    if not ok:
        reasons.append("orphaned shared footnote ref(s) introduced: " + ", ".join(fn))

    # TRDD-VJCMZ2OP item 1e — an atom that moves into the merged page must keep its
    # [^N] citations. Defined and tested since the card landed but never COMPOSED here,
    # so a hand-merge could orphan a lesson from its atom and still commit (the review
    # finding of 2026-08-02): footnote_refs_resolve permits the orphan def and
    # no_new_dangling_footnote_refs sees no new dangling ref.
    ok, lost = atom_lessons_travel(source_texts, [result_text])
    if not ok:
        reasons.append("atom lesson citation(s) lost in merge: " + ", ".join(lost))

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

    # issue #91 — the documented v0.10.0 wrong-scope-root bug's exact shape: a split
    # that CONDENSES §-level prose into new, shorter path bullets can drop a
    # load-bearing token even when body_facts_preserved's 24-char/heading filters
    # let the surrounding sentence's disappearance read as mere restructuring.
    ok, missing_tokens = fact_tokens_preserved([source_text], concatenated)
    if not ok:
        reasons.append("source load-bearing token(s) lost/mutated across sub-pages: " + "; ".join(missing_tokens))

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

    # TRDD-VJCMZ2OP item 1e — same composition gap as verify_merge (2026-08-02 review):
    # an atom landing on a sub-page must keep its [^N] citations wherever it now lives.
    ok, lost = atom_lessons_travel([source_text], [overview_text, *subpage_texts])
    if not ok:
        reasons.append("atom lesson citation(s) lost in split: " + ", ".join(lost))

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

    # Atom-level `desc:` completeness (TRDD-3SOO1RWE, parent duty 2): a REPAIR means
    # completing the page, and the page-level `description` bar above never covered the
    # ATOM descs — authoring skills require them at write time, but nothing validated
    # existing atoms, so desc-less atoms accumulated. Same completeness contract as
    # `_REQUIRED_FM_KEYS`: a repair that leaves one missing did not finish.
    bad_descs = atom_desc_violations(result_text)
    if bad_descs:
        reasons.append("atom desc incomplete after repair: " + "; ".join(bad_descs))

    return (not reasons, reasons)


# An atom block-property marker on its own line: `^<id> [<props>]` (TRDD-3b9b2040). The atomize pass
# adds markers on dedicated lines so every existing FACT line stays byte-identical — the regex matches
# exactly that shape (optional indent, kebab id, optional space, a bracketed props blob). Built from the
# SHARED `_ATOM_MARKER_CORE` so extract_lessons' stop-set and this full-line matcher can never disagree
# on what an atom marker is (TRDD-MADJ00KA). Byte-identical to the prior literal: without a DOTALL flag
# `.` already excluded newlines, so `[^\n]*` inside the core changes nothing here.
_ATOM_MARKER_RE = re.compile(rf"^\s*{_ATOM_MARKER_CORE}\s*$")

# --- Atom-level desc completeness (TRDD-3SOO1RWE, parent duty 2 of TRDD-87RKBYJ8) --- #

# A marker line captured WITH its props blob, so desc can be inspected per atom.
_ATOM_MARKER_PROPS_RE = re.compile(r"^\s*\^([A-Za-z0-9_-]+)\s*\[([^\n]*)\]\s*$")
# `desc:"…"` — the canonical QUOTED form (memgrep's `atom-unquoted-desc` lint marks the
# unquoted form a defect, so a completing repair must leave the quoted one).
_ATOM_DESC_QUOTED_RE = re.compile(r'(?:^|[\[,])\s*desc\s*:\s*"([^"]*)"')
# Unquoted value: runs to the next top-level comma — safe because an UNQUOTED value
# cannot itself contain a protected comma (only quoted values can, and those match above).
_ATOM_DESC_UNQUOTED_RE = re.compile(r"(?:^|[\[,])\s*desc\s*:\s*([^,\]]*)")
_ATOM_DESC_MAX = 200
# Fenced code can carry marker-SHAPED example lines (janitor#152's lesson from the other
# direction); fences are masked via the SHARED `_mask_code_fences` (which carries the
# issue-#178 inline-span guard) so this scanner and every other fence-aware check in the
# module agree on what a fence is — a second bespoke regex here was how #178's bug got
# fixed twice and still survived in the shared helper.


def atom_desc_violations(text: str) -> list[str]:
    """Every atom marker whose `desc:` is MISSING, UNQUOTED, or over the 200-char cap —
    one human-readable violation string per atom. PURE; fenced code is ignored.

    This is the SSOT the commit-time bar (`verify_repair`) and the scheduler precheck
    (`memory_content_precheck._page_needs_repair`) both call, so they cannot drift —
    the same discipline the frontmatter checks already follow. Authoring skills REQUIRE
    a desc at write time; this closes the retroactive half (existing atoms predating
    the requirement, and descs that rotted past the cap)."""
    violations: list[str] = []
    try:
        body = _body_minus_lessons(text)
    except ValueError:
        # A page with DUPLICATE Notes headings trips _body_minus_lessons' multi-page
        # guard (issue #88). That duplication is itself a structural defect repair must
        # fix FIRST — report it as the violation instead of crashing the scheduler
        # (repair_has_work) or the oracle (verify_repair must return, never raise).
        return [
            "page has duplicate '## Notes and lessons learned' headings — "
            "merge them before atom descs can be checked"
        ]
    for line in _mask_code_fences(body).splitlines():
        m = _ATOM_MARKER_PROPS_RE.match(line)
        if not m:
            continue
        atom_id, props = m.group(1), m.group(2)
        quoted = _ATOM_DESC_QUOTED_RE.search(props)
        if quoted:
            if len(quoted.group(1)) > _ATOM_DESC_MAX:
                violations.append(
                    f"^{atom_id}: desc is {len(quoted.group(1))} chars (max {_ATOM_DESC_MAX})"
                )
            elif not quoted.group(1).strip():
                violations.append(f"^{atom_id}: desc is empty")
            continue
        unq = _ATOM_DESC_UNQUOTED_RE.search(props)
        if unq:
            val = unq.group(1).strip()
            if not val:
                violations.append(f"^{atom_id}: desc is empty")
            elif not re.fullmatch(r"[a-z0-9_]+", val):
                # Mirror memgrep's `desc_unquoted_prose` EXACTLY (memory.rs:3081): an
                # unquoted clean legacy SLUG ([a-z0-9_]+) is accepted; unquoted PROSE is
                # the Error the linter raises — a stricter bar here would demand repairs
                # the linter never asks for (churn), a looser one would pass pages lint
                # rejects.
                violations.append(
                    f'^{atom_id}: desc is unquoted prose (quote it: desc:"…")'
                )
            elif len(val) > _ATOM_DESC_MAX:
                violations.append(
                    f"^{atom_id}: desc is {len(val)} chars (max {_ATOM_DESC_MAX})"
                )
        else:
            violations.append(f"^{atom_id}: desc missing")
    return violations


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

    # issue #91 — defense-in-depth alongside the additive-lines-only guard below: a
    # token-grained check catches the same class of mutation the line-grained
    # body_facts_preserved does, independent of line length or heading placement.
    ok, dropped_tokens = fact_tokens_preserved([source_text], result_text)
    if not ok:
        reasons.append("load-bearing token(s) dropped/mutated in atomize: " + "; ".join(dropped_tokens))

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
