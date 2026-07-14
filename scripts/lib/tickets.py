"""The janitor's support-ticket system — incident management (TRDD-CGYMUKO6).

The janitor DETECTED incidents well and REPAIRED almost none: a finding became a drift line, a nag the
main Claude may or may not act on, and if it didn't, the finding recurred forever. A detector that can
only print is a monitoring system, not a maintenance system — and a nag that recurs forever trains its
reader to ignore it. This module is the queue that turns detection into maintenance: dedupe, severity
ordering, backoff, attempt limits, an explicit `needs_human` terminal, and a budget.

THE OWNERSHIP BOUNDARY (the load-bearing rule, enforced HERE in code — not in the ticket's text):

    HARNESS  — the janitor's OWN machinery (the memgrep index and its migrations, the daemon, its own
               state). The janitor is fixing ITSELF: nobody else owns that machinery and the blast
               radius is its own regeneratable state. It opens AND dispatches automatically.

    PROJECT  — the USER's code, repo, workflows, rulesets. The janitor is a GUEST. It may only
               PROPOSE: author a proposal TRDD under `design/proposals/` and recommend the exact
               command bearing that TRDD's id. Running the command IS the approval.

`KIND_REGISTRY` maps kind → domain, so the DOMAIN IS A PROPERTY OF THE KIND, never of the ticket's
free text. A ticket cannot talk its way from PROJECT into HARNESS, and `open_ticket` REFUSES a
PROJECT-domain ticket that carries no approved TRDD id.

THE INJECTION BOUNDARY. A HARNESS ticket dispatches an agent with NO human in the loop, and ticket
fields carry text derived from attacker-influenceable sources — filenames, dependency names, workflow
lines, GitHub issue titles. Pasting that into an agent prompt would be a prompt-injection vector THAT
THE JANITOR ITSELF DELIVERS. So free text is sanitized on ingest (`state.sanitize_for_drift_line`,
which defangs `[`/`]` so a payload cannot mimic a `[janitor-…]` marker) and capped; the agent's
INSTRUCTIONS never come from the ticket, only from the `kind → skill` registry in this file.
"""

from __future__ import annotations

import json
import secrets
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import state  # noqa: E402

# --------------------------------------------------------------------------- #
# the registry — kind decides EVERYTHING that matters (domain, agent, skill)
# --------------------------------------------------------------------------- #

HARNESS = "harness"
PROJECT = "project"


@dataclass(frozen=True)
class Kind:
    """What a kind of incident IS. Domain and agent come from HERE, never from a ticket's payload."""

    domain: str  # HARNESS (auto) | PROJECT (needs an approved TRDD)
    agent: str  # the subagent_type the cron turn spawns
    severity: str  # default severity when the producer does not override
    summary: str  # human label for the console


KIND_REGISTRY: dict[str, Kind] = {
    # ---- HARNESS: the janitor's own machinery. Auto-open, auto-dispatch. ----
    "index-corruption": Kind(HARNESS, "janitor-repair-agent", "high", "a memgrep index fails validation"),
    "migration-failure": Kind(HARNESS, "janitor-repair-agent", "critical", "a schema migration cannot produce a valid DB"),
    "daemon-crash-loop": Kind(HARNESS, "janitor-repair-agent", "critical", "the global daemon keeps dying"),
    "self-integrity": Kind(HARNESS, "janitor-repair-agent", "critical", "the janitor's own files failed attestation"),
    "state-corruption": Kind(HARNESS, "janitor-repair-agent", "high", "a janitor state file is unreadable"),
    "memory-corpus": Kind(HARNESS, "janitor-memory-subconscious-agent", "medium", "the wikimem corpus needs repair"),
    # ---- PROJECT: the USER's repo. PROPOSE ONLY — never dispatched without an approved TRDD. ----
    "security-workflow": Kind(PROJECT, "janitor-security-agent", "high", "a GitHub Actions workflow is vulnerable"),
    "branch-protection": Kind(PROJECT, "janitor-security-agent", "high", "the branch-protection baseline has drifted"),
    "dependency-advisory": Kind(PROJECT, "janitor-security-agent", "high", "a dependency carries a known advisory"),
    "leaked-credential": Kind(PROJECT, "janitor-security-agent", "critical", "a credential may be exposed"),
    "github-config": Kind(PROJECT, "janitor-security-agent", "medium", "the repo's GitHub config is off-baseline"),
    "code-defect": Kind(PROJECT, "janitor-repair-agent", "medium", "a defect in the project's code"),
}

