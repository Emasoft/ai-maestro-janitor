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

CONFIG (all `CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_*`; any threshold of 0 disables that check):
  * ENABLED                  — master switch, DEFAULT ON (false/0/no/off disables).
  * TURN_OUTPUT              — advisory output budget (default 10000).
  * TURN_OUTPUT_HARD         — hard output budget (default 40000).
  * TURN_CACHE_CREATION      — advisory cache-miss-write budget (default 25000).
  * TURN_CACHE_CREATION_HARD — hard cache-miss-write budget (default 75000).
  * ENFORCE                  — DEFAULT OFF; when on, a `Task`/`Agent` spawn at the hard
                               tier is DENIED (not just advised).

DATA: reuses `token_meter.tail_turn_usage` (the tested turn-boundary parser the Stop-hook
meter uses) + `token_meter.evaluate_turn_budget` (a pure decision fn). No new accounting.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import time

import token_meter  # noqa: E402

_DEFAULT_TURN_OUTPUT = 10_000
_DEFAULT_TURN_OUTPUT_HARD = 40_000
_DEFAULT_TURN_CACHE_CREATION = 25_000
_DEFAULT_TURN_CACHE_CREATION_HARD = 75_000
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


# TRDD-4MMXTJFB — repeat-nudge suppression window (seconds). While a turn stays in the
# SAME (tier, signal-set) state, the full nudge paragraph is injected ONCE; repeats within
# the window are silenced (advisory) or shrunk to one stable line (hard). Every injected
# nudge rides the transcript and is re-read by all later turns, so re-injecting the same
# ~120-token paragraph on EVERY tool call is exactly the context bloat this hook polices.
# TRDD-K1RJUYGK raised this from 180s. 3 minutes sounds conservative but is not: a long
# session re-injects the nudge every 3 minutes for hours, and EVERY injection seeds a fresh
# system-reminder block that Claude Code later STRIPS retroactively — and it is the strip,
# not the text, that mutates the cached prefix and re-bills everything after it. A 30-minute
# floor cuts the injection count ~10x while still re-warning a genuinely runaway session.
# Bucketing the text (TRDD-YRPUSIFY) does NOT substitute for this: a stripped block costs the
# same no matter what it said.
#
# NOTE: an earlier version of this comment blamed the janitor's two no-matcher PreToolUse
# hooks for a measured "#1 cache-break cause on the machine ($23.05)". That attribution is
# RETRACTED (see the TRDD) — agentlensPro's `hook: <Event>` label names the event BOUNDARY a
# changed block was observed at, not its emitter. The mechanism is real and bounding the
# injection is right; the blame was not established. Do not restore a $ figure here.
_DEFAULT_REPEAT_S = 1800

# Cap the per-key stamp file. The key space is (tier x signal-set) — a handful of values —
# so this only trims genuinely stale entries.
_STAMP_MAX_KEYS = 32


