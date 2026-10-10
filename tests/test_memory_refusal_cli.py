"""memory_refusal_cli.py — a one-page consolidate refusal is inert, so the CLI refuses it (TRDD-K5F7US68).

Run as a SUBPROCESS: argparse and the exit code are what an agent actually sees. The ledger
lands in the session-isolated JANITOR_GLOBAL_STATE_DIR that tests/conftest.py sets.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "memory_refusal_cli.py"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import memory_refusals  # noqa: E402


def _page(d: Path, name: str) -> Path:
    p = d / name
    p.write_text(f"---\nname: {name[:-3]}\ndescription: a page\n---\n\nA fact.\n", encoding="utf-8")
    return p


def _record(root: Path, intervention: str, *pages: str) -> subprocess.CompletedProcess[str]:
    args = [sys.executable, str(CLI), "record", "--intervention", intervention,
            "--scope", "LOCAL", "--root", str(root), "--reason", "distinct subjects"]
    for page in pages:
        args += ["--page", page]
    return subprocess.run(args, capture_output=True, text=True)


def test_one_page_consolidate_refusal_is_refused_and_not_recorded(tmp_path):
    """A single --page with consolidate exits 2, prints REFUSED, and leaves the ledger empty."""
    _page(tmp_path, "a.md")
    proc = _record(tmp_path, "consolidate", "a.md")
    assert proc.returncode == 2
    assert proc.stdout.startswith("REFUSED:")
    assert memory_refusals.read("consolidate", "LOCAL", tmp_path) == {}


def test_two_page_consolidate_refusal_is_recorded(tmp_path):
    """Positive control: two --page values record one key naming both pages."""
    _page(tmp_path, "a.md")
    _page(tmp_path, "b.md")
    proc = _record(tmp_path, "consolidate", "a.md", "b.md")
    assert proc.returncode == 0, proc.stdout
    assert list(memory_refusals.read("consolidate", "LOCAL", tmp_path)) == ["a.md|b.md"]


def test_one_page_refusal_for_another_intervention_is_still_recorded(tmp_path):
    """The pair rule is consolidate-only: a one-page repair refusal still exits 0 and records."""
    _page(tmp_path, "a.md")
    proc = _record(tmp_path, "repair", "a.md")
    assert proc.returncode == 0, proc.stdout
    assert list(memory_refusals.read("repair", "LOCAL", tmp_path)) == ["a.md"]
