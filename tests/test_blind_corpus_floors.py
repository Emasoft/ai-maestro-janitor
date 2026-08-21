"""Regression floors for the five rules fixed against the 2026-08-21 blind corpus.

TRDD-VAWIKRK2, acceptance box 4. Each of these rules previously matched ZERO of its class
while appearing on the coverage report as a claimed rule — the silent-false-negative
asymmetry the bench exists to expose. These floors exist so that state cannot return
quietly: a pattern edit that drops a class back toward zero fails here by name.

WHAT THESE NUMBERS ARE, AND ARE NOT
-----------------------------------
They are REGRESSION FLOORS. They are **not** out-of-sample recall, and must never be quoted
as such.

`agent_context_bench.split_of` documents the discipline — *"tune on `dev`, quote the number
from `holdout`"* — and these five rules were fixed while looking at EVERY sample in each
class. So this corpus is spent as a generalisation measure for these five rules: the honest
description of the numbers below is "the gap that was found is closed", which is worth
pinning and is not the same claim as "the rule now generalises".

The dev/holdout split at the time of fixing is recorded per rule below, because it does say
something even under contamination: where a fix is one general SHAPE it covers holdout
samples it was not individually shaped against (two-step: 6/6 holdout from four branches),
and where it does not, that is visible too (the exfil boundary fix: 0/4 holdout).

The FALSE-POSITIVE evidence is NOT contaminated and is the stronger half: every one of these
fixes was swept against ~23,800 real agent-context files on this machine, and the four
attempts that produced false positives there were reverted rather than shipped. That corpus
was never used to choose a pattern, only to reject one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import agent_config_patterns as acp  # noqa: E402

_CORPUS = _REPO / "tests" / "agent_context_bench" / "corpus-vawikrk2-20260821.jsonl"

# (corpus label, rule id that must catch it, floor, dev/holdout at fix time)
_FLOORS = [
    ("concealment-directive", "concealment-directive", 8, "dev 4/4, holdout 4/5"),
    ("prompt-injection-multilingual", "prompt-injection-multilingual", 9, "dev 7/7, holdout 2/2"),
    # NOT `exfil-webhook-sink`: that rule is a literal host blocklist and scoring 0 on an
    # attacker-chosen host is its documented design (janitor#226), not a defect. The rule
    # under test for this class is its structural companion.
    ("exfil-webhook-sink", "exfil-structural-probe", 2, "dev 2/5, holdout 0/4"),
    ("mcp-annotation-lying", "mcp-annotation-lying", 4, "dev 1/5, holdout 3/4"),
    ("two-step-code-injection", "two-step-code-injection", 7, "dev 1/1, holdout 6/6"),
]


def _samples() -> list[dict]:
    if not _CORPUS.exists():  # pragma: no cover - corpus is committed
        pytest.skip(f"blind corpus not present: {_CORPUS}")
    return [json.loads(line) for line in _CORPUS.read_text(encoding="utf-8").splitlines() if line.strip()]


@pytest.mark.parametrize(("label", "rule_id", "floor", "split"), _FLOORS,
                         ids=[f[0] for f in _FLOORS])
def test_class_recall_floor(label: str, rule_id: str, floor: int, split: str) -> None:
    """The class must not regress below the count measured when its gap was closed."""
    rule = next(r for r in acp.RULES if r.id == rule_id)
    hits = [s["id"] for s in _samples()
            if s["label"] == label and rule.pattern.search(s["content"])]
    assert len(hits) >= floor, (
        f"{rule_id} matched {len(hits)} of the '{label}' class, floor is {floor} "
        f"(split at fix time: {split}). A pattern edit has narrowed this rule — "
        f"matched: {sorted(hits)}"
    )


def test_no_false_positives_on_the_blind_benign_population() -> None:
    """The floors above must never be paid for with the benign population.

    Goes through `scan_text` rather than matching patterns directly, because a raw pattern
    match is NOT a finding: `file_kind` decides which rules run at all (`source` skips the
    injection and authority rules, which fire constantly inside code comments), and
    `provenance_verified` downgrades a corroborated described-attack. Asserting on raw
    matches reports four `dynamic-exec-in-body` "false positives" that the detector never
    emits — a gate that fails on correct behaviour gets deleted, so it has to measure the
    thing the detector actually does. Mirrors `agent_context_bench.score`.

    Whole-catalog rather than per-rule: a widening that moves a false positive from one rule
    id to another has not fixed anything, and a per-rule assertion would call that a pass.
    """
    offenders = {}
    for s in _samples():
        if not s["label"].startswith("benign"):
            continue
        findings = acp.scan_text(
            s["content"],
            file_kind=s.get("kind") or "prose",
            filename="",
            provenance_verified=True,
        )
        fired = sorted({f.rule_id for f in findings
                        if f.severity.upper() not in ("LOW", "INFO")})
        if fired:
            offenders[s["id"]] = fired
    assert not offenders, f"benign samples produced findings: {offenders}"
