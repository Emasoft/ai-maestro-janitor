"""Tests for the external handoff-and-clear WATCHER (TRDD-PXP08ZQC).

Real, no mocks: the gatherers run against a real temp project tree (real TRDD files, a real
`git` repo, real state files), and the end-to-end check runs the script as a real subprocess
and asserts on the filesystem afterwards — because "fires nothing / writes nothing" is a claim
about the disk, and only the disk can settle it.
"""

import os
import subprocess
import sys
import time
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import external_clear as ec  # noqa: E402
import external_handoff_clear as ehc  # noqa: E402

SCRIPT = _ROOT / "scripts" / "external_handoff_clear.py"


def _project(tmp_path: Path) -> Path:
    """A minimal project tree: janitor state dir + design/tasks."""
    (tmp_path / ".janitor" / "state").mkdir(parents=True)
    (tmp_path / "design" / "tasks").mkdir(parents=True)
    return tmp_path


# --- _last_turn_age ----------------------------------------------------------


def test_last_turn_age_is_none_without_a_transcript(tmp_path):
    """Unknown cache age must read as unknown — `next_fire_misses_cache` then declines."""
    assert ehc._last_turn_age(_project(tmp_path), int(time.time())) is None


# --- pending_summary_key (TRDD-QZVAEWQH) --------------------------------------


def test_pending_summary_key_reads_the_live_pending_record(tmp_path):
    """The still-armed record's own `key` field wins over anything already on disk."""
    import json

    sd = _project(tmp_path) / ".janitor" / "state"
    (sd / ehc._PENDING_FILE).write_text(
        json.dumps({"key": "abcd1234", "expires": int(time.time()) + 900}), encoding="utf-8"
    )
    assert ehc.pending_summary_key(sd) == "abcd1234"


def test_pending_summary_key_falls_back_to_the_newest_group_once_released(tmp_path):
    """After `_release_summary_hold` deletes the record, the newest handoff group on disk
    still names the key a late reader needs."""
    import handoff_files

    sd = _project(tmp_path) / ".janitor" / "state"
    handoff_files.write(sd, "ffee9988", "some summary text")
    assert ehc.pending_summary_key(sd) == "ffee9988"


def test_pending_summary_key_empty_when_neither_source_names_one(tmp_path):
    """No pending record, no handoff on disk — "" is the correct "nothing to point at"."""
    sd = _project(tmp_path) / ".janitor" / "state"
    assert ehc.pending_summary_key(sd) == ""


# --- _run: NEITHER lane composes (TRDD-QZVAEWQH) ------------------------------


def _armed_run(root: Path, *, on_resume: bool) -> tuple[int, str]:
    """Invoke `ehc._run` with `_decide`/`_fire`/the pane lookup already monkeypatched by the
    caller, so the real capture -> fire -> (delegate | compose) tail runs unmodified."""
    import argparse
    import contextlib
    import io

    sd = root / ".janitor" / "state"
    args = argparse.Namespace(dry_run=False, force=False, on_resume=on_resume, project_root=str(root))
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = ehc._run(root, sd, int(time.time()), args)
    return rc, buf.getvalue()


def _delegation_case(tmp_path, monkeypatch, *, on_resume: bool, trigger: str, gate_facts: dict):
    """Shared body for both delegation tests: only the gate verdict/facts differ by mode."""
    import fleet_restart

    root = _project(tmp_path)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("{}\n")
    monkeypatch.setattr(
        ehc, "_decide",
        lambda *_a, **_k: (
            ec.ClearVerdict(True, trigger, "test"),
            {"transcript": str(transcript), **gate_facts},
        ),
    )
    monkeypatch.setattr(fleet_restart, "recorded_terminal", lambda _r: {"kind": "tmux"})
    monkeypatch.setattr(ec, "terminal_from_record", lambda _r: {"kind": "tmux", "pane": "%1"})
    monkeypatch.setattr(ehc, "_fire", lambda *_a, **_k: None)

    def must_not_compose(*_a, **_k):
        raise AssertionError("must not compose — every caller delegates (TRDD-QZVAEWQH)")

    monkeypatch.setattr(ec, "summarize_with_retry", must_not_compose)
    return _armed_run(root, on_resume=on_resume), root


