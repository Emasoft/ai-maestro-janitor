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
import types
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "clear_trigger.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import handoff_files  # noqa: E402  # COMPOSED_MARKER — the marker is defined there, never retyped
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



def _seed_handoff(project: Path) -> Path:
    """A real `/clear` now REFUSES without a handoff (owner invariant 2026-08-28), so any test
    exercising the non-dry path must seed one. Kept minimal and concise-contract-clean so it
    warns about nothing and only satisfies the existence gate."""
    sd = _state_dir(project)
    sd.mkdir(parents=True, exist_ok=True)
    h = sd / "agent-handoff.md"
    h.write_text(
        "# Handoff\n\nNEXT ACTION: continue TRDD-Z582IKIR.\nSee design/tasks/ for the card.\n",
        encoding="utf-8",
    )
    return h


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


def test_a_composer_handoff_is_exempt_from_size_and_references_but_not_the_fence() -> None:
    """TRDD-L46IG69Y — the marker lifts `too-large` + `no-references`, and NOT `inlined-block`.

    ONE payload violating all three, asserted twice, because the split is the whole point: the
    same bytes must yield all three unmarked and exactly `inlined-block` marked. Two payloads
    could not show that the marker is what moved, and asserting only the marked half would pass
    on a check that had stopped working for everyone.

    WHY the first two lift: they restate the link-only DESIGN (concise, exhaustive by
    REFERENCE); an `llm-ext` summary is exhaustive by INCLUSION by design, and measured over
    every composer handoff this host had (n=5) it ran 5.8-9.9x the budget — `too-large` on every
    run, and an always-firing warning trains its reader to ignore it.

    WHY the fence does NOT lift, and an earlier draft that lifted it was wrong: its predicate is
    "you pasted a big blob", which stays true of prose — it is llm-ext quoting a file instead of
    summarizing it. It fired 0/5, so it is a check that earned its keep by staying quiet.
    """
    mod = _import()
    body = (
        "prose with no pointers at all.\n"
        "```\n" + "\n".join(f"line {i}" for i in range(20)) + "\n```\n" + ("x" * 5000)
    )
    ok, reasons = mod.check_handoff_concise(body)
    assert not ok and set(reasons) == {"too-large", "no-references", "inlined-block"}, (
        f"positive control failed — the payload must violate all three unmarked, got {reasons}"
    )
    ok, reasons = mod.check_handoff_concise(f"{handoff_files.COMPOSED_MARKER}\n{body}")
    assert not ok and reasons == ["inlined-block"], (
        f"the marker must lift exactly too-large + no-references, got {reasons}"
    )


def test_the_exemption_needs_the_marker_at_the_top_not_merely_present() -> None:
    """The marker EXEMPTS, so a handoff must not be able to earn it by quoting the string.

    A model-authored handoff that discusses this mechanism (this repo's handoffs discuss the
    janitor constantly) would otherwise exempt itself by mentioning the marker mid-prose, and
    the check would go quietly dead on the one producer it is for.
    """
    mod = _import()
    quoting = (
        "TRDD-L46IG69Y\n\n"
        f"the composer stamps `{handoff_files.COMPOSED_MARKER}` on its output.\n"
        + ("x" * 5000)
    )
    ok, reasons = mod.check_handoff_concise(quoting)
    assert not ok and "too-large" in reasons, (
        f"only a LEADING marker may exempt; a quoted one must not, got {reasons}"
    )


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
    _seed_handoff(p)
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
    _seed_handoff(p)
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
    _seed_handoff(p)
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
    _seed_handoff(p)
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


# ---------- TRDD-11GAS4LC addendum: the third `_still_wanted` cancel + land logging -------
#
# The chain can defer for minutes (`inject_until_sent`) between the Stop hook's decision and
# the verified Enter, so a background agent spawned meanwhile, or a fresh interrupt, must be
# able to cancel a /clear that is still in flight. These drive `_run_chain_payload` directly
# (base64 JSON payload, exactly what `_spawn_chain` hands the detached child), with
# `terminal_trigger.run_chained_inject` replaced by a capture so no real keystroke or pane
# I/O ever happens, and `pending_agents`/`user_intent`/`token_meter` faked via `sys.modules`
# (the chain imports them lazily by name).


