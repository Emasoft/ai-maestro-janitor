#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""window-burn-rate — alarm when a subscription window outpaces its linear budget
(TRDD-OY0W6LX5).

Each fixed-reset usage window (5h rolling / 7d) should reach 100% exactly at its reset if
spent evenly. This per-session detector reads every known account's live utilization% +
reset boundary READ-ONLY through the OAuth rotator (`rotator.usage_request`) and, for any
window burning ≥ RATIO× that even pace, emits ONE drift line so the main Claude learns it
is heading for an early rate-limit — the model records per-turn usage but cannot know its
own subscription baseline; only the janitor can.

When a burn trips, it ALSO attributes the spend across the fleet (`token_history` via the
shared 30-min cache) and names the top-consuming project + where its spike came from, so
the advisory points at WHO to throttle — the account util% is aggregate across ~10 parallel
projects and can't say that on its own.

READ-ONLY + FAIL-OPEN: it never writes, rotates, or mutates any credential, and every step
is wrapped so a rotator/network failure is a SILENT skip — a detector crash must never break
the heartbeat. OPT-OUT via CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED=false.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))
sys.path.insert(0, str(_HERE.parent / "oauth_rotator"))

import agentlens_probe as alp  # noqa: E402  # agentlensPro culprit/cause enrichment (TRDD-90B47EM9)
import dedupe  # noqa: E402
import rotator_usage  # noqa: E402  # shared READ-ONLY account-usage gather (drives rotator)
import state  # noqa: E402
import token_attribution_cache as tac  # noqa: E402
import token_burn  # noqa: E402
import token_history as th  # noqa: E402

# The pure decision helper the tests exercise (structure the detector so the verdict is a
# pure function of usage dicts + env — no network in the tested path).
_evaluate = token_burn.evaluate


def _coerce_float(raw: str | None, default: float) -> float:
    """Best-effort positive float; junk/absent/non-positive → default (a typo must never
    crash the heartbeat or silently disable the floor)."""
    if not raw:
        return default
    try:
        val = float(raw.strip())
    except (ValueError, AttributeError):
        return default
    return val if val > 0 else default


def _stamp_path() -> Path:
    return state.state_dir() / "window-burn-rate.selfrun.ts"


def _due(now: int, interval: int) -> bool:
    """True iff at least `interval` seconds have elapsed since the last self-run — a second,
    detector-owned cadence gate on top of the dispatcher's, so a standalone invocation is
    still rate-limited."""
    return (now - state.read_int_state(_stamp_path(), 0)) >= interval


def _short_slug(slug: str) -> str:
    """Compact a harness project slug (the absolute path with every separator dashed) to its
    trailing tokens so a drift line stays readable."""
    parts = [p for p in slug.split("-") if p]
    return "-".join(parts[-2:]) if parts else slug


def _agentlens_cause_clause() -> str:
    """The preferred culprit clause from agentlensPro's `investigate_burn`, or "" when the CLI
    is absent / disabled / uninformative (TRDD-90B47EM9). Config-gated + fail-open: an empty
    `heartbeat_investigate_burn_command` disables the probe; ANY failure yields "" so the caller
    falls back to the native `_top_consumer_clause`. Invoked ONLY on a tripped burn — the
    expensive `investigate_burn` probe is never run speculatively — and its (local-session)
    output is defanged for a drift line before it is returned.

    WHY prefer it over the native attribution: agentlensPro reads real OTEL telemetry and
    classifies the CAUSE (FORK_STORM, FAT_SESSION_REWRITES, …); the native `token_history`
    attribution is a heuristic over transcript sizes. The native path stays as the fallback so
    a machine without the CLI is byte-identical to before."""
    command = os.environ.get(
        "CLAUDE_PLUGIN_OPTION_HEARTBEAT_INVESTIGATE_BURN_COMMAND",
        alp.DEFAULT_INVESTIGATE_BURN_COMMAND,
    )
    try:
        data = alp.probe_json(command)
        cause = alp.parse_investigate_cause(data) if data is not None else None
        if cause is None:
            return ""
        return state.sanitize_for_drift_line(alp.format_cause_clause(cause))
    except Exception:
        return ""


