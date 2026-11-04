"""tests/conftest.py must scrub host CLAUDE_PLUGIN_OPTION_* vars before any test runs (TRDD-90LAMQ8B)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_host_plugin_option_env_does_not_leak_into_a_test_run() -> None:
    """A host CLAUDE_PLUGIN_OPTION_IDLE_CLEAR_ENABLED=false must not break a default-assuming test.

    TRDD-90LAMQ8B: the host Claude Code session carries CLAUDE_PLUGIN_OPTION_* from the `env` block
    of ~/.claude/settings.json, and `state.plugin_option` lets an env var win over the code default,
    so five idle-clear tests failed on the owner's machine and passed on CI. This runs a real nested pytest, with the
    host value present in its environment, against one of those tests; it passes only while
    conftest drops the host value before the test body runs. The nested run is a real child
    process, not a mock, because the leak lives in process-start environment handling.
    """
    env = dict(os.environ)
    env["CLAUDE_PLUGIN_OPTION_IDLE_CLEAR_ENABLED"] = "false"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/test_dispatch_phases.py",
            "-k",
            "test_idle_clear_still_fires_on_a_big_context",
            "-p",
            "no:cacheprovider",
            "-q",
        ],
        cwd=_PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        # A hung child must fail this test, not hang the suite (host load reaches 40-130).
        timeout=600,
    )
    assert result.returncode == 0, result.stdout + result.stderr
