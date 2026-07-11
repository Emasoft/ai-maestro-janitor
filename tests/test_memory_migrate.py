"""Tests for the memory scope-migration classifier (TRDD-47df698b, Phase 1).

The helper re-scopes a LOCAL memory corpus toward PROJECT scope, conservatively
and privacy-FIRST: a hard privacy gate forces any note carrying machine/user-
private data (local abs path, hostname, PII, credential, high-entropy secret) to
LOCAL-stay regardless of topic; a privacy-clean project-structure note becomes
PROJECT; everything ambiguous defaults LOCAL ("UNSURE → LOCAL").

Real I/O, no mocks: the corpus tests build a tmp memory dir on disk and run the
ACTUAL classifier; the CLI tests run `migrate_memory_scope.py` as a real
subprocess. The privacy gate REUSES the same pattern libraries the
`memory-scope-leak` detector uses (private_path_patterns / privacy_patterns /
cloud_credential_patterns / cicd_secret_leak_patterns + the entropy gate), so the
two never disagree about what leaks — the fixtures below were confirmed against
those live libs, not guessed.
"""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

_LIB = Path(__file__).resolve().parent.parent / "scripts" / "lib"
sys.path.insert(0, str(_LIB))

import memory_migrate as mm  # noqa: E402

CLI = Path(__file__).resolve().parent.parent / "scripts" / "migrate_memory_scope.py"

# Real, lib-confirmed leak fixtures (see the module docstring).
LEAK_HOME_PATH = "The config lives at /Users/alice/Code/secret/config.toml on my box."
LEAK_EMAIL = "Ping susanne.sommers@box.example for the staging key."
CLEAN_ARCH = "# Auth\nThe backend auth module exposes a login endpoint. Architecture: token-based. Convention: one handler per route."
CLEAN_PLAIN = "We retry 3 times then fail."


