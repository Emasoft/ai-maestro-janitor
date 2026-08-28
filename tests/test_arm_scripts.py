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


def _prepare_with_cron_env(project: Path, cron: str) -> tuple[int, dict[str, str], str]:
    """Like `_prepare`, but with `CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON` set — the user's own
    override knob (TRDD-BRHJHWW0 acceptance: the knob still wins once tiers stop driving
    `desired-cadence.cron`)."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(project / "home"),
        "CLAUDE_PROJECT_DIR": str(project),
        "CLAUDE_PLUGIN_DATA": str(project / "data"),
        "JANITOR_GLOBAL_STATE_DIR": str(project / "gs"),
        "CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON": cron,
    }
    proc = subprocess.run(
        [sys.executable, str(PREPARE), "--plugin-root", str(ROOT), "--data-dir", str(project / "data")],
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
    )
    kv = {}
    for line in proc.stdout.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            kv[k.strip()] = v.strip()
    return proc.returncode, kv, proc.stdout


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
    """No override on disk and no user config knob (TRDD-BRHJHWW0) — the fixed default."""
    rc, kv, _ = _prepare(project)

    assert rc == 0
    assert kv["cron"] == "*/15 * * * *"


def test_prepare_honors_the_user_cron_knob(project: Path) -> None:
    """TRDD-BRHJHWW0 acceptance: `CLAUDE_PLUGIN_OPTION_HEARTBEAT_CRON` still overrides the
    fixed default once the dispatcher no longer writes a tier-driven `desired-cadence.cron`."""
    rc, kv, _ = _prepare_with_cron_env(project, "*/10 * * * *")

    assert rc == 0
    assert kv["cron"] == "*/10 * * * *"


def test_prepare_prefers_an_on_disk_override_over_the_user_knob(project: Path) -> None:
    """An explicit `desired-cadence.cron` (a manual or future override) still wins over the
    config knob — `resolve_cron`'s documented precedence, unchanged by TRDD-BRHJHWW0."""
    _sd(project).mkdir(parents=True)
    (_sd(project) / "desired-cadence.cron").write_text("*/20 * * * *\n", encoding="utf-8")

    rc, kv, _ = _prepare_with_cron_env(project, "*/10 * * * *")

    assert rc == 0
    assert kv["cron"] == "*/20 * * * *"


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


def test_prepare_sweeps_every_retired_LOCAL_sentinel(project: Path) -> None:
    """Arming means "this session starts in a KNOWN state", and after 2026-07-31 that state is
    the ONLY state: pause and maintenance are gone, so their sentinels are inert litter.

    The sweep is the load-bearing half of the removal, not tidiness. Real hosts have these files
    on disk right now, and every lever that used to lift them went away with the switches — so a
    flag left behind is a project that reads as suppressed with nothing able to un-suppress it.
    Driven off `state.RETIRED_SENTINELS` so the list has ONE definition shared with the
    dispatcher's per-fire sweep; a name added there is swept by both without touching this test."""
    _sd(project).mkdir(parents=True)
    for name in state.RETIRED_SENTINELS:
        (_sd(project) / name).write_text("left by an older janitor", encoding="utf-8")

    rc, kv, out = _prepare(project)

    assert rc == 0
    for name in state.RETIRED_SENTINELS:
        assert not (_sd(project) / name).exists(), f"arming must sweep the retired {name!r} sentinel"
    # And it says NOTHING about any of it. Printing `maintenance=off` on every arm caused a
    # fleet-wide escalation loop (owner report 2026-07-21): agents read the line as "the arm
    # just disabled maintenance", collided it with the heartbeat nudge's "do NOT disable
    # maintenance mode", and re-enabled maintenance at GLOBAL scope — which the next re-arm
    # could not clear, so every re-arm re-ran the same reasoning and ratcheted the whole fleet
    # into a suppression nothing lifted. There is no mode to report now, and no line about one.
    assert "maintenance" not in kv, f"the arm must never print a maintenance line, got {out!r}"


def test_prepare_sweeps_the_retired_GLOBAL_maintenance_flag(project: Path) -> None:
    """INVERTED. The arm used to leave the GLOBAL flag alone and merely REPORT it, because a
    project arm must not undo a deliberate machine-wide decision. There is no decision left to
    respect: the mode is gone, the flag is inert, and its own lever
    (/janitor-global-maintenance-off) went with it — while /janitor-global-arm is reached only
    after a DISARM. So without this sweep a host left in maintenance would keep that file
    forever, and every reader of the control plane would keep seeing a suspended machine.

    The kill-switch is deliberately NOT swept here — that one is still a live human decision
    (see the neighbouring guard)."""
    gs_dir = project / "gs"
    gs_dir.mkdir(parents=True)
    flag = gs_dir / "maintenance-mode.flag"
    flag.write_text("set by an older janitor", encoding="utf-8")

    rc, kv, _ = _prepare(project)

    assert rc == 0
    assert not flag.exists(), "an arm must sweep the retired global maintenance flag"
    assert "maintenance" not in kv, "and must not mention it"


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


