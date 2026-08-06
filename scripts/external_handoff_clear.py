#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""External (ZERO model turn) handoff-and-clear — the watcher (TRDD-PXP08ZQC).

The gathering + firing half of the external clear; the decisions are PURE and live in
`lib/external_clear.py`. Run one-shot from outside the model:

    external_handoff_clear.py --project-root <path> [--dry-run] [--force]

WHAT MAKES IT ZERO-TURN. Three things have to happen for an abandoned session to shrink, and
today the model does all three. Here:

  1. DECIDE  — `external_clear.should_clear_externally`, from files the session already writes
     (transcript mtime, `ttl-regime.json`, `armed-cadence.cron`, the presence breadcrumb).
  2. COMPOSE — the handoff is built from on-disk facts (TRDD STATE blocks, git log, the findings
     ledger). No model, no tokens. `--llm-ext` upgrades the prose; the template is what ships.
  3. TYPE    — `clear_trigger`'s ALREADY-RATIFIED verified injection chain, reused verbatim by
     spawning its `--__chain` child with a payload we build. Nothing in `clear_trigger` had to
     change: `_run_chain_payload` takes the pane, the state dir and the directive as DATA, and
     resolves the project root from `CLAUDE_PROJECT_DIR`, which we set for the child.

THE PANE COMES FROM DISK, NOT FROM THE ENVIRONMENT. A process that is not the session cannot see
`TMUX_PANE` / `ITERM_SESSION_ID` — they do not propagate. The session records them at start into
`.janitor/state/terminal-identity.json`; `fleet_restart.recorded_terminal` reads that back and
`external_clear.terminal_from_record` adapts the shape. Without a recorded pane there is no
channel and the watcher declines rather than clearing a session it cannot bootstrap afterwards —
that is the one failure mode that must never happen, because `/clear` destroys the cron and the
bootstrap keystroke is what re-arms it.

DEFAULT OFF (`external_clear.DEFAULT_ENABLED`). Opt in with
`CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED=1`.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import external_clear as ec  # noqa: E402
import state  # noqa: E402

_LOG = "external-clear"
# The columns whose cards are genuinely IN FLIGHT. `todo`/`backburner` are queued, not in
# progress, so listing them would bury the one card the next session should actually resume.
_WORK_COLUMNS = ("dev", "testing", "ai_review", "human_review")
_MAX_CARDS = 6
_MAX_COMMITS = 5
_MAX_FINDINGS = 4
_TITLE_RE = re.compile(r"^title:\s*(.+?)\s*$", re.MULTILINE)
_FRONTMATTER_BYTES = 4096