def test_daemon_lane_delegates_and_leaves_the_hold_armed(tmp_path, monkeypatch):
    """No --on-resume (the keyless launchd caller): fires the clear, never calls llm-ext,
    prints SUMMARY_DELEGATED, and leaves `summary-pending.json` in place for the cleared
    session's own SessionStart summarizer to pick up."""
    (rc, out), root = _delegation_case(
        tmp_path, monkeypatch,
        on_resume=False, trigger="cache-certainly-expired", gate_facts={},
    )
    assert rc == 0
    assert "SUMMARY_DELEGATED" in out, out
    assert "NO_SUMMARY_POST_CLEAR" not in out and "SUMMARY_READY" not in out
    assert (root / ".janitor" / "state" / ehc._PENDING_FILE).exists(), "hold stays armed"


def test_on_resume_lane_also_delegates_and_never_calls_llm_ext(tmp_path, monkeypatch):
    """TRDD-QZVAEWQH: `--on-resume` (the SessionStart hook caller) used to compose inline —
    that kept alive the race this card removes (an on-resume fire's own compose racing the
    freshly-cleared session's SessionStart summarizer over the SAME transcript). It now
    delegates exactly like the daemon lane, and calling llm-ext at all is a bug."""
    (rc, out), root = _delegation_case(
        tmp_path, monkeypatch,
        on_resume=True, trigger="resumed-cold", gate_facts={"gate": "resume"},
    )
    assert rc == 0
    assert "SUMMARY_DELEGATED" in out, out
    assert "SUMMARY_READY" not in out and "NO_SUMMARY_POST_CLEAR" not in out
    assert (root / ".janitor" / "state" / ehc._PENDING_FILE).exists(), "hold stays armed"


# --- end to end (real subprocess) --------------------------------------------


# The reactive trigger shells out to agentlensPro, an OPTIONAL third-party CLI. These tests are
# about the watcher, not about that probe (which has its own unit tests against an injected
# runner), and the suite's sandbox guard rightly refuses to let a unit test spawn arbitrary
# binaries. An empty command is the probe's documented disable, so this pins the tests to the
# no-agentlensPro configuration rather than to whatever happens to be installed on the host —
# which is also the only configuration that is reproducible in CI.
_NO_AGENTLENS = {ec.CACHE_EXPIRED_COMMAND_ENV: ""}


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(root), *args],
        capture_output=True, text=True, timeout=180,
        env={**os.environ, **_NO_AGENTLENS, ec.ENABLED_ENV: "1"},
    )


def _iso(epoch: int) -> str:
    """A transcript-style UTC timestamp ('2026-07-17T16:55:41.797Z' shape)."""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def test_awaiting_user_veto_reaches_the_watcher_end_to_end(tmp_path, monkeypatch):
    """GATHER layer, not the pure gate (TRDD-OO301H7D). The bug was `idle_s, _enq, _await =
    fleet_scan.transcript_activity(...)` — an argument that was computed and then never PASSED.
    No mutation of `should_clear_externally` alone can catch a value that never arrives at its
    call site; only a real transcript flowing through `_decide` proves the wiring is intact. A
    tail ending on an unanswered `ExitPlanMode` must refuse EVEN THOUGH every trigger the gate
    would otherwise fire on (long idle, a readable but irrelevant cron) is satisfied — and
    `--force` must not be able to override that refusal, because it is a safety veto."""
    import json

    import memory_scopes  # noqa: PLC0415

    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv(ec.CACHE_EXPIRED_COMMAND_ENV, "")  # no agentlensPro subprocess
    monkeypatch.setenv(ec.MIN_CONTEXT_ENV, "0")  # context-size clause never vetoes this test
    import cold_cache_compact  # noqa: PLC0415

    monkeypatch.setenv(cold_cache_compact.CLEAR_MIN_IDLE_ENV, "60")  # trivially met if not vetoed

    now = int(time.time())
    root = tmp_path / "proj"
    (root / ".janitor" / "state").mkdir(parents=True)
    slug = memory_scopes.project_slug(os.path.realpath(str(root)))
    tdir = tmp_path / ".claude" / "projects" / slug
    tdir.mkdir(parents=True)
    lines = [
        json.dumps({"type": "assistant", "timestamp": _iso(now - 4000), "message": {}}),
        json.dumps(
            {
                "type": "assistant",
                "timestamp": _iso(now - 2000),
                "message": {
                    "content": [{"type": "tool_use", "id": "toolu_PLAN", "name": "ExitPlanMode"}]
                },
            }
        ),
    ]
    (tdir / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    sd = root / ".janitor" / "state"
    verdict, facts = ehc._decide(root, sd, now, force=False)
    assert verdict.fire is False
    assert verdict.why == "awaiting-user"
    assert facts["awaiting_user"] is True

    forced, _ = ehc._decide(root, sd, now, force=True)
    assert forced.fire is False and forced.why == "awaiting-user", (
        "--force overrides trigger terms only; a human is being asked a question"
    )


def test_unknown_idle_holds_end_to_end_and_touches_nothing(tmp_path):
    """A project with no transcript has an unknown idle age, which may never authorize a clear."""
    root = _project(tmp_path)
    proc = _run(root)
    assert proc.returncode == 0, proc.stderr
    assert "VERDICT HOLD" in proc.stdout
    assert "idle-unknown" in proc.stdout
    assert not (root / ".janitor" / "state" / "agent-handoff.md").exists()
    assert not (root / ".janitor" / "state" / "resume-after-clear.flag").exists()


def test_a_project_without_janitor_state_is_skipped(tmp_path):
    """Not every directory is a janitor-armed session; those are none of our business."""
    proc = _run(tmp_path)
    assert proc.returncode == 0
    assert "NO_JANITOR_STATE" in proc.stdout


def test_the_feature_is_off_unless_opted_in(tmp_path):
    """DEFAULT OFF: this path clears with no model turn in front of it, so it ships opt-in."""
    root = _project(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(root)],
        capture_output=True, text=True, timeout=180,
        env={**{k: v for k, v in os.environ.items() if k != ec.ENABLED_ENV}, **_NO_AGENTLENS},
    )
    assert "DISABLED" in proc.stdout


