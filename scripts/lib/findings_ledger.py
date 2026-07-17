"""Per-project findings ledger — the ONE choke point for finding events (TRDD-FENWWB4E).

Implements `design/ARCHITECTURE.md` §4 (RATIFIED rev 3 on janitor#100, 2026-07-17):
`gather → route → record → surface`, with routing strictly per-project. The ledger is an
append-only INDEX — one sanitized JSON line per finding EVENT — never a payload: bodies
live in the ticket / proposal TRDD named by `ref`, so a human can quote `T-XXXXXXXX` to
the affected project's Claude, which reads the ticket ("traceable, recorded, easily
referenced" — the owner's requirement).

THE LINE SHAPE IS A FROZEN CONTRACT: `{"ts","sev","code","src","ref","msg"}`, ≤ ~200
chars, sanitized. The ai-maestro dashboard tails its own agents' ledger FILES and renders
them (their §6.5 acceptance) — any shape change must be re-negotiated on #100 as a new
ARCHITECTURE.md revision BEFORE code changes it.

Three sinks, one `record()` call:
  1. the AFFECTED project's ledger — `<project>/.janitor/state/findings-ledger.ndjsonl`.
     The daemon writes X's findings into X's OWN state dir (the per-project mailbox);
     per-session detectors write their own project's. That routing IS the isolation.
  2. the firing session's drift line — `record()` RETURNS the rendered line iff the
     affected project is the CURRENT project (TRDD-X92VBFNF: an automatic surface may
     carry only the project it fires in), else None. The caller prints it (or ignores it
     when it already emits a richer line, e.g. `issue_catalog.raise_issue`).
  3. the human push — the `notify` SEAM: a callable invoked with the entry dict.
     TRDD-4649ZLE0 (plan Phase 5) supplies the real severity-gated / deduped /
     no-live-session push; until then callers pass None and the sink is inert.

Fail-open everywhere: a ledger failure must never break a detector, a hook, or the
daemon loop.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Callable, Optional

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import state  # noqa: E402  -- sibling lib
import token_meter  # noqa: E402  -- trim_log (the structural-cap pattern, TRDD-a4e41e89)

LEDGER_NAME = "findings-ledger.ndjsonl"
CURSOR_NAME = "findings-ledger.cursor"

# Caps. `msg` is truncated so one JSON line stays ≤ ~200 chars (the ratified shape);
# the file is structurally trimmed so the mailbox of a project unattended for months
# stays bounded (every append site must rotate or trim — the S3+S4 invariant).
MAX_MSG_CHARS = 120
KEEP_LINES = 500
MAX_BYTES = 120_000

# SessionStart surfacing budget (the owner's conciseness requirement: "as concise as
# possible to avoid burning the context before even starting to work").
SURFACE_CAP_LINES = 10
SURFACE_BUDGET_BYTES = 1024


def _enabled() -> bool:
    return state.is_truthy_env("CLAUDE_PLUGIN_OPTION_FINDINGS_LEDGER_ENABLED", True)


def state_dir_for(project_dir: str | os.PathLike[str] | None = None) -> Path:
    """The janitor state dir of the AFFECTED project. None ⇒ the CURRENT project
    (state.state_dir() — the per-session caller's own mailbox); a path ⇒ that project's
    `<dir>/.janitor/state` (the daemon writing into the affected project's mailbox)."""
    if project_dir is None:
        return state.state_dir()
    return Path(project_dir) / ".janitor" / "state"


def ledger_path(project_dir: str | os.PathLike[str] | None = None) -> Path:
    return state_dir_for(project_dir) / LEDGER_NAME


def _cursor_path(project_dir: str | os.PathLike[str] | None = None) -> Path:
    return state_dir_for(project_dir) / CURSOR_NAME


def _clean(text: object, cap: int) -> str:
    """One ledger FIELD: sanitize (defang brackets, strip control/bidi chars), then
    COLLAPSE all whitespace to single spaces, then cap. The collapse matters on top of
    `sanitize_for_drift_line` because that helper deliberately keeps tab + newline —
    fine for a drift line printed as-is, but a ledger entry must render as ONE line
    (an embedded newline in `msg` would split the rendered line and let attacker text
    fake a standalone finding/marker line)."""
    return " ".join(state.sanitize_for_drift_line(str(text)).split())[:cap]


def _is_current_project(project_dir: str | os.PathLike[str] | None) -> bool:
    """Sink-2 gate (TRDD-X92VBFNF): the drift line may surface ONLY in the affected
    project's own session. None means "the caller's own project" by construction."""
    if project_dir is None:
        return True
    try:
        return Path(project_dir).resolve() == state.project_root().resolve()
    except Exception:  # noqa: BLE001 -- an unresolvable path must not crash the caller
        return False


def render_line(entry: dict) -> str:
    """One greppable session line for a ledger entry. Values were sanitized at record
    time, but render defensively anyway — an entry may come off DISK, where any process
    could have written it."""
    sev = _clean(entry.get("sev", ""), 12)
    code = _clean(entry.get("code", ""), 24)
    src = _clean(entry.get("src", ""), 32)
    ref = _clean(entry.get("ref", "-"), 24)
    msg = _clean(entry.get("msg", ""), MAX_MSG_CHARS)
    return f"[findings] {sev} {code} ({src}): {msg} — ref {ref}"


def record(
    *,
    sev: str,
    code: str,
    src: str,
    msg: str,
    ref: str = "-",
    project_dir: str | os.PathLike[str] | None = None,
    now: Optional[int] = None,
    notify: Optional[Callable[[dict], None]] = None,
) -> str | None:
    """THE choke point: record one finding event into the affected project's ledger.

    Returns the rendered drift line iff the affected project is the CURRENT project
    (sink 2 — the caller decides whether to print it), else None. Sink 3 (`notify`)
    is the TRDD-4649ZLE0 seam — invoked best-effort with the entry dict when supplied;
    Phase 5 provides the real push, so today every caller passes None.

    Never raises; a failed append returns the sink-2 answer anyway (surfacing beats
    bookkeeping — a finding that reached the session is not lost even if the mailbox
    write failed).
    """
    import time  # noqa: PLC0415 -- stdlib, keep module import-light

    entry = {
        "ts": int(time.time()) if now is None else int(now),
        "sev": _clean(sev, 12),
        "code": _clean(code, 24),
        "src": _clean(src, 32),
        "ref": _clean(ref or "-", 24),
        "msg": _clean(msg, MAX_MSG_CHARS),
    }
    if _enabled():
        try:
            path = ledger_path(project_dir)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, separators=(",", ":")) + "\n")
            token_meter.trim_log(path, keep_lines=KEEP_LINES, max_bytes=MAX_BYTES)
        except Exception:  # noqa: BLE001 -- the mailbox must never break its writers
            pass
    if notify is not None:
        try:
            notify(entry)
        except Exception:  # noqa: BLE001 -- the push seam must never break the record
            pass
    return render_line(entry) if _is_current_project(project_dir) else None


