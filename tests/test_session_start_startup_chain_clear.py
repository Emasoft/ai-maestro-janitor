"""A chain-clear that re-enters SessionStart as STARTUP must still run the post-clear service
(TRDD-C7M4RXQ2).

The janitor's `clear_trigger.py` types `/clear` into the pane; on some platforms the harness
re-enters SessionStart for the cleared session as a FRESH process reporting `source=startup`
(restart #1, 2026-09-25: the handoff was composed and on disk, the fresh session injected
NOTHING, and the agent sat idle until the owner typed "resume" by hand). `main()` used to gate
the ENTIRE clear service on `source == "clear"`.

The service must be gated on EVIDENCE that a clear just happened, not the source string: a
fresh `resume-after-clear.flag` + a fresh PER-PANE sidecar for this pane. On startup with no
pending flag, behaviour is byte-identical to pre-C7M4RXQ2.

OWNERSHIP (one decision site, `_startup_chain_clear_service`): a fresh sidecar (unconsumed, or
`.consumed-<epoch>` within the dedicated hook's minutes-scale window) means
`on-session-start-post-clear-compact.py` owns the BODY — this hook stamps and injects NOTHING.
Nothing fresh means stamp + the honest POINTER directly (deliberately never
`_inject_post_clear_handoff`, whose own sidecar defer-glob is UNBOUNDED and would return
silently on a stale `.consumed-*` — the exact silence this card kills). The flag is NEVER
unlinked here: `dispatch.py::_phase_clear_resume` owns consuming it.

The hook runs as a SUBPROCESS, the way Claude Code actually runs it — same pattern (and same
in-process `@lru_cache` rationale) as `tests/test_session_start_clear_observed.py`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
HOOK = REPO / "scripts" / "hooks" / "on-session-start.py"
POST_CLEAR_HOOK = REPO / "scripts" / "hooks" / "on-session-start-post-clear-compact.py"

# Mirrors the dedicated hook's own `_SIDECAR_FRESH_MAX_AGE_S` (a DUPLICATE there too — the
# filename is hyphenated and unimportable). Used only to write test fixtures at the window's
# boundary, never to assert an exact threshold behaviour.
_SIDECAR_FRESH_MAX_AGE_S = 300


def _seed_and_run(tmp_path: Path, *, source: str, seed: dict | None = None) -> tuple[Path, str]:
    """Seed the project state dir, then run the SessionStart hook as Claude Code does.

    `seed` names state files to write BEFORE the run: `"flag"` (+ `.ts` sidecar at
    `flag_age_s`), `"sidecar"` (fresh, this pane), `"sidecar_consumed_fresh"`,
    `"sidecar_consumed_stale"`, `"handoff"` (a legacy `agent-handoff.md` for the pointer to
    name). Returns (state dir, hook stdout).
    """
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    # The plugin must look installed, or scope detection short-circuits before the hook
    # reaches the branch under test.
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ai-maestro-janitor@ai-maestro-plugins": True}}),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    sd = project / ".janitor" / "state"
    sd.mkdir(parents=True)

    now = int(time.time())
    if seed and "flag" in seed:
        (sd / "resume-after-clear.flag").write_text("resume your prior task", encoding="utf-8")
        (sd / "resume-after-clear.ts").write_text(
            str(now - seed.get("flag_age_s", 0)), encoding="utf-8"
        )
    if seed and "sidecar" in seed:
        (sd / "resume-after-clear.tmux-3.transcript").write_text(
            f"{tmp_path / 'cleared.jsonl'}\n{now}\n", encoding="utf-8"
        )
    if seed and "sidecar_consumed_fresh" in seed:
        consumed = sd / f"resume-after-clear.tmux-3.transcript.consumed-{now}"
        consumed.write_text(f"{tmp_path / 'cleared.jsonl'}\n{now}\n", encoding="utf-8")
    if seed and "sidecar_consumed_stale" in seed:
        (sd / "resume-after-clear.tmux-3.transcript.consumed-1000000000").write_text(
            f"{tmp_path / 'cleared.jsonl'}\n1000000000\n", encoding="utf-8"
        )
    if seed and "handoff" in seed:
        (sd / "agent-handoff.md").write_text(
            "# Handoff\n\nNEXT ACTION: finish TRDD-C7M4RXQ2.", encoding="utf-8"
        )

    env = {
        **os.environ,
        "HOME": str(home),
        "CLAUDE_PLUGIN_ROOT": str(REPO),
        "CLAUDE_PROJECT_DIR": str(project),
        # The pane id the hook resolves ITS sidecar key from — the same
        # `pane_key_from_terminal(self_terminal(env))` the writer side uses.
        "TMUX_PANE": "%3",
        # Never touch the real machine: no daemon spawn, no OS keepalive, no real
        # global state.
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "global-state"),
        "CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED": "false",
        "CLAUDE_PLUGIN_OPTION_OS_KEEPALIVE_ENABLED": "false",
    }

    proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        [sys.executable, str(HOOK)],
        input=json.dumps(
            {"source": source, "session_id": "sid-1", "transcript_path": ""}
        ),
        capture_output=True,
        text=True,
        timeout=120,
        env=env,
        cwd=str(project),
    )
    assert "Traceback" not in proc.stderr, (
        f"the hook crashed, so any assertion below would be vacuous:\n{proc.stderr[:2000]}"
    )
    return sd, proc.stdout


def _diagnosis(sd: Path) -> str:
    """Why a file is missing, from the hook's own log — a wrong `source` and a failed write
    both leave no file, and the hook logs BOTH (same rationale as
    `test_session_start_clear_observed._diagnosis`)."""
    log = sd.parent / "logs" / "session-start.log"
    return (
        f"\n  state dir contents: {sorted(p.name for p in sd.glob('*')) if sd.is_dir() else 'MISSING'}"
        f"\n  session-start.log tail: {log.read_text(encoding='utf-8')[-600:] if log.is_file() else 'no log'}"
    )


def test_startup_with_fresh_flag_and_sidecar_stamps_but_injects_nothing(tmp_path: Path) -> None:
    """THE 2026-09-25 SHAPE, positive arm: flag + fresh per-pane sidecar + source=startup →
    `clear-observed.ts` stamped (dispatch's `_phase_clear_resume` can now ARM, and the chain's
    own `_await_fresh_session` gate is satisfied), the observing session id stamped, and this
    hook injects NOTHING — the dedicated `on-session-start-post-clear-compact.py` hook owns
    the body for a sidecar-bearing clear (its source gate accepts startup since phase 2 of
    this card; it is a SEPARATE hook process, so this test still runs on-session-start.py
    alone and asserts THIS hook stays silent).

    A second stamp overwriting an earlier clear's `clear-observed.ts` seconds later is an
    overwrite with the same epoch — expected-harmless (see
    `_stamp_clear_observation`'s docstring), so a future reader does not re-litigate it."""
    sd, out = _seed_and_run(
        tmp_path, source="startup", seed={"flag": True, "sidecar": True}
    )
    stamp = sd / "clear-observed.ts"
    assert stamp.is_file(), "the startup chain-clear must record the observation" + _diagnosis(sd)
    observed = int(stamp.read_text(encoding="utf-8").strip())
    assert int(time.time()) - 5 <= observed <= int(time.time()) + 1, f"stale epoch: {observed}"
    session_id = sd / "resume-after-clear.session-id.txt"
    assert session_id.is_file(), "the observing session id must be stamped" + _diagnosis(sd)
    assert session_id.read_text(encoding="utf-8").strip() == "sid-1"
    assert "[janitor-handoff]" not in out, (
        "the dedicated post-clear-compact hook owns the body — this hook must stay silent"
    )
    # The heartbeat (`dispatch._phase_clear_resume`) is still the actuator: the flag survives.
    assert (sd / "resume-after-clear.flag").is_file(), (
        "the startup service must never unlink the flag — dispatch owns consuming it"
    )


def test_startup_without_flag_is_byte_identical_to_the_old_path(tmp_path: Path) -> None:
    """Negative arm: startup with NO pending flag — a genuinely fresh pane or project — runs
    none of the service: no stamp, no session-id file, no pointer, no injection. Identical to
    the pre-C7M4RXQ2 behaviour. Paired with positive log proof the hook parsed this source,
    so a hook that died before the branch cannot pass vacuously."""
    sd, out = _seed_and_run(tmp_path, source="startup")
    log = (sd.parent / "logs" / "session-start.log").read_text(encoding="utf-8")
    assert "source=startup" in log, f"the hook did not reach the source branch{_diagnosis(sd)}"
    assert not (sd / "clear-observed.ts").exists(), "no flag ⇒ no clear evidence ⇒ no stamp"
    assert not (sd / "resume-after-clear.session-id.txt").exists(), (
        "the session-id stamp rides the same evidence gate" + _diagnosis(sd)
    )
    assert "[janitor-handoff]" not in out, "nothing to resume must inject or point at nothing"


def test_startup_with_stale_flag_is_byte_identical_to_the_old_path(tmp_path: Path) -> None:
    """A day-old flag on a reused pane is NOT this pane's clear: past the same
    `CLAUDE_PLUGIN_OPTION_CLEAR_RESUME_MAX_AGE_S` bound the clear path and dispatch use, the
    service must not arm a fresh pane's startup."""
    sd, out = _seed_and_run(
        tmp_path, source="startup", seed={"flag": True, "flag_age_s": 86400 * 3}
    )
    assert not (sd / "clear-observed.ts").exists(), (
        "a 3-day-old flag must not arm a fresh pane's clear" + _diagnosis(sd)
    )
    assert not (sd / "resume-after-clear.session-id.txt").exists()
    assert "[janitor-handoff]" not in out


def test_startup_with_fresh_flag_and_no_sidecar_falls_through_to_the_pointer(tmp_path: Path) -> None:
    """Flag fresh, sidecar ABSENT (e.g. reload-shrink, or an unresolvable pane at write time):
    stamps still land, and the honest POINTER names the newest handoff — never a full body,
    never silence. This is the arm round-2's keyed-path decision calls for."""
    sd, out = _seed_and_run(
        tmp_path, source="startup", seed={"flag": True, "handoff": True}
    )
    assert (sd / "clear-observed.ts").is_file(), (
        "a fresh flag is evidence enough to stamp the observation" + _diagnosis(sd)
    )
    assert "agent-handoff.md" in out, "the pointer must NAME the handoff it found"
    assert "NOT injected because" in out, "pointer, not body — and the reason must say why"
    assert "NEXT ACTION: finish TRDD-C7M4RXQ2." not in out, (
        "the handoff BODY must never be injected without per-pane sidecar evidence"
    )


def test_startup_with_stale_consumed_sidecar_emits_the_pointer(tmp_path: Path) -> None:
    """The epoch-freshness bound on `.consumed-<epoch>`: a consumed sidecar for this pane
    whose consume epoch is OUTSIDE the minutes-scale window is yesterday's clear, not this
    one. The service must fall through to the POINTER — asserting merely "no body" would pass
    while the silence hole ships, so the pointer's presence IS the assertion."""
    sd, out = _seed_and_run(
        tmp_path,
        source="startup",
        seed={"flag": True, "sidecar_consumed_stale": True, "handoff": True},
    )
    assert (sd / "clear-observed.ts").is_file(), (
        "a fresh flag still stamps the observation even when the sidecar is stale"
        + _diagnosis(sd)
    )
    assert "agent-handoff.md" in out, (
        "a stale consumed sidecar must fall through to the pointer — never silence"
    )
    assert "NOT injected because" in out


def test_startup_with_fresh_consumed_sidecar_stamps_but_injects_nothing(tmp_path: Path) -> None:
    """The dedicated hook already consumed this pane's sidecar this start (the
    `.consumed-<epoch>` rename retains the pane prefix, so the pane-scoped glob sees it): the
    body was or will be delivered by the dedicated hook — this hook stamps and stays silent,
    so the fresh session is never woken twice."""
    sd, out = _seed_and_run(
        tmp_path,
        source="startup",
        seed={"flag": True, "sidecar_consumed_fresh": True, "handoff": True},
    )
    assert (sd / "clear-observed.ts").is_file(), (
        "a freshness-bounded consumed sidecar still proves the clear" + _diagnosis(sd)
    )
    assert "[janitor-handoff] A handoff from a prior session exists" not in out, (
        "no pointer for a clear the dedicated hook just injected the body for — no double wake"
    )


def test_a_real_clear_source_still_stamps_via_the_shared_helper(tmp_path: Path) -> None:
    """The clear branch now routes its stamps through the SAME `_stamp_clear_observation` the
    startup arm uses — one extraction, both callers. Pin the extraction itself: source=clear
    must still stamp both files (the dedicated per-case coverage lives in
    `test_session_start_clear_observed.py`)."""
    sd, _out = _seed_and_run(tmp_path, source="clear", seed={"handoff": True})
    assert (sd / "clear-observed.ts").is_file(), (
        "the shared helper must keep the clear path stamping" + _diagnosis(sd)
    )
    assert (sd / "resume-after-clear.session-id.txt").is_file()


def test_duplicated_sidecar_fresh_max_age_constants_match_across_hooks() -> None:
    """The two hooks carry a DUPLICATE `_SIDECAR_FRESH_MAX_AGE_S` (hyphenated filename is
    unimportable, so both files are read as text). The two constants gate the SAME sidecar
    race from two processes; a silent mismatch makes both hooks defer to nothing (review
    round 6, TRDD-C7M4RXQ2)."""
    pattern = re.compile(r"^_SIDECAR_FRESH_MAX_AGE_S\s*=\s*(\d+)\s*$", re.MULTILINE)
    values: dict[str, str] = {}
    for hook in (HOOK, POST_CLEAR_HOOK):
        matches = pattern.findall(hook.read_text())
        assert len(matches) == 1, f"{hook.name} must define _SIDECAR_FRESH_MAX_AGE_S exactly once"
        values[hook.name] = matches[0]
    assert values[HOOK.name] == values[POST_CLEAR_HOOK.name], (
        f"the duplicated constants drifted: {values} — the two hooks gate the same "
        "sidecar race and a mismatch makes both defer to nothing"
    )
