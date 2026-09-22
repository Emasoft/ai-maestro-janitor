"""The compacted-context composer (TRDD-RAEGS1D5 card 3, part A).

Pure functions over data: extract the OLD transcript's items, build a small task digest,
score each item through Jev, then compose the final injected document. No side effects
(no file writes, no subprocess calls) -- the caller (``scripts/jev_compact.py``, part B)
owns I/O and wires the Jev client / TRDD STATE heads in.

Only ever imported by the PEP-723 script ``scripts/jev_compact.py`` (which needs
``httpx`` via jevctx's HTTP clients) -- never by a stdlib-only hook script. This module
itself has no third-party dependency; it only touches the vendored ``jevctx`` package,
which lives one directory up (``scripts/lib/jevctx/``).
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

# WHY: this file lives in scripts/lib/, a sibling of scripts/lib/jevctx/ -- adding this
# directory to sys.path lets `import jevctx...` work whether this module is imported by
# scripts/jev_compact.py (which already does the same insert) or directly by a test that
# never ran that script.
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

from jevctx import scorer as _scorer  # noqa: E402  -- needs the sys.path line above
from jevctx.budget import BudgetPlanner  # noqa: E402
from jevctx.tokens import estimate_tokens  # noqa: E402
from jevctx.types import (  # noqa: E402
    MAX_QUESTIONS_PER_REQUEST,
    JevClient,
    JevValidationError,
    Noul,
    NoulAnswer,
    Question,
    ScoreItem,
)

__all__ = [
    "Item",
    "Scores",
    "NoDigest",
    "RELEVANCE_QUESTION",
    "DECISION_QUESTION",
    "DEFAULT_RELEVANCE_THRESHOLD",
    "DEFAULT_DECISION_THRESHOLD",
    "extract_items",
    "build_digest",
    "score_items",
    "compose",
]

ItemKind = Literal["user", "assistant", "tool"]

# Entry `type`s that ever carry a extractable item (spec: skip `system` entries and the
# auxiliary types -- mode, file-history-snapshot, last-prompt, queue-operation, attachment
# -- outright; only `user`/`assistant` entries are walked at all).
_WALKED_ENTRY_TYPES = {"user", "assistant"}

_HEARTBEAT_PREFIX = "[janitor-heartbeat]"

# Truncation cap for a remembered tool_use `input` (spec: "name+input truncated to 300
# chars") -- long enough to identify the call, short enough that a page of `Bash` args
# doesn't dominate the digest/score request.
_TOOL_INPUT_TRUNCATE = 300

# Pointer first-line preview cap (spec: `"<first line ≤80 chars>"`).
_POINTER_PREVIEW_CHARS = 80


@dataclass(frozen=True)
class Item:
    """One scorable/inlinable unit of the OLD transcript.

    `id` = "<entry uuid>:<block index>" -- the block index is the position in the RAW
    content list of the entry that produced it (including blocks that were themselves
    skipped, e.g. `thinking`/`tool_use`), so the id stays a valid pointer back into the
    original JSONL for `jev_compact.py expand` to resolve, and is stable across re-runs
    because it depends only on the transcript's own content, never on extraction order.
    """

    id: str
    kind: ItemKind
    text: str
    tokens: int
    ts: str | None
    turn: int


@dataclass(frozen=True)
class Scores:
    """Both Noul answers for one item, plus the two derived facts callers need.

    `kept`/`oversized` are computed here (not left for `compose` to recompute) because
    `score_items` is the one place that knows the thresholds it used -- `compose`'s
    signature has no threshold parameters, it just trusts these booleans.
    """

    relevance: float
    decision: float
    oversized: bool
    kept: bool
    # Baked in here for the same reason `kept`/`oversized` are: `score_items` is the one
    # place that knows `decision_threshold`. `compose`'s budget eviction reads this to
    # protect a user-stated decision/constraint/correction from being dropped for space
    # before a merely-relevant item is (see `compose`'s eviction-order comment).
    decision_passed: bool


class NoDigest(Exception):
    """Raised by `build_digest` when there is nothing to build a digest from.

    Neither a human message nor a TRDD STATE head exists -- the caller declines Jev
    compaction entirely rather than score every item against an empty/meaningless task.
    """


# jevctx.pipeline (the source of the canonical RETRIEVE_QUESTION wording) is NOT vendored
# in this repo (see scripts/lib/jevctx/VENDORED.md -- trimmed to what card 3 needs), so this
# is copied from its quotation in
# reports/compaction-replacement/20260922_205137+0200-jev-compaction-study.md §C rather
# than from source. The `true`/`false` criteria strings are authored here (the report only
# quotes `instructions`; jevctx's own `true`/`false` text for this question isn't recorded
# anywhere in this repo).
RELEVANCE_QUESTION = Noul(
    instructions=(
        "Is this stored item relevant to the task described in `task` right now? "
        "Answer true if it contains facts, identifiers, errors, results, or decisions "
        "the current task may need. Answer false if it belongs to unrelated work, or "
        "is superseded by something more recent."
    ),
    true="Relevant to the task described in `task`, right now.",
    false="Belongs to unrelated work, or superseded by something more recent.",
)

# Verbatim per the implementation spec (docs_dev/jev-compaction-spec.md, card 3).
DECISION_QUESTION = Noul(
    instructions=(
        "Is this a decision, constraint, correction or instruction the user stated, "
        "that later work must obey?"
    ),
    true="Yes -- a decision, constraint, correction or instruction the user stated.",
    false="No -- not a decision, constraint, correction or instruction from the user.",
)

DEFAULT_RELEVANCE_THRESHOLD = 0.5
DEFAULT_DECISION_THRESHOLD = 0.5


def _tool_result_text(content: Any) -> str:
    """Text of a `tool_result` block's `content` -- a plain string, or a list of text blocks."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return ""


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[:limit]