SEVERITY_RANK = {"critical": 3, "high": 2, "medium": 1, "low": 0}

# Statuses. `needs_human` and `cancelled` and `resolved` are TERMINAL for the scheduler.
OPEN = "open"
DISPATCHED = "dispatched"
IN_PROGRESS = "in_progress"
RESOLVED = "resolved"
FAILED = "failed"
NEEDS_HUMAN = "needs_human"
CANCELLED = "cancelled"

DISPATCHABLE = {OPEN}
IN_FLIGHT = {DISPATCHED, IN_PROGRESS}
TERMINAL = {RESOLVED, CANCELLED, NEEDS_HUMAN}

TITLE_CAP = 160
DETAIL_CAP = 2000
EVIDENCE_CAP = 12

# Defaults (overridable via CLAUDE_PLUGIN_OPTION_* — see `config()`).
DEFAULTS = {
    "TICKETS_ENABLED": True,
    "TICKETS_PER_HEARTBEAT": 2,
    "TICKETS_PER_DAY": 20,
    "TICKET_MAX_ATTEMPTS": 3,
    "TICKET_BACKOFF_S": 1800,
    "TICKET_STALE_S": 3600,
}

LEDGER_MAX_LINES = 500  # bounded append site (repo invariant S3/S4)
DAY_S = 86400


def config(name: str) -> int | bool:
    """Read one knob from the environment, falling back to its default."""
    default = DEFAULTS[name]
    env = f"CLAUDE_PLUGIN_OPTION_{name}"
    if isinstance(default, bool):
        return state.is_truthy_env(env, default)
    import os

    return state.coerce_int(os.environ.get(env), int(default), var_name=env)


# --------------------------------------------------------------------------- #
# the model
# --------------------------------------------------------------------------- #


def new_id() -> str:
    """`T-` + 8 uppercase base36. Regex-validated (`is_ticket_id`) before it can reach a prompt."""
    alphabet = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    return "T-" + "".join(secrets.choice(alphabet) for _ in range(8))


def is_ticket_id(value: str) -> bool:
    """True iff `value` is a well-formed ticket id — the ONLY form allowed into an agent prompt."""
    if not isinstance(value, str) or len(value) != 10 or not value.startswith("T-"):
        return False
    return all(c in "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ" for c in value[2:])


def _clean(text: str, cap: int) -> str:
    """Sanitize UNTRUSTED free text on ingest, then cap it.

    `sanitize_for_drift_line` defangs `[` and `]` and strips control characters, so a payload in a
    filename or a dependency name cannot mimic a `[janitor-…]` marker once it is echoed into the
    heartbeat's stdout — which the model READS AS INSTRUCTIONS. This is the single most important
    line in this module: it is what makes it safe for a detector to put a hostile string into a
    ticket at all.
    """
    cleaned = state.sanitize_for_drift_line(str(text or "")).strip()
    return cleaned[:cap]


@dataclass
class Ticket:
    id: str
    kind: str
    title: str
    detail: str = ""
    evidence: list[str] = field(default_factory=list)
    severity: str = "medium"
    dedupe_key: str = ""
    origin: str = ""
    status: str = OPEN
    attempts: int = 0
    max_attempts: int = 3
    not_before: int = 0
    opened_at: int = 0
    updated_at: int = 0
    dispatched_at: int = 0
    trdd: str = ""  # the approving TRDD id (PROJECT domain only)
    reports: list[str] = field(default_factory=list)
    resolution: str = ""
    seen_count: int = 1

    @property
    def domain(self) -> str:
        """From the REGISTRY, never from the payload. An unknown kind is treated as PROJECT — the
        restrictive side — so a typo can never grant a ticket unattended dispatch."""
        k = KIND_REGISTRY.get(self.kind)
        return k.domain if k else PROJECT

    @property
    def agent(self) -> str:
        k = KIND_REGISTRY.get(self.kind)
        return k.agent if k else ""

    def to_json(self) -> dict:
        return asdict(self)


def from_json(data: dict) -> Ticket:
    known = {f for f in Ticket.__dataclass_fields__}
    return Ticket(**{k: v for k, v in data.items() if k in known})


