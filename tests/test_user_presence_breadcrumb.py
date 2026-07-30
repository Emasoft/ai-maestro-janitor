"""Tests for the host-level user-presence breadcrumb (TRDD-fb4850b5, janitor#15).

The breadcrumb is a cross-plugin host file the MANAGER's `amama-presence-tracker`
reads as a *server-unreachable fallback*:

    ~/.aimaestro/state/user-presence.json
    {"last_user_input_epoch": <int>, "source": "janitor", "written_at_epoch": <int>}

Two writers, two responsibilities:

  - `scripts/hooks/on-prompt-submit.py` (UserPromptSubmit hook) bumps BOTH epochs
    on a GENUINE user prompt, but must NOT bump on a cron-injected `[janitor-…]`
    prompt — those arrive on the identical UserPromptSubmit channel and the only
    discriminator is the prompt-text prefix. Getting that wrong reports the user
    "present" every heartbeat forever (the load-bearing trap).

  - `scripts/dispatch.py` (the heartbeat) refreshes `written_at_epoch` (liveness)
    each tick WITHOUT touching `last_user_input_epoch`, preserving the existing
    value when the file exists+parses and seeding `0` when it is new/corrupt.

`HOME` is redirected to a tmp dir so the real host file is never touched; the hook
resolves the path via `Path.home()`, which honors that override naturally.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "on-prompt-submit.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import state  # noqa: E402


def _breadcrumb_path(home: Path) -> Path:
    """The on-disk breadcrumb path under the (tmp) HOME the test pins."""
    return home / ".aimaestro" / "state" / "user-presence.json"


def _run_hook(prompt: str, home: Path) -> tuple[int, str, str]:
    """Invoke the prompt-submit hook with a crafted UserPromptSubmit stdin JSON."""
    import os

    env = dict(os.environ)
    env["HOME"] = str(home)
    # CLAUDE_PLUGIN_ROOT is set so the hook does not early-return on the unset guard.
    env["CLAUDE_PLUGIN_ROOT"] = str(_PROJECT_ROOT)
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


# --------------------------------------------------------------------------
# (a) a genuine prompt bumps last_user_input_epoch
# --------------------------------------------------------------------------


def test_genuine_prompt_writes_breadcrumb(tmp_path):
    """A real user prompt writes the breadcrumb with both epochs set and source=janitor."""
    home = tmp_path / "home"
    rc, out, _err = _run_hook("how do I rotate the oauth token?", home)
    assert rc == 0
    assert out.strip() == ""  # the hook injects nothing into the agent context
    data = json.loads(_breadcrumb_path(home).read_text())
    assert data["source"] == "janitor"
    assert isinstance(data["last_user_input_epoch"], int)
    assert isinstance(data["written_at_epoch"], int)
    assert data["last_user_input_epoch"] > 0
    # On a genuine bump the two epochs are stamped together.
    assert data["last_user_input_epoch"] == data["written_at_epoch"]
    # Exactly the agreed three-field contract — no extra fields.
    assert set(data.keys()) == {"last_user_input_epoch", "source", "written_at_epoch"}


def test_genuine_prompt_advances_last_user_input_epoch(tmp_path):
    """A second genuine prompt advances last_user_input_epoch past a stale prior value."""
    home = tmp_path / "home"
    path = _breadcrumb_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Seed an old breadcrumb; the genuine prompt must overwrite it with `now`.
    path.write_text(json.dumps({"last_user_input_epoch": 1, "source": "janitor", "written_at_epoch": 1}))
    rc, _out, _err = _run_hook("a real question from the user", home)
    assert rc == 0
    data = json.loads(path.read_text())
    assert data["last_user_input_epoch"] > 1


# --------------------------------------------------------------------------
# (b) a [janitor-heartbeat] prompt does NOT bump (file untouched/absent)
# --------------------------------------------------------------------------


def test_janitor_heartbeat_prompt_does_not_create_breadcrumb(tmp_path):
    """A cron `[janitor-heartbeat]` prompt is NOT user presence — the file stays absent."""
    home = tmp_path / "home"
    rc, out, _err = _run_hook("[janitor-heartbeat] run the drift detectors", home)
    assert rc == 0
    assert out.strip() == ""
    assert not _breadcrumb_path(home).exists()


def test_janitor_directive_prompt_does_not_touch_existing_breadcrumb(tmp_path):
    """ANY `[janitor-…]` directive leaves an existing last_user_input_epoch untouched."""
    home = tmp_path / "home"
    path = _breadcrumb_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    seeded = {"last_user_input_epoch": 12345, "source": "janitor", "written_at_epoch": 12345}
    path.write_text(json.dumps(seeded))
    rc, _out, _err = _run_hook("[janitor-resume] continue TRDD-abc", home)
    assert rc == 0
    # The cron-injected prompt must not bump presence — bytes unchanged.
    assert json.loads(path.read_text()) == seeded


def test_leading_whitespace_janitor_marker_is_still_skipped(tmp_path):
    """A `[janitor-…]` marker preceded by whitespace is still recognised as cron, not user."""
    home = tmp_path / "home"
    rc, _out, _err = _run_hook("   [janitor-heartbeat] tick", home)
    assert rc == 0
    assert not _breadcrumb_path(home).exists()


def test_marker_below_a_PREPENDED_block_is_still_cron_not_presence(tmp_path):
    """A cron fire whose prompt has text PREPENDED must not stamp presence (issue #113).

    The offset-0 `startswith` assumed the janitor's text is the first thing in
    `payload["prompt"]`. On a host where something prepends — another plugin's
    UserPromptSubmit hook, or the ai-maestro CLI wrapping a delivered prompt — the marker
    moves and every cron fire was recorded as GENUINE USER INPUT. Measured effect there:
    `recent_activity` stuck True on an unattended session, so the TTL-aware cadence
    oscillated SLOW↔MID and burned five re-arm turns in 2.5 h — the feature spending turns
    instead of saving them.
    """
    home = tmp_path / "home"
    path = _breadcrumb_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    seeded = {"last_user_input_epoch": 12345, "source": "janitor", "written_at_epoch": 12345}
    path.write_text(json.dumps(seeded))

    prompt = (
        "<pss-skills>\n  ops-next [skill] (HIGH, 1.00)\n</pss-skills>\n"
        "[janitor-heartbeat]\n/path/to/dispatcher-stub.py\nHandle this fire's stdout.\n"
    )
    rc, _out, _err = _run_hook(prompt, home)

    assert rc == 0
    assert json.loads(path.read_text()) == seeded          # untouched — not presence


def test_a_marker_buried_PAST_the_scan_window_is_treated_as_user_input(tmp_path):
    """The scan is bounded, and that boundary is deliberate — assert where it lies.

    Scanning the whole prompt would let any human message mentioning `[janitor-…]` at the
    start of some later line silently suppress its own presence stamp. Five lines clears a
    prepended context block without turning a long human prompt into a cron fire.
    """
    home = tmp_path / "home"
    prompt = "\n".join(["human line"] * 8 + ["[janitor-heartbeat]"])
    rc, _out, _err = _run_hook(prompt, home)

    assert rc == 0
    assert _breadcrumb_path(home).exists()                  # treated as genuine input


# --------------------------------------------------------------------------
# (c) heartbeat refresh updates written_at_epoch, leaves last_user_input_epoch
# --------------------------------------------------------------------------


def test_refresh_updates_written_at_only(tmp_path):
    """The heartbeat refresh bumps written_at_epoch but preserves last_user_input_epoch."""
    home = tmp_path / "home"
    path = _breadcrumb_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_user_input_epoch": 555, "source": "janitor", "written_at_epoch": 555}))
    state.refresh_user_presence_written_at(home=home, now=999)
    data = json.loads(path.read_text())
    assert data["last_user_input_epoch"] == 555  # untouched — input recency preserved
    assert data["written_at_epoch"] == 999  # liveness advanced
    assert data["source"] == "janitor"
    assert set(data.keys()) == {"last_user_input_epoch", "source", "written_at_epoch"}


# --------------------------------------------------------------------------
# (d) corrupt/new existing file → refresh seeds 0 without crashing
# --------------------------------------------------------------------------


def test_refresh_seeds_zero_when_file_corrupt(tmp_path):
    """A corrupt breadcrumb is reseeded: last_user_input_epoch=0, written_at_epoch=now, no crash."""
    home = tmp_path / "home"
    path = _breadcrumb_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("}{ this is not valid json")
    state.refresh_user_presence_written_at(home=home, now=42)
    data = json.loads(path.read_text())
    assert data["last_user_input_epoch"] == 0
    assert data["written_at_epoch"] == 42
    assert data["source"] == "janitor"


def test_refresh_seeds_zero_when_file_absent(tmp_path):
    """A first heartbeat with no breadcrumb yet seeds last_user_input_epoch=0 and writes the file."""
    home = tmp_path / "home"
    path = _breadcrumb_path(home)
    assert not path.exists()
    state.refresh_user_presence_written_at(home=home, now=77)
    data = json.loads(path.read_text())
    assert data["last_user_input_epoch"] == 0
    assert data["written_at_epoch"] == 77
    assert data["source"] == "janitor"


def test_refresh_recovers_non_dict_json(tmp_path):
    """A breadcrumb that parses to a non-dict (e.g. a list) is reseeded, not crashed on."""
    home = tmp_path / "home"
    path = _breadcrumb_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([1, 2, 3]))
    state.refresh_user_presence_written_at(home=home, now=88)
    data = json.loads(path.read_text())
    assert data["last_user_input_epoch"] == 0
    assert data["written_at_epoch"] == 88


def test_refresh_coerces_non_int_last_user_input_epoch(tmp_path):
    """A breadcrumb whose last_user_input_epoch is non-int is reseeded to 0 (defensive)."""
    home = tmp_path / "home"
    path = _breadcrumb_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"last_user_input_epoch": "nope", "source": "x", "written_at_epoch": 1}))
    state.refresh_user_presence_written_at(home=home, now=100)
    data = json.loads(path.read_text())
    assert data["last_user_input_epoch"] == 0
    assert data["written_at_epoch"] == 100
    assert data["source"] == "janitor"


# --------------------------------------------------------------------------
# (e) the hook exits 0 on garbage stdin
# --------------------------------------------------------------------------


def test_garbage_stdin_is_noop(tmp_path):
    """Garbage on stdin (not JSON) must not crash the session — exit 0, no breadcrumb."""
    import os

    home = tmp_path / "home"
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PROJECT_ROOT)
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input="this is not json {{{",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert proc.stdout.strip() == ""
    assert not _breadcrumb_path(home).exists()


def test_empty_stdin_is_noop(tmp_path):
    """Empty stdin is a no-op: exit 0, no breadcrumb written."""
    import os

    home = tmp_path / "home"
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PROJECT_ROOT)
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input="",
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert not _breadcrumb_path(home).exists()


def test_missing_prompt_key_is_noop(tmp_path):
    """A JSON payload with no `prompt` key is a no-op (no crash, no breadcrumb)."""
    import os

    home = tmp_path / "home"
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PROJECT_ROOT)
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps({"hook_event_name": "UserPromptSubmit"}),
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )
    assert proc.returncode == 0
    assert not _breadcrumb_path(home).exists()


# --------------------------------------------------------------------------
# wiring: hook registered under UserPromptSubmit
# --------------------------------------------------------------------------


def test_hook_is_registered_in_hooks_json():
    """on-prompt-submit.py is wired under UserPromptSubmit in hooks/hooks.json and exists."""
    hooks_json = json.loads((_PROJECT_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    ups = hooks_json["hooks"]["UserPromptSubmit"]
    commands = [h["command"] for entry in ups for h in entry["hooks"]]
    assert any("on-prompt-submit.py" in c for c in commands), "prompt-submit hook not registered"
    assert _HOOK.is_file()


# --------------------------------------------------------------------------
# (c) PER-PANE presence (user directive 2026-07-16)
# --------------------------------------------------------------------------


def _run_hook_env(prompt: str, home: Path, extra_env: dict[str, str]) -> int:
    """Invoke the hook with extra env (e.g. a pane id) merged in. Returns the exit code."""
    import os

    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PROJECT_ROOT)
    env.update(extra_env)
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": prompt}),
        capture_output=True, text=True, env=env, timeout=30,
    )
    return proc.returncode


def test_terminal_pane_key_namespaces_by_source_and_sanitizes():
    """The key is `<source>-<sanitized id>`; tmux wins, then iTerm/kitty/WezTerm; unsafe runs → one
    '-' trimmed at the ends; a terminal with no per-pane id → None."""
    # tmux is preferred and focus-independent; '%' is not filename-safe → collapses, leading '-' trimmed.
    assert state.terminal_pane_key({"TMUX_PANE": "%3"}) == "tmux-3"
    assert state.terminal_pane_key({"TMUX_PANE": "%3", "ITERM_SESSION_ID": "w0t1p0:UUID"}) == "tmux-3"
    # iTerm fallback; ':' → '-'.
    assert state.terminal_pane_key({"ITERM_SESSION_ID": "w0t1p0:ABC-DEF"}) == "iterm-w0t1p0-ABC-DEF"
    # Other terminal types are detected too (the user's "another type of terminal" requirement).
    assert state.terminal_pane_key({"KITTY_WINDOW_ID": "3"}) == "kitty-3"
    assert state.terminal_pane_key({"WEZTERM_PANE": "0"}) == "wezterm-0"
    # Precedence: iTerm beats kitty beats WezTerm when several are present.
    assert state.terminal_pane_key({"ITERM_SESSION_ID": "s", "KITTY_WINDOW_ID": "3"}) == "iterm-s"
    assert state.terminal_pane_key({"KITTY_WINDOW_ID": "3", "WEZTERM_PANE": "0"}) == "kitty-3"
    # No per-pane id (Apple Terminal / plain xterm) → None → machine-global fallback.
    assert state.terminal_pane_key({}) is None
    assert state.terminal_pane_key({"TMUX_PANE": "  "}) is None
    # A source namespace prevents cross-terminal collision: tmux '%3' and kitty '3' differ.
    assert state.terminal_pane_key({"TMUX_PANE": "%3"}) != state.terminal_pane_key({"KITTY_WINDOW_ID": "3"})


def test_genuine_prompt_writes_per_pane_breadcrumb(tmp_path):
    """A genuine prompt with a pane id stamps BOTH the global breadcrumb AND this pane's own file."""
    home = tmp_path / "home"
    rc = _run_hook_env("a real question", home, {"TMUX_PANE": "%7"})
    assert rc == 0
    key = state.terminal_pane_key({"TMUX_PANE": "%7"})
    assert key is not None
    pane_path = state.per_pane_presence_path(key, home)
    assert pane_path.is_file(), "the per-pane breadcrumb must be written"
    data = json.loads(pane_path.read_text())
    assert data["last_user_input_epoch"] > 0
    # The machine-global one is still written too (cross-plugin consumers depend on it).
    assert _breadcrumb_path(home).is_file()


def test_heartbeat_marker_writes_no_per_pane_breadcrumb(tmp_path):
    """A [janitor-…] cron prompt is the machine talking to itself — it must not stamp presence
    in ANY form, per-pane included (else an active heartbeat marks its own pane present forever)."""
    home = tmp_path / "home"
    rc = _run_hook_env("[janitor-heartbeat]\n/path/to/stub.py", home, {"TMUX_PANE": "%7"})
    assert rc == 0
    key = state.terminal_pane_key({"TMUX_PANE": "%7"})
    assert key is not None
    assert not state.per_pane_presence_path(key, home).exists()
    assert not _breadcrumb_path(home).exists()


def test_no_pane_id_writes_global_only(tmp_path):
    """With no pane id (plain terminal) only the global breadcrumb is written — nothing to key on."""
    home = tmp_path / "home"
    import os

    env = dict(os.environ)
    for k in ("TMUX_PANE", "ITERM_SESSION_ID"):
        env.pop(k, None)
    env["HOME"] = str(home)
    env["CLAUDE_PLUGIN_ROOT"] = str(_PROJECT_ROOT)
    proc = subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps({"hook_event_name": "UserPromptSubmit", "prompt": "a real question"}),
        capture_output=True, text=True, env=env, timeout=30,
    )
    assert proc.returncode == 0
    assert _breadcrumb_path(home).is_file()
    panes_dir = home / ".aimaestro" / "state" / "user-presence-panes"
    assert not panes_dir.exists() or not any(panes_dir.iterdir()), "no per-pane file without a pane id"
