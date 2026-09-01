"""`/clear` is never typed unless the handoff is already on disk (TRDD-UQW5IOAE).

THE INVARIANT, and why it is the one that matters most in this whole feature: the clear is
UNRECOVERABLE and nothing reviews it first, so the handoff is the only thing standing between an
unattended shrink and a session losing everything it was working on. If the chain can ever fire
while the handoff write failed, the feature stops being "shrink a session" and becomes "destroy
one".

It holds today by CONSTRUCTION — `state.atomic_write` raises rather than swallowing, and the write
is a plain statement before `_fire`, so an OSError skips the clear. That is exactly why it needs a
test: the invariant is currently protected by the ABSENCE of a try/except, and the most natural
future "improvement" to a write that can fail is to wrap it in one. That refactor would look like
hardening and would silently convert a failed handoff into a destructive clear, with every other
test in the suite still green.

END-TO-END ON PURPOSE, not a pure-function check. This card's advisor verdict (2026-08-14) is
explicit that a mutation of a pure gate cannot catch a wiring defect — TRDD-OO301H7D was an
argument computed and never passed, and 53 of 54 pure-layer tests stayed green through it. So
these drive the real `main()` and assert on the ORDER of real effects.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import external_clear as ec  # noqa: E402
import external_handoff_clear as ehc  # noqa: E402
import handoff_files  # noqa: E402


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _firing_project(tmp_path, monkeypatch) -> tuple[Path, Path]:
    """A project the watcher will actually decide to clear, with a recorded pane.

    Every veto is satisfied with REAL inputs rather than by stubbing the gate: a long-idle
    transcript that does not end on an unanswered question, the feature switched on, and both
    external subprocesses (the agentlensPro probe and the llm-ext summariser) switched OFF so
    nothing machine-touching is spawned.
    """
    import memory_scopes  # noqa: PLC0415

    monkeypatch.setenv("HOME", str(tmp_path))
    # log_line resolves the log dir from THIS env, not from --project-root argv — without it
    # this file's fixture "fired:" lines (idle=9000, min_idle=60) landed in the REAL repo's
    # external-clear.log and read there as production long-idle misfires (2026-08-18).
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.setenv(ec.ENABLED_ENV, "true")
    monkeypatch.setenv(ec.CACHE_EXPIRED_COMMAND_ENV, "")  # no third-party probe
    # llm-ext is ON but its subprocess is STUBBED — the summariser must never really spawn here.
    # The original leak is worth keeping in view: these tests once spawned the machine's REAL
    # llm-ext against a pytest tmp transcript, which the suite's allow-list correctly refused
    # (SandboxViolation), after which the retry loop slept through its backoff — slow AND impure.
    #
    # It used to be switched OFF instead, because `compose_handoff` produced a template handoff
    # with no summary. TRDD-79LXF6PJ retired that template: no summary now means NO CLEAR, so an
    # OFF switch would make every test in this file assert nothing. Stubbing keeps the subject
    # intact — the ORDER of the payload write versus the chain spawn — without a subprocess.
    monkeypatch.setenv(ec.USE_LLM_EXT_ENV, "true")
    monkeypatch.setattr(
        ec,
        "summarize_with_retry",
        lambda *a, **k: ec.SummaryAttempt(text="stubbed llm-ext session summary", outcome="ok"),
    )
    monkeypatch.setenv(ec.MIN_CONTEXT_ENV, "0")  # size must not veto

    import cold_cache_compact  # noqa: PLC0415

    monkeypatch.setenv(cold_cache_compact.CLEAR_MIN_IDLE_ENV, "60")

    now = int(time.time())
    root = tmp_path / "proj"
    sd = root / ".janitor" / "state"
    sd.mkdir(parents=True)
    (root / "design" / "tasks").mkdir(parents=True)

    slug = memory_scopes.project_slug(os.path.realpath(str(root)))
    tdir = tmp_path / ".claude" / "projects" / slug
    tdir.mkdir(parents=True)
    (tdir / "s1.jsonl").write_text(
        json.dumps({"type": "assistant", "timestamp": _iso(now - 9000), "message": {}}) + "\n",
        encoding="utf-8",
    )
    # An old mtime is what makes the session look abandoned rather than merely quiet.
    os.utime(tdir / "s1.jsonl", (now - 9000, now - 9000))

    # A pane the chain could type into — without one the watcher declines before any of this.
    monkeypatch.setattr(
        ehc.ec, "terminal_from_record", lambda _rec: {"kind": "tmux", "pane": "%1"}
    )
    return root, sd


def _run_main(root: Path, monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["external_handoff_clear.py", "--project-root", str(root),
                                      "--force"])
    return ehc.main()


def test_the_summary_SOURCE_is_on_disk_before_the_clear_chain_is_spawned(
    tmp_path, monkeypatch
) -> None:
    """The ordering invariant, REWRITTEN for TRDD-2F3I2P18 rather than deleted.

    This test used to assert the finished HANDOFF was on disk before the fire. That was the
    2026-08-28 "never clear blind" rule, and the owner superseded it on 2026-09-01: llm-ext
    summarizes from the on-disk transcript, which `/clear` does not touch, so waiting for the
    summary bought no safety and cost the whole point of the clear — it arrived minutes late,
    after the cache write it exists to prevent.

    What must still be true before the destructive step is that the summary's SOURCE is named
    and readable. That is the claim asserted here, from INSIDE the fire, because both happening
    is not the same as the right one happening first.
    """
    root, sd = _firing_project(tmp_path, monkeypatch)
    seen: dict = {}

    def _spy_fire(_root, _sd, _terminal, _now, trigger=""):
        del trigger  # not part of this test's claim; named so the call shape is exact
        pending = sd / "summary-pending.json"
        seen["pending_at_fire"] = pending.is_file()
        if pending.is_file():
            rec = json.loads(pending.read_text(encoding="utf-8"))
            seen["transcript_at_fire"] = rec.get("transcript", "")
            seen["expires_at_fire"] = rec.get("expires", 0)

    monkeypatch.setattr(ehc, "_fire", _spy_fire)

    rc = _run_main(root, monkeypatch)

    assert rc == 0
    assert seen.get("pending_at_fire") is True, (
        "the clear chain was spawned before the summary source was captured — after the clear "
        "the newest transcript is the NEW EMPTY one, so a later capture summarizes nothing "
        "while reporting success."
    )
    assert Path(seen.get("transcript_at_fire", "")).is_file(), (
        "the captured path must be a readable transcript at fire time, not merely a string"
    )
    assert seen.get("expires_at_fire", 0) > 0, (
        "the hold must carry a TTL — an unbounded hold turns a failed summary into a "
        "permanently stuck session, which is worse than the cost this reorder avoids"
    )
def test_a_model_authored_handoff_survives_a_real_external_fire(tmp_path, monkeypatch) -> None:
    """TRDD-5RXBI65T acceptance box 1: the daemon's auto handoff must not destroy the model's.

    Drives the REAL `external_handoff_clear.main()`, not a fabricated second writer — the unit
    tests around `handoff_files` prove filenames are unique, which is a claim about NAMING, not
    about whether the two production writers actually take that path. This is the one that would
    have caught the original bug: before the fix, :428 wrote `agent-handoff.md` unconditionally,
    so the rich text below was simply gone by the time the chain spawned.
    """
    root, sd = _firing_project(tmp_path, monkeypatch)
    rich = "# Rich model handoff\n\nTRDD-5RXBI65T — the reasoning a snapshot cannot produce.\n"
    # Seeded on the LEGACY path on purpose: that is where `/janitor-write-handoff` wrote before
    # the fix, so this also covers the upgrade case where a pre-D handoff is on disk when the
    # daemon next fires.
    (sd / handoff_files.LEGACY_NAME).write_text(rich, encoding="utf-8")

    monkeypatch.setattr(ehc, "_fire", lambda *a, **k: None)
    assert _run_main(root, monkeypatch) == 0

    survivors = [p.read_text(encoding="utf-8") for p in sd.glob("agent-handoff*.md")]
    assert rich in survivors, (
        "the external composer destroyed the model-authored handoff — the exact TRDD-5RXBI65T "
        "defect: a cheap automatic artifact overwriting an expensive deliberate one, silently"
    )
    assert len(survivors) >= 2, "the auto-composed handoff should exist ALONGSIDE the rich one"


def test_a_failed_handoff_write_never_reaches_the_clear(tmp_path, monkeypatch) -> None:
    """The guard this file exists for. `atomic_write` currently RAISES, so the clear is skipped —
    wrapping it in a try/except would look like hardening and would silently make a failed
    handoff clear the session anyway."""
    root, _sd = _firing_project(tmp_path, monkeypatch)
    fired: list[bool] = []

    def _boom(_target, _value):
        raise OSError("disk full")

    monkeypatch.setattr(ehc.state, "atomic_write", _boom)
    monkeypatch.setattr(ehc, "_fire", lambda *_a, **_k: fired.append(True))

    with pytest.raises(OSError):
        _run_main(root, monkeypatch)

    assert fired == [], (
        "the clear chain was spawned even though writing the handoff FAILED — the session would "
        "be cleared with no handoff to resume from."
    )


def test_the_heartbeat_HOLDS_while_a_cleared_session_awaits_its_summary(
    tmp_path, monkeypatch
) -> None:
    """TRDD-2F3I2P18. Between the clear and the injection the session knows nothing, so resuming
    it would hand a blank context its old task list and every chore at once. The owner's ruling
    was explicit: the resume comes AFTER the injection."""
    import external_handoff_clear as ehc_mod

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    now = int(time.time())
    (sd / "summary-pending.json").write_text(
        json.dumps({"transcript": "/x.jsonl", "key": "abc", "captured": now,
                    "expires": now + 900}),
        encoding="utf-8",
    )
    assert ehc_mod.summary_hold_active(sd, now) is True


def test_the_hold_EXPIRES_rather_than_stranding_the_session(tmp_path) -> None:
    """The TTL is the whole reason the hold is safe to have. llm-ext dying must degrade the
    session to the mechanical precompact handoff, not hold it forever — an unbounded hold turns
    one expensive session into a permanently stuck one, which is worse than the cost the reorder
    exists to avoid."""
    import external_handoff_clear as ehc_mod

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    now = int(time.time())
    (sd / "summary-pending.json").write_text(
        json.dumps({"transcript": "/x.jsonl", "key": "abc", "captured": now - 1000,
                    "expires": now - 1}),
        encoding="utf-8",
    )
    assert ehc_mod.summary_hold_active(sd, now) is False


def test_an_unreadable_hold_record_FAILS_OPEN(tmp_path) -> None:
    """A hold is a REFUSAL to do work, so an unparseable record must never be able to stop the
    session. A corrupt byte wedging a host is the exact failure the TTL exists to bound."""
    import external_handoff_clear as ehc_mod

    sd = tmp_path / ".janitor" / "state"
    sd.mkdir(parents=True)
    (sd / "summary-pending.json").write_text("{ not json", encoding="utf-8")
    assert ehc_mod.summary_hold_active(sd, int(time.time())) is False
    assert ehc_mod.summary_hold_active(sd / "nope", int(time.time())) is False
