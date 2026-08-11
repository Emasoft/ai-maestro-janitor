#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreToolUse hook — real-time token-spike + cache-miss guard (TRDD-KI24GR5Z).

Phase 3 of the heartbeat token meter (TRDD-a4e41e89). The Stop-hook meter MEASURES
per-turn cost (passive, after the turn); this hook turns that measurement into a
REAL-TIME CAP: on every tool call it reads the IN-PROGRESS turn's cumulative usage and,
when the turn SPIKES, nudges the agent to STOP the runaway before the cost compounds. It
watches the TWO cost signals the user named:

  * OUTPUT tokens — full-price agent work (long replies / many tool calls).
  * CACHE_CREATION tokens — a CACHE-MISS cache WRITE: the prompt prefix changed, so the
    new prefix is re-written to cache at ~1.25x premium. The cheap 0.1x cache_READ
    re-read is NOT billed here — only the miss-driven WRITE, which is what the user asked
    to catch ("any cache write caused by cache miss").

Two tiers (mirrors the context-watchdog `pre-tool-context-usage`):
  * advisory — `additionalContext` nudge naming the tripped signal(s); be terse / wrap up.
  * hard     — a STRONG stop nudge (end the step, `TaskStop` background subagents,
               `/compact`). AND, when the tool being called is a SUBAGENT SPAWNER
               (`Task`/`Agent`) and enforcement is opted in, `permissionDecision: deny`
               the spawn — subagents are the biggest token multiplier, so the guard stops
               MORE of them from starting mid-runaway.

DEFAULT-ON (opt-out): the user asked for an always-present monitor; the thresholds are
generous so it stays SILENT in normal use and only fires on a genuine spike. The DENY is
OPT-IN — advisory is the default, matching the user's word "nudge".

CONFIG (all `CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_*`; a HARD threshold of 0 disables that hard
cap — but note `TURN_OUTPUT_HARD` ALSO caps the baseline-relative output advisory, whose bar
is clamped under it (`token_meter._ADVISORY_HARD_CEILING`) so the advisory tier stays
reachable. So `TURN_OUTPUT_HARD=0` does NOT just disable the hard tier: it also removes that
clamp, and on a heavy-tailed history the unclamped bar can climb out of reach and silence the
advisory too. To keep both tiers, RAISE `TURN_OUTPUT_HARD` rather than zeroing it):
  * ENABLED                  — master switch, DEFAULT ON (false/0/no/off disables).
  * TURN_OUTPUT_HARD         — hard output budget (default 40000).
  * TURN_CACHE_CREATION_HARD — hard cache-miss-write budget (default 75000).
  * ENFORCE                  — DEFAULT OFF; when on, a `Task`/`Agent` spawn at the hard
                               tier is DENIED (not just advised).
  * REPEAT_S                 — issue #79: seconds a STEADY hard tier must persist before
                               its `additionalContext` nudge re-fires (default 600 = 10m).
                               Does NOT apply to advisory (which only nudges on a tier
                               CHANGE, never periodically) and does NOT gate the deny path.
                               <= 0 disables ALL throttling (every non-ok tier always nudges).

