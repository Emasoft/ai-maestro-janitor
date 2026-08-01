"""Tests for the window-burn-rate alarm (TRDD-OY0W6LX5).

Real I/O, no mocks, NO network: the burn verdict is the pure `token_burn` layer, exercised
with hand-built `/api/oauth/usage` payloads; the detector is exercised only via subprocess on
its network-free early-return paths (opt-out flag off, and not-yet-due). The usage-probing
path is never hit — that is deliberately behind the rotator gather the tests bypass.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_LIB = _PROJECT_ROOT / "scripts" / "lib"
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "window-burn-rate.py"

sys.path.insert(0, str(_LIB))
import token_burn as tbn  # noqa: E402

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"

# Load the hyphenated detector module by path so its private helpers are unit-testable
# in-process (no mocks — the agentlensPro enrichment tests below drive it with REAL subprocess
# scripts). Import runs only top-level code (imports + an alias); main() is __main__-guarded.
import importlib.util  # noqa: E402

_wbr_spec = importlib.util.spec_from_file_location("window_burn_rate_detector", _DETECTOR)
assert _wbr_spec is not None and _wbr_spec.loader is not None
_wbr = importlib.util.module_from_spec(_wbr_spec)
_wbr_spec.loader.exec_module(_wbr)

# Hour-aligned synthetic NOW so window arithmetic is exact.
NOW = 1_800_000_000
_5H = 5 * 3600
_7D = 7 * 86400


def _iso(epoch: int) -> str:
    """Epoch → UTC ISO-8601 with a trailing `Z` (the shape /api/oauth/usage emits)."""
    return datetime.fromtimestamp(epoch, tz=timezone.utc).replace(tzinfo=None).isoformat() + "Z"


def _reset_for(window_s: int, elapsed_fraction: float) -> str:
    """The `resets_at` ISO string that puts `NOW` at `elapsed_fraction` of a `window_s`
    window (start = resets − window_s → elapsed = 1 − remaining/window_s)."""
    return _iso(NOW + int(window_s * (1.0 - elapsed_fraction)))


def _usage(*, five: tuple[float, str] | None = None, seven: tuple[float, str] | None = None) -> dict:
    """Build a usage payload from optional (utilization, resets_at) tuples per window."""
    out: dict = {}
    if five is not None:
        out["five_hour"] = {"utilization": five[0], "resets_at": five[1]}
    if seven is not None:
        out["seven_day"] = {"utilization": seven[0], "resets_at": seven[1]}
    return out


def _acct(label: str, usage: dict) -> list[dict]:
    return [{"label": label, "usage": usage}]


def test_evaluate_trips_at_1_6x() -> None:
    """7d at 46% with 2/7 of the window elapsed → 1.61× pace → one drift line naming the
    window, util, ratio and the account prefix."""
    usage = _usage(seven=(46.0, _reset_for(_7D, 2 / 7)))
    lines = tbn.evaluate(_acct("fmuaddib", usage), NOW, 1.5, 10.0)
    assert len(lines) == 1
    line = lines[0]
    assert "7d window 46%" in line and "1.6x linear pace" in line and "fmuaddib" in line


def test_evaluate_silent_at_1_2x() -> None:
    """60% at half the window elapsed → 1.2× pace → below the 1.5× bar → no alarm."""
    usage = _usage(seven=(60.0, _reset_for(_7D, 0.5)))
    assert tbn.evaluate(_acct("acct", usage), NOW, 1.5, 10.0) == []


def test_evaluate_min_util_floor_suppresses_low_use() -> None:
    """A high ratio on a barely-used window (8% util) is floored by min_util=10 → silent;
    lowering the floor to 5 lets the same window trip (proves the floor is what suppressed it)."""
    usage = _usage(seven=(8.0, _reset_for(_7D, 0.02)))  # 0.08 / 0.02 = 4.0× but util 8 < 10
    assert tbn.evaluate(_acct("acct", usage), NOW, 1.5, 10.0) == []
    assert len(tbn.evaluate(_acct("acct", usage), NOW, 1.5, 5.0)) == 1


def test_evaluate_malformed_resets_at_skipped() -> None:
    """A window whose resets_at is unparseable is dropped, never alarmed or crashed."""
    usage = {"seven_day": {"utilization": 99.0, "resets_at": "not-a-date"}}
    assert tbn.evaluate(_acct("acct", usage), NOW, 1.5, 10.0) == []


def test_account_prefix_is_local_part_only() -> None:
    """The label is the email local part only (privacy) — never the full address in a line."""
    assert tbn.account_prefix("fmuaddib@gmail.com") == "fmuaddib"
    assert tbn.account_prefix(None) == "live"
    assert tbn.account_prefix("") == "live"
    usage = _usage(seven=(46.0, _reset_for(_7D, 2 / 7)))
    line = tbn.evaluate(_acct(tbn.account_prefix("secret@example.com"), usage), NOW, 1.5, 10.0)[0]
    assert "secret" in line and "@" not in line


def test_evaluate_reports_projected_exhaustion_when_early() -> None:
    """A tripped window that will exhaust before its reset reports the projected exhaustion
    and the lead time."""
    usage = _usage(seven=(46.0, _reset_for(_7D, 2 / 7)))
    line = tbn.evaluate(_acct("acct", usage), NOW, 1.5, 10.0)[0]
    assert "projected exhaustion" in line and "before reset" in line


def test_windows_from_usage_parses_both_windows() -> None:
    """Both windows present + parseable → two computed window dicts with a real burn ratio."""
    usage = _usage(five=(80.0, _reset_for(_5H, 0.5)), seven=(46.0, _reset_for(_7D, 2 / 7)))
    wins = tbn.windows_from_usage(usage, NOW)
    assert {w["label"] for w in wins} == {"5h", "7d"}
    assert all(w["burn_ratio"] is not None for w in wins)


def _limit(
    *,
    group: str,
    percent: float,
    resets_at: str | None,
    model: str | None = None,
    kind: str = "weekly_scoped",
    severity: str = "normal",
    is_active: bool = False,
) -> dict:
    """One `limits[]` entry in the exact shape /api/oauth/usage emits (verified against a
    live payload 2026-08-01): unscoped entries carry `scope: null`."""
    scope = {"model": {"id": None, "display_name": model}, "surface": None} if model else None
    return {
        "kind": kind, "group": group, "percent": percent, "severity": severity,
        "resets_at": resets_at, "scope": scope, "is_active": is_active,
    }


# --------------------------------------------------------------------------- #
# idle accounts: a window that is not moving has no pace to be above
# --------------------------------------------------------------------------- #
def test_idle_account_does_not_trip() -> None:
    """The real 2026-08-01 false alarm: `five_hour = {0.0, resets_at: null}` (no session
    window open) with `seven_day` at 94% — an ALTERNATE account consuming nothing. It must
    stay silent, and the control proves the 1.6x ratio is otherwise trip-worthy, i.e. the
    idle gate is what suppressed it and not the threshold."""
    idle = _usage(five=(0.0, None), seven=(94.0, _reset_for(_7D, 0.58)))  # type: ignore[arg-type]
    assert tbn.evaluate(_acct("acct", idle), NOW, 1.5, 5.0) == []
    control = _usage(seven=(94.0, _reset_for(_7D, 0.58)))
    assert len(tbn.evaluate(_acct("acct", control), NOW, 1.5, 5.0)) == 1


def test_unknown_session_state_still_trips() -> None:
    """A payload with NO `five_hour` key at all cannot prove the account idle, so the alarm
    still fires — the gate fails TOWARD coverage, never toward silence."""
    assert tbn.session_is_open({"seven_day": {}}, NOW) is None
    usage = _usage(seven=(94.0, _reset_for(_7D, 0.58)))
    assert len(tbn.evaluate(_acct("acct", usage), NOW, 1.5, 5.0)) == 1


def test_session_is_open_reads_the_reset_boundary() -> None:
    """Open (future reset) → True; null, unparseable, or already-past reset → False (the
    API's shape for 'no session running'); absent bucket → None (unknown)."""
    assert tbn.session_is_open({"five_hour": {"utilization": 3.0, "resets_at": _iso(NOW + 900)}}, NOW) is True
    assert tbn.session_is_open({"five_hour": {"utilization": 0.0, "resets_at": None}}, NOW) is False
    assert tbn.session_is_open({"five_hour": {"utilization": 0.0, "resets_at": "nope"}}, NOW) is False
    assert tbn.session_is_open({"five_hour": {"utilization": 9.0, "resets_at": _iso(NOW - 60)}}, NOW) is False
    assert tbn.session_is_open({}, NOW) is None


def test_an_actively_burning_account_is_never_idle() -> None:
    """The gate cannot hide a genuine burn: a window that is actually being spent has an
    open session by construction, so the live 5h window keeps its own alarm."""
    usage = _usage(five=(80.0, _reset_for(_5H, 0.4)), seven=(94.0, _reset_for(_7D, 0.58)))
    labels = {ln.split(" window")[0].rsplit(" ", 1)[-1] for ln in tbn.evaluate(_acct("a", usage), NOW, 1.5, 5.0)}
    assert labels == {"5h", "7d"}


# --------------------------------------------------------------------------- #
# whose window is it?
# --------------------------------------------------------------------------- #
def test_line_names_live_vs_alternate_account() -> None:
    """A burn line must say WHICH account it describes. Two accounts differ only by an email
    prefix, so without this marker a reader assumes the line is about their own session —
    the exact mis-read that made a 94% ALTERNATE look like the live account's window."""
    usage = _usage(seven=(46.0, _reset_for(_7D, 2 / 7)))
    live = tbn.evaluate_trips([{"label": "acct", "usage": usage, "is_live": True}], NOW, 1.5, 10.0)
    alt = tbn.evaluate_trips([{"label": "acct", "usage": usage, "is_live": False}], NOW, 1.5, 10.0)
    assert "(live)" in live[0]["line"] and "(alternate)" not in live[0]["line"]
    assert "(alternate)" in alt[0]["line"] and "(live)" not in alt[0]["line"]


def test_marker_omitted_when_liveness_unknown() -> None:
    """A caller that cannot tell live from alternate gets NO marker — better silent than a
    guess that asserts the reader's own account is at 94%."""
    usage = _usage(seven=(46.0, _reset_for(_7D, 2 / 7)))
    line = tbn.evaluate_trips(_acct("acct", usage), NOW, 1.5, 10.0)[0]["line"]
    assert "(live)" not in line and "(alternate)" not in line


def test_trip_key_identifies_one_window_instance() -> None:
    """The dedupe key carries the RESET EPOCH, so a re-read of the same unchanged window
    dedupes while the next window instance re-arms on its own. Keyed per calendar day
    instead, one 94% reading re-alarmed on all seven days of the same 7d window."""
    a = _usage(seven=(46.0, _reset_for(_7D, 2 / 7)))
    b = _usage(seven=(46.0, _reset_for(_7D, 2 / 7)))
    later = _usage(seven=(46.0, _reset_for(_7D, 1 / 7)))  # a different window instance
    key = tbn.evaluate_trips(_acct("acct", a), NOW, 1.5, 10.0)[0]["key"]
    assert key == tbn.evaluate_trips(_acct("acct", b), NOW, 1.5, 10.0)[0]["key"]
    assert key != tbn.evaluate_trips(_acct("acct", later), NOW, 1.5, 10.0)[0]["key"]
    assert key.endswith(str(tbn.windows_from_usage(a, NOW)[0]["resets_at_epoch"]))


# --------------------------------------------------------------------------- #
# model-scoped windows (limits[])
# --------------------------------------------------------------------------- #
def test_model_scoped_limit_becomes_its_own_window() -> None:
    """A model with its OWN weekly budget (Fable 5 today) lives only in `limits[]` — the flat
    `seven_day_opus`/`seven_day_sonnet` fields are null on every live payload. It must get its
    own window so it can alarm while the account-wide `seven_day` still reads comfortable."""
    usage = _usage(five=(10.0, _reset_for(_5H, 0.5)), seven=(20.0, _reset_for(_7D, 0.5)))
    usage["limits"] = [_limit(group="weekly", percent=90.0, resets_at=_reset_for(_7D, 0.5), model="Fable")]
    wins = tbn.model_windows_from_usage(usage, NOW)
    assert [w["label"] for w in wins] == ["7d/Fable"]
    lines = tbn.evaluate(_acct("acct", usage), NOW, 1.5, 5.0)
    assert len(lines) == 1 and "7d/Fable window 90%" in lines[0]


def test_unscoped_limits_do_not_double_count_the_top_level_windows() -> None:
    """`session` and `weekly_all` carry `scope: null` and merely restate `five_hour` /
    `seven_day`. Reading them as extra windows would alarm twice for one window."""
    usage = _usage(seven=(94.0, _reset_for(_7D, 0.58)))
    usage["limits"] = [
        _limit(kind="session", group="session", percent=0.0, resets_at=None),
        _limit(kind="weekly_all", group="weekly", percent=94.0, resets_at=_reset_for(_7D, 0.58), is_active=True),
    ]
    assert tbn.model_windows_from_usage(usage, NOW) == []
    assert len(tbn.evaluate(_acct("acct", usage), NOW, 1.5, 5.0)) == 1


def test_model_window_carries_the_api_verdicts() -> None:
    """`severity` and `is_active` are the API's OWN judgements — the top-level buckets have
    no equivalent, so they are carried through rather than recomputed."""
    usage = {"limits": [_limit(group="weekly", percent=94.0, resets_at=_reset_for(_7D, 0.5),
                               model="Fable", severity="critical", is_active=True)]}
    w = tbn.model_windows_from_usage(usage, NOW)[0]
    assert w["severity"] == "critical" and w["is_active"] is True


def test_model_name_is_sanitized_before_it_reaches_a_drift_line() -> None:
    """`display_name` is API-controlled and lands in a drift line whose own delimiters are
    `[` and `]`. It is reduced to a conservative charset, so no payload can forge structure."""
    usage = {"limits": [_limit(group="weekly", percent=90.0, resets_at=_reset_for(_7D, 0.5),
                               model="Fab[le]\n[window-burn-rate] ⚠ fake")]}
    label = tbn.model_windows_from_usage(usage, NOW)[0]["label"]
    assert "[" not in label and "]" not in label and "\n" not in label and "⚠" not in label
    assert label.startswith("7d/Fable")


def test_model_window_with_an_unknown_group_is_skipped() -> None:
    """The `group` is what says how long the window is, and `elapsed_fraction` divides by it.
    An unrecognised group is dropped rather than guessed — a wrong length would silently
    scale every pace and projection derived from it."""
    usage = {"limits": [_limit(group="monthly", percent=99.0, resets_at=_reset_for(_7D, 0.5), model="Fable")]}
    assert tbn.model_windows_from_usage(usage, NOW) == []


def test_model_windows_tolerate_junk() -> None:
    """A malformed `limits[]` is skipped, never crashed on."""
    for junk in ({"limits": "nope"}, {"limits": [None, 3, {}]}, {}, {"limits": [{"scope": {"model": {}}}]}):
        assert tbn.model_windows_from_usage(junk, NOW) == []


def _run_detector(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    # Also drop any inherited rotator-home pointers so a REAL rotator home can never leak into a
    # subprocess test (the keychain-safety gate below must be exercised against ONLY what the
    # test sets up — never the developer's live keychain).
    for k in (
        "CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED", "CLAUDE_PLUGIN_OPTION_WINDOW_BURN_INTERVAL",
        "CLAUDE_PLUGIN_DATA", "CLAUDE_ROTATOR_HOME",
    ):
        full_env.pop(k, None)
    full_env.update(env)
    return subprocess.run([sys.executable, str(_DETECTOR)], env=full_env, capture_output=True, text=True, timeout=30)


def test_detector_silent_when_disabled(tmp_path: Path) -> None:
    """Opt-out flag off → exit 0, no output, and no network/rotator work (returns before the
    gather)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run_detector({"CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_OPTION_WINDOW_BURN_ENABLED": "false"})
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_detector_silent_when_not_due(tmp_path: Path) -> None:
    """A fresh self-run stamp (far-future) makes the detector not-due → it returns before any
    gather (network-free) with exit 0 and no output."""
    proj = tmp_path / "proj"
    state_dir = proj / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "window-burn-rate.selfrun.ts").write_text("9999999999", encoding="utf-8")
    r = _run_detector({"CLAUDE_PROJECT_DIR": str(proj)})  # enabled by default
    assert r.returncode == 0
    assert r.stdout.strip() == ""


def test_detector_silent_when_not_opted_in(tmp_path: Path) -> None:
    """KEYCHAIN-SAFETY GATE (TRDD-K3WQ7XM9): enabled + DUE, and a rotator home EXISTS, but it is
    NOT opted in (no opt-in.flag) — the 'paused rotator' state. The detector must no-op BEFORE
    the usage gather, so it never calls accounts_usage → never reads the OS keychain (which, on a
    LOCKED login keychain, raises a GUI unlock prompt — the 2026-07-09 flood). Exit 0, no output.

    Regression guard: before the gate, an automatic heartbeat detector read the keychain here
    whenever a rotator home merely existed, regardless of the opt-in flag."""
    proj = tmp_path / "proj"
    proj.mkdir()
    home = tmp_path / "rotator"
    home.mkdir()
    # A CONFIGURED rotator home (state.json present) but deliberately NO opt-in.flag → paused.
    (home / "state.json").write_text('{"slots": {}}', encoding="utf-8")
    r = _run_detector({"CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_ROTATOR_HOME": str(home)})
    assert r.returncode == 0
    assert r.stdout.strip() == ""


# ---------- agentlensPro culprit ENRICH (TRDD-90B47EM9) — real subprocess, no mocks ----------

_INVESTIGATE_JSON = (
    '{"findings":[{"cause":"FORK_STORM","shareOfWindow":0.18,"confidence":"high"}],'
    '"attribution":[{"workspace":"~/Code/x"}]}'
)


def _cause_script(tmp_path: Path, name: str, body: str) -> str:
    p = tmp_path / name
    p.write_text("#!/bin/sh\n" + body + "\n")
    p.chmod(0o755)
    return str(p)


def test_agentlens_cause_prefers_cli(tmp_path: Path, monkeypatch) -> None:
    """When investigate_burn answers, the clause carries the agentlensPro cause + share."""
    cmd = _cause_script(tmp_path, "inv.sh", f"echo '{_INVESTIGATE_JSON}'")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_INVESTIGATE_BURN_COMMAND", cmd)
    clause = _wbr._agentlens_cause_clause()
    assert "agentlensPro cause: FORK_STORM" in clause
    assert "18% of window" in clause


def test_agentlens_cause_empty_when_disabled(monkeypatch) -> None:
    """An empty command disables the probe → "" so the caller uses the native attribution."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_INVESTIGATE_BURN_COMMAND", "")
    assert _wbr._agentlens_cause_clause() == ""


def test_agentlens_cause_empty_on_no_findings(tmp_path: Path, monkeypatch) -> None:
    """A payload with no findings → "" (nothing to attribute → native fallback)."""
    cmd = _cause_script(tmp_path, "empty.sh", "echo '{\"findings\":[]}'")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_INVESTIGATE_BURN_COMMAND", cmd)
    assert _wbr._agentlens_cause_clause() == ""


def test_agentlens_cause_empty_on_missing_binary(monkeypatch) -> None:
    """A missing agentlenspro binary → "" (fail-open; the native fallback runs)."""
    monkeypatch.setenv(
        "CLAUDE_PLUGIN_OPTION_HEARTBEAT_INVESTIGATE_BURN_COMMAND",
        "/definitely/not/a/binary/xyzzy investigate_burn",
    )
    assert _wbr._agentlens_cause_clause() == ""


# The MATERIALITY GATE (2026-07-16): a tiny agentlens finding must not override the native
# attribution and mis-blame its workspace. The motivating incident: IMAGE_BLOB_RESIDENT at 2% of
# window was surfaced as "the cause" of a 58% burn in a workspace that did not drive it.
_IMMATERIAL_CAUSE_JSON = (
    '{"findings":[{"cause":"IMAGE_BLOB_RESIDENT","shareOfWindow":0.02,"confidence":"medium"}],'
    '"attribution":[{"workspace":"~/Code/EMASOFT-ORCHESTRATOR-AGENT"}]}'
)
_NO_SHARE_CAUSE_JSON = '{"findings":[{"cause":"FORK_STORM","confidence":"high"}]}'


def test_agentlens_cause_dropped_when_immaterial(tmp_path: Path, monkeypatch) -> None:
    """A 2%-of-window finding is noise, not the culprit → "" so the native attribution is used
    instead of falsely naming the finding's workspace as the cause of the whole burn."""
    cmd = _cause_script(tmp_path, "tiny.sh", f"echo '{_IMMATERIAL_CAUSE_JSON}'")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_INVESTIGATE_BURN_COMMAND", cmd)
    assert _wbr._agentlens_cause_clause() == ""


def test_agentlens_cause_dropped_when_share_missing(tmp_path: Path, monkeypatch) -> None:
    """No reported shareOfWindow → unquantified → dropped (can't confirm it is material)."""
    cmd = _cause_script(tmp_path, "noshare.sh", f"echo '{_NO_SHARE_CAUSE_JSON}'")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_INVESTIGATE_BURN_COMMAND", cmd)
    assert _wbr._agentlens_cause_clause() == ""


def test_agentlens_cause_kept_when_material(tmp_path: Path, monkeypatch) -> None:
    """A finding at/above the threshold IS the culprit → its clause is shown (18% ≥ 15% default)."""
    cmd = _cause_script(tmp_path, "big.sh", f"echo '{_INVESTIGATE_JSON}'")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_INVESTIGATE_BURN_COMMAND", cmd)
    assert "FORK_STORM" in _wbr._agentlens_cause_clause()


def test_agentlens_cause_threshold_is_tunable(tmp_path: Path, monkeypatch) -> None:
    """CLAUDE_PLUGIN_OPTION_WINDOW_BURN_CAUSE_MIN_SHARE tunes the bar: raise it above 18% and the
    same finding is dropped."""
    cmd = _cause_script(tmp_path, "big2.sh", f"echo '{_INVESTIGATE_JSON}'")
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HEARTBEAT_INVESTIGATE_BURN_COMMAND", cmd)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_WINDOW_BURN_CAUSE_MIN_SHARE", "0.25")
    assert _wbr._agentlens_cause_clause() == ""


