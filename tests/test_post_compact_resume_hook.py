"""Tests for the PostCompact resume hook (scripts/hooks/post-compact-resume.py).

The hook records WHAT the next heartbeat should auto-resume after a context
compaction. We test the three pure-ish helpers directly (`_explicit_directive`,
`_inflight_trdd_directive`, `_record_resume_directive`) plus one real
end-to-end subprocess run (no mocks — a JSON payload on stdin, a flag file on
disk).

Per-test isolation: $CLAUDE_PROJECT_DIR points at tmp_path so the user's real
state is never touched; the `state` module is reloaded so its lru_cached
project-root resolution picks up the env.
"""

from __future__ import annotations

import importlib.util as _u
import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

_HOOK_PATH = _PROJECT_ROOT / "scripts" / "hooks" / "post-compact-resume.py"


def _import_hook():
    """Import the hook script as a module (safe — no side effects at import)."""
    spec = _u.spec_from_file_location("post_compact_resume_under_test", str(_HOOK_PATH))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _write_trdd(
    tasks_dir: Path,
    uid8: str,
    column: str,
    updated: str,
    title: str,
    slug: str = "x",
) -> None:
    """Write a minimal but schema-valid TRDD with a canonical filename."""
    tasks_dir.mkdir(parents=True, exist_ok=True)
    fn = f"TRDD-20260602_044555+0200-{uid8}-{slug}.md"
    (tasks_dir / fn).write_text(
        "---\n"
        f"trdd-id: {uid8}-62d0-4788-88d5-2f2f3b3f1524\n"
        f"title: {title}\n"
        f"column: {column}\n"
        "created: 2026-06-02T04:45:55+0200\n"
        f"updated: {updated}\n"
        "---\n\nbody text\n",
        encoding="utf-8",
    )


