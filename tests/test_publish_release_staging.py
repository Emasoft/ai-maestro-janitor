"""Tests for publish.py's release-commit staging — the replacement for `git add -A`.

THE INCIDENT THIS EXISTS FOR (2026-07-28). Step 1 of the pipeline refuses to run
unless `git status --porcelain` is empty, and step 10 commits the version bump about
ten minutes later — the lint, the full pytest suite, the remote CPV validate and the
CI-parity preflight all happen in between. `git add -A` at step 10 therefore swept
whatever appeared during that window into a commit titled "chore: bump version to
X.Y.Z" that nobody reads. It nearly happened: two memory pages edited while the suite
ran were one `git add -A` away from shipping inside a release commit, and an agent
report or a leaked test scratch file would have gone the same way — reports routinely
carry absolute paths and private data.

So the staging list is now ENUMERATED, and anything else that is dirty is a refusal,
not a silent inclusion. These tests build REAL git repositories in tmp_path and run
REAL `git` — no mocks, because the whole behaviour under test is what `git status
--porcelain` prints for renames, untracked files, and quoted paths.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import publish  # noqa: E402


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=True, timeout=30,
    )
    return r.stdout


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A real git repo with a committed baseline of real release artifacts."""
    r = tmp_path / "repo"
    (r / ".claude-plugin").mkdir(parents=True)
    _git(r.parent, "init", "-q", "repo")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    (r / ".claude-plugin" / "plugin.json").write_text('{"version": "1.0.0"}\n', encoding="utf-8")
    (r / "pyproject.toml").write_text('version = "1.0.0"\n', encoding="utf-8")
    (r / "README.md").write_text("badge 1.0.0\n", encoding="utf-8")
    (r / "notes.md").write_text("untouched\n", encoding="utf-8")
    (r / "scripts").mkdir()
    (r / "scripts" / "tool.py").write_text('__version__ = "1.0.0"\n\nX = 1\n', encoding="utf-8")
    _git(r, "add", "-A")
    _git(r, "commit", "-qm", "baseline")
    return r


def test_a_clean_tree_yields_nothing_to_stage_and_nothing_to_refuse(repo: Path) -> None:
    """A clean tree produces two empty lists, so the caller refuses rather than committing."""
    assert publish._release_paths(repo) == ([], [])


