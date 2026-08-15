"""The git fact `scripts/memgrep/build.rs` got wrong, pinned as an executable claim (TRDD-9XMPS8OZ).

`build.rs` embeds the build's commit sha into `memgrep --version` so a stale `cargo install`
"is visible in --version output instead of silent" (janitor#164). It told cargo to re-run it
whenever `<git-dir>/HEAD` changed. On a branch, `HEAD` holds the constant text
`ref: refs/heads/<branch>` and **a commit never writes it** — git writes the RESOLVED ref. So
cargo saw an unchanged input, never re-ran the script, and every binary from that checkout kept
reporting the commit that was HEAD the first time the crate was ever built there. Measured on
this host 2026-08-16: the binary contained code committed 2026-08-14 while `--version` said
`a685cca, 2026-08-07`.

The mechanism built to expose a stale binary was itself frozen, and — worse than silence — it
answered confidently. This file pins the underlying git behaviour, because that is the fact the
original code assumed wrongly and the fact any future rewrite of the watch list must respect. It
costs one temp repo and no build.
"""

from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_BUILD_RS = _ROOT / "scripts" / "memgrep" / "build.rs"

# An arbitrary fixed past instant. Backdating both files to the SAME value before the commit is
# what makes the assertion deterministic: no sleeps, and no dependence on filesystem timestamp
# granularity, which on a fast machine can make two genuinely-different writes compare equal.
_BACKDATED = 1_000_000_000


def _git(repo: Path, *args: str) -> str:
    """Run git in `repo` with the user's real config neutralised.

    `GIT_CONFIG_GLOBAL=/dev/null` matters: a developer's `~/.gitconfig` can set
    `init.defaultBranch`, hooks, or a signing key, any of which would change what this test
    observes or make `commit` fail for reasons that have nothing to do with the claim.
    """
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@example.invalid",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@example.invalid",
    }
    out = subprocess.run(
        ["git", *args], cwd=repo, env=env, capture_output=True, text=True, check=True
    )
    return out.stdout.strip()


def _repo_with_one_commit(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    repo.mkdir()
    _git(repo, "-c", "init.defaultBranch=main", "init", "-q")
    (repo / "a.txt").write_text("1\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "one")
    return repo


def test_a_commit_does_not_touch_git_HEAD_but_does_touch_the_resolved_ref(tmp_path) -> None:
    """The exact premise build.rs violated: on a branch, committing moves `refs/heads/<b>` and
    leaves `HEAD` alone — so watching only `HEAD` watches a file that never changes."""
    repo = _repo_with_one_commit(tmp_path)
    git_dir = Path(_git(repo, "rev-parse", "--absolute-git-dir"))
    refname = _git(repo, "symbolic-ref", "-q", "HEAD")
    assert refname == "refs/heads/main"

    head_file = git_dir / "HEAD"
    ref_file = Path(_git(repo, "rev-parse", "--git-path", refname))
    if not ref_file.is_absolute():
        # `--git-path` answers relative to the CWD it was run in — the same trap build.rs's
        # `absolutize()` exists for. Resolve it the same way rather than assuming a shape.
        ref_file = (repo / ref_file).resolve()
    assert ref_file.is_file(), "the first commit must have written a loose ref"

    for f in (head_file, ref_file):
        os.utime(f, (_BACKDATED, _BACKDATED))

    (repo / "a.txt").write_text("2\n", encoding="utf-8")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "two")

    assert head_file.stat().st_mtime == _BACKDATED, (
        "`.git/HEAD` was rewritten by a commit — if git ever starts doing this, build.rs's "
        "ORIGINAL watch list would have been adequate and this test's whole premise changes. "
        "Read TRDD-9XMPS8OZ before relaxing the watch list on the strength of it."
    )
    assert ref_file.stat().st_mtime != _BACKDATED, (
        "the resolved ref did not change across a commit — then nothing cargo can watch would "
        "signal a new commit, and the build stamp cannot be kept honest by mtime at all."
    )


def test_build_rs_watches_the_resolved_ref_and_not_only_HEAD() -> None:
    """build.rs must ACT on the fact above.

    What this does NOT prove: cargo's fingerprinting is not observable from here, so this
    cannot show that a rebuild really is triggered — only that the correct instruction is
    handed to cargo. The end-to-end proof is the Rust test
    `version_stamp_names_the_commit_this_binary_was_actually_built_from` in
    `scripts/memgrep/tests/cli.rs`, which compares the built binary's stamp against HEAD.
    """
    src = _BUILD_RS.read_text(encoding="utf-8")

    assert "symbolic-ref" in src, (
        "build.rs no longer resolves HEAD to its branch ref, so it cannot watch the file a "
        "commit writes — the janitor#164 stamp will freeze again (TRDD-9XMPS8OZ)."
    )
    # The regression shape to forbid is specifically the old one: deriving the watch path by
    # pasting "/HEAD" onto the git dir, with nothing else watched.
    pasted_head = re.findall(r"rerun-if-changed=\{[a-z_]+\}/HEAD", src)
    assert not pasted_head, (
        f"build.rs is back to watching a hard-coded <git-dir>/HEAD ({pasted_head}) — that is "
        "the exact line that froze the build stamp for nine days."
    )
    assert "packed-refs" in src, (
        "a freshly-cloned repo keeps its branch tip in packed-refs with no loose ref, so a "
        "watch list that ignores it is blind for exactly as long as that state lasts."
    )
