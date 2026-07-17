"""SessionStart cold-cache auto-compact wiring (TRDD-EUWIHP0G).

Pins `_maybe_cold_compact_on_session_start`: it self-fires /compact ONLY on a
`startup`/`resume` with a large resumed context, and does NOT fire when the
context is small, the source is `compact`/`clear`, the feature is disabled, or a
cooldown is active. We monkeypatch `subprocess.Popen` (so no real /compact is
ever launched) and the context reader (so the size is deterministic); the cooldown
uses the REAL stamp under an isolated CLAUDE_PROJECT_DIR.
"""

from __future__ import annotations

import importlib
import importlib.util
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(_ROOT / "scripts"))


def _load_hook():
    spec = importlib.util.spec_from_file_location(
        "on_session_start_hook_cc", _ROOT / "scripts" / "hooks" / "on-session-start.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolated project + a recorded Popen + a controllable context reader.

    Returns (hook, state, ccc, spawned) where `spawned` collects each argv list
    passed to subprocess.Popen. `plugin_root` is the REAL repo so the helper's
    `compact_trigger.py` existence check passes.
    """
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    # Clean env: default-on, default thresholds.
    for var in (
        "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_ENABLED",
        "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_CONTEXT_TOKENS",
        "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_IDLE_SECONDS",
        "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_COOLDOWN_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)

    for mod in ("state", "cold_cache_compact", "lib.cold_cache_compact"):
        sys.modules.pop(mod, None)

    state = importlib.import_module("state")
    state.init_state()
    # The helper does `from lib import cold_cache_compact`; patch THAT module object.
    ccc = importlib.import_module("lib.cold_cache_compact")

    spawned: list[list[str]] = []

    def _fake_run(cmd, **_kw):  # noqa: ANN001, ANN003
        spawned.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="COMPACT_FIRED\n", stderr="")

    # The helper runs compact_trigger SYNCHRONOUSLY (via state.run_subprocess) so it can
    # read COMPACT_FIRED vs NO_ITERM and commit the cooldown only on a real fire.
    monkeypatch.setattr(state, "run_subprocess", _fake_run)

    hook = _load_hook()
    return hook, state, ccc, spawned, str(_ROOT)


def _set_ctx(monkeypatch: pytest.MonkeyPatch, ccc, value) -> None:  # noqa: ANN001
    monkeypatch.setattr(ccc, "context_tokens_for", lambda _p: value)


def test_fires_on_resume_with_large_context(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """source=resume + context >= 270k → fires /compact (records cooldown), returns True."""
    hook, state, ccc, spawned, plugin_root = harness
    _set_ctx(monkeypatch, ccc, 600_000)

    fired = hook._maybe_cold_compact_on_session_start(state, plugin_root, "resume", "/x/session.jsonl")

    assert fired is True
    assert len(spawned) == 1, f"exactly one /compact spawn expected, got {spawned}"
    argv = spawned[0]
    assert argv[1].endswith("compact_trigger.py"), f"must spawn compact_trigger.py, got {argv}"
    assert "--directive" in argv
    directive = argv[argv.index("--directive") + 1]
    assert "cold-cache resume" in directive
    # cooldown stamp was written (blocks a racing heartbeat re-fire before the compact lands)
    stamp_ts = state.read_int_state(state.state_dir() / ccc._FIRED_STAMP, 0)
    assert stamp_ts > 0, "cold-compact must record a cooldown stamp"
    assert ccc.in_cooldown(state.state_dir(), now=stamp_ts + 1) is True


def test_fires_on_startup_with_large_context(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """`startup` is also eligible (a --continue may report startup on some builds); the
    size guard is the real gate."""
    hook, state, ccc, spawned, plugin_root = harness
    # Above the default threshold, which is floor-relative (350k > the 308,644 post-compaction
    # floor) — 300k used to qualify as "large" and no longer does, by design.
    _set_ctx(monkeypatch, ccc, 400_000)
    assert hook._maybe_cold_compact_on_session_start(state, plugin_root, "startup", "/x/s.jsonl") is True
    assert len(spawned) == 1


def test_no_fire_when_context_small(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """A small resumed context (a fresh session) → no fire, nothing spawned."""
    hook, state, ccc, spawned, plugin_root = harness
    _set_ctx(monkeypatch, ccc, 12_000)
    assert hook._maybe_cold_compact_on_session_start(state, plugin_root, "resume", "/x/s.jsonl") is False
    assert spawned == []


def test_no_fire_when_context_unknown(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """Unknown context (bad/empty transcript → None) → no fire."""
    hook, state, ccc, spawned, plugin_root = harness
    _set_ctx(monkeypatch, ccc, None)
    assert hook._maybe_cold_compact_on_session_start(state, plugin_root, "resume", "") is False
    assert spawned == []


@pytest.mark.parametrize("source", ["compact", "clear", "unknown-source", ""])
def test_no_fire_on_non_resume_source(harness, monkeypatch: pytest.MonkeyPatch, source: str) -> None:
    """Only startup/resume are eligible. A `compact` (our own /compact re-entering the
    hook), a `clear`, or any other source must NOT fire — even with a large context.
    This is the belt-and-suspenders that blocks a re-fire loop."""
    hook, state, ccc, spawned, plugin_root = harness
    _set_ctx(monkeypatch, ccc, 600_000)
    assert hook._maybe_cold_compact_on_session_start(state, plugin_root, source, "/x/s.jsonl") is False
    assert spawned == []


def test_no_fire_when_disabled(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """The opt-out knob disables it even for a large cold resume."""
    hook, state, ccc, spawned, plugin_root = harness
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_ENABLED", "false")
    _set_ctx(monkeypatch, ccc, 600_000)
    assert hook._maybe_cold_compact_on_session_start(state, plugin_root, "resume", "/x/s.jsonl") is False
    assert spawned == []


def test_no_fire_when_in_cooldown(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """A recent cold-compact (cooldown active) suppresses a second fire before the
    first one lands — no double /compact."""
    hook, state, ccc, spawned, plugin_root = harness
    _set_ctx(monkeypatch, ccc, 600_000)
    import time

    ccc.mark_fired(state.state_dir(), now=int(time.time()))  # fresh stamp → in cooldown
    assert hook._maybe_cold_compact_on_session_start(state, plugin_root, "resume", "/x/s.jsonl") is False
    assert spawned == []


def test_no_iterm_does_not_burn_the_cooldown(harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """REGRESSION (code-review): when the session can't self-compact (headless / NO_ITERM),
    the helper must report NOT-fired and must NOT stamp the cooldown. The old shape stamped
    it before a detached fire-and-forget, so a headless session burned the 600s window with
    no compaction — and that also suppressed the heartbeat trigger. Both trigger points must
    agree on what 'fired' means."""
    hook, state, ccc, spawned, plugin_root = harness
    _set_ctx(monkeypatch, ccc, 600_000)
    monkeypatch.setattr(
        state,
        "run_subprocess",
        lambda cmd, **_kw: SimpleNamespace(returncode=0, stdout="NO_ITERM\n", stderr=""),
    )

    fired = hook._maybe_cold_compact_on_session_start(state, plugin_root, "resume", "/x/s.jsonl")

    assert fired is False, "a session with no automatable pane did not compact"
    assert ccc.in_cooldown(state.state_dir(), now=int(time.time())) is False, (
        "cooldown must NOT be stamped when no compaction actually fired"
    )


def test_no_fire_when_compact_trigger_missing(harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """If plugin_root has no compact_trigger.py, the helper degrades to no-op (returns
    False), never spawning a bogus process."""
    hook, state, ccc, spawned, _plugin_root = harness
    _set_ctx(monkeypatch, ccc, 600_000)
    empty_root = tmp_path / "empty-root"
    (empty_root / "scripts").mkdir(parents=True)
    assert hook._maybe_cold_compact_on_session_start(state, str(empty_root), "resume", "/x/s.jsonl") is False
    assert spawned == []


def test_falls_back_to_newest_transcript_when_passed_path_unreadable(
        harness, monkeypatch: pytest.MonkeyPatch) -> None:
    """HARDENING (TRDD-D3PROACT): a resume can hand a STALE/rotated transcript path that yields
    no size. Before the fix that silently meant 'no compact' and the large cold context paid the
    full 2x write on turn one. Now the hook falls back to the project's NEWEST transcript, finds
    the real (large) size, and fires — so the burn this hook exists to prevent is actually caught."""
    hook, state, ccc, spawned, plugin_root = harness
    newest = Path("/tmp/real-newest-session.jsonl")
    monkeypatch.setattr(ccc, "newest_transcript", lambda _p: newest)
    # The passed (stale) path yields None; only the newest transcript has a (large) size.
    monkeypatch.setattr(
        ccc, "context_tokens_for",
        lambda p: 600_000 if p == newest else None,
    )
    fired = hook._maybe_cold_compact_on_session_start(state, plugin_root, "resume", "/x/stale.jsonl")
    assert fired is True, "the newest-transcript fallback must recover the size and fire"
    assert len(spawned) == 1 and spawned[0][1].endswith("compact_trigger.py")