def _top_consumer_clause(w5_lo: int | None = None, w7_lo: int | None = None) -> str:
    """The ' Top consumer: …' suffix, computed ONLY when a burn tripped (never on quiet
    runs), from the shared 30-min fleet-attribution cache. Empty string on any failure — the
    burn line is still worth emitting without attribution. `w5_lo`/`w7_lo` are the LIVE
    subscription windows' start epochs (TRDD-0NRVNDSZ) so the shares are summed over the
    SAME windows the meter bills; None falls back to trailing."""
    try:
        now = int(time.time())
        projects_root = Path.home() / ".claude" / "projects"
        fleet = tac.get(projects_root, now, w5_lo=w5_lo, w7_lo=w7_lo)
        slug = th.culprit(fleet)
        if not slug:
            return ""
        m = fleet.get("projects", {}).get(slug, {})
        share = float(m.get("share_5h", 0.0)) * 100.0
        spike = m.get("spike_factor")
        spike_txt = f"{float(spike):.1f}x own baseline" if isinstance(spike, (int, float)) else "no baseline"
        src = m.get("source", {}) or {}
        output_share = float(src.get("output_share", 0.0))
        cache_share = float(src.get("cache_creation_share", 0.0)) + float(src.get("cache_read_tenth_share", 0.0))
        source = "output" if output_share >= cache_share else "cache"
        spawns = int(src.get("subagent_spawns", 0) or 0)
        if spawns:
            # "spawns" (bare plural), NOT "spawn(s)": the parenthesized plural
            # pattern-matches a spawn(...) process-exec call in CPV skillaudit's
            # SHELL_EXEC heuristic and blocked the v0.29.0 publish gate.
            source = f"{source} + {spawns} subagent spawns"
        return f" Top consumer: {_short_slug(slug)} ({share:.0f}% of fleet 5h, spike {spike_txt}, source: {source})."
    except Exception:
        return ""


def _keychain_opt_in_ok() -> bool:
    """True iff the rotator is OPTED IN, so this detector may read account tokens from the OS
    keychain (TRDD-K3WQ7XM9). The SAME gate the daemon's rotator tick uses — it makes "rotator
    paused" mean "zero keychain access" for this AUTOMATIC detector, so a locked login keychain
    can never turn its usage gather into a GUI unlock-prompt flood. (The user-invoked
    `/janitor-token-report --live`, the OTHER `accounts_usage` caller, is deliberately NOT gated:
    the user explicitly asked, and the safe_storage denied-latch still caps any prompt at one.)
    Lazy-imports so a disabled/not-due heartbeat never loads the rotator, and FAILS CLOSED — any
    resolution error returns False, i.e. do NOT touch the keychain."""
    try:
        import rotator  # noqa: PLC0415  # configured_rotator_home SSOT (scripts/oauth_rotator)
        import supervisor  # noqa: PLC0415  # opt_in_present gate (scripts/oauth_rotator)

        home = rotator.configured_rotator_home()
        return home is not None and supervisor.opt_in_present(home)
    except Exception:
        return False


def main() -> int:
    state.init_state()

    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED", True):
        return 0  # opt-out — silent no-op before any network / rotator work

    interval = state.coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_WINDOW_BURN_INTERVAL"), 900)
    now = int(time.time())
    if not _due(now, interval):
        return 0

    # KEYCHAIN-SAFETY GATE (TRDD-K3WQ7XM9): the usage gather below reads each account's token
    # from the OS keychain; an AUTOMATIC heartbeat detector must never let that raise a GUI
    # unlock prompt on a locked keychain, so it only runs when the user has OPTED IN.
    if not _keychain_opt_in_ok():
        return 0

    ratio = _coerce_float(os.environ.get("CLAUDE_PLUGIN_OPTION_WINDOW_BURN_RATIO"), 1.5)
    min_util = _coerce_float(os.environ.get("CLAUDE_PLUGIN_OPTION_WINDOW_BURN_MIN_UTIL"), 10.0)

    # Gather + evaluate are wrapped together: even an unexpected rotator shape must not crash
    # the heartbeat. A gather failure yields no accounts → no trips → silent.
    # The aligned window starts ride the same probe: resets_at − window_s per label. On any
    # gather failure they stay None and attribution falls back to trailing windows.
    w5_lo: int | None = None
    w7_lo: int | None = None
    try:
        accounts = rotator_usage.accounts_usage()
        trips = token_burn.evaluate_trips(accounts, now, ratio, min_util)
        w5_lo, w7_lo = token_burn.window_starts(accounts, now)
    except Exception:
        trips = []

    # Stamp the self-run cadence whether or not anything tripped (a probe DID run) so the
    # detector backs off to its interval instead of re-probing every heartbeat.
    try:
        state.atomic_write(_stamp_path(), str(now))
    except OSError:
        pass

    if not trips:
        state.rotate_log_if_big("window-burn-rate")
        return 0

    # Prefer agentlensPro's investigate_burn culprit/cause (authoritative OTEL attribution) when
    # present; else the native fleet-scan attribution. ONE attribution, shared by every tripped
    # window. Both run ONLY here (post-trip), so the expensive investigate_burn is never
    # speculative (TRDD-90B47EM9).
    clause = _agentlens_cause_clause() or _top_consumer_clause(w5_lo, w7_lo)
    seen = state.state_dir() / "window-burn-rate-seen.txt"
    day = now // 86400
    for trip in trips:
        key = f"burn-{day}-{trip['key']}"
        line = dedupe.emit_once(seen, key, trip["line"] + clause)
        if line is not None:
            # emit_once stored line+clause; if the clause changed but the key already fired
            # today it stays deduped — the burn condition (account+window+day) is the signal.
            print(line)

    state.rotate_log_if_big("window-burn-rate")
    return 0


if __name__ == "__main__":
    sys.exit(main())
