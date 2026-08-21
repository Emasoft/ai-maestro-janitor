"""Tests for the shared agentlensPro probe lib (TRDD-WUUR2DFX).

Real, no mocks: the parsers are pure functions exercised against fixtures
captured from the LIVE `agentlenspro` CLI (2026-07-12); the `probe_json`
subprocess wrapper is exercised with REAL scripts written to a temp dir (a
printing script, a failing script, a garbage script, an array-not-object
script, a missing binary, a hanging script), never a mock.
"""

import sys
from pathlib import Path

import pytest

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
         "cause": "FORK_STORM", "confidence": "high", "verdict": "12 full-prefix cache writes…",
         # A finding carries its OWN locations, and the live tool routinely lists
         # several plus a truncation marker. The fixture omitted `evidence`
         # entirely, so the old test could not tell that the workspace was being
         # borrowed from the unrelated `attribution` list above (janitor#121).
         "evidence": {"workspaces": [
             "/Users/x/Code/AgentlensPro",
             "/Users/x/Code/AI-MAESTRO-PLUGIN/ai-maestro-plugin",
             "/Users/x/ai-maestro",
             '… +2 more — use verbosity:"full"',
         ]}},
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
    """The verified fixture yields the top culprit with share/confidence.

    Its finding spans several workspaces, so NO single one is named — and in
    particular not `attribution[0]` (`~/Code/ANIME2SVG`), which ranks a different
    list and has never been evidence for where this cause occurred.
    """
    c = ap.parse_investigate_cause(INVESTIGATE_BURN)
    assert c is not None
    assert c.cause == "FORK_STORM"
    assert c.confidence == "high"
    assert c.share is not None and 0.18 < c.share < 0.19
    assert c.workspace is None
    assert c.multi_workspace is True


def test_parse_investigate_cause_never_borrows_the_attribution_workspace() -> None:
    """A cause is never located by `attribution[0]` — a separately-ranked list.

    Splicing the two produced a claim neither makes. Here the finding names ONE
    workspace and `attribution` names a different one; the finding's own evidence
    must win, so a passing test cannot be satisfied by the old borrow.
    """
    c = ap.parse_investigate_cause({
        "attribution": [{"workspace": "~/Code/UNRELATED"}],
        "findings": [{"cause": "FORK_STORM", "evidence": {"workspaces": ["/Users/x/real"]}}],
    })
    assert c is not None
    assert c.workspace == "/Users/x/real"
    assert c.multi_workspace is False


def test_parse_investigate_cause_unattributable_sentinel_is_not_a_location() -> None:
    """`(subagent/no-env-block)` means "could not attribute" — never print it as a place.

    This is the shape a consumer acted on (janitor#121): they read a confident
    `PREMIUM_MODEL_FANOUT … in (subagent/no-env-block)`, throttled off agent
    launches and deferred authorized chores, while the real spend was main-loop
    work. A sentinel rendered as a location is a wrong mitigation, not a cosmetic
    blemish.
    """
    c = ap.parse_investigate_cause({
        "findings": [{"cause": "PREMIUM_MODEL_FANOUT",
                      "evidence": {"workspaces": ["(subagent/no-env-block)"]}}],
    })
    assert c is not None
    assert c.workspace is None
    assert c.multi_workspace is False
    assert "subagent/no-env-block" not in ap.format_cause_clause(c)


def test_parse_investigate_cause_truncation_marker_is_not_a_workspace() -> None:
    """One real path + a `+N more` marker is SEVERAL, not one — never name the one."""
    c = ap.parse_investigate_cause({
        "findings": [{"cause": "X", "evidence": {"workspaces": [
            "/Users/x/only-one-shown", '… +4 more — use verbosity:"full"']}}],
    })
    assert c is not None
    assert c.workspace is None and c.multi_workspace is True


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
    # No evidence at all is "unknown", not "several" — silence, not a hedge.
    assert c.multi_workspace is False


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


def test_format_cause_clause_multi_workspace_says_so_instead_of_naming_one() -> None:
    """A cause spanning several places reports that, rather than picking one.

    The reader's next action is "go look at X", so an invented X sends them
    somewhere the burn did not happen.
    """
    c = ap.BurnCause(cause="FORK_STORM", share=0.18, confidence="high",
                     workspace=None, multi_workspace=True)
    assert ap.format_cause_clause(c) == (
        " agentlensPro cause: FORK_STORM (18% of window, high) spanning several workspaces."
    )


# ---------- probe_json (real subprocess) ----------


def _write_script(tmp_path: Path, name: str, body: str) -> str:
    """Return a COMMAND that runs `body` — as DATA passed to /bin/sh, never a new executable.

    Not `chmod +x` + a bare path: the first exec of a newly-created executable pays a one-time
    macOS scan, measured at 0.22-0.25 s (40/40) with a tail reaching ~15 s under load. That
    races the very timeouts these tests exercise, and when it wins the probe fails open to None
    and the test asserts on empty output with nothing naming a timeout (TRDD-WMQQYLSZ).
    Passing the file to an already-trusted interpreter measured 0.00 s (12/12) and is
    load-immune, because no new executable is ever created. Callers are unchanged — the return
    value was always a command string, and `shlex.split` handles the extra token.
    """
    script = tmp_path / name
    script.write_text("#!/bin/sh\n" + body + "\n")
    return f"/bin/sh {script}"


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


