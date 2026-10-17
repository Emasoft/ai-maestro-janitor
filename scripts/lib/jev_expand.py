"""Resolve one ``jev_compact.py expand`` pointer id to its original bytes (TRDD-I40IKPWU).

This is the ONE implementation of "read the transcript entry, take block ``n``, slice lines
``a..b``". It used to live inside ``scripts/jev_compact.py`` (``cmd_expand``) and
``scripts/lib/jev_compaction.py``, which made it unreachable from the cross-/clear verifier
(``scripts/handoff_clear_verify.py``): that script is a dependency-free PEP-723 script, and
``jev_compaction`` pulls in ``jevctx``, which needs ``httpx``.

So this module imports the standard library and ``jsonl_walk`` ONLY -- never ``jev_compaction``,
``jevctx`` or ``jev_shadow_log``. ``tests/test_jev_expand.py`` proves that with a ``python -I -S``
subprocess. Pure: no printing, no shadow log (the shadow-log write is ``cmd_expand``'s job and
happens only on success, because it is a false-negative signal for the compaction gate -- a
verifier probing a pointer must never feed it).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

# WHY: same sys.path bootstrap as jev_compaction -- lets `import jsonl_walk` work whether this is
# imported from a script that already put scripts/lib on the path or directly by a test.
_LIB_DIR = Path(__file__).resolve().parent
if str(_LIB_DIR) not in sys.path:
    sys.path.insert(0, str(_LIB_DIR))

import jsonl_walk  # noqa: E402  -- needs the sys.path line above; stdlib-only


def tool_result_text(content: Any) -> str:
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


def attachment_item_text(entry: dict[str, Any]) -> str | None:
    """The item text for a `type: "attachment"` entry, or `None` if `entry` is not one, or if
    it is one that produces no item at all -- the ONE place the EXISTENCE-and-text rule for an
    attachment entry is allowed to live.

    TRDD-DQXMND59 follow-up (adversarial review of e23e0b39): before this function, the SAME
    predicate -- "only `attachment.type == "queued_command"`, text = the joined text blocks of
    `attachment.prompt`" -- was written out twice: once in `jev_compaction.extract_items`'s own
    attachment branch, and once in `extract_block` (here; it then lived in
    `scripts/jev_compact.py` and reached across the module boundary to call a PRIVATE
    text-joiner (`jev_compaction`'s private tool-result helper) directly). Two copies drift the moment one changes without the other:
    `expand` would start returning "not found" for a real pointer (matrix row V2, TRDD-DQXMND59's
    own report), or accept an id `extract_items` never actually generated (matrix row V10).

    `entry.get("type") != "attachment"` is checked HERE, first (stage 3, item N -- a second
    review of this function): the function now owns the WHOLE existence rule, not just the
    `attachment.type` sub-check, so a caller cannot forget the outer gate the way
    `extract_block` almost did on its first cut (it used to check `entry.get("type") ==
    "attachment"` itself, before ever calling this function).

    Stage 3 correction (item O, same review): this is the existence-and-text rule ONLY. Later
    filtering in `jev_compaction.extract_items`'s own attachment branch (an unmeasured
    `commandMode` skips item creation entirely -- see the `continue` after the commandMode/origin
    classification there) is NOT mirrored here, so this function can return text for an
    attachment `extract_items` itself goes on to drop. Harmless for `expand`: it reaches an entry
    by its transcript `uuid`, never by asking "did `extract_items` keep this", so a wider accept
    here does not let `expand` "succeed" on an id `extract_items` could never have generated
    (matrix row V10 stays closed) -- it only means "not found" (V2) and "id extract_items would
    keep" are no longer the exact same predicate as "id `attachment_item_text` accepts".

    `tool_result_text` (not a plain string read) because TRDD-RAEGS1D5: `attachment.prompt`
    is a plain str for a typed message, but a LIST of content blocks (text/image, same shape
    as `message.content`) when the owner pastes an image alongside text -- measured on the
    183 MB c8a95d7e transcript, whose crash was `is_control_input` calling `.strip()` on that
    list. Fixed in af09571b by reusing `tool_result_text`, the existing str-or-block-list
    joiner, rather than assuming str.
    """
    if entry.get("type") != "attachment":
        return None
    attachment = entry.get("attachment")
    if not isinstance(attachment, dict) or attachment.get("type") != "queued_command":
        return None
    return tool_result_text(attachment.get("prompt", "")) or None


def read_jsonl_entry(
    transcript: Path, target_uuid: str, *, malformed_lines: list[int],
) -> dict[str, Any] | None:
    """Scan the transcript for the entry with ``uuid == target_uuid``.

    A plain linear scan, not an index: a transcript is read here once per `expand` call,
    which is an interactive, occasional operation (a pointer the model chose to follow) —
    not the hot path card 3's compaction pass walks. Building an index for a one-shot CLI
    invocation would be optimizing a call that happens a handful of times per session.

    TRDD-DQXMND59 follow-up (adversarial review, 2026-09-24, finding B): this used to open
    the file in TEXT mode (`encoding="utf-8"`) and its own bare `json.loads` loop, so a
    single non-UTF-8 byte anywhere before `target_uuid`'s line raised `UnicodeDecodeError`
    and crashed `expand` outright -- the exact damage `compact`'s `extract_items` already
    knew how to skip. Now shares `jsonl_walk.iter_jsonl_entries`, the SAME byte-safe walk
    (stage 3: moved out of `jc` into its own stdlib-only module), so a damaged line earlier
    in the file no longer blocks reaching a healthy one later.
    """
    try:
        for _line_no, entry in jsonl_walk.iter_jsonl_entries(transcript, malformed_lines=malformed_lines):
            if entry.get("uuid") == target_uuid:
                return entry
    except OSError:
        return None
    return None


def extract_block(entry: dict[str, Any], index: int) -> str | None:
    """The original bytes of block ``index`` of ``entry`` — user text (str content, index
    must be 0), or one block of a list-shaped ``user``/``assistant`` content (a
    ``text`` block's ``text``, or a ``tool_result`` block's ``content``, verbatim), or an
    ``attachment`` entry's queued prompt (the joined TEXT blocks only when the prompt is a
    list of content blocks -- see the WHY comment below; NOT byte-verbatim in that one case).
    ``thinking``/``tool_use`` blocks are not expandable on their own (card 3 pairs a
    ``tool_use`` with its ``tool_result`` — expanding the tool_result is the pointer).

    "Verbatim" here means byte-for-byte EXCEPT that a lone (unpaired) UTF-16 surrogate becomes
    U+FFFD -- this function itself returns the raw block text unchanged, but `cmd_expand` (the
    only caller that prints it) always runs the result through `jsonl_walk.drop_lone_surrogates`
    before printing (stage 3b, "also" item)."""
    if entry.get("type") == "attachment":
        # TRDD-DQXMND59 follow-up (adversarial review of e23e0b39): this used to restate
        # `extract_items`'s attachment predicate (the `queued_command` type gate, the
        # prompt text-join) here, calling the OTHER module's PRIVATE tool-result text helper
        # directly -- two independent copies of one rule that could drift the moment either
        # changed without the other (matrix row V2: `expand` "not found" for a real pointer;
        # row V10: `expand` accepting an id `extract_items` never generated). Now calls
        # `attachment_item_text`, the ONE shared, public rule -- see its own docstring.
        #
        # WHY this is not byte-verbatim like the other branches: `attachment_item_text` joins
        # only the `text`-type blocks of a list-shaped prompt (matching what `extract_items`
        # scores/inlines) -- an image or other non-text block in the same prompt is silently
        # excluded from the returned string, same as the docstring above now says.
        if index != 0:
            return None
        return attachment_item_text(entry)
    message = entry.get("message")
    content = (message.get("content") if isinstance(message, dict) else None) or entry.get("content")
    if isinstance(content, str):
        return content if index == 0 else None
    if not isinstance(content, list):
        return None
    if index < 0 or index >= len(content):
        return None
    block = content[index]
    if not isinstance(block, dict):
        return None
    block_type = block.get("type")
    if block_type == "text":
        text = block.get("text")
        return text if isinstance(text, str) else None
    if block_type == "tool_result":
        result = block.get("content")
        if isinstance(result, str):
            return result
        if isinstance(result, list):
            # A structured tool_result: concatenate its own text sub-blocks verbatim.
            parts = [part.get("text", "") for part in result if isinstance(part, dict) and part.get("type") == "text"]
            return "\n".join(parts)
        return None
    return None


def resolve_pointer(
    transcript: Path, pointer_id: str, *, malformed_lines: list[int],
) -> tuple[str | None, str | None]:
    """Resolve ``pointer_id`` (``<uuid>:<n>`` or ``<uuid>:<n>@<a>-<b>``) against ``transcript``.

    Returns ``(text, None)`` on success or ``(None, error)``. ``error`` is exactly the message
    `jev_compact.py expand` prints after its ``expand failed: `` prefix, so the CLI's stderr is
    the same bytes it was before this was extracted (pinned in tests/test_jev_compact_cli.py).

    ORDER matters: a malformed id returns BEFORE the transcript is read, so ``malformed_lines``
    stays untouched; otherwise the read fills ``malformed_lines`` (even when the lookup then
    fails), and the caller reports the skipped-line count BEFORE the failure line.
    """
    # Card 6 (TRDD-88DOI824): a segment id is "<uuid>:<n>@<a>-<b>" -- split the span off
    # FIRST (rsplit on the last "@", matching real ids, which never carry one otherwise) so
    # the "<uuid>:<n>" half below is parsed exactly as it always was, pre-card-6.
    id_part = pointer_id
    line_span: tuple[int, int] | None = None
    if "@" in id_part:
        id_part, span_str = id_part.rsplit("@", 1)
        try:
            start_str, end_str = span_str.split("-", 1)
            line_span = (int(start_str), int(end_str))
        except ValueError:
            return None, f"malformed id {pointer_id!r}, expected '<uuid>:<n>@<a>-<b>'"

    try:
        target_uuid, index_str = id_part.rsplit(":", 1)
        index = int(index_str)
    except ValueError:
        return None, f"malformed id {pointer_id!r}, expected '<uuid>:<n>'"

    entry = read_jsonl_entry(transcript, target_uuid, malformed_lines=malformed_lines)
    if entry is None:
        return None, f"no transcript entry with uuid={target_uuid!r} in {transcript}"

    text = extract_block(entry, index)
    if text is None:
        return None, f"no block {index} in entry {target_uuid!r}"

    if line_span is not None:
        # `jev_compaction.py::_segment_tool_result` sliced ITS segment from this SAME raw
        # block text (never the synthetic "name(input)\n" prefix) -- see that function's own
        # docstring for why the two must agree on what "the original" is.
        start, end = line_span
        lines = text.splitlines(keepends=True)
        if start < 1 or end < start or end > len(lines):
            return None, (
                f"line span {start}-{end} out of range for block {index} "
                f"in entry {target_uuid!r} ({len(lines)} lines)"
            )
        text = "".join(lines[start - 1:end])
    return text, None
