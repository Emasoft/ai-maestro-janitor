"""Tests for scripts/generate_integrity_manifest.py (TRDD-53a00e44, GROUP C / C1).

The generator is thin glue over the already-tested compute_manifest /
write_manifest / verify_manifest helpers (covered in
test_janitor_self_integrity.py). These tests therefore exercise only the
NEW behaviour the generator adds:

  * default mode writes a manifest that verifies CLEAN against the tree it
    was generated from (the release-artifact round-trip),
  * --dry-run computes but writes NOTHING (so `publish.py --dry-run` can
    exercise the generator without dirtying the working tree),
  * the generated manifest never lists itself (so its own presence can't make
    the detector report an `extra` file),
  * --root targets an arbitrary checkout (testability + publish.py passing the
    resolved plugin root),
  * the script resolves the REAL plugin root + globs end-to-end.

The generator is invoked exactly as publish.py invokes it — via
`sys.executable` (it is stdlib-only, so no `uv` is needed) — so these tests
exercise the shipping invocation path, not a bespoke one.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_GEN = _PROJECT_ROOT / "scripts" / "generate_integrity_manifest.py"
_LIB_DIR = _PROJECT_ROOT / "scripts" / "lib"

assert _GEN.is_file(), f"generator not found at {_GEN}"

sys.path.insert(0, str(_LIB_DIR))

from janitor_self_integrity import (  # noqa: E402
    load_manifest,
    verify_manifest,
)

_MANIFEST_REL = Path(".integrity") / "manifest-sha256.json"


def _seed_plugin_tree(root: Path) -> None:
    """Create a minimal plugin tree covering every DEFAULT_MANIFEST_GLOB.

    Mirrors the fixture in test_janitor_self_integrity.py so the two suites
    agree on what a hashable prompt surface looks like.
    """
    (root / "README.md").write_text("# readme\n", encoding="utf-8")
    (root / "CLAUDE.md").write_text("# claude\n", encoding="utf-8")
    skill_dir = root / "skills" / "janitor-foo"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text("# foo skill\n", encoding="utf-8")
    cmd_dir = root / "commands"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "janitor-arm.md").write_text("# arm\n", encoding="utf-8")
    rules_dir = root / "rules"
    rules_dir.mkdir(parents=True)
    (rules_dir / "core.md").write_text("# core rule\n", encoding="utf-8")


def _run_gen(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(_GEN), *args],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_generator_writes_clean_manifest(tmp_path: Path) -> None:
    """Default mode writes a manifest that verifies clean against its tree."""
    _seed_plugin_tree(tmp_path)
    r = _run_gen("--root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    manifest_path = tmp_path / _MANIFEST_REL
    assert manifest_path.is_file(), "generator did not write the manifest"
    mutated, missing, extra = verify_manifest(tmp_path, manifest_path)
    assert mutated == []
    assert missing == []
    assert extra == []


def test_generator_dry_run_writes_nothing(tmp_path: Path) -> None:
    """--dry-run computes + reports but leaves the tree untouched."""
    _seed_plugin_tree(tmp_path)
    r = _run_gen("--dry-run", "--root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    assert not (tmp_path / ".integrity").exists(), "dry-run must write nothing"
    assert "DRY-RUN" in r.stdout
    # 5 globbed files were seeded; the count must be reported.
    assert "5 file hash(es)" in r.stdout


def test_generated_manifest_excludes_itself(tmp_path: Path) -> None:
    """The manifest never lists itself, and its presence creates no `extra`.

    Regression guard for the self-reference trap: if DEFAULT_MANIFEST_GLOBS
    ever matched `.integrity/manifest-sha256.json`, the detector would report
    the manifest as an `extra` file on every clean install.
    """
    _seed_plugin_tree(tmp_path)
    r = _run_gen("--root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    manifest_path = tmp_path / _MANIFEST_REL
    baseline = load_manifest(manifest_path)
    assert _MANIFEST_REL.as_posix() not in baseline
    # Verifying AGAIN, now that the manifest file physically exists, must
    # still be clean — proving the manifest's own presence isn't seen as drift.
    mutated, missing, extra = verify_manifest(tmp_path, manifest_path)
    assert (mutated, missing, extra) == ([], [], [])


def test_generator_hashes_prompt_surface(tmp_path: Path) -> None:
    """Sanity: every prompt-surface kind ends up in the manifest."""
    _seed_plugin_tree(tmp_path)
    r = _run_gen("--root", str(tmp_path))
    assert r.returncode == 0, r.stderr
    baseline = load_manifest(tmp_path / _MANIFEST_REL)
    assert "README.md" in baseline
    assert "CLAUDE.md" in baseline
    assert "skills/janitor-foo/SKILL.md" in baseline
    assert "commands/janitor-arm.md" in baseline
    assert "rules/core.md" in baseline


def test_generator_real_repo_dry_run() -> None:
    """End-to-end: resolve the REAL plugin root + globs without writing.

    No --root → the script auto-resolves its own plugin root. The janitor's
    own tree has many globbed files, so the reported count must be positive.
    Uses --dry-run so the real repo's tree is never mutated by the test.
    """
    r = _run_gen("--dry-run")
    assert r.returncode == 0, r.stderr
    assert "DRY-RUN" in r.stdout
    assert "would write 0 file" not in r.stdout
