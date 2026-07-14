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

import json
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import token_meter  # noqa: E402

HOOK = REPO / "scripts" / "hooks" / "on-stop-token-meter.py"

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


if __name__ == "__main__":
    unittest.main()
