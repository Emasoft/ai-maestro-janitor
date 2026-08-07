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


# --------------------------------------------------------------------------- #
# --intervention atomize
# --------------------------------------------------------------------------- #

def _curated(d: Path, name: str, *, tier: str | None, marker: bool = False) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    if tier is None:
        fm = f"---\nname: {name[:-3]}\ndescription: raw note\nmetadata:\n  type: reference\n---\n"
    else:
        fm = (
            f"---\nname: {name[:-3]}\ndescription: a page\nnode_type: memory\n"
            f"tier: {tier}\nmetadata:\n  type: reference\n---\n"
        )
    body = "^fact-1 [desc: x, keywords: y]\nA fact.\n" if marker else "A durable fact line.\n"
    p.write_text(fm + "\n" + body, encoding="utf-8")
    return p


def test_atomize_lists_only_the_free_prose_page(tmp_path):
    """A page with an atom marker never appears; a free-prose curated page does,
    with the stable 'free-prose' reason slug."""
    _curated(tmp_path, "marked.md", tier="component", marker=True)
    _curated(tmp_path, "raw.md", tier=None)
    _curated(tmp_path, "bare.md", tier="component")

    code, out = _cli("--intervention", "atomize", "--scope", "LOCAL", "--root", str(tmp_path))

    assert code == 0
    lines = [ln for ln in out.splitlines() if ln]
    assert lines == ["bare.md\tfree-prose"]


def test_atomize_refused_page_is_omitted(tmp_path):
    """A page already judged un-atomizable (issue #212) is not re-listed."""
    p = _curated(tmp_path, "bare.md", tier="component")
    code, out = _cli("--intervention", "atomize", "--scope", "LOCAL", "--root", str(tmp_path))
    assert [ln for ln in out.splitlines() if ln] == ["bare.md\tfree-prose"]

    memory_refusals.record("atomize", "LOCAL", tmp_path, [p], reason="boilerplate stub")

    code, out = _cli("--intervention", "atomize", "--scope", "LOCAL", "--root", str(tmp_path))
    assert code == 0
    assert out.strip() == ""


# --------------------------------------------------------------------------- #
# --intervention consolidate
# --------------------------------------------------------------------------- #

def test_consolidate_lists_the_qualifying_group(tmp_path):
    """A same-(tier,type) pair is listed as ONE line: comma-joined pages, the
    stable 'same-tier-type' reason slug."""
    _curated(tmp_path, "a.md", tier="component")
    _curated(tmp_path, "b.md", tier="component")

    code, out = _cli("--intervention", "consolidate", "--scope", "LOCAL", "--root", str(tmp_path))

    assert code == 0
    lines = [ln for ln in out.splitlines() if ln]
    assert lines == ["a.md,b.md\tsame-tier-type"]


def test_consolidate_lone_page_lists_nothing(tmp_path):
    """A single page can never form a merge pair -> no candidates."""
    _curated(tmp_path, "a.md", tier="component")
    code, out = _cli("--intervention", "consolidate", "--scope", "LOCAL", "--root", str(tmp_path))
    assert code == 0
    assert out.strip() == ""


def test_consolidate_group_over_the_size_cap_lists_nothing(tmp_path):
    """janitor#210: a structural pair whose combined size exceeds --max-bytes is
    not a real candidate."""
    a = tmp_path / "a.md"
    a.write_text(
        "---\nname: a\ndescription: a page\nnode_type: memory\ntier: component\n"
        "metadata:\n  type: reference\n---\n\n" + ("x" * 9000),
        encoding="utf-8",
    )
    b = tmp_path / "b.md"
    b.write_text(
        "---\nname: b\ndescription: a page\nnode_type: memory\ntier: component\n"
        "metadata:\n  type: reference\n---\n\n" + ("x" * 9000),
        encoding="utf-8",
    )
    code, out = _cli(
        "--intervention", "consolidate", "--scope", "LOCAL", "--root", str(tmp_path),
        "--max-bytes", "10000",
    )
    assert code == 0
    assert out.strip() == ""


