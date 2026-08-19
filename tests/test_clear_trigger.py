"""Tests for the /janitor-handoff-and-clear backing script (scripts/clear_trigger.py).

SAFETY: every test that exercises main() passes --dry-run and a controlled env, so
the real osascript /clear is NEVER fired (it would wipe the developer's own live
session — /clear is unrecoverable). The pure helpers are tested directly; main() is
tested via real subprocess runs with --dry-run.
"""

from __future__ import annotations

import importlib.util as _u
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "clear_trigger.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import state  # noqa: E402  # for the per-pane presence key (matches compact_trigger tests)


def _import():
    spec = _u.spec_from_file_location("clear_trigger_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _home(tmp: Path, *, present: bool, pane_id: str | None = None) -> Path:
    """A HOME carrying a presence breadcrumb that says the user IS / IS NOT here.

    Without this the tests inherit the DEVELOPER's real breadcrumb — a test that
    reports on the tester, not the code. Mirrors test_compact_trigger._home.
    """
    import json
    import time

    now = int(time.time())
    h = tmp / ("home-present" if present else "home-away")
    (h / ".aimaestro" / "state").mkdir(parents=True, exist_ok=True)
    stamp = now if present else 0
    payload = json.dumps({"last_user_input_epoch": stamp, "written_at_epoch": now})
    (h / ".aimaestro" / "state" / "user-presence.json").write_text(payload, encoding="utf-8")
    if present and pane_id is not None:
        key = state.terminal_pane_key({"ITERM_SESSION_ID": pane_id})
        assert key is not None
        pane_path = state.per_pane_presence_path(key, h)
        pane_path.parent.mkdir(parents=True, exist_ok=True)
        pane_path.write_text(payload, encoding="utf-8")
    return h


def _run(
    args: list[str],
    *,
    project: Path,
    iterm: str | None,
    home: Path | None = None,
    env_extra: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "CLAUDE_PROJECT_DIR": str(project)}
    if env_extra:
        env.update(env_extra)
    # Pin rung 0 (live HID) to "keyboard idle" unless a test overrides it: the real probe
    # reads the HOST's keyboard, so every real-subprocess test here was hostage to whether
    # a human touched the machine during its 30 s window (measured flake, 2026-08-20:
    # hid=0.6 s while the suite ran ⇒ the injector truthfully deferred ⇒ timeout).
    env.setdefault("JANITOR_HID_IDLE_OVERRIDE_S", "9999")
    # Pin the terminal-kind so these tests exercise the iTerm path deterministically
    # regardless of the host terminal (e.g. running the suite inside tmux).
    env["JANITOR_FORCE_TERMINAL_KIND"] = "iterm"
    if home is not None:
        env["HOME"] = str(home)
    if iterm is not None:
        env["ITERM_SESSION_ID"] = iterm
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _state_dir(project: Path) -> Path:
    return project / ".janitor" / "state"


# ---------- pure helpers ---------------------------------------------------

def test_plan_clear_is_clear_then_bootstrap() -> None:
    """The plan is exactly two phases: /clear, then re-arm + resume, in order."""
    mod = _import()
    phase_a, phase_b = mod.plan_clear()
    assert phase_a == ["/clear"]
    assert phase_b == ["/janitor-arm", "/janitor-resume"], "bootstrap re-arms THEN resumes"


def test_write_directive_and_marker_paths(monkeypatch, tmp_path: Path) -> None:
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    dpath = mod._write_directive("read the handoff, then continue TRDD-Z582IKIR")
    mpath = mod._write_clear_marker("read the handoff, then continue TRDD-Z582IKIR")
    sd = tmp_path / ".janitor" / "state"
    assert dpath == sd / "resume-directive.txt"
    assert mpath == sd / "resume-after-clear.flag"
    assert dpath.read_text(encoding="utf-8").strip() == "read the handoff, then continue TRDD-Z582IKIR"
    assert mpath.read_text(encoding="utf-8") == "read the handoff, then continue TRDD-Z582IKIR"
    assert (sd / "resume-after-clear.ts").is_file(), "the .ts sidecar must be written too"


def test_check_handoff_concise_accepts_link_only() -> None:
    """A short, reference-carrying, no-big-inline handoff passes the contract."""
    mod = _import()
    good = (
        "# Handoff\n\n"
        "NEXT: continue TRDD-Z582IKIR — read its STATE block.\n"
        "- decided the flag name because of X, see id:ATOM-AB12-CD34\n"
        "- open: rotator masks burn — [[oauth-rotator-burn]] / #101\n"
        "- recall the settle-delay rationale: memgrep recall \"clear settle\"\n"
    )
    ok, reasons = mod.check_handoff_concise(good)
    assert ok, f"a concise link-only handoff must pass, got {reasons}"


def test_check_handoff_concise_flags_too_large() -> None:
    """Over the byte budget → 'too-large' (not concise)."""
    mod = _import()
    big = "TRDD-Z582IKIR\n" + ("x" * 5000)
    ok, reasons = mod.check_handoff_concise(big)
    assert not ok and "too-large" in reasons


def test_check_handoff_concise_flags_no_references() -> None:
    """Carries no pointer into the payload store → 'no-references' (not exhaustive-by-ref)."""
    mod = _import()
    bare = "# Handoff\n\nI did some work and it went fine. Continue where I left off.\n"
    ok, reasons = mod.check_handoff_concise(bare)
    assert not ok and "no-references" in reasons


def test_check_handoff_concise_flags_inlined_block() -> None:
    """A large fenced block is inlined payload the handoff should LINK to → 'inlined-block'."""
    mod = _import()
    fenced = "TRDD-Z582IKIR\n\n```\n" + "\n".join(f"line {i}" for i in range(20)) + "\n```\n"
    ok, reasons = mod.check_handoff_concise(fenced)
    assert not ok and "inlined-block" in reasons


def test_build_osascript_soft_clear_targets_uuid() -> None:
    """iTerm osascript for /clear: targets the session id, SOFT (no ESC byte)."""
    mod = _import()
    osa = mod._build_osascript(
        "789D8299-5AA2-48CF-9325-3BC972B9BEAE", 2.0, commands=["/clear"]
    )
    assert '"789D8299-5AA2-48CF-9325-3BC972B9BEAE"' in osa
    assert '"/clear"' in osa
    assert "character id 27" not in osa, "the /clear phase must be SOFT (no ESC)"


def test_build_osascript_bootstrap_types_arm_then_resume() -> None:
    """iTerm osascript for the bootstrap: /janitor-arm typed before /janitor-resume."""
    mod = _import()
    osa = mod._build_osascript(
        "789D8299-5AA2-48CF-9325-3BC972B9BEAE",
        10.0,
        commands=["/janitor-arm", "/janitor-resume"],
    )
    assert osa.index('"/janitor-arm"') < osa.index('"/janitor-resume"'), "re-arm before resume"
    assert "character id 27" not in osa, "bootstrap is SOFT (no ESC)"


def test_uuid_regex_accepts_real_rejects_injection() -> None:
    """The UUID guard accepts a real session id and rejects AppleScript-injection."""
    mod = _import()
    assert mod._UUID_RE.match("789D8299-5AA2-48CF-9325-3BC972B9BEAE")
    for bad in (
        'x" then do shell script "touch /tmp/pwned" --',
        'abc"; tell app "Finder"',
        "id with spaces",
        "",
        "../../etc",
    ):
        assert not mod._UUID_RE.match(bad), f"{bad!r} must be rejected"


# ---------- main() via subprocess, ALWAYS --dry-run -----------------------

def test_dry_run_shows_the_CHAINED_plan_and_writes_NOTHING(tmp_path: Path) -> None:
    """--dry-run: the plan is printed (/clear THEN bootstrap), nothing fired, and — since
    TRDD-0BVF4K7E phase 2 — NO resume state is written.

    This test previously asserted the OPPOSITE (that a dry run persists the resume marker),
    and the change is deliberate, not a relaxation. The resume state is now written by the
    chained child at `pre_submit`, i.e. in the instant between "the field verifies as exactly
    /clear" and "Enter". That is the only moment at which "a clear is about to happen" is
    actually TRUE. Writing it from `main()` — as the old code did, and as this test encoded —
    means a chain that later DEFERS past its deadline (rule 2: the user started typing) leaves
    `resume-after-clear.flag` on disk for a clear that never ran.

    A dry run firing nothing must therefore write nothing; anything else is a mutation from a
    command whose whole contract is that it does not mutate."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run(
        [
            "--dry-run",
            "--directive",
            "read the handoff, then continue TRDD-Z582IKIR — read STATE block",
        ],
        project=p,
        iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE",
    )
    assert proc.returncode == 0, proc.stderr
    # The plan must show /clear BEFORE the bootstrap, and name both bootstrap commands.
    out = proc.stdout
    assert "DRY_RUN would chain /clear" in out
    assert out.index("/clear") < out.index("/janitor-arm") < out.index("/janitor-resume")
    assert "CLEAR_FIRED" not in out, "dry-run must not fire"
    assert "CLEAR_CHAIN_SPAWNED" not in out, "dry-run must not spawn the chain either"
    sd = _state_dir(p)
    for name in ("resume-directive.txt", "resume-after-clear.flag", "resume-after-clear.ts"):
        assert not (sd / name).exists(), f"a dry run must not write {name}"


def test_the_chain_is_spawned_on_a_readable_channel(tmp_path: Path) -> None:
    """A real (non-dry) run on a readable channel takes the CHAINED path — one verified
    sequence — and still writes no state up front; the child owns that now."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run([], project=p, iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE")
    assert proc.returncode == 0, proc.stderr
    assert "CLEAR_CHAIN_SPAWNED" in proc.stdout
    sd = _state_dir(p)
    assert not (sd / "resume-after-clear.flag").exists(), (
        "the flag must not exist until the child is about to press Enter on /clear (issue #105)"
    )


