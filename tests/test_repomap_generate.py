"""repomap_generate end-to-end + the ANTI-CORRUPTION contract (TRDD-e247a349).

Real tests, no mocks: each case builds a throwaway git project with source
files and a human-authored CLAUDE.md, runs the actual script (subprocess) or
the imported splice function, and asserts on the real file system.

The contract under test (the user's explicit worry — the janitor must never
corrupt a CLAUDE.md co-owned by the human and the session's Claude):
  - the human narrative outside the fences is preserved BYTE-FOR-BYTE across
    insert / refresh / remove;
  - malformed fences → safe bail, file untouched;
  - a held generator lock → skip, file untouched;
  - a concurrent editor never produces a torn/corrupted file, and the editor's
    latest narrative always survives (lost-update guard);
  - a rolling backup exists before any write;
  - no-change reruns make ZERO writes (AC2), and --check exit codes encode
    fresh/stale/no-block.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "repomap_generate.py"

_NARRATIVE = (
    "# My project\n\n"
    "Human-authored architecture notes the janitor must NEVER touch.\n"
    "- gotcha one\n- gotcha two\n"
)


def _load_module():
    """Import repomap_generate as a module (for the splice-level race tests)."""
    sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
    spec = importlib.util.spec_from_file_location("repomap_generate", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_project(root: Path, *, with_claude_md: bool = True) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "alpha.py").write_text(
        '"""Alpha module — does alpha things."""\n\n'
        "def alpha_fn(x: int) -> int:\n"
        '    """Return x doubled — never negative input."""\n'
        "    return x * 2\n"
    )
    (root / "pkg" / "beta.py").write_text(
        '"""Beta module — does beta things."""\n\n'
        "def beta_fn() -> None:\n"
        '    """Fire the beta path exactly once."""\n'
    )
    if with_claude_md:
        (root / "CLAUDE.md").write_text(_NARRATIVE)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)


def _run(root: Path, *args: str) -> tuple[int, str]:
    res = subprocess.run(
        [sys.executable, str(_SCRIPT), "--root", str(root), *args],
        capture_output=True, text=True, timeout=120,
    )
    return res.returncode, res.stdout + res.stderr


def _narrative_of(text: str) -> str:
    """Everything outside the fenced block (mirrors the script's invariant)."""
    start = text.find("<+-+-JANITOR-REPO-MAP-START-")
    if start < 0:
        return text
    end_marker = "<+-+-JANITOR-REPO-MAP-END-(do-not-modify)-+-+>"
    end = text.find(end_marker) + len(end_marker)
    while end < len(text) and text[end] == "\n":
        end += 1
    return text[:start] + text[end:]


def test_insert_preserves_narrative_and_check_is_fresh():
    """First generate inserts the block; the human narrative survives
    byte-for-byte and --check immediately reports fresh."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        rc, out = _run(root, )
        assert rc == 0 and "wrote" in out, out
        text = (root / "CLAUDE.md").read_text()
        assert text.startswith(_NARRATIVE.rstrip("\n")), "narrative must lead, untouched"
        assert text.count("<+-+-JANITOR-REPO-MAP-START-") == 1
        assert "`pkg/alpha.py`" in text and "alpha_fn" in text
        rc, out = _run(root, "--check")
        assert rc == 0 and "fresh" in out, out


def test_rerun_without_change_makes_zero_writes():
    """AC2: identical structure → 'already current', file untouched (mtime)."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        before = (root / "CLAUDE.md").stat().st_mtime_ns
        time.sleep(0.02)
        rc, out = _run(root)
        assert rc == 0 and "already current" in out, out
        assert (root / "CLAUDE.md").stat().st_mtime_ns == before, "no-op must not rewrite"


def test_check_codes_stale_and_noblock():
    """--check: 2 = no block; 1 = structure changed; 0 again after refresh."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root, "--check")[0] == 2  # no block yet
        assert _run(root)[0] == 0
        # add a public symbol → structure changes
        with open(root / "pkg" / "alpha.py", "a") as f:
            f.write("\ndef gamma_fn() -> None:\n    \"\"\"New public symbol.\"\"\"\n")
        rc, out = _run(root, "--check")
        assert rc == 1 and "STALE" in out, out
        assert _run(root)[0] == 0  # refresh
        assert _run(root, "--check")[0] == 0


def test_comment_only_change_does_not_rewrite():
    """A comment edit moves the digest but not the structure → check says
    refresh optional (exit 0) and generate makes no write."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        with open(root / "pkg" / "beta.py", "a") as f:
            f.write("# trailing comment, no structural change\n")
        rc, out = _run(root, "--check")
        assert rc == 0 and "structure unchanged" in out, out
        rc, out = _run(root)
        assert rc == 0 and "already current" in out, out


def test_remove_restores_narrative_exactly():
    """--remove splices the block out; the narrative is byte-identical."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        rc, out = _run(root, "--remove")
        assert rc == 0 and "removed" in out, out
        after = (root / "CLAUDE.md").read_text()
        assert "JANITOR-REPO-MAP" not in after
        assert after.rstrip("\n") == _NARRATIVE.rstrip("\n")


def test_malformed_fence_bails_without_touching_file():
    """A hand-broken fence pair → exit 3, CLAUDE.md byte-identical."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        path = root / "CLAUDE.md"
        broken = path.read_text().replace(
            "<+-+-JANITOR-REPO-MAP-END-(do-not-modify)-+-+>", "<oops-the-end-fence-is-gone>"
        )
        path.write_text(broken)
        rc, out = _run(root)
        assert rc == 3 and "refusing" in out.lower() or "malformed" in out.lower(), out
        assert path.read_text() == broken, "bail must not modify the file"


def test_held_lock_skips_safely():
    """A held generator flock → exit 3 skip, file untouched."""
    import fcntl
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        lock_dir = root / ".janitor" / "state"
        lock_dir.mkdir(parents=True)
        with open(lock_dir / "repomap.lock", "w") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            before = (root / "CLAUDE.md").read_text()
            rc, out = _run(root)
            assert rc == 3 and "lock" in out, out
            assert (root / "CLAUDE.md").read_text() == before


def test_backup_written_before_write():
    """The rolling pre-write backup carries the PRE-write content."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        bak = root / ".janitor" / "state" / "CLAUDE.md.pre-repomap.bak"
        assert bak.is_file()
        assert bak.read_text() == _NARRATIVE, "backup must be the pre-write CLAUDE.md"


def test_excludes_are_persisted_and_honored():
    """--exclude trims the map AND persists so --check compares the same set."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        (root / "tests").mkdir()
        (root / "tests" / "test_alpha.py").write_text(
            '"""Alpha tests."""\n\ndef test_alpha():\n    pass\n'
        )
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "tests"], cwd=root, check=True)
        assert _run(root, "--exclude", "tests/*")[0] == 0
        text = (root / "CLAUDE.md").read_text()
        assert "test_alpha" not in text, "excluded tree must not appear in the map"
        assert (root / ".janitor" / "state" / "repomap-excludes.txt").read_text() == "tests/*\n"
        # --check (no --exclude flag) must reuse the persisted set → fresh.
        assert _run(root, "--check")[0] == 0


