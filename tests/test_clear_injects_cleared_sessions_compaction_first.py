"""End to end: after a janitor clear, the NEW session gets the CLEARED session's Jev-compacted
context, and never an older session's handoff body (GitHub #306, TRDD-RAEGS1D5).

Runs BOTH real SessionStart hooks as separate processes, in hooks.json order, against one real
state dir: `on-session-start.py` (which used to inject whichever handoff was newest) and
`on-session-start-post-clear-compact.py` (which composes the cleared transcript's own
compaction). Only `jev_compact.py` is a stub script (it is a network call); everything else is
the shipped code reading and writing real files.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts" / "lib"))

import handoff_files  # noqa: E402

START_HOOK = REPO / "scripts" / "hooks" / "on-session-start.py"
POST_CLEAR_HOOK = REPO / "scripts" / "hooks" / "on-session-start-post-clear-compact.py"

_COMPACTED = "CLEARED-SESSION-COMPACTED-CONTEXT-MARKER"
_OLDER_HANDOFF = "OLDER-SESSION-HANDOFF-BODY-MARKER"

_STUB = f"""#!/usr/bin/env python3
import sys
from pathlib import Path
a = sys.argv
doc = "# Compacted context (Jev compaction)\\n{_COMPACTED}\\n"
for flag in ("--out", "--inject-out"):
    if flag in a:
        Path(a[a.index(flag) + 1]).write_text(doc, encoding="utf-8")
"""


def _run_hooks(tmp_path: Path, *, older_handoff_newer_than_clear: bool) -> tuple[str, str]:
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    (home / ".claude" / "settings.json").write_text(
        json.dumps({"enabledPlugins": {"ai-maestro-janitor" + "@ai-maestro-plugins": True}}),
        encoding="utf-8",
    )
    project = tmp_path / "project"
    project.mkdir()
    sd = project / ".janitor" / "state"
    sd.mkdir(parents=True)

    stub_root = tmp_path / "stub-plugin"
    stub = stub_root / "scripts" / "jev_compact.py"
    stub.parent.mkdir(parents=True)
    stub.write_text(_STUB, encoding="utf-8")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)

    now = int(time.time())
    cleared = tmp_path / "aaaaaaaa-cleared-session.jsonl"
    cleared.write_text('{"message": {"role": "user", "content": "hi"}}\n', encoding="utf-8")
    older = tmp_path / "bbbbbbbb-older-session.jsonl"
    older.write_text("{}\n", encoding="utf-8")
    handoff_files.write(
        sd, handoff_files.session_key(str(older)), f"# Handoff\n\n{_OLDER_HANDOFF}",
        now=now + 5 if older_handoff_newer_than_clear else now - 3600,
    )

    # What `clear_trigger` leaves behind at the verified Enter of an orchestrated clear.
    (sd / "resume-after-clear.flag").write_text("resume your prior task", encoding="utf-8")
    (sd / "resume-after-clear.ts").write_text(str(now), encoding="utf-8")
    (sd / "resume-after-clear.tmux-3.transcript").write_text(
        f"{cleared}\n{now}\n", encoding="utf-8"
    )

    # The suite's sandbox guard denies the real `trddgrep`; a tmp stub that fails makes the
    # hook take its "board unavailable" path, which does not touch what this test pins.
    bindir = tmp_path / "bin"
    bindir.mkdir()
    fake = bindir / "trddgrep"
    fake.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake.chmod(fake.stat().st_mode | stat.S_IEXEC)

    env = {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "HOME": str(home),
        "CLAUDE_PROJECT_DIR": str(project),
        "TMUX_PANE": "%3",
        "JANITOR_GLOBAL_STATE_DIR": str(tmp_path / "global-state"),
        "CLAUDE_PLUGIN_OPTION_DAEMON_ENABLED": "false",
        "CLAUDE_PLUGIN_OPTION_OS_KEEPALIVE_ENABLED": "false",
    }
    payload = json.dumps({"source": "clear", "session_id": "new-sid", "cwd": str(project)})
    outs = []
    for hook, plugin_root in ((START_HOOK, REPO), (POST_CLEAR_HOOK, stub_root)):
        proc = subprocess.run(  # noqa: S603 -- fixed argv, no shell
            [sys.executable, str(hook)], input=payload, capture_output=True, text=True,
            timeout=120, env={**env, "CLAUDE_PLUGIN_ROOT": str(plugin_root)}, cwd=str(project),
        )
        assert "Traceback" not in proc.stderr, proc.stderr[:2000]
        outs.append(proc.stdout)
    return outs[0], outs[1]


def test_clear_injects_the_cleared_sessions_compaction_not_an_older_handoff(tmp_path: Path) -> None:
    """The cleared session's compacted context reaches the new session; an older handoff body does not."""
    start_out, post_out = _run_hooks(tmp_path, older_handoff_newer_than_clear=False)
    assert _COMPACTED in post_out, post_out
    assert _OLDER_HANDOFF not in start_out + post_out


def test_a_newer_foreign_handoff_never_displaces_the_cleared_sessions_compaction(tmp_path: Path) -> None:
    """Even when the older session's handoff is the NEWEST file, only the cleared session's compaction is injected."""
    start_out, post_out = _run_hooks(tmp_path, older_handoff_newer_than_clear=True)
    assert _COMPACTED in post_out, post_out
    assert _OLDER_HANDOFF not in start_out + post_out
