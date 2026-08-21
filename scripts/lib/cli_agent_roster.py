"""CLI agent roster — the INDEPENDENT SECOND VIEW of the running fleet (TRDD-DFKEXO79).

`claude agents --json` (Claude Code 2.1.224+) enumerates running sessions from a plain
shell — no attached session, no macOS Automation (TCC) grant needed — and it can see MORE
sessions than the in-session `ListAgents` tool (measured 2026-08-08 on this host: 24 vs
18). The janitor's fleet guardian (`fleet_scan.py`) currently discovers iTerm panes via
`osascript`, which a TCC denial silently empties: "0 sessions" is then indistinguishable
from "genuinely 0 sessions" (janitor#92 / janitor#229 — "the status table says a project
is NOT armed but I armed it myself"). This module is the SECOND, INDEPENDENT enumerator
that lets a caller tell those two cases apart.

Real `claude agents --json` output (probed 2026-08-08, Claude Code — this is the actual
schema, not a guess): a bare top-level JSON ARRAY (not dict-wrapped) of row dicts. Two
row shapes share the array, discriminated by `kind`:

  background:  {"id": "<8hex>", "cwd": str, "kind": "background", "startedAt": <epoch-ms>,
                "sessionId": <uuid>, "name": str, "state": "blocked"|...}
  interactive: {"pid": int, "cwd": str, "kind": "interactive", "startedAt": <epoch-ms>,
                "sessionId": <uuid>, "name": str, "status": "idle"|"busy"|...}

Background rows carry `state` and no `pid`; interactive rows carry `pid` and `status`
instead. Everything else here treats both shapes uniformly by only ever reading `cwd`,
`kind`, `sessionId`, and `name` — the fields present on every row.

THE LOAD-BEARING RULE (six real misroutes this repo hit before): `name` is a MUTABLE
DISPLAY STRING a user or agent can rename at any time — it must NEVER be used as a join
key across two enumerations or two points in time. `cwd` (paired with `sessionId`/`pid`
when finer identity is needed) is the actual identity. Every function here keys and
compares by `cwd`, never by `name`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from typing import Any

import state as _state  # sibling in scripts/lib/ — the SSOT for the subprocess-timeout scale


def parse_agents_json(stdout: str) -> list[dict[str, Any]]:
    """Parse `claude agents --json` stdout into a list of row dicts.

    Tolerates the real shapes seen in the wild: a bare JSON array (the normal case), a
    dict-wrapped list (defensive — some CLI surfaces wrap arrays under a key such as
    `"agents"`), an empty string, and outright malformed/non-JSON text. Any of those
    failure cases returns `[]` — fail-open, never raises — because a parse failure must
    be treated the same as "no data" by callers, never as "there was a real error worth
    crashing over" (the janitor's per-session detectors run in the cron hot path).

    Non-dict entries in the array are dropped (a row must be a JSON object to be usable).
    """
    text = stdout.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return []

    rows: list[Any]
    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        # Defensive dict-wrapped shape: {"agents": [...]} or similar single-list value.
        found: list[Any] | None = None
        for value in data.values():
            if isinstance(value, list):
                found = value
                break
        if found is None:
            return []
        rows = found
    else:
        return []

    return [row for row in rows if isinstance(row, dict)]


def _normalize_cwd(cwd: str) -> str:
    """Pure string normalization only — no symlink resolution, no filesystem I/O.

    Strips a trailing "/" so "/a/b" and "/a/b/" key identically. Deliberately does NOT
    call `os.path.realpath` or touch the filesystem: this module is the PURE half, and
    two enumerators (osascript, `claude agents --json`) may run on different machines or
    at different times where symlink resolution would silently diverge.
    """
    if len(cwd) > 1 and cwd.endswith("/"):
        return cwd.rstrip("/")
    return cwd


def roster_by_cwd(agents: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Group agent rows by NORMALIZED `cwd` — never by `name`.

    Returns `{normalized_cwd: [row, ...]}`, preserving input order within each group.
    Rows missing a usable (non-empty, string) `cwd` are dropped — a row this module
    cannot place under a project directory is useless to a fleet-vs-project cross-check.

    `name` is a mutable display string a user or agent can rename at any time (six real
    misroutes recorded before this rule was written) — it is NEVER a join key. `cwd` is
    the identity this module and its callers key on.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in agents:
        cwd = row.get("cwd")
        if not isinstance(cwd, str) or not cwd:
            continue
        key = _normalize_cwd(cwd)
        grouped.setdefault(key, []).append(row)
    return grouped


def second_view_verdict(*, osascript_sessions: int, cli_rows_for_host: int) -> str:
    """The janitor#92 discriminator: is an empty osascript enumeration REALLY empty?

    Pure, total function over the two enumerators' counts:

      * `osascript_sessions == 0` and `cli_rows_for_host > 0` ->
        `"channel-blocked-not-empty"` — the osascript/iTerm channel is blocked or
        denied (e.g. a TCC Automation denial) WHILE sessions demonstrably exist via the
        independent `claude agents --json` view. This is exactly the janitor#92/#229
        failure mode: "0 sessions" silently meant "denied", not "empty".
      * `osascript_sessions == 0` and `cli_rows_for_host == 0` -> `"consistent-empty"` —
        both enumerators agree there is genuinely nothing running.
      * `osascript_sessions > 0` -> `"channel-working"` — the osascript channel itself
        produced results, so it is not blocked (regardless of what the CLI view says).
    """
    if osascript_sessions == 0:
        if cli_rows_for_host > 0:
            return "channel-blocked-not-empty"
        return "consistent-empty"
    return "channel-working"


def fetch_agents(*, timeout_s: int = 15) -> tuple[list[dict[str, Any]], str]:
    """Run `claude agents --json` and return `(rows, why)`. The ONE I/O function here.

    `why` is `""` on success (rows may still legitimately be `[]` — no agents running).
    On failure `rows` is always `[]` and `why` names the cause, so an empty roster and a
    failed probe are never confused with each other:

      * `"claude-not-on-PATH"` — the `claude` binary could not be resolved via
        `shutil.which`. Checked up front so a missing binary never even attempts a
        subprocess call.
      * `"timeout"` — the process ran past `timeout_s` seconds.
      * `"exit-<code>"` — the process exited non-zero.
      * `"unparseable"` — the process exited 0 but stdout did not parse (delegates to
        `parse_agents_json`, whose fail-open `[]` is otherwise indistinguishable from a
        genuinely empty roster — this branch restores that distinction).

    Never raises: `FileNotFoundError` / `OSError` from `subprocess.run` are caught
    alongside the explicit timeout case, mirroring `state.run_subprocess`'s contract
    that a hung or missing external tool must never park the caller's hot path.
    """
    binary = shutil.which("claude")
    if binary is None:
        return [], "claude-not-on-PATH"

    try:
        proc = subprocess.run(
            [binary, "agents", "--json"],
            capture_output=True,
            text=True,
            # Scaled by the SHARED knob (1.0 in production — byte-identical there). This is a
            # direct subprocess.run with its OWN ceiling, so scaling `state.run_subprocess`
            # never reached it. Measured under suite load: this expired and returned "timeout",
            # and the tests asserting the OTHER classifications failed as
            # `assert 'timeout' == 'exit-7'` / `== 'unparseable'` — the outcome under test was
            # replaced by a load artefact, which reads as a classification bug in code that is
            # correct (TRDD-7NSRD8OV).
            timeout=timeout_s * _state.timeout_scale(),
            check=False,
        )
    except subprocess.TimeoutExpired:
        return [], "timeout"
    except OSError:
        return [], "exec-failed"

    if proc.returncode != 0:
        return [], f"exit-{proc.returncode}"

    stdout = proc.stdout.strip()
    if not stdout:
        # Empty stdout on exit 0 is a genuinely empty roster, not a parse failure.
        return [], ""

    rows = parse_agents_json(stdout)
    if not rows and stdout.strip() not in ("[]", "{}"):
        return [], "unparseable"
    return rows, ""
