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
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import dedupe  # noqa: E402
import findings_ledger  # noqa: E402
import global_state  # noqa: E402
import state  # noqa: E402

_LOG = "session-summary"

# `jev_compact.py compact`'s exit-code contract (its own module docstring is the source of
# truth; TRDD-RAEGS1D5 card 3 part B). `run_compact` ITSELF never retries -- one call, one
# subprocess, a `TimeoutExpired` is a bug exit here, same as any other non-zero/non-{5,6}
# code. `run_compact_with_fallback` (below), added by owner decision 2026-09-23, is the one
# place that calls `run_compact` more than once for the SAME compaction, on a bounded budget.
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
    writes the stamp, only `jev_compact.py` itself does.

    TRDD-RAEGS1D5 owner review finding #7: the stamp lives under `global_state.control_dir()`
    -- MACHINE-WIDE, not per-project (same file every janitor-armed session on this box
    reads/writes). Between one caller's `jev_compact.py compact` failing (which writes this
    stamp) and that SAME caller reading it back a moment later (here), a DIFFERENT session's
    own compaction attempt can legitimately land in between and overwrite it with its own
    kind/reason -- the finding this lane then records could describe the other session's
    failure, not the one that triggered this read. Accepted at LOW severity: the stamp is a
    best-effort diagnostic (which kind of outage, how old), never a correctness input (the
    decline gate re-reads it fresh on its own next call, so a stale/foreign read here cannot
    cause a wrong compact/decline decision, only a momentarily misattributed finding message).
    """
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
#
# TRDD-RAEGS1D5 (retune, owner per-item token cap follow-up): raised from 5000 -- measured
# directly (reports/compaction-replacement/): with an empty facts/cards section (the common
# case), `external_clear.compose_handoff`'s OWN room for this summary (its `max_bytes`
# LANE_INJECTION_MAX_BYTES=8192, minus the facts+recent-turns-tail it always reserves first)
# came to ~5250-6442 bytes across the three real transcripts this project keeps for
# acceptance testing (d30bf250 49MB, 4eb7bf5d 258MB, 06f2b2be 4.7MB) -- 5000 left real,
# measured slack unused on all three, which is exactly why the injected copy kept only 2 of
# the ~3+ non-owner items real data showed should fit. 6500 uses more of that slack (closer to
# the middle of the measured range) while `compose_handoff`'s own downstream byte-slice
# backstop (unconditional, in `external_clear.py`, outside this module) still guarantees the
# TOTAL injected hook output never exceeds `LANE_INJECTION_MAX_BYTES` -- confirmed directly:
# with an oversized dummy summary, `compose_handoff`'s own output measured 8149-8183 bytes on
# these same three transcripts, ~1.8-1.9 KB under the ~10,000-byte real hook-stdout ceiling
# (docs_dev/jev-card5-post-clear-injection-proposal.md) -- comfortably past the ~1.5 KB
# headroom target regardless of this constant's own value. Raising this constant only changes
# how much of that already-safe budget jev_compaction.py's OWN priority-aware backstop gets to
# fill, rather than `compose_handoff`'s cruder byte slice.
LANE_COMPACTED_MAX_BYTES = 6500


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
        # TRDD-RAEGS1D5 R5: this used to hardcode "within 120s" -- true only for the old
        # single fixed-timeout callers. `run_compact_with_fallback`'s retry loop calls
        # `run_compact` with a VARIABLE `timeout=min(120, remaining)` on each attempt, so a
        # fixed number here would misreport the actual bound of the attempt that timed out.
        record_finding(
            sev="HIGH", code="JEV-COMPACT-FAILED",
            msg="[jev-compaction] jev_compact failed (timeout): no response within the "
            "attempt's own timeout — fact-only context injected",
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
            # TRDD-RAEGS1D5 R5: "30 min" was the pre-owner-decision TTL; PROBE_FAIL_TTL_S is
            # now 5 min (jev_compact.py), so this wording would otherwise mislead a reader
            # about how long the next automatic attempt is actually held back.
            record_finding(
                sev="MEDIUM", code="JEV-SCORER-UNAVAILABLE",
                msg=f"[jev-compaction] scorer unavailable: {reason} — fact-only context "
                "injected; compactions decline for 5 min",
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
        # kind == "budget" or "blocked" (TRDD-1ETALGDG -- a Cloudflare edge block that
        # persisted past every split-retry `score_items` tried), or any other unrecognized
        # string — scoped to THIS attempt, not a known whole-endpoint outage shape; never
        # decline the next one on it. No dedicated branch needed: `reason` already carries
        # the specific "blocked"/"budget" detail, and this generic wording is accurate for
        # both.
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
    return `(proc, timed_out)`. `timeout` defaults to 120s (jev's own client retries 3x with
    <=8s backoff on a 15s request timeout; six parallel batches bound the worst case near 70s)
    for a bare caller that passes none -- the sync hook passes its own smaller
    `_RUN_COMPACT_TIMEOUT_S` (60s) explicitly, and `run_compact_with_fallback` (below) passes
    the WHOLE remaining retry budget explicitly (orchestrator correction 2026-09-23, measured:
    a 49MB transcript took 168s for one real run, well past this 120s default), so neither of
    the two real production callers actually relies on this default. A `TimeoutExpired` is a
    bug exit here -- THIS FUNCTION itself never retries on it, so a caller that wants to (only
    `run_compact_with_fallback`, per owner decision 2026-09-23 -- and it deliberately never
    retries a timeout either, only the FAST transient failure kinds) makes the SAME bounded-
    budget decision explicitly, one call at a time, rather than this function silently looping
    and risking landing past the hold's own deadline on its own.

    `budget_tokens`/`digest_tokens`, when given, are forwarded as `--budget-tokens`/`--digest-
    tokens` -- unset (the automatic lane's own default now, card 5 two-renderings) keeps
    `jev_compact.py`'s own card-3 defaults, so `--out` (the keyed handoff file) always gets the
    FULL document and digest, never shrunk by an injection budget.

    `inject_out_path`/`max_elided_pointers`/`inject_max_bytes`, when given, are forwarded as
    `--inject-out`/`--max-elided-pointers`/`--inject-max-bytes` -- a SECOND, capped rendering of
    the SAME scored items, written alongside `--out` for a caller that needs to inject a
    size-bounded companion document (the SessionStart hook) rather than the full one.

    `no_decline`, when true, forwards `--no-decline` -- bypasses `jev_compact.py compact`'s own
    early decline gate for `kind="unavailable"`/`"unreachable"`, NEVER `"rate_limited"` (owner
    decision 2026-09-23 R1; card 5 two-renderings, item 5, originally bypassed `"unreachable"`
    only). Set by an explicit compact-now request, AND by `run_compact_with_fallback` (below)
    on every retry inside its own bounded 5-minute budget -- without it, the first real
    failure would stamp a decline that fast-declines every later retry in this same window."""
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


