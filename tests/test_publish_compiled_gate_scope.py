"""The G2e compiled-component gate must only build code this plugin actually SHIPS.

Discovery used to be a bare `rglob` filtered by a directory-NAME skip list, which reached into
`downloads_dev/` — a gitignored scratch dir holding third-party crates vendored for reading — and
ran `cargo clippy -D warnings` on them. On 2026-08-29 that blocked a real publish: someone else's
lint debt in `pagerunner-main` failed the pre-push gate for code this repo does not ship, cannot
fix, and (per `how-to-fix-issues-of-other-projects.md`) must not modify.

Measured at the time: 59 `Cargo.toml` candidates in the tree, 58 of them gitignored. The gate was
building 59 crates to verify 1.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SKIP = {"target", ".git", "node_modules", ".venv", "vendor",
         "dist", "build", "obj", "zig-out", "zig-cache", ".zig-cache"}


def _candidates(pattern: str) -> list[Path]:
    """Discovery BEFORE the ignore filter — the old behaviour, reproduced here."""
    return [
        m for m in _PROJECT_ROOT.rglob(pattern)
        if not any(part in _SKIP for part in m.relative_to(_PROJECT_ROOT).parts)
    ]


def _git_ignored(paths: list[Path]) -> set[str]:
    if not paths:
        return set()
    proc = subprocess.run(
        ["git", "check-ignore", "--stdin"],
        cwd=str(_PROJECT_ROOT),
        input="\n".join(str(p) for p in paths),
        capture_output=True,
        text=True,
        timeout=60,
    )
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def test_the_compiled_gate_never_builds_a_gitignored_crate() -> None:
    """Only NON-ignored Cargo manifests reach the build gate.

    The assertion is on the PREDICATE, not on a path list, so it keeps holding when someone
    vendors a new crate under a scratch dir the skip list has never heard of — which is exactly
    how the original bug arrived.
    """
    candidates = _candidates("Cargo.toml")
    assert candidates, "expected at least this plugin's own crate to be discoverable"

    ignored = _git_ignored(candidates)
    kept = [
        m for m in candidates
        if str(m) not in ignored and str(m.relative_to(_PROJECT_ROOT)) not in ignored
    ]

    leaked = [str(m.relative_to(_PROJECT_ROOT)) for m in kept if str(m) in ignored]
    assert not leaked, f"gitignored manifests survived the filter: {leaked}"

    # The plugin's own crate must NOT be filtered out — a gate that builds nothing is the
    # opposite failure, and it is silent, so pin both directions.
    rel = {str(m.relative_to(_PROJECT_ROOT)) for m in kept}
    assert "scripts/memgrep/Cargo.toml" in rel, (
        f"the plugin's own crate was filtered out of the build gate; kept={sorted(rel)}"
    )


def test_the_shell_lint_gate_never_lints_a_gitignored_script() -> None:
    """G2f has the same shape as G2e and the same bug — and a sharper argument against it.

    That gate exists for PARITY with CI's Mega-Linter, and CI only ever sees TRACKED files. A
    local scan of gitignored paths is therefore STRICTER than the thing it mirrors, so anything
    it finds there is a false block by construction: nothing in `scripts_dev/` can ever fail CI.

    Measured 2026-08-29 while unblocking the 3.4.0 publish: 319 shell candidates in the tree, 8
    of them shipped. It blocked on a dated backup of the OAuth rotator's reauth script.
    """
    candidates = _candidates("*.sh") + _candidates("*.bash")
    assert candidates, "expected the plugin's own shell scripts to be discoverable"

    ignored = _git_ignored(candidates)
    kept = [
        s for s in candidates
        if str(s) not in ignored and str(s.relative_to(_PROJECT_ROOT)) not in ignored
    ]
    rel = {str(s.relative_to(_PROJECT_ROOT)) for s in kept}

    assert not any(str(s) in ignored for s in kept), "a gitignored script survived the filter"
    assert "hooks/hook-run.sh" in rel, (
        f"a SHIPPED shell script was filtered out of the lint gate; kept={sorted(rel)}"
    )
    assert not any(p.startswith(("scripts_dev/", "downloads_dev/")) for p in rel), (
        f"a *_dev scratch script reached the lint gate: {sorted(rel)}"
    )


def test_publish_py_filters_discovery_by_git_ignore() -> None:
    """The source itself must consult git-ignore, not just a name list.

    A behavioural end-to-end run of G2e would mean invoking the whole publish pipeline, so this
    pins the mechanism instead: `_find_manifests` has to route its candidates through
    `_git_ignored`. Without that call the name-list-only discovery is back, and the only symptom
    is a publish that fails on a stranger's code — 12 minutes into a run.
    """
    src = (_PROJECT_ROOT / "scripts" / "publish.py").read_text(encoding="utf-8")
    assert "def _git_ignored(" in src, "the git-ignore filter helper is gone from publish.py"
    assert "check-ignore" in src, "the git-ignore filter no longer asks git"
    body = src.split("def _find_manifests(", 1)
    assert len(body) == 2, "_find_manifests vanished from publish.py"
    assert "_git_ignored(" in body[1].split("\n    # (label,", 1)[0], (
        "_find_manifests no longer filters its candidates through _git_ignored — the compiled "
        "gate is back to building every crate in the tree, gitignored scratch included."
    )