def test_bumped_release_artifacts_are_the_staging_list(repo: Path) -> None:
    """The files a version bump legitimately rewrites are the ones staged."""
    (repo / ".claude-plugin" / "plugin.json").write_text('{"version": "1.1.0"}\n', encoding="utf-8")
    (repo / "pyproject.toml").write_text('version = "1.1.0"\n', encoding="utf-8")
    (repo / "README.md").write_text("badge 1.1.0\n", encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("## 1.1.0\n", encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)

    assert unexpected == []
    assert sorted(artifacts) == [
        ".claude-plugin/plugin.json", "CHANGELOG.md", "README.md", "pyproject.toml",
    ]


def test_an_unrelated_edit_made_while_the_suite_ran_is_refused_not_swept(repo: Path) -> None:
    """The regression: a file edited after step 1 must never ride into the release commit."""
    (repo / "pyproject.toml").write_text('version = "1.1.0"\n', encoding="utf-8")
    (repo / "notes.md").write_text("edited while pytest was running\n", encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == ["pyproject.toml"]
    assert unexpected == ["notes.md"]


def test_an_untracked_file_that_appeared_mid_run_is_refused(repo: Path) -> None:
    """A leaked test artifact or an agent report is untracked — and must still block."""
    (repo / "pyproject.toml").write_text('version = "1.1.0"\n', encoding="utf-8")
    (repo / "report-with-absolute-paths.md").write_text("/Users/someone/secret\n", encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == ["pyproject.toml"]
    assert unexpected == ["report-with-absolute-paths.md"]


def test_a_stray_untracked_DIRECTORY_is_expanded_into_the_files_it_holds(repo: Path) -> None:
    """git collapses a wholly-untracked dir to "?? dir/" unless asked for every file.

    That default nearly reintroduced the bug from the other side: a first release writes
    `.integrity/` fresh, git would report the FOLDER, and the manifest — a legitimate
    artifact — would be refused as a stray. The refusal must also name real files, since
    "reports/" tells a human nothing about what almost shipped.
    """
    (repo / "reports").mkdir()
    (repo / "reports" / "audit.md").write_text("/Users/someone/private\n", encoding="utf-8")
    (repo / "reports" / "scan.md").write_text("token=abc\n", encoding="utf-8")

    _artifacts, unexpected = publish._release_paths(repo)

    assert sorted(unexpected) == ["reports/audit.md", "reports/scan.md"]


def test_a_version_only_python_rewrite_is_a_release_artifact(repo: Path) -> None:
    """update_python_versions rewrites __version__ across scripts/ — that IS part of a bump."""
    (repo / "scripts" / "tool.py").write_text('__version__ = "1.1.0"\n\nX = 1\n', encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == ["scripts/tool.py"]
    assert unexpected == []


def test_the_same_python_file_carrying_a_real_code_change_is_refused(repo: Path) -> None:
    """Allowlisting the PATH would have shipped this; checking the DIFF is why it does not."""
    (repo / "scripts" / "tool.py").write_text(
        '__version__ = "1.1.0"\n\nX = 2\n', encoding="utf-8",
    )

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == []
    assert unexpected == ["scripts/tool.py"]


def test_a_renamed_file_is_reported_by_its_new_path(repo: Path) -> None:
    """git prints "old -> new" for a rename; staging the raw string would fail the add."""
    _git(repo, "mv", "notes.md", "renamed-notes.md")

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == []
    assert unexpected == ["renamed-notes.md"]


def test_a_path_with_a_space_is_returned_unquoted(repo: Path) -> None:
    """git quotes such paths in --porcelain; a quoted string would not match the allowlist."""
    (repo / "a file.md").write_text("x\n", encoding="utf-8")

    _artifacts, unexpected = publish._release_paths(repo)

    assert unexpected == ["a file.md"]


def test_every_staged_path_is_one_git_can_actually_add(repo: Path) -> None:
    """End-to-end: the list is fed to a REAL `git add`, proving the paths are usable."""
    (repo / "pyproject.toml").write_text('version = "1.1.0"\n', encoding="utf-8")
    (repo / "CHANGELOG.md").write_text("## 1.1.0\n", encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)
    assert unexpected == []
    _git(repo, "add", "--", *artifacts)

    staged = _git(repo, "diff", "--cached", "--name-only").split()
    assert sorted(staged) == ["CHANGELOG.md", "pyproject.toml"]


def test_a_non_repo_directory_yields_empty_lists_so_the_caller_refuses(tmp_path: Path) -> None:
    """An unreadable status must never degrade into "stage everything"."""
    assert publish._release_paths(tmp_path) == ([], [])


# --- the integrity manifest a release must ship (found stale by three releases) -------


def test_the_integrity_manifest_is_a_release_artifact(repo: Path) -> None:
    """It is regenerated at step 10, so it MUST be in the staging list.

    Left out, the refreshed manifest would sit uncommitted, the release would ship the
    stale one anyway, and the NEXT publish would refuse it as a stray file — the defect
    would come back wearing a different hat.
    """
    assert ".integrity/manifest-sha256.json" in publish._RELEASE_ARTIFACTS

    (repo / ".integrity").mkdir()
    (repo / ".integrity" / "manifest-sha256.json").write_text("{}\n", encoding="utf-8")

    artifacts, unexpected = publish._release_paths(repo)

    assert artifacts == [".integrity/manifest-sha256.json"]
    assert unexpected == []


def test_refreshing_the_manifest_makes_it_agree_with_the_tree(tmp_path: Path) -> None:
    """The contract the stale manifest broke: after a refresh, every hash matches.

    Real generator, real files, real hashes — the point is precisely that the recorded
    digests equal the digests of the shipped bytes, which a mock could not demonstrate.
    """
    import hashlib
    import json
    import shutil

    scripts_src = Path(__file__).resolve().parent.parent / "scripts"
    root = tmp_path / "plugin"
    (root / "scripts" / "lib").mkdir(parents=True)
    (root / "rules").mkdir()
    shutil.copy2(
        scripts_src / "generate_integrity_manifest.py",
        root / "scripts" / "generate_integrity_manifest.py",
    )
    # The generator imports this from its sibling lib/ — a stdlib-only module, so the
    # copy is the whole dependency and the test still exercises the REAL hashing code.
    shutil.copy2(
        scripts_src / "lib" / "janitor_self_integrity.py",
        root / "scripts" / "lib" / "janitor_self_integrity.py",
    )
    (root / "README.md").write_text("# readme\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    (root / "rules" / "a-rule.md").write_text("rule body\n", encoding="utf-8")

    publish._refresh_integrity_manifest(root)

    files = json.loads(
        (root / ".integrity" / "manifest-sha256.json").read_text(encoding="utf-8"),
    )["files"]
    assert set(files) >= {"README.md", "CLAUDE.md", "rules/a-rule.md"}
    for rel, recorded in files.items():
        assert hashlib.sha256((root / rel).read_bytes()).hexdigest() == recorded

    # And a later edit must now be VISIBLE as drift — that is the whole detector.
    (root / "rules" / "a-rule.md").write_text("tampered\n", encoding="utf-8")
    live = hashlib.sha256((root / "rules" / "a-rule.md").read_bytes()).hexdigest()
    assert live != files["rules/a-rule.md"]


def test_a_missing_generator_warns_instead_of_blocking_the_release(tmp_path: Path) -> None:
    """A degraded detector is not worth failing a release over — but it must be audible."""
    root = tmp_path / "plugin"
    (root / "scripts").mkdir(parents=True)

    publish._refresh_integrity_manifest(root)  # must not raise

    assert not (root / ".integrity").exists()


# ── every remote-CPV call is bounded, and by the SAME number ──────────────────
#
# THE INCIDENT (2026-07-30). `stage_validate` carried no explicit timeout, so it
# inherited `run()`'s generic 300 s — sized for a lint invocation. The real run is
# ~237 s on a quiet machine, so the gate passed when idle and failed under load,
# blocking two publishes that were each misread as a transient upstream fault.
# Meanwhile `run_gate` used 600 s for the IDENTICAL command and
# `stage_ci_preflight` used none at all: one behaviour, three numbers, none of
# them stated. These tests pin the invariant rather than any one value — the bug
# was the disagreement, so a future edit that changes the constant is fine and a
# future edit that reintroduces a second number is not.


def _cpv_call_sites() -> list[ast.Call]:
    """Every `subprocess.run`/`run` call in publish.py that invokes remote CPV."""
    tree = ast.parse(Path(publish.__file__).read_text(encoding="utf-8"))
    sites: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.List):
            continue
        literals = [e.value for e in first.elts if isinstance(e, ast.Constant)]
        if "cpv-remote-validate" in literals:
            sites.append(node)
    return sites


def test_every_remote_cpv_call_is_bounded_by_the_shared_constant() -> None:
    """No CPV invocation may inherit a default or invent its own number."""
    sites = _cpv_call_sites()
    # Guard the guard: if the call shape changes and this finds nothing, the test
    # would pass vacuously while enforcing nothing.
    assert len(sites) >= 3, f"expected to find the CPV call sites, found {len(sites)}"

    for call in sites:
        kw = {k.arg: k.value for k in call.keywords}
        assert "timeout" in kw, (
            f"a cpv-remote-validate call at line {call.lineno} has NO timeout — it "
            f"either inherits a cap sized for something else or can hang forever"
        )
        value = kw["timeout"]
        assert isinstance(value, ast.Name) and value.id == "_CPV_TIMEOUT_SEC", (
            f"the cpv-remote-validate call at line {call.lineno} uses a literal or a "
            f"different name instead of _CPV_TIMEOUT_SEC — that is exactly the drift "
            f"that made one command carry three different caps"
        )


def test_cpv_timeout_has_real_headroom_over_the_measured_run() -> None:
    """The cap must exceed the ~237 s measured run by enough to survive load.

    A gate whose cap sits near its own runtime is a coin flip on a busy host, and a
    timeout is indistinguishable from a genuine failure — so it asserts nothing
    about the plugin while still blocking releases.
    """
    measured_seconds = 237
    assert publish._CPV_TIMEOUT_SEC >= measured_seconds * 3, (
        f"_CPV_TIMEOUT_SEC={publish._CPV_TIMEOUT_SEC}s is too close to the measured "
        f"{measured_seconds}s run to survive a loaded machine"
    )


# -- _release_notes_for: the run-12 HTTP 422 fix ---------------------------------
#
# CHANGELOG.md is full-history (git-cliff's `--unreleased` flag was removed on
# purpose). Passing the whole file to `gh release create --notes-file` hit
# GitHub's 125,000-char release-body limit on 2026-08-08 (run 12). These tests
# prove the release body is bounded to the newest section, with a hard cap.


def test_release_notes_extracts_only_the_newest_section(tmp_path: Path) -> None:
    """Only the v2.0.0 section is returned, not the older v1.1.0/v1.0.0 history."""
    changelog = (
        "# Changelog\n\n"
        "## [2.0.0] - 2026-08-08\n\n"
        "### Added\n- feature X\n\n"
        "## [1.1.0] - 2026-07-01\n\n"
        "### Fixed\n- bug Y\n\n"
        "## [1.0.0] - 2026-06-01\n\n"
        "### Added\n- initial release\n"
    )
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    notes = publish._release_notes_for(tmp_path, "2.0.0")
    assert "feature X" in notes
    assert "bug Y" not in notes
    assert "initial release" not in notes


def test_release_notes_falls_back_when_version_heading_is_absent(tmp_path: Path) -> None:
    """A CHANGELOG.md with no matching version heading falls back to the commit log."""
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [1.0.0] - 2026-06-01\n\n- initial release\n", encoding="utf-8",
    )
    _git(tmp_path.parent, "init", "-q", tmp_path.name)
    _git(tmp_path, "config", "user.email", "t@example.invalid")
    _git(tmp_path, "config", "user.name", "t")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "seed commit for fallback log")
    notes = publish._release_notes_for(tmp_path, "9.9.9")
    assert "could not be resolved" in notes
    assert "seed commit for fallback log" in notes


def test_release_notes_are_hard_capped_at_120000_chars(tmp_path: Path) -> None:
    """An oversized matched section is truncated with a marker, never sent whole."""
    oversized_body = "x" * 200_000
    changelog = f"# Changelog\n\n## [3.0.0] - 2026-08-08\n\n{oversized_body}\n\n## [2.0.0]\n\nold\n"
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    notes = publish._release_notes_for(tmp_path, "3.0.0")
    assert len(notes) <= publish._RELEASE_NOTES_MAX_CHARS
    assert "truncated" in notes
    assert "CHANGELOG.md" in notes