def test_dry_run_warns_on_bloated_handoff(tmp_path: Path) -> None:
    """A too-large handoff on disk is WARNED (stderr), but /clear still proceeds (fail-soft)."""
    p = tmp_path / "proj"
    p.mkdir()
    sd = _state_dir(p)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "agent-handoff.md").write_text("TRDD-Z582IKIR\n" + ("x" * 6000), encoding="utf-8")
    proc = _run(
        ["--dry-run", "--directive", "continue TRDD-Z582IKIR"],
        project=p,
        iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE",
    )
    assert proc.returncode == 0
    assert "HANDOFF_NOT_CONCISE" in proc.stderr and "too-large" in proc.stderr


def test_dry_run_warns_when_handoff_missing(tmp_path: Path) -> None:
    """No agent-handoff.md on disk → a loud stderr warning (/clear is unrecoverable)."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run(
        ["--dry-run", "--directive", "continue TRDD-Z582IKIR"],
        project=p,
        iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE",
    )
    assert proc.returncode == 0
    assert "HANDOFF_MISSING" in proc.stderr


def test_a_deferred_clear_writes_NO_resume_state(tmp_path: Path) -> None:
    """SUPERSEDED IN PART, and the surviving half is the one that mattered.

    This used to assert `USER_PRESENT` — that a user at the keyboard is never typed at, ever.
    That cancel is GONE (owner directive 2026-08-02: *"the old system that cancelled a command
    or prevented the agent to execute it if the user is PRESENT must go"*), because it is how
    the owner, typing `/janitor-handoff-and-clear` themselves, was told to go away. Presence
    now DEFERS: wait for an empty field and 8s of no keystrokes, then proceed.

    What SURVIVES unchanged is the issue #105 invariant, and deferral must not weaken it: when
    the clear does NOT fire, NO resume state may be left behind. Previously the flag was written
    even when the clear was refused, so the next heartbeat consumed
    `resume-after-clear.flag`, emitted a spurious [janitor-resume], and cleared it — silently
    disarming a later MANUAL /clear's auto-resume. The wait therefore returns BEFORE any write,
    exactly where the cancel used to sit."""
    p = tmp_path / "proj"
    p.mkdir()
    pane = "w0t0p0:11111111-2222-3333-4444-555555555555"
    proc = _run(
        ["--directive", "continue TRDD-Z582IKIR"],
        project=p,
        iterm=pane,
        home=_home(tmp_path, present=True, pane_id=pane),
        # The deferral under test happens in the chained CHILD (giveup 0 ⇒ it gives up
        # before firing); the parent's own 120 s pane-free wait must NOT be the thing
        # deferring, so the _run-level idle HID pin (9999) is exactly right here too —
        # pinning rung 0 to "typing" instead parks the parent in its hard-coded 120 s
        # wait and times the subprocess out (found while making this file hermetic).
        env_extra={"JANITOR_INJECT_GIVEUP_S": "0"},
    )
    assert proc.returncode == 0
    assert "CLEAR_FIRED" not in proc.stdout, "a deferred clear must not fire"
    assert not (_state_dir(p) / "resume-after-clear.flag").exists()
    assert not (_state_dir(p) / "resume-after-clear.ts").exists()
    assert not (_state_dir(p) / "resume-directive.txt").exists()
    assert "CLEAR_MARKER_WRITTEN" not in proc.stdout


def test_no_iterm_reports_and_still_records_state(tmp_path: Path) -> None:
    """No automatable pane: prints NO_ITERM but the resume state is still recorded."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run(
        ["--directive", "continue TRDD-Z582IKIR"],
        project=p,
        iterm=None,
        home=_home(tmp_path, present=False),
    )
    assert proc.returncode == 0
    assert "NO_ITERM" in proc.stdout
    assert "CLEAR_FIRED" not in proc.stdout
    assert (_state_dir(p) / "resume-after-clear.flag").is_file()


def test_malformed_iterm_id_refuses_to_fire(tmp_path: Path) -> None:
    """An injection-shaped ITERM_SESSION_ID is rejected (NO_ITERM), never executed;
    the resume state is still recorded."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run(
        ["--directive", "continue TRDD-Z582IKIR"],
        project=p,
        iterm='x:" then do shell script "touch /tmp/pwned_clear" --',
        home=_home(tmp_path, present=False),
    )
    assert proc.returncode == 0
    assert "NO_ITERM" in proc.stdout
    assert "CLEAR_FIRED" not in proc.stdout
    assert (_state_dir(p) / "resume-after-clear.flag").is_file()
    assert not Path("/tmp/pwned_clear").exists(), "the AppleScript injection must never execute"
