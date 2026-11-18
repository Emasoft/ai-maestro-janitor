"""Real-git, real-bun tests of the commit-time secret scan (TRDD-FNPDFZWU increment 1).

scripts/lib/staged_secret_scan.py scans what a commit would contain (the index, or the commit message)
with the shield scanner. Every test runs the real script, the real scan.ts under real bun and real git
in tmp_path; nothing is mocked. Fake credentials are built at call time by `_fake_secrets.secret` from
fragmented prefixes, so no secret-shaped literal sits in this file (tests/test_secret_fixture_hygiene.py).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from _fake_secrets import secret

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import publish  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "lib" / "staged_secret_scan.py"
KIND = "github-token"
FAKE = secret("gh" + "p_", "fnpdfzwu-a", 36)
FAKE2 = secret("gh" + "p_", "fnpdfzwu-b", 36)
DATA_REL = Path(".claude") / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
# The suite denies every real binary by default (tests/sandbox_guard.py); this file runs the real git, bun and python.
pytestmark = pytest.mark.real_subprocess("git", "bun", os.path.basename(sys.executable))


def _env(home: Path, tmp: Path) -> dict[str, str]:
    """Environment of a hook run: a private HOME (the DATA dir decides active/inert), a private TMPDIR, no inherited GIT_* repo vars."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["HOME"] = str(home)
    env["TMPDIR"] = str(tmp)
    return env


class Box:
    """One scratch repo plus the private HOME and TMPDIR a scan runs under."""

    def __init__(self, root: Path) -> None:
        self.fakehome = root / "home"
        self.tmp = root / "scantmp"
        self.repo = root / "repo"
        self.hooks = root / "hooks"
        for d in (self.fakehome, self.tmp, self.repo, self.hooks):
            d.mkdir()
        (self.fakehome / DATA_REL).mkdir(parents=True)
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test" + "@" + "users.noreply.github.com")
        self.git("config", "commit.gpgsign", "false")

    def git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
        return subprocess.run(["git", *args], cwd=self.repo, env=_env(self.fakehome, self.tmp), capture_output=True, text=True, check=check)

    def write(self, rel: str, text: str) -> None:
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def stage(self, rel: str, text: str) -> None:
        self.write(rel, text)
        self.git("add", rel)

    def scan(self, *args: str, script: Path = SCRIPT) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, str(script), *args], cwd=self.repo, env=_env(self.fakehome, self.tmp), capture_output=True, text=True, check=False)

    def install_hook(self, name: str, tail: str = "") -> None:
        hook = self.hooks / name
        hook.write_text(f"#!/bin/sh\nexec {sys.executable} {SCRIPT} {tail}\n", encoding="utf-8")
        hook.chmod(0o755)
        self.git("config", "core.hooksPath", str(self.hooks))

    def commits(self) -> int:
        r = self.git("rev-list", "--count", "HEAD", check=False)
        return int(r.stdout.strip()) if r.returncode == 0 else 0


@pytest.fixture
def box(tmp_path: Path) -> Box:
    return Box(tmp_path)


def _no_value(out: str) -> None:
    assert FAKE not in out and FAKE[-10:] not in out and FAKE2 not in out


def test_new_secret_staged_blocks_with_file_line_kind_and_no_value(box: Box) -> None:
    """A new secret line in the index exits 1 naming path, line and kind, never the value, and leaves no temp dir."""
    box.stage("notes/a.md", f"line one\ntoken = {FAKE}\nline three\n")
    r = box.scan()
    out = r.stdout + r.stderr
    assert r.returncode == 1, out
    assert "notes/a.md:2" in out and KIND in out
    _no_value(out)
    assert list(box.tmp.iterdir()) == []


def test_clean_staged_file_passes(box: Box) -> None:
    """A staged file with no secret exits 0."""
    box.stage("a.md", "nothing here\n")
    r = box.scan()
    assert r.returncode == 0, r.stdout + r.stderr


