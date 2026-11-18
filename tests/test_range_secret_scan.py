"""Real-git, real-bun tests of the range secret scan (TRDD-FNPDFZWU increment 2).

Commit-time hooks miss commits made elsewhere (cherry-pick, rebase picks, `commit --no-verify`, fast-forward merges,
`am`), so every commit that leaves the machine, and every commit git-cliff reads, is scanned as a range:
`staged_secret_scan.py --range <rev-list args>`, run by git-hooks/pre-push for each pushed ref and by publish.py before
git-cliff. Every test runs the real script, the real scan.ts under real bun and real git in tmp_path; nothing is mocked.
Fake credentials come from `_fake_secrets.secret`, so no secret-shaped literal sits in this file.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sys
from pathlib import Path

import pytest
from _fake_secrets import secret
from test_staged_secret_scan import DATA_REL, Box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import publish  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
KIND = "github-token"
FAKE = secret("gh" + "p_", "fnpdfzwu-r1", 36)
FAKE2 = secret("gh" + "p_", "fnpdfzwu-r2", 36)
pytestmark = pytest.mark.real_subprocess("git", "bun", "uv", "sh", os.path.basename(sys.executable))


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def _no_value(out: str) -> None:
    for fake in (FAKE, FAKE2):
        assert fake not in out and fake[-10:] not in out


def _commit(box: Box, rel: str, text: str, msg: str = "c") -> str:
    """Commit `text` at `rel` with --no-verify, as a commit made where no hook ran; return the new sha."""
    box.stage(rel, text)
    box.git("commit", "-q", "--no-verify", "-m", msg)
    return box.git("rev-parse", "HEAD").stdout.strip()


def test_clean_history_passes(box: Box) -> None:
    """A range of clean commits exits 0."""
    base = _commit(box, "a.md", "one\n")
    _commit(box, "b.md", "two\n")
    _commit(box, "a.md", "one\nthree\n")
    r = box.scan("--range", f"{base}..HEAD")
    assert r.returncode == 0, r.stdout + r.stderr


def test_empty_range_passes(box: Box) -> None:
    """A range holding no commit exits 0 without running the scanner."""
    _commit(box, "a.md", "one\n")
    r = box.scan("--range", "HEAD..HEAD")
    assert r.returncode == 0, r.stdout + r.stderr


def test_no_verify_commit_adding_a_secret_is_blocked_with_sha_path_line_kind(box: Box) -> None:
    """A `commit --no-verify` that adds a secret is caught by the range scan: output names short sha, path, line and kind, never the value."""
    base = _commit(box, "a.md", "one\n")
    bad = _commit(box, "notes/n.md", f"x\ntoken = {FAKE}\n", "add notes")
    r = box.scan("--range", f"{base}..HEAD")
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert bad[:12] in out and "notes/n.md:2" in out and KIND in out
    _no_value(out)
    assert list(box.tmp.iterdir()) == []


def test_cherry_picked_commit_with_a_secret_is_blocked(box: Box) -> None:
    """A secret commit cherry-picked onto another branch is in the range of that branch and blocks."""
    base = _commit(box, "a.md", "one\n")
    box.git("checkout", "-q", "-b", "side")
    side = _commit(box, "s.md", f"key = {FAKE}\n", "side work")
    box.git("checkout", "-q", "main")
    box.git("cherry-pick", side)
    r = box.scan("--range", f"{base}..main")
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "s.md:1" in out, out
    _no_value(out)


def test_secret_only_in_one_commit_message_blocks(box: Box) -> None:
    """A secret in a commit message of the range blocks (the message is what git-cliff publishes); the clean files around it do not matter."""
    base = _commit(box, "a.md", "one\n")
    _commit(box, "b.md", "two\n", f"fix: rotate {FAKE}")
    bad = box.git("rev-parse", "HEAD").stdout.strip()
    r = box.scan("--range", f"{base}..HEAD")
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "commit message" in out and bad[:12] in out and KIND in out, out
    _no_value(out)


def test_secret_added_and_removed_inside_the_range_is_still_blocked(box: Box) -> None:
    """The intermediate commit holds the secret even though the tip does not: the commit that added it is named."""
    base = _commit(box, "a.md", "one\n")
    added = _commit(box, "a.md", f"one\nkey = {FAKE}\n", "add")
    removed = _commit(box, "a.md", "one\n", "remove")
    r = box.scan("--range", f"{base}..HEAD")
    out = r.stdout + r.stderr
    assert r.returncode == 1 and added[:12] in out and "a.md:2" in out, out
    assert removed[:12] not in out
    _no_value(out)


def test_fixture_line_already_in_the_parent_passes_and_is_counted(box: Box) -> None:
    """A secret line that is in the parent blob of the same path is pre-existing: not blocking, disclosed."""
    base = _commit(box, "fixture.txt", f"key = {FAKE}\n", "seed")
    _commit(box, "fixture.txt", f"key = {FAKE}\nclean addition\n", "touch")
    r = box.scan("--range", f"{base}..HEAD")
    out = r.stdout + r.stderr
    assert r.returncode == 0 and "pre-existing" in out, out
    _no_value(out)


def test_same_value_on_a_baselined_line_and_on_a_new_line_still_blocks(box: Box) -> None:
    """The baseline is by whole line text, never by value: the same secret on a new line of the file, or in a new file, blocks."""
    base = _commit(box, "fixture.txt", f"key = {FAKE}\n", "seed")
    _commit(box, "fixture.txt", f"key = {FAKE}\nother = {FAKE}\n", "same file")
    out = box.scan("--range", f"{base}..HEAD")
    assert out.returncode == 1 and "fixture.txt:2" in out.stdout and "fixture.txt:1" not in out.stdout, out.stdout + out.stderr
    mid = box.git("rev-parse", "HEAD").stdout.strip()
    _commit(box, "elsewhere.txt", f"key = {FAKE}\n", "new file")
    out2 = box.scan("--range", f"{mid}..HEAD")
    assert out2.returncode == 1 and "elsewhere.txt:1" in out2.stdout, out2.stdout + out2.stderr


def test_clean_merge_passes_and_a_merge_is_compared_with_its_first_parent(box: Box) -> None:
    """A merge commit is diffed against its first parent: a clean merge passes; a secret that arrived from the side branch is attributed to the merge too."""
    base = _commit(box, "a.md", "one\n")
    box.git("checkout", "-q", "-b", "side")
    side = _commit(box, "side.md", f"key = {FAKE}\n", "side secret")
    box.git("checkout", "-q", "main")
    _commit(box, "main.md", "clean main\n", "main work")
    box.git("merge", "-q", "--no-ff", "--no-verify", "-m", "merge side", "side")
    merge = box.git("rev-parse", "HEAD").stdout.strip()
    # Range limited to the merge itself: the side commit is excluded, so only the merge's own diff against its FIRST parent can name side.md.
    r = box.scan("--range", merge, "--not", side)
    out = r.stdout + r.stderr
    assert r.returncode == 1 and f"{merge[:12]}:side.md:1" in out, out
    clean = box.scan("--range", f"{base}..main~1")
    assert clean.returncode == 0, clean.stdout + clean.stderr


def test_new_branch_scans_only_commits_not_on_any_remote(box: Box) -> None:
    """`B --not --remotes` skips what a remote already holds (a pushed fixture) and scans the new commits only."""
    old = _commit(box, "fixture.txt", f"key = {FAKE}\n", "already pushed")
    box.git("update-ref", "refs/remotes/origin/main", old)
    box.git("checkout", "-q", "-b", "feature")
    _commit(box, "new.md", "clean\n", "feature work")
    ok = box.scan("--range", "feature", "--not", "--remotes")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    whole = box.scan("--range", "feature")
    assert whole.returncode == 1 and "fixture.txt:1" in whole.stdout, whole.stdout + whole.stderr


def test_a_bad_revision_is_cannot_run_exit_2(box: Box) -> None:
    """A range git cannot resolve is exit 2 (blocks while active), never a clean pass."""
    _commit(box, "a.md", "one\n")
    r = box.scan("--range", "nosuchrev..HEAD")
    assert r.returncode == 2 and "BLOCKED" in r.stdout + r.stderr


def test_an_option_shaped_revision_is_refused(box: Box) -> None:
    """Only `--not` and `--remotes` may start with a dash: any other option is refused (exit 2), so a ref name can never inject a git option."""
    _commit(box, "a.md", "one\n")
    r = box.scan("--range", "--output=x", "HEAD")
    assert r.returncode == 2, r.stdout + r.stderr


def test_range_scan_is_inert_without_the_janitor(box: Box) -> None:
    """No DATA dir: the range scan is inert (exit 0) even with a secret in the range."""
    base = _commit(box, "a.md", "one\n")
    _commit(box, "b.md", f"key = {FAKE}\n")
    shutil.rmtree(box.fakehome / ".claude")
    r = box.scan("--range", f"{base}..HEAD")
    assert r.returncode == 0 and "inert" in r.stdout + r.stderr


# -- the real pre-push hook, in a scratch repo, feature branches only (a main or tag push would run the real release gate) --


def _push_box(box: Box, tmp_path: Path) -> Path:
    """Bare local remote, the real pre-push hook as core.hooksPath, and scripts/lib + scripts/shield_scan linked in (never publish.py)."""
    remote = tmp_path / "remote.git"
    box.git("init", "-q", "--bare", str(remote))
    box.git("remote", "add", "origin", str(remote))
    scripts = box.repo / "scripts"
    scripts.mkdir()
    for name in ("lib", "shield_scan"):
        (scripts / name).symlink_to(REPO / "scripts" / name)
    shutil.copy2(REPO / "git-hooks" / "pre-push", box.hooks / "pre-push")
    box.git("config", "core.hooksPath", str(box.hooks))
    return remote


def _remote_refs(box: Box, remote: Path) -> str:
    return box.git("ls-remote", str(remote)).stdout


def test_real_pre_push_hook_blocks_a_feature_push_holding_a_no_verify_secret(box: Box, tmp_path: Path) -> None:
    """The real pre-push hook runs the range scan on <remote>..<local> and refuses a push whose new commit holds a secret; the remote gets nothing."""
    remote = _push_box(box, tmp_path)
    _commit(box, "a.md", "one\n")
    box.git("push", "-q", "origin", "main:refs/heads/seed", "--no-verify")
    box.git("checkout", "-q", "-b", "feature")
    bad = _commit(box, "f.md", f"key = {FAKE}\n", "feature work")
    r = box.git("push", "origin", "feature", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and bad[:12] in out and "f.md:1" in out and KIND in out, out
    _no_value(out)
    assert "refs/heads/feature" not in _remote_refs(box, remote)


def test_real_pre_push_hook_scans_a_new_branch_only_for_commits_not_on_a_remote(box: Box, tmp_path: Path) -> None:
    """A new remote branch (remote sha all zeros) scans `local --not --remotes`: a secret that origin already holds is not re-scanned, a new one blocks."""
    remote = _push_box(box, tmp_path)
    old = _commit(box, "fixture.txt", f"key = {FAKE}\n", "already pushed")
    box.git("push", "-q", "origin", "main:refs/heads/seed", "--no-verify")
    box.git("fetch", "-q", "origin")
    assert old in box.git("rev-parse", "refs/remotes/origin/seed").stdout
    box.git("checkout", "-q", "-b", "feature")
    _commit(box, "new.md", "clean\n", "clean feature work")
    ok = box.git("push", "origin", "feature", check=False)
    assert "secret in" not in ok.stdout + ok.stderr, ok.stdout + ok.stderr
    box.git("checkout", "-q", "-b", "feature2")
    bad = _commit(box, "g.md", f"key = {FAKE2}\n", "second feature")
    r = box.git("push", "origin", "feature2", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and bad[:12] in out and "g.md:1" in out, out
    assert "fixture.txt" not in out
    _no_value(out)
    assert "refs/heads/feature2" not in _remote_refs(box, remote)


def test_real_pre_push_hook_lets_a_clean_feature_push_through(box: Box, tmp_path: Path) -> None:
    """A clean feature-branch push passes the range scan and reaches the remote."""
    remote = _push_box(box, tmp_path)
    _commit(box, "a.md", "one\n")
    box.git("push", "-q", "origin", "main:refs/heads/seed", "--no-verify")
    box.git("checkout", "-q", "-b", "feature")
    _commit(box, "f.md", "clean\n", "feature work")
    r = box.git("push", "origin", "feature", check=False)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "refs/heads/feature" in _remote_refs(box, remote)

def test_real_pre_push_hook_scans_every_ref_of_a_multi_ref_push(box: Box, tmp_path: Path) -> None:
    """A push of two refs through the real hook, the secret only in the SECOND: the scan must see both ref lines (stdin not swallowed) and refuse the whole push."""
    remote = _push_box(box, tmp_path)
    _commit(box, "a.md", "one\n")
    box.git("push", "-q", "origin", "main:refs/heads/seed", "--no-verify")
    box.git("checkout", "-q", "-b", "clean-one")
    _commit(box, "c.md", "clean\n", "clean work")
    box.git("checkout", "-q", "-b", "dirty-two", "main")
    bad = _commit(box, "d.md", f"key = {FAKE}\n", "dirty work")
    r = box.git("push", "origin", "clean-one", "dirty-two", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and bad[:12] in out and "d.md:1" in out, out
    _no_value(out)
    refs = _remote_refs(box, remote)
    assert "refs/heads/clean-one" not in refs and "refs/heads/dirty-two" not in refs

def test_real_pre_push_hook_falls_back_to_not_remotes_when_the_remote_sha_is_not_in_this_clone(box: Box, tmp_path: Path) -> None:
    """A forced push over a remote sha this clone never fetched cannot use <remote>..<local>: the hook scans `<local> --not --remotes` instead (a clean one gets through, a secret one is named and refused)."""
    remote = _push_box(box, tmp_path)
    _commit(box, "a.md", "one\n")
    box.git("push", "-q", "origin", "main:refs/heads/seed", "--no-verify")
    other = tmp_path / "other"
    box.git("clone", "-q", str(remote), str(other))
    for name in ("feature", "feature2"):
        box.git("-C", str(other), "checkout", "-q", "-b", name, "origin/seed")
        (other / f"{name}.md").write_text("remote only\n", encoding="utf-8")
        box.git("-C", str(other), "add", f"{name}.md")
        box.git("-C", str(other), "-c", "user.name=T", "-c", "user.email=t@users.noreply.github.com", "-c", "commit.gpgsign=false", "commit", "-q", "-m", "remote work")
        box.git("-C", str(other), "push", "-q", "origin", name)
    remote_sha = _remote_refs(box, remote).split("refs/heads/feature\n")[0].split()[-1]
    assert box.git("cat-file", "-e", f"{remote_sha}^{{commit}}", check=False).returncode != 0, "the clone must not have the remote sha"
    box.git("checkout", "-q", "-b", "feature", "main")
    _commit(box, "f.md", "clean\n", "clean local work")
    ok = box.git("push", "--force", "origin", "feature", check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    box.git("checkout", "-q", "-b", "feature2", "main")
    bad = _commit(box, "g.md", f"key = {FAKE}\n", "local secret")
    r = box.git("push", "--force", "origin", "feature2", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and bad[:12] in out and "g.md:1" in out, out
    _no_value(out)

def test_real_pre_push_hook_scans_an_existing_ref_from_its_remote_sha(box: Box, tmp_path: Path) -> None:
    """Pushing an EXISTING remote branch scans `<remote sha>..<local sha>`: a secret already on the remote is not rescanned, a new one is named alone."""
    remote = _push_box(box, tmp_path)
    _commit(box, "a.md", "one\n")
    box.git("checkout", "-q", "-b", "feature")
    old = _commit(box, "old.md", f"key = {FAKE}\n", "old secret already on the remote")
    box.git("push", "-q", "--no-verify", "origin", "feature")
    _commit(box, "clean.md", "clean\n", "clean follow-up")
    ok = box.git("push", "origin", "feature", check=False)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    bad = _commit(box, "new.md", f"key = {FAKE2}\n", "new secret")
    r = box.git("push", "origin", "feature", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and bad[:12] in out and "new.md:1" in out and old[:12] not in out and "old.md" not in out, out
    _no_value(out)
    assert box.git("rev-parse", "HEAD~1").stdout.strip() in _remote_refs(box, remote)


def test_real_pre_push_hook_does_not_range_scan_a_ref_deletion(box: Box, tmp_path: Path) -> None:
    """A deletion line (local sha all zeros) is skipped by the range scan: run the hook directly on it and no scan message appears (the release gate that follows is unchanged and not available in this scratch repo)."""
    _push_box(box, tmp_path)
    sha = _commit(box, "a.md", f"key = {FAKE}\n")
    import subprocess

    r = subprocess.run(
        [str(box.hooks / "pre-push"), "origin", "file:///unused"],
        input="(delete) " + "0" * 40 + f" refs/heads/feature {sha}\n", cwd=box.repo, capture_output=True, text=True, check=False,
        env={**os.environ, "HOME": str(box.fakehome), "TMPDIR": str(box.tmp)},
    )
    out = r.stdout + r.stderr
    assert "secret in a commit" not in out and "secret scan of the pushed commits" not in out, out
    assert "scripts/publish.py" in out, "the hook must have moved on to the release gate (which fails here: publish.py is not linked)"
    _no_value(out)


def test_shipped_pre_push_hook_runs_the_range_scan_before_every_gate() -> None:
    """git-hooks/pre-push scans every pushed ref with --range before trufflehog and the release gate, with stdin closed for the scan."""
    text = (REPO / "git-hooks" / "pre-push").read_text(encoding="utf-8")
    scan_call = text.index('range_scan "$localsha" "$remotesha"')
    assert scan_call < text.index('secret_scan_range "$localsha"') < text.index("run_release_gate\n    exit $?")
    scan_lines = [ln for ln in text.splitlines() if "staged_secret_scan.py --range" in ln and not ln.strip().startswith("#")]
    assert len(scan_lines) == 2 and all("</dev/null" in ln for ln in scan_lines)
    assert os.access(REPO / "git-hooks" / "pre-push", os.X_OK)


# -- publish.py: the range scan before git-cliff, and the release text scan --


@pytest.fixture
def active(box: Box, monkeypatch: pytest.MonkeyPatch) -> Box:
    """The publish.py functions spawn the scanner with the inherited environment: point HOME at the box's fake home (DATA dir present)."""
    monkeypatch.setenv("HOME", str(box.fakehome))
    monkeypatch.setenv("TMPDIR", str(box.tmp))
    assert (box.fakehome / DATA_REL).is_dir()
    return box


