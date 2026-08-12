"""The quiet heartbeat filter (owner directive 2026-08-12).

The contract has two halves and the second is the dangerous one: routine advisories must
stop reaching the conversation, and NOTHING ELSE may. A filter that also swallows a marker
silently stops work; one that swallows an alarm hides a breach. Both look identical to a
clean run from the outside, so they are pinned here explicitly.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import dispatch  # noqa: E402


def _quiet(monkeypatch, recorded: list | None = None):
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_VERBOSE", raising=False)
    if recorded is not None:
        monkeypatch.setattr(
            dispatch.findings_ledger, "record",
            lambda **kw: recorded.append(kw) or "x",
        )


def test_advisory_chatter_is_dropped_from_stdout(monkeypatch):
    """The literal complaint: reminders and counts dumped into the conversation."""
    _quiet(monkeypatch, [])
    out = dispatch._quiet_filter(
        "trdd-reminder", "[trdd-reminder] 7 TRDD(s) currently active: TRDD-AAAA (idle 0d)\n"
    )
    assert out == ""


def test_a_dropped_advisory_is_RECORDED_not_discarded(monkeypatch):
    """Trading noise for blindness would be a worse bug than the noise. The line the user
    no longer sees must still be readable via /janitor-findings."""
    rec: list = []
    _quiet(monkeypatch, rec)
    dispatch._quiet_filter("memorize-nudge", "[memorize-nudge] 40 commits changed code\n")
    assert len(rec) == 1
    assert rec[0]["src"] == "memorize-nudge"
    assert "40 commits" in rec[0]["msg"]


def test_a_bare_marker_is_NEVER_suppressed(monkeypatch):
    """Markers are ACTIONS. Dropping one silently stops work, and a stopped janitor looks
    exactly like a quiet one — the single failure this filter must not have."""
    _quiet(monkeypatch, [])
    for marker in ("[janitor-resume]", "[janitor-memory-repair]", "[janitor-ticket]"):
        out = dispatch._quiet_filter("trdd-reminder", f"{marker}\n")
        assert out.strip() == marker, f"{marker} was suppressed"


def test_an_urgent_line_survives_even_from_an_advisory_detector(monkeypatch):
    """The advisory list must not be able to muzzle a real alarm."""
    _quiet(monkeypatch, [])
    for line in (
        "[findings] HIGH RESUME-ORPHANED: resume never delivered",
        "memgrep lint: 3 finding(s) at ERROR",
        "CRITICAL: memory scope leak detected",
        "ci-status: the pushed commit FAILED its checks",
    ):
        assert dispatch._quiet_filter("memory-librarian", line + "\n").strip() == line


def test_non_advisory_detectors_are_untouched(monkeypatch):
    """DEFAULT LOUD. A detector is silenced only by being listed — so a security detector
    added later is noisy by omission, never silent by omission."""
    _quiet(monkeypatch, [])
    text = "supply chain: unpinned action at .github/workflows/ci.yml\n"
    assert dispatch._quiet_filter("supply-chain-fingerprints", text) == text
    assert dispatch._quiet_filter("janitor-self-integrity", text) == text


def test_no_security_detector_is_on_the_advisory_list():
    """A standing guard on the LIST itself, not on the filter: the whole design rests on
    security-class detectors never appearing here, and a list is edited by people."""
    security = {
        "workflow-security", "branch-protection", "remote-credentials", "memory-scope-leak",
        "supply-chain-fingerprints", "historical-cache-scan", "typosquat-watcher",
        "mcp-rugpull", "repo-trust-score", "binary-magic-scanner", "provenance-audit",
        "janitor-self-integrity", "agent-context-integrity", "ai-context-poisoning",
        "keychain-health", "package-manager-policy", "fleet-github-config",
    }
    leaked = security & dispatch._ADVISORY_DETECTORS
    assert not leaked, f"security detectors must never be silenced: {sorted(leaked)}"


def test_verbose_opt_out_restores_everything(monkeypatch):
    """An escape hatch, because a filter you cannot turn off is a filter you cannot debug."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_VERBOSE", "1")
    text = "[trdd-reminder] 7 TRDD(s) currently active\n"
    assert dispatch._quiet_filter("trdd-reminder", text) == text
