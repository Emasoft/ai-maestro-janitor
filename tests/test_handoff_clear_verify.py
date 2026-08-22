"""Tests for the cross-/clear verification harness (scripts/handoff_clear_verify.py).

The pure decision layer (extract_wikilinks / compute_verdicts / render_report) is
tested directly; the two phases are tested via real subprocess runs against an
isolated tmp project, so no real /clear, cron, or memory store is touched.
"""

from __future__ import annotations

import importlib.util as _u
import json
import os
import subprocess
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "handoff_clear_verify.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _import():
    spec = _u.spec_from_file_location("handoff_clear_verify_under_test", str(_SCRIPT))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run(args: list[str], *, project: Path) -> subprocess.CompletedProcess:
    env = {
        "PATH": os.environ.get("PATH", ""),
        "CLAUDE_PROJECT_DIR": str(project),
        # Skip the external agentlensPro probe in tests — the transcript fallback (None
        # in a tmp project) is deterministic.
        "CLAUDE_PLUGIN_OPTION_HANDOFF_VERIFY_CONTEXT_COMMAND": "",
    }
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def _state_dir(project: Path) -> Path:
    return project / ".janitor" / "state"


# ---------- pure helpers ---------------------------------------------------


def test_extract_wikilinks_targets_dedupe_and_strip() -> None:
    mod = _import()
    text = (
        "see [[oauth-rotator-burn]] and [[oauth-rotator-burn|the rotator]] "
        "and [[continuity-engineering#section]] — but not a stray [[ open bracket\n"
    )
    links = mod.extract_wikilinks(text)
    assert links == ["oauth-rotator-burn", "continuity-engineering"], links


def test_compute_verdicts_all_pass() -> None:
    mod = _import()
    before = {
        "ts": 1000,
        "cron_id": "oldid",
        "context_tokens": 400000,
        "handoff_links": ["page-a", "page-b"],
        "resume_flag_present": True,
    }
    after = {
        "ts": 1100,
        "cron_id": "newid",
        "context_tokens": 40000,
        "resume_flag_present": False,
        "armed_at_ts": 1050,
        "links_resolved": {"page-a": True, "page-b": True},
    }
    v = mod.compute_verdicts(before, after)
    assert {k: x["status"] for k, x in v.items()} == {
        "cron_recreated": "PASS",
        "context_collapsed": "PASS",
        "handoff_links_resolve": "PASS",
        "resume_flag_consumed": "PASS",
        "session_restarted": "PASS",
    }


def test_compute_verdicts_flags_failures() -> None:
    mod = _import()
    before = {
        "ts": 1000,
        "cron_id": "beforeid",
        "context_tokens": 400000,
        "handoff_links": ["page-a"],
        "resume_flag_present": True,
    }
    after = {
        "ts": 1100,
        "cron_id": "",  # gone after /clear, and no re-arm observed → genuinely broken
        "context_tokens": 390000,  # did not collapse
        "resume_flag_present": True,  # not consumed
        "armed_at_ts": 500,  # predates the snapshot
        "links_resolved": {"page-a": False},  # unresolved
    }
    v = mod.compute_verdicts(before, after)
    assert v["cron_recreated"]["status"] == "FAIL"
    assert v["context_collapsed"]["status"] == "FAIL"
    assert v["handoff_links_resolve"]["status"] == "FAIL"
    assert v["resume_flag_consumed"]["status"] == "FAIL"
    assert v["session_restarted"]["status"] == "FAIL"


def test_compute_verdicts_cron_survived_unchanged_is_healthy_not_a_failure() -> None:
    """#186 regression: /clear does not always destroy the session cron (SessionStart's
    re-arm is CONDITIONAL — "if it is missing" — so a cron that never went missing is
    correctly never re-armed). A prior version of this harness asserted destruction +
    recreation UNCONDITIONALLY and reported FAIL on a real, healthy machine where the
    cron simply survived `/clear` with the SAME id — the false assumption was the
    harness's, not the primitive's. Both the cron check and the dependent re-arm check
    must read this as healthy (PASS / SKIP), never FAIL."""
    mod = _import()
    before = {
        "ts": 1000,
        "cron_id": "4deceffa",
        "context_tokens": 400000,
        "handoff_links": [],
        "resume_flag_present": False,
    }
    after = {
        "ts": 1100,
        "cron_id": "4deceffa",  # UNCHANGED — this build's /clear does not drop the cron
        "context_tokens": 40000,
        "resume_flag_present": False,
        "armed_at_ts": 500,  # predates the snapshot — no fresh re-arm, because none was needed
        "links_resolved": {},
    }
    v = mod.compute_verdicts(before, after)
    assert v["cron_recreated"]["status"] == "PASS", v["cron_recreated"]
    assert v["session_restarted"]["status"] == "SKIP", v["session_restarted"]