TRDD-KI6OWCZT (janitor#246) — there is no fixed OUTPUT-advisory knob any more. The
advisory tier is now BASELINE-RELATIVE: it compares the in-progress turn's output
against this project's own recent per-turn output history (`token-meter.jsonl`, the
Stop-hook meter's log), reusing `token_baseline`'s robust statistics (see
`token_meter.evaluate_turn_budget`). The CACHE-CREATION advisory tier was deleted
outright — a cache-miss write is a sunk cost by the time this hook fires, so a
single-write nudge is never actionable (only a SUSTAINED pattern past the HARD cap
still interrupts).

DATA: reuses `token_meter.tail_turn_usage` (the tested turn-boundary parser the Stop-hook
meter uses) + `token_meter.evaluate_turn_budget` (a pure decision fn), plus a BOUNDED TAIL read
of the meter's own `token-meter.jsonl` for the historical per-turn output samples. No new
accounting.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import time

import state  # noqa: E402  # atomic_write — the tier-transition state file (issue #79)
import token_meter  # noqa: E402

_DEFAULT_TURN_OUTPUT_HARD = 40_000
_DEFAULT_TURN_CACHE_CREATION_HARD = 75_000
# TRDD-KI6OWCZT — recent-only: the session's OWN RECENT baseline, not its all-time history.
_MAX_OUTPUT_BASELINE_SAMPLES = 200
# How much of the meter log to read for that baseline. This hook runs on EVERY tool call in
# EVERY session, so parsing the WHOLE file (up to `trim_log`'s 1 MB cap — measured 412 KB /
# 3147 records on this repo) per call is pure waste when only the last
# `_MAX_OUTPUT_BASELINE_SAMPLES` records are ever used. 64 KB holds ~500 records at the ~130
# bytes each `as_record` emits.
#
# But those ~500 are ALL records, and the baseline counts only the INTERACTIVE ones: the log
# is dominated by the ~5-minute HEARTBEAT turns (measured on this repo's own log: the 64 KB
# tail = 480 records, of which only 118 are interactive). So a fixed 64 KB window never
# reaches the 200-sample target even here, and on a project that is armed but worked in only
# occasionally it can hold FEWER than `token_meter._MIN_OUTPUT_BASELINE_HISTORY` interactive
# records — which silently kills the advisory tier outright. Hence the window ESCALATES: the
# cheap 64 KB read is tried first and is the only one paid in the common case; it grows only
# while the interactive samples are still short of the target and the file has more to give.
# The second (and last) window is `trim_log`'s own 1 MB cap — i.e. the whole log — so the
# worst case is ONE extra full read, and only on a log so heartbeat-dominated that the
# alternative is a permanently dead advisory tier.
_BASELINE_TAIL_WINDOWS = (64 * 1024, 1_024 * 1024)
# TRDD-TKNSTP82 A2 — window (seconds) after a compaction during which cache_creation is
# EXPECTED to spike (the one-time full-prefix re-cache) and is therefore ignored by the
# classifier. A bit more generous than the ~5-min heartbeat cadence that clears the
# resume-after-compact.ts flag, so a slow heartbeat tick never leaves a gap. 0 disables
# (restores unconditional cache_creation classification).
_DEFAULT_COMPACT_GRACE_S = 600

# The tools that SPAWN a subagent — the biggest token multiplier. `Task` is Claude Code's
# built-in; `Agent` is the same capability in the AI-Maestro harness. A hard-tier spawn of
# either is what ENFORCE denies.
_SPAWNER_TOOLS = frozenset({"Task", "Agent"})


# issue #79 — throttle to STATE TRANSITIONS instead of a time-windowed repeat-suppression.
#
# TRDD-4MMXTJFB (a repeat-suppression keyed on `tier:signal-set`, 180s) and TRDD-K1RJUYGK
# (raised the window to 1800s, fixed a fail-open bug and an A/B-alternation bypass) both
# reduced injection VOLUME but kept periodically RE-nudging a steady ADVISORY tier every
# window — agentlensPro's raw-body measurement in issue #79 (opened 2 days after K1RJUYGK
# shipped) still classified HOOK_INJECTION as the #2 cache-break cause, ~25.6% of wasted
# cache_creation. The remaining waste was exactly those steady-state re-nudges: an
# `additionalContext` block is not free just because its TEXT is byte-stable (TRDD-YRPUSIFY
# tried that and the data falsified it) — Claude Code strips it retroactively regardless of
# content, and the strip mutates the cached prefix.
#
# The fix: persist the LAST COMPUTED tier (not "last emitted", so an "ok" tier is recorded
# too — see `_track_tier`) and emit an advisory ONLY on a genuine tier change. The ADVISORY
# tier never periodically re-nudges on its own now (that's the behavior change from
# K1RJUYGK's uniform 1800s window). The HARD tier still gets a periodic re-nudge — a
# sustained runaway is worth reminding about — but on a shorter, HARD-only interval: default
# 10 minutes (600s), down from the old 30-minute window that used to also cover advisory.
_DEFAULT_HARD_RENUDGE_S = 600


def _last_tier_path(project_dir: str) -> Path:
    return Path(project_dir) / ".janitor" / "state" / "token-budget-last-tier.txt"


def _read_last_tier(project_dir: str) -> tuple[str, int]:
    """The (tier, epoch) persisted by the previous call, or ("", 0) when absent/corrupt.

    Read failures resolve to "never seen before" (tier ""), which — combined with
    `_track_tier`'s fail-CLOSED behavior on a missing `project_dir` — means a corrupt or
    unreadable stamp can only ever cause an EXTRA transition-emit, never suppress a real
    one; the opposite direction (silently swallowing a genuine escalation) is the one this
    hook must never risk.
    """
    try:
        raw = _last_tier_path(project_dir).read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return "", 0
    tier, _, ts_raw = raw.partition(" ")
    try:
        return tier, int(ts_raw)
    except ValueError:
        return "", 0


def _write_last_tier(project_dir: str, tier: str, now: int) -> None:
    """Best-effort persist via the shared atomic-write helper. A failed write just means
    the NEXT call re-derives the transition from a stale tier — worst case one extra
    emission, never a suppressed real one (see `_read_last_tier`)."""
    try:
        state.atomic_write(_last_tier_path(project_dir), f"{tier} {now}\n")
    except OSError:
        pass


def _track_tier(tier: str, project_dir: str, now: int, hard_renudge_s: int) -> bool:
    """Unconditional per-call bookkeeping (issue #79). Called ONCE per invocation for
    every computed `tier` (including "ok"), regardless of whether it ends up producing a
    deny or an additionalContext — so an "ok" observation is always recorded, which is
    what makes a LATER ok->advisory climb detectable as a genuine transition rather than a
    stale replay of whatever tier was last observed.

    Returns True iff THIS call is a "fresh signal" worth an additionalContext nudge:
      * the tier CHANGED since the last observed call (ok<->advisory<->hard, either
        direction) — always fresh, except "ok" itself never nudges; or
      * the tier is steadily "hard" and >= `hard_renudge_s` seconds have passed since the
        last fresh signal — a sustained runaway is worth periodically re-flagging.
    Any other case (steady ok, steady advisory, steady hard inside its renudge window) is
    NOT fresh — the hook stays silent, which is the whole point of issue #79: a steady
    tier no longer re-injects an `additionalContext` block on every tool call.

    `hard_renudge_s <= 0` is the documented full opt-out (matches the pre-issue-#79
    contract of the env var it reads from): every non-ok tier is always fresh and nothing
    is persisted, restoring the always-nudge behavior. Missing `project_dir` fails CLOSED
    (not fresh) — mirrors TRDD-K1RJUYGK: an unbounded per-call injection is worse than an
    occasional missed reminder, and the hard-tier `deny` (a decision field, never
    stripped) remains the real backstop for the case that matters most.
    """
    if hard_renudge_s <= 0:
        return tier != "ok"
    if not project_dir:
        return False
    last_tier, last_ts = _read_last_tier(project_dir)
    if tier != last_tier:
        _write_last_tier(project_dir, tier, now)
        return tier != "ok"
    if tier == "hard" and (now - last_ts) >= hard_renudge_s:
        _write_last_tier(project_dir, tier, now)
        return True
    return False


def _enabled(raw: str | None) -> bool:
    """DEFAULT-ON: unset/empty → True; explicit false/0/no/off → False."""
    if raw is None or raw.strip() == "":
        return True
    return raw.strip().lower() not in ("false", "0", "no", "off")


def _optin(raw: str | None) -> bool:
    """DEFAULT-OFF: only an explicit truthy value enables it."""
    if not raw:
        return False
    return raw.strip().lower() not in ("false", "0", "no", "off", "")


def _coerce_int(raw: str | None, default: int) -> int:
    """Best-effort non-negative int; junk → default (a typo must never crash a hook).

    Delegates to the shared parser (one source of truth) so a knob set the way Claude
    Code documents its own int env vars — `1e6`, `64_000` (CC 2.1.208/2.1.211) — is
    honored here too, not silently reverted to the default."""
    if not raw:
        return default
    parsed = state.parse_nonneg_int(raw.strip())
    return parsed if parsed is not None else default


def _bucket_tokens(n: int) -> str:
    """Floor `n` to the nearest 10k and render it as a cache-STABLE label.

    TRDD-YRPUSIFY (cache-stability): this hook injects its nudge text into model
    context on EVERY tool call. A raw per-call token count ("output 43053") makes each
    injection a unique string that can never share the prompt cache and compounds
    across a session. Flooring to a 10k bucket collapses a whole band of raw counts to
    ONE label ("~40k"), so two turns in the same spike band emit byte-identical text
    and stay cache-shareable. Pure + deterministic (unit-tested): same bucket → same
    string, always. `~1.3M` for >=1M, `~40k` otherwise, `~0k` for <10k.
    """
    if n < 0:
        n = 0
    b = (n // 10_000) * 10_000
    if b >= 1_000_000:
        return f"~{b / 1_000_000:.1f}M"
    return f"~{b // 1_000}k"


def _resume_after_compact_ts_path(project_dir: str) -> Path:
    return Path(project_dir) / ".janitor" / "state" / "resume-after-compact.ts"


def _in_compact_grace(project_dir: str, now: int, grace_s: int) -> bool:
    """True iff `post-compact-resume.py` wrote `resume-after-compact.ts` within the last
    `grace_s` seconds — the window where a large `cache_creation` is EXPECTED (the
    one-time full-prefix re-cache after a compaction), not a runaway signal.

    `project_dir` empty (no `CLAUDE_PROJECT_DIR` and no payload `cwd`) or `grace_s <= 0`
    → always False (never silently resolve a relative path from the process cwd — that
    would be non-deterministic depending on where the hook happens to be invoked from).
    Mirrors `pre-tool-context-usage.py`'s `_recently_compacted` dedupe pattern.
    """
    if not project_dir or grace_s <= 0:
        return False
    try:
        ts = int(_resume_after_compact_ts_path(project_dir).read_text(encoding="utf-8").strip() or "0")
    except (FileNotFoundError, OSError, ValueError):
        return False
    return 0 <= (now - ts) < grace_s


def _token_meter_log_path(project_dir: str) -> Path:
    return Path(project_dir) / ".janitor" / "state" / "token-meter.jsonl"


def _load_output_baseline(project_dir: str) -> list[int]:
    """This project's own recent INTERACTIVE (non-heartbeat) per-turn output-token
    counts, oldest first — the baseline `evaluate_turn_budget` measures a live turn's
    output spike against (TRDD-KI6OWCZT, janitor#246).

    Heartbeat turns are EXCLUDED: their near-zero output would collapse the baseline
    toward zero and make every real interactive turn look like a spike. No project
    dir / no log yet / read failure all resolve to `[]` — `evaluate_turn_budget`
    treats that as "no basis to judge", so the advisory stays silent rather than
    guess (same correct-by-omission stance as the rest of this hook), never a
    fallback to a fixed number.

    Reads only a bounded TAIL (see `_BASELINE_TAIL_WINDOWS`) rather than going through
    `token_meter.load_log`, for two reasons — both of which that helper fails HERE, on a
    per-tool-call hot path it was never written for:
      * COST — `load_log` parses the entire file on every single tool call to use at most
        the last `_MAX_OUTPUT_BASELINE_SAMPLES` records.
      * SAFETY — `load_log` guards only `json.loads`: its `p.open()` and its STRICT-utf-8
        line iteration are unguarded, so an unreadable log (permissions, I/O error) or one
        torn mid-append by a concurrent writer raises straight through a hook that must
        never crash. `trim_log` already decodes with `errors="replace"` precisely because
        it expects such bytes. Every OTHER file read in this hook catches OSError; this one
        must too. A truncated first line in the window is dropped by its own json-parse
        failure, exactly as `token_meter._read_tail_lines` documents.
    """
    if not project_dir:
        return []
    p = _token_meter_log_path(project_dir)
    values: list[int] = []
    for window in _BASELINE_TAIL_WINDOWS:
        try:
            size = p.stat().st_size
            with p.open("rb") as f:
                if size > window:
                    f.seek(size - window)
                raw = f.read()
        except OSError:
            return []
        values = _parse_output_samples(raw)
        # Enough interactive samples, or the window already covered the whole file — a
        # bigger read cannot add anything, so stop paying for it.
        if len(values) >= _MAX_OUTPUT_BASELINE_SAMPLES or window >= size:
            break
    return values[-_MAX_OUTPUT_BASELINE_SAMPLES:]


def _parse_output_samples(raw: bytes) -> list[int]:
    """The `output` counts of the INTERACTIVE (non-heartbeat) records in a meter-log tail,
    oldest first. Pure. Negative counts are dropped along with unparseable ones: a
    hand-edited or torn record must never crash the hook, and must never drag the median
    (the whole baseline) below zero either."""
    values: list[int] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            rec = json.loads(s)
        except ValueError:
            continue  # partial first line of the tail window / non-JSON noise
        if not isinstance(rec, dict) or rec.get("heartbeat", True):
            continue
        try:
            v = int(rec.get("output", 0) or 0)
        except (TypeError, ValueError):
            continue  # a hand-edited / corrupt `output` must not crash the hook
        if v >= 0:
            values.append(v)
    return values


def _emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj))


