"""The llm-externalizer handoff composer (TRDD-1QJIZFFW).

These pin the two properties that make the feature safe to leave switched on by default:
it NEVER produces no handoff (the `/clear` it precedes is unrecoverable), and it never
produces one large enough to refill the context it was built to empty.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO / "scripts" / "lib"))

import external_clear as ec  # noqa: E402


def _inputs() -> ec.HandoffInputs:
    return ec.HandoffInputs(
        cards=[("ABC12345", "dev", "A card that is in progress")],
        commits=[("deadbee", "fix: something")],
        findings=["HIGH something happened"],
        memory_dir=".claude/project/memory",
        trigger="cache-miss",
    )


class _Proc:
    def __init__(self, rc: int, out: str = "") -> None:
        self.returncode, self.stdout, self.stderr = rc, out, ""


# --- llm-ext's data dir is ITS OWN business, not ours ------------------------------
#
# The caller-side derivation these tests pinned is GONE (2026-08-16). The launcher resolves its
# own store — 13.5.1 self-derives from its resolved path, 13.5.2+ pins `~/.llm-externalizer`
# (`LLM_EXT_CONFIG_DIR`) and does not read CLAUDE_PLUGIN_DATA at all — and the component that
# owns the layout is authoritative where every caller could only guess. Guessing was not
# hypothetical harm: our derivation refused for any binary outside the cache layout and turned
# that refusal into `permanent — llm-ext data dir unresolvable`, which degraded EVERY
# daemon-context handoff to the template seven times on 2026-08-16 alone (TRDD-CEWVQ8DG).
#
# What replaced them: `test_the_child_env_STRIPS_our_own_plugin_data` below. The env var must be
# REMOVED rather than merely unset by us — in a janitor hook/daemon child it names the JANITOR's
# store, and on 13.5.1 an inherited value WINS over the launcher's own derivation, which would
# self-install llm-ext's native module into the wrong plugin's directory.


def test_the_child_env_STRIPS_our_own_plugin_data(tmp_path, monkeypatch) -> None:
    """We must not hand llm-ext a CLAUDE_PLUGIN_DATA we inherited — it points at OUR store."""
    t = tmp_path / "s.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ec.shutil, "which", lambda _n: "/x/cache/m/llm-externalizer/1/bin/llm-ext")
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", "/the/JANITORS/store")
    seen: dict = {}

    def _run(cmd, **kw):
        seen["env"] = kw.get("env") or {}
        return _Proc(0, "a summary")

    assert ec.run_llm_ext_summary(str(t), runner=_run) == "a summary"
    assert "CLAUDE_PLUGIN_DATA" not in seen["env"], (
        "inherited CLAUDE_PLUGIN_DATA names the JANITOR's data dir and beats the launcher's own "
        "resolution — llm-ext would install its native module into the wrong plugin's store"
    )


def test_the_progress_signal_watches_the_CHECKPOINT_SUBDIR_not_the_config_root(
    tmp_path, monkeypatch
) -> None:
    """The gate must watch `session-summary-checkpoints/`, never the config root.

    llm-ext's `saveCheckpoint()` writes `<name>.tmp` and renames it inside that subdir once per
    completed chunk, so only the SUBDIR's mtime ticks per chunk; the root's moves solely when a
    top-level entry appears or disappears. Watching the root yields a signal that never advances
    during a healthy summarize — the retry gate then abandons every chunk at its no-progress
    timeout and handoffs silently degrade to the template.

    Asserted as the exact path rather than behaviourally because the failure is INVISIBLE: both
    directories exist, both are readable, and a fingerprint on the wrong one looks perfectly
    healthy right up until it reports stalled work that is not stalled.
    """
    root = tmp_path / "llm-ext-state"
    (root / "session-summary-checkpoints").mkdir(parents=True)
    monkeypatch.setenv("LLM_EXT_CONFIG_DIR", str(root))
    assert ec.llm_ext_state_dir() == str(root / "session-summary-checkpoints")
    assert ec.llm_ext_state_dir() != str(root), "the config ROOT is a dead per-chunk signal"


def test_the_progress_signal_is_ABSENT_rather_than_wrong_before_any_checkpoint(
    tmp_path, monkeypatch
) -> None:
    """No checkpoint subdir yet ⇒ "" ⇒ the retry loop runs UNGATED.

    The alternative — returning the root as a fallback — would substitute a signal that cannot
    tick for one that is merely missing, and the loop would treat healthy work as stalled. No
    gate is strictly better than a lying gate.
    """
    root = tmp_path / "llm-ext-state"
    root.mkdir()  # config root exists, but llm-ext has never checkpointed here
    monkeypatch.setenv("LLM_EXT_CONFIG_DIR", str(root))
    assert ec.llm_ext_state_dir() == ""


# --- every CLI failure mode must arrive as None -----------------------------------


def test_summary_is_none_when_the_cli_exits_non_zero(tmp_path, monkeypatch) -> None:
    t = tmp_path / "s.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ec.shutil, "which", lambda _n: "/x/cache/m/llm-externalizer/1/bin/llm-ext")
    assert ec.run_llm_ext_summary(str(t), runner=lambda *a, **k: _Proc(1, "junk")) is None


def test_summary_is_none_on_timeout_rather_than_raising(tmp_path, monkeypatch) -> None:
    """A composer that can raise is a composer that can stop the clear from happening."""
    t = tmp_path / "s.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ec.shutil, "which", lambda _n: "/x/cache/m/llm-externalizer/1/bin/llm-ext")

    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="llm-ext", timeout=1)

    assert ec.run_llm_ext_summary(str(t), runner=_boom) is None


# (Two tests deleted 2026-08-16, not lost: `test_summary_is_none_when_the_data_dir_cannot_be_
# resolved` pinned the refuse-without-data-dir behaviour, and `test_summary_passes_the_data_dir_
# in_the_child_env` pinned passing CLAUDE_PLUGIN_DATA. Both pinned the CALLER-side derivation
# that produced the `permanent — llm-ext data dir unresolvable` field failure. The launcher owns
# its store now; the replacement contract — invoke unconditionally, STRIP the inherited var —
# is `test_the_child_env_STRIPS_our_own_plugin_data` above. The `--stdout` flag assertion the
# second test carried moves here:)


def test_summary_reads_stdout_not_a_report_path(tmp_path, monkeypatch) -> None:
    t = tmp_path / "s.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ec.shutil, "which", lambda _n: "/x/cache/m/llm-externalizer/1/bin/llm-ext")
    seen: dict = {}

    def _run(cmd, **kw):
        seen["cmd"] = cmd
        return _Proc(0, "a summary")

    assert ec.run_llm_ext_summary(str(t), runner=_run) == "a summary"
    assert "--stdout" in seen["cmd"], "must read the TEXT, not a report path still being written"


# --- the payload budget: the whole point of the card ------------------------------


def test_handoff_survives_a_failed_summary(tmp_path) -> None:
    """summary=None must still yield the scriptable facts + tail, never an empty handoff."""
    text = ec.compose_handoff(
        _inputs(), now_iso="2026-08-12T18:00:00+0200", summary=None,
        tail=["USER: do the thing", "ASSISTANT: done"],
    )
    assert "ABC12345" in text
    assert "do the thing" in text


def test_the_composer_targets_the_budget_the_checker_enforces() -> None:
    """The producer and its checker must agree, or the contract is decorative.

    MEASURED DRIFT (TRDD-PXP08ZQC): `compose_handoff` defaulted to 8192 while
    `clear_trigger.check_handoff_concise` enforced 4096, and the caller passed neither — so every
    full handoff aimed at a budget the contract rejects. A real one shipped at 4571 bytes: over
    the limit, under the composer's target, logged as `['too-large']` and injected anyway.

    Asserted as a CONSTANT EQUALITY rather than only behaviourally, because two independently
    tuned numbers drift silently the moment someone changes one side — the same failure this file
    already carries a lesson about for the fleet-lease TTL.
    """
    import inspect

    import clear_trigger  # noqa: PLC0415 -- a script, imported only by this assertion

    default = inspect.signature(ec.compose_handoff).parameters["max_bytes"].default
    assert default == clear_trigger._HANDOFF_MAX_BYTES == ec.HANDOFF_MAX_BYTES, (
        f"composer default ({default}) and enforced contract "
        f"({clear_trigger._HANDOFF_MAX_BYTES}) disagree — a handoff composed with defaults would "
        "violate the check that gates it."
    )


def test_a_REALISTIC_handoff_passes_the_contract_with_defaults() -> None:
    """The regression the toy fixture could not catch.

    `test_external_handoff_clear.py::test_composed_handoff_satisfies_the_concision_contract`
    exercised ONE card and no transcript, so its handoff was far too small to reach either budget
    and passed under both — green while production was violating the contract. This composes a
    handoff the size a real project produces (many cards, commits, findings, a long tail and an
    oversized summary) and asserts the SHIPPED defaults keep it inside the contract.
    """
    import clear_trigger  # noqa: PLC0415

    inputs = ec.HandoffInputs(
        cards=[(f"CARD{i:04d}", "dev", f"A card with a reasonably long descriptive title {i}")
               for i in range(12)],
        commits=[(f"abc{i:04d}", f"feat(area): a commit subject of realistic length {i}")
                 for i in range(10)],
        findings=[f"HIGH something notable happened in subsystem {i}" for i in range(8)],
        memory_dir=".claude/project/memory",
        trigger=ec.TRIGGER_RESUMED_COLD,
    )
    text = ec.compose_handoff(
        inputs,
        now_iso="2026-08-16T00:50:00+0200",
        summary="S" * 40_000,
        tail=[f"USER: a message of some length, number {i}" for i in range(300)],
    )

    ok, reasons = clear_trigger.check_handoff_concise(text)
    assert ok, f"a realistic handoff violates the contract it is gated by: {reasons}"


def test_whole_payload_respects_one_budget(tmp_path) -> None:
    """Three 'small' parts add up — the budget is over the WHOLE injection, not per part."""
    text = ec.compose_handoff(
        _inputs(), now_iso="2026-08-12T18:00:00+0200",
        summary="S" * 40_000,
        tail=[f"USER: message number {i}" for i in range(400)],
        max_bytes=6000,
    )
    assert len(text.encode("utf-8")) <= 6000, f"payload overran its budget: {len(text)}"


def test_tail_is_trimmed_from_the_OLDEST_end_and_says_so(tmp_path) -> None:
    """A resuming session needs the most recent exchanges; a silent clip reads as complete."""
    tail = [f"USER: m{i}" for i in range(200)]
    text = ec.compose_handoff(
        _inputs(), now_iso="2026-08-12T18:00:00+0200", summary=None, tail=tail, max_bytes=3000,
    )
    # EXACT-LINE membership, not substring: "m0" occurs inside "m100".."m199", so a substring
    # check can never fail and would assert nothing. Same trap as the dead-symbol detector's
    # suffix match — a test that cannot fail is worse than no test.
    lines = set(text.splitlines())
    assert "USER: m199" in lines, "the NEWEST turn must survive"
    assert "USER: m0" not in lines, "the OLDEST turn should be dropped first"
    assert "earlier message(s) dropped" in text, "truncation must be STATED, not silent"


def test_recent_messages_skips_tool_noise(tmp_path) -> None:
    """Tool payloads are the bulk of a transcript and the least useful thing to restore."""
    t = tmp_path / "s.jsonl"
    t.write_text(
        json.dumps({"message": {"role": "user", "content": [{"type": "text", "text": "hello"}]}})
        + "\n"
        + json.dumps({"message": {"role": "assistant", "content": [
            {"type": "tool_use", "name": "Bash"},
            {"type": "text", "text": "hi back"},
        ]}})
        + "\n",
        encoding="utf-8",
    )
    got = ec.recent_messages(str(t))
    assert got == ["USER: hello", "ASSISTANT: hi back"]
