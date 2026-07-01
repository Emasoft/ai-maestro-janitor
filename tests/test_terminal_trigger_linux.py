"""Tests for the Linux GUI-terminal channel of the self-trigger abstraction (TRDD-ME8V2YJF).

A Linux janitor session running directly in a GUI terminal (gnome-terminal / konsole /
xterm) with NO tmux is reached by typing into the FOCUSED window via `wtype` (Wayland) or
`xdotool` (X11). These tests prove: the pure argv builders mirror `build_tmux_steps`; the
channel selector picks the right tool from the session's display env and the tool's real
presence on PATH; it fails OPEN (→ None → USE_ITERM_PATH) when the tool is absent; and it is
Linux-ONLY, so a macOS/iTerm host is never diverted even with `$DISPLAY` + `xdotool` present.

No module is mocked: the tool-presence gate is exercised with REAL throwaway executables on a
patched PATH, and the OS gate with a patched `sys.platform` (simulating the host OS). Dry-run
is used for the dispatch tests so no keystrokes ever fire.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import terminal_trigger as tt  # noqa: E402


def _fake_tool(dir_path: Path, name: str) -> None:
    """Create a REAL executable `name` in `dir_path` so `shutil.which` resolves it."""
    p = dir_path / name
    p.write_text("#!/usr/bin/env bash\nexit 0\n")
    p.chmod(0o755)


def _linux_env(**extra: str) -> dict[str, str]:
    """A minimal env with no ai-maestro signals (so dispatch takes the terminal path)."""
    return {"HOME": os.path.expanduser("~"), **extra}


# --- build_wtype_steps (pure) ----------------------------------------------

def test_build_wtype_steps_sequence():
    """Hard default (esc_first=True): a leading Escape keypress then the single command
    typed + Return, mirroring build_tmux_steps."""
    assert tt.build_wtype_steps("/compact") == [
        ["RUN", "wtype", "-k", "Escape"],
        ["SLEEP", "0.6"],
        ["RUN", "wtype", "/compact"],
        ["RUN", "wtype", "-k", "Return"],
    ]


def test_build_wtype_steps_soft_omits_escape():
    """esc_first=False (soft): no leading Escape — the command is typed to be enqueued."""
    assert tt.build_wtype_steps("/compact", esc_first=False) == [
        ["RUN", "wtype", "/compact"],
        ["RUN", "wtype", "-k", "Return"],
    ]


def test_build_wtype_steps_multi_command_back_to_back():
    """Multiple commands are typed back-to-back with a settle SLEEP between them."""
    assert tt.build_wtype_steps(["/janitor-write-handoff", "/compact"], esc_first=False) == [
        ["RUN", "wtype", "/janitor-write-handoff"],
        ["RUN", "wtype", "-k", "Return"],
        ["SLEEP", "0.4"],
        ["RUN", "wtype", "/compact"],
        ["RUN", "wtype", "-k", "Return"],
    ]


def test_build_wtype_steps_bare_string_not_per_character():
    """A bare string is one command, NOT one keystroke per character (the str-is-a-Sequence
    trap) — so it equals passing a one-element list."""
    assert tt.build_wtype_steps("/compact", esc_first=False) == tt.build_wtype_steps(
        ["/compact"], esc_first=False
    )
    # and the command survives as a single argv element
    assert ["RUN", "wtype", "/compact"] in tt.build_wtype_steps("/compact")


# --- build_xdotool_steps (pure) --------------------------------------------

def test_build_xdotool_steps_sequence():
    """Hard default: `key Escape`, then `type --clearmodifiers -- <cmd>`, then `key Return`."""
    assert tt.build_xdotool_steps("/compact") == [
        ["RUN", "xdotool", "key", "Escape"],
        ["SLEEP", "0.6"],
        ["RUN", "xdotool", "type", "--clearmodifiers", "--", "/compact"],
        ["RUN", "xdotool", "key", "Return"],
    ]


def test_build_xdotool_steps_soft_omits_escape():
    """esc_first=False (soft): no leading Escape keypress."""
    assert tt.build_xdotool_steps("/compact", esc_first=False) == [
        ["RUN", "xdotool", "type", "--clearmodifiers", "--", "/compact"],
        ["RUN", "xdotool", "key", "Return"],
    ]


# --- _resolve_linux_gui_channel (env + real tool presence) -----------------

def test_resolve_prefers_wtype_on_wayland(tmp_path, monkeypatch):
    """Wayland ($WAYLAND_DISPLAY) with wtype on PATH → 'wtype' (preferred over xdotool
    because xdotool via XWayland can't inject into native Wayland windows)."""
    _fake_tool(tmp_path, "wtype")
    _fake_tool(tmp_path, "xdotool")
    monkeypatch.setattr(tt.sys, "platform", "linux")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    assert tt._resolve_linux_gui_channel(_linux_env(WAYLAND_DISPLAY="wayland-0", DISPLAY=":0")) == "wtype"


def test_resolve_xdotool_on_x11(tmp_path, monkeypatch):
    """X11 ($DISPLAY, no $WAYLAND_DISPLAY) with xdotool on PATH → 'xdotool'."""
    _fake_tool(tmp_path, "xdotool")
    monkeypatch.setattr(tt.sys, "platform", "linux")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    assert tt._resolve_linux_gui_channel(_linux_env(DISPLAY=":0")) == "xdotool"


def test_resolve_none_without_display(tmp_path, monkeypatch):
    """No graphical display env → None (headless session, nothing to type into)."""
    _fake_tool(tmp_path, "wtype")
    _fake_tool(tmp_path, "xdotool")
    monkeypatch.setattr(tt.sys, "platform", "linux")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    assert tt._resolve_linux_gui_channel(_linux_env()) is None


def test_resolve_fail_open_when_tool_absent(tmp_path, monkeypatch):
    """Display set but the tool is NOT on PATH → None (fail open → USE_ITERM_PATH)."""
    monkeypatch.setattr(tt.sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(tmp_path))  # empty of wtype/xdotool
    assert tt._resolve_linux_gui_channel(_linux_env(WAYLAND_DISPLAY="wayland-0")) is None
    assert tt._resolve_linux_gui_channel(_linux_env(DISPLAY=":0")) is None


def test_resolve_none_off_linux(tmp_path, monkeypatch):
    """OFF Linux (e.g. macOS) → None even with $DISPLAY + xdotool present (XQuartz guard):
    a macOS host must never be diverted off the iTerm path."""
    _fake_tool(tmp_path, "xdotool")
    monkeypatch.setattr(tt.sys, "platform", "darwin")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    assert tt._resolve_linux_gui_channel(_linux_env(DISPLAY=":0")) is None


# --- _try_linux_gui_send (dry-run — nothing fires) -------------------------

def test_try_linux_gui_send_dry_run(tmp_path, monkeypatch):
    """dry_run returns a DRY_RUN status naming the channel, the focused-window target, the
    ESC prefix (hard), and the delay — no child is spawned."""
    _fake_tool(tmp_path, "wtype")
    monkeypatch.setattr(tt.sys, "platform", "linux")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    out = tt._try_linux_gui_send(
        ["/compact"], delay_s=2.0, esc_first=True, dry_run=True,
        env=_linux_env(WAYLAND_DISPLAY="wayland-0"),
    )
    assert out == "DRY_RUN:wtype:focused:ESC+/compact@2.0s"


def test_try_linux_gui_send_none_when_channel_unavailable(tmp_path, monkeypatch):
    """No resolvable channel → None so the caller falls through to USE_ITERM_PATH."""
    monkeypatch.setattr(tt.sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(tmp_path))
    assert tt._try_linux_gui_send(
        ["/compact"], delay_s=2.0, esc_first=True, dry_run=True,
        env=_linux_env(WAYLAND_DISPLAY="wayland-0"),
    ) is None


# --- send_self_command integration (dispatch) ------------------------------

def _force_kind(monkeypatch, kind: str) -> None:
    monkeypatch.setenv("JANITOR_FORCE_TERMINAL_KIND", kind)
    for var in ("AIMAESTRO_AGENT", "THIS_IS_AIMAESTRO", "AMP_AGENT_ID", "AID_AUTH"):
        monkeypatch.delenv(var, raising=False)


def test_send_self_command_uses_linux_channel(tmp_path, monkeypatch):
    """On Linux, a non-tmux GUI terminal with wtype present routes through the Linux channel
    (proven via dry-run) instead of degrading to USE_ITERM_PATH."""
    _fake_tool(tmp_path, "wtype")
    _force_kind(monkeypatch, "gnome-terminal")
    monkeypatch.setattr(tt.sys, "platform", "linux")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    out = tt.send_self_command(
        "/compact", delay_s=2.0, dry_run=True, env=_linux_env(WAYLAND_DISPLAY="wayland-0")
    )
    assert out == "DRY_RUN:wtype:focused:ESC+/compact@2.0s"


def test_send_self_command_degrades_when_no_linux_tool(tmp_path, monkeypatch):
    """On Linux with NO wtype/xdotool the non-tmux branch still degrades to USE_ITERM_PATH —
    the unchanged behaviour (fail open)."""
    _force_kind(monkeypatch, "gnome-terminal")
    monkeypatch.setattr(tt.sys, "platform", "linux")
    monkeypatch.setenv("PATH", str(tmp_path))  # no wtype/xdotool
    out = tt.send_self_command(
        "/compact", delay_s=2.0, dry_run=True, env=_linux_env(WAYLAND_DISPLAY="wayland-0")
    )
    assert out == tt.USE_ITERM_PATH


def test_send_self_command_macos_never_diverted(tmp_path, monkeypatch):
    """Regression guard: a macOS host (non-tmux) returns USE_ITERM_PATH even with $DISPLAY +
    xdotool present — the Linux channel is never attempted off Linux."""
    _fake_tool(tmp_path, "xdotool")
    _force_kind(monkeypatch, "iterm")
    monkeypatch.setattr(tt.sys, "platform", "darwin")
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    out = tt.send_self_command(
        "/compact", delay_s=2.0, dry_run=True, env=_linux_env(DISPLAY=":0")
    )
    assert out == tt.USE_ITERM_PATH
