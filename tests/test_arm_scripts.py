"""The arm's prepare/record pair (TRDD-DLI76AUC) — the tool-call collapse and its crash-safety.

A tool call is not free: every round-trip re-reads the whole conversation at the 0.1x cache-read
rate, so at a ~520k context one costs ~52k weighted. The arm was SIX of them, which made a
re-arm cost about what six quiet heartbeat fires cost — and the dynamic cadence re-arms on every
tier change, so switching tiers could cost more than the slower tier saved. These two scripts
fold four calls into one, and remove the `CronList` from the steady state by remembering the
cron's id.

That memory is the dangerous part, and it is what most of this file tests. A STALE id is worse
than no id: `CronDelete` on a dead id fails harmlessly, the arm then creates a heartbeat anyway,
and if a live-but-unrecorded cron already existed the session ends up with TWO heartbeats firing
forever — silently double cost, the exact failure this whole TRDD is trying to avoid. So the id
is CONSUMED by `arm_prepare` before any cron is touched: a turn that dies mid-arm leaves no id,
and the next arm sweeps with a `CronList` instead of trusting one.
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PREPARE = ROOT / "scripts" / "arm_prepare.py"
RECORD = ROOT / "scripts" / "arm_record.py"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import state  # noqa: E402


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An isolated project + HOME + plugin DATA dir, so no test touches the real heartbeat."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()
    yield tmp_path
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()


def _sd(project: Path) -> Path:
    return project / ".janitor" / "state"


def _run(script: Path, project: Path, *args: str) -> tuple[int, dict[str, str], str]:
    """Run a script the way the skill does; return (rc, parsed key=value lines, raw stdout)."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(project / "home"),
        "CLAUDE_PROJECT_DIR": str(project),
        "CLAUDE_PLUGIN_DATA": str(project / "data"),
        # Isolate the machine-wide flags too, so a test can set/inspect GLOBAL maintenance
        # without ever touching the real fleet state.
        "JANITOR_GLOBAL_STATE_DIR": str(project / "gs"),
    }
    proc = subprocess.run([sys.executable, str(script), *args], capture_output=True, text=True, env=env, cwd=project)
    kv = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            kv[k.strip()] = v.strip()
    return proc.returncode, kv, proc.stdout


def _prepare(project: Path) -> tuple[int, dict[str, str], str]:
    return _run(PREPARE, project, "--plugin-root", str(ROOT), "--data-dir", str(project / "data"))


# --------------------------------------------------------------------------- #
# The crash-safety property — a half-finished arm must never leak a heartbeat
# --------------------------------------------------------------------------- #


def test_a_crash_between_prepare_and_record_forces_a_SWEEP(project: Path) -> None:
    """THE test. `arm_prepare` CONSUMES the stored id before any cron is touched, so a turn that
    dies mid-arm leaves nothing behind to trust. The next arm must report `sweep=yes` and go find
    every heartbeat with a CronList.

    If the id survived a crash it would be STALE — pointing at a cron that was already deleted —
    and the CronDelete would silently no-op while CronCreate added another. A previously-created
    but unrecorded heartbeat would then keep firing alongside the new one: two heartbeats, double
    the fire cost, forever, and nothing anywhere would say so."""
    _sd(project).mkdir(parents=True)
    (_sd(project) / "heartbeat-cron-id.txt").write_text("ff020fd5", encoding="utf-8")

    rc, kv, _ = _prepare(project)  # the arm begins…
    assert rc == 0
    assert kv["prior-cron-id"] == "ff020fd5", "the id must be handed to the caller to delete"
    # …and now the turn dies. `arm_record` never runs.

    rc, kv, _ = _prepare(project)  # the NEXT arm
    assert rc == 0
    assert kv["prior-cron-id"] == "", "a consumed id must not come back"
    assert kv["sweep"] == "yes", "an unknown id MUST fall back to a full CronList sweep"


def test_a_completed_arm_stores_the_id_so_the_next_one_needs_no_CronList(project: Path) -> None:
    """The steady state, and the entire point: with the id on disk the next arm deletes the old
    cron directly — four tool calls instead of five."""
    _sd(project).mkdir(parents=True)
    _prepare(project)
    rc, _, _ = _run(RECORD, project, "--cron", "*/15 * * * *", "--id", "abc123")
    assert rc == 0

    rc, kv, _ = _prepare(project)

    assert rc == 0
    assert kv["prior-cron-id"] == "abc123"
    assert kv["sweep"] == "no", "a known id means no CronList round-trip"


