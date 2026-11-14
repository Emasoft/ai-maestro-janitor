"""A long `/goal <text>` is typed in small pieces so Claude Code never collapses it (issue #343).

THE BUG. Claude Code 2.1.325 collapses any SINGLE input chunk longer than 800 chars into a
`[Pasted text #N]` placeholder. The injector typed the whole command in one write, so a 1036-char
`/goal ...` was collapsed, could never run as a command, and stranded in the input box, blocking
every later /clear chain for 19 h.

WHAT THESE TESTS DRIVE. The REAL `terminal_trigger.inject_until_sent` with the REAL step builders
(`_step_runners`), typing through REAL `tmux send-keys` into a REAL tmux pane on a PRIVATE socket
(own `-L` label, reached through the `TMUX` env var) and reading it back through REAL
`tmux capture-pane`. The pane does NOT run Claude Code: it runs a tiny script that mimics the one
behaviour under test, rendering any single `os.read` chunk over 800 bytes as `[Pasted text #N]`
and echoing smaller chunks verbatim. Whether Claude Code's real input box deletes a placeholder
chip on C-u is UNMEASURED, so the pane models the worst case (the chip survives the first clear
pass). A true end-to-end still needs a live session (owner-run).
"""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_FRAMES = _PROJECT_ROOT / "tests" / "fixtures" / "pane_frames"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import terminal_trigger as tt  # noqa: E402

_IDLE_FRAME = "synthetic-idle-empty-field.txt"
_THRESHOLD = 800  # Claude Code 2.1.325's single-chunk paste threshold (R8)

# argv: frame, submitted-file, reads-file, first placeholder number, C-u presses a chip survives.
_PANE_SCRIPT = '''\
import os, pathlib, select, sys, tty
frame_path, submitted_path, reads_path = sys.argv[1], sys.argv[2], sys.argv[3]
pastes, chip_clears_needed = int(sys.argv[4]) - 1, int(sys.argv[5])
chip_hits = 0
sys.stdout.reconfigure(encoding="utf-8")
fd = sys.stdin.fileno()
tty.setcbreak(fd)
typed, drawn = "", None
while True:
    frame = pathlib.Path(frame_path).read_text(encoding="utf-8")
    if (frame, typed) != drawn:
        out = ["\\u276f\\u00a0" + typed if ln == "\\u276f" else ln for ln in frame.split("\\n")]
        sys.stdout.write("\\x1b[H\\x1b[2J" + "\\n".join(out))
        sys.stdout.flush()
        drawn = (frame, typed)
    ready, _, _ = select.select([fd], [], [], 0.05)
    if not ready:
        continue
    data = os.read(fd, 8192).decode("utf-8", "replace")
    with open(reads_path, "a", encoding="utf-8") as fh:
        fh.write(str(len(data)) + "\\n")
    if len(data) > 800:
        pastes += 1
        typed += "[Pasted text #%d]" % pastes
        continue
    for ch in data:
        if ch in "\\r\\n":
            if typed:
                with open(submitted_path, "a", encoding="utf-8") as fh:
                    fh.write(typed + "\\n")
            typed, chip_hits = "", 0
        elif ch in "\\x01\\x0b\\x15":
            if typed.startswith("[Pasted text #"):
                if ch == "\\x15":
                    chip_hits += 1
                    if chip_hits >= chip_clears_needed:
                        typed, chip_hits = "", 0
            else:
                typed = ""
        elif ch == "\\x7f":
            typed = typed[:-1]
        else:
            typed += ch
'''

pytestmark = [
    pytest.mark.skipif(shutil.which("tmux") is None, reason="tmux not installed"),
    pytest.mark.real_subprocess("tmux"),
]

# 1036 chars, like the goal that failed on 2026-11-13; single spaces only so the read-back
# (which collapses space runs) compares it exactly.
_GOAL = ("/goal " + " ".join(f"step{i:03d}" for i in range(200)))[:1036].rstrip()


