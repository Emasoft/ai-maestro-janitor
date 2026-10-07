"""Tests for the hook-timeout-scan detector (TRDD-QX59MA4H): HOOK-001 and HOOK-002.

Real files in tmp_path, real subprocess runs of the detector, no mocks. Every fixture is
synthetic: made-up session ids, hook names and paths.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_DETECTOR = Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "hook-timeout-scan.py"
_SESSION = "11111111-2222-3333-4444-555555555555"
_OWN_CMD = "bash ${CLAUDE_PLUGIN_ROOT}/hooks/hook-run.sh ${CLAUDE_PLUGIN_ROOT}/scripts/hooks/fake-hook.py"
_OTHER_CMD = "bash ${CLAUDE_PLUGIN_ROOT}/scripts/hooks/someone-elses.py"


class _Env:
    def __init__(self, tmp: Path) -> None:
        self.fakehome = tmp / "home"
        self.project = tmp / "proj"
        self.plugin = tmp / "plugin"
        self.project.mkdir()
        (self.plugin / "hooks").mkdir(parents=True)
        # fake-hook.py has a 10 s budget in this synthetic plugin; nothing else is configured.
        (self.plugin / "hooks" / "hooks.json").write_text(
            json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": _OWN_CMD, "timeout": 10}]}]}}),
            encoding="utf-8",
        )
        slug = re.sub(r"[^A-Za-z0-9]", "-", str(self.project))
        self.tdir = self.fakehome / ".claude" / "projects" / slug
        self.tdir.mkdir(parents=True)

    def transcript(self, name: str = _SESSION) -> Path:
        return self.tdir / f"{name}.jsonl"

    def run(self) -> str:
        env = dict(os.environ)
        env.update(
            HOME=str(self.fakehome),
            CLAUDE_PROJECT_DIR=str(self.project),
            CLAUDE_SESSION_ID="hooktimeoutsess",
            CLAUDE_PLUGIN_ROOT=str(self.plugin),
        )
        res = subprocess.run([sys.executable, str(_DETECTOR)], capture_output=True, text=True, env=env, timeout=60)
        assert res.returncode == 0, f"detector exited {res.returncode}; stderr:\n{res.stderr}"
        return res.stdout

    def ledger_path(self) -> Path:
        return self.project / ".janitor" / "state" / "findings-ledger.ndjsonl"

    def codes(self) -> list[str]:
        p = self.ledger_path()
        if not p.exists():
            return []
        return [json.loads(ln)["code"] for ln in p.read_text(encoding="utf-8").splitlines() if ln.strip()]


def _rec(att_type: str, *, session: str = _SESSION, ts: str | None = None, **att: object) -> str:
    ts = ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    body = {"type": att_type, "hookName": "Stop", "hookEvent": "Stop", "command": _OWN_CMD, **att}
    return json.dumps({"type": "attachment", "sessionId": session, "timestamp": ts, "attachment": body})


def _cancelled(session: str = _SESSION) -> str:
    return _rec("hook_cancelled", session=session, timedOut=True, durationMs=10000, timeoutMs=10000)


def _write(path: Path, *lines: str) -> None:
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_one_timed_out_record_gives_exactly_one_hook_001(tmp_path: Path) -> None:
    """A hook_cancelled/timedOut=true record yields one HOOK-001."""
    e = _Env(tmp_path)
    _write(e.transcript(), _cancelled())
    e.run()
    assert e.codes().count("HOOK-001") == 1


def test_same_session_and_hook_twice_still_one_hook_001(tmp_path: Path) -> None:
    """Two timeouts of the same (session, hookName) collapse to one HOOK-001."""
    e = _Env(tmp_path)
    _write(e.transcript(), _cancelled(), _cancelled())
    e.run()
    assert e.codes().count("HOOK-001") == 1


def test_second_run_over_same_transcript_emits_nothing_new(tmp_path: Path) -> None:
    """A re-run must not re-record HOOK-001 (seen-set persisted in the project state dir)."""
    e = _Env(tmp_path)
    _write(e.transcript(), _cancelled())
    e.run()
    e.run()
    assert e.codes().count("HOOK-001") == 1


def test_timed_out_after_text_is_not_a_signal(tmp_path: Path) -> None:
    """The phrase 'timed out after' in a non-hook line must not produce HOOK-001."""
    e = _Env(tmp_path)
    _write(
        e.transcript(),
        json.dumps({"type": "user", "sessionId": _SESSION, "message": {"content": "request timed out after 30s"}}),
        _rec("hook_cancelled", timedOut=False, durationMs=100, timeoutMs=10000),
    )
    e.run()
    assert "HOOK-001" not in e.codes()


def test_hook_002_fires_at_80_percent_of_configured_timeout(tmp_path: Path) -> None:
    """hook_success at 8000 of a configured 10000 ms budget gives HOOK-002."""
    e = _Env(tmp_path)
    _write(e.transcript(), _rec("hook_success", durationMs=8000))
    e.run()
    assert e.codes().count("HOOK-002") == 1


def test_hook_002_does_not_fire_at_79_percent(tmp_path: Path) -> None:
    """7900 of 10000 ms is below the 80% threshold."""
    e = _Env(tmp_path)
    _write(e.transcript(), _rec("hook_success", durationMs=7900))
    e.run()
    assert "HOOK-002" not in e.codes()


def test_hook_002_uses_the_records_own_timeout_when_present(tmp_path: Path) -> None:
    """A hook_cancelled record carries timeoutMs; 4000 of 5000 ms fires though hooks.json says 10 s."""
    e = _Env(tmp_path)
    _write(e.transcript(), _rec("hook_cancelled", timedOut=False, durationMs=4000, timeoutMs=5000))
    e.run()
    assert e.codes().count("HOOK-002") == 1


def test_hook_002_skips_unknown_timeout(tmp_path: Path) -> None:
    """A janitor-style command absent from hooks.json, with no timeoutMs, is skipped."""
    e = _Env(tmp_path)
    cmd = "bash ${CLAUDE_PLUGIN_ROOT}/hooks/hook-run.sh ${CLAUDE_PLUGIN_ROOT}/scripts/hooks/unconfigured.py"
    _write(e.transcript(), _rec("hook_success", command=cmd, durationMs=999999))
    e.run()
    assert "HOOK-002" not in e.codes()


def test_hook_002_skips_non_janitor_hook(tmp_path: Path) -> None:
    """Another plugin's slow hook is not ours: no HOOK-002 even with a timeoutMs on the record."""
    e = _Env(tmp_path)
    _write(e.transcript(), _rec("hook_cancelled", command=_OTHER_CMD, timedOut=False, durationMs=9000, timeoutMs=10000))
    e.run()
    assert "HOOK-002" not in e.codes()