def test_compute_verdicts_skips_on_missing_signals() -> None:
    """Missing data → SKIP, never a manufactured FAIL (fail-open diagnostic)."""
    mod = _import()
    before = {"ts": 1000, "cron_id": "", "context_tokens": None, "handoff_links": [], "resume_flag_present": False}
    after = {"ts": 1100, "cron_id": "", "context_tokens": None, "resume_flag_present": False, "armed_at_ts": 0, "links_resolved": {}}
    v = mod.compute_verdicts(before, after)
    assert all(x["status"] == "SKIP" for x in v.values()), v


def test_render_report_has_table_and_snapshots() -> None:
    mod = _import()
    before = {"ts": 1000, "cron_id": "oldid", "context_tokens": 400000, "handoff_links": ["p"], "resume_flag_present": True}
    after = {"ts": 1100, "cron_id": "newid", "context_tokens": 40000, "resume_flag_present": False, "armed_at_ts": 1050, "links_resolved": {"p": True}}
    report = mod.render_report(before, after, mod.compute_verdicts(before, after))
    assert "cross-/clear verification" in report
    assert "| # | assumption | result | detail |" in report
    assert "PASS" in report
    assert "before snapshot" in report and "after snapshot" in report


# ---------- phases via subprocess -----------------------------------------


def test_phase_before_writes_snapshot(tmp_path: Path) -> None:
    """--phase before records the cron id + handoff links into the survive-/clear JSON."""
    p = tmp_path / "proj"
    sd = _state_dir(p)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "heartbeat-cron-id.txt").write_text("cron-abc", encoding="utf-8")
    (sd / "agent-handoff.md").write_text(
        "NEXT: continue TRDD-Z582IKIR\n- [[page-a]] and [[page-b]]\n", encoding="utf-8"
    )
    (sd / "resume-after-clear.flag").write_text("resume me", encoding="utf-8")

    proc = _run(["--phase", "before"], project=p)
    assert proc.returncode == 0, proc.stderr
    assert "VERIFY_BEFORE" in proc.stdout
    saved = json.loads((sd / "handoff-clear-verify.json").read_text(encoding="utf-8"))
    before = saved["before"]
    assert before["cron_id"] == "cron-abc"
    assert before["handoff_links"] == ["page-a", "page-b"]
    assert before["handoff_link_count"] == 2
    assert before["resume_flag_present"] is True


def test_phase_before_warns_when_the_staging_cannot_resume(tmp_path: Path) -> None:
    """--phase before with no resume-after-clear.flag WARNS that a hand-typed /clear won't resume."""
    p = tmp_path / "proj"
    sd = _state_dir(p)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "heartbeat-cron-id.txt").write_text("cron-abc", encoding="utf-8")
    (sd / "agent-handoff.md").write_text("NEXT: something\n", encoding="utf-8")
    # deliberately NO resume-after-clear.flag — the 2026-08-22 staging that left a resumed
    # session idle, which this script certified while silently recording the missing flag

    proc = _run(["--phase", "before"], project=p)
    assert proc.returncode == 0, proc.stderr
    assert "VERIFY_BEFORE" in proc.stdout
    assert "VERIFY_BEFORE_NO_RESUME_FLAG" in proc.stderr
    assert "--phase after" in proc.stderr, "the warning must carry the command to paste"


def test_phase_before_is_quiet_when_the_flag_is_there(tmp_path: Path) -> None:
    """The no-resume warning stays silent on a properly staged clear — a warning that always fires gets ignored."""
    p = tmp_path / "proj"
    sd = _state_dir(p)
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "heartbeat-cron-id.txt").write_text("cron-abc", encoding="utf-8")
    (sd / "agent-handoff.md").write_text("NEXT: something\n", encoding="utf-8")
    (sd / "resume-after-clear.flag").write_text("resume me", encoding="utf-8")

    proc = _run(["--phase", "before"], project=p)
    assert proc.returncode == 0, proc.stderr
    assert "VERIFY_BEFORE_NO_RESUME_FLAG" not in proc.stderr


def test_phase_after_no_before_is_graceful(tmp_path: Path) -> None:
    """--phase after with no before-snapshot → a warning, never a crash."""
    p = tmp_path / "proj"
    (_state_dir(p)).mkdir(parents=True, exist_ok=True)
    proc = _run(["--phase", "after"], project=p)
    assert proc.returncode == 0
    assert "VERIFY_NO_BEFORE" in proc.stderr