def extract_items(transcript_path: str | Path) -> list[Item]:
    """Walk one transcript JSONL and return its extracted, chronologically ordered items.

    One pass, top to bottom: a `tool_use` block is remembered by its own `id` as soon as
    it's seen, so the `tool_result` block that answers it (which always appears in a LATER
    line -- the transcript is append-only) can be paired with it by the time we reach it.
    """
    path = Path(transcript_path)
    items: list[Item] = []
    turn = 0
    # tool_use id -> (name, truncated-input-json) remembered for pairing with its result.
    pending_tool_uses: dict[str, tuple[str, str]] = {}

    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = json.loads(line)
            entry_type = entry.get("type")
            if entry_type not in _WALKED_ENTRY_TYPES:
                continue
            # A subagent's turns live in the SAME main transcript file (isSidechain: true)
            # but are not the main conversation -- scoring/inlining them into the parent
            # session's compacted context would mix two different tasks' history.
            if entry.get("isSidechain"):
                continue

            uuid = entry.get("uuid")
            ts = entry.get("timestamp")
            content = entry.get("message", {}).get("content")

            if entry_type == "user":
                is_meta = bool(entry.get("isMeta"))
                if isinstance(content, str):
                    if not is_meta and not content.startswith(_HEARTBEAT_PREFIX):
                        items.append(Item(f"{uuid}:0", "user", content,
                                           estimate_tokens(content), ts, turn))
                        turn += 1
                elif isinstance(content, list):
                    for idx, block in enumerate(content):
                        if not isinstance(block, dict):
                            continue
                        btype = block.get("type")
                        if btype == "text":
                            text = block.get("text", "")
                            if not is_meta and not text.startswith(_HEARTBEAT_PREFIX):
                                items.append(Item(f"{uuid}:{idx}", "user", text,
                                                   estimate_tokens(text), ts, turn))
                                turn += 1
                        elif btype == "tool_result":
                            # WHY no isMeta guard here: isMeta marks a human-facing pseudo
                            # user message (hook-injected context), never a tool result --
                            # the spec's isMeta clause is scoped to str/list[text] content.
                            tool_use_id = str(block.get("tool_use_id"))
                            name, tool_input = pending_tool_uses.get(
                                tool_use_id, ("<unknown tool>", "")
                            )
                            result_text = _tool_result_text(block.get("content"))
                            text = f"{name}({tool_input})\n{result_text}"
                            items.append(Item(f"{uuid}:{idx}", "tool", text,
                                               estimate_tokens(text), ts, turn))
                            turn += 1
                # else: no content (or an unrecognised shape) -- nothing to extract.

            else:  # entry_type == "assistant"
                if not isinstance(content, list):
                    continue
                for idx, block in enumerate(content):
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type")
                    if btype == "thinking":
                        continue  # never an item, never remembered
                    if btype == "text":
                        text = block.get("text", "")
                        items.append(Item(f"{uuid}:{idx}", "assistant", text,
                                           estimate_tokens(text), ts, turn))
                        turn += 1
                    elif btype == "tool_use":
                        tool_input = _truncate(
                            json.dumps(block.get("input", {}), sort_keys=True),
                            _TOOL_INPUT_TRUNCATE,
                        )
                        pending_tool_uses[str(block.get("id"))] = (
                            block.get("name", "<unnamed tool>"), tool_input
                        )
                    # any other block type: skip, not remembered

    return items