# --------------------------------------------------------------------------- #
# PURE decisions — the testable heart (no I/O)
# --------------------------------------------------------------------------- #


def reclaim_stale(tickets: list[Ticket], *, now: int, stale_s: int) -> list[Ticket]:
    """Return the in-flight tickets whose agent DIED, reset to `open` with attempts++.

    Without this, an agent killed mid-work (the weekly rate cap did exactly that to a memory agent on
    2026-07-14) strands its ticket in `dispatched` forever — the queue quietly stops working and
    nothing says so.
    """
    out: list[Ticket] = []
    for t in tickets:
        if t.status not in IN_FLIGHT:
            continue
        if now - max(t.dispatched_at, t.updated_at) < stale_s:
            continue
        t.attempts += 1
        t.updated_at = now
        if t.attempts >= t.max_attempts:
            t.status = NEEDS_HUMAN
            t.resolution = "its agent died repeatedly; a human must look"
        else:
            t.status = OPEN
            t.not_before = now  # a dead agent is not a failed fix — retry promptly
        out.append(t)
    return out


def select_due(tickets: list[Ticket], *, now: int, per_fire: int, budget_left: int, inflight: int) -> list[Ticket]:
    """Pick the tickets to dispatch on THIS fire. PURE.

    Ordered by severity (critical first) then oldest-first, so a flood of low-severity findings can
    never starve a critical one, and no ticket can be starved forever by newer arrivals.

    Every cap is applied: the per-fire cap, the rolling-24h budget, and the in-flight slots (a ticket
    already being worked is not re-dispatched). `budget_left <= 0` or `per_fire <= 0` ⇒ NOTHING.
    """
    slots = min(per_fire, budget_left, max(0, per_fire - inflight))
    if slots <= 0:
        return []
    ready = [t for t in tickets if t.status in DISPATCHABLE and t.not_before <= now and t.kind in KIND_REGISTRY]
    ready.sort(key=lambda t: (-SEVERITY_RANK.get(t.severity, 0), t.opened_at))
    return ready[:slots]


def mark_failed(t: Ticket, *, now: int, backoff_s: int, why: str = "") -> Ticket:
    """A failed attempt: back off and retry, or give up EXPLICITLY.

    `needs_human` is a real terminal state and is surfaced on every fire — a ticket the janitor could
    not fix must never just go quiet, because a silent give-up is indistinguishable from a fix.
    """
    t.attempts += 1
    t.updated_at = now
    t.resolution = _clean(why, 200)
    if t.attempts >= t.max_attempts:
        t.status = NEEDS_HUMAN
    else:
        t.status = OPEN
        t.not_before = now + backoff_s
    return t


def budget_left(ledger: list[int], *, now: int, per_day: int) -> int:
    """Dispatches still allowed in the rolling 24h window."""
    recent = sum(1 for ts in ledger if now - ts < DAY_S)
    return max(0, per_day - recent)


# --------------------------------------------------------------------------- #
# the store
# --------------------------------------------------------------------------- #


def tickets_dir(state_dir: Path | None = None) -> Path:
    base = state_dir if state_dir is not None else state.state_dir()
    return Path(base) / "tickets"


def closed_dir(state_dir: Path | None = None) -> Path:
    return tickets_dir(state_dir) / "closed"


def ledger_path(state_dir: Path | None = None) -> Path:
    return tickets_dir(state_dir) / "dispatch-ledger.jsonl"