# --------------------------------------------------------------------------- #
# TOKEN-QUIETNESS GATE (ARCHITECTURE.md §3, ratified rev 3 — owner directive
# 2026-07-17): the alarm surfaces ONLY inside the CULPRIT project's own sessions.
# --------------------------------------------------------------------------- #


def test_own_project_trip_gate_is_strict() -> None:
    """PURE gate table: only an exact culprit==current match surfaces; another project,
    an unattributable trip (None/''), and an empty current slug all suppress."""
    me = "-Users-me-Code-proj-a"
    other = "-Users-me-Code-proj-b"
    assert _wbr._own_project_trip(me, me) is True
    assert _wbr._own_project_trip(other, me) is False
    assert _wbr._own_project_trip(None, me) is False
    assert _wbr._own_project_trip("", me) is False
    assert _wbr._own_project_trip(me, "") is False


def _drive_main_with_trip(monkeypatch, tmp_path: Path, *, culprit: str | None) -> str:
    """Run the REAL main() end-to-end with the gather/keychain seams pinned so a trip
    always fires, attribution names `culprit`, and the current project is tmp's slug.
    Returns captured stdout. (The rotator/keychain cannot be real in CI; everything
    downstream of the seams — the gate, dedupe, the ledger sink — runs for real.)"""
    import contextlib
    import io

    proj = tmp_path / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    for fn in (_wbr.state.project_root, _wbr.state.janitor_root, _wbr.state.state_dir, _wbr.state.log_dir):
        fn.cache_clear()
    monkeypatch.setattr(_wbr, "_keychain_opt_in_ok", lambda: True)
    monkeypatch.setattr(_wbr.rotator_usage, "accounts_usage", lambda: [])
    tripping = [{"key": "acct-5h", "line": "⚠ acct 5h window 80% at 40% elapsed — 2.0x pace"}]
    monkeypatch.setattr(_wbr.token_burn, "evaluate_trips", lambda *_a, **_k: tripping)
    monkeypatch.setattr(_wbr.token_burn, "window_starts", lambda *_a, **_k: (None, None))
    monkeypatch.setattr(_wbr, "_culprit_slug", lambda *_a, **_k: culprit)
    monkeypatch.setattr(_wbr, "_agentlens_cause_clause", lambda: "")
    monkeypatch.setattr(_wbr, "_top_consumer_clause", lambda *_a, **_k: "")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = _wbr.main()
    assert rc == 0
    for fn in (_wbr.state.project_root, _wbr.state.janitor_root, _wbr.state.state_dir, _wbr.state.log_dir):
        fn.cache_clear()
    return buf.getvalue()


