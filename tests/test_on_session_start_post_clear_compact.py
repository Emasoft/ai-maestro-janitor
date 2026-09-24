"""Tests for `scripts/hooks/on-session-start-post-clear-compact.py` (TRDD-RAEGS1D5 card 5).

Loaded dynamically (`importlib.util`, matching `tests/test_clear_trigger.py`'s own pattern)
because the filename carries hyphens and is not a normal import target. `jev_compact.py` is
NEVER invoked for real — every test uses a stub script exactly like
`tests/test_summarize_previous_session.py` does, so no network call, no httpx/jevctx import,
ever happens in this file.
"""

from __future__ import annotations

import ast
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

import external_clear as ec  # noqa: E402
import handoff_files  # noqa: E402
import jev_compaction_lane as jcl  # noqa: E402
import state  # noqa: E402
import terminal_trigger  # noqa: E402


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
# Card 5 two-renderings (TRDD-RAEGS1D5): the real CLI writes a SECOND, capped rendering to
# `--inject-out` when given -- the stub mirrors that shape (same text is fine for these tests,
# which only assert on presence/size/content markers, never on the two documents differing).
if out_text and "--inject-out" in argv:
    Path(argv[argv.index("--inject-out") + 1]).write_text(out_text, encoding="utf-8")
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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

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


_STUB_JEV_COMPACT_TWO_DOCS = """#!/usr/bin/env python3
import sys
from pathlib import Path
argv = sys.argv
if "--out" in argv:
    Path(argv[argv.index("--out") + 1]).write_text({full_text!r}, encoding="utf-8")
if "--inject-out" in argv:
    Path(argv[argv.index("--inject-out") + 1]).write_text({inject_text!r}, encoding="utf-8")
sys.exit(0)
"""


def test_keyed_handoff_gets_the_full_document_injection_gets_the_capped_one(tmp_path, monkeypatch):
    """Card 5 two-renderings (TRDD-RAEGS1D5): the defect this card fixes was that the keyed
    handoff FILE on disk (what a later manual read, or the next SessionStart's fallback
    injection, sees) was the SAME capped ~4.3 KB rendering as the printed stdout injection --
    discarding the full document for no reason. This test uses a stub that writes two
    DELIBERATELY DIFFERENT documents to `--out` and `--inject-out` and asserts each lands where
    it belongs: the FULL one in the keyed handoff file, the CAPPED one in stdout."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%11")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%11"}, transcript=str(transcript))

    # TRDD-EFA4P42B: `render()` no longer repeats the transcript path in the header (the
    # trailer is now the only place it appears), and drops the "## Digest" heading entirely
    # from an injected render with an empty digest -- so `inject_doc` below carries neither.
    full_doc = (
        "# Compacted context (Jev compaction)\n\n## Digest\nTHE-FULL-DIGEST"
        '-MARKER\n\n## Kept items\nsome text\n\npointers expand with: uv run --script '
        '"$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" expand --transcript /tmp/x <id>'
    )
    inject_doc = (
        "# Compacted context (Jev compaction)\n\n"
        "## Kept items\nsome text\n\nFull compacted context: /tmp/full.md -- read it ONLY if "
        "what you need is not shown above; try list/search first with the expand command "
        'below (replace <id> with --list --grep TEXT).\n\npointers expand with: uv run --script '
        '"$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" expand --transcript /tmp/x <id>'
    )
    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT_TWO_DOCS.format(full_text=full_doc, inject_text=inject_doc),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    # The printed injection carries the CAPPED document's own marker, not the full one's.
    assert "Full compacted context:" in out
    assert "THE-FULL-DIGEST-MARKER" not in out
    # The keyed handoff FILE on disk carries the FULL document verbatim -- never the capped one.
    group = handoff_files.newest_group(sd)
    assert group, "expected a keyed handoff to have been written"
    on_disk = group[0].read_text(encoding="utf-8")
    assert "THE-FULL-DIGEST-MARKER" in on_disk
    assert "Full compacted context:" not in on_disk


_STUB_JEV_COMPACT_OUT_ONLY = """#!/usr/bin/env python3
import sys
from pathlib import Path
argv = sys.argv
if "--out" in argv:
    Path(argv[argv.index("--out") + 1]).write_text({full_text!r}, encoding="utf-8")
# Deliberately never writes --inject-out, even though it is present in argv -- simulates a
# crash/kill between the two atomic_write calls in the real jev_compact.py.
sys.exit(0)
"""


def test_missing_inject_out_falls_back_to_the_full_document_not_the_template(tmp_path, monkeypatch):
    """Review finding, card 5 two-renderings (TRDD-RAEGS1D5): `--out` and `--inject-out` are two
    separately `atomic_write`-n files, not one atomic pair -- a process killed between the two
    (OOM, hitting the timeout boundary) leaves `--out` complete and `--inject-out` missing. The
    hook must not discard the perfectly good full document in that case and degrade all the way
    to the TEMPLATE_MARKER fallback; it must inject/keep the full document instead."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%12")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%12"}, transcript=str(transcript))

    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT_OUT_ONLY.format(full_text=_COMPACTED_DOC), encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    assert handoff_files.TEMPLATE_MARKER not in out, "must not degrade to the template fallback"
    assert "pointers expand with:" in out, "the full document must still be injected"
    group = handoff_files.newest_group(sd)
    assert group and not group[0].read_text(encoding="utf-8").lstrip().startswith(
        handoff_files.TEMPLATE_MARKER
    )


