# Consume the ai-maestro server's hibernation answer (janitor#194).
#
# The janitor cannot observe hibernation. Nothing in the process table or on disk
# distinguishes an agent that is deliberately asleep from one that crashed — the registry's
# own `status` reads `offline` for both, and for never-woken too. So the janitor used to
# report NEITHER, refusing to guess, which left the state unknown rather than wrong.
#
# The server now answers it, and the delivery shape is the important part: it WRITES a file
# into each janitor's own project; the janitor never calls a script, needs no credential, and
# executes nothing. Agent status is not public data, so the only party that reads the registry
# or runs those commands is the daemon integrated into the server. Janitors RECEIVE.
#
# Least privilege is theirs to enforce and ours to respect: an agent workdir gets that agent's
# OWN record plus fleet counts, never the roster, because the full map in every workdir would
# mean compromising any one agent yields every agent's id, name and tmux session. This module
# therefore reads only the file belonging to the project it is asked about — never another
# project's, and never the install tree's roster on behalf of somebody else.

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

# Bump only for a BREAKING schema change; an unrecognised version is treated as ABSENT
# (their contract, verbatim: "unrecognised version => treat as ABSENT, not as data").
SUPPORTED_VERSION = 1

RESPONSE_DIR = "daemon_responses"
FILENAME = "hibernation.json"

# A deliberate sleep is a HEALTHY state and must never be diagnosed as a fault — that is the
# whole point of the request. A guardian that reports a deliberate sleep as an outage
# manufactures alarms nobody can act on. Only `crashed` is unhealthy.
HEALTHY_STATES = frozenset({"running", "hibernated", "never_woken"})
UNHEALTHY_STATES = frozenset({"crashed"})


@dataclass(frozen=True)
class Hibernation:
    """One live answer. `agent` is this workdir's OWN record (agent workdirs); `roster` is
    the full list (the ai-maestro install tree only). Exactly one is usually populated."""

    counts: dict[str, int]
    agent: Optional[dict[str, Any]]
    roster: Optional[list[dict[str, Any]]]
    age_s: int

    def state(self) -> str:
        """This workdir's agent state, or "" when the answer carries no per-agent record."""
        return str((self.agent or {}).get("state") or "")

    def is_healthy(self) -> Optional[bool]:
        """True/False for a known state, or None when there is no per-agent record to judge.

        None is NOT "healthy" — a caller that cannot tell must say so, not reassure.
        """
        s = self.state()
        if s in HEALTHY_STATES:
            return True
        if s in UNHEALTHY_STATES:
            return False
        return None

    def counts_label(self) -> str:
        """A compact `6 hibernated · 3 crashed` summary, empty when nothing is noteworthy.

        `running` is omitted deliberately: the fleet table already lists running sessions
        one per row, so repeating the number in the summary would invite two counts that
        disagree (they are measured differently — registry vs process table).
        """
        parts = [
            f"{self.counts[k]} {k.replace('_', ' ')}"
            for k in ("hibernated", "crashed", "never_woken", "orphaned")
            if self.counts.get(k)
        ]
        return " · ".join(parts)


def path_for(project_root: str | Path) -> Path:
    """Where the server delivers this project's answer."""
    return Path(project_root) / ".janitor" / RESPONSE_DIR / FILENAME


def read(project_root: str | Path, *, now: Optional[float] = None) -> Optional[Hibernation]:
    """This project's live hibernation answer, or None when there is NO LIVE ANSWER.

    None means exactly that — **never "the fleet is fine" and never "the fleet is broken"**.
    With no server running there is deliberately no answer at all, and a caller that renders
    None as either verdict is inventing one. Returned None for: absent file, unreadable or
    malformed JSON, an unrecognised `v`, a missing/garbled `ts`, or an answer older than the
    server's own `staleAfterS`.

    Never raises: this runs on the dashboard render path and inside detectors.
    """
    try:
        raw = json.loads(path_for(project_root).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- absent/unreadable/malformed are all "no answer"
        return None
    if not isinstance(raw, dict) or raw.get("v") != SUPPORTED_VERSION:
        return None

    ts = raw.get("ts")
    # bool is an int subclass — exclude it explicitly or `"ts": true` reads as epoch 1.
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return None
    age = int((time.time() if now is None else now) - float(ts))

    # Trust the producer's own staleness window rather than hard-coding one here: they can
    # change their cadence without the janitor silently declaring every answer stale.
    stale_after = raw.get("staleAfterS")
    if not isinstance(stale_after, (int, float)) or isinstance(stale_after, bool):
        return None
    if age > float(stale_after):
        return None

    data = raw.get("data")
    if not isinstance(data, dict):
        return None
    counts = data.get("counts")
    agent = data.get("agent")
    roster = data.get("agents")
    return Hibernation(
        counts={k: v for k, v in counts.items() if isinstance(v, int)} if isinstance(counts, dict) else {},
        agent=agent if isinstance(agent, dict) else None,
        roster=roster if isinstance(roster, list) else None,
        age_s=age,
    )
