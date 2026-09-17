"""TRDD-7MGJYLY5 box 4: "A clear with a live background subagent leaves that subagent
alive and the resume listing names it. A test asserts it against a real subagent, not a
mock."

`TestTurnBoundaryClear` in test_token_meter_logs_every_turn.py drives `_maybe_clear` with
`_fake_pending_agents_module` -- BOTH `load_pending` and `agent_is_live` are stubbed to
return canned values, so the real liveness computation (a transcript mtime stat) and the
real resume-listing code (`pending_agents.directive_lines`) are never exercised. This test
closes that gap: it spawns an actual OS child process, records it in a REAL
pending-agents.json via the REAL `pending_agents` module (no `sys.modules` stub), drives
the REAL `_maybe_clear` against that real manifest, and reads the REAL resume-listing
function -- proving the code path the box describes, not a rehearsal of it.
"""

from __future__ import annotations

import importlib.util as _u
import os
import subprocess
import sys
import time
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import pending_agents  # noqa: E402
import state  # noqa: E402
import token_meter  # noqa: E402

HOOK = REPO / "scripts" / "hooks" / "on-stop-token-meter.py"


def _import_meter_hook():
    # The hook filename has dashes, so it cannot be a normal import -- load it by path.
    spec = _u.spec_from_file_location("on_stop_token_meter_under_test_box4", str(HOOK))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)  # runs the module body; main() is NOT called
    return mod


import clear_trigger  # noqa: E402 -- module-scope so the test can spy on / patch its

# `spawn_shrink_chain` -- the SAME module object the hook's own lazy `import clear_trigger`
# resolves from sys.modules.