# --------------------------------------------------------------------------------------- #
# Retry-then-llm-ext fallback (TRDD-RAEGS1D5, owner decision 3 of 2026-09-23 + advisor
# review 20260923_191616+0200-jev-fallback-advisor.md, R1-R5 + recommendations).
#
# Owner's own words: "if jev is not working after 5 minutes retries, the llm-ext compaction
# function must be called as a fallback ... but llm-ext must be used if jev is unavailable
# after 5 minutes." Also: no failure may pause compaction for 30 minutes.
#
# LIVES HERE, NOT IN summarize_previous_session.py, so the entry point stays a thin
# orchestrator (its own docstring: "THIN ON PURPOSE") and BOTH callers of `run_compact` --
# the pane-keyed detached lane AND the no-pane-key path -- get the identical retry+fallback
# behaviour by calling this one function instead of duplicating the loop.
# --------------------------------------------------------------------------------------- #

# Skip a Jev attempt entirely once less than this remains of the retry budget: a real compact
# is ~13s on a 4.6MB transcript, up to ~70s worst case (measure report) -- a 5-30s remainder
# cannot possibly complete one, so spend it on the llm-ext fallback instead (advisor §4).
_MIN_JEV_ATTEMPT_S = 30.0
# Sleep between retries after a FAST transient (non-rate-limited) failure -- kind unavailable/
# unreachable/unknown, which `jev_compact.py` returns in seconds, never a `run_compact`
# subprocess TIMEOUT (that one never retries at all -- see `run_compact_with_fallback`'s own
# docstring, orchestrator correction 2026-09-23: measured 168s for a 49MB transcript, so a
# single attempt can legitimately span the WHOLE remaining budget, and re-running identical
# deterministic work after it times out would only burn what budget is left proving the same
# thing again). Arbitrary but harmless (advisor §5).
_TRANSIENT_RETRY_SLEEP_S = 15.0
# The outer bound added around the llm-ext fallback subprocess (advisor §4 "minor"): its own
# internal timeout is `llm_ext_timeout_s`, but a `uv`/launcher hang BEFORE that timer even
# starts could otherwise outlive the 15-minute hold entirely.
_LLM_EXT_OUTER_SLACK_S = 15.0

