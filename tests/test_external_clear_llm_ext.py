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


# --- the data dir, which is another plugin's and cannot be guessed -----------------


def test_data_dir_is_derived_from_the_binarys_own_marketplace(tmp_path, monkeypatch) -> None:
    """Two llm-externalizer stores exist on a real host; the binary's path picks the right one.

    Guessing installs a second copy of a native module into the wrong store, so this must be
    derived, never hardcoded.
    """
    home = tmp_path
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: home))
    want = home / ".claude" / "plugins" / "data" / "llm-externalizer-emasoft-plugins"
    want.mkdir(parents=True)
    (home / ".claude" / "plugins" / "data" / "llm-externalizer-inline").mkdir()
    binary = home / ".claude/plugins/cache/emasoft-plugins/llm-externalizer/12.0.0/bin/llm-ext"
    binary.parent.mkdir(parents=True)
    binary.touch()
    assert ec.llm_ext_data_dir(str(binary)) == str(want)


def test_data_dir_returns_empty_for_an_unexpected_layout(tmp_path) -> None:
    """An unrecognised path yields "" so the caller DEGRADES rather than inventing a directory."""
    assert ec.llm_ext_data_dir(str(tmp_path / "usr" / "local" / "bin" / "llm-ext")) == ""


# --- every CLI failure mode must arrive as None -----------------------------------


def test_summary_is_none_when_the_cli_exits_non_zero(tmp_path, monkeypatch) -> None:
    t = tmp_path / "s.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ec.shutil, "which", lambda _n: "/x/cache/m/llm-externalizer/1/bin/llm-ext")
    monkeypatch.setattr(ec, "llm_ext_data_dir", lambda _b: "/data")
    assert ec.run_llm_ext_summary(str(t), runner=lambda *a, **k: _Proc(1, "junk")) is None


def test_summary_is_none_on_timeout_rather_than_raising(tmp_path, monkeypatch) -> None:
    """A composer that can raise is a composer that can stop the clear from happening."""
    t = tmp_path / "s.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ec.shutil, "which", lambda _n: "/x/cache/m/llm-externalizer/1/bin/llm-ext")
    monkeypatch.setattr(ec, "llm_ext_data_dir", lambda _b: "/data")

    def _boom(*_a, **_k):
        raise subprocess.TimeoutExpired(cmd="llm-ext", timeout=1)

    assert ec.run_llm_ext_summary(str(t), runner=_boom) is None


def test_summary_is_none_when_the_data_dir_cannot_be_resolved(tmp_path, monkeypatch) -> None:
    """Without CLAUDE_PLUGIN_DATA the launcher dies before doing any work — do not even call."""
    t = tmp_path / "s.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ec.shutil, "which", lambda _n: "/weird/llm-ext")
    monkeypatch.setattr(ec, "llm_ext_data_dir", lambda _b: "")
    called = []
    ec.run_llm_ext_summary(str(t), runner=lambda *a, **k: called.append(1) or _Proc(0, "x"))
    assert not called, "must not invoke the CLI when its data dir is unknown"


def test_summary_passes_the_data_dir_in_the_child_env(tmp_path, monkeypatch) -> None:
    t = tmp_path / "s.jsonl"
    t.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr(ec.shutil, "which", lambda _n: "/x/cache/m/llm-externalizer/1/bin/llm-ext")
    monkeypatch.setattr(ec, "llm_ext_data_dir", lambda _b: "/data/llm-ext")
    seen: dict = {}

    def _run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw.get("env") or {}
        return _Proc(0, "a summary")

    assert ec.run_llm_ext_summary(str(t), runner=_run) == "a summary"
    assert seen["env"].get("CLAUDE_PLUGIN_DATA") == "/data/llm-ext"
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
