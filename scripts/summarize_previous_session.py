#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Summarize the PREVIOUS session's transcript at SessionStart (TRDD-2F3I2P18, TRDD-RAEGS1D5).

WHY THIS EXISTS AS ITS OWN ENTRY POINT. `external_handoff_clear.py` covers the case where the
JANITOR fires the clear. It cannot cover the case where a HUMAN ends a session — `/clear` has no
hook, and `claude -n` is a brand-new process. Both are the same event from the transcript's point
of view: a session stopped, its `.jsonl` is complete on disk, and the next session starts blank
beside it.

THE ORDERING IS THE POINT, and it is the owner's ruling of 2026-09-01. The new session is ALREADY
cheap — it starts at base context — so there is nothing to save by summarizing first. What must
not happen is the session picking up work before the summary lands, because then it does that work
blind and the injection arrives into a context that has already moved on. So: capture, hold,
summarize, release.

NOTHING HERE COSTS CLAUDE TOKENS. `jev_compact.py compact` (below) runs Jev scoring out of
process against its own provider; this script's whole job is to name the source, take the hold,
invoke it, and wait.

JEV COMPACTION (TRDD-RAEGS1D5, docs_dev/jev-compaction-spec.md card 3) replaced the llm-ext
summary here: instead of `external_clear.summarize_with_retry`, this script now runs
`scripts/jev_compact.py compact` as a subprocess and, on success, composes the injected payload
(facts + the compacted context + a message tail) via `external_clear.compose_handoff`. This
module stays stdlib-only PEP-723 on purpose — `jev_compact.py` is the ONE place `httpx`/`jevctx`
may be imported in-process (see its own module docstring and `tests/test_jev_boundary.py`, which
pins this file into the forbidden-import list). Never `import jevctx`, `httpx`, or
`jev_compaction` here; always reach Jev through a subprocess.
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import dedupe  # noqa: E402
import external_clear as ec  # noqa: E402
import external_handoff_clear as ehc  # noqa: E402
import findings_ledger  # noqa: E402
import global_state  # noqa: E402
import handoff_files  # noqa: E402
import state  # noqa: E402

_LOG = "session-summary"

# resolve like every sibling PEP-723 script does: the real plugin root when the harness set it,
# else this script's own parent (scripts/.. == the plugin root) -- see jev_compact.py itself,
# which is exec'd BY PATH below (it is git-tracked 100755, so its own shebang runs it; no `uv
# run` prefix needed here, matching how the rest of this lane invokes its siblings).
PLUGIN_ROOT = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or str(_SCRIPTS.parent))

# `jev_compact.py compact`'s exit-code contract (its own module docstring is the source of
# truth; TRDD-RAEGS1D5 card 3 part B). Never retried in-process -- a `TimeoutExpired` is a bug
# exit, same as any other non-zero/non-{5,6} code.
_EXIT_OK = 0
_EXIT_DECLINED_UNAVAILABLE = 5
_EXIT_DECLINED_NO_DIGEST = 6
_EXIT_JEV_ERROR = 7

# jev_compact.py's own probe-stamp filename/location (its module docstring is the single
# source of truth for the SHAPE; duplicated here only as a bare string, never as a schema,
# because this file must not `import jev_compact` in-process -- that would pull in
# `jevctx`/`httpx`, exactly what `test_jev_boundary.py` forbids for every stdlib-only script).
_PROBE_STAMP_NAME = "jev-probe.json"

