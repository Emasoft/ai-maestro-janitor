"""Tests for the SessionStart TRDD-STATE reminder hook.

The hook actively surfaces in-progress TRDDs' `## STATE` blocks at session start
(injecting them in full on source=compact, listing them otherwise) so a lossy
compaction summary can never silently replace the authoritative plan. Real I/O,
no mocks: each case builds a temp project tree and runs the hook as a subprocess
with a controlled stdin JSON.
"""

import importlib.util
import json
import os
import subprocess
import sys
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from exe_path import exe

HOOK = Path(__file__).resolve().parent.parent / "scripts" / "hooks" / "on-session-start-trdd-state.py"


def _trdd(status: str, title: str, *, with_state: bool) -> str:
    state = ""
    if with_state:
        state = (
            "## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-05-30\n\n"
            "### NEXT ACTION\nDo the next concrete step here.\n\n"
            "### POST-MORTEM\nWhy this block exists.\n\n"
        )
    return (
        f"---\ntrdd-id: 00000000-0000-0000-0000-000000000000\n"
        f"title: {title}\nstatus: {status}\n"
        f"created: 2026-05-30T10:00:00+0200\nupdated: 2026-05-30T10:00:00+0200\n---\n\n"
        f"# TRDD — {title}\n\n{state}## Problem\nThe body.\n"
    )


def _run(cwd: Path, source: str) -> str:
    payload = json.dumps({"source": source, "cwd": str(cwd), "hook_event_name": "SessionStart"})
    res = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload, capture_output=True, text=True, timeout=30,
    )
    return res.stdout


def _load_module():
    spec = importlib.util.spec_from_file_location("trdd_state_hook", HOOK)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _card(column: str, updated: str, title: str) -> str:
    return f"---\ntitle: {title}\ncolumn: {column}\nupdated: {updated}\n---\n\n# {title}\n"


