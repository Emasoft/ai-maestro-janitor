"""Real-bun, real-git tests of the secrets-shield scan core (TRDD-BAQB9SYO increment 1a).

No mock: every test runs `scripts/shield_scan/scan.ts` under real bun on a fixture tree built in tmp_path, with real git
repos, real child worker processes and the real shield core. Every fake credential is generated at call time by
`_fake_secrets` from fragmented prefixes, so no contiguous credential literal sits in this file
(see tests/test_secret_fixture_hygiene.py). The scan root is `tmp_path/root`; the findings file, the home folder and the
global git config live beside it, so the scan never reads its own output.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

import pytest
import transcript_redact as tr
from _fake_secrets import b62, hexs, secret

# The suite denies every real binary by default (tests/sandbox_guard.py); this file exists to run the REAL bun and the REAL git, so it opts in.
pytestmark = pytest.mark.real_subprocess("bun", "git")

SCAN = Path(__file__).resolve().parents[1] / "scripts" / "shield_scan" / "scan.ts"
TIMEOUT_S = 180.0
TOKEN = secret("gh" + "p_", "scan-1a", 36)
AT = chr(64)


class Scan:
    """The result of one scanner run: exit code, both streams, and the records of the findings file when it was written."""

    def __init__(self, done: subprocess.CompletedProcess[str], out: Path) -> None:
        self.code = done.returncode
        self.stdout = done.stdout
        self.stderr = done.stderr
        self.out = out
        self.records: list[dict[str, Any]] = []
        if out.exists():
            self.records = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]

    @property
    def summary(self) -> dict[str, Any]:
        """The last record of the findings file."""
        assert self.records[-1]["type"] == "summary"
        return self.records[-1]

    @property
    def findings(self) -> list[tuple[str, str, int | None, int]]:
        """Every finding as (path, kind, line, count), in file order."""
        return [(r["path"], r["kind"], r["line"], r["count"]) for r in self.records if r["type"] == "finding"]

    @property
    def skips(self) -> list[tuple[str, str]]:
        """Every skip record as (path, reason), in file order."""
        return [(r["path"], r["reason"]) for r in self.records if r["type"] == "skip"]

    def paths(self) -> set[str]:
        """The paths that hold a finding."""
        return {f[0] for f in self.findings}


class Box:
    """One test's folders (root, out, home, global git config) and the commands that run in them."""

    def __init__(self, base: Path) -> None:
        self.base = base.resolve()
        self.root = self.base / "root"
        self.root.mkdir()
        self.home_dir = self.base / "home"
        self.home_dir.mkdir()
        self.gitconfig = self.base / "gitconfig"
        self.gitconfig.write_text(f"[user]\n\tname = scan test\n\temail = scan{AT}example.test\n", encoding="utf-8")
        self.runs = 0

    def env(self, extra: dict[str, str] | None = None) -> dict[str, str]:
        """The environment of every child: HOME and the global git config are the test's own, so the host config never leaks in."""
        env = dict(os.environ)
        env.update({"HOME": str(self.home_dir), "GIT_CONFIG_GLOBAL": str(self.gitconfig), "GIT_CONFIG_NOSYSTEM": "1"})
        for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
            env.pop(name, None)
        env.update(extra or {})
        return env

    def git(self, cwd: Path, *args: str) -> None:
        """Run git in cwd; a failure raises."""
        subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True, text=True, timeout=TIMEOUT_S, env=self.env())

    def put(self, path: Path, text: str | bytes) -> Path:
        """Write a file, creating its folders."""
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(text, bytes):
            path.write_bytes(text)
        else:
            path.write_text(text, encoding="utf-8")
        return path

    def repo(self, path: Path, *tracked: str) -> Path:
        """Make a git repo at path and commit the named files (relative to path)."""
        path.mkdir(parents=True, exist_ok=True)
        self.git(path, "init", "-q")
        if tracked:
            self.git(path, "add", "-f", "--", *tracked)
            self.git(path, "commit", "-q", "-m", "c")
        return path

    def scan(self, *args: str, root: Path | None = None, out: Path | None = None, default_out: bool = False, env_extra: dict[str, str] | None = None) -> Scan:
        """Run the scanner over root (default: the box root) with 2 jobs and an explicit findings file under the box."""
        self.runs += 1
        out_path = out or self.base / "out" / f"run{self.runs}.jsonl"
        cmd = [tr.resolve_bun(), str(SCAN), "--jobs", "2"]
        if not default_out:
            cmd += ["--out", str(out_path)]
        cmd += [*args, str(root or self.root)]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_S, env=self.env(env_extra), check=False)
        if default_out and done.returncode in (0, 1, 3):
            out_path = Path(done.stdout.splitlines()[1])
        return Scan(done, out_path)


