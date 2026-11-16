"""Issue 356, TRDD-C9CO0I7L: a janitor clear must wait while THIS session composes its handoff.

`handoff_files.compose_inflight` is a per-session probe over a stamp the composing process
writes. Everything here is real: a real child process owns the stamp (written through the very
function `compose_agent_handoff.py` calls, from a separate interpreter, keyed from its own
`CLAUDE_CODE_SESSION_ID`), the clear side derives its key from the TRANSCRIPT PATH
(`handoff_files.session_key`), real `_maybe_clear` runs over a real transcript, real `state`
and real `token_meter`. The only stub is `clear_trigger._spawn_chain` (the OS fork that would type
`/clear` into a pane), which is the same chokepoint the sibling tests stub; here it also records
whether the clear path was reached.
"""

from __future__ import annotations

import importlib.util as _u
import json
import os
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import clear_trigger  # noqa: E402
import handoff_files  # noqa: E402
import state  # noqa: E402
import token_meter  # noqa: E402
from test_clear_trigger import (  # noqa: E402
    _capture_still_wanted,
    _chain_payload_with_transcript,
    _import,
    _no_agents_no_interrupt,
)

HOOK = REPO / "scripts" / "hooks" / "on-stop-token-meter.py"
_SLEEPER = [sys.executable, "-c", "import time; time.sleep(30)"]
# Between the clear-at point (83% of 900k) and the ceiling (92%), where deferrals apply.
_TOKENS_BELOW_CEILING = 780_000

# A separate interpreter that stamps the way the composer does, then idles until killed.
_COMPOSER = (
    "import sys, time\n"
    "from pathlib import Path\n"
    f"sys.path.insert(0, {str(REPO / 'scripts' / 'lib')!r})\n"
    "import handoff_files\n"
    "handoff_files.compose_stamp_write(Path(sys.argv[1]), handoff_files.in_session_key())\n"
    "print('stamped', flush=True)\n"
    "time.sleep(30)\n"
)


def _import_meter_hook():
    spec = _u.spec_from_file_location("on_stop_token_meter_under_test_inflight", str(HOOK))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _clear_state_cache() -> None:
    state.project_root.cache_clear()
    state.janitor_root.cache_clear()
    state.state_dir.cache_clear()


def _write_stamp(sd: Path, key: str, pid: int, started: float) -> None:
    sd.mkdir(parents=True, exist_ok=True)
    (sd / handoff_files.compose_stamp_name(key)).write_text(
        json.dumps({"pid": pid, "started": started, "key": key}), encoding="utf-8"
    )


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("HOME", str(tmp_path))
    # A well-formed FAKE pane id so `spawn_shrink_chain` passes its channel check and reaches the
    # `_spawn_chain` chokepoint (stubbed below) instead of short-circuiting.
    monkeypatch.setenv("TMUX_PANE", "%99999")
    monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "900000")
    # The master switch is OFF by default (TRDD-HM8WOCOO); enable it the way the sibling tests do.
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_AUTO_CLEAR_ENABLED", "true")
    _clear_state_cache()
    yield tmp_path
    _clear_state_cache()


@pytest.fixture
def composer(project: Path) -> Iterator[tuple[subprocess.Popen, str]]:
    """A REAL separate process that has written the stamp. Yields (process, session id)."""
    session_id = str(uuid.uuid4())
    sd = project / ".janitor" / "state"
    sd.mkdir(parents=True)
    env = {**os.environ, "CLAUDE_CODE_SESSION_ID": session_id}
    proc = subprocess.Popen(
        [sys.executable, "-c", _COMPOSER, str(sd)],
        stdout=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "stamped"
        yield proc, session_id
    finally:
        if proc.poll() is None:
            proc.kill()
        proc.wait(timeout=5)


def test_probe_true_while_the_owner_lives_false_after_it_dies(tmp_path: Path) -> None:
    """A stamp whose pid is a live child reads True; once that child is killed it reads False."""
    child = subprocess.Popen(_SLEEPER)
    try:
        _write_stamp(tmp_path, "abcd1234", child.pid, time.time())
        assert handoff_files.compose_inflight(tmp_path, "abcd1234") is True
        child.kill()
        child.wait(timeout=5)
        assert handoff_files.compose_inflight(tmp_path, "abcd1234") is False
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)


