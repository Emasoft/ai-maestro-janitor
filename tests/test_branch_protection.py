"""Tests for the branch-protection detector.

The detector lives at scripts/detectors/branch-protection.py. It shells out
to `gh` (read-only) to decide whether the default branch is protected. Tests
run it as a subprocess with a FAKE `gh` on PATH (a tiny Python stub) so no
network or real GitHub auth is involved; the stub returns canned
responses+exit-codes driven by GH_* env vars. `git` is the real binary
(only `gh` is stubbed), so the detector's own `git rev-parse --git-dir`
check passes against a `git init`-ed tmp repo.

The canned shapes mirror the real API (verified against a live repo):
  * rulesets  → JSON array of {target, enforcement, ...}; [] when none.
  * protection→ HTTP 404 body {"status":"404"} + non-zero exit when absent;
                exit 0 + a JSON object when classic protection exists.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "branch-protection.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"

# Fake gh: dispatches on argv, prints a canned body, exits a canned code.
# The `/rulesets/<id>` DETAIL endpoint (TRDD-157OH2D7 linear-history check) defaults to rc 99
# (unhandled) so tests that don't set GH_RULESET_DETAIL_* keep the pre-linear-history behavior:
# the detail fetch fails → indeterminate → no linear-history line.
_GH_STUB = '''#!/usr/bin/env python3
import os, re, sys
a = sys.argv[1:]
def out(body, rc):
    if body:
        sys.stdout.write(body)
    raise SystemExit(rc)
if a[:1] == ["auth"]:
    out("", int(os.environ.get("GH_AUTH_RC", "0")))
if a[:2] == ["repo", "view"]:
    out(os.environ.get("GH_REPO_VIEW_JSON", ""), int(os.environ.get("GH_REPO_VIEW_RC", "0")))
if a[:1] == ["api"]:
    t = a[-1]
    if t.endswith("/protection"):
        out(os.environ.get("GH_PROTECTION_BODY", ""), int(os.environ.get("GH_PROTECTION_RC", "0")))
    if re.search(r"/rulesets/\\d+$", t):
        out(os.environ.get("GH_RULESET_DETAIL_BODY", ""), int(os.environ.get("GH_RULESET_DETAIL_RC", "99")))
    if t.endswith("/rulesets"):
        out(os.environ.get("GH_RULESETS_BODY", ""), int(os.environ.get("GH_RULESETS_RC", "0")))
sys.stderr.write("gh-stub: unhandled %r\\n" % (a,))
raise SystemExit(99)
'''

# Default scenario: authed ADMIN, repo o/r default branch main, NO ruleset
# ([]), NO classic protection (genuine 404) → the detector must FIRE.
_DEFAULT_ENV = {
    "GH_AUTH_RC": "0",
    "GH_REPO_VIEW_JSON": json.dumps(
        {"nameWithOwner": "o/r", "defaultBranchRef": {"name": "main"}, "viewerPermission": "ADMIN"}
    ),
    "GH_REPO_VIEW_RC": "0",
    "GH_PROTECTION_BODY": json.dumps({"message": "Branch not protected", "status": "404"}),
    "GH_PROTECTION_RC": "1",
    "GH_RULESETS_BODY": "[]",
    "GH_RULESETS_RC": "0",
}


def _make_repo(tmp_path: Path) -> tuple[Path, Path]:
    """git-init a tmp repo and drop the fake gh into a bin dir; return both."""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    binp = tmp_path / "_bin"
    binp.mkdir()
    gh = binp / "gh"
    gh.write_text(_GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    return tmp_path, binp


def _run(repo: tuple[Path, Path], overrides: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    project_dir, binp = repo
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project_dir)
    env["PATH"] = f"{binp}{os.pathsep}{env['PATH']}"  # fake gh wins; real git/uv still resolve
    env.pop("CLAUDE_PLUGIN_OPTION_BRANCH_PROTECTION_ENABLED", None)
    env.pop("CLAUDE_PLUGIN_OPTION_GITHUB_REPO", None)
    env.update(_DEFAULT_ENV)
    if overrides:
        env.update(overrides)
    return subprocess.run([str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60)


def test_fires_when_unprotected(tmp_path: Path) -> None:
    """No ruleset + 404 classic protection → URGENT drift line."""
    r = _run(_make_repo(tmp_path))
    assert r.returncode == 0, r.stderr
    assert "[branch-protection]" in r.stdout
    assert "URGENT" in r.stdout
    assert "o/r" in r.stdout
    assert "main" in r.stdout


def test_silent_when_ruleset_protected(tmp_path: Path) -> None:
    """An active branch ruleset means protected → silent."""
    r = _run(
        _make_repo(tmp_path),
        {"GH_RULESETS_BODY": json.dumps([{"id": 1, "target": "branch", "enforcement": "active"}])},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_silent_when_classic_protected(tmp_path: Path) -> None:
    """Classic branch protection (HTTP 200) means protected → silent."""
    r = _run(
        _make_repo(tmp_path),
        {"GH_PROTECTION_RC": "0", "GH_PROTECTION_BODY": json.dumps({"url": "x", "required_pull_request_reviews": {}})},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_silent_when_unauthenticated(tmp_path: Path) -> None:
    """gh not authenticated → cannot verify → silent."""
    r = _run(_make_repo(tmp_path), {"GH_AUTH_RC": "1"})
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_silent_when_non_admin(tmp_path: Path) -> None:
    """A non-admin viewer cannot configure protection → silent (no noise)."""
    r = _run(
        _make_repo(tmp_path),
        {"GH_REPO_VIEW_JSON": json.dumps(
            {"nameWithOwner": "o/r", "defaultBranchRef": {"name": "main"}, "viewerPermission": "WRITE"}
        )},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_silent_when_ruleset_probe_indeterminate(tmp_path: Path) -> None:
    """A 403 on the rulesets probe means we cannot confirm → silent (no false alarm)."""
    r = _run(
        _make_repo(tmp_path),
        {"GH_RULESETS_RC": "1", "GH_RULESETS_BODY": json.dumps({"message": "Forbidden", "status": "403"})},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_silent_when_protection_error_not_404(tmp_path: Path) -> None:
    """A 500 (not a genuine 404) on protection is non-definitive → silent."""
    r = _run(
        _make_repo(tmp_path),
        {"GH_PROTECTION_RC": "1", "GH_PROTECTION_BODY": json.dumps({"message": "err", "status": "500"})},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_inactive_ruleset_still_nags(tmp_path: Path) -> None:
    """An 'evaluate'/'disabled' ruleset does not enforce → still unprotected → fires."""
    r = _run(
        _make_repo(tmp_path),
        {"GH_RULESETS_BODY": json.dumps([{"id": 1, "target": "branch", "enforcement": "evaluate"}])},
    )
    assert r.returncode == 0, r.stderr
    assert "[branch-protection]" in r.stdout


def test_empty_permission_surfaces(tmp_path: Path) -> None:
    """An unknown ('') viewer permission errs toward surfacing the gap."""
    r = _run(
        _make_repo(tmp_path),
        {"GH_REPO_VIEW_JSON": json.dumps(
            {"nameWithOwner": "o/r", "defaultBranchRef": {"name": "main"}, "viewerPermission": ""}
        )},
    )
    assert r.returncode == 0, r.stderr
    assert "[branch-protection]" in r.stdout


def test_dedupe_then_rearm(tmp_path: Path) -> None:
    """Fires once, dedupes, then re-arms after protection is added and later removed."""
    repo = _make_repo(tmp_path)
    protected = {"GH_RULESETS_BODY": json.dumps([{"id": 1, "target": "branch", "enforcement": "active"}])}

    assert "[branch-protection]" in _run(repo).stdout          # first: fires
    assert _run(repo).stdout == ""                              # second: deduped
    assert _run(repo, protected).stdout == ""                  # protected: silent + forgets
    assert "[branch-protection]" in _run(repo).stdout          # regression: re-alerts


def test_disabled_env_silent(tmp_path: Path) -> None:
    """Setting BRANCH_PROTECTION_ENABLED=0 silences even an unprotected repo."""
    r = _run(_make_repo(tmp_path), {"CLAUDE_PLUGIN_OPTION_BRANCH_PROTECTION_ENABLED": "0"})
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


# ---- TRDD-157OH2D7: fix-skill hint + linear-history detection --------------

def test_unprotected_line_carries_the_fix_pointer(tmp_path: Path) -> None:
    """The UNPROTECTED line now points at /janitor-github-config-fix and DROPS the old
    'will not change repo settings' anti-suggestion (the root cause the user reported)."""
    r = _run(_make_repo(tmp_path))
    assert "[branch-protection]" in r.stdout and "URGENT" in r.stdout
    assert "/janitor-github-config-fix" in r.stdout
    assert "will not change repo settings" not in r.stdout


def test_linear_history_line_fires_on_protected_repo(tmp_path: Path) -> None:
    """A PROTECTED repo whose active branch ruleset carries required_linear_history → a
    distinct LINEAR HISTORY line (blocks merges) + the fix pointer, and NO UNPROTECTED nag."""
    r = _run(
        _make_repo(tmp_path),
        {
            "GH_RULESETS_BODY": json.dumps([{"id": 1, "target": "branch", "enforcement": "active"}]),
            "GH_RULESET_DETAIL_RC": "0",
            "GH_RULESET_DETAIL_BODY": json.dumps(
                {"id": 1, "name": "baseline-history-protect", "target": "branch",
                 "enforcement": "active",
                 "rules": [{"type": "deletion"}, {"type": "non_fast_forward"},
                           {"type": "required_linear_history"}]}
            ),
        },
    )
    assert r.returncode == 0, r.stderr
    assert "[branch-protection]" in r.stdout
    assert "LINEAR HISTORY" in r.stdout
    assert "/janitor-github-config-fix" in r.stdout
    assert "URGENT" not in r.stdout  # it IS protected — only the linear-history problem


def test_linear_history_line_falsified_without_the_rule(tmp_path: Path) -> None:
    """FALSIFY: same protected repo but the detail has NO required_linear_history → no line."""
    r = _run(
        _make_repo(tmp_path),
        {
            "GH_RULESETS_BODY": json.dumps([{"id": 1, "target": "branch", "enforcement": "active"}]),
            "GH_RULESET_DETAIL_RC": "0",
            "GH_RULESET_DETAIL_BODY": json.dumps(
                {"id": 1, "name": "baseline-history-protect", "target": "branch",
                 "enforcement": "active",
                 "rules": [{"type": "deletion"}, {"type": "non_fast_forward"}]}
            ),
        },
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""  # protected + no linear history → fully silent


def test_non_git_dir_silent(tmp_path: Path) -> None:
    """A non-git directory is skipped before any gh call."""
    binp = tmp_path / "_bin"
    binp.mkdir()
    gh = binp / "gh"
    gh.write_text(_GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)  # NOT a git repo
    env["PATH"] = f"{binp}{os.pathsep}{env['PATH']}"
    env.pop("CLAUDE_PLUGIN_OPTION_BRANCH_PROTECTION_ENABLED", None)
    env.update(_DEFAULT_ENV)
    r = subprocess.run([str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""
