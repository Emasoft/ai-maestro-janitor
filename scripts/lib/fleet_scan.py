"""Daemon-side fleet scanner (TRDD-324223a6) — find EVERY running claude instance
and diagnose its janitor's health from OUTSIDE it.

The 2026-06-20→21 freeze was not one session — a live scan found 23 running
claude instances on this host, 15 with a broken janitor (frozen, or a dead
heartbeat stale for up to 23h). The mandate: the janitor must guard the whole
fleet — re-arm a dead cron, reload a version-mismatch, run the freeze ladder —
from outside, regardless of terminal env, leaving only deliberately-unarmed
instances alone.

This module is the daemon's eyes. The PARSERS are pure (tested against captured
tool output, no mocks); ``gather_fleet`` runs the subprocesses (ps / lsof / tmux
/ osascript) and composes them with the pure decision functions in
``session_liveness``. Crucially it resolves each instance's terminal by its live
TTY — NOT by a recorded id — so it can reach even an OLD/zombie instance whose
janitor predates ``terminal-identity.json``. The daemon (which has no session
env of its own) could never do this from inside a session.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import harness_backend
import session_liveness
import state
import terminal_trigger

# A session whose transcript has NOT advanced in this window is treated as stuck
# (dead heartbeat / frozen). A live heartbeat fires a turn every ~5 min and every
# turn is appended to the transcript, so 3× the cadence tolerates two missed fires
# (a slow tick / a brief throttle) before we ever flag it. This — NOT dispatch.log
# (silent on quiet fires) and NOT a new heartbeat stamp (legacy instances lack it)
# — is the reliable liveness signal that also works on old instances.
STALE_S = 15 * 60

# A transcript advanced this recently means the session is BUSY working (continuous
# tool-call appends) — a display nuance over the merely-alive idle-but-cron-firing
# case. Both are "fresh" (< STALE_S) and never flagged; this just distinguishes
# "ending a turn now" from "idle but its heartbeat is keeping it alive".
ACTIVE_FRESH_S = 5 * 60

# Read each iTerm session's controlling TTY + stable session id. Read-only — it
# never brings a window to front and never relaunches iTerm (the caller only runs
# it when iTerm is already in the process table). The id is the UUID that the
# daemon's inject filter matches (`if (id of s) is "<uuid>"`).
#
# The delimiter is a literal "|", NOT the AppleScript `tab` constant: empirically
# (od -c) `osascript -e '… & tab & …'` emits the THREE LETTERS "tab", not a tab
# byte, so a "\t"-split silently matched nothing and every instance read
# UNREACHABLE. A literal "|" round-trips correctly (neither a TTY path nor a UUID
# contains it), resolving 20/21 live instances on the real host.
_ITERM_TTY_OSASCRIPT = (
    'tell application "iTerm2"\n'
    "  set out to \"\"\n"
    "  repeat with w in windows\n"
    "    repeat with t in tabs of w\n"
    "      repeat with s in sessions of t\n"
    '        set out to out & (tty of s) & "|" & (id of s) & linefeed\n'
    "      end repeat\n"
    "    end repeat\n"
    "  end repeat\n"
    "  return out\n"
    "end tell"
)


@dataclass(frozen=True)
class Instance:
    """One running claude instance + its diagnosed janitor health. ``terminal`` is the
    injection identity, resolved from the live TTY and then extended by the taggers:
    ``{tmux_pane?, iterm_session_id?, aimaestro_session?+aimaestro_cli?,
    linux_gui_channel?}``. ``fleet_inject.build_command_plan`` consumes it in that
    fallback order (tmux -> iterm -> aimaestro -> linux-gui). EMPTY means the daemon
    cannot reach this pane by keystroke at all — an armed instance with an empty
    identity is genuinely unreachable, not merely on an unusual terminal."""

    pid: int
    command: str
    tty: str
    project_root: str | None
    terminal: dict[str, str]
    diagnosis: str
    recovery: str | None
    dispatch_age_s: int | None
    active: bool
    transcript_age_s: int | None
    # Typed-but-never-executed commands queued at the newest transcript's tail —
    # the wedged-session evidence the daemon's recovery beat short-circuits on
    # (TRDD-8DR0X08A F2). Defaulted so pre-existing constructors stay valid.
    trailing_enqueues: int = 0
    # The newest transcript ends on an UNANSWERED tool_use ⇒ the session is parked on a
    # question meant for a HUMAN, not dead (TRDD-8IZ8COQ8). Defaulted so pre-existing
    # constructors stay valid.
    awaiting_user: bool = False


#: Every `claude` verb that starts a ONE-SHOT CLI invocation rather than an interactive REPL
#: session. Sourced from `claude --help` PLUS the hidden verbs that listing omits.
#:
#: `daemon` is the case that motivated this (TRDD-R3D5YRQJ) and the reason this comment is
#: long: `claude daemon run` runs in production, is long-lived BY DESIGN — so its inherited
#: transcript age grows forever and it looks more dead every day — and appears in NO help
#: listing. An allowlist derived from the help text is the obvious way to build this set and
#: the way that looks rigorous, and it misses that single case SILENTLY. Hidden verbs exist;
#: when the next one surfaces, add it here explicitly rather than re-deriving from `--help`.
#: `bg-spare` and `bg-pty-host` were found the same way and prove the point twice over: they
#: were running on this host while the card was being fixed, they are internal background
#: helpers, they are in no help listing either, and the card that documented `daemon` did not
#: know about them. Two more hidden verbs surfaced by ONE live scan is the reason the list is
#: maintained from observed processes rather than from documentation.
_CLAUDE_SUBCOMMANDS = frozenset({
    "agents", "auth", "auto-mode", "bg-pty-host", "bg-spare", "daemon", "doctor", "gateway",
    "import", "install", "mcp", "plugin", "plugins", "project", "setup-token", "ultrareview",
    "update", "upgrade",
})


def is_repl_invocation(cmd: str) -> bool:
    """True iff `cmd` starts an interactive claude SESSION rather than a one-shot subcommand.

    Only the token IMMEDIATELY after argv[0] is consulted, and that positional choice is what
    makes this safe: every real subcommand puts its verb first (`claude daemon run`,
    `claude plugin marketplace update`), while a session's argv starts with a FLAG. So a flag
    VALUE — `--agent foo`, `--model sonnet`, `--add-dir /tmp` — can never reach position 1 and
    be misread as a verb. Scanning for the first non-flag token instead would need the full
    which-flags-take-values table to avoid exactly that, and getting it wrong DROPS a real
    headless session.

    UNKNOWN first token ⇒ SESSION, deliberately (TRDD-R3D5YRQJ): including a non-session costs
    one no-op recovery, excluding a real session costs a lost one. The same asymmetry is why
    the fix is argv-shaped and not tty-shaped — filtering on an empty tty would also drop real
    headless/harness sessions, the opposite and worse mistake.

    A transcript-shaped filter is not available at all: the scan resolves a project from the
    process cwd and reads that PROJECT's newest transcript, so a non-session inherits whatever
    session last worked there — `claude daemon run` reported a 16.3-day age it never earned.
    """
    toks = cmd.split()
    if len(toks) < 2:
        return True  # bare `claude` — the plainest REPL there is
    return toks[1] not in _CLAUDE_SUBCOMMANDS


def parse_ps_claude(ps_text: str) -> list[tuple[int, str, str]]:
    """``(pid, normalized_tty, command)`` for every claude SESSION in
    ``ps -eo pid=,tty=,command=`` output. A claude process = argv[0] basename
    ``claude`` OR a ``/share/claude/versions/`` launcher path in the cmdline
    (the two shapes the real install presents). Malformed rows are skipped.

    One-shot CLI invocations are EXCLUDED (`is_repl_invocation`, TRDD-R3D5YRQJ): both callers
    — the fleet guardian and the status table — are asking about sessions, and a live scan
    counted `claude daemon run` and `claude plugin marketplace update` among its `cron_dead`
    instances, which is the number a human reads to decide whether the guardian works."""
    out: list[tuple[int, str, str]] = []
    for ln in ps_text.splitlines():
        if not ln.strip():
            continue
        parts = ln.split(None, 2)  # pid, tty, command (command keeps its spaces)
        if len(parts) < 3:
            continue
        pid_s, tty_s, cmd = parts
        try:
            pid = int(pid_s)
        except ValueError:
            continue
        toks = cmd.split()
        first = toks[0] if toks else ""
        if os.path.basename(first) == "claude" or "/share/claude/versions/" in cmd:
            if not is_repl_invocation(cmd):
                continue  # a one-shot CLI verb, not a session that can be dead or recovered
            out.append((pid, session_liveness.normalize_tty(tty_s), cmd))
    return out


def parse_iterm_sessions(text: str) -> dict[str, str]:
    """``{normalized_tty: iterm_session_id}`` from the osascript dump of
    ``tty|session_id`` lines (see _ITERM_TTY_OSASCRIPT for why the delimiter is a
    literal ``|``, not a tab). Rows without both fields are skipped."""
    out: dict[str, str] = {}
    for ln in text.splitlines():
        if "|" not in ln:
            continue
        tty_s, sid = ln.split("|", 1)
        tty = session_liveness.normalize_tty(tty_s.strip())
        sid = sid.strip()
        if tty and sid:
            out[tty] = sid
    return out


ITERM_TCC_FLAG = "iterm-automation-blocked.flag"


def iterm_automation_blocked(*, iterm_running: bool, sessions: dict[str, str]) -> bool:
    """True iff iTerm is UP but the osascript enumerated ZERO sessions. PURE.

    **This is ONE OBSERVATION, not a diagnosis, and the distinction is load-bearing
    (janitor#229).** A denied Automation (Apple Events) grant produces exactly this
    signature — that is the whole reason the launchd-spawned daemon resolved a channel 0
    times in 254 beats while a session-spawned daemon resolved 56 (TRDD-VQ4LX7ND): the
    grant is attributed to a binary identity, and a background daemon's request is denied
    silently. But a denial is not the ONLY thing that produces it: a crashed/hung
    osascript, a timeout, and an iTerm that is mid-launch all return empty too, and none
    of them writes a distinguishable error either.

    So callers must report what this MEASURED ("0 sessions enumerated"), never what it
    implies ("the grant is denied"). Measured live 2026-08-07: the alarm fired on a host
    where two independent reports said the grant was working, with ZERO denial signatures
    in the logs and an UNCHANGED interpreter path — evidence consistent with both stories,
    because absence of an error string is not evidence of a grant.

    This is a DETECTION, not a fix. The grant itself can only be given by the human, in
    System Settings. What it kills is the failure the TRDD actually indicts: a dead channel
    degrading into a MUTE skip loop for hours. Silence is not success.
    """
    return iterm_running and not sessions


def iterm_automation_payload(
    *,
    interpreter: str,
    second_view: str = "",
    probe_outcome: str = "",
    rearm_evidence_age_s: int | None = None,
) -> str:
    """The flag's exact content for a blocked observation. PURE — so the compare-and-write
    below can decide "has anything CHANGED?" without a timestamp making it always-yes.

    `second_view` carries the grant-free `claude agents --json` verdict (TRDD-DFKEXO79):
    `channel-blocked-not-empty` / `consistent-empty` / `probe-failed:<why>` / "" (not
    probed). It is part of the payload so a verdict CHANGE re-alarms once — the moment
    the second view first proves "blocked-not-empty" is exactly new information.

    `probe_outcome` (TRDD-EZ3PMQYX, janitor#233) is the call site's OWN classification
    of the osascript run that produced zero sessions: ``"error"`` (nonzero exit or the
    binary could not run), ``"timeout"`` (exceeded its deadline), or ``"empty"`` (the
    call succeeded and simply returned nothing to parse). Empty string means the caller
    did not classify it (e.g. a pre-upgrade write path) — never invented as a default,
    because a guessed outcome is worse than an admittedly-absent one.

    `rearm_evidence_age_s` (#237) is the age, in seconds, of the newest `FIRED rearm →
    iterm` daemon-log line AT THE MOMENT this flag was written — read here so the flag is
    self-contained for a consumer that never reads the daemon log itself. Absent (None)
    when no such line was found; the field is OMITTED, not written as 0 (a zero would
    read as "just happened" rather than "unknown").
    """
    data: dict[str, str | int] = {
        "observed": "iTerm running, 0 iTerm sessions enumerated by osascript",
        "interpreter": interpreter,
    }
    if second_view:
        data["second_view"] = second_view
    if probe_outcome:
        data["probe_outcome"] = probe_outcome
    if rearm_evidence_age_s is not None:
        data["rearm_evidence_age_s"] = rearm_evidence_age_s
    return json.dumps(data, sort_keys=True)


# The `FIRED rearm → iterm` parser and its log-name list now live in `session_liveness`,
# which OWNS that line (its recovery path writes it), and both this module and dispatch.py
# call the one copy. They were previously duplicated verbatim and "kept in sync by comment,
# not by import" — which meant a change to the line's wording or timestamp format would be
# applied to one copy, leaving the other to return None forever with nothing looking broken.
_ITERM_REARM_LOG_NAMES = session_liveness.ITERM_REARM_LOG_NAMES
_latest_iterm_rearm_epoch = session_liveness.latest_iterm_rearm_epoch


def _iterm_rearm_evidence_age_s(gs) -> int | None:  # noqa: ANN001 -- gs is the global_state module
    """Age, in seconds, of the newest `FIRED rearm → iterm` daemon-log line, or None when
    no such line was found in either the live or the just-rotated log. Never raises."""
    latest: int | None = None
    for log_name in _ITERM_REARM_LOG_NAMES:
        log_path = gs.global_state_dir() / log_name
        if log_path.is_file():
            try:
                found = _latest_iterm_rearm_epoch(log_path.read_text(encoding="utf-8"))
            except OSError:
                continue
            if found is not None and (latest is None or found > latest):
                latest = found
    if latest is None:
        return None
    return max(0, int(time.time()) - latest)


def record_iterm_automation_state(
    blocked: bool, *, second_view: str = "", probe_outcome: str = ""
) -> None:
    """Persist (or clear) the observation for the heartbeat to surface.

    The daemon is a detached process nobody reads the logs of; the heartbeat is the only
    surface that reaches a human. So the daemon stamps a flag and `dispatch` turns it into
    ONE actionable drift line. Clearing on success matters as much as setting: the moment
    sessions come back, the alarm must stop by itself — an alarm you have to remember to
    silence is one you learn to ignore.

    Two properties, both learned from janitor#229:

    * **Record the INTERPRETER whose Apple Event came back empty** — `sys.executable` of
      THIS process, which for the real scan is the DAEMON's. A human grants Automation to
      a *binary*, so an alarm naming no binary is unactionable, and one naming the
      SESSION's interpreter names the wrong binary entirely. `uv` moves that path on
      upgrade, silently orphaning a grant that was genuinely given — which is precisely
      why the path has to be re-read rather than assumed.
    * **Rewrite when the content CHANGES, and ONLY then.** The previous version wrote only
      `if not flag.exists()`, so a changed interpreter path could never reach the flag and
      the alarm went on naming a binary that no longer ran. Rewriting unconditionally is
      the opposite failure: `dispatch` keys its once-per-occurrence ack on the flag's
      MTIME, so a rewrite every beat would re-alarm every beat.

    `probe_outcome` (TRDD-EZ3PMQYX) is threaded straight into the payload — the caller
    (`gather_fleet`) is the one that actually ran osascript and knows whether it errored,
    timed out, or returned cleanly-but-empty; this function only persists that verdict.

    `rearm_evidence_age_s` is EXCLUDED from the change-detection comparison below on
    purpose: it is a live clock, seconds older on every single scan of an unbroken
    episode, so comparing it byte-for-byte would make the flag "change" every beat and
    re-alarm every beat via dispatch's content-hash ack — exactly the fatigue the
    unchanged-content skip exists to prevent. The written age is therefore a SNAPSHOT
    taken at the moment something else about the observation actually changed (or the
    episode began), not a continuously-updated live value; a consumer reads "how old was
    the evidence when this was last written", which is what the field promises.

    Best-effort: this must never break a fleet scan.
    """
    try:
        import global_state as gs  # local import — fleet_scan is imported by non-daemon paths

        flag = gs.global_state_dir() / ITERM_TCC_FLAG
        if not blocked:
            flag.unlink(missing_ok=True)
            return
        core_payload = iterm_automation_payload(
            interpreter=sys.executable, second_view=second_view, probe_outcome=probe_outcome
        )
        try:
            if _iterm_payload_core(flag.read_text(encoding="utf-8")) == core_payload:
                return  # unchanged — leave the flag (and its age snapshot) alone
        except OSError:
            pass  # absent or unreadable → (re)write it below
        payload = iterm_automation_payload(
            interpreter=sys.executable,
            second_view=second_view,
            probe_outcome=probe_outcome,
            rearm_evidence_age_s=_iterm_rearm_evidence_age_s(gs),
        )
        # Atomic (tmp+rename): dispatch reads this file concurrently from another
        # process, and a truncate-then-write lets it observe a half-written flag —
        # json.loads then fails and the alarm prints the wrong fallback diagnosis.
        state.atomic_write(flag, payload)
    except Exception:  # noqa: BLE001 -- advisory only; never break the scan
        pass


def _iterm_payload_core(raw: str) -> str:
    """`raw` with `rearm_evidence_age_s` stripped, re-serialized the same way
    `iterm_automation_payload` does — the comparable EQUALITY surface a change-detection
    check can use without a live clock field forcing a "changed" verdict every scan.
    Malformed/legacy (pre-JSON) content is returned unchanged, so it never spuriously
    compares equal to a well-formed payload and the upgrade path still rewrites once."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return raw
    if isinstance(data, dict):
        data.pop("rearm_evidence_age_s", None)
    return json.dumps(data, sort_keys=True)


def iterm_rescue_warranted(fleet: "list[Instance]") -> bool:
    """True iff THIS scan's own diagnoses give the iTerm-blocked observation an
    UNCONDITIONAL-NEGATIVE reading (TRDD-9PDH8G0W, janitor#92 peer self-correction
    2026-08-08): at least one instance was diagnosed `cron_dead` while its terminal
    resolution found NO other channel (no `tmux_pane`, `aimaestro_session`, or
    `linux_gui_channel`) — the "UNREACHABLE" case `fleet_scan._main` already prints.
    On a host where `iterm_by_tty` came back empty (the blocked condition itself), such
    an instance's ONLY possible channel was iTerm, so a rescue was WARRANTED and the
    channel was EXERCISED and returned nothing — unlike the v2.8.1 rearm-evidence
    downgrade, this has no "quiet fleet, nothing needed rescuing" explanation available.

    Callers only need this when `blocked` is already True (a healthy scan never diagnoses
    the flag at all), but the function itself stays a pure predicate over `fleet` so it is
    testable without constructing a whole scan. PURE.
    """
    return any(
        inst.diagnosis == "cron_dead"
        and "tmux_pane" not in inst.terminal
        and "aimaestro_session" not in inst.terminal
        and "linux_gui_channel" not in inst.terminal
        for inst in fleet
    )


def record_iterm_rescue_warranted(warranted: bool) -> None:
    """Patch the iTerm-automation-blocked flag `record_iterm_automation_state` already
    wrote THIS beat with whether the SAME scan's diagnoses warrant the unconditional-
    negative reading (TRDD-9PDH8G0W). This is a separate, later write rather than a
    field on the original call because the fact it carries — a `cron_dead` diagnosis
    correlated with the iTerm-blocked observation — is only known once `gather_fleet`'s
    per-instance loop has run, which happens AFTER `record_iterm_automation_state`'s own
    early write. That early write cannot be deferred to loop's end either:
    `capture_pane_text` declines the iTerm channel by checking the flag's mere
    EXISTENCE mid-loop (TRDD-WKTD5JTC), so delaying the whole write would blind that
    same-beat decline on the very first blocked beat. Hence: write early (unblocks the
    decline), patch late (adds the fact once it exists).

    Compare-and-write, same discipline as the rest of this flag: a no-op when the value
    is unchanged, so this never causes ack churn on its own (no rewrite → no new content
    hash → dispatch's once-per-observation ack does not re-fire). Read-modify-write on
    the CURRENT flag content — never creates the flag (nothing to patch once the
    condition already cleared this beat) and never touches the clear/unlink path.

    Best-effort: a scan must never break because this patch failed.
    """
    try:
        import global_state as gs  # local import — mirrors record_iterm_automation_state

        flag = gs.global_state_dir() / ITERM_TCC_FLAG
        try:
            raw = flag.read_text(encoding="utf-8")
        except OSError:
            return  # nothing to patch — absent (condition cleared) or unreadable
        try:
            data = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return  # legacy/pre-JSON content — leave it; the next full rewrite fixes it
        if not isinstance(data, dict):
            return
        if data.get("rescue_warranted") == warranted:
            return  # unchanged — no rewrite, no ack churn
        data["rescue_warranted"] = warranted
        state.atomic_write(flag, json.dumps(data, sort_keys=True))
    except Exception:  # noqa: BLE001 -- advisory; must never break the scan
        pass


def iterm_automation_interpreter(raw: str) -> str:
    """The interpreter path recorded in a flag's contents, or "" when it names none. PURE.

    Fail-open by construction: the flag was plain prose before this was JSON, so a
    pre-upgrade flag left on disk parses to "" and the alarm simply omits the path rather
    than crashing or printing garbage.
    """
    return _iterm_flag_field(raw, "interpreter")


def iterm_automation_second_view(raw: str) -> str:
    """The second-view verdict recorded in a flag's contents, or "" when absent. PURE.
    Same fail-open contract as `iterm_automation_interpreter`."""
    return _iterm_flag_field(raw, "second_view")


def iterm_automation_probe_outcome(raw: str) -> str:
    """The osascript probe's own outcome (`"error"` / `"timeout"` / `"empty"`) recorded
    in a flag's contents, or "" when the write path did not classify it. PURE. Same
    fail-open contract as `iterm_automation_interpreter` (TRDD-EZ3PMQYX)."""
    return _iterm_flag_field(raw, "probe_outcome")


def iterm_automation_rearm_evidence_age_s(raw: str) -> int | None:
    """Seconds since the newest `FIRED rearm → iterm` daemon-log line AS OF the moment
    this flag was last written, or None when the flag names none (no evidence was found,
    or a pre-upgrade/malformed flag). PURE. #237."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("rearm_evidence_age_s")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def iterm_automation_rescue_warranted(raw: str) -> bool | None:
    """Whether the SAME scan that wrote this flag also diagnosed `cron_dead` on an
    instance whose only possible channel was iTerm (TRDD-9PDH8G0W, janitor#92 peer
    self-correction). ``None`` means "not yet known / not recorded" — distinct from
    ``False`` ("known: no such instance this scan") — because the field is patched in
    AFTER the initial write (see `record_iterm_rescue_warranted`) and a pre-patch or
    pre-upgrade flag must never be misread as a negative verdict. PURE, fail-open like
    every other flag-field reader here."""
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    value = data.get("rescue_warranted")
    return value if isinstance(value, bool) else None


def _iterm_flag_field(raw: str, key: str) -> str:
    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return ""
    if not isinstance(data, dict):
        return ""
    value = data.get(key, "")
    return value if isinstance(value, str) else ""


def parse_tmux_panes(text: str) -> dict[str, str]:
    """``{normalized_tty: pane_id}`` from
    ``tmux list-panes -a -F '#{pane_tty} #{pane_id}'``."""
    out: dict[str, str] = {}
    for ln in text.splitlines():
        toks = ln.split()
        if len(toks) < 2:
            continue
        tty = session_liveness.normalize_tty(toks[0])
        if tty and toks[1]:
            out[tty] = toks[1]
    return out


def find_janitor_root(cwd: str | None) -> str | None:
    """Walk up from ``cwd`` to the nearest dir containing ``.janitor/`` (the
    project where the janitor is/was active). ``None`` if ``cwd`` is unset or no
    ancestor qualifies — a claude running where the janitor never ran is not our
    concern (its SessionStart hook will set it up)."""
    if not cwd:
        return None
    d = os.path.realpath(cwd)
    for _ in range(8):  # bounded walk — never loop on a pathological tree
        if os.path.isdir(os.path.join(d, ".janitor")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def _age(path: str, now: int) -> int | None:
    """Seconds since ``path`` was last modified, or ``None`` if it does not exist."""
    try:
        return now - int(os.path.getmtime(path))
    except OSError:
        return None


def stale_threshold_for(armed_cron: str, base_stale_s: int = STALE_S) -> int:
    """The staleness window for a session armed at ``armed_cron`` — 3× its heartbeat
    interval (the same two-missed-fires tolerance ``STALE_S`` encodes for */5), never
    below ``base_stale_s``. Pure; an empty/unparseable cron keeps the base window
    (fail to the stricter default, never to a looser one). TRDD-8DR0X08A F4."""
    minutes = 0
    first = armed_cron.strip().split()[0] if armed_cron.strip() else ""
    if first.startswith("*/"):
        try:
            minutes = int(first[2:])
        except ValueError:
            minutes = 0
    return max(base_stale_s, 3 * minutes * 60)


def _tail_lines(path: str, max_bytes: int = 64 * 1024) -> list[str]:
    """The last ``max_bytes`` of ``path`` as text lines (first line dropped when the
    read started mid-line). Empty list on any I/O failure — the caller falls back to
    mtime semantics, never crashes the scan."""
    try:
        size = os.path.getsize(path)
        with open(path, "rb") as fh:
            if size > max_bytes:
                fh.seek(size - max_bytes)
            data = fh.read(max_bytes + 1)
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").splitlines()
    if len(lines) > 1 and size > max_bytes:
        lines = lines[1:]  # the first line is almost certainly truncated mid-record
    return [ln for ln in lines if ln.strip()]


def substantive_age_from_tail(
    tail: list[str], *, now: int, fallback_age: int | None
) -> tuple[int | None, int]:
    """``(substantive_age_s, trailing_enqueues)`` for a transcript tail.

    TRDD-8DR0X08A: the fleet guardian's own typed recovery command makes Claude Code
    append a ``{"type":"queue-operation","operation":"enqueue",...}`` line to the
    target's transcript — which refreshed the mtime this scanner used as the liveness
    signal, so every injection diagnosed the target "healthy" on the next beat, reset
    its attempt budget, and re-injected forever. The liveness signal must therefore be
    the age of the newest SUBSTANTIVE line (anything that is not queue bookkeeping),
    never the file mtime alone.

    Pure. Walks the tail backwards: consecutive trailing ``queue-operation`` lines are
    counted (``operation == "enqueue"`` only — the queued-but-never-executed evidence);
    the first non-queue line with a parseable ``timestamp`` yields the age. A tail that
    is ALL queue bookkeeping uses its OLDEST parseable timestamp (a lower bound on the
    true substantive age — conservative: keeps a wedged session diagnosed stale). No
    parseable timestamp at all → ``fallback_age`` (the mtime — degrade to the old
    behavior rather than break the scan on an unknown transcript format)."""
    import token_history

    trailing_enqueues = 0
    oldest_seen: int | None = None
    in_trailing_run = True
    for raw in reversed(tail):
        try:
            rec = json.loads(raw)
        except ValueError:
            rec = None  # malformed → treat as substantive content of unknown time
        ts = token_history.parse_ts(rec.get("timestamp", "")) if isinstance(rec, dict) else None
        if ts is not None:
            oldest_seen = ts if oldest_seen is None else min(oldest_seen, ts)
        if isinstance(rec, dict) and rec.get("type") == "queue-operation":
            if in_trailing_run and rec.get("operation") == "enqueue":
                trailing_enqueues += 1
            continue
        in_trailing_run = False
        if ts is not None:
            return max(0, now - ts), trailing_enqueues
        # substantive but timestamp-less (e.g. malformed) — keep walking for a
        # parseable neighbor; adjacent lines are seconds apart, close enough.
    if oldest_seen is not None:
        return max(0, now - oldest_seen), trailing_enqueues
    return fallback_age, trailing_enqueues


# Tools whose ONLY possible answer comes from a person, so an unanswered call to one is
# proof the session is blocked on a human — never on a machine that will finish on its own.
# Deliberately a NAME allow-list, not "any unanswered tool_use": an unanswered call also
# describes a tool that is merely still RUNNING (Bash timeouts here are 20 minutes, which
# outlives the staleness threshold), and mislabelling a working session as "waiting on YOUR
# answer" is a worse failure than the missed recovery it causes. A permission prompt on an
# ARBITRARY tool is the same hazard and is NOT covered — it is indistinguishable from a
# slow tool with the signals available here (see the card's follow-up).
_HUMAN_FACING_TOOLS = frozenset({"ExitPlanMode", "AskUserQuestion"})


def awaiting_user_decision(tail: list[str]) -> bool:
    """True iff the transcript tail ends on an UNANSWERED call to a HUMAN-FACING tool
    (``ExitPlanMode`` / ``AskUserQuestion``) — the session is parked on a question meant
    for a person, not dead.

    TRDD-8IZ8COQ8. A blocked session is indistinguishable from a dead one by the signals
    the guardian had: its transcript stops appending and its cron cannot fire, because
    both need the turn to end. Measured on 2026-07-17 in this very repo — the last line
    before a 33-minute silence was an ``ExitPlanMode`` tool_use, the guardian read
    ``cron_dead``, and typed ``/janitor-arm`` into the approval dialog. That is worse than
    the "janitor keeps printing commands" spam the user reported: it is an unattended
    machine answering a question that was addressed to a person.

    ``trailing_enqueues`` cannot cover this. It only becomes non-zero AFTER something has
    been typed, so it catches the second injection and every one after — never the first,
    which is the one that reaches the dialog. This predicate reads the state that is true
    BEFORE anyone types.

    Pure. Walks the tail backwards collecting answered ``tool_use_id``s, skipping queue
    bookkeeping (the guardian's own typed command appends an enqueue line, which must not
    hide the pending question beneath it), and stops at the newest substantive record: it
    is a pending question iff that record carries a ``tool_use`` no ``tool_result``
    answers. Anything else — ordinary content, an answered call, an unparseable tail — is
    False, so a genuinely dead session stays recoverable. Combine with staleness: mid-turn
    a tool_use is briefly unanswered by design, and only a STALE one means blocked."""
    answered: set[str] = set()
    for raw in reversed(tail):
        try:
            rec = json.loads(raw)
        except ValueError:
            return False  # unparseable tail — cannot prove a pending question; stay recoverable
        if not isinstance(rec, dict):
            return False
        if rec.get("type") == "queue-operation":
            continue
        msg = rec.get("message")
        if not isinstance(msg, dict):
            # Message-LESS bookkeeping (summary / system / progress / snapshot lines):
            # it can neither ask a question nor answer one, so it must not TERMINATE
            # the walk — bailing here was the 2026-08-02 review finding: ONE trailing
            # harness record hid a pending ExitPlanMode beneath it and the guardian
            # typed into the human's approval dialog (the exact TRDD-8IZ8COQ8 incident
            # this predicate exists to prevent). Only a real MESSAGE resolves anything.
            continue
        content = msg.get("content")
        if not isinstance(content, list):
            return False  # a real message with prose content — someone spoke ⇒ not pending
        blocks = [b for b in content if isinstance(b, dict)]
        for b in blocks:
            if b.get("type") == "tool_result" and isinstance(b.get("tool_use_id"), str):
                answered.add(b["tool_use_id"])
        calls = [
            b for b in blocks if b.get("type") == "tool_use" and isinstance(b.get("id"), str)
        ]
        if calls:
            return any(
                b["id"] not in answered and b.get("name") in _HUMAN_FACING_TOOLS
                for b in calls
            )
        if any(b.get("type") == "tool_result" for b in blocks):
            continue  # a results-only record: keep walking back to the call it answers
        return False
    return False


def transcript_activity(root: str, now: int) -> tuple[int | None, int, bool]:
    """``(substantive_age_s, trailing_enqueues, awaiting_user)`` for this project's
    transcripts — ``(None, 0, False)`` when none exist. The age is seconds since the
    newest SUBSTANTIVE transcript line (see ``substantive_age_from_tail``);
    ``trailing_enqueues`` is how many typed-but-never-executed commands sit queued at the
    newest transcript's tail — the daemon's wedged-session evidence (TRDD-8DR0X08A F2);
    ``awaiting_user`` is whether that same tail ends on an unanswered ``tool_use``, i.e.
    the session is blocked on a HUMAN decision (TRDD-8IZ8COQ8). All three come from ONE
    read of the same tail. The transcript lives
    outside ``.janitor`` (``~/.claude/projects/<dashed-cwd>/*.jsonl``), so this maps
    the project root to its harness slug the same way the memory scopes do."""
    # SSOT slug (memory_scopes.project_slug): the harness dashes EVERY non-alphanumeric
    # char, not just "/" — a separators-only replace returned None for any dotted or
    # underscored project path, so the fleet guardian never saw those sessions' activity.
    import memory_scopes

    slug = memory_scopes.project_slug(os.path.realpath(root))
    tdir = os.path.join(os.path.expanduser("~"), ".claude", "projects", slug)
    ages: list[tuple[int, str]] = []
    try:
        for name in os.listdir(tdir):
            if name.endswith(".jsonl"):
                age = _age(os.path.join(tdir, name), now)
                if age is not None:
                    ages.append((age, os.path.join(tdir, name)))
    except OSError:
        return None, 0, False
    if not ages:
        return None, 0, False
    ages.sort()
    newest_mtime_age, newest_path = ages[0]
    tail = _tail_lines(newest_path)
    sub_age, trailing = substantive_age_from_tail(
        tail, now=now, fallback_age=newest_mtime_age
    )
    awaiting = awaiting_user_decision(tail)
    # Another session's transcript may be substantively younger than the newest file's
    # substantive age (its mtime is an upper bound on its own substantive age) — take
    # the minimum so a genuinely-working sibling session keeps the project "alive".
    candidates = [a for a, _ in ages[1:]]
    if sub_age is not None:
        candidates.append(sub_age)
    return (min(candidates) if candidates else None), trailing, awaiting


def transcript_age(root: str, now: int) -> int | None:
    """Seconds since this project's newest SUBSTANTIVE transcript line, or ``None``
    if no transcript exists. Thin wrapper over ``transcript_activity`` kept for the
    existing callers; see there for the queue-operation exclusion (TRDD-8DR0X08A)."""
    return transcript_activity(root, now)[0]


def sweep_stale_rate_limit(root: str, *, now: int, max_age_s: int) -> bool:
    """Delete `<root>/.janitor/state/rate-limited.flag` if it is stale. Returns True if swept.

    The daemon is the ONLY actor that can do this (janitor#77 item C). The flag is cleared
    by `dispatch.py`, which runs only from a live heartbeat cron — so the project that most
    needs its flag cleared (the one whose cron died) is precisely the one that can never
    clear it. The daemon is alive when the cron is not, which is what breaks the circle.

    A `disarmed.flag` project is sacrosanct and is skipped: the user opted out, its diagnosis
    is `unarmed` regardless of the rate-limit flag, and we do not touch its files.

    Never raises. A missing flag, an unreadable mtime, or a losing unlink race are all
    "nothing to do" — the sweep is idempotent and bounded (one stat, at most one unlink).
    """
    sdir = os.path.join(root, ".janitor", "state")
    if os.path.isfile(os.path.join(sdir, state.DISARMED_FLAG)):
        return False
    flag = os.path.join(sdir, state.RATE_LIMITED_FLAG)
    try:
        mtime: int | None = int(os.stat(flag).st_mtime)
    except OSError:
        return False  # absent or unreadable — never delete what we cannot assess
    if not session_liveness.rate_limit_flag_is_stale(mtime, now, max_age_s):
        return False
    try:
        os.unlink(flag)
    except OSError:
        return False  # lost a race with dispatch.py clearing it — the same outcome
    return True


def capture_pane_text(terminal: Mapping[str, str]) -> str | None:
    """Read the CURRENT RENDERED FRAME of an instance's pane, for retry-wedge detection
    (TRDD-WKTD5JTC §1) — CC runs on the alternate screen buffer, so this is the only
    content a daemon-side probe can ever see (no scrollback exists). None when no channel
    resolves OR the read fails; the caller MUST treat None as "cannot assess", never as
    "not wedged" — the same fail-open contract every other probe in this module keeps.

    Declines the iTerm channel EARLY when `iterm-automation-blocked.flag` is set
    (TRDD-WKTD5JTC advisor correction #4): iTerm capture AND inject both ride osascript, so
    a TCC-denied launchd daemon silently empties BOTH — and `fleet_inject.fire()` would then
    falsely report the follow-up ESC as "delivered". Declining the read here means no wedge
    is ever diagnosed on that channel this beat, so no attempt is burned on an injection
    that could never have landed.
    """
    pane = terminal.get("tmux_pane", "").strip()
    if pane:
        return terminal_trigger.read_pane_text({"kind": "tmux", "pane": pane})
    sid = terminal.get("iterm_session_id", "").strip().split(":")[-1].strip()
    if sid:
        try:
            import global_state as gs  # local import — mirrors record_iterm_automation_state

            if (gs.global_state_dir() / ITERM_TCC_FLAG).exists():
                return None  # declined — proven-dead channel this beat (TCC denial)
        except Exception:  # noqa: BLE001 -- a probe fault must never break the scan
            pass
        return terminal_trigger.read_pane_text({"kind": "iterm", "session_id": sid})
    return None


_RETRY_WEDGE_STATE_FILE = "retry-wedge-episode.json"


def _read_retry_wedge_state(root: str) -> dict | None:
    """The persisted retry-wedge episode state for `root`, or None (no episode / unreadable —
    the two are indistinguishable and both correctly start `retry_wedge_state_update` fresh,
    i.e. the next poll is treated as a first sighting)."""
    path = os.path.join(root, ".janitor", "state", _RETRY_WEDGE_STATE_FILE)
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_retry_wedge_state(root: str, value: dict | None) -> None:
    """Persist (or clear, on None) the retry-wedge episode state for `root`. Best-effort —
    a write failure must never break the fleet scan; the next poll simply re-derives it."""
    path = os.path.join(root, ".janitor", "state", _RETRY_WEDGE_STATE_FILE)
    try:
        if value is None:
            os.unlink(path)
            return
        os.makedirs(os.path.dirname(path), exist_ok=True)
        state.atomic_write(path, json.dumps(value))
    except OSError:
        pass


def write_rate_limited_flag(root: str, now: int) -> None:
    """Stamp `<root>/.janitor/state/rate-limited.flag` (+ `rate-limited-since.ts`) as if
    `on-stop-failure` had fired — the DAEMON's own fallback (TRDD-WKTD5JTC §1b, empirically
    measured 2026-08-13): an ESC that breaks CC's retry-watchdog wedge fires plain `Stop`,
    NOT `on-stop-failure` (832/832 turn-ending API errors trip StopFailure; only 1/53 ESC
    interrupts do — below the 5.1% chance rate). So nothing else writes this flag on the
    retry-wedge path, and without it the wedge breaks but the session then just sits idle —
    strictly worse than the wedge, which at least made the stall visible. Mirrors
    `on-stop-failure.py`'s write exactly (same two files) so the EXISTING
    `[janitor-resume]` + OAuth-rotator recovery chain proceeds downstream unchanged.

    Best-effort: a write failure here must never break the recovery beat — the ESC itself
    is the load-bearing action; this flag is the follow-up that makes it actually resume.
    """
    sdir = os.path.join(root, ".janitor", "state")
    try:
        os.makedirs(sdir, exist_ok=True)
        Path(os.path.join(sdir, state.RATE_LIMITED_FLAG)).touch()
        state.atomic_write(os.path.join(sdir, state.RATE_LIMITED_SINCE_FILE), str(now))
    except OSError:
        pass


def diagnose_root(
    root: str,
    *,
    now: int,
    transcript_age: int | None,
    stale_s: int = STALE_S,
    server_owned: bool = False,
    terminal: Mapping[str, str] | None = None,
) -> tuple[str, str | None, int | None]:
    """Read a project's ``.janitor`` state + the session's ``transcript_age`` and
    diagnose its janitor health. Returns ``(diagnosis, recovery, dispatch_age_s)``
    — ``dispatch_age_s`` is INFORMATIONAL ONLY (dispatch.log logs notable events,
    not liveness); the diagnosis runs entirely on the transcript.

    A transcript that advanced within ``stale_s`` means the session is working OR
    its heartbeat is firing — either way alive, never flagged. A stale transcript
    means neither: stuck. An unknown transcript age (cannot locate the file) is
    treated as NOT stale — we never flag what we cannot actually assess. The
    opt-out is POSITIVE: only a ``disarmed.flag`` (written by ``/janitor-disarm``)
    makes an instance sacrosanct; a merely-absent ``heartbeat-armed-at.ts`` is a
    lapsed arm to restore, which is exactly what the user wants guarded.
    """
    sdir = os.path.join(root, ".janitor", "state")
    ldir = os.path.join(root, ".janitor", "logs")
    deliberately_unarmed = os.path.isfile(os.path.join(sdir, state.DISARMED_FLAG))
    rate_limited = os.path.isfile(os.path.join(sdir, state.RATE_LIMITED_FLAG))
    # TRDD-8DR0X08A F4: the dynamic cadence (TRDD-0QQX9H0G) legitimately demotes an
    # idle session's heartbeat to */15 or */30 — a fixed 15-min staleness window would
    # flag every such session as cron_dead BETWEEN its own healthy beats. Scale the
    # window to the cadence the session is actually ARMED at (same 3-missed-beats
    # tolerance STALE_S encodes for */5), never below the caller's floor.
    try:
        with open(os.path.join(sdir, "armed-cadence.cron"), encoding="utf-8") as fh:
            armed = fh.read()
    except OSError:
        armed = ""
    effective_stale_s = stale_threshold_for(armed, stale_s)
    transcript_stale = transcript_age is not None and transcript_age >= effective_stale_s
    # TRDD-WKTD5JTC §1: only poll the pane (a subprocess) when the FP guard the design
    # requires is already satisfied — a transcript that is NOT stale can never be a
    # retry-wedge (CC's watchdog keeps the turn alive without appending, so 1a proved
    # transcript_stale DOES trip during a real wedge). This also keeps a healthy host at
    # ≈0 captures/beat (advisor correction #4). Any prior episode is cleared the moment
    # the transcript is fresh again — the wedge already broke (or never existed here).
    # Guardrail (never touch an unarmed/server_owned instance): skip the pane poll
    # entirely for those — reading its content is a real Apple Event / tmux call and
    # the result would be discarded anyway (diagnose_instance returns unarmed/
    # server_owned before ever consulting retry_wedged).
    retry_wedged = False
    if transcript_stale and terminal and not deliberately_unarmed and not server_owned:
        pane_text = capture_pane_text(terminal)
        prev = _read_retry_wedge_state(root)
        if pane_text is None:
            # CANNOT ASSESS — `capture_pane_text` returns None for a DECLINED or FAILED read
            # (TCC-blocked iTerm, a transient tmux hiccup), and its contract says a caller must
            # never read that as "not wedged". Folding it into `current_attempt=None` did exactly
            # that: `retry_wedge_state_update` treats a missing attempt number as "the signature
            # is gone" and CLEARS the episode, so a single flaky read resets the advance-across-
            # polls counter and a genuine wedge on a flaky channel could never reach `confirmed`.
            # Leave the episode exactly as it stands and report only what it has already proven.
            retry_wedged = bool(prev and prev.get("confirmed"))
        else:
            new_state, retry_wedged = session_liveness.retry_wedge_state_update(
                prev=prev, current_attempt=session_liveness.retry_wedge_attempt(pane_text)
            )
            _write_retry_wedge_state(root, new_state)
    else:
        _write_retry_wedge_state(root, None)
    diagnosis = session_liveness.diagnose_instance(
        retry_wedged=retry_wedged,
        deliberately_unarmed=deliberately_unarmed,
        pane_alive=True,  # the caller only diagnoses processes found alive in ps
        transcript_stale=transcript_stale,
        rate_limited=rate_limited,
        version_stale=False,  # v1: cross-process version compare deferred (Group C)
        server_owned=server_owned,  # a live ai-maestro server owns this agent (TRDD-PZLVT2RN)
    )
    dispatch_age = _age(os.path.join(ldir, "dispatch.log"), now)
    return diagnosis, session_liveness.recovery_for_diagnosis(diagnosis), dispatch_age


def _run(cmd: list[str], *, timeout: int = 10) -> str:
    """Run a read-only probe; never raise. Empty string on any failure/timeout."""
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        ).stdout
    except Exception:  # noqa: BLE001 -- a probe failure must never break the scan
        return ""


def _run_probe_outcome(cmd: list[str], *, timeout: float = 10) -> tuple[str, str]:
    """Like ``_run``, but distinguishes HOW an empty result happened (TRDD-EZ3PMQYX,
    janitor#233): a nonzero exit or an unrunnable binary is ``"error"``, an exceeded
    deadline is ``"timeout"``, and a clean exit is ``"ok"`` whatever the stdout looks
    like (the caller decides "empty" from the parsed result, since an ``"ok"`` run can
    legitimately return nothing to parse).

    ``_run`` alone cannot support this: it swallows both a nonzero return code (no
    ``check=True``) and every exception into the SAME blank string, so "the Apple Event
    was denied", "osascript hung past the deadline", and "osascript is not installed"
    were all indistinguishable at the call site — the exact ambiguity the iTerm-blocked
    alarm has had to hedge around with two-cause language ever since. Never raises.
    """
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", "timeout"
    except Exception:  # noqa: BLE001 -- a probe failure must never break the scan
        return "", "error"
    return result.stdout, ("ok" if result.returncode == 0 else "error")


def _cwd_of(pid: int) -> str | None:
    """The working directory of ``pid`` via ``lsof`` (macOS-friendly), or None."""
    for line in _run(
        ["lsof", "-a", "-p", str(pid), "-d", "cwd", "-Fn"], timeout=8
    ).splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def _aimaestro_agents(env: Mapping[str, str] | None = None) -> tuple[str | None, list, bool]:
    """Resolve the ai-maestro CLI and fetch its agent list ONCE per ``gather_fleet()``
    call — never per-instance, an N-instance scan must not shell out N times.
    Best-effort: returns ``(None, [], False)`` on ANY failure (CLI absent, server down,
    malformed JSON) so a host without ai-maestro installed/running never breaks the
    fleet scan. Reuses ``terminal_trigger``'s resolver/runner — the SAME ones
    self-trigger's ``_try_ai_maestro_send`` uses — instead of re-implementing CLI
    discovery. (TRDD-ME8V2YJF follow-up)

    The third element is ``list_ok`` — whether the server ANSWERED the list call
    (parsed JSON, even an empty registry). It matters because the list is fetched off
    the server's own HTTP API, so ``list_ok`` doubles as this scan's live-server proof
    and its False is the trigger for the cached-roots exclusion fallback
    (TRDD-PZLVT2RN — ``harness_backend.instance_is_server_owned``).
    """
    e = env if env is not None else os.environ
    cli = terminal_trigger._resolve_aimaestro_cli(e)
    if not cli:
        return None, [], False
    proc = terminal_trigger._run_aimaestro_cli(cli, ["list", "--json"], env=e, timeout=5.0)
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return cli, [], False
    try:
        agents = json.loads(proc.stdout)
    except ValueError:
        return cli, [], False
    if isinstance(agents, dict) and isinstance(agents.get("agents"), list):
        agents = agents["agents"]
    return cli, (agents if isinstance(agents, list) else []), isinstance(agents, list)


def tag_aimaestro_identity(
    terminal: dict[str, str], *, agents: list, cli: str | None, root: str | None
) -> None:
    """Extend a resolved ``terminal`` identity dict IN PLACE with the ai-maestro CLI
    channel when this instance's ``root`` matches an ai-maestro agent's
    ``workingDirectory``. Pure — ``agents``/``cli`` are the values ``_aimaestro_agents``
    already fetched ONCE for the whole scan; this just does the per-instance match via
    ``terminal_trigger.match_agent_tmux`` (the SAME pure matcher self-trigger uses,
    keyed on this instance's project root instead of ``os.getcwd()``). Stores
    ``aimaestro_session`` — an ai-maestro TMUX SESSION NAME (e.g. ``agent-foo``), NOT
    a ``tmux_pane`` id — alongside the resolved CLI path, so ``fleet_restart._command_plan``
    has both pieces it needs to build the CLI argv. No-op (leaves ``terminal``
    untouched) when ``cli``/``agents``/``root`` are falsy or nothing matches, so a host
    without ai-maestro running never grows a dangling identity key. (TRDD-ME8V2YJF follow-up)
    """
    if not cli or not agents or not root:
        return
    session = terminal_trigger.match_agent_tmux(agents, [root])
    if session:
        terminal["aimaestro_session"] = session
        terminal["aimaestro_cli"] = cli


def tag_linux_gui_identity(terminal: dict[str, str], *, channel: str | None) -> None:
    """Extend a resolved ``terminal`` identity dict IN PLACE with the Linux
    GUI-terminal channel (``wtype``/``xdotool``) — but ONLY when neither tmux nor
    iTerm already resolved a channel for this instance. ``wtype``/``xdotool`` have no
    per-window target (they type into whichever window has focus — see
    ``terminal_trigger.build_wtype_steps``), so this is deliberately the LAST-RESORT
    tag, mirroring ``fleet_restart._command_plan``'s fallback order
    (tmux -> iterm -> aimaestro -> linux-gui): tagging it unconditionally would
    misrepresent an already-reachable instance as needing the imprecise
    focused-window channel. No-op when ``channel`` is falsy or a channel already
    resolved. (TRDD-ME8V2YJF follow-up)
    """
    if channel and "tmux_pane" not in terminal and "iterm_session_id" not in terminal:
        terminal["linux_gui_channel"] = channel


def gather_fleet(*, now: int, sweep_stale_rate_limit_s: int | None = None) -> list[Instance]:
    """Scan the whole host: every running claude instance whose cwd resolves to a
    ``.janitor`` project, with its terminal (by TTY) and diagnosed janitor health.

    Pure-ish I/O: one ``ps``, one ``tmux``, at most one ``osascript`` (only if
    iTerm is actually running — so we NEVER relaunch a closed iTerm), at most one
    ai-maestro CLI ``list --json`` (only if the CLI resolves), and one ``lsof`` per
    claude pid. Instances outside a janitor project are skipped. The ai-maestro
    agent list and the Linux GUI channel are each resolved ONCE for the whole scan
    (never per-instance) and then tagged onto every matching instance's terminal
    identity — the same fan-out shape as ``iterm_by_tty``/``tmux_by_tty`` below.
    (TRDD-ME8V2YJF follow-up)

    ``sweep_stale_rate_limit_s`` is the ONLY way this function writes to disk, and it
    defaults to None (read-only). Pass a window and each root's stale ``rate-limited.flag``
    is deleted BEFORE it is diagnosed, so the same beat sees the corrected `cron_dead`
    instead of a false `frozen` (janitor#77 item C). The daemon passes it; ``fleet_status``
    must not — a status table that mutates the thing it reports on is a status table nobody
    can trust.
    """
    ps_text = _run(["ps", "-eo", "pid=,tty=,command="])
    claude = parse_ps_claude(ps_text)
    tmux_by_tty = parse_tmux_panes(
        _run(["tmux", "list-panes", "-a", "-F", "#{pane_tty} #{pane_id}"])
    )
    iterm_by_tty: dict[str, str] = {}
    iterm_running = "iTerm" in ps_text
    # `osascript_outcome` classifies HOW the call went, not just what it returned
    # (TRDD-EZ3PMQYX, janitor#233): "error" (nonzero exit / unrunnable), "timeout"
    # (exceeded its deadline), or "ok" (clean exit, whatever the stdout held). Only
    # meaningful when `iterm_running` — osascript is never invoked otherwise.
    osascript_outcome = "ok"
    if iterm_running:  # only drive osascript when iTerm is already up
        osascript_stdout, osascript_outcome = _run_probe_outcome(
            ["osascript", "-e", _ITERM_TTY_OSASCRIPT], timeout=15
        )
        iterm_by_tty = parse_iterm_sessions(osascript_stdout)
    # iTerm up + zero sessions enumerated = the Apple Event was blocked (TRDD-VQ4LX7ND).
    # Record it so the heartbeat can tell the human ONCE, instead of the daemon skipping
    # every frozen iTerm instance in silence forever. Self-clears the moment the grant
    # lands and sessions come back.
    blocked = iterm_automation_blocked(iterm_running=iterm_running, sessions=iterm_by_tty)
    # A clean exit (`"ok"`) that still enumerated zero sessions means the CALL succeeded
    # and simply had nothing to report — that is what the alarm names `"empty"`, distinct
    # from the call itself failing. An `"error"`/`"timeout"` outcome carries as-is.
    probe_outcome = "empty" if (blocked and osascript_outcome == "ok") else (
        osascript_outcome if blocked else ""
    )
    second_view = ""
    if blocked:
        # The INDEPENDENT SECOND VIEW (TRDD-DFKEXO79, janitor#92): osascript's zero alone
        # cannot distinguish a denied/hung channel from a genuinely empty host — a denial
        # returning empty writes no error either. `claude agents --json` needs no session
        # and no Automation grant, so its answer discriminates. Only probed on the RARE
        # blocked path (one ~1s subprocess), never on a healthy scan. A failed probe is
        # recorded AS a failed probe — "cannot check" must never read as "checked, empty".
        try:
            import cli_agent_roster  # noqa: PLC0415 -- local, like global_state below

            rows, why = cli_agent_roster.fetch_agents()
            second_view = (
                f"probe-failed:{why}"
                if why
                else cli_agent_roster.second_view_verdict(
                    osascript_sessions=0, cli_rows_for_host=len(rows)
                )
            )
        except Exception:  # noqa: BLE001 -- the second view must never break a scan
            second_view = ""
    record_iterm_automation_state(blocked, second_view=second_view, probe_outcome=probe_outcome)
    aimaestro_cli, aimaestro_agents, aimaestro_list_ok = _aimaestro_agents()
    # The harness-exclusion inputs (TRDD-PZLVT2RN): a SUCCESSFUL list refreshes the
    # last-known agent-roots cache; a FAILED one (server down OR hiccup — we cannot
    # tell) falls back to that cache so the exclusion HOLDS instead of the daemon
    # actuating on agents it merely lost sight of. The operator override can force
    # adoption. All policy lives in harness_backend.instance_is_server_owned.
    aimaestro_override = harness_backend.server_state_override()
    if aimaestro_list_ok and aimaestro_agents:
        harness_backend.remember_agent_roots(harness_backend.agent_workdirs(aimaestro_agents))
    cached_agent_roots = (
        harness_backend.recall_agent_roots() if (aimaestro_cli and not aimaestro_list_ok) else []
    )
    linux_gui_channel = (
        terminal_trigger._resolve_linux_gui_channel(os.environ)
        if sys.platform.startswith("linux")
        else None
    )

    fleet: list[Instance] = []
    for pid, tty, cmd in claude:
        root = find_janitor_root(_cwd_of(pid))
        if not root:
            continue
        tr_age, trailing_enqueues, awaiting_user = transcript_activity(root, now)
        active = tr_age is not None and tr_age < ACTIVE_FRESH_S
        if sweep_stale_rate_limit_s is not None and sweep_stale_rate_limit(
            root, now=now, max_age_s=sweep_stale_rate_limit_s
        ):
            # BEFORE diagnose_root, so this beat already sees the honest diagnosis.
            state.log_line(
                "daemon",
                f"session-liveness: swept stale rate-limited.flag in {root} "
                f"(older than {sweep_stale_rate_limit_s}s) — restores cron_dead over frozen",
            )
        terminal = session_liveness.resolve_terminal_for_tty(
            tty, iterm_by_tty=iterm_by_tty, tmux_by_tty=tmux_by_tty
        )
        # Tag BEFORE diagnosing (reordered by TRDD-PZLVT2RN): the diagnosis must be able
        # to see whether a live server owns this instance, and the tag is that evidence.
        tag_aimaestro_identity(terminal, agents=aimaestro_agents, cli=aimaestro_cli, root=root)
        tag_linux_gui_identity(terminal, channel=linux_gui_channel)
        server_owned = harness_backend.instance_is_server_owned(
            tagged="aimaestro_session" in terminal,
            root=root,
            cli_present=aimaestro_cli is not None,
            list_ok=aimaestro_list_ok,
            cached_roots=cached_agent_roots,
            override=aimaestro_override,
            under_agents_home=harness_backend.root_under_agents_home(root),
        )
        diagnosis, recovery, dispatch_age = diagnose_root(
            root, now=now, transcript_age=tr_age, server_owned=server_owned, terminal=terminal
        )
        fleet.append(
            Instance(
                pid=pid,
                command=cmd,
                tty=tty,
                project_root=root,
                terminal=terminal,
                diagnosis=diagnosis,
                recovery=recovery,
                dispatch_age_s=dispatch_age,
                active=active,
                transcript_age_s=tr_age,
                trailing_enqueues=trailing_enqueues,
                awaiting_user=awaiting_user,
            )
        )
    if blocked:
        # Only known once every instance in THIS scan has been diagnosed — see
        # `record_iterm_rescue_warranted`'s docstring for why this is a separate,
        # later patch rather than a field on the early `record_iterm_automation_state`
        # write above (TRDD-9PDH8G0W).
        record_iterm_rescue_warranted(iterm_rescue_warranted(fleet))
    return fleet


def _main() -> int:
    """Live diagnostic: print the fleet, one line per instance. Read-only."""
    import time

    fleet = gather_fleet(now=int(time.time()))
    broken = [i for i in fleet if i.recovery is not None]
    print(f"fleet: {len(fleet)} janitor-project claude instance(s), {len(broken)} need recovery\n")
    for inst in fleet:
        chan = (
            "tmux:" + inst.terminal["tmux_pane"]
            if "tmux_pane" in inst.terminal
            else "iterm:" + inst.terminal["iterm_session_id"]
            if "iterm_session_id" in inst.terminal
            else "UNREACHABLE"
        )
        age = f"{inst.dispatch_age_s // 60}m" if inst.dispatch_age_s is not None else "none"
        rec = inst.recovery or "—"
        print(f"  pid {inst.pid:>6}  {inst.diagnosis:<16} → {rec:<9} [{chan}]  dispatch {age}")
        print(f"          {inst.project_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
