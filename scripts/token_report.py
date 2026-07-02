#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for /janitor-token-report (TRDD-a4e41e89, Phase 1).

Reads the per-heartbeat token log written by the on-stop-token-meter hook
(`$PROJECT/.janitor/state/token-meter.jsonl`) and prints recent per-fire costs
plus distribution stats (mean / p50 / p95 / max) so spikes or a too-high
average are visible. `--json` for scripting.

Cost view: `output` tokens are the headline (full-price, the clearest driver of
agent work); `input` + `cache_creation` are full/premium price too; `cache_read`
is the cheap (~0.1x) context re-read, shown for context but not the alarm metric.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

# A heartbeat whose output exceeds this is a "spike" worth the user's eye; also
# flagged relative to the run's own p95. Env-overridable.
import memory_scopes  # noqa: E402
import rotator_usage  # noqa: E402
import token_attribution_cache as tac  # noqa: E402
import token_baseline as tb  # noqa: E402
import token_burn  # noqa: E402
import token_graph  # noqa: E402
import token_history as th  # noqa: E402
import token_meter  # noqa: E402

_SPIKE_OUTPUT = int(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_SPIKE_OUTPUT", "4000"))
_HIGH_MEAN_OUTPUT = int(os.environ.get("CLAUDE_PLUGIN_OPTION_TOKEN_HIGH_MEAN_OUTPUT", "2500"))

_5H = 5 * 3600
_7D = 7 * 86400


def _fmt_k(n: float) -> str:
    """Compact big-number format: 1234 → '1.2k', 5_000_000 → '5.0M'."""
    n = float(n)
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.1f}k"
    return f"{n:.0f}"


def _window_metrics(records: list[dict], now: int, util5h: float | None, util7d: float | None, events: list[dict]) -> dict:
    """Rolling 5h/7d weighted sums + per-min rates, the busiest observed windows (cap
    lower bounds), the per-5-min robust baseline, the empirical cap from logged
    window-exhaustion events, and — when a live utilization% is supplied — the estimated
    absolute cap + minutes-to-exhaustion at the recent rate."""
    roll5h = tb.rolling_sum(records, _5H, now)
    roll7d = tb.rolling_sum(records, _7D, now)
    buckets = sorted(tb.bucketize(records, 300).values())
    med = tb.robust_baseline(buckets)[0]
    out: dict = {
        "now": now,
        "roll_5h_weighted": roll5h,
        "roll_5h_per_min": round(tb.per_minute(roll5h, _5H), 1),
        "roll_7d_weighted": roll7d,
        "roll_7d_per_min": round(tb.per_minute(roll7d, _7D), 1),
        "busiest_5h_weighted": tb.max_window_sum(records, _5H),
        "busiest_7d_weighted": tb.max_window_sum(records, _7D),
        "bucket_median": int(med),
        "bucket_p95": tb.percentile(buckets, 95),
        "bucket_p99": tb.percentile(buckets, 99),
    }
    for label, util, roll, wsec in (("5h", util5h, roll5h, _5H), ("7d", util7d, roll7d, _7D)):
        cap = tb.estimate_window_cap(util, roll)
        out[f"est_cap_{label}"] = cap
        if cap is not None and util is not None:
            remaining = int(cap * (1.0 - util / 100.0))
            rate_min = tb.per_minute(roll, wsec)
            out[f"exhaust_min_{label}"] = tb.project_exhaustion_minutes(remaining, rate_min)
    if events:
        out["exhaustion_events"] = len(events)
        out["exhaustion_max_5h"] = max(int(e.get("roll_5h", 0) or 0) for e in events)
        out["exhaustion_max_7d"] = max(int(e.get("roll_7d", 0) or 0) for e in events)
    return out


def _project_dir() -> str:
    return os.environ.get("CLAUDE_PROJECT_DIR", "").strip() or os.getcwd()


def _state_dir() -> Path:
    return Path(_project_dir()) / ".janitor" / "state"


