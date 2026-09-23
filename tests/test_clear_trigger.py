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


def _chain_payload_with_transcript(tmp_path: Path, *, transcript: str, terminal: dict,
                                    directive: str = "resume") -> str:
    """`_chain_payload` plus a `transcript_path` and a caller-chosen `terminal` dict -- the two
    fields TRDD-RAEGS1D5 card 5 added to the chain payload for the per-pane sidecar."""
    import base64
    import json as _json

    payload = {
        "delay": 0.0,
        "terminal": terminal,
        "first": "/clear",
        "then": ["/janitor-arm", "/janitor-resume"],
        "state_dir": str(tmp_path / ".janitor" / "state"),
        "gate_baseline": 0,
        "directive": directive,
        "transcript_path": transcript,
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



NBSP = " "


def _real_pane_text(field: str) -> str:
    """Shaped like a real tmux/iTerm capture: box rule, marker + NBSP + field, box rule --
    same fixture convention as `tests/test_inject_still_wanted.py::_pane`. The shape is
    load-bearing: an invented pane format parses as 'busy' to `prompt_field_is_empty`/
    `prompt_field_shows_only`, which silently defeats the whole point of driving the real
    `inject_until_sent` state machine below."""
    return "some earlier output\n" + "─" * 40 + f"\n❯{NBSP}{field}\n" + "─" * 40 + "\n"


def _fake_tmux_io(monkeypatch, mod):
    """TRDD-RAEGS1D5 card 5 item 4: patches ONLY the two I/O primitives
    `terminal_trigger` bottoms out on for a tmux channel -- `subprocess.run` (the keystroke
    sender `terminal_trigger._run_steps` uses for `tmux send-keys`) and
    `terminal_trigger.state.run_subprocess` (the pane read-back `read_pane_text`'s tmux
    branch uses for `tmux capture-pane`) -- against a tiny stateful pane. Everything ABOVE
    that -- `inject_until_sent`'s type/read-back/submit state machine, `run_chained_inject`'s
    gate wait, and `_run_chain_payload`'s real `still_wanted`/`pre_submit_first` closures --
    is unmodified production code, never a test-controlled fake of `run_chained_inject`
    itself (the shape the two tests this replaces used, and the shape that made them
    self-fulfilling: whether `pre_submit_first` ran was decided by the TEST, not by any
    real cancel logic).

    Returns the mutable `field` dict so a test can assert nothing was ever typed.
    """
    field = {"text": ""}

    def _fake_run(argv, **_kwargs):
        # argv shape fixed by `terminal_trigger.build_type_only_steps` /
        # `build_submit_steps` / `build_clear_field_steps`:
        #   ["tmux", "send-keys", "-t", pane, "-l", text]   (type)
        #   ["tmux", "send-keys", "-t", pane, "Enter"]       (submit)
        #   ["tmux", "send-keys", "-t", pane, "C-a"|"C-k"|"C-u"]  (clear)
        if len(argv) >= 5 and argv[0] == "tmux" and argv[1] == "send-keys":
            key = argv[4]
            if key == "-l" and len(argv) >= 6:
                field["text"] = argv[5]
            elif key in ("Enter", "C-a", "C-k", "C-u"):
                field["text"] = ""
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(subprocess, "run", _fake_run)

    def _fake_run_subprocess(cmd, **_kwargs):
        if cmd[:2] == ["tmux", "capture-pane"]:
            return subprocess.CompletedProcess(cmd, 0, stdout=_real_pane_text(field["text"]))
        return subprocess.CompletedProcess(cmd, 1)

    monkeypatch.setattr(mod.terminal_trigger.state, "run_subprocess", _fake_run_subprocess)
    return field


def _no_agents_no_interrupt_no_typing(monkeypatch) -> None:
    """`_no_agents_no_interrupt` plus a `user_intent.typing_now` stub -- needed ONLY by a
    test that drives the REAL `inject_until_sent` (via `_fake_tmux_io`), whose default
    `is_typing` probe lazily imports `user_intent.typing_now`. Every OTHER test in this file
    replaces `run_chained_inject` wholesale, so `inject_until_sent` never runs and never
    reaches that probe -- adding it to the shared `_no_agents_no_interrupt` would be an
    unused, misleading attribute on every other caller."""
    _no_agents_no_interrupt(monkeypatch)
    ui = sys.modules["user_intent"]
    ui.typing_now = lambda *a, **kw: False  # type: ignore[attr-defined]


def _real_chain_payload(tmp_path: Path, *, count_toward_cooldown: bool) -> str:
    """`_payload_with_cooldown_flag`, but with a REAL tmux pane id -- `_fake_tmux_io`'s
    fakes key off `valid_tmux_pane`, which a bare `{"kind": "tmux"}` (no `pane`) fails."""
    import base64
    import json as _json

    payload = {
        "delay": 0.0,
        "terminal": {"kind": "tmux", "pane": "%1"},
        "first": "/clear",
        "then": ["/janitor-arm", "/janitor-resume"],
        "state_dir": str(tmp_path / ".janitor" / "state"),
        "gate_baseline": 0,
        "directive": "resume",
        "count_toward_cooldown": count_toward_cooldown,
    }
    return base64.b64encode(_json.dumps(payload).encode("utf-8")).decode("ascii")


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

def _no_agents_no_interrupt(monkeypatch) -> None:
    """Baseline fakes so `_agents_and_interrupt_ok` returns True and `_recovery_ok` is the
    only cancel under test."""
    fake_pa = types.ModuleType("pending_agents")
    fake_pa.load_pending = lambda now=None, *, state_dir=None: []  # type: ignore[attr-defined]
    fake_pa.agent_is_live = lambda entry, now, stale_s: False  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pending_agents", fake_pa)

    fake_ui = types.ModuleType("user_intent")
    fake_ui.recently_interrupted = lambda *a, **kw: None  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "user_intent", fake_ui)