_STUB_JEV_COMPACT_EMPTY_INJECT = """#!/usr/bin/env python3
import sys
from pathlib import Path
argv = sys.argv
if "--out" in argv:
    Path(argv[argv.index("--out") + 1]).write_text({full_text!r}, encoding="utf-8")
# `--inject-out` IS written (unlike _STUB_JEV_COMPACT_OUT_ONLY above -- no OSError on read), but
# with EMPTY content -- mirrors `jev_compaction.compose`'s own terminal budget-floor stage
# (`_render_minimal_fallback`) degrading all the way to "" when `--inject-max-bytes` is too
# small even for its own constant-size marker.
if "--inject-out" in argv:
    Path(argv[argv.index("--inject-out") + 1]).write_text("", encoding="utf-8")
sys.exit(0)
"""


def test_empty_inject_out_gets_a_marked_line_not_silence_or_the_full_document(
    tmp_path, monkeypatch,
):
    """Round 4 coordinator task (TRDD-RAEGS1D5): `compose()`'s own terminal budget-floor stage
    can legitimately write an EMPTY `--inject-out` file (see `_render_minimal_fallback`) -- the
    read succeeds (no `OSError`), so the "missing companion" fallback above (falls back to the
    full document) never fires. Feeding that empty string straight to `external_clear.
    compose_handoff` as `summary` would be silently indistinguishable from `summary=None`
    ("Jev never ran") -- its own `if summary:` check treats `""` exactly like `None`, dropping
    the WHOLE compacted-context section with no notice at all. The hook must instead inject one
    short marked line naming where the full copy landed -- never the full uncapped document
    (that would refill the very context the clear was meant to empty) and never nothing."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%13")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%13"}, transcript=str(transcript))

    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT_EMPTY_INJECT.format(full_text=_COMPACTED_DOC), encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    key = handoff_files.session_key(str(transcript))
    out_path = sd / f"jev-compacted-{key or handoff_files.UNKEYED_KEY}.md"

    assert rc == 0
    assert handoff_files.TEMPLATE_MARKER not in out, "must not degrade to the template fallback"
    # Never the full document refilling the injection (the "missing companion" fallback is a
    # DIFFERENT, OSError-triggered path -- not this one).
    assert "some text" not in out, "must not fall back to the full uncapped document"
    # Never silent either -- one short marked line, naming the real path to the full copy.
    assert (
        f"compacted context too large for the handoff; read the full copy at {out_path}"
    ) in out
    # The keyed handoff FILE on disk still carries the full document, untouched.
    group = handoff_files.newest_group(sd)
    assert group and "some text" in group[0].read_text(encoding="utf-8")


_STUB_JEV_COMPACT_MARKER_ONLY_INJECT = """#!/usr/bin/env python3
import sys
from pathlib import Path
argv = sys.argv
if "--out" in argv:
    Path(argv[argv.index("--out") + 1]).write_text({full_text!r}, encoding="utf-8")
# `--inject-out` gets JUST the marker `jev_compaction.py::_render_minimal_fallback` can write
# alone (no truncated owner-message body, no pointer) when there is room for the marker but not
# for anything else -- non-empty (`.strip()` alone would not catch it), but as content-free as
# "" for a resumed session: no real transcript content, no path back to the full copy either
# (review finding, round 4: the FIRST fix here only caught the fully-empty case).
if "--inject-out" in argv:
    Path(argv[argv.index("--inject-out") + 1]).write_text(
        "(budget too small, see full copy)", encoding="utf-8",
    )
sys.exit(0)
"""


def test_marker_only_inject_out_also_gets_the_marked_line_not_passed_through(
    tmp_path, monkeypatch,
):
    """Round 4 review finding (TRDD-RAEGS1D5): `_render_minimal_fallback` in jev_compaction.py
    has THREE possible outputs, not two -- `""`, its own fixed marker ALONE (no body, no
    pointer, no path), or the marker plus a truncated body plus a pointer. The first fix here
    (`test_empty_inject_out_gets_a_marked_line_...`) only special-cased the fully-empty string;
    the marker-alone case is non-empty so `.strip()` alone lets it straight through to
    `external_clear.compose_handoff`, which would render it VERBATIM as the compacted-context
    body -- "(budget too small, see full copy)" with no path at all, a dead end for a resumed
    session (round 3's own report, finding 2, named this exact gap and deferred the fix to
    "whichever caller wires the injected copy in"). This hook must replace THIS case with the
    same marked-line-plus-real-path treatment, not pass the pathless marker through."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%14")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%14"}, transcript=str(transcript))

    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT_MARKER_ONLY_INJECT.format(full_text=_COMPACTED_DOC), encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    key = handoff_files.session_key(str(transcript))
    out_path = sd / f"jev-compacted-{key or handoff_files.UNKEYED_KEY}.md"

    assert rc == 0
    assert handoff_files.TEMPLATE_MARKER not in out, "must not degrade to the template fallback"
    assert "some text" not in out, "must not fall back to the full uncapped document"
    # The bare, pathless marker must never reach the printed injection unchanged.
    assert mod._JEV_MINIMAL_FALLBACK_MARKER not in out
    assert (
        f"compacted context too large for the handoff; read the full copy at {out_path}"
    ) in out


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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

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