def _repeat_suppressed(key: str, now: int, project_dir: str, window_s: int) -> bool:
    """True iff this nudge `key` was already emitted < `window_s` ago (and stamp the
    emission otherwise). The stamp lives beside the other per-session state files.

    Keeps a stamp PER KEY, not a single last-key stamp. The original stored one
    `"<key> <ts>"` line, so it only ever suppressed a CONSECUTIVE repeat: the key is
    `tier:signal-set` (e.g. `advisory:10`, `hard:11`) and it flips between turns as the
    in-progress turn's output/cache-miss signals change. Any alternation —
    advisory → hard → advisory — saw `prev_key != key` each time and re-emitted, so the
    window suppressed nothing in exactly the runaway session it is meant to police.

    Fails CLOSED (returns True → SUPPRESS) whenever the stamp cannot be read or written,
    AND when there is no project dir to stamp into. TRDD-K1RJUYGK inverted this: it used to
    fail OPEN ("never suppress on doubt"), which is exactly backwards now that INJECTING is
    known to be the expensive act. Not being able to remember that we warned meant warning on
    EVERY tool call — the worst possible outcome. Silence is the safe failure: the hard-tier
    `deny` (a decision field, not an injected block) remains the backstop.

    `window_s <= 0` is the one deliberate fail-OPEN: it is the documented way to DISABLE
    repeat-suppression by config, and a config that says "never suppress" must be obeyed.
    """
    if window_s <= 0:
        return False  # explicitly configured OFF — not a doubt, an instruction
    if not project_dir:
        return True  # nowhere to stamp → cannot bound repeats → stay silent (fail closed)
    stamp = Path(project_dir) / ".janitor" / "state" / "token-budget-last-nudge.txt"
    try:
        raw = stamp.read_text(encoding="utf-8")
    except FileNotFoundError:
        raw = ""
    except OSError:
        return True  # cannot read → cannot bound → stay silent
    seen: dict[str, int] = {}
    for line in raw.splitlines():
        try:
            k, ts = line.rsplit(" ", 1)
            seen[k] = int(ts)
        except ValueError:
            continue  # corrupt line — drop it, treat as never emitted
    prev = seen.get(key)
    if prev is not None and 0 <= now - prev < window_s:
        return True
    seen[key] = now
    # Cap the file: keep only the most recent keys. The key space is tiny (tier x
    # signal-set), so this only ever trims genuinely stale entries.
    keep = sorted(seen.items(), key=lambda kv: kv[1])[-_STAMP_MAX_KEYS:]
    try:
        stamp.parent.mkdir(parents=True, exist_ok=True)
        tmp = stamp.with_suffix(f".tmp.{os.getpid()}")
        tmp.write_text("".join(f"{k} {ts}\n" for k, ts in keep), encoding="utf-8")
        os.replace(tmp, stamp)
    except OSError:
        return True  # cannot record the emission → cannot bound repeats → stay silent
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
    """Best-effort non-negative int; junk → default (a typo must never crash a hook)."""
    if not raw:
        return default
    try:
        val = int(raw.strip())
    except (ValueError, AttributeError):
        return default
    return val if val >= 0 else default


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
    ">5 min, or a recent compaction) and is billed ~1.25x — a one-time WRITE cost, not "
    "standing context size. That write already happened and cannot be undone; see "
    "/janitor-token-report --live or the context-window % shown by the context watchdog "
    "if you suspect the context itself is bloated."
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
            msg = f"⚠⚠ TOKEN RUNAWAY: this turn {signals}. STOP NOW — finish the current step, stop background subagents with TaskStop, and consider /compact or /janitor-compact-context. Sustained output burns subscription usage fastest."
            if has_cache_miss:
                msg += f" {_CACHE_MISS_NOTE}"
            return _context(msg)
        # cache-miss-only hard trip: NOT an output/context problem — see _CACHE_MISS_NOTE.
        return _context(f"⚠⚠ TOKEN RUNAWAY: this turn {signals}. {_CACHE_MISS_NOTE}")

    # advisory tier
    if has_output:
        msg = f"⚠ Token spike: this turn {signals}. Be terse, wrap up the step, or compact — long output is billed at full price."
        if has_cache_miss:
            msg += f" {_CACHE_MISS_NOTE}"
        return _context(msg)
    return _context(f"⚠ Token spike: this turn {signals}. {_CACHE_MISS_NOTE}")


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

    verdict = token_meter.evaluate_turn_budget(
        usage,
        output_advisory=_coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_OUTPUT"), _DEFAULT_TURN_OUTPUT),
        output_hard=_coerce_int(
            os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_OUTPUT_HARD"),
            _DEFAULT_TURN_OUTPUT_HARD,
        ),
        cache_creation_advisory=_coerce_int(
            os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_CACHE_CREATION"),
            _DEFAULT_TURN_CACHE_CREATION,
        ),
        cache_creation_hard=_coerce_int(
            os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_TURN_CACHE_CREATION_HARD"),
            _DEFAULT_TURN_CACHE_CREATION_HARD,
        ),
        ignore_cache_creation=ignore_cache_creation,
    )
    resp = _response(
        verdict,
        usage,
        str(payload.get("tool_name", "") or ""),
        _optin(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_ENFORCE")),
    )
    if resp is not None:
        # TRDD-4MMXTJFB — repeat-nudge suppression: only additionalContext nudges are
        # deduped (a deny must ALWAYS fire — it gates a real spawn). Key = tier +
        # signal-set (NOT the bucketed counts, which drift as the turn grows — the point
        # is "same situation", not "same numbers").
        hso = resp.get("hookSpecificOutput", {})
        if isinstance(hso, dict) and "additionalContext" in hso:
            key = f"{verdict.tier}:{int(_has_signal(verdict.reasons, 'output '))}{int(_has_signal(verdict.reasons, 'cache-miss write'))}"
            window_s = _coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_BUDGET_REPEAT_S"), _DEFAULT_REPEAT_S)
            if _repeat_suppressed(key, int(time.time()), project_dir, window_s):
                # SILENCE — emit nothing, for the hard tier too (TRDD-K1RJUYGK).
                #
                # This path used to re-emit a short `additionalContext` reminder on every
                # hard-tier tool call, reasoning that a "tiny, byte-stable" block was cheap.
                # That is exactly the TRDD-YRPUSIFY argument this TRDD falsified: the cost is
                # not the block's SIZE or the stability of its TEXT, it is that Claude Code
                # later STRIPS the block retroactively, in place — and that mutation lands
                # inside the cached PREFIX, re-billing every token after it. A stripped block
                # costs the same whatever it said. So the suppression path was itself
                # injecting on every call in the hard tier — the hook's own hot path, in the
                # exact runaway session it exists to police.
                #
                # The signal is not lost: the first full nudge already rides the transcript,
                # and the hard-tier `deny` of a Task/Agent spawn (a decision field, NOT a
                # strippable block) is the enforcement backstop.
                return 0
        _emit(resp)
    return 0


if __name__ == "__main__":
    # Bare main() — side effects inside it so the module is import-safe (no
    # module-scope sys.exit), matching the other janitor hooks.
    main()
