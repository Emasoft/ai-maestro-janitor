"""Regression guards for the idle auto-clear injection path (TRDD-5C42VCUX).

THE BUG THESE EXIST TO CATCH. `dispatch._phase_idle_clear_nudge` fired the auto-clear with
`terminal_trigger.send_self_command(respect_user_presence=True)`. On iTerm that call returns the
`USE_ITERM_PATH` SENTINEL — "caller, run your own osascript" — which every one of the five sibling
trigger scripts branches on and this caller did not. So its `sent.startswith("FIRED:")` test was
False on every single fire and the lever was structurally dead on the owner's own terminal.
Measured 2026-08-06: `send_self_command(...)` -> `'USE_ITERM_PATH'`.

Nothing failed, which is why it survived: the phase logged "not injected … will retry" and
returned cleanly, forever. A green suite plus a silent no-op is exactly the shape that needs a
guard rather than a fix alone.

The checks below are AST-based, not text greps: `respect_user_presence=True` also appears in this
codebase's own comments and in `send_verified`'s docstring (where it is the warning NOT to use
it), and a text grep cannot tell a warning from a call.
"""

import ast
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import external_clear as ec  # noqa: E402
import session_liveness as sl  # noqa: E402
import terminal_trigger as tt  # noqa: E402

SCRIPTS = _ROOT / "scripts"
ITERM_ENV = {"ITERM_SESSION_ID": "w0t1p0:ECEF0378-8D5D-4834-A8A9-371F0FDB3720",
             "TERM_PROGRAM": "iTerm.app"}
TMUX_ENV = {"TMUX_PANE": "%3"}


def _calls_named(path: Path, name: str) -> list[ast.Call]:
    """Every Call node in `path` whose callee is `<anything>.name` or bare `name`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (isinstance(func, ast.Attribute) and func.attr == name) or (
            isinstance(func, ast.Name) and func.id == name
        ):
            out.append(node)
    return out


def _py_files() -> list[Path]:
    return sorted(p for p in SCRIPTS.rglob("*.py") if p.is_file())


# --- the class-level guards --------------------------------------------------


def test_no_live_caller_passes_the_retired_presence_cancel():
    """`send_self_command(respect_user_presence=True)` is retired — `send_verified` says so itself.

    AST-based so the warning in `send_verified`'s own docstring, and the explanatory comment left
    at the fixed call site, are not mistaken for uses.
    """
    offenders = []
    for path in _py_files():
        for call in _calls_named(path, "send_self_command"):
            for kw in call.keywords:
                if kw.arg == "respect_user_presence" and getattr(kw.value, "value", None) is True:
                    offenders.append(f"{path.relative_to(_ROOT)}:{call.lineno}")
    assert not offenders, f"retired one-shot presence-cancel in use: {offenders}"


def test_the_idle_clear_phase_does_not_use_the_sentinel_returning_api_at_all():
    """dispatch.py must not call `send_self_command`: it has no osascript branch to pair with it.

    The five trigger SCRIPTS may keep calling it — each owns the `!= USE_ITERM_PATH` branch (the
    next test pins that). dispatch is a phase runner, not a trigger script, and adding a sixth
    copy of the osascript path there is what this fix deliberately avoided.
    """
    calls = _calls_named(SCRIPTS / "dispatch.py", "send_self_command")
    assert not calls, f"dispatch.py calls send_self_command at lines {[c.lineno for c in calls]}"


def test_every_remaining_caller_handles_the_iterm_sentinel():
    """A `send_self_command` caller that never mentions USE_ITERM_PATH is blind on iTerm."""
    blind = []
    for path in _py_files():
        if path.name == "terminal_trigger.py":  # the definer + its own CLI demo
            continue
        if not _calls_named(path, "send_self_command"):
            continue
        if "USE_ITERM_PATH" not in path.read_text(encoding="utf-8"):
            blind.append(str(path.relative_to(_ROOT)))
    assert not blind, f"callers with no iTerm branch: {blind}"


# --- the behavioural pin: the fix's premise, on the owner's terminal type ----


def test_iterm_env_resolves_to_a_channel_send_verified_can_actually_drive():
    """The composition the phase now uses must yield a TYPE-able, SUBMIT-able channel on iTerm.

    This is the positive half of the bug: it was never that iTerm is undrivable — the ratified
    injector handles it fine — only that the retired one-shot refused to. If this ever returns an
    unsupported channel, the auto-clear is silently dead again.
    """
    terminal = ec.terminal_from_record(sl.capture_terminal_identity(ITERM_ENV))
    assert terminal == {"kind": "iterm", "session_id": "ECEF0378-8D5D-4834-A8A9-371F0FDB3720"}
    assert tt.build_type_only_steps(terminal, "/janitor-handoff-and-clear") is not None
    assert tt.build_submit_steps(terminal) is not None
    assert tt.channel_is_readable(terminal) is True


def test_tmux_env_resolves_and_is_preferred_over_iterm():
    """tmux must keep winning when both are present — its pane is what can be read back cheaply."""
    terminal = ec.terminal_from_record(sl.capture_terminal_identity({**ITERM_ENV, **TMUX_ENV}))
    assert terminal == {"kind": "tmux", "pane": "%3"}
    assert tt.build_type_only_steps(terminal, "/x") is not None
    assert tt.build_submit_steps(terminal) is not None


def test_an_unautomatable_terminal_is_refused_rather_than_silently_dropped():
    """No pane at all must produce a channel `send_verified` REFUSES, with a reason.

    The failure mode being pinned: returning something falsy-but-shaped that a caller treats as
    "sent". `send_verified` returns (False, why) so the phase logs and retries next heartbeat.
    """
    terminal = ec.terminal_from_record(sl.capture_terminal_identity({"TERM_PROGRAM": "Apple_Terminal"}))
    assert terminal == {"kind": "unknown"}
    assert tt.build_type_only_steps(terminal, "/x") is None
    ok, why = tt.send_verified(terminal, "/janitor-handoff-and-clear")
    assert ok is False
    assert "cannot type-then-verify" in why


def test_send_self_command_still_returns_the_sentinel_on_iterm():
    """Documents the trap that caused the bug, so a future reader sees it is not hypothetical.

    If terminal_trigger ever stops degrading on iTerm this test fails LOUDLY — at which point the
    sibling trigger scripts' osascript branches become dead code worth deleting, which is a change
    someone should make deliberately rather than discover.
    """
    import os

    saved = {k: os.environ.get(k) for k in ("ITERM_SESSION_ID", "TERM_PROGRAM", "TMUX_PANE")}
    try:
        os.environ.update(ITERM_ENV)
        os.environ.pop("TMUX_PANE", None)
        assert tt.send_self_command(
            ["/janitor-handoff-and-clear"], dry_run=True, respect_user_presence=False
        ) == tt.USE_ITERM_PATH
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
