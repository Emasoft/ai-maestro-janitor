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
import sys
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# token_meter is imported BOTH as top-level `token_meter` (most callers put scripts/lib on the
# path) AND as `lib.token_meter` (e.g. on-stop-failure.py puts only scripts/ on the path). Add
# this file's OWN dir to sys.path so the sibling `token_baseline` resolves in EITHER context —
# mirrors harness_backend.py. Without it, `import token_baseline` raises under the `lib.token_meter`
# import and silently disables the StopFailure hook's exhaustion-log path (regression 2026-07-23).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import token_baseline  # noqa: E402  -- sibling lib: weighted-cost + rolling-window primitives

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
        # `heartbeat` tags WHICH KIND of turn this was. Until TRDD-DLI76AUC #4 the meter logged
        # heartbeat turns ONLY, so the flag was implicit — and the log was therefore blind to every
        # interactive turn, including a user-typed `/janitor-arm`. Now every turn is logged and the
        # flag is explicit. A record WITHOUT the key predates that change and is a heartbeat, which
        # is why every reader must default it to True rather than False.
        return {
            "ts": int(now_epoch),
            "heartbeat": bool(self.is_heartbeat),
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

    # Claude Code writes one `assistant` transcript ENTRY per streamed CONTENT BLOCK, and
    # every entry of the same API response repeats the SAME `message.usage` object. Summing
    # per ENTRY therefore multiplies one response's usage by its block count — measured live
    # at 2.1-3.7x inflation (the "janitor meter is FLAWED" bug, 2026-07-07). Usage must be
    # counted ONCE per unique message id; last entry wins (values are identical today, and
    # last-wins stays correct if CC ever streams cumulative usage). Entries with no message
    # id fall back to their per-entry uuid so they are never silently dropped or merged.
    usage_by_msg: dict[str, dict] = {}
    tool_calls = 0
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
                    key = str(msg.get("id") or entry.get("uuid") or id(entry))
                    # reversed() walk: the FIRST time we see an id here is the file-order
                    # LAST entry for it — setdefault keeps that one, i.e. last-wins.
                    usage_by_msg.setdefault(key, usage)
                content = msg.get("content")
                if isinstance(content, list):
                    # tool_use blocks are NOT duplicated across a message's entries (each
                    # entry carries its own distinct block) — per-entry counting is right.
                    tool_calls += sum(1 for b in content if isinstance(b, dict) and b.get("type") == "tool_use")
    if trigger is None:
        return None  # turn boundary not in the tail window — omit rather than guess

    inp = sum(int(u.get("input_tokens") or 0) for u in usage_by_msg.values())
    out = sum(int(u.get("output_tokens") or 0) for u in usage_by_msg.values())
    cache_read = sum(int(u.get("cache_read_input_tokens") or 0) for u in usage_by_msg.values())
    cache_create = sum(int(u.get("cache_creation_input_tokens") or 0) for u in usage_by_msg.values())

    is_heartbeat = _message_text(trigger).lstrip().startswith(_HEARTBEAT_MARKER)
    return TurnUsage(
        is_heartbeat=is_heartbeat,
        input_tokens=inp,
        output_tokens=out,
        cache_read_input_tokens=cache_read,
        cache_creation_input_tokens=cache_create,
        assistant_messages=len(usage_by_msg),
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
        total = int(usage.get("input_tokens") or 0) + int(usage.get("cache_read_input_tokens") or 0) + int(usage.get("cache_creation_input_tokens") or 0)
        if total > 0:
            return total
    return None


_CONTEXT_SNAPSHOT_STALE_AGE_S = 120  # statusline-write lag beyond which a snapshot is untrusted


def read_context_snapshot(project_dir: str, session_id: str) -> Optional[dict]:
    """The statusline-written context snapshot dict for (project_dir, session_id), or
    None when absent/unreadable/not-a-dict.

    Moved out of ``pre-tool-context-usage.py`` (TRDD-TKNSTP82 A4) so the context-watchdog
    hook and ``/janitor-token-report --live`` share one implementation instead of two
    independently-drifting copies.
    """
    if not project_dir or not session_id:
        return None
    p = Path(project_dir) / ".claude" / "janitor" / f"context-usage.{session_id}.json"
    try:
        snap = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    return snap if isinstance(snap, dict) else None


def resolve_context(project_dir: str, session_id: str, transcript: str, window_default: int, *, now: int) -> tuple[Optional[int], Optional[int], Optional[int], bool]:
    """Return (pct, tokens, window, stale) — the live context-window occupancy.

    Prefers the statusline snapshot (it carries the real window → an accurate %); falls
    back to `latest_context_size` over `window_default` when no snapshot is readable.
    (None, None, None, False) when neither source yields a usable %.

    Moved out of ``pre-tool-context-usage.py`` (TRDD-TKNSTP82 A4) — that hook's own
    behavior is UNCHANGED, it now just calls this shared implementation, and
    ``/janitor-token-report --live`` reuses it for the same "exact context %" view so the
    two surfaces can never silently drift apart.

    **The snapshot is not trusted blindly.** A `pct` at/above the hardstop makes the
    context-usage hook fire `/compact` and DENY the tool call — it destroys real
    conversation — so a single bogus number from outside must not be able to trigger it.
    Claude Code 2.1.208 fixed exactly such a bug: after a CLI auto-update the context
    window "briefly reset to 200k", producing a false "100% context used" on long-context
    sessions. Its signature is `tokens > window`, which is impossible in a healthy session
    (the harness compacts before occupancy can exceed the window). When we see it, the
    WINDOW is what is wrong, not the token count — so we recompute the % against
    `window_default` (the configured expectation) instead of believing the reset one.
    Users on a pre-2.1.208 CLI are still exposed; the guard costs one comparison.
    """
    snap = read_context_snapshot(project_dir, session_id)
    if snap is not None and isinstance(snap.get("pct"), int):
        tokens = snap.get("tokens") if isinstance(snap.get("tokens"), int) else None
        window = snap.get("window") if isinstance(snap.get("window"), int) and snap["window"] > 0 else None
        ts = snap.get("ts")
        stale = isinstance(ts, int) and (now - ts) > _CONTEXT_SNAPSHOT_STALE_AGE_S
        if tokens is not None and window is not None and tokens > window and window_default > 0:
            return int(round(100 * tokens / window_default)), tokens, window_default, stale
        return snap["pct"], tokens, window, stale
    if transcript and window_default > 0:
        tokens = latest_context_size(transcript)
        if tokens is not None:
            pct = int(round(100 * tokens / window_default))
            return pct, tokens, window_default, False
    return None, None, None, False


# F1 reload-churn guard (TRDD-Z582IKIR): default context-token threshold above which
# `/reload-plugins` is deferred by dispatch.py's `_phase_plugin_reload` (the janitor's
# OWN auto-emitted `[janitor-reload]`). A human-typed `/reload-plugins` cannot be guarded
# at all — it fires NO hook of any kind (measured; see the `claude-code-hook-types` memory,
# `^no-plugin-reload-hook`). `/reload-plugins` breaks the prompt-cache prefix, forcing a
# full cache-CREATE (~1.25x) of the WHOLE context on the next turn instead of a cheap
# cache-read (~0.1x) — on a large session that single reload is a ~500k+ weighted-token tax.
RELOAD_GUARD_DEFAULT_THRESHOLD = 350_000


def reload_guard_should_block(tokens: Optional[int], threshold: int) -> bool:
    """True iff the janitor's auto-emitted `[janitor-reload]` should be DEFERRED now.

    Pure predicate used by dispatch.py's `_phase_plugin_reload` to defer emitting the
    `[janitor-reload]` marker while the context is large (so the janitor does not nudge a
    costly reload at high context; the deferral resolves once the context shrinks). It was
    ALSO meant to back a UserPromptSubmit `reload-guard` hook that blocked a human-typed
    `/reload-plugins`, but that hook was REMOVED (TRDD-Z582IKIR follow-up): a built-in
    `/reload-plugins` fires no hook, so it can never be intercepted — the auto-defer is the
    only place the churn is actually prevented. (The function name is kept to avoid churning
    the dispatch call site + tests; it now governs only the deferral.)

    FAILS OPEN (returns False = allow the reload) whenever the context size is unknown
    (`tokens` is not an int — a read error, a fresh session with no transcript yet, a
    missing statusline snapshot, etc.) or the guard is disabled (`threshold <= 0`). A
    reload's whole point is to pick up fresh code; an unreadable context must never turn
    into a reload that can never happen.
    """
    if threshold <= 0:
        return False
    if not isinstance(tokens, int):
        return False
    return tokens >= threshold


# The compact ROUTINE spends ~this many tokens writing its OWN summary, so the auto-compact
# actually fires ~this far BEFORE CLAUDE_CODE_AUTO_COMPACT_WINDOW (user-measured, TRDD-TKNSTP82 C).
_DEFAULT_COMPACT_SUMMARY_OVERHEAD = 34000


def _coerce_env_int(raw: str | None, default: int) -> int:
    """Best-effort non-negative int from an env value; junk/absent → default (a typo in an
    env var must never crash a hook that reads it)."""
    if not raw:
        return default
    try:
        val = int(raw.strip())
    except (ValueError, AttributeError):
        return default
    return val if val >= 0 else default


@dataclass(frozen=True)
class CompactPrediction:
    """Predicted auto-compact geometry from CLAUDE_CODE_AUTO_COMPACT_WINDOW (TRDD-TKNSTP82 C).

    `auto_window` is the env-var value — the token count at which Claude Code force-compacts;
    `overhead` is the compact routine's own summary-write cost; `effective_compact_point =
    auto_window - overhead` is where compaction ACTUALLY fires; `tokens_until_compact =
    effective_compact_point - used` (goes negative once past the point).
    """

    auto_window: int
    overhead: int
    effective_compact_point: int
    tokens_until_compact: int


def predict_auto_compact(used_tokens: Optional[int], *, env: Mapping[str, str] | None = None) -> Optional[CompactPrediction]:
    """Predict the EXACT auto-compact point from the CLAUDE_CODE_AUTO_COMPACT_WINDOW env var.

    The user sets CLAUDE_CODE_AUTO_COMPACT_WINDOW to the token count at which Claude Code
    force-compacts (e.g. 700000 = compact at 70% of a 1M window — NOT a fixed %, so we must
    read the env var, not assume). The compact routine itself spends ~`overhead` tokens
    writing the summary, so compaction fires at `auto_window - overhead` (700000 − 34000 =
    666000). Returns the geometry, or None when the env var is unset/≤0 or `used_tokens` is
    unknown — callers then fall back to the %-of-window gauge (TRDD-TKNSTP82 C1). `overhead`
    is overridable via CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS.

    Pure (reads only the passed `env`, defaulting to os.environ) so it is unit-testable AND
    shared by the context-watchdog hook and `/janitor-token-report --live` — one predictor,
    so the two surfaces can never disagree (the A4 single-source-of-truth pattern).
    """
    e: Mapping[str, str] = os.environ if env is None else env
    auto_window = _coerce_env_int(e.get("CLAUDE_CODE_AUTO_COMPACT_WINDOW"), 0)
    if auto_window <= 0 or not isinstance(used_tokens, int):
        return None
    overhead = _coerce_env_int(e.get("CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS"), _DEFAULT_COMPACT_SUMMARY_OVERHEAD)
    effective = auto_window - overhead
    return CompactPrediction(
        auto_window=auto_window,
        overhead=overhead,
        effective_compact_point=effective,
        tokens_until_compact=effective - used_tokens,
    )


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


def append_exhaustion_event(path: str | os.PathLike[str], event: dict, *, max_events: int = 500) -> None:
    """Append ONE window-exhaustion snapshot (a turn-ending API error / rate-limit) as a
    JSON line, then cap the file to the last `max_events`. Best-effort — NEVER raises, so a
    logging glitch can never break the StopFailure hook's critical resume-cue capture. The
    MAX `roll_5h`/`roll_7d` across these events is the empirical window-cap lower bound
    ("log when the window is exhausted before the time" — TRDD-EDSFEQ5C)."""
    try:
        p = Path(path)
        with open(p, "a", encoding="utf-8") as f:
            f.write(json.dumps(event, separators=(",", ":")) + "\n")
        lines = [ln for ln in p.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        if len(lines) > max_events:
            tmp = p.with_name(p.name + ".tmp")
            tmp.write_text("\n".join(lines[-max_events:]) + "\n", encoding="utf-8")
            os.replace(tmp, p)
    except (OSError, ValueError, TypeError):
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


# TRDD-KI6OWCZT (janitor#246) — the minimum count of historical per-turn output samples
# before the output-advisory bar is allowed to fire at all. Below this there is no basis
# to call anything a spike, so the signal stays silent rather than fall back to a fixed
# number (the whole point of moving off a fixed threshold in the first place).
_MIN_OUTPUT_BASELINE_HISTORY = 8

# TRDD-KI6OWCZT follow-up — the advisory bar may never REACH the hard cap. The advisory
# exists to warn BEFORE the hard tier; a baseline-derived bar at or above `output_hard` does
# not tune the tier, it DELETES it — every trip lands on `hard` instead, so the "be terse /
# wrap up" nudge this card is about can never be delivered. MEASURED on this repo's own
# `token-meter.jsonl` (200 interactive turns): median 4638, MAD 3886 — the z-band alone was
# 39_202 against the 40_000 default hard cap, an 800-token-wide advisory window; a project
# with median 10_000 / MAD 7_500 scores 76_717 and closes it outright. Lowering
# `output_advisory_z` alone does NOT fix that second case (43_358 — still dead), so the bar
# must ALSO be clamped under the hard cap. Both levers are load-bearing; neither is enough.
_ADVISORY_HARD_CEILING = 0.75


def evaluate_turn_budget(
    usage: TurnUsage,
    *,
    output_hard: int,
    cache_creation_hard: int,
    output_baseline_history: list[int] | None = None,
    output_advisory_floor_pct: float = 95.0,
    output_advisory_z: float = 3.0,
    output_advisory_ratio: float = 4.0,
    ignore_cache_creation: bool = False,
) -> BudgetVerdict:
    """Classify the in-progress turn's cost into ok / advisory / hard from TWO signals:

    - **output** tokens — full-price agent work (long replies / many tool calls). The
      HARD cap is a fixed budget (a runaway is a runaway regardless of history); the
      ADVISORY tier is BASELINE-RELATIVE (TRDD-KI6OWCZT, janitor#246) — it fires only
      when `usage.output_tokens` clears a bar derived from `output_baseline_history`
      (the session's own recent per-turn output samples), reusing the existing robust
      statistics primitives (`token_baseline.robust_baseline` / `percentile`) rather
      than a fixed knob. The bar is the MAX of three gates — mirrors
      `token_baseline.classify_recent`'s combination, applied to a flat per-turn
      history instead of a bucketed time series:
        * `percentile(history, output_advisory_floor_pct)` — an absolute floor (never
          advise on a value that is unremarkable next to this session's own recent
          turns);
        * `median + output_advisory_z * 1.4826 * MAD` — the robust-z band (z is 3.0 here,
          NOT the 6.0 `classify_recent` uses: that one scores 5-minute BUCKET SUMS with no
          competing hard cap, and the constant does not transfer to per-turn output);
        * `median * output_advisory_ratio` — a multiplicative bar that stays
          meaningful when MAD≈0 (a flat history), where the z-band collapses to the
          median and a genuine multi-x spike would otherwise score 0.
      Fewer than `_MIN_OUTPUT_BASELINE_HISTORY` samples (including none at all) means
      there is no basis to judge a spike, so the advisory NEVER fires — not a silent
      fallback to a fixed number.
    - **cache_creation** tokens — a CACHE-MISS cache WRITE (the prompt prefix changed, so
      the new prefix is written to cache at a ~2× premium on the main agent's 1-hour cache
      TTL, ~1.25× on a subagent's 5-minute one). Only the HARD tier is checked here
      (janitor#246): the write is a SUNK cost by the time this turn is observed — a
      single-write advisory would report on something already done and undoable, which
      fails the "actionable now" bar, so that advisory branch was deleted outright. A
      SUSTAINED pattern crossing the hard cap is still worth interrupting for.

    `tier` is the worst tripped tier; `reasons` lists every tripped signal, hard first.
    Pure — no I/O, so it is unit-tested with plain ``TurnUsage`` values.

    ``ignore_cache_creation`` (TRDD-TKNSTP82 A1) — when True, the cache_creation signal
    is EXCLUDED from classification entirely: it neither contributes a reason nor raises
    the tier, even past its hard threshold. For the post-compact / cold-cache grace
    window, where a large one-time full-prefix re-cache write is EXPECTED (a billing
    artifact of the caching mechanism, not evidence of reckless behavior) — see
    ``pre-tool-token-budget.py``'s ``_in_compact_grace``. The output signal is entirely
    unaffected: sustained output still trips advisory/hard exactly as before, so a
    genuine runaway during the grace window is still caught.
    """
    reasons_hard: list[str] = []
    reasons_advisory: list[str] = []
    o = usage.output_tokens
    c = usage.cache_creation_input_tokens
    if output_hard > 0 and o >= output_hard:
        reasons_hard.append(f"output {o} ≥ hard {output_hard}")
    elif output_baseline_history is not None and len(output_baseline_history) >= _MIN_OUTPUT_BASELINE_HISTORY:
        median, mad = token_baseline.robust_baseline(output_baseline_history)
        threshold = max(
            float(token_baseline.percentile(output_baseline_history, output_advisory_floor_pct)),
            median + output_advisory_z * 1.4826 * mad,
            median * output_advisory_ratio,
        )
        # Keep the tier REACHABLE on ANY history — see `_ADVISORY_HARD_CEILING`. The three
        # gates above are unbounded, so on a real (heavy-tailed) history they routinely land
        # past `output_hard`, which silently removes the advisory tier instead of tuning it.
        if output_hard > 0:
            threshold = min(threshold, output_hard * _ADVISORY_HARD_CEILING)
        if threshold > 0 and o >= threshold:
            reasons_advisory.append(f"output {o} ≥ baseline {threshold:.0f} (median {median:.0f})")
    if not ignore_cache_creation:
        if cache_creation_hard > 0 and c >= cache_creation_hard:
            reasons_hard.append(f"cache-miss write {c} ≥ hard {cache_creation_hard}")
    if reasons_hard:
        return BudgetVerdict(tier="hard", reasons=reasons_hard + reasons_advisory)
    if reasons_advisory:
        return BudgetVerdict(tier="advisory", reasons=reasons_advisory)
    return BudgetVerdict(tier="ok", reasons=[])


# The rolling window the janitor's own heartbeat spend is reported over: one week.
SELF_COST_WINDOW_S = 7 * 86400


def heartbeat_cost_7d(records: list[dict], *, now: int) -> int:
    """THIS project's rolling-7d WEIGHTED cost of the janitor's OWN heartbeat fires. PURE.

    HEARTBEAT-ONLY: only ``heartbeat == True`` records count (a record MISSING the key is a
    heartbeat, same rule as ``beats`` in token_report.py). Summing the USER's interactive
    turns would blame them for their own work and make the janitor's line fire during it —
    the backwards mistake logged twice before.

    This used to be the input to a self-budget THROTTLE (``evaluate_self_budget``) that
    capped the cadence and then dropped the project into local maintenance. That actuation
    is gone (owner ruling 2026-07-31, *"never self-disable"*): cost pressure is reported,
    never acted on, because a janitor that quiets itself when it gets expensive is
    indistinguishable from a healthy one while doing nothing. The only consumer is now
    ``dispatch._phase_self_cost_alarm``, which prints the number and changes nothing.

    ``isinstance(r, dict)`` keeps this fail-open: ``load_log`` only yields dicts, but a
    stray non-dict is skipped rather than raised on (a garbage log reads as 0, never a
    crash). An empty list is 0."""
    beats = [r for r in records if isinstance(r, dict) and r.get("heartbeat", True)]
    return token_baseline.rolling_sum(beats, SELF_COST_WINDOW_S, now)


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