def _coerce_int(raw: str | None, default: int) -> int:
    """Best-effort positive int; junk/absent → default (a typo must never crash the report)."""
    if not raw:
        return default
    try:
        val = int(raw.strip())
    except (ValueError, AttributeError):
        return default
    return val if val > 0 else default


# TRDD-TKNSTP82 A4 — default context-window size for `--live`, shared with the
# context-watchdog hook via the same env var so the two surfaces never disagree.
_CONTEXT_WINDOW_DEFAULT = 1_000_000


def _discover_transcript(project_dir: str) -> tuple[str, str] | None:
    """(transcript_path, session_id) of the most-recently-modified transcript under this
    project's ``~/.claude/projects/<slug>/`` dir, or None when none exist.

    The harness names transcripts ``<session-uuid>.jsonl``, so the filename stem IS the
    session id the statusline snapshot is keyed on. Uses
    ``memory_scopes.project_slug`` — the single source of truth for the slug derivation,
    shared with the memory subsystem, instead of re-deriving it here.
    """
    home = os.environ.get("HOME", "").strip() or os.path.expanduser("~")
    projects_dir = Path(home) / ".claude" / "projects" / memory_scopes.project_slug(project_dir)
    if not projects_dir.is_dir():
        return None
    candidates = [p for p in projects_dir.glob("*.jsonl") if p.is_file()]
    if not candidates:
        return None
    latest = max(candidates, key=lambda p: p.stat().st_mtime)
    return str(latest), latest.stem


def _render_live(as_json: bool) -> int:
    """`--live` — the CURRENT session's exact context percent + last-turn token breakdown,
    no heartbeat log needed. Shares `token_meter.resolve_context`/`tail_turn_usage` with
    the context-watchdog hook so the two views can never silently disagree (TRDD-TKNSTP82
    A4)."""
    project_dir = _project_dir()
    discovered = _discover_transcript(project_dir)
    if discovered is None:
        note = "no transcript found under ~/.claude/projects/<slug>/ for this project"
        if as_json:
            print(json.dumps({"live": True, "session_id": None, "context": None, "last_turn": None, "note": note}, separators=(",", ":")))
        else:
            print(f"[janitor-token-report] --live: {note}.")
        return 0

    transcript, session_id = discovered
    now = int(time.time())
    window_default = _coerce_int(os.environ.get("CLAUDE_PLUGIN_OPTION_CONTEXT_WINDOW_TOKENS"), _CONTEXT_WINDOW_DEFAULT)
    pct, tokens, window, stale = token_meter.resolve_context(project_dir, session_id, transcript, window_default, now=now)
    usage = token_meter.tail_turn_usage(transcript)
    # TRDD-TKNSTP82 C2 — the exact predicted auto-compact point, shared with the
    # context-watchdog hook via token_meter.predict_auto_compact (None when
    # CLAUDE_CODE_AUTO_COMPACT_WINDOW is unset → the % gauge above stands alone).
    pred = token_meter.predict_auto_compact(tokens)

    if as_json:
        print(
            json.dumps(
                {
                    "live": True,
                    "session_id": session_id,
                    "transcript": transcript,
                    "context": {"pct": pct, "tokens": tokens, "window": window, "stale": stale},
                    "compact_prediction": (
                        {
                            "auto_window": pred.auto_window,
                            "overhead": pred.overhead,
                            "effective_compact_point": pred.effective_compact_point,
                            "tokens_until_compact": pred.tokens_until_compact,
                        }
                        if pred is not None
                        else None
                    ),
                    "last_turn": usage.as_record(now) if usage is not None else None,
                },
                separators=(",", ":"),
            )
        )
        return 0

    print(f"[janitor-token-report] --live  ·  session {session_id}")
    if pct is not None:
        size = f"{_fmt_k(tokens)}/{_fmt_k(window)}" if isinstance(tokens, int) and isinstance(window, int) else "?"
        lag = "  (snapshot may lag)" if stale else ""
        print(f"  Context window: {pct}% ({size}) used{lag}")
    else:
        print("  Context window: unknown (no statusline snapshot, no readable transcript occupancy)")
    if pred is not None:
        until = pred.tokens_until_compact
        phrase = f"~{_fmt_k(until)} until auto-compact" if until > 0 else f"~{_fmt_k(-until)} PAST the auto-compact point"
        print(f"  Auto-compact point: {_fmt_k(pred.effective_compact_point)} (window {_fmt_k(pred.auto_window)} − {_fmt_k(pred.overhead)} summary)  ·  {phrase}")
    if usage is not None:
        print(f"  Last turn — output: {usage.output_tokens} (full price)  ·  cache_creation: {usage.cache_creation_input_tokens} (one-time write, ~1.25x, billed once per prefix change)  ·  cache_read: {usage.cache_read_input_tokens} (cheap re-read, ~0.1x)")
    else:
        print("  Last turn: unavailable (turn boundary not found in the transcript tail)")
    burn = _account_burn_lines()
    if burn:
        print("  window burn (live utilization%, read-only via the account rotator):")
        for ln in burn:
            print(ln)
    return 0


