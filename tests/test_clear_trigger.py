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
) -> subprocess.CompletedProcess:
    env = {"PATH": os.environ.get("PATH", ""), "CLAUDE_PROJECT_DIR": str(project)}
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

def test_dry_run_writes_resume_state_and_plan(tmp_path: Path) -> None:
    """--dry-run: resume-directive + resume-after-clear marker written, plan printed
    (/clear THEN bootstrap), NOTHING fired."""
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
    assert "DIRECTIVE_WRITTEN" in proc.stdout
    assert "CLEAR_MARKER_WRITTEN" in proc.stdout
    # The plan must show /clear BEFORE the bootstrap, and name both bootstrap commands.
    out = proc.stdout
    assert "DRY_RUN would fire /clear" in out
    assert out.index("/clear") < out.index("/janitor-arm") < out.index("/janitor-resume")
    assert "CLEAR_FIRED" not in out, "dry-run must not fire"
    sd = _state_dir(p)
    assert (sd / "resume-directive.txt").is_file()
    assert (sd / "resume-after-clear.flag").read_text(encoding="utf-8").startswith("read the handoff")
    assert (sd / "resume-after-clear.ts").is_file()


def test_dry_run_default_directive_when_omitted(tmp_path: Path) -> None:
    """No --directive: a fallback pointer at the link-only handoff is still persisted,
    so the post-clear cron always has a resume target (no PostClear hook to synthesise one)."""
    p = tmp_path / "proj"
    p.mkdir()
    proc = _run(
        ["--dry-run"], project=p, iterm="w0t3p0:789D8299-5AA2-48CF-9325-3BC972B9BEAE"
    )
    assert proc.returncode == 0, proc.stderr
    flag = _state_dir(p) / "resume-after-clear.flag"
    assert flag.is_file()
    assert "agent-handoff.md" in flag.read_text(encoding="utf-8"), "fallback points at the handoff"


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


def test_present_user_is_never_typed_at_and_no_resume_flag_written(tmp_path: Path) -> None:
    """The presence gate (issue #105 fix): a user at the keyboard is never typed at (it would
    clobber their input AND wipe their session), AND — the fix — NO resume state is written.

    Previously the flag was recorded even on USER_PRESENT, but /clear never fired, so the next
    heartbeat consumed `resume-after-clear.flag`, emitted a spurious [janitor-resume], and
    cleared it — silently disarming a later MANUAL /clear's auto-resume. The gate now runs
    BEFORE the writes, so a refused clear leaves nothing behind for a heartbeat to consume."""
    p = tmp_path / "proj"
    p.mkdir()
    pane = "w0t0p0:11111111-2222-3333-4444-555555555555"
    proc = _run(
        ["--directive", "continue TRDD-Z582IKIR"],
        project=p,
        iterm=pane,
        home=_home(tmp_path, present=True, pane_id=pane),
    )
    assert proc.returncode == 0
    assert "USER_PRESENT" in proc.stdout
    assert "CLEAR_FIRED" not in proc.stdout, "must NOT clear a session the user is using"
    # The fix: with /clear refused, the resume flag/marker/directive are NOT written, so no
    # heartbeat can consume them and disarm a later manual /clear (issue #105).
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
