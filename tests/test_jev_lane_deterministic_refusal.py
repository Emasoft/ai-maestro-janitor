"""End-to-end lane test for TRDD-7XDBJZCZ: a deterministic llm-ext refusal stops the Jev retry loop.

Real `jev_compact.py compact` runs as a subprocess under the real
`jev_compaction_lane.run_compact_with_fallback`; only the `llm-ext` binary (a stand-in script
first on PATH that counts its own invocations) and the `llm_ext_compact.py` fallback are stubbed,
and the retry clock is simulated so the 15 s sleeps cost no wall time.
"""

from __future__ import annotations

import json
import os
import stat
import sys
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import jev_compaction_lane as jcl  # noqa: E402
import state  # noqa: E402

_REAL_JEV_COMPACT = _SCRIPTS / "jev_compact.py"
_FALLBACK_TEXT = "llm-ext fallback summary"

_STAND_IN_LLM_EXT = """#!{python}
import sys
from pathlib import Path

with Path({counter!r}).open("a", encoding="utf-8") as fh:
    fh.write(" ".join(sys.argv[1:3]) + "\\n")
sys.stderr.write({stderr!r})
sys.exit({exit_code})
"""

_FALLBACK_STUB = """#!{python}
import sys

sys.stdout.write({text!r})
"""


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def _write_executable(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def _write_transcript(tmp_path: Path) -> Path:
    """A human message plus a tool result, so `compact` has a digest and one item to score."""
    entries = [
        {"type": "user", "uuid": "u-1", "parentUuid": None,
         "message": {"role": "user", "content": "hello, please fix the bug"}},
        {"type": "assistant", "uuid": "a-1", "parentUuid": "u-1",
         "message": {"role": "assistant", "content": [{"type": "text", "text": "fixed it."}]}},
        {"type": "user", "uuid": "u-2", "parentUuid": "a-1",
         "message": {"role": "user", "content": [
             {"type": "tool_result", "tool_use_id": "t1", "content": "file written: 12 lines"}]}},
    ]
    path = tmp_path / "transcript.jsonl"
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "control"))
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        fn.cache_clear()
    yield
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        fn.cache_clear()


def _run_lane(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, llm_ext_stderr: str, llm_ext_exit: int,
    deadline: float,
) -> tuple[tuple[str, str | None, str], list[str], _FakeClock]:
    """Run the real lane against a stand-in `llm-ext`; return (result, classify-call log, clock)."""
    bin_dir = tmp_path / "bin"
    counter = tmp_path / "llm-ext-calls.txt"
    _write_executable(
        bin_dir / "llm-ext",
        _STAND_IN_LLM_EXT.format(
            python=sys.executable, counter=str(counter), stderr=llm_ext_stderr,
            exit_code=llm_ext_exit,
        ),
    )
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")

    plugin_root = tmp_path / "plugin"
    # The real CLI, exec'd by path the way the lane does, but through the venv interpreter so the
    # test needs no `uv` network access for the script's PEP-723 dependency.
    _write_executable(
        plugin_root / "scripts" / "jev_compact.py",
        f'#!/bin/sh\nexec "{sys.executable}" "{_REAL_JEV_COMPACT}" "$@"\n',
    )
    _write_executable(
        plugin_root / "scripts" / "llm_ext_compact.py",
        _FALLBACK_STUB.format(python=sys.executable, text=_FALLBACK_TEXT),
    )
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    clock = _FakeClock()
    result = jcl.run_compact_with_fallback(
        plugin_root, transcript=str(_write_transcript(tmp_path)), out_path=tmp_path / "out.md",
        session_key="k", heads_args=[], sd=state.state_dir(), deadline=deadline,
        hold_expires=900.0, now_fn=clock.time, sleep_fn=clock.sleep,
    )
    calls = counter.read_text(encoding="utf-8").splitlines() if counter.exists() else []
    return result, calls, clock


def test_path_refusal_makes_one_jev_attempt_then_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """llm-ext exit 1 ("Path traversal blocked") is one Jev attempt, no sleep, then the fallback."""
    (source, text, _detail), calls, clock = _run_lane(
        tmp_path, monkeypatch,
        llm_ext_stderr="Path traversal blocked: /private/var/x is outside the allowed roots\n",
        llm_ext_exit=1, deadline=300.0,
    )

    assert calls == ["classify filter"], f"expected exactly one classify attempt, got {calls}"
    assert clock.now == 0.0, "a deterministic refusal must not sleep before falling back"
    assert (source, text) == (jcl.SOURCE_LLM_EXT, _FALLBACK_TEXT)


def test_transient_llm_ext_failure_is_retried_before_the_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """llm-ext exit 5 is retried after the 15 s backoff, then falls back at the deadline."""
    (source, text, _detail), calls, clock = _run_lane(
        tmp_path, monkeypatch,
        llm_ext_stderr="API error 503: Service Unavailable\n", llm_ext_exit=5, deadline=50.0,
    )

    assert len(calls) > 1, f"a transient failure must retry, got {calls}"
    assert clock.now > 0.0, "retries must have gone through the backoff sleep"
    assert (source, text) == (jcl.SOURCE_LLM_EXT, _FALLBACK_TEXT)
