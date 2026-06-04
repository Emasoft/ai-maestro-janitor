"""Tests for the provenance-audit detector.

The detector at scripts/detectors/provenance-audit.py runs the
Wave-16 provenance / SBOM regex catalogue from
scripts/lib/provenance_patterns.py over every `.github/workflows/*`
file in the project root, plus SLSA-level extraction from a handful
of well-known declaration files, plus the cross-file release / SBOM /
attestation invariants.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "provenance-audit.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


def _run(
    project_dir: Path,
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    # Strip stale janitor envs from the parent process — tests must be
    # deterministic regardless of the developer's local shell config.
    for k in list(env):
        if k.startswith("JANITOR_OPT_") or k.startswith("CLAUDE_PLUGIN_OPTION_"):
            env.pop(k, None)
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60,
    )


def _seed_clean_workflows(project_dir: Path) -> None:
    """Workflow set that follows every provenance rule — no findings."""
    wf = project_dir / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "release.yml").write_text(
        """
name: release
on:
  push:
    tags: ['v*']
permissions:
  id-token: write
  contents: write
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm publish --provenance --access public
      - uses: anchore/sbom-action@v0
      - uses: actions/attest-build-provenance@v1
      - run: sha256sum dist/*.tar.gz > checksums.txt
      - uses: softprops/action-gh-release@v2
""",
        encoding="utf-8",
    )


def _seed_dirty_workflows(project_dir: Path) -> None:
    """Workflow set with multiple provenance failures across rules."""
    wf = project_dir / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "release.yml").write_text(
        """
name: release
on:
  push:
    tags: ['v*']
jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - run: npm install
      - run: npm publish --access public
      - run: gh release download v1.0.0 -R foo/bar
      - run: gh release create v1.0.0 --notes "release"
      - uses: pypa/gh-action-pypi-publish@release/v1
""",
        encoding="utf-8",
    )


# ---------- Silent paths -------------------------------------------------


def test_silent_on_empty_project(tmp_path: Path) -> None:
    """A project with no workflows produces nothing."""
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_on_clean_release_workflow(tmp_path: Path) -> None:
    _seed_clean_workflows(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_on_second_run_unchanged_state(tmp_path: Path) -> None:
    _seed_dirty_workflows(tmp_path)
    first = _run(tmp_path)
    assert "[provenance-audit]" in first.stdout
    second = _run(tmp_path)
    # Same input ⇒ unchanged hash ⇒ silent on second pass.
    assert second.returncode == 0
    assert second.stdout == ""


# ---------- Fires on real findings --------------------------------------


def test_fires_on_dirty_release_workflow(tmp_path: Path) -> None:
    _seed_dirty_workflows(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[provenance-audit]" in r.stdout
    # Several rules should fire — at least cosign, SBOM, and trusted-pub.
    assert "prov-missing-cosign-verify-on-download" in r.stdout
    assert "prov-sbom-absent-but-release-built" in r.stdout


def test_fires_on_slsa_below_floor(tmp_path: Path) -> None:
    """A repo declaring SLSA L1 with default floor (2) must fire."""
    (tmp_path / ".slsa").mkdir()
    (tmp_path / ".slsa" / "level.json").write_text(
        json.dumps({"slsa_level": "1"}), encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[provenance-audit]" in r.stdout
    assert "prov-slsa-level-below-floor" in r.stdout


def test_silent_on_slsa_above_floor(tmp_path: Path) -> None:
    """SLSA L3 with default floor (2) must NOT fire."""
    (tmp_path / ".slsa").mkdir()
    (tmp_path / ".slsa" / "level.json").write_text(
        json.dumps({"slsa_level": "3"}), encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_slsa_floor_env_override(tmp_path: Path) -> None:
    """A repo declaring L2 with floor=3 must fire (gap=1, MAJOR)."""
    (tmp_path / ".slsa").mkdir()
    (tmp_path / ".slsa" / "level.json").write_text(
        json.dumps({"slsa_level": "2"}), encoding="utf-8",
    )
    r = _run(tmp_path, env_overrides={"JANITOR_OPT_SLSA_FLOOR": "3"})
    assert r.returncode == 0
    assert "prov-slsa-level-below-floor" in r.stdout


def test_release_invariant_fires_when_no_sbom_anywhere(tmp_path: Path) -> None:
    """A repo publishes a release but no workflow references any SBOM
    tool — the cross-file invariant fires."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "release.yml").write_text(
        """
jobs:
  release:
    steps:
      - run: cosign attest --predicate p.json $IMAGE
      - run: actions/attest-build-provenance@v1
      - uses: softprops/action-gh-release@v2
""",
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "prov-release-without-sbom-anywhere" in r.stdout


def test_release_invariant_fires_when_no_attestation_anywhere(
    tmp_path: Path,
) -> None:
    """A repo publishes a release with SBOM but no attestation /
    sigstore tool — the second cross-file invariant fires."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    (wf / "release.yml").write_text(
        """
jobs:
  release:
    steps:
      - uses: anchore/sbom-action@v0
      - run: gh release create v1 --notes "x"
""",
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "prov-release-without-attestation-anywhere" in r.stdout


# ---------- Self-scan guard ---------------------------------------------


def test_self_scan_guard_silences_detector(tmp_path: Path) -> None:
    """A project that LOOKS like the janitor (matching plugin.json
    name) must be silenced even when the workflows have findings."""
    plug_dir = tmp_path / ".claude-plugin"
    plug_dir.mkdir()
    (plug_dir / "plugin.json").write_text(
        json.dumps({"name": "ai-maestro-janitor", "version": "0.5.1"}),
        encoding="utf-8",
    )
    _seed_dirty_workflows(tmp_path)
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_self_scan_override_force_enables_scan(tmp_path: Path) -> None:
    """CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1 must override the self-scan guard
    so the official CI can still catch regressions in the janitor's
    own workflows."""
    plug_dir = tmp_path / ".claude-plugin"
    plug_dir.mkdir()
    (plug_dir / "plugin.json").write_text(
        json.dumps({"name": "ai-maestro-janitor", "version": "0.5.1"}),
        encoding="utf-8",
    )
    _seed_dirty_workflows(tmp_path)
    r = _run(tmp_path, env_overrides={"CLAUDE_PLUGIN_ALLOW_SELF_SCAN": "1"})
    assert r.returncode == 0
    assert "[provenance-audit]" in r.stdout


# ---------- Feature flag ------------------------------------------------


def test_disabled_by_env_flag(tmp_path: Path) -> None:
    _seed_dirty_workflows(tmp_path)
    r = _run(
        tmp_path,
        env_overrides={"CLAUDE_PLUGIN_OPTION_PROVENANCE_AUDIT_ENABLED": "0"},
    )
    assert r.returncode == 0
    assert r.stdout == ""


def test_full_mode_surfaces_minor(tmp_path: Path) -> None:
    """In default mode MINOR severities are suppressed; with FULL=1 the
    reproducible-build flag (MINOR) must appear.

    FP-hardening round 3 — the reproducible-build rule only applies
    to workflows that ALSO publish an artefact, so the fixture
    includes a `cargo publish` step alongside the unlocked build.
    """
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    # Only-MINOR workflow: cargo without --locked. Also publishes.
    (wf / "build.yml").write_text(
        """
jobs:
  build:
    steps:
      - run: cargo build --release
      - run: cargo publish
""",
        encoding="utf-8",
    )
    default = _run(tmp_path)
    # Without FULL, the MINOR reproducible-build finding should not
    # surface.
    assert "prov-reproducible-build-flag-absent" not in default.stdout
    # With FULL=1 it does.
    full = _run(
        tmp_path,
        env_overrides={"CLAUDE_PLUGIN_OPTION_PROVENANCE_AUDIT_FULL": "1"},
    )
    assert "prov-reproducible-build-flag-absent" in full.stdout


# ---------- Bounded output ----------------------------------------------


def test_overflow_tail_when_many_findings(tmp_path: Path) -> None:
    """Many findings → only `_MAX_FINDINGS_SHOWN` printed + overflow tail."""
    wf = tmp_path / ".github" / "workflows"
    wf.mkdir(parents=True, exist_ok=True)
    # 8 workflow files each with the same issues → > _MAX_FINDINGS_SHOWN
    for i in range(8):
        (wf / f"w{i}.yml").write_text(
            """
jobs:
  publish:
    steps:
      - run: npm publish --access public
      - uses: pypa/gh-action-pypi-publish@release/v1
""",
            encoding="utf-8",
        )
    r = _run(tmp_path)
    assert "[provenance-audit]" in r.stdout
    # Tail line should appear (the overflow marker).
    assert "more finding" in r.stdout


# ---------- Sanity: detector is executable ------------------------------


def test_detector_is_executable() -> None:
    """The plugin loader expects shebang executables; verify the bit
    is set so the heartbeat won't fail on `permission denied`."""
    mode = _DETECTOR.stat().st_mode
    # Owner-execute bit
    assert mode & 0o100, (
        f"detector missing owner-execute bit (mode {oct(mode)}). "
        "Run `chmod +x scripts/detectors/provenance-audit.py`."
    )