# Sources `run_compact_with_fallback` can report success from.
SOURCE_JEV = "jev"
SOURCE_LLM_EXT = "llm-ext"
SOURCE_FAILED = "failed"

# `kind`s (from the probe stamp) that mean "retrying THIS attempt again cannot help" --
# stop the loop and fall back at once rather than spending more of the 5-minute budget.
_NON_RETRYABLE_KINDS = frozenset({"auth", "budget", "invalid"})


# --------------------------------------------------------------------------------------- #
# `blocked=N` visibility (TRDD-1ETALGDG followup): a compaction that succeeds (exit 0) but
# had to pointer some items -- a provider firewall block or an oversized batch that
# survived every split retry `jev_compaction.py::score_items` tried -- is otherwise
# invisible to this lane's own findings: `handle_nonzero_exit` above only ever fires on a
# NON-zero exit. `jev_compact.py`'s own `compacted items=...` success line now carries
# `blocked=N blocked_digest=<hex>` (jev_compact.py::cmd_compact); this parses it and records
# ONE LOW `JEV-COMPACT-BLOCKED` finding, reusing `record_finding` the same way every other
# finding in this module does.
# --------------------------------------------------------------------------------------- #

_BLOCKED_LINE_RE = re.compile(r"\bblocked=(\d+)\s+blocked_digest=([0-9a-f]*)")

# Dedup is CONTENT-based, not session-based (coordinator amendment, 2026-09-23): the SAME
# poisoning content (e.g. one recurring transcript entry a provider firewall always blocks)
# recurs in EVERY new session of this repo, each with a DIFFERENT set of item ids (ids embed
# the transcript's own uuids, which differ per session) -- a session-keyed dedupe would never
# suppress the repeat. `blocked_digest` is a hash of the blocked items' own TEXT (never the
# text itself, matching the codebase's existing cf_ray/body_sha256 pattern -- see
# jevctx.openrouter.JevBlockedError), sorted before hashing so batch-split ORDER (which
# varies run to run) never changes the digest for identical content. `emit_once` against a
# seen-file under the PROJECT state dir (`sd`, never per-session) then suppresses the exact
# same content forever -- the same mechanism `record_once_per_reason` already uses for
# `kind=auth`.
#
# On top of the content dedupe, a separate one-per-day cap on the CODE itself (regardless of
# digest) bounds how often this fires even when the blocked content keeps changing -- a LOW-
# severity visibility finding is not worth repeating more than once a day no matter how many
# distinct poison items a flaky firewall produces on a given day.
BLOCKED_SEEN_FILE = "jev-blocked-finding-seen"
_BLOCKED_LAST_EMIT_FILE = "jev-blocked-finding-last-emit.ts"
_BLOCKED_DAY_CAP_S = 86400.0


def parse_blocked_summary(stdout: str) -> tuple[int, str]:
    """`(blocked_count, blocked_digest)` off `jev_compact.py compact`'s own `compacted
    items=...` stdout summary line, or `(0, "")` when the line is missing/malformed (an
    older `jev_compact.py` without this field, or stdout captured mid-write) -- a best-
    effort visibility signal, never a correctness input, so a parse miss just means "nothing
    to report", not an error."""
    m = _BLOCKED_LINE_RE.search(stdout)
    if not m:
        return 0, ""
    return int(m.group(1)), m.group(2)


