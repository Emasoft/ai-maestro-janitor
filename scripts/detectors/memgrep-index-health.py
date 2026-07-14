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

So this detector validates each memory scope's index on a cadence and turns a failure into WORK.

TWO decisions worth the words:

  1. **It validates WITHOUT healing.** `memgrep validate` is a separate, non-repairing path precisely
     because the normal `open()` self-heals (rebuild → nuke → rebuild). A self-heal is right for a
     caller who wants to USE the index and is exactly how the defect stayed invisible: it papered over
     the symptom on every open. An observer must not repair what it is measuring.

  2. **It waits for the failure to RECUR.** A single failure is often a corruption that the next
     `open()` will heal by itself — a ticket for that would be noise. A failure still present on the
     NEXT probe means the corruption is being re-manufactured, and a freshly built index that fails
     validation is a CODE bug, not a data problem. That is the ticket worth an agent's time.

The index is HARNESS domain — the janitor's own machinery — so `raise_issue` opens the ticket and the
scheduler dispatches the repair agent with no human in the loop. Nothing here touches the user's repo.
Fail-open throughout: no memgrep, no index, or an unparseable probe ⇒ silence, never a crash.
"""

from __future__ import annotations

import json
import re
import sys
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

# `FAIL <root> [MEMGREP-001] <prose>` — the CODE is the contract, the prose is free to change.
_FAIL_RE = re.compile(r"^FAIL\s+(?P<root>.+?)\s+\[(?P<code>[A-Z][A-Z0-9]{1,9}-\d{3})\]\s*(?P<msg>.*)$")


def _load(path: Path) -> dict[str, int]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return {str(k): int(v) for k, v in data.items()} if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def main() -> int:
    state.init_state()

    memgrep = user_mem_lib.find_memgrep()
    if not memgrep:
        return 0  # not installed — nothing to validate, and that is not a finding

    scopes = memory_scopes.resolve_scope_dirs()  # [(scope, root)] — only the roots that EXIST
    if not scopes:
        return 0

    by_root = {str(root): scope for scope, root in scopes}
    proc = state.run_subprocess(
        [memgrep, "validate", *by_root],
        timeout=60,
        capture=True,
        detector_name=_NAME,
    )
    if proc is None:
        return 0  # the probe itself failed (timeout, missing binary) — indeterminate, not a finding

    # Whatever the probe says about a root NOW replaces what we believed: a root that passes clears its
    # streak, so a healed index never carries a stale count into a future ticket.
    streak_path = state.state_dir() / _STATE
    previous = _load(streak_path)
    current: dict[str, int] = {}
    lines: list[str] = []

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
