"""Harness self-test probes (TRDD-B0SABNP8) — each REAL-artifact probe goes RED on a
CC-drift artifact and GREEN on a healthy one; the self-consistency guards go RED on a
janitor regression; and the whole surface is fail-open and NEVER touches real state.

CRITICAL ISOLATION (the `janitor-keepalive-test-isolation-fsevents` lesson): a past
janitor test polluted the REAL ~/.claude / plugin DATA dir and cascaded into an OS crash.
Root cause: a frozen `Path.home()` module constant vs a test that only set HOME in env
AFTER import — the two never met. Here every probe path is INJECTED (fixtures under
tmp_path), the module resolves defaults at CALL time from a sandboxed HOME/env, and an
autouse tripwire snapshots the real ~/.claude and asserts it is byte-for-byte unchanged
after every test.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
# scripts/lib so harness_selftest's own `import state` resolves; scripts too, for parity
# with the janitor test convention.
sys.path.insert(0, str(_REPO / "scripts" / "lib"))
sys.path.insert(0, str(_REPO / "scripts"))

import harness_selftest as hs  # noqa: E402
import state  # noqa: E402

# Captured ONCE at import, while HOME is still the REAL home — before any monkeypatch. The
# tripwire compares against this so a test that resolves a real default path and writes is
# caught. (The module is read-only by construction; this proves it stays that way.)
_REAL_CLAUDE = Path(os.environ.get("HOME", os.path.expanduser("~"))) / ".claude"


def _sentinel_snapshot(base: Path) -> dict[str, tuple[int, int]]:
    """A cheap, bounded (mtime_ns, size) map of the real ~/.claude files this module could
    touch by default — settings.json + rules/*.md. NOT a full recursive walk (the plugins
    cache is huge); these are the surfaces a default-path read/write would hit."""
    snap: dict[str, tuple[int, int]] = {}
    for p in [base / "settings.json", *sorted((base / "rules").glob("*.md"))]:
        try:
            st = p.stat()
            snap[str(p)] = (st.st_mtime_ns, st.st_size)
        except OSError:
            continue
    return snap


@pytest.fixture(autouse=True)
def _sandbox(monkeypatch, tmp_path):
    """Point HOME + every janitor state env at tmp, so a default-path resolution can NEVER
    reach real ~/.claude, and trip if real state is nonetheless modified."""
    fake_home = tmp_path / "home"
    (fake_home / ".claude").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "project"))
    monkeypatch.setenv("CLAUDE_PLUGIN_DATA", str(tmp_path / "data"))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "gstate"))
    monkeypatch.setenv("JANITOR_CONTROL_DIR", str(tmp_path / "control"))
    monkeypatch.delenv("CLAUDE_PLUGIN_ROOT", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_HARNESS_SELFTEST_ENABLED", raising=False)
    before = _sentinel_snapshot(_REAL_CLAUDE)
    yield
    assert _sentinel_snapshot(_REAL_CLAUDE) == before, (
        "a harness_selftest unit test modified real ~/.claude — isolation defect"
    )


def _write(path: Path, obj) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj) if not isinstance(obj, str) else obj, encoding="utf-8")
    return path


# ------------------------------------------------------------------ probe 1: option delivery
_JID = "ai-maestro-janitor@ai-maestro-plugins"


def test_option_delivery_green_when_declared_knob_is_delivered(tmp_path):
    """A declared janitor knob whose CLAUDE_PLUGIN_OPTION_* is present → green."""
    sp = _write(tmp_path / "settings.json", {"pluginConfigs": {_JID: {"github_repo": "o/r"}}})
    env = {"CLAUDE_PLUGIN_OPTION_GITHUB_REPO": "o/r"}
    assert hs.probe_option_delivery([sp], env, known_keys={"github_repo"}) is None


def test_option_delivery_red_on_2207_delivery_drop(tmp_path):
    """A declared janitor knob whose env var is ABSENT → FAIL (the 2.1.207 signature)."""
    sp = _write(tmp_path / "settings.json", {"pluginConfigs": {_JID: {"github_repo": "o/r"}}})
    res = hs.probe_option_delivery([sp], {}, known_keys={"github_repo"})
    assert res is not None
    sev, msg = res
    assert sev == "HIGH"
    assert "github_repo" in msg and "2.1.207" in msg


def test_option_delivery_inapplicable_when_nothing_declared(tmp_path):
    """No pluginConfigs → inapplicable → green (a fresh/default machine never false-fails)."""
    sp = _write(tmp_path / "settings.json", {"enabledPlugins": {_JID: True}})
    assert hs.probe_option_delivery([sp], {}, known_keys={"github_repo"}) is None


def test_option_delivery_ignores_non_janitor_plugin_block(tmp_path):
    """A DIFFERENT plugin's declared-but-undelivered knob is not the janitor's problem —
    CC delivers each plugin's options only to that plugin, so we scope by plugin id."""
    sp = _write(tmp_path / "settings.json", {"pluginConfigs": {"some-other-plugin": {"github_repo": "x"}}})
    assert hs.probe_option_delivery([sp], {}, known_keys={"github_repo"}) is None


def test_option_delivery_ignores_unknown_key_in_janitor_block(tmp_path):
    """A key that is NOT a real janitor userConfig option is ignored (a typo or a knob CC
    never delivers can't false-fail) — RESIDUAL-2 robustness."""
    sp = _write(tmp_path / "settings.json", {"pluginConfigs": {_JID: {"not_a_real_knob": "x"}}})
    assert hs.probe_option_delivery([sp], {}, known_keys={"github_repo", "trdd_path"}) is None


def test_option_delivery_ignores_unreadable_settings(tmp_path):
    """An absent / non-JSON settings file → nothing to check → green (fail-open)."""
    assert hs.probe_option_delivery([tmp_path / "nope.json"], {}, known_keys={"github_repo"}) is None
    garbage = _write(tmp_path / "settings.json", "{ not json")
    assert hs.probe_option_delivery([garbage], {}, known_keys={"github_repo"}) is None


# ------------------------------------------------------------ probe 2: context snapshot schema
def test_snapshot_green_on_healthy_schema(tmp_path):
    """A well-formed snapshot (pct/tokens/window/ts ints, tokens <= window) → green."""
    p = _write(tmp_path / "snap.json", {"pct": 42, "tokens": 84_000, "window": 200_000, "ts": 100})
    assert hs.probe_context_snapshot_schema(p) is None


def test_snapshot_green_minimal_pct_only(tmp_path):
    """A minimal healthy snapshot carrying only pct → green (tokens/window optional)."""
    p = _write(tmp_path / "snap.json", {"pct": 10})
    assert hs.probe_context_snapshot_schema(p) is None


def test_snapshot_red_missing_pct(tmp_path):
    """A present snapshot with no `pct` → schema drift → FAIL."""
    p = _write(tmp_path / "snap.json", {"tokens": 1, "window": 2})
    res = hs.probe_context_snapshot_schema(p)
    assert res is not None and res[0] == "HIGH" and "pct" in res[1]


def test_snapshot_red_tokens_exceed_window(tmp_path):
    """The 2.1.208 window-reset signature (tokens > window) → FAIL — the destructive case."""
    p = _write(tmp_path / "snap.json", {"pct": 100, "tokens": 300_000, "window": 200_000})
    res = hs.probe_context_snapshot_schema(p)
    assert res is not None and "2.1.208" in res[1]


def test_snapshot_red_absurd_window(tmp_path):
    """A present-but-invalid window (zero) → FAIL."""
    p = _write(tmp_path / "snap.json", {"pct": 5, "tokens": 10, "window": 0})
    res = hs.probe_context_snapshot_schema(p)
    assert res is not None and "window" in res[1]


def test_snapshot_red_non_int_pct(tmp_path):
    """pct present as a float/string → non-int → FAIL (bool is excluded too)."""
    p = _write(tmp_path / "snap.json", {"pct": "42"})
    assert hs.probe_context_snapshot_schema(p) is not None
    pb = _write(tmp_path / "snap2.json", {"pct": True})
    assert hs.probe_context_snapshot_schema(pb) is not None


def test_snapshot_inapplicable_absent_or_torn(tmp_path):
    """Absent file OR a torn/unparseable write → inapplicable → green (resolve_context
    degrades safely in both, so neither is the destructive bug)."""
    assert hs.probe_context_snapshot_schema(tmp_path / "missing.json") is None
    assert hs.probe_context_snapshot_schema(None) is None
    torn = _write(tmp_path / "torn.json", '{"pct": 4')
    assert hs.probe_context_snapshot_schema(torn) is None


# ------------------------------------------------------------------- probe 3: int spellings
def test_int_spellings_green_on_real_parser():
    """The shipped parse_nonneg_int accepts every CC-2.1.211 spelling → green."""
    assert hs.probe_int_spellings() is None


def test_int_spellings_red_on_regressed_parser(monkeypatch):
    """A parser that stops accepting `64_000`/`1e6` (the janitor regression) → FAIL."""
    real = state.parse_nonneg_int

    def broken(s: str):
        if "_" in s or "e" in s.lower():
            return None
        return real(s)

    monkeypatch.setattr(state, "parse_nonneg_int", broken)
    res = hs.probe_int_spellings()
    assert res is not None and res[0] == "MEDIUM" and "64_000" in res[1]


# ------------------------------------------------------------------- probe 4: marker path
def _detector_fixtures(tmp_path: Path) -> tuple[Path, Path]:
    """Copies of the two real detector sources — the healthy baseline the tests mutate."""
    det = _REPO / "scripts" / "detectors"
    mm = tmp_path / "memory-maintenance.py"
    td = tmp_path / "ticket-dispatch.py"
    mm.write_text((det / "memory-maintenance.py").read_text(encoding="utf-8"), encoding="utf-8")
    td.write_text((det / "ticket-dispatch.py").read_text(encoding="utf-8"), encoding="utf-8")
    return mm, td


def test_marker_green_on_real_sources(tmp_path):
    """The real detector sources carry all six memory markers + [janitor-ticket], and the
    real sanitize defangs → green."""
    mm, td = _detector_fixtures(tmp_path)
    assert hs.probe_marker_path(memory_maintenance_path=mm, ticket_dispatch_path=td) is None


def test_marker_red_on_missing_memory_marker(tmp_path):
    """A memory marker renamed away in memory-maintenance.py → FAIL (vocabulary drift)."""
    mm, td = _detector_fixtures(tmp_path)
    mm.write_text(mm.read_text().replace("[janitor-memory-split]", "[janitor-memory-RENAMED]"), encoding="utf-8")
    res = hs.probe_marker_path(memory_maintenance_path=mm, ticket_dispatch_path=td)
    assert res is not None and "memory-maintenance" in res[1]


def test_marker_red_on_missing_ticket_marker(tmp_path):
    """[janitor-ticket] gone from ticket-dispatch.py → FAIL (the second SSOT)."""
    mm, td = _detector_fixtures(tmp_path)
    td.write_text(td.read_text().replace("[janitor-ticket]", "[janitor-GONE]"), encoding="utf-8")
    res = hs.probe_marker_path(memory_maintenance_path=mm, ticket_dispatch_path=td)
    assert res is not None and "ticket-dispatch" in res[1]


def test_marker_red_when_sanitize_stops_defanging(tmp_path, monkeypatch):
    """sanitize_for_drift_line that no longer maps [→⟦ → FAIL (anti-mimicry broke)."""
    mm, td = _detector_fixtures(tmp_path)
    monkeypatch.setattr(state, "sanitize_for_drift_line", lambda s: s)
    res = hs.probe_marker_path(memory_maintenance_path=mm, ticket_dispatch_path=td)
    assert res is not None and "sanitize" in res[1]


def test_marker_inapplicable_when_source_unreadable(tmp_path):
    """An unreadable source is inapplicable for its half (fail-open, not a false alarm);
    with both unreadable only the sanitize check runs → green on the real sanitize."""
    assert hs.probe_marker_path(
        memory_maintenance_path=tmp_path / "gone1.py",
        ticket_dispatch_path=tmp_path / "gone2.py",
    ) is None


# --------------------------------------------------------------------------- run_selftest
def test_run_selftest_all_green(tmp_path, monkeypatch):
    """Healthy machine: nothing declared, no snapshot, real parser + markers → []."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_REPO))
    sp = _write(tmp_path / "settings.json", {"enabledPlugins": {_JID: True}})
    assert hs.run_selftest(settings_paths=[sp], snapshot_path=None) == []


def test_run_selftest_collects_each_break(tmp_path, monkeypatch):
    """Two simulated breaks (option delivery + bad snapshot) → both surface as
    (HARNESS-DRIFT, sev, msg) tuples."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_REPO))
    sp = _write(tmp_path / "settings.json", {"pluginConfigs": {_JID: {"github_repo": "x"}}})
    snap = _write(tmp_path / "snap.json", {"pct": 100, "tokens": 9, "window": 1})
    failures = hs.run_selftest(settings_paths=[sp], snapshot_path=snap, env={"CLAUDE_PLUGIN_ROOT": str(_REPO)})
    codes = {c for c, _s, _m in failures}
    assert codes == {"HARNESS-DRIFT"}
    joined = " ".join(m for _c, _s, m in failures)
    assert "delivery broke" in joined and "2.1.208" in joined


def test_run_selftest_default_reads_user_settings_only(tmp_path, monkeypatch):
    """RESIDUAL-1: the DEFAULT settings path is the USER ~/.claude/settings.json ONLY. A
    project .claude/settings.json declaring an undelivered knob is NOT read (post-2.1.207
    project pluginConfigs is intentionally undelivered, so reading it would false-fail)."""
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_REPO))
    home = Path(os.environ["HOME"])
    project = Path(os.environ["CLAUDE_PROJECT_DIR"])
    _write(home / ".claude" / "settings.json", {"pluginConfigs": {_JID: {"github_repo": "x"}}})
    _write(project / ".claude" / "settings.json", {"pluginConfigs": {_JID: {"heartbeat_cron": "*/5 * * * *"}}})
    failures = hs.run_selftest(snapshot_path=None)  # default settings_paths → user only
    joined = " ".join(m for _c, _s, m in failures)
    assert "github_repo" in joined, "user-scope declared knob must be checked"
    assert "heartbeat_cron" not in joined, "project settings.json must NOT be read (RESIDUAL-1)"


