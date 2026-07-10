"""Tests for the context-size runaway guard (TRDD-SMZFJVZ3, TRDD-31095269).

Two units under test:
  * token_meter.latest_context_size — the LIVE context-window occupancy read from
    the transcript tail (input + cache_read + cache_creation of the newest assistant
    message). This is the cost-driving number: every turn re-reads ~this many tokens.
  * scripts/hooks/pre-tool-context-usage.py — the PreToolUse guard's pure decision
    functions + the in-process main() flow (gate / advisory / enforce / fail-open).

SAFETY: the enforcement tier shells out to compact_trigger.py, which would fire a
real ESC->/compact on the developer's OWN pane. EVERY test that reaches enforcement
monkeypatches `_run_compact_trigger`, so the real keystroke is NEVER sent. The
in-process main() tests patch sys.stdin/sys.stdout + `_run_compact_trigger` — no
subprocess, no uv, no pane touched. Real code, no mocked behaviour of the unit
itself.
"""

from __future__ import annotations

import importlib.util as _u
import io
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "pre-tool-context-usage.py"
_LIB = _PROJECT_ROOT / "scripts" / "lib"

if str(_LIB) not in sys.path:
    sys.path.insert(0, str(_LIB))
import token_meter  # noqa: E402


def _import_hook():
    # The hook filename has dashes, so it cannot be a normal import — load it by path.
    spec = _u.spec_from_file_location("pre_tool_context_usage_under_test", str(_HOOK))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)  # runs the module body; main() is NOT called (name != __main__)
    return mod


def _write_transcript(path: Path, entries: list[dict]) -> str:
    path.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return str(path)


def _assistant(inp: int = 0, cache_read: int = 0, cache_creation: int = 0, output: int = 0) -> dict:
    return {
        "type": "assistant",
        "message": {
            "usage": {
                "input_tokens": inp,
                "cache_read_input_tokens": cache_read,
                "cache_creation_input_tokens": cache_creation,
                "output_tokens": output,
            }
        },
    }


def _payload(session_id: str = "s", transcript: str = "", cwd: str = "") -> dict:
    return {"session_id": session_id, "transcript_path": transcript, "cwd": cwd}


# ---------- token_meter.latest_context_size --------------------------------


def test_latest_context_size_sums_input_and_cache(tmp_path: Path) -> None:
    """input + cache_read + cache_creation of the latest assistant message."""
    tp = _write_transcript(
        tmp_path / "t.jsonl",
        [
            {"type": "user", "message": {"content": "hi"}},
            _assistant(inp=1000, cache_read=800000, cache_creation=5000, output=200),
        ],
    )
    assert token_meter.latest_context_size(tp) == 806000


def test_latest_context_size_picks_most_recent_assistant(tmp_path: Path) -> None:
    """The NEWEST assistant message wins, not an earlier one."""
    tp = _write_transcript(
        tmp_path / "t.jsonl",
        [
            _assistant(inp=100, cache_read=100, cache_creation=0),  # older: 200
            {"type": "user", "message": {"content": "x"}},
            _assistant(inp=2000, cache_read=300000, cache_creation=0),  # newest: 302000
        ],
    )
    assert token_meter.latest_context_size(tp) == 302000


def test_latest_context_size_missing_file_is_none(tmp_path: Path) -> None:
    """Absent transcript -> None (correct-by-omission, the guard stays silent)."""
    assert token_meter.latest_context_size(tmp_path / "nope.jsonl") is None


def test_latest_context_size_no_assistant_usage_is_none(tmp_path: Path) -> None:
    """No assistant `usage` in the tail -> None rather than guess."""
    tp = _write_transcript(
        tmp_path / "t.jsonl",
        [
            {"type": "user", "message": {"content": "hi"}},
            {"type": "assistant", "message": {"content": "no usage block"}},
        ],
    )
    assert token_meter.latest_context_size(tp) is None


def test_latest_context_size_skips_zero_total(tmp_path: Path) -> None:
    """A zero-total assistant message is skipped; the earlier nonzero one is returned."""
    tp = _write_transcript(
        tmp_path / "t.jsonl",
        [
            _assistant(inp=500, cache_read=0, cache_creation=0),  # 500
            _assistant(inp=0, cache_read=0, cache_creation=0),  # 0 -> skipped
        ],
    )
    assert token_meter.latest_context_size(tp) == 500


# ---------- _truthy / _coerce_int / _bucket_tokens / _bucket_pct ------------


def test_truthy_default_when_empty() -> None:
    """Unset/empty -> the supplied default (default-ON is the load-bearing case)."""
    mod = _import_hook()
    assert mod._truthy(None, default=True) is True
    assert mod._truthy("", default=True) is True
    assert mod._truthy(None, default=False) is False