def _git(*args: str) -> None:
    """Run a real git command with a throwaway identity (no global config, no signing, no hooks)."""
    subprocess.run(
        [exe("git"), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null", *args],
        check=True, capture_output=True, text=True, timeout=30,
    )


def _main_and_linked_worktree(tmp: str) -> tuple[Path, Path]:
    """A real repo with one commit and a real linked worktree of it, both inside tmp."""
    main = Path(tmp) / "main"
    main.mkdir()
    _git("-C", str(main), "init", "-q")
    _git("-C", str(main), "commit", "-q", "--allow-empty", "-m", "init")
    wt = Path(tmp) / "wt"
    _git("-C", str(main), "worktree", "add", "-q", str(wt), "-b", "wt-branch")
    return main, wt
class TestTrddStateHook(unittest.TestCase):
    def _project(self, tmp: str) -> Path:
        d = Path(tmp) / "design" / "tasks"
        d.mkdir(parents=True)
        return Path(tmp)

    def _write_handoff(self, root: Path, *, age_s: int = 0) -> Path:
        """Create a precompact-handoff.md under the temp project, optionally aged."""
        sd = root / ".janitor" / "state"
        sd.mkdir(parents=True, exist_ok=True)
        p = sd / "precompact-handoff.md"
        p.write_text("# PreCompact ground-truth handoff\n(test fixture)\n")
        if age_s:
            past = time.time() - age_s
            os.utime(p, (past, past))
        return p

    def test_compact_injects_state_block(self):
        """On source=compact WITHOUT a fresh handoff, the full STATE block is injected."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-aaaaaaaa-x.md").write_text(
                _trdd("in-progress", "Active thing", with_state=True))
            out = _run(root, "compact")
            self.assertIn("COMPACTION just occurred", out)
            self.assertIn("### NEXT ACTION", out)
            self.assertIn("### POST-MORTEM", out)
            self.assertIn("SUPERSEDE", out)

    def test_compact_with_fresh_handoff_injects_digest_only(self):
        """On source=compact WITH a fresh handoff, only a pointer + digest is injected.

        The handoff already carries the STATE blocks verbatim — injecting them again
        doubled the post-compact context (TRDD-498LEWZ4)."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-aaaaaaaa-x.md").write_text(
                _trdd("in-progress", "Active thing", with_state=True))
            self._write_handoff(root)
            out = _run(root, "compact")
            self.assertIn("COMPACTION just occurred", out)          # the warning survives
            self.assertIn("precompact-handoff.md", out)             # the pointer
            self.assertIn("TRDD-20260530_100000+0200-aaaaaaaa-x.md", out)  # the digest line
            self.assertNotIn("### POST-MORTEM", out)                # STATE body NOT duplicated
            self.assertNotIn("### NEXT ACTION", out)

    def test_compact_with_stale_handoff_falls_back_to_full_injection(self):
        """A handoff older than the freshness window is a PREVIOUS compaction's — the
        hook must not point at outdated truth, so it falls back to full injection."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-aaaaaaaa-x.md").write_text(
                _trdd("in-progress", "Active thing", with_state=True))
            self._write_handoff(root, age_s=2 * 3600)
            out = _run(root, "compact")
            self.assertIn("### POST-MORTEM", out)                   # full STATE injected
            self.assertIn("SUPERSEDE", out)

    def test_fresh_handoff_does_not_change_startup_listing(self):
        """A fresh handoff must not alter the non-compact sources — startup still lists."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-aaaaaaaa-x.md").write_text(
                _trdd("in-progress", "Active thing", with_state=True))
            self._write_handoff(root)
            out = _run(root, "startup")
            self.assertIn("in-progress TRDD(s)", out)
            self.assertNotIn("precompact-handoff.md", out)          # pointer is compact-only
            self.assertNotIn("### POST-MORTEM", out)

    def test_completed_trdd_is_ignored(self):
        """A completed TRDD is never surfaced — only in-progress ones."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-bbbbbbbb-done.md").write_text(
                _trdd("completed", "Finished thing", with_state=True))
            out = _run(root, "compact")
            self.assertEqual(out.strip(), "")

    def test_resume_lists_without_injecting_body(self):
        """On source=resume, the hook LISTS the TRDD (path) but does not inject the STATE body."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-cccccccc-y.md").write_text(
                _trdd("in-progress", "Active thing", with_state=True))
            out = _run(root, "resume")
            self.assertIn("in-progress TRDD(s)", out)
            self.assertIn("has ## STATE block", out)
            self.assertNotIn("### POST-MORTEM", out)  # body NOT injected on resume

    def test_no_design_tasks_is_silent(self):
        """A project without design/tasks/ produces no output."""
        with TemporaryDirectory() as tmp:
            out = _run(Path(tmp), "compact")
            self.assertEqual(out.strip(), "")

    def test_no_in_progress_is_silent(self):
        """A project whose only TRDD is terminal produces no output."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-dddddddd-z.md").write_text(
                _trdd("superseded", "Old thing", with_state=False))
            out = _run(root, "startup")
            self.assertEqual(out.strip(), "")

    def test_missing_state_block_flagged_on_compact(self):
        """An in-progress TRDD with no STATE block is surfaced with a read-the-file note."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-eeeeeeee-w.md").write_text(
                _trdd("in-progress", "Stateless thing", with_state=False))
            out = _run(root, "compact")
            self.assertIn("no ## STATE block", out)

    def test_human_review_card_is_not_an_active_trdd(self):
        """A card in human_review is not reported as active; a dev card on the same board still is (TRDD-4K7V0GFW, issue 365)."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            (root / "design/tasks/TRDD-20260530_100000+0200-hhhhhhhh-waiting.md").write_text(
                "---\ntitle: Waiting for the owner\ncolumn: human_review\n"
                "updated: 2026-05-30T10:00:00+0200\n---\n\n# waiting\n")
            (root / "design/tasks/TRDD-20260530_100000+0200-iiiiiiii-working.md").write_text(
                "---\ntitle: Being worked\ncolumn: dev\n"
                "updated: 2026-05-30T10:00:00+0200\n---\n\n# working\n")
            out = _run(root, "resume")
            self.assertIn("iiiiiiii-working.md", out)
            self.assertNotIn("hhhhhhhh-waiting.md", out)

    def test_board_root_is_the_git_toplevel_of_the_payload_cwd_not_the_env_dir(self):
        """cwd = a subfolder of a linked worktree, CLAUDE_PROJECT_DIR = the main checkout: the hook reads the
        WORKTREE board (TRDD-4K7V0GFW, issue 365). Without the toplevel resolution the subfolder has no design/."""
        with TemporaryDirectory() as tmp:
            main, wt = _main_and_linked_worktree(tmp)
            (main / "design/tasks").mkdir(parents=True)
            (wt / "design/tasks").mkdir(parents=True)
            (wt / "sub").mkdir()
            (main / "design/tasks/TRDD-20260530_100000+0200-mmmmmmmm-main.md").write_text(
                _card("dev", "2026-05-30T10:00:00+0200", "Main checkout card"))
            (wt / "design/tasks/TRDD-20260530_100000+0200-wwwwwwww-wt.md").write_text(
                _card("dev", "2026-05-30T10:00:00+0200", "Worktree card"))
            payload = json.dumps({"source": "resume", "cwd": str(wt / "sub"), "hook_event_name": "SessionStart"})
            env = dict(os.environ, CLAUDE_PROJECT_DIR=str(main))
            res = subprocess.run([sys.executable, str(HOOK)], input=payload, capture_output=True,
                                 text=True, timeout=30, env=env)
            self.assertIn("wwwwwwww-wt.md", res.stdout)
            self.assertNotIn("mmmmmmmm-main.md", res.stdout)

    def test_more_than_max_active_cards_keeps_the_newest_by_updated_instant(self):
        """With more active cards than MAX_TRDDS, the newest `updated:` instants are kept, newest first, even when
        the newest card sorts last by filename and mixed offsets make text order disagree (TRDD-4K7V0GFW, issue 365)."""
        with TemporaryDirectory() as tmp:
            root = self._project(tmp)
            stamps = {
                "aaaaaaaa": "2026-05-01T10:00:00+0200",
                "bbbbbbbb": "2026-05-02T10:00:00+0200",
                "cccccccc": "2026-05-03T10:00:00+0200",
                "dddddddd": "2026-05-30T10:30:00+0100",  # 09:30Z: the later instant, though its text sorts lower
                "eeeeeeee": "2026-05-30T11:00:00+0200",  # 09:00Z
                "ffffffff": "2026-06-01T10:00:00+0200",  # newest of all, last by filename
            }
            for uid, stamp in stamps.items():
                (root / f"design/tasks/TRDD-20260530_100000+0200-{uid}-x.md").write_text(
                    _card("dev", stamp, f"Card {uid}"))
            out = _run(root, "resume")
            for kept in ("ffffffff", "dddddddd", "eeeeeeee", "cccccccc"):
                self.assertIn(f"{kept}-x.md", out)
            for dropped in ("aaaaaaaa", "bbbbbbbb"):
                self.assertNotIn(f"{dropped}-x.md", out)
            order = [out.index(f"{uid}-x.md") for uid in ("ffffffff", "dddddddd", "eeeeeeee", "cccccccc")]
            self.assertEqual(order, sorted(order), "newest updated first")
    def test_failing_toplevel_probe_fails_open_to_the_raw_payload_cwd(self):
        """The hook runs from a copy whose lib/ has no exe_path (a real ImportError inside the toplevel probe): it
        must still exit 0 and read the board of the raw payload cwd, with a stderr notice (TRDD-4K7V0GFW)."""
        with TemporaryDirectory() as tmp:
            hooks = Path(tmp) / "plugin" / "scripts" / "hooks"
            hooks.mkdir(parents=True)
            (Path(tmp) / "plugin" / "scripts" / "lib").mkdir()  # namespace package without exe_path
            hook = hooks / HOOK.name
            hook.write_text(HOOK.read_text(encoding="utf-8"), encoding="utf-8")
            root = Path(tmp) / "proj"
            (root / "design/tasks").mkdir(parents=True)
            (root / "design/tasks/TRDD-20260530_100000+0200-ffffffff-x.md").write_text(
                _card("dev", "2026-05-30T10:00:00+0200", "Raw cwd card"))
            env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PLUGIN_ROOT"}
            payload = json.dumps({"source": "resume", "cwd": str(root), "hook_event_name": "SessionStart"})
            res = subprocess.run([sys.executable, str(hook)], input=payload, capture_output=True,
                                 text=True, timeout=30, env=env)
            self.assertEqual(res.returncode, 0, res.stderr)
            self.assertIn("ffffffff-x.md", res.stdout)
            self.assertIn("git toplevel probe failed", res.stderr)
    def test_state_block_extraction_unit(self):
        """_state_block returns the section from the STATE heading to the next H2."""
        mod = _load_module()
        text = _trdd("in-progress", "T", with_state=True)
        block = mod._state_block(text)
        self.assertIsNotNone(block)
        self.assertTrue(block.startswith("## ⏵ STATE"))
        self.assertIn("### POST-MORTEM", block)
        self.assertNotIn("## Problem", block)  # stops at the next H2


if __name__ == "__main__":
    unittest.main()
