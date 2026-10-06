"""janitor#326 item 3: the heartbeat detector must not leak memgrep's unconditional
`memgrep lint: N finding(s), none at or above ERROR (...)` summary onto the heartbeat's stderr.

Real memgrep on a real (empty) temp scope root; skipped only when the binary is absent.
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import wikimem_syntax_lint as lint  # noqa: E402

pytestmark = pytest.mark.skipif(shutil.which("memgrep") is None, reason="memgrep binary not on PATH")


def test_run_lint_echoes_the_memgrep_summary_by_default(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    lint.run_lint([tmp_path])
    assert "memgrep lint:" in capsys.readouterr().err


def test_run_lint_with_echo_off_keeps_the_summary_off_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, _out, findings = lint.run_lint([tmp_path], echo_stderr=False)
    assert code == 0 and findings == []
    assert capsys.readouterr().err == ""