@pytest.fixture
def state_mod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Fresh `state` module rooted at a tmp project dir."""
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    sys.modules.pop("state", None)
    import state  # noqa: PLC0415 - intentional per-test reload
    return project, state


# ---------- _explicit_directive -------------------------------------------

def test_explicit_directive_first_meaningful_line(tmp_path: Path) -> None:
    """Returns the first non-empty, non-comment line of resume-directive.txt."""
    hook = _import_hook()
    sd = tmp_path
    (sd / "resume-directive.txt").write_text(
        "# a comment\n\n   \ncontinue TRDD-deadbeef at P2\nignored second line\n",
        encoding="utf-8",
    )
    assert hook._explicit_directive(sd) == "continue TRDD-deadbeef at P2"


def test_explicit_directive_absent_returns_empty(tmp_path: Path) -> None:
    """No directive file → empty string (caller falls back to the board)."""
    hook = _import_hook()
    assert hook._explicit_directive(tmp_path) == ""


# ---------- _inflight_trdd_directive --------------------------------------

def test_inflight_picks_inflight_trdd(tmp_path: Path) -> None:
    """An in-flight (column: dev) TRDD yields a 'continue TRDD-<uid> (title)' line."""
    hook = _import_hook()
    tasks = tmp_path / "design" / "tasks"
    _write_trdd(tasks, "31095269", "dev", "2026-06-02T05:00:00+0200", "Context watchdog")
    out = hook._inflight_trdd_directive(tmp_path)
    assert out.startswith("continue TRDD-31095269 (Context watchdog)")
    assert "STATE block" in out


def test_inflight_ignores_parked_and_terminal(tmp_path: Path) -> None:
    """backburner / complete / published columns are NOT in-flight → empty."""
    hook = _import_hook()
    tasks = tmp_path / "design" / "tasks"
    _write_trdd(tasks, "aaaa0001", "backburner", "2026-06-02T05:00:00+0200", "Parked", "a")
    _write_trdd(tasks, "aaaa0002", "complete", "2026-06-02T06:00:00+0200", "Done", "b")
    _write_trdd(tasks, "aaaa0003", "published", "2026-06-02T07:00:00+0200", "Shipped", "c")
    assert hook._inflight_trdd_directive(tmp_path) == ""


def test_inflight_picks_newest_updated(tmp_path: Path) -> None:
    """With several in-flight TRDDs, the most recently `updated:` one wins."""
    hook = _import_hook()
    tasks = tmp_path / "design" / "tasks"
    _write_trdd(tasks, "11110000", "dev", "2026-06-01T10:00:00+0200", "Older", "older")
    _write_trdd(tasks, "22220000", "testing", "2026-06-02T09:30:00+0200", "Newer", "newer")
    out = hook._inflight_trdd_directive(tmp_path)
    assert "TRDD-22220000" in out
    assert "TRDD-11110000" not in out


def test_inflight_no_tasks_dir_returns_empty(tmp_path: Path) -> None:
    """No design/tasks/ directory at all → empty (no crash)."""
    hook = _import_hook()
    assert hook._inflight_trdd_directive(tmp_path) == ""


# ---------- _record_resume_directive --------------------------------------

def test_record_writes_flag_from_board(state_mod) -> None:
    """In-flight TRDD on the board → flag + ts written into the state dir."""
    project, state = state_mod
    hook = _import_hook()
    _write_trdd(project / "design" / "tasks", "31095269", "dev",
                "2026-06-02T05:00:00+0200", "Watchdog")
    hook._record_resume_directive(state)
    sd = state.state_dir()
    assert (sd / "resume-after-compact.flag").exists()
    assert (sd / "resume-after-compact.ts").exists()
    assert "TRDD-31095269" in (sd / "resume-after-compact.flag").read_text()
    # ts is a recent epoch second.
    assert abs(int((sd / "resume-after-compact.ts").read_text()) - int(time.time())) < 30


def test_record_explicit_directive_overrides_board(state_mod) -> None:
    """resume-directive.txt takes priority over the auto-detected board task."""
    project, state = state_mod
    hook = _import_hook()
    state.init_state()
    (state.state_dir() / "resume-directive.txt").write_text(
        "execute the handoff at docs_dev/handoff.md\n", encoding="utf-8"
    )
    _write_trdd(project / "design" / "tasks", "31095269", "dev",
                "2026-06-02T05:00:00+0200", "Watchdog")
    hook._record_resume_directive(state)
    flag = (state.state_dir() / "resume-after-compact.flag").read_text()
    assert flag == "execute the handoff at docs_dev/handoff.md"
    assert "TRDD-31095269" not in flag
    # One-shot: the directive file is consumed so a later auto-compact won't replay it.
    assert not (state.state_dir() / "resume-directive.txt").exists()


def test_record_consumes_directive_file_even_when_empty(state_mod) -> None:
    """A whitespace-only directive file is still consumed (one-shot), board used instead."""
    project, state = state_mod
    hook = _import_hook()
    state.init_state()
    (state.state_dir() / "resume-directive.txt").write_text("   \n# only a comment\n", encoding="utf-8")
    _write_trdd(project / "design" / "tasks", "31095269", "dev",
                "2026-06-02T05:00:00+0200", "Watchdog")
    hook._record_resume_directive(state)
    assert not (state.state_dir() / "resume-directive.txt").exists(), "must be consumed"
    # Fell back to the board since the file had no usable directive.
    assert "TRDD-31095269" in (state.state_dir() / "resume-after-compact.flag").read_text()


def test_record_no_inflight_writes_nothing(state_mod) -> None:
    """No directive file and no in-flight TRDD → NO flag (no spurious resume)."""
    project, state = state_mod
    hook = _import_hook()
    _write_trdd(project / "design" / "tasks", "deadbeef", "complete",
                "2026-06-02T05:00:00+0200", "Done")
    hook._record_resume_directive(state)
    assert not (state.state_dir() / "resume-after-compact.flag").exists()


# ---------- end-to-end subprocess -----------------------------------------

def test_hook_subprocess_writes_flag(tmp_path: Path) -> None:
    """Real run: PostCompact JSON on stdin → flag file on disk. No mocks.

    Runs the hook with the plain interpreter (the PEP-723 shebang is a comment
    to python3); CLAUDE_PLUGIN_ROOT points at the repo so `from lib import state`
    resolves, CLAUDE_PROJECT_DIR points at the tmp project.
    """
    project = tmp_path / "project"
    (project / "design" / "tasks").mkdir(parents=True)
    _write_trdd(project / "design" / "tasks", "31095269", "dev",
                "2026-06-02T05:00:00+0200", "Context watchdog")

    env = {
        "PATH": __import__("os").environ.get("PATH", ""),
        "CLAUDE_PLUGIN_ROOT": str(_PROJECT_ROOT),
        "CLAUDE_PROJECT_DIR": str(project),
        # Keep THIS test scoped to "flag written": disable the TRDD-HI0BGQGJ push so
        # the hook spawns no detached resume_trigger.py. The push path has its own
        # dedicated unit tests below (_maybe_push_resume).
        "CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ENABLED": "false",
    }
    payload = json.dumps(
        {"session_id": "sess-1", "cwd": str(project),
         "trigger": "manual", "hook_event_name": "PostCompact"}
    )
    proc = subprocess.run(
        [sys.executable, str(_HOOK_PATH)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0, f"hook must always exit 0; stderr={proc.stderr!r}"
    flag = project / ".janitor" / "state" / "resume-after-compact.flag"
    assert flag.exists(), f"flag not written; stderr={proc.stderr!r}"
    assert "TRDD-31095269" in flag.read_text()


# ---------- _record_resume_directive return value (the push gate) ---------
# TRDD-HI0BGQGJ: the push must fire ONLY when a resume target was actually recorded.
# _record_resume_directive returns that boolean; main() guards the push on it.

def test_record_returns_true_when_flag_written(state_mod) -> None:
    """An in-flight TRDD → a flag is written → returns True (the push is allowed)."""
    project, state = state_mod
    hook = _import_hook()
    _write_trdd(project / "design" / "tasks", "31095269", "dev",
                "2026-06-02T05:00:00+0200", "Watchdog")
    assert hook._record_resume_directive(state) is True


def test_record_returns_false_when_nothing_to_resume(state_mod) -> None:
    """No directive, no in-flight TRDD, no handoff → returns False (no push)."""
    project, state = state_mod
    hook = _import_hook()
    _write_trdd(project / "design" / "tasks", "deadbeef", "complete",
                "2026-06-02T05:00:00+0200", "Done")
    assert hook._record_resume_directive(state) is False


# ---------- _push_grace_s -------------------------------------------------

def test_push_grace_default(monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _import_hook()
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_GRACE_S", raising=False)
    assert hook._push_grace_s() == 20


def test_push_grace_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _import_hook()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_GRACE_S", "42")
    assert hook._push_grace_s() == 42


def test_push_grace_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _import_hook()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_GRACE_S", "notanint")
    assert hook._push_grace_s() == 20
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_GRACE_S", "-5")
    assert hook._push_grace_s() == 20


# ---------- _push_prompt_window_s (attended-SESSION window, TRDD-GRHP2YHP) --

def test_push_prompt_window_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The attended-session window defaults to 5 min — longer than the 20 s HID grace."""
    hook = _import_hook()
    monkeypatch.delenv(
        "CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_PROMPT_WINDOW_S", raising=False
    )
    assert hook._push_prompt_window_s() == 300


