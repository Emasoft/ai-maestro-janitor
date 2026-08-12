"""The ticket CLI (TRDD-CGYMUKO6) — the SINGLE mutation surface, and the last untested one.

Every actor mutates the queue through `ticket_cli.py`: the skills, the detectors, and — the reason
this file exists — the dispatched repair agent. It is therefore where two guarantees actually live,
and neither was covered by a test until now:

  1. **A FORGED MARKER MUST BE WORTHLESS.** `[janitor-ticket]` is a line of model-visible text. A
     hallucination, or a payload that survived defanging, could put one in front of an agent. The only
     thing standing between that and a repair agent running is `start` REFUSING a ticket the scheduler
     never dispatched. If that refusal breaks, the marker becomes the authorization — which is exactly
     what the marker design says it must never be.

  2. **A TICKET IS NEVER SILENTLY DROPPED.** A failed repair retries, and when the attempts are spent
     it becomes `needs_human` and is surfaced on every fire. A ticket that quietly disappears is
     indistinguishable from one that was fixed — the failure mode this whole system was built against.

The CLI is run as a SUBPROCESS on purpose. Its exit code is the contract (the skill's step 1 is "if
this REFUSES, stop"), argparse is part of the surface, and it resolves its store through `lru_cache`d
paths. Calling `main()` in-process would test a shape, not the thing an agent runs.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "ticket_cli.py"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import state  # noqa: E402
import tickets  # noqa: E402

NOW = 1_784_000_000


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An isolated project + HOME, so no test touches the real ticket queue."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()
    yield tmp_path
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()


def _cli(project: Path, *args: str) -> tuple[int, str]:
    """Run the CLI exactly as an agent does, and return (exit code, stdout)."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(project / "home"),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    proc = subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True, env=env, cwd=project
    )
    return proc.returncode, proc.stdout


def _ticket(status: str = tickets.OPEN, **kw: object) -> tickets.Ticket:
    """Seed one HARNESS ticket in the isolated store, in the status under test."""
    kw.setdefault("kind", "index-corruption")
    kw.setdefault("title", "a memgrep index fails validation")
    kw.setdefault("now", NOW)
    t, _ = tickets.open_ticket(**kw)  # type: ignore[arg-type]
    assert t is not None
    if status != t.status:
        t.status = status
        tickets.save(t)
    return t


def _reload(ticket_id: str) -> tickets.Ticket:
    """Re-read a ticket from disk. A ticket the CLI was asked to mutate must still BE there — losing
    it is the failure this suite exists to catch, so an absent one fails here rather than surfacing as
    an unrelated attribute error."""
    t = tickets.load(ticket_id)
    assert t is not None, f"{ticket_id} vanished from the store"
    return t


# --------------------------------------------------------------------------- #
# 1. A FORGED MARKER MUST BE WORTHLESS — the `start` gate
# --------------------------------------------------------------------------- #


def test_start_REFUSES_a_ticket_that_nobody_dispatched(project: Path) -> None:
    """THE security test. A marker is text; the claim is the truth. An agent handed a ticket the
    SCHEDULER never dispatched must be turned away — otherwise anything able to put `[janitor-ticket]`
    in front of the model can pick a ticket off the board and have an agent work it."""
    t = _ticket(status=tickets.OPEN)

    rc, out = _cli(project, "start", t.id)

    assert rc == 1, "a refusal MUST be a non-zero exit — the skill branches on it"
    assert "REFUSED" in out
    assert _reload(t.id).status == tickets.OPEN, "a refused claim must not mutate the ticket"


def test_start_REFUSES_a_ticket_that_is_already_closed(project: Path) -> None:
    """The archived half of the same gate: naming a ticket that was resolved days ago must not
    resurrect it into `in_progress` and hand an agent a fault that no longer exists."""
    t = _ticket(status=tickets.RESOLVED)

    rc, out = _cli(project, "start", t.id)

    assert rc == 1
    assert "REFUSED" in out
    assert _reload(t.id).status == tickets.RESOLVED


def test_start_claims_a_ticket_the_scheduler_DID_dispatch(project: Path) -> None:
    """The gate is a gate, not a wall: the real dispatch path must pass through it."""
    t = _ticket(status=tickets.DISPATCHED)

    rc, out = _cli(project, "start", t.id)

    assert rc == 0
    assert "in_progress" in out
    assert _reload(t.id).status == tickets.IN_PROGRESS


def test_start_lets_a_working_agent_re_claim_its_own_ticket(project: Path) -> None:
    """An agent that re-runs step 1 (a retried turn, a resumed run) must not be locked out of the work
    it was legitimately dispatched to do. The guard is against UNAUTHORIZED work, not against repeating
    an authorized claim."""
    t = _ticket(status=tickets.IN_PROGRESS)

    rc, _ = _cli(project, "start", t.id)

    assert rc == 0
    assert _reload(t.id).status == tickets.IN_PROGRESS


