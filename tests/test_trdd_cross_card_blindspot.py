"""Integration tests for the trdd-cross-card-blindspot detector (TRDD-XFPOAF2I).

Real I/O, no mocks: each case writes fixture TRDDs directly under
design/tasks/ (no git needed — this detector never touches git) and runs the
detector as a SUBPROCESS with CLAUDE_PROJECT_DIR pointed at the fixture.

Load-bearing cases:
  * two open cards sharing a ref, neither citing the other -> ONE pair reported.
  * card A's external-refs names card B -> SILENT.
  * card A's BODY mentions TRDD-<B-id8> -> SILENT.
  * one of the two cards is terminal -> SILENT.
  * three cards sharing one ref -> 3 pairs, each reported once (no dupes).
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

DETECTOR = (
    Path(__file__).resolve().parent.parent
    / "scripts"
    / "detectors"
    / "trdd-cross-card-blindspot.py"
)

_TS = "20260101_000000+0000"


def _trdd_path(root: Path, uid: str) -> Path:
    return root / "design" / "tasks" / f"TRDD-{_TS}-{uid}-slug.md"


def _write_trdd(
    root: Path,
    uid: str,
    *,
    column: str = "todo",
    external_refs: str = "[]",
    body: str = "\n# body\nx\n",
) -> Path:
    text = textwrap.dedent(
        f"""\
        ---
        trdd-id: {uid}
        title: T
        column: {column}
        external-refs: {external_refs}
        ---
        """
    ) + body
    p = _trdd_path(root, uid)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
    return p


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "design" / "tasks").mkdir(parents=True)
    return root


def _run(root: Path) -> str:
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(root)
    env["JANITOR_FORCE_AI_MAESTRO"] = "1"
    env.pop("CLAUDE_PLUGIN_OPTION_TRDD_PATH", None)
    res = subprocess.run(
        [sys.executable, str(DETECTOR)],
        capture_output=True, text=True, env=env, timeout=60,
    )
    assert res.returncode == 0, res.stderr
    return res.stdout


def test_shared_ref_no_cross_reference_reports_one_pair(repo: Path):
    """Two open cards citing the same issue, neither naming the other, surfaces one pair."""
    uid_a, uid_b = "aaaaaaaa", "bbbbbbbb"
    _write_trdd(repo, uid_a, external_refs="[janitor#241]")
    _write_trdd(repo, uid_b, external_refs="[janitor#241]")

    out = _run(repo)
    assert "[trdd-cross-card-blindspot]" in out
    assert f"TRDD-{uid_a}" in out
    assert f"TRDD-{uid_b}" in out
    assert "janitor#241" in out


def test_external_refs_cross_reference_silences_pair(repo: Path):
    """Card A's external-refs naming card B silences the pair entirely."""
    uid_a, uid_b = "cccccccc", "dddddddd"
    _write_trdd(repo, uid_a, external_refs=f"[janitor#241, TRDD-{uid_b}]")
    _write_trdd(repo, uid_b, external_refs="[janitor#241]")

    out = _run(repo)
    assert out.strip() == ""


def test_body_mention_silences_pair(repo: Path):
    """Card A's BODY mentioning TRDD-<B-id8> silences the pair, even with empty external-refs."""
    uid_a, uid_b = "eeeeeeee", "ffffffff"
    _write_trdd(
        repo, uid_a, external_refs="[janitor#241]",
        body=f"\n## STATE\nsee also TRDD-{uid_b} for the other half of this fix.\n",
    )
    _write_trdd(repo, uid_b, external_refs="[janitor#241]")

    out = _run(repo)
    assert out.strip() == ""


def test_terminal_card_excludes_pair(repo: Path):
    """One of the two cards being terminal (column: complete) silences the pair."""
    uid_a, uid_b = "11111111", "22222222"
    _write_trdd(repo, uid_a, column="complete", external_refs="[janitor#241]")
    _write_trdd(repo, uid_b, column="todo", external_refs="[janitor#241]")

    out = _run(repo)
    assert out.strip() == ""


def test_three_cards_sharing_ref_report_three_distinct_pairs(repo: Path):
    """Three open cards sharing one ref report exactly 3 pairs, no duplicates, no A/B + B/A."""
    uid_a, uid_b, uid_c = "33333333", "44444444", "55555555"
    _write_trdd(repo, uid_a, external_refs="[janitor#900]")
    _write_trdd(repo, uid_b, external_refs="[janitor#900]")
    _write_trdd(repo, uid_c, external_refs="[janitor#900]")

    out = _run(repo)
    assert "3 pair(s)" in out
    for pair in (
        f"TRDD-{uid_a} & TRDD-{uid_b}",
        f"TRDD-{uid_a} & TRDD-{uid_c}",
        f"TRDD-{uid_b} & TRDD-{uid_c}",
    ):
        assert pair in out
    # No reversed duplicate of any pair.
    assert f"TRDD-{uid_b} & TRDD-{uid_a}" not in out
    assert f"TRDD-{uid_c} & TRDD-{uid_a}" not in out
    assert f"TRDD-{uid_c} & TRDD-{uid_b}" not in out


def test_a_shared_trdd_ref_is_not_a_pair(repo: Path):
    """Two cards citing the same PARENT card is hub-and-spoke structure, not blindness.

    An umbrella card is cited by many unrelated children (one per contract row), so keying
    on a shared `TRDD-<id8>` pairs every child with every other and reports cards that have
    nothing to do with each other.

    It is also SELF-INFLICTED and unbounded, which is what makes it fatal rather than merely
    noisy: cross-linking is the remedy this detector RECOMMENDS, so each remedy adds a shared
    TRDD-ref and manufactures the next finding. Observed live immediately after shipping —
    cross-linking the janitor#246 pair created a brand-new pair whose only shared ref was the
    umbrella both had just been linked to. A check whose own advice re-arms it never
    converges, and a check that never converges gets switched off.
    """
    uid_a, uid_b = "11111111", "22222222"
    _write_trdd(repo, uid_a, external_refs="[TRDD-99999999]")
    _write_trdd(repo, uid_b, external_refs="[TRDD-99999999]")

    assert _run(repo).strip() == ""


def test_an_issue_ref_still_pairs_when_a_trdd_ref_is_also_shared(repo: Path):
    """The TRDD-ref exclusion must not swallow a REAL finding that rides alongside it —
    two cards sharing both an umbrella AND a genuine issue still surface on the issue."""
    uid_a, uid_b = "33333333", "44444444"
    _write_trdd(repo, uid_a, external_refs="[TRDD-99999999, janitor#777]")
    _write_trdd(repo, uid_b, external_refs="[TRDD-99999999, janitor#777]")

    out = _run(repo)
    assert "1 pair(s)" in out
    assert "janitor#777" in out
    assert "99999999" not in out
