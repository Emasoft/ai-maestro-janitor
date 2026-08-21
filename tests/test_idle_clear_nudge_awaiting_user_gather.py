"""GATHER-layer test for the IN-MODEL idle-clear nudge (TRDD-UQW5IOAE, acceptance box 2).

Box 2 requires TWO layers because one is provably insufficient: (a) a PURE-layer
mutation/neuter test on `cold_cache_compact.should_clear_when_long_idle` (already covered in
`tests/test_cold_cache_compact.py` — flipping `active_waiting`/`user_present` is asserted to
change the verdict), and (b) a GATHER-layer test proving a real fixture transcript ending on an
unanswered `tool_use` refuses END TO END through `dispatch._phase_idle_clear_nudge`. (b) is not
optional: no mutation of a pure function can detect an input that is computed and then never
PASSED to it — that is exactly the shape of TRDD-OO301H7D (the EXTERNAL watcher path discarded
`awaiting_user` via `_, _await = ...` and the underscore convention hid it from review).

This test exercises the SAME class of wiring defect on the IN-MODEL path. Unlike
`tests/test_dispatch_phases.py::_arm_idle_clear`, which stubs
`fleet_scan.transcript_activity(root, now) -> (idle_s, 0, False)` (a HARDCODED `awaiting_user`,
matching production's own discard), this test does NOT stub `transcript_activity` — it writes a
real `~/.claude/projects/<slug>/*.jsonl` fixture and lets the real function compute
`awaiting_user`, so the assertion is only satisfied if that value actually reaches the decision.
"""

from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


def _iso(epoch: float) -> str:
    """A transcript-style UTC timestamp ('2026-07-17T16:55:41.000Z' shape)."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


@pytest.fixture
def env_isolation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Point project state, global state, and the transcript HOME at tmp dirs; reload dispatch
    + state so their `lru_cache`d path resolution picks up the new env (mirrors
    `test_dispatch_phases.env_isolation`, duplicated here so this file owns its own fixture and
    does not collide with another worker editing that file)."""
    project = tmp_path / "project"
    project.mkdir()
    global_dir = tmp_path / "janitor-global-state"

    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(global_dir))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "janitor-control"))
    monkeypatch.setenv("HOME", str(tmp_path))  # transcripts live under ~/.claude/projects/<slug>

    for mod in ("dispatch", "global_state", "state"):
        if mod in sys.modules:
            del sys.modules[mod]

    return {"project": project, "global_dir": global_dir}


def _import_dispatch():
    """Import scripts/dispatch.py without running main()."""
    import importlib.util as _u

    spec = _u.spec_from_file_location(
        "janitor_dispatch_under_test_gather",
        str(_PROJECT_ROOT / "scripts" / "dispatch.py"),
    )
    assert spec is not None and spec.loader is not None
    module = _u.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_idle_clear_nudge_refuses_a_real_transcript_ending_on_unanswered_tool_use(
    env_isolation: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A tail ending on an unanswered `ExitPlanMode`, written long enough ago to clear every
    OTHER gate (idle >> 1h, no cooldown, nobody present, no cadence-active-waiting), must still
    refuse — the session is parked on a question for a HUMAN, not abandoned. No mutation of
    `should_clear_when_long_idle` can catch this: the function is never given `awaiting_user` to
    begin with, so the defect (if present) is in what `_phase_idle_clear_nudge` gathers and
    passes, not in the pure gate itself."""
    import memory_scopes  # noqa: PLC0415

    project = env_isolation["project"]
    (project / ".janitor" / "state").mkdir(parents=True)

    now = int(time.time())
    slug = memory_scopes.project_slug(os.path.realpath(str(project)))
    tdir = Path(os.environ["HOME"]) / ".claude" / "projects" / slug
    tdir.mkdir(parents=True)
    lines = [
        json.dumps({"type": "assistant", "timestamp": _iso(now - 7200), "message": {}}),
        json.dumps(
            {
                "type": "assistant",
                "timestamp": _iso(now - 7100),
                "message": {
                    "content": [{"type": "tool_use", "id": "toolu_PLAN", "name": "ExitPlanMode"}]
                },
            }
        ),
    ]
    (tdir / "s1.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")

    import cold_cache_compact  # noqa: PLC0415
    import terminal_trigger  # noqa: PLC0415
    import user_intent  # noqa: PLC0415

    dispatch = _import_dispatch()

    monkeypatch.setattr(user_intent, "user_is_present", lambda **kw: False)
    monkeypatch.setattr(dispatch, "_cadence_active_waiting", lambda sd, now: False)
    monkeypatch.setattr(cold_cache_compact, "context_tokens_for", lambda t: 500_000)
    sent: list = []
    monkeypatch.setattr(
        terminal_trigger,
        "send_verified",
        lambda terminal, cmd, **kw: sent.append((cmd, kw)) or (True, "sent"),
    )

    assert dispatch._phase_idle_clear_nudge() is False, (
        "a session parked on an unanswered ExitPlanMode must never be auto-cleared, even "
        "though every other gate (idle time, cooldown, presence, cadence) is satisfied"
    )
    assert sent == [], "the command must not be injected while a human decision is pending"