@pytest.mark.parametrize(
    "hostile",
    [
        "[janitor-self-disarm]",
        "T-../../../etc/passwd",
        "T-7QK2M4XZ; rm -rf /",
        "not-a-ticket",
    ],
)
def test_a_hostile_id_is_rejected_before_it_can_reach_the_store(project: Path, hostile: str) -> None:
    """The ticket id is the ONE field of an agent's prompt that becomes a filesystem path. It is
    regex-validated first, so a traversal or a marker-shaped string is refused as malformed — it never
    gets as far as being looked up."""
    rc, out = _cli(project, "start", hostile)

    assert rc == 2, "a malformed id is a hard error, never a lookup"
    assert "not a ticket id" in out
    assert not (project / ".janitor" / "state" / "tickets").exists(), "nothing may be created"


def test_an_unknown_but_WELL_FORMED_id_is_a_clean_miss(project: Path) -> None:
    """A well-formed id that simply is not on the board fails loudly, and is not confused with a
    malformed one — the agent's report should say which."""
    rc, out = _cli(project, "show", "T-ZZZZZZZZ")

    assert rc == 2
    assert "no such ticket" in out


# --------------------------------------------------------------------------- #
# 2. A TICKET IS NEVER SILENTLY DROPPED — the close paths
# --------------------------------------------------------------------------- #


def test_close_resolved_records_what_was_done_and_archives_it(project: Path) -> None:
    """A resolved ticket leaves the queue but NOT the record: the resolution and the report path are
    what a human reads six months later to find out what the janitor did to this machine."""
    t = _ticket(status=tickets.IN_PROGRESS)

    rc, _ = _cli(
        project,
        "close",
        t.id,
        "--status",
        "resolved",
        "--resolution",
        "rebuilt the index; fixed the migration that corrupted it",
        "--report",
        "reports/janitor-repair-agent/x.md",
    )

    assert rc == 0
    done = _reload(t.id)
    assert done.status == tickets.RESOLVED
    assert "fixed the migration" in done.resolution
    assert done.reports == ["reports/janitor-repair-agent/x.md"]
    assert tickets.load_all() == [], "a closed ticket must leave the live queue"


def test_close_failed_retries_and_then_ASKS_FOR_A_HUMAN(project: Path) -> None:
    """The honest give-up. A repair that fails is retried with backoff, and when the attempts are spent
    the ticket becomes `needs_human` — a real state the heartbeat surfaces on every fire. It must never
    just go quiet: a ticket that vanishes looks exactly like a ticket that was fixed."""
    t = _ticket(status=tickets.IN_PROGRESS)
    assert t.max_attempts >= 2, "this test assumes at least one retry before giving up"

    for attempt in range(1, t.max_attempts + 1):
        rc, _ = _cli(project, "close", t.id, "--status", "failed", "--resolution", "the fix did not hold")
        assert rc == 0
        now = _reload(t.id)
        assert now.attempts == attempt
        if attempt < t.max_attempts:
            assert now.status == tickets.OPEN, "attempts left ⇒ back on the board"
            assert now.not_before > 0, "…but not immediately — a hot retry loop fixes nothing"
            now.status = tickets.IN_PROGRESS  # the scheduler re-dispatches; simulate the next claim
            tickets.save(now)

    assert _reload(t.id).status == tickets.NEEDS_HUMAN
    assert "the fix did not hold" in _reload(t.id).resolution


def test_a_retried_ticket_lives_in_exactly_ONE_place(project: Path) -> None:
    """`retry` un-archives a `needs_human` ticket. The move must be symmetric with the archiving one, or
    the ticket exists in the live queue AND the archive at once — and `list --all` then shows a ticket
    that is actively in flight as also being closed. An archive that contradicts the board is worse than
    no archive: it is a record that lies."""
    t = _ticket(status=tickets.NEEDS_HUMAN)

    rc, _ = _cli(project, "retry", t.id)
    assert rc == 0

    live = _reload(t.id)
    assert live.status == tickets.OPEN
    assert live.attempts == 0, "a retry starts the attempt budget over"

    rc, out = _cli(project, "list", "--all")
    assert rc == 0
    assert out.count(t.id) == 1, "the ticket must not appear as both open and closed"


def test_cancel_archives_the_ticket_with_its_reason(project: Path) -> None:
    """Cancelling is a decision, so it is recorded like one."""
    t = _ticket(status=tickets.OPEN)

    rc, _ = _cli(project, "cancel", t.id, "--why", "the index was rebuilt by hand")

    assert rc == 0
    done = _reload(t.id)
    assert done.status == tickets.CANCELLED
    assert "rebuilt by hand" in done.resolution
    assert tickets.load_all() == []


