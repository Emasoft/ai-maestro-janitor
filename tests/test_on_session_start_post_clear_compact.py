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

    full_doc = (
        "# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Digest\nTHE-FULL-DIGEST"
        '-MARKER\n\n## Kept items\nsome text\n\npointers expand with: uv run --script '
        '"$CLAUDE_PLUGIN_ROOT/scripts/jev_compact.py" expand --transcript /tmp/x <id>'
    )
    inject_doc = (
        "# Compacted context (Jev compaction)\ntranscript: /tmp/x\n\n## Digest\n\n\n"
        "## Kept items\nsome text\n\nFull compacted context: /tmp/full.md -- Read it for "
        'everything not shown here.\n\npointers expand with: uv run --script '
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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()
    assert rc == 0

    # Independently compute the SAME room the hook must have computed, from the SAME inputs
    # (empty findings/cards -- `state_head_paths` was stubbed to `([], False, [])` above).
    # `now_iso`'s exact clock reading does not matter to the byte count, only its fixed
    # strftime length, so a fresh call here reproduces the same byte total the hook's own
    # (differently-timed) call produced.
    room = ec.compose_handoff_room(
        ec.HandoffInputs(trigger="jev-compaction", findings=[], cards=[]),
        now_iso=time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        tail=ec.recent_messages(str(transcript)),
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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

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
    monkeypatch.setattr(jcl, "state_head_paths", lambda root, sd: ([], False, []))

    import contextlib
    import io

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = mod.main()
    out = buf.getvalue()

    assert rc == 0
    assert "Handoff you wrote before the clear:" not in out


if __name__ == "__main__":
    import pytest

    sys.exit(pytest.main([__file__, "-v"]))
