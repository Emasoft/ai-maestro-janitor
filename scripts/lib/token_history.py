"""Cross-project per-ACCOUNT token attribution miner (TRDD-OY0W6LX5).

The OAuth usage API reports ONE aggregate 5h/7d utilization% per subscription — it
cannot say WHICH of the ~10 parallel projects sharing that account is burning the
window. This module answers that: it mines every project's Claude Code transcript
(`~/.claude/projects/<slug>/*.jsonl`), turns each assistant turn into a weighted-token
`Event`, and rolls the events up per project so the daemon / detector / CLI can rank
the fleet and name the culprit — the project that is both LARGE in absolute 5h
consumption AND above its own trailing baseline.

Design constraints (verified against the real transcript format):
  * Assistant entries carry `timestamp` (ISO-8601 with a Z or offset, e.g.
    "2026-07-02T12:16:37.606Z") and
    `message.usage.{input,output,cache_read,cache_creation}_tokens`.
  * A subagent spawn is a `message.content` block of `type:tool_use` whose `name` is
    `Task` or `Agent` — counted so "where the spike came from" can point at a runaway
    fan-out.
  * Transcripts reach 100+ MB → we STREAM line-by-line and never read a whole file into
    memory, and we PRUNE a file whose mtime predates the lookback (its newest append —
    hence every entry — is older than the window, so nothing inside can qualify).
  * Junk / partial lines are tolerated (a JSON error skips the line, never the file).

Everything here is PURE — the only I/O is reading the paths you pass, and `now` /
`since_epoch` are parameters — so it is unit-testable with fixture project dirs, no
mocks, no wall clock, no environment. Weighting mirrors token_report.py exactly
(`output + input + cache_creation + cache_read/10`) so this fallback miner and the
live per-heartbeat report agree on what a token "costs".
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from json import JSONDecodeError, loads
from pathlib import Path

# Windows (matching token_report.py's constants) + the per-hour bucket unit.
_5H = 5 * 3600
_7D = 7 * 86400
_HOUR = 3600

# A wall-clock hour whose per-minute rate reaches this multiple of the trailing
# baseline marks a "step up" — where the current elevated burn run began.
_STEP_UP_MULTIPLE = 2.0

# The token classes that count as a subagent SPAWN in a tool_use content block.
_SUBAGENT_TOOLS = ("Task", "Agent")


def _as_int(value: object) -> int:
    """Coerce a possibly-junk usage value to a non-negative-ish int; unparseable → 0.

    Transcript usage fields are ints, but a corrupt line can carry a float, a numeric
    string, or None — so coerce defensively instead of trusting the type (a junk value
    must never crash a fleet-wide scan)."""
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return 0
    return 0


def _median(values: list[float]) -> float:
    """Median of `values`; 0.0 on empty. A project with no baseline buckets has no
    meaningful median — callers treat a baseline of 0 as "no baseline at all"."""
    if not values:
        return 0.0
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2 == 1:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def weighted(usage: dict) -> float:
    """Weighted token cost of one turn's usage dict, mirroring token_report.py:
    `output + input + cache_creation + cache_read/10`.

    The full-price components (output, uncached input, the ~1.25× cache-miss write) count
    1×; the cheap ~0.1× context re-read (`cache_read`) counts 1/10. A non-dict `usage`
    (corrupt line) weighs 0.0 rather than raising."""
    if not isinstance(usage, dict):
        return 0.0
    output = _as_int(usage.get("output_tokens"))
    inp = _as_int(usage.get("input_tokens"))
    cache_creation = _as_int(usage.get("cache_creation_input_tokens"))
    cache_read = _as_int(usage.get("cache_read_input_tokens"))
    return float(output + inp + cache_creation) + cache_read / 10.0


def parse_ts(iso: str) -> int | None:
    """ISO-8601 timestamp (with a trailing `Z` OR a numeric offset, optional fractional
    seconds) → epoch seconds. None on anything unparseable.

    A trailing `Z` is normalised to `+00:00` (belt-and-suspenders across Python versions),
    and a naive timestamp is assumed UTC — the harness always writes UTC, and a naive
    fallback must not skew attribution by the local offset."""
    if not isinstance(iso, str):
        return None
    s = iso.strip()
    if not s:
        return None
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.timestamp())


@dataclass
class Event:
    """One assistant turn's contribution to attribution.

    `weighted` is the token cost (see `weighted`); `output` and `cache_creation` are kept
    raw so a spike can be attributed to full-price work vs. a cache-miss write;
    `tool_calls` / `subagent_spawns` count the turn's `tool_use` blocks (spawns = the
    `Task`/`Agent` subset) so a fan-out runaway is visible."""

    ts: int
    weighted: float
    output: int
    cache_creation: int
    tool_calls: int
    subagent_spawns: int


def _count_tool_use(content: object) -> tuple[int, int]:
    """(tool_calls, subagent_spawns) over a message's content blocks — spawns are the
    `Task`/`Agent` subset. Non-list / malformed content yields (0, 0)."""
    tool_calls = 0
    subagent_spawns = 0
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_use":
                tool_calls += 1
                if block.get("name") in _SUBAGENT_TOOLS:
                    subagent_spawns += 1
    return tool_calls, subagent_spawns


def _event_from_assistant(obj: dict, since_epoch: int) -> Event | None:
    """Build an `Event` from a parsed `type:assistant` transcript entry, or None when it
    is malformed, carries no usage, or predates `since_epoch`."""
    raw_ts = obj.get("timestamp")
    ts = parse_ts(raw_ts) if isinstance(raw_ts, str) else None
    if ts is None or ts < since_epoch:
        return None
    msg = obj.get("message")
    if not isinstance(msg, dict):
        return None
    usage = msg.get("usage")
    if not isinstance(usage, dict):
        return None
    tool_calls, subagent_spawns = _count_tool_use(msg.get("content"))
    return Event(
        ts=ts,
        weighted=weighted(usage),
        output=_as_int(usage.get("output_tokens")),
        cache_creation=_as_int(usage.get("cache_creation_input_tokens")),
        tool_calls=tool_calls,
        subagent_spawns=subagent_spawns,
    )


def scan_transcript(path: str | os.PathLike[str], since_epoch: int) -> list[Event]:
    """Stream one `*.jsonl` transcript and return every assistant `Event` at or after
    `since_epoch`. Line-by-line — a 100+ MB transcript is never loaded whole. Junk lines
    (JSON errors, blanks, non-assistant entries) are skipped; an unreadable file yields
    whatever was collected before the error (best-effort, never raises)."""
    events: list[Event] = []
    try:
        with Path(path).open("r", encoding="utf-8", errors="replace") as f:
            for line in f:
                s = line.strip()
                if not s:
                    continue
                try:
                    obj = loads(s)
                except JSONDecodeError:
                    continue  # partial / corrupt line — skip it, keep scanning
                if not isinstance(obj, dict) or obj.get("type") != "assistant":
                    continue
                ev = _event_from_assistant(obj, since_epoch)
                if ev is not None:
                    events.append(ev)
    except OSError:
        return events
    return events


def scan_project(project_dir: Path, since_epoch: int) -> list[Event]:
    """Every assistant `Event` at or after `since_epoch` across all `*.jsonl` transcripts
    under `project_dir`, merged and sorted ascending by `ts`.

    Cheap prune: a file whose mtime is older than `since_epoch` is SKIPPED without opening
    it — its last append (hence its newest entry) predates the window, so nothing inside
    can qualify. This is what makes a full-fleet scan affordable."""
    d = Path(project_dir)
    if not d.is_dir():
        return []
    events: list[Event] = []
    for jsonl in d.glob("*.jsonl"):
        if not jsonl.is_file():
            continue
        try:
            mtime = jsonl.stat().st_mtime
        except OSError:
            continue
        if mtime < since_epoch:
            continue  # newest entry predates the window — prune the whole file
        events.extend(scan_transcript(jsonl, since_epoch))
    events.sort(key=lambda e: e.ts)
    return events


def _window_sum(events: list[Event], lo_ts: int, hi_ts: int) -> float:
    """Weighted-token sum over the inclusive window [lo_ts, hi_ts]."""
    return sum(e.weighted for e in events if lo_ts <= e.ts <= hi_ts)


def _bucketize_hourly(events: list[Event], lo_ts: int, hi_ts: int) -> dict[int, float]:
    """Weighted tokens summed into wall-clock hour buckets (key = ts // 3600) for events
    in the half-open window [lo_ts, hi_ts). Only non-empty buckets appear — the caller's
    median/step-up logic only cares about hours that actually saw activity."""
    buckets: dict[int, float] = {}
    for e in events:
        if lo_ts <= e.ts < hi_ts:
            key = e.ts // _HOUR
            buckets[key] = buckets.get(key, 0.0) + e.weighted
    return buckets


def _step_up_ts(events: list[Event], now: int, rate_baseline_per_min: float) -> int | None:
    """Epoch (start of the wall-clock hour) where the CURRENT elevated burn run began, or
    None when there is no baseline (`rate_baseline_per_min<=0`) or no elevated hour.

    Scanning back from `now`: find the most-recent hour bucket whose per-minute rate is
    >= `_STEP_UP_MULTIPLE`× the baseline, then walk back over its CONTIGUOUS elevated
    predecessors and return the earliest one's hour-start epoch. Contiguous-from-the-most-
    recent (not "oldest elevated anywhere") so an old, since-subsided blip cannot
    masquerade as the current spike's origin — this is "where the spike came from"."""
    if rate_baseline_per_min <= 0:
        return None
    threshold_per_min = _STEP_UP_MULTIPLE * rate_baseline_per_min
    buckets = _bucketize_hourly(events, now - _7D, now + 1)
    elevated = {k for k, v in buckets.items() if (v / 60.0) >= threshold_per_min}
    cur_hour = now // _HOUR
    candidates = [k for k in elevated if k <= cur_hour]
    if not candidates:
        return None
    k = max(candidates)
    while (k - 1) in elevated:
        k -= 1
    return k * _HOUR


def project_metrics(events: list[Event], now: int) -> dict:
    """Roll one project's `events` up into the attribution metrics for time `now`.

    Returns a dict with rolling weighted sums (`roll_5h`, `roll_7d`, `recent_1h`), the
    recent vs. baseline per-minute rates and their `spike_factor`, the last hour's `source`
    breakdown, and `step_up_ts`. Safe on an empty list (all zeros / None). Pure."""
    roll_5h = _window_sum(events, now - _5H, now)
    roll_7d = _window_sum(events, now - _7D, now)
    recent_1h = _window_sum(events, now - _HOUR, now)
    rate_recent_per_min = recent_1h / 60.0

    # Baseline = the MEDIAN hourly rate over the prior 7 days, EXCLUDING the last hour (the
    # "recent" window we compare against). Median, not mean — the per-hour series is
    # bursty/heavy-tailed, so a mean would be dragged up by a handful of busy hours and
    # hide a genuine step-up.
    baseline_buckets = _bucketize_hourly(events, now - _7D, now - _HOUR)
    rate_baseline_per_min = _median(list(baseline_buckets.values())) / 60.0

    spike_factor = (rate_recent_per_min / rate_baseline_per_min) if rate_baseline_per_min > 0 else None

    # Source breakdown of the last hour: which token class drove the weighted cost. The
    # three shares PARTITION the weighted total (they sum to 1.0). Each `Event` carries only
    # `output` and `cache_creation`, so the third share is the residual (weighted − output −
    # cache_creation)/weighted — dominated by the cheap cache_read/10 term; the small
    # uncached `input_tokens` is folded into it (negligible vs. cache_read in real
    # transcripts). subagent_spawns is the last hour's total Task/Agent spawn count.
    hour_events = [e for e in events if now - _HOUR <= e.ts <= now]
    wsum = sum(e.weighted for e in hour_events)
    osum = sum(e.output for e in hour_events)
    csum = sum(e.cache_creation for e in hour_events)
    if wsum > 0:
        output_share = osum / wsum
        cache_creation_share = csum / wsum
        cache_read_tenth_share = (wsum - osum - csum) / wsum
    else:
        output_share = cache_creation_share = cache_read_tenth_share = 0.0
    source = {
        "output_share": output_share,
        "cache_creation_share": cache_creation_share,
        "cache_read_tenth_share": cache_read_tenth_share,
        "subagent_spawns": sum(e.subagent_spawns for e in hour_events),
    }

    return {
        "roll_5h": roll_5h,
        "roll_7d": roll_7d,
        "recent_1h": recent_1h,
        "rate_recent_per_min": rate_recent_per_min,
        "rate_baseline_per_min": rate_baseline_per_min,
        "spike_factor": spike_factor,
        "source": source,
        "step_up_ts": _step_up_ts(events, now, rate_baseline_per_min),
    }


def fleet_attribution(projects_root: Path, now: int, *, since_epoch: int | None = None) -> dict:
    """Attribute fleet-wide consumption across every project under `projects_root`.

    Walks each child dir that contains at least one `*.jsonl`, scans it (mtime-pruned by
    `since_epoch`, defaulting to `now - 7d` — the widest window we report), and computes its
    `project_metrics`, keyed by the dir name (the harness slug). Each project's metrics gain
    `share_5h`/`share_7d` (its fraction of the fleet 5h/7d totals). `ranking` lists the
    slugs by `roll_5h` descending — the order `culprit` walks."""
    root = Path(projects_root)
    if since_epoch is None:
        since_epoch = now - _7D
    projects: dict[str, dict] = {}
    if root.is_dir():
        for child in sorted(root.iterdir()):
            if not child.is_dir():
                continue
            if not any(child.glob("*.jsonl")):
                continue  # not a project transcript dir — skip
            projects[child.name] = project_metrics(scan_project(child, since_epoch), now)

    total_5h = sum(m["roll_5h"] for m in projects.values())
    total_7d = sum(m["roll_7d"] for m in projects.values())
    for m in projects.values():
        m["share_5h"] = (m["roll_5h"] / total_5h) if total_5h > 0 else 0.0
        m["share_7d"] = (m["roll_7d"] / total_7d) if total_7d > 0 else 0.0

    ranking = sorted(projects.keys(), key=lambda s: projects[s]["roll_5h"], reverse=True)
    return {
        "now": now,
        "since_epoch": since_epoch,
        "projects": projects,
        "totals": {"roll_5h": total_5h, "roll_7d": total_7d},
        "ranking": ranking,
    }


def culprit(fleet: dict, *, min_share: float = 0.1, min_spike: float = 1.5) -> str | None:
    # min_share default 0.1 (was 0.2): validated on the first REAL fleet run (2026-07-02,
    # 82 projects) — the true top consumer held 17% of the fleet with a 9.1x spike and the
    # 0.2 floor wrongly reported "no culprit". On a many-project fleet no single session
    # reaches 20%; 10% + a spike is already the one to advise.
    """The one project to advise: the highest-`roll_5h` slug whose `share_5h >= min_share`
    AND whose `spike_factor` is None OR `>= min_spike`. None when nobody clears the floors.

    A None `spike_factor` (a project with no trailing baseline — e.g. brand-new heavy work)
    PASSES the spike gate: it has no "own norm" to exceed, so a large share alone makes it
    the culprit. Walking `fleet["ranking"]` (already `roll_5h`-descending) returns the
    biggest qualifying consumer, skipping a bigger one that fails the floors."""
    projects = fleet.get("projects", {})
    for slug in fleet.get("ranking", []):
        m = projects.get(slug)
        if not isinstance(m, dict):
            continue
        share = m.get("share_5h", 0.0)
        spike = m.get("spike_factor")
        if share >= min_share and (spike is None or spike >= min_spike):
            return slug
    return None