def test_splice_survives_a_writer_caught_between_truncate_and_write():
    """The torn-read race that made the concurrency test flaky (and is real data loss).

    `Path.write_text` — what Claude's Edit tool and most editors do — truncates
    first and writes after. A read landing in that window sees 0 bytes while the
    stat signature stays STABLE (the writer has not written yet), so the collision
    check cannot see it. Splicing that would persist a block-only CLAUDE.md,
    destroying the human narrative the fences exist to protect — and the writer
    would lose its own write too, because our atomic rename swaps the inode out
    from under its open fd.

    The window here (5 ms) is an order of magnitude under the settle delay, so the
    assertion is about correctness, not about winning a timing race.
    """
    mod = _load_module()
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        claude_md = root / "CLAUDE.md"
        block = ("<+-+-JANITOR-REPO-MAP-START-(do-not-modify)-+-+> v1 sha=x digest=y generated=z\n"
                 "body\n<+-+-JANITOR-REPO-MAP-END-(do-not-modify)-+-+>\n")

        def torn_writer() -> None:
            # Truncate, hold the window open, THEN write — the exact shape of a
            # read-modify-write save, slowed down enough to be landed on.
            with open(claude_md, "w", encoding="utf-8") as fh:
                time.sleep(0.005)
                fh.write(_NARRATIVE)

        t = threading.Thread(target=torn_writer)
        t.start()
        time.sleep(0.001)  # land INSIDE the truncate window
        mod.splice_with_verify(claude_md, block, attempts=3)
        t.join()

        final = claude_md.read_text()
        assert _NARRATIVE.strip().splitlines()[0] in final, (
            f"the human narrative was destroyed by a splice over a torn read:\n{final!r}"
        )
        assert final.count("<+-+-JANITOR-REPO-MAP-START-") <= 1, "torn/duplicated fences"