def test_the_first_ever_arm_sweeps(project: Path) -> None:
    """No id has ever been stored, so we cannot know what is out there — sweep."""
    rc, kv, _ = _prepare(project)

    assert rc == 0
    assert kv["sweep"] == "yes"


# --------------------------------------------------------------------------- #
# What prepare resolves
# --------------------------------------------------------------------------- #


def test_prepare_arms_the_cadence_the_DISPATCHER_asked_for(project: Path) -> None:
    """A `[janitor-renew]` fire exists precisely because the dynamic cadence (TRDD-0QQX9H0G) wants
    a different tier. If the arm ignored `desired-cadence.cron` and re-armed the default, the
    dispatcher would ask again on the next fire — a renew loop that re-arms forever and never
    converges, each iteration costing a full model turn."""
    _sd(project).mkdir(parents=True)
    (_sd(project) / "desired-cadence.cron").write_text("*/30 * * * *\n", encoding="utf-8")

    rc, kv, _ = _prepare(project)

    assert rc == 0
    assert kv["cron"] == "*/30 * * * *"


def test_prepare_falls_back_to_the_default_cadence(project: Path) -> None:
    """No tier chosen yet (dynamic cadence off, or a first arm) — the documented default."""
    rc, kv, _ = _prepare(project)

    assert rc == 0
    assert kv["cron"] == "*/5 * * * *"


def test_prepare_revokes_the_opt_out_and_installs_the_stub(project: Path) -> None:
    """The opt-out is cleared FIRST so a turn that dies leaves no cron AND no opt-out — the fleet
    guardian then reads `cron_dead` and re-arms, and the arm self-heals. Clearing it last would
    leave a cron plus a stale opt-out, and the guardian would file the project under "the user
    opted out" and never touch it again. The stub is what the cron actually fires."""
    _sd(project).mkdir(parents=True)
    (_sd(project) / "disarmed.flag").write_text("x", encoding="utf-8")

    rc, _, _ = _prepare(project)

    assert rc == 0
    assert not (_sd(project) / "disarmed.flag").exists(), "arming must revoke the opt-out"
    stub = project / "data" / "dispatcher-stub.py"
    assert stub.is_file(), "the cron fires the stub — it must exist before the cron does"
    assert stub.stat().st_mode & 0o111, "the stub must be executable"


def test_prepare_revokes_the_LOCAL_maintenance_sentinel(project: Path) -> None:
    """Arming means "this session starts in a KNOWN state". A stale LOCAL maintenance sentinel
    would otherwise keep every fire cache-refresh-only forever with nothing on screen saying so —
    you'd have to inspect each instance to find the suppressed ones (owner directive 2026-07-21)."""
    _sd(project).mkdir(parents=True)
    (_sd(project) / state.MAINTENANCE_FLAG).write_text("x", encoding="utf-8")

    rc, kv, out = _prepare(project)

    assert rc == 0
    assert not (_sd(project) / state.MAINTENANCE_FLAG).exists(), "arming must revoke local maintenance"
    # And it says NOTHING about it. Printing `maintenance=off` on every arm caused a
    # fleet-wide escalation loop (owner report 2026-07-21): agents read the line as "the arm
    # just disabled maintenance", collided it with the heartbeat nudge's "do NOT disable
    # maintenance mode", and re-enabled maintenance at GLOBAL scope — which the next re-arm
    # cannot clear, so every re-arm re-ran the same reasoning and ratcheted the whole fleet
    # into a suppression nothing lifted. Silence is the signal for "nothing is suppressing
    # this host"; only a SET global flag is worth a line.
    assert "maintenance" not in kv, f"an unset maintenance flag must be SILENT, got {out!r}"


