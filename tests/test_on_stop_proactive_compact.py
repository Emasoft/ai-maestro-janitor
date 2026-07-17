"""Stop-hook proactive compaction (TRDD-D3PROACT) — the PREVENTION trigger point.

A cron fire cannot compact before its own burn (the turn re-reads the transcript before
dispatch runs). Stop CAN: it fires at the end of EVERY turn, while the cache is still warm
and BEFORE the next LLM call — including the end of a >1h working turn, which no cron can
sit inside. These pin the gates: it stays SILENT during interactive work (the user is
present) and whenever anything is pending, fires only on an idle+large context, never
stamps the cooldown unless a compact really fired, and NEVER breaks a turn's completion.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))


def _load_hook():
    spec = importlib.util.spec_from_file_location(
        "on_stop_proactive_compact_hook", _ROOT / "scripts" / "hooks" / "on-stop-proactive-compact.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_ROOT))
    for var in (
        "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_ENABLED",
        "CLAUDE_PLUGIN_OPTION_PROACTIVE_IDLE_COMPACT_ENABLED",
        "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_CONTEXT_TOKENS",
    ):
        monkeypatch.delenv(var, raising=False)
    for mod in ("state", "lib.state", "cold_cache_compact", "user_intent", "pending_agents"):
        sys.modules.pop(mod, None)

    import cold_cache_compact as ccc
    import user_intent
    from lib import state as lib_state  # noqa: E402 -- the module object the HOOK imports

    # state_dir/project_root are lru_cache'd (read once per process). Without clearing, every
    # test after the first resolves the FIRST test's tmp dir — so the firing test's cooldown
    # stamp leaked forward and silently suppressed later tests (they passed in isolation and
    # failed in the file run). Same clear the repo's test_state_log_dir.py does.
    for fn in (lib_state.project_root, lib_state.janitor_root, lib_state.state_dir, lib_state.log_dir):
        fn.cache_clear()
    lib_state.init_state()
    spawned: list[list[str]] = []

    def _fake_run(cmd, **_kw):  # noqa: ANN001, ANN003
        spawned.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="COMPACT_FIRED\n", stderr="")

    # PATCH `lib.state`, NOT `state`. The hook does `from lib import state`, which is a
    # DIFFERENT module object than a bare `import state` — patching the wrong one lets the
    # test call the REAL compact_trigger, which types /compact into the developer's own pane.
    # (Verified the hard way: the first run of this file did exactly that.) Same trap the
    # session-start cold-cache test documents for `from lib import cold_cache_compact`.
    monkeypatch.setattr(lib_state, "run_subprocess", _fake_run)
    monkeypatch.setattr(ccc, "newest_transcript", lambda _p: Path("/tmp/fake.jsonl"))
    return SimpleNamespace(state=lib_state, ccc=ccc, ui=user_intent, spawned=spawned, project=project)


def _run(hook, payload: dict, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(read=lambda: json.dumps(payload)))
    return hook.main()


def _set(h, monkeypatch: pytest.MonkeyPatch, *, present: bool, ctx) -> None:  # noqa: ANN001
    monkeypatch.setattr(h.ui, "user_is_present", lambda **_k: present)
    monkeypatch.setattr(h.ccc, "context_tokens_for", lambda _p: ctx)


def test_fires_when_turn_ends_idle_with_a_large_context(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE PREVENTION: a turn ends, nobody at the keyboard, context large → queue /compact
    NOW while the cache is warm, so the next cold resume reads ~50k not ~600k."""
    hook = _load_hook()
    _set(harness, monkeypatch, present=False, ctx=600_000)
    import time as _t

    assert _run(hook, {"transcript_path": "/tmp/fake.jsonl"}, monkeypatch) == 0
    assert len(harness.spawned) == 1, f"expected one compact_trigger spawn, got {harness.spawned}"
    argv = harness.spawned[0]
    assert argv[1].endswith("compact_trigger.py")
    assert "--directive" in argv, "the compact must carry a resume directive (work is preserved)"
    # A real fire STAMPS the shared cooldown, so a second Stop moments later cannot re-compact
    # before the first one lands.
    sd = harness.state.state_dir()
    assert harness.ccc.in_cooldown(sd, now=int(_t.time()) + 1) is True