def test_publish_range_scan_blocks_a_secret_after_the_last_release_tag(active: Box, capsys: pytest.CaptureFixture[str]) -> None:
    """stage_secret_scan scans <last v tag>..HEAD and exits 1 naming the commit, path and kind, never the value."""
    _commit(active, "a.md", "one\n")
    active.git("tag", "v1.0.0")
    bad = _commit(active, "b.md", f"key = {FAKE}\n", "after the tag")
    with pytest.raises(SystemExit) as exc:
        publish.stage_secret_scan(active.repo, "1.1.0")
    out = capsys.readouterr().out
    assert exc.value.code == 1 and bad[:12] in out and "b.md:1" in out and KIND in out, out
    _no_value(out)


def test_publish_range_scan_passes_when_the_only_secret_predates_the_last_tag(active: Box) -> None:
    """A secret already released (before the last v tag) is not re-scanned: the range starts at the tag."""
    _commit(active, "a.md", f"key = {FAKE}\n")
    active.git("tag", "v1.0.0")
    _commit(active, "b.md", "clean\n")
    publish.stage_secret_scan(active.repo, "1.1.0")


def test_publish_range_scan_with_no_tag_scans_the_whole_history(active: Box, capsys: pytest.CaptureFixture[str]) -> None:
    """With no release tag reachable, every commit of HEAD is scanned."""
    _commit(active, "a.md", f"key = {FAKE}\n")
    _commit(active, "b.md", "clean\n")
    with pytest.raises(SystemExit):
        publish.stage_secret_scan(active.repo, "1.0.0")
    assert "a.md:1" in capsys.readouterr().out


