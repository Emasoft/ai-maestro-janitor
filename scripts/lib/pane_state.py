"""One screen-state reader for a Claude Code pane (TRDD-N954KWUC, Phase 1).

"A janitor is supposed to control Claude Code to ensure continuity, but without a smart
script that understands the content of the screen there is no hope of a clean and guaranteed
janitor management of Claude Code." (USER, 2026-09-02.) This module is the READER half of
that directive: `read()`/`parse()` turn a captured pane frame into one structured `PaneState`
— everything a later policy table (Phase 2) needs to decide a keystroke, and nothing an
actuator has to re-derive from the raw text itself. Phase 1 wires no call site; `daemon.py`
still reads the pane directly via `session_liveness.retry_wedge_attempt_at_tail` until Phase 3.

PURE parsing throughout: `parse()` never raises on malformed input — a garbage capture
classifies as `StatusKind.UNKNOWN`, never an exception, so a caller can always act on the
result without a try/except around this module.

Anchored on the SAME chrome `session_liveness.status_row_text_at_tail` already anchors on
(the input-box dash borders, Claude Code's own column-0 status-glyph row) — imported, not
duplicated, per the TRDD's instruction to reuse that module's anchors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from session_liveness import (
    _INPUT_BOX_BORDER_RE,
    _RETRY_WEDGE_RE,
    _WEDGE_DETAIL_RE,
    status_row_text_at_tail,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

# How many rows above the input box's upper border may hold queued `❯ cmd` echoes — the same
# window `status_row_text_at_tail` scans, so a queued command sitting just above a status row
# is still counted. Kept as a local constant rather than importing the private one: this
# module's queue-counting is its own concern, not `session_liveness`'s.
_QUEUE_WINDOW_ROWS = 8

# How many non-empty rows ABOVE the input box's top border can hold a LIVE `API Error` banner
# (TRDD-RJJGXPIK): the banner sits just above the box, so anything further up is scrollback.
_API_ERROR_TAIL_ROWS = 8
# Fallback window when no input box is on screen to anchor to: the last N non-empty rows.
_API_ERROR_NO_BOX_ROWS = 15

_MODEL_LINE_RE = re.compile(r"🤖\s*(?P<model>.+?)\s*\|\s*📁")
_CONTEXT_PCT_RE = re.compile(r"(?P<pct>\d{1,3})%\s*context", re.IGNORECASE)


class InputFieldKind(str, Enum):
    EMPTY = "empty"
    TEXT = "text"
    QUEUED = "queued"


class StatusKind(str, Enum):
    IDLE = "idle"
    WORKING = "working"
    RETRY_WEDGE = "retry_wedge"
    AWAITING_USER = "awaiting_user"
    API_ERROR = "api_error"
    SESSION_LIMIT = "session_limit"
    COMPACTING = "compacting"
    RELOADING = "reloading"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class InputField:
    """What the pane's editable line currently shows."""

    kind: InputFieldKind
    text: str | None = None  # the typed text, only when kind is TEXT
    queued_count: int = 0  # only meaningful when kind is QUEUED


@dataclass(frozen=True)
class Status:
    """The pane's classified activity. Only the fields relevant to `kind` are populated —
    everything else stays at its default, so a caller can pattern-match on `kind` alone."""

    kind: StatusKind
    attempt: int | None = None
    total: int | None = None
    retry_in: str | None = None
    resets_at: str | None = None
    scope: str | None = None  # "session-limit" | "rate-limit" | "usage-limit" | None
    awaiting_kind: str | None = None  # "permission" | "ask-user-menu" | "model-confirm" | "rewind-menu"


@dataclass(frozen=True)
class PaneState:
    """The whole classified screen. Immutable — Phase 2's policy table takes this plus an
    event and returns a plan; it never mutates the state it was handed."""

    input_field: InputField
    status: Status
    agents_running: int
    model: str | None
    context_pct: int | None
    bypass_on: bool


def read(terminal: Mapping[str, str]) -> PaneState | None:
    """Capture `terminal`'s current pane frame and classify it. None when the pane could not
    be read at all (no channel, a dead terminal) — the caller's existing fail-open contract
    for an unreadable pane (`fleet_scan.capture_pane_text`'s own docstring: treat None as
    "cannot assess", never as a specific state)."""
    import fleet_scan  # noqa: PLC0415 -- local: avoids a hard import cycle at module load

    frame = fleet_scan.capture_pane_text(terminal)
    if frame is None:
        return None
    return parse(frame)


