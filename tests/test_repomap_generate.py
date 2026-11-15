"""repomap_generate end-to-end + the anti-corruption contract (TRDD-e247a349, TRDD-FADYLSQB).

Real tests, no mocks: each case builds a throwaway git project with source
files and a human-authored CLAUDE.md, runs the actual script (subprocess) or
the imported function, and asserts on the real file system and real git.

The contract under test:
  - the generator writes the generated, git-ignored root PROJECT_MAP.md and never
    touches the human narrative of CLAUDE.md;
  - the ignore rule lands in the file `git rev-parse --git-path info/exclude` names
    (also in a linked worktree); a tracked PROJECT_MAP.md is refused;
  - a LEGACY REPO-MAP fence in CLAUDE.md is stripped once, only AFTER the new file is
    written and re-read with a matching header sha; a failed write leaves the fence;
  - malformed fences -> safe bail, CLAUDE.md untouched; a held lock -> skip;
  - the strip never loses a concurrent editor's text (lost-update guard) and keeps a
    rolling backup;
  - no-change reruns make ZERO writes, and --check exit codes encode fresh/stale/no-map.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_SCRIPT = _PROJECT_ROOT / "scripts" / "repomap_generate.py"
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import pytest  # noqa: E402
from repomap import insert_map_block, read_header, render_block  # noqa: E402

_NARRATIVE = "# My project\n\nHuman-authored architecture notes the janitor must NEVER touch.\n- gotcha one\n- gotcha two\n"
_FENCE_START = "<+-+-JANITOR-REPO-MAP-START-"
_FENCE_END = "<+-+-JANITOR-REPO-MAP-END-(do-not-modify)-+-+>"


def _load_module():
    """Import repomap_generate as a module (for the function-level tests)."""
    spec = importlib.util.spec_from_file_location("repomap_generate", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _check_ignore_rc(root: Path) -> int:
    return subprocess.run(["git", "check-ignore", "-q", "PROJECT_MAP.md"], cwd=root, capture_output=True).returncode


def _make_project(root: Path, *, with_claude_md: bool = True) -> None:
    (root / "pkg").mkdir(parents=True)
    (root / "pkg" / "alpha.py").write_text(
        '"""Alpha module — does alpha things."""\n\ndef alpha_fn(x: int) -> int:\n    """Return x doubled — never negative input."""\n    return x * 2\n\n\nclass Alpha:\n    def run(self) -> int:\n        return 1\n'
    )
    (root / "pkg" / "beta.py").write_text('"""Beta module — does beta things."""\n\ndef beta_fn() -> None:\n    """Fire the beta path exactly once."""\n')
    if with_claude_md:
        (root / "CLAUDE.md").write_text(_NARRATIVE)
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)


def _legacy_block(root: Path) -> str:
    """A fenced REPO-MAP block exactly as the pre-PROJECT_MAP.md generator wrote it."""
    maps = _load_module().extract_all(root, [])
    return render_block(maps, generated_iso="2026-01-01T00:00:00+0000", digest="olddigest")


def _with_legacy_fence(root: Path) -> str:
    """Give CLAUDE.md the legacy fence after the narrative; returns the new text."""
    text = insert_map_block(_NARRATIVE, _legacy_block(root))
    (root / "CLAUDE.md").write_text(text)
    return text


def _run(root: Path, *args: str, env: dict[str, str] | None = None) -> tuple[int, str]:
    res = subprocess.run(
        [sys.executable, str(_SCRIPT), "--root", str(root), *args],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, **(env or {})},
    )
    return res.returncode, res.stdout + res.stderr


def _narrative_of(text: str) -> str:
    """Everything outside the legacy fenced block."""
    start = text.find(_FENCE_START)
    if start < 0:
        return text
    end = text.find(_FENCE_END) + len(_FENCE_END)
    while end < len(text) and text[end] == "\n":
        end += 1
    return text[:start] + text[end:]


def test_generate_writes_the_map_file_and_leaves_claude_md_alone():
    """First generate writes PROJECT_MAP.md (names, methods included, methods=1 header); CLAUDE.md is byte-identical; --check is fresh."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        rc, out = _run(root)
        assert rc == 0 and "wrote" in out, out
        text = (root / "PROJECT_MAP.md").read_text()
        header = read_header(text)
        assert header is not None and header["methods"] == "1"
        assert "`pkg/alpha.py`" in text and "alpha_fn" in text and "Alpha.run" in text
        assert (root / "CLAUDE.md").read_text() == _NARRATIVE
        assert not [p for p in root.iterdir() if p.name.startswith(".claudemd-tmp-")], "tmp file leaked"
        rc, out = _run(root, "--check")
        assert rc == 0 and "fresh" in out, out