def test_still_wanted_cancels_on_a_pending_rate_limit_flag(tmp_path: Path, monkeypatch) -> None:
    """TRDD-RAEGS1D5 card 5 item 2: a rate-limit / API-error resume still unconsumed on disk
    means the interrupted task has not yet been replayed to the model -- a /clear right now
    would destroy the context that replay needs. `rate-limited.flag` alone must veto."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / mod.state.RATE_LIMITED_FLAG).write_text("1", encoding="utf-8")

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok, why = captured["still_wanted"]()
    assert ok is False
    assert "recovery pending" in why


def test_still_wanted_cancels_on_an_unconsumed_compact_resume(tmp_path: Path, monkeypatch) -> None:
    """The compact-resume flag is the second recovery-pending signal: dispatch.py's own
    `_phase_compact_resume` has not yet replayed the compacted task to the model."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / "resume-after-compact.flag").write_text("1", encoding="utf-8")

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok, why = captured["still_wanted"]()
    assert ok is False
    assert "recovery pending" in why


def test_still_wanted_ignores_its_own_resume_after_clear_flag(tmp_path: Path, monkeypatch) -> None:
    """`resume-after-clear.flag` must NOT veto once THIS chain has itself written it (via
    `_persist_resume_state`, captured here as `pre_submit_first` and invoked directly rather
    than pre-seeded on disk) -- a retry loop that re-validates `still_wanted` after that write
    (Enter deferred on a busy pane, the chain loops again) must not self-veto on its own write.

    Deliberately does NOT pre-write the flag by hand: `_recovery_ok` keys off `persisted["done"]`
    (this process's own record of its own write), not off file existence, precisely so a STALE
    flag from a different chain instance (crash, or another pane) still vetoes -- see
    `test_still_wanted_still_vetoes_on_a_stale_resume_after_clear_flag` below for that case."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    mod._run_chain_payload(_chain_payload(tmp_path))
    captured["pre_submit_first"]()  # simulates THIS chain having just written the flag

    ok, why = captured["still_wanted"]()
    assert ok is True, why

def test_still_wanted_still_vetoes_on_a_stale_resume_after_clear_flag(
    tmp_path: Path, monkeypatch,
) -> None:
    """A `resume-after-clear.flag` already on disk BEFORE this chain instance has written
    anything is necessarily a STALE marker -- from a crashed prior chain, or another pane's
    still-pending one (the state dir is per-project, not per-pane) -- and must still veto.
    This is the failure mode a blind existence check would miss (adversarial review finding,
    TRDD-RAEGS1D5 card 5): only `persisted["done"]` can distinguish "mine" from "someone else's"."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / "resume-after-clear.flag").write_text("continue TRDD-Z582IKIR", encoding="utf-8")

    mod._run_chain_payload(_chain_payload(tmp_path))
    # `pre_submit_first` is deliberately NEVER called here -- this chain instance has not
    # written anything, so `persisted["done"]` stays False.

    ok, why = captured["still_wanted"]()
    assert ok is False
    assert "recovery pending" in why