def _wedge_scope(status_row: str) -> str:
    low = status_row.lower()
    if "session limit" in low:
        return "session-limit"
    if "429" in low or "rate limit" in low:
        return "rate-limit"
    return "usage-limit"


def _api_error_on_screen(text: str, status_row: str | None) -> bool:
    """True iff a LIVE `API Error` banner is on screen (TRDD-RJJGXPIK) — never one that has
    scrolled away. Live means the status row, or one of the `_API_ERROR_TAIL_ROWS` non-empty
    rows directly ABOVE the input box's top border. Anchoring to the box, not to the end of
    the frame, is the point: everything BELOW the top border (a multi-line draft, a todo list,
    the footer) is a block of variable height, and counting it would push a real banner out of
    a fixed trailing window. With no input box on screen (fewer than two borders) there is no
    anchor, so fall back to the last `_API_ERROR_NO_BOX_ROWS` non-empty rows."""
    if status_row is not None and "api error" in status_row.lower():
        return True
    rows = [ln for ln in text.splitlines() if ln.strip()]
    borders = [i for i, r in enumerate(rows) if _INPUT_BOX_BORDER_RE.match(r.rstrip())]
    if len(borders) >= 2:
        window = rows[max(0, borders[-2] - _API_ERROR_TAIL_ROWS) : borders[-2]]
    else:
        window = rows[-_API_ERROR_NO_BOX_ROWS:]
    return any("api error" in ln.lower() for ln in window)


def _rewind_menu_on_screen(text: str) -> bool:
    """True iff Claude Code's Rewind picker is open (TRDD-RJJGXPIK, measured live on 2.1.323:
    Esc Esc on an EMPTY prompt opens it). It REPLACES the input box, so no border/field is
    parsed and the frame used to read as IDLE with an EMPTY field — a screen a caller would
    happily type into, with Enter one keystroke from confirming a restore point. Both landmarks
    must sit in the last `_API_ERROR_TAIL_ROWS` non-empty rows: the title and its `Esc to
    cancel` footer."""
    tail = [ln.lower() for ln in text.splitlines() if ln.strip()][-_API_ERROR_TAIL_ROWS:]
    return any(ln.strip() == "rewind" for ln in tail) and any("esc to cancel" in ln for ln in tail)


def _classify_status(text: str, status_row: str | None, agents_running: int) -> Status:
    low = text.lower()
    # TRDD-RJJGXPIK: the Rewind picker overlays everything else on screen and a human decision
    # is pending in it (Enter confirms a restore point), so it outranks every other status.
    if _rewind_menu_on_screen(text):
        return Status(kind=StatusKind.AWAITING_USER, awaiting_kind="rewind-menu")
    # TRDD-RJJGXPIK: anchor the API-error test to where Claude Code prints a LIVE error — the
    # status row, or the last few non-empty rows just above the input box. A whole-pane
    # substring test also matched an "API Error" line that merely scrolled past (an old
    # error, or a transcript/doc quoting one), so a session that had long recovered kept
    # classifying as API_ERROR and the policy table acted on a screen that no longer said so.
    if _api_error_on_screen(text, status_row):
        return Status(kind=StatusKind.API_ERROR)
    if status_row is not None:
        m = _RETRY_WEDGE_RE.search(status_row)
        if m:
            detail = _WEDGE_DETAIL_RE.search(status_row)
            return Status(
                kind=StatusKind.RETRY_WEDGE,
                attempt=int(m.group(1)),
                total=int(detail.group("total")) if detail else None,
                retry_in=detail.group("retry_in").strip() if detail else None,
                resets_at=detail.group("resets_at").strip() if detail and detail.group("resets_at") else None,
                scope=_wedge_scope(status_row),
            )
    if "do you want to proceed" in low:
        return Status(kind=StatusKind.AWAITING_USER, awaiting_kind="permission")
    if "switch to model" in low:
        return Status(kind=StatusKind.AWAITING_USER, awaiting_kind="model-confirm")
    if "askuserquestion" in low:
        return Status(kind=StatusKind.AWAITING_USER, awaiting_kind="ask-user-menu")
    if "compacting" in low:
        return Status(kind=StatusKind.COMPACTING)
    if "reloading" in low:
        return Status(kind=StatusKind.RELOADING)
    if "session limit reached" in low:
        return Status(kind=StatusKind.SESSION_LIMIT)
    # A status row that says the turn is DONE ("✻ Cogitated for 9s · done 8:46 PM") is not
    # active work — it is the last line a finished turn leaves on screen before the input box
    # goes quiet. Checked before the generic "any status row present -> working" fallback, or
    # a completed turn misreads as still busy.
    if status_row is not None and "done" in status_row.lower():
        return Status(kind=StatusKind.IDLE)
    if agents_running > 0 or status_row is not None:
        return Status(kind=StatusKind.WORKING)
    borders = [ln for ln in text.splitlines() if _INPUT_BOX_BORDER_RE.match(ln.rstrip())]
    if len(borders) >= 2:
        return Status(kind=StatusKind.IDLE)
    return Status(kind=StatusKind.UNKNOWN)