def load_all(state_dir: Path | None = None) -> list[Ticket]:
    """Every OPEN (non-archived) ticket. A corrupt file is skipped, never fatal."""
    d = tickets_dir(state_dir)
    out: list[Ticket] = []
    if not d.is_dir():
        return out
    for p in sorted(d.glob("T-*.json")):
        try:
            out.append(from_json(json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError, TypeError):
            continue
    return out


def load(ticket_id: str, state_dir: Path | None = None) -> Ticket | None:
    if not is_ticket_id(ticket_id):
        return None
    for p in (
        tickets_dir(state_dir) / f"{ticket_id}.json",
        closed_dir(state_dir) / f"{ticket_id}.json",
    ):
        try:
            return from_json(json.loads(p.read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError):
            continue
    return None


def save(t: Ticket, state_dir: Path | None = None) -> None:
    """Persist a ticket. Terminal ones are ARCHIVED, never deleted (RULE 0's spirit: the record of
    what the janitor did to this machine outlives the incident).

    A ticket lives in EXACTLY ONE of the two dirs, and the move between them runs BOTH ways: `retry`
    un-archives a `needs_human` ticket. Unlinking only on the way in (the original shape) left the
    archived copy behind, so the same ticket sat on the live board and in the archive at once — an
    archive that says "closed" about work that is in flight is a record that lies, and `list --all`
    printed it twice. Hence: write the destination first, then unlink the other side, so the only
    crash window leaves a duplicate that `load()` resolves to the LIVE copy — never a vanished ticket.
    """
    terminal = t.status in TERMINAL
    dest = closed_dir(state_dir) if terminal else tickets_dir(state_dir)
    other = tickets_dir(state_dir) if terminal else closed_dir(state_dir)
    dest.mkdir(parents=True, exist_ok=True)
    state.atomic_write(dest / f"{t.id}.json", json.dumps(t.to_json(), indent=2))
    try:
        (other / f"{t.id}.json").unlink()
    except OSError:
        pass


def open_ticket(
    *,
    kind: str,
    title: str,
    detail: str = "",
    evidence: list[str] | None = None,
    severity: str = "",
    dedupe_key: str = "",
    origin: str = "",
    trdd: str = "",
    now: int | None = None,
    state_dir: Path | None = None,
) -> tuple[Ticket | None, str]:
    """Open a ticket, or bump an existing one with the same `dedupe_key`. Returns (ticket, why).

    THE OWNERSHIP GATE lives here: a PROJECT-domain kind REFUSES to open without an approving `trdd`
    id, because the janitor is a guest in the user's repo and `design/proposals/` already means
    "authored, not authorized". A HARNESS kind opens freely — the janitor is fixing itself.

    DEDUPE is what keeps a queue from becoming a flood: 50 findings of the same defect are ONE
    ticket with `seen_count` bumped, not 50 dispatches.
    """
    spec = KIND_REGISTRY.get(kind)
    if spec is None:
        return None, f"unknown ticket kind `{_clean(kind, 40)}`"
    if spec.domain == PROJECT and not trdd:
        return None, (f"`{kind}` is a PROJECT-domain incident: the janitor may only PROPOSE it. Author a proposal TRDD and approve it with /janitor-ticket-open --trdd <ID8>.")

    ts = int(time.time()) if now is None else int(now)
    key = _clean(dedupe_key or f"{kind}:{title}", 200)

    for existing in load_all(state_dir):
        if existing.dedupe_key == key and existing.status not in TERMINAL:
            existing.seen_count += 1
            existing.updated_at = ts
            save(existing, state_dir)
            return existing, f"already tracked as {existing.id} (seen {existing.seen_count}x)"

    t = Ticket(
        id=new_id(),
        kind=kind,
        title=_clean(title, TITLE_CAP),
        detail=_clean(detail, DETAIL_CAP),
        evidence=[_clean(e, 200) for e in (evidence or [])][:EVIDENCE_CAP],
        severity=severity if severity in SEVERITY_RANK else spec.severity,
        dedupe_key=key,
        origin=_clean(origin, 80),
        trdd=_clean(trdd, 12),
        max_attempts=int(config("TICKET_MAX_ATTEMPTS")),
        opened_at=ts,
        updated_at=ts,
    )
    save(t, state_dir)
    return t, f"opened {t.id}"


def record_dispatch(ticket_id: str, *, now: int, state_dir: Path | None = None) -> None:
    """Append to the rolling-24h ledger, TRIMMED on every append (no unbounded append sites)."""
    p = ledger_path(state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    try:
        lines = p.read_text(encoding="utf-8").splitlines()
    except OSError:
        pass
    lines.append(json.dumps({"id": ticket_id, "ts": now}))
    state.atomic_write(p, "\n".join(lines[-LEDGER_MAX_LINES:]) + "\n")


def read_ledger(state_dir: Path | None = None) -> list[int]:
    out: list[int] = []
    try:
        for line in ledger_path(state_dir).read_text(encoding="utf-8").splitlines():
            try:
                out.append(int(json.loads(line)["ts"]))
            except (ValueError, KeyError, TypeError):
                continue
    except OSError:
        pass
    return out