def test_truthy_false_spellings() -> None:
    """false/0/no/off (case/space-insensitive) -> False; anything else -> True."""
    mod = _import_hook()
    for v in ("false", "0", "no", "off", "FALSE", " Off "):
        assert mod._truthy(v, default=True) is False
    for v in ("true", "1", "yes", "on"):
        assert mod._truthy(v, default=False) is True


def test_coerce_int() -> None:
    """Junk/negative -> default; 0 stays 0 (a valid disable value)."""
    mod = _import_hook()
    assert mod._coerce_int("85", 60) == 85
    assert mod._coerce_int(None, 60) == 60
    assert mod._coerce_int("junk", 60) == 60
    assert mod._coerce_int("-5", 60) == 60
    assert mod._coerce_int("0", 60) == 0


def test_bucket_tokens_and_pct() -> None:
    """TRDD-YRPUSIFY: tokens floor to 10k and pct floors to 5-pt steps — the cache-stable
    labels the injected lines use so a band of raw values renders identically."""
    mod = _import_hook()
    assert mod._bucket_tokens(806000) == "~800k"  # floored to the 10k bucket
    assert mod._bucket_tokens(1_000_000) == "~1.0M"
    assert mod._bucket_tokens(9_999) == "~0k"
    assert mod._bucket_tokens(-5) == "~0k"
    assert mod._bucket_pct(72) == "~70%"
    assert mod._bucket_pct(85) == "~85%"


# ---------- _resolve_context -----------------------------------------------


def test_resolve_context_prefers_snapshot(tmp_path: Path) -> None:
    """The statusline snapshot (real window) is preferred over the transcript."""
    mod = _import_hook()
    sid = "sess-1"
    snapdir = tmp_path / ".claude" / "janitor"
    snapdir.mkdir(parents=True)
    (snapdir / f"context-usage.{sid}.json").write_text(json.dumps({"pct": 73, "tokens": 730000, "window": 1000000, "ts": 100}), encoding="utf-8")
    pct, tokens, window, stale = mod._resolve_context(str(tmp_path), sid, "", 1_000_000, now=150)
    assert (pct, tokens, window) == (73, 730000, 1000000)
    assert stale is False


def test_resolve_context_snapshot_stale(tmp_path: Path) -> None:
    """An old snapshot is flagged stale (ts far in the past)."""
    mod = _import_hook()
    sid = "s"
    snapdir = tmp_path / ".claude" / "janitor"
    snapdir.mkdir(parents=True)
    (snapdir / f"context-usage.{sid}.json").write_text(json.dumps({"pct": 50, "ts": 0}), encoding="utf-8")
    res = mod._resolve_context(str(tmp_path), sid, "", 1_000_000, now=10_000)
    assert res[0] == 50 and res[3] is True


def test_resolve_context_transcript_fallback(tmp_path: Path) -> None:
    """No snapshot -> read occupancy from the transcript over the fallback window."""
    mod = _import_hook()
    tp = _write_transcript(tmp_path / "t.jsonl", [_assistant(inp=10000, cache_read=800000)])
    pct, tokens, window, stale = mod._resolve_context(str(tmp_path), "no-snap", tp, 1_000_000, now=0)
    assert tokens == 810000 and window == 1_000_000 and pct == 81 and stale is False


def test_resolve_context_none_when_no_source(tmp_path: Path) -> None:
    """No snapshot AND no transcript -> (None, None, None, False) -> guard stays silent."""
    mod = _import_hook()
    assert mod._resolve_context(str(tmp_path), "x", "", 1_000_000, now=0) == (None, None, None, False)


# ---------- _format_line ----------------------------------------------------


def test_format_line_below_suggest_no_nudge() -> None:
    """Below the advisory threshold -> info line only, no compact nudge."""
    mod = _import_hook()
    line = mod._format_line(40, 400000, 1_000_000, False, 60)
    assert "~40% (~400k/~1.0M) used" in line  # bucketed (TRDD-YRPUSIFY)
    assert "/janitor-compact-context" not in line


def test_format_line_at_suggest_has_nudge() -> None:
    """At/above the advisory threshold -> append the /janitor-compact-context nudge."""
    mod = _import_hook()
    line = mod._format_line(72, 720000, 1_000_000, False, 60)
    assert "~70%" in line and "/janitor-compact-context" in line  # 72 floored to the 5-pt band (TRDD-YRPUSIFY)


def test_format_line_stale_suffix() -> None:
    """A stale snapshot adds the lag caveat."""
    mod = _import_hook()
    line = mod._format_line(50, None, None, True, 60)
    assert "snapshot may lag" in line


