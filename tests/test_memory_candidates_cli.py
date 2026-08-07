"""memory_candidates_cli.py — the single-source candidate lister (janitor#227).

Before this CLI existed, the janitor-memory-repair skill discovered candidates via
`memgrep lint`, which could disagree with the scheduler's own structural precheck
(`memory_content_precheck.repair_defect`) — a page the scheduler flagged could return
ZERO lint findings, so the agent found nothing to work, could not record a refusal,
and the chore re-dispatched forever. This CLI prints exactly what the scheduler's own
predicate flags, so the two can never drift again.

The CLI is run as a SUBPROCESS on purpose — argparse is part of its surface, and it is
what an agent actually invokes.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "memory_candidates_cli.py"
sys.path.insert(0, str(ROOT / "scripts" / "lib"))

import memory_refusals  # noqa: E402


def _cli(*args: str) -> tuple[int, str]:
    proc = subprocess.run(
        [sys.executable, str(CLI), *args], capture_output=True, text=True
    )
    return proc.returncode, proc.stdout


def _well_formed(d: Path, name: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(
        "---\n"
        f"name: {name[:-3]}\n"
        "description: what breaks when X happens — symptom words\n"
        "ocd: 2026-07-01\n"
        "lmd: 2026-07-08\n"
        "metadata:\n"
        "  node_type: memory\n"
        "  type: project\n"
        "  tier: component\n"
        "---\n\nA durable fact line.\n\n## Notes and lessons learned\n",
        encoding="utf-8",
    )
    return p


def _no_notes(d: Path, name: str) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(
        "---\n"
        f"name: {name[:-3]}\n"
        "description: what breaks when Y happens — symptom words\n"
        "ocd: 2026-07-01\n"
        "lmd: 2026-07-08\n"
        "metadata:\n"
        "  node_type: memory\n"
        "  type: project\n"
        "  tier: component\n"
        "---\n\nA durable fact line, no Notes section.\n",
        encoding="utf-8",
    )
    return p


def test_lists_only_the_broken_page_with_its_reason_slug(tmp_path):
    """A well-formed page never appears; a broken page appears with the exact
    tab-separated `<relative-path>\\t<reason-slug>` shape."""
    _well_formed(tmp_path, "good.md")
    _no_notes(tmp_path, "bad.md")

    code, out = _cli("--intervention", "repair", "--scope", "LOCAL", "--root", str(tmp_path))

    assert code == 0
    lines = [ln for ln in out.splitlines() if ln]
    assert lines == ["bad.md\tno-notes-heading"]


def test_empty_corpus_prints_nothing(tmp_path):
    """No candidates -> empty stdout, exit 0 (not an error)."""
    code, out = _cli("--intervention", "repair", "--scope", "LOCAL", "--root", str(tmp_path))
    assert code == 0
    assert out.strip() == ""


def test_a_refused_page_is_omitted(tmp_path):
    """A page the ledger already covers (issue #131) is NOT a candidate — a refused
    defect must not keep re-dispatching the agent that already declined it."""
    bad = _no_notes(tmp_path, "bad.md")

    code, out = _cli("--intervention", "repair", "--scope", "LOCAL", "--root", str(tmp_path))
    assert [ln for ln in out.splitlines() if ln] == ["bad.md\tno-notes-heading"]

    memory_refusals.record("repair", "LOCAL", tmp_path, [bad], reason="unfixable for now")

    code, out = _cli("--intervention", "repair", "--scope", "LOCAL", "--root", str(tmp_path))
    assert code == 0
    assert out.strip() == ""


def test_unsupported_intervention_is_refused(tmp_path):
    """An intervention this CLI does not implement fails loud with exit 2, not a
    silent empty candidate list that looks like 'nothing to do'."""
    code, out = _cli("--intervention", "split", "--scope", "LOCAL", "--root", str(tmp_path))
    assert code == 2