def test_publish_range_scan_ignores_the_tag_of_the_version_being_released(active: Box) -> None:
    """A leftover local tag v<new_ver> (interrupted publish) is skipped when looking for the last release: the range still starts at the previous tag."""
    _commit(active, "a.md", "one\n")
    active.git("tag", "v1.0.0")
    _commit(active, "b.md", f"key = {FAKE}\n", "unreleased")
    active.git("tag", "v1.1.0")
    with pytest.raises(SystemExit):
        publish.stage_secret_scan(active.repo, "1.1.0")


def test_publish_release_text_scan_blocks_a_secret_and_passes_clean_text(active: Box, capsys: pytest.CaptureFixture[str]) -> None:
    """scan_release_text exits 1 on text holding a secret (label named, value never printed) and returns on clean text."""
    publish.scan_release_text(active.repo, "release notes", "## v1\n- fix: a thing\n")
    with pytest.raises(SystemExit) as exc:
        publish.scan_release_text(active.repo, "release notes", f"## v1\n- fix: {FAKE}\n")
    out = capsys.readouterr().out
    assert exc.value.code == 1 and "release notes" in out and KIND in out, out
    _no_value(out)

# git-cliff preview of the notes, and the position of the scan in main.
@pytest.mark.real_subprocess("git", "git-cliff", "bun", "uv", "sh", os.path.basename(sys.executable))
def test_publish_previews_the_release_notes_to_stdout_without_touching_the_tree(active: Box) -> None:
    """_preview_release_notes renders the unreleased section for the new tag with git-cliff on stdout: the section names the new version and the unreleased commit, and no file is written."""
    shutil.copy2(REPO / "cliff.toml", active.repo / "cliff.toml")
    _commit(active, "a.md", "one\n", "feat: first thing")
    active.git("tag", "v1.0.0")
    _commit(active, "b.md", "two\n", "fix: the second thing")
    before = active.git("status", "--porcelain").stdout
    notes = publish._preview_release_notes(active.repo, "1.1.0")
    assert notes is not None and "1.1.0" in notes and "econd thing" in notes and "irst thing" not in notes, notes
    assert active.git("status", "--porcelain").stdout == before


