"""Refusal-aware PROJECT-proposal dedupe (ai-maestro-plugins#15).

A proposal a HUMAN refused (moved to `design/refused/`, premise judged false) must not be
re-authored every heartbeat under the same dedupe key: the second time PKGPOL-001 came around,
the human approved the false-premise dispatch on the title alone, and only a memory note
surfacing during recall stopped it. These are the same evidence-scoped semantics
`tickets.refusal_for()` already applies to HARNESS tickets, extended to the proposal path:

  - unchanged evidence  → suppressed (a settled verdict is not re-litigated),
  - changed evidence    → a NEW proposal, citing the prior refusal in its body,
  - janitor-WITHDRAWN   → never suppresses (retract() explicitly promises re-proposal).
"""

from __future__ import annotations

import re
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts" / "lib"))

import state  # noqa: E402
import ticket_proposal  # noqa: E402

NOW = 1_784_000_000


@pytest.fixture
def project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """An isolated project + HOME + global-state dir (same idiom as test_ticket_dispatch) so no
    test touches the real ticket queue, the real design roots, or the machine-wide flock."""
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()
    yield tmp_path
    for cached in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        cached.cache_clear()


def _propose(project: Path, *, evidence: list[str] | None = None, now: int = NOW):
    return ticket_proposal.propose(
        kind="security-workflow",
        title="a package-manager safety knob is disabled",
        detail="config disables a supply-chain safeguard",
        evidence=["package.json", ".npmrc"] if evidence is None else evidence,
        severity="medium",
        dedupe_key="PKGPOL-001:package-manager config",
        origin="package-manager-policy",
        project_dir=str(project),
        now=now,
    )


def _proposal_files(project: Path) -> list[Path]:
    d = project / "design" / "proposals"
    return sorted(d.glob("TRDD-*.md")) if d.is_dir() else []


def _refuse_by_hand(project: Path, uid: str) -> Path:
    """What a human/main-Claude does per the TRDD lifecycle: move the card to design/refused/
    and flip its column. Deliberately NOT a plugin API call — no refuse verb exists, and the
    scan must work against exactly this manual shape."""
    src = next(p for p in _proposal_files(project) if uid in p.name)
    dest_dir = project / "design" / "refused"
    dest_dir.mkdir(parents=True, exist_ok=True)
    text = src.read_text(encoding="utf-8")
    text = re.sub(r"(?m)^column: proposal$", "column: refused", text)
    text = text.replace(
        "**PROPOSED BY THE JANITOR — awaiting approval. NOT authorized to execute.**",
        "**REFUSED 2026-08-05 — THE PREMISE IS FALSE.** Measured first-hand; nothing is disabled.",
    )
    dest = dest_dir / src.name
    dest.write_text(text, encoding="utf-8")
    src.unlink()
    return dest


def test_a_human_refused_proposal_is_not_reproposed_on_unchanged_evidence(project: Path) -> None:
    """THE regression (ai-maestro-plugins#15): same key, same evidence, after a human refusal
    → no fresh proposal, no approve command — the settled verdict suppresses the re-raise."""
    first = _propose(project)
    assert first is not None and first[2] is True
    uid = first[0]
    _refuse_by_hand(project, uid)

    again = _propose(project, now=NOW + 600)
    assert again is not None
    r_uid, command, is_new = again
    assert command == "", "a refused finding must NOT carry an approve command"
    assert is_new is False
    assert r_uid == uid, "the suppression must cite the refusing card, not invent an id"
    assert _proposal_files(project) == [], "no fresh proposal may be authored"


def test_changed_evidence_reproposes_and_cites_the_prior_refusal(project: Path) -> None:
    """A refusal is a claim about the INPUTS examined, not about the key forever — the harness
    layer's exact rule (test_changed_evidence_reopens_because_it_is_a_NEW_finding), on the
    proposal path. The new card must carry the prior verdict so nobody approves on the title."""
    first = _propose(project)
    assert first is not None
    old_uid = first[0]
    _refuse_by_hand(project, old_uid)

    fresh = _propose(project, evidence=["pnpm-workspace.yaml", "minimumReleaseAge removed"], now=NOW + 600)
    assert fresh is not None
    new_uid, command, is_new = fresh
    assert is_new is True and new_uid != old_uid
    assert command.endswith(f"TRDD-{new_uid}")
    body = _proposal_files(project)[0].read_text(encoding="utf-8")
    assert "REFUSED" in body and f"TRDD-{old_uid}" in body, "the prior refusal must be cited in the body"


def test_a_janitor_withdrawn_card_never_suppresses(project: Path) -> None:
    """retract() moves a cleared finding to refused/ but PROMISES re-proposal when the condition
    reappears ("the janitor proposes it again with a NEW id"). Withdrawn ≠ refused: only a human
    verdict suppresses."""
    first = _propose(project)
    assert first is not None
    old_uid = first[0]
    assert ticket_proposal.retract("PKGPOL-001:package-manager config", project_dir=str(project), now=NOW + 60) == old_uid

    again = _propose(project, now=NOW + 600)
    assert again is not None
    new_uid, command, is_new = again
    assert is_new is True, "a withdrawn (not refused) card must not suppress re-proposal"
    assert new_uid != old_uid
    assert command.endswith(f"TRDD-{new_uid}")


def test_evidence_comparison_is_order_insensitive(project: Path) -> None:
    """Mirrors tickets.evidence_fingerprint(): a detector may emit the same facts in a different
    order, and order alone must not defeat the suppression (it would re-litigate the refusal
    every time a directory listing changed order)."""
    first = _propose(project, evidence=["package.json", ".npmrc"])
    assert first is not None
    _refuse_by_hand(project, first[0])

    again = _propose(project, evidence=[".npmrc", "package.json"], now=NOW + 600)
    assert again is not None
    assert again[1] == "", "reordered but identical evidence must still suppress"
    assert _proposal_files(project) == []