def _read_raw(project_dir: str | os.PathLike[str] | None = None) -> tuple[list[dict], int]:
    """(entries in file order, total file size in bytes). Corrupt lines are skipped —
    the ledger is append-only NDJSON, so one torn write must not hide the rest."""
    try:
        raw = ledger_path(project_dir).read_bytes()
    except OSError:
        return [], 0
    entries: list[dict] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            data = json.loads(line)
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("ts"), (int, float)):
            entries.append(data)
    return entries, len(raw)


def _read_cursor(project_dir: str | os.PathLike[str] | None = None) -> tuple[int, int]:
    """(consumed byte offset, newest surfaced ts). (0, 0) when never advanced."""
    try:
        data = json.loads(_cursor_path(project_dir).read_text(encoding="utf-8"))
        return int(data.get("offset", 0)), int(data.get("ts", 0))
    except Exception:  # noqa: BLE001 -- absent/corrupt cursor = nothing surfaced yet
        return 0, 0


def unread_entries(
    project_dir: str | os.PathLike[str] | None = None,
    *,
    cap: int = SURFACE_CAP_LINES,
    budget_bytes: int = SURFACE_BUDGET_BYTES,
) -> tuple[list[str], int]:
    """(rendered unread lines, NEWEST first, capped by count AND byte budget;
    total unread count). Read-only — `advance_cursor()` is the separate ack, so a
    surfacing path that crashes mid-print re-surfaces instead of losing entries.

    Cursor semantics: the primary mark is the consumed BYTE OFFSET (exact). When the
    structural trim rewrote the file smaller than the stored offset, the offset no
    longer addresses the same bytes — fall back to the stored newest-surfaced TS
    (entries with ts > cursor ts are unread), so a trim can neither re-inject the
    whole history nor lose the tail.
    """
    entries, size = _read_raw(project_dir)
    offset, cursor_ts = _read_cursor(project_dir)
    if offset > size:
        unread = [e for e in entries if e["ts"] > cursor_ts]
    elif offset <= 0:
        unread = entries
    else:
        # Exact: re-serialize file-order entries counting bytes until the offset is
        # consumed; everything past it is unread. Cheaper than tracking offsets per
        # line on write, and exact because the file is what we just read.
        unread = []
        consumed = 0
        try:
            raw_lines = ledger_path(project_dir).read_bytes().split(b"\n")
        except OSError:
            raw_lines = []
        for bline in raw_lines:
            line_len = len(bline) + 1  # + the newline
            s = bline.strip()
            parsed = None
            if s:
                try:
                    parsed = json.loads(s.decode("utf-8", errors="replace"))
                except ValueError:
                    parsed = None
            if consumed >= offset and isinstance(parsed, dict) and isinstance(parsed.get("ts"), (int, float)):
                unread.append(parsed)
            consumed += line_len
    total = len(unread)
    lines: list[str] = []
    used = 0
    for e in reversed(unread):  # newest first
        line = render_line(e)
        if len(lines) >= cap or used + len(line.encode("utf-8")) > budget_bytes:
            break
        lines.append(line)
        used += len(line.encode("utf-8"))
    return lines, total


def advance_cursor(project_dir: str | os.PathLike[str] | None = None) -> None:
    """Mark everything currently in the ledger as surfaced (the ack). Atomic; never raises."""
    try:
        entries, size = _read_raw(project_dir)
        newest_ts = max((int(e["ts"]) for e in entries), default=0)
        payload = json.dumps({"offset": size, "ts": newest_ts})
        state.atomic_write(_cursor_path(project_dir), payload)
    except Exception:  # noqa: BLE001 -- an unacked cursor merely re-surfaces; never crash
        pass


def surface_block(project_dir: str | os.PathLike[str] | None = None) -> str:
    """The SessionStart injection: capped unread lines + ONE fold line, then the cursor
    advances. Empty string when nothing is unread (silence — no empty-inbox chatter).
    ≤ ~1 KB by construction (the owner's context-budget constraint)."""
    lines, total = unread_entries(project_dir)
    if not lines:
        return ""
    folded = total - len(lines)
    out = list(lines)
    if folded > 0:
        out.append(f"[findings] …{folded} older unread — `/janitor-findings` to browse")
    advance_cursor(project_dir)
    return "\n".join(out)