def test_publish_main_scans_before_it_bumps_anything() -> None:
    """In main, stage_secret_scan runs before stage_bump, so a block leaves the tree exactly as it was; the later scans are a safety net."""
    import inspect

    src = inspect.getsource(publish.main)
    assert src.index("stage_secret_scan(root, new_ver)") < src.index("stage_bump(root, new_ver, args.dry_run)") < src.index("stage_changelog(root, new_ver, args.dry_run)")
    assert src.index("stage_changelog(root, new_ver, args.dry_run)") < src.index("scan_release_text(root, \"the new CHANGELOG.md section\"")

def test_publish_secret_scan_block_writes_nothing_to_the_tree(active: Box, capsys: pytest.CaptureFixture[str]) -> None:
    """A blocked stage_secret_scan leaves `git status` and the working files exactly as they were (it only reads git)."""
    _commit(active, "a.md", "one\n")
    active.git("tag", "v1.0.0")
    _commit(active, "b.md", f"key = {FAKE}\n", "after the tag")
    active.write("a.md", "edited, not committed\n")
    before = active.git("status", "--porcelain").stdout
    with pytest.raises(SystemExit):
        publish.stage_secret_scan(active.repo, "1.1.0")
    assert active.git("status", "--porcelain").stdout == before
    assert (active.repo / "a.md").read_text(encoding="utf-8") == "edited, not committed\n"
    _no_value(capsys.readouterr().out)