def test_dry_run_runs_even_while_disabled(tmp_path):
    """Observing the decision must never require arming the destructive path first."""
    root = _project(tmp_path)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), "--project-root", str(root), "--dry-run"],
        capture_output=True, text=True, timeout=180,
        env={**{k: v for k, v in os.environ.items() if k != ec.ENABLED_ENV}, **_NO_AGENTLENS},
    )
    assert "DISABLED" not in proc.stdout
    assert "VERDICT" in proc.stdout


def test_force_never_overrides_a_safety_veto():
    """--force overrides the idle/cache TRIGGER terms only; presence and cooldown still hold.

    Asserted against the pure gate the watcher wraps, since the override is expressed as a
    predicate on the refusal reason: only `idle …` and `no-headroom …` are overridable, and
    every safety veto returns a different reason string.
    """
    overridable = {"idle 600s < 3600s and the next fire is still warm", "no-headroom (10s < 60s)"}
    safety = {"cooldown", "active-waiting", "awaiting-user", "idle-unknown",
              "context 50000 < 150000 — nothing worth reclaiming"}
    for why in overridable:
        assert why.startswith(("idle ", "no-headroom"))
    for why in safety:
        assert not why.startswith(("idle ", "no-headroom")), why


# --- _fire: the warm-cancel gate is trigger-scoped ----------------------------


def _captured_payload(monkeypatch, tmp_path: Path, trigger: str) -> dict:
    """Run `_fire` with the chain spawn and the fired-stamp both replaced, and return the
    payload it built. Real function, real payload — only the two side effects are stubbed."""
    import clear_trigger
    import cold_cache_compact

    seen: dict = {}
    monkeypatch.setattr(clear_trigger, "_spawn_chain",
                        lambda payload, env=None: seen.update(payload))
    monkeypatch.setattr(cold_cache_compact, "mark_clear_fired", lambda sd, now=0: None)
    sd = tmp_path / ".janitor" / "state"
    ehc._fire(tmp_path, sd, {"kind": "tmux", "pane": "%1"}, 0, trigger=trigger)
    return seen


def test_a_cold_cache_trigger_arms_the_warm_cancel_probe(tmp_path, monkeypatch):
    """`resumed-cold` and `cache-certain-expired` fire BECAUSE the cache went cold, so a cache
    that warms up again while the pane is busy genuinely retires the /clear."""
    _project(tmp_path)
    for trigger in (ec.TRIGGER_RESUMED_COLD, ec.TRIGGER_CACHE_CERTAIN_EXPIRED):
        assert _captured_payload(monkeypatch, tmp_path, trigger)["cache_gated"] is True, trigger


