"""Real-bun run of the secrets-shield vault tests (TRDD-BAQB9SYO increment 3, step 3a-1).

No mock: the TypeScript suite `scripts/shield_scan/tests/vault.test.ts` runs under the real `bun test`, against a real
SQLite file under the system temp folder and the real vault CLI in child processes. This file only starts it and reads
its verdict, so the Python suite fails when the vault suite fails (or silently runs nothing).
"""

from __future__ import annotations

import os
import pwd
import re
import subprocess
from pathlib import Path

import pytest
import transcript_redact as tr

# The suite denies every real binary by default (tests/sandbox_guard.py); this file exists to run the REAL bun, so it opts in.
pytestmark = pytest.mark.real_subprocess("bun")

_SHIELD_SCAN = Path(__file__).resolve().parents[1] / "scripts" / "shield_scan"
_TEST_FILE = _SHIELD_SCAN / "tests" / "vault.test.ts"
_TIMEOUT_S = 180.0
# The number of tests in vault.test.ts: a run that reports fewer passes ran less than the suite.
_EXPECTED_TESTS = 20


def test_vault_bun_suite_passes() -> None:
    """`bun test` over vault.test.ts exits 0, reports no failure and all of its tests passing."""
    env = dict(os.environ)
    # WHY these two: the suite must run on a temp vault only (the setting is set per test inside it, so an inherited one is dropped),
    # and it needs an oracle for the account's real home that does not come from the vault code. conftest points HOME at a fake folder,
    # so the oracle is the OS account record, read here by Python.
    env.pop("SECRETS_SHIELD_VAULT_DIR", None)
    env["SHIELD_TEST_ACCOUNT_HOME"] = pwd.getpwuid(os.getuid()).pw_dir
    done = subprocess.run(
        [tr.resolve_bun(), "test", str(_TEST_FILE)],
        cwd=_SHIELD_SCAN,
        capture_output=True,
        text=True,
        timeout=_TIMEOUT_S,
        env=env,
        check=False,
    )
    report = done.stdout + done.stderr  # bun test prints its summary on stderr
    assert done.returncode == 0, report
    passed = re.search(r"^\s*(\d+) pass$", report, re.MULTILINE)
    failed = re.search(r"^\s*(\d+) fail$", report, re.MULTILINE)
    assert passed is not None and failed is not None, report
    assert int(failed.group(1)) == 0, report
    assert int(passed.group(1)) >= _EXPECTED_TESTS, report