def _chain_payload(tmp_path: Path, *, directive: str = "resume") -> str:
    import base64
    import json as _json

    payload = {
        "delay": 0.0,
        "terminal": {"kind": "tmux"},
        "first": "/clear",
        "then": ["/janitor-arm", "/janitor-resume"],
        "state_dir": str(tmp_path / ".janitor" / "state"),
        "gate_baseline": 0,
        "directive": directive,
    }
    return base64.b64encode(_json.dumps(payload).encode("utf-8")).decode("ascii")


def _capture_still_wanted(mod, monkeypatch) -> dict:
    """Replace `terminal_trigger.run_chained_inject` with a capture of the callbacks
    `_run_chain_payload` builds, instead of running any real pane I/O."""
    captured: dict = {}

    def _fake(_terminal, **kwargs):
        captured["still_wanted"] = kwargs["still_wanted"]
        captured["pre_submit_first"] = kwargs["pre_submit_first"]
        return True, "ok"

    monkeypatch.setattr(mod.terminal_trigger, "run_chained_inject", _fake)
    return captured


def test_still_wanted_cancels_on_a_live_agent(tmp_path: Path, monkeypatch) -> None:
    """A background agent (review fork, lean-worker) spawned after the verdict must still
    be able to cancel a /clear that has not landed yet."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)

    fake_pa = types.ModuleType("pending_agents")
    fake_pa.load_pending = lambda now=None, *, state_dir=None: [{"id": "a1"}]  # type: ignore[attr-defined]
    fake_pa.agent_is_live = lambda entry, now, stale_s: True  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pending_agents", fake_pa)

    rc = mod._run_chain_payload(_chain_payload(tmp_path))
    assert rc == 0

    ok, why = captured["still_wanted"]()
    assert ok is False
    assert "agent(s) live" in why


def test_still_wanted_cancels_on_a_recent_interrupt(tmp_path: Path, monkeypatch) -> None:
    """A bare Esc/Ctrl-C with no completed turn yet trips neither `_user_came_back` nor a
    live-agent check -- only the interrupt-cooldown check catches it."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)

    fake_pa = types.ModuleType("pending_agents")
    fake_pa.load_pending = lambda now=None, *, state_dir=None: []  # type: ignore[attr-defined]
    fake_pa.agent_is_live = lambda entry, now, stale_s: False  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pending_agents", fake_pa)

    fake_ui = types.ModuleType("user_intent")
    fake_ui.recently_interrupted = lambda *a, **kw: 12.0  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "user_intent", fake_ui)

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok, why = captured["still_wanted"]()
    assert ok is False
    assert "interrupted" in why


def test_cancel_at_land_gets_its_own_distinct_log_line(tmp_path: Path, monkeypatch) -> None:
    """A `still_wanted`-cancelled chain logs `clear cancelled at land: <reason>` on top of
    the plain FAILED line, so the miss rate is greppable on its own."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    monkeypatch.setattr(
        mod.terminal_trigger,
        "run_chained_inject",
        lambda _t, **_kw: (False, "cancelled — the session took a real turn"),
    )

    mod._run_chain_payload(_chain_payload(tmp_path))

    assert any("clear cancelled at land: the session took a real turn" in ln for ln in logs), logs


def test_persist_resume_state_logs_context_size_at_land(tmp_path: Path, monkeypatch) -> None:
    """The moment /clear actually lands (immediately before the verified Enter), the
    context size at that instant is logged -- this can be minutes after the Stop hook's
    own decision, and the gap is otherwise unmeasurable."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    monkeypatch.setenv("JANITOR_TRANSCRIPT_PATH", str(tmp_path / "t.jsonl"))

    fake_tm = types.ModuleType("token_meter")
    fake_tm.latest_context_size = lambda _p: 760_000  # type: ignore[attr-defined]
    fake_tm.default_window = lambda *a, **kw: 900_000  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "token_meter", fake_tm)

    captured = _capture_still_wanted(mod, monkeypatch)
    mod._run_chain_payload(_chain_payload(tmp_path))
    captured["pre_submit_first"]()

    assert any("clear landing at 760000 tokens (84% of window)" in ln for ln in logs), logs
