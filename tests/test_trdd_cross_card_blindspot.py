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


def test_rg4iuz6i_3qiq2e6j_prelink_state_is_not_caught(repo: Path):
    """Characterization test (TRDD-4EKZ81MV) — the shared-ref mechanism CANNOT catch this
    real, confirmed miss, at any point before the two cards were cross-linked.

    Reconstructed from git history of the real cards: TRDD-RG4IUZ6I was created with
    `external-refs: [janitor#241, janitor#227]`; TRDD-3QIQ2E6J was created with
    `external-refs: [TRDD-WP7TCRME]` and only gained `janitor#241` in the SAME commit
    that added the `TRDD-RG4IUZ6I` cross-reference (854259d8). There was never a window
    where the two shared a ref without also already citing each other — the detector's
    grouping key never had anything to group on. This is NOT a regression to fix here;
    it documents why the detector's own docstring calls this a structural blind spot
    that needs a new (unratified) similarity signal, not a tweak to this detector.
    """
    rg4iuz6i, sanqiq = "rg4iuz61", "3qiq2e61"  # 8-char stand-ins for the real ids
    _write_trdd(repo, rg4iuz6i, external_refs="[janitor#241, janitor#227]")
    _write_trdd(repo, sanqiq, external_refs="[TRDD-WP7TCRME]")

    assert _run(repo).strip() == ""


def test_az6qrk0d_jpl0ju86_never_shared_a_ref(repo: Path):
    """Characterization test (TRDD-4EKZ81MV) — same structural miss, zero-overlap case.

    Reconstructed from git history of the real cards: TRDD-AZ6QRK0D was created with NO
    `external-refs:` at all; TRDD-JPL0JU86 was created with
    `external-refs: [janitor#249, TRDD-G4BCRUP7]`. The two never shared a ref, at
    creation or since — so the shared-ref grouping this detector implements has no
    signal to key on, regardless of how strongly the two cards' content overlaps.
    """
    az6qrk0d, jpl0ju86 = "az6qrk01", "jpl0ju81"  # 8-char stand-ins for the real ids
    _write_trdd(repo, az6qrk0d, external_refs="[]")
    _write_trdd(repo, jpl0ju86, external_refs="[janitor#249, TRDD-G4BCRUP7]")

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