def test_rerun_without_change_makes_zero_writes():
    """AC2: identical structure -> 'already current', the map file is untouched (mtime)."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        before = (root / "PROJECT_MAP.md").stat().st_mtime_ns
        time.sleep(0.02)
        rc, out = _run(root)
        assert rc == 0 and "already current" in out, out
        assert (root / "PROJECT_MAP.md").stat().st_mtime_ns == before, "no-op must not rewrite"


def test_check_codes_stale_and_nomap():
    """--check: 2 = no map file; 1 = structure changed; 0 again after refresh."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root, "--check")[0] == 2  # no map yet
        assert _run(root)[0] == 0
        # add a public symbol -> structure changes
        with open(root / "pkg" / "alpha.py", "a") as f:
            f.write('\ndef gamma_fn() -> None:\n    """New public symbol."""\n')
        rc, out = _run(root, "--check")
        assert rc == 1 and "STALE" in out, out
        assert _run(root)[0] == 0  # refresh
        assert _run(root, "--check")[0] == 0


def test_comment_only_change_does_not_rewrite():
    """A comment edit moves the digest but not the structure -> check says refresh optional (exit 0) and generate makes no write."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        with open(root / "pkg" / "beta.py", "a") as f:
            f.write("# trailing comment, no structural change\n")
        rc, out = _run(root, "--check")
        assert rc == 0 and "structure unchanged" in out, out
        rc, out = _run(root)
        assert rc == 0 and "already current" in out, out


def test_check_hashes_with_the_methods_value_the_header_names():
    """A map written with methods=0 is judged with methods=0: no phantom STALE when the writer default and the header differ."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        mod = _load_module()
        maps = mod.extract_all(root, [])
        assert mod.map_sha(maps) != mod.map_sha(maps, include_methods=False), "fixture needs a method to discriminate"
        # digest "stale0" never equals the repo digest, forcing the extract-and-hash path
        (root / "PROJECT_MAP.md").write_text(mod.render_file(maps, generated_iso="2026-01-01T00:00:00+0000", digest="stale0", include_methods=False))
        rc, out = _run(root, "--check")
        assert rc == 0 and "structure unchanged" in out, out


def test_check_refuses_a_file_without_a_generated_header():
    """--check on a hand-written PROJECT_MAP.md is an error (exit 3), not a freshness verdict."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        (root / "PROJECT_MAP.md").write_text("# my own notes\n")
        assert _run(root, "--check")[0] == 3


def test_remove_deletes_only_a_generated_map():
    """--remove unlinks a file with a generated header, leaves CLAUDE.md alone, and refuses a header-less file."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        rc, out = _run(root, "--remove")
        assert rc == 0 and "removed" in out, out
        assert not (root / "PROJECT_MAP.md").exists()
        assert (root / "CLAUDE.md").read_text() == _NARRATIVE
        assert _run(root, "--remove")[0] == 0  # nothing to remove is fine
        (root / "PROJECT_MAP.md").write_text("# hand-written\n")
        rc, out = _run(root, "--remove")
        assert rc == 3 and "REFUSING" in out, out
        assert (root / "PROJECT_MAP.md").read_text() == "# hand-written\n"


