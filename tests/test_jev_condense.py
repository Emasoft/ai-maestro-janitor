"""jev_condense: the "results, not full output" views applied before Jev scoring (TRDD-RAEGS1D5).

Pure functions on synthetic inputs, no network. Each test pins one rule or guard from the
condenser design (reports/compaction-replacement/20260924_133449+0200-condenser-design.md §5).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import jev_condense as jcd  # noqa: E402

CEILING = 1000  # jev_compaction._SEGMENT_THRESHOLD_TOKENS, passed in by the real caller
DOTS = "tests/test_mod.py " + "." * 60 + " [ 10%]"


def _bash(command: str, output: str) -> str | None:
    return jcd.condense_tool("Bash", {"command": command}, output, item_id="u-1:0",
                             ceiling_tokens=CEILING)


def test_all_pass_run_keeps_only_the_summary_and_the_label() -> None:
    """R1: 200 progress lines collapse; the verbatim summary and the excerpt label remain."""
    out = "\n".join([DOTS] * 200 + ["412 passed in 3.1s"])
    view = _bash("uv run pytest -q", out)
    assert view is not None
    assert view.splitlines()[0] == "412 passed in 3.1s"
    assert "..........." not in view
    assert view.splitlines()[-1].startswith("[[excerpt id=u-1:0 kept=1/201 lines rule=test-noise")


def test_failing_run_keeps_every_failure_line_verbatim_and_in_order() -> None:
    """R1: FAILED, E lines, the short test summary and the summary survive, in order."""
    failure = [
        "____________________ test_thing ____________________",
        "tests/test_mod.py:12: in test_thing",
        "E   AssertionError: assert 1 == 2",
        "=========================== short test summary info ============================",
        "FAILED tests/test_mod.py::test_thing - AssertionError: assert 1 == 2",
        "1 failed, 411 passed in 3.4s",
    ]
    out = "\n".join([DOTS] * 200 + failure)
    view = _bash("pytest", out)
    assert view is not None
    assert view.splitlines()[:-1] == failure


def test_a_progress_line_carrying_f_or_e_is_never_noise() -> None:
    """R1: `..F..  [ 50%]` survives — the deny-list only drops lines made of . s x X p u."""
    out = "\n".join([DOTS] * 200 + ["..F..E..  [ 50%]", "1 failed, 1 error in 2.0s"])
    view = _bash("pytest", out)
    assert view is not None
    assert "..F..E..  [ 50%]" in view.splitlines()


def test_timeout_lines_survive() -> None:
    """R1: pytest-timeout's banner and failure line are not noise."""
    timeout = ["+++++++++++++++++++ Timeout +++++++++++++++++++", "Failed: Timeout >30.0s"]
    out = "\n".join([DOTS] * 200 + timeout + ["1 failed in 31.0s"])
    view = _bash("pytest", out)
    assert view is not None
    assert all(line in view.splitlines() for line in timeout)


def test_an_unrelated_line_in_a_test_chain_survives() -> None:
    """R1 deny-list property: a commit line from `pytest && git commit` is kept (v1's allow-list lost it)."""
    out = "\n".join([DOTS] * 200 + ["412 passed in 3.1s", "[main abc1234] fix: x"])
    view = _bash("pytest -q && git commit -m x", out)
    assert view is not None
    assert "[main abc1234] fix: x" in view.splitlines()


def test_lint_drops_only_pyright_noise_and_keeps_diagnostics_and_summaries() -> None:
    """R2: pyright's header lines go; diagnostics and both tools' summaries stay verbatim."""
    out = "\n".join([
        "No configuration file found.",
        "Searching for source files",
        "Found 12 source files",
        "pyright 1.1.400",
        "/repo/x.py:1:2 - error: Import \"y\" could not be resolved",
        "1 error, 0 warnings, 0 informations",
        "x.py:3:1: F401 `os` imported but unused",
        "Found 3 errors (2 fixed, 1 remaining).",
    ])
    selected = jcd._runner_kept_lines("ruff check --fix . && pyright", out)
    assert selected is not None
    rule, kept, _ = selected
    assert rule == "lint-noise"
    assert kept == out.splitlines()[4:]