def test_probe_false_for_a_stale_stamp_even_with_a_live_pid(tmp_path: Path) -> None:
    """Older than budget + grace is stale (covers pid reuse), whatever the pid says."""
    started = time.time() - (handoff_files.COMPOSE_BUDGET_S + 120)
    _write_stamp(tmp_path, "abcd1234", os.getpid(), started)
    assert handoff_files.compose_inflight(tmp_path, "abcd1234") is False


def test_probe_honours_the_budget_parameter(tmp_path: Path) -> None:
    """`budget_s` bounds the age: 100 s old is fresh under the default, stale under budget_s=10."""
    _write_stamp(tmp_path, "abcd1234", os.getpid(), time.time() - 100)
    assert handoff_files.compose_inflight(tmp_path, "abcd1234") is True
    assert handoff_files.compose_inflight(tmp_path, "abcd1234", budget_s=10) is False


def test_probe_false_when_no_stamp(tmp_path: Path) -> None:
    """No stamp file is no compose."""
    assert handoff_files.compose_inflight(tmp_path, "abcd1234") is False


@pytest.mark.parametrize(
    "content",
    ["not json {", "[]", "{}", "{\"pid\": \"x\", \"started\": 1}", "{\"pid\": 0, \"started\": 1e18}",
     "{\"pid\": true, \"started\": 1e18}"],
)
def test_probe_false_for_a_corrupt_stamp(tmp_path: Path, content: str) -> None:
    """Corrupt or malformed JSON reads False and never raises (pid 0 must not probe a process group)."""
    (tmp_path / handoff_files.compose_stamp_name("abcd1234")).write_text(content, encoding="utf-8")
    assert handoff_files.compose_inflight(tmp_path, "abcd1234") is False


def test_probe_is_per_session(tmp_path: Path) -> None:
    """Another session's live stamp does not count, and an empty key never matches anything."""
    _write_stamp(tmp_path, "aaaaaaaa", os.getpid(), time.time())
    assert handoff_files.compose_inflight(tmp_path, "aaaaaaaa") is True
    assert handoff_files.compose_inflight(tmp_path, "bbbbbbbb") is False
    assert handoff_files.compose_inflight(tmp_path, "") is False


def test_key_from_the_transcript_matches_the_composers_own_key(
    project: Path, composer: tuple[subprocess.Popen, str]
) -> None:
    """The clear side keys by `session_key(transcript)`, the composer by its session-id env: same key."""
    _proc, session_id = composer
    sd = project / ".janitor" / "state"
    transcript = project / f"{session_id}.jsonl"
    key = handoff_files.session_key(transcript)
    assert (sd / handoff_files.compose_stamp_name(key)).is_file()
    assert handoff_files.compose_inflight(sd, key) is True



def test_unset_session_env_files_the_stamp_under_unkeyed_so_the_clear_side_cannot_match(
    project: Path,
) -> None:
    """KNOWN LIMIT, pinned: with CLAUDE_CODE_SESSION_ID unset the composer falls back to the
    `unkeyed` key (the one its handoff file uses), which no transcript path yields, so a clear
    keyed by the transcript is not held. Claude Code always sets the variable inside a session."""
    sd = project / ".janitor" / "state"
    sd.mkdir(parents=True)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CODE_SESSION_ID"}
    proc = subprocess.Popen(
        [sys.executable, "-c", _COMPOSER, str(sd)], stdout=subprocess.PIPE, text=True, env=env
    )
    try:
        assert proc.stdout is not None
        assert proc.stdout.readline().strip() == "stamped"
        assert handoff_files.compose_inflight(sd, handoff_files.UNKEYED_KEY) is True
        clear_side_key = handoff_files.session_key(project / f"{uuid.uuid4()}.jsonl")
        assert handoff_files.compose_inflight(sd, clear_side_key) is False
    finally:
        proc.kill()
        proc.wait(timeout=5)


