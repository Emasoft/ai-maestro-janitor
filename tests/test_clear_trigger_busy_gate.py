"""The /clear chain never types `/clear` into a pane whose MAIN turn is still running (#355, #356).

THE BUG. The chain typed `/clear` into a pane that was mid-turn (a /goal Stop-hook continuation,
a model call that kept running). The input field is EMPTY mid-turn, so the injector's "field is
empty" rule passed; Claude Code QUEUED the command and ran it at the next turn boundary — 19
minutes later in #355, after the chain had given up, so phase B (/janitor-arm, /goal) never ran.
The fix: wait while `pane_state.main_turn_busy` is True OR None, and on give-up do not type at all,
so no queued `/clear` can outlive the chain.

WHAT THESE TESTS DRIVE. The REAL `clear_trigger._run_chain_payload` -> `run_chained_inject` ->
`inject_until_sent`, typing through REAL `tmux send-keys` into a REAL tmux pane and reading it
back through REAL `tmux capture-pane`. The pane does NOT run Claude Code: it runs a tiny script
(`_PANE_SCRIPT`) that PRINTS A CAPTURED FRAME from `tests/fixtures/pane_frames/` with a live input
field, so the pane is a simulated TUI, not a live Claude Code. A true end-to-end still needs a live
session with `/goal` (owner-run). The tmux server is PRIVATE (own `-L` socket, reached through the
`TMUX` env var) so no keystroke can ever land in the developer's own tmux.

Only the machine-wide HID typing probe (`user_intent.typing_now`, which reads `ioreg`) is stubbed
to "nobody typing" — it reports the developer's real keyboard — and the injector's 8 s / 5 s
retry cadence is shortened so the tests run in seconds.
"""

from __future__ import annotations

import importlib.util as _u
import os
import shlex
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "clear_trigger.py"
_FRAMES = _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import terminal_trigger  # noqa: E402
import user_intent  # noqa: E402
from exe_path import exe  # noqa: E402

# The sandbox guard denies every spawn not on its allow-list; the REAL private-socket tmux is the point.
pytestmark = [
    pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed"),
    pytest.mark.real_subprocess("tmux"),
]

# A captured main-turn spinner row (`✽ Boogieing… (1m 13s · ↓ 779 tokens)`) above an empty input box.
_BUSY_FRAME = "real-calm-working.txt"
# A captured idle prompt: finished turn, empty input box.
_IDLE_FRAME = "synthetic-idle-empty-field.txt"

# The simulated TUI that runs inside the tmux pane: re-reads the frame file every cycle (so the test
# can swap busy <-> idle), draws it with the typed text in the `❯` input field, and appends a
# submitted line to the submitted-file on Enter. C-a / C-k / C-u (the injector's clear steps) kill the field.
_PANE_SCRIPT = '''\
import os, pathlib, select, sys, tty
frame_path, submitted_path = sys.argv[1], sys.argv[2]
sys.stdout.reconfigure(encoding="utf-8")
fd = sys.stdin.fileno()
tty.setcbreak(fd)
typed, drawn = "", None
while True:
    frame = pathlib.Path(frame_path).read_text(encoding="utf-8")
    if (frame, typed) != drawn:
        out = ["❯ " + typed if ln == "❯" else ln for ln in frame.split("\\n")]
        sys.stdout.write("\\x1b[H\\x1b[2J" + "\\n".join(out))
        sys.stdout.flush()
        drawn = (frame, typed)
    ready, _, _ = select.select([fd], [], [], 0.05)
    if not ready:
        continue
    for ch in os.read(fd, 1024).decode("utf-8", "replace"):
        if ch in "\\r\\n":
            if typed:
                with open(submitted_path, "a", encoding="utf-8") as fh:
                    fh.write(typed + "\\n")
            typed = ""
        elif ch in "\\x01\\x0b\\x15":
            typed = ""
        elif ch == "\\x7f":
            typed = typed[:-1]
        else:
            typed += ch
'''