# ---------- _recently_compacted / _mark_compacted (real fs dedupe) ----------


def test_dedupe_roundtrip(tmp_path: Path) -> None:
    """A mark suppresses a re-fire inside the window and expires past it."""
    mod = _import_hook()
    pd = str(tmp_path)
    assert mod._recently_compacted(pd, now=1000) is False
    mod._mark_compacted(pd, now=1000)
    assert mod._recently_compacted(pd, now=1000 + 10) is True  # within 180s window
    assert mod._recently_compacted(pd, now=1000 + 10_000) is False  # past the window


# ---------- _maybe_enforce (the decision matrix) ---------------------------


def test_enforce_below_hardstop_is_none(tmp_path: Path) -> None:
    """Below the hard-stop -> no enforcement (falls through to advisory)."""
    mod = _import_hook()
    assert mod._maybe_enforce(50, 500000, str(tmp_path), hardstop_pct=85, autocompact=True, now=0) is None


def test_enforce_autocompact_disabled_is_none(tmp_path: Path) -> None:
    """autocompact off -> advisory-only even above the cap."""
    mod = _import_hook()
    assert mod._maybe_enforce(95, 950000, str(tmp_path), hardstop_pct=85, autocompact=False, now=0) is None


def test_enforce_hardstop_zero_disables(tmp_path: Path) -> None:
    """hardstop_pct=0 disables enforcement by threshold."""
    mod = _import_hook()
    assert mod._maybe_enforce(95, 950000, str(tmp_path), hardstop_pct=0, autocompact=True, now=0) is None


def test_run_compact_trigger_argv_requests_hard(tmp_path: Path, monkeypatch) -> None:
    """The >=85% enforcement tier must pass --hard explicitly (TRDD-0GPQROC1): the
    trigger's CLI default became soft/enqueue, but this is the emergency wall — the
    ESC-now semantics have to be requested. Captures the REAL argv by intercepting
    subprocess.run inside the hook module; no keystroke is ever sent."""
    mod = _import_hook()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "compact_trigger.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(tmp_path))
    captured: list[list[str]] = []

    class _Done:
        stdout = "COMPACT_FIRED"

    def _fake_run(argv, **_kw):
        captured.append(list(argv))
        return _Done()

    monkeypatch.setattr(mod.subprocess, "run", _fake_run)
    assert mod._run_compact_trigger(90) == "COMPACT_FIRED"
    assert len(captured) == 1
    assert "--hard" in captured[0], "enforcement auto-compact must request the ESC path"


def test_enforce_fires_deny_on_compact_fired(tmp_path: Path, monkeypatch) -> None:
    """Above the cap with a fired compaction -> deny, and the mark suppresses re-deny."""
    mod = _import_hook()
    monkeypatch.setattr(mod, "_run_compact_trigger", lambda _pct: "COMPACT_FIRED")
    d = mod._maybe_enforce(90, 900000, str(tmp_path), hardstop_pct=85, autocompact=True, now=500)
    assert d is not None
    assert d["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert mod._recently_compacted(str(tmp_path), now=520) is True
    # immediate re-call inside the dedupe window -> None (no deny-after-resume loop)
    assert mod._maybe_enforce(90, 900000, str(tmp_path), hardstop_pct=85, autocompact=True, now=520) is None


def test_enforce_no_iterm_degrades_to_advisory(tmp_path: Path, monkeypatch) -> None:
    """No automatable terminal -> None (advisory), and NOT marked (a later fire is allowed)."""
    mod = _import_hook()
    monkeypatch.setattr(mod, "_run_compact_trigger", lambda _pct: "NO_ITERM")
    assert mod._maybe_enforce(90, 900000, str(tmp_path), hardstop_pct=85, autocompact=True, now=0) is None
    assert mod._recently_compacted(str(tmp_path), now=1) is False


def test_enforce_recently_compacted_short_circuits(tmp_path: Path, monkeypatch) -> None:
    """A recent mark short-circuits BEFORE the trigger runs (no compact spam)."""
    mod = _import_hook()
    mod._mark_compacted(str(tmp_path), now=100)
    called: list[int] = []
    monkeypatch.setattr(mod, "_run_compact_trigger", lambda pct: called.append(pct) or "COMPACT_FIRED")
    assert mod._maybe_enforce(90, 900000, str(tmp_path), hardstop_pct=85, autocompact=True, now=110) is None
    assert called == []


def test_enforce_trigger_exception_is_none(tmp_path: Path, monkeypatch) -> None:
    """A crashing trigger never crashes/blocks the tool -> None (fail-open)."""
    mod = _import_hook()

    def _boom(_pct: int) -> str:
        raise RuntimeError("nope")

    monkeypatch.setattr(mod, "_run_compact_trigger", _boom)
    assert mod._maybe_enforce(90, 900000, str(tmp_path), hardstop_pct=85, autocompact=True, now=0) is None


# ---------- _deny / _advisory shapes ---------------------------------------


def test_deny_shape() -> None:
    """The deny dict carries the PreToolUse deny decision + the % in its reason."""
    mod = _import_hook()
    d = mod._deny(90, 900000)
    hs = d["hookSpecificOutput"]
    assert hs["hookEventName"] == "PreToolUse"
    assert hs["permissionDecision"] == "deny"
    assert "90%" in hs["permissionDecisionReason"]


def test_advisory_shape() -> None:
    """The advisory dict carries additionalContext and NO permissionDecision."""
    mod = _import_hook()
    a = mod._advisory("hello")
    hs = a["hookSpecificOutput"]
    assert hs["hookEventName"] == "PreToolUse"
    assert hs["additionalContext"] == "hello"
    assert "permissionDecision" not in hs


# ---------- main() — the whole flow, in-process + hermetic ------------------


def test_main_disabled_is_silent(monkeypatch, capsys) -> None:
    """Watchdog disabled -> exit 0, zero output."""
    mod = _import_hook()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED", "false")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload())))
    assert mod.main() == 0
    assert capsys.readouterr().out == ""


def test_main_silent_when_no_context(tmp_path: Path, monkeypatch, capsys) -> None:
    """No snapshot and no transcript -> pct None -> exit 0, zero output (fail-open)."""
    mod = _import_hook()
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload())))
    assert mod.main() == 0
    assert capsys.readouterr().out == ""