def test_stdout_prints_the_file_and_touches_nothing():
    """--stdout prints the exact file text; no map, no lock dir, no exclude rule is created."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        exclude = root / ".git" / "info" / "exclude"
        before = exclude.read_text() if exclude.is_file() else ""
        rc, out = _run(root, "--stdout")
        assert rc == 0 and read_header(out) is not None, out
        assert not (root / "PROJECT_MAP.md").exists() and not (root / ".janitor").exists()
        assert (exclude.read_text() if exclude.is_file() else "") == before


def test_map_is_ignored_through_info_exclude_and_never_dirties_the_tree():
    """The ignore rule goes to info/exclude (not .gitignore), once, even when that file lacks a final newline."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        exclude = root / ".git" / "info" / "exclude"
        exclude.write_text("# local\n*.scratch")  # no trailing newline: the append must not glue onto it
        assert _run(root)[0] == 0 and _run(root)[0] == 0
        assert exclude.read_text().splitlines() == ["# local", "*.scratch", "/PROJECT_MAP.md"]
        assert _check_ignore_rc(root) == 0
        assert "PROJECT_MAP.md" not in _git(root, "status", "--porcelain")
        assert not (root / ".gitignore").exists()


def test_ignore_rule_lands_in_the_common_exclude_file_of_a_linked_worktree(tmp_path):
    """Real linked worktree: `.git` there is a FILE, the rule goes to the common dir's info/exclude and covers both checkouts."""
    main, wt = tmp_path / "main", tmp_path / "wt"
    main.mkdir()
    _make_project(main)
    _git(main, "worktree", "add", "-q", "-b", "wt-branch", str(wt))
    assert (wt / ".git").is_file()
    rc, out = _run(wt)
    assert rc == 0, out
    assert (wt / "PROJECT_MAP.md").is_file()
    common = (wt / _git(wt, "rev-parse", "--git-common-dir").strip()).resolve()
    assert "/PROJECT_MAP.md" in (common / "info" / "exclude").read_text().splitlines()
    assert _check_ignore_rc(wt) == 0
    assert "PROJECT_MAP.md" not in _git(wt, "status", "--porcelain")
    (main / "PROJECT_MAP.md").write_text("x\n")
    assert _check_ignore_rc(main) == 0, "the common exclude file also covers the main checkout"


def test_tracked_map_is_refused():
    """A PROJECT_MAP.md already tracked by git is never overwritten: exit 3, content and exclude file untouched."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        (root / "PROJECT_MAP.md").write_text("committed by hand\n")
        _git(root, "add", "-f", "PROJECT_MAP.md")
        _git(root, "commit", "-qm", "track the map")
        exclude = root / ".git" / "info" / "exclude"
        before = exclude.read_text() if exclude.is_file() else ""
        rc, out = _run(root)
        assert rc == 3 and "tracked" in out, out
        assert (root / "PROJECT_MAP.md").read_text() == "committed by hand\n"
        assert (exclude.read_text() if exclude.is_file() else "") == before



def test_a_git_failure_while_checking_tracked_status_is_an_error_not_untracked():
    """A corrupt index makes `git ls-files` fail (rc 128): the run exits 3 naming the git failure instead of treating the map as untracked."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        (root / ".git" / "index").write_bytes(b"not an index")
        rc, out = _run(root)
        assert rc == 3 and "git ls-files failed" in out, out
        assert not (root / "PROJECT_MAP.md").exists()



def test_handwritten_map_file_is_never_overwritten():
    """A PROJECT_MAP.md without a generated header is refused (exit 3) and kept byte-identical, same rule as --remove."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        fenced = _with_legacy_fence(root)
        (root / "PROJECT_MAP.md").write_text("HANDWRITTEN\n")
        rc, out = _run(root)
        assert rc == 3 and "REFUSING" in out, out
        assert (root / "PROJECT_MAP.md").read_text() == "HANDWRITTEN\n"
        assert (root / "CLAUDE.md").read_text() == fenced, "no strip after a refused write"


def test_non_git_root_writes_the_map_without_an_ignore_rule():
    """Outside a git work tree there is nothing to ignore: the map is written and --check is fresh."""
    with TemporaryDirectory() as d:
        root = Path(d)
        (root / "pkg").mkdir()
        (root / "pkg" / "alpha.py").write_text('"""Alpha."""\n\ndef alpha_fn() -> None:\n    pass\n')
        rc, out = _run(root)
        assert rc == 0 and "wrote" in out, out
        assert "alpha_fn" in (root / "PROJECT_MAP.md").read_text()
        assert _run(root, "--check")[0] == 0


def test_untracked_unignored_map_does_not_move_the_digest():
    """repo_digest excludes PROJECT_MAP.md like CLAUDE.md, so a map whose ignore rule failed cannot re-dirty the digest it records."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        mod = _load_module()
        before = mod.repo_digest(root)
        (root / "PROJECT_MAP.md").write_text("x\n")
        assert "PROJECT_MAP.md" in _git(root, "status", "--porcelain")
        assert mod.repo_digest(root) == before