def _blocked_day_cap_spent(sd: Path, *, now_fn: Callable[[], float] = time.time) -> bool:
    """True iff a `JEV-COMPACT-BLOCKED` finding already fired within the last
    `_BLOCKED_DAY_CAP_S` -- read-only, never mutates (the caller stamps
    `_mark_blocked_day_spent` only right after it actually emits one)."""
    try:
        last = float((sd / _BLOCKED_LAST_EMIT_FILE).read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return False
    return now_fn() - last < _BLOCKED_DAY_CAP_S


def _mark_blocked_day_spent(sd: Path, *, now_fn: Callable[[], float] = time.time) -> None:
    try:
        sd.mkdir(parents=True, exist_ok=True)
        state.atomic_write(sd / _BLOCKED_LAST_EMIT_FILE, str(now_fn()))
    except OSError:
        pass  # best-effort -- see record_finding's own guard rationale


def record_blocked_finding(
    sd: Path, *, blocked: int, blocked_digest: str, now_fn: Callable[[], float] = time.time,
) -> None:
    """Record ONE LOW `JEV-COMPACT-BLOCKED` finding for a compaction that succeeded (exit 0)
    but had to pointer some items -- see the module-level comment above for the two dedupe
    layers this applies (content digest, forever; the code itself, once a day). A no-op when
    `blocked <= 0` -- nothing to report."""
    if blocked <= 0:
        return
    if _blocked_day_cap_spent(sd, now_fn=now_fn):
        return
    key = f"JEV-COMPACT-BLOCKED:{blocked_digest}"
    msg = (
        f"[jev-compaction] {blocked} item(s) could not be scored (provider firewall or "
        "oversize) and were rendered as pointers instead -- verbatim guarantee held, "
        "nothing was inlined or altered"
    )
    emitted = dedupe.emit_once(sd / BLOCKED_SEEN_FILE, key, msg)
    if emitted:
        record_finding(sev="LOW", code="JEV-COMPACT-BLOCKED", msg=emitted)
        _mark_blocked_day_spent(sd, now_fn=now_fn)


def _sleep_for_kind_or_break(
    stamp: dict, *, deadline: float, now_fn: Callable[[], float], sleep_fn: Callable[[float], None],
) -> bool:
    """For a `kind="rate_limited"` stamp: sleep out the server's own `Retry-After` (floor 5s)
    when it fits inside the remaining budget, or signal "stop, fall back now" when it does not
    (R3: falling back immediately is strictly better than sleeping to the deadline only to
    learn what the stamp's own `retry_after_s` already told us). Returns True to keep
    retrying, False to break out of the loop."""
    remaining = deadline - float(now_fn())
    if remaining <= 0:
        return False
    retry_after = stamp.get("retry_after_s")
    wait = max(float(retry_after), 5.0) if isinstance(retry_after, (int, float)) else 5.0
    if wait > remaining:
        return False  # R3: the decline window outlasts the retry budget -- fall back now
    sleep_fn(min(wait, remaining))
    return True


def _run_llm_ext_fallback(
    plugin_root: Path, *, transcript: str, timeout_s: float,
) -> tuple[bool, str]:
    """EXEC (never import) `scripts/llm_ext_compact.py` -- the llm-ext equivalent of how this
    lane execs `jev_compact.py` BY PATH, for the same reason: `tests/test_jev_boundary.py`
    forbids this stdlib-only module from importing `llm_ext_summary` in-process (owner
    decision 2026-09-23: the automatic lane may EXEC llm-ext, never import it).

    `timeout_s + _LLM_EXT_OUTER_SLACK_S` bounds the whole subprocess -- `llm_ext_compact.py`
    already bounds its OWN internal attempt at `timeout_s`; the slack only guards against a
    `uv`/launcher hang before that internal timer starts (advisor §4).

    Runs in ITS OWN process group (`start_new_session=True`) and, on the outer timeout, kills
    the WHOLE group (`os.killpg`), not just this one child (owner review finding #4,
    TRDD-RAEGS1D5). `llm_ext_compact.py`'s own shebang is `uv run --script`, which execs `uv`,
    which in turn launches the real llm-ext binary as ITS OWN child -- two more generations of
    process below the one `subprocess.run(cmd, timeout=...)` used to reach. A plain
    `Popen.kill()` (or `subprocess.run`'s own timeout handling, which only signals the direct
    child) leaves those grandchildren running past the hold's own deadline with nothing left
    to reap them. `start_new_session=True` makes this process (and everything IT spawns,
    unless one of them calls `setsid` itself) share one process group whose id equals this
    child's own pid, so `os.killpg(proc.pid, ...)` reaches the whole tree in one signal.
    """
    if timeout_s < _MIN_JEV_ATTEMPT_S:
        # Not enough of the hold left to plausibly get a real llm-ext summary back --
        # degrade straight to the mechanical template rather than spend the remainder on a
        # call almost certain to be killed mid-flight.
        return False, f"llm-ext fallback skipped: only {timeout_s:.0f}s left in the hold"
    script = plugin_root / "scripts" / "llm_ext_compact.py"
    cmd = [str(script), "--transcript", transcript, "--timeout-s", str(int(timeout_s))]
    try:
        proc = subprocess.Popen(  # noqa: S603 - explicit args, no shell
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            start_new_session=True,
        )
    except OSError as exc:
        return False, f"llm-ext fallback spawn failed: {exc!r}"
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s + _LLM_EXT_OUTER_SLACK_S)
    except subprocess.TimeoutExpired:
        try:
            if sys.platform == "win32":
                # os.killpg/SIGKILL don't exist on Windows (no POSIX process groups) --
                # start_new_session=True above is a no-op there too, so there is no group to
                # reach anyway; Popen.kill() (TerminateProcess) at least stops the direct
                # child. Grandchildren (uv's own children) going unreaped on this platform is
                # a pre-existing gap this fix does not attempt to close.
                proc.kill()
            else:
                os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass  # already gone, or this platform/sandbox denies killpg -- nothing more to do
        try:
            proc.communicate(timeout=5)  # reap the now-dead group leader
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        return False, "llm-ext fallback timed out (outer bound)"
    if proc.returncode == 0:
        text = (stdout or "").strip()
        if text:
            return True, text
        return False, "llm-ext fallback produced no output"
    return False, (stderr or "").strip()[-400:] or f"llm-ext fallback exited {proc.returncode}"