def _run_maybe_clear(project: Path, transcript: Path) -> tuple[list[str], list[dict]]:
    """Drive the REAL `_maybe_clear`; return (token-meter log lines it wrote, `_spawn_chain` calls)."""
    forks: list[dict] = []
    original = clear_trigger._spawn_chain
    clear_trigger._spawn_chain = lambda payload, *, env=None: forks.append(payload)  # type: ignore[assignment]
    try:
        _import_meter_hook()._maybe_clear(str(project), str(transcript), state, token_meter)
    finally:
        clear_trigger._spawn_chain = original  # type: ignore[assignment]
    log = state.log_dir() / "token-meter.log"
    return (log.read_text(encoding="utf-8").splitlines() if log.is_file() else []), forks


def _transcript(project: Path, session_id: str) -> Path:
    path = project / f"{session_id}.jsonl"
    path.write_text(
        json.dumps(
            {"type": "assistant", "message": {"usage": {"input_tokens": _TOKENS_BELOW_CEILING}}}
        )
        + "\n",
        encoding="utf-8",
    )
    return path


def test_maybe_clear_defers_while_this_session_composes(
    project: Path, composer: tuple[subprocess.Popen, str]
) -> None:
    """With the stamp live, `_maybe_clear` logs the deferral and the clear chain is never spawned."""
    _proc, session_id = composer
    lines, forks = _run_maybe_clear(project, _transcript(project, session_id))
    assert any("clear deferred: handoff compose running, 86% < ceiling 92%" in ln for ln in lines), lines
    assert not any("clear at" in ln for ln in lines), lines
    assert forks == []



def test_maybe_clear_refires_once_the_compose_has_finished(
    project: Path, composer: tuple[subprocess.Popen, str]
) -> None:
    """Deferred while the composer lives; the NEXT `_maybe_clear` (next Stop) spawns the chain once
    it has exited -- the re-fire the comments at the decision sites rely on, at the hook level."""
    proc, session_id = composer
    transcript = _transcript(project, session_id)
    _lines, forks = _run_maybe_clear(project, transcript)
    assert forks == []
    proc.kill()
    proc.wait(timeout=5)
    lines, forks = _run_maybe_clear(project, transcript)
    assert len(forks) == 1, lines


def test_maybe_clear_control_without_a_stamp_reaches_the_clear_path(project: Path) -> None:
    """Same setup, no stamp: the chain IS spawned, so the deferral above is what stopped it."""
    lines, forks = _run_maybe_clear(project, _transcript(project, str(uuid.uuid4())))
    assert not any("handoff compose running" in ln for ln in lines), lines
    assert any("clear at 86%" in ln and "spawned" in ln for ln in lines), lines
    assert len(forks) == 1


def test_maybe_clear_ignores_another_sessions_compose(
    project: Path, composer: tuple[subprocess.Popen, str]
) -> None:
    """A compose running in a different session (same state dir) must not hold THIS session's clear."""
    lines, forks = _run_maybe_clear(project, _transcript(project, str(uuid.uuid4())))
    assert not any("handoff compose running" in ln for ln in lines), lines
    assert len(forks) == 1


def test_chain_cancels_while_this_session_composes_and_not_otherwise(
    project: Path, monkeypatch: pytest.MonkeyPatch, composer: tuple[subprocess.Popen, str]
) -> None:
    """`_agents_and_interrupt_ok` (via `_still_wanted`) cancels on a live stamp of THIS session only."""
    _proc, session_id = composer
    mod = _import()
    captured = _capture_still_wanted(mod, monkeypatch)
    _no_agents_no_interrupt(monkeypatch)

    def _ask(transcript: Path) -> tuple[bool, str]:
        payload = _chain_payload_with_transcript(
            project, transcript=str(transcript), terminal={"kind": "tmux"}
        )
        mod._run_chain_payload(payload)
        return captured["still_wanted"]()

    ok, why = _ask(project / f"{session_id}.jsonl")
    assert ok is False
    assert why == "handoff compose running"

    ok, why = _ask(project / f"{uuid.uuid4()}.jsonl")
    assert ok is True, why
