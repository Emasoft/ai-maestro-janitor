"""Tests for the trdd-reminder detector (issue #59).

The reminder consolidates a once-per-interval nag listing the TRDDs that are
genuinely IN-FLIGHT, so nothing active is forgotten. Issue #59 reported two
defects this suite guards against forever:

  * Defect 1 — `column: backburner` (the parking lot) was reported as "currently
    active". The active set is now ONLY the WORK columns
    {dev, testing, ai_review, human_review} (plus v1 `status: in-progress`);
    parked / pre-work / terminal columns are excluded.
  * Defect 2 — the bare "(Nd)" was ambiguous (days-since-touch read as age). The
    label now shows BOTH: `(idle Nd, age Md)` — idle = days since last-touched
    (the staleness that justifies the nag), age = days since `created:` (context).
    Falls back to `(idle Nd)` when `created:` is absent/unparseable.

Real I/O, no mocks: each case builds a temp project with a `design/tasks/` dir and
runs the detector as a subprocess, with HOME / CLAUDE_PROJECT_DIR redirected into
tmp and JANITOR_FORCE_AI_MAESTRO=1 to satisfy the ai-maestro context gate. The temp
project is NOT a git repo, so `_last_touched_epoch` falls back to the file mtime —
which the test sets explicitly via os.utime, making the idle-days value deterministic.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

DETECTOR = (
    Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "trdd-reminder.py"
)

_DAY = 86400


def _env(home: Path, project: Path) -> dict:
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    # The reminder is silent outside an ai-maestro project — force the gate ON so the
    # test exercises the real emission path regardless of the temp dir's identity.
    env["JANITOR_FORCE_AI_MAESTRO"] = "1"
    # A stable per-run session key so the dedupe file is deterministic (a fresh tmp
    # state dir per case means first-run always emits anyway).
    env["CLAUDE_SESSION_ID"] = "trdd-reminder-test"
    # Drop any inherited interval override so the default 4h bucket applies.
    env.pop("CLAUDE_PLUGIN_OPTION_TRDD_REMINDER_INTERVAL", None)
    env.pop("CLAUDE_PLUGIN_OPTION_TRDD_PATH", None)
    return env


def _run(env: dict) -> str:
    res = subprocess.run(
        [sys.executable, str(DETECTOR), "--one-shot"],
        capture_output=True, text=True, env=env, timeout=60,
    )
    if res.returncode != 0:
        raise AssertionError(f"detector exited {res.returncode}; stderr:\n{res.stderr}")
    return res.stdout


def _write_trdd(
    tasks: Path,
    *,
    uid: str,
    slug: str,
    column: str | None = None,
    status: str | None = None,
    created_days_ago: int | None = None,
    idle_days: int = 5,
    legacy: bool = False,
) -> str:
    """Create a TRDD file and return the 8-char display ref the reminder will use.

    `legacy=True` → the old `TRDD-<full-uuid>-<slug>.md` filename (uid must be a full
    36-char UUID); otherwise the canonical `TRDD-<ts>-<uid8>-<slug>.md`. The file's
    mtime is set to `idle_days` ago (+1h margin) so the idle-days value floors stably.
    """
    fm = ["---"]
    if column is not None:
        fm.append(f"column: {column}")
    if status is not None:
        fm.append(f"status: {status}")
    if created_days_ago is not None:
        created = (datetime.now().astimezone() - timedelta(days=created_days_ago, hours=1))
        fm.append(f"created: {created.strftime('%Y-%m-%dT%H:%M:%S%z')}")
    fm.append("---")
    fm.append(f"# {slug}\n")
    if legacy:
        name = f"TRDD-{uid}-{slug}.md"
        display = uid[:8]
    else:
        name = f"TRDD-20260101_120000+0200-{uid}-{slug}.md"
        display = uid
    path = tasks / name
    path.write_text("\n".join(fm), encoding="utf-8")
    # Set mtime to idle_days ago (+1h) so (now - mtime)//86400 == idle_days robustly.
    touched = datetime.now().timestamp() - (idle_days * _DAY + 3600)
    os.utime(path, (touched, touched))
    return display


@pytest.fixture
def project(tmp_path):
    home = tmp_path / "home"
    proj = tmp_path / "project"
    (proj / "design" / "tasks").mkdir(parents=True, exist_ok=True)
    return {"home": home, "project": proj, "tasks": proj / "design" / "tasks"}


# --------------------------------------------------------------------------- #
# Defect 1 — backburner / parked / terminal columns are NOT "active"
# --------------------------------------------------------------------------- #

def test_backburner_is_not_reported_active(project):
    """The #59 regression guard: a `column: backburner` proto-TRDD is the parking
    lot — it must NEVER appear in the 'currently active' reminder."""
    ref = _write_trdd(project["tasks"], uid="aaaaaaaa", slug="parked",
                      column="backburner", created_days_ago=45, idle_days=12)
    out = _run(_env(project["home"], project["project"]))
    assert ref not in out, out
    # With nothing else present, the detector emits nothing at all.
    assert out.strip() == "", out


@pytest.mark.parametrize("column", ["complete", "published", "todo", "design", "dispatch", "blocked"])
def test_non_work_columns_excluded(project, column):
    """Terminal (complete/published), pre-work (todo/design/dispatch), and `blocked`
    are all excluded from 'active' — only the WORK columns nag."""
    ref = _write_trdd(project["tasks"], uid="bbbbbbbb", slug="x",
                      column=column, created_days_ago=30, idle_days=20)
    out = _run(_env(project["home"], project["project"]))
    assert ref not in out, out


@pytest.mark.parametrize("column", ["dev", "testing", "ai_review", "human_review"])
def test_work_columns_reported_active(project, column):
    """Each of the four WORK columns is genuinely active work and IS reported."""
    ref = _write_trdd(project["tasks"], uid="cccccccc", slug="x",
                      column=column, created_days_ago=45, idle_days=10)
    out = _run(_env(project["home"], project["project"]))
    assert ref in out, out
    assert "currently active" in out, out


def test_v1_status_in_progress_reported_active(project):
    """A v1 `status: in-progress` TRDD (no `column:`) is still reported active —
    backward compatibility with the pre-column TRDD format."""
    ref = _write_trdd(project["tasks"], uid="dddddddd", slug="x",
                      status="in-progress", created_days_ago=20, idle_days=7)
    out = _run(_env(project["home"], project["project"]))
    assert ref in out, out


# --------------------------------------------------------------------------- #
# Defect 2 — the label shows BOTH idle (staleness) and age (true age)
# --------------------------------------------------------------------------- #

def test_label_shows_idle_and_age(project):
    """An active TRDD created 45d ago and last-touched 10d ago is labelled
    `(idle 10d, age 45d)` — idle is the staleness that justifies the nag, age is
    the true age for context. The bare '(10d)' ambiguity is gone."""
    ref = _write_trdd(project["tasks"], uid="eeeeeeee", slug="x",
                      column="dev", created_days_ago=45, idle_days=10)
    out = _run(_env(project["home"], project["project"]))
    assert f"TRDD-{ref} (idle 10d, age 45d)" in out, out


def test_label_idle_only_when_no_created(project):
    """When `created:` is absent (a legacy TRDD), the label degrades to `(idle Nd)`
    — never a bare or misleading age."""
    ref = _write_trdd(project["tasks"], uid="ffffffff", slug="x",
                      column="dev", created_days_ago=None, idle_days=8)
    out = _run(_env(project["home"], project["project"]))
    assert f"TRDD-{ref} (idle 8d)" in out, out
    assert "age" not in out, out


# --------------------------------------------------------------------------- #
# the legacy full-UUID filename still resolves to an 8-char display ref
# --------------------------------------------------------------------------- #

def test_legacy_full_uuid_filename(project):
    """The old `TRDD-<full-uuid>-<slug>.md` filename (no timestamp prefix) is
    matched and shown as the UUID's first 8 chars."""
    full = "12345678-9abc-4def-8123-456789abcdef"
    ref = _write_trdd(project["tasks"], uid=full, slug="legacy",
                      column="dev", created_days_ago=15, idle_days=6, legacy=True)
    assert ref == "12345678"
    out = _run(_env(project["home"], project["project"]))
    assert f"TRDD-{ref} (idle 6d, age 15d)" in out, out