def _fm(**kv: str) -> str:
    """A minimal `metadata:`-style frontmatter block."""
    lines = ["---", "metadata:"]
    for k, v in kv.items():
        lines.append(f"  {k}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n"


class PrivacyGateTests(unittest.TestCase):
    """The privacy gate is the SINGLE source of 'what leaks' (shared with the
    scope-leak detector). It must catch local paths and PII and pass clean text."""

    def test_local_path_is_a_leak(self) -> None:
        self.assertIn("local-path", mm.privacy_scan(LEAK_HOME_PATH))

    def test_email_is_a_pii_leak(self) -> None:
        self.assertIn("pii:email", mm.privacy_scan(LEAK_EMAIL))

    def test_clean_architecture_text_is_privacy_clean(self) -> None:
        self.assertEqual([], mm.privacy_scan(CLEAN_ARCH))

    def test_plain_fact_is_privacy_clean(self) -> None:
        self.assertEqual([], mm.privacy_scan(CLEAN_PLAIN))


class ClassifyTextTests(unittest.TestCase):
    """The verdict order is load-bearing: privacy FIRST, then topic, then UNSURE."""

    def test_privacy_overrides_a_project_topic(self) -> None:
        # A note that LOOKS like project knowledge (type: project) but carries a
        # local path MUST be forced LOCAL — privacy beats topic.
        text = _fm(type="project") + "# Layout\n" + LEAK_HOME_PATH
        v = mm.classify_text("project_layout.md", text)
        self.assertEqual(mm.LOCAL, v.verdict)
        self.assertEqual(["local-path"], v.leak_classes)
        self.assertIn("privacy", v.reason)

    def test_clean_project_note_goes_to_project(self) -> None:
        text = _fm(type="project", tier="component") + CLEAN_ARCH
        v = mm.classify_text("project_auth.md", text)
        self.assertEqual(mm.PROJECT, v.verdict)
        self.assertEqual([], v.leak_classes)

    def test_hub_tier_alone_signals_project(self) -> None:
        text = _fm(tier="hub") + "The frontend codebase uses a component architecture."
        v = mm.classify_text("frontend_overview.md", text)
        self.assertEqual(mm.PROJECT, v.verdict)

    def test_project_filename_stem_signals_project(self) -> None:
        # No frontmatter type, but a `project_*` stem + a topic word.
        v = mm.classify_text("project_db.md", "The schema lives in the database module.")
        self.assertEqual(mm.PROJECT, v.verdict)

    def test_user_type_stays_local(self) -> None:
        v = mm.classify_text("local_box.md", _fm(type="user") + "My personal aliases.")
        self.assertEqual(mm.LOCAL, v.verdict)
        self.assertIn("about-user", v.reason)

    def test_ambiguous_clean_note_defaults_local(self) -> None:
        v = mm.classify_text("random_thought.md", CLEAN_PLAIN)
        self.assertEqual(mm.LOCAL, v.verdict)
        self.assertIn("unsure", v.reason.lower())


class CorpusWalkTests(unittest.TestCase):
    """iter_notes / classify_corpus must read every real note and skip non-notes
    and the excluded sub-dirs (read-only)."""

    def _corpus(self, root: Path) -> Path:
        memdir = root / "memory"
        memdir.mkdir()
        (memdir / "project_auth.md").write_text(_fm(type="project") + CLEAN_ARCH, encoding="utf-8")
        (memdir / "local_secret.md").write_text(_fm(type="project") + LEAK_HOME_PATH, encoding="utf-8")
        (memdir / "musing.md").write_text(CLEAN_PLAIN, encoding="utf-8")
        # Non-notes that MUST be skipped.
        (memdir / "MEMORY.md").write_text("# index stub\n", encoding="utf-8")
        (memdir / "memory-index.md").write_text("# generated\n", encoding="utf-8")
        # Excluded sub-dirs.
        um = memdir / "user-mem"
        um.mkdir()
        (um / "000001.md").write_text("private user memory\n", encoding="utf-8")
        mg = memdir / ".memgrep"
        mg.mkdir()
        (mg / "stray.md").write_text("cache\n", encoding="utf-8")
        return memdir

    def test_iter_notes_excludes_non_notes_and_subdirs(self) -> None:
        with TemporaryDirectory() as d:
            memdir = self._corpus(Path(d))
            names = {p.name for p in mm.iter_notes(memdir)}
            self.assertEqual({"project_auth.md", "local_secret.md", "musing.md"}, names)
            self.assertNotIn("MEMORY.md", names)
            self.assertNotIn("000001.md", names)
            self.assertNotIn("stray.md", names)

    def test_classify_corpus_verdicts(self) -> None:
        with TemporaryDirectory() as d:
            memdir = self._corpus(Path(d))
            by_path = {v.rel_path: v for v in mm.classify_corpus(memdir)}
            self.assertEqual(mm.PROJECT, by_path["project_auth.md"].verdict)
            # The privacy gate forces the path-leaking note LOCAL even though it is
            # typed project.
            self.assertEqual(mm.LOCAL, by_path["local_secret.md"].verdict)
            self.assertEqual(["local-path"], by_path["local_secret.md"].leak_classes)
            self.assertEqual(mm.LOCAL, by_path["musing.md"].verdict)


class PlanInvariantTests(unittest.TestCase):
    """The plan must enforce the acceptance invariant: ZERO privacy-flagged notes
    in PROJECT, and must never echo a matched secret value."""

    def test_plan_passes_invariant_and_lists_verdicts(self) -> None:
        with TemporaryDirectory() as d:
            memdir = Path(d) / "memory"
            memdir.mkdir()
            (memdir / "project_auth.md").write_text(_fm(type="project") + CLEAN_ARCH, encoding="utf-8")
            (memdir / "leak.md").write_text(LEAK_HOME_PATH, encoding="utf-8")
            verdicts = mm.classify_corpus(memdir)
            plan = mm.render_plan(memdir, verdicts, project_repo="/some/repo")
            self.assertIn("✅ PASS: zero privacy-flagged notes are PROJECT-bound", plan)
            self.assertIn("project_auth.md", plan)
            self.assertIn("leak.md", plan)
            # NEVER echo the matched secret value (the local path) — only the class.
            self.assertNotIn("/Users/alice/Code/secret/config.toml", plan)
            self.assertIn("local-path", plan)


class CliTests(unittest.TestCase):
    """The CLI runs the classifier as a real subprocess, default dry-run, and
    refuses --apply (fail-fast, never a silent no-op)."""

    def _run(self, args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
        env = dict(os.environ)
        return subprocess.run(
            [sys.executable, str(CLI), *args],
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )

    def test_dry_run_writes_plan_and_mutates_nothing(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            memdir = root / "memory"
            memdir.mkdir()
            (memdir / "project_auth.md").write_text(_fm(type="project") + CLEAN_ARCH, encoding="utf-8")
            (memdir / "leak.md").write_text(LEAK_HOME_PATH, encoding="utf-8")
            before = {p: p.read_bytes() for p in memdir.iterdir()}

            proc = self._run([str(memdir), "--project-repo", str(root)], cwd=root)
            self.assertEqual(0, proc.returncode, proc.stderr)
            self.assertIn("classified 2 notes", proc.stdout)
            self.assertIn("1 → PROJECT", proc.stdout)
            self.assertIn("1 privacy-flagged", proc.stdout)

            # The plan was written under reports/migrate-memory-scope/ (gitignored).
            plans = list((root / "reports" / "migrate-memory-scope").glob("*-plan.md"))
            self.assertEqual(1, len(plans))
            # The corpus was not mutated.
            after = {p: p.read_bytes() for p in memdir.iterdir()}
            self.assertEqual(before, after)

    def test_apply_without_a_plan_refuses_loudly(self) -> None:
        """`--apply` used to refuse because it was unbuilt; now it refuses because it is
        driven by a REVIEWED plan. Either way it must never silently no-op — apply is
        publish-and-retire, so a bare invocation with no reviewed artifact is a bug, not
        a default."""
        with TemporaryDirectory() as d:
            root = Path(d)
            memdir = root / "memory"
            memdir.mkdir()
            (memdir / "x.md").write_text(CLEAN_PLAIN, encoding="utf-8")
            proc = self._run([str(memdir), "--project-repo", str(root), "--apply"], cwd=root)
            self.assertEqual(2, proc.returncode)
            self.assertIn("--plan", proc.stderr)
            # And nothing was published.
            self.assertFalse((root / ".claude" / "project" / "memory").exists())

    def test_apply_refuses_against_another_projects_store(self) -> None:
        """End-to-end through the CLI: the cross-project contract holds even when the
        caller passes a real corpus and a real plan — the cwd's repo is not the target."""
        with TemporaryDirectory() as d:
            root = Path(d)
            memdir = root / "memory"
            memdir.mkdir()
            (memdir / "x.md").write_text(CLEAN_PLAIN, encoding="utf-8")
            target = root / "someone-elses-repo"
            target.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=target, check=True)
            here = root / "my-repo"
            here.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=here, check=True)
            plan = root / "plan.md"
            plan.write_text("## → PROJECT\n\n- `x.md` — topic\n", encoding="utf-8")

            proc = self._run(
                [str(memdir), "--project-repo", str(target), "--apply", "--plan", str(plan)],
                cwd=here,
            )

            self.assertEqual(2, proc.returncode)
            self.assertIn("REFUSED", proc.stderr)
            self.assertFalse((target / ".claude" / "project" / "memory").exists())
            self.assertTrue((memdir / "x.md").is_file())  # source untouched

    def test_missing_dir_fails_fast(self) -> None:
        with TemporaryDirectory() as d:
            root = Path(d)
            proc = self._run([str(root / "nope"), "--project-repo", str(root)], cwd=root)
            self.assertEqual(2, proc.returncode)
            self.assertIn("not found", proc.stderr)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# PHASE 2 — the apply. Every test here is about a guard REFUSING and leaving the
# corpus untouched, because apply both PUBLISHES (git-tracked + pushed — you cannot
# un-push a leak) and RETIRES the only existing copy of a human-authored note.
# Real files, real git repos, no mocks.
# ---------------------------------------------------------------------------
def _note(text: str = "a project note about the codebase architecture") -> str:
    return f"---\nname: n\ndescription: d\nmetadata:\n  type: project\n---\n\n{text}\n"


def _corpus(tmp_path: Path, notes: dict[str, str]) -> Path:
    memdir = tmp_path / "local-mem"
    memdir.mkdir(parents=True, exist_ok=True)
    for name, body in notes.items():
        (memdir / name).write_text(body, encoding="utf-8")
    return memdir


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "owning-repo"
    repo.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    return repo


def test_parse_plan_reads_only_the_project_section() -> None:
    """Apply is driven by the plan's PROJECT list — a LOCAL-stay entry must never be
    picked up (that would publish a note the reviewer chose to keep private)."""
    plan = (
        "# plan\n\n## → PROJECT\n\n- `arch.md` — topic\n- `build.md` — topic\n\n"
        "## → LOCAL-stay\n\n- `secrets.md` — privacy: local-path\n"
    )
    assert mm.parse_plan_project_set(plan) == ["arch.md", "build.md"]


def test_apply_refuses_outside_the_owning_repo(tmp_path: Path) -> None:
    """The cross-project contract, enforced in code: a session whose repo is not the
    target repo may not mutate the target's store. There is no bypass flag."""
    repo = _repo(tmp_path)
    other = tmp_path / "some-other-repo"
    other.mkdir()

    with pytest.raises(mm.MigrationRefused, match="cross-project contract"):
        mm.check_ownership(repo, other)


def test_apply_refuses_when_cwd_is_not_in_a_repo(tmp_path: Path) -> None:
    with pytest.raises(mm.MigrationRefused, match="owning project"):
        mm.check_ownership(_repo(tmp_path), None)


def test_apply_refuses_when_a_planned_note_vanished(tmp_path: Path) -> None:
    """The plan is a promise about a corpus. If the corpus moved on, what a human
    reviewed is not what would be applied."""
    memdir = _corpus(tmp_path, {"arch.md": _note()})

    with pytest.raises(mm.MigrationRefused, match="no longer in the corpus"):
        mm.check_plan_matches_corpus(memdir, ["arch.md", "gone.md"])


def test_apply_refuses_when_a_planned_note_now_leaks(tmp_path: Path) -> None:
    """THE guard that matters. A note edited between review and apply must never be
    published on the strength of its stale verdict — PROJECT scope is PUSHED, and a
    leaked local path cannot be un-pushed."""
    memdir = _corpus(tmp_path, {
        "arch.md": _note("the architecture lives at /Users/someone/secret/path/app.py"),
    })

    with pytest.raises(mm.MigrationRefused, match="now scans PRIVATE"):
        mm.check_plan_matches_corpus(memdir, ["arch.md"])


def test_apply_refuses_on_an_empty_plan(tmp_path: Path) -> None:
    memdir = _corpus(tmp_path, {"arch.md": _note()})
    with pytest.raises(mm.MigrationRefused, match="nothing to apply"):
        mm.check_plan_matches_corpus(memdir, [])


def test_apply_refuses_to_overwrite_an_existing_project_note(tmp_path: Path) -> None:
    """A name collision in PROJECT scope is someone else's note. Refuse, don't clobber."""
    memdir = _corpus(tmp_path, {"arch.md": _note()})
    repo = _repo(tmp_path)
    dest = mm.project_memory_root(repo) / "arch.md"
    dest.parent.mkdir(parents=True)
    dest.write_text("SOMEONE ELSE'S NOTE", encoding="utf-8")

    with pytest.raises(mm.MigrationRefused, match="never overwrites"):
        mm.apply_plan(memdir, repo, ["arch.md"], stamp="20260711_000000+0200")

    assert dest.read_text(encoding="utf-8") == "SOMEONE ELSE'S NOTE"
    assert (memdir / "arch.md").is_file()  # source untouched too


def test_apply_publishes_and_retires_the_source_recoverably(tmp_path: Path) -> None:
    """The happy path. The note lands in PROJECT scope byte-identical, and the LOCAL
    original is MOVED to the repo's gitignored .trashcan/ — never deleted, because it is
    human-authored work outside any git repo (RULE 0). Recovery is a single `mv`."""
    body = _note("architecture of the build pipeline")
    memdir = _corpus(tmp_path, {"arch.md": body})
    repo = _repo(tmp_path)

    results = mm.apply_plan(memdir, repo, ["arch.md"], stamp="20260711_000000+0200")

    published = mm.project_memory_root(repo) / "arch.md"
    assert published.read_text(encoding="utf-8") == body     # byte-identical
    assert not (memdir / "arch.md").exists()                  # retired from LOCAL
    retired = repo / ".trashcan" / "migrate-memory-scope" / "20260711_000000+0200" / "arch.md"
    assert retired.read_text(encoding="utf-8") == body        # …but recoverable
    assert results[0][0] == "arch.md"


def test_apply_keep_source_copies_without_retiring(tmp_path: Path) -> None:
    """--keep-source: publish a copy, leave the original in place."""
    body = _note()
    memdir = _corpus(tmp_path, {"arch.md": body})
    repo = _repo(tmp_path)

    mm.apply_plan(memdir, repo, ["arch.md"], stamp="20260711_000000+0200", keep_source=True)

    assert (mm.project_memory_root(repo) / "arch.md").read_text(encoding="utf-8") == body
    assert (memdir / "arch.md").read_text(encoding="utf-8") == body  # still there


def test_a_failed_copy_retires_nothing(tmp_path: Path) -> None:
    """Copy-then-verify-then-retire, in that order: if ANY destination fails, every
    source must still be on disk. A half-migrated corpus is the one outcome that cannot
    be recovered from by hand."""
    memdir = _corpus(tmp_path, {"a.md": _note(), "b.md": _note()})
    repo = _repo(tmp_path)
    # Make the destination un-writable for the SECOND note by planting a directory where
    # its file must go — a real filesystem refusal, not a simulated one.
    (mm.project_memory_root(repo) / "b.md").mkdir(parents=True)

    with pytest.raises((mm.MigrationRefused, OSError)):
        mm.apply_plan(memdir, repo, ["a.md", "b.md"], stamp="20260711_000000+0200")

    assert (memdir / "a.md").is_file()   # nothing was retired
    assert (memdir / "b.md").is_file()