@pytest.fixture
def box(tmp_path: Path) -> Box:
    """A fresh Box in tmp_path."""
    return Box(tmp_path)


def _line(text: str = TOKEN) -> str:
    return f"k = {text}\n"


def test_tracked_file_with_token_gives_located_finding_and_exit_1(box: Box) -> None:
    """A tracked file with a token on line 3 gives one located finding there, exit 1, and no token text in the file, stdout or stderr."""
    box.put(box.root / "a.txt", "one\ntwo\n" + _line())
    box.repo(box.root, "a.txt")
    result = box.scan()
    assert result.code == 1
    assert result.findings == [("a.txt", "github-token", 3, 1)]
    assert result.summary["complete"] is True and result.summary["files_with_findings"] == 1
    body = TOKEN[4:]
    for text in (result.out.read_text(encoding="utf-8"), result.stdout, result.stderr):
        assert TOKEN not in text and body not in text


def test_gitignored_env_is_skipped_by_default_and_scanned_with_all(box: Box) -> None:
    """A gitignored .env with a token is not scanned by default (gitignored_entries counts it) and is scanned with --all."""
    box.put(box.root / ".gitignore", ".env\n")
    box.put(box.root / "clean.txt", "nothing\n")
    box.put(box.root / ".env", _line())
    box.repo(box.root, ".gitignore", "clean.txt")
    default = box.scan()
    assert default.code == 0 and default.findings == []
    assert default.summary["gitignored_entries"] == 1 and default.summary["scope"] == "default"
    everything = box.scan("--all")
    assert everything.code == 1 and everything.findings == [(".env", "github-token", 1, 1)]
    assert everything.summary["scope"] == "all"


def test_tracked_hidden_file_is_scanned_by_default(box: Box) -> None:
    """A tracked hidden file (.npmrc) is scanned by default."""
    box.put(box.root / ".npmrc", _line())
    box.repo(box.root, ".npmrc")
    assert box.scan().findings == [(".npmrc", "github-token", 1, 1)]


def test_tracked_file_matching_a_gitignore_pattern_is_scanned(box: Box) -> None:
    """A file that matches a .gitignore pattern but was force-added is tracked, so it is scanned."""
    box.put(box.root / ".gitignore", "*.log\n")
    box.put(box.root / "x.log", _line())
    box.repo(box.root, ".gitignore", "x.log")
    result = box.scan()
    assert result.findings == [("x.log", "github-token", 1, 1)]
    assert result.summary["gitignored_entries"] == 0


def test_untracked_file_that_no_rule_hides_is_scanned(box: Box) -> None:
    """An untracked, not ignored file is scanned."""
    box.put(box.root / "tracked.txt", "x\n")
    box.repo(box.root, "tracked.txt")
    box.put(box.root / "new.txt", _line())
    assert box.scan().findings == [("new.txt", "github-token", 1, 1)]


