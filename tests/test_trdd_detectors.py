"""Tests for the trdd-drift and trdd-reminder detectors.

These detectors surface stale/active TRDDs. The bug they had: the status
parser looked for a `**Status:**` markdown body line, but real TRDDs carry
their state in YAML frontmatter (`status:` v1 / `column:` v2). On top of
that, the filename regex only matched the legacy `TRDD-<full-uuid>-...`
shape, dropping every current `TRDD-<timestamp>-<uid8>-...` file.

Real I/O, no mocks: each case builds a temp project (design/tasks/), ages the
files so the drift staleness gate fires, and runs the detector as a subprocess
with CLAUDE_PROJECT_DIR pointed at it.
"""

import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

DETECTORS = Path(__file__).resolve().parent.parent / "scripts" / "detectors"
DRIFT = DETECTORS / "trdd-drift.py"
REMINDER = DETECTORS / "trdd-reminder.py"

# Current-format filename: TRDD-<YYYYMMDD_HHMMSS±HHMM>-<uid8>-<slug>.md
_TS = "20260101_000000+0000"


def _fm(status: str | None = None, column: str | None = None) -> str:
    """YAML-frontmatter TRDD body with the given status/column."""
    lines = ["---", "trdd-id: 00000000-0000-0000-0000-000000000000", "title: T"]
    if status is not None:
        lines.append(f"status: {status}")
    if column is not None:
        lines.append(f"column: {column}")
    lines += ["created: 2026-01-01T00:00:00+0000", "---", "", "# body", "x"]
    return "\n".join(lines) + "\n"


def _legacy_body(status: str) -> str:
    """Pre-frontmatter TRDD with a `**Status:**` markdown body line."""
    return f"# Title\n\n**Status:** {status}\n\nbody\n"


def _age(path: Path, days: int = 100) -> None:
    t = time.time() - days * 86400
    os.utime(path, (t, t))


def _write(tasks: Path, uid8: str, content: str, *, legacy_uuid: str | None = None) -> Path:
    if legacy_uuid is not None:
        name = f"TRDD-{legacy_uuid}-slug.md"
    else:
        name = f"TRDD-{_TS}-{uid8}-slug.md"
    p = tasks / name
    p.write_text(content)
    _age(p)
    return p


def _run(detector: Path, project: Path, session: str = "sess") -> str:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_SESSION_ID"] = session
    # These tests exercise the drift/reminder LOGIC, not the ai-maestro context
    # gate (TRDD-db169d9e R1). The temp project isn't an ai-maestro-plugins
    # member, so force the gate ON; the gate itself is covered by
    # test_context_gate_detectors.py.
    env["JANITOR_FORCE_AI_MAESTRO"] = "1"
    # Default staleness (14d) is fine — files are aged 100d. Clear knobs so a
    # host env value can't change the threshold under the test.
    for k in (
        "CLAUDE_PLUGIN_OPTION_TRDD_STALENESS_DAYS",
        "CLAUDE_PLUGIN_OPTION_TRDD_REMINDER_INTERVAL",
        "CLAUDE_PLUGIN_OPTION_TRDD_PATH",
    ):
        env.pop(k, None)
    res = subprocess.run(
        [sys.executable, str(detector)],
        capture_output=True, text=True, env=env, timeout=30,
    )
    return res.stdout