def test_publish_shows_the_exemption_disclosure_on_a_passing_scan(active: Box, capsys: pytest.CaptureFixture[str]) -> None:
    """On a PASSING publish scan the exemption disclosure still reaches the output (stderr), so a self-added exemption is visible."""
    _commit(active, "a.md", "one\n")
    active.git("tag", "v1.0.0")
    _commit(active, "fixture.txt", f"key = {FAKE}\n", "fixture")
    _commit(active, ALLOW, _entry(KIND, "fixture.txt", f"key = {FAKE}"), "list")
    publish.stage_secret_scan(active.repo, "1.1.0")
    err = capsys.readouterr().err
    assert "1 finding(s) exempted by .janitor-secret-allow" in err and "1 of them by entries not present at the base" in err, err


@pytest.mark.real_subprocess("git", "git-cliff", "bun", "uv", "sh", os.path.basename(sys.executable))
def test_the_notes_preview_is_the_section_stage_changelog_really_writes(active: Box) -> None:
    """With an existing CHANGELOG.md and two tags, the pre-bump preview equals the newest section of the CHANGELOG.md stage_changelog then writes (git-cliff footer aside)."""
    shutil.copy2(REPO / "cliff.toml", active.repo / "cliff.toml")
    _commit(active, "a.md", "one\n", "feat: first thing")
    active.git("tag", "v1.0.0")
    _commit(active, "b.md", "two\n", "fix: second thing")
    active.git("tag", "v1.0.1")
    publish.stage_changelog(active.repo, "1.0.1", False)
    _commit(active, "c.md", "three\n", "feat(scope): third thing")
    _commit(active, "CHANGELOG.md", (active.repo / "CHANGELOG.md").read_text(encoding="utf-8"), "docs: changelog")
    _commit(active, "d.md", "four\n", "fix!: fourth thing")
    preview = publish._preview_release_notes(active.repo, "1.1.0")
    publish.stage_changelog(active.repo, "1.1.0", False)
    real = publish._release_notes_for(active.repo, "1.1.0")
    assert preview is not None
    strip = lambda text: text.split("---\n*Generated by")[0].strip()  # noqa: E731
    assert strip(preview) == strip(real), (preview, real)
    assert "hird thing" in real and "ourth thing" in real

