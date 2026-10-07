"""HOOK-003 (TRDD-QXG8SRVD): the autorecall hook records a finding when its own limit trips."""

from __future__ import annotations

import importlib.util
import json
import stat
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))


def _load_hook():
    spec = importlib.util.spec_from_file_location(
        "autorecall_hook", _ROOT / "scripts" / "hooks" / "on-prompt-submit-autorecall.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _records(project: Path) -> list[dict]:
    ledger = project / ".janitor" / "state" / "findings-ledger.ndjsonl"
    if not ledger.is_file():
        return []
    return [json.loads(ln) for ln in ledger.read_text().splitlines() if ln.strip()]


def _slow_memgrep(tmp_path: Path) -> str:
    script = tmp_path / "memgrep"
    script.write_text("#!/bin/sh\nsleep 5\n")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


def test_forced_limit_records_exactly_one_hook_003(tmp_path: Path, monkeypatch) -> None:
    """A recall that outlives the 0.01 s limit yields one HOOK-003 record and an empty result."""
    hook = _load_hook()
    project = tmp_path / "proj"
    project.mkdir()
    monkeypatch.setattr(hook, "_TIMEOUT_S", 0.01)

    out = hook._recall(_slow_memgrep(tmp_path), "some long enough query", ["/x.md"], str(project))

    assert out == ""
    recs = _records(project)
    assert [r["code"] for r in recs] == ["HOOK-003"]


def test_fast_recall_records_nothing(tmp_path: Path) -> None:
    """A recall that finishes inside the limit leaves the ledger empty."""
    hook = _load_hook()
    project = tmp_path / "proj"
    project.mkdir()
    fast = tmp_path / "memgrep"
    fast.write_text("#!/bin/sh\nexit 0\n")
    fast.chmod(fast.stat().st_mode | stat.S_IXUSR)

    hook._recall(str(fast), "some long enough query", ["/x.md"], str(project))

    assert _records(project) == []