def test_compose_failure_spawns_the_detached_retry_fallback_lane_with_transcript(
    tmp_path, monkeypatch,
):
    """R2 (TRDD-RAEGS1D5, owner decision 2026-09-23): this hook only ever gets ONE bounded
    attempt (its own `hooks.json` timeout) -- on failure it must ALSO spawn
    `summarize_previous_session.py --transcript <this transcript>` (never a guess) detached,
    with the SAME Popen shape `on-session-start.py`'s own unconditional spawn uses
    (`start_new_session=True`, `env=state.detached_uv_env()`), so the owner's 5-minute
    retry-then-llm-ext budget gets spent by a process that can afford it."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%13")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%13"}, transcript=str(transcript))
    _stub_jev_compact(plugin_root, tmp_path / "argv.txt", exit_code=7)  # EXIT_JEV_ERROR
    # The hook only spawns the detached lane when it finds the script on disk (the same
    # `.is_file()` guard `on-session-start.py`'s own unconditional spawn uses) -- a placeholder
    # is enough here since the spawn itself is faked below, never actually run.
    (plugin_root / "scripts" / "summarize_previous_session.py").write_text("", encoding="utf-8")

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import subprocess as _subprocess

    captured: dict = {}
    real_popen = _subprocess.Popen

    def _fake_popen(argv, **kwargs):
        # `subprocess.run` (used by `jcl.run_compact` for the REAL jev_compact.py stub call
        # above) is ITSELF implemented on top of `Popen` -- a blanket patch would also
        # intercept (and break) that call. Only the detached spawn this test targets is
        # faked; every other Popen construction (the jev_compact.py stub) runs for real.
        if isinstance(argv, (list, tuple)) and argv and "summarize_previous_session.py" in str(argv[0]):
            captured["argv"] = list(argv)
            captured["kwargs"] = kwargs

            class _Dummy:
                pass

            return _Dummy()
        return real_popen(argv, **kwargs)

    monkeypatch.setattr(_subprocess, "Popen", _fake_popen)

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()

    assert rc == 0
    assert "argv" in captured, "expected the hook to spawn the detached retry-fallback lane"
    argv = captured["argv"]
    assert argv[0] == str(plugin_root / "scripts" / "summarize_previous_session.py")
    assert argv[1:] == ["--transcript", str(transcript)]
    kwargs = captured["kwargs"]
    assert kwargs.get("start_new_session") is True
    assert kwargs.get("stdout") is _subprocess.DEVNULL
    # `env=state.detached_uv_env()` -- proven by shape (every real env var + no VIRTUAL_ENV),
    # not by identity, since `detached_uv_env()` builds a fresh dict each call.
    assert "VIRTUAL_ENV" not in kwargs.get("env", {"VIRTUAL_ENV": "should not be here"})
    assert kwargs.get("env", {}).get("HOME") == str(tmp_path / "fake-home")


def test_large_compacted_context_still_injects_under_9000_bytes(tmp_path, monkeypatch):
    """Card 5 measured fact (reports/compaction-replacement/20260923_064108+0200-hook-output-
    experiments.md): the SessionStart hook's stdout is only injected in full up to ~9,000
    bytes. The stub `jev_compact.py` here stands in for a LARGE real compaction (many kept
    items + a full elided-pointer list, unbounded before `LANE_BUDGET_TOKENS`/`_MAX_ELIDED_
    POINTERS` capped them) -- the hook must pass `LANE_INJECTION_MAX_BYTES` through to
    `compose_handoff`, which enforces the byte cap regardless of how large the compacted
    document itself is."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%9")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%9"}, transcript=str(transcript))

    huge_doc = (
        "# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Kept items\n"
        + ("some kept text\n" * 2000)
        + "\n## Elided\n"
        + "\n".join(f'[[elided id=e{i}:0 tokens=10 "line {i}"]]' for i in range(2000))
        + '\n\npointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py"'
        " expand --transcript /tmp/x <id>"
    )
    assert len(huge_doc.encode("utf-8")) > 30_000, "the fixture must actually be large"
    _stub_jev_compact(plugin_root, tmp_path / "argv.txt", exit_code=0, out_text=huge_doc)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    assert len(out.encode("utf-8")) <= 9000, f"injection was {len(out.encode('utf-8'))} bytes"
    assert "pointers expand with:" in out


