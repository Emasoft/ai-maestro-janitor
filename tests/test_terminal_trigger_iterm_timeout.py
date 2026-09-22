"""iTerm osascript-timeout retry (jev-compaction-spec CARD 1 item 4).

The owner measured 92 iTerm injection failures/week, all osascript timeouts at 15s, during
system load — traced to `read_pane_text`'s iTerm branch walking every window/tab/session on
every read. On a timeout, `_read_iterm_pane_text` must (a) log the 1-minute load average and
the timeout value, and (b) retry ONCE against a script that targets the session directly
(no `repeat with w in windows`), never a second retry.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import terminal_trigger as tt  # noqa: E402

_SID = "4C4A9B7A-1111-2222-3333-444455556666"


def _proc(stdout: str, returncode: int = 0) -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(args=["osascript"], returncode=returncode, stdout=stdout, stderr="")


def test_a_clean_read_never_logs_or_retries(monkeypatch) -> None:
    """No timeout -> one osascript call, no failure record."""
    calls: list[str] = []
    logged: list[str] = []
    monkeypatch.setattr(tt, "_run_osascript", lambda script, *, timeout: (calls.append(script), _proc("hello"))[1])
    monkeypatch.setattr(tt.state, "log_line", lambda _name, msg: logged.append(msg))
    assert tt._read_iterm_pane_text(_SID) == "hello"
    assert len(calls) == 1
    assert logged == []


def test_timeout_logs_the_load_average_and_the_timeout_value(monkeypatch) -> None:
    """Requirement (a): the failure record carries `os.getloadavg()[0]` and the timeout used."""
    logged: list[str] = []

    def fake_run(script: str, *, timeout: float) -> subprocess.CompletedProcess[str]:
        if "repeat with w in windows" in script:
            raise subprocess.TimeoutExpired(cmd="osascript", timeout=timeout)
        return _proc("recovered")

    monkeypatch.setattr(tt, "_run_osascript", fake_run)
    monkeypatch.setattr(tt.state, "log_line", lambda _name, msg: logged.append(msg))
    monkeypatch.setattr(tt.os, "getloadavg", lambda: (7.5, 6.0, 5.0))

    tt._read_iterm_pane_text(_SID)

    assert len(logged) == 1
    assert "load1=7.50" in logged[0]
    assert f"{tt._ITERM_READ_TIMEOUT_S:.0f}s" in logged[0]


def test_timeout_retries_exactly_once_targeting_the_session_directly(monkeypatch) -> None:
    """Requirement (b): after a timeout, retry ONCE (not twice, not zero) with a script that
    targets `sid` directly and contains no window enumeration."""
    scripts: list[str] = []

    def fake_run(script: str, *, timeout: float) -> subprocess.CompletedProcess[str]:
        scripts.append(script)
        if "repeat with w in windows" in script:
            raise subprocess.TimeoutExpired(cmd="osascript", timeout=timeout)
        return _proc("direct-hit")

    monkeypatch.setattr(tt, "_run_osascript", fake_run)
    monkeypatch.setattr(tt.state, "log_line", lambda *a, **k: None)
    monkeypatch.setattr(tt.os, "getloadavg", lambda: (1.0, 1.0, 1.0))

    result = tt._read_iterm_pane_text(_SID)

    assert result == "direct-hit"
    assert len(scripts) == 2, "must retry exactly once, not spin"
    assert "repeat with w in windows" not in scripts[1]
    assert _SID in scripts[1]


def test_a_second_timeout_gives_up_without_a_third_call(monkeypatch) -> None:
    """The retry is BOUNDED: if the direct-target script also times out, give up (None) —
    never a second retry, or a wedged iTerm would double every caller's wait forever."""
    calls = {"n": 0}
    logged: list[str] = []

    def fake_run(script: str, *, timeout: float) -> subprocess.CompletedProcess[str]:
        calls["n"] += 1
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=timeout)

    monkeypatch.setattr(tt, "_run_osascript", fake_run)
    monkeypatch.setattr(tt.state, "log_line", lambda _name, msg: logged.append(msg))
    monkeypatch.setattr(tt.os, "getloadavg", lambda: (9.9, 9.0, 8.0))

    assert tt._read_iterm_pane_text(_SID) is None
    assert calls["n"] == 2
    assert len(logged) == 2, "one record for each timeout, no more"


def test_the_direct_script_never_enumerates_windows() -> None:
    """`_iterm_direct_session_script` is the non-enumerating form on its own terms, not just
    as observed through the retry — no `repeat with w in windows` and the session id present."""
    script = tt._iterm_direct_session_script(_SID, ["            return contents"])
    assert "repeat with w in windows" not in script
    assert "repeat" not in script
    assert _SID in script
