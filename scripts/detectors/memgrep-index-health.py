#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""memgrep-index-health — the ticket system's motivating producer (TRDD-CGYMUKO6).

THE INCIDENT THIS EXISTS FOR (2026-07-14). memgrep's own schema migration manufactured a corrupt FTS
index: it recreated the table and left it EMPTY while the content table stayed full. Nothing noticed.
`PRAGMA integrity_check` said `ok`, `SELECT count(*)` read the content table, and recall just… found
less and less. It surfaced only because an agent tripped over it by accident, days later.

So this detector watches each memory scope's index — through TWO channels, because one of them alone
would have missed the very incident that motivated it:

  1. **The self-heal LEDGER (`.memgrep/self-heal.log`) — the channel that actually catches the bug.**
     memgrep's `open()` self-heals, and it RACES any observer and wins: every process that opens the
     index (the autorecall hook on every prompt, the librarian, a memory agent) repairs it in passing.
     So a probe that inspects the DATABASE always finds it pristine, and a corruption being
     RE-MANUFACTURED every day is invisible to state inspection. This was not theory — the first live
     heartbeat test of this detector found a healthy index because another detector had healed it
     seconds earlier. A repair is an EVENT, and an event can be recorded: the heal writes a line, and
     REPEATED heals mean something keeps breaking the index. That is the code bug worth a ticket.

  2. **A NON-HEALING validation probe (`memgrep validate`)** for the corruption the self-heal cannot
     fix — the case where the index is broken and STAYS broken. This path exists precisely because the
     normal `open()` would repair what it is measuring; an observer must not do that.

Channel 2 waits for the failure to RECUR before ticketing (one failure is often a corruption the next
`open()` heals; a ticket for that is noise). Channel 1 needs no such patience — a heal already IS a
failure that happened.

The index is HARNESS domain — the janitor's own machinery — so `raise_issue` opens the ticket and the
scheduler dispatches the repair agent with no human in the loop. Nothing here touches the user's repo.
Fail-open throughout: no memgrep, no index, or an unparseable probe ⇒ silence, never a crash.
"""

from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import issue_catalog  # noqa: E402
import memory_scopes  # noqa: E402
import state  # noqa: E402
import user_mem_lib  # noqa: E402

_NAME = "memgrep-index-health"
_STATE = "memgrep-health.json"

# A failure must be seen on this many CONSECUTIVE probes before it becomes a ticket. 1 would ticket
# every transient corruption that the next open() silently fixes; 2 means "it came back".
_CONSECUTIVE_BEFORE_TICKET = 2

# Channel 1 — the self-heal ledger. ONE heal is a corruption that got fixed; fine, that is the system
# working. TWO within a day means something is RE-BREAKING the index, and repairing it a third time
# would just be participating in the loop.
_HEALS_BEFORE_TICKET = 2
_HEAL_WINDOW_S = 86400

# `FAIL <root> [MEMGREP-001] <prose>` — the CODE is the contract, the prose is free to change.
_FAIL_RE = re.compile(r"^FAIL\s+(?P<root>.+?)\s+\[(?P<code>[A-Z][A-Z0-9]{1,9}-\d{3})\]\s*(?P<msg>.*)$")


def _load(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def recent_heals(root: str, *, now: int, window_s: int = _HEAL_WINDOW_S) -> list[str]:
    """The `<epoch> <stage> <why>` heal lines for `root` inside the window. PURE-ish (one file read).

    memgrep writes one line per self-repair. We count only recent ones so a corruption fixed months
    ago cannot resurrect itself into today's ticket.
    """
    try:
        raw = (Path(root) / ".memgrep" / "self-heal.log").read_text(encoding="utf-8")
    except OSError:
        return []
    out: list[str] = []
    for line in raw.splitlines():
        head, _, _rest = line.partition(" ")
        try:
            ts = int(head)
        except ValueError:
            continue  # a malformed line is not a heal — never crash on a log we did not write
        if now - ts <= window_s:
            out.append(line)
    return out


def main() -> int:
    state.init_state()

    memgrep = user_mem_lib.find_memgrep()
    if not memgrep:
        return 0  # not installed — nothing to validate, and that is not a finding

    scopes = memory_scopes.resolve_scope_dirs()  # [(scope, root)] — only the roots that EXIST
    if not scopes:
        return 0

    by_root = {str(root): scope for scope, root in scopes}
    now = int(time.time())
    lines: list[str] = []

    # ---- Channel 1: the self-heal LEDGER — the one that catches a RE-manufactured corruption. ----
    # A probe of the database state cannot see this: whoever opens the index next repairs it, so the
    # state is always clean by the time anyone looks. Only the record of the repairs survives.
    for root, scope in by_root.items():
        heals = recent_heals(root, now=now)
        if len(heals) < _HEALS_BEFORE_TICKET:
            continue
        raised = issue_catalog.raise_issue(
            "MEMGREP-009",
            scope=scope,
            where=root,
            count=len(heals),
            window="24h",
            evidence=[f"{root}/.memgrep/self-heal.log"],
            origin=_NAME,
        )
        if raised.line:
            lines.append(raised.line)
        state.log_line(_NAME, f"{len(heals)} self-heals on {root} in 24h → {raised.why}")

    # ---- Channel 2: a NON-HEALING validation probe — for damage the self-heal could NOT fix. ----
    proc = state.run_subprocess(
        [memgrep, "validate", *by_root],
        timeout=60,
        capture=True,
        detector_name=_NAME,
    )
    if proc is None:
        if lines:
            print("\n".join(lines), flush=True)
        return 0  # the probe itself failed (timeout, missing binary) — indeterminate, not a finding

    # Whatever the probe says about a root NOW replaces what we believed: a root that passes clears its
    # streak, so a healed index never carries a stale count into a future ticket.
    streak_path = state.state_dir() / _STATE
    previous = _load(streak_path)
    current: dict[str, int] = {}

    for raw in (proc.stdout or "").splitlines():
        m = _FAIL_RE.match(raw.strip())
        if not m:
            continue  # OK / NONE / anything unexpected — not a failure
        root, code, msg = m.group("root"), m.group("code"), m.group("msg")
        key = f"{root}|{code}"
        current[key] = previous.get(key, 0) + 1
        if current[key] < _CONSECUTIVE_BEFORE_TICKET:
            state.log_line(_NAME, f"{code} on {root} (streak {current[key]}) — waiting to see if it recurs")
            continue

        scope = by_root.get(root, "unknown")
        raised = issue_catalog.raise_issue(
            code,
            scope=scope,
            where=root,
            # The prose is UNTRUSTED (it embeds sqlite's message and a table name) — `raise_issue`
            # sanitizes every value before it reaches the template.
            table=msg[:120],
            column="",
            evidence=[f"{root}/.memgrep/index.db"],
            origin=_NAME,
        )
        if raised.line:
            lines.append(raised.line)
        state.log_line(_NAME, f"{code} on {root} recurred ({current[key]}x) → {raised.why}")

    state.atomic_write(streak_path, json.dumps(current, indent=2))
    if lines:
        print("\n".join(lines), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
