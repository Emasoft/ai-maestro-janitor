"""Tests for the package-manager-policy detector.

The detector lives at scripts/detectors/package-manager-policy.py and is the
detection complement to the pre-tool-pkg-guard PreToolUse hook: the hook
PREVENTS weakening, this detector REPORTS pre-existing gaps. Tests run it
as a subprocess (the dispatch.py invocation surface) with CLAUDE_PROJECT_DIR
pointed at tmp_path so per-project state stays isolated. The install-time
firewall PATH check is steered by prepending a tmp bin dir with stub `sfw`
when we want "firewall installed" coverage.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "package-manager-policy.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


def _run(project_dir: Path, env_overrides: dict[str, str] | None = None,
         with_firewall: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env.pop("CLAUDE_PLUGIN_OPTION_PKG_MANAGER_POLICY_ENABLED", None)
    env.pop("CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES", None)
    if with_firewall:
        # Drop a tmp bin dir with stub `sfw` on PATH so the firewall check passes.
        binp = project_dir / "_bin"
        binp.mkdir(exist_ok=True)
        sfw = binp / "sfw"
        sfw.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        sfw.chmod(0o755)
        env["PATH"] = f"{binp}{os.pathsep}{env['PATH']}"
    else:
        # Empty bin dir prefix to ensure no system-installed sfw/safe-chain
        # leaks into the assertion. We DON'T put sfw/safe-chain on PATH.
        emptyp = project_dir / "_empty_bin"
        emptyp.mkdir(exist_ok=True)
        # Replace PATH to only contain essentials (uv + system) AND not the
        # real sfw location. Keep python tooling reachable.
        keep = []
        for d in env.get("PATH", "").split(os.pathsep):
            if d and "homebrew/bin" not in d:
                keep.append(d)
        env["PATH"] = os.pathsep.join([str(emptyp), *keep])
    if env_overrides:
        env.update(env_overrides)
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60,
    )


def test_silent_on_non_node_project(tmp_path: Path) -> None:
    """A project with no package.json + no JS lockfiles is silent."""
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_fires_on_node_project_with_no_npmrc(tmp_path: Path) -> None:
    """A REAL node project (package.json with installable deps) missing
    .npmrc is flagged. The dependency is what proves the project has an
    install attack surface — see _has_installable_deps."""
    (tmp_path / "package.json").write_text(
        json.dumps({
            "name": "x", "version": "1.0.0",
            "dependencies": {"lodash": "^4.0.0"},
        }), encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[package-manager-policy]" in r.stdout
    assert "no .npmrc" in r.stdout


def test_silent_on_metadata_only_package_json(tmp_path: Path) -> None:
    """A package.json with ZERO installable dependencies (e.g. a Claude skill
    bundle or doc-site config) has no install attack surface — supply-chain
    knobs are irrelevant and the detector must not flag them.

    This is the false-positive shape found on nutlope/hallmark:
    `{name, version, files, skill: {...}, scripts: {...}}` with no deps."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "hallmark", "version": "1.0.0",
        "license": "MIT", "type": "module",
        "files": ["skills"],
        "skill": {"entry": "skills/x/SKILL.md", "harnesses": ["claude-code"]},
        "scripts": {"serve": "python3 -m http.server"},
    }), encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == "", \
        f"metadata-only package.json must not be flagged, got: {r.stdout!r}"


def test_fires_on_dev_dependencies_only(tmp_path: Path) -> None:
    """devDependencies alone are still an install attack surface — flag."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "devDependencies": {"vitest": "^1.0.0"},
    }), encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[package-manager-policy]" in r.stdout


def test_fires_on_workspaces_root(tmp_path: Path) -> None:
    """A monorepo root with no own deps but a `workspaces` list IS a node
    project — sub-packages will run installs against shared hardening."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "mono", "version": "1.0.0",
        "workspaces": ["packages/*"],
    }), encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[package-manager-policy]" in r.stdout