class _Pane:
    """A private-socket tmux server with one pane running `_PANE_SCRIPT`."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, chip_clears_needed: int = 1) -> None:
        self.frame_file = tmp_path / "frame.txt"
        self.submitted_file = tmp_path / "submitted.txt"
        self.reads_file = tmp_path / "reads.txt"
        script = tmp_path / "pane_tui.py"
        script.write_text(_PANE_SCRIPT, encoding="utf-8")
        self.frame_file.write_text((_FRAMES / _IDLE_FRAME).read_text(encoding="utf-8"), encoding="utf-8")
        self._label = f"janitor-paste-chunk-{os.getpid()}-{time.monotonic_ns()}"
        cmd = shlex.join([
            sys.executable, str(script), str(self.frame_file), str(self.submitted_file),
            str(self.reads_file), "3", str(chip_clears_needed),
        ])
        # Wide enough that the 1036-char command never wraps: capture-pane trims trailing spaces
        # at a wrap point, which would make the joined read-back differ from the command.
        self._tmux("new-session", "-d", "-s", "t", "-x", "1500", "-y", "30", cmd)
        info = self._tmux("display-message", "-p", "-t", "t", "#{socket_path},#{pid},#{pane_id}").strip()
        socket_path, server_pid, self.pane_id = info.split(",")
        # Production's `tmux send-keys -t %N` has no -L: it finds its server through $TMUX.
        monkeypatch.setenv("TMUX", f"{socket_path},{server_pid},0")
        seen = subprocess.run(
            ["tmux", "display-message", "-p", "-t", self.pane_id, "#{socket_path}"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
        assert seen == socket_path, f"TMUX env does not select the private server: {seen!r} != {socket_path!r}"
        self.terminal = {"kind": "tmux", "pane": self.pane_id}
        self.wait_for("❯")

    def _tmux(self, *args: str) -> str:
        return subprocess.run(
            ["tmux", "-u", "-L", self._label, "-f", "/dev/null", *args],
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

    def submitted(self) -> list[str]:
        if not self.submitted_file.exists():
            return []
        return self.submitted_file.read_text(encoding="utf-8").splitlines()

    def read_sizes(self) -> list[int]:
        if not self.reads_file.exists():
            return []
        return [int(n) for n in self.reads_file.read_text(encoding="utf-8").split()]

    def close(self) -> None:
        subprocess.run(["tmux", "-L", self._label, "kill-server"], check=False, timeout=10, capture_output=True)


def _make_pane(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, chip_clears_needed: int = 1) -> _Pane:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.delenv("JANITOR_TRANSCRIPT_PATH", raising=False)
    return _Pane(tmp_path, monkeypatch, chip_clears_needed=chip_clears_needed)


def _inject(pane: _Pane, tmp_path: Path, command: str, *, type_fn_override=None) -> tuple[bool, str]:
    """Run the real `inject_until_sent` with the production step builders against `pane`."""
    runner, submit, clear = tt._step_runners(pane.terminal)
    return tt.inject_until_sent(
        pane.terminal,
        command,
        type_fn=type_fn_override or runner(command),
        submit_fn=submit,
        clear_fn=clear,
        state_dir=tmp_path / ".janitor" / "state",
        quiet_s=0.5,
        retry_s=0.5,
        giveup_s=60.0,
        is_typing=lambda _t: False,  # the HID probe reports the developer's real keyboard
    )


def test_long_goal_is_typed_in_small_pieces_and_arrives_verbatim(tmp_path: Path, monkeypatch) -> None:
    """A 1036-char `/goal ...` typed through the real step path arrives verbatim and is submitted; no read tops 250 chars."""
    assert len(_GOAL) > _THRESHOLD
    pane = _make_pane(tmp_path, monkeypatch)
    try:
        sent, why = _inject(pane, tmp_path, _GOAL)
        assert sent, why
        assert pane.submitted() == [_GOAL]
        sizes = pane.read_sizes()
        assert len(sizes) >= 5, sizes  # 1036 chars = 5 pieces of at most 250
        assert max(sizes) <= tt._TYPE_CHUNK_CHARS, sizes
    finally:
        pane.close()


def test_stranded_paste_placeholder_is_cleared_before_the_next_typing(tmp_path: Path, monkeypatch) -> None:
    """A collapsed `[Pasted text #3]` left by an over-threshold write (surviving the first clear pass) is cleared, then the command is typed and submitted."""
    # The chip survives ONE clear pass: pre-fix, the tidy stopped after pass 1 (the field is not a
    # suffix of our command), the field stayed non-empty, and rule 1 deferred until the give-up.
    pane = _make_pane(tmp_path, monkeypatch, chip_clears_needed=2)
    try:
        calls: list[str] = []
        runner, _submit, _clear = tt._step_runners(pane.terminal)
        chunked = runner(_GOAL)

        def type_fn() -> None:
            if not calls:
                # The OLD behaviour, to strand the placeholder for real: the whole command in ONE write.
                subprocess.run(
                    ["tmux", "send-keys", "-t", pane.pane_id, "-l", _GOAL],
                    check=True, timeout=10, capture_output=True,
                )
                time.sleep(1.0)
                calls.append(pane.text())
            else:
                calls.append("chunked")
                chunked()

        sent, why = _inject(pane, tmp_path, _GOAL, type_fn_override=type_fn)

        assert "[Pasted text #3]" in calls[0], "the pane did not strand a placeholder; the test proves nothing"
        assert sent, why
        assert calls[1:] == ["chunked"]
        assert pane.submitted() == [_GOAL], "the placeholder was submitted or the command never arrived"
    finally:
        pane.close()


def test_short_command_is_one_write_step() -> None:
    """A command of 250 chars or fewer stays a single write step; a longer one splits into pieces with a pause between."""
    tmux = {"kind": "tmux", "pane": "%1"}
    assert tt.build_type_only_steps(tmux, "/clear") == [["RUN", "tmux", "send-keys", "-t", "%1", "-l", "/clear"]]
    at_limit = "/" + "a" * (tt._TYPE_CHUNK_CHARS - 1)
    assert len(tt.build_type_only_steps(tmux, at_limit) or []) == 1

    over = "/" + "b" * tt._TYPE_CHUNK_CHARS  # 251 chars
    steps = tt.build_type_only_steps(tmux, over)
    assert steps is not None
    assert [s[0] for s in steps] == ["RUN", "SLEEP", "RUN"]
    assert float(steps[1][1]) >= 0.3
    assert "".join(s[-1] for s in steps if s[0] == "RUN") == over
    assert all(len(s[-1]) <= tt._TYPE_CHUNK_CHARS for s in steps if s[0] == "RUN")

    iterm = {"kind": "iterm", "session_id": "ECEF0378-1111-2222-3333-444455556666"}
    assert len(tt.build_type_only_steps(iterm, "/clear") or []) == 1
    iterm_steps = tt.build_type_only_steps(iterm, _GOAL)
    assert iterm_steps is not None
    assert [s[0] for s in iterm_steps] == ["RUN", "SLEEP"] * 4 + ["RUN"]
    assert all("without newline" in s[3] for s in iterm_steps if s[0] == "RUN")