def test_prepare_does_NOT_clear_GLOBAL_maintenance_but_reports_it(project: Path) -> None:
    """The GLOBAL flag survives an arm, and the arm SAYS so. /janitor-arm runs automatically on
    every SessionStart re-arm, so clearing it here would mean merely opening a new session silently
    lifts fleet-wide maintenance — the mode could never stay on. Same rule the arm already applies
    to the kill-switch: a project arm must not undo a deliberate machine-wide decision. Reporting
    solves the visibility problem without the override."""
    gs_dir = project / "gs"
    gs_dir.mkdir(parents=True)
    flag = gs_dir / "maintenance-mode.flag"
    flag.write_text("fleet paused", encoding="utf-8")

    rc, kv, _ = _prepare(project)

    assert rc == 0
    assert flag.exists(), "a project arm must NOT lift fleet-wide maintenance"
    assert kv["maintenance"] == "global-on", "the arm must surface the suppression it did not clear"


# --------------------------------------------------------------------------- #
# What record writes — and what it refuses to write
# --------------------------------------------------------------------------- #


def test_record_writes_the_state_the_dispatcher_reads_back(project: Path) -> None:
    """`armed-cadence.cron` is how the dispatcher's cadence phase knows the live tier already
    matches the tier it wants — without it, it would keep emitting `[janitor-renew]` at a cron
    that is already correct, re-arming on every single fire."""
    rc, _, out = _run(RECORD, project, "--cron", "*/15 * * * *", "--id", "1d703364")

    assert rc == 0
    sd = _sd(project)
    assert (sd / "armed-cadence.cron").read_text(encoding="utf-8") == "*/15 * * * *"
    assert (sd / "heartbeat-cron-id.txt").read_text(encoding="utf-8") == "1d703364"
    assert int((sd / "heartbeat-armed-at.ts").read_text(encoding="utf-8")) > 0
    assert "1d703364" in out


def test_record_clears_the_stale_renew_dedupe(project: Path) -> None:
    """The renew-marker dedupe is about the cron we just replaced. Carried across an arm it would
    suppress the NEXT genuine renew, stranding the heartbeat on a tier nobody wants."""
    _sd(project).mkdir(parents=True)
    (_sd(project) / "heartbeat-renew-seen.txt").write_text("seen", encoding="utf-8")

    _run(RECORD, project, "--cron", "*/5 * * * *", "--id", "abc")

    assert not (_sd(project) / "heartbeat-renew-seen.txt").exists()


@pytest.mark.parametrize("bad", ["", "id with spaces", "id;rm -rf /", "a" * 65, "id$(whoami)"])
def test_record_REFUSES_a_malformed_cron_id(project: Path, bad: str) -> None:
    """A stored id becomes a `CronDelete` argument on the NEXT arm. Validate its shape at the
    moment it is produced, so a malformed value fails loudly here rather than silently becoming a
    delete that never matches — which would leak a live heartbeat and double the fire cost with
    nothing anywhere reporting it."""
    rc, _, out = _run(RECORD, project, "--cron", "*/5 * * * *", "--id", bad)

    assert rc == 2, "a malformed id must be a hard refusal"
    assert "refused" in out
    assert not (_sd(project) / "heartbeat-cron-id.txt").exists(), "nothing may be stored"


def test_record_refuses_an_empty_cron(project: Path) -> None:
    """Arming 'nothing' would record a heartbeat that does not exist."""
    rc, _, out = _run(RECORD, project, "--cron", "  ", "--id", "abc")

    assert rc == 2
    assert "refused" in out


def test_the_arm_NEVER_tells_an_agent_to_re_enable_maintenance(project: Path) -> None:
    """The escalation loop, pinned at its source (owner report 2026-07-21).

    Two individually-correct instructions produced a fleet-wide outage: the heartbeat nudge
    said "do NOT disable maintenance mode", the arm then cleared the LOCAL sentinel, and
    agents reconciled the two by RE-ENABLING maintenance — at GLOBAL scope, because the local
    flag is cleared again by the very next re-arm while the global one is not. Each re-arm
    re-ran the same reasoning, ratcheting the fleet into a machine-wide maintenance nothing
    lifted: every daemon chore idled, plugin self-updates stopped, and no session could see
    why.

    So the arm's output must never read as a fault needing repair. With no global flag set it
    says nothing at all about maintenance; with one set it reports it as a FACT and points at
    the human's off-switch — never at an on-switch."""
    _sd(project).mkdir(parents=True, exist_ok=True)
    rc, _, out = _prepare(project)

    assert rc == 0
    lowered = out.lower()
    for forbidden in ("maintenance-on", "global-maintenance-on", "enable maintenance", "re-enable"):
        assert forbidden not in lowered, f"the arm must never point at an on-switch: {out!r}"
