# Marker-fence operations for the project-map block (TRDD-e247a349 §3, §4).
#
# Pure string surgery on CLAUDE.md text: locate the fenced block, parse its
# header, and replace / insert / remove it — touching ONLY the bytes between
# (and including) the START/END fences, never the surrounding human narrative.
#
# Safety invariants (TRDD §4):
#   - Operate ONLY on the fenced region. Every non-fenced byte is preserved.
#   - Malformed fences (one side missing, duplicated, or END-before-START) →
#     raise MalformedFences. NEVER guess where the block is.
#   - No I/O here. The maintainer/skill does the atomic read+write; this module
#     is deterministic and trivially testable.

from __future__ import annotations

from .renderer import FENCE_END, FENCE_START


class MalformedFences(ValueError):
    """The CLAUDE.md text contains a broken janitor fence pair
    (one side missing, duplicated, or END appearing before START)."""


# Every function below takes optional `start=` / `end=` fence strings, defaulting to the
# repo-map pair — so the SAME surgery serves the wikimem-index fence (TRDD-H12K9JYX) and
# any future janitor-owned region. One implementation, because two fence-splicers that
# drift apart is how one of them eats the other's block.


def _fence_span(text: str, start: str = FENCE_START, end: str = FENCE_END) -> tuple[int, int] | None:
    """Char span [start, end) covering the whole fenced block — from the first
    char of the START fence line through the END fence line's trailing newline.

    Returns None when NO fence of either kind is present (a clean, map-less
    CLAUDE.md). Raises MalformedFences when the fences are present but broken.
    """
    lines = text.splitlines(keepends=True)
    starts = [i for i, ln in enumerate(lines) if ln.strip().startswith(start)]
    ends = [i for i, ln in enumerate(lines) if ln.strip() == end]
    if not starts and not ends:
        return None
    if len(starts) != 1 or len(ends) != 1 or starts[0] > ends[0]:
        raise MalformedFences(
            f"expected exactly one START before one END fence ({start[:40]}…); "
            f"found {len(starts)} START / {len(ends)} END"
        )
    s, e = starts[0], ends[0]
    start_off = sum(len(ln) for ln in lines[:s])
    end_off = sum(len(ln) for ln in lines[: e + 1])  # incl. END line + its newline
    return start_off, end_off


def has_map_block(text: str, start: str = FENCE_START, end: str = FENCE_END) -> bool:
    """True iff a well-formed fenced block is present. Malformed fences raise
    (the caller must surface that, not silently treat it as absent)."""
    return _fence_span(text, start, end) is not None


def read_fence_header(text: str, start: str = FENCE_START, end: str = FENCE_END) -> dict[str, str] | None:
    """Parse the START fence's metadata (`sha`, `digest`, `generated`, schema)
    so the maintainer can decide 'regen needed?' from one line without
    re-extracting. None when no block. The ISO `generated` value has no spaces,
    so whitespace tokenisation is safe."""
    span = _fence_span(text, start, end)
    if span is None:
        return None
    start_line = text[span[0] : span[1]].splitlines()[0]
    rest = start_line[len(start) :].strip()
    fields: dict[str, str] = {}
    for tok in rest.split():
        if "=" in tok:
            key, val = tok.split("=", 1)
            fields[key] = val
        elif tok and "schema" not in fields:
            fields["schema"] = tok  # the leading bare `v1`
    return fields


def replace_map_block(text: str, new_block: str, start: str = FENCE_START, end: str = FENCE_END) -> str:
    """Swap the existing fenced block for `new_block` (the maintainer's
    on-change path). `new_block` is a full rendered string (fences
    included, trailing newline included). Raises if no block exists — callers
    must use insert_map_block for first-time insertion so the absence is
    explicit, not silently papered over."""
    span = _fence_span(text, start, end)
    if span is None:
        raise MalformedFences(f"no {start[:40]}… block to replace; use insert_map_block")
    return text[: span[0]] + new_block + text[span[1] :]


def insert_map_block(text: str, new_block: str, start: str = FENCE_START, end: str = FENCE_END) -> str:
    """First-time insertion (the /janitor-auto-repomap-on path): append the
    block at the end, after the human narrative, with one blank-line separator.
    Raises if a block already exists (use replace_map_block instead)."""
    if _fence_span(text, start, end) is not None:
        raise MalformedFences(f"a {start[:40]}… block already exists; use replace_map_block")
    if not text.strip():
        return new_block
    return text.rstrip("\n") + "\n\n" + new_block


def remove_map_block(text: str, start: str = FENCE_START, end: str = FENCE_END) -> str:
    """Splice out the fenced block entirely (the /janitor-auto-repomap-off
    path), restoring the map-less CLAUDE.md with sane spacing at the seam.
    No-op (returns text unchanged) when no block is present."""
    span = _fence_span(text, start, end)
    if span is None:
        return text
    before, after = text[: span[0]], text[span[1] :]
    if not before.strip():
        return after.lstrip("\n")
    if not after.strip():
        return before.rstrip("\n") + "\n"
    return before.rstrip("\n") + "\n\n" + after.lstrip("\n")
