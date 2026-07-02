"""Terminal token-usage graphs (TRDD-4MMXTJFB).

Renders a time-bucketed token series as unicode sparklines for the token report:
the PER-BUCKET rate (the derivative — "tokens per turn/bucket") and its RUNNING
SUM (the cumulative curve), so a window's consumption shape is visible at a
glance without leaving the terminal.

Everything is PURE (values in, strings out; stdlib only) so it is unit-testable
with no I/O, no wall clock, no environment. The data source is
`token_history.bucket_series` — this module never scans transcripts itself.
"""

from __future__ import annotations

from datetime import datetime
from itertools import accumulate

# 8-level unicode bars, lowest→highest. A zero bucket renders as the GAP glyph so
# "no activity" is visually distinct from "tiny activity" (▁).
_BARS = "▁▂▃▄▅▆▇█"
_GAP = "·"


def _fmt_k(n: float) -> str:
    """Compact big-number format shared with token_report: 1234 → '1.2k'."""
    n = float(n)
    if abs(n) >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if abs(n) >= 1_000:
        return f"{n / 1_000:.1f}k"
    return f"{n:.0f}"


def sparkline(values: list[float]) -> str:
    """One-row sparkline of `values`, scaled to the series' own max. Zeros render as
    the gap glyph; an empty/all-zero series renders as all gaps (never divides by 0)."""
    if not values:
        return ""
    peak = max(values)
    if peak <= 0:
        return _GAP * len(values)
    out = []
    for v in values:
        if v <= 0:
            out.append(_GAP)
        else:
            # ceil-ish index so any non-zero value gets at least the lowest bar.
            idx = min(int(v / peak * (len(_BARS) - 1) + 0.999), len(_BARS) - 1)
            out.append(_BARS[idx])
    return "".join(out)


def _fmt_edge(epoch: int) -> str:
    try:
        return datetime.fromtimestamp(int(epoch)).strftime("%m-%d %H:%M")
    except (ValueError, OSError, OverflowError):
        return str(epoch)


def render_series(
    series: list[float], lo_ts: int, hi_ts: int, *, label: str, bucket_label: str
) -> list[str]:
    """Render one bucketed series as TWO annotated sparkline rows — the per-bucket RATE
    (derivative) and the CUMULATIVE running sum — plus a time axis. Returns printable
    lines; [] on an empty series so callers can skip silently.

    `label` names the token category (e.g. 'weighted'); `bucket_label` names the bin
    width (e.g. '5min') so the rate row is self-describing."""
    if not series:
        return []
    cum = list(accumulate(series))
    total = cum[-1]
    peak = max(series)
    # Fixed-width row prefixes so the two sparklines start at the same column; the axis
    # row below states the window edges textually instead of trying to align under bars
    # (terminal fonts make glyph-precise alignment unreliable — keep it simple).
    rate_tag = f"rate/{bucket_label}"
    return [
        f"  {label:<14} {rate_tag:<12} {sparkline(series)}  peak {_fmt_k(peak)}",
        f"  {'':<14} {'cumulative':<12} {sparkline(cum)}  total {_fmt_k(total)}",
        f"  {'':<14} {'axis':<12} {_fmt_edge(lo_ts)} → {_fmt_edge(hi_ts)}  ({len(series)} bins)",
    ]


def render_window_graphs(
    events: list,
    lo_ts: int,
    hi_ts: int,
    *,
    buckets: int,
    bucket_label: str,
    fields: tuple[str, ...] = ("weighted", "output", "cache_creation", "cache_read"),
) -> list[str]:
    """Full graph block for one window: per `fields` category, the rate + cumulative
    sparkline pair (categories with zero activity are skipped). `events` are
    `token_history.Event`s; bucketing is delegated to `token_history.bucket_series`."""
    import token_history as th  # local import: keep this module import-light for tests

    lines: list[str] = []
    for field in fields:
        series = th.bucket_series(events, lo_ts, hi_ts, buckets, field)
        if not series or max(series) <= 0:
            continue
        lines.extend(render_series(series, lo_ts, hi_ts, label=field, bucket_label=bucket_label))
        lines.append("")
    if lines and not lines[-1]:
        lines.pop()
    return lines