def test_untracked_nested_repo_is_scanned_as_its_own_repo(box: Box) -> None:
    """An untracked nested repo is a repo of its own: its .gitignore applies, and it counts as a second repo."""
    box.put(box.root / "top.txt", "x\n")
    box.repo(box.root, "top.txt")
    nested = box.root / "nested"
    box.put(nested / ".gitignore", "secret.txt\n")
    box.put(nested / "secret.txt", _line())
    box.put(nested / "open.txt", _line())
    box.repo(nested, ".gitignore")
    result = box.scan()
    assert result.findings == [("nested/open.txt", "github-token", 1, 1)]
    assert result.summary["repos"] == 2 and result.summary["gitignored_entries"] == 1


def test_submodule_is_recursed(box: Box) -> None:
    """A submodule (a gitlink in the parent) is recursed as a repo of its own."""
    source = box.base / "submodule-source"
    box.put(source / "s.txt", _line())
    box.repo(source, "s.txt")
    box.put(box.root / "top.txt", "x\n")
    box.repo(box.root, "top.txt")
    box.git(box.root, "-c", "protocol.file.allow=always", "submodule", "add", "-q", str(source), "sm")
    result = box.scan()
    assert result.findings == [("sm/s.txt", "github-token", 1, 1)]
    assert result.summary["repos"] == 2


def test_linked_worktree_inside_root_is_a_repo_root(box: Box) -> None:
    """A linked worktree inside the root (its .git is a file) is scanned as a repo root of its own."""
    box.put(box.root / "t.txt", _line())
    box.repo(box.root, "t.txt")
    box.git(box.root, "worktree", "add", "-q", "wt", "-b", "wt-branch")
    assert (box.root / "wt" / ".git").is_file()
    result = box.scan()
    assert result.findings == [("t.txt", "github-token", 1, 1), ("wt/t.txt", "github-token", 1, 1)]
    assert result.summary["repos"] == 2


def test_git_file_with_missing_gitdir_gives_git_error_and_exit_3(box: Box) -> None:
    """A .git file whose gitdir does not exist gives a git-error skip for that folder (no fallback walk of it) and exit 3."""
    box.put(box.root / "broken" / ".git", f"gitdir: {box.base}/does-not-exist\n")
    box.put(box.root / "broken" / "f.txt", _line())
    box.put(box.root / "other.txt", "clean\n")
    result = box.scan()
    assert result.code == 3
    assert result.skips == [("broken", "git-error")]
    assert result.findings == []
    assert result.summary["complete"] is False and result.summary["skipped"]["git-error"] == 1


def test_tracked_path_deleted_from_disk_counts_as_missing(box: Box) -> None:
    """A tracked path that no longer exists is counted as skip missing, and the run is still complete."""
    box.put(box.root / "a.txt", "a\n")
    box.put(box.root / "b.txt", "b\n")
    box.repo(box.root, "a.txt", "b.txt")
    (box.root / "b.txt").unlink()
    result = box.scan()
    assert result.code == 0 and result.skips == []
    assert result.summary["skipped"]["missing"] == 1 and result.summary["files_scanned"] == 1


def test_symlink_to_a_file_with_a_token_is_not_followed(box: Box) -> None:
    """A tracked symlink to a file that holds a token is counted as skip symlink and never followed."""
    outside = box.put(box.base / "outside.txt", _line())
    (box.root / "link.txt").symlink_to(outside)
    box.repo(box.root, "link.txt")
    result = box.scan()
    assert result.code == 0 and result.findings == []
    assert result.summary["skipped"]["symlink"] == 1 and result.summary["files_scanned"] == 0


def test_fifo_is_counted_as_special_and_never_opened(box: Box) -> None:
    """A FIFO is counted as skip special; a scanner that opened it would block, and the run timeout would fail the test."""
    os.mkfifo(box.root / "pipe")
    box.put(box.root / "plain.txt", "clean\n")
    result = box.scan()
    assert result.code == 0
    assert result.summary["skipped"]["special"] == 1 and result.summary["files_scanned"] == 1