def _context(line: str) -> dict:
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": line}}


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


_CACHE_MISS_NOTE = (
    "A cache-miss write happens once when the prompt prefix changes (an idle gap "
    ">5 min, or a recent compaction) and is billed at a TTL-tiered rate — ~1.25x for "
    "a 5-minute cache entry (subagents, usage-credit sessions), ~2x for a 1-hour entry "
    "(the default for a subscription's main-conversation turn) — a one-time WRITE "
    "cost, not standing context size. That write already happened and cannot be "
    "undone; see /janitor-token-report --live or the context-window % shown by the "
    "context watchdog if you suspect the context itself is bloated."
)


def _has_signal(reasons: list[str], prefix: str) -> bool:
    return any(r.startswith(prefix) for r in reasons)


def _response(
    verdict: "token_meter.BudgetVerdict",
    usage: "token_meter.TurnUsage",
    tool_name: str,
    enforce: bool,
) -> dict | None:
    """The hook payload for a budget `verdict`, or None when nothing to emit (tier ok).

    Pure (given the verdict + tool + enforce flag) so the deny-vs-nudge decision is
    unit-tested directly:
      * hard + a `Task`/`Agent` spawn + ENFORCE → deny the spawn (stop the multiplier).
      * hard otherwise → a strong stop nudge (TaskStop background subagents, /compact).
      * advisory → a soft be-terse/wrap-up nudge.

    TRDD-TKNSTP82 A3 — the two signals render DISTINCT text: a cache-miss-ONLY trip is a
    one-time cache-WRITE billing artifact (see `_CACHE_MISS_NOTE`), never a context-size
    problem, so it never recommends `/compact` (that would be circular — /compact is what
    caused the prefix rewrite in the first place, or would trigger another one). An
    output-driven trip keeps the `/compact` recommendation — it's legitimately correct
    there, since a compaction shrinks a bloated turn's future cost.
    """
    if verdict.tier == "ok":
        return None
    has_output = _has_signal(verdict.reasons, "output ")
    has_cache_miss = _has_signal(verdict.reasons, "cache-miss write")

    # TRDD-YRPUSIFY (cache-stability): build the signal text from BUCKETED usage + which
    # signals tripped — never from `verdict.reasons`, whose raw counts + exact thresholds
    # ("output 43053 ≥ hard 40000") vary every call and would make each injected nudge a
    # unique, non-cache-shareable string. The per-call span ("N msg / M tool call(s)") is
    # DROPPED entirely: it carries no advisory value and is pure per-call noise. What
    # remains is ONE canonical phrase per (signal-set, tier), byte-identical whenever the
    # turn sits in the same bucket band, so identical situations share the prompt cache.
    parts: list[str] = []
    if has_output:
        parts.append(f"output {_bucket_tokens(usage.output_tokens)}")
    if has_cache_miss:
        parts.append(f"cache-miss write {_bucket_tokens(usage.cache_creation_input_tokens)}")
    signals = "; ".join(parts)

    if verdict.tier == "hard":
        if enforce and tool_name in _SPAWNER_TOOLS:
            return _deny(f"[token-guard] STOP — token runaway ({signals}). Do NOT spawn another subagent (the biggest token multiplier). End this step, TaskStop any background subagents, and /compact before continuing. (Disable: CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENFORCE=false.)")
        if has_output:
            msg = f"⚠⚠ TOKEN RUNAWAY: this turn {signals}. STOP NOW — finish the current step, stop background subagents with TaskStop, and consider /compact or /janitor-compact-context. Sustained output burns subscription usage fastest. If bounded work remains, delegate it to a lean-worker subagent instead of continuing in this expensive turn."
            if has_cache_miss:
                msg += f" {_CACHE_MISS_NOTE}"
            return _context(msg)
        # cache-miss-only hard trip: NOT an output/context problem — see _CACHE_MISS_NOTE.
        # Still worth interrupting for (a runaway is a runaway) even though the write
        # itself is sunk cost — unlike the advisory tier below, this can still stop a
        # SUSTAINED pattern of repeated cache-miss writes from compounding further.
        return _context(f"⚠⚠ TOKEN RUNAWAY: this turn {signals}. {_CACHE_MISS_NOTE}")

    # advisory tier — TRDD-KI6OWCZT (janitor#246): OUTPUT is the ONLY signal that can
    # ever reach here now. `evaluate_turn_budget` never adds a cache-miss reason to
    # `reasons_advisory` any more (that branch was deleted outright — a single cache-
    # miss write is a sunk cost the moment this hook fires, so an advisory-tier nudge
    # about it is unactionable telemetry, not a gate). The HARD tier above still fires
    # on a SUSTAINED cache-miss pattern, which is worth interrupting for.
    return _context(f"⚠ Token spike: this turn {signals}. Be terse, wrap up the step, or compact — long output is billed at full price. Consider delegating remaining bounded work to a lean-worker subagent.")