def test_fires_on_lockfile_even_without_deps(tmp_path: Path) -> None:
    """A package.json with no deps BUT a present lockfile is a real node
    project — the lockfile proves installs happened (or are expected)."""
    (tmp_path / "package.json").write_text(
        json.dumps({"name": "x", "version": "1.0.0"}), encoding="utf-8",
    )
    (tmp_path / "package-lock.json").write_text(
        json.dumps({"name": "x", "lockfileVersion": 3, "packages": {}}),
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[package-manager-policy]" in r.stdout


def test_fires_on_malformed_package_json(tmp_path: Path) -> None:
    """Malformed package.json is treated as a real node project (conservative
    fail-safe — we'd rather over-report than miss a real attack surface
    hidden behind a parse error)."""
    (tmp_path / "package.json").write_text("{ not valid json", encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "[package-manager-policy]" in r.stdout


def test_silent_on_workspaces_object_without_packages(tmp_path: Path) -> None:
    """`workspaces: {nohoist: [...]}` without `packages:` is not a monorepo
    root — Yarn syntax for hoist controls only. Must not fire."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "workspaces": {"nohoist": ["**/foo"]},
    }), encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_firewall_recognised_in_project_local_node_modules(tmp_path: Path) -> None:
    """A safe-chain binary inside <root>/node_modules/.bin is sufficient
    proof of the install-time firewall — even if nothing's on global PATH."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "devDependencies": {"@aikidosec/safe-chain": "^1.0.0"},
    }), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=7200\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    bin_dir = tmp_path / "node_modules" / ".bin"
    bin_dir.mkdir(parents=True)
    (bin_dir / "safe-chain").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (bin_dir / "safe-chain").chmod(0o755)
    r = _run(tmp_path)  # NO --with-firewall (no global sfw)
    assert r.returncode == 0
    assert r.stdout == "", \
        f"local node_modules/.bin/safe-chain must satisfy firewall check, got: {r.stdout!r}"


def test_firewall_recognised_via_devDependencies_only(tmp_path: Path) -> None:
    """Listing @aikidosec/safe-chain in devDependencies (without installing
    the binary yet) is acceptance too — some teams use it via `npx`."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "dependencies": {"lodash": "^4.0.0"},
        "devDependencies": {"@aikidosec/safe-chain": "^1.0.0"},
    }), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=7200\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "install-time malware firewall" not in r.stdout


def test_firewall_still_flagged_when_neither_present(tmp_path: Path) -> None:
    """Sanity check: a project with no PATH binary, no node_modules/.bin
    entry, no dependency listing still gets the recommend-install warning."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=7200\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    r = _run(tmp_path)  # no firewall via any path
    assert r.returncode == 0
    assert "install-time malware firewall" in r.stdout