def _import_clear_trigger():
    spec = _u.spec_from_file_location("clear_trigger_busy_gate_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Pane:
    """A private-socket tmux server with one pane running `_PANE_SCRIPT`."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.frame_file = tmp_path / "frame.txt"
        self.submitted_file = tmp_path / "submitted.txt"
        script = tmp_path / "pane_tui.py"
        script.write_text(_PANE_SCRIPT, encoding="utf-8")
        self.frame_file.write_text((_FRAMES / _BUSY_FRAME).read_text(encoding="utf-8"), encoding="utf-8")
        self._label = f"janitor-busy-gate-{os.getpid()}"
        cmd = shlex.join([sys.executable, str(script), str(self.frame_file), str(self.submitted_file)])
        self._tmux("new-session", "-d", "-s", "t", "-x", "100", "-y", "30", cmd)
        info = self._tmux("display-message", "-p", "-t", "t", "#{socket_path},#{pid},#{pane_id}").strip()
        socket_path, server_pid, self.pane_id = info.split(",")
        # Production's `tmux send-keys -t %N` has no -L: it finds its server through $TMUX.
        monkeypatch.setenv("TMUX", f"{socket_path},{server_pid},0")
        # Safety: never type unless the env really points at OUR server (a `%0` also exists in the
        # developer's own tmux).
        seen = subprocess.run(
            [exe("tmux"), "display-message", "-p", "-t", self.pane_id, "#{socket_path}"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        assert seen == socket_path, f"TMUX env does not select the private server: {seen!r} != {socket_path!r}"
        self.terminal = {"kind": "tmux", "pane": self.pane_id}
        self.wait_for("❯")

    def _tmux(self, *args: str) -> str:
        return subprocess.run(
            [exe("tmux"), "-u", "-L", self._label, "-f", "/dev/null", *args],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout

    def text(self) -> str:
        return self._tmux("capture-pane", "-p", "-t", "t")

    def wait_for(self, needle: str, timeout_s: float = 10.0) -> None:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if needle in self.text():
                return
            time.sleep(0.1)
        raise AssertionError(f"{needle!r} never appeared in the pane:\n{self.text()}")

    def show(self, frame_name: str) -> None:
        self.frame_file.write_text((_FRAMES / frame_name).read_text(encoding="utf-8"), encoding="utf-8")

    def submitted(self) -> list[str]:
        if not self.submitted_file.exists():
            return []
        return self.submitted_file.read_text(encoding="utf-8").splitlines()

    def close(self) -> None:
        subprocess.run([exe("tmux"), "-L", self._label, "kill-server"], check=False, timeout=10, capture_output=True)


@pytest.fixture
def pane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    p = _Pane(tmp_path, monkeypatch)
    # Fast cadence for the injector (production: 8 s quiet window, 5 s retry) and no HID probe.
    kwdefaults = terminal_trigger.inject_until_sent.__kwdefaults__
    assert kwdefaults is not None
    monkeypatch.setitem(kwdefaults, "quiet_s", 0.5)
    monkeypatch.setitem(kwdefaults, "retry_s", 0.5)
    monkeypatch.setattr(user_intent, "typing_now", lambda *a, **kw: False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("JANITOR_TRANSCRIPT_PATH", raising=False)
    yield p
    p.close()


def _payload(tmp_path: Path, terminal: dict) -> str:
    import base64
    import json

    payload = {
        "delay": 0.0,
        "terminal": terminal,
        "first": "/clear",
        "then": [],
        "state_dir": str(tmp_path / ".janitor" / "state"),
        "gate_baseline": 0,
        "directive": "resume",
    }
    return base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")


def _run_chain(
    mod, pane: _Pane, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, while_running=None, limit_s: float = 60.0
) -> tuple[int, list[str]]:
    """Run `_run_chain_payload` in a thread; whenever the pane has submitted a line, stamp
    `clear-observed.ts` the way the fresh session's SessionStart hook would, so a chain that DID
    type finishes at once instead of waiting out its 180 s landing gate. Returns (rc, log lines)."""
    logs: list[str] = []
    monkeypatch.setattr(mod.state, "log_line", lambda name, msg: logs.append(f"[{name}] {msg}"))
    result: dict[str, int] = {}
    t = threading.Thread(target=lambda: result.update(rc=mod._run_chain_payload(_payload(tmp_path, pane.terminal))))
    stamp = tmp_path / ".janitor" / "state" / "clear-observed.ts"
    t.start()
    t0 = time.monotonic()
    stamped = False
    while t.is_alive() and time.monotonic() - t0 < limit_s:
        if while_running is not None:
            while_running(time.monotonic() - t0)
        if pane.submitted() and not stamped:
            stamp.parent.mkdir(parents=True, exist_ok=True)
            stamp.write_text(str(int(time.time()) + 5), encoding="utf-8")
            stamped = True
        time.sleep(0.1)
    t.join(timeout=5)
    assert not t.is_alive(), "chain did not finish"
    return result["rc"], logs


def test_busy_pane_never_gets_a_clear_typed_within_the_giveup(pane: _Pane, tmp_path: Path, monkeypatch) -> None:
    """A real tmux pane printing a captured BUSY frame (not a live Claude Code): no `/clear` is typed before the chain gives up."""
    mod = _import_clear_trigger()
    monkeypatch.setattr(mod, "_CLEAR_CHAIN_GIVEUP_S", 4.0)
    seen_in_pane: list[str] = []

    rc, logs = _run_chain(mod, pane, tmp_path, monkeypatch, while_running=lambda _t: seen_in_pane.append(pane.text()))

    assert rc == 1
    assert pane.submitted() == [], "a /clear was typed and submitted into a busy pane"
    assert not any("/clear" in shot for shot in seen_in_pane), "/clear was typed into the busy pane"
    assert any("never went idle" in line for line in logs), logs
    # Nothing was persisted for a clear that never happened (issue #105 shape).
    assert not (tmp_path / ".janitor" / "state" / "resume-after-clear.flag").exists()


def test_idle_pane_gets_the_clear_typed_and_submitted(pane: _Pane, tmp_path: Path, monkeypatch) -> None:
    """A real tmux pane printing a captured IDLE frame (not a live Claude Code): `/clear` is typed and submitted."""
    pane.show(_IDLE_FRAME)
    mod = _import_clear_trigger()

    rc, logs = _run_chain(mod, pane, tmp_path, monkeypatch)

    assert rc == 0, logs
    assert pane.submitted() == ["/clear"]


def test_clear_waits_for_the_turn_to_end_then_types(pane: _Pane, tmp_path: Path, monkeypatch) -> None:
    """A real tmux pane that starts BUSY and flips to the captured IDLE frame mid-chain: `/clear` is held back, then typed only after the flip."""
    mod = _import_clear_trigger()
    monkeypatch.setattr(mod, "_CLEAR_CHAIN_GIVEUP_S", 60.0)
    flipped_at: list[float] = []
    typed_before_flip: list[bool] = []

    def _flip(elapsed: float) -> None:
        if flipped_at:
            return
        typed_before_flip.append(bool(pane.submitted()))
        if elapsed > 3.0:
            pane.show(_IDLE_FRAME)
            flipped_at.append(elapsed)

    rc, logs = _run_chain(mod, pane, tmp_path, monkeypatch, while_running=_flip)

    assert rc == 0, logs
    assert flipped_at, "the frame never flipped"
    assert not any(typed_before_flip), "/clear was typed while the pane still showed the busy frame"
    assert pane.submitted() == ["/clear"]