def test_legacy_fence_is_stripped_after_a_verified_write_and_backed_up():
    """A legacy REPO-MAP fence is removed once PROJECT_MAP.md is written and verified; the narrative survives byte-for-byte and the backup holds the pre-strip text."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        fenced = _with_legacy_fence(root)
        rc, out = _run(root)
        assert rc == 0 and "legacy" in out, out
        assert (root / "PROJECT_MAP.md").is_file()
        after = (root / "CLAUDE.md").read_text()
        assert _FENCE_START not in after
        assert after.rstrip("\n") == _NARRATIVE.rstrip("\n")
        bak = root / ".janitor" / "state" / "CLAUDE.md.pre-repomap.bak"
        assert bak.read_text() == fenced, "backup must be the pre-strip CLAUDE.md"
        mtime = (root / "CLAUDE.md").stat().st_mtime_ns
        assert _run(root)[0] == 0
        assert (root / "CLAUDE.md").stat().st_mtime_ns == mtime, "a rerun must not touch CLAUDE.md again"


def test_a_failed_write_never_strips_the_legacy_fence():
    """If PROJECT_MAP.md cannot be written (a directory is in the way) the run fails and the fence, the only copy of the map, stays."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        fenced = _with_legacy_fence(root)
        (root / "PROJECT_MAP.md").mkdir()
        rc, out = _run(root)
        assert rc == 3 and "could not write" in out, out
        assert (root / "CLAUDE.md").read_text() == fenced


def test_map_verification_checks_the_header_sha_read_back_from_disk():
    """_map_verified is True only for a file whose re-read header carries the expected sha; a wrong sha, no header or no file is False."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        mod = _load_module()
        maps = mod.extract_all(root, [])
        sha = mod.map_sha(maps)
        target = root / "PROJECT_MAP.md"
        assert not mod._map_verified(target, sha)
        good = mod.render_file(maps, generated_iso="2026-01-01T00:00:00+0000", digest="d")
        target.write_text(good)
        assert mod._map_verified(target, sha)
        target.write_text(good.replace(sha, "0" * 12, 1))
        assert not mod._map_verified(target, sha)
        target.write_text("# no header\n")
        assert not mod._map_verified(target, sha)


def test_malformed_fence_bails_without_touching_claude_md():
    """A hand-broken legacy fence pair -> exit 3, CLAUDE.md byte-identical (the map file itself was already written)."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        path = root / "CLAUDE.md"
        _with_legacy_fence(root)
        broken = path.read_text().replace(_FENCE_END, "<oops-the-end-fence-is-gone>")
        path.write_text(broken)
        rc, out = _run(root)
        assert rc == 3 and "refusing" in out.lower(), out
        assert path.read_text() == broken, "bail must not modify the file"


def test_held_lock_skips_safely():
    """A held generator flock -> exit 3 skip; no map is written and CLAUDE.md is untouched."""
    import fcntl

    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        lock_dir = root / ".janitor" / "state"
        lock_dir.mkdir(parents=True)
        with open(lock_dir / "repomap.lock", "w") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            before = (root / "CLAUDE.md").read_text()
            rc, out = _run(root)
            assert rc == 3 and "lock" in out, out
            assert (root / "CLAUDE.md").read_text() == before
            assert not (root / "PROJECT_MAP.md").exists()