def test_still_wanted_cancels_when_the_pane_shows_the_retry_wedge(tmp_path: Path, monkeypatch) -> None:
    """FIFTH cancel (owner report §3.6): a pane showing the retry-wedge banner is a state
    `pane_policy` will type into on its own (the rotation/no-headroom flush) -- `/clear` must
    not race it. Reuses the real captured wedge fixture, classified with `pane_state.parse`
    (the same classifier `pane_policy` reads), never a reimplementation."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    wedge_text = (
        _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames" / "real-wedged-session-limit.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(mod.terminal_trigger, "read_pane_text", lambda terminal: wedge_text)

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok, why = captured["still_wanted"]()
    assert ok is False
    assert "retry_wedge" in why


def test_still_wanted_proceeds_over_a_normal_idle_pane(tmp_path: Path, monkeypatch) -> None:
    """The counterpart: a pane classified as an ordinary idle prompt (not wedged) must NOT be
    vetoed by the new check -- `/clear` still needs to be able to type into a normal idle
    pane, which is the state it exists to type into."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    idle_text = (
        _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames" / "synthetic-idle-empty-field.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(mod.terminal_trigger, "read_pane_text", lambda terminal: idle_text)

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok, why = captured["still_wanted"]()
    assert ok is True, why


def test_still_wanted_repeats_the_wedge_veto_until_the_pane_state_changes(
    tmp_path: Path, monkeypatch,
) -> None:
    """`still_wanted` is re-asked on EVERY iteration (the chain can defer for minutes) -- the
    wedge veto must keep firing, WITHOUT stamping the cooldown, for as long as the pane stays
    wedged, and only stop once the pane text actually changes. No loop is driven here (that is
    `inject_until_sent`'s own job); this pins that repeated calls give the same answer while
    wedged, and a different one the moment the fixture is swapped for an idle frame."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    frames = _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames"
    wedge_text = (frames / "real-wedged-session-limit.txt").read_text(encoding="utf-8")
    idle_text = (frames / "synthetic-idle-empty-field.txt").read_text(encoding="utf-8")
    current = {"text": wedge_text}
    monkeypatch.setattr(mod.terminal_trigger, "read_pane_text", lambda terminal: current["text"])

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok1, why1 = captured["still_wanted"]()
    ok2, why2 = captured["still_wanted"]()
    assert ok1 is False and ok2 is False, (why1, why2)
    assert "retry_wedge" in why1 and "retry_wedge" in why2

    current["text"] = idle_text
    ok3, why3 = captured["still_wanted"]()
    assert ok3 is True, why3



def test_still_wanted_cancels_when_the_current_model_window_is_exhausted_now(
    tmp_path: Path, monkeypatch
) -> None:
    """Refinement (c), orchestrator review: `_pane_policy_conflict_ok` also vetoes on a
    usage-PERCENTAGE verdict invisible in pane text -- reusing (never reimplementing) the
    REAL `token_burn.model_fallback_verdict`, the same function `detectors/model-fallback.py`
    calls (only `rotator_usage` is faked here, to supply the account -- `token_burn` runs
    for real against a crafted usage payload, closing a review gap the first draft of this
    test left open: faking BOTH modules only proved `_pane_policy_conflict_ok` wires a
    verdict-shaped dict into a veto, never that the real function's `require_active=True`
    semantics -- exhausted at 100%, not merely high -- actually hold here.
    `test_window_burn_rate.py::test_model_fallback_require_active_*` separately proves that
    truth table against `token_burn.model_fallback_verdict` in isolation; this test proves
    `clear_trigger.py`'s own integration with it). Pane text is a normal idle prompt -- this
    veto must fire independently of the RETRY_WEDGE one above."""
    import datetime as _dt

    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    idle_text = (
        _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames" / "synthetic-idle-empty-field.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(mod.terminal_trigger, "read_pane_text", lambda terminal: idle_text)

    now = int(_dt.datetime.now(tz=_dt.timezone.utc).timestamp())
    resets_at = (
        _dt.datetime.fromtimestamp(now + 3600, tz=_dt.timezone.utc)
        .replace(tzinfo=None).isoformat() + "Z"
    )
    # Same shape /api/oauth/usage emits (test_window_burn_rate.py's `_usage`/`_limit`
    # helpers, verified against a live payload 2026-08-01): account windows comfortable,
    # ONE model-scoped weekly limit at 100% -- the only reading `require_active=True`
    # accepts.
    usage = {
        "five_hour": {"utilization": 20.0, "resets_at": resets_at},
        "seven_day": {"utilization": 20.0, "resets_at": resets_at},
        "limits": [
            {
                "kind": "weekly_scoped", "group": "weekly", "percent": 100.0,
                "severity": "critical", "resets_at": resets_at,
                "scope": {"model": {"id": None, "display_name": "Fable"}, "surface": None},
                "is_active": True,
            },
        ],
    }
    fake_ru = types.ModuleType("rotator_usage")
    fake_ru.accounts_usage = (  # type: ignore[attr-defined]
        lambda: [{"is_live": True, "usage": usage, "sample_age_s": 5}]
    )
    monkeypatch.setitem(sys.modules, "rotator_usage", fake_ru)

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok, why = captured["still_wanted"]()
    assert ok is False
    assert "exhausted now" in why
    assert "Fable" in why


def test_still_wanted_proceeds_when_no_live_account_usage_is_available(
    tmp_path: Path, monkeypatch
) -> None:
    """Fail-open side of the same veto: no live-account sample (the daemon's own usage-scan
    heartbeat has not run, or the rotator has no live account at all) must never cancel a
    pending clear -- an unmeasured window is not a proven-exhausted one, same asymmetry as
    every other cancel in this function."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)


    idle_text = (
        _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames" / "synthetic-idle-empty-field.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(mod.terminal_trigger, "read_pane_text", lambda terminal: idle_text)

    fake_ru = types.ModuleType("rotator_usage")
    fake_ru.accounts_usage = lambda: []  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "rotator_usage", fake_ru)

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok, why = captured["still_wanted"]()
    assert ok is True, why


def test_pane_policy_veto_log_is_rate_limited_across_repeated_polls(
    tmp_path: Path, monkeypatch
) -> None:
    """Refinement (b), orchestrator review: `still_wanted` is re-asked roughly every 8s for
    up to an hour, so an un-rate-limited log line per veto could write ~450 lines for one
    stuck pane. Three consecutive polls of the SAME wedge must log at most once."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    wedge_text = (
        _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames" / "real-wedged-session-limit.txt"
    ).read_text(encoding="utf-8")
    monkeypatch.setattr(mod.terminal_trigger, "read_pane_text", lambda terminal: wedge_text)

    mod._run_chain_payload(_chain_payload(tmp_path))

    for _ in range(3):
        ok, _why = captured["still_wanted"]()
        assert ok is False

    veto_lines = [line for line in logs if "veto — pane shows retry_wedge" in line]
    assert len(veto_lines) == 1, veto_lines


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



# --- TRDD-RAEGS1D5 card 5: the per-pane sidecar `_persist_resume_state` writes when the
# chain payload names a transcript -----------------------------------------------------------


def test_persist_resume_state_writes_a_per_pane_sidecar_when_a_transcript_is_named(
    tmp_path: Path, monkeypatch,
) -> None:
    """When the payload carries `transcript_path`, `_persist_resume_state` writes
    `resume-after-clear.<pane-key>.transcript` -- the ONE thing the fresh session's dedicated
    hook consumes to know WHICH transcript this clear was for."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    captured = _capture_still_wanted(mod, monkeypatch)

    payload = _chain_payload_with_transcript(tmp_path, transcript="/tmp/real-transcript.jsonl",
                                              terminal={"kind": "tmux", "pane": "%3"})
    mod._run_chain_payload(payload)
    captured["pre_submit_first"]()

    pane_key = state.terminal_pane_key({"TMUX_PANE": "%3"})
    sidecar = tmp_path / ".janitor" / "state" / f"resume-after-clear.{pane_key}.transcript"
    assert sidecar.is_file(), "expected a per-pane sidecar naming the cleared transcript"
    lines = sidecar.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "/tmp/real-transcript.jsonl"
    assert int(lines[1]) > 0


def test_persist_resume_state_writes_no_sidecar_without_a_transcript(
    tmp_path: Path, monkeypatch,
) -> None:
    """`reload_trigger.py --shrink` (and any caller that names no transcript) must write NO
    sidecar -- a reload is not a compaction, so nothing should later Jev-compact it."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    captured = _capture_still_wanted(mod, monkeypatch)

    mod._run_chain_payload(_chain_payload(tmp_path))
    captured["pre_submit_first"]()

    sd = tmp_path / ".janitor" / "state"
    assert not list(sd.glob("resume-after-clear.*.transcript")), (
        "no transcript in the payload must mean no sidecar on disk"
    )


def test_two_panes_sidecars_do_not_cross(tmp_path: Path, monkeypatch) -> None:
    """Two chains firing for two different panes of the same project must each write their
    OWN sidecar, keyed by pane -- never overwrite or merge into one file."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    captured_a = _capture_still_wanted(mod, monkeypatch)
    payload_a = _chain_payload_with_transcript(
        tmp_path, transcript="/tmp/pane-a.jsonl", terminal={"kind": "tmux", "pane": "%1"},
    )
    mod._run_chain_payload(payload_a)
    captured_a["pre_submit_first"]()

    captured_b = _capture_still_wanted(mod, monkeypatch)
    payload_b = _chain_payload_with_transcript(
        tmp_path, transcript="/tmp/pane-b.jsonl", terminal={"kind": "tmux", "pane": "%2"},
    )
    mod._run_chain_payload(payload_b)
    captured_b["pre_submit_first"]()

    sd = tmp_path / ".janitor" / "state"
    key_a = state.terminal_pane_key({"TMUX_PANE": "%1"})
    key_b = state.terminal_pane_key({"TMUX_PANE": "%2"})
    text_a = (sd / f"resume-after-clear.{key_a}.transcript").read_text(encoding="utf-8")
    text_b = (sd / f"resume-after-clear.{key_b}.transcript").read_text(encoding="utf-8")
    assert "/tmp/pane-a.jsonl" in text_a
    assert "/tmp/pane-b.jsonl" in text_b
    assert text_a != text_b


def test_spawn_shrink_chain_carries_transcript_path_into_the_payload(
    tmp_path: Path, monkeypatch,
) -> None:
    """`spawn_shrink_chain`'s own `transcript_path` argument must reach `_spawn_chain`'s
    payload dict (not just the `JANITOR_TRANSCRIPT_PATH` env var) -- that dict key is what
    `_persist_resume_state` reads to decide whether to write a sidecar at all."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setattr(mod.terminal_trigger, "self_terminal", lambda env: {"kind": "tmux", "pane": "%5"})
    monkeypatch.setattr(mod.terminal_trigger, "channel_is_readable", lambda t: True)

    captured: dict = {}

    def _fake_spawn(payload, *, env=None):
        captured["payload"] = payload

    monkeypatch.setattr(mod, "_spawn_chain", _fake_spawn)

    spawned, why = mod.spawn_shrink_chain(
        then=["/janitor-arm", "/janitor-resume"], directive="resume",
        transcript_path="/tmp/shrink-me.jsonl",
    )
    assert spawned, why
    assert captured["payload"]["transcript_path"] == "/tmp/shrink-me.jsonl"


def test_spawn_shrink_chain_transcript_path_defaults_to_none(tmp_path: Path, monkeypatch) -> None:
    """`reload_trigger.py --shrink` never passes `transcript_path` -- the payload key must
    default to `None`, not be silently omitted (which would read the same to a `.get()`
    caller, but this pins the CONTRACT explicitly)."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setattr(mod.terminal_trigger, "self_terminal", lambda env: {"kind": "tmux", "pane": "%6"})
    monkeypatch.setattr(mod.terminal_trigger, "channel_is_readable", lambda t: True)

    captured: dict = {}

    def _fake_spawn(payload, *, env=None):
        captured["payload"] = payload

    monkeypatch.setattr(mod, "_spawn_chain", _fake_spawn)

    mod.spawn_shrink_chain(then=["/janitor-arm", "/janitor-resume"], directive="resume")
    assert captured["payload"]["transcript_path"] is None

def test_spawn_shrink_chain_never_stamps_the_cooldown_itself(tmp_path: Path, monkeypatch) -> None:
    """Regression fix (post-2f463d3b review): the PARENT `spawn_shrink_chain` must never stamp
    the cooldown at spawn time -- only the CHILD, immediately before the verified Enter, may.
    Spawning (with the default `count_toward_cooldown=True`) must leave the cooldown untouched."""
    import time as _time

    import cold_cache_compact

    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setattr(mod.terminal_trigger, "self_terminal", lambda env: {"kind": "tmux", "pane": "%9"})
    monkeypatch.setattr(mod.terminal_trigger, "channel_is_readable", lambda t: True)
    monkeypatch.setattr(mod, "_spawn_chain", lambda payload, *, env=None: None)

    spawned, why = mod.spawn_shrink_chain(then=["/janitor-arm", "/janitor-resume"], directive="resume")
    assert spawned, why

    sd = tmp_path / ".janitor" / "state"
    assert cold_cache_compact.clear_in_cooldown(sd, now=int(_time.time())) is False


def test_spawn_shrink_chain_carries_count_toward_cooldown_into_the_payload(tmp_path: Path, monkeypatch) -> None:
    """The flag must reach `_spawn_chain`'s payload dict so the CHILD can act on it -- this is
    the seam the regression fix moved the stamp to."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setattr(mod.terminal_trigger, "self_terminal", lambda env: {"kind": "tmux", "pane": "%9"})
    monkeypatch.setattr(mod.terminal_trigger, "channel_is_readable", lambda t: True)

    captured: dict = {}

    def _fake_spawn(payload, *, env=None):
        captured["payload"] = payload

    monkeypatch.setattr(mod, "_spawn_chain", _fake_spawn)

    mod.spawn_shrink_chain(
        then=["/janitor-arm", "/janitor-resume"], directive="resume", count_toward_cooldown=False,
    )
    assert captured["payload"]["count_toward_cooldown"] is False

    mod.spawn_shrink_chain(then=["/janitor-arm", "/janitor-resume"], directive="resume")
    assert captured["payload"]["count_toward_cooldown"] is True


def _payload_with_cooldown_flag(tmp_path: Path, *, count_toward_cooldown: bool) -> str:
    import base64
    import json as _json

    payload = {
        "delay": 0.0,
        "terminal": {"kind": "tmux"},
        "first": "/clear",
        "then": ["/janitor-arm", "/janitor-resume"],
        "state_dir": str(tmp_path / ".janitor" / "state"),
        "gate_baseline": 0,
        "directive": "resume",
        "count_toward_cooldown": count_toward_cooldown,
    }
    return base64.b64encode(_json.dumps(payload).encode("utf-8")).decode("ascii")


def test_completed_chain_with_cooldown_flag_stamps_at_verified_enter(tmp_path: Path, monkeypatch) -> None:
    """The regression case, positive side, driven through the REAL
    `terminal_trigger.run_chained_inject` (TRDD-RAEGS1D5 card 5 item 4 -- replaces the
    earlier version, which asserted only that a TEST-CONTROLLED fake of `run_chained_inject`
    decided to call `pre_submit_first`, never that the real `still_wanted`/`inject_until_sent`
    machinery reaches it). `still_wanted` never vetoes here (no recovery flags, no wedge, no
    live agent), so the real chain types `/clear`, reaches the verified Enter for real, and
    that must leave `clear_in_cooldown` True."""
    import time as _time

    import cold_cache_compact

    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_HID_IDLE_OVERRIDE_S", "9999")
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    _no_agents_no_interrupt_no_typing(monkeypatch)
    field = _fake_tmux_io(monkeypatch, mod)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / mod._GATE_STAMP).write_text("999999999999", encoding="utf-8")  # already > baseline 0

    rc = mod._run_chain_payload(_real_chain_payload(tmp_path, count_toward_cooldown=True))

    assert rc == 0
    assert field["text"] == "", "the final Enter must have cleared the field"
    assert cold_cache_compact.clear_in_cooldown(sd, now=int(_time.time())) is True



def test_aborted_before_enter_chain_never_stamps_the_cooldown(tmp_path: Path, monkeypatch) -> None:
    """The regression case, negative side, driven through the REAL
    `terminal_trigger.run_chained_inject` (TRDD-RAEGS1D5 card 5 item 4 -- replaces the
    earlier version, which never called `pre_submit_first` only because the TEST chose not
    to, not because any real cancel fired). A FRESH `rate-limited.flag` makes the real
    `_recovery_ok` cancel fire on the very first `still_wanted()` poll inside
    `inject_until_sent` -- before it ever reads the pane to type -- so `pre_submit_first`
    must never run, no keystroke must ever be sent, and the cooldown must stay untouched so a
    real clear can still fire for the rest of the window."""
    import time as _time

    import cold_cache_compact

    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_HID_IDLE_OVERRIDE_S", "9999")
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    _no_agents_no_interrupt_no_typing(monkeypatch)
    field = _fake_tmux_io(monkeypatch, mod)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / mod.state.RATE_LIMITED_FLAG).write_text("1", encoding="utf-8")
    (sd / "rate-limited-since.ts").write_text(str(int(_time.time())), encoding="utf-8")

    rc = mod._run_chain_payload(_real_chain_payload(tmp_path, count_toward_cooldown=True))

    assert rc == 1
    assert field["text"] == "", "cancelled before the first type_fn() ever ran"
    assert cold_cache_compact.clear_in_cooldown(sd, now=int(_time.time())) is False


def test_still_wanted_ignores_a_stale_rate_limit_flag_past_its_max_age(tmp_path: Path, monkeypatch) -> None:
    """Lockout fix (post-2f463d3b review): `rate-limited.flag` is written on EVERY turn-ending
    API error and nothing synchronous consumes it, so an orphaned flag older than the daemon's
    own sweep window (`CLAUDE_PLUGIN_OPTION_RATE_LIMIT_FLAG_MAX_AGE_HOURS`, default 24h) must
    stop vetoing here -- exactly when it stops mattering to the daemon's own sweep too."""
    import time as _time

    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / mod.state.RATE_LIMITED_FLAG).write_text("1", encoding="utf-8")
    stale_since = int(_time.time()) - (25 * 3600)  # 25h old, past the 24h default
    (sd / "rate-limited-since.ts").write_text(str(stale_since), encoding="utf-8")

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok, why = captured["still_wanted"]()
    assert ok is True, why