def test_run_selftest_opt_out(monkeypatch):
    """The master opt-out short-circuits to []."""
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_HARNESS_SELFTEST_ENABLED", "false")
    assert hs.run_selftest() == []


def test_run_selftest_never_raises_when_a_probe_throws(monkeypatch):
    """A probe that itself throws is swallowed (fail-open) — the self-test can never break
    the SessionStart survival path placed after it."""
    def boom(*a, **k):
        raise RuntimeError("probe fault")

    monkeypatch.setattr(hs, "probe_int_spellings", boom)
    # Should not raise; the surviving probes still run and (on a clean env) return [].
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_REPO))
    assert hs.run_selftest(settings_paths=[], snapshot_path=None) == []


# --------------------------------------------------------------- digest + drift-line surface
def test_failure_digest_stable_and_order_independent():
    a = [("HARNESS-DRIFT", "HIGH", "one"), ("HARNESS-DRIFT", "MEDIUM", "two")]
    b = [("HARNESS-DRIFT", "MEDIUM", "two"), ("HARNESS-DRIFT", "HIGH", "one")]
    assert hs.failure_digest(a) == hs.failure_digest(b)
    assert hs.failure_digest([]) == ""
    assert hs.failure_digest([("HARNESS-DRIFT", "HIGH", "one")]) != hs.failure_digest(a)