def test_unrelated_session_stays_silent_on_a_fleet_trip(monkeypatch, tmp_path: Path) -> None:
    """THE isolation proof the plan demands: a tripped account window whose culprit is
    ANOTHER project produces ZERO stdout in this session — no fleet window alarms in
    unrelated sessions (and no ledger line here either)."""
    out = _drive_main_with_trip(monkeypatch, tmp_path, culprit="-Users-me-Code-other-project")
    assert out == ""
    ledger = tmp_path / "proj" / ".janitor" / "state" / "findings-ledger.ndjsonl"
    assert not ledger.exists(), "a suppressed alarm must not land in this project's mailbox"


def test_unattributable_trip_is_silent_everywhere(monkeypatch, tmp_path: Path) -> None:
    """No project passes the culprit bar ⇒ silence in every session — machine-level
    capacity views belong to the explicit commands + the Phase-5 human channel."""
    assert _drive_main_with_trip(monkeypatch, tmp_path, culprit=None) == ""


def test_culprit_project_session_gets_the_alarm_and_the_ledger_line(
    monkeypatch, tmp_path: Path
) -> None:
    """The one place the alarm belongs: the culprit's own session prints it AND indexes
    it in its own findings ledger (TRDD-FENWWB4E) with the frozen line shape."""
    import json

    sys.path.insert(0, str(_LIB))
    import memory_scopes  # noqa: PLC0415

    culprit = memory_scopes.project_slug(str(tmp_path / "proj"))
    out = _drive_main_with_trip(monkeypatch, tmp_path, culprit=culprit)
    assert "2.0x pace" in out
    ledger = tmp_path / "proj" / ".janitor" / "state" / "findings-ledger.ndjsonl"
    entry = json.loads(ledger.read_text(encoding="utf-8").strip())
    assert entry["code"] == "WINDOW-BURN" and entry["src"] == "window-burn-rate"