def test_concurrent_editor_never_corrupts_and_their_edit_survives():
    """THE race test (the user's corruption worry): a hostile editor rewrites
    the narrative in a tight loop while splice_with_verify runs repeatedly.
    Invariants asserted on the final file: (a) never torn — at most one intact
    fence pair; (b) the narrative is one of the editor's exact versions (no
    interleaving, no loss to a half-spliced state)."""
    mod = _load_module()
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        claude_md = root / "CLAUDE.md"
        block = "<+-+-JANITOR-REPO-MAP-START-(do-not-modify)-+-+> v1 sha=x digest=y generated=z\nbody\n<+-+-JANITOR-REPO-MAP-END-(do-not-modify)-+-+>\n"

        versions = [f"# Narrative v{i}\n\nhuman text {i}\n" for i in range(40)]
        stop = threading.Event()

        def editor():
            for v in versions:
                if stop.is_set():
                    return
                # the human/Claude path: read-modify-write of the narrative,
                # PRESERVING an existing block (as Claude's Edit tool would)
                current = claude_md.read_text()
                start = current.find("<+-+-JANITOR-REPO-MAP-START-")
                tail = current[start:] if start >= 0 else ""
                claude_md.write_text(v + ("\n" + tail if tail else ""))
                time.sleep(0.001)

        t = threading.Thread(target=editor)
        t.start()
        try:
            for _ in range(30):
                mod.splice_with_verify(claude_md, block, attempts=3)
                time.sleep(0.001)
        finally:
            stop.set()
            t.join()

        final = claude_md.read_text()
        assert final.count("<+-+-JANITOR-REPO-MAP-START-") <= 1, "torn/duplicated fences"
        assert final.count("<+-+-JANITOR-REPO-MAP-END-") == final.count(
            "<+-+-JANITOR-REPO-MAP-START-"
        )
        narrative = _narrative_of(final).rstrip("\n") + "\n"
        valid = {v.rstrip("\n") + "\n" for v in versions} | {_NARRATIVE.rstrip("\n") + "\n"}
        assert narrative in valid, f"narrative corrupted/interleaved:\n{narrative!r}"


def test_detector_nudges_only_when_opted_in_and_stale():
    """project-map-drift: silent without the flag; silent when fresh; ONE
    deduped nudge when the digest moved — and it NEVER modifies CLAUDE.md."""
    detector = _PROJECT_ROOT / "scripts" / "detectors" / "project-map-drift.py"

    def run_detector(root: Path) -> str:
        env = dict(os.environ)
        env["CLAUDE_PROJECT_DIR"] = str(root)
        res = subprocess.run(
            [sys.executable, str(detector)], capture_output=True, text=True,
            timeout=120, env=env, cwd=root,
        )
        assert res.returncode == 0, res.stderr
        return res.stdout

    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0  # insert the map (digest = committed+clean)
        assert run_detector(root) == ""  # no opt-in flag → silent

        flag_dir = root / ".janitor" / "state"
        flag_dir.mkdir(parents=True, exist_ok=True)
        (flag_dir / "repomap-opt-in.flag").write_text("on")
        assert run_detector(root) == ""  # fresh → silent

        (root / "pkg" / "alpha.py").write_text("# changed\n")  # dirty → digest moves
        before = (root / "CLAUDE.md").read_text()
        out = run_detector(root)
        assert "[project-map-drift]" in out and "STALE" in out
        assert (root / "CLAUDE.md").read_text() == before, "detector must never write"
        assert run_detector(root) == ""  # deduped on repeat


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