def test_silent_on_empty_dependencies_block(tmp_path: Path) -> None:
    """`dependencies: {}` (empty) → still no install surface. Many lints add
    the empty block as a placeholder; treat it the same as missing."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "dependencies": {},
        "devDependencies": {},
    }), encoding="utf-8")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert r.stdout == ""


def test_silent_on_hardened_node_project(tmp_path: Path) -> None:
    """A fully-hardened pnpm project with sfw on PATH produces zero output.

    The settings live in `pnpm-workspace.yaml` because that is the only file pnpm
    reads them from. This fixture previously put them in `package.json#pnpm` and
    asserted silence — encoding the very false assurance of janitor#148, since
    pnpm ignores that location and the project was NOT hardened at all.
    """
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
    }), encoding="utf-8")
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "minimumReleaseAge: 7200\ntrustPolicy: no-downgrade\nblockExoticSubdeps: true\n",
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    r = _run(tmp_path, with_firewall=True)
    assert r.returncode == 0
    assert r.stdout == ""


# ── janitor#148: the remedy must name the file that actually takes effect ─────
#
# VERIFIED against pnpm 11.11.0, not inferred: a `minimumReleaseAge` written to
# `pnpm-workspace.yaml` shows up in `pnpm config list`; the SAME key written to
# `package.json#pnpm` does not. These run as a PAIR (the shape #130 established)
# so neither can pass by the check simply going quiet.


def test_pnpm_settings_in_package_json_are_flagged_as_misplaced(tmp_path: Path) -> None:
    """Policy keys parked where pnpm ignores them must NOT read as protection.

    This is the false-assurance half: a user who followed our old advice edited
    package.json, watched the finding clear, and believed a release cooldown was
    guarding them against a compromised publish. It was not.
    """
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "pnpm": {"minimumReleaseAge": 7200, "trustPolicy": "no-downgrade",
                 "blockExoticSubdeps": True},
    }), encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    out = _run(tmp_path, with_firewall=True).stdout
    assert "does NOT read settings from package.json" in out
    assert "pnpm-workspace.yaml" in out, "the remedy must name the file that works"


def test_pnpm_block_for_non_policy_keys_is_left_alone(tmp_path: Path) -> None:
    """`package.json#pnpm` is a REAL field — only the POLICY keys are misplaced.

    `overrides` / `packageExtensions` / `patchedDependencies` genuinely live there,
    which is why the near-miss survived review. Flagging the whole block would trade
    one false assurance for a false positive.
    """
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "pnpm": {"overrides": {"lodash": "4.17.21"}, "packageExtensions": {}},
    }), encoding="utf-8")
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "minimumReleaseAge: 7200\ntrustPolicy: no-downgrade\nblockExoticSubdeps: true\n",
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    out = _run(tmp_path, with_firewall=True).stdout
    assert "does NOT read settings from package.json" not in out


def test_redundant_pjson_copies_of_live_workspace_settings_are_not_a_gap(tmp_path: Path) -> None:
    """ai-maestro-plugins#15: keys parked in package.json#pnpm while pnpm-workspace.yaml already
    carries every knob at strength are redundant DUPLICATES of live values — a tidiness matter.
    Raising them fed a proposal whose catalog title asserts a DISABLED safeguard; a human approved
    that false premise on the title alone. A knob reported at its intended value by the file pnpm
    reads is not disabled, whatever other files say."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "pnpm": {"minimumReleaseAge": 7200, "trustPolicy": "no-downgrade",
                 "blockExoticSubdeps": True},
    }), encoding="utf-8")
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "minimumReleaseAge: 7200\ntrustPolicy: no-downgrade\nblockExoticSubdeps: true\n",
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    out = _run(tmp_path, with_firewall=True).stdout
    assert "does NOT read settings from package.json" not in out, (
        "redundant copies of LIVE values must not raise a supply-chain gap"
    )


def test_misplaced_keys_still_flagged_when_the_workspace_file_has_gaps(tmp_path: Path) -> None:
    """The counter-case that keeps the #15 fix honest: with the workspace file WEAK, the misplaced
    copies are genuine context for the fix (the user configured the right values in the wrong
    file) and must keep firing alongside the workspace gap."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
        "pnpm": {"minimumReleaseAge": 7200, "trustPolicy": "no-downgrade",
                 "blockExoticSubdeps": True},
    }), encoding="utf-8")
    (tmp_path / "pnpm-workspace.yaml").write_text(
        "minimumReleaseAge: 60\n",  # present but far below threshold; other knobs absent
        encoding="utf-8",
    )
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    out = _run(tmp_path, with_firewall=True).stdout
    assert "does NOT read settings from package.json" in out
    assert "minimumReleaseAge=60" in out


def test_pnpm_project_missing_workspace_settings_is_flagged_there(tmp_path: Path) -> None:
    """Absence is proposed against the file that enforces it, not package.json."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "version": "1.0.0",
    }), encoding="utf-8")
    (tmp_path / "pnpm-lock.yaml").write_text("", encoding="utf-8")
    out = _run(tmp_path, with_firewall=True).stdout
    assert "pnpm-workspace.yaml lacks pnpm supply-chain settings" in out
    assert "package.json lacks a `pnpm` settings block" not in out


def test_flags_weak_npmrc(tmp_path: Path) -> None:
    """A .npmrc with weak values flags each issue."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=60\ntrust-policy=allow\naudit-level=info\n",
        encoding="utf-8",
    )
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "minimum-release-age=60" in r.stdout
    assert "trust-policy" in r.stdout
    assert "audit-level" in r.stdout


def test_flags_missing_firewall(tmp_path: Path) -> None:
    """A node project with no sfw/safe-chain on PATH is flagged."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=7200\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    r = _run(tmp_path)  # with_firewall=False
    assert r.returncode == 0
    assert "[package-manager-policy]" in r.stdout
    assert "install-time malware firewall" in r.stdout


