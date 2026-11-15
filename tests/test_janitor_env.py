"""Tests for scripts/janitor_env.py (janitor issue #354): print a process environment with every value hidden
except the names the caller allows, and never a secret-named one."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))

import janitor_env  # noqa: E402

_HELPER = _ROOT / "scripts" / "janitor_env.py"


def test_render_shows_only_allowed_names_and_hides_secret_named_ones_even_when_allowed() -> None:
    """An allowed name prints its value; an unlisted name prints its length; a secret-named one stays hidden even if a pattern lists it."""
    secret = secrets.token_urlsafe(30)
    entries = [b"PYTHON_MARK=visible-marker", b"OTHER_VAR=abc", b"FAKE_API_TOKEN=" + secret.encode(), b"GH_PAT=" + secret.encode()]
    lines = janitor_env.render(entries, ["PYTHON*", "FAKE_*", "GH_*"])
    assert "PYTHON_MARK=visible-marker" in lines
    assert "OTHER_VAR=<hidden, 3 characters>" in lines
    assert f"FAKE_API_TOKEN=<hidden, {len(secret)} characters>" in lines
    assert f"GH_PAT=<hidden, {len(secret)} characters>" in lines
    assert secret not in "\n".join(lines)


def test_reads_the_environment_of_a_running_child_in_memory() -> None:
    """The helper, run as a program, reads another process's real environment and prints the allowed names only."""
    secret = secrets.token_urlsafe(30)
    env = {"PATH": os.environ.get("PATH", ""), "PYTHON_MARK": "visible-marker", "FAKE_API_TOKEN_0000": secret}
    child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], env=env, stdout=subprocess.DEVNULL)
    try:
        time.sleep(0.5)
        if not janitor_env.read_environment(child.pid):
            pytest.skip("this system hides the environment of this interpreter (a system-signed binary)")
        done = subprocess.run(
            [sys.executable, str(_HELPER), "--pid", str(child.pid), "--allow", "PYTHON*,FAKE_*"],
            capture_output=True, text=True, timeout=30, check=False,
        )
    finally:
        child.terminate()
        child.wait()
    assert done.returncode == 0
    assert "PYTHON_MARK=visible-marker" in done.stdout.splitlines()
    assert f"FAKE_API_TOKEN_0000=<hidden, {len(secret)} characters>" in done.stdout.splitlines()
    assert secret not in done.stdout and secret not in done.stderr


def test_a_pid_that_does_not_exist_is_an_error_not_an_empty_listing() -> None:
    """Fail loud: a process the system cannot report exits 1 with a message on stderr."""
    done = subprocess.run([sys.executable, str(_HELPER), "--pid", "2147483646"], capture_output=True, text=True, timeout=30, check=False)
    assert done.returncode == 1
    assert "cannot read the environment" in done.stderr



# Review leads of 2026-11-15 (outside-model review of the code drop; each failure below was reproduced first).
@pytest.mark.parametrize("buffer", [b"", b"\x01\x00", b"\x02\x00\x00\x00/bin/x", b"\x05\x00\x00\x00/bin/x\x00\x00a\x00b\x00"])
def test_a_short_or_unterminated_process_buffer_is_a_clean_error(buffer: bytes) -> None:
    """A process that exits between the two sysctl calls, or rewrites its argv area (nginx, redis), gives a buffer
    the parser must refuse with an OSError that main() reports, not a struct.error or ValueError traceback."""
    with pytest.raises(OSError):
        janitor_env.parse_procargs2(buffer)


def test_a_value_with_credentials_in_it_stays_hidden_even_when_its_name_is_allowed() -> None:
    """DATABASE_URL is not secret-named, yet a user and password before the @ of its URL is a password, and that part is hidden."""
    entries = [b"DATABASE_URL=postgres://admin:" + b"hunter2hunter2" + b"@db.internal:5432/app", b"HOME_URL=https://example.com/a@b", b"MARK=ok"]
    lines = janitor_env.render(entries, ["*"])
    assert "DATABASE_URL=<hidden, 52 characters>" in lines
    assert "HOME_URL=https://example.com/a@b" in lines and "MARK=ok" in lines
    assert "hunter2" not in "\n".join(lines)
    slash = janitor_env.render([b"REDIS_URL=redis://u:" + b"pa/ss-word" + b"@cache:6379/0"], ["*"])
    assert slash == ["REDIS_URL=<hidden, 33 characters>"]
