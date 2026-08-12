"""External (ZERO model turn) handoff-and-clear — policy + composition (TRDD-PXP08ZQC).

The in-model lever (`dispatch._phase_idle_clear_nudge` → `/janitor-handoff-and-clear`) works,
but it costs what it is trying to save: the handoff is authored BY THE MODEL, so an abandoned
session pays a full turn on its huge context just to write the note that lets it shrink. This
module is the decision + composition half of doing the same thing from OUTSIDE the model — the
typist half already exists (`clear_trigger.py`'s verified injection chain).

Split exactly like the rest of the codebase: everything here is PURE (all runtime facts are
injected) so the gate is unit-testable without a live session. The I/O gatherer and the firing
live in `scripts/external_handoff_clear.py`.

## WHY THE TRIGGER IS NOT "the cache is expired"

The card was written as *idle + cache-expired + over-threshold*. Taken literally that lever is
DEAD on the machine it was written for, measured 2026-08-06: `ttl-regime.json` reports a probed
60-minute cache TTL and the armed cadence is `*/5 * * * *`, so a fire every 5 minutes keeps the
cache permanently warm and `cache_expired` is never true. That is the same shape
`cold_cache_compact` burned on twice — "a threshold high enough to never be met is a feature that
does not exist".

The card's *intent* is sound once expressed correctly: what costs money is not that the cache is
cold, it is that **the next fire will pay a cache MISS**. So trigger (a) asks exactly that —
`age_since_last_turn + seconds_until_next_fire >= ttl`. It fires in the idle gap BEFORE the
expensive fire, which is the timing contract the card asks for.

Trigger (b) is the owner's 2026-08-04 rule (nothing but beats for >= 1 h). It is what actually
bites in the warm case: a warm fire on a 460k context still re-reads ~10M weighted tokens, and
177.7M of one 7-day window went to heartbeat fires alone. Neither trigger subsumes the other, so
the gate ORs them and NAMES the one that fired — a lever that cannot say why it acted is one
nobody can tune.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import state  # noqa: E402  -- sibling lib

# --- config knobs (userConfig → env; read via the shared coercers) ----------
ENABLED_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED"
MIN_CONTEXT_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_MIN_CONTEXT_TOKENS"
HEADROOM_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_HEADROOM_SECONDS"
USE_LLM_EXT_ENV = "CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_USE_LLM_EXT"

# DEFAULT OFF, deliberately, unlike its in-model sibling. `/clear` is unrecoverable, and this
# path fires it with NO model turn in front of it — nothing reads the handoff back before the
# context is gone. It ships opt-in until the card's "one observed end-to-end unattended cycle"
# acceptance box is ticked; flipping this default is that box's payoff, not its precondition.
DEFAULT_ENABLED = False
# Low on purpose. Size is NOT the reason to clear (owner directive 2026-08-04 dropped it from the
# in-model gate); it is only a floor below which clearing buys nothing measurable. Anything under
# this is cheap to keep, so leave it alone.
DEFAULT_MIN_CONTEXT_TOKENS = 150_000
# The chain types /clear, waits for the fresh session, then types the bootstrap. Firing with less
# than this before the next cron fire means the fire lands mid-chain — survivable (the injector
# waits for a free pane) but it wastes the very fire we were trying to prevent.
DEFAULT_HEADROOM_SECONDS = 60
# The prompt-cache TTL used when `ttl-regime.json` is absent/unreadable. 5 minutes is the
# platform's standard TTL and the SHORT side, so an unknown TTL biases toward "the next fire will
# miss" → toward acting. That is the safe direction here: the cost of a spurious clear on an
# abandoned session is one re-read of a link-only handoff.
DEFAULT_TTL_MINUTES = 5

_TTL_REGIME_FILE = "ttl-regime.json"

# Trigger names — returned in the verdict and written to the log, so a fire can always be
# attributed to the rule that caused it.
TRIGGER_NEXT_FIRE_MISSES = "next-fire-misses"
TRIGGER_LONG_IDLE = "long-idle"

__all__ = [
    "ClearVerdict",
    "compose_handoff",
    "compose_template_handoff",
    "enabled",
    "llm_ext_data_dir",
    "recent_messages",
    "run_llm_ext_summary",
    "headroom_seconds",
    "min_context_tokens",
    "next_fire_misses_cache",
    "read_ttl_minutes",
    "seconds_until_next_fire",
    "should_clear_externally",
    "terminal_from_record",
    "use_llm_ext",
]


def enabled() -> bool:
    return state.is_truthy_env(ENABLED_ENV, DEFAULT_ENABLED)


def min_context_tokens() -> int:
    return state.coerce_int(os.environ.get(MIN_CONTEXT_ENV), DEFAULT_MIN_CONTEXT_TOKENS)


def headroom_seconds() -> int:
    return state.coerce_int(os.environ.get(HEADROOM_ENV), DEFAULT_HEADROOM_SECONDS)


def use_llm_ext() -> bool:
    return state.is_truthy_env(USE_LLM_EXT_ENV, True)


# Bounded by US, not by the CLI. llm-externalizer 12.0.0 shipped with an unbounded body-read:
# its abort was disarmed once headers arrived, so its own timeout covered time-to-first-byte
# only and a stalled generation hung forever. A handoff composer that can hang is worse than
# one that degrades, because the `/clear` it precedes never happens and the session simply
# stops.
LLM_EXT_TIMEOUT_S = 240


def llm_ext_data_dir(binary: str) -> str:
    """The `CLAUDE_PLUGIN_DATA` value llm-externalizer needs, DERIVED from its own path.

    Without this set the launcher dies before doing any work:

        FATAL: native module 'better-sqlite3' is missing AND CLAUDE_PLUGIN_DATA is unset.
        The launcher cannot self-install without a persistent data directory.

    A janitor hook or detached child is exactly that context. Worse, the value is ANOTHER
    plugin's data dir and this host carries two candidates
    (`llm-externalizer-emasoft-plugins`, `llm-externalizer-inline`), so it cannot be guessed
    and picking wrong self-installs a second copy of a native module.

    Derived rather than hardcoded: the harness lays plugins out as
    `…/cache/<marketplace>/<plugin>/<version>/bin/llm-ext` and names the data dir
    `<plugin>-<marketplace>` — the same convention as this plugin's own
    `ai-maestro-janitor-ai-maestro-plugins`. So the binary that will actually run tells us
    which store belongs to it, and a reinstall under a different marketplace keeps working.
    Returns "" when the path does not match, so the caller degrades instead of inventing one.
    """
    parts = Path(binary).resolve().parts
    if "cache" not in parts:
        return ""
    i = parts.index("cache")
    if len(parts) < i + 3:
        return ""
    marketplace, plugin = parts[i + 1], parts[i + 2]
    data = Path.home() / ".claude" / "plugins" / "data" / f"{plugin}-{marketplace}"
    return str(data) if data.is_dir() else ""


def run_llm_ext_summary(
    transcript: str,
    *,
    timeout_s: int = LLM_EXT_TIMEOUT_S,
    runner: Any = None,
) -> str | None:
    """The session summary as TEXT, or None on any failure. NEVER raises.

    `--stdout` is used deliberately: without it stdout carries the report PATH and we would
    read a file the CLI may still be writing. Banner, progress and errors go to stderr, so
    stdout is the summary alone.

    The exit code is read from the process, never through a pipe — `llm-ext … | head` reports
    `head`'s status and the launcher's own failure becomes invisible.

    Returning None (rather than raising or returning a partial) is what makes the caller's
    degrade-to-template path reachable: every failure mode of a young CLI — missing binary,
    unresolvable data dir, non-zero exit, timeout, empty output — arrives here as the same
    answer, and the handoff still gets written.
    """
    binary = shutil.which("llm-ext")
    if not binary or not transcript or not Path(transcript).is_file():
        return None
    data_dir = llm_ext_data_dir(binary)
    if not data_dir:
        return None
    env = dict(os.environ, CLAUDE_PLUGIN_DATA=data_dir)
    run = runner or subprocess.run
    try:
        proc = run(
            [binary, "session-summary", "--stdout", "--transcript", transcript],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            env=env,
            check=False,
        )
    except Exception:  # noqa: BLE001 - a handoff must survive ANY subprocess failure
        return None
    if getattr(proc, "returncode", 1) != 0:
        return None
    out = (getattr(proc, "stdout", "") or "").strip()
    return out or None


def recent_messages(transcript: str, *, limit: int = 12) -> list[str]:
    """The last `limit` conversation turns as `ROLE: text` lines. ZERO model tokens.

    Read straight off the JSONL, so this part of the payload costs nothing and cannot be
    paraphrased — which matters because it is the part a resuming session checks its own
    understanding against. Tool payloads and thinking blocks are skipped: they are the bulk of
    a transcript and the least useful thing to restore into a context we are trying to empty.
    """
    out: list[str] = []
    try:
        with Path(transcript).open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = rec.get("message") or {}
                role = msg.get("role") or rec.get("type") or ""
                if role not in ("user", "assistant"):
                    continue
                content = msg.get("content")
                if isinstance(content, list):
                    text = " ".join(
                        c.get("text", "") for c in content
                        if isinstance(c, dict) and c.get("type") == "text"
                    )
                else:
                    text = str(content or "")
                text = " ".join(text.split())
                if text:
                    out.append(f"{role.upper()}: {text}")
    except OSError:
        return []
    return out[-limit:]


def compose_handoff(
    inputs: HandoffInputs,
    *,
    now_iso: str,
    summary: str | None,
    tail: Sequence[str] = (),
    max_bytes: int = 8192,
) -> str:
    """The full injected payload: scriptable facts + llm-ext summary + a TRUNCATED tail.

    THE HARD CONSTRAINT (owner, 2026-08-12): the injection must not refill the context it was
    built to empty. A handoff that restores a large payload at session start pays back the
    cache-write we just avoided, one turn later — so the WHOLE payload carries one budget, not
    one per part. Three "small" parts add up.

    Priority under that single budget, and the order is the design:
      1. the scriptable facts — small, load-bearing, and the part that must never be
         paraphrased, so it is composed FIRST and always survives;
      2. the llm-ext summary — high value, absent whenever the CLI failed;
      3. the message tail — the ELASTIC part, trimmed from the OLDEST end because a resuming
         session needs the most recent exchanges.

    Truncation is STATED, never silent: a clipped tail reads as a complete record, which is
    worse than an explicitly short one — the reader cannot tell that anything is missing.
    """
    facts = compose_template_handoff(inputs, now_iso=now_iso, max_bytes=max_bytes)
    used = len(facts.encode("utf-8"))

    # ALLOCATION ORDER IS NOT OUTPUT ORDER. The tail is allocated BEFORE the summary even
    # though it prints last, because the summary is unbounded (7 KB in practice) and would
    # otherwise consume the whole remainder, leaving a handoff with no recent turns at all —
    # measured, after the first version did exactly that. The owner asked for the latest
    # messages explicitly, so the tail gets a guaranteed slice and the summary takes what is
    # left. Both remain elastic; only the scriptable facts are unconditional.
    tail_note_max = " — 9999 earlier message(s) dropped"
    tail_header = f"\n## Recent turns{tail_note_max}\n\n"
    tail_budget = min(max_bytes // 3, max(0, max_bytes - used - 200))
    kept: list[str] = []
    if tail and tail_budget > len(tail_header.encode("utf-8")):
        spent = len(tail_header.encode("utf-8"))
        for line in reversed(list(tail)):  # the OLDEST end is what gets dropped
            cost = len(line.encode("utf-8")) + 1
            if spent + cost > tail_budget:
                break
            kept.append(line)
            spent += cost
        kept.reverse()
        used += spent

    summary_part = ""
    if summary:
        head = "\n## Session summary (llm-externalizer, $0)\n\n"
        # The truncation NOTICE is charged before slicing, not appended after. Appending it to
        # a body already filled to `room` overran by exactly its own length every time
        # (measured: +38 at every budget — a constant offset is the signature of a fixed-size
        # string added outside the accounting).
        notice = "\n\n_(summary truncated to fit the handoff budget)_"
        room = max_bytes - used - len(head.encode("utf-8")) - len(notice.encode("utf-8")) - 8
        if room > 400:
            raw = summary.encode("utf-8")
            body = raw[:room].decode("utf-8", "ignore").rstrip()
            if len(raw) > room:
                body += notice
            summary_part = head + body

    parts = [facts]
    if summary_part:
        parts.append(summary_part)
    if kept:
        dropped = len(tail) - len(kept)
        note = f" — {dropped} earlier message(s) dropped" if dropped else ""
        parts.append(f"\n## Recent turns{note}\n\n" + "\n".join(kept))
    return "\n".join(parts)


# --- pure policy ------------------------------------------------------------


def seconds_until_next_fire(cron: str, now: int) -> int | None:
    """Seconds from `now` until the next `*/N * * * *` fire, or None when the cron is not that
    shape. PURE apart from reading the LOCAL timezone (cron fires on local wall-clock).

    Only the minute-step form the janitor arms is understood — anything else returns None so the
    caller falls back to "unknown headroom" rather than inventing a schedule from a cron it
    cannot actually read (the same contract as `orphaned_resume.cadence_seconds`).

    The wrap is computed over the real minute-of-hour set, not by adding the step: cron's `*/7`
    fires at minutes 0,7,…,56 and then 0, a FOUR-minute gap. `cur_min + step` would report 7
    there and we would think we had headroom we do not have.
    """
    field_min = (cron or "").strip().split(" ")[0] if cron else ""
    if not field_min.startswith("*/"):
        return None
    step_raw = field_min[2:]
    if not step_raw.isdigit():
        return None
    step = int(step_raw)
    if step <= 0 or step > 59:
        return None
    tm = time.localtime(now)
    fire_minutes = [m for m in range(60) if m % step == 0]
    later = [m for m in fire_minutes if m > tm.tm_min]
    if later:
        minutes_ahead = later[0] - tm.tm_min
    else:
        minutes_ahead = (60 - tm.tm_min) + fire_minutes[0]
    return minutes_ahead * 60 - tm.tm_sec


def next_fire_misses_cache(
    *,
    last_turn_age_s: int | None,
    seconds_to_next_fire: int | None,
    ttl_minutes: int,
) -> bool:
    """PURE. Will the NEXT heartbeat fire land on an EXPIRED prompt cache (and so pay the full
    cache-creation write on this session's whole context)?

    This is the card's trigger, expressed as the question that actually costs money. Asking
    instead whether the cache is *already* cold makes the lever unreachable whenever the cadence
    is faster than the TTL — which is the normal, healthy configuration (see the module
    docstring's measurement).

    Unknown inputs return False: an unknown schedule or an unmeasurable transcript is not
    evidence that a miss is coming, and the long-idle trigger still covers the abandoned case.
    """
    if last_turn_age_s is None or seconds_to_next_fire is None:
        return False
    if ttl_minutes <= 0:
        return False
    return (last_turn_age_s + seconds_to_next_fire) >= ttl_minutes * 60


@dataclass(frozen=True)
class ClearVerdict:
    """Whether to clear, which rule decided it, and a human-readable why.

    `why` is populated on BOTH branches on purpose. A refusal that cannot explain itself is how
    a silently-dead lever looks from the outside, and this project has shipped that twice.
    """

    fire: bool
    trigger: str = ""
    why: str = ""


def should_clear_externally(
    *,
    idle_seconds: int | None,
    last_turn_age_s: int | None,
    ttl_minutes: int,
    seconds_to_next_fire: int | None,
    context_tokens: int | None,
    min_context: int,
    min_idle_s: int,
    headroom_s: int,
    user_present: bool,
    active_waiting: bool,
    in_cooldown: bool,
) -> ClearVerdict:
    """PURE. The whole external-clear decision, with the deciding rule named.

    Vetoes, in the order they are cheapest to establish:

      * `in_cooldown`    — a clear already fired recently. Shared with the in-model lever via
        `cold_cache_compact`'s `idle-clear-fired.ts`, so whichever path fires first stands the
        other down. That sharing IS the coexistence contract while both exist.
      * `user_present` / `active_waiting` — somebody is typing in this pane, or a resume /
        background agent is in flight. `/clear` is unrecoverable; neither is an abandoned session.
      * `idle_seconds is None` — an UNKNOWN idle age must never authorize a destructive action.
        Note the deliberate asymmetry with `context_tokens`, below.
      * headroom — a fire is imminent, so the chain would be typing into a session mid-turn.
        Wait for the next gap; nothing is lost, the gap recurs every cadence period. An UNKNOWN
        headroom (a cron shape we cannot read) does NOT veto — that would make an unreadable
        cron silently disable the lever.

    Then the two triggers, OR'd (see the module docstring for why neither subsumes the other).

    `context_tokens is None` is NOT a veto, and that is a correction, not an oversight: the
    unknown-context veto is exactly what silently disabled `should_clear_when_long_idle` for
    every session whose transcript could not be measured (owner directive 2026-08-04). An
    unmeasurable context skips the size clause and the idle/miss terms decide alone.
    """
    if in_cooldown:
        return ClearVerdict(False, why="cooldown")
    if user_present:
        return ClearVerdict(False, why="user-present")
    if active_waiting:
        return ClearVerdict(False, why="active-waiting")
    if idle_seconds is None:
        return ClearVerdict(False, why="idle-unknown")
    if seconds_to_next_fire is not None and seconds_to_next_fire < headroom_s:
        return ClearVerdict(
            False, why=f"no-headroom ({seconds_to_next_fire}s < {headroom_s}s to next fire)"
        )
    if context_tokens is not None and context_tokens < min_context:
        return ClearVerdict(
            False, why=f"context {context_tokens} < {min_context} — nothing worth reclaiming"
        )

    if next_fire_misses_cache(
        last_turn_age_s=last_turn_age_s,
        seconds_to_next_fire=seconds_to_next_fire,
        ttl_minutes=ttl_minutes,
    ):
        return ClearVerdict(
            True,
            TRIGGER_NEXT_FIRE_MISSES,
            f"next fire lands {last_turn_age_s}+{seconds_to_next_fire}s after the last turn, "
            f"past the {ttl_minutes}min cache TTL — it would pay a full miss",
        )
    if idle_seconds >= min_idle_s:
        return ClearVerdict(
            True,
            TRIGGER_LONG_IDLE,
            f"nothing but heartbeats for {idle_seconds}s (>= {min_idle_s}s)",
        )
    return ClearVerdict(
        False, why=f"idle {idle_seconds}s < {min_idle_s}s and the next fire is still warm"
    )


def terminal_from_record(record: Mapping[str, str]) -> dict[str, str]:
    """PURE adapter: the FLEET-shaped pane identity a session records at start →
    the `terminal_trigger` shape (`kind` + channel key).

    Two dict shapes for one concept exist in this codebase and they are NOT interchangeable:
    `session_liveness.capture_terminal_identity` / `fleet_restart.recorded_terminal` emit
    `{iterm_session_id, tmux_pane}`, while `terminal_trigger` and `clear_trigger._this_terminal`
    consume `{kind, pane|session_id}`. Handing the former straight to the latter yields
    `kind=""`, which every builder treats as "unsupported channel" — a silent no-op.

    tmux is preferred over iTerm for the same reason `_this_terminal()` prefers it: its pane can
    be read back cheaply, which is what lets the chain VERIFY a command before submitting it.

    `ITERM_SESSION_ID` is recorded verbatim and is `<tty>:<UUID>`; the UUID must be split off
    here or `clear_trigger._UUID_RE` rejects the whole string and refuses to build the osascript.
    """
    pane = (record.get("tmux_pane") or "").strip()
    if pane:
        return {"kind": "tmux", "pane": pane}
    iterm = (record.get("iterm_session_id") or "").strip()
    if iterm:
        return {"kind": "iterm", "session_id": iterm.split(":")[-1].strip()}
    return {"kind": "unknown"}


# --- best-effort readers (never raise) --------------------------------------


def read_ttl_minutes(state_dir: Path) -> int:
    """The probed prompt-cache TTL the dispatcher cached, or `DEFAULT_TTL_MINUTES`.

    `ttl-regime.json` was written by the dynamic-cadence phase's TTL probe, retired by
    TRDD-BRHJHWW0 — nothing writes this file any more, so this reader now always falls
    back to `DEFAULT_TTL_MINUTES`. Left in place (rather than deleted) because a future
    probe could still populate the same file, and a watcher that runs outside the model
    has no business spending a subprocess on a probe of its own.
    """
    import json  # noqa: PLC0415 -- only this reader needs it

    try:
        data = json.loads((state_dir / _TTL_REGIME_FILE).read_text(encoding="utf-8"))
        minutes = int(data["minutes"])
    except (FileNotFoundError, OSError, ValueError, KeyError, TypeError):
        return DEFAULT_TTL_MINUTES
    return minutes if minutes > 0 else DEFAULT_TTL_MINUTES


# --- the zero-token handoff (template fallback) ------------------------------


@dataclass
class HandoffInputs:
    """Everything the template composer needs, already gathered from disk.

    A dataclass rather than a pile of keyword args because the llm-ext composer consumes the
    same inputs — it is handed these PATHS (never their contents; `use-llm-externalizer.md`),
    and this template is what runs when llm-ext is absent or fails.
    """

    cards: Sequence[tuple[str, str, str]] = field(default_factory=list)  # (id, column, title)
    commits: Sequence[tuple[str, str]] = field(default_factory=list)  # (sha, subject)
    findings: Sequence[str] = field(default_factory=list)
    memory_dir: str = ""
    trigger: str = ""
    idle_seconds: int | None = None
    context_tokens: int | None = None


def compose_template_handoff(inputs: HandoffInputs, *, now_iso: str, max_bytes: int = 4096) -> str:
    """PURE. Build a link-only handoff from on-disk facts, with ZERO model tokens.

    It must satisfy `clear_trigger.check_handoff_concise` BY CONSTRUCTION, because the thing it
    is handed to is unrecoverable and nobody reviews it first:
      * under `max_bytes` — enforced by trimming the tail of each list (see below), not hoped for;
      * carries a reference — the `memgrep recall` line is unconditional, so even a handoff with
        no cards, no commits and no findings still points at the payload store;
      * no fenced blocks at all — so the `inlined-block` check cannot trip.

    Trimming drops list ITEMS from the tail rather than truncating the text mid-line: a handoff
    cut mid-sentence can leave a half-written TRDD id, which reads as a real pointer and resolves
    to nothing. Losing a whole low-priority line is recoverable; a corrupted pointer is not.
    """
    cards = list(inputs.cards)
    commits = list(inputs.commits)
    findings = list(inputs.findings)

    def render(n_cards: int, n_commits: int, n_findings: int) -> str:
        idle_h = "unknown" if inputs.idle_seconds is None else f"~{inputs.idle_seconds // 3600}h"
        ctx = "unknown" if inputs.context_tokens is None else f"~{inputs.context_tokens // 1000}k"
        out = [
            f"# Handoff — {now_iso} (auto-composed, no model turn — TRDD-PXP08ZQC)",
            "",
            f"Written by the janitor's EXTERNAL watcher, not by the model: trigger "
            f"`{inputs.trigger}`, idle {idle_h}, context {ctx}. Link-only by construction — "
            "every pointer below is resolved on demand, nothing is inlined.",
            "",
            "## NEXT ACTION (one step, runnable)",
            "",
            "Read the `## STATE` block of the first in-flight card below, then continue its "
            "NEXT ACTION. A card's STATE block is authoritative; this handoff is only an index.",
        ]
        if cards[:n_cards]:
            out += ["", "## In-flight cards (open work)", ""]
            out += [f"- TRDD-{cid} (`{col}`) — {title}" for cid, col, title in cards[:n_cards]]
        if commits[:n_commits]:
            out += ["", "## Recent commits (the WHY lives in the messages — `git show <sha>`)", ""]
            out += [f"- {sha} {subject}" for sha, subject in commits[:n_commits]]
        if findings[:n_findings]:
            out += ["", "## Open findings", ""]
            out += [f"- {f}" for f in findings[:n_findings]]
        recall_dir = inputs.memory_dir or ".claude/project/memory"
        out += [
            "",
            "## Recall",
            "",
            f'Deep knowledge is in the wiki, not here: `memgrep recall "<symptom>" {recall_dir}`.',
            "",
        ]
        return "\n".join(out)

    n_cards, n_commits, n_findings = len(cards), len(commits), len(findings)
    text = render(n_cards, n_commits, n_findings)
    # Drop the least load-bearing section first (findings are re-derivable from the ledger every
    # session; commits from git; the CARDS are the only thing that says what was being worked on).
    while len(text.encode("utf-8")) > max_bytes and (n_findings or n_commits or n_cards > 1):
        if n_findings:
            n_findings -= 1
        elif n_commits:
            n_commits -= 1
        else:
            n_cards -= 1
        text = render(n_cards, n_commits, n_findings)
    return text