def _fmt_ts(epoch: int) -> str:
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return str(epoch)


def _render_window(window: dict) -> None:
    """Print the rolling 5h/7d window view + baseline + (if available) the cap estimate."""
    print("  window usage (weighted = output + input + cache_creation + cache_read/10):")
    print(f"    last 5h  {_fmt_k(window['roll_5h_weighted']):>7}  ({_fmt_k(window['roll_5h_per_min'])}/min)      busiest 5h seen  {_fmt_k(window['busiest_5h_weighted']):>7}  (→ cap ≥ this)")
    print(f"    last 7d  {_fmt_k(window['roll_7d_weighted']):>7}  ({_fmt_k(window['roll_7d_per_min'])}/min)      busiest 7d seen  {_fmt_k(window['busiest_7d_weighted']):>7}  (→ cap ≥ this)")
    print(f"    per-5-min baseline: median {_fmt_k(window['bucket_median'])}  ·  p95 {_fmt_k(window['bucket_p95'])}  ·  p99 {_fmt_k(window['bucket_p99'])}")
    for lbl in ("5h", "7d"):
        cap = window.get(f"est_cap_{lbl}")
        if cap is not None:
            exhaust = window.get(f"exhaust_min_{lbl}")
            tail = f"; exhausts in ~{exhaust / 60:.1f}h at the recent rate" if exhaust else ""
            print(f"    est {lbl} cap ≈ {_fmt_k(cap)} weighted (from live utilization%){tail}")
    if window.get("est_cap_5h") is None and window.get("est_cap_7d") is None:
        print("    (pass --util5h/--util7d from /api/oauth/usage — or /janitor-oauth-health — to estimate the absolute cap + pace)")
    if window.get("exhaustion_events"):
        print(f"    window-exhaustion events logged: {window['exhaustion_events']}  ·  empirical cap ≥ {_fmt_k(window['exhaustion_max_5h'])} (5h) / {_fmt_k(window['exhaustion_max_7d'])} (7d) — the max window sum seen at a turn-ending rate-limit")


def _projects_root() -> Path:
    home = os.environ.get("HOME", "").strip() or os.path.expanduser("~")
    return Path(home) / ".claude" / "projects"


def _short_slug(slug: str) -> str:
    """Compact a harness project slug (abs path with separators dashed) to its trailing
    two tokens so the attribution table stays readable."""
    parts = [p for p in slug.split("-") if p]
    return "-".join(parts[-2:]) if parts else slug