def test_push_prompt_window_env_override(monkeypatch: pytest.MonkeyPatch) -> None:
    """The window is env-overridable, distinct from the HID grace knob."""
    hook = _import_hook()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_PROMPT_WINDOW_S", "600")
    assert hook._push_prompt_window_s() == 600


def test_push_prompt_window_invalid_falls_back(monkeypatch: pytest.MonkeyPatch) -> None:
    """A non-int or negative window reverts to the 5 min default (fail-safe)."""
    hook = _import_hook()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_PROMPT_WINDOW_S", "notanint")
    assert hook._push_prompt_window_s() == 300
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_PROMPT_WINDOW_S", "-5")
    assert hook._push_prompt_window_s() == 300


# ---------- _user_recently_active (the attended detector) -----------------

def _write_presence(home: Path, last_epoch: int) -> None:
    """Write the cross-plugin user-presence breadcrumb under a controlled HOME."""
    p = home / ".aimaestro" / "state" / "user-presence.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"last_user_input_epoch": last_epoch, "source": "janitor",
             "written_at_epoch": last_epoch}
        ),
        encoding="utf-8",
    )


_PANE_ENV_VARS = ("TMUX_PANE", "ITERM_SESSION_ID", "KITTY_WINDOW_ID", "WEZTERM_PANE")


