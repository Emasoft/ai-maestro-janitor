"""Tests for the fleet-github-config SURFACE detector (TRDD-157OH2D7).

The detector reads ONLY the daemon's findings JSON (no gh) and emits ONE deduped drift line
+ the fix-skill pointer. Run as a real subprocess (no mocks) with the global-state dir and the
project dir redirected to tmp, so the real machine state is untouched.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_DETECTOR = _PROJECT_ROOT / "scripts" / "detectors" / "fleet-github-config.py"

assert _DETECTOR.is_file(), f"detector not found at {_DETECTOR}"


def _run(
    tmp_path: Path, findings: list[dict] | None, *, disabled: bool = False
) -> subprocess.CompletedProcess[str]:
    gsd = tmp_path / "global-state"
    gsd.mkdir(parents=True, exist_ok=True)
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    if findings is not None:
        (gsd / "github-config-findings.json").write_text(
            json.dumps({"generated_at": 1, "repos_scanned": 13, "findings": findings}),
            encoding="utf-8",
        )
    env = os.environ.copy()
    env["JANITOR_GLOBAL_STATE_DIR"] = str(gsd)
    env["CLAUDE_PROJECT_DIR"] = str(proj)
    env.pop("CLAUDE_PLUGIN_OPTION_FLEET_GITHUB_CONFIG_ENABLED", None)
    if disabled:
        env["CLAUDE_PLUGIN_OPTION_FLEET_GITHUB_CONFIG_ENABLED"] = "0"
    return subprocess.run(
        [str(_DETECTOR)], env=env, capture_output=True, text=True, timeout=60
    )


def test_silent_when_no_findings_file(tmp_path: Path) -> None:
    """Daemon hasn't written a file yet → silent (the common early state)."""
    r = _run(tmp_path, None)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_silent_when_findings_empty(tmp_path: Path) -> None:
    r = _run(tmp_path, [])
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


def test_emits_line_with_fix_pointer(tmp_path: Path) -> None:
    """With findings → one [github-config] line naming counts + the fix skill."""
    r = _run(tmp_path, [
        {"slug": "o/a", "code": "UNPROTECTED", "detail": "d"},
        {"slug": "o/b", "code": "LINEAR_HISTORY", "detail": "d"},
    ])
    assert r.returncode == 0, r.stderr
    assert "[github-config]" in r.stdout
    assert "/janitor-github-config-fix" in r.stdout
    assert "UNPROTECTED" in r.stdout and "linear_history" in r.stdout


def test_deduped_on_second_run(tmp_path: Path) -> None:
    """Same finding set → fires once, silent on repeat (content-hash dedupe)."""
    findings = [{"slug": "o/a", "code": "UNPROTECTED", "detail": "d"}]
    assert "[github-config]" in _run(tmp_path, findings).stdout
    # second run against the SAME tmp (seen-file persists) with the same findings → silent
    r2 = _run(tmp_path, findings)
    assert r2.returncode == 0, r2.stderr
    assert r2.stdout == ""


def test_reemits_when_finding_set_changes(tmp_path: Path) -> None:
    """A changed finding set (a repo fixed / a new gap) shifts the digest → re-alerts."""
    assert "[github-config]" in _run(tmp_path, [{"slug": "o/a", "code": "UNPROTECTED", "detail": "d"}]).stdout
    # different set → new digest → fires again
    r2 = _run(tmp_path, [
        {"slug": "o/a", "code": "UNPROTECTED", "detail": "d"},
        {"slug": "o/b", "code": "LINEAR_HISTORY", "detail": "d"},
    ])
    assert "[github-config]" in r2.stdout


def test_disabled_env_silent(tmp_path: Path) -> None:
    r = _run(tmp_path, [{"slug": "o/a", "code": "UNPROTECTED", "detail": "d"}], disabled=True)
    assert r.returncode == 0, r.stderr
    assert r.stdout == ""


# ---- TRDD-CGYMUKO6: it PROPOSES for this repo, and NEVER for another one ----


def _with_origin(tmp_path: Path, slug: str) -> Path:
    """Give the tmp project a GitHub origin, so the detector can recognise itself in the fleet."""
    proj = tmp_path / "proj"
    proj.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=proj, check=True)
    subprocess.run(
        ["git", "remote", "add", "origin", f"https://github.com/{slug}.git"], cwd=proj, check=True
    )
    return proj


def _proposals(tmp_path: Path) -> list[Path]:
    return sorted((tmp_path / "proj" / "design" / "proposals").glob("TRDD-*.md"))


def test_proposes_a_fix_when_THIS_repo_is_the_drifted_one(tmp_path: Path) -> None:
    """The fleet line only NOTIFIES. For the repo we are actually standing in, the janitor also
    proposes the fix and hands back the one command that authorizes it."""
    _with_origin(tmp_path, "o/a")

    r = _run(tmp_path, [{"slug": "o/a", "code": "UNPROTECTED", "detail": "d"}])

    assert "GHCFG-001" in r.stdout
    assert "/janitor-support-open-ticket TRDD-" in r.stdout
    assert len(_proposals(tmp_path)) == 1


def test_NEVER_writes_a_proposal_about_ANOTHER_repo(tmp_path: Path) -> None:
    """The load-bearing boundary. A proposal TRDD is a file in THIS repo's git-tracked board; one
    describing a DIFFERENT repository would litter a project with work that is not its own. The other
    repos are notified in the summary line and proposed for in their OWN board, when the janitor fires
    there."""
    _with_origin(tmp_path, "o/mine")

    r = _run(tmp_path, [{"slug": "o/someone-else", "code": "UNPROTECTED", "detail": "d"}])

    assert "[github-config]" in r.stdout, "the other repo is still NOTIFIED"
    assert "GHCFG-001" not in r.stdout
    assert _proposals(tmp_path) == [], "no TRDD about a repo we are not in"


def test_a_repo_fixed_while_the_fleet_is_still_dirty_has_its_proposal_WITHDRAWN(tmp_path: Path) -> None:
    """The clear path that the fleet-is-clean check alone would miss: our repo gets fixed while some
    OTHER repo is still broken. Without this, the stale proposal sits on our board forever."""
    _with_origin(tmp_path, "o/mine")
    assert "GHCFG-001" in _run(tmp_path, [{"slug": "o/mine", "code": "UNPROTECTED", "detail": "d"}]).stdout
    assert len(_proposals(tmp_path)) == 1

    _run(tmp_path, [{"slug": "o/other", "code": "UNPROTECTED", "detail": "d"}])

    assert _proposals(tmp_path) == []
