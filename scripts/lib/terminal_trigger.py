#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Terminal-aware self-trigger send-abstraction (TRDD-db169d9e R3).

The janitor's self-trigger commands (`/compact`, `/reload-plugins`) need to type a
slash-command into THIS session's OWN pane, and the mechanism differs per terminal.
The terminal is identified by `state.terminal_kind()` — a PROCESS-ANCESTRY walk, not
fragile `$TERM_PROGRAM` inference.

Division of labour with the two entry scripts (`compact_trigger.py` /
`reload_trigger.py`):

  - This module owns the NON-iTerm backends. Today that is **tmux** (the terminal
    ai-maestro agents run in): a detached, delayed `tmux send-keys` ESC -> command
    -> Enter at the pane named by `$TMUX_PANE`.
  - For **iTerm** (and any terminal we don't yet automate) `send_self_command`
    returns the sentinel `USE_ITERM_PATH`, and the caller falls back to its own
    proven iTerm osascript path (or prints its degrade marker when even that
    isn't available). This keeps the working iTerm path — and its tests —
    untouched while adding tmux.

kitty / WezTerm / Apple Terminal etc. are future best-effort backends; until they
can be verified on a real host they degrade to `USE_ITERM_PATH` (→ the caller's
"ask the human to run it manually" path), which is exactly today's behaviour for
every non-iTerm terminal — never a regression.

The keystroke delivery runs in a DETACHED, delayed CHILD so the ESC it sends can't
kill the parent mid-turn, and so the parent returns instantly. The target pane is
resolved in the PARENT (which still has the full process ancestry) and passed to
the child as data — a child that got reparented to init couldn't re-resolve it.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state  # noqa: E402

# Terminals this module automates beyond iTerm. tmux is first-class (verifiable +
# the ai-maestro agent host). Add "kitty"/"wezterm" here once a real host confirms
# their send commands; until then they fall through to USE_ITERM_PATH (degrade).
_DELEGATE_KINDS = frozenset({"tmux"})

# A tmux pane id is `%<n>` (e.g. `%3`). $TMUX_PANE is set by tmux for the active
# pane. Validate before interpolating it into an argv — never trust an env var.
_TMUX_PANE_RE = re.compile(r"^%[0-9]+$")


def valid_tmux_pane(pane: str) -> bool:
    """True iff `pane` is a bare tmux pane id (`%<n>`) safe to place on a
    `tmux send-keys -t <pane>` argv. Anything else — notably a leading `-`, which
    tmux would parse as a FLAG rather than a target — is rejected. This is the tmux
    counterpart to the iTerm `valid_session_id` UUID gate, so BOTH injection sinks
    are hardened symmetrically (a tampered TTY→pane map can't reach the argv)."""
    return bool(_TMUX_PANE_RE.match(pane.strip()))

# Sentinel: the caller should use its own iTerm-osascript path (covers iTerm and
# every not-yet-automated terminal, whose fallback is "ask the human").
USE_ITERM_PATH = "USE_ITERM_PATH"


def build_tmux_steps(pane: str, command: str) -> list[list[str]]:
    """The ordered send sequence for a tmux pane: ESC, settle, the command (literal),
    then Enter to submit. Pure — returns argv steps tagged RUN / SLEEP.

    `send-keys ... Escape` interrupts an in-flight turn / clears partial input;
    `send-keys ... -l <command>` sends the command as LITERAL text (so `/compact`
    isn't parsed as a tmux key name); `send-keys ... Enter` submits it.
    """
    return [
        ["RUN", "tmux", "send-keys", "-t", pane, "Escape"],
        ["SLEEP", "0.6"],
        ["RUN", "tmux", "send-keys", "-t", pane, "-l", command],
        ["RUN", "tmux", "send-keys", "-t", pane, "Enter"],
    ]


def _encode_payload(delay_s: float, steps: list[list[str]]) -> str:
    return base64.b64encode(
        json.dumps({"delay": float(delay_s), "steps": steps}).encode("utf-8")
    ).decode("ascii")


def _run_send_payload(payload_b64: str) -> int:
    """CHILD role: decode the pre-resolved plan, wait out the initial delay, then
    run each step. Never raises — a failed send (e.g. the pane closed) degrades to
    the human noticing nothing happened, which is safe."""
    try:
        data = json.loads(base64.b64decode(payload_b64.encode("ascii")).decode("utf-8"))
    except (ValueError, json.JSONDecodeError):
        return 2
    time.sleep(max(0.0, float(data.get("delay", 0.0))))
    for step in data.get("steps", []):
        if not step:
            continue
        tag, rest = step[0], step[1:]
        if tag == "SLEEP" and rest:
            time.sleep(max(0.0, float(rest[0])))
        elif tag == "RUN" and rest:
            subprocess.run(  # noqa: S603 - fixed argv, no shell; values are validated/literal
                rest,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
    return 0


def _fire_detached_steps(delay_s: float, steps: list[list[str]]) -> None:
    """Launch a fully-detached child that sleeps then runs the steps, so the ESC it
    sends can't kill the parent and the parent returns immediately."""
    subprocess.Popen(  # noqa: S603 - fixed argv (this script + a base64 blob), no shell
        [sys.executable, str(Path(__file__).resolve()), "--__send", _encode_payload(delay_s, steps)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


# --- ai-maestro send via the SHIPPED CLI (issue #42; TRDD-db169d9e R4) ------
#
# When running INSIDE an ai-maestro agent, the AUTHORITATIVE way to type a command
# into the agent's own terminal goes through the ai-maestro server — but NOT by
# calling the server's HTTP API directly. Per the ecosystem decoupling rule
# (ai-maestro@8a2cc269: "no plugin element may call the server API directly — hooks
# and MCP included"), the janitor couples to the IMMUTABLE CLI layer the ai-maestro
# installer ships to ~/.local/bin, never the endpoints (the API changes constantly;
# the CLI is a frozen interface that POSTs the same endpoints behind it). So:
# `aimaestro-agent.sh list --json` to find this agent (CWD match) → its tmux session
# → `aimaestro-agent.sh session command <tmux> --newline -- <cmd>`. Every step is
# best-effort: a missing CLI, a down server, or an unconfirmed send returns None so
# the caller falls back to the local tmux keystroke send (ai-maestro agents run in
# tmux, so that path works too). Auth (AID_AUTH / AIMAESTRO_SUDO_TOKEN) is read by
# the CLI from the inherited env — the janitor never handles a token itself.


def _resolve_aimaestro_cli(env: Mapping[str, str]) -> str | None:
    """Resolve the ai-maestro CLI: $AIMAESTRO_CLI → ~/.local/bin → PATH; None if absent.

    The unified installer drops `aimaestro-agent.sh` in ~/.local/bin; an explicit
    `$AIMAESTRO_CLI` overrides (as the COS scripts do) so it resolves under a
    minimal hook/cron env where ~/.local/bin may not be on PATH.
    """
    override = env.get("AIMAESTRO_CLI")
    if override and Path(override).is_file() and os.access(override, os.X_OK):
        return override
    home = env.get("HOME") or os.path.expanduser("~")
    cand = Path(home) / ".local" / "bin" / "aimaestro-agent.sh"
    if cand.is_file() and os.access(cand, os.X_OK):
        return str(cand)
    return shutil.which("aimaestro-agent.sh")


def _run_aimaestro_cli(
    cli: str, args: list[str], *, env: Mapping[str, str], timeout: float
) -> subprocess.CompletedProcess[str] | None:
    """Run `<cli> <args…>` with the inherited env; None on ANY failure (best-effort)."""
    try:
        return subprocess.run(
            [cli, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            env=dict(env),
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def _agent_working_dir(agent: dict) -> str | None:
    wd = agent.get("workingDirectory")
    if not (isinstance(wd, str) and wd):
        sess = agent.get("session")
        wd = sess.get("workingDirectory") if isinstance(sess, dict) else None
    return wd if isinstance(wd, str) and wd else None


def _agent_tmux_session(agent: dict) -> str | None:
    sess = agent.get("session")
    if isinstance(sess, dict):
        ts = sess.get("tmuxSessionName")
        if isinstance(ts, str) and ts:
            return ts
    ts = agent.get("tmuxSessionName")
    return ts if isinstance(ts, str) and ts else None


def match_agent_tmux(agents: list, cwd_candidates: list[str]) -> str | None:
    """Pure: the tmux session of the agent whose workingDirectory equals — or is a
    parent of — any cwd candidate. Returns None when nothing matches."""
    cands = [os.path.realpath(c) for c in cwd_candidates if c]
    for agent in agents:
        if not isinstance(agent, dict):
            continue
        wd = _agent_working_dir(agent)
        if not wd:
            continue
        wdr = os.path.realpath(wd)
        if any(c == wdr or c.startswith(wdr + os.sep) for c in cands):
            ts = _agent_tmux_session(agent)
            if ts:
                return ts
    return None


def _try_ai_maestro_send(command: str, *, dry_run: bool, env: Mapping[str, str]) -> str | None:
    """Best-effort ai-maestro send via the shipped CLI (issue #42). Returns a status
    string on success, or None to fall through to the local terminal send.

    Repointed off the direct `/api/...` calls to `aimaestro-agent.sh` (the frozen
    CLI interface). CLI absent / server down / unconfirmed → None → caller degrades
    to the tmux keystroke send.
    """
    cli = _resolve_aimaestro_cli(env)
    if not cli:
        return None
    # 1) Enumerate agents → find THIS agent's tmux session by cwd match. `list
    #    --json` returns the same agent objects the API did, so the pure matcher is
    #    reused unchanged.
    proc = _run_aimaestro_cli(cli, ["list", "--json"], env=env, timeout=5.0)
    if proc is None or proc.returncode != 0 or not proc.stdout.strip():
        return None
    try:
        agents = json.loads(proc.stdout)
    except ValueError:
        return None
    if isinstance(agents, dict) and isinstance(agents.get("agents"), list):
        agents = agents["agents"]
    if not isinstance(agents, list):
        return None
    tmux = match_agent_tmux(agents, [os.getcwd(), env.get("CLAUDE_PROJECT_DIR", "")])
    if not tmux:
        return None
    if dry_run:
        return f"DRY_RUN:aimaestro:{tmux}:{command}"
    # 2) Type the command into that agent's terminal via the CLI (frozen interface
    #    over POST /api/sessions/<tmux>/command). `--newline` presses Enter;
    #    requireIdle stays False (flag omitted). `--` guards a dash-leading command.
    sent = _run_aimaestro_cli(
        cli, ["session", "command", tmux, "--newline", "--", command],
        env=env, timeout=6.0,
    )
    if sent is not None and sent.returncode == 0:
        return "FIRED:aimaestro"
    return None  # unconfirmed → caller falls back to the tmux keystroke send


def send_self_command(
    command: str, *, delay_s: float = 2.0, dry_run: bool = False,
    env: Mapping[str, str] | None = None,
) -> str:
    """Send `command` (a fixed literal like `/compact`) to this session's own pane,
    choosing the mechanism by `state.terminal_kind()`.

    Returns a status string:
      - `USE_ITERM_PATH` — kind is iTerm or a terminal we don't automate; the caller
        should use its own iTerm-osascript path (which itself degrades to "ask the
        human" when iTerm isn't actually available).
      - `FIRED:<kind>` — a detached delayed send was launched.
      - `DRY_RUN:<kind>:<pane>:<command>@<delay>s` — dry-run plan (nothing fired).
      - `NO_AUTO_TERMINAL:<kind>` — the kind is delegated but its target was
        unresolvable (e.g. `$TMUX_PANE` malformed); caller degrades.
    """
    e: Mapping[str, str] = os.environ if env is None else env
    # Inside an ai-maestro agent the server API is the authoritative way to reach
    # the agent's own terminal. Best-effort — any failure (server down, no match,
    # unconfirmed POST) falls through to the local terminal send below; ai-maestro
    # agents run in tmux, so that fallback works too (TRDD-db169d9e R4).
    if state.in_ai_maestro_agent_env(e):
        api = _try_ai_maestro_send(command, dry_run=dry_run, env=e)
        if api is not None:
            return api
    kind = state.terminal_kind()
    if kind not in _DELEGATE_KINDS:
        return USE_ITERM_PATH
    if kind == "tmux":
        pane = (e.get("TMUX_PANE") or "").strip()
        if not valid_tmux_pane(pane):
            return "NO_AUTO_TERMINAL:tmux"
        if dry_run:
            return f"DRY_RUN:tmux:{pane}:{command}@{delay_s}s"
        _fire_detached_steps(delay_s, build_tmux_steps(pane, command))
        return "FIRED:tmux"
    return f"NO_AUTO_TERMINAL:{kind}"  # unreachable while _DELEGATE_KINDS == {"tmux"}


def main() -> int:
    # Child entry: `terminal_trigger.py --__send <base64-plan>`.
    if len(sys.argv) >= 3 and sys.argv[1] == "--__send":
        return _run_send_payload(sys.argv[2])

    import argparse

    ap = argparse.ArgumentParser(description="Type a slash-command into this session's own pane.")
    ap.add_argument("command", help="the slash-command to send, e.g. /compact")
    ap.add_argument("--delay", type=float, default=2.0, help="seconds before sending (lets the turn settle)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, do not fire")
    args = ap.parse_args()
    print(send_self_command(args.command, delay_s=args.delay, dry_run=args.dry_run))
    return 0


if __name__ == "__main__":
    sys.exit(main())
