"""Jev-compaction lane library (TRDD-RAEGS1D5 card 3 C2).

Extracted out of `scripts/summarize_previous_session.py` once that entry point grew from 137 to
~530 lines wiring `jev_compact.py compact` in (card 3 C1): the trddgrep board/STATE-heads
discovery, the `jev_compact.py compact` subprocess runner, the exit-code -> findings-ledger
mapper, and their supporting constants all live here now, so the entry script goes back to being
a thin ~140-line orchestrator.

STDLIB ONLY. This module is imported IN-PROCESS by `summarize_previous_session.py`, which must
itself stay PEP-723 stdlib-only (see its own module docstring: `jev_compact.py` is the ONE place
`httpx`/`jevctx`/`jev_compaction` may be imported, always reached through a subprocess). Never add
a `jevctx`/`httpx`/`jev_compaction` import here -- `tests/test_jev_boundary.py` pins this file
into the same forbidden-import list as `scripts/lib/external_clear.py` and
`scripts/summarize_previous_session.py` for exactly that reason.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import dedupe  # noqa: E402
import findings_ledger  # noqa: E402
import global_state  # noqa: E402
import state  # noqa: E402

_LOG = "session-summary"

# `jev_compact.py compact`'s exit-code contract (its own module docstring is the source of
# truth; TRDD-RAEGS1D5 card 3 part B). Never retried in-process -- a `TimeoutExpired` is a bug
# exit, same as any other non-zero/non-{5,6} code.
EXIT_OK = 0
EXIT_DECLINED_UNAVAILABLE = 5
EXIT_DECLINED_NO_DIGEST = 6
EXIT_JEV_ERROR = 7
# Not one of jev_compact.py's own contract codes -- the shell's own "command not found", which
# the exec-by-path call in `run_compact` can hit when a launchd/cron-started session inherits a
# bare PATH with no `uv` on it (coordinator amendment, card 3 C2).
EXIT_COMMAND_NOT_FOUND = 127

# jev_compact.py's own probe-stamp filename/location (its module docstring is the single
# source of truth for the SHAPE; duplicated here only as a bare string, never as a schema,
# because nothing in this lane may `import jev_compact` in-process -- that would pull in
# `jevctx`/`httpx`, exactly what `test_jev_boundary.py` forbids for every stdlib-only module).
PROBE_STAMP_NAME = "jev-probe.json"

# Which board columns count as "in-flight" for STATE-head selection (brief: docs_dev/
# jev-card3c-brief.md, C1). Cards outside these columns (backburner, complete, blocked, ...)
# are not active work a resuming session needs restated.
STATE_HEAD_COLUMNS = frozenset(
    {"dev", "testing", "ai_review", "verify_assumptions", "plan", "dispatch"}
)

# `trddgrep`'s bare board dump is ANSI-colored, human prose -- there is no machine-readable
# board listing in the installed CLI (its own --help says `--porcelain` covers `show`/search
# only, and testing confirmed the board view ignores it). Rather than read a TRDD file
# ourselves (forbidden -- PRRD G12.1, only trddgrep touches a TRDD), this parses the SAME
# board dump a human would see: strip ANSI, track the `═══ <COLUMN> (` section headers, and
# pull the 8-char id token off each entry line.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")
_HEADER_RE = re.compile(r"^═+\s*(\S+)\s*\(")
_ID_RE = re.compile(r"^\s*([A-Z0-9]{8})\s+\S+\s+\S+\s+(.*)$")

# The env marker a future non-SessionStart spawn point (e.g. a daemon lane) would set before
# invoking this lane, so the "scorer unreachable" finding can name which lane hit it
# (coordinator amendment to TRDD-RAEGS1D5 card 3 part C). TODAY only the SessionStart hook
# spawns `summarize_previous_session.py` (`scripts/hooks/on-session-start.py`, confirmed by
# grep -- no daemon spawn site exists yet), so the default is correct as shipped; this is only a
# hook for later.
LANE = os.environ.get("JANITOR_JEV_LANE") or "session-start"

# `kind=auth` findings are deduped (coordinator amendment): a rejected provider key does not
# change on every retry, so re-surfacing it every SessionStart is noise, not new information.
# Every other kind is re-surfaced on each occurrence -- an outage or a bug is worth repeating
# until it's fixed. One seen-file, keyed by a hash of the reason text (unbounded length).
AUTH_SEEN_FILE = "jev-auth-finding-seen"

# Every `trddgrep` subprocess call is capped at 10s (TRDD-RAEGS1D5 card 3 C2, amended down from
# C1's 15-20s): a SQLite index locked by a concurrent `trddgrep move` must not stall the
# composer -- TimeoutExpired or a non-zero exit both degrade to "no heads", never a hang.
_TRDDGREP_TIMEOUT_S = 10


def previous_transcript(root: Path, current_session_id: str) -> Path | None:
    """The newest transcript that is NOT this session's.

    `current_session_id` is excluded by STEM, not by mtime: at SessionStart the new transcript may
    already exist and may already be the newest, so "newest" alone would summarize the blank
    session that just started — the same empty-source trap the post-clear path guards against,
    arriving by a different route.
    """
    try:
        import cold_cache_compact  # noqa: PLC0415

        newest = cold_cache_compact.newest_transcript(root)
        if newest is None:
            return None
        parent = newest.parent
        candidates = [
            p for p in parent.glob("*.jsonl")
            if p.is_file() and p.stat().st_size > 0 and current_session_id not in p.stem
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda p: p.stat().st_mtime)
    except (OSError, ValueError, ImportError):
        return None


def _board_ids_by_column(root: Path) -> dict[str, list[tuple[str, str]]] | None:
    """`{column: [(id, title), ...]}` off `trddgrep`'s plain board dump, or `None` when
    trddgrep is absent or the call failed -- the caller's signal to note "heads unavailable"
    rather than silently inject zero heads/cards as if that were simply this session's true
    state. `title` is carried alongside `id` (not just the id) so callers can build real
    `HandoffInputs.cards` entries from the SAME call, instead of shipping an always-empty
    facts section whose "read the first in-flight card" NEXT ACTION text would otherwise lie
    (review finding on TRDD-RAEGS1D5 C1: an empty `cards=[]` makes compose_template_handoff's
    fixed NEXT-ACTION prose point at nothing)."""
    exe = shutil.which("trddgrep")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "--design-dir", str(root / "design")],
            cwd=str(root), capture_output=True, text=True, timeout=_TRDDGREP_TIMEOUT_S,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode not in (0, 1):  # 1 == "no cards match" -- still a clean run
        return None
    by_col: dict[str, list[tuple[str, str]]] = {}
    current: str | None = None
    for raw_line in proc.stdout.splitlines():
        line = _ANSI_RE.sub("", raw_line)
        header = _HEADER_RE.match(line)
        if header:
            current = header.group(1).lower()
            continue
        m = _ID_RE.match(line)
        if m and current:
            title = m.group(2).strip()
            by_col.setdefault(current, []).append((m.group(1), title))
    return by_col


def _extract_state_section(show_output: str) -> str | None:
    """The `⏵ STATE` section of a `trddgrep show <id>` transcript, or `None` when the card
    carries none (its output then reads literally "(no STATE block — read the file)" — noise,
    not a head worth passing on)."""
    cleaned = _ANSI_RE.sub("", show_output)
    idx = cleaned.find("⏵ STATE")
    if idx == -1:
        return None
    return cleaned[idx:].strip()


def state_head_paths(
    root: Path, sd: Path,
) -> tuple[list[str], bool, list[tuple[str, str, str]]]:
    """Paths of `<state_dir>/jev-heads/<id>.txt`, one per in-flight card's STATE block; whether
    trddgrep was unavailable/failing (the caller's cue to note that in the injected header);
    and the SAME cards as `(id, column, title)` tuples for `HandoffInputs.cards` -- reusing the
    one board-dump call already made here rather than shipping an always-empty `cards=[]` whose
    NEXT-ACTION prose ("read the first in-flight card below") would otherwise point at nothing
    (review finding on TRDD-RAEGS1D5 C1). Never reads a TRDD file directly — every touch goes
    through `trddgrep`."""
    exe = shutil.which("trddgrep")
    if not exe:
        return [], True, []
    by_col = _board_ids_by_column(root)
    if by_col is None:
        return [], True, []
    cards = [
        (card_id, col, title)
        for col in STATE_HEAD_COLUMNS
        for card_id, title in by_col.get(col, [])
    ]
    heads_dir = sd / "jev-heads"
    paths: list[str] = []
    for card_id, _col, _title in cards:
        try:
            proc = subprocess.run(
                [exe, "--design-dir", str(root / "design"), "show", card_id],
                cwd=str(root), capture_output=True, text=True, timeout=_TRDDGREP_TIMEOUT_S,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.returncode != 0:
            continue
        head_text = _extract_state_section(proc.stdout)
        if not head_text:
            continue
        try:
            heads_dir.mkdir(parents=True, exist_ok=True)
            head_path = heads_dir / f"{card_id}.txt"
            state.atomic_write(head_path, head_text)
        except OSError:
            continue
        paths.append(str(head_path))
    return paths, False, cards


def fmt_age(seconds: float) -> str:
    """A short human age phrase — `12m ago`-style, matching the wording the brief's findings
    text expects (e.g. `declined: endpoint unavailable <age> ago`)."""
    seconds = max(0.0, seconds)
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def read_probe_stamp() -> dict | None:
    """The current Jev probe stamp (`jev_compact.py`'s own contract — see its module
    docstring), or `None` if it doesn't exist / isn't valid JSON. Read-only: this lane never
    writes the stamp, only `jev_compact.py` itself does."""
    path = global_state.control_dir() / PROBE_STAMP_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


# TRDD-RAEGS1D5 card 5 measured facts (reports/compaction-replacement/20260923_064108+0200-
# hook-output-experiments.md, 20260923_072806+0200-card5-core.md): the SessionStart hook can
# only inject ~9,000 bytes of stdout before Claude Code truncates it to a 2KB preview, and the
# manual `compose_handoff` default (`external_clear.HANDOFF_MAX_BYTES`, 4096) is deliberately
# unchanged for the manual `/clear` paths -- the AUTOMATIC lane (this hook +
# `summarize_previous_session.py`) instead gets its OWN, larger budget, shared here so both
# callers pass the identical numbers instead of hand-copied magic constants.
LANE_INJECTION_MAX_BYTES = 8192
# Card 5 two-renderings (TRDD-RAEGS1D5): `LANE_BUDGET_TOKENS`/`LANE_DIGEST_TOKENS` are RETIRED
# -- score once, render twice (`jev_compact.py compact`'s own docstring). `--out` (the keyed
# handoff file on disk) now always gets the FULL card-3 budget and the FULL digest; shrinking
# them here used to shrink `--out` too (the card 5 content-fit defect: "the keyed handoff FILE
# on disk is the capped ~4.3 KB document"). Only the SEPARATE `--inject-out` rendering below is
# capped, and its own kept-item budget "aims at the ceiling" -- the byte backstop
# (`LANE_COMPACTED_MAX_BYTES`) is the guarantee, so no separate small token budget is needed for
# it either.
# `jev_compaction.py::compose`'s `max_elided_pointers` (default 40) was the single largest
# line-count contributor once the digest was capped. 12 pointers measured at ~1,732 bytes --
# still enough to name the highest-scoring elided items, far short of showing all 40. Applies
# ONLY to the `--inject-out` rendering, never to `--out`.
LANE_MAX_ELIDED_POINTERS = 12
# The backstop forwarded to `jev_compact.py compact --inject-max-bytes` (via `run_compact`) --
# see `jev_compaction.py::compose`'s own docstring for the drop-oldest-kept-first / drop-lowest-
# score-pointer-first / truncate-digest-last degrade order it applies once this is exceeded.
# Well under `LANE_INJECTION_MAX_BYTES` so `external_clear.compose_handoff` (facts + this + the
# recent-turns tail) still has room for the other two parts of its own single budget.
LANE_COMPACTED_MAX_BYTES = 5000


def record_finding(*, sev: str, code: str, msg: str) -> None:
    """The choke point for every non-zero-exit finding below: record it and, if this project
    is the one it happened in, print the drift line so the heartbeat's quiet-filter can surface
    it. A ledger failure must never break the caller (`findings_ledger.record` never raises,
    but the print/log around it is still guarded for the same reason every other caller in
    this codebase guards it)."""
    try:
        line = findings_ledger.record(sev=sev, code=code, src="jev-compaction", msg=msg, ref="")
        if line:
            print(line)
    except Exception as exc:  # noqa: BLE001 - a ledger failure must never break the caller
        state.log_line(_LOG, f"could not record finding {code!r}: {exc!r}")


def handle_nonzero_exit(
    proc: subprocess.CompletedProcess[str] | None, *, timed_out: bool, sd: Path,
) -> None:
    """Map `jev_compact.py compact`'s exit code (or a `TimeoutExpired`) to a finding, per
    docs_dev/jev-card3c-brief.md's C1 exit-code table plus coordinator amendments: a
    `kind=unreachable` stamp (a transport failure with no HTTP response at all -- offline,
    DNS, TLS) is HIGH and names the LANE; a `kind=rate_limited` stamp (HTTP 429) is MEDIUM and
    names the provider's own retry window; exit 127 (the shell's "command not found") is HIGH
    and names the likely cause -- a launchd/cron-started session inheriting a bare PATH with no
    `uv` on it (card 3 C2 amendment). Never writes/releases the hold — the fact-only template
    injection on TTL expiry is today's (unchanged) fallback behaviour; this function only
    records WHY.

    BOTH `kind` and `retry_after_s` are read DEFENSIVELY off the stamp (coordinator amendment):
    a stamp with no `kind` at all (or `rate_limited` with no `retry_after_s`) degrades to the
    `unavailable` wording rather than crashing or guessing a number — the generic outage
    text is always a safe fallback, never a more alarming one.
    """
    if timed_out or proc is None:
        record_finding(
            sev="HIGH", code="JEV-COMPACT-FAILED",
            msg="[jev-compaction] jev_compact failed (timeout): no response within 120s "
            "— fact-only context injected",
        )
        return

    stderr_tail = (proc.stderr or "").strip()[-200:]

    if proc.returncode == EXIT_COMMAND_NOT_FOUND:
        # exec-by-path resolves `#!/usr/bin/env -S uv run ...` through the SPAWNING process's
        # own PATH, not this repo's -- a launchd/cron-started session can legitimately inherit
        # one with no `uv` on it, which is a config problem to fix, not a jev outage to wait out.
        record_finding(
            sev="HIGH", code="JEV-COMPACT-FAILED",
            msg="[jev-compaction] jev_compact failed (exit 127): uv not on PATH for this "
            "session (a launchd/cron-started session may inherit a bare PATH) — fact-only "
            "context injected",
        )
        return

    if proc.returncode == EXIT_DECLINED_UNAVAILABLE:
        stamp = read_probe_stamp() or {}
        reason = stamp.get("reason") or "unknown"
        age_s = time.time() - float(stamp.get("ts", time.time()))
        stamp_kind = stamp.get("kind")
        retry_after = stamp.get("retry_after_s") if stamp_kind == "rate_limited" else None
        if retry_after is not None:
            record_finding(
                sev="MEDIUM", code="JEV-RATE-LIMITED",
                msg=f"[jev-compaction] provider rate limit — compactions retry after "
                f"{retry_after}s — fact-only context injected",
            )
            return
        # Card 5 two-renderings (TRDD-RAEGS1D5, item 5): a `kind="unreachable"` decline (no HTTP
        # response ever came back -- offline, DNS, TLS) is a DIFFERENT fact than a real
        # `kind="unavailable"` outage (a 5xx response) -- saying "unavailable" for both erased
        # that distinction right where a reader would look for it. Any other/missing kind still
        # reads as the generic "unavailable" wording (defensive, per the stamp docstring above).
        word = "unreachable" if stamp_kind == "unreachable" else "unavailable"
        record_finding(
            sev="LOW", code="JEV-COMPACT-DECLINED",
            msg=f"[jev-compaction] declined: endpoint {word} {fmt_age(age_s)} ago "
            f"({reason}) — fact-only context injected",
        )
        return

    if proc.returncode == EXIT_DECLINED_NO_DIGEST:
        record_finding(
            sev="LOW", code="JEV-COMPACT-NO-DIGEST",
            msg="[jev-compaction] declined: nothing to digest — fact-only context injected",
        )
        return

    if proc.returncode == EXIT_JEV_ERROR:
        stamp = read_probe_stamp() or {}
        reason = stamp.get("reason") or stderr_tail or "unknown"
        # A stamp with no `kind` field at all reads as the generic outage shape -- defensive,
        # per the amendment, never an escalation to a more alarming wording it never claimed.
        kind = stamp.get("kind") or "unavailable"

        if kind == "rate_limited":
            retry_after = stamp.get("retry_after_s")
            if retry_after is not None:
                record_finding(
                    sev="MEDIUM", code="JEV-RATE-LIMITED",
                    msg=f"[jev-compaction] provider rate limit — compactions retry after "
                    f"{retry_after}s — fact-only context injected",
                )
                return
            kind = "unavailable"  # no retry_after_s -- fall back to unavailable's own text

        if kind == "unavailable":
            record_finding(
                sev="MEDIUM", code="JEV-SCORER-UNAVAILABLE",
                msg=f"[jev-compaction] scorer unavailable: {reason} — fact-only context "
                "injected; compactions decline for 30 min",
            )
            return
        if kind == "auth":
            key = hashlib.sha256(reason.encode("utf-8")).hexdigest()[:16]
            msg = record_once_per_reason(sd, key, reason)
            if msg:
                record_finding(sev="HIGH", code="JEV-AUTH-REJECTED", msg=msg)
            return
        if kind == "unreachable":
            record_finding(
                sev="HIGH", code="JEV-SCORER-UNREACHABLE",
                msg=f"[jev-compaction] scorer unreachable from this lane ({LANE}): {reason} "
                "— fact-only context injected",
            )
            return
        # kind == "budget", or any other unrecognized string — a bug in THIS attempt, not a
        # known outage shape; never decline the next one on it.
        record_finding(
            sev="HIGH", code="JEV-COMPACT-FAILED",
            msg=f"[jev-compaction] jev_compact failed (exit {proc.returncode}): {reason}",
        )
        return

    # Any other exit code is a bug per the CLI's own contract — one flat space, nothing else
    # is meant to happen.
    record_finding(
        sev="HIGH", code="JEV-COMPACT-FAILED",
        msg=f"[jev-compaction] jev_compact failed (exit {proc.returncode}): {stderr_tail}",
    )


def record_once_per_reason(sd: Path, key: str, reason: str) -> str | None:
    """The `kind=auth` finding text, or `None` when this exact reason was already surfaced
    (coordinator amendment: dedupe auth-rejection findings, not every other kind — an auth
    failure is a standing config problem, not a fresh event each SessionStart)."""
    msg = (
        f"[jev-compaction] provider key rejected: {reason} — set OPENROUTER_API_KEY / "
        "CLAUDE_PLUGIN_OPTION_JEV_PROVIDER"
    )
    seen_file = sd / AUTH_SEEN_FILE
    return dedupe.emit_once(seen_file, key, msg)


def run_compact(
    plugin_root: Path, *, transcript: str, out_path: Path, session_key: str,
    heads_args: list[str], timeout: int = 120, budget_tokens: int | None = None,
    digest_tokens: int | None = None, max_elided_pointers: int | None = None,
    inject_out_path: Path | None = None, inject_max_bytes: int | None = None,
    no_decline: bool = False,
) -> tuple[subprocess.CompletedProcess[str] | None, bool]:
    """Exec `jev_compact.py compact` BY PATH (it is git-tracked 100755, own shebang runs it) and
    return `(proc, timed_out)`. 120s: jev's own client retries 3x with <=8s backoff on a 15s
    request timeout; six parallel batches bound the worst case near 70s; the 15-min summary hold
    is the outer bound (docs_dev/jev-card3c-brief.md C1). A `TimeoutExpired` is a bug exit here,
    never retried in-process -- retrying would risk landing past the hold's own deadline.

    `budget_tokens`/`digest_tokens`, when given, are forwarded as `--budget-tokens`/`--digest-
    tokens` -- unset (the automatic lane's own default now, card 5 two-renderings) keeps
    `jev_compact.py`'s own card-3 defaults, so `--out` (the keyed handoff file) always gets the
    FULL document and digest, never shrunk by an injection budget.

    `inject_out_path`/`max_elided_pointers`/`inject_max_bytes`, when given, are forwarded as
    `--inject-out`/`--max-elided-pointers`/`--inject-max-bytes` -- a SECOND, capped rendering of
    the SAME scored items, written alongside `--out` for a caller that needs to inject a
    size-bounded companion document (the SessionStart hook) rather than the full one.

    `no_decline`, when true, forwards `--no-decline` -- bypasses `jev_compact.py compact`'s own
    early decline gate entirely (card 5 two-renderings, item 5). The automatic lane never sets
    this; only an explicit compact-now request should."""
    cmd = [
        str(plugin_root / "scripts" / "jev_compact.py"), "compact",
        "--transcript", transcript, "--out", str(out_path),
        "--session-key", session_key, *heads_args,
    ]
    if budget_tokens is not None:
        cmd += ["--budget-tokens", str(budget_tokens)]
    if digest_tokens is not None:
        cmd += ["--digest-tokens", str(digest_tokens)]
    if max_elided_pointers is not None:
        cmd += ["--max-elided-pointers", str(max_elided_pointers)]
    if inject_out_path is not None:
        cmd += ["--inject-out", str(inject_out_path)]
    if inject_max_bytes is not None:
        cmd += ["--inject-max-bytes", str(inject_max_bytes)]
    if no_decline:
        cmd += ["--no-decline"]
    try:
        proc = subprocess.run(cmd, timeout=timeout, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        return None, True
    return proc, False