def run_compact_with_fallback(
    plugin_root: Path, *, transcript: str, out_path: Path, session_key: str,
    heads_args: list[str], sd: Path, deadline: float, llm_ext_timeout_s: float,
    budget_tokens: int | None = None, digest_tokens: int | None = None,
    now_fn: Callable[[], float] = time.time, sleep_fn: Callable[[float], None] = time.sleep,
) -> tuple[str, str | None, str]:
    """Retry `jev_compact.py compact` (with `--no-decline`) until `deadline`, then fall back to
    `llm_ext_compact.py` once. Returns `(source, text, detail)`:
      * `(SOURCE_JEV, <compacted text>, "")` — a real Jev compose succeeded; `out_path` is
        already written (by `run_compact`/`jev_compact.py` itself).
      * `(SOURCE_LLM_EXT, <summary text>, "")` — Jev was exhausted, the llm-ext fallback
        produced a real summary.
      * `(SOURCE_FAILED, None, <why>)` — both Jev and the llm-ext fallback failed; the
        caller degrades to the mechanical template (per the owner's recommendation: ensure a
        template handoff exists for the key, then RELEASE the hold rather than leave it to
        expire — see `summarize_previous_session.py`).

    THIS RETRY LOOP LIVES INSIDE ONE COMPACTION (TRDD-RAEGS1D5, advisor §1): it never stamps
    the clear cooldown, never types `/clear`, and never re-enters the trigger path -- it only
    calls `jev_compact.py compact` and (on exhaustion) `llm_ext_compact.py`, both read-only
    with respect to the clear machinery. That is what keeps it compatible with card 1's loop
    guard ("a failed attempt records evaluated, not fired; no hot retry").

    `--no-decline` is passed on every Jev attempt (R1): without it, the FIRST real failure
    stamps `kind="unavailable"`/`"unreachable"` and every later iteration inside this same
    5-minute budget would fast-decline in microseconds instead of actually retrying.
    `kind="rate_limited"` is deliberately never bypassed (the server's own `Retry-After` is
    honoured via `_sleep_for_kind_or_break`, not raced past).

    ONE ATTEMPT MAY SPAN THE WHOLE REMAINING BUDGET (orchestrator correction, 2026-09-23,
    from a real measurement: a 49MB transcript took 168s for ONE `jev_compact.py compact` run,
    4.7MB took 10s). So `timeout=remaining` here, not a fixed sub-budget -- and a TIMEOUT is
    NEVER retried: it is deterministic work (same transcript, same digest, same items), so a
    re-run would reproduce the identical slowness and just spend more of an already-exhausted
    budget learning nothing new. On timeout the loop goes straight to the llm-ext fallback.
    Retries stay reserved for the FAST transient failures (`kind` unavailable/unreachable/
    unknown/rate_limited), which `jev_compact.py` returns in seconds, not minutes.
    """
    last_proc: subprocess.CompletedProcess[str] | None = None
    last_timed_out = False

    while True:
        remaining = deadline - float(now_fn())
        if remaining < _MIN_JEV_ATTEMPT_S:
            break  # not enough budget left for one more attempt to plausibly finish

        proc, timed_out = run_compact(
            plugin_root, transcript=transcript, out_path=out_path, session_key=session_key,
            heads_args=heads_args, timeout=int(remaining), budget_tokens=budget_tokens,
            digest_tokens=digest_tokens, no_decline=True,
        )
        last_proc, last_timed_out = proc, timed_out

        if not timed_out and proc is not None and proc.returncode == EXIT_OK:
            try:
                text = out_path.read_text(encoding="utf-8")
            except OSError:
                pass  # written but unreadable -- treat exactly like any other failed attempt
            else:
                # TRDD-1ETALGDG followup: a successful (exit 0) compact can still have had
                # to pointer some items -- surface that here, the one place this retry
                # loop's own Jev success returns through. (`run_compact`'s OTHER caller,
                # on-session-start-post-clear-compact.py, does not go through this loop and
                # is unaffected -- out of this followup's file set.)
                blocked, blocked_digest = parse_blocked_summary(proc.stdout or "")
                record_blocked_finding(sd, blocked=blocked, blocked_digest=blocked_digest)
                return SOURCE_JEV, text, ""

        if timed_out or proc is None:
            # Orchestrator correction 2026-09-23: NEVER retried. The attempt just spent (up
            # to) the WHOLE remaining budget on deterministic work that did not finish in
            # time -- a re-run of the SAME transcript/digest/items would time out again,
            # identically, for the same reason. Go straight to the llm-ext fallback.
            break

        if proc.returncode == EXIT_DECLINED_UNAVAILABLE:
            # With `--no-decline` set, `unavailable`/`unreachable` are bypassed by
            # jev_compact.py itself (R1) -- this exit is reachable, with a REAL binary, ONLY
            # for a `kind="rate_limited"` decline (never bypassed). Defensively still guard
            # on the actual stamp kind (never assume) -- an unexpected kind here (a stub in a
            # test, a future stamp shape) stops the loop rather than sleeping on a guess.
            stamp = read_probe_stamp() or {}
            if stamp.get("kind") == "rate_limited" and _sleep_for_kind_or_break(
                stamp, deadline=deadline, now_fn=now_fn, sleep_fn=sleep_fn
            ):
                continue
            break

        if proc.returncode == EXIT_JEV_ERROR:
            stamp = read_probe_stamp() or {}
            kind = stamp.get("kind")
            if kind in _NON_RETRYABLE_KINDS:
                break  # auth/budget/invalid -- retrying cannot help, fall back now
            if kind == "rate_limited":
                if _sleep_for_kind_or_break(
                    stamp, deadline=deadline, now_fn=now_fn, sleep_fn=sleep_fn
                ):
                    continue
                break
            # unavailable / unreachable / unknown / a missing kind -- transient, short sleep
            remaining = deadline - float(now_fn())
            if remaining <= 0:
                break
            sleep_fn(min(_TRANSIENT_RETRY_SLEEP_S, remaining))
            continue

        # EXIT_DECLINED_NO_DIGEST, EXIT_COMMAND_NOT_FOUND, or any other code -- deterministic
        # for this same transcript/environment; retrying cannot change the outcome.
        break

    # Jev exhausted (deadline reached, or a non-retryable stop). Record WHY, per the existing
    # exit-code -> findings-ledger mapping, then try the fallback exactly once -- EXCEPT for
    # two exit codes where trying it is certain to be pointless (owner review finding #2,
    # TRDD-RAEGS1D5): EXIT_COMMAND_NOT_FOUND (127) means `uv` is missing from this session's
    # PATH, and `llm_ext_compact.py` is exec'd BY PATH with the IDENTICAL `uv run --script`
    # shebang -- it would fail the same way, for the same reason, wasting the rest of the hold
    # to learn nothing new. EXIT_DECLINED_NO_DIGEST (6) means the transcript itself carries no
    # digest material (no human message, no TRDD STATE head) -- there is nothing in it for
    # llm-ext to summarize either, so the fallback can only reach the same "nothing to
    # summarize" conclusion the mechanical template already states directly.
    handle_nonzero_exit(last_proc, timed_out=last_timed_out, sd=sd)

    if last_proc is not None and last_proc.returncode == EXIT_COMMAND_NOT_FOUND:
        return SOURCE_FAILED, None, "uv not on PATH -- llm-ext would fail identically"
    if last_proc is not None and last_proc.returncode == EXIT_DECLINED_NO_DIGEST:
        return SOURCE_FAILED, None, "no digest material -- nothing for llm-ext to summarize either"

    ok, payload = _run_llm_ext_fallback(
        plugin_root, transcript=transcript, timeout_s=llm_ext_timeout_s,
    )
    if ok:
        return SOURCE_LLM_EXT, payload, ""

    record_finding(
        sev="HIGH", code="JEV-COMPACT-FAILED",
        msg=f"[jev-compaction] llm-ext fallback also failed: {payload} — degrading to the "
        "mechanical handoff",
    )
    return SOURCE_FAILED, None, payload