def test_excludes_are_persisted_and_honored():
    """--exclude trims the map AND persists so --check compares the same set."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        (root / "tests").mkdir()
        (root / "tests" / "test_alpha.py").write_text('"""Alpha tests."""\n\ndef test_alpha():\n    pass\n')
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "tests"], cwd=root, check=True)
        assert _run(root, "--exclude", "tests/*")[0] == 0
        text = (root / "PROJECT_MAP.md").read_text()
        assert "test_alpha" not in text, "excluded tree must not appear in the map"
        # TRACKED location: every clone must map the same file set, so it must not depend on
        # gitignored state (2026-07-26 balloon).
        assert (root / ".repomapignore").read_text().endswith("tests/*\n")
        assert not (root / ".janitor" / "state" / "repomap-excludes.txt").exists()
        # --check (no --exclude flag) must reuse the persisted set -> fresh.
        assert _run(root, "--check")[0] == 0


def test_legacy_exclude_file_is_still_read():
    """An existing checkout keeps its list until a save migrates it to the tracked file."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        (root / "tests").mkdir()
        (root / "tests" / "test_alpha.py").write_text('"""Alpha tests."""\n\ndef test_alpha():\n    pass\n')
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "tests"], cwd=root, check=True)
        legacy = root / ".janitor" / "state" / "repomap-excludes.txt"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("tests/*\n")
        assert _run(root)[0] == 0  # no --exclude: must fall back to the legacy list
        assert "test_alpha" not in (root / "PROJECT_MAP.md").read_text()


def test_oversized_map_is_refused_and_names_the_contributors():
    """A map that would balloon is REFUSED, not written; the message names what to exclude and does not claim the file rides every turn.

    On 2026-07-26 a lost exclude list silently took the old CLAUDE.md map 1720 -> 6032 lines and
    no gate complained. The cap is the cause-independent backstop and still applies to the file.
    """
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        before = (root / "CLAUDE.md").read_text()
        rc, out = _run(root, env={"CLAUDE_PLUGIN_OPTION_REPOMAP_MAX_BLOCK_BYTES": "100"})
        assert rc == 3, out
        assert "REFUSING to write" in out, out
        assert "Top contributors" in out, "a refusal must name what to exclude, or it gets --forced"
        assert "injected" not in out, "PROJECT_MAP.md is not injected into every turn"
        assert not (root / "PROJECT_MAP.md").exists()
        assert (root / "CLAUDE.md").read_text() == before


def test_a_refused_run_does_not_mutate_the_persisted_excludes():
    """The refusal must not corrupt the state it exists to protect: persisting the CLI excludes before the size check would poison the recovery."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root, "--exclude", "vendor/*")[0] == 0
        good = (root / ".repomapignore").read_text()
        rc, _out = _run(
            root,
            "--exclude",
            "something-else/*",
            env={"CLAUDE_PLUGIN_OPTION_REPOMAP_MAX_BLOCK_BYTES": "100"},
        )
        assert rc == 3
        assert (root / ".repomapignore").read_text() == good, "refused run rewrote the exclude list"


def test_strip_survives_a_writer_caught_between_truncate_and_write():
    """The torn-read race: a read landing in a writer's truncate window sees 0 bytes. The strip must treat that as 'no fence' and write nothing, never persist a narrative-less file.

    `Path.write_text` truncates first and writes after; the window here (5 ms) is an order of
    magnitude under the settle delay, so the assertion is about correctness, not a timing race.
    """
    mod = _load_module()
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        claude_md = root / "CLAUDE.md"
        fenced = insert_map_block(_NARRATIVE, _legacy_block(root))
        claude_md.write_text(fenced)

        def torn_writer() -> None:
            with open(claude_md, "w", encoding="utf-8") as fh:
                time.sleep(0.005)
                fh.write(fenced)

        t = threading.Thread(target=torn_writer)
        t.start()
        time.sleep(0.001)  # land INSIDE the truncate window
        mod.strip_legacy_fence(claude_md, attempts=3)
        t.join()

        final = claude_md.read_text()
        assert _NARRATIVE.strip().splitlines()[0] in final, f"the human narrative was destroyed by a strip over a torn read:\n{final!r}"
        assert final.count(_FENCE_START) <= 1, "torn/duplicated fences"


def test_concurrent_editor_never_corrupts_and_their_edit_survives():
    """THE race test: a hostile editor rewrites the narrative in a tight loop while strip_legacy_fence runs repeatedly. The final file is never torn and its narrative is one of the editor's exact versions."""
    mod = _load_module()
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        claude_md = root / "CLAUDE.md"
        block = _legacy_block(root)
        claude_md.write_text(insert_map_block(_NARRATIVE, block))

        versions = [f"# Narrative v{i}\n\nhuman text {i}\n" for i in range(40)]
        stop = threading.Event()

        def editor():
            for v in versions:
                if stop.is_set():
                    return
                # the human/Claude path: read-modify-write of the narrative, PRESERVING an existing block
                current = claude_md.read_text()
                start = current.find(_FENCE_START)
                tail = current[start:] if start >= 0 else ""
                claude_md.write_text(v + ("\n" + tail if tail else ""))
                time.sleep(0.001)

        t = threading.Thread(target=editor)
        t.start()
        try:
            for _ in range(30):
                current = claude_md.read_text()
                if _FENCE_START not in current:  # give the strip something to remove each round
                    claude_md.write_text(current.rstrip("\n") + "\n\n" + block)
                mod.strip_legacy_fence(claude_md, attempts=3)
                time.sleep(0.001)
        finally:
            stop.set()
            t.join()

        final = claude_md.read_text()
        assert final.count(_FENCE_START) <= 1, "torn/duplicated fences"
        assert final.count(_FENCE_END) == final.count(_FENCE_START)
        narrative = _narrative_of(final).rstrip("\n") + "\n"
        valid = {v.rstrip("\n") + "\n" for v in versions} | {_NARRATIVE.rstrip("\n") + "\n"}
        assert narrative in valid, f"narrative corrupted/interleaved:\n{narrative!r}"