# This test DRIVES a timeout — it is the subject, not an incidental ceiling — so it opts out
# of the suite-wide scaling (TRDD-7NSRD8OV). Scaled, its 0.5 s becomes 5 s, the hang script
# finishes inside that, and the assertion would pass having proven nothing.
@pytest.mark.no_timeout_scale
def test_probe_json_none_on_timeout(tmp_path: Path) -> None:
    """A command that hangs past the timeout → None (the daemon must never wedge)."""
    cmd = _write_script(tmp_path, "hang.sh", "sleep 5; echo '{}'")
    assert ap.probe_json(cmd, timeout=0.5) is None


# --- probe_cache_expired: the answer is the LAST non-empty stdout line ------------------
#
# WHY THESE EXIST, stated accurately (the first draft of this block was wrong and is corrected
# here the same day). The tolerant parse was written as a fix for a preamble on stdout; measuring
# the live CLI showed the preamble goes to STDERR and stdout carries the bare verdict, so the
# previous `stdout.strip().lower()` was already correct. The observed `None` came from the
# probe's TIMEOUT, not from parsing.
#
# The parse is still worth pinning, for the property it has regardless of that history: EVERY
# failure of this probe returns None, None means "no signal", and no-signal is indistinguishable
# from "agentlensPro is not installed" — so if the CLI ever adds a stdout line, the trigger goes
# quiet and NOTHING reports it. These tests pin the shapes that must not silently answer None.


def test_cache_expired_reads_the_verdict_after_a_preamble(tmp_path: Path) -> None:
    """A stdout preamble ahead of `false` must still yield False.

    NOT the shape the CLI emits today (its preamble is on stderr) — this pins tolerance to the
    day it changes, because that change would otherwise turn the trigger off silently.
    """
    cmd = _write_script(
        tmp_path,
        "verbose-false.sh",
        "echo 'session 35e1e917 in /tmp/x — idle 32s vs 60min TTL'\necho false",
    )
    assert ap.probe_cache_expired(cmd) is False


def test_cache_expired_reads_a_true_verdict_after_a_preamble(tmp_path: Path) -> None:
    """The same preamble shape with `true` yields True — a real expiry is still detected."""
    cmd = _write_script(
        tmp_path,
        "verbose-true.sh",
        "echo 'session 35e1e917 in /tmp/x — idle 9h vs 60min TTL'\necho TRUE",
    )
    assert ap.probe_cache_expired(cmd) is True


def test_cache_expired_ignores_trailing_blank_lines(tmp_path: Path) -> None:
    """Trailing blank lines are not the answer — the LAST NON-EMPTY line is."""
    cmd = _write_script(tmp_path, "trailing.sh", "echo preamble\necho false\necho ''\necho '  '")
    assert ap.probe_cache_expired(cmd) is False


def test_cache_expired_zero_exit_does_not_mean_expired(tmp_path: Path) -> None:
    """rc=0 is only 'I answered'. `--help` documents rc=0 as EXPIRED, but that applies to -q
    only: the verbose form exits 0 while printing `false`. Reading rc here would report a cache
    miss on every healthy session, and the consumer of this signal fires an irreversible
    /clear."""
    cmd = _write_script(tmp_path, "zero-false.sh", "echo false; exit 0")
    assert ap.probe_cache_expired(cmd) is False


def test_cache_expired_none_when_the_cli_cannot_answer(tmp_path: Path) -> None:
    """Cannot-answer is a non-zero exit with empty stdout → None, never a fabricated False."""
    cmd = _write_script(tmp_path, "cannot.sh", "exit 2")
    assert ap.probe_cache_expired(cmd) is None


def test_cache_expired_none_on_missing_binary() -> None:
    """A missing executable → None (fail-open), never an exception."""
    assert ap.probe_cache_expired("/definitely/not/a/real/binary/xyzzy cache-expired") is None


@pytest.mark.no_timeout_scale  # drives a timeout — see the twin above (TRDD-7NSRD8OV)
def test_cache_expired_none_on_timeout(tmp_path: Path) -> None:
    """A hanging probe → None. It runs in a SessionStart hook, which must never wedge."""
    cmd = _write_script(tmp_path, "hang-cache.sh", "sleep 5; echo false")
    assert ap.probe_cache_expired(cmd, timeout=0.5) is None


def test_the_cache_expired_timeout_clears_the_measured_latency_with_headroom() -> None:
    """The timeout is THE failure mode of this probe, so it is pinned as a number.

    A timeout returns None; None means "no signal"; no signal is indistinguishable from
    "agentlensPro is not installed" — so an under-set timeout does not degrade the trigger, it
    deletes it, silently. Measured calls on this host reached 26.14 s, and the previous 30 s
    ceiling left ~4 s of headroom, i.e. one slow call from reporting "unknown" and doing nothing.

    Pinned against the WORST OBSERVED latency rather than a round number, so a future edit that
    tightens this has to argue with the measurement instead of a taste for small timeouts.
    """
    worst_observed_s = 26.14
    assert ap._CACHE_EXPIRED_TIMEOUT_S >= worst_observed_s * 3, (
        "a timeout near the observed latency silently disables the cache-expiry trigger"
    )
    assert ap._CACHE_EXPIRED_TIMEOUT_S > ap._TIMEOUT_S, (
        "it must stay SEPARATE from the burn-probe timeout — tuning those must not re-break this"
    )


def test_cache_expired_passes_the_project_through(tmp_path: Path) -> None:
    """`--project <path>` is appended, so the probe answers about the RIGHT session — a probe
    that silently answered about the daemon's cwd would be worse than no probe at all."""
    cmd = _write_script(tmp_path, "echo-argv.sh", 'echo preamble\n[ "$1" = "--project" ] && [ "$2" = "/tmp/proj" ] && echo true || echo false')
    assert ap.probe_cache_expired(cmd, project="/tmp/proj") is True