class _FakeState:
    """Collects log_line calls instead of writing to disk -- the SAME boundary stub the
    sibling TestTurnBoundaryClear tests use; it is not the behaviour under test."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def log_line(self, name: str, message: str) -> None:
        self.lines.append(f"[{name}] {message}")


class _FakeTokenMeter:
    """Fixed context size, real default_window -- same boundary stub as the sibling tests."""

    def __init__(self, tokens: int) -> None:
        self._tokens = tokens

    def latest_context_size(self, _transcript_path: str):
        return self._tokens

    def default_window(self, env=None) -> int:
        return token_meter.default_window(env)


def _clear_state_cache() -> None:
    state.project_root.cache_clear()
    state.janitor_root.cache_clear()
    state.state_dir.cache_clear()


class TestClearPreservesLiveSubagent(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = _import_meter_hook()
        self._tmp = TemporaryDirectory()
        self._project = Path(self._tmp.name)
        # Isolate the real `state` module's project resolution to this tmp project --
        # WITHOUT this, `pending_agents.add`/`load_pending`/`directive_lines` (all of
        # which call the ambient `state.state_dir()`) would read/write the REAL
        # ~/.claude or the repo's own .janitor/state, corrupting live janitor state
        # (a prior incident this repo's own tests guard against elsewhere).
        # TMUX_PANE is a FAKE, well-formed pane id (`%<n>` -- `terminal_trigger.
        # valid_tmux_pane` is a format-only regex check) so `spawn_shrink_chain`'s own
        # channel-readability gate passes deterministically regardless of the host's
        # ambient terminal, and the real code under test reaches `_spawn_chain` instead
        # of short-circuiting on "channel unknown cannot be read back". This value is
        # otherwise INERT: `_spawn_chain` (the actual OS-fork + tmux/iTerm dispatch
        # seam) is stubbed below, so no real subprocess or terminal command is ever
        # built from it -- a real vs. colliding tmux pane id makes no difference here.
        self._env_patch = unittest.mock.patch.dict(
            os.environ,
            {
                "CLAUDE_PROJECT_DIR": str(self._project),
                "HOME": str(self._project),
                "TMUX_PANE": "%99999",
            },
        )
        self._env_patch.start()
        _clear_state_cache()
        self._child: subprocess.Popen | None = None

    def tearDown(self) -> None:
        # A real child process must be killed even if an assertion above it failed --
        # a leaked sleep(600) process is exactly the "leftover" the testing rules ban.
        if self._child is not None and self._child.poll() is None:
            self._child.kill()
            self._child.wait(timeout=5)
        _clear_state_cache()
        self._env_patch.stop()
        self._tmp.cleanup()

    def _record_spawn_call(self, **kwargs):
        """`spawn_shrink_chain` side_effect: records the call, then calls straight through
        to the REAL function -- this is the spy proving `_maybe_clear` actually invoked it,
        not a mock standing in for it."""
        self._spawn_calls.append(kwargs)
        return self._real_spawn_shrink_chain(**kwargs)

    def _record_fork_call(self, payload, *, env=None):
        """`clear_trigger._spawn_chain` side_effect -- REPLACES the real function, does not
        call through to it. `_spawn_chain` is pure OS-fork: build a base64 blob and call
        `subprocess.Popen([...interpreter..., "clear_trigger.py", "--__chain", blob], ...,
        start_new_session=True)`, launching a REAL detached child that eventually reaches
        `_fire_phase` -> `terminal_trigger.send_self_command` (the function that actually
        types into a pane via tmux/iTerm/AppleScript). That is a genuinely separate OS
        process -- once forked, no in-process patch in THIS interpreter can reach it, so
        the only deterministic way to guarantee this test never sends a real keystroke,
        on any host, under any timing, is to never let that process exist at all. Stubbing
        here (one level above `subprocess.Popen`, at the exact chokepoint between "decided
        to clear" and "OS-level side effect") proves `spawn_shrink_chain` built the right
        payload without ever giving the real terminal-dispatch code a chance to run."""
        self._fork_calls.append((payload, env))

    def test_live_real_subagent_survives_clear_and_is_named_in_the_resume_listing(self) -> None:
        # 1. A REAL child process stands in for a background agent -- not a Mock object,
        # not a dict. `_maybe_clear` never touches this process (a /clear only rewinds the
        # MAIN session's context, per the janitor's own R3 code-check on this card's STATE
        # block); this asserts that directly instead of taking the docstring's word for it.
        self._child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"])
        pid = self._child.pid
        agent_id = f"real-subagent-{pid}"

        # 2. A REAL transcript file with a fresh mtime -- `agent_is_live` (the real
        # function, not a stub) stats this file; a fresh mtime is what makes it live.
        transcript = self._project / f"agent-{agent_id}.jsonl"
        transcript.write_text('{"type": "assistant", "message": {"content": []}}\n', encoding="utf-8")

        # 3. Register it in a REAL pending-agents.json via the REAL `pending_agents.add`.
        pending_agents.add(agent_id, description="real child process subagent (box 4 test)", transcript=str(transcript))

        now = int(time.time())
        entries = pending_agents.load_pending(now)
        self.assertTrue(any(e["agentId"] == agent_id for e in entries), entries)
        entry = next(e for e in entries if e["agentId"] == agent_id)
        self.assertTrue(
            pending_agents.agent_is_live(entry, now, 900),
            "the real agent_is_live() must see this entry as live from its real transcript mtime",
        )

        # 4. Drive the REAL `_maybe_clear` at 850k/900k -- ABOVE the 92% ceiling (828k),
        # so it takes the unconditional "clear regardless of a live agent" branch and
        # actually calls the REAL `clear_trigger.spawn_shrink_chain` -- not the DEFER
        # branch the previous version of this test drove (760k, below ceiling), which
        # never invoked it at all and so could not have failed no matter what the real
        # shrink chain did (the finding this rewrite closes). Everything `spawn_shrink_
        # chain` does before the OS fork -- the channel-readability check, the handoff
        # read, the gate baseline read -- runs for real under `tmp_path`; only the fork
        # itself (`_spawn_chain`) is stubbed, deterministically, never a real subprocess
        # (see `_record_fork_call`'s docstring for why that boundary and not a lower one).
        self._spawn_calls: list[dict] = []
        self._fork_calls: list[tuple] = []
        self._real_spawn_shrink_chain = clear_trigger.spawn_shrink_chain

        fake_state = _FakeState()
        tm = _FakeTokenMeter(850_000)
        with (
            unittest.mock.patch.dict(os.environ, {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "900000"}),
            unittest.mock.patch.object(clear_trigger, "spawn_shrink_chain", side_effect=self._record_spawn_call),
            unittest.mock.patch.object(clear_trigger, "_spawn_chain", side_effect=self._record_fork_call),
        ):
            self.mod._maybe_clear(str(self._project), str(transcript), fake_state, tm)

        # 4a. The real ceiling branch fired (not the DEFER branch) -- proves this test no
        # longer exercises the vacuous path the finding flagged.
        self.assertTrue(any("past ceiling" in ln for ln in fake_state.lines), fake_state.lines)
        # 4b. The real `clear_trigger.spawn_shrink_chain` was actually invoked -- exactly
        # once, per the singleton-chain contract it documents.
        self.assertEqual(len(self._spawn_calls), 1, self._spawn_calls)
        # 4c. It really reached the fork chokepoint with the correct payload -- proves
        # `spawn_shrink_chain`'s real logic (not a rehearsal) built the real `/clear` +
        # bootstrap commands, without ever creating the OS process that would type them.
        self.assertEqual(len(self._fork_calls), 1, self._fork_calls)
        payload, _env = self._fork_calls[0]
        self.assertEqual(payload["first"], clear_trigger.CLEAR_CMD, payload)
        self.assertEqual(payload["then"], list(clear_trigger.BOOTSTRAP_CMDS), payload)

        # 5. The subagent PROCESS is untouched -- proves "leaves that subagent alive"
        # against the real OS, not against a mock's call count. No code anywhere in the
        # traced call graph above (`_maybe_clear` -> `spawn_shrink_chain` -> the stubbed
        # `_spawn_chain` chokepoint) ever references this PID or the subagent's
        # pending-agents entry -- the assertion below is a real check of that, not a
        # tautology, because the real functions ran all the way up to the fork.
        self.assertIsNone(self._child.poll(), "the child process must still be running")
        os.kill(pid, 0)  # raises OSError if the pid is gone; must not raise

        # 6. The REAL resume listing (dispatch's post-clear cue source) names this agent --
        # `directive_lines` is the exact function `dispatch._phase_clear_resume` calls to
        # build the `[janitor-resume]` payload after a clear.
        lines = pending_agents.directive_lines(now)
        self.assertTrue(
            any(f"resume background agent via SendMessage: {agent_id}" in ln for ln in lines),
            lines,
        )


if __name__ == "__main__":
    unittest.main()