def test_git_info_exclude_pattern_hides_a_file_by_default(box: Box) -> None:
    """A pattern in .git/info/exclude hides a file in the default scope."""
    box.put(box.root / "keep.txt", "x\n")
    box.repo(box.root, "keep.txt")
    box.put(box.root / ".git" / "info" / "exclude", "hidden.txt\n")
    box.put(box.root / "hidden.txt", _line())
    result = box.scan()
    assert result.code == 0 and result.findings == []
    assert result.summary["gitignored_entries"] == 1


def test_global_excludes_file_hides_a_file_by_default(box: Box) -> None:
    """A pattern in the global excludes file (core.excludesFile) hides a file in the default scope."""
    excludes = box.put(box.base / "global-excludes", "globally-hidden.txt\n")
    with box.gitconfig.open("a", encoding="utf-8") as handle:
        handle.write(f"[core]\n\texcludesFile = {excludes}\n")
    box.put(box.root / "keep.txt", "x\n")
    box.repo(box.root, "keep.txt")
    box.put(box.root / "globally-hidden.txt", _line())
    result = box.scan()
    assert result.code == 0 and result.findings == []
    assert result.summary["gitignored_entries"] == 1


def test_folder_that_is_not_a_repo_is_walked_whole(box: Box) -> None:
    """A folder outside any repo is walked whole, hidden files included, and counted in non_repo_dirs."""
    box.put(box.root / "plain" / "a.txt", _line())
    box.put(box.root / "plain" / ".hidden", _line())
    result = box.scan()
    assert result.findings == [("plain/.hidden", "github-token", 1, 1), ("plain/a.txt", "github-token", 1, 1)]
    assert result.summary["non_repo_dirs"] == 2 and result.summary["repos"] == 0


def test_all_scans_git_config_and_default_does_not(box: Box) -> None:
    """--all scans .git/config (a token in a remote URL) and no other .git content; the default scope does not scan it."""
    box.put(box.root / "keep.txt", "x\n")
    box.repo(box.root, "keep.txt")
    box.git(box.root, "remote", "add", "origin", f"https://oauth2:{TOKEN}{AT}host.example.test/o/r.git")
    assert ".git/config" not in box.scan().paths()
    everything = box.scan("--all")
    assert everything.code == 1
    assert ".git/config" in everything.paths()
    assert all(p == ".git/config" or not p.startswith(".git/") for p in everything.paths())


def test_file_names_with_a_space_and_a_newline(box: Box) -> None:
    """Paths with a space and with a newline come through the -z listing and the JSON records intact."""
    box.put(box.root / "a b.txt", _line())
    box.put(box.root / "n\nl.txt", _line())
    box.repo(box.root, "a b.txt", "n\nl.txt")
    result = box.scan()
    assert result.paths() == {"a b.txt", "n\nl.txt"}


def test_binary_file_with_a_token_is_skipped_as_binary(box: Box) -> None:
    """A file with a NUL byte in its first 8192 bytes is skipped as binary, whatever it holds."""
    box.put(box.root / "blob.bin", b"\x00" + TOKEN.encode("utf-8") + b"\n")
    result = box.scan()
    assert result.code == 0 and result.findings == []
    assert result.summary["skipped"]["binary"] == 1 and result.summary["files_scanned"] == 0


def test_forced_timeout_gives_skip_timeout_and_exit_3(box: Box) -> None:
    """One file of a few MB against a limit of a few milliseconds is killed: skip timeout, incomplete run, exit 3."""
    box.put(box.root / "big.txt", "x = 1\n" * 524288)
    result = box.scan("--file-timeout-base", "0", "--file-timeout-per-mb", "0.001")
    assert result.code == 3
    assert result.skips == [("big.txt", "timeout")]
    assert result.summary["complete"] is False and result.summary["files_scanned"] == 0