def test_format_drift_line():
    assert hs.format_drift_line([]) == ""
    line = hs.format_drift_line([("HARNESS-DRIFT", "HIGH", "boom"), ("HARNESS-DRIFT", "MEDIUM", "bang")])
    assert "[ai-maestro-janitor]" in line and "2 Claude Code" in line
    assert "boom" in line and "bang" in line


def test_no_expensive_io_paths_are_pure(tmp_path, monkeypatch):
    """The probes spawn NO subprocess and open NO socket — assert by making both fatal for
    the duration of a run_selftest over injected fixtures (the reconciled 'no expensive
    I/O' proof)."""
    import socket
    import subprocess

    def no_subprocess(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("run_selftest spawned a subprocess")

    def no_socket(*a, **k):  # noqa: ANN002, ANN003
        raise AssertionError("run_selftest opened a socket")

    monkeypatch.setattr(subprocess, "Popen", no_subprocess)
    monkeypatch.setattr(subprocess, "run", no_subprocess)
    monkeypatch.setattr(socket, "socket", no_socket)
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(_REPO))
    sp = _write(tmp_path / "settings.json", {"pluginConfigs": {_JID: {"github_repo": "x"}}})
    snap = _write(tmp_path / "snap.json", {"pct": 100, "tokens": 9, "window": 1})
    # Runs all four probes (two of them RED) without touching subprocess/socket.
    assert hs.run_selftest(settings_paths=[sp], snapshot_path=snap, env={"CLAUDE_PLUGIN_ROOT": str(_REPO)})