def build_digest(
    items: list[Item], trdd_state_heads: list[str], cap_tokens: int = 4000
) -> str:
    """The small task description scored items are judged against.

    Order: STATE heads first (the durable, machine-produced facts), then the last three
    human messages and the last two assistant `text` blocks, chronological -- so that
    if the cap forces dropping whole parts, the least essential piece (an OLDER state head)
    goes first and the freshest words survive longest. The last two assistant messages are
    included alongside the human ones (not just the human ones alone) because on an
    unattended session the last HUMAN message can be old -- what the agent last said it was
    doing anchors relevance-scoring better than a stale human prompt alone would.
    """
    user_items = [it for it in items if it.kind == "user"]
    assistant_items = [it for it in items if it.kind == "assistant"]
    recent = sorted(user_items[-3:] + assistant_items[-2:], key=lambda it: it.turn)

    parts: list[str] = [
        "\n".join(head.splitlines()[:30]) for head in trdd_state_heads
    ] + [it.text for it in recent]

    if not recent and not trdd_state_heads:
        raise NoDigest("no human message and no TRDD STATE head -- nothing to digest")

    # Drop whole parts from the front (the lowest-priority end, per the ordering above)
    # until the joined digest fits the cap. A part that alone exceeds the cap is itself
    # truncated rather than dropped, so a non-empty digest never collapses to nothing.
    while parts and estimate_tokens("\n\n".join(parts)) > cap_tokens:
        if len(parts) == 1:
            # Binary-shrink the last remaining part until it fits.
            part = parts[0]
            while part and estimate_tokens(part) > cap_tokens:
                part = part[: max(1, len(part) // 2)]
            parts[0] = part
            break
        parts.pop(0)

    return "\n\n".join(parts)


def _ref_question(question: Noul, ref: str) -> Noul:
    """A copy of `question` whose instructions name `ref`.

    Mirrors `jevctx.scorer._ref_question` (private, so duplicated here rather than reached
    into across module boundaries): every item in a batch shares one `state`, so the
    question text is the only thing that tells the model which ref+question pair an answer
    is about.
    """
    return Noul(
        instructions=f"Considering item {ref} only: {question.instructions}",
        true=question.true,
        false=question.false,
    )


def score_items(
    items: list[Item],
    digest: str,
    client: JevClient,
    *,
    relevance_threshold: float = DEFAULT_RELEVANCE_THRESHOLD,
    decision_threshold: float = DEFAULT_DECISION_THRESHOLD,
) -> dict[str, Scores]:
    """Score every item against both Noul questions in ONE fan-out, not two.

    A review of the first draft (two sequential `jevctx.scorer.score_items` calls, one per
    question) found that sends every item's TEXT twice -- once per question's own batch
    `state` -- doubling exactly the cost `jevctx.budget` exists to avoid (Jev bills for
    `state`, not for questions). `jevctx.scorer.score_items` has no "two questions per item"
    mode, so this drives `BudgetPlanner` + `client.ask()` directly instead: each batch's
    `state.items` carries ONE entry per item (never duplicated), while the `questions` dict
    carries TWO keys per item (`<ref>:rel`, `<ref>:dec`). `max_questions` is therefore HALVED
    (`MAX_QUESTIONS_PER_REQUEST // 2`) when planning batches: the planner counts
    `len(batch.items)` against `max_questions`, but each item now costs 2 real questions in
    the request, so halving the item cap keeps the actual question count at or under Jev's
    hard `MAX_QUESTIONS_PER_REQUEST` limit.

    Always raises on a scorer failure -- never fails open like the library's own default.
    The one caller (`scripts/jev_compact.py compact`) must fall back to the fact-only
    template on any Jev error, never silently keep everything.
    """
    if not items:
        return {}

    lib_items = [ScoreItem(id=it.id, text=it.text, tokens=it.tokens) for it in items]
    items_by_id = {it.id: it for it in items}

    rel_tokens = estimate_tokens(_ref_question(RELEVANCE_QUESTION, "i0").to_payload())
    dec_tokens = estimate_tokens(_ref_question(DECISION_QUESTION, "i0").to_payload())
    # `BudgetPlanner._fits` uses `question_tokens` two ways: (a) `state + question_tokens *
    # count` against the "all questions" cap -- correct here, since `count` items really do
    # cost `question_tokens` (both questions) each; and (b) `state + question_tokens` against
    # the "longest single question" cap -- an intentional OVER-estimate here (a real batch's
    # longest single question is only ~half of `question_tokens`), which is conservative in
    # the safe direction (packs batches a bit smaller / more round trips, never overflows a
    # real Jev limit) rather than under-estimating and risking a 422.
    question_tokens = rel_tokens + dec_tokens
    envelope_tokens = estimate_tokens(_scorer.build_state(digest, [], []))

    planner = BudgetPlanner(max_questions=MAX_QUESTIONS_PER_REQUEST // 2)
    batches = planner.plan(lib_items, question_tokens, envelope_tokens)

    scores: dict[str, Scores] = {}
    for batch in batches:
        if batch.meta.get("oversized"):
            # Never sent -- fail-open at the library level regardless of caller intent,
            # exactly like jevctx.scorer's own oversized handling. `compose` still refuses
            # to inline it because `oversized=True` here (spec: "never inlined").
            it = items_by_id[batch.items[0].id]
            scores[it.id] = Scores(relevance=1.0, decision=1.0, oversized=True,
                                    kept=False, decision_passed=False)
            continue

        refs = batch.question_keys
        state = _scorer.build_state(digest, batch.items, refs)
        questions: dict[str, Question] = {}
        for ref in refs:
            questions[f"{ref}:rel"] = _ref_question(RELEVANCE_QUESTION, ref)
            questions[f"{ref}:dec"] = _ref_question(DECISION_QUESTION, ref)

        answers = client.ask(state, questions)  # a JevError here propagates -- see docstring

        for ref, lib_item in zip(refs, batch.items, strict=True):
            rel_answer = answers.get(f"{ref}:rel")
            dec_answer = answers.get(f"{ref}:dec")
            if not isinstance(rel_answer, NoulAnswer) or not isinstance(dec_answer, NoulAnswer):
                raise JevValidationError(
                    f"expected NoulAnswers for ref {ref!r}, got "
                    f"{type(rel_answer).__name__}/{type(dec_answer).__name__}"
                )
            it = items_by_id[lib_item.id]
            rel = rel_answer.value
            dec = dec_answer.value
            decision_passed = dec >= decision_threshold
            kept = rel >= relevance_threshold or decision_passed
            scores[it.id] = Scores(relevance=rel, decision=dec, oversized=False,
                                    kept=kept, decision_passed=decision_passed)
    return scores


def _format_pointer(item: Item) -> str:
    first_line = item.text.splitlines()[0] if item.text else ""
    preview = _truncate(first_line, _POINTER_PREVIEW_CHARS)
    # WHY no path here: a pointer must never hand the model something it could `Read` --
    # the transcript is 24-258 MB (docs_dev/jev-compaction-spec.md card 3) -- so the path
    # lives once, in the header, never per pointer.
    return f'[[elided id={item.id} tokens={item.tokens} "{preview}"]]'


# Spec: "Oversized single item (jev marks oversized) -> never inlined; pointer + first 20
# lines" -- a DIFFERENT, richer pointer than a plain budget-dropped item gets (that one is
# just the single-line `_format_pointer` above). An oversized item never even reached Jev
# (jevctx's own budget planner refuses to send it -- see `score_items`), so it has no
# relevance/decision signal at all; the extra 20 lines give the model enough to decide
# whether `expand` is worth it, which the 80-char preview alone cannot.
_OVERSIZED_PREVIEW_LINES = 20


def _oversized_preview(item: Item) -> str:
    return "\n".join(item.text.splitlines()[:_OVERSIZED_PREVIEW_LINES])


def compose(
    items: list[Item],
    scores: dict[str, Scores],
    *,
    budget_tokens: int = 8000,
    header: dict[str, Any],
) -> str:
    """Assemble the final injected document: header, kept items verbatim, then pointers.

    `header` carries: `transcript_path`, `session_key`, `digest`, and an optional `usage`
    dict (`{"tokens": int, "cost": float}` from the Jev response). The transcript path is
    written out exactly twice by design -- once in the header, once in the fixed trailing
    "expand with" line -- never inside an individual pointer.
    """
    # Oversized is re-checked here, not just trusted from `scores[...].kept`, because
    # "never inlined" is the compose-time invariant the spec actually cares about -- this
    # function is where inlining happens, so this is where the guard has to hold even if a
    # caller builds `scores` by hand (as the tests do) instead of via `score_items`.
    kept_items = [
        it for it in items if scores[it.id].kept and not scores[it.id].oversized
    ]

    def max_score(it: Item) -> float:
        s = scores[it.id]
        return max(s.relevance, s.decision)

    def evict_key(it: Item) -> tuple[bool, float, int]:
        # (decision_passed, max_score, turn) ascending: a relevance-only item (`False`)
        # sorts, and is dropped, BEFORE any item that passed the decision question -- "never
        # let the budget undo the decision question" (a user-stated decision, constraint,
        # correction or instruction the user gave later work must obey is worse to lose than
        # merely-relevant background). Within each group, lowest score first, oldest
        # (smallest `turn`) among equal scores -- unchanged from before.
        return (scores[it.id].decision_passed, max_score(it), it.turn)

    total_tokens = sum(it.tokens for it in kept_items)
    kept_ids = {it.id for it in kept_items}
    if total_tokens > budget_tokens:
        for it in sorted(kept_items, key=evict_key):
            if total_tokens <= budget_tokens:
                break
            kept_ids.discard(it.id)
            total_tokens -= it.tokens

    transcript_path = header.get("transcript_path", "")
    usage = header.get("usage") or {}

    lines: list[str] = [
        "# Compacted context (Jev compaction)",
        f"transcript: {transcript_path}",
        f"session: {header.get('session_key', '')}",
        "",
        "## Digest",
        header.get("digest", ""),
        "",
        f"usage: tokens={usage.get('tokens', '?')} cost={usage.get('cost', '?')}",
        "",
        "## Kept items",
    ]

    for it in items:  # `items` is already chronological -- preserve it verbatim
        if it.id in kept_ids:
            lines.append(f"-- {it.kind} {it.id} --")
            lines.append(it.text)

    lines.append("")
    lines.append("## Elided")
    for it in items:
        if it.id not in kept_ids:
            lines.append(_format_pointer(it))
            if scores[it.id].oversized:
                lines.append(_oversized_preview(it))

    lines.append("")
    lines.append(
        'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
        f"expand --transcript {transcript_path} <id>"
    )

    return "\n".join(lines)