def test_content_hash_short_circuits(tmp_path: Path) -> None:
    """Second run with unchanged config produces no output (cache hit)."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    first = _run(tmp_path)
    assert "[package-manager-policy]" in first.stdout
    second = _run(tmp_path)
    assert second.returncode == 0
    assert second.stdout == ""


def test_edit_invalidates_cache(tmp_path: Path) -> None:
    """Editing a config file changes the hash → re-emits the current findings."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    assert "[package-manager-policy]" in _run(tmp_path).stdout
    # Editing the file (any byte change that keeps the project a real node
    # project — i.e. deps still present) re-fires. Removing every dep would
    # legitimately silence the detector by turning the project into a
    # metadata-only one; that's the new context-aware behaviour, not a
    # cache bug.
    (tmp_path / "package.json").write_text(
        json.dumps({
            "name": "x", "version": "1.0.0",
            "dependencies": {"lodash": "^4.1.0"},
        }), encoding="utf-8",
    )
    second = _run(tmp_path)
    assert "[package-manager-policy]" in second.stdout


def test_swapping_the_lockfile_invalidates_the_cache(tmp_path: Path) -> None:
    """A yarn→npm migration that leaves package.json untouched MUST re-fire.

    Lockfile presence decides which manager is audited (janitor#130), but it was absent from the
    content hash, so the yarn-era "nothing to say" cache entry survived the migration and the
    repo's now-missing npm knobs were never reported — a false negative created by the very
    change that removed the yarn false positive.
    """
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n", encoding="utf-8")
    first = _run(tmp_path, with_firewall=True)
    assert "no .npmrc" not in first.stdout  # yarn ignores those keys — correctly silent

    (tmp_path / "yarn.lock").unlink()
    (tmp_path / "package-lock.json").write_text("{}\n", encoding="utf-8")

    second = _run(tmp_path, with_firewall=True)
    assert "no .npmrc" in second.stdout, \
        f"npm knobs must be reported after the migration, got: {second.stdout!r}"


def test_two_lockfiles_reported_even_with_a_packageManager_pin(tmp_path: Path) -> None:
    """The pin resolves WHO installs, but two managers' lockfiles is a hazard in its own right —
    reporting it must not depend on the resolver having returned 'ambiguous'."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "packageManager": "yarn@1.22.22",
        "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    (tmp_path / "yarn.lock").write_text("# yarn lockfile v1\n", encoding="utf-8")
    (tmp_path / "package-lock.json").write_text("{}\n", encoding="utf-8")

    r = _run(tmp_path, with_firewall=True)
    assert r.returncode == 0
    assert "Keep one lockfile" in r.stdout


def test_disabled_env_silent(tmp_path: Path) -> None:
    """ENABLED=false silences the detector entirely."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    r = _run(tmp_path, env_overrides={"CLAUDE_PLUGIN_OPTION_PKG_MANAGER_POLICY_ENABLED": "0"})
    assert r.returncode == 0
    assert r.stdout == ""


def test_threshold_override_relaxes_block(tmp_path: Path) -> None:
    """Lowering the threshold knob lets a lower minimum-release-age pass."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=60\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    r = _run(
        tmp_path,
        env_overrides={"CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES": "30"},
        with_firewall=True,
    )
    assert r.returncode == 0
    assert r.stdout == ""  # 60 > 30 → passes


def test_yarnrc_enable_scripts_true_flagged(tmp_path: Path) -> None:
    """.yarnrc.yml enableScripts: true is flagged."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=7200\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    (tmp_path / ".yarnrc.yml").write_text("enableScripts: true\n", encoding="utf-8")
    r = _run(tmp_path, with_firewall=True)
    assert r.returncode == 0
    assert "enableScripts" in r.stdout


def test_bunfig_verify_false_flagged(tmp_path: Path) -> None:
    """bunfig.toml [install].verify=false is flagged."""
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "x", "dependencies": {"lodash": "^4.0.0"},
    }), encoding="utf-8")
    (tmp_path / ".npmrc").write_text(
        "minimum-release-age=7200\ntrust-policy=no-downgrade\nblock-exotic-subdeps=true\n",
        encoding="utf-8",
    )
    (tmp_path / "bunfig.toml").write_text("[install]\nverify = false\n", encoding="utf-8")
    r = _run(tmp_path, with_firewall=True)
    assert r.returncode == 0
    assert "verify=false" in r.stdout
