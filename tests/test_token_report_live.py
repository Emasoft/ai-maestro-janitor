"""Tests for token_meter.read_context_snapshot/resolve_context (moved out of the
pre-tool-context-usage hook, TRDD-TKNSTP82 A4) and for `/janitor-token-report --live`.

Real I/O, no mocks: unit tests write fixture snapshot/transcript files to tmp_path and
call the pure token_meter functions directly; --live tests run the real script via
subprocess with HOME/CLAUDE_PROJECT_DIR pointed at isolated tmp directories.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "token_report.py"
_LIB = _PROJECT_ROOT / "scripts" / "lib"

sys.path.insert(0, str(_LIB))
import memory_scopes  # noqa: E402
import token_meter  # noqa: E402

assert _SCRIPT.is_file(), f"script not found at {_SCRIPT}"


def _write_transcript(path: Path, entries: list[dict]) -> str:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return str(path)


def _assistant_usage(inp: int = 0, out: int = 0, cache_read: int = 0, cache_creation: int = 0) -> dict:
    return {
        "type": "assistant",
        "message": {
            "role": "assistant",
            "content": [{"type": "text", "text": "x"}],
            "usage": {
                "input_tokens": inp,
                "output_tokens": out,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
            },
        },
    }


def _user(text: str) -> dict:
    return {"type": "user", "message": {"role": "user", "content": text}}


# ---------- token_meter.read_context_snapshot -------------------------------


def test_read_context_snapshot_missing_project_or_session_returns_none(tmp_path: Path) -> None:
    assert token_meter.read_context_snapshot("", "sid") is None
    assert token_meter.read_context_snapshot(str(tmp_path), "") is None


def test_read_context_snapshot_reads_dict(tmp_path: Path) -> None:
    sid = "sess-1"
    snapdir = tmp_path / ".claude" / "janitor"
    snapdir.mkdir(parents=True)
    (snapdir / f"context-usage.{sid}.json").write_text(json.dumps({"pct": 42}), encoding="utf-8")
    assert token_meter.read_context_snapshot(str(tmp_path), sid) == {"pct": 42}


def test_read_context_snapshot_absent_file_returns_none(tmp_path: Path) -> None:
    assert token_meter.read_context_snapshot(str(tmp_path), "nope") is None


def test_read_context_snapshot_non_dict_returns_none(tmp_path: Path) -> None:
    sid = "sess-2"
    snapdir = tmp_path / ".claude" / "janitor"
    snapdir.mkdir(parents=True)
    (snapdir / f"context-usage.{sid}.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
    assert token_meter.read_context_snapshot(str(tmp_path), sid) is None


# ---------- token_meter.resolve_context --------------------------------------


def test_resolve_context_prefers_snapshot_over_transcript(tmp_path: Path) -> None:
    sid = "s1"
    snapdir = tmp_path / ".claude" / "janitor"
    snapdir.mkdir(parents=True)
    (snapdir / f"context-usage.{sid}.json").write_text(json.dumps({"pct": 73, "tokens": 730000, "window": 1000000, "ts": 100}), encoding="utf-8")
    pct, tokens, window, stale = token_meter.resolve_context(str(tmp_path), sid, "", 1_000_000, now=150)
    assert (pct, tokens, window, stale) == (73, 730000, 1000000, False)


def test_resolve_context_snapshot_stale_flagged(tmp_path: Path) -> None:
    sid = "s2"
    snapdir = tmp_path / ".claude" / "janitor"
    snapdir.mkdir(parents=True)
    (snapdir / f"context-usage.{sid}.json").write_text(json.dumps({"pct": 50, "ts": 0}), encoding="utf-8")
    pct, _, _, stale = token_meter.resolve_context(str(tmp_path), sid, "", 1_000_000, now=10_000)
    assert pct == 50 and stale is True


def test_resolve_context_transcript_fallback(tmp_path: Path) -> None:
    tp = _write_transcript(tmp_path / "t.jsonl", [_assistant_usage(inp=10000, cache_read=800000)])
    pct, tokens, window, stale = token_meter.resolve_context(str(tmp_path), "no-snap", tp, 1_000_000, now=0)
    assert (tokens, window, pct, stale) == (810000, 1_000_000, 81, False)


def test_resolve_context_none_when_no_source(tmp_path: Path) -> None:
    assert token_meter.resolve_context(str(tmp_path), "x", "", 1_000_000, now=0) == (None, None, None, False)


# ---------- /janitor-token-report --live (subprocess, isolated HOME) --------


_PREDICT_ENV_KEYS = ("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS")


def _run_report(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    # Hermetic: drop the auto-compact-prediction env vars the DEV may have set (the user runs
    # with CLAUDE_CODE_AUTO_COMPACT_WINDOW=700000) so a test only sees them when it sets them.
    for k in _PREDICT_ENV_KEYS:
        full_env.pop(k, None)
    full_env.update(env)
    return subprocess.run(
        [sys.executable, str(_SCRIPT), *args],
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_live_no_transcript_found(tmp_path: Path) -> None:
    """--live with no transcript anywhere under HOME/.claude/projects/<slug>/ -> a clear
    'no transcript found' message, exit 0 (never a crash)."""
    home = tmp_path / "home"
    home.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run_report({"HOME": str(home), "CLAUDE_PROJECT_DIR": str(proj)}, "--live")
    assert r.returncode == 0
    assert "no transcript found" in r.stdout.lower()


def test_live_prints_context_and_last_turn(tmp_path: Path) -> None:
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    proj.mkdir()
    slug = memory_scopes.project_slug(str(proj))
    projects_dir = home / ".claude" / "projects" / slug
    projects_dir.mkdir(parents=True)
    transcript = projects_dir / "sess-live-1.jsonl"
    transcript.write_text(
        "\n".join(
            json.dumps(e)
            for e in [
                _user("do work"),
                _assistant_usage(inp=100, out=500, cache_read=2000, cache_creation=300),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    r = _run_report({"HOME": str(home), "CLAUDE_PROJECT_DIR": str(proj)}, "--live")
    assert r.returncode == 0
    assert "Context window:" in r.stdout
    assert "output: 500" in r.stdout
    assert "cache_creation: 300" in r.stdout
    assert "cache_read: 2000" in r.stdout


def test_live_json_output(tmp_path: Path) -> None:
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    proj.mkdir()
    slug = memory_scopes.project_slug(str(proj))
    projects_dir = home / ".claude" / "projects" / slug
    projects_dir.mkdir(parents=True)
    transcript = projects_dir / "sess-live-2.jsonl"
    transcript.write_text(
        "\n".join(
            json.dumps(e)
            for e in [
                _user("do work"),
                _assistant_usage(inp=100, out=250, cache_read=1000, cache_creation=50),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    r = _run_report({"HOME": str(home), "CLAUDE_PROJECT_DIR": str(proj)}, "--live", "--json")
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["live"] is True
    assert data["session_id"] == "sess-live-2"
    assert data["last_turn"]["output"] == 250
    assert data["last_turn"]["cache_creation"] == 50
    assert data["last_turn"]["cache_read"] == 1000


def test_live_json_no_transcript(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    proj = tmp_path / "proj"
    proj.mkdir()
    r = _run_report({"HOME": str(home), "CLAUDE_PROJECT_DIR": str(proj)}, "--live", "--json")
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data == {"live": True, "session_id": None, "context": None, "last_turn": None, "note": "no transcript found under ~/.claude/projects/<slug>/ for this project"}


# ---------- token_meter.predict_auto_compact (TRDD-TKNSTP82 C) ---------------


def test_predict_auto_compact_env_unset_returns_none() -> None:
    assert token_meter.predict_auto_compact(500_000, env={}) is None


def test_predict_auto_compact_used_unknown_returns_none() -> None:
    assert token_meter.predict_auto_compact(None, env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "700000"}) is None


def test_predict_auto_compact_junk_window_returns_none() -> None:
    assert token_meter.predict_auto_compact(500_000, env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "notanint"}) is None


def test_predict_auto_compact_applies_34k_overhead() -> None:
    """The user's verified example: 700000 window − 34000 summary = 666000; at 559k used,
    ~107k remain."""
    p = token_meter.predict_auto_compact(559_000, env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "700000"})
    assert p is not None
    assert p.auto_window == 700_000
    assert p.overhead == 34_000
    assert p.effective_compact_point == 666_000
    assert p.tokens_until_compact == 107_000


def test_predict_auto_compact_overhead_override() -> None:
    p = token_meter.predict_auto_compact(
        600_000,
        env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "700000", "CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS": "10000"},
    )
    assert p is not None
    assert p.overhead == 10_000
    assert p.effective_compact_point == 690_000
    assert p.tokens_until_compact == 90_000


def test_predict_auto_compact_negative_once_past_the_point() -> None:
    p = token_meter.predict_auto_compact(680_000, env={"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "700000"})
    assert p is not None
    assert p.tokens_until_compact == -14_000  # past the 666000 point


# ---------- /janitor-token-report --live prediction surface (C2) -------------


def _seed_live(tmp_path: Path, sid: str, *, pct: int, tokens: int) -> tuple[Path, Path]:
    """Write a statusline snapshot (known occupancy) + a transcript stub so `--live`
    discovers the session and reads the snapshot. Returns (home, proj)."""
    home = tmp_path / "home"
    proj = tmp_path / "proj"
    proj.mkdir()
    slug = memory_scopes.project_slug(str(proj))
    projects_dir = home / ".claude" / "projects" / slug
    projects_dir.mkdir(parents=True)
    (projects_dir / f"{sid}.jsonl").write_text(json.dumps(_assistant_usage(inp=1, out=1)) + "\n", encoding="utf-8")
    snapdir = proj / ".claude" / "janitor"
    snapdir.mkdir(parents=True)
    (snapdir / f"context-usage.{sid}.json").write_text(json.dumps({"pct": pct, "tokens": tokens, "window": 1_000_000, "ts": 10_000_000_000}), encoding="utf-8")
    return home, proj


def test_live_text_shows_compact_prediction(tmp_path: Path) -> None:
    home, proj = _seed_live(tmp_path, "sess-pred-1", pct=64, tokens=640_000)  # until = 26000
    r = _run_report({"HOME": str(home), "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "700000"}, "--live")
    assert r.returncode == 0
    assert "Auto-compact point:" in r.stdout
    assert "until auto-compact" in r.stdout


def test_live_json_shows_compact_prediction(tmp_path: Path) -> None:
    home, proj = _seed_live(tmp_path, "sess-pred-2", pct=64, tokens=640_000)
    r = _run_report({"HOME": str(home), "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "700000"}, "--live", "--json")
    assert r.returncode == 0
    pred = json.loads(r.stdout)["compact_prediction"]
    assert pred["effective_compact_point"] == 666_000
    assert pred["tokens_until_compact"] == 26_000


def test_live_json_no_prediction_when_env_unset(tmp_path: Path) -> None:
    home, proj = _seed_live(tmp_path, "sess-pred-3", pct=64, tokens=640_000)
    # _run_report pops CLAUDE_CODE_AUTO_COMPACT_WINDOW; not re-set here → prediction is None.
    r = _run_report({"HOME": str(home), "CLAUDE_PROJECT_DIR": str(proj)}, "--live", "--json")
    assert r.returncode == 0
    assert json.loads(r.stdout)["compact_prediction"] is None


# ---------- pre-tool-context-usage.py PREPARE tier (C1) ----------------------

_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "pre-tool-context-usage.py"
assert _HOOK.is_file(), f"hook not found at {_HOOK}"

_HOOK_ENV_KEYS = (
    "CLAUDE_CODE_AUTO_COMPACT_WINDOW",
    "CLAUDE_PLUGIN_OPTION_COMPACT_SUMMARY_TOKENS",
    "CLAUDE_PLUGIN_OPTION_CONTEXT_PREPARE_TOKENS",
    "CLAUDE_PLUGIN_OPTION_CONTEXT_COMPACT_SUGGEST_PCT",
    "CLAUDE_PLUGIN_OPTION_CONTEXT_HARDSTOP_PCT",
    "CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED",
    "CLAUDE_PLUGIN_OPTION_CONTEXT_AUTOCOMPACT_ENABLED",
)


def _run_context_hook(env: dict[str, str], payload: dict) -> subprocess.CompletedProcess[str]:
    full_env = os.environ.copy()
    for k in _HOOK_ENV_KEYS:  # hermetic vs the dev's real context-watchdog tuning
        full_env.pop(k, None)
    full_env.update(env)
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=json.dumps(payload),
        env=full_env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _snapshot_only(proj: Path, sid: str, *, pct: int, tokens: int) -> None:
    snapdir = proj / ".claude" / "janitor"
    snapdir.mkdir(parents=True)
    (snapdir / f"context-usage.{sid}.json").write_text(json.dumps({"pct": pct, "tokens": tokens, "window": 1_000_000, "ts": 10_000_000_000}), encoding="utf-8")


def test_context_hook_prepare_fires_in_zone(tmp_path: Path) -> None:
    """Within CONTEXT_PREPARE_TOKENS of the predicted auto-compact point, the hook emits the
    PREPARE alert (TRDD-TKNSTP82 C1)."""
    proj = tmp_path / "proj"
    proj.mkdir()
    sid = "hook-1"
    _snapshot_only(proj, sid, pct=64, tokens=640_000)  # until = 666000 - 640000 = 26000 <= 30000
    r = _run_context_hook(
        {"CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "700000"},
        {"session_id": sid, "cwd": str(proj), "transcript_path": ""},
    )
    assert r.returncode == 0
    ctx = json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]
    assert "PREPARE for auto-compact" in ctx


# ---------- Deliverable 1: the weekly heartbeat-cost rollup (TRDD-ZCODD6YS) --------


def _seed_meter(proj: Path, records: list[dict]) -> None:
    sd = proj / ".janitor" / "state"
    sd.mkdir(parents=True, exist_ok=True)
    (sd / "token-meter.jsonl").write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")


def test_report_heartbeat_week_line_weighted_only(tmp_path: Path) -> None:
    """The historical report prints a heartbeat-ONLY weekly rollup computed from `beats`
    alone; with no price knob it shows weighted tokens only (no $), and a big interactive
    turn never inflates it."""
    import time as _time

    proj = tmp_path / "proj"
    proj.mkdir()
    now = int(_time.time())
    _seed_meter(
        proj,
        [
            {"ts": now, "heartbeat": True, "output": 1000},
            {"ts": now, "heartbeat": True, "output": 500},
            {"ts": now, "heartbeat": False, "output": 999_999},  # interactive turn — must NOT count
        ],
    )
    r = _run_report({"HOME": str(tmp_path / "home"), "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_OPTION_TOKEN_PRICE_PER_MTOK": ""})
    assert r.returncode == 0
    assert "janitor heartbeat:" in r.stdout
    assert "1.5k weighted tokens this week" in r.stdout, "beats only (1000+500), interactive 999999 excluded"
    assert "~$" not in r.stdout, "no dollar estimate without the price knob"


def test_report_heartbeat_week_line_with_price(tmp_path: Path) -> None:
    """With the price knob set the rollup shows a $ ESTIMATE, labeled WEIGHTED est."""
    import time as _time

    proj = tmp_path / "proj"
    proj.mkdir()
    now = int(_time.time())
    _seed_meter(
        proj,
        [
            {"ts": now, "heartbeat": True, "output": 1_000_000},
            {"ts": now, "heartbeat": True, "output": 1_000_000},
        ],
    )  # 2.0M weighted beats
    r = _run_report({"HOME": str(tmp_path / "home"), "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_OPTION_TOKEN_PRICE_PER_MTOK": "15"})
    assert r.returncode == 0
    assert "~$30.00 this week on quiet fires" in r.stdout  # 2.0M / 1e6 * 15
    assert "WEIGHTED est." in r.stdout, "the $ figure must be labeled an estimate"
    assert "2.0M weighted" in r.stdout


def test_report_heartbeat_week_json_fields(tmp_path: Path) -> None:
    """The JSON report carries heartbeat_7d_weighted (beats only) + heartbeat_7d_usd
    (None without the price knob)."""
    import time as _time

    proj = tmp_path / "proj"
    proj.mkdir()
    now = int(_time.time())
    _seed_meter(
        proj,
        [
            {"ts": now, "heartbeat": True, "output": 1000},
            {"ts": now, "heartbeat": False, "output": 500_000},  # excluded
        ],
    )
    r = _run_report({"HOME": str(tmp_path / "home"), "CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_PLUGIN_OPTION_TOKEN_PRICE_PER_MTOK": ""}, "--json")
    assert r.returncode == 0
    data = json.loads(r.stdout)
    assert data["heartbeat_7d_weighted"] == 1000, "beats only"
    assert data["heartbeat_7d_usd"] is None


def test_context_hook_prepare_silent_out_of_zone(tmp_path: Path) -> None:
    """Well before the auto-compact point (and below the % advisory band), no PREPARE alert."""
    proj = tmp_path / "proj"
    proj.mkdir()
    sid = "hook-2"
    _snapshot_only(proj, sid, pct=50, tokens=500_000)  # until = 166000 > 30000; pct 50 < suggest 60
    r = _run_context_hook(
        {"CLAUDE_PROJECT_DIR": str(proj), "CLAUDE_CODE_AUTO_COMPACT_WINDOW": "700000"},
        {"session_id": sid, "cwd": str(proj), "transcript_path": ""},
    )
    assert r.returncode == 0
    assert "PREPARE" not in r.stdout