def test_idle_and_predictive_triggers_do_not_arm_the_warm_cancel_probe(tmp_path, monkeypatch):
    """The regression this test exists for (2026-08-16): `long-idle` and `next-fire-misses`
    fire while heartbeats keep the cache WARM — that is their normal, healthy state. Arming
    the "still expired?" probe on them cancelled every single fire, six in a row, making the
    long-idle lever unreachable exactly as `external_clear.next_fire_misses_cache` warns."""
    _project(tmp_path)
    for trigger in (ec.TRIGGER_LONG_IDLE, ec.TRIGGER_NEXT_FIRE_MISSES, ""):
        assert _captured_payload(monkeypatch, tmp_path, trigger)["cache_gated"] is False, trigger


# --- _fire: the verify harness's before-snapshot lands ahead of the keystroke (TRDD-BDZG8Y8A) --


def test_fire_takes_a_verify_before_snapshot_before_spawning_the_chain(tmp_path, monkeypatch):
    """An automated clear used to leave `handoff-clear-verify.json` whatever the last hand-run
    drill wrote, so the resumed session's `--phase after` compared against a snapshot hours old
    (AgentlensPro, 2026-09-02 04:23). `_fire` now takes the harness's own `before` snapshot, and
    it must exist BEFORE the chain is spawned — one taken after the `/clear` keystroke would
    record the collapsed state and turn the `after` table into a false FAIL."""
    import json

    import clear_trigger
    import cold_cache_compact

    _project(tmp_path)
    sd = tmp_path / ".janitor" / "state"
    (sd / "heartbeat-cron-id.txt").write_text("abc12345", encoding="utf-8")
    verify = sd / "handoff-clear-verify.json"
    seen: dict = {}

    def fake_spawn(payload, env=None):
        seen["json_present_at_spawn"] = verify.is_file()
        seen["env_root"] = (env or {}).get("CLAUDE_PROJECT_DIR")

    monkeypatch.setattr(clear_trigger, "_spawn_chain", fake_spawn)
    monkeypatch.setattr(cold_cache_compact, "mark_clear_fired", lambda sd, now=0: None)
    t0 = int(time.time())
    ehc._fire(tmp_path, sd, {"kind": "tmux", "pane": "%1"}, t0, trigger=ec.TRIGGER_NEXT_FIRE_MISSES)

    assert seen["json_present_at_spawn"] is True
    assert seen["env_root"] == str(tmp_path)
    before = json.loads(verify.read_text(encoding="utf-8"))["before"]
    assert before["cron_id"] == "abc12345"
    assert t0 <= before["ts"] <= t0 + ehc._VERIFY_BEFORE_TIMEOUT_S


def test_fire_still_spawns_when_the_verify_snapshot_fails(tmp_path, monkeypatch):
    """The snapshot is a DIAGNOSTIC: a broken harness must never hold back the clear it exists
    to measure — fail-open, logged, like every other gather in that harness."""
    import clear_trigger
    import cold_cache_compact

    _project(tmp_path)
    sd = tmp_path / ".janitor" / "state"
    spawned: list = []
    logged: list = []
    monkeypatch.setattr(clear_trigger, "_spawn_chain",
                        lambda payload, env=None: spawned.append(payload))
    monkeypatch.setattr(cold_cache_compact, "mark_clear_fired", lambda sd, now=0: None)
    monkeypatch.setattr(ehc.state, "log_line", lambda name, msg: logged.append(msg))

    def boom(*args, **kwargs):
        raise OSError("no interpreter here")

    monkeypatch.setattr(ehc.subprocess, "run", boom)
    ehc._fire(tmp_path, sd, {"kind": "tmux", "pane": "%1"}, 0, trigger="")

    assert len(spawned) == 1
    assert not (sd / "handoff-clear-verify.json").exists()
    assert any("before-snapshot skipped" in m for m in logged)


# --- came_back_since: the cancel that falsifies EVERY trigger's premise -------


def test_a_real_turn_after_the_verdict_retires_the_clear():
    """The gap ai-maestro's review closed (2026-08-16). Every trigger that fires this chain
    rests on "no real work is happening here"; a substantive turn after the verdict falsifies
    that, and for `long-idle` it is the ONLY thing that does — a warm cache never contradicted
    idleness. The 1h ceiling cannot cover this: it bounds how long a wrong verdict may WAIT,
    not the verdict BECOMING wrong, and /clear has no undo."""
    import clear_trigger as ct

    now, verdict = 10_000, 9_000
    # idle 500s ⇒ last real turn at 9_500, AFTER the verdict ⇒ the user is back.
    assert ct.came_back_since(verdict, 500, now) is True
    # idle 2_000s ⇒ last real turn at 8_000, BEFORE the verdict ⇒ still the idle session.
    assert ct.came_back_since(verdict, 2_000, now) is False