# -- .janitor-secret-allow: the committed exemption list (increment 2c) --

ALLOW = ".janitor-secret-allow"


def _entry(kind: str, path: str, line_text: str, reason: str = "reviewed test fixture") -> str:
    """One list line for the line `line_text` of `path`: kind, path, line:<sha256>, reason, TAB separated."""
    return "\t".join((kind, path, "line:" + hashlib.sha256(line_text.encode()).hexdigest(), reason)) + "\n"


def test_an_entry_for_one_line_exempts_only_that_line_and_discloses_it(box: Box) -> None:
    """An entry for `key = <fake>` clears that line (disclosed on stderr); a different secret on another line of the same file still blocks."""
    base = _commit(box, "a.md", "one\n")
    _commit(box, "fixture.txt", f"key = {FAKE}\n", "fixture")
    assert box.scan("--range", f"{base}..HEAD").returncode == 1, "no list yet"
    _commit(box, ALLOW, _entry(KIND, "fixture.txt", f"key = {FAKE}"), "list")
    r = box.scan("--range", f"{base}..HEAD")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "1 finding(s) exempted by .janitor-secret-allow" in r.stderr and "1 of them by entries not present at the base" in r.stderr
    _commit(box, "fixture.txt", f"key = {FAKE}\nother = {FAKE2}\n", "second secret")
    r2 = box.scan("--range", f"{base}..HEAD")
    out = r2.stdout + r2.stderr
    assert r2.returncode == 1 and "fixture.txt:2" in out and "fixture.txt:1" not in out, out
    _no_value(out)