# --------------------------------------------------------------------------- #
# 3. The console never breaks
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("cmd", [["list"], ["list", "--all"], ["stats"], ["proposals"]])
def test_the_console_survives_an_empty_board(project: Path, cmd: list[str]) -> None:
    """The read-only commands are what a human reaches for when something is already wrong. They must
    not be the thing that fails — on a machine with no queue at all, they say so and exit 0."""
    rc, out = _cli(project, *cmd)

    assert rc == 0
    assert out.strip(), "a silent empty board is indistinguishable from a crash"


def test_approve_refuses_a_TRDD_that_is_not_on_the_board(project: Path) -> None:
    """The approval command is the janitor's one door into the user's repo. Handed an id that names no
    proposal, it must fail — never invent the ticket the id was supposed to authorize."""
    rc, out = _cli(project, "approve", "TRDD-ZZZZZZZZ")

    assert rc == 1
    assert out.strip()
    assert tickets.load_all() == [], "a failed approval must not leave a ticket behind"


# --------------------------------------------------------------------------- #
# 4. AN AGENT MUST BE ABLE TO SAY "NOT A DEFECT" AND BE BELIEVED (#128)
# --------------------------------------------------------------------------- #


def test_close_invalid_is_terminal_and_says_so(project: Path) -> None:
    """The missing option. Before this, proving a finding false had no honest close."""
    t = _ticket(status=tickets.IN_PROGRESS)

    rc, out = _cli(project, "close", t.id, "--status", "invalid",
                   "--resolution", "the validator checks table shape before the version stamp")

    assert rc == 0
    assert "invalid" in out and "NOT re-queue" in out
    after = _reload(t.id)
    assert after.status == tickets.INVALID
    assert after.attempts == 0, "a disproof is not a failed attempt"


def test_close_invalid_REFUSES_without_the_proof(project: Path) -> None:
    """A suppression with no stated reason is indistinguishable from giving up, and nobody can
    re-check it. The disproof IS the deliverable."""
    t = _ticket(status=tickets.IN_PROGRESS)

    rc, out = _cli(project, "close", t.id, "--status", "invalid", "--resolution", "   ")

    assert rc == 2 and "REFUSED" in out
    assert _reload(t.id).status == tickets.IN_PROGRESS, "a refused close must not mutate the ticket"


def test_close_needs_human_is_terminal_without_burning_attempts(project: Path) -> None:
    """The missing option (#213). Before this, the only honest exit for a real finding whose fix
    is owned by another repo cost two wasted `failed` dispatches to burn `max_attempts`."""
    t = _ticket(status=tickets.IN_PROGRESS)

    rc, out = _cli(project, "close", t.id, "--status", "needs_human",
                   "--resolution", "root cause confirmed; fix belongs to a different repo")

    assert rc == 0
    assert "needs_human" in out and "NOT re-queue" in out
    after = _reload(t.id)
    assert after.status == tickets.NEEDS_HUMAN
    assert after.attempts == 0, "a direct needs_human close is not a failed attempt"


def test_close_needs_human_REFUSES_without_the_proof(project: Path) -> None:
    """Same discipline as `invalid`: an unexplained hand-off to a human is indistinguishable from
    giving up."""
    t = _ticket(status=tickets.IN_PROGRESS)

    rc, out = _cli(project, "close", t.id, "--status", "needs_human", "--resolution", "   ")

    assert rc == 2 and "REFUSED" in out
    assert _reload(t.id).status == tickets.IN_PROGRESS, "a refused close must not mutate the ticket"


def test_close_failed_says_RE_QUEUED_not_closed(project: Path) -> None:
    """The silent half of #128: an agent reported a ticket 'closed' that was still in the pool.

    The subcommand is called `close`, so an agent that ran it reasonably believed it had closed the
    ticket. The output must name what actually happened.
    """
    t = _ticket(status=tickets.IN_PROGRESS)

    rc, out = _cli(project, "close", t.id, "--status", "failed", "--resolution", "could not repair")

    assert rc == 0
    assert "RE-QUEUED" in out and "not closed" in out
    assert "--status invalid" in out, "point the agent at the option it actually needed"
    assert _reload(t.id).status == tickets.OPEN


def test_retry_lifts_the_refusal_a_disproof_created(project: Path) -> None:
    """A disproof is never permanent — and a refusal left behind by a retry would silently swallow
    the detector's next finding while the ticket sits open."""
    t = _ticket(status=tickets.IN_PROGRESS, dedupe_key="k", evidence=["e"])
    _cli(project, "close", t.id, "--status", "invalid", "--resolution", "not a defect")
    assert tickets.refusal_for("k", ["e"]) == t.id

    rc, out = _cli(project, "retry", t.id)

    assert rc == 0 and "refusal lifted" in out
    assert tickets.refusal_for("k", ["e"]) == ""