def test_record_writes_the_persistent_armed_flag(project: Path) -> None:
    """TRDD-TUIBWHT7: a completed arm also records the machine-global "armed" claim that
    SessionStart reads via `armed_state()` — the thing that survives a restart when the
    session-only cron itself cannot."""
    rc, _, _ = _run(RECORD, project, "--cron", "*/15 * * * *", "--id", "1d703364")

    assert rc == 0
    armed_flag = project / "home" / ".claude" / "janitor-control" / "armed.flag"
    assert armed_flag.is_file(), "arm_record must persist the machine-global armed claim"


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


def test_skill_falls_back_to_a_full_sweep_when_the_targeted_delete_fails(project: Path) -> None:
    """A stale `heartbeat-cron-id.txt` must not make the skill trust `sweep=no` blindly (janitor#239).

    `sweep=no` only means "the stamp names an id" — it cannot tell a harmlessly-stale id (the cron
    died with the session, the stamp survived on disk) apart from a live cron under a DIFFERENT,
    unrecorded id (an arm interrupted between `CronCreate` and `arm_record.py`). A `CronDelete`
    that fails on the stamped id is consistent with the dangerous case, so the skill must instruct
    a fallback to the full `CronList` sweep on that failure — not "proceed, it's fine"."""
    text = (ROOT / "skills" / "janitor-arm" / "SKILL.md").read_text(encoding="utf-8")
    lowered = text.lower()
    assert "janitor#239" in text, "the fix must be traceable to the issue it closes"
    assert "fall back to the full sweep" in lowered
    assert "cronlist" in lowered.split("## 2. delete the old cron")[1].split("## 3.")[0], (
        "step 2 must actually instruct a CronList fallback, not just mention the concept elsewhere"
    )


def test_restricted_mode_refuses_the_arm_instead_of_promising_a_heartbeat(project: Path) -> None:
    """CC 2.1.248 `--restricted` strips Bash and ignores settings-file hooks, so an armed cron
    could never fire its dispatcher stub — the arm must REFUSE, not report success.

    Arming anyway is the dangerous outcome, not a harmless no-op: `armed.flag` would claim
    machine-wide protection that cannot exist in that session, and nothing downstream re-checks.
    The refusal reuses the existing `scope=refused` STOP contract so the skill needs no new
    branch to honor it."""
    env = {
        "PATH": "/usr/bin:/bin",
        "HOME": str(project / "home"),
        "CLAUDE_PROJECT_DIR": str(project),
        "CLAUDE_PLUGIN_DATA": str(project / "data"),
        "JANITOR_GLOBAL_STATE_DIR": str(project / "gs"),
        "CLAUDE_CODE_RESTRICTED": "1",
    }
    proc = subprocess.run(
        [sys.executable, str(PREPARE), "--plugin-root", str(ROOT), "--data-dir", str(project / "data")],
        capture_output=True,
        text=True,
        env=env,
        cwd=project,
    )
    assert proc.returncode != 0, "a refusal must be non-zero, or the skill arms anyway"
    assert "scope=refused" in proc.stdout, "must reuse the STOP contract the skill already honors"
    assert "restricted" in proc.stdout.lower()


def test_restricted_mode_predicate_has_ONE_home_and_errs_toward_refusing() -> None:
    """`doctor` and `arm_prepare` must decide "is this session restricted?" identically.

    Two hand-rolled parses is how the three-way drift recorded in `state.is_truthy_env` began —
    and here the two surfaces disagreeing means one of them claims protection the other says is
    impossible. The direction also matters: an unexpected-but-affirmative spelling must read as
    RESTRICTED, because guessing "not restricted" is what makes the janitor promise a guard that
    cannot fire."""
    import os

    for affirmative in ("1", "true", "yes", "on", "enabled"):
        os.environ["CLAUDE_CODE_RESTRICTED"] = affirmative
        assert state.restricted_mode() is True, f"{affirmative!r} must read as restricted"
    for negative in ("0", "false", "no", "off"):
        os.environ["CLAUDE_CODE_RESTRICTED"] = negative
        assert state.restricted_mode() is False, f"{negative!r} must not read as restricted"
    os.environ.pop("CLAUDE_CODE_RESTRICTED", None)
    assert state.restricted_mode() is False, "unset means a normal session"