def test_main_silent_below_suggest(tmp_path: Path, monkeypatch, capsys) -> None:
    """Below the advisory threshold -> NO output (zero context cost until near the cap)."""
    mod = _import_hook()
    tp = _write_transcript(tmp_path / "t.jsonl", [_assistant(inp=10000, cache_read=200000)])  # 210000 -> 21%
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload(transcript=tp))))
    assert mod.main() == 0
    assert capsys.readouterr().out == ""


def test_main_advisory_when_enforcement_disabled(tmp_path: Path, monkeypatch, capsys) -> None:
    """High context but autocompact off -> advisory only, never a deny, never a fire."""
    mod = _import_hook()
    tp = _write_transcript(tmp_path / "t.jsonl", [_assistant(inp=10000, cache_read=700000)])  # 710000 -> 71%
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED", raising=False)
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_CONTEXT_AUTOCOMPACT_ENABLED", "false")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))

    def _boom(_pct: int) -> str:
        raise AssertionError("compact must NOT fire when autocompact is disabled")

    monkeypatch.setattr(mod, "_run_compact_trigger", _boom)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload(transcript=tp))))
    assert mod.main() == 0
    hs = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert "~70%" in hs["additionalContext"]  # 71 floored to the 5-pt band (TRDD-YRPUSIFY)
    assert "permissionDecision" not in hs


def test_main_enforces_deny_near_cap(tmp_path: Path, monkeypatch, capsys) -> None:
    """Near the cap with autocompact on (default) -> deny, trigger called with the pct."""
    mod = _import_hook()
    tp = _write_transcript(tmp_path / "t.jsonl", [_assistant(inp=10000, cache_read=900000)])  # 910000 -> 91%
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_CONTEXT_AUTOCOMPACT_ENABLED", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    fired: list[int] = []
    monkeypatch.setattr(mod, "_run_compact_trigger", lambda pct: fired.append(pct) or "COMPACT_FIRED")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload(transcript=tp))))
    assert mod.main() == 0
    assert json.loads(capsys.readouterr().out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert fired == [91]


def test_main_no_iterm_degrades_to_advisory_near_cap(tmp_path: Path, monkeypatch, capsys) -> None:
    """Near the cap but no terminal -> advisory only, never a stuck deny."""
    mod = _import_hook()
    tp = _write_transcript(tmp_path / "t.jsonl", [_assistant(inp=10000, cache_read=900000)])  # 91%
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_CONTEXT_WATCHDOG_ENABLED", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_CONTEXT_AUTOCOMPACT_ENABLED", raising=False)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setattr(mod, "_run_compact_trigger", lambda _pct: "NO_ITERM")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(_payload(transcript=tp))))
    assert mod.main() == 0
    hs = json.loads(capsys.readouterr().out)["hookSpecificOutput"]
    assert "additionalContext" in hs
    assert "permissionDecision" not in hs