def test_a_non_runner_bash_command_is_not_condensed() -> None:
    """G4: a plain query or action stays whole — its output IS the result."""
    assert _bash("git log --oneline -200", "\n".join(["abc1234 fix: thing"] * 300)) is None


def test_a_log_dump_is_not_condensed() -> None:
    """R3 is deliberately not built (0.1% saved, can hide the success line a log was read for)."""
    log = "\n".join([f"2026-09-24 10:00:{i:02d} INFO renew ok" for i in range(60)] * 5)
    assert _bash("tail -300 /var/log/app.log", log) is None


def test_persisted_output_is_never_condensed() -> None:
    """G1: the preview's saved-file path is the only way back to the full output."""
    out = "\n".join(["<persisted-output>", "Output too large. Full output saved to: /x/y.txt"]
                    + [DOTS] * 200 + ["412 passed in 3.1s"])
    assert _bash("pytest", out) is None


def test_read_of_a_code_file_keeps_its_first_and_last_numbered_lines() -> None:
    """R4: 300 numbered lines become the range read, verbatim, plus the on-disk label."""
    out = "\n".join(f"{i:>6}\tvalue_{i} = compute(value_{i - 1}, factor=2)" for i in range(1, 301))
    view = jcd.condense_tool("Read", {"file_path": "/repo/scripts/x.py"}, out, item_id="u-2:0",
                             ceiling_tokens=CEILING)
    assert view is not None
    first, last, label = view.splitlines()
    assert first == out.splitlines()[0]
    assert last == out.splitlines()[-1]
    assert "rule=read-range" in label and "the file is on disk" in label


def test_read_of_a_temp_file_or_a_non_code_file_is_not_condensed() -> None:
    """R4 scope: scratch files may be gone on resume; reports carry findings Jev keeps."""
    out = "\n".join(f"{i:>6}\tline {i} with some text to make it long enough" for i in range(1, 301))
    for path in ("/private/tmp/claude-501/x/scratchpad/x.py", "/repo/reports/x.md"):
        assert jcd.condense_tool("Read", {"file_path": path}, out, ceiling_tokens=CEILING) is None


def test_notification_keeps_a_failed_status_and_drops_a_completed_one() -> None:
    """R5: summary and result verbatim; <status> kept only when the sub-agent did not complete."""
    def notification(status: str) -> str:
        return "\n".join([
            "<task-notification>",
            "<task-id>a1b2c3d4e5f6a7b8c</task-id>",
            "<tool-use-id>toolu_0123456789abcdefghijkl</tool-use-id>",
            "<output-file>/private/tmp/claude-501/some/very/long/path/tasks/a1b2c3d4e5f6a7b8c.output</output-file>",
            f"<status>{status}</status>",
            '<summary>Agent "Fix the thing" finished</summary>',
            "<result>[DONE] fixed the thing. Report: /repo/reports/x.md</result>",
            "<usage><subagent_tokens>123456</subagent_tokens><tool_uses>42</tool_uses></usage>",
            "</task-notification>",
        ])

    failed = jcd.condense_event(notification("failed"), item_id="u-3:0", ceiling_tokens=CEILING)
    assert failed is not None
    assert failed.splitlines()[:-1] == [
        "<status>failed</status>",
        '<summary>Agent "Fix the thing" finished</summary>',
        "<result>[DONE] fixed the thing. Report: /repo/reports/x.md</result>",
    ]
    completed = jcd.condense_event(notification("completed"), ceiling_tokens=CEILING)
    assert completed is not None
    assert "<status>" not in completed
    assert "<task-id>" not in completed and "<output-file>" not in completed


def test_a_short_runner_output_is_below_the_minimum_saving() -> None:
    """G2: a 5-line pytest output saves too little to be worth a label."""
    out = "\n".join(["tests/test_mod.py ....", "", "4 passed in 0.1s", "", ""])
    assert _bash("pytest -q", out) is None


def test_a_view_over_the_ceiling_is_left_for_the_caller_to_segment() -> None:
    """G3: a failing run whose kept lines still exceed one item's budget returns None."""
    failures = [f"E   assert value_{i} == expected_{i}  # mismatch at index {i}" for i in range(400)]
    out = "\n".join([DOTS] * 2000 + failures + ["400 failed in 9.0s"])
    assert _bash("pytest", out) is None
