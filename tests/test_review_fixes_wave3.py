"""Regression tests for the token-waste review batch (TRDD wave 3, run wf_6aee2965).

Pins: the SessionStart TRDD-STATE injector recognizes v2 `column:` TRDDs, the three
interval/bucket zero-division guards, the resume-directive id case preservation, and
the map-drift detector's structure-hash confirmation path.
"""

from __future__ import annotations

import re
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import token_baseline as tb  # noqa: E402


def test_classify_recent_zero_bucket_disables_not_crashes() -> None:
    """bucket_s=0 (a legal knob value) must return None, never ZeroDivisionError."""
    records = [{"ts": 1000 + i * 60, "output": 10} for i in range(20)]
    assert tb.classify_recent(records, bucket_s=0, now=int(time.time())) is None


def test_detector_tick_keys_guard_zero_interval() -> None:
    """Both tick_key sites must divide by max(1, interval) (interval=0 is legal)."""
    for det in ("trdd-reminder.py", "report-to-trdd-drift.py"):
        text = (_ROOT / "scripts" / "detectors" / det).read_text(encoding="utf-8")
        assert "now // max(1, interval)" in text, det
        assert re.search(r"now // interval\b", text) is None, det


def test_trdd_state_hook_matches_v2_columns(tmp_path: Path) -> None:
    """A v2 `column: dev` TRDD must be selected by the SessionStart injector."""
    hook = (_ROOT / "scripts" / "hooks" / "on-session-start-trdd-state.py").read_text(encoding="utf-8")
    ns: dict = {}
    exec(compile(hook, "hook", "exec"), ns)  # module is import-safe (no side effects at top level)
    tasks = tmp_path / "design" / "tasks"
    tasks.mkdir(parents=True)
    (tasks / "TRDD-20260703_000000+0200-AAAA1111-v2.md").write_text(
        "---\ntrdd-id: AAAA1111\ntitle: x\ncolumn: dev\n---\n## ⏵ STATE\n- next\n", encoding="utf-8"
    )
    (tasks / "TRDD-20260518_000000+0200-bbbb2222-v1.md").write_text(
        "---\ntrdd-id: b\ntitle: y\nstatus: in-progress\n---\n", encoding="utf-8"
    )
    (tasks / "TRDD-20260518_000000+0200-cccc3333-done.md").write_text(
        "---\ntrdd-id: c\ntitle: z\ncolumn: complete\n---\n", encoding="utf-8"
    )
    # `_in_progress` now takes the already-resolved board (the caller composes it from BOTH
    # design scopes via _trdd_paths). This test is about the COLUMN-MATCHING filter, not the
    # discovery, so hand it the files directly and keep the assertions unchanged.
    picked = {p.name for p in ns["_in_progress"](sorted(tasks.glob("TRDD-*.md")))}
    assert "TRDD-20260703_000000+0200-AAAA1111-v2.md" in picked  # v2 WORK column
    assert "TRDD-20260518_000000+0200-bbbb2222-v1.md" in picked  # v1 fallback kept
    assert "TRDD-20260518_000000+0200-cccc3333-done.md" not in picked  # terminal skipped


def test_post_compact_resume_preserves_id_case() -> None:
    """The newest-TRDD fallback must not lowercase v2 UPPERCASE base36 ids."""
    text = (_ROOT / "scripts" / "hooks" / "post-compact-resume.py").read_text(encoding="utf-8")
    assert "m.group(1).lower()" not in text


def test_map_drift_detector_confirms_with_structure_hash() -> None:
    """A digest mismatch alone must not nudge — the structure probe gates it."""
    text = (_ROOT / "scripts" / "detectors" / "project-map-drift.py").read_text(encoding="utf-8")
    assert "structure_hash(maps)" in text
    assert "project-map-fresh-at.digest" in text  # per-digest verdict cache


def test_skill_bash_blocks_stay_context_lean() -> None:
    """The two flagged skills must not dump unbounded diff/scan output inline."""
    rec = (_ROOT / "skills" / "janitor-memory-record-recent" / "SKILL.md").read_text(encoding="utf-8")
    assert not re.search(r"^git diff\s*$", rec, re.MULTILINE)  # bare unbounded diff banned
    wfc = (_ROOT / "skills" / "janitor-github-workflow-create" / "SKILL.md").read_text(encoding="utf-8")
    assert "| tee" not in wfc  # full scan streams to file, only the tail surfaces