def main() -> int:
    if not _enabled(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENABLED")):
        return 0

    try:
        raw = sys.stdin.read()
    except (OSError, ValueError):
        return 0
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        return 0

    transcript = str(payload.get("transcript_path", "") or "")
    if not transcript:
        return 0

    usage = token_meter.tail_turn_usage(transcript)
    if usage is None:
        # Turn boundary not in the tail window (or transcript unreadable) — stay silent
        # rather than guess (correctness-by-omission, same as the meter + context guard).
        return 0

    # TRDD-TKNSTP82 A2 — suppress the cache_creation signal for one grace window right
    # after a compaction, where a big one-time full-prefix re-cache write is EXPECTED
    # (not a runaway). project_dir mirrors pre-tool-context-usage.py's resolution order
    # (CLAUDE_PROJECT_DIR env, else the payload's cwd).
    project_dir = os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or str(payload.get("cwd", "") or "")
    grace_s = _coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_COMPACT_GRACE_S"),
        _DEFAULT_COMPACT_GRACE_S,
    )
    ignore_cache_creation = _in_compact_grace(project_dir, int(time.time()), grace_s)

    output_hard = _coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_OUTPUT_HARD"),
        _DEFAULT_TURN_OUTPUT_HARD,
    )
    # Skip the (per-tool-call) meter-log read whenever the history CANNOT change the
    # verdict: the hard cap already tripped, so `evaluate_turn_budget` never reaches its
    # baseline branch, or the turn has produced no output at all, which no positive bar can
    # ever clear. Behavior-identical, one fewer file read on the two commonest paths.
    baseline_can_matter = 0 < usage.output_tokens and not (output_hard > 0 and usage.output_tokens >= output_hard)
    verdict = token_meter.evaluate_turn_budget(
        usage,
        output_hard=output_hard,
        cache_creation_hard=_coerce_int(
            os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_CACHE_CREATION_HARD"),
            _DEFAULT_TURN_CACHE_CREATION_HARD,
        ),
        output_baseline_history=_load_output_baseline(project_dir) if baseline_can_matter else [],
        ignore_cache_creation=ignore_cache_creation,
    )
    # issue #79 — unconditional per-call tier bookkeeping, BEFORE building the response.
    # Must run for every tier (including "ok") so a later climb is a detectable transition
    # (see `_track_tier`), and must run whether the eventual response is a deny or an
    # additionalContext — the two are gated differently below.
    now_ts = int(time.time())
    hard_renudge_s = _coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_REPEAT_S"), _DEFAULT_HARD_RENUDGE_S)
    fresh_signal = _track_tier(verdict.tier, project_dir, now_ts, hard_renudge_s)

    resp = _response(
        verdict,
        usage,
        str(payload.get("tool_name", "") or ""),
        _optin(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENFORCE")),
    )
    if resp is not None:
        # ENFORCEMENT is UNCHANGED (issue #79 explicitly scopes the throttle to the
        # additionalContext channel only): a `deny` gates a real subagent spawn and must
        # ALWAYS fire when the verdict says so — it is a decision field, never an injected
        # transcript block, so it is never retroactively stripped and never re-bills the
        # cached prefix. Only the additionalContext nudge is gated on `fresh_signal`.
        hso = resp.get("hookSpecificOutput", {})
        if isinstance(hso, dict) and "additionalContext" in hso and not fresh_signal:
            # SILENCE — a steady tier (or a hard tier still inside its renudge window)
            # injects NOTHING. The signal is not lost: the transition nudge already rode
            # the transcript, and the hard-tier `deny` (when ENFORCE is on) is the
            # enforcement backstop regardless of this channel's state.
            return 0
        _emit(resp)
    return 0


if __name__ == "__main__":
    # Bare main() — side effects inside it so the module is import-safe (no
    # module-scope sys.exit), matching the other janitor hooks.
    main()