def test_hook_002_same_command_twice_in_one_hour_gives_one(tmp_path: Path) -> None:
    """Dedupe is one HOOK-002 per (command, hour)."""
    e = _Env(tmp_path)
    ts = datetime.fromtimestamp(int(time.time()) // 3600 * 3600 + 5, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    _write(e.transcript(), _rec("hook_success", durationMs=9000, ts=ts), _rec("hook_success", durationMs=9500, ts=ts))
    e.run()
    assert e.codes().count("HOOK-002") == 1


def test_invalid_utf8_byte_and_torn_last_line_do_not_crash(tmp_path: Path) -> None:
    """A 0xFF byte inside a line and a half-written final line are skipped, valid lines still count."""
    e = _Env(tmp_path)
    good = _cancelled().encode("utf-8")
    e.transcript().write_bytes(b"\xff\xfe garbage line\n" + good + b"\n" + good[: len(good) // 2])
    e.run()
    assert e.codes().count("HOOK-001") == 1



def test_valid_json_non_object_lines_do_not_crash(tmp_path: Path) -> None:
    """A JSON string, list and number that mention hook_ are skipped, the real record still counts."""
    e = _Env(tmp_path)
    _write(
        e.transcript(),
        json.dumps("mentions \"hook_cancelled\""),
        json.dumps(["hook_cancelled"]),
        "12345 \"hook_\"",
        json.dumps(7),
        _cancelled(),
    )
    e.run()
    assert e.codes().count("HOOK-001") == 1



def test_timed_out_record_gives_hook_001_only_not_hook_002(tmp_path: Path) -> None:
    """A janitor hook killed at its full budget is one HOOK-001, never also a HOOK-002."""
    e = _Env(tmp_path)
    _write(e.transcript(), _cancelled())
    e.run()
    assert e.codes() == ["HOOK-001"]


def test_flood_prints_five_lines_plus_summary_but_records_all(tmp_path: Path) -> None:
    """8 distinct findings: all 8 recorded, 5 printed plus one summary line, a rerun prints nothing."""
    e = _Env(tmp_path)
    _write(e.transcript(), *(_cancelled(session=f"sess-{i}") for i in range(8)))
    out = e.run().splitlines()
    assert len(out) == 6
    assert out[5] == "hook-timeout-scan: 3 more recorded, see /janitor-findings"
    assert e.codes().count("HOOK-001") == 8
    assert e.run() == ""


def test_missing_timeout_ms_says_timeout_unknown_not_none(tmp_path: Path) -> None:
    """A timed-out hook_cancelled with no timeoutMs reports an unknown timeout, never the text None."""
    e = _Env(tmp_path)
    _write(e.transcript(), _rec("hook_cancelled", timedOut=True))
    out = e.run()
    assert "HOOK-001" in out
    assert "None" not in out
    assert "timeout unknown" in out


def test_findings_never_name_a_home_or_transcript_path(tmp_path: Path) -> None:
    """Ledger and stdout carry the hook name and session id only, never a filesystem path."""
    e = _Env(tmp_path)
    _write(e.transcript(), _cancelled())
    out = e.run()
    ledger = e.ledger_path().read_text(encoding="utf-8")
    for text in (out, ledger):
        assert str(tmp_path) not in text
        assert ".jsonl" not in text


def test_other_projects_transcripts_are_not_scanned(tmp_path: Path) -> None:
    """Only the current project's slug folder is read."""
    e = _Env(tmp_path)
    other = e.fakehome / ".claude" / "projects" / "some-other-project"
    other.mkdir(parents=True)
    _write(other / "zzz.jsonl", _cancelled(session="zzz"))
    e.run()
    assert "HOOK-001" not in e.codes()


def test_a_high_finding_is_never_pushed_out_of_the_print_cap_by_medium_ones(tmp_path: Path) -> None:
    """Six HOOK-002 in an earlier transcript and one HOOK-001 in a later one: the HOOK-001 line is printed."""
    e = _Env(tmp_path)
    base = int(time.time()) // 3600 * 3600
    medium = [
        _rec(
            "hook_success",
            durationMs=9000,
            ts=datetime.fromtimestamp(base - 3600 * i, timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        )
        for i in range(6)
    ]
    _write(e.transcript("aaa-early"), *medium)
    _write(e.transcript("zzz-late"), _cancelled(session="zzz-late"))
    out = e.run().splitlines()
    assert any("HOOK-001" in ln for ln in out), out