# Which board columns count as "in-flight" for STATE-head selection (brief: docs_dev/
# jev-card3c-brief.md, C1). Cards outside these columns (backburner, complete, blocked, ...)
# are not active work a resuming session needs restated.
_STATE_HEAD_COLUMNS = frozenset(
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
# invoking this script, so the "scorer unreachable" finding can name which lane hit it
# (coordinator amendment to TRDD-RAEGS1D5 card 3 part C). TODAY only the SessionStart hook
# spawns this script (`scripts/hooks/on-session-start.py`, confirmed by grep — no daemon spawn
# site exists yet), so the default is correct as shipped; this is only a hook for later.
_LANE = os.environ.get("JANITOR_JEV_LANE") or "session-start"

# `kind=auth` findings are deduped (coordinator amendment): a rejected provider key does not
# change on every retry, so re-surfacing it every SessionStart is noise, not new information.
# Every other kind is re-surfaced on each occurrence -- an outage or a bug is worth repeating
# until it's fixed. One seen-file, keyed by a hash of the reason text (unbounded length).
_AUTH_SEEN_FILE = "jev-auth-finding-seen"


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
    state. `title` is carried alongside `id` (not just the id) so `_main` can build real
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
            cwd=str(root), capture_output=True, text=True, timeout=20,
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


def _state_head_paths(
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
        for col in _STATE_HEAD_COLUMNS
        for card_id, title in by_col.get(col, [])
    ]
    heads_dir = sd / "jev-heads"
    paths: list[str] = []
    for card_id, _col, _title in cards:
        try:
            proc = subprocess.run(
                [exe, "--design-dir", str(root / "design"), "show", card_id],
                cwd=str(root), capture_output=True, text=True, timeout=15,
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


def _fmt_age(seconds: float) -> str:
    """A short human age phrase — `12m ago`-style, matching the wording the brief's findings
    text expects (e.g. `declined: endpoint unavailable <age> ago`)."""
    seconds = max(0.0, seconds)
    if seconds < 3600:
        return f"{int(seconds // 60)}m"
    if seconds < 86400:
        return f"{seconds / 3600:.1f}h"
    return f"{seconds / 86400:.1f}d"


def _read_probe_stamp() -> dict | None:
    """The current Jev probe stamp (`jev_compact.py`'s own contract — see its module
    docstring), or `None` if it doesn't exist / isn't valid JSON. Read-only: this script never
    writes the stamp, only `jev_compact.py` itself does."""
    import json  # noqa: PLC0415 -- only this one read needs it

    path = global_state.control_dir() / _PROBE_STAMP_NAME
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _record_finding(*, sev: str, code: str, msg: str) -> None:
    """The choke point for every non-zero-exit finding below: record it and, if this project
    is the one it happened in, print the drift line so the heartbeat's quiet-filter can surface
    it. A ledger failure must never break this script (`findings_ledger.record` never raises,
    but the print/log around it is still guarded for the same reason every other caller in
    this codebase guards it)."""
    try:
        line = findings_ledger.record(sev=sev, code=code, src="jev-compaction", msg=msg, ref="")
        if line:
            print(line)
    except Exception as exc:  # noqa: BLE001 - a ledger failure must never break this script
        state.log_line(_LOG, f"could not record finding {code!r}: {exc!r}")


def _handle_nonzero_exit(
    proc: subprocess.CompletedProcess[str] | None, *, timed_out: bool, sd: Path,
) -> None:
    """Map `jev_compact.py compact`'s exit code (or a `TimeoutExpired`) to a finding, per
    docs_dev/jev-card3c-brief.md's C1 exit-code table plus two coordinator amendments: a
    `kind=unreachable` stamp (a transport failure with no HTTP response at all -- offline,
    DNS, TLS) is HIGH and names the LANE; a `kind=rate_limited` stamp (HTTP 429) is MEDIUM and
    names the provider's own retry window. Never writes/releases the hold — the fact-only
    template injection on TTL expiry is today's (unchanged) fallback behaviour; this function
    only records WHY.

    BOTH `kind` and `retry_after_s` are read DEFENSIVELY off the stamp (coordinator amendment):
    a stamp with no `kind` at all (or `rate_limited` with no `retry_after_s`) degrades to the
    `unavailable` wording rather than crashing or guessing a number — the generic outage
    text is always a safe fallback, never a more alarming one.
    """
    if timed_out or proc is None:
        _record_finding(
            sev="HIGH", code="JEV-COMPACT-FAILED",
            msg="[jev-compaction] jev_compact failed (timeout): no response within 120s "
            "— fact-only context injected",
        )
        return

    stderr_tail = (proc.stderr or "").strip()[-200:]

    if proc.returncode == _EXIT_DECLINED_UNAVAILABLE:
        stamp = _read_probe_stamp() or {}
        reason = stamp.get("reason") or "unknown"
        age_s = time.time() - float(stamp.get("ts", time.time()))
        retry_after = stamp.get("retry_after_s") if stamp.get("kind") == "rate_limited" else None
        if retry_after is not None:
            _record_finding(
                sev="MEDIUM", code="JEV-RATE-LIMITED",
                msg=f"[jev-compaction] provider rate limit — compactions retry after "
                f"{retry_after}s — fact-only context injected",
            )
            return
        _record_finding(
            sev="LOW", code="JEV-COMPACT-DECLINED",
            msg=f"[jev-compaction] declined: endpoint unavailable {_fmt_age(age_s)} ago "
            f"({reason}) — fact-only context injected",
        )
        return

    if proc.returncode == _EXIT_DECLINED_NO_DIGEST:
        _record_finding(
            sev="LOW", code="JEV-COMPACT-NO-DIGEST",
            msg="[jev-compaction] declined: nothing to digest — fact-only context injected",
        )
        return

    if proc.returncode == _EXIT_JEV_ERROR:
        stamp = _read_probe_stamp() or {}
        reason = stamp.get("reason") or stderr_tail or "unknown"
        # A stamp with no `kind` field at all reads as the generic outage shape -- defensive,
        # per the amendment, never an escalation to a more alarming wording it never claimed.
        kind = stamp.get("kind") or "unavailable"

        if kind == "rate_limited":
            retry_after = stamp.get("retry_after_s")
            if retry_after is not None:
                _record_finding(
                    sev="MEDIUM", code="JEV-RATE-LIMITED",
                    msg=f"[jev-compaction] provider rate limit — compactions retry after "
                    f"{retry_after}s — fact-only context injected",
                )
                return
            kind = "unavailable"  # no retry_after_s -- fall back to unavailable's own text

        if kind == "unavailable":
            _record_finding(
                sev="MEDIUM", code="JEV-SCORER-UNAVAILABLE",
                msg=f"[jev-compaction] scorer unavailable: {reason} — fact-only context "
                "injected; compactions decline for 30 min",
            )
            return
        if kind == "auth":
            key = hashlib.sha256(reason.encode("utf-8")).hexdigest()[:16]
            msg = _record_once_per_reason(sd, key, reason)
            if msg:
                _record_finding(sev="HIGH", code="JEV-AUTH-REJECTED", msg=msg)
            return
        if kind == "unreachable":
            _record_finding(
                sev="HIGH", code="JEV-SCORER-UNREACHABLE",
                msg=f"[jev-compaction] scorer unreachable from this lane ({_LANE}): {reason} "
                "— fact-only context injected",
            )
            return
        # kind == "budget", or any other unrecognized string — a bug in THIS attempt, not a
        # known outage shape; never decline the next one on it.
        _record_finding(
            sev="HIGH", code="JEV-COMPACT-FAILED",
            msg=f"[jev-compaction] jev_compact failed (exit {proc.returncode}): {reason}",
        )
        return

    # Any other exit code is a bug per the CLI's own contract — one flat space, nothing else
    # is meant to happen.
    _record_finding(
        sev="HIGH", code="JEV-COMPACT-FAILED",
        msg=f"[jev-compaction] jev_compact failed (exit {proc.returncode}): {stderr_tail}",
    )


def _record_once_per_reason(sd: Path, key: str, reason: str) -> str | None:
    """The `kind=auth` finding text, or `None` when this exact reason was already surfaced
    (coordinator amendment: dedupe auth-rejection findings, not every other kind — an auth
    failure is a standing config problem, not a fresh event each SessionStart)."""
    msg = (
        f"[jev-compaction] provider key rejected: {reason} — set OPENROUTER_API_KEY / "
        "CLAUDE_PLUGIN_OPTION_JEV_PROVIDER"
    )
    seen_file = sd / _AUTH_SEEN_FILE
    return dedupe.emit_once(seen_file, key, msg)


def main() -> int:
    """Entry point — wraps `_main` so a crash is LOGGED, not silent (TRDD-QZVAEWQH).

    Measured incident: AgentlensPro 2026-09-02 04:24 took the summary hold and never logged
    READY or FAILED — its stderr went to DEVNULL (fixed separately, at the spawn site in
    on-session-start.py), so nothing on disk said WHY. Re-raising after logging keeps the
    fail-fast contract: the caller's stderr file still gets the traceback, and this line names
    the exception before it propagates.
    """
    try:
        return _main()
    except Exception as exc:  # noqa: BLE001 - log then re-raise, never swallow
        state.log_line(_LOG, f"crashed: {exc!r}")
        raise


def _main() -> int:
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or ".").resolve()
    sd = state.state_dir()
    now = int(time.time())
    session_id = os.environ.get("CLAUDE_CODE_SESSION_ID", "")

    prev = previous_transcript(root, session_id)
    if prev is None:
        state.log_line(_LOG, "no previous transcript to summarize — nothing to do")
        return 0

    key = handoff_files.session_key(str(prev))
    # ALREADY SUMMARIZED? Do not pay for it twice. A session that restarts several times in a row
    # would otherwise re-summarize the same transcript on every start, which is exactly the kind
    # of repeated external work this whole card exists to stop paying for.
    if any(p.is_file() for p in handoff_files.newest_group(sd) if key and key in p.name):
        state.log_line(_LOG, f"a handoff already exists for {key} — skipping")
        return 0

    pending = ehc._capture_summary_source(sd, {"transcript": str(prev)}, now)
    if pending is None:
        state.log_line(_LOG, f"previous transcript unreadable ({prev}) — no hold taken")
        return 0

    print(f"SUMMARY_HOLD_TAKEN {prev.name}")
    state.log_line(_LOG, f"holding this session while jev_compact compacts {prev.name}")

    head_paths, heads_unavailable, in_flight_cards = _state_head_paths(root, sd)
    heads_args = ["--state-heads", *head_paths] if head_paths else []

    out_path = sd / f"jev-compacted-{key or handoff_files.UNKEYED_KEY}.md"
    cmd = [
        str(PLUGIN_ROOT / "scripts" / "jev_compact.py"), "compact",
        "--transcript", str(prev), "--out", str(out_path),
        "--session-key", key, *heads_args,
    ]
    proc: subprocess.CompletedProcess[str] | None = None
    timed_out = False
    try:
        # 120s: jev's own client retries 3x with <=8s backoff on a 15s request timeout; six
        # parallel batches bound the worst case near 70s; the 15-min summary hold is the outer
        # bound (docs_dev/jev-card3c-brief.md C1). A TimeoutExpired is a bug exit here, never
        # retried in-process — retrying would risk landing past the hold's own deadline.
        proc = subprocess.run(cmd, timeout=120, capture_output=True, text=True)
    except subprocess.TimeoutExpired:
        timed_out = True

    if timed_out or proc is None or proc.returncode != _EXIT_OK:
        _handle_nonzero_exit(proc, timed_out=timed_out, sd=sd)
        # The hold's TTL releases the session onto the mechanical handoff (compose_template_
        # handoff). Do NOT clear the hold early here: an immediate release would hand the
        # session a blank context with no explanation, whereas letting the TTL expire produces
        # the documented degrade path — unchanged from the llm-ext-era behaviour.
        state.log_line(
            _LOG,
            "jev_compact produced no compacted context — leaving the hold to expire onto the "
            "mechanical precompact handoff",
        )
        print("SUMMARY_FAILED degrading to the mechanical handoff on TTL")
        return 0

    try:
        compacted_text = out_path.read_text(encoding="utf-8")
    except OSError as exc:
        # jev_compact.py exited 0 (it wrote the file itself, atomically) but this process
        # somehow can't read it back — treat exactly like any other bug exit rather than
        # crash the SessionStart lane over a filesystem race.
        state.log_line(_LOG, f"compacted context written but unreadable ({out_path}): {exc!r}")
        print("SUMMARY_FAILED degrading to the mechanical handoff on TTL")
        return 0

    findings = ["heads: none (trddgrep unavailable)"] if heads_unavailable else []
    # `cards` comes from the SAME board dump `_state_head_paths` already made for the STATE
    # heads, not a fresh fetch -- so composing the facts section costs nothing extra here.
    # WHY this matters (review finding, TRDD-RAEGS1D5 C1): `compose_template_handoff`'s
    # boilerplate NEXT ACTION always reads "read the STATE block of the first in-flight card
    # below" -- an empty `cards=[]` would leave that sentence pointing at nothing every time
    # compaction succeeds, which is worse than the boilerplate being absent.
    inputs = ec.HandoffInputs(trigger="jev-compaction", findings=findings, cards=in_flight_cards)
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    tail = ec.recent_messages(str(prev))
    text = ec.compose_handoff(inputs, now_iso=now_iso, summary=compacted_text, tail=tail)

    handoff_files.write(sd, key or handoff_files.UNKEYED_KEY, text, now=now)
    ehc._release_summary_hold(sd)
    print(f"SUMMARY_READY {len(text.encode('utf-8'))}B for {prev.name}")
    state.log_line(_LOG, f"compacted context ready ({len(text)} chars) — hold released")
    return 0


if __name__ == "__main__":
    sys.exit(main())