def test_forced_locate_kill_gives_unlocated_findings_and_no_skip(box: Box) -> None:
    """A kill during the locate pass keeps the whole-file counts as unlocated findings: unlocated_timeout 1, no skip, complete."""
    box.put(box.root / "t.txt", _line())
    result = box.scan("--file-timeout-base", "6", "--file-timeout-per-mb", "0", env_extra={"SHIELD_SCAN_TEST_LOCATE_DELAY_MS": "60000"})
    assert result.code == 1
    assert result.findings == [("t.txt", "github-token", None, 1)]
    assert result.skips == [] and result.summary["unlocated_timeout"] == 1 and result.summary["complete"] is True


def test_unterminated_private_key_header_locates_hits_after_it_per_line(box: Box) -> None:
    """After an unterminated private-key header the whole-file pass swallows the rest, but the per-line pass locates the token."""
    header = "-----BEGIN " + "RSA PRIVATE KEY-----\n"
    body = "".join(b62(f"kb{i}", 64) + "\n" for i in range(3))
    box.put(box.root / "k.txt", header + body + _line())
    result = box.scan()
    assert result.code == 1
    assert result.findings == [("k.txt", "private-key", 1, 1), ("k.txt", "github-token", 5, 1)]


def test_whole_file_surplus_is_reported_as_an_unlocated_finding(box: Box) -> None:
    """A session cookie value on the line after its name is formed only by a window of several lines: whole-file hit, no per-line hit, so line null."""
    box.put(box.root / "c.txt", "_gitlab" + "_session:\n" + hexs("scan-cookie", 32) + "\n")
    result = box.scan()
    assert result.code == 1
    assert result.findings == [("c.txt", "gitlab-session-cookie", None, 1)]


def test_out_inside_a_work_tree_exits_2_and_default_out_lands_under_home(box: Box) -> None:
    """An --out inside a git work tree exits 2 and writes nothing; the default out path lands under HOME; no findings file holds a token value."""
    box.put(box.root / "t.txt", _line())
    work_tree = box.repo(box.base / "work-tree")
    refused = box.scan(out=work_tree / "o.jsonl")
    assert refused.code == 2 and "git work tree" in refused.stderr and not (work_tree / "o.jsonl").exists()
    result = box.scan(default_out=True)
    assert result.code == 1
    scans = box.home_dir / ".secrets_shield" / "scans"
    assert result.out.parent == scans
    assert re.fullmatch(r"root-\d{8}_\d{6}[+-]\d{4}\.jsonl", result.out.name)
    assert TOKEN not in result.out.read_text(encoding="utf-8")


def test_two_runs_give_identical_records_apart_from_the_timing_fields(box: Box) -> None:
    """Two runs over the same tree give the same records and the same summary, except elapsed_s and mb_per_s."""
    box.put(box.root / ".gitignore", ".env\n")
    box.put(box.root / "a.txt", "one\n" + _line())
    box.put(box.root / "z.txt", _line())
    box.put(box.root / ".env", _line())
    box.repo(box.root, ".gitignore", "a.txt", "z.txt")
    box.put(box.root / "plain" / "p.txt", _line())
    box.put(box.root / "plain" / "blob.bin", b"\x00\x01")
    (box.root / "plain" / "link").symlink_to(box.root / "a.txt")
    first = box.scan()
    second = box.scan()
    assert first.code == second.code == 1 and first.paths() == {"a.txt", "z.txt", "plain/p.txt"}

    def strip(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: v for k, v in r.items() if k not in ("elapsed_s", "mb_per_s")} for r in records]

    assert strip(first.records) == strip(second.records)


def test_default_out_inside_a_home_that_is_a_git_repo_exits_2_and_names_out(box: Box) -> None:
    """With HOME inside a git work tree the default out path is refused with exit 2, and the error says to pass --out."""
    box.git(box.home_dir, "init", "-q")
    box.put(box.root / "t.txt", _line())
    result = box.scan(default_out=True)
    assert result.code == 2
    assert "--out" in result.stderr
    assert not (box.home_dir / ".secrets_shield").exists()