def _make_ts_heavy_project(root: Path) -> None:
    """A repo where TypeScript dominates and the one Python file is peripheral
    — the #175 repro shape: a Python-only extractor covering 18 peripheral
    scripts and ZERO of the real (TypeScript) app."""
    (root / "app").mkdir(parents=True)
    for i in range(5):
        (root / "app" / f"component{i}.tsx").write_text(f"export function Component{i}() {{ return null; }}\n")
    (root / "scripts").mkdir()
    (root / "scripts" / "helper.py").write_text('"""A peripheral helper script."""\n\ndef helper_fn() -> None:\n    """Do a peripheral thing."""\n')
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=root, check=True)


def test_ts_heavy_repo_gets_an_honest_coverage_disclaimer():
    """#175: a Python-only extractor on an overwhelmingly-TypeScript repo must not present its partial map as complete — the written file carries an explicit disclaimer naming the gap."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_ts_heavy_project(root)
        rc, out = _run(root)
        assert rc == 0 and "wrote" in out, out
        text = (root / "PROJECT_MAP.md").read_text()
        assert "Python-only extractor" in text
        assert "5 other tracked source file(s)" in text
        assert "janitor#175" in text
        assert _run(root, "--check")[0] == 0, "the note is part of the hash on both sides"


def test_ordinary_python_repo_gets_no_disclaimer():
    """A couple of incidental non-Python files next to many Python modules must NOT trip the honesty check."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)  # alpha.py + beta.py, no other-language files
        assert _run(root)[0] == 0
        assert "Python-only extractor" not in (root / "PROJECT_MAP.md").read_text()


def test_excluded_tree_does_not_trip_the_disclaimer():
    """--exclude applies to the coverage count too — an intentionally-excluded tree must not trigger the honesty note either."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_ts_heavy_project(root)
        rc, out = _run(root, "--exclude", "app/*")
        assert rc == 0, out
        assert "Python-only extractor" not in (root / "PROJECT_MAP.md").read_text()


def test_discovery_follows_the_registry_not_a_hardcoded_extension():
    """#175 option 1: discover_sources derives its extension set from EXTRACTORS, so a newly-registered extractor changes discovery with ZERO changes to discover_sources."""
    mod = _load_module()
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        (root / "pkg" / "widget.fake").write_text("not really parsed")
        subprocess.run(["git", "add", "-A"], cwd=root, check=True)
        subprocess.run(["git", "commit", "-qm", "add fake"], cwd=root, check=True)
        before = {p.name for p in mod.discover_sources(root)}
        assert "widget.fake" not in before, "an unregistered extension must stay invisible"
        mod.EXTRACTORS[".fake"] = lambda p: mod.FileMap(path=str(p), role="", symbols=[])
        try:
            after = {p.name for p in mod.discover_sources(root)}
            assert "widget.fake" in after, "registering the extension must be the ONLY change needed"
        finally:
            del mod.EXTRACTORS[".fake"]