def _run_git(root: Path, *args: str) -> str:
    """Best-effort `git` in `root`; "" on any failure. Never raises — a repo-less project must
    still get a handoff, just one without the commit section."""
    try:
        out = subprocess.run(  # noqa: S603 - fixed argv, no shell
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return out.stdout if out.returncode == 0 else ""


def _gather_cards(root: Path) -> list[tuple[str, str, str]]:
    """(id, column, title) for every in-flight card, both scopes, newest-updated first."""
    try:
        import trdd_common  # noqa: PLC0415 - lazy: a project without TRDDs pays nothing
    except ImportError:
        return []
    rows: list[tuple[float, str, str, str]] = []
    try:
        files = trdd_common.trdd_files("tasks", str(root))
    except Exception:  # noqa: BLE001 - a malformed design tree must not block the clear
        return []
    for _scope, path in files:
        try:
            head = path.read_text(encoding="utf-8", errors="replace")[:_FRONTMATTER_BYTES]
            _status, column = trdd_common.parse_state_text(head)
        except (OSError, ValueError):
            continue
        if column not in _WORK_COLUMNS:
            continue
        uid = trdd_common.extract_uid(path.name)
        if not uid:
            continue
        m = _TITLE_RE.search(head)
        title = (m.group(1) if m else "").strip().strip('"')
        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0
        rows.append((mtime, uid.upper(), column, title))
    rows.sort(reverse=True)
    return [(uid, col, title) for _mt, uid, col, title in rows[:_MAX_CARDS]]


def _gather_commits(root: Path) -> list[tuple[str, str]]:
    """(short-sha, subject) for the most recent commits. The subjects are the WHY index — the
    handoff links to them rather than restating what changed."""
    out = _run_git(root, "log", f"-{_MAX_COMMITS}", "--format=%h %s")
    rows: list[tuple[str, str]] = []
    for line in out.splitlines():
        sha, _, subject = line.partition(" ")
        if sha and subject:
            rows.append((sha, subject.strip()))
    return rows


def _gather_findings(root: Path) -> list[str]:
    """Unread findings, READ-ONLY. The cursor is deliberately NOT advanced: surfacing a finding
    in a handoff is not the same as a human having seen it, and advancing here would make the
    fresh session's own SessionStart injection silently skip them."""
    try:
        import findings_ledger  # noqa: PLC0415

        lines, _total = findings_ledger.unread_entries(str(root), cap=_MAX_FINDINGS)
    except Exception:  # noqa: BLE001 - the ledger is an extra, never a precondition
        return []
    return [state.sanitize_for_drift_line(line) for line in lines]


def _memory_dir(root: Path) -> str:
    rel = Path(".claude") / "project" / "memory"
    return str(rel) if (root / rel).is_dir() else ""


def _last_turn_age(root: Path, now: int) -> int | None:
    """Seconds since the last turn of ANY kind — the PROMPT-CACHE clock.

    Deliberately raw transcript mtime, NOT `fleet_scan.transcript_activity`'s substantive age:
    a heartbeat fire is a real API request and refreshes the cache even though it is not
    substantive work. Using the substantive age here would claim the cache had expired while
    5-minute beats were keeping it hot, and the watcher would clear a warm session for nothing.
    """
    try:
        import cold_cache_compact  # noqa: PLC0415

        transcript = cold_cache_compact.newest_transcript(root)
        if transcript is None:
            return None
        return max(0, now - int(transcript.stat().st_mtime))
    except (OSError, ValueError, ImportError):
        return None


def _decide(root: Path, sd: Path, now: int, *, force: bool) -> tuple[ec.ClearVerdict, dict]:
    """Gather every runtime fact and run the pure gate. Returns (verdict, facts-for-logging)."""
    import cold_cache_compact  # noqa: PLC0415
    import dispatch  # noqa: PLC0415 - reuses _cadence_active_waiting rather than re-deriving it
    import fleet_scan  # noqa: PLC0415
    import user_intent  # noqa: PLC0415

    cron = ""
    try:
        cron = (sd / "armed-cadence.cron").read_text(encoding="utf-8").strip()
    except (OSError, ValueError):
        pass

    idle_s, _enq, _await = fleet_scan.transcript_activity(str(root), now)
    facts = {
        "idle_seconds": idle_s,
        "last_turn_age_s": _last_turn_age(root, now),
        "ttl_minutes": ec.read_ttl_minutes(sd),
        "seconds_to_next_fire": ec.seconds_until_next_fire(cron, now),
        "context_tokens": cold_cache_compact.context_tokens_for(
            cold_cache_compact.newest_transcript(root)
        ),
        "min_context": ec.min_context_tokens(),
        "min_idle_s": cold_cache_compact.clear_min_idle_seconds(),
        "headroom_s": ec.headroom_seconds(),
        "user_present": user_intent.user_is_present(now=now),
        "active_waiting": dispatch._cadence_active_waiting(sd, now),
        "in_cooldown": cold_cache_compact.clear_in_cooldown(sd, now=now),
    }
    verdict = ec.should_clear_externally(**facts)  # type: ignore[arg-type]
    if force and not verdict.fire and verdict.why.startswith(("idle ", "no-headroom")):
        # --force overrides the two TRIGGER terms ONLY (is it idle enough / would the next fire
        # miss). Every SAFETY veto — cooldown, user present, active waiting, unknown idle, tiny
        # context — still holds, because those are the ones that protect work, and an operator
        # asking to observe the mechanism has not thereby authorized clearing a session someone
        # is typing into.
        verdict = ec.ClearVerdict(True, "forced", f"--force (gate said: {verdict.why})")
    return verdict, facts


def _llm_ext() -> tuple[str, str] | None:
    """(binary, its plugin-DATA dir) for the llm-externalizer CLI, or None when unavailable.

    The DATA dir is NOT optional and NOT ours: the launcher self-installs its native deps into
    `CLAUDE_PLUGIN_DATA`, and if the janitor's own value is inherited it would install into the
    JANITOR's data dir — measured 2026-08-06, the bare binary aborts with "better-sqlite3 is
    missing AND CLAUDE_PLUGIN_DATA is unset". So the dir is derived from the marketplace segment
    of whichever cached copy we resolve, never inherited.
    """
    import shutil  # noqa: PLC0415

    home = Path.home()
    found = shutil.which("llm-ext")
    if found:
        data = home / ".claude" / "plugins" / "data" / "llm-externalizer-emasoft-plugins"
        return (found, str(data))
    cache = home / ".claude" / "plugins" / "cache"
    candidates = sorted(cache.glob("*/llm-externalizer/*/bin/llm-ext"))
    if not candidates:
        return None
    binary = candidates[-1]  # highest version dir sorts last
    marketplace = binary.parents[3].name
    return (str(binary), str(home / ".claude" / "plugins" / "data" / f"llm-externalizer-{marketplace}"))


def _llm_ext_output_is_safe(text: str) -> bool:
    """Reject an externally-composed handoff that could STEER the session that reads it.

    This text is written by a remote LLM and then read by a fresh session as its first
    instruction, so it is an injection surface — the one place in this feature where untrusted
    generated prose reaches a directive position. Two structural refusals, both cheap:

      * a bare `[janitor-...]` line — the heartbeat protocol acts on exactly that shape, so a
        composed handoff containing one could forge a marker (the protocol's own rule is that a
        marker is only honoured from the stub's stdout, but forging one here is not a boundary
        worth testing in production);
      * any fenced block — the template never emits one, so its presence means the model inlined
        payload instead of linking, which also fails the concision contract.

    Anything rejected falls back to the deterministic template, which cannot contain either.
    """
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[janitor-") and stripped.endswith("]") and " " not in stripped:
            return False
        if stripped.startswith("```"):
            return False
    return True


def _compose_via_llm_ext(root: Path, cards: list[tuple[str, str, str]]) -> str | None:
    """Compose the handoff with the llm-externalizer CLI — ZERO main-model tokens.

    Returns the text, or None on ANY failure (binary absent, timeout, non-zero exit, unreadable
    report, unsafe content). None is not an error path, it is THE designed path: the template
    fallback is what actually ships, and this only upgrades the prose when it is available and
    behaves. A clear must never be blocked on a remote service.

    Per `use-llm-externalizer.md`: PATHS are passed, never file contents, so the TRDD bodies
    never enter anyone's context. The call is small and bounded (<= 4 STATE blocks), and the
    profile's own free/auto-free handling makes it ~$0; that is why there is no `--estimate`
    round-trip in front of it — it would double the latency of a time-boxed idle window to price
    a call whose input is capped at four small files.
    """
    resolved = _llm_ext()
    if resolved is None:
        return None
    binary, data_dir = resolved
    paths = []
    try:
        import trdd_common  # noqa: PLC0415

        for _scope, path in trdd_common.trdd_files("tasks", str(root)):
            uid = trdd_common.extract_uid(path.name)
            if uid and uid.upper() in {c[0] for c in cards}:
                paths.append(str(path))
    except Exception:  # noqa: BLE001
        return None
    if not paths:
        return None

    instructions = (
        "You are writing a LINK-ONLY session handoff for a Claude Code session that is about to "
        "be cleared. The attached files are TRDD task cards; each has a '## STATE' block that is "
        "authoritative. Write at most 25 lines of markdown: a one-line summary, then a 'NEXT "
        "ACTION' section naming ONE runnable step taken from the most recently updated card's "
        "STATE block, then a bullet list of the card ids as 'TRDD-<id>'. Reference things by id "
        "and path ONLY - never quote or inline file contents. No code fences. Under 3000 bytes."
    )
    env = {**os.environ, "CLAUDE_PLUGIN_DATA": data_dir}
    try:
        proc = subprocess.run(  # noqa: S603 - fixed argv, no shell
            [binary, "chat", "--instructions", instructions,
             "--input_files_paths", *paths[:4], "--answer_mode", "2"],
            capture_output=True, text=True, timeout=180, env=env, cwd=str(root),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if proc.returncode != 0:
        state.log_line(_LOG, f"llm-ext composer exited {proc.returncode} — using the template")
        return None
    report = proc.stdout.strip().splitlines()[-1].strip() if proc.stdout.strip() else ""
    if not report or not Path(report).is_file():
        return None
    try:
        text = Path(report).read_text(encoding="utf-8")
    except OSError:
        return None
    if not _llm_ext_output_is_safe(text):
        state.log_line(_LOG, "llm-ext output rejected (marker mimicry or fenced block)")
        return None
    return text


def _compose(root: Path, verdict: ec.ClearVerdict, facts: dict) -> tuple[str, list[str]]:
    """Build the handoff and validate it against the concise-but-exhaustive contract.

    Returns (text, reasons) — `reasons` empty means it passed. A failing handoff is REPORTED,
    not silently shipped: `/clear` is unrecoverable and this text is the only thing that
    survives it, so a contract breach here is the last moment anyone can notice.
    """
    import clear_trigger  # noqa: PLC0415

    cards = _gather_cards(root)
    inputs = ec.HandoffInputs(
        cards=cards,
        commits=_gather_commits(root),
        findings=_gather_findings(root),
        memory_dir=_memory_dir(root),
        trigger=verdict.trigger,
        idle_seconds=facts.get("idle_seconds"),
        context_tokens=facts.get("context_tokens"),
    )
    template = ec.compose_template_handoff(inputs, now_iso=time.strftime("%Y-%m-%dT%H:%M:%S%z"))

    # The llm-ext text is an UPGRADE, never a dependency: it ships only if it also passes the
    # same contract the template satisfies by construction. Validating it here rather than
    # trusting it is the whole reason the fallback is safe — a bloated or steering handoff is
    # worse than a terse one, because /clear is unrecoverable and nobody reviews this text.
    if ec.use_llm_ext() and cards:
        composed = _compose_via_llm_ext(root, cards)
        if composed and clear_trigger.check_handoff_concise(composed)[0]:
            return composed, []
        if composed:
            state.log_line(_LOG, "llm-ext handoff failed the concision contract — template used")

    _ok, reasons = clear_trigger.check_handoff_concise(template)
    return template, reasons


def _fire(root: Path, sd: Path, terminal: dict[str, str], now: int) -> None:
    """Spawn `clear_trigger`'s verified chain against the RECORDED pane.

    `CLAUDE_PROJECT_DIR` is set for the child because `clear_trigger._project_root()` reads it,
    and its fallbacks (git toplevel, then cwd) would resolve to the DAEMON's cwd — writing the
    resume marker into some other tree while the cleared session waits for one that never
    arrives.
    """
    import clear_trigger  # noqa: PLC0415
    import cold_cache_compact  # noqa: PLC0415

    os.environ["CLAUDE_PROJECT_DIR"] = str(root)
    clear_trigger._spawn_chain({
        "delay": 0.0,  # no turn to settle out — nothing is running in front of us
        "terminal": terminal,
        "first": clear_trigger.CLEAR_CMD,
        "then": list(clear_trigger._BOOTSTRAP_CMDS),
        "state_dir": str(sd),
        "gate_baseline": clear_trigger._gate_baseline(),
        "directive": (
            "read .janitor/state/agent-handoff.md FIRST (link-only handoff, auto-composed "
            "with no model turn — follow its wikimem/TRDD links via memgrep recall on "
            "demand), then resume your prior in-flight task."
        ),
    })
    # STAMP AT SPAWN, unlike the in-model lever which stamps only on a confirmed send.
    # The difference is real, not a relaxation: there, a refused send meant the USER WAS
    # PRESENT, so stamping would have turned a veto into a two-hour mute. Here presence is
    # already a hard veto upstream, the send is asynchronous (the chain waits for a free pane
    # and retries with long patience), and NOT stamping would respawn a chain on every daemon
    # beat — a spawn storm against a `clear-chain.lock` that only serializes them.
    cold_cache_compact.mark_clear_fired(sd, now=now)


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Decide, compose and fire a handoff-and-clear from OUTSIDE the model."
    )
    ap.add_argument("--project-root", default="", help="the session's project root (required "
                    "for a daemon run; defaults to CLAUDE_PROJECT_DIR / cwd)")
    ap.add_argument("--dry-run", action="store_true",
                    help="gather, decide and compose, but write NOTHING and fire NOTHING")
    ap.add_argument("--force", action="store_true",
                    help="override the idle/cache TRIGGER terms; every safety veto still holds")
    args = ap.parse_args()

    root = Path(args.project_root or os.environ.get("CLAUDE_PROJECT_DIR") or Path.cwd()).resolve()
    sd = root / ".janitor" / "state"
    now = int(time.time())

    if not ec.enabled() and not args.dry_run:
        print(f"DISABLED set {ec.ENABLED_ENV}=1 to opt in")
        return 0
    if not sd.is_dir():
        print(f"NO_JANITOR_STATE {sd}")
        return 0

    verdict, facts = _decide(root, sd, now, force=args.force)
    print(f"VERDICT {'FIRE' if verdict.fire else 'HOLD'} "
          f"trigger={verdict.trigger or '-'} why={verdict.why}")
    if not verdict.fire:
        return 0

    # The pane is resolved BEFORE the handoff is written: a session we cannot type into must
    # not be cleared at all, and finding that out after writing state would leave a handoff
    # claiming a clear that never happens.
    import fleet_restart  # noqa: PLC0415

    terminal = ec.terminal_from_record(fleet_restart.recorded_terminal(str(root)))
    if terminal.get("kind") == "unknown":
        print("NO_RECORDED_PANE cannot bootstrap after /clear — declining")
        state.log_line(_LOG, "declined: no recorded pane, a cleared session could not re-arm")
        return 0

    text, reasons = _compose(root, verdict, facts)
    if reasons:
        print(f"HANDOFF_NOT_CONCISE {','.join(reasons)}")
        state.log_line(_LOG, f"handoff violates the concision contract: {reasons}")

    if args.dry_run:
        print(f"DRY_RUN would clear via {terminal.get('kind')} "
              f"({len(text.encode('utf-8'))}B handoff)")
        print("--- handoff ---")
        print(text)
        return 0

    state.atomic_write(sd / "agent-handoff.md", text)
    _fire(root, sd, terminal, now)
    state.log_line(_LOG, f"fired: trigger={verdict.trigger} — {verdict.why}")
    print(f"CLEAR_CHAIN_SPAWNED trigger={verdict.trigger}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
