"""Heartbeat rate-limit cold-cache branch (TRDD-EUWIHP0G).

When an IN-SESSION rate-limit gap outlives the 1h prompt-cache TTL AND the resumed
context is large, `_phase_rate_limit_recovery` self-fires /compact FIRST (so the
inevitable ~600k cold cache-creation write shrinks to ~50k) instead of emitting the
normal `[janitor-resume]` cue — the resume arrives AFTER the compaction. These tests
pin that branch: it fires only when cold AND large, emits a NON-marker notice (never
`[janitor-resume]`), clears the rate-limit flags, stamps the cooldown, and — crucially —
FALLS THROUGH to the normal `[janitor-resume]` resume when the compact can't fire
(headless / NO_ITERM), so a resume is never stalled.

`run_subprocess` is monkeypatched so no real /compact is ever launched; the transcript
readers are monkeypatched so context size is deterministic. State I/O uses an isolated
CLAUDE_PROJECT_DIR.
"""

from __future__ import annotations

import importlib.util
import sys
import time
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))


def _import_dispatch():
    spec = importlib.util.spec_from_file_location(
        "janitor_dispatch_cold_cache", str(_ROOT / "scripts" / "dispatch.py")
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _run_capturing(fn):
    """Run fn() with stdout captured; return (stdout_text, fn_return_value)."""
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        result = fn()
    finally:
        sys.stdout = old
    return buf.getvalue(), result


@pytest.fixture
def iso(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gs"))
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_CADENCE_DYNAMIC", "false")
    for var in (
        "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_ENABLED",
        "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_IDLE_SECONDS",
        "CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_COOLDOWN_SECONDS",
    ):
        monkeypatch.delenv(var, raising=False)
    # Pin the compact threshold EXPLICITLY (these tests exercise the dispatch WIRING, not the
    # threshold value). Since the threshold is now HARNESS-RELATIVE (TRDD-P7WU40G9), leaving it
    # to the default would make it depend on the ambient CLAUDE_CODE_AUTO_COMPACT_WINDOW (700000
    # in a dev env → 716k threshold), so the 500k "large" cases would no longer trip. An explicit
    # override keeps the fixture deterministic: 500k > 350k = large; 50k / 312k < 350k = small.
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_MIN_CONTEXT_TOKENS", "350000")
    monkeypatch.delenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", raising=False)

    for mod in ("dispatch", "state", "global_state", "cold_cache_compact", "heartbeat_cadence"):
        sys.modules.pop(mod, None)

    dispatch = _import_dispatch()
    import cold_cache_compact as ccc
    import state

    state.init_state()
    # Never touch the real ~/.claude/projects: the size comes from the patched reader,
    # so the actual transcript path is irrelevant.
    monkeypatch.setattr(ccc, "newest_transcript", lambda _p: Path("/tmp/fake-session.jsonl"))
    return SimpleNamespace(dispatch=dispatch, state=state, ccc=ccc, project=project)


def _patch_run(monkeypatch: pytest.MonkeyPatch, iso, stdout: str, returncode: int = 0):
    """Replace state.run_subprocess with a recorder that returns a fixed result."""
    calls: list[list[str]] = []

    def _run(cmd, **_kw):  # noqa: ANN001, ANN003
        calls.append(list(cmd))
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(iso.state, "run_subprocess", _run)
    return calls


def _set_ctx(monkeypatch: pytest.MonkeyPatch, iso, value) -> None:  # noqa: ANN001
    monkeypatch.setattr(iso.ccc, "context_tokens_for", lambda _p: value)


# --------------------------------------------------------------------------- #
# _maybe_cold_compact_on_rate_limit — the branch in isolation                  #
# --------------------------------------------------------------------------- #

def test_fires_when_cold_and_large(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """age >= 1h AND context large AND COMPACT_FIRED → returns True, emits a NON-marker
    notice, clears the rate-limit flags, stamps the cooldown, and spawns compact_trigger."""
    d, state, ccc = iso.dispatch, iso.state, iso.ccc
    sd = state.state_dir()
    (sd / "rate-limited.flag").write_text("1", encoding="utf-8")
    (sd / "rate-limited-since.ts").write_text("0", encoding="utf-8")
    _set_ctx(monkeypatch, iso, 500_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")

    now = int(time.time())
    out, ret = _run_capturing(lambda: d._maybe_cold_compact_on_rate_limit(sd, 5_000, now))
    assert ret is True

    # A NON-marker notice, never the bare [janitor-resume] marker (which would start a
    # resume into a context about to be compacted).
    assert "[janitor-resume]" not in out
    assert "prompt cache is cold" in out
    assert "/compact" in out
    # Spawned compact_trigger.py with a cold-cache directive.
    assert len(calls) == 1 and calls[0][1].endswith("compact_trigger.py")
    assert "--directive" in calls[0]
    # Flags cleared + cooldown stamped.
    assert not (sd / "rate-limited.flag").exists()
    assert not (sd / "rate-limited-since.ts").exists()
    assert ccc.in_cooldown(sd, now=now + 1) is True


def test_no_fire_when_warm(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """A sub-TTL gap (warm cache) → returns False and never even reads the transcript
    (the cheap age gate short-circuits before run_subprocess)."""
    d, state = iso.dispatch, iso.state
    sd = state.state_dir()
    _set_ctx(monkeypatch, iso, 500_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")
    assert d._maybe_cold_compact_on_rate_limit(sd, 600, int(time.time())) is False
    assert calls == [], "warm cache must not fire /compact"


def test_no_fire_when_small_context(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cold but small context → returns False, nothing spawned."""
    d, state = iso.dispatch, iso.state
    sd = state.state_dir()
    _set_ctx(monkeypatch, iso, 50_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")
    assert d._maybe_cold_compact_on_rate_limit(sd, 5_000, int(time.time())) is False
    assert calls == []


def test_falls_through_on_no_iterm(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE STALL GUARD: cold + large but the session can't self-compact (NO_ITERM) →
    returns False (so the caller emits the normal resume), and it must NOT clear the
    rate-limit flags or stamp the cooldown (a resume must still happen)."""
    d, state, ccc = iso.dispatch, iso.state, iso.ccc
    sd = state.state_dir()
    (sd / "rate-limited.flag").write_text("1", encoding="utf-8")
    (sd / "rate-limited-since.ts").write_text("0", encoding="utf-8")
    _set_ctx(monkeypatch, iso, 500_000)
    _patch_run(monkeypatch, iso, "NO_ITERM\n")  # trigger couldn't self-compact

    now = int(time.time())
    assert d._maybe_cold_compact_on_rate_limit(sd, 5_000, now) is False
    assert (sd / "rate-limited.flag").exists(), "flags must survive so the normal resume still fires"
    assert ccc.in_cooldown(sd, now=now + 1) is False, "no cooldown stamped when the compact didn't fire"


def test_no_fire_when_disabled(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    d, state = iso.dispatch, iso.state
    sd = state.state_dir()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_COLD_CACHE_COMPACT_ENABLED", "false")
    _set_ctx(monkeypatch, iso, 500_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")
    assert d._maybe_cold_compact_on_rate_limit(sd, 5_000, int(time.time())) is False
    assert calls == []


def test_no_fire_when_in_cooldown(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    d, state, ccc = iso.dispatch, iso.state, iso.ccc
    sd = state.state_dir()
    _set_ctx(monkeypatch, iso, 500_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")
    now = int(time.time())
    ccc.mark_fired(sd, now=now)  # fresh stamp → in cooldown
    assert d._maybe_cold_compact_on_rate_limit(sd, 5_000, now) is False
    assert calls == []


# --------------------------------------------------------------------------- #
# _phase_rate_limit_recovery — the branch wired into the phase                 #
# --------------------------------------------------------------------------- #

def test_phase_cold_branch_replaces_resume_cue(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """With the cold branch firing, _phase_rate_limit_recovery emits the NON-marker cold
    notice (NOT [janitor-resume]) and still returns True so main() skips the detectors."""
    d, state = iso.dispatch, iso.state
    sd = state.state_dir()
    (sd / "rate-limited.flag").write_text("1", encoding="utf-8")
    (sd / "rate-limited-since.ts").write_text(str(int(time.time()) - 6_000), encoding="utf-8")
    _set_ctx(monkeypatch, iso, 500_000)
    _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")

    out, ret = _run_capturing(d._phase_rate_limit_recovery)
    assert ret is True
    assert "[janitor-resume]" not in out, "the cold branch must NOT emit the resume marker"
    assert "prompt cache is cold" in out


def test_phase_normal_resume_when_not_cold(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """When the cold branch does NOT fire (warm cache), the phase emits the normal
    [janitor-resume] cue exactly as before — behavior preserved."""
    d, state = iso.dispatch, iso.state
    sd = state.state_dir()
    (sd / "rate-limited.flag").write_text("1", encoding="utf-8")
    (sd / "rate-limited-since.ts").write_text(str(int(time.time()) - 30), encoding="utf-8")
    _set_ctx(monkeypatch, iso, 500_000)  # large, but the gap is warm (30s)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")

    out, ret = _run_capturing(d._phase_rate_limit_recovery)
    assert ret is True
    assert out.startswith("[janitor-resume]"), "warm resume must emit the normal marker"
    assert "rate-limit cleared" in out
    assert calls == [], "no /compact fired on a warm resume"


def test_phase_normal_resume_falls_through_on_no_iterm(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """Cold + large but headless (NO_ITERM): the phase must still emit the normal
    [janitor-resume] — a resume is NEVER stalled behind a compact that can't run."""
    d, state = iso.dispatch, iso.state
    sd = state.state_dir()
    (sd / "rate-limited.flag").write_text("1", encoding="utf-8")
    (sd / "rate-limited-since.ts").write_text(str(int(time.time()) - 6_000), encoding="utf-8")
    _set_ctx(monkeypatch, iso, 500_000)
    _patch_run(monkeypatch, iso, "NO_ITERM\n")

    out, ret = _run_capturing(d._phase_rate_limit_recovery)
    assert ret is True
    assert out.startswith("[janitor-resume]"), "headless cold resume must fall through to the normal cue"
    assert "rate-limit cleared" in out


# --------------------------------------------------------------------------- #
# TRDD-D3PROACT — _phase_proactive_idle_compact (the PREVENTIVE path)          #
# --------------------------------------------------------------------------- #

def _patch_idle(monkeypatch: pytest.MonkeyPatch, iso, *, present: bool, active: bool) -> None:
    """Stub the two runtime idle signals the proactive phase reads."""
    import user_intent
    monkeypatch.setattr(user_intent, "user_is_present", lambda **_k: present)
    monkeypatch.setattr(iso.dispatch, "_cadence_active_waiting", lambda *_a, **_k: active)


def test_proactive_idle_fires_when_absent_idle_and_large(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """The prevention: user absent + nothing pending + large context → queue /compact NOW during
    a warm fire, emit a NON-marker notice (never [janitor-resume]), stamp the cooldown, spawn
    compact_trigger. This is what keeps the context small so a future cold event is cheap."""
    d, state, ccc = iso.dispatch, iso.state, iso.ccc
    sd = state.state_dir()
    _patch_idle(monkeypatch, iso, present=False, active=False)
    _set_ctx(monkeypatch, iso, 500_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")

    out, ret = _run_capturing(lambda: d._phase_proactive_idle_compact())
    assert ret is True
    assert "[janitor-resume]" not in out
    assert "/compact" in out and "large context" in out
    assert len(calls) == 1 and calls[0][1].endswith("compact_trigger.py")
    assert ccc.in_cooldown(sd, now=int(time.time()) + 1) is True


def test_proactive_idle_never_fires_when_user_present(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """A present user vetoes — compaction must never fire out from under active work."""
    d = iso.dispatch
    _patch_idle(monkeypatch, iso, present=True, active=False)
    _set_ctx(monkeypatch, iso, 500_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")
    out, ret = _run_capturing(lambda: d._phase_proactive_idle_compact())
    assert ret is False and out == "" and calls == []


def test_proactive_idle_never_fires_when_active_waiting(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """A pending resume / keep-going / directive / agent vetoes — the session has queued work."""
    d = iso.dispatch
    _patch_idle(monkeypatch, iso, present=False, active=True)
    _set_ctx(monkeypatch, iso, 500_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")
    _, ret = _run_capturing(lambda: d._phase_proactive_idle_compact())
    assert ret is False and calls == []


def test_proactive_idle_never_fires_on_small_context(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """A small context saves nothing and would be a pointless lossy compaction."""
    d = iso.dispatch
    _patch_idle(monkeypatch, iso, present=False, active=False)
    _set_ctx(monkeypatch, iso, 50_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")
    _, ret = _run_capturing(lambda: d._phase_proactive_idle_compact())
    assert ret is False and calls == []


def test_proactive_idle_no_cooldown_stamp_when_compact_cannot_fire(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """NO_ITERM / headless: the compact can't run, so DON'T stamp the cooldown — a stamp with no
    compact would suppress the SessionStart + rate-limit paths too (the three must agree on fired)."""
    d, state, ccc = iso.dispatch, iso.state, iso.ccc
    sd = state.state_dir()
    _patch_idle(monkeypatch, iso, present=False, active=False)
    _set_ctx(monkeypatch, iso, 500_000)
    _patch_run(monkeypatch, iso, "NO_ITERM\n")
    _, ret = _run_capturing(lambda: d._phase_proactive_idle_compact())
    assert ret is False
    assert ccc.in_cooldown(sd, now=int(time.time()) + 1) is False


def test_proactive_idle_respects_opt_out(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """The dedicated knob turns prevention off while leaving the reactive backstops alone."""
    d = iso.dispatch
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_PROACTIVE_IDLE_COMPACT_ENABLED", "false")
    _patch_idle(monkeypatch, iso, present=False, active=False)
    _set_ctx(monkeypatch, iso, 500_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")
    _, ret = _run_capturing(lambda: d._phase_proactive_idle_compact())
    assert ret is False and calls == []


def test_proactive_idle_learns_floor_through_its_own_side_effects(iso, monkeypatch: pytest.MonkeyPatch) -> None:
    """THE v0.49.0 REGRESSION (TRDD-28XF77X6), heartbeat side: the compact this phase fires
    stamps the cooldown itself, and the compaction's auto-resume holds active-waiting for
    30 min — so a floor measurement placed behind those gates never ran, and the loop-killing
    gain gate stayed inert in production. The measurement must run on the very next fire,
    through the closed gates; the compact ACTION must still be vetoed by them."""
    d, state, ccc = iso.dispatch, iso.state, iso.ccc
    sd = state.state_dir()
    now = int(time.time())
    ccc.mark_fired(sd, now=now)  # the compact this phase fired started the cooldown…
    ccc.mark_compacted(sd, now=now)  # …the compaction landed…
    _patch_idle(monkeypatch, iso, present=False, active=True)  # …and its auto-resume is pending
    _set_ctx(monkeypatch, iso, 312_000)
    calls = _patch_run(monkeypatch, iso, "COMPACT_FIRED\n")

    out, ret = _run_capturing(lambda: d._phase_proactive_idle_compact())
    assert ret is False and calls == [], "cooldown + active-waiting must veto the compact"
    assert out == ""
    assert ccc.read_floor(sd)[0] == 312_000, "but the floor must still be learned on this fire"