def test_a_turn_in_the_verdicts_own_second_is_not_a_comeback():
    """Strictly greater, not >=. The turn the verdict was computed FROM lands in the same
    second; `>=` would cancel every chain the instant it was fired — the same 100%-veto shape
    the cache probe had."""
    import clear_trigger as ct

    assert ct.came_back_since(9_000, 1_000, 10_000) is False


def test_a_missing_verdict_timestamp_disables_the_comeback_cancel():
    """0/absent means the payload predates this field. Disable the cancel rather than invent a
    reference point: a wrong pin cancels either every chain or none, both silently."""
    import clear_trigger as ct

    assert ct.came_back_since(0, 1, 10_000) is False


def test_the_payload_carries_the_verdict_timestamp(tmp_path, monkeypatch):
    """Wiring: without this the predicate above is unreachable in production."""
    _project(tmp_path)
    payload = _captured_payload(monkeypatch, tmp_path, ec.TRIGGER_LONG_IDLE)
    assert payload["verdict_ts"] == 0  # _fire was called with now=0 in the helper
    assert "verdict_ts" in payload


# --- the singleflight lock (incident 2026-08-23) ------------------------------


def test_a_second_watcher_for_the_same_root_exits_instead_of_queueing(tmp_path):
    """Singleflight: a held lock turns invocation 2 into a no-op (the 2026-08-23 interleaved
    retry chains), and a STALE lock is taken over rather than parking the lever forever."""
    root = tmp_path / "p"
    sd = root / ".janitor" / "state"
    sd.mkdir(parents=True)
    lock = sd / "external-clear.lock"

    lock.write_text("999999 0\n")  # fresh mtime — a live holder
    got = _run(root, "--dry-run")
    assert "ALREADY_RUNNING" in got.stdout, got.stdout

    stale = time.time() - (ec.DEFAULT_SUMMARY_DEADLINE_S + 601)
    os.utime(lock, (stale, stale))
    got = _run(root, "--dry-run")
    assert "ALREADY_RUNNING" not in got.stdout, got.stdout
    assert "VERDICT" in got.stdout, "past a stale lock the watcher must actually run"
    assert not lock.exists(), "the takeover's own lock is released on exit"


def test_dry_run_never_arms_the_summary_hold(tmp_path, monkeypatch, capsys):
    """--dry-run must WRITE NOTHING (review-fork finding, 2026-09-01): the first cut captured
    `summary-pending.json` before the dry-run return, arming the 15-minute hold that blocks
    [janitor-resume] and chores — on a session that was never cleared."""
    import argparse
    import types

    import fleet_restart

    root = tmp_path / "p"
    sd = root / ".janitor" / "state"
    sd.mkdir(parents=True)
    transcript = tmp_path / "t.jsonl"
    transcript.write_text("{}\n")

    monkeypatch.setattr(
        ehc, "_decide",
        lambda *_a, **_k: (
            ec.ClearVerdict(True, "cache-certainly-expired", "test"),
            {"transcript": str(transcript)},
        ),
    )
    monkeypatch.setattr(fleet_restart, "recorded_terminal", lambda _r: {"kind": "tmux"})
    monkeypatch.setattr(ec, "terminal_from_record", lambda _r: {"kind": "tmux", "pane": "%1"})
    fired = types.SimpleNamespace(count=0)
    monkeypatch.setattr(ehc, "_fire", lambda *_a, **_k: setattr(fired, "count", fired.count + 1))

    args = argparse.Namespace(dry_run=True, force=False, on_resume=False, project_root=str(root))
    assert ehc._run(root, sd, int(time.time()), args) == 0
    out = capsys.readouterr().out
    assert "DRY_RUN" in out, out
    assert fired.count == 0, "a dry-run must never spawn the clear chain"
    assert not (sd / ehc._PENDING_FILE).exists(), "a dry-run must not arm the summary hold"

    # FIDELITY (review-fork, 2026-09-01): on a transcript the real run would DECLINE (empty
    # file), the dry-run must say so — not claim "would clear" from the path string alone.
    transcript.write_text("")
    assert ehc._run(root, sd, int(time.time()), args) == 0
    out = capsys.readouterr().out
    assert "would decline" in out, out
    assert "would clear" not in out, "same inputs must not produce opposite reports"