def _parse_input_field(rows: list[str], borders: list[int]) -> InputField:
    if len(borders) < 2:
        return InputField(kind=InputFieldKind.EMPTY)
    top, bottom = borders[-2], borders[-1]
    field_lines = rows[top + 1 : bottom]
    raw = field_lines[0].strip() if field_lines else ""
    content = raw[1:].strip() if raw.startswith("❯") else raw
    if "queued messages" in content.lower():
        window = rows[max(0, top - _QUEUE_WINDOW_ROWS) : top]
        count = sum(1 for r in window if r.strip()[:1] == "❯")
        return InputField(kind=InputFieldKind.QUEUED, queued_count=count)
    if not content:
        return InputField(kind=InputFieldKind.EMPTY)
    return InputField(kind=InputFieldKind.TEXT, text=content)


def parse(frame: str) -> PaneState:
    """Classify a captured pane frame into a `PaneState`. PURE — never raises; a frame that
    matches nothing recognizable classifies as `StatusKind.UNKNOWN` with an empty input
    field, never an exception."""
    text = frame or ""
    rows = [ln.rstrip() for ln in text.splitlines() if ln.strip()]
    borders = [i for i, r in enumerate(rows) if _INPUT_BOX_BORDER_RE.match(r)]
    status_row = status_row_text_at_tail(text)
    agents_running = sum(1 for r in rows if r.strip()[:1] == "◯")
    model_m = _MODEL_LINE_RE.search(text)
    pct_m = _CONTEXT_PCT_RE.search(text)
    return PaneState(
        input_field=_parse_input_field(rows, borders),
        status=_classify_status(text, status_row, agents_running),
        agents_running=agents_running,
        model=model_m.group("model").strip() if model_m else None,
        context_pct=int(pct_m.group("pct")) if pct_m else None,
        bypass_on="bypass permissions on" in text.lower(),
    )



# Status kinds that mean the MAIN turn (or a modal in front of it) is not at an idle prompt.
_MAIN_TURN_BUSY_KINDS = frozenset({
    StatusKind.COMPACTING,
    StatusKind.RELOADING,
    StatusKind.AWAITING_USER,
    StatusKind.API_ERROR,
    StatusKind.RETRY_WEDGE,
    StatusKind.SESSION_LIMIT,
})


def main_turn_busy(frame: str | None) -> bool | None:
    """Is the MAIN turn still running (or blocked behind a modal)? True / False, None when the
    frame cannot be read. PURE — never raises.

    WHY this exists and is NOT `parse(frame).status.kind != StatusKind.IDLE` (issues #355, #356):
    the /clear chain typed `/clear` into a pane mid-turn. The input field is EMPTY mid-turn, so
    the injector's "field is empty" rule passed, Claude Code QUEUED the command, and it ran at
    the next turn boundary — 19 minutes later in #355, after the chain had given up, so phase B
    never ran. `StatusKind.WORKING` cannot be the gate: `_classify_status` also returns it when
    only BACKGROUND-AGENT rows (`◯ ...`) are on screen while the main turn is idle, and a gate on
    it would hold every clear for up to an hour whenever a background agent is listed.

    Busy means the LAST status block (`status_row_text_at_tail` keeps the block closest to the
    input box, so an older stale glyph row above it is ignored) is a glyph-led row that does not
    say `done`, or the status kind is one of `_MAIN_TURN_BUSY_KINDS`. `agents_running` alone is
    never busy. None (a frame with no input box and no status) must be treated by the caller as
    busy too: typing blind into an unreadable pane is the original bug.
    """
    text = frame or ""
    status = parse(text).status
    if status.kind in _MAIN_TURN_BUSY_KINDS:
        return True
    status_row = status_row_text_at_tail(text)
    if status_row is not None and "done" not in status_row.lower():
        return True
    if status.kind == StatusKind.UNKNOWN:
        return None
    return False
