"""Tests for the per-heartbeat token meter (TRDD-a4e41e89, Phase 1).

Real I/O, no mocks: each case writes a fixture transcript JSONL to a temp file
and runs the pure parser, asserting the summed usage + heartbeat detection.
"""

import json
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import token_meter  # noqa: E402


def _user(text: str) -> str:
    return json.dumps({"type": "user", "message": {"role": "user", "content": text}})


def _assistant(
    *, text: str = "", usage: dict | None = None, tool: bool = False, msg_id: str | None = None
) -> str:
    content: list = []
    if text:
        content.append({"type": "text", "text": text})
    if tool:
        content.append({"type": "tool_use", "name": "Bash", "input": {}})
    msg: dict = {"role": "assistant", "content": content}
    if usage is not None:
        msg["usage"] = usage
    if msg_id is not None:
        msg["id"] = msg_id
    return json.dumps({"type": "assistant", "message": msg})


def _tool_result() -> str:
    """A tool-result entry — delivered as a user-role message (NOT a real prompt),
    exactly as the real transcript records the reply to a tool call."""
    return json.dumps({"type": "user", "message": {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "x", "content": "out"}]}})


_HB = "[janitor-heartbeat]\n/path/to/dispatcher-stub.py\nSurface stdout verbatim..."


def _write(tmp: Path, *lines: str) -> Path:
    p = tmp / "transcript.jsonl"
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