def test_still_wanted_still_vetoes_on_a_fresh_rate_limit_flag(tmp_path: Path, monkeypatch) -> None:
    """The other side of the age bound: a flag well within its max age must still veto -- the
    bound only releases a genuinely orphaned flag, never a live one."""
    import time as _time

    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / mod.state.RATE_LIMITED_FLAG).write_text("1", encoding="utf-8")
    fresh_since = int(_time.time()) - 60  # 1 minute old
    (sd / "rate-limited-since.ts").write_text(str(fresh_since), encoding="utf-8")

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok, why = captured["still_wanted"]()
    assert ok is False
    assert "recovery pending" in why



def test_still_wanted_ignores_an_orphan_rate_limit_flag_with_no_since_sidecar(
    tmp_path: Path, monkeypatch
) -> None:
    """Item 1 (orchestrator review of 1b5ceec8): `rate-limited-since.ts` missing used to make
    `read_int_state(since, now_ts)`'s own default read as age 0 -- FRESH FOREVER, an orphaned
    flag (no sidecar ever written for it) vetoing every automatic /clear indefinitely. Falls
    back to the flag's own (old) mtime, the same pattern `on-session-start.py` already uses
    for this exact flag -- a flag whose mtime alone is already past the max age must not veto
    just because its `.ts` sidecar happens to be missing."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    import time as _time

    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    flag = sd / mod.state.RATE_LIMITED_FLAG
    flag.write_text("1", encoding="utf-8")
    old = int(_time.time()) - (25 * 3600)  # 25h old, past the 24h default
    os.utime(flag, (old, old))
    assert not (sd / "rate-limited-since.ts").exists(), "the orphan case: no sidecar at all"

    mod._run_chain_payload(_chain_payload(tmp_path))

    ok, why = captured["still_wanted"]()
    assert ok is True, why


def _chain_payload_with_recovered_after(tmp_path: Path, *, recovered_after: int) -> str:
    import base64
    import json as _json

    payload = {
        "delay": 0.0,
        "terminal": {"kind": "tmux"},
        "first": "/clear",
        "then": ["/janitor-arm", "/janitor-resume"],
        "state_dir": str(tmp_path / ".janitor" / "state"),
        "gate_baseline": 0,
        "directive": "resume",
        "recovered_after": recovered_after,
    }
    return base64.b64encode(_json.dumps(payload).encode("utf-8")).decode("ascii")


def test_recovered_after_ignores_a_fresh_rate_limit_flag_predating_it(
    tmp_path: Path, monkeypatch
) -> None:
    """Item 2: `on-stop-token-meter.py` only calls `_maybe_clear` after a Stop that
    SUCCEEDED -- proof this session already ran a full turn past whatever earlier
    rate-limit/API-error wrote `rate-limited.flag`, however fresh that flag still reads on
    its own 24h clock. `recovered_after` (this Stop's own epoch) must let `_recovery_ok`
    ignore a flag written BEFORE it, even though the same flag alone (no `recovered_after`)
    still vetoes -- see the sibling test below."""
    import time as _time

    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / mod.state.RATE_LIMITED_FLAG).write_text("1", encoding="utf-8")
    since = int(_time.time()) - 60  # 1 minute old -- still "fresh" on the plain age check
    (sd / "rate-limited-since.ts").write_text(str(since), encoding="utf-8")

    mod._run_chain_payload(_chain_payload_with_recovered_after(tmp_path, recovered_after=int(_time.time())))

    ok, why = captured["still_wanted"]()
    assert ok is True, why


def test_the_idle_path_keeps_the_veto_on_the_same_fresh_flag_with_no_recovered_after(
    tmp_path: Path, monkeypatch
) -> None:
    """Item 2, the other side: a caller with no successful-Stop evidence of its own (the
    idle-nudge path, `dispatch.py`) passes no `recovered_after` and must keep vetoing on the
    SAME fresh flag the test above bypasses -- the bypass is per-caller, not a global
    loosening of the age check."""
    import time as _time

    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / mod.state.RATE_LIMITED_FLAG).write_text("1", encoding="utf-8")
    since = int(_time.time()) - 60
    (sd / "rate-limited-since.ts").write_text(str(since), encoding="utf-8")

    mod._run_chain_payload(_chain_payload(tmp_path))  # no recovered_after

    ok, why = captured["still_wanted"]()
    assert ok is False
    assert "recovery pending" in why


def test_persisted_done_is_set_before_the_flag_write_so_a_raise_cannot_self_veto(
    tmp_path: Path, monkeypatch,
) -> None:
    """Self-veto ordering fix (post-2f463d3b review): `persisted["done"]` must be True BEFORE
    `_write_clear_marker` is attempted, not after -- so a chain whose write raises AFTER landing
    the flag on disk can never mistake its OWN flag for someone else's unconsumed recovery on a
    later `still_wanted` re-check."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    real_write_clear_marker = mod._write_clear_marker

    def _write_then_raise(directive):
        real_write_clear_marker(directive)  # the flag DOES land on disk
        raise OSError("simulated crash right after the write")

    monkeypatch.setattr(mod, "_write_clear_marker", _write_then_raise)

    mod._run_chain_payload(_chain_payload(tmp_path))
    raised = False
    try:
        captured["pre_submit_first"]()
    except OSError:
        raised = True
    assert raised, "expected the simulated OSError to propagate"

    ok, why = captured["still_wanted"]()
    assert ok is True, why


def test_still_wanted_is_stable_across_repeated_checks_until_the_flag_is_gone(
    tmp_path: Path, monkeypatch,
) -> None:
    """No-loop guarantee: as long as a fresh recovery flag is on disk, repeated `still_wanted`
    re-checks (simulating repeated Stop-hook fires while the flag is unconsumed) keep vetoing --
    never flip to True by themselves. The moment the flag is consumed (unlinked, the way
    dispatch.py's own resume phase does), the SAME check flips to True."""
    mod = _import()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / mod.state.RATE_LIMITED_FLAG).write_text("1", encoding="utf-8")

    mod._run_chain_payload(_chain_payload(tmp_path))

    for _ in range(3):
        ok, why = captured["still_wanted"]()
        assert ok is False, why

    (sd / mod.state.RATE_LIMITED_FLAG).unlink()  # consumed, the way dispatch.py's own phase does

    ok, why = captured["still_wanted"]()
    assert ok is True, why