def test_large_multibyte_compacted_context_stays_under_9000_bytes_with_no_split_char(
    tmp_path, monkeypatch,
):
    """Card 5 content-fit (TRDD-RAEGS1D5, item 2): every byte-budget cut in this lane
    (`compose_handoff`'s `raw[:room]` slice, `jev_compaction.py::compose`'s own `max_bytes`
    backstop) counts UTF-8 BYTES, not characters -- a fixture built only of ASCII never
    exercises the boundary where a 3-byte character (an em dash, a checkmark, box-drawing) can
    straddle a cut point. This fixture is HEAVY in exactly those: the whole document (header +
    body, including `_INJECTION_HEADER` itself, which already contains an em dash) must still
    print at <= 9,000 bytes, and decoding the printed bytes back with `errors="strict"` must
    succeed with no U+FFFD replacement character -- a split multi-byte sequence would either
    raise or leave one behind; `raw[:room].decode("utf-8", "ignore")` silently DROPS a dangling
    partial sequence instead of emitting a corrupt glyph, which is what this test pins."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%10")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%10"}, transcript=str(transcript))

    # "— ✓ " repeated: every character here is 3 bytes in UTF-8 (em dash U+2014, checkmark
    # U+2713, box-drawing U+2500), so a byte-count cut is highly likely to land mid-character
    # unless the surrounding code decodes with "ignore" rather than a bare index slice.
    multibyte_line = "— ✓ ━ " * 40
    huge_doc = (
        "# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Kept items\n"
        + ((multibyte_line + "\n") * 500)
        + "\n## Elided\n"
        + "\n".join(f'[[elided id=e{i}:0 tokens=10 "{multibyte_line}"]]' for i in range(500))
        + '\n\npointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py"'
        " expand --transcript /tmp/x <id>"
    )
    assert len(huge_doc.encode("utf-8")) > 30_000, "the fixture must actually be large"
    _stub_jev_compact(plugin_root, tmp_path / "argv.txt", exit_code=0, out_text=huge_doc)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()
    out_bytes = out.encode("utf-8")

    assert rc == 0
    assert len(out_bytes) <= 9000, f"injection was {len(out_bytes)} bytes"
    # Round-trips cleanly (no exception) and carries no replacement character -- either would
    # mean a multi-byte sequence was cut in half somewhere along the way.
    assert out_bytes.decode("utf-8", "strict") == out
    assert "�" not in out


def test_computed_inject_max_bytes_matches_room_and_summary_is_not_sliced(tmp_path, monkeypatch):
    """TRDD-RAEGS1D5 retune follow-up: `LANE_COMPACTED_MAX_BYTES` (a flat constant) used to be
    passed as `--inject-max-bytes` regardless of how much of `compose_handoff`'s own budget the
    facts section and the recent-turns tail had already spent -- whenever that flat guess
    overran the REAL room, `compose_handoff`'s own raw byte-slice cut the TAIL of the injected
    Jev summary (the newest kept items, the pointer line) instead of Jev's own priority-aware
    trim ever getting a chance to decide what to drop. The hook must now pass the room
    `external_clear.compose_handoff_room` actually computes (minus the lane's small safety
    margin) -- and a summary that fits inside it must come out of `compose_handoff` WHOLE."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%11")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text('{"message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%11"}, transcript=str(transcript))

    # Small on purpose -- well under any plausible room, so `compose_handoff` has no reason to
    # slice it; this test is about the SIZING decision (is the right number even passed?), not
    # about the slicer itself (that is `test_large_compacted_context_still_injects_under_9000_
    # bytes`'s job). No `[`/`]` anywhere -- the hook's own `state.sanitize_for_drift_line`
    # defangs every literal bracket (marker-mimicry defense, unconditional, unrelated to this
    # fix), which would otherwise make a verbatim substring check like the one below fail for a
    # reason that has nothing to do with slicing.
    small_doc = (
        "# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Kept items\n"
        "a modest kept item\nanother modest kept item\n\n"
        'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py"'
        " expand --transcript /tmp/x <id>"
    )
    argv_log = tmp_path / "argv.txt"
    _stub_jev_compact(plugin_root, argv_log, exit_code=0, out_text=small_doc)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()
    assert rc == 0

    # Independently compute the SAME room the hook must have computed, from the SAME inputs
    # (empty findings/cards -- `state_head_paths` was stubbed to `([], False, [], "")` above).
    # `now_iso`'s exact clock reading does not matter to the byte count, only its fixed
    # strftime length, so a fresh call here reproduces the same byte total the hook's own
    # (differently-timed) call produced.
    # `tail=()` (TRDD-D7RLXAN1): the Jev block carries the newest exchanges itself, so the
    # hook sizes the room with no "Recent turns" tail.
    room = ec.compose_handoff_room(
        ec.HandoffInputs(trigger="jev-compaction", findings=[], cards=[]),
        now_iso=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        tail=(),
        max_bytes=jcl.LANE_INJECTION_MAX_BYTES, source=jcl.SOURCE_JEV,
    )
    expected_inject_max_bytes = jcl.inject_max_bytes_for(room, str(transcript))

    argv_list = ast.literal_eval(argv_log.read_text(encoding="utf-8"))
    assert "--inject-max-bytes" in argv_list
    passed = int(argv_list[argv_list.index("--inject-max-bytes") + 1])
    assert passed == expected_inject_max_bytes, (passed, expected_inject_max_bytes)
    # (Adversarial review, TRDD-RAEGS1D5 retune follow-up: a `passed <= LANE_COMPACTED_MAX_BYTES`
    # assertion used to sit here -- dropped, it is a tautology once the equality above holds:
    # `inject_max_bytes_for` clamps with `min(..., LANE_COMPACTED_MAX_BYTES)` unconditionally, so
    # it can never fail once `passed == expected_inject_max_bytes` is already proven. It restated
    # a fact this test already established, not a new one.)

    # Unsliced: the WHOLE document, trailer included, appears verbatim in the final output --
    # no "_(summary truncated to fit the handoff budget)_" marker anywhere.
    assert small_doc in out
    assert "summary truncated" not in out


def test_card_heavy_facts_section_keeps_every_id_and_shortens_titles_first(tmp_path, monkeypatch):
    """TRDD-RAEGS1D5 room-floor follow-up, round 2 (coordinator review of commit 44fdec8c, gap 1):
    round 1 dropped whole CARDS to reclaim room -- but the card list is how a resumed session
    finds its in-flight TRDDs, and a card-heavy facts section is exactly the situation a BUSY
    session is in. `jcl.trim_cards_for_room` must never drop a card's id; it shortens TITLES
    (toward "") instead, so every id -- and the STATE block it points at -- survives no matter how
    much trimming this fixture needs. 10 cards with long titles is enough for this fixture to
    still get a summary out (titles shrink, not to empty -- see the companion fixture below for
    the "even empty titles aren't enough" case)."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%20")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text('{"message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%20"}, transcript=str(transcript))

    # 10 in-flight cards, (id, column, title) -- `HandoffInputs.cards`'s own shape -- each title
    # long enough (measured directly, not guessed: 750 chars x 10 cards) that the RAW, pre-trim
    # room this fixture produces is proven below the floor below, before asserting anything about
    # the fix's own behaviour on it.
    long_title = ("a very long TRDD title describing exactly what this card is about " * 20)[:750]
    cards = [(f"CARD{i:04d}", "dev", long_title) for i in range(10)]
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, cards, ""))

    small_doc = (
        "# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Kept items\n"
        "-- user newest-owner-item --\nTHE NEWEST OWNER MESSAGE survives verbatim\n\n"
        "another modest kept item\n\n"
        'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py"'
        " expand --transcript /tmp/x <id>"
    )
    argv_log = tmp_path / "argv.txt"
    _stub_jev_compact(plugin_root, argv_log, exit_code=0, out_text=small_doc)

    # Independently compute the EXACT (trimmed-inputs, inject_max_bytes) `jcl.trim_cards_for_room`
    # must produce for this fixture -- same rigor as `test_computed_inject_max_bytes_matches_
    # room_and_summary_is_not_sliced` above (exact equality against an independently-computed
    # value, not just a bound). Doubles as the fixture-adversarial check: if the RAW, full-title
    # room already met the target, this fixture would prove nothing new.
    now_iso_probe = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    tail_probe = ()  # TRDD-D7RLXAN1: the hook sizes the room with no "Recent turns" tail
    raw_room = ec.compose_handoff_room(
        ec.HandoffInputs(trigger="jev-compaction", findings=[], cards=cards),
        now_iso=now_iso_probe, tail=tail_probe,
        max_bytes=jcl.LANE_INJECTION_MAX_BYTES, source=jcl.SOURCE_JEV,
    )
    assert jcl.inject_max_bytes_for(raw_room, str(transcript)) < jcl.LANE_MIN_INJECT_BYTES, (
        "fixture must starve the RAW, full-title room below the target, or it proves nothing new"
    )
    expected_inputs, expected_inject_max_bytes = jcl.trim_cards_for_room(
        ec.HandoffInputs(trigger="jev-compaction", findings=[], cards=cards),
        now_iso=now_iso_probe, tail=tail_probe, transcript_path=str(transcript),
        max_bytes=jcl.LANE_INJECTION_MAX_BYTES, source=jcl.SOURCE_JEV,
    )
    # Every id AND column present, unchanged, none dropped -- only titles may have shrunk
    # (adversarial review, round 2 self-review: id-only checks would miss a mutation that
    # corrupted `col` while leaving `cid` intact).
    assert len(expected_inputs.cards) == 10
    assert [(cid, col) for cid, col, _title in expected_inputs.cards] == [
        (f"CARD{i:04d}", "dev") for i in range(10)
    ]
    assert any(len(title) < len(long_title) for _cid, _col, title in expected_inputs.cards), (
        "fixture must actually shorten at least one title, or this test proves nothing new"
    )

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()
    assert rc == 0

    argv_list = ast.literal_eval(argv_log.read_text(encoding="utf-8"))
    assert "--inject-max-bytes" in argv_list
    passed = int(argv_list[argv_list.index("--inject-max-bytes") + 1])
    # Exact equality (never just "never 0/negative") -- sized exactly as `jcl.trim_cards_for_room`
    # computed above, never inflated above it (round 2's own correction -- see its module comment).
    assert passed == expected_inject_max_bytes, (passed, expected_inject_max_bytes)
    assert passed > 0

    # Unsliced: the whole stub summary -- including its "newest owner" line -- survives verbatim.
    assert small_doc in out
    assert "THE NEWEST OWNER MESSAGE survives verbatim" in out
    assert "summary truncated" not in out

    # Every one of the 10 ids is still present in the printed facts section -- the round-2
    # invariant this test exists to pin.
    for i in range(10):
        assert f"TRDD-CARD{i:04d}" in out, f"card {i} lost its id"


def test_floor_backstop_holds_even_when_trimming_every_card_is_not_enough(monkeypatch):
    """Adversarial review finding (TRDD-RAEGS1D5 room-floor follow-up, self-review round 2):
    `jcl.trim_cards_for_room`'s title-shortening loop can only reclaim room by shrinking titles --
    with zero cards to begin with there is nothing to shrink, so the function's `max(1, ...)`
    correction is the ONLY thing left standing between a starved room and a 0/negative
    `--inject-max-bytes`. `external_clear.compose_handoff_room` is monkeypatched to always report
    a deeply negative room regardless of input -- this isolates that branch itself from whether
    today's real facts/tail formulas can actually drive room that low with zero cards
    (structurally, mostly they cannot -- see `LANE_MIN_INJECT_BYTES`'s own comment in
    `jev_compaction_lane.py`), so this proves the defensive code path is correct on its own terms
    rather than leaving it untested as "unreachable in practice". Round 2 lowered the bump from
    round 1's flat `LANE_MIN_INJECT_BYTES` (800, provably unsafe -- see the companion fixture
    below) to `1`: the smallest positive int, which changes nothing about what `jev_compact.py`
    actually renders at that budget either way (both are below any real skeleton's own baseline),
    so it satisfies "never 0/negative" without ever handing out a budget bigger than
    `compose_handoff`'s real room can use."""
    monkeypatch.setattr(jcl.external_clear, "compose_handoff_room", lambda *a, **k: -99999)
    inputs = ec.HandoffInputs(trigger="jev-compaction", findings=[], cards=[])

    trimmed_inputs, inject_max_bytes = jcl.trim_cards_for_room(
        inputs, now_iso="2026-01-01T00:00:00+0000", tail=[], transcript_path="/tmp/x.jsonl",
        max_bytes=jcl.LANE_INJECTION_MAX_BYTES, source=jcl.SOURCE_JEV,
    )

    assert list(trimmed_inputs.cards) == [], "there was nothing to shrink -- the loop never ran"
    # `1`, not round 1's `LANE_MIN_INJECT_BYTES` (800) -- the never-inflating correction.
    assert inject_max_bytes == 1, inject_max_bytes


def test_natural_value_never_inflated_past_real_room_even_when_titles_are_fully_emptied(
    monkeypatch,
):
    """Coordinator review of commit 44fdec8c, gap 2: round 1's `max(LANE_MIN_INJECT_BYTES,
    inject_max_bytes)` could hand `jev_compact.py` a bigger budget than `compose_handoff`'s own
    room actually has -- if a well-behaved Jev render fills close to that budget,
    `compose_handoff`'s own `room > 400` slice (external_clear.py:941-944) cuts it, the exact
    defect this whole TRDD chain exists to remove, one level down. This fixture (231 in-flight
    cards, long titles) lands the NATURAL, fully-title-emptied room at 656 bytes -- above
    `compose_handoff`'s no-slice threshold (400) but below round 1's flat 800-byte floor -- so it
    reproduces the danger precisely: a companion sized to round 1's flat floor DOES get sliced
    against this room; one sized to what this fix actually returns does not. No hook/subprocess
    plumbing needed -- this exercises `jcl.trim_cards_for_room` and `ec.compose_handoff` directly,
    the same real functions the hook and the detached lane both call."""
    now_iso = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    transcript_path = "/private/tmp/some/fairly/typical/test/path/cleared.jsonl"
    long_title = ("a very long TRDD title describing exactly what this card is about " * 20)[:750]
    cards = [(f"CARD{i:04d}", "dev", long_title) for i in range(231)]
    inputs = ec.HandoffInputs(trigger="jev-compaction", findings=[], cards=cards)

    trimmed_inputs, inject_max_bytes = jcl.trim_cards_for_room(
        inputs, now_iso=now_iso, tail=[], transcript_path=transcript_path,
        max_bytes=jcl.LANE_INJECTION_MAX_BYTES, source=jcl.SOURCE_JEV,
    )

    # Every id AND column survived unchanged (round-2 invariant); titles were emptied because
    # even that wasn't enough to reach the `LANE_MIN_INJECT_BYTES` target.
    assert len(trimmed_inputs.cards) == 231
    assert all(title == "" for _cid, _col, title in trimmed_inputs.cards)
    assert [(cid, col) for cid, col, _title in trimmed_inputs.cards] == [
        (f"CARD{i:04d}", "dev") for i in range(231)
    ]

    # The natural value is positive but below round 1's flat floor -- proves title-shortening
    # alone wasn't enough AND that the returned value was NOT bumped up to 800 anyway.
    assert 0 < inject_max_bytes < jcl.LANE_MIN_INJECT_BYTES, inject_max_bytes

    # The REAL room `compose_handoff` will compute for this exact (trimmed_inputs, tail, max_bytes)
    # -- what a real summary must fit inside to avoid slicing.
    real_room = ec.compose_handoff_room(
        trimmed_inputs, now_iso=now_iso, tail=[], max_bytes=jcl.LANE_INJECTION_MAX_BYTES,
        source=jcl.SOURCE_JEV,
    )
    assert 400 < real_room < jcl.LANE_MIN_INJECT_BYTES, (
        "fixture must land in the exact danger band -- above the no-slice threshold (400) but "
        "below round 1's flat floor (800) -- or it does not reproduce what the coordinator flagged"
    )

    def _summary_of_size(n: int) -> str:
        marker = "/tmp/x"
        head = f"# Compacted context (Jev compaction)\ntranscript: {marker}\n\n## Kept items\n"
        trailer = (
            f'\n\npointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/'
            f'jev_compact.py" expand --transcript {marker} <id>'
        )
        fixed = len(head.encode("utf-8")) + len(trailer.encode("utf-8"))
        return head + ("x" * max(0, n - fixed)) + trailer

    # (a) A companion sized to round 1's flat 800-byte floor -- proves the danger was real: this
    # is EXACTLY what round 1's code would have requested from `jev_compact.py` for this fixture.
    old_round1_summary = _summary_of_size(jcl.LANE_MIN_INJECT_BYTES)
    old_text = ec.compose_handoff(
        trimmed_inputs, now_iso=now_iso, summary=old_round1_summary, source=jcl.SOURCE_JEV,
        tail=[], max_bytes=jcl.LANE_INJECTION_MAX_BYTES,
    )
    assert "_(summary truncated to fit the handoff budget)_" in old_text, (
        "a companion sized to round 1's flat floor must actually get sliced against this real "
        "room, or this fixture does not reproduce the danger the coordinator flagged"
    )

    # (b) A companion sized to what THIS fix actually returns -- must NOT be sliced.
    new_summary = _summary_of_size(inject_max_bytes)
    new_text = ec.compose_handoff(
        trimmed_inputs, now_iso=now_iso, summary=new_summary, source=jcl.SOURCE_JEV,
        tail=[], max_bytes=jcl.LANE_INJECTION_MAX_BYTES,
    )
    assert "_(summary truncated to fit the handoff budget)_" not in new_text
    assert new_summary in new_text


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


# --- Review finding, 2026-09-23: reader/writer pane-key parity ------------------------------


def test_iterm_session_id_prefix_is_stripped_to_match_writer_side_pane_key(tmp_path, monkeypatch):
    """Real-shaped regression test for the janitor#297-adjacent finding: the WRITER
    (`clear_trigger._persist_resume_state`) names the sidecar via `pane_key_from_terminal(
    self_terminal())`, which STRIPS iTerm's `w0t1p0:` window/tab/pane prefix off
    `$ITERM_SESSION_ID` before sanitising. Before this fix the reader used `terminal_pane_key`
    on the RAW env var instead, computing `iterm-w0t1p0-04F9A16F-...` while the writer computed
    `iterm-04F9A16F-...` -- two different filenames, so this hook's sidecar consume was a
    silent no-op on iTerm. This test writes the sidecar under the WRITER's key and sets the
    RAW (unstripped) env var the reader actually sees, exactly as production does."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    raw_session_id = "w0t1p0:04F9A16F-04B3-42A0-9B20-C1E08CFE1D36"
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.setenv("ITERM_SESSION_ID", raw_session_id)

    writer_key = state.pane_key_from_terminal(
        terminal_trigger.self_terminal({"ITERM_SESSION_ID": raw_session_id})
    )
    assert writer_key == "iterm-04F9A16F-04B3-42A0-9B20-C1E08CFE1D36"

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text('{"message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    sd.mkdir(parents=True, exist_ok=True)
    sidecar = sd / f"resume-after-clear.{writer_key}.transcript"
    sidecar.write_text(f"{transcript}\n{int(time.time())}\n", encoding="utf-8")
    _stub_jev_compact(plugin_root, tmp_path / "argv.txt", exit_code=0, out_text=_COMPACTED_DOC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()

    assert rc == 0
    assert "[janitor-handoff] Post-clear handoff, ALREADY IN CONTEXT below" in buf.getvalue(), (
        "the reader must consume the WRITER's own sidecar name, not a differently-sanitised one"
    )
    assert not sidecar.is_file()


def test_tmux_wins_over_iterm_when_both_env_vars_are_set(tmp_path, monkeypatch):
    """`self_terminal` checks tmux BEFORE iTerm (a multiplexer pane is focus-independent) --
    when a session runs tmux inside an iTerm window both vars are set, and the tmux key must
    win on BOTH the writer and the reader side, or the two would disagree exactly as the
    iTerm-prefix bug did."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%5")
    monkeypatch.setenv("ITERM_SESSION_ID", "w0t1p0:04F9A16F-04B3-42A0-9B20-C1E08CFE1D36")

    writer_key = state.pane_key_from_terminal(
        terminal_trigger.self_terminal({"TMUX_PANE": "%5", "ITERM_SESSION_ID": "irrelevant"})
    )
    assert writer_key == "tmux-5", writer_key

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    sd.mkdir(parents=True, exist_ok=True)
    sidecar = sd / f"resume-after-clear.{writer_key}.transcript"
    sidecar.write_text(f"{transcript}\n{int(time.time())}\n", encoding="utf-8")
    _stub_jev_compact(plugin_root, tmp_path / "argv.txt", exit_code=0, out_text=_COMPACTED_DOC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()

    assert rc == 0
    assert "[janitor-handoff] Post-clear handoff, ALREADY IN CONTEXT below" in buf.getvalue()
    assert not sidecar.is_file()


# --- Review finding, 2026-09-23: fast-decline on a fresh "unreachable" probe stamp -----------


def test_declines_fast_on_a_fresh_unreachable_probe_stamp_without_spawning_jev_compact(
    tmp_path, monkeypatch,
):
    """Card 5 content-fit (TRDD-RAEGS1D5, item 4): the fast-decline on a fresh
    `kind="unreachable"` stamp (DNS/TLS/offline, no HTTP response at all) used to live ONLY in
    this hook's own pre-check -- moved into `jev_compact.py compact`'s own decline gate (next
    to `PROBE_FAIL_TTL_S`'s existing `"unavailable"` handling) so `summarize_previous_
    session.py`'s detached lane honours it too, not just this hook. This test therefore runs
    the REAL `jev_compact.py` (not a stub) -- the fast-decline being asserted now lives THERE,
    and a stub standing in for it would only prove this test file agrees with itself."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    # The REAL plugin root, so `run_compact` execs the REAL `jev_compact.py` -- its OWN decline
    # gate is what this test pins, not a hook-side duplicate that no longer exists.
    plugin_root = _PROJECT_ROOT
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%6")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%6"}, transcript=str(transcript))

    import global_state  # noqa: PLC0415

    global_state.control_dir().mkdir(parents=True, exist_ok=True)
    stamp_path = global_state.control_dir() / jcl.PROBE_STAMP_NAME
    stamp_path.write_text(
        json.dumps({"ok": False, "kind": "unreachable", "reason": "DNS failure",
                    "ts": time.time() - 5}),
        encoding="utf-8",
    )

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    assert handoff_files.TEMPLATE_MARKER in out or "does not exist" not in out
    group = handoff_files.newest_group(sd)
    assert group and group[0].read_text(encoding="utf-8").lstrip().startswith(
        handoff_files.TEMPLATE_MARKER
    ), "a declined-unreachable compact must still land a TEMPLATE-marked handoff, never silence"


def test_unresolvable_pane_key_is_logged_not_silent(tmp_path, monkeypatch):
    """Card 5 content-fit (TRDD-RAEGS1D5, item 5): when `self_terminal()` cannot resolve a
    pane (`kind == "unknown"` -- Apple Terminal, plain xterm, or a detection failure), the hook
    used to just `return 0` with no trace anywhere. That is indistinguishable from "nothing to
    do" when it might instead be "detection broke" -- log ONE line naming the kind so the two
    are distinguishable in `jev-post-clear-hook.log`."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    # No TMUX_PANE, no ITERM_SESSION_ID -- `self_terminal()` falls through to
    # `{"kind": "unknown"}`, so `pane_key_from_terminal` returns None.
    monkeypatch.delenv("TMUX_PANE", raising=False)
    monkeypatch.delenv("ITERM_SESSION_ID", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()

    assert rc == 0
    assert buf.getvalue() == ""
    log_path = state.log_dir() / "jev-post-clear-hook.log"
    assert log_path.is_file(), "the unresolvable-pane-key case must leave a trace, not silence"
    log_text = log_path.read_text(encoding="utf-8")
    assert "no pane key" in log_text
    assert "kind='unknown'" in log_text


def test_unreachable_decline_finding_says_unreachable_not_unavailable(tmp_path, monkeypatch):
    """Card 5 two-renderings (TRDD-RAEGS1D5, item 5): `handle_nonzero_exit`'s `EXIT_DECLINED_
    UNAVAILABLE` branch used to say "endpoint unavailable" for EVERY decline reason, including a
    `kind="unreachable"` stamp (no HTTP response ever came back -- offline, DNS, TLS) -- a
    different fact than a real `kind="unavailable"` outage (a 5xx response). The finding text
    must now distinguish them."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=tmp_path / "plugin")
    sd = state.state_dir()
    sd.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(jcl, "read_probe_stamp", lambda: {
        "kind": "unreachable", "reason": "DNS failure", "ts": time.time(),
    })

    import subprocess as _sp

    proc = _sp.CompletedProcess(args=[], returncode=jcl.EXIT_DECLINED_UNAVAILABLE, stdout="", stderr="")

    captured: list[str] = []
    monkeypatch.setattr(jcl, "record_finding", lambda **kw: captured.append(kw["msg"]))

    jcl.handle_nonzero_exit(proc, timed_out=False, sd=sd)

    assert captured, "expected one finding"
    assert "endpoint unreachable" in captured[0]
    assert "endpoint unavailable" not in captured[0]


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


def test_a_model_authored_handoff_before_the_clear_is_named_in_the_injection(tmp_path, monkeypatch):
    """Card 5 injection-caps review (TRDD-RAEGS1D5, chain-hardening §7): a handoff the MODEL
    itself wrote just before a reload-shrink clear (the skill prompts it to, at high context)
    must not go silently unreferenced -- one line names its path, within the same stdout budget
    the Jev summary is already sized to."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%20")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%20"}, transcript=str(transcript))

    key = handoff_files.session_key(str(transcript))
    now = int(time.time())
    model_handoff = handoff_files.write(
        sd, key, "# Handoff\n\nNEXT ACTION: finish the migration before the reload.", now=now,
    )

    argv_log = tmp_path / "argv.txt"
    _stub_jev_compact(plugin_root, argv_log, exit_code=0, out_text=_COMPACTED_DOC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    assert f"Handoff you wrote before the clear: {model_handoff}" in out
    assert len(out.encode("utf-8")) <= 9000, "must stay within the measured stdout ceiling"


def test_no_recent_model_handoff_omits_the_line(tmp_path, monkeypatch):
    """No model-authored handoff on disk for this key -- the pointer line must not appear."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%21")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text("{}\n", encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%21"}, transcript=str(transcript))

    argv_log = tmp_path / "argv.txt"
    _stub_jev_compact(plugin_root, argv_log, exit_code=0, out_text=_COMPACTED_DOC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    assert "Handoff you wrote before the clear:" not in out


def test_other_open_cards_line_reaches_the_injected_stdout(tmp_path, monkeypatch):
    """TRDD-O2FNJ4KW follow-up (review correction 3): the "other open cards" line
    `jcl.state_head_paths` returns must reach the injected stdout the resumed session actually
    reads, under its OWN heading -- not silently dropped by the hook on the way from
    `state_head_paths` to `HandoffInputs`."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%7")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text('{"message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%7"}, transcript=str(transcript))
    _stub_jev_compact(plugin_root, tmp_path / "argv.txt", exit_code=0, out_text=_COMPACTED_DOC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(
        jcl, "state_head_paths",
        lambda root, sd, transcript="": ([], False, [], "other open cards: ZZZZ9999"),
    )

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    assert "## Other open cards" in out
    assert "other open cards: ZZZZ9999" in out


# TRDD-D7RLXAN1: a real two-message transcript and the injected copy the real `jev_compact.py`
# now writes for it -- the exchanges verbatim inside the Jev block, READ FIRST as line one.
_EXCHANGE_TRANSCRIPT = [
    {"type": "user", "uuid": "u1", "message": {"role": "user", "content":
        "please ship it NEWEST-OWNER-MARKER"}},
    {"type": "assistant", "uuid": "a1", "message": {"role": "assistant", "content": [
        {"type": "text", "text": "on it ASSISTANT-REPLY-MARKER"}]}},
]
_EXCHANGE_INJECT_DOC = (
    "READ FIRST: /tmp/full.md holds every message since the last compaction verbatim (2 "
    "messages; 2 shown below). Read it in full before acting; it may take several Reads "
    "(offset/limit).\n# Compacted context (Jev compaction)\nsession: s\n\n"
    "## Newest messages since the last compaction (verbatim, never scored)\n"
    "-- user u1:0 --\nplease ship it NEWEST-OWNER-MARKER\n"
    "-- assistant a1:0 --\non it ASSISTANT-REPLY-MARKER\n\n## Kept items\n\n## Elided\n\n"
    'pointers expand with: uv run --script "$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" '
    "expand --transcript /tmp/x <id>"
)


def test_success_injection_has_no_recent_turns_section_and_each_exchange_once(
    tmp_path, monkeypatch,
):
    """TRDD-D7RLXAN1 test 10: on the Jev success path the newest exchanges arrive verbatim
    inside the Jev block, so the hook must not ALSO inject its "## Recent turns" tail -- a
    whitespace-flattened second copy of the same messages. Each message appears exactly once,
    and READ FIRST opens the Jev block's own text."""
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    plugin_root = tmp_path / "plugin"
    _env(tmp_path, monkeypatch, project_dir=project_dir, plugin_root=plugin_root)
    monkeypatch.setenv("TMUX_PANE", "%31")

    transcript = tmp_path / "cleared.jsonl"
    transcript.write_text(
        "\n".join(json.dumps(r) for r in _EXCHANGE_TRANSCRIPT) + "\n", encoding="utf-8",
    )
    assert ec.recent_messages(str(transcript)), "fixture must give the old tail something to show"
    sd = project_dir / ".janitor" / "state"
    _write_sidecar(sd, {"TMUX_PANE": "%31"}, transcript=str(transcript))
    script = plugin_root / "scripts" / "jev_compact.py"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        _STUB_JEV_COMPACT_TWO_DOCS.format(full_text=_EXCHANGE_INJECT_DOC,
                                          inject_text=_EXCHANGE_INJECT_DOC),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IEXEC)

    mod = _import()
    monkeypatch.setattr(mod, "_payload", lambda: {"source": "clear"})
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd, transcript="": ([], False, [], ""))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    assert "## Recent turns" not in out
    assert out.count("NEWEST-OWNER-MARKER") == 1
    assert out.count("ASSISTANT-REPLY-MARKER") == 1
    jev_block = out.split("## Compacted context (Jev compaction)", 1)[1]
    assert jev_block.index("READ FIRST:") < jev_block.index("-- user u1:0 --")


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
