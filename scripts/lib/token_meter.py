"""Per-heartbeat token accounting (TRDD-a4e41e89, Phase 1).

The heartbeat cron fires an agent turn every ~5 min; each turn costs tokens. This
module measures that cost from the session transcript so the user can see spikes
or a too-high average (`/janitor-token-report`).

Design constraints (verified against the real transcript format):
  * Each `assistant` entry carries `message.usage` with input/output/cache token
    counts — summing a turn's assistant messages gives the turn's token cost.
  * A HEARTBEAT turn's triggering `type:user` entry's content STARTS WITH
    `[janitor-heartbeat]` (`promptSource` is not unique, so match on content).
  * The transcript is large (tens of MB) → read only the TAIL, walk entries
    backwards to the triggering user message; never parse the whole file.

Everything here is PURE (the only I/O is reading a path you pass + appending one
log line) so it is unit-testable with fixture transcripts. The Stop-hook wrapper
(`on-stop-token-meter.py`) is the only side-effecting caller.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

_HEARTBEAT_MARKER = "[janitor-heartbeat]"
# 512 KB tail comfortably covers one heartbeat turn (a few short messages). If a
# turn ever exceeds this the boundary won't be found and we log nothing rather
# than guess — correct-by-omission beats a wrong number.
_TAIL_BYTES = 512 * 1024


@dataclass
class TurnUsage:
    """Summed token usage of the most-recent turn, plus whether it was a heartbeat.

    The four token components are the raw transcript fields; the report layer
    decides how to weight them (output + input + cache_creation are full/premium
    price; cache_read is the cheap ~0.1x context re-read, kept for visibility).
    """

    is_heartbeat: bool
    input_tokens: int
    output_tokens: int
    cache_read_input_tokens: int
    cache_creation_input_tokens: int
    assistant_messages: int
    tool_calls: int

    def as_record(self, now_epoch: int) -> dict:
        return {
            "ts": int(now_epoch),
            "input": self.input_tokens,
            "output": self.output_tokens,
            "cache_read": self.cache_read_input_tokens,
            "cache_creation": self.cache_creation_input_tokens,
            "assistant_msgs": self.assistant_messages,
            "tool_calls": self.tool_calls,
        }


def _read_tail_lines(path: Path, max_bytes: int = _TAIL_BYTES) -> list[str]:
    """Return the text lines in the last `max_bytes` of `path` (file order).

    The first line may be a partial JSON fragment when the file is larger than
    the window — the caller drops it via a json-parse failure.
    """
    size = path.stat().st_size
    with path.open("rb") as f:
        if size > max_bytes:
            f.seek(size - max_bytes)
        data = f.read()
    return data.decode("utf-8", errors="replace").splitlines()


def _is_tool_result(entry: dict) -> bool:
    """True iff a `type:user` entry is a tool RESULT, not a real prompt.

    Tool results are delivered as user-role messages whose content is a list
    containing `tool_result` blocks. They are part of the IN-PROGRESS turn (the
    agent called a tool, this is the reply), NOT the turn-triggering user prompt
    — so the walk-back must step over them, or it stops at the wrong boundary and
    every multi-step turn (i.e. every heartbeat that runs the dispatcher) is
    misread as a non-heartbeat turn with zero usage.
    """
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return False
    content = msg.get("content")
    if isinstance(content, list):
        return any(isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
    return False


def _message_text(entry: dict) -> str:
    """The text of a transcript entry's message — handles a string OR a list of
    content blocks (only `text` blocks contribute)."""
    msg = entry.get("message")
    if not isinstance(msg, dict):
        return ""
    content = msg.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = [b["text"] for b in content if isinstance(b, dict) and isinstance(b.get("text"), str)]
        return "\n".join(parts)
    return ""


def tail_turn_usage(transcript_path: str | os.PathLike[str]) -> Optional[TurnUsage]:
    """Sum the most-recent turn's token usage and flag whether it's a heartbeat.

    Walks the tail entries backwards, accumulating `assistant` usage until the
    triggering `type:user` entry. Returns None when the file is absent/unreadable
    or the turn's boundary isn't inside the tail window (don't guess).
    """
    p = Path(transcript_path)
    if not p.is_file():
        return None
    try:
        lines = _read_tail_lines(p)
    except OSError:
        return None

    entries: list[dict] = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except ValueError:
            continue  # partial first line / non-JSON noise
        if isinstance(obj, dict):
            entries.append(obj)
    if not entries:
        return None

    inp = out = cache_read = cache_create = 0
    assistant_msgs = tool_calls = 0
    trigger: Optional[dict] = None
    for entry in reversed(entries):
        etype = entry.get("type")
        if etype == "user":
            if _is_tool_result(entry):
                continue  # tool result — part of the turn, not its boundary
            trigger = entry
            break
        if etype == "assistant":
            msg = entry.get("message")
            if isinstance(msg, dict):
                usage = msg.get("usage")
                if isinstance(usage, dict):
                    inp += int(usage.get("input_tokens") or 0)
                    out += int(usage.get("output_tokens") or 0)
                    cache_read += int(usage.get("cache_read_input_tokens") or 0)
                    cache_create += int(usage.get("cache_creation_input_tokens") or 0)
                    assistant_msgs += 1
                content = msg.get("content")
                if isinstance(content, list):
                    tool_calls += sum(
                        1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use"
                    )
    if trigger is None:
        return None  # turn boundary not in the tail window — omit rather than guess

    is_heartbeat = _message_text(trigger).lstrip().startswith(_HEARTBEAT_MARKER)
    return TurnUsage(
        is_heartbeat=is_heartbeat,
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
        assistant_messages=assistant_msgs,
        tool_calls=tool_calls,
    )


def latest_context_size(transcript_path: str | os.PathLike[str]) -> Optional[int]:
    """Total INPUT context (input + cache_read + cache_creation tokens) the model
    processed for the MOST RECENT assistant message — i.e. the live context-window
    occupancy. This is the cost-driving number the user named: every turn re-reads
    ~this many tokens, so a session bloated near the window cap bleeds ~this much PER
    TURN regardless of how much it produces ("a context of 999k executed each turn").
    The context-watchdog uses it to FORCE a compaction before the next turn pays it
    again (TRDD-SMZFJVZ3).

    Distinct from `tail_turn_usage`, which SUMS a turn's assistant messages (per-turn
    COST). Here we want the LATEST single message's input occupancy — the live size.

    Returns None when the file is absent/unreadable or no assistant `usage` sits in the
    tail window (correct-by-omission: the watchdog then stays silent rather than guess).
    """
    p = Path(transcript_path)
    if not p.is_file():
        return None
    try:
        lines = _read_tail_lines(p)
    except OSError:
        return None
    for line in reversed(lines):
        s = line.strip()
        if not s:
            continue
        try:
            obj = json.loads(s)
        except ValueError:
            continue
        if not isinstance(obj, dict) or obj.get("type") != "assistant":
            continue
        msg = obj.get("message")
        if not isinstance(msg, dict):
            continue
        usage = msg.get("usage")
        if not isinstance(usage, dict):
            continue
        total = (
            int(usage.get("input_tokens") or 0)
            + int(usage.get("cache_read_input_tokens") or 0)
            + int(usage.get("cache_creation_input_tokens") or 0)
        )
        if total > 0:
            return total
    return None


def append_log(log_path: str | os.PathLike[str], turn_usage: TurnUsage, now_epoch: int) -> None:
    """Append one JSON line for a heartbeat turn's usage (append is atomic enough
    for single-line writes on local fs; the meter is the only writer)."""
    line = json.dumps(turn_usage.as_record(now_epoch), separators=(",", ":")) + "\n"
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(line)


def trim_log(log_path: str | os.PathLike[str], *, keep_lines: int = 5000, max_bytes: int = 1_000_000) -> None:
    """Cap the append-only log: when it exceeds `max_bytes`, atomically rewrite
    it keeping only the last `keep_lines` records. Amortised-cheap — only rewrites
    when oversized (≈17 days of 5-min heartbeats at the default cap)."""
    p = Path(log_path)
    try:
        if not p.is_file() or p.stat().st_size <= max_bytes:
            return
        lines = [ln for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        kept = lines[-keep_lines:]
        tmp = p.with_name(p.name + ".tmp")
        tmp.write_text("\n".join(kept) + "\n", encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        pass


def load_log(log_path: str | os.PathLike[str]) -> list[dict]:
    p = Path(log_path)
    if not p.is_file():
        return []
    out: list[dict] = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                continue
            try:
                rec = json.loads(s)
            except ValueError:
                continue
            if isinstance(rec, dict):
                out.append(rec)
    return out


def _percentile(sorted_vals: list[int], pct: float) -> int:
    if not sorted_vals:
        return 0
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    k = int(round((pct / 100.0) * (n - 1)))
    return sorted_vals[max(0, min(n - 1, k))]


@dataclass
class BudgetVerdict:
    """The budget-tier decision for the IN-PROGRESS turn (TRDD-KI24GR5Z).

    `tier` is the WORST tier any signal tripped: ``ok`` | ``advisory`` | ``hard``.
    `reasons` names every tripped signal (hard before advisory) for the nudge text.
    """

    tier: str
    reasons: list[str]


def evaluate_turn_budget(
    usage: TurnUsage,
    *,
    output_advisory: int,
    output_hard: int,
    cache_creation_advisory: int,
    cache_creation_hard: int,
) -> BudgetVerdict:
    """Classify the in-progress turn's cost into ok / advisory / hard from TWO signals:

    - **output** tokens — full-price agent work (long replies / many tool calls).
    - **cache_creation** tokens — a CACHE-MISS cache WRITE (the prompt prefix changed, so
      the new prefix is written to cache at ~1.25× premium). A large value in one turn is
      the "cache write caused by a cache miss" the guard must catch — distinct from the
      cheap 0.1× ``cache_read`` re-read, which is NOT billed here.

    Each threshold is checked INDEPENDENTLY; a threshold of ``0`` DISABLES that check
    (so a user can watch only output, only cache-miss, or both). ``tier`` is the worst
    tripped tier; ``reasons`` lists every tripped signal, hard first. Pure — no I/O, so
    it is unit-tested with plain ``TurnUsage`` values.
    """
    reasons_hard: list[str] = []
    reasons_advisory: list[str] = []
    o = usage.output_tokens
    c = usage.cache_creation_input_tokens
    if output_hard > 0 and o >= output_hard:
        reasons_hard.append(f"output {o} ≥ hard {output_hard}")
    elif output_advisory > 0 and o >= output_advisory:
        reasons_advisory.append(f"output {o} ≥ {output_advisory}")
    if cache_creation_hard > 0 and c >= cache_creation_hard:
        reasons_hard.append(f"cache-miss write {c} ≥ hard {cache_creation_hard}")
    elif cache_creation_advisory > 0 and c >= cache_creation_advisory:
        reasons_advisory.append(f"cache-miss write {c} ≥ {cache_creation_advisory}")
    if reasons_hard:
        return BudgetVerdict(tier="hard", reasons=reasons_hard + reasons_advisory)
    if reasons_advisory:
        return BudgetVerdict(tier="advisory", reasons=reasons_advisory)
    return BudgetVerdict(tier="ok", reasons=[])


def summarize(records: list[dict], *, field: str = "output") -> Optional[dict]:
    """Distribution stats for `field` over the per-heartbeat records.

    Default `output` — the clearest cost driver (full-price, reflects agent work).
    Returns None on an empty log.
    """
    if not records:
        return None
    vals = sorted(int(r.get(field, 0) or 0) for r in records)
    n = len(vals)
    return {
        "count": n,
        "field": field,
        "total": sum(vals),
        "mean": sum(vals) / n,
        "min": vals[0],
        "p50": _percentile(vals, 50),
        "p95": _percentile(vals, 95),
        "max": vals[-1],
    }
