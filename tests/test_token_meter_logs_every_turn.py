"""The token meter must log EVERY turn, not just heartbeats (TRDD-DLI76AUC #4).

The meter was born as a *heartbeat* meter (TRDD-a4e41e89) and its Stop hook returned early
on `not usage.is_heartbeat`. So the janitor's own cost telemetry could not see a single
INTERACTIVE turn — including a user-typed `/janitor-arm`, i.e. exactly the turn TRDD-DLI76AUC
set out to make cheaper. The optimization could be argued but not measured, which is how a
±4-minute fuzzy join came to be used as evidence instead (that TRDD's `[^2]`).

The same blindness quietly under-counted `/janitor-token-report`'s rolling 5h/7d window sums,
since a user's own work turns are the expensive ones.

These tests drive the REAL hook as a subprocess over a REAL fixture transcript — the hook's
early return lived in the hook, so a unit test of the pure parser could never have caught it.
"""

from __future__ import annotations

import importlib.util as _u
import json
import os
import subprocess
import sys
import types
import unittest
import unittest.mock
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import token_meter  # noqa: E402

HOOK = REPO / "scripts" / "hooks" / "on-stop-token-meter.py"


def _import_meter_hook():
    # The hook filename has dashes, so it cannot be a normal import — load it by path.
    spec = _u.spec_from_file_location("on_stop_token_meter_under_test", str(HOOK))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)  # runs the module body; main() is NOT called (name != __main__)
    return mod


class _FakeState:
    """Collects log_line calls instead of writing to disk."""

    def __init__(self) -> None:
        self.lines: list[str] = []

    def log_line(self, name: str, message: str) -> None:
        self.lines.append(f"[{name}] {message}")


class _FakeTokenMeter:
    """Stands in for the real token_meter module: fixed context size, real default_window."""

    def __init__(self, tokens: int) -> None:
        self._tokens = tokens

    def latest_context_size(self, _transcript_path: str):
        return self._tokens

    def default_window(self, env=None) -> int:
        return token_meter.default_window(env)


def _fake_pending_agents_module(*, live_count: int) -> types.ModuleType:
    mod = types.ModuleType("pending_agents")

    def load_pending(now=None, *, state_dir=None):
        return [{"id": f"agent-{i}"} for i in range(live_count)]

    def agent_is_live(entry, now, stale_s):
        return True

    mod.load_pending = load_pending  # type: ignore[attr-defined]
    mod.agent_is_live = agent_is_live  # type: ignore[attr-defined]
    return mod


def _fake_user_intent_module(*, interrupted_secs) -> types.ModuleType:
    mod = types.ModuleType("user_intent")

    def recently_interrupted(project_dir, window_s=None, now=None, *, transcript_path=None, home=None):
        return interrupted_secs

    mod.recently_interrupted = recently_interrupted  # type: ignore[attr-defined]
    return mod


def _fake_clear_trigger_module(*, spawned: bool = True, why: str = "chain spawned") -> types.ModuleType:
    mod = types.ModuleType("clear_trigger")
    mod.BOOTSTRAP_CMDS = ("/janitor-arm", "/janitor-resume")  # type: ignore[attr-defined]
    calls: list[dict] = []

    def spawn_shrink_chain(
        *, then, directive, delay=2.0, settle_between_s=0.0, transcript_path=None,
        count_toward_cooldown=False, recovered_after=None,
    ):
        calls.append({
            "then": list(then),
            "directive": directive,
            "transcript_path": transcript_path,
            "count_toward_cooldown": count_toward_cooldown,
            "recovered_after": recovered_after,
        })
        return spawned, why

    mod.spawn_shrink_chain = spawn_shrink_chain  # type: ignore[attr-defined]
    mod._calls = calls  # type: ignore[attr-defined]
    return mod

_HB = "[janitor-heartbeat]\n/path/to/dispatcher-stub.py\nSurface stdout verbatim..."
_USER = "/janitor-arm"


