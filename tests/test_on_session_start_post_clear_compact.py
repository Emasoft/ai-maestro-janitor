"""Tests for `scripts/hooks/on-session-start-post-clear-compact.py` (TRDD-RAEGS1D5 card 5).

Loaded dynamically (`importlib.util`, matching `tests/test_clear_trigger.py`'s own pattern)
because the filename carries hyphens and is not a normal import target. `jev_compact.py` is
NEVER invoked for real — every test uses a stub script exactly like
`tests/test_summarize_previous_session.py` does, so no network call, no httpx/jevctx import,
ever happens in this file.
"""

from __future__ import annotations

import importlib.util as _u
import json
import stat
import sys
import time
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "on-session-start-post-clear-compact.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import handoff_files  # noqa: E402
import jev_compaction_lane as jcl  # noqa: E402
import state  # noqa: E402


def _import():
    spec = _u.spec_from_file_location("post_clear_compact_hook_under_test", str(_HOOK))
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_STUB_JEV_COMPACT = """#!/usr/bin/env python3
import sys
from pathlib import Path
argv = sys.argv
Path({argv_log!r}).write_text(repr(argv), encoding="utf-8")
out_text = {out_text!r}
if out_text and "--out" in argv:
    Path(argv[argv.index("--out") + 1]).write_text(out_text, encoding="utf-8")
sys.exit({exit_code})
"""


def _stub_jev_compact(plugin_root: Path, argv_log: Path, *, exit_code: int, out_text: str = "") -> None:
    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT.format(argv_log=str(argv_log), out_text=out_text, exit_code=exit_code),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)


_COMPACTED_DOC = (
    "# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Kept items\nsome text\n\n"
    'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
    "expand --transcript /tmp/x <id>"
)


def _env(tmp_path: Path, monkeypatch, *, project_dir: Path, plugin_root: Path) -> None:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(project_dir))
    monkeypatch.setenv("CLAUDE_PLUGIN_ROOT", str(plugin_root))
    monkeypatch.setenv("HOME", str(tmp_path / "fake-home"))
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    for fn in (state.project_root, state.janitor_root, state.state_dir, state.log_dir):
        fn.cache_clear()


def _write_sidecar(sd: Path, pane_env: dict, *, transcript: str, age_s: int = 0) -> Path:
    pane_key = state.terminal_pane_key(pane_env)
    assert pane_key
    sd.mkdir(parents=True, exist_ok=True)
    path = sd / f"resume-after-clear.{pane_key}.transcript"
    epoch = int(time.time()) - age_s
    path.write_text(f"{transcript}\n{epoch}\n", encoding="utf-8")
    return path


def test_consumes_fresh_sidecar_and_injects_real_compacted_context(tmp_path, monkeypatch):
    """A fresh sidecar for THIS pane is consumed (renamed to `.consumed-*`), a REAL Jev
    compose runs against the NAMED transcript, and the injected text carries the header +
    the compacted context."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%4")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text('{"message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    sidecar = _write_sidecar(sd, {"TMUX_PANE": "%4"}, transcript=str(transcript))
    _stub_jev_compact(plugin_root, tmp_path / "argv.txt", exit_code=0, out_text=_COMPACTED_DOC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    assert "[janitor-handoff] Post-clear handoff, ALREADY IN CONTEXT below" in out
    assert "pointers expand with:" in out
    assert not sidecar.is_file(), "the pristine sidecar must be renamed away, not left in place"
    consumed = list(sd.glob("resume-after-clear.*.transcript.consumed-*"))
    assert consumed, "expected a .consumed-<epoch> sidecar after this run"
    group = handoff_files.newest_group(sd)
    assert group and "pointers expand with:" in group[0].read_text(encoding="utf-8")


def test_a_stale_sidecar_is_ignored_and_never_composed(tmp_path, monkeypatch):
    """A sidecar older than 300s is consumed (so it is never replayed later) but triggers NO
    compose and NO injection."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%8")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%8"}, transcript=str(transcript), age_s=10_000)
    argv_log = tmp_path / "argv.txt"
    _stub_jev_compact(plugin_root, argv_log, exit_code=0, out_text=_COMPACTED_DOC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()

    assert rc == 0
    assert buf.getvalue() == ""
    assert not argv_log.is_file(), "jev_compact.py must never run for a stale sidecar"
    assert list(sd.glob("resume-after-clear.*.transcript.consumed-*")), (
        "a stale sidecar must still be consumed, so a later manual clear cannot replay it"
    )


def test_compose_failure_writes_the_template_marker(tmp_path, monkeypatch):
    """A non-zero `jev_compact.py compact` exit writes a TEMPLATE_MARKER-prefixed handoff and
    injects THAT — never silence, and never mistaken for a real compose later."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%2")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%2"}, transcript=str(transcript))
    _stub_jev_compact(plugin_root, tmp_path / "argv.txt", exit_code=6)  # EXIT_DECLINED_NO_DIGEST

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    assert handoff_files.TEMPLATE_MARKER in out
    group = handoff_files.newest_group(sd)
    assert group and group[0].read_text(encoding="utf-8").lstrip().startswith(
        handoff_files.TEMPLATE_MARKER
    )


def test_two_panes_do_not_cross(tmp_path, monkeypatch):
    """A sidecar written for pane A must be invisible to a session running in pane B."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    sidecar_a = _write_sidecar(sd, {"TMUX_PANE": "%1"}, transcript=str(transcript))

    monkeypatch.setenv("TMUX_PANE", "%2")  # a DIFFERENT pane running this hook
    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()

    assert rc == 0
    assert buf.getvalue() == ""
    assert sidecar_a.is_file(), "pane B's run must never touch pane A's sidecar"


def test_non_clear_source_does_nothing(tmp_path, monkeypatch):
    """Only `source == "clear"` may run at all -- `compact`/`resume`/`startup` must be a
    guaranteed no-op (the loop guard every sibling SessionStart hook in this lane relies on)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%3")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%3"}, transcript=str(tmp_path / "cleared.jsonl"))

    mod = _import()
    for source in ("compact", "resume", "startup", "fork"):
        monkeypatch.setattr(mod, "_payload", lambda source=source: {"source": source})
        assert mod.main() == 0
    # sidecar untouched -- no rename attempted for a non-clear source
    pane_key = state.terminal_pane_key({"TMUX_PANE": "%3"})
    assert (sd / f"resume-after-clear.{pane_key}.transcript").is_file()


def test_hooks_json_registers_the_new_hook_with_timeout_90():
    """`hooks/hooks.json` must register this hook under SessionStart with `timeout: 90`."""
    data = json.loads((_PROJECT_ROOT / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    matches = [
        entry
        for group in data["hooks"]["SessionStart"]
        for entry in group["hooks"]
        if "on-session-start-post-clear-compact.py" in entry.get("command", "")
    ]
    assert len(matches) == 1, matches
    assert matches[0]["timeout"] == 90


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