def test_consolidate_refused_group_is_omitted(tmp_path):
    """A group already judged un-mergeable (the exact member set) is not re-listed."""
    a = _curated(tmp_path, "a.md", tier="component")
    b = _curated(tmp_path, "b.md", tier="component")
    code, out = _cli("--intervention", "consolidate", "--scope", "LOCAL", "--root", str(tmp_path))
    assert [ln for ln in out.splitlines() if ln] == ["a.md,b.md\tsame-tier-type"]

    memory_refusals.record("consolidate", "LOCAL", tmp_path, [a, b], reason="distinct subjects")

    code, out = _cli("--intervention", "consolidate", "--scope", "LOCAL", "--root", str(tmp_path))
    assert code == 0
    assert out.strip() == ""


def test_consolidate_pair_refusal_narrows_but_keeps_a_three_group(tmp_path):
    """Review 2026-08-08: the merge-protocol records abstains keyed on the judged PAIR,
    and the old exact-group filter never matched one — so any 3+-member group re-listed
    forever. The rule now: a group stays a candidate while an UNJUDGED pair remains, and
    disappears exactly when every pair is judged."""
    a = _curated(tmp_path, "a.md", tier="component")
    b = _curated(tmp_path, "b.md", tier="component")
    c = _curated(tmp_path, "c.md", tier="component")

    memory_refusals.record("consolidate", "LOCAL", tmp_path, [a, b], reason="different subjects")
    code, out = _cli("--intervention", "consolidate", "--scope", "LOCAL", "--root", str(tmp_path))
    assert [ln for ln in out.splitlines() if ln] == ["a.md,b.md,c.md\tsame-tier-type"], (
        "pairs (a,c) and (b,c) are unjudged — the group must stay listed"
    )

    memory_refusals.record("consolidate", "LOCAL", tmp_path, [a, c], reason="different subjects")
    memory_refusals.record("consolidate", "LOCAL", tmp_path, [b, c], reason="different subjects")
    code, out = _cli("--intervention", "consolidate", "--scope", "LOCAL", "--root", str(tmp_path))
    assert code == 0
    assert out.strip() == "", "every pair judged — no judgment work remains"


# --------------------------------------------------------------------------- #
# unreadable pages — the scheduler fails OPEN on them, so the CLI must NAME them
# (review 2026-08-08: a silent skip hands the dispatched agent an empty list with
# nothing to record a refusal on — the #227 loop through the tool built to fix it).
# --------------------------------------------------------------------------- #

def _make_unreadable(p: Path) -> None:
    import os

    if os.geteuid() == 0:
        import pytest

        pytest.skip("running as root — chmod 000 does not block reads")
    p.chmod(0o000)


def test_repair_names_an_unreadable_page(tmp_path):
    """repair_has_work dispatches on a page nobody can read; the CLI must name it."""
    good = _well_formed(tmp_path, "good.md")
    bad = _no_notes(tmp_path, "broken.md")
    _make_unreadable(bad)
    try:
        code, out = _cli("--intervention", "repair", "--scope", "LOCAL", "--root", str(tmp_path))
    finally:
        bad.chmod(0o644)
    assert code == 0
    assert "broken.md\tunreadable-page" in out.splitlines()
    assert str(good.name) not in out


def test_atomize_names_an_unreadable_page(tmp_path):
    """Same contract as repair — the mirrors must not drift (janitor#227)."""
    bad = _well_formed(tmp_path, "locked.md")
    _make_unreadable(bad)
    try:
        code, out = _cli("--intervention", "atomize", "--scope", "LOCAL", "--root", str(tmp_path))
    finally:
        bad.chmod(0o644)
    assert code == 0
    assert "locked.md\tunreadable-page" in out.splitlines()


def test_consolidate_names_the_unreadable_page_not_an_empty_list(tmp_path):
    """The grouping helper returns None on ANY unreadable page (fail-open) and the CLI
    used to return [] on that — scheduler dispatches, agent gets nothing. Now the
    unreadable page itself is the named candidate."""
    _curated(tmp_path, "a.md", tier="component")
    _curated(tmp_path, "b.md", tier="component")
    bad = _curated(tmp_path, "sealed.md", tier="component")
    _make_unreadable(bad)
    try:
        code, out = _cli(
            "--intervention", "consolidate", "--scope", "LOCAL", "--root", str(tmp_path)
        )
    finally:
        bad.chmod(0o644)
    assert code == 0
    assert [ln for ln in out.splitlines() if ln] == ["sealed.md\tunreadable-page"]