def _no_pane(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin the NO-PER-PANE-ID world (Apple Terminal, plain xterm), where the gate documents a
    fallback to the machine-global breadcrumb. Without this the test inherits the REAL pane id of
    whatever terminal runs pytest, so it silently exercises the per-pane branch instead."""
    for var in _PANE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


def _in_pane(monkeypatch: pytest.MonkeyPatch, pane: str = "%7") -> str:
    """Pin THIS process to a specific tmux pane and return its breadcrumb key."""
    for var in _PANE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("TMUX_PANE", pane)
    import state as _state

    key = _state.terminal_pane_key()
    assert key
    return key


def _write_pane_presence(home: Path, key: str, last_epoch: int) -> None:
    p = home / ".aimaestro" / "state" / "user-presence-panes" / f"{key}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps({"last_user_input_epoch": last_epoch, "written_at_epoch": last_epoch}),
        encoding="utf-8",
    )


def test_user_recently_active_true_when_recent(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    _no_pane(monkeypatch)  # this test pins the machine-global FALLBACK world
    monkeypatch.setenv("HOME", str(home))
    now = int(time.time())
    _write_presence(home, now - 5)
    # 4-arg (TRDD-GRHP2YHP): HID grace 20 (pinned None in tests), prompt-session window 180.
    assert hook._user_recently_active(state, now, 20, 180) is True


def test_user_recently_active_false_when_old(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    now = int(time.time())
    _write_presence(home, now - 10_000)
    assert hook._user_recently_active(state, now, 20, 180) is False


def test_user_recently_active_false_when_absent(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No breadcrumb at all → treat as UNATTENDED (fail-safe → the push may fire)."""
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    assert hook._user_recently_active(state, int(time.time()), 20, 180) is False


def test_user_recently_active_attended_by_prompt_beyond_hid_grace(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE FIX (TRDD-GRHP2YHP): a genuine prompt 2 min ago (no keystroke since) → ATTENDED.

    HID is pinned None in tests, so this exercises the breadcrumb window: 120 s is well past the
    20 s HID grace (the OLD code fired the push here) but inside the 300 s attended-session window.
    """
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    _no_pane(monkeypatch)  # this test pins the machine-global FALLBACK world
    monkeypatch.setenv("HOME", str(home))
    now = int(time.time())
    _write_presence(home, now - 120)  # last real prompt 2 min ago; reading since
    assert hook._user_recently_active(state, now, 20, 300) is True
    # Falsify the OLD behavior: with the window collapsed to the 20 s HID grace it read as away.
    assert hook._user_recently_active(state, now, 20, 20) is False


def test_user_recently_active_unattended_beyond_window(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No genuine prompt for longer than the window → UNATTENDED → the push still fires."""
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    now = int(time.time())
    _write_presence(home, now - 600)  # last prompt 10 min ago
    assert hook._user_recently_active(state, now, 20, 300) is False


# ---------- _maybe_push_resume (the three gates; falsifiable) --------------

def _patch_popen(monkeypatch: pytest.MonkeyPatch, hook) -> list:
    """Replace the hook's subprocess.Popen with a recorder; return the calls list."""
    calls: list = []
    monkeypatch.setattr(hook.subprocess, "Popen", lambda argv, **kw: calls.append(list(argv)))
    return calls


def test_push_fires_when_unattended(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unattended + enabled + trigger present → the detached resume_trigger.py is spawned."""
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))  # no presence file → unattended
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_PROJECT_ROOT))  # resume_trigger.py exists
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ENABLED", raising=False)
    calls = _patch_popen(monkeypatch, hook)
    hook._maybe_push_resume(state)
    assert len(calls) == 1, "push must fire when unattended + enabled + trigger present"
    assert calls[0][-1].endswith("resume_trigger.py")


def test_push_skips_when_attended(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FALSIFICATION of the attended gate: recent user input → NO push."""
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    _no_pane(monkeypatch)  # this test pins the machine-global FALLBACK world
    monkeypatch.setenv("HOME", str(home))
    _write_presence(home, int(time.time()) - 5)  # attended
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_PROJECT_ROOT))
    calls = _patch_popen(monkeypatch, hook)
    hook._maybe_push_resume(state)
    assert calls == [], "push must NOT fire while the user is recently active"


def test_push_skips_when_disabled(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FALSIFICATION of the enabled gate: config off → NO push even when unattended."""
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))  # unattended
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_PROJECT_ROOT))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ENABLED", "false")
    calls = _patch_popen(monkeypatch, hook)
    hook._maybe_push_resume(state)
    assert calls == [], "push must NOT fire when disabled by config"


def test_push_skips_when_no_plugin_root(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No CLAUDE_PLUGIN_ROOT → the injector can't be located → NO push (no crash)."""
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    calls = _patch_popen(monkeypatch, hook)
    hook._maybe_push_resume(state)
    assert calls == [], "push cannot fire without CLAUDE_PLUGIN_ROOT to locate the trigger"


def test_push_skips_when_attended_but_reading(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE FIX end-to-end (TRDD-GRHP2YHP): last prompt 2 min ago, no keystroke since → NO push.

    Reproduces the owner incident — submitted a prompt, then read a long reply for >20 s. With HID
    pinned None and the default 300 s window, 120 s reads as attended → the push is suppressed.
    """
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    _no_pane(monkeypatch)  # this test pins the machine-global FALLBACK world
    monkeypatch.setenv("HOME", str(home))
    _write_presence(home, int(time.time()) - 120)  # attended-but-reading
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_PROJECT_ROOT))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ENABLED", raising=False)
    calls = _patch_popen(monkeypatch, hook)
    hook._maybe_push_resume(state)
    assert calls == [], "push must NOT fire for an attended-but-reading user (last prompt 2 min ago)"


# --------------------------------------------------------------------------- #
# THE FLEET REGRESSION (2026-07-28): a busy pane must not strand every other one
# --------------------------------------------------------------------------- #


def test_a_user_typing_in_ANOTHER_pane_does_not_suppress_this_pane_s_resume(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE bug that left sessions dead for days.

    Measured on the live machine: five projects held an UNCONSUMED `resume-after-compact.flag`,
    two of them **4.3 days** old. The flag is cleared only by a heartbeat fire, so those sessions
    were woken by NEITHER path — and the push, the path that wakes them in seconds, had been
    suppressed every single time because the gate read the MACHINE-GLOBAL presence breadcrumb. For
    someone who works all day in one terminal, "a prompt somewhere in the last 5 minutes" is a
    permanent state, so every other pane on the machine was permanently "attended" and never
    resumed.

    `user_intent.user_is_present` was fixed for exactly this on 2026-07-16; this gate had kept its
    own machine-global read and so inherited the bug from next door.
    """
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    now = int(time.time())

    # The user is HERE on the machine and prompted 3 seconds ago — but in a DIFFERENT pane.
    _write_presence(home, now - 3)
    _write_pane_presence(home, "tmux-%1", now - 3)

    # We are pane %7, where nobody has ever typed.
    _in_pane(monkeypatch, "%7")
    assert hook._user_recently_active(state, now, 20, 300) is False, (
        "an unattended pane must resume even while the user is busy in another one"
    )


def test_this_pane_being_attended_still_suppresses_the_push(
    state_mod, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The other half of the contract — the per-pane read must not become a licence to type into a
    pane the user IS sitting in. Same machine, same instant, opposite verdict, and the only thing
    that differs is which pane the breadcrumb belongs to."""
    _project, state = state_mod
    hook = _import_hook()
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    now = int(time.time())

    key = _in_pane(monkeypatch, "%7")
    _write_pane_presence(home, key, now - 3)
    assert hook._user_recently_active(state, now, 20, 300) is True
