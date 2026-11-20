"""Real-git, real-bun tests of the chained secret-shield pre-commit hook (TRDD-NYKNE7MY).

No mock: every test builds a git repo in tmp_path, runs scripts/shield_hook.py as a child process, and commits with
real git, so the installed hook, the DATA-dir stub and the real scanner (scripts/shield_scan/scan.ts under bun) all run.
The DATA dir, HOME and the global git config are the test own, so nothing is installed into the real repo or the real
DATA dir. Every fake credential is generated at call time (tests/_fake_secrets.py), never written as a literal.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest
import transcript_redact as tr
from _fake_secrets import secret
from exe_path import exe

# The suite denies every real binary by default (tests/sandbox_guard.py); these tests run the REAL git and bun.
pytestmark = pytest.mark.real_subprocess("bun", "git")

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
HOOK_SCRIPT = PLUGIN_ROOT / "scripts" / "shield_hook.py"
TIMEOUT_S = 240.0
TOKEN = secret("gh" + "p_", "shield-hook", 36)
AT = chr(64)


class Box:
    """One test folders (repo, DATA dir, home, global git config) and the commands that run in them."""

    def __init__(self, base: Path) -> None:
        self.base = base.resolve()
        self.repo = self.base / "repo"
        self.home_dir = self.base / "home"
        self.home_dir.mkdir()
        # The DATA dir is where dispatcher-stub.py looks for the anchor (HOME is the box own), so both stubs and the anchor agree.
        self.data = self.home_dir / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins"
        self.gitconfig = self.base / "gitconfig"
        self.gitconfig.write_text(f"[user]\n\tname = hook test\n\temail = hook{AT}example.test\n", encoding="utf-8")
        self.bun_dir = str(Path(tr.resolve_bun()).parent)

    def env(self, path: str | None = None) -> dict[str, str]:
        """The child environment: no GIT_* from the host, the box own HOME and global config, bun on PATH unless path is given."""
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update({"HOME": str(self.home_dir), "GIT_CONFIG_GLOBAL": str(self.gitconfig), "GIT_CONFIG_NOSYSTEM": "1"})
        env["PATH"] = path if path is not None else self.bun_dir + os.pathsep + env.get("PATH", "")
        return env

    def git(self, cwd: Path, *args: str, check: bool = True, path: str | None = None) -> subprocess.CompletedProcess[str]:
        """Run git -C cwd; a failure raises unless check is False."""
        return subprocess.run([exe("git"), "-C", str(cwd), *args], check=check, capture_output=True, text=True, timeout=TIMEOUT_S, env=self.env(path))

    def init(self, commit: bool = True) -> Path:
        """Make the repo, with one committed file unless commit is False (a repo with no HEAD)."""
        self.repo.mkdir()
        self.git(self.repo, "init", "-q")
        if commit:
            (self.repo / "base.txt").write_text("base\n", encoding="utf-8")
            self.git(self.repo, "add", "base.txt")
            self.git(self.repo, "commit", "-q", "-m", "base")
        return self.repo

    def hook(self, command: str, cwd: Path | None = None, *extra: str, pin: bool = True) -> subprocess.CompletedProcess[str]:
        """Run shield_hook.py <command> with the box DATA dir; install pins the real plugin folder unless pin is False (then the stub verifies the box cache)."""
        args = [sys.executable, str(HOOK_SCRIPT), command, "--repo", str(cwd or self.repo), "--data-dir", str(self.data)]
        if command == "install" and pin:
            args += ["--plugin-root", str(PLUGIN_ROOT)]
        return subprocess.run([*args, *extra], capture_output=True, text=True, timeout=TIMEOUT_S, env=self.env(), check=False)

    def commit(self, message: str = "c", cwd: Path | None = None, path: str | None = None) -> subprocess.CompletedProcess[str]:
        """git commit; the hook runs inside it."""
        return self.git(cwd or self.repo, "commit", "-q", "-m", message, check=False, path=path)

    def commits(self, cwd: Path | None = None) -> int:
        """The number of commits reachable from HEAD."""
        return int(self.git(cwd or self.repo, "rev-list", "--count", "HEAD").stdout.strip())

    def hooks_dir(self) -> Path:
        """The effective hooks folder of the repo."""
        return Path(self.git(self.repo, "rev-parse", "--path-format=absolute", "--git-path", "hooks").stdout.strip())


@pytest.fixture
def box(tmp_path: Path) -> Box:
    """A fresh Box in tmp_path."""
    return Box(tmp_path)


def _stage(box: Box, name: str, text: str, cwd: Path | None = None) -> None:
    """Write a file and stage it."""
    where = cwd or box.repo
    (where / name).write_text(text, encoding="utf-8")
    box.git(where, "add", name)


def test_install_without_existing_hook(box: Box) -> None:
    """With no pre-commit, install writes an executable marked hook, copies the stub to the DATA dir, and chains nothing."""
    box.init()
    done = box.hook("install")
    assert done.returncode == 0, done.stderr
    hook = box.hooks_dir() / "pre-commit"
    assert hook.is_file() and os.access(hook, os.X_OK)
    assert "janitor-shield-hook" in hook.read_text(encoding="utf-8")
    assert (box.data / "shield-hook-stub.py").is_file()
    assert not (box.hooks_dir() / "pre-commit.pre-janitor").exists()
    status = box.hook("status").stdout
    assert "installed=yes" in status and "chained=no" in status and "stub=yes" in status


def test_existing_ubs_style_hook_is_kept_and_runs_first(box: Box) -> None:
    """An existing pre-commit is renamed byte for byte, still runs on every commit, and its failing exit code blocks the commit."""
    box.init()
    log = box.base / "ubs.log"
    original = f"#!/bin/sh\n# ubs-style gate\necho ran >> {log}\nexit 0\n"
    old = box.hooks_dir() / "pre-commit"
    old.write_text(original, encoding="utf-8")
    old.chmod(0o755)
    assert box.hook("install").returncode == 0
    chained = box.hooks_dir() / "pre-commit.pre-janitor"
    assert chained.read_text(encoding="utf-8") == original
    _stage(box, "a.txt", "plain text\n")
    assert box.commit().returncode == 0
    assert log.read_text(encoding="utf-8") == "ran\n"
    chained.write_text("#!/bin/sh\necho ubs-says-no >&2\nexit 7\n", encoding="utf-8")
    _stage(box, "b.txt", "more text\n")
    before = box.commits()
    blocked = box.commit()
    assert blocked.returncode != 0 and "ubs-says-no" in blocked.stderr
    assert box.commits() == before


def test_tracked_hooks_dir_is_refused_and_the_line_is_printed(box: Box) -> None:
    """A core.hooksPath folder that git tracks is not written: install exits 1 and prints the line to add, naming the stub."""
    box.init()
    tracked = box.repo / "git-hooks"
    tracked.mkdir()
    (tracked / "pre-push").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    box.git(box.repo, "add", "git-hooks/pre-push")
    box.git(box.repo, "commit", "-q", "-m", "hooks")
    box.git(box.repo, "config", "core.hooksPath", "git-hooks")
    done = box.hook("install")
    assert done.returncode == 1
    assert "refused" in done.stdout and "shield-hook-stub.py" in done.stdout and "|| exit $?" in done.stdout
    assert sorted(p.name for p in tracked.iterdir()) == ["pre-push"]


def test_core_hooks_path_untracked_folder_is_the_target(box: Box) -> None:
    """core.hooksPath pointing at an untracked folder makes that folder the install target, not .git/hooks."""
    box.init()
    box.git(box.repo, "config", "core.hooksPath", "myhooks")
    (box.repo / "myhooks").mkdir()
    assert box.hook("install").returncode == 0
    assert (box.repo / "myhooks" / "pre-commit").is_file()
    assert not (box.repo / ".git" / "hooks" / "pre-commit").exists()


def test_reinstall_is_idempotent_and_keeps_the_original(box: Box) -> None:
    """Installing twice leaves one hook, and the saved original keeps its bytes and mode (the hook is never saved as the original)."""
    box.init()
    original = "#!/bin/sh\n# original\nexit 0\n"
    old = box.hooks_dir() / "pre-commit"
    old.write_text(original, encoding="utf-8")
    old.chmod(0o750)
    assert box.hook("install").returncode == 0
    first = (box.hooks_dir() / "pre-commit").read_bytes()
    again = box.hook("install")
    assert again.returncode == 0, again.stderr
    chained = box.hooks_dir() / "pre-commit.pre-janitor"
    assert (box.hooks_dir() / "pre-commit").read_bytes() == first
    assert chained.read_text(encoding="utf-8") == original
    assert stat.S_IMODE(chained.stat().st_mode) == 0o750


def test_uninstall_restores_the_original_byte_for_byte(box: Box) -> None:
    """Uninstall puts the original back under its own name with the same bytes and mode, and removes the saved copy."""
    box.init()
    original = b"#!/bin/sh\n# odd bytes \xff\xfe and no final newline\nexit 0"
    old = box.hooks_dir() / "pre-commit"
    old.write_bytes(original)
    old.chmod(0o755)
    assert box.hook("install").returncode == 0
    assert box.hook("uninstall").returncode == 0
    assert old.read_bytes() == original
    assert stat.S_IMODE(old.stat().st_mode) == 0o755
    assert not (box.hooks_dir() / "pre-commit.pre-janitor").exists()


def test_uninstall_without_an_original_removes_the_hook_and_refuses_a_foreign_hook(box: Box) -> None:
    """With no original, uninstall leaves no pre-commit; a pre-commit the janitor did not install is refused and untouched."""
    box.init()
    assert box.hook("install").returncode == 0
    assert box.hook("uninstall").returncode == 0
    assert not (box.hooks_dir() / "pre-commit").exists()
    foreign = box.hooks_dir() / "pre-commit"
    foreign.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    refused = box.hook("uninstall")
    assert refused.returncode == 1 and "not installed by the janitor" in refused.stderr
    assert foreign.read_text(encoding="utf-8") == "#!/bin/sh\nexit 0\n"


def test_install_refuses_a_hook_it_cannot_chain(box: Box) -> None:
    """A symlinked pre-commit, or a pre-commit next to an existing pre-commit.pre-janitor, is refused and nothing changes."""
    box.init()
    hooks = box.hooks_dir()
    real = box.base / "real-hook"
    real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (hooks / "pre-commit").symlink_to(real)
    assert box.hook("install").returncode == 1
    assert (hooks / "pre-commit").is_symlink()
    (hooks / "pre-commit").unlink()
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (hooks / "pre-commit.pre-janitor").write_text("saved\n", encoding="utf-8")
    refused = box.hook("install")
    assert refused.returncode == 1 and "would overwrite" in refused.stderr
    assert (hooks / "pre-commit.pre-janitor").read_text(encoding="utf-8") == "saved\n"


def test_staged_secret_blocks_even_when_the_working_copy_is_clean(box: Box) -> None:
    """A secret in the staged blob blocks the commit though the working file no longer holds it; the output names rule, path, line and never the value."""
    box.init()
    assert box.hook("install").returncode == 0
    _stage(box, "cfg.txt", "one\ntwo\nk = " + TOKEN + "\n")
    (box.repo / "cfg.txt").write_text("one\ntwo\nclean\n", encoding="utf-8")
    before = box.commits()
    blocked = box.commit()
    assert blocked.returncode != 0
    assert "github-token cfg.txt:3" in blocked.stderr
    assert TOKEN not in blocked.stdout + blocked.stderr
    assert box.commits() == before


def test_working_tree_only_secret_does_not_block(box: Box) -> None:
    """A secret added to the working file AFTER staging a clean version is not committed, so the commit passes."""
    box.init()
    assert box.hook("install").returncode == 0
    _stage(box, "cfg.txt", "clean\n")
    (box.repo / "cfg.txt").write_text("k = " + TOKEN + "\n", encoding="utf-8")
    before = box.commits()
    done = box.commit()
    assert done.returncode == 0, done.stderr
    assert box.commits() == before + 1


def test_hidden_staged_file_is_scanned(box: Box) -> None:
    """A staged dotfile (.env style) is in scope of the scan."""
    box.init()
    assert box.hook("install").returncode == 0
    _stage(box, ".env.local", "k = " + TOKEN + "\n")
    blocked = box.commit()
    assert blocked.returncode != 0 and "github-token .env.local:1" in blocked.stderr


def test_missing_scanner_fails_closed_naming_the_install_command(box: Box) -> None:
    """A plugin folder without scripts/shield_scan/scan.ts refuses the commit and says what is missing, the command that fixes it, and what to do next."""
    box.init()
    fake = box.base / "fakeplugin"
    (fake / "scripts").mkdir(parents=True)
    (fake / "scripts" / "shield_hook.py").symlink_to(HOOK_SCRIPT)
    # A plugin folder that ships the hook script and the stub but no scripts/shield_scan/scan.ts, pinned into the hook.
    shutil.copyfile(PLUGIN_ROOT / "scripts" / "shield-hook-stub.py", fake / "scripts" / "shield-hook-stub.py")
    pinned = subprocess.run(
        [sys.executable, str(fake / "scripts" / "shield_hook.py"), "install", "--repo", str(box.repo), "--data-dir", str(box.data), "--plugin-root", str(fake)],
        capture_output=True, text=True, timeout=TIMEOUT_S, env=box.env(), check=False,
    )
    assert pinned.returncode == 0, pinned.stderr
    _stage(box, "a.txt", "plain\n")
    before = box.commits()
    blocked = box.commit()
    assert blocked.returncode != 0
    assert "shield scanner is missing" in blocked.stderr
    assert "claude plugin update ai-maestro-janitor@ai-maestro-plugins --scope user" in blocked.stderr
    assert "run the same `git commit` again" in blocked.stderr
    assert box.commits() == before


def test_missing_bun_fails_closed_naming_the_tool_and_install_command(box: Box) -> None:
    """With bun off PATH the commit is refused; the message names bun, gives the brew command, and says to run the same commit again."""
    box.init()
    assert box.hook("install").returncode == 0
    tools = box.base / "tools"
    tools.mkdir()
    (tools / "python3").symlink_to(sys.executable)
    (tools / "git").symlink_to(exe("git"))
    no_bun_path = str(tools) + os.pathsep + "/usr/bin" + os.pathsep + "/bin"
    assert shutil.which("bun", path=no_bun_path) is None
    _stage(box, "a.txt", "plain\n")
    before = box.commits()
    blocked = box.commit(path=no_bun_path)
    assert blocked.returncode != 0
    assert "bun is not on PATH" in blocked.stderr
    assert "brew install oven-sh/bun/bun" in blocked.stderr
    assert "run the same `git commit` again" in blocked.stderr
    assert box.commits() == before


def test_missing_stub_fails_closed_naming_the_stub_and_the_fix(box: Box) -> None:
    """If the DATA-dir stub is gone the commit is refused and the message names the stub and the reinstall command."""
    box.init()
    assert box.hook("install").returncode == 0
    (box.data / "shield-hook-stub.py").unlink()
    _stage(box, "a.txt", "plain\n")
    blocked = box.commit()
    assert blocked.returncode != 0
    assert "shield-hook-stub.py is missing" in blocked.stderr
    assert "/janitor-secrets-shield-scan --install-hook" in blocked.stderr


def test_linked_worktree_installs_into_the_shared_hooks_and_blocks_there(box: Box) -> None:
    """Install run from a linked worktree writes the shared hooks folder, and a commit made in that worktree is scanned (clean passes, staged secret blocks)."""
    box.init()
    tree = box.base / "tree"
    box.git(box.repo, "worktree", "add", "-q", "-b", "side", str(tree))
    assert box.hook("install", cwd=tree).returncode == 0
    assert (box.repo / ".git" / "hooks" / "pre-commit").is_file()
    _stage(box, "w.txt", "plain\n", cwd=tree)
    assert box.commit(cwd=tree).returncode == 0
    _stage(box, "x.txt", "k = " + TOKEN + "\n", cwd=tree)
    before = box.commits(cwd=tree)
    blocked = box.commit(cwd=tree)
    assert blocked.returncode != 0 and "github-token x.txt:1" in blocked.stderr
    assert box.commits(cwd=tree) == before



def test_first_commit_with_no_head_is_scanned(box: Box) -> None:
    """In a repo with no commit yet, a staged secret blocks the first commit and a clean first commit passes."""
    box.init(commit=False)
    assert box.hook("install").returncode == 0
    _stage(box, "cfg.txt", "k = " + TOKEN + "\n")
    blocked = box.commit()
    assert blocked.returncode != 0 and "github-token cfg.txt:1" in blocked.stderr
    assert box.git(box.repo, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode != 0
    _stage(box, "cfg.txt", "clean\n")
    assert box.commit().returncode == 0


def test_partial_commit_with_a_temporary_index_is_scanned(box: Box) -> None:
    """`git commit <path>` builds a temporary GIT_INDEX_FILE; a secret in that path is blocked, so the hook reads the live index and not .git/index."""
    box.init()
    (box.repo / "t.txt").write_text("clean\n", encoding="utf-8")
    box.git(box.repo, "add", "t.txt")
    box.git(box.repo, "commit", "-q", "-m", "t")
    assert box.hook("install").returncode == 0
    (box.repo / "t.txt").write_text("k = " + TOKEN + "\n", encoding="utf-8")
    before = box.commits()
    blocked = box.git(box.repo, "commit", "-q", "-m", "partial", "t.txt", check=False)
    assert blocked.returncode != 0 and "github-token t.txt:1" in blocked.stderr
    assert box.commits() == before


def test_missing_python3_fails_closed_naming_the_install_command(box: Box) -> None:
    """With python3 off PATH the hook text itself refuses the commit, names python3, gives the brew command and the way on."""
    box.init()
    assert box.hook("install").returncode == 0
    tools = box.base / "pytools"
    tools.mkdir()
    (tools / "dirname").symlink_to(exe("dirname"))
    assert shutil.which("python3", path=str(tools)) is None
    _stage(box, "a.txt", "plain\n")
    before = box.commits()
    blocked = box.commit(path=str(tools))
    assert blocked.returncode != 0
    assert "python3 is not on PATH" in blocked.stderr and "brew install python" in blocked.stderr
    assert "run the same git commit again" in blocked.stderr
    assert box.commits() == before


# -- the integrity gate of the stub: unpinned installs verify the cached janitor ------------------------------


def _make_cache(box: Box, version: str, *, manifest: bool = True) -> Path:
    """A cached janitor version in the box HOME: symlinks to the real scanner pieces, plus a real README.md the manifest hashes."""
    vdir = box.home_dir / ".claude" / "plugins" / "cache" / "ai-maestro-plugins" / "ai-maestro-janitor" / version
    vdir.mkdir(parents=True)
    for name in ("scripts", "hooks", ".claude-plugin", "bunfig.toml", "package.json"):
        if (PLUGIN_ROOT / name).exists():
            (vdir / name).symlink_to(PLUGIN_ROOT / name)
    (vdir / "README.md").write_text("readme\n", encoding="utf-8")
    if manifest:
        (vdir / ".integrity").mkdir()
        digest = hashlib.sha256((vdir / "README.md").read_bytes()).hexdigest()
        (vdir / ".integrity" / "manifest-sha256.json").write_text(json.dumps({"version": 1, "files": {"README.md": digest}}), encoding="utf-8")
    return vdir


def _anchor(box: Box, vdir: Path, pinned_version: str | None = None) -> None:
    """The C3 anchor: a DATA-dir key and a last-good pin holding the HMAC of the version manifest, in the format the daemon writes."""
    key = bytes(range(32))
    box.data.mkdir(parents=True, exist_ok=True)
    (box.data / ".integrity-key").write_bytes(key)
    mac = base64.b64encode(hmac.new(key, (vdir / ".integrity" / "manifest-sha256.json").read_bytes(), hashlib.sha256).digest()).decode("ascii")
    (box.data / "integrity").mkdir(exist_ok=True)
    (box.data / "integrity" / "last-good.json").write_text(json.dumps({"version": pinned_version or vdir.name, "manifest_hmac": mac}), encoding="utf-8")


def _gate(box: Box) -> None:
    """Install unpinned (both stubs land in the DATA dir) and stage a secret; the caller commits."""
    box.init()
    assert box.hook("install", pin=False).returncode == 0
    _stage(box, "cfg.txt", "k = " + TOKEN + "\n")


def test_verified_cached_version_runs_with_both_stubs_side_by_side(box: Box) -> None:
    """A version that passes manifest and anchor runs the scanner (a staged secret is found); the DATA dir holds both stubs."""
    vdir = _make_cache(box, "9.9.9")
    _anchor(box, vdir)
    _gate(box)
    assert (box.data / "shield-hook-stub.py").is_file() and (box.data / "dispatcher-stub.py").is_file()
    blocked = box.commit()
    assert blocked.returncode != 0 and "github-token cfg.txt:1" in blocked.stderr
    _stage(box, "cfg.txt", "clean\n")
    assert box.commit().returncode == 0



def test_install_leaves_an_existing_dispatcher_stub_untouched(box: Box) -> None:
    """An unpinned install does not overwrite a dispatcher-stub.py already in the DATA dir (the armed cron fires it)."""
    box.init()
    box.data.mkdir(parents=True)
    existing = box.data / "dispatcher-stub.py"
    existing.write_text("# armed dispatcher, must survive\n", encoding="utf-8")
    assert box.hook("install", pin=False).returncode == 0
    assert existing.read_text(encoding="utf-8") == "# armed dispatcher, must survive\n"
    assert (box.data / "shield-hook-stub.py").is_file()


def test_tampered_manifest_listed_file_is_refused(box: Box) -> None:
    """A manifest-listed file changed in the cache refuses the commit, naming the mismatch and the repair command; the scanner never ran."""
    vdir = _make_cache(box, "9.9.9")
    _anchor(box, vdir)
    _gate(box)
    (vdir / "README.md").write_text("tampered\n", encoding="utf-8")
    before = box.commits()
    blocked = box.commit()
    assert blocked.returncode != 0
    assert "mismatch:README.md" in blocked.stderr and "/janitor-repin-integrity" in blocked.stderr
    assert "run the same `git commit` again" in blocked.stderr and "github-token" not in blocked.stderr
    assert box.commits() == before


def test_manifest_rewritten_against_the_anchor_is_refused(box: Box) -> None:
    """A manifest rewritten after it was anchored (a pin naming this version whose HMAC differs) refuses the commit."""
    vdir = _make_cache(box, "9.9.9")
    _anchor(box, vdir)
    _gate(box)
    manifest = vdir / ".integrity" / "manifest-sha256.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    data["files"]["extra.md"] = ""
    manifest.write_text(json.dumps(data), encoding="utf-8")
    blocked = box.commit()
    assert blocked.returncode != 0 and "pin-mismatch" in blocked.stderr and "github-token" not in blocked.stderr


def test_stale_anchor_naming_another_version_is_accepted(box: Box) -> None:
    """The anchor this host leaves stale (a pin for another version) does not block: the scanner runs and a clean commit passes."""
    vdir = _make_cache(box, "9.9.9")
    _anchor(box, vdir, pinned_version="1.0.0")
    _gate(box)
    assert "github-token cfg.txt:1" in box.commit().stderr
    _stage(box, "cfg.txt", "clean\n")
    assert box.commit().returncode == 0


def test_missing_anchor_and_key_are_accepted(box: Box) -> None:
    """With a valid manifest but no anchor files at all, the version is accepted (uncertain, not proven bad)."""
    _make_cache(box, "9.9.9")
    _gate(box)
    assert "github-token cfg.txt:1" in box.commit().stderr


def test_version_without_manifest_is_skipped_and_alone_refuses(box: Box) -> None:
    """A newest version with no manifest is rejected and the walk goes to the older verified one; as the only version it refuses the commit."""
    older = _make_cache(box, "9.9.8")
    _anchor(box, older)
    _make_cache(box, "9.9.9", manifest=False)
    _gate(box)
    assert "github-token cfg.txt:1" in box.commit().stderr
    shutil.rmtree(older)
    alone = box.commit()
    assert alone.returncode != 0
    assert "no usable integrity manifest (no-manifest)" in alone.stderr and "github-token" not in alone.stderr


def test_walk_goes_down_past_a_tampered_newest_version(box: Box) -> None:
    """A tampered newest version is passed over for the older acceptable one, so the scanner still runs."""
    older = _make_cache(box, "9.9.8")
    newest = _make_cache(box, "9.9.9")
    _anchor(box, older)
    (newest / "README.md").write_text("tampered\n", encoding="utf-8")
    _gate(box)
    assert "github-token cfg.txt:1" in box.commit().stderr


def test_missing_dispatcher_stub_in_data_dir_refuses_and_never_loads_the_repo_copy(box: Box) -> None:
    """Without dispatcher-stub.py beside the stub in the DATA dir the commit is refused with a clear message, though the repo has its own copy."""
    vdir = _make_cache(box, "9.9.9")
    _anchor(box, vdir)
    _gate(box)
    (box.data / "dispatcher-stub.py").unlink()
    assert (PLUGIN_ROOT / "scripts" / "dispatcher-stub.py").is_file()
    before = box.commits()
    blocked = box.commit()
    assert blocked.returncode != 0
    assert "dispatcher-stub.py (the integrity verifier) is missing" in blocked.stderr and "/janitor-secrets-shield-scan --install-hook" in blocked.stderr
    assert "github-token" not in blocked.stderr and box.commits() == before



def test_dispatcher_stub_too_old_for_the_verifier_refuses_naming_janitor_arm(box: Box) -> None:
    """A dispatcher-stub.py that loads but lacks the verifier routines refuses the commit and names /janitor-arm, which refreshes it."""
    vdir = _make_cache(box, "9.9.9")
    _anchor(box, vdir)
    _gate(box)
    # The real dispatcher stub of this plugin, minus _pin_rejects: loads fine, lacks one routine the gate calls.
    old = (PLUGIN_ROOT / "scripts" / "dispatcher-stub.py").read_text(encoding="utf-8").replace("def _pin_rejects(", "def _pin_rejects_removed(")
    (box.data / "dispatcher-stub.py").write_text(old, encoding="utf-8")
    before = box.commits()
    blocked = box.commit()
    assert blocked.returncode != 0
    assert "lacks the verifier routines" in blocked.stderr and "/janitor-arm" in blocked.stderr
    assert "github-token" not in blocked.stderr and box.commits() == before


def test_no_cached_version_refuses_with_the_update_command(box: Box) -> None:
    """An unpinned hook with no cached janitor refuses the commit and names the update command."""
    _gate(box)
    blocked = box.commit()
    assert blocked.returncode != 0
    assert "no cached ai-maestro-janitor version ships the shield hook script" in blocked.stderr
    assert "claude plugin update ai-maestro-janitor@ai-maestro-plugins --scope user" in blocked.stderr