def test_hidden_staged_file_is_scanned(box: Box) -> None:
    """A staged dotfile (.env) is scanned: the scan runs with --all."""
    box.stage(".env", f"A=1\nTOKEN={FAKE}\n")
    r = box.scan()
    assert r.returncode == 1 and ".env:2" in r.stdout + r.stderr


def test_same_line_already_at_head_passes_and_is_counted(box: Box) -> None:
    """A secret line already in the HEAD blob of the same path does not block; the pre-existing count is disclosed."""
    box.stage("fixture.txt", f"key = {FAKE}\n")
    box.git("commit", "-q", "-m", "seed")
    box.stage("fixture.txt", f"key = {FAKE}\nadded clean line\n")
    r = box.scan()
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    assert "pre-existing" in out
    _no_value(out)


def test_a_second_new_secret_next_to_an_old_one_blocks(box: Box) -> None:
    """Only the new line blocks: the old secret line is pre-existing, the added one is not."""
    box.stage("fixture.txt", f"key = {FAKE}\n")
    box.git("commit", "-q", "-m", "seed")
    box.stage("fixture.txt", f"key = {FAKE}\nother = {FAKE2}\n")
    r = box.scan()
    out = r.stdout + r.stderr
    assert r.returncode == 1 and "fixture.txt:2" in out and "fixture.txt:1" not in out
    _no_value(out)


def test_renamed_file_is_compared_with_its_source_blob(box: Box) -> None:
    """A pure rename keeps its secret line pre-existing: the baseline is the rename source at HEAD."""
    box.stage("old.txt", f"key = {FAKE}\nmore text to keep similarity high\nand more\n")
    box.git("commit", "-q", "-m", "seed")
    box.git("mv", "old.txt", "new.txt")
    r = box.scan()
    assert r.returncode == 0, r.stdout + r.stderr