class TestTokenMeter(unittest.TestCase):
    def test_heartbeat_turn_sums_usage(self):
        """A heartbeat turn's assistant messages are summed; is_heartbeat=True."""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            t = _write(
                tmp,
                _user("a previous human prompt"),
                _assistant(text="prev", usage={"input_tokens": 9, "output_tokens": 9}),
                _user(_HB),
                _assistant(text="", tool=True, usage={"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 5000, "cache_creation_input_tokens": 20}),
                _assistant(text="silent", usage={"input_tokens": 30, "output_tokens": 12, "cache_read_input_tokens": 5100, "cache_creation_input_tokens": 0}),
            )
            u = token_meter.tail_turn_usage(t)
            self.assertIsNotNone(u)
            assert u is not None
            self.assertTrue(u.is_heartbeat)
            self.assertEqual(u.input_tokens, 130)
            self.assertEqual(u.output_tokens, 52)
            self.assertEqual(u.cache_read_input_tokens, 10100)
            self.assertEqual(u.cache_creation_input_tokens, 20)
            self.assertEqual(u.assistant_messages, 2)
            self.assertEqual(u.tool_calls, 1)
            # The previous turn's usage (9/9) must NOT be included.

    def test_multistep_heartbeat_turn_with_tool_results(self):
        """The REAL shape: a heartbeat turn whose assistant calls tools, so the
        turn contains tool_result USER messages interleaved. The walk-back must
        step over those and find the real `[janitor-heartbeat]` prompt — summing
        usage across ALL the turn's assistant messages. (Regression for the bug
        where the meter stopped at the last tool_result → is_heartbeat=False.)"""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            t = _write(
                tmp,
                _user(_HB),
                _assistant(text="", tool=True, usage={"input_tokens": 100, "output_tokens": 40}),
                _tool_result(),
                _assistant(text="", tool=True, usage={"input_tokens": 30, "output_tokens": 15}),
                _tool_result(),
                _assistant(text="silent", usage={"input_tokens": 12, "output_tokens": 5}),
            )
            u = token_meter.tail_turn_usage(t)
            self.assertIsNotNone(u)
            assert u is not None
            self.assertTrue(u.is_heartbeat)  # found the real prompt, not a tool_result
            self.assertEqual(u.input_tokens, 142)  # summed across all 3 assistant msgs
            self.assertEqual(u.output_tokens, 60)
            self.assertEqual(u.assistant_messages, 3)
            self.assertEqual(u.tool_calls, 2)

    def test_duplicated_usage_entries_counted_once_per_message(self):
        """REGRESSION (the 'janitor meter is FLAWED' bug, 2026-07-07): Claude Code writes
        one assistant transcript ENTRY per streamed content block, each repeating the SAME
        message.usage — verified live at 2.1-3.7x inflation when summed per entry. Usage
        must be counted ONCE per unique message id, while tool_use blocks (distinct per
        entry) keep per-entry counting."""
        dup_usage = {
            "input_tokens": 10,
            "output_tokens": 50,
            "cache_read_input_tokens": 9_000_000,
            "cache_creation_input_tokens": 300_000,
        }
        with TemporaryDirectory() as d:
            tmp = Path(d)
            t = _write(
                tmp,
                _user("do the thing"),
                # ONE API response streamed as 3 entries (text + 2 tool_use blocks),
                # all carrying identical usage under the same message id.
                _assistant(text="thinking...", usage=dup_usage, msg_id="msg_A"),
                _assistant(tool=True, usage=dup_usage, msg_id="msg_A"),
                _assistant(tool=True, usage=dup_usage, msg_id="msg_A"),
                _tool_result(),
                # A second, distinct API response.
                _assistant(
                    text="done",
                    usage={
                        "input_tokens": 5,
                        "output_tokens": 20,
                        "cache_read_input_tokens": 1_000_000,
                        "cache_creation_input_tokens": 7_000,
                    },
                    msg_id="msg_B",
                ),
            )
            u = token_meter.tail_turn_usage(t)
            self.assertIsNotNone(u)
            assert u is not None
            # Once per message — NOT 3x msg_A.
            self.assertEqual(u.input_tokens, 15)
            self.assertEqual(u.output_tokens, 70)
            self.assertEqual(u.cache_read_input_tokens, 10_000_000)
            self.assertEqual(u.cache_creation_input_tokens, 307_000)
            self.assertEqual(u.assistant_messages, 2)  # unique messages, not entries
            self.assertEqual(u.tool_calls, 2)  # per-entry blocks are genuinely distinct

    def test_non_heartbeat_turn_flagged_false(self):
        """A normal (typed) user turn → is_heartbeat=False (so the hook logs nothing)."""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            t = _write(
                tmp,
                _user("please fix the bug"),
                _assistant(text="done", usage={"input_tokens": 200, "output_tokens": 80}),
            )
            u = token_meter.tail_turn_usage(t)
            self.assertIsNotNone(u)
            assert u is not None
            self.assertFalse(u.is_heartbeat)

    def test_missing_usage_is_graceful(self):
        """An assistant message with no usage object contributes zeros, no crash."""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            t = _write(tmp, _user(_HB), _assistant(text="no-usage-here", usage=None))
            u = token_meter.tail_turn_usage(t)
            self.assertIsNotNone(u)
            assert u is not None
            self.assertTrue(u.is_heartbeat)
            self.assertEqual(u.output_tokens, 0)
            self.assertEqual(u.assistant_messages, 0)

    def test_no_trigger_in_tail_returns_none(self):
        """A tail with assistant entries but no `user` boundary → None (don't guess)."""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            t = _write(
                tmp,
                _assistant(text="orphan", usage={"input_tokens": 1, "output_tokens": 1}),
            )
            self.assertIsNone(token_meter.tail_turn_usage(t))

    def test_absent_file_returns_none(self):
        self.assertIsNone(token_meter.tail_turn_usage("/no/such/transcript.jsonl"))

    def test_partial_first_line_skipped(self):
        """A leading partial JSON fragment (as when the tail window cuts a line) is
        skipped without breaking the parse."""
        with TemporaryDirectory() as d:
            tmp = Path(d)
            p = tmp / "t.jsonl"
            p.write_text(
                '{"type":"assistant","message":{"content":[],"usage":{"output_to'  # truncated
                + "\n"
                + _user(_HB)
                + "\n"
                + _assistant(text="ok", usage={"input_tokens": 7, "output_tokens": 3})
                + "\n",
                encoding="utf-8",
            )
            u = token_meter.tail_turn_usage(p)
            self.assertIsNotNone(u)
            assert u is not None
            self.assertTrue(u.is_heartbeat)
            self.assertEqual(u.output_tokens, 3)

    def test_append_and_summarize_roundtrip(self):
        """append_log writes one JSON line per turn; summarize computes stats."""
        with TemporaryDirectory() as d:
            log = Path(d) / "token-meter.jsonl"
            for i, out in enumerate((10, 20, 30, 40, 1000)):  # 1000 = spike
                u = token_meter.TurnUsage(is_heartbeat=True, input_tokens=5, output_tokens=out, cache_read_input_tokens=100, cache_creation_input_tokens=0, assistant_messages=1, tool_calls=1)
                token_meter.append_log(log, u, now_epoch=1000 + i)
            recs = token_meter.load_log(log)
            self.assertEqual(len(recs), 5)
            stats = token_meter.summarize(recs, field="output")
            assert stats is not None
            self.assertEqual(stats["count"], 5)
            self.assertEqual(stats["total"], 1100)
            self.assertEqual(stats["max"], 1000)
            self.assertEqual(stats["min"], 10)
            self.assertEqual(stats["mean"], 220)

    def test_summarize_empty_is_none(self):
        self.assertIsNone(token_meter.summarize([]))

    def test_trim_log_caps_oversized(self):
        """An oversized log is rewritten to the last keep_lines; a small one is left alone."""
        with TemporaryDirectory() as d:
            log = Path(d) / "token-meter.jsonl"
            log.write_text("".join(f'{{"ts":{i},"output":{i}}}\n' for i in range(100)), encoding="utf-8")
            # Small file, tiny max_bytes=huge → no trim.
            token_meter.trim_log(log, keep_lines=10, max_bytes=10_000_000)
            self.assertEqual(len(token_meter.load_log(log)), 100)
            # Force a trim by setting max_bytes below the current size.
            token_meter.trim_log(log, keep_lines=10, max_bytes=10)
            recs = token_meter.load_log(log)
            self.assertEqual(len(recs), 10)
            self.assertEqual(recs[0]["ts"], 90)  # kept the LAST 10
            self.assertEqual(recs[-1]["ts"], 99)


def _usage(*, output: int = 0, cache_creation: int = 0) -> token_meter.TurnUsage:
    return token_meter.TurnUsage(
        is_heartbeat=False,
        input_tokens=0,
        output_tokens=output,
        cache_read_input_tokens=0,
        cache_creation_input_tokens=cache_creation,
        assistant_messages=1,
        tool_calls=1,
    )


class TestEvaluateTurnBudget(unittest.TestCase):
    """The pure real-time budget classifier (TRDD-KI24GR5Z)."""

    _TH = dict(output_advisory=100, output_hard=1000, cache_creation_advisory=200, cache_creation_hard=2000)

    def test_ok_below_both_advisory(self):
        v = token_meter.evaluate_turn_budget(_usage(output=50, cache_creation=50), **self._TH)
        self.assertEqual(v.tier, "ok")
        self.assertEqual(v.reasons, [])

    def test_output_advisory(self):
        v = token_meter.evaluate_turn_budget(_usage(output=150), **self._TH)
        self.assertEqual(v.tier, "advisory")
        self.assertTrue(any("output 150" in r for r in v.reasons))

    def test_output_hard(self):
        v = token_meter.evaluate_turn_budget(_usage(output=1500), **self._TH)
        self.assertEqual(v.tier, "hard")

    def test_cache_miss_advisory_independent_of_output(self):
        """A cache-miss write over its advisory budget trips even with zero output."""
        v = token_meter.evaluate_turn_budget(_usage(output=0, cache_creation=300), **self._TH)
        self.assertEqual(v.tier, "advisory")
        self.assertTrue(any("cache-miss write 300" in r for r in v.reasons))

    def test_cache_miss_hard(self):
        v = token_meter.evaluate_turn_budget(_usage(cache_creation=2500), **self._TH)
        self.assertEqual(v.tier, "hard")

    def test_hard_wins_over_advisory_across_signals(self):
        """One signal hard + the other advisory → tier is hard; reasons name both."""
        v = token_meter.evaluate_turn_budget(_usage(output=1500, cache_creation=300), **self._TH)
        self.assertEqual(v.tier, "hard")
        self.assertEqual(len(v.reasons), 2)

    def test_zero_threshold_disables_that_signal(self):
        """output budgets = 0 → output never trips, even at a huge value."""
        v = token_meter.evaluate_turn_budget(
            _usage(output=10_000_000),
            output_advisory=0,
            output_hard=0,
            cache_creation_advisory=200,
            cache_creation_hard=2000,
        )
        self.assertEqual(v.tier, "ok")

    def test_ignore_cache_creation_suppresses_hard_trip(self):
        """TRDD-TKNSTP82 A1: ignore_cache_creation=True + cache_creation past HARD threshold
        + output below threshold -> tier 'ok' (the post-compact grace window)."""
        v = token_meter.evaluate_turn_budget(_usage(output=0, cache_creation=5000), ignore_cache_creation=True, **self._TH)
        self.assertEqual(v.tier, "ok")
        self.assertEqual(v.reasons, [])

    def test_ignore_cache_creation_suppresses_advisory_trip(self):
        """Same suppression at the advisory tier, not just hard."""
        v = token_meter.evaluate_turn_budget(_usage(output=0, cache_creation=300), ignore_cache_creation=True, **self._TH)
        self.assertEqual(v.tier, "ok")

    def test_ignore_cache_creation_does_not_suppress_output(self):
        """The output signal is UNAFFECTED by ignore_cache_creation — a genuine runaway
        during the grace window is still caught."""
        v = token_meter.evaluate_turn_budget(_usage(output=1500, cache_creation=5000), ignore_cache_creation=True, **self._TH)
        self.assertEqual(v.tier, "hard")
        self.assertEqual(len(v.reasons), 1)
        self.assertTrue(v.reasons[0].startswith("output"))

    def test_ignore_cache_creation_default_false_unchanged(self):
        """Default (no ignore_cache_creation arg) behavior is byte-identical to before A1:
        a cache-miss-hard trip still fires."""
        v = token_meter.evaluate_turn_budget(_usage(cache_creation=2500), **self._TH)
        self.assertEqual(v.tier, "hard")
        self.assertTrue(any("cache-miss write 2500" in r for r in v.reasons))


class TestReloadGuardShouldBlock(unittest.TestCase):
    """F1 reload-churn guard (TRDD-Z582IKIR) — the shared predicate used by BOTH
    dispatch.py's `_phase_plugin_reload` (defer) and the UserPromptSubmit hook
    (block), so the two gates can never disagree about the trip point."""

    def test_below_threshold_allows(self):
        self.assertFalse(token_meter.reload_guard_should_block(100_000, 350_000))

    def test_at_or_above_threshold_blocks(self):
        self.assertTrue(token_meter.reload_guard_should_block(350_000, 350_000))
        self.assertTrue(token_meter.reload_guard_should_block(999_999, 350_000))

    def test_unknown_context_fails_open(self):
        """None (unresolvable context) must never block — an unreadable context must
        never turn a reload into a stuck block."""
        self.assertFalse(token_meter.reload_guard_should_block(None, 350_000))

    def test_disabled_threshold_fails_open(self):
        """threshold <= 0 is the documented explicit opt-out — never blocks regardless
        of context size."""
        self.assertFalse(token_meter.reload_guard_should_block(999_999, 0))
        self.assertFalse(token_meter.reload_guard_should_block(999_999, -1))

    def test_default_threshold_constant(self):
        self.assertEqual(token_meter.RELOAD_GUARD_DEFAULT_THRESHOLD, 350_000)


class TestExhaustionLog(unittest.TestCase):
    """The window-exhaustion event log (TRDD-EDSFEQ5C) — best-effort, capped, never raises."""

    def test_append_and_load(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "window-exhaustion.jsonl"
            for i in range(3):
                token_meter.append_exhaustion_event(p, {"ts": i, "roll_5h": i * 100, "roll_7d": i * 200})
            recs = token_meter.load_log(p)
            self.assertEqual(len(recs), 3)
            self.assertEqual(recs[-1]["roll_5h"], 200)

    def test_caps_to_max_events(self):
        with TemporaryDirectory() as d:
            p = Path(d) / "we.jsonl"
            for i in range(10):
                token_meter.append_exhaustion_event(p, {"ts": i}, max_events=5)
            recs = token_meter.load_log(p)
            self.assertEqual(len(recs), 5)
            self.assertEqual(recs[0]["ts"], 5)  # oldest kept is event #5 (0-4 trimmed)

    def test_bad_path_never_raises(self):
        with TemporaryDirectory() as d:
            token_meter.append_exhaustion_event(d, {"ts": 1})  # d is a DIR → open() fails, swallowed


if __name__ == "__main__":
    unittest.main()