def test_does_not_loop_after_a_compaction(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE LOOP GUARD, end-to-end through the hook — the bug the user caught 2026-07-17.

    Real numbers from this repo: a compaction went 343,007 -> 308,644 (only 10%; the base
    reloads and cannot be compacted away). With a size-only gate the hook would fire, compact,
    land at 308,644, wait out the cooldown, and fire AGAIN — forever, destroying context each
    time. Here the compaction is observed, the floor is learned from the very next Stop, and the
    hook goes silent even though the context is still huge and the user is still away.
    """
    hook = _load_hook()
    import time as _t

    sd = harness.state.state_dir()
    # A compaction just happened, and the context it left behind is the floor.
    harness.ccc.mark_compacted(sd, now=int(_t.time()))
    _set(harness, monkeypatch, present=False, ctx=308_644)

    assert _run(hook, {"transcript_path": "/tmp/fake.jsonl"}, monkeypatch) == 0
    assert harness.spawned == [], "compacting at the post-compaction floor reclaims nothing"
    assert harness.ccc.read_floor(sd)[0] == 308_644, "the floor must be learned from this Stop"

    # The cooldown expiring must NOT resurrect it — the cooldown only defers a loop, the floor
    # ends it. Even the pre-compact size that legitimately fired once is now silent.
    _set(harness, monkeypatch, present=False, ctx=343_007)
    assert _run(hook, {"transcript_path": "/tmp/fake.jsonl"}, monkeypatch) == 0
    assert harness.spawned == [], "34k of reclaimable context is not worth a lossy compaction"

    # But real growth above the floor still fires — the guard must not be a permanent latch.
    _set(harness, monkeypatch, present=False, ctx=700_000)
    assert _run(hook, {"transcript_path": "/tmp/fake.jsonl"}, monkeypatch) == 0
    assert len(harness.spawned) == 1, "a session that grows large again still gets its compaction"


def test_silent_during_interactive_work(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """The user just typed → present → NEVER compact out from under them (it is lossy).
    This is the overwhelmingly common Stop, and it must cost a stat and nothing else."""
    hook = _load_hook()
    _set(harness, monkeypatch, present=True, ctx=600_000)
    assert _run(hook, {"transcript_path": "/tmp/fake.jsonl"}, monkeypatch) == 0
    assert harness.spawned == []


def test_silent_on_small_context(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """A small context saves nothing — a pointless lossy compaction."""
    hook = _load_hook()
    _set(harness, monkeypatch, present=False, ctx=40_000)
    assert _run(hook, {"transcript_path": "/tmp/fake.jsonl"}, monkeypatch) == 0
    assert harness.spawned == []


def test_silent_when_work_is_pending(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pending resume directive means the session has queued work → don't interrupt it."""
    hook = _load_hook()
    _set(harness, monkeypatch, present=False, ctx=600_000)
    (harness.state.state_dir() / "resume-directive.txt").write_text("continue X", encoding="utf-8")
    assert _run(hook, {"transcript_path": "/tmp/fake.jsonl"}, monkeypatch) == 0
    assert harness.spawned == []


def test_silent_when_keep_going_opt_in_is_set(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """An explicit keep-going opt-in means the session is meant to be working."""
    hook = _load_hook()
    _set(harness, monkeypatch, present=False, ctx=600_000)
    (harness.state.state_dir() / "keep-going").write_text("", encoding="utf-8")
    assert _run(hook, {"transcript_path": "/tmp/fake.jsonl"}, monkeypatch) == 0
    assert harness.spawned == []


def test_respects_opt_out(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    hook = _load_hook()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_PROACTIVE_IDLE_COMPACT_ENABLED", "false")
    _set(harness, monkeypatch, present=False, ctx=600_000)
    assert _run(hook, {"transcript_path": "/tmp/fake.jsonl"}, monkeypatch) == 0
    assert harness.spawned == []


def test_no_cooldown_stamp_when_compact_cannot_fire(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """NO_ITERM: no compaction happened, so the cooldown must stay CLEAR — a stamp would also
    suppress the SessionStart + heartbeat trigger points (all three agree on 'fired')."""
    hook = _load_hook()
    _set(harness, monkeypatch, present=False, ctx=600_000)
    monkeypatch.setattr(
        harness.state, "run_subprocess",
        lambda cmd, **_k: SimpleNamespace(returncode=0, stdout="NO_ITERM\n", stderr=""),
    )
    assert _run(hook, {"transcript_path": "/tmp/fake.jsonl"}, monkeypatch) == 0
    import time as _t
    assert harness.ccc.in_cooldown(harness.state.state_dir(), now=int(_t.time())) is False


def test_falls_back_to_newest_transcript_and_never_raises(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """An absent/stale transcript_path must not silently skip the compact (the size is
    recovered from the newest transcript), and a broken payload must never break the turn."""
    hook = _load_hook()
    newest = Path("/tmp/fake.jsonl")
    monkeypatch.setattr(harness.ui, "user_is_present", lambda **_k: False)
    monkeypatch.setattr(harness.ccc, "context_tokens_for", lambda p: 600_000 if p == newest else None)
    assert _run(hook, {"transcript_path": ""}, monkeypatch) == 0
    assert len(harness.spawned) == 1, "the newest-transcript fallback must recover the size"

    # A garbage payload exits 0 and spawns nothing — a Stop hook must never block a turn.
    harness.spawned.clear()
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(read=lambda: "not-json"))
    assert hook.main() == 0