def test_commit_dash_a_is_blocked_by_the_real_hook(box: Box) -> None:
    """`git commit -a` builds its index inside git; the pre-commit hook still sees it and blocks the commit."""
    box.stage("a.md", "clean\n")
    box.git("commit", "-q", "-m", "seed")
    box.install_hook("pre-commit")
    box.write("a.md", f"clean\nkey = {FAKE}\n")
    r = box.git("commit", "-a", "-q", "-m", "add", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "a.md:2" in out, out
    assert box.commits() == 1
    _no_value(out)


def test_pathspec_commit_is_blocked_by_the_real_hook(box: Box) -> None:
    """`git commit <path>` builds a temporary index from the working file; the hook judges that index."""
    box.stage("a.md", "clean\n")
    box.stage("b.md", "clean\n")
    box.git("commit", "-q", "-m", "seed")
    box.install_hook("pre-commit")
    box.write("a.md", f"clean\nkey = {FAKE}\n")
    r = box.git("commit", "-q", "-m", "add", "a.md", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "a.md:2" in out, out
    assert box.commits() == 1
    _no_value(out)


def test_partly_staged_file_is_judged_by_the_index_both_ways(box: Box) -> None:
    """The scan reads the staged blob: a secret staged then removed from the working file blocks; one only in the working file passes."""
    box.stage("a.md", f"key = {FAKE}\n")
    box.write("a.md", "clean now\n")
    assert box.scan().returncode == 1
    box.stage("b.md", "clean staged\n")
    box.write("b.md", f"clean staged\nkey = {FAKE}\n")
    box.git("reset", "-q", "a.md")
    assert box.scan().returncode == 0


def test_secret_only_in_the_commit_message_blocks(box: Box) -> None:
    """--message-file: any finding blocks (the message has no baseline) and the value is not printed; a clean message passes."""
    msg = box.repo / "msg.txt"
    msg.write_text(f"fix: rotate {FAKE}\n", encoding="utf-8")
    r = box.scan("--message-file", str(msg))
    out = r.stdout + r.stderr
    assert r.returncode == 1 and KIND in out and "commit message:1" in out, out
    _no_value(out)
    msg.write_text("fix: rotate the token\n", encoding="utf-8")
    assert box.scan("--message-file", str(msg)).returncode == 0
    assert list(box.tmp.iterdir()) == []


def test_secret_in_the_message_is_blocked_by_the_real_commit_msg_hook(box: Box) -> None:
    """A commit whose message holds a secret is refused by commit-msg, so it never reaches the changelog."""
    box.install_hook("commit-msg", tail='--message-file "$1"')
    box.stage("a.md", "clean\n")
    r = box.git("commit", "-q", "-m", f"add {FAKE}", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and box.commits() == 0, out
    assert "commit message:1" in out and KIND in out, out
    _no_value(out)

def test_merge_that_brings_a_new_secret_is_blocked_by_the_real_hook(box: Box) -> None:
    """`git merge --no-ff` runs pre-merge-commit, not pre-commit; a side branch that adds a secret is refused."""
    box.stage("a.md", "clean\n")
    box.git("commit", "-q", "-m", "seed")
    box.git("checkout", "-q", "-b", "side")
    box.stage("side.md", f"key = {FAKE}\n")
    box.git("commit", "-q", "-m", "side")
    box.git("checkout", "-q", "main")
    box.stage("main.md", "clean main\n")
    box.git("commit", "-q", "-m", "main work")
    box.install_hook("pre-merge-commit")
    before = box.commits()
    r = box.git("merge", "--no-ff", "-m", "merge side", "side", check=False)
    out = r.stdout + r.stderr
    assert r.returncode != 0 and "side.md:1" in out, out
    assert box.commits() == before
    _no_value(out)


def test_bunfig_preload_in_the_repo_does_not_run_and_does_not_disarm_the_scan(box: Box) -> None:
    """A bunfig.toml preload in the committing repo must not run: bun starts in the plugin folder (TRDD-6E2I17HN)."""
    marker = box.repo / "preload-ran.txt"
    box.write("pre.ts", f"await Bun.write({str(marker)!r}, \"ran\")\n")
    box.write("bunfig.toml", "preload = [\"./pre.ts\"]\n")
    box.stage("a.md", f"key = {FAKE}\n")
    r = box.scan()
    assert r.returncode == 1, r.stdout + r.stderr
    assert not marker.exists()


def test_inert_when_the_janitor_data_dir_is_absent(box: Box) -> None:
    """No DATA dir (plugin uninstalled): one inert line, exit 0, even with a secret staged."""
    shutil.rmtree(box.fakehome / ".claude")
    box.stage("a.md", f"key = {FAKE}\n")
    r = box.scan()
    assert r.returncode == 0 and "inert" in r.stdout + r.stderr


def test_inert_when_the_kill_switch_exists(box: Box) -> None:
    """The kill-switch flag stops the janitor machine-wide: the scan is inert."""
    flag = box.fakehome / ".claude" / "janitor-control" / "kill-switch.flag"
    flag.parent.mkdir(parents=True)
    flag.write_text("", encoding="utf-8")
    box.stage("a.md", f"key = {FAKE}\n")
    r = box.scan()
    assert r.returncode == 0 and "inert" in r.stdout + r.stderr


def test_scanner_missing_while_active_exits_2(box: Box, tmp_path: Path) -> None:
    """A plugin copy with no scripts/shield_scan: the scan cannot run, exits 2 and blocks."""
    lib = tmp_path / "plugin" / "scripts" / "lib"
    lib.mkdir(parents=True)
    for name in ("staged_secret_scan.py", "transcript_redact.py"):
        shutil.copy2(REPO / "scripts" / "lib" / name, lib / name)
    box.stage("a.md", "clean\n")
    r = box.scan(script=lib / "staged_secret_scan.py")
    assert r.returncode == 2 and "BLOCKED" in r.stdout + r.stderr, r.stdout + r.stderr

def _plugin_with_fake_scanner(tmp_path: Path, scan_ts: str) -> Path:
    """A plugin copy whose scan.ts is a fixture script run by the real bun, so the exit-code handling of the scan is exercised."""
    lib = tmp_path / "plugin" / "scripts" / "lib"
    lib.mkdir(parents=True)
    for name in ("staged_secret_scan.py", "transcript_redact.py"):
        shutil.copy2(REPO / "scripts" / "lib" / name, lib / name)
    shield = tmp_path / "plugin" / "scripts" / "shield_scan"
    shield.mkdir()
    (shield / "scan.ts").write_text(scan_ts, encoding="utf-8")
    return lib / "staged_secret_scan.py"


FAKE_OUT = "const out = process.argv[process.argv.indexOf(\"--out\") + 1]\n"


def test_incomplete_scan_exit_3_is_cannot_run_never_clean(box: Box, tmp_path: Path) -> None:
    """A scanner that exits 3 (a file skipped) makes the scan exit 2 and names the skipped path; it is never read as clean."""
    script = _plugin_with_fake_scanner(
        tmp_path,
        "import { writeFileSync } from \"node:fs\"\n" + FAKE_OUT
        + "writeFileSync(out, JSON.stringify({ type: \"skip\", path: \"big.bin\", reason: \"over-size\" }) + \"\\n\")\nprocess.exit(3)\n",
    )
    box.stage("a.md", "clean\n")
    r = box.scan(script=script)
    out = r.stdout + r.stderr
    assert r.returncode == 2 and "big.bin" in out, out


def test_scanner_exit_0_without_a_complete_summary_is_cannot_run(box: Box, tmp_path: Path) -> None:
    """Exit 0 with no summary record is not a clean scan: exit 2."""
    script = _plugin_with_fake_scanner(
        tmp_path,
        "import { writeFileSync } from \"node:fs\"\n" + FAKE_OUT + "writeFileSync(out, \"\")\nprocess.exit(0)\n",
    )
    box.stage("a.md", "clean\n")
    r = box.scan(script=script)
    assert r.returncode == 2 and "BLOCKED" in r.stdout + r.stderr


def test_shipped_hooks_are_wired() -> None:
    """pre-commit runs the scan between stage 0 and stage 1; commit-msg passes the message file; pre-merge-commit runs the index scan; all are executable."""
    pre = (REPO / "git-hooks" / "pre-commit").read_text(encoding="utf-8")
    run = "uv run python scripts/lib/"
    assert pre.index(run + "redact_staged_reports.py") < pre.index(run + "staged_secret_scan.py") < pre.index(run + "staged_privacy_scan.py")
    msg_hook = REPO / "git-hooks" / "commit-msg"
    assert os.access(msg_hook, os.X_OK)
    assert "staged_secret_scan.py --message-file" in msg_hook.read_text(encoding="utf-8")
    merge_hook = REPO / "git-hooks" / "pre-merge-commit"
    assert os.access(merge_hook, os.X_OK)
    assert "staged_secret_scan.py" in merge_hook.read_text(encoding="utf-8")

def test_install_hook_installs_the_new_hooks(tmp_path: Path) -> None:
    """publish.install_hook copies commit-msg and pre-merge-commit into .git/hooks, executable."""
    root = tmp_path / "plugin"
    (root / ".git").mkdir(parents=True)
    (root / "git-hooks").mkdir()
    for name in ("pre-push", "pre-commit", "commit-msg", "pre-merge-commit"):
        shutil.copy2(REPO / "git-hooks" / name, root / "git-hooks" / name)
    assert publish.install_hook(root) == 0
    for name in ("commit-msg", "pre-merge-commit"):
        assert os.access(root / ".git" / "hooks" / name, os.X_OK)
