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


def test_a_NEGATED_severity_word_does_not_claim_urgency(monkeypatch):
    """`none at or above ERROR` says nothing is wrong — it must not ride the urgency override.

    janitor#276. `memgrep lint` ALWAYS prints a summary, deliberately: a linter silent on
    success is indistinguishable from one that never ran (janitor#191). Its clean-corpus line
    is `memgrep lint: N finding(s), none at or above ERROR (...)`. `_URGENT_LINE_RE` matched
    the word ERROR inside a clause that NEGATES it, so the single most routine line in the
    system was promoted past quiet mode on every fire — reported as an advisory that "re-emits
    the identical line on every fire and can never be driven down".

    The reported cause was a chore-ownership gap. It is not: it is a regex matching a word
    while the sentence around it says the opposite.
    """
    _quiet(monkeypatch, [])
    clean = "memgrep lint: 71 finding(s), none at or above ERROR (3 scope(s): LOCAL/PROJECT/USER)"
    assert dispatch._quiet_filter("wikimem-syntax", clean + "\n") == ""


def test_a_REAL_severity_count_still_claims_urgency(monkeypatch):
    """The twin of the above — the fix must not muzzle the line that reports actual errors.

    Without this, suppressing the negated form could be 'fixed' by suppressing the whole
    advisory, which is the blindness the quiet filter exists to avoid.

    SCOPE NARROWED 2026-08-29 (TRDD-VJL1YTCG Part C): the guard is right and its subject was
    wrong. It is asserted here on `memory-librarian` — a detector whose findings the reader can
    act on — because `wikimem-syntax` moved to `_OTHER_ACTOR_DETECTORS`; see the test below for
    why that is not the blindness this guards against.
    """
    _quiet(monkeypatch, [])
    loud = "memgrep lint: 557 finding(s), 3 at or above ERROR (3 scope(s): LOCAL/PROJECT/USER)"
    assert dispatch._quiet_filter("memory-librarian", loud + "\n").strip() == loud


def test_another_actors_finding_does_not_claim_urgency_however_loud(monkeypatch):
    """A line the reader is NOT ALLOWED to act on must not ride the urgency override.

    This deliberately reverses what the test above used to assert about `wikimem-syntax`, so the
    reasoning belongs here rather than in a commit message.

    The old assertion protected a real property — do not let a fix for the clean line blind us to
    the dirty one — but it was applied to a detector whose findings are the LIBRARIAN's work, by
    owner directive (TRDD-VJL1YTCG Part C): "all the migrations and corrections of errors reported
    by the memgrep linter must be carried in background invisibly by the wikimem librarians
    agents, not by the main agent." Urgency is a claim on the READER's attention; a reader with no
    permitted response gains nothing from it, and pays on every fire. Measured 2026-08-29:
    `1009 at or above ERROR` printed into a live session for hours, and not one of those fires
    produced or could have produced an action.

    This is NOT the blindness the quiet filter exists to avoid: the line is still recorded in the
    findings ledger and read on demand via `/janitor-findings`. Suppressed here means "routed to
    the actor who owns it", not "discarded" — which is exactly the distinction the test above
    still enforces for detectors the main agent DOES own.

    Note the count is deliberately huge: severity words inside a COUNT are not a severity claim,
    and no threshold on the number would have made this line actionable.
    """
    _quiet(monkeypatch, [])
    loud = "memgrep lint: 1053 finding(s), 1009 at or above ERROR (3 scope(s): LOCAL/PROJECT/USER)"
    assert dispatch._quiet_filter("wikimem-syntax", loud + "\n") == ""


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