def _user(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def _assistant(usage: dict, *, tool: bool = False) -> str:
    content: list = [{"type": "text", "text": "ok"}]
    if tool:
        content.append({"type": "tool_use", "name": "Bash", "input": {}})
    return json.dumps({"type": "assistant", "message": {"role": "assistant", "content": content, "usage": usage}})


_USAGE = {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 20}


def _run_hook(project: Path, transcript: Path) -> list[dict]:
    """Run the real Stop hook against `transcript`, return the resulting log records."""
    env = {
        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        "HOME": str(project),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
        "CLAUDE_PROJECT_DIR": str(project),
    }
    proc = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps({"transcript_path": str(transcript)}),
        capture_output=True,
        text=True,
        env=env,
        timeout=120,
    )
    # The hook must NEVER fail a turn, whatever happens inside it.
    assert proc.returncode == 0, f"hook exited {proc.returncode}: {proc.stderr}"
    log = project / ".janitor" / "state" / "token-meter.jsonl"
    if not log.is_file():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _read_kind_log(project: Path) -> list[dict]:
    """The TRDD-NEVQOHGS box-3 sidecar `.janitor/state/token-meter-kind.jsonl`
    the hook writes ONLY for a heartbeat turn whose stub printed a bare
    `[janitor-<kind>]` token line."""
    log = project / ".janitor" / "state" / "token-meter-kind.jsonl"
    if not log.is_file():
        return []
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _tool_result_with(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": text}]}})


class TestEveryTurnIsLogged(unittest.TestCase):
    def test_a_user_turn_is_logged_and_tagged_interactive(self) -> None:
        """A user-typed turn (e.g. /janitor-arm) IS metered, tagged heartbeat=False.

        This is the regression that motivated the change: under the old `not
        usage.is_heartbeat` gate this produced ZERO records, so an arm's cost was
        unmeasurable.
        """
        with TemporaryDirectory() as d:
            project = Path(d)
            t = project / "transcript.jsonl"
            t.write_text("\n".join([_user(_USER), _assistant(_USAGE, tool=True)]) + "\n", encoding="utf-8")

            records = _run_hook(project, t)

            self.assertEqual(len(records), 1, "a user turn must be logged — the meter was blind to interactive turns")
            self.assertIs(records[0]["heartbeat"], False, "a user turn must be tagged heartbeat=False")
            self.assertEqual(records[0]["output"], 40)
            self.assertEqual(records[0]["tool_calls"], 1, "tool_calls is the cost driver (cost ~ tool_calls x context x 0.1)")

    def test_a_heartbeat_turn_is_still_logged_and_tagged(self) -> None:
        """Widening the meter must not stop it doing its original job."""
        with TemporaryDirectory() as d:
            project = Path(d)
            t = project / "transcript.jsonl"
            t.write_text("\n".join([_user(_HB), _assistant(_USAGE)]) + "\n", encoding="utf-8")

            records = _run_hook(project, t)

            self.assertEqual(len(records), 1)
            self.assertIs(records[0]["heartbeat"], True)


class TestFireKindSidecar(unittest.TestCase):
    """TRDD-NEVQOHGS box 3: the hook writes `token-meter-kind.jsonl` for a heartbeat
    fire, joined to its token-meter.jsonl record by the SAME `ts` (never a key on the
    pinned record itself, TRDD-ZCODD6YS)."""

    def test_janitor_quiet_heartbeat_writes_sidecar_kind(self) -> None:
        with TemporaryDirectory() as d:
            project = Path(d)
            t = project / "transcript.jsonl"
            t.write_text(
                "\n".join(
                    [
                        _user(_HB),
                        _assistant(_USAGE, tool=True),
                        _tool_result_with("[janitor-quiet]\n"),
                        _assistant(_USAGE),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            records = _run_hook(project, t)
            kind_records = _read_kind_log(project)

            self.assertEqual(len(records), 1)
            self.assertEqual(len(kind_records), 1)
            self.assertEqual(kind_records[0]["kind"], "quiet")
            self.assertEqual(kind_records[0]["id"], records[0]["ts"], "sidecar must join on the SAME ts")

    def test_janitor_memory_consolidate_heartbeat_writes_sidecar_kind(self) -> None:
        with TemporaryDirectory() as d:
            project = Path(d)
            t = project / "transcript.jsonl"
            t.write_text(
                "\n".join(
                    [
                        _user(_HB),
                        _assistant(_USAGE, tool=True),
                        _tool_result_with("[janitor-memory-consolidate]\nSTATE_DIR=/x\n"),
                        _assistant(_USAGE),
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            records = _run_hook(project, t)
            kind_records = _read_kind_log(project)

            self.assertEqual(len(kind_records), 1)
            self.assertEqual(kind_records[0]["kind"], "memory-consolidate")
            self.assertEqual(kind_records[0]["id"], records[0]["ts"])

    def test_interactive_turn_writes_no_sidecar(self) -> None:
        """An interactive (non-heartbeat) turn is metered but never kind-tagged."""
        with TemporaryDirectory() as d:
            project = Path(d)
            t = project / "transcript.jsonl"
            t.write_text("\n".join([_user(_USER), _assistant(_USAGE, tool=True)]) + "\n", encoding="utf-8")

            records = _run_hook(project, t)
            kind_records = _read_kind_log(project)

            self.assertEqual(len(records), 1)
            self.assertEqual(kind_records, [], "an interactive turn must never write a fire-kind sidecar line")


class TestRecordShape(unittest.TestCase):
    def test_as_record_carries_the_heartbeat_tag(self) -> None:
        """Without the tag the widened log is unreadable — every turn would look alike."""
        for is_hb in (True, False):
            usage = token_meter.TurnUsage(
                is_heartbeat=is_hb,
                input_tokens=1,
                output_tokens=2,
                cache_read_input_tokens=3,
                cache_creation_input_tokens=4,
                assistant_messages=1,
                tool_calls=5,
            )
            rec = usage.as_record(1_700_000_000)
            self.assertIn("heartbeat", rec)
            self.assertIs(rec["heartbeat"], is_hb)

    def test_the_report_reads_a_legacy_untagged_record_as_a_heartbeat(self) -> None:
        """A record predating the widening MUST count as a heartbeat, not as interactive.

        Every line written before this change was, by construction, a heartbeat — the old gate
        admitted nothing else. A reader that defaulted the missing key to False would relabel
        the WHOLE history as interactive, which would empty the heartbeat-only sample that
        `/janitor-token-report` uses to decide whether to advise on the beat.

        This drives the real report as a subprocess over a mixed log (2 legacy + 1 tagged
        heartbeat + 1 tagged user turn) and asserts the split it prints.
        """
        with TemporaryDirectory() as d:
            project = Path(d)
            state = project / ".janitor" / "state"
            state.mkdir(parents=True)
            base = {"output": 10, "input": 1, "cache_read": 100, "cache_creation": 0, "tool_calls": 1}
            lines = [
                json.dumps({"ts": 1_700_000_000, **base}),  # legacy: no `heartbeat` key
                json.dumps({"ts": 1_700_000_060, **base}),  # legacy: no `heartbeat` key
                json.dumps({"ts": 1_700_000_120, "heartbeat": True, **base}),
                json.dumps({"ts": 1_700_000_180, "heartbeat": False, **base}),
            ]
            (state / "token-meter.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

            proc = subprocess.run(
                [sys.executable, str(REPO / "scripts" / "token_report.py"), "--json"],
                capture_output=True,
                text=True,
                env={
                    "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                    "HOME": str(project),
                    "CLAUDE_PROJECT_DIR": str(project),
                },
                timeout=120,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            report = json.loads(proc.stdout)

            self.assertEqual(report["count"], 4)
            self.assertEqual(report["heartbeat_turns"], 3, "the 2 legacy records must count as heartbeats, not interactive")
            self.assertEqual(report["user_turns"], 1)


class TestTurnBoundaryClear(unittest.TestCase):
    """TRDD-11GAS4LC / issue #306: the Stop hook, not the PreToolUse guard, decides
    whether to launch a turn-boundary /clear. These drive `_maybe_clear` in-process with
    fake `state`/`token_meter` (explicit params) and fake `pending_agents`/`user_intent`/
    `clear_trigger` injected via `sys.modules` (the hook imports them lazily by name)."""

    def setUp(self) -> None:
        self.mod = _import_meter_hook()
        self._saved_modules = {
            name: sys.modules.get(name) for name in ("pending_agents", "user_intent", "clear_trigger")
        }

    def tearDown(self) -> None:
        for name, mod in self._saved_modules.items():
            if mod is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = mod

    def test_clear_point_is_below_the_harness_forced_compact_point(self) -> None:
        """A test reads the value the harness actually has (CLAUDE_CODE_AUTO_COMPACT_WINDOW)
        and asserts the clear point is below it."""
        with unittest.mock.patch.dict("os.environ", {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "900000"}):
            window = self.mod._harness_window(dict(os.environ), token_meter)
            self.assertEqual(window, 900000)
            clear_at = self.mod._pct_tokens(window, self.mod._DEFAULT_CLEAR_AT_PCT)
            self.assertLess(clear_at, window - self.mod._COMPACT_SUMMARY_OVERHEAD)
            self.assertLess(clear_at, window)

    def test_700k_of_900k_does_not_clear(self) -> None:
        state = _FakeState()
        tm = _FakeTokenMeter(700_000)
        with unittest.mock.patch.dict("os.environ", {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "900000"}):
            self.mod._maybe_clear("/proj", "/proj/t.jsonl", state, tm)
        self.assertEqual(state.lines, [], "700k of 900k is below the 83% clear point — no clear, no log")

    def test_760k_with_a_live_agent_defers_and_logs(self) -> None:
        sys.modules["pending_agents"] = _fake_pending_agents_module(live_count=1)
        state = _FakeState()
        tm = _FakeTokenMeter(760_000)
        with unittest.mock.patch.dict("os.environ", {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "900000"}):
            self.mod._maybe_clear("/proj", "/proj/t.jsonl", state, tm)
        self.assertTrue(any("clear deferred" in ln and "agent(s) live" in ln for ln in state.lines), state.lines)

    def test_830k_with_a_live_agent_clears_past_the_ceiling(self) -> None:
        """830k of 900k = 92.2%, past the default 92% ceiling — clears regardless."""
        sys.modules["pending_agents"] = _fake_pending_agents_module(live_count=1)
        sys.modules["clear_trigger"] = fake_ct = _fake_clear_trigger_module()
        state = _FakeState()
        tm = _FakeTokenMeter(830_000)
        with unittest.mock.patch.dict("os.environ", {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "900000"}):
            self.mod._maybe_clear("/proj", "/proj/t.jsonl", state, tm)
        self.assertEqual(len(fake_ct._calls), 1, "past the ceiling the chain must be launched regardless of a live agent")
        self.assertTrue(any("past ceiling" in ln for ln in state.lines), state.lines)
        # TRDD-RAEGS1D5 card 5: this is an AUTOMATIC clear, so it must opt into the shared
        # cooldown stamp -- `spawn_shrink_chain` itself now owns writing the stamp.
        self.assertTrue(fake_ct._calls[0]["count_toward_cooldown"])

    def test_760k_with_a_recent_interrupt_defers(self) -> None:
        sys.modules["pending_agents"] = _fake_pending_agents_module(live_count=0)
        sys.modules["user_intent"] = _fake_user_intent_module(interrupted_secs=30.0)
        state = _FakeState()
        tm = _FakeTokenMeter(760_000)
        with unittest.mock.patch.dict("os.environ", {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "900000"}):
            self.mod._maybe_clear("/proj", "/proj/t.jsonl", state, tm)
        self.assertTrue(any("clear deferred" in ln and "interrupted" in ln for ln in state.lines), state.lines)

    def test_760k_with_no_agent_and_no_interrupt_launches_the_chain(self) -> None:
        sys.modules["pending_agents"] = _fake_pending_agents_module(live_count=0)
        sys.modules["user_intent"] = _fake_user_intent_module(interrupted_secs=None)
        sys.modules["clear_trigger"] = fake_ct = _fake_clear_trigger_module()
        state = _FakeState()
        tm = _FakeTokenMeter(760_000)
        with unittest.mock.patch.dict("os.environ", {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "900000"}):
            self.mod._maybe_clear("/proj", "/proj/t.jsonl", state, tm)
        self.assertEqual(len(fake_ct._calls), 1)
        self.assertEqual(fake_ct._calls[0]["transcript_path"], "/proj/t.jsonl")
        # TRDD-RAEGS1D5 card 5: this Stop-boundary clear used to stamp NOTHING, leaving the
        # shared cooldown blind to it -- it must now opt into the stamp `spawn_shrink_chain`
        # owns internally.
        self.assertTrue(fake_ct._calls[0]["count_toward_cooldown"])
        # TRDD-RAEGS1D5 card 5 item 2: this hook only runs after a Stop that SUCCEEDED --
        # `recovered_after` must be a real, roughly-now epoch, not the default None, so a
        # fresh `rate-limited.flag` from an EARLIER turn's transient API error cannot lock
        # this clear out for up to a day.
        import time as _time

        recovered_after = fake_ct._calls[0]["recovered_after"]
        self.assertIsNotNone(recovered_after)
        self.assertAlmostEqual(recovered_after, int(_time.time()), delta=5)


if __name__ == "__main__":
    unittest.main()
