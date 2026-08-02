"""Tests for the SessionEnd teardown hook (scripts/hooks/on-session-end.py) — TRDD-TL6NL7MK.

Real subprocess runs, no mocks: an isolated $HOME + $CLAUDE_PROJECT_DIR, a JSON
payload on stdin, files on disk. The contract under test:

- EVERY termination stamps `.janitor/state/session-clean-exit.ts` (the breadcrumb
  that lets fleet diagnostics tell a clean exit from a died session).
- A standalone (#N) session ALSO syncs the USER-memory mirror, so a session's own
  memory writes reach the uninstall-safe backup at teardown, not a session later.
- A THIN-harness (#J) session stamps but NEVER writes outside the project.
- stdout stays EMPTY (side-effect only — TRDD-K1RJUYGK's injection-budget rule),
  and garbage stdin / a broken environment still exits 0 (teardown must never
  turn a clean exit into an error exit).
- The resume flags are NEVER cleared — they are the CROSS-SESSION resume
  mechanism the next session's heartbeat consumes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_HOOK = _PROJECT_ROOT / "scripts" / "hooks" / "on-session-end.py"

_DATA_MEM = Path(".claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/memory")
_MIRROR = Path(".claude/ai-maestro-janitor-memory")


def _run(tmp: Path, *, stdin: str = "{}", extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    home = tmp / "home"
    proj = tmp / "proj"
    (proj / ".janitor" / "state").mkdir(parents=True, exist_ok=True)
    home.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ.get("PATH", ""),
        "HOME": str(home),
        "CLAUDE_PROJECT_DIR": str(proj),
    }
    env.update(extra_env or {})
    return subprocess.run(
        [sys.executable, str(_HOOK)],
        input=stdin,
        capture_output=True,
        text=True,
        env=env,
        timeout=30,
    )


def test_stamps_clean_exit_and_syncs_mirror(tmp_path: Path) -> None:
    """Standalone path: the breadcrumb lands AND the seeded USER note reaches the
    uninstall-safe mirror at teardown. stdout must stay empty (side-effect only)."""
    primary = tmp_path / "home" / _DATA_MEM
    primary.mkdir(parents=True)
    (primary / "a-note.md").write_text("---\nname: a-note\n---\nfact\n", encoding="utf-8")

    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout == "", "SessionEnd works by side effect only — no stdout, ever"

    stamp = tmp_path / "proj" / ".janitor" / "state" / "session-clean-exit.ts"
    assert stamp.is_file(), "every termination must stamp the clean-exit breadcrumb"
    assert stamp.read_text().strip().isdigit()

    mirrored = tmp_path / "home" / _MIRROR / "a-note.md"
    assert mirrored.is_file(), "the session's own memory writes must reach the mirror at teardown"


def test_thin_harness_stamps_but_never_writes_outside_the_project(tmp_path: Path) -> None:
    """#J backend: the stamp (project-scoped) lands; the mirror (user-scope write)
    does NOT — the server owns user-scope chores in the harness."""
    primary = tmp_path / "home" / _DATA_MEM
    primary.mkdir(parents=True)
    (primary / "a-note.md").write_text("---\nname: a-note\n---\nfact\n", encoding="utf-8")

    proc = _run(tmp_path, extra_env={"AIMAESTRO_AGENT": "1"})
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "proj" / ".janitor" / "state" / "session-clean-exit.ts").is_file()
    assert not (tmp_path / "home" / _MIRROR).exists(), (
        "a thin-harness session must not write outside the project"
    )


def test_garbage_stdin_still_exits_zero_and_stamps(tmp_path: Path) -> None:
    """Fail-open: the payload is not load-bearing; a malformed one changes nothing."""
    proc = _run(tmp_path, stdin="\x00not json{{{")
    assert proc.returncode == 0, proc.stderr
    assert (tmp_path / "proj" / ".janitor" / "state" / "session-clean-exit.ts").is_file()


def test_resume_flags_survive_teardown(tmp_path: Path) -> None:
    """The flags are PROJECT-scoped cross-session state: the NEXT session's heartbeat
    consumes them and resumes the pending work. Teardown must never clear them."""
    state_dir = tmp_path / "proj" / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "rate-limited.flag").touch()
    (state_dir / "resume-after-compact.flag").touch()

    proc = _run(tmp_path)
    assert proc.returncode == 0, proc.stderr
    assert (state_dir / "rate-limited.flag").is_file(), "resume flag must survive teardown"
    assert (state_dir / "resume-after-compact.flag").is_file(), "resume flag must survive teardown"
