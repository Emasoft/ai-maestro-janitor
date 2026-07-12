"""Tests for the shared agentlensPro probe lib (TRDD-WUUR2DFX).

Real, no mocks: the parsers are pure functions exercised against fixtures
captured from the LIVE `agentlenspro` CLI (2026-07-12); the `probe_json`
subprocess wrapper is exercised with REAL scripts written to a temp dir (a
printing script, a failing script, a garbage script, an array-not-object
script, a missing binary, a hanging script), never a mock.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts" / "lib"))

import agentlens_probe as ap  # noqa: E402

# Fixtures — trimmed but shape-faithful captures of the real CLI (verified 2026-07-12).
BURN_STATUS = {
    "now": 1783819455792,
    "activeSessions": 1,
    "accountWindows": [
        {"accountUuid": "80ddbe47", "fiveMinTokensPerMin": 302492, "events": 7789,
         "accountLabel": "emanuele.sabetta@gmail.com"},
    ],
    "topSessions": [
        {"sessionId": "c8a95d7e-048f-4c47-ae33-1dfacbcab3b1",
         "workspace": "/Users/x/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor"},
    ],
    "global": {"costPerHour": 10.4523},
    # Window budget is null without configured capacity — the janitor never reads it.
    "window": {"capacitySource": "none", "capacityConfigured": False},
}

INVESTIGATE_BURN = {
    "verdict": "Top culprits: 1. FORK_STORM (5.1M equiv, 18%) …",
    "attribution": [
        {"workspace": "~/Code/ANIME2SVG", "model": "claude-opus-4-8",
         "kind": "interactive", "requests": 78},
    ],
    "findings": [
        {"equivTokens": 5069468, "shareOfWindow": 0.18244987215209763,
         "cause": "FORK_STORM", "confidence": "high", "verdict": "12 full-prefix cache writes…"},
    ],
}


# ---------- _num ----------


def test_num_accepts_int_and_float() -> None:
    """Plain numbers coerce to float."""
    assert ap._num(10) == 10.0
    assert ap._num(10.4523) == 10.4523


def test_num_rejects_bool_and_nonnumeric() -> None:
    """A stray bool must NOT read as 1.0; strings/None are not numbers here."""
    assert ap._num(True) is None
    assert ap._num(False) is None
    assert ap._num("10") is None
    assert ap._num(None) is None


def test_num_rejects_nan_and_inf() -> None:
    """NaN / ±inf are not finite numbers → None."""
    assert ap._num(float("nan")) is None
    assert ap._num(float("inf")) is None
    assert ap._num(float("-inf")) is None


# ---------- parse_burn_status ----------


def test_parse_burn_status_full() -> None:
    """The verified fixture yields cost, active count, and the top session."""
    bs = ap.parse_burn_status(BURN_STATUS)
    assert bs is not None
    assert bs.cost_per_hour == 10.4523
    assert bs.active_sessions == 1
    assert bs.top_workspace == "/Users/x/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor"
    assert bs.top_session_id == "c8a95d7e-048f-4c47-ae33-1dfacbcab3b1"


def test_parse_burn_status_ignores_null_window() -> None:
    """capacitySource:none window is irrelevant — a cost/top still parses."""
    bs = ap.parse_burn_status(BURN_STATUS)
    assert bs is not None and bs.cost_per_hour is not None  # window never consulted


def test_parse_burn_status_none_on_nondict() -> None:
    """A non-dict payload (None / list / str / int) → None."""
    for bad in (None, [], "x", 5, ["topSessions"]):
        assert ap.parse_burn_status(bad) is None


def test_parse_burn_status_none_on_empty_shell() -> None:
    """No cost AND no top session → None (nothing worth returning)."""
    assert ap.parse_burn_status({}) is None
    assert ap.parse_burn_status({"window": {"capacitySource": "none"}}) is None


def test_parse_burn_status_cost_only() -> None:
    """Cost present, topSessions absent → BurnStatus with a None top."""
    bs = ap.parse_burn_status({"global": {"costPerHour": 3.5}})
    assert bs is not None
    assert bs.cost_per_hour == 3.5
    assert bs.top_workspace is None and bs.top_session_id is None


def test_parse_burn_status_top_only() -> None:
    """A top session with no cost still yields a BurnStatus (culprit is usable)."""
    bs = ap.parse_burn_status({"topSessions": [{"workspace": "/w", "sessionId": "s"}]})
    assert bs is not None
    assert bs.cost_per_hour is None and bs.top_workspace == "/w"


def test_parse_burn_status_bool_cost_rejected() -> None:
    """A bool costPerHour is not a number → cost None (and thus shell rule applies)."""
    assert ap.parse_burn_status({"global": {"costPerHour": True}}) is None


# ---------- parse_investigate_cause ----------


def test_parse_investigate_cause_full() -> None:
    """The verified fixture yields the top culprit with share/confidence/workspace."""
    c = ap.parse_investigate_cause(INVESTIGATE_BURN)
    assert c is not None
    assert c.cause == "FORK_STORM"
    assert c.confidence == "high"
    assert c.workspace == "~/Code/ANIME2SVG"
    assert c.share is not None and 0.18 < c.share < 0.19


def test_parse_investigate_cause_none_on_nondict() -> None:
    """Non-dict → None."""
    for bad in (None, [], "x", 7):
        assert ap.parse_investigate_cause(bad) is None


def test_parse_investigate_cause_none_without_findings() -> None:
    """No findings / empty findings / a finding without a cause → None."""
    assert ap.parse_investigate_cause({"verdict": "…"}) is None
    assert ap.parse_investigate_cause({"findings": []}) is None
    assert ap.parse_investigate_cause({"findings": [{"confidence": "high"}]}) is None
    assert ap.parse_investigate_cause({"findings": [{"cause": "  "}]}) is None


def test_parse_investigate_cause_out_of_range_share_dropped() -> None:
    """A share outside [0,1] is dropped to None, not trusted blindly."""
    c = ap.parse_investigate_cause({"findings": [{"cause": "X", "shareOfWindow": 5.0}]})
    assert c is not None and c.share is None


def test_parse_investigate_cause_missing_optional_fields() -> None:
    """cause only → a BurnCause with None share/confidence/workspace."""
    c = ap.parse_investigate_cause({"findings": [{"cause": "IMAGE_BLOB_RESIDENT"}]})
    assert c is not None
    assert c.cause == "IMAGE_BLOB_RESIDENT"
    assert c.share is None and c.confidence is None and c.workspace is None


# ---------- format_cause_clause ----------


def test_format_cause_clause_full() -> None:
    """A full cause renders the compact, leading-space suffix."""
    c = ap.BurnCause(cause="FORK_STORM", share=0.18, confidence="high", workspace="~/Code/x")
    clause = ap.format_cause_clause(c)
    assert clause == " agentlensPro cause: FORK_STORM (18% of window, high) in ~/Code/x."


def test_format_cause_clause_minimal() -> None:
    """Cause only → no parenthetical, no workspace."""
    c = ap.BurnCause(cause="FAT_SESSION_REWRITES", share=None, confidence=None, workspace=None)
    assert ap.format_cause_clause(c) == " agentlensPro cause: FAT_SESSION_REWRITES."


# ---------- probe_json (real subprocess) ----------


def _write_script(tmp_path: Path, name: str, body: str) -> str:
    script = tmp_path / name
    script.write_text("#!/bin/sh\n" + body + "\n")
    script.chmod(0o755)
    return str(script)


def test_probe_json_parses_object(tmp_path: Path) -> None:
    """A real script printing a JSON object yields the parsed dict."""
    cmd = _write_script(tmp_path, "ok.sh", "echo '{\"global\":{\"costPerHour\":1.5}}'")
    data = ap.probe_json(cmd)
    assert isinstance(data, dict) and data["global"]["costPerHour"] == 1.5


def test_probe_json_none_on_empty_command() -> None:
    """An empty / whitespace command disables the probe → None."""
    assert ap.probe_json("") is None
    assert ap.probe_json("   ") is None


def test_probe_json_none_on_nonzero_exit(tmp_path: Path) -> None:
    """A failing command → None (fail-open)."""
    cmd = _write_script(tmp_path, "fail.sh", "echo '{}'; exit 3")
    assert ap.probe_json(cmd) is None


def test_probe_json_none_on_garbage(tmp_path: Path) -> None:
    """Non-JSON stdout → None."""
    cmd = _write_script(tmp_path, "garbage.sh", "echo 'not json'")
    assert ap.probe_json(cmd) is None


def test_probe_json_none_on_array(tmp_path: Path) -> None:
    """A JSON array (non-object top level) → None — every consumed tool returns an object."""
    cmd = _write_script(tmp_path, "arr.sh", "echo '[1,2,3]'")
    assert ap.probe_json(cmd) is None


def test_probe_json_none_on_missing_binary() -> None:
    """A missing executable → None, never an exception."""
    assert ap.probe_json("/definitely/not/a/real/binary/xyzzy get_burn_status") is None


def test_probe_json_none_on_timeout(tmp_path: Path) -> None:
    """A command that hangs past the timeout → None (the daemon must never wedge)."""
    cmd = _write_script(tmp_path, "hang.sh", "sleep 5; echo '{}'")
    assert ap.probe_json(cmd, timeout=0.5) is None