def test_a_commit_message_secret_is_never_exempt(box: Box) -> None:
    """A message finding stays blocking even with entries naming the message and its line: only file blobs are exemptable."""
    base = _commit(box, "a.md", "one\n")
    msg = f"fix: rotate {FAKE}"
    box.stage(ALLOW, _entry(KIND, "commit message", msg) + _entry(KIND, "message.txt", msg))
    box.git("commit", "-q", "--no-verify", "-m", msg)
    r = box.scan("--range", f"{base}..HEAD")
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "commit message" in out, out
    _no_value(out)


def test_a_list_only_in_the_working_tree_exempts_nothing(box: Box) -> None:
    """The list is read from the tip commit, never the working tree: an uncommitted list clears nothing."""
    base = _commit(box, "a.md", "one\n")
    _commit(box, "fixture.txt", f"key = {FAKE}\n", "fixture")
    box.write(ALLOW, _entry(KIND, "fixture.txt", f"key = {FAKE}"))
    assert box.scan("--range", f"{base}..HEAD").returncode == 1
    box.git("add", ALLOW)
    assert box.scan("--range", f"{base}..HEAD").returncode == 1, "a staged list is not committed either"


def test_entries_added_inside_the_range_are_counted_apart_from_base_entries(box: Box) -> None:
    """One exemption comes from an entry already in the list below the range, one from an entry added inside it: the M line says 1 of 2."""
    box.stage(ALLOW, _entry(KIND, "old.txt", f"key = {FAKE}"))
    box.git("commit", "-q", "--no-verify", "-m", "list")
    base = box.git("rev-parse", "HEAD").stdout.strip()
    _commit(box, "old.txt", f"key = {FAKE}\n", "old fixture")
    box.stage(ALLOW, _entry(KIND, "old.txt", f"key = {FAKE}") + _entry(KIND, "new.txt", f"key = {FAKE2}"))
    box.stage("new.txt", f"key = {FAKE2}\n")
    box.git("commit", "-q", "--no-verify", "-m", "new fixture and entry")
    r = box.scan("--range", f"{base}..HEAD")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "2 finding(s) exempted by .janitor-secret-allow" in r.stderr and "1 of them by entries not present at the base" in r.stderr, r.stderr


def test_a_malformed_list_is_cannot_run_exit_2_naming_the_line_number_only(box: Box) -> None:
    """A bad line in the committed list fails closed: exit 2, the message names the line number and never the line."""
    base = _commit(box, "a.md", "one\n")
    box.stage(ALLOW, "# comment\n" + _entry(KIND, "a.md", "x") + f"{KIND}\tonly-two-fields-{FAKE}\n")
    box.git("commit", "-q", "--no-verify", "-m", "bad list")
    r = box.scan("--range", f"{base}..HEAD")
    out = r.stdout + r.stderr
    assert r.returncode == 2 and ".janitor-secret-allow line 3 is malformed" in out, out
    _no_value(out)