def _run_detector(root: Path) -> str:
    """Run the real project-map-drift detector against `root`; its stdout is the nudge text."""
    detector = _PROJECT_ROOT / "scripts" / "detectors" / "project-map-drift.py"
    res = subprocess.run(
        [sys.executable, str(detector)],
        capture_output=True,
        text=True,
        timeout=120,
        env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
        cwd=root,
    )
    assert res.returncode == 0, res.stderr
    return res.stdout


def _opt_in(root: Path) -> None:
    flag_dir = root / ".janitor" / "state"
    flag_dir.mkdir(parents=True, exist_ok=True)
    (flag_dir / "repomap-opt-in.flag").write_text("on")


def test_detector_nudges_only_when_opted_in_and_stale():
    """project-map-drift reads PROJECT_MAP.md: silent without the flag; silent when fresh; ONE deduped STALE nudge when the structure changed — and it NEVER writes CLAUDE.md or the map."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        assert _run_detector(root) == ""  # no opt-in flag -> silent

        _opt_in(root)
        assert _run_detector(root) == ""  # fresh -> silent

        (root / "pkg" / "alpha.py").write_text("def changed_fn() -> None:\n    pass\n")  # structure changes
        claude_before = (root / "CLAUDE.md").read_text()
        map_before = (root / "PROJECT_MAP.md").read_text()
        out = _run_detector(root)
        assert "[project-map-drift]" in out and "PROJECT_MAP.md is STALE" in out
        assert "CLAUDE.md project map" not in out
        assert (root / "CLAUDE.md").read_text() == claude_before, "detector must never write"
        assert (root / "PROJECT_MAP.md").read_text() == map_before, "detector must never write"
        assert _run_detector(root) == ""  # deduped on repeat


def test_detector_stays_silent_on_a_comment_only_change_when_the_map_has_a_coverage_note():
    """TRDD-6HFOB5S4: the writer hashes the map WITH the coverage note, so a detector that hashed without it never matched and nudged STALE forever on a TS-heavy repo; a real structure change must still nudge."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_ts_heavy_project(root)
        assert _run(root)[0] == 0
        assert "Python-only extractor" in (root / "PROJECT_MAP.md").read_text(), "the fixture must carry a coverage note or this proves nothing"
        _opt_in(root)
        assert _run_detector(root) == ""  # fresh

        helper = root / "scripts" / "helper.py"
        helper.write_text(helper.read_text() + "\n# comment only\n")
        assert _run_detector(root) == "", "structure is unchanged, so no STALE nudge may fire"

        # Commit first: the digest hashes `git status --porcelain`, whose " M" line does not change
        # when an already-dirty file is edited again, so a second edit would not move the digest.
        _git(root, "commit", "-qam", "comment only")
        assert _run_detector(root) == ""
        helper.write_text(helper.read_text() + "\n\ndef another_fn() -> None:\n    pass\n")
        assert "PROJECT_MAP.md is STALE" in _run_detector(root)


def test_detector_nudges_once_when_an_opted_in_project_has_no_map():
    """Opted in but PROJECT_MAP.md absent -> ONE deduped 'missing' nudge; opted out -> silent."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run_detector(root) == ""  # not opted in
        _opt_in(root)
        out = _run_detector(root)
        assert "PROJECT_MAP.md is missing" in out and "repomap_generate.py" in out
        assert _run_detector(root) == ""  # deduped
        assert not (root / "PROJECT_MAP.md").exists(), "detector must never write"
        # A condition that cleared and came back is a NEW episode, not a latched key.
        assert _run(root)[0] == 0
        assert _run_detector(root) == ""  # map present -> clear (re-arms the key)
        (root / "PROJECT_MAP.md").unlink()
        assert "PROJECT_MAP.md is missing" in _run_detector(root)


def test_detector_flags_a_leftover_legacy_fence_even_without_the_opt_in_flag():
    """A legacy REPO-MAP fence in CLAUDE.md is dead weight whether or not the project opted in: ONE deduped nudge naming the generator, which strips it; the detector itself never writes."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        text = _with_legacy_fence(root)
        out = _run_detector(root)
        assert "legacy REPO-MAP block" in out and "strips the fence once" in out
        assert (root / "CLAUDE.md").read_text() == text, "detector must never write"
        assert _run_detector(root) == ""  # deduped
        assert _run(root)[0] == 0  # the generator strips it...
        assert _FENCE_START not in (root / "CLAUDE.md").read_text()
        assert "legacy REPO-MAP block" not in _run_detector(root)  # clear (re-arms the key)
        _with_legacy_fence(root)  # e.g. an older plugin on another machine writes it back
        assert "legacy REPO-MAP block" in _run_detector(root)
        assert "side effect" in out, "the nudge must say the generator also writes the map"


