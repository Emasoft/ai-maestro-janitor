"""Real-bun run of the secrets-shield JSONL planner tests (TRDD-BAQB9SYO increment 3, step 3b-2b part A).

No mock: the TypeScript suite `scripts/shield_scan/tests/jsonl.test.ts` runs under the real `bun test`, against the pure
planner `scripts/shield_scan/jsonl.ts`. This file only starts it and reads its verdict, so the Python suite fails when the
JSONL suite fails (or silently runs nothing).
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

import pytest
import transcript_redact as tr

# The suite denies every real binary by default (tests/sandbox_guard.py); this file exists to run the REAL bun, so it opts in.
pytestmark = pytest.mark.real_subprocess("bun")

_SHIELD_SCAN = Path(__file__).resolve().parents[1] / "scripts" / "shield_scan"
_TEST_FILE = _SHIELD_SCAN / "tests" / "jsonl.test.ts"
_TIMEOUT_S = 180.0
# The number of tests in jsonl.test.ts: a run that reports fewer passes ran less than the suite.
_EXPECTED_TESTS = 5


def test_jsonl_bun_suite_passes() -> None:
    """`bun test` over jsonl.test.ts exits 0, reports no failure and all of its tests passing."""
    # WHY the variable is dropped: the planner suite needs no vault and must never see one the caller exported.
    env = dict(os.environ)
    env.pop("SECRETS_SHIELD_VAULT_DIR", None)
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