def test_a_blob_entry_exempts_only_that_exact_blob(box: Box) -> None:
    """`blob:<oid>` clears the finding in that blob only: after the file is edited the new blob blocks again."""
    base = _commit(box, "a.md", "one\n")
    box.stage("fixture.txt", f"key = {FAKE}\n")
    oid = box.git("rev-parse", ":fixture.txt").stdout.strip()
    box.stage(ALLOW, "\t".join((KIND, "fixture.txt", f"blob:{oid}", "reviewed")) + "\n")
    box.git("commit", "-q", "--no-verify", "-m", "fixture and list")
    ok = box.scan("--range", f"{base}..HEAD")
    assert ok.returncode == 0 and "1 finding(s) exempted" in ok.stderr, ok.stdout + ok.stderr
    edited = _commit(box, "fixture.txt", f"key = {FAKE2}\n", "edit the fixture")
    r = box.scan("--range", f"{base}..HEAD")
    out = r.stdout + r.stderr
    assert r.returncode == 1 and edited[:12] in out and "fixture.txt:1" in out, out
    _no_value(out)


def test_index_scan_honours_the_index_version_of_the_list(box: Box) -> None:
    """Index mode reads `.janitor-secret-allow` from the index: staged, it clears the staged fixture; only in the working tree, it does not."""
    box.stage("fixture.txt", f"key = {FAKE}\n")
    box.write(ALLOW, _entry(KIND, "fixture.txt", f"key = {FAKE}"))
    assert box.scan().returncode == 1, "the list is only in the working tree"
    box.git("add", ALLOW)
    r = box.scan()
    assert r.returncode == 0 and "1 finding(s) exempted" in r.stderr, r.stdout + r.stderr


def test_print_allow_entries_prints_ready_lines_and_they_make_the_range_pass(box: Box) -> None:
    """--print-allow-entries prints one REVIEW-ME entry per blocking file finding (exit 1, no value); committing them clears the range, and a clean range prints nothing (exit 0)."""
    base = _commit(box, "a.md", "one\n")
    assert box.scan("--print-allow-entries", "--range", f"{base}..HEAD").stdout == ""
    _commit(box, "fixture.txt", f"x\nkey = {FAKE}\n", "fixture")
    r = box.scan("--print-allow-entries", "--range", f"{base}..HEAD")
    assert r.returncode == 1, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert len(lines) == 1 and lines[0].split("\t")[:2] == [KIND, "fixture.txt"] and lines[0].endswith("\tREVIEW-ME"), r.stdout
    _no_value(r.stdout + r.stderr)
    assert lines[0].split("\t")[2] == "line:" + hashlib.sha256(f"key = {FAKE}".encode()).hexdigest()
    _commit(box, ALLOW, r.stdout, "list")
    again = box.scan("--range", f"{base}..HEAD")
    assert again.returncode == 0, again.stdout + again.stderr


def test_the_list_file_is_scanned_like_any_other_file(box: Box) -> None:
    """A secret typed into an entry reason is a finding in `.janitor-secret-allow` and blocks."""
    base = _commit(box, "a.md", "one\n")
    _commit(box, ALLOW, _entry(KIND, "a.md", "x", f"token {FAKE}"), "list with a secret reason")
    r = box.scan("--range", f"{base}..HEAD")
    out = r.stdout + r.stderr
    assert r.returncode == 1 and f"{ALLOW}:1" in out, out
    _no_value(out)

def test_a_commit_adding_a_valid_list_with_its_comment_header_passes(box: Box) -> None:
    """The list file scans itself: a commit that adds a list of valid entries under a comment block exits 0 (hashes and comments are not findings)."""
    base = _commit(box, "a.md", "one\n")
    header = (REPO / ALLOW).read_text(encoding="utf-8")
    _commit(box, ALLOW, header + _entry(KIND, "a.md", "one") + _entry(KIND, "b.md", "two", "judged fake by review"), "add the list")
    r = box.scan("--range", f"{base}..HEAD")
    assert r.returncode == 0, r.stdout + r.stderr