def test_detector_flags_a_claude_md_that_names_the_map_only_when_opted_in():
    """CLAUDE.md has no map element: a mention of PROJECT_MAP nudges once for an opted-in project."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        (root / "CLAUDE.md").write_text(_NARRATIVE + "\nSee PROJECT_MAP.md for the code map.\n")
        assert _run_detector(root) == ""  # not opted in -> the map half is off
        _opt_in(root)
        out = _run_detector(root)
        assert "CLAUDE.md names PROJECT_MAP" in out
        assert _run_detector(root) == ""  # deduped
        # The env-var name merely CONTAINS the token; it is not a mention, and fixing the file re-arms.
        (root / "CLAUDE.md").write_text(_NARRATIVE + "\nTune `CLAUDE_PLUGIN_OPTION_PROJECT_MAP_DRIFT_INTERVAL`.\n")
        assert _run_detector(root) == ""
        (root / "CLAUDE.md").write_text(_NARRATIVE + "\nSee PROJECT_MAP.md again.\n")
        assert "CLAUDE.md names PROJECT_MAP" in _run_detector(root)


def test_detector_degrades_to_zero_findings_and_logs_once_when_the_map_computation_fails():
    """PRRD S6.1: an undecodable .repomapignore makes the structure probe raise; the detector still exits 0 with no nudge and logs that error once, not once per fire."""
    with TemporaryDirectory() as d:
        root = Path(d)
        _make_project(root)
        assert _run(root)[0] == 0
        _opt_in(root)
        # Untracked, so the digest moves and the structure probe runs; invalid UTF-8 makes load_excludes raise UnicodeDecodeError.
        (root / ".repomapignore").write_bytes(b"\xff\xfe\x00not utf-8\n")
        detector = _PROJECT_ROOT / "scripts" / "detectors" / "project-map-drift.py"
        log = root / ".janitor" / "logs" / "project-map-drift.log"

        def fire() -> subprocess.CompletedProcess[str]:
            return subprocess.run(
                [sys.executable, str(detector)],
                capture_output=True,
                text=True,
                timeout=120,
                env={**os.environ, "CLAUDE_PROJECT_DIR": str(root)},
                cwd=root,
            )

        first = fire()
        assert first.returncode == 0, first.stderr
        assert first.stdout == "", "a failed probe must degrade to zero findings"
        entries = log.read_text().splitlines()
        assert len(entries) == 1 and "UnicodeDecodeError" in entries[0], entries
        second = fire()
        assert second.returncode == 0 and second.stdout == "", second.stderr
        assert log.read_text().splitlines() == entries, "the same error must not be logged twice"


@pytest.mark.parametrize(
    ("start_mode", "want"),
    [(None, 0o644), (0o644, 0o644), (0o600, 0o644), (0o640, 0o640), (0o444, 0o444)],
)
def test_atomic_replace_keeps_chosen_mode_and_heals_0600(tmp_path, start_mode, want):
    """_atomic_replace keeps a mode the user chose; 0600 and a new file end at 0644."""
    target = tmp_path / "CLAUDE.md"
    if start_mode is not None:
        target.write_text("old")
        os.chmod(target, start_mode)
    _load_module()._atomic_replace(target, "new")
    assert os.stat(target).st_mode & 0o777 == want
    os.chmod(target, 0o644)
    assert target.read_text() == "new"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