class TestTrddDetectors(unittest.TestCase):
    def _proj(self, tmp: str) -> Path:
        root = Path(tmp)
        (root / "design" / "tasks").mkdir(parents=True)
        return root

    # ---- drift: frontmatter status parsing ------------------------------

    def test_drift_frontmatter_in_progress_flagged(self):
        """A `status: in-progress` (YAML frontmatter) TRDD is drift-flagged."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "aaaaaaaa", _fm(status="in-progress"))
            out = _run(DRIFT, root)
            self.assertIn("[trdd-drift]", out)
            self.assertIn("TRDD-aaaaaaaa", out)
            self.assertIn("in-progress", out)

    def test_drift_frontmatter_not_started_flagged(self):
        """A `status: not-started` TRDD is drift-flagged."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "bbbbbbbb", _fm(status="not-started"))
            out = _run(DRIFT, root)
            self.assertIn("TRDD-bbbbbbbb", out)

    def test_drift_completed_not_flagged(self):
        """A `status: completed` TRDD is terminal → never drift-flagged."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "cccccccc", _fm(status="completed"))
            out = _run(DRIFT, root)
            self.assertEqual(out.strip(), "")

    # ---- drift: v2 column support ---------------------------------------

    def test_drift_v2_column_dev_flagged(self):
        """A v2 `column: dev` TRDD (no status:) is drift-flagged."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "dddddddd", _fm(column="dev"))
            out = _run(DRIFT, root)
            self.assertIn("TRDD-dddddddd", out)
            self.assertIn("dev", out)

    def test_drift_v2_column_backburner_flagged(self):
        """A v2 `column: backburner` TRDD is drift-flagged (active set)."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "eeeeeeee", _fm(column="backburner"))
            out = _run(DRIFT, root)
            self.assertIn("TRDD-eeeeeeee", out)

    def test_drift_v2_column_published_not_flagged(self):
        """A v2 terminal `column: published` TRDD is NOT drift-flagged."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "ffffffff", _fm(column="published"))
            out = _run(DRIFT, root)
            self.assertEqual(out.strip(), "")

    # ---- drift: legacy body fallback ------------------------------------

    def test_drift_legacy_status_body_flagged(self):
        """A pre-frontmatter `**Status:** In progress` body still works."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "12345678", _legacy_body("In progress"))
            out = _run(DRIFT, root)
            self.assertIn("TRDD-12345678", out)
            # Title-case body value normalised to kebab-case for display.
            self.assertIn("in-progress", out)

    def test_drift_legacy_uuid_filename_flagged(self):
        """A legacy `TRDD-<full-uuid>-...` filename is matched (not just the
        current `<timestamp>-<uid8>` shape)."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            uuid = "deadbeef-0000-0000-0000-000000000000"
            _write(root / "design/tasks", "", _fm(status="in-progress"),
                   legacy_uuid=uuid)
            out = _run(DRIFT, root)
            self.assertIn("TRDD-deadbeef", out)

    # ---- reminder -------------------------------------------------------

    def test_reminder_in_progress_listed(self):
        """The reminder lists `status: in-progress` TRDDs."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "aaaaaaaa", _fm(status="in-progress"))
            out = _run(REMINDER, root)
            self.assertIn("[trdd-reminder]", out)
            self.assertIn("TRDD-aaaaaaaa", out)

    def test_reminder_v2_column_listed(self):
        """The reminder lists v2 active-column TRDDs."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "bbbbbbbb", _fm(column="testing"))
            out = _run(REMINDER, root)
            self.assertIn("TRDD-bbbbbbbb", out)

    def test_reminder_not_started_excluded(self):
        """`status: not-started` is NOT 'in progress' → excluded from reminder."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "cccccccc", _fm(status="not-started"))
            out = _run(REMINDER, root)
            self.assertEqual(out.strip(), "")

    def test_reminder_completed_excluded(self):
        """A completed TRDD is never in the reminder."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "dddddddd", _fm(status="completed"))
            out = _run(REMINDER, root)
            self.assertEqual(out.strip(), "")

    def test_reminder_counts_mixed_active(self):
        """v1 in-progress + v2 dev-column TRDDs are both counted active."""
        with TemporaryDirectory() as tmp:
            root = self._proj(tmp)
            _write(root / "design/tasks", "aaaaaaaa", _fm(status="in-progress"))
            _write(root / "design/tasks", "bbbbbbbb", _fm(column="dev"))
            _write(root / "design/tasks", "cccccccc", _fm(status="completed"))
            out = _run(REMINDER, root)
            self.assertIn("2 TRDD(s)", out)
            self.assertIn("TRDD-aaaaaaaa", out)
            self.assertIn("TRDD-bbbbbbbb", out)
            self.assertNotIn("TRDD-cccccccc", out)


if __name__ == "__main__":
    unittest.main()