def test_phase_after_proves_cron_recreated_and_writes_report(tmp_path: Path) -> None:
    """--phase after: a changed cron id + a fresh re-arm ts → PASS, report emitted."""
    p = tmp_path / "proj"
    sd = _state_dir(p)
    sd.mkdir(parents=True, exist_ok=True)
    # Seed a before-snapshot as if the invoking session recorded it pre-/clear.
    now = int(time.time())
    (sd / "handoff-clear-verify.json").write_text(
        json.dumps({"before": {"ts": now - 60, "cron_id": "old-cron", "context_tokens": 400000, "handoff_links": [], "resume_flag_present": True}}),
        encoding="utf-8",
    )
    # The fresh session's re-arm wrote a NEW cron id + a fresh armed-at stamp.
    (sd / "heartbeat-cron-id.txt").write_text("new-cron", encoding="utf-8")
    (sd / "heartbeat-armed-at.ts").write_text(str(now), encoding="utf-8")
    # The resume flag was consumed by _phase_clear_resume (absent now).

    proc = _run(["--phase", "after"], project=p)
    assert proc.returncode == 0, proc.stderr
    assert "VERIFY_AFTER" in proc.stdout
    assert "[PASS] cron_recreated" in proc.stdout
    assert "[PASS] resume_flag_consumed" in proc.stdout
    # A PASS/FAIL report was written under reports/continuity-build/ of the tmp project.
    reports = list((p / "reports" / "continuity-build").glob("*-handoff-clear-verify.md"))
    assert reports, "a verification report must be written"
    body = reports[0].read_text(encoding="utf-8")
    assert "cross-/clear verification" in body
    # The JSON now carries the verdicts too.
    saved = json.loads((sd / "handoff-clear-verify.json").read_text(encoding="utf-8"))
    assert saved["verdicts"]["cron_recreated"]["status"] == "PASS"


# --- janitor#224: two verdicts that misreported a healthy clear -------------------


def _snap(**over):
    base = {"ts": 1000, "cron_id": "a", "context_tokens": 177_499,
            "resume_flag_present": False, "handoff_links": []}
    return {**base, **over}


def test_consumption_stamp_proves_the_resume_even_when_before_never_saw_the_flag():
    """Defect 2: on the spawned-chain path the flag is written by a detached child AFTER
    the before-snapshot (measured 23:29:10 vs 23:29:12), so `b_flag` is False on exactly
    the runs that worked. The stamp is direct evidence and outranks that inference."""
    v = _import().compute_verdicts(
        _snap(resume_flag_present=False),
        _snap(ts=2000, resume_consumed_at=1500, resume_flag_present=False),
    )
    assert v["resume_flag_consumed"]["status"] == "PASS"


def test_without_a_stamp_the_skip_no_longer_asserts_a_falsehood():
    """The old text said 'no resume-after-clear flag was set before /clear' — stated as
    fact, on runs where one had been set AND consumed. A verdict that cannot observe its
    subject must not narrate it."""
    v = _import().compute_verdicts(_snap(), _snap(ts=2000))
    d = v["resume_flag_consumed"]
    assert d["status"] == "SKIP"
    assert "could not observe" in d["detail"]
    assert "no resume-after-clear flag was set" not in d["detail"]


def test_a_stale_stamp_from_a_previous_clear_does_not_count():
    """A stamp older than the before-snapshot belongs to an earlier event; crediting it
    would let one real resume vouch for every later one."""
    v = _import().compute_verdicts(_snap(ts=5000), _snap(ts=6000, resume_consumed_at=100))
    assert v["resume_flag_consumed"]["status"] == "SKIP"


def test_context_at_the_install_floor_is_a_PASS_not_a_FAIL():
    """Defect 3, the reported numbers: 177499 → 166167 against a ~166k floor. The clear was
    perfect; the ratio was measuring the install."""
    v = _import().compute_verdicts(
        _snap(context_tokens=177_499),
        _snap(ts=2000, context_tokens=166_167, context_floor=166_000),
    )
    assert v["context_collapsed"]["status"] == "PASS", v["context_collapsed"]["detail"]


def test_a_before_too_close_to_the_floor_still_PASSes():
    """180k -> 175k against a 166k floor cannot satisfy a 0.5x ratio — but the session DID
    land at its floor, which is the only thing a clear can achieve. Judged by the ratio this
    was the reported FAIL; judged by the floor it is what success looks like."""
    v = _import().compute_verdicts(
        _snap(context_tokens=180_000),
        _snap(ts=2000, context_tokens=175_000, context_floor=166_000),
    )
    assert v["context_collapsed"]["status"] == "PASS"


def test_a_genuinely_uncollapsed_context_still_FAILs():
    """The floor must not become a blanket excuse: far above it and barely moved is a real
    failure, and this is what stops defect 3's fix from disabling the check."""
    v = _import().compute_verdicts(
        _snap(context_tokens=800_000),
        _snap(ts=2000, context_tokens=790_000, context_floor=166_000),
    )
    assert v["context_collapsed"]["status"] == "FAIL"


def test_an_unknown_floor_falls_back_to_the_ratio():
    """Fail-open: an unmeasured floor degrades to the old behaviour, never to a crash."""
    v = _import().compute_verdicts(
        _snap(context_tokens=400_000), _snap(ts=2000, context_tokens=100_000),
    )
    assert v["context_collapsed"]["status"] == "PASS"
