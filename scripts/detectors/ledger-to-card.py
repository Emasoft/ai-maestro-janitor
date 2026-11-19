#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""ledger-to-card — a finding that keeps recurring in the findings ledger becomes a ticket or a proposal TRDD.

TRDD-IP23RNLY R2 (PRRD G34.1, owner order 2026-11-19: "every issue must become either a janitor ticket
or a TRDD; the janitor must ensure that, enforce that, nudge that"). The quiet heartbeat records every
advisory in the ledger and prints none of it, so a condition can recur for days with nobody owning it.
This detector reads the ledger (read-only: `findings_ledger.entries` never touches the owner cursor),
groups it by (code, src), and for every group that REPEATS and has no card, raises ONE card through
`issue_catalog.raise_issue`, which alone decides domain, agent and template:

    LEDGER-001  the janitor own machinery   → HARNESS ticket, auto-dispatched (janitor-repair-agent)
    LEDGER-002  the user repo or board      → PROJECT proposal TRDD, the printed command approves it
    LEDGER-003  only the owner can fix it   → HARNESS record-only ticket, moved to needs_human

The ownership group comes from the CODE-OWNED table `_GROUP_BY_SRC` below, keyed on the ledger `src`
(the emitting detector name) and never derived from ledger text, which is attacker-influenceable. An
unknown src is a PROJECT finding: that group needs a human approval, the restrictive side.

Identity is `LEDGER:<code>:<src>` with NO date: a day-stamped key would open a new card each day while
yesterday one is still unapproved (ADVISORY-STALE-STASH alone has 125 entries in 3 days). Evidence is
`[code, src]` only, so it is stable and a human refusal of the card sticks (propose() suppresses a
re-proposal while evidence is unchanged). NOT an advisory detector: its lines must reach the agent.
"""

from __future__ import annotations

import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import findings_ledger  # noqa: E402
import issue_catalog  # noqa: E402
import state  # noqa: E402
import ticket_proposal  # noqa: E402
import tickets  # noqa: E402
import trdd_common  # noqa: E402

NAME = "ledger-to-card"

# Ownership groups → the catalog code that files them. Domain and agent come from the code, never from here.
JANITOR, PROJECT, HUMAN = "janitor", "project", "human"
_CODE_BY_GROUP = {JANITOR: "LEDGER-001", PROJECT: "LEDGER-002", HUMAN: "LEDGER-003"}
ERROR_CODE = "LEDGER-004"
# The codes this detector itself writes into the ledger (raise_issue logs ref=T-/TRDD- at birth and an
# error row is recorded on failure). Counting them would make the detector card its own cards.
OWN_CODES = frozenset({*_CODE_BY_GROUP.values(), ERROR_CODE})

# src values MEASURED in the real ledger 2026-11-19. Code-owned: a finding cannot pick its own group.
_GROUP_BY_SRC = {
    **dict.fromkeys(
        ("memory-librarian", "reports-purge", "subagent-report", "wikimem-syntax", "daemon", "hook-timeout-scan",
         "janitor:autorecall", "jev-compaction", "orphaned-memory-maint"),
        JANITOR,
    ),
    **dict.fromkeys(
        ("dirty-tree", "gh-reply-watch", "github-issues-watch", "memorize-nudge", "project-map-drift", "repo-state",
         "report-to-trdd-drift", "stale-stash", "trdd-drift", "trdd-reminder", "trdd-cross-card-blindspot",
         "trdd-state-reconciliation"),
        PROJECT,
    ),
    **dict.fromkeys(("iterm-automation-alarm", "background-worker-progress"), HUMAN),
}

# A group REPEATS at this many counted entries, or at two entries this far apart (one fire is often a
# transient; the same finding an hour later is a condition).
REPEAT_COUNT = 3
REPEAT_SPAN_S = 3600
# New PROJECT proposals are files in the user git-tracked design/proposals/, so a first run over a full
# ledger must not author a dozen of them. Over-cap groups are reported, never dropped silently.
MAX_PROPOSALS_PER_DAY = 3
LAST_MSGS = 5

_SEV_TO_TICKET = {
    "CRITICAL": "critical",
    "HIGH": "high", "ERROR": "high", "MAJOR": "high",
    "MEDIUM": "medium", "MED": "medium", "WARN": "medium", "WARNING": "medium",
    "LOW": "low", "MINOR": "low",
}
_TRDD_REF_RE = re.compile(r"TRDD-([A-Z0-9]{8})")


@dataclass
class Candidate:
    code: str  # the LEDGER-00N catalog code that files it
    group: str
    ledger_code: str
    src: str
    key: str
    severity: str
    count: int
    first: int
    last: int
    msgs: list[str]
    open_ticket: bool  # an open ticket already carries the key → only bump its seen count


def _iso(ts: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(ts))


def _group_of(src: str) -> str:
    return _GROUP_BY_SRC.get(src, PROJECT)


def _known_card_uids() -> set[str]:
    uids: set[str] = set()
    for folder in ("proposals", "tasks", "archived"):
        for _scope, path in trdd_common.trdd_files(folder):
            uid = trdd_common.extract_uid(path.name)
            if uid:
                uids.add(uid.upper())
    return uids


def _written_by_raise_issue(entry: dict, known_uids: set[str]) -> bool:
    """True for a ledger row `raise_issue` itself wrote at a card birth (ref names that card).

    Only CATALOGUED codes: other codes put a subject TRDD or a git tag in `ref` (TRDD-CLOSEABLE names the
    closeable card, REPO-OUTSIDE-PUBLISH a tag), and treating those as a link would mark an untracked
    finding as tracked. The card must still EXIST: a ref to a card that is gone links nothing."""
    if str(entry.get("code", "")) not in issue_catalog.ISSUE_CATALOG:
        return False
    ref = str(entry.get("ref", ""))
    if ref.startswith("T-"):
        return tickets.is_ticket_id(ref) and tickets.load(ref) is not None
    m = _TRDD_REF_RE.fullmatch(ref)
    return m is not None and m.group(1) in known_uids


def _candidates() -> list[Candidate]:
    known_uids = _known_card_uids()
    groups: dict[tuple[str, str], list[dict]] = {}
    for e in findings_ledger.entries():
        code, src = str(e.get("code", "")), str(e.get("src", ""))
        sev = str(e.get("sev", "")).strip().upper()
        if not code or not src or sev == "INFO":
            continue
        if code in OWN_CODES or code.startswith("TICKETED-") or code in findings_ledger.NEVER_SURFACE_CODES:
            continue
        if _written_by_raise_issue(e, known_uids):
            continue
        groups.setdefault((code, src), []).append(e)

    live = {t.dedupe_key: t for t in tickets.load_all() if t.status not in tickets.ARCHIVED}
    archived = tickets.load_archived()
    out: list[Candidate] = []
    for (code, src), rows in groups.items():
        key = f"LEDGER:{code}:{src}"
        canon = tickets._clean(key, 200)
        floor = max((t.updated_at for t in archived if t.dedupe_key == canon), default=0)
        is_open = canon in live
        if not is_open:
            cards = ticket_proposal.cards_for_key(key)
            if any(c.column != "refused" for c in cards):
                continue  # an open proposal: ticket-dispatch already reminds about it hourly
            if any(c.column == "refused" and not c.withdrawn for c in cards):
                continue  # a HUMAN refusal is a settled verdict — never re-filed on new messages
            # A janitor-withdrawn card promised re-proposal; its `updated:` is the closing time.
            floor = max([floor, *(c.updated for c in cards)])
        counted = sorted((e for e in rows if int(e["ts"]) > floor), key=lambda e: int(e["ts"]))
        if not counted:
            continue
        first, last = int(counted[0]["ts"]), int(counted[-1]["ts"])
        if not is_open and not (len(counted) >= REPEAT_COUNT or (len(counted) >= 2 and last - first >= REPEAT_SPAN_S)):
            continue
        group = _group_of(src)
        top = max((_SEV_TO_TICKET.get(str(e.get("sev", "")).strip().upper(), "medium") for e in counted), key=lambda s: tickets.SEVERITY_RANK[s])
        out.append(Candidate(
            code=_CODE_BY_GROUP[group], group=group, ledger_code=code, src=src, key=key, severity=top,
            count=len(counted), first=first, last=last, msgs=[str(e.get("msg", "")) for e in counted[-LAST_MSGS:]],
            open_ticket=is_open,
        ))
    # Most severe, then most frequent, first: a cap must drop the least important, not the alphabetical tail.
    out.sort(key=lambda c: (-tickets.SEVERITY_RANK[c.severity], -c.count, c.ledger_code, c.src))
    return out


def _proposals_today_file() -> Path:
    return state.state_dir() / f"ledger-to-card-proposals-{time.strftime('%Y-%m-%d')}.txt"


def _prune_old_day_files(today: Path) -> None:
    for p in state.state_dir().glob("ledger-to-card-proposals-*.txt"):
        if p != today:
            p.unlink(missing_ok=True)


def _record_error(c: Candidate, why: str) -> str:
    msg = f"{c.ledger_code} from {c.src} could not be filed: {why}"
    findings_ledger.record(sev="HIGH", code=ERROR_CODE, src=NAME, msg=msg)
    return f"[ledger-to-card] {msg}"


def _raise(c: Candidate, now: int) -> issue_catalog.Raised:
    """File (or dedupe into) the card for `c`. `found` is the only template slot that reaches the card body."""
    found = f"{c.count} ledger entries, first {_iso(c.first)}, last {_iso(c.last)}. Latest: " + " | ".join(c.msgs)
    return issue_catalog.raise_issue(
        c.code,
        where=f"{c.ledger_code} from {c.src}",
        evidence=[c.ledger_code, c.src],
        severity=c.severity,
        dedupe_key=c.key,
        found=found,
        now=now,
    )


def main() -> int:
    if not tickets.config("TICKETS_ENABLED"):
        return 0
    state.init_state()
    now = int(time.time())
    cands = _candidates()
    if not cands:
        return 0

    today_file = _proposals_today_file()
    _prune_old_day_files(today_file)
    proposals_today = state.read_int_state(today_file, 0)

    lines: list[str] = []
    dropped: list[str] = []
    calls = 0
    for c in cands:
        if c.open_ticket:
            # Already carded: raise_issue dedupes into the open ticket and bumps its seen count, no new card.
            _raise(c, now)
            continue
        is_project = c.group == PROJECT
        if calls >= issue_catalog.MAX_RAISES_PER_FIRE or (is_project and proposals_today >= MAX_PROPOSALS_PER_DAY):
            dropped.append(f"{c.ledger_code}:{c.src}")
            continue
        calls += 1
        r = _raise(c, now)
        if not r.ok:
            if r.why.startswith("refused"):
                continue  # a prior agent PROVED this finding is not a defect; the verdict stands until its evidence changes
            lines.append(_record_error(c, r.why))
            continue
        if c.group == HUMAN and r.first_seen:
            # raise_issue says "the janitor will repair this itself", which is false for a human-only finding.
            # The kind is record-only (dispatch=False); needs_human is what ticket-dispatch surfaces every fire.
            t = tickets.load(r.ticket_id)
            if t is not None:
                tickets.save(tickets.mark_needs_human(t, now=now, why="only the owner can fix this recurring finding"))
            lines.append(f"[ticket] {c.code} {r.ticket_id}: {c.ledger_code} from {c.src} keeps recurring ({c.count}x) and only the owner can fix it")
            continue
        if is_project and r.first_seen:
            proposals_today += 1
            state.atomic_write(today_file, str(proposals_today))
        if r.line:
            lines.append(r.line)
    if dropped:
        shown = ", ".join(dropped[:5]) + (" …" if len(dropped) > 5 else "")
        lines.append(f"[ledger-to-card] {len(dropped)} recurring finding(s) not carded this fire (per-fire or per-day cap), next fire retries: {shown}")
    if lines:
        print("\n".join(lines), flush=True)
    state.rotate_log_if_big(NAME)
    return 0


if __name__ == "__main__":
    sys.exit(trdd_common.exit_on_git_root_error(main, NAME))
