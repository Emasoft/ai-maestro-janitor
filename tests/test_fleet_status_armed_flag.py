"""janitor#77 item 2 — the `heartbeat-armed-at.ts` stamp is advisory, not authoritative.

The issue's forensics: `fleet_status.py`'s "armed" column is purely the presence of the
stamp file, and it can lie in EITHER direction — a live cron never re-stamps it (so a
genuinely healthy, actively-firing project can show `armed: no`), and a stamp can outlive
a dead cron or a Claude restart (so a genuinely dead project can show `armed: yes`).
`fleet_scan.diagnose_root` already never reads this file for the DIAGNOSIS (only
`disarmed.flag` + the transcript decide `diag`); this file's dashboard-only "⚠️ NOT armed"
attention flag was the one place still trusting the stamp on its own, which reintroduces
two concrete false positives:

  1. `diag == "healthy"` (transcript provably fresh right now) + no stamp: the exact
     race #77 item 3 describes (a turn that rate-limited between CronCreate and the
     stamp write), which the SessionStart nudge already treats as self-healing
     (TRDD-EFTQB9RR item A re-arms unconditionally regardless of the stamp).
  2. `diag == "unarmed"` (`disarmed.flag` present, sacrosanct) + no stamp (disarm
     deletes the stamp): flagging "needs /janitor-arm" here is precisely the
     disarm-optout bug TRDD-EFTQB9RR fixed for the SessionStart path, reintroduced on
     the dashboard.

These tests pin `_flags()`'s advisory behavior directly (no process/daemon needed — it is
a pure function of the row dict) plus the doc-honesty fixes for /janitor-global-arm.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))

import fleet_status as fstat  # type: ignore[import-not-found]  # noqa: E402
import global_control_cli as cli  # type: ignore[import-not-found]  # noqa: E402


def _row(diag: str, armed: str) -> dict:
    """Minimal row dict — only the keys `_flags` actually reads."""
    return {
        "diag": diag, "armed": armed, "ci": "—", "prrd": "ok", "ghsec": "—",
        "uncommitted": "0", "kanban": {},
    }


# --------------------------------------------------------------------------- #
# The two false-positive diagnoses are suppressed
# --------------------------------------------------------------------------- #


def test_healthy_with_no_stamp_is_not_flagged() -> None:
    """A provably-fresh transcript outranks a missing stamp — no false 'needs arm'."""
    out = fstat._flags(_row("healthy", "no"))
    assert "⚠️" not in out


def test_unarmed_with_no_stamp_is_not_flagged() -> None:
    """disarmed.flag is sacrosanct; disarm deletes the stamp too — never nudge to re-arm."""
    out = fstat._flags(_row("unarmed", "no"))
    assert "⚠️" not in out


# --------------------------------------------------------------------------- #
# Every other diagnosis keeps the flag (redundant with the diag icon, never wrong)
# --------------------------------------------------------------------------- #


def test_cron_dead_with_no_stamp_is_still_flagged() -> None:
    out = fstat._flags(_row("cron_dead", "no"))
    assert "⚠️" in out


def test_frozen_with_no_stamp_is_still_flagged() -> None:
    out = fstat._flags(_row("frozen", "no"))
    assert "⚠️" in out


def test_version_mismatch_with_no_stamp_is_still_flagged() -> None:
    out = fstat._flags(_row("version_mismatch", "no"))
    assert "⚠️" in out


def test_dead_with_no_stamp_is_still_flagged() -> None:
    out = fstat._flags(_row("dead", "no"))
    assert "⚠️" in out


# --------------------------------------------------------------------------- #
# A present stamp never triggers the flag, on any diagnosis
# --------------------------------------------------------------------------- #


def test_stamp_present_never_flags_regardless_of_diag() -> None:
    for diag in ("healthy", "unarmed", "frozen", "cron_dead", "version_mismatch", "dead"):
        out = fstat._flags(_row(diag, "yes"))
        assert "⚠️" not in out, f"diag={diag!r} armed=yes must never show the NOT-armed flag"


# --------------------------------------------------------------------------- #
# The tooltip documents the advisory semantics honestly (janitor#77 item 2)
# --------------------------------------------------------------------------- #


def test_armed_column_tooltip_documents_advisory_semantics() -> None:
    tip = fstat._COL_TIPS["armed"]
    assert "ADVISORY" in tip
    assert "diag" in tip or "cron" in tip, "must point the reader at the authoritative columns"


# --------------------------------------------------------------------------- #
# janitor#77 item 1 — /janitor-global-arm's own output states it arms no per-project cron
# --------------------------------------------------------------------------- #


def test_cli_arm_output_states_it_creates_no_per_project_cron(tmp_path, monkeypatch, capsys) -> None:
    """The CLI's OWN printed line — not just the skill doc — must be honest: clearing the
    two machine-wide flags creates no cron anywhere; only /janitor-arm, run inside a
    project's own session, does that."""
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path))
    monkeypatch.setattr(cli.sys, "argv", ["x", "arm"])
    assert cli.main() == 0
    out = capsys.readouterr().out
    assert "does NOT arm any" in out or "does NOT arm" in out
    assert "/janitor-arm" in out


def test_skill_doc_states_no_fan_out() -> None:
    """skills/janitor-global-arm/SKILL.md must keep saying, in plain language, that it
    arms no per-project cron and point at /janitor-arm — the doc-honesty half of item 1."""
    text = (_PROJECT_ROOT / "skills" / "janitor-global-arm" / "SKILL.md").read_text(encoding="utf-8")
    assert "Does NOT arm any" in text
    assert "/janitor-arm" in text