def _account_burn_line(acct: dict, now: int) -> str | None:
    """One account's `<prefix>  5h NN% (ratio X.Xx)  ·  7d NN% (ratio X.Xx, exhausts …)`
    line for `--live`, or None when it has no computable window. Pure over the gathered
    payload."""
    usage = acct.get("usage")
    if not isinstance(usage, dict):
        return None
    parts: list[str] = []
    for w in token_burn.windows_from_usage(usage, now):
        r = w["burn_ratio"]
        rt = f"{r:.1f}x" if r is not None else "n/a"
        seg = f"{w['label']} {w['util_pct']:.0f}% (ratio {rt}"
        ex = w["exhaustion_epoch"]
        if isinstance(ex, int) and ex < w["resets_at_epoch"]:
            seg += f", exhausts {_fmt_ts(ex)}"
        parts.append(seg + ")")
    if not parts:
        return None
    return f"  {acct.get('label', 'live')}  " + "  ·  ".join(parts)


def _account_burn_lines() -> list[str]:
    """READ-ONLY per-account 5h/7d burn summary for `--live`. Returns [] when no rotator is
    configured or on ANY failure — the `--live` view degrades silently. Uses the shared
    rotator_usage gather + token_burn math so this and the detector never disagree."""
    try:
        import rotator_usage  # noqa: PLC0415  # lazy — only --live needs the rotator drive

        accounts = rotator_usage.accounts_usage()
    except Exception:
        return []
    now = int(time.time())
    lines = [ln for acct in accounts if (ln := _account_burn_line(acct, now)) is not None]
    return lines


def _parse_when(raw: str) -> int | None:
    """Epoch seconds from a CLI timestamp: bare epoch int, or ISO 8601 (a naive ISO is
    LOCAL time — the user quotes their meter's local window bounds, e.g. '2026-07-02T14:40')."""
    s = raw.strip()
    if s.isdigit():
        return int(s)
    # fromisoformat FIRST: a NAIVE string must resolve in LOCAL time (datetime.timestamp()
    # does exactly that), while th.parse_ts would silently read it as UTC — a 2h shift here
    # (observed: '14:40' summed as 16:40) is a wrong-window answer, the very bug this
    # command exists to fix. Offset-aware strings resolve identically either way.
    try:
        return int(datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp())
    except ValueError:
        return th.parse_ts(s)


