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

from session_liveness import _INPUT_BOX_BORDER_RE, _RETRY_WEDGE_RE, status_row_text_at_tail

if TYPE_CHECKING:
    from collections.abc import Mapping

# How many rows above the input box's upper border may hold queued `❯ cmd` echoes — the same
# window `status_row_text_at_tail` scans, so a queued command sitting just above a status row
# is still counted. Kept as a local constant rather than importing the private one: this
# module's queue-counting is its own concern, not `session_liveness`'s.
_QUEUE_WINDOW_ROWS = 8

# The richer wedge-detail regex `session_liveness._RETRY_WEDGE_RE` doesn't capture: total
# attempts, the retry-in duration, and the optional wall-clock reset time. Anchored on the
# SAME `retrying in … attempt N/M` shape (reuses `_RETRY_WEDGE_RE`'s own vocabulary), just
# with capture groups `session_liveness` has no reason to carry itself.
_WEDGE_DETAIL_RE = re.compile(
    r"retrying\s+in\s+(?P<retry_in>[^·(]+?)\s*(?:\((?P<resets_at>[^)]+)\))?\s*·\s*"
    r"attempt\s+(?P<attempt>\d+)\s*/\s*(?P<total>\d+)",
    re.IGNORECASE,
)

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
    awaiting_kind: str | None = None  # "permission" | "ask-user-menu" | "model-confirm"


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


def _classify_status(text: str, status_row: str | None, agents_running: int) -> Status:
    low = text.lower()
    if "api error" in low:
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