def _graph_bins(span_s: int) -> tuple[int, str]:
    """(bucket_count, bucket_label) for a graph over a `span_s`-second window: 5-min bins
    for a 5h-class window, 30-min up to 2 days, hourly beyond (capped at 168 = one 7d of
    hours) — enough resolution to see shape without overflowing a terminal row."""
    if span_s <= 6 * 3600:
        return max(span_s // 300, 1), "5min"
    if span_s <= 48 * 3600:
        return max(span_s // 1800, 1), "30min"
    return min(max(span_s // 3600, 1), 168), "1h"


def _render_interval(since: int, until: int, as_json: bool, *, graph: bool = False, label: str = "EXACT interval") -> int:
    """Exact-interval attribution (TRDD-0NRVNDSZ) with per-category columns + optional
    graphs (TRDD-4MMXTJFB).

    A fresh, uncached, recursive scan of every project, summed over exactly [since, until]
    — the four RAW usage categories (output / input / cache_creation / cache_read) shown
    separately beside the weighted blend, so cheap 0.1x re-reads are never conflated with
    full-price work. No 30-min cache (an ad-hoc question must never be answered with
    someone else's window). `graph=True` appends cumulative + per-bucket-rate sparklines
    for the CURRENT project's events over the same interval."""
    rows: list[tuple[str, dict[str, float], int]] = []
    root = _projects_root()
    cur_slug = memory_scopes.project_slug(_project_dir())
    cur_events: list = []
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir() or not any(child.rglob("*.jsonl")):
                continue
            events = th.scan_project(child, since)
            cats = th._category_sums(events, since, until)
            if child.name == cur_slug:
                cur_events = events
            if cats["weighted"] > 0:
                rows.append((child.name, cats, sum(1 for e in events if since <= e.ts <= until)))
    rows.sort(key=lambda r: r[1]["weighted"], reverse=True)
    total = {f: sum(r[1][f] for r in rows) for f in th.CATEGORY_FIELDS}
    if as_json:
        print(json.dumps({"attribution": True, "since": since, "until": until, "total_weighted": total["weighted"], "totals": total, "projects": [{"slug": s, "weighted": c["weighted"], "categories": c, "events": n} for s, c, n in rows]}, separators=(",", ":")))
        return 0
    span_h = (until - since) / 3600.0
    print(f"[janitor-token-attribution] {label} {datetime.fromtimestamp(since):%Y-%m-%d %H:%M} → {datetime.fromtimestamp(until):%m-%d %H:%M} ({span_h:.1f}h)  ·  fleet {_fmt_k(total['weighted'])} weighted (transcript-measured, subagents included)")
    print(f"  fleet by category — output {_fmt_k(total['output'])} (full price)  ·  input {_fmt_k(total['input'])} (uncached, full price)  ·  cache_write {_fmt_k(total['cache_creation'])} (~1.25x, once per prefix change)  ·  cache_read {_fmt_k(total['cache_read'])} (~0.1x re-read)")
    print()
    print(f"  {'project':<26} {'weighted':>8} {'share':>6} {'output':>7} {'input':>7} {'cache_wr':>8} {'cache_rd':>8} {'msgs':>5}")
    print(f"  {'-' * 26} {'-' * 8} {'-' * 6} {'-' * 7} {'-' * 7} {'-' * 8} {'-' * 8} {'-' * 5}")
    for slug, c, n in rows[:15]:
        share = (c["weighted"] / total["weighted"] * 100.0) if total["weighted"] > 0 else 0.0
        print(f"  {_short_slug(slug):<26} {_fmt_k(c['weighted']):>8} {share:>5.0f}% {_fmt_k(c['output']):>7} {_fmt_k(c['input']):>7} {_fmt_k(c['cache_creation']):>8} {_fmt_k(c['cache_read']):>8} {n:>5}")
    if not rows:
        print("  no transcript activity in that interval.")
    if graph:
        bins, blabel = _graph_bins(until - since)
        print()
        print(f"  graphs — THIS project ({_short_slug(cur_slug)}), {bins} × {blabel} bins:")
        lines = token_graph.render_window_graphs(cur_events, since, until, buckets=bins, bucket_label=blabel, fields=("weighted", "output", "input", "cache_creation", "cache_read"))
        for ln in lines:
            print(ln)
        if not lines:
            print("  (no activity from this project in the interval)")
    return 0


def _render_selected_window(window: str, last: bool, as_json: bool, *, graph: bool) -> int:
    """`--window 5h|7d [--last]` — exact-interval attribution over ONE subscription window
    (TRDD-4MMXTJFB). Bounds come from the live probe (`token_burn.window_starts`: current
    start = resets_at − W); CURRENT = [start, now], LAST = [start − W, start]. Probe
    failure → trailing [now − W, now], labeled as such so the reader knows the bounds are
    NOT meter-aligned."""
    now = int(time.time())
    wsec = _5H if window == "5h" else _7D
    try:
        w5_lo, w7_lo = token_burn.window_starts(rotator_usage.accounts_usage(), now)
    except Exception:
        w5_lo = w7_lo = None
    lo = w5_lo if window == "5h" else w7_lo
    if lo is None:
        since, until, label = now - wsec, now, f"TRAILING {window} (no live probe)"
    elif last:
        since, until, label = lo - wsec, lo, f"LAST {window} window"
    else:
        since, until, label = lo, now, f"CURRENT {window} window"
    return _render_interval(since, until, as_json, graph=graph, label=label)


def _render_attribution(as_json: bool) -> int:
    """`--attribution` — rank every project by its cross-project token consumption and name
    the culprit (the one to advise). Reads the shared 30-min fleet cache (scans fresh only
    when stale). Read-only."""
    now = int(time.time())
    # Window-ALIGNED bounds from the live usage probe (TRDD-0NRVNDSZ): the 5h/7d sums must
    # cover the SAME fixed windows the subscription meter bills (start = resets_at −
    # window_s), not trailing intervals. Probe failure → (None, None) → trailing fallback.
    try:
        w5_lo, w7_lo = token_burn.window_starts(rotator_usage.accounts_usage(), now)
    except Exception:
        w5_lo = w7_lo = None
    try:
        fleet = tac.get(_projects_root(), now, w5_lo=w5_lo, w7_lo=w7_lo)
    except Exception:
        fleet = {"now": now, "projects": {}, "totals": {"roll_5h": 0.0, "roll_7d": 0.0}, "ranking": []}
    culprit_slug = th.culprit(fleet)

    if as_json:
        print(json.dumps({"attribution": True, "now": now, "fleet": fleet, "culprit": culprit_slug}, separators=(",", ":")))
        return 0

    projects = fleet.get("projects", {})
    ranking = fleet.get("ranking", [])
    totals = fleet.get("totals", {})
    aligned = "window-aligned (resets_at)" if fleet.get("w5_lo") is not None else "trailing (no live probe)"
    print(
        f"[janitor-token-attribution] {len(projects)} project(s)  ·  fleet 5h {_fmt_k(totals.get('roll_5h', 0))}  ·  7d {_fmt_k(totals.get('roll_7d', 0))} weighted  ·  {aligned}"
    )
    if not ranking:
        print("  no per-project transcript activity in the last 7d.")
        return 0
    print()
    print(f"  {'project':<26} {'5h':>7} {'7d':>7} {'share5h':>8} {'spike':>7} {'subagents':>9}")
    print(f"  {'-' * 26} {'-' * 7} {'-' * 7} {'-' * 8} {'-' * 7} {'-' * 9}")
    for slug in ranking:
        m = projects.get(slug, {})
        spike = m.get("spike_factor")
        spike_txt = f"{spike:.1f}x" if isinstance(spike, (int, float)) else "—"
        spawns = int((m.get("source", {}) or {}).get("subagent_spawns", 0) or 0)
        print(f"  {_short_slug(slug):<26} {_fmt_k(m.get('roll_5h', 0)):>7} {_fmt_k(m.get('roll_7d', 0)):>7} {m.get('share_5h', 0.0) * 100:>7.0f}% {spike_txt:>7} {spawns:>9}")
    print()
    if culprit_slug:
        m = projects.get(culprit_slug, {})
        spike = m.get("spike_factor")
        spike_txt = f"{spike:.1f}x own baseline" if isinstance(spike, (int, float)) else "no trailing baseline"
        print(f"  ⚠ top consumer: {_short_slug(culprit_slug)} — {m.get('share_5h', 0.0) * 100:.0f}% of fleet 5h, {spike_txt}. Advise it to compact / throttle / stop idle subagents.")
    else:
        print("  ✓ no single project stands out above the fleet floors.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Per-heartbeat token report")
    ap.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    ap.add_argument("--recent", type=int, default=15, help="how many recent fires to list")
    ap.add_argument("--util5h", type=float, default=None, help="live 5h-window utilization%% (from /api/oauth/usage) → estimate the absolute cap + pace")
    ap.add_argument("--util7d", type=float, default=None, help="live 7d-window utilization%% → estimate the absolute cap + pace")
    ap.add_argument("--live", action="store_true", help="show the CURRENT session's exact context %% + last-turn token breakdown (no heartbeat log needed) instead of the historical report")
    ap.add_argument("--attribution", action="store_true", help="rank every project by cross-project token consumption and name the top consumer (fleet burn attribution; read-only)")
    ap.add_argument("--since", default=None, help="exact interval start (ISO 8601 or epoch) for --attribution: fresh uncached scan summed over [since, until]")
    ap.add_argument("--until", default=None, help="exact interval end (ISO 8601 or epoch), default now; only with --since")
    ap.add_argument("--window", choices=("5h", "7d"), default=None, help="report exactly ONE subscription window (bounds from the live probe): the CURRENT window by default, the previous one with --last")
    ap.add_argument("--last", action="store_true", help="with --window: the LAST completed window instead of the current one")
    ap.add_argument("--graph", action="store_true", help="append cumulative + per-bucket-rate sparklines (this project's events) to the window/interval view")
    args = ap.parse_args()

    if args.window is not None:
        return _render_selected_window(args.window, args.last, args.json, graph=args.graph)
    if args.attribution:
        if args.since is not None:
            now = int(time.time())
            since = _parse_when(args.since)
            until = _parse_when(args.until) if args.until else now
            if since is None or until is None or until <= since:
                print(f"[janitor-token-attribution] invalid interval: since={args.since!r} until={args.until!r}")
                return 2
            return _render_interval(since, until, args.json, graph=args.graph)
        return _render_attribution(args.json)
    if args.live:
        return _render_live(args.json)

    log_path = _state_dir() / "token-meter.jsonl"
    records = token_meter.load_log(log_path)

    if not records:
        if args.json:
            print(json.dumps({"count": 0, "log": str(log_path)}))
        else:
            print("[janitor-token-report] no heartbeat token data yet.")
            print(f"  (the on-stop-token-meter hook logs to {log_path} after each heartbeat fire)")
        return 0

    out_stats = token_meter.summarize(records, field="output")
    in_stats = token_meter.summarize(records, field="input")
    assert out_stats is not None and in_stats is not None
    p95_out = out_stats["p95"]
    spikes = [r for r in records if int(r.get("output", 0) or 0) >= max(_SPIKE_OUTPUT, p95_out)]
    events = token_meter.load_log(_state_dir() / "window-exhaustion.jsonl")
    window = _window_metrics(records, int(time.time()), args.util5h, args.util7d, events)

    if args.json:
        print(
            json.dumps(
                {
                    "count": out_stats["count"],
                    "output": out_stats,
                    "input": in_stats,
                    "spike_threshold": max(_SPIKE_OUTPUT, p95_out),
                    "spikes": len(spikes),
                    "window": window,
                    "log": str(log_path),
                },
                separators=(",", ":"),
            )
        )
        return 0

    print(f"[janitor-token-report] {out_stats['count']} heartbeat fires logged  ·  {log_path}")
    print()
    print(f"  output tokens/fire   mean {out_stats['mean']:.0f}  ·  p50 {out_stats['p50']}  ·  p95 {out_stats['p95']}  ·  max {out_stats['max']}  ·  total {out_stats['total']}")
    print(f"  input  tokens/fire   mean {in_stats['mean']:.0f}  ·  p95 {in_stats['p95']}  ·  max {in_stats['max']}")
    print()
    _render_window(window)
    print()
    print(f"  {'when':<12} {'output':>7} {'input':>7} {'cache_rd':>9} {'cache_cr':>8} {'tools':>5}")
    print(f"  {'-' * 12} {'-' * 7} {'-' * 7} {'-' * 9} {'-' * 8} {'-' * 5}")
    for r in records[-args.recent :]:
        flag = "  ⚠ spike" if int(r.get("output", 0) or 0) >= max(_SPIKE_OUTPUT, p95_out) else ""
        print(f"  {_fmt_ts(r.get('ts', 0)):<12} {r.get('output', 0):>7} {r.get('input', 0):>7} {r.get('cache_read', 0):>9} {r.get('cache_creation', 0):>8} {r.get('tool_calls', 0):>5}{flag}")
    print()
    if spikes:
        print(f"  ⚠ {len(spikes)} fire(s) above the spike threshold ({max(_SPIKE_OUTPUT, p95_out)} output tokens).")
    if out_stats["mean"] >= _HIGH_MEAN_OUTPUT:
        print(f"  ⚠ mean output/fire ({out_stats['mean']:.0f}) is above {_HIGH_MEAN_OUTPUT} — consider lengthening the heartbeat interval or pushing more work into scripts.")
    if not spikes and out_stats["mean"] < _HIGH_MEAN_OUTPUT:
        print("  ✓ no spikes; mean per-fire cost is within budget.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
