"""Tests for the memorize-nudge detector (scripts/detectors/memorize-nudge.py).

Real fixtures, no mocks. The detector is invoked AS A SUBPROCESS — exactly how the
heartbeat runs it — so each case is hermetic (a fresh process, no lru-cached
project-root / no shared in-memory state) and the test mirrors production. The
fixtures are real: a real ``git init`` repo with real commits, real memory note
files whose mtimes are set with ``os.utime`` to control the "last memorized"
clock, and HOME/CLAUDE_PROJECT_DIR redirected to tmp so the live tree is untouched.

Covers the acceptance for TRDD-87935f21 priority #6:
- FIRES on ≥ threshold substantive commits since the last note (adoption present).
- SILENT below threshold, when the wiki is empty (adoption gate), when every
  commit is bookkeeping, when a note is newer than the commits (gap closed), and
  when not inside a git repo.
- AGGRESSIVE mode (require_adoption=false) nudges an empty wiki.
- DEDUPE: a second run in the same interval/session is silent.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_DETECTOR = (
    Path(__file__).resolve().parent.parent
    / "scripts" / "detectors" / "memorize-nudge.py"
)

# Option vars the test must NOT inherit from the surrounding session, so the
# detector's documented defaults (threshold 3, interval 4h, adoption required)
# apply unless a test sets them explicitly.
_OPT_VARS = (
    "CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_MIN_COMMITS",
    "CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_INTERVAL",
    "CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_REQUIRE_ADOPTION",
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


def _init_repo(repo: Path) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.name", "Test")
    _git(repo, "config", "user.email", "test@example.com")


def _commit(repo: Path, rel: str, content: str, msg: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", msg)


def _write_note(repo: Path, name: str, *, age_s: float, body: str = "body") -> Path:
    """Write a PROJECT-scope memory note whose mtime is `age_s` seconds in the
    past (negative age_s → in the future, i.e. 'memorized after the commits').

    `body` is what the note SAYS — load-bearing since coverage is decided by whether any
    note MENTIONS a changed module, not by mtime."""
    mem = repo / ".claude" / "project" / "memory"
    mem.mkdir(parents=True, exist_ok=True)
    note = mem / name
    note.write_text(f"---\nname: x\n---\n{body}\n", encoding="utf-8")
    t = time.time() - age_s
    os.utime(note, (t, t))
    return note


@pytest.fixture
def home(tmp_path):
    h = tmp_path / "home"
    h.mkdir()
    return h


def _run(repo: Path, home: Path, **opts: str) -> str:
    """Run the detector as a fresh subprocess (the heartbeat's contract).

    `opts` set CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_* vars; any not given are
    REMOVED from the env so the detector defaults apply.
    """
    env = dict(os.environ)
    env["HOME"] = str(home)
    env["CLAUDE_PROJECT_DIR"] = str(repo)
    env["CLAUDE_SESSION_ID"] = "test-session-fixed"
    for v in _OPT_VARS:
        env.pop(v, None)
    for k, val in opts.items():
        env[f"CLAUDE_PLUGIN_OPTION_MEMORIZE_NUDGE_{k.upper()}"] = val
    proc = subprocess.run(
        [sys.executable, str(_DETECTOR)],
        cwd=str(repo if repo.is_dir() else repo.parent),
        env=env, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def test_fires_on_substantive_commits_after_last_note(tmp_path, home):
    """≥3 substantive commits after the last memory note → one nudge line."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_note(repo, "old.md", age_s=7200)  # memorized 2h ago
    for i in range(3):
        _commit(repo, f"src/f{i}.py", f"x = {i}\n", f"feat: thing {i}")
    out = _run(repo, home)
    assert "[memorize-nudge]" in out
    assert "3 substantive commit(s)" in out


def test_silent_below_threshold(tmp_path, home):
    """Only 2 substantive commits (default threshold 3) → silent."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_note(repo, "old.md", age_s=7200)
    for i in range(2):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    assert _run(repo, home) == ""


def test_silent_when_no_notes_adoption_gate(tmp_path, home):
    """No memory note anywhere → adoption gate keeps it silent (never nag a
    project that does not use the wiki)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(5):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    assert _run(repo, home) == ""


def test_aggressive_mode_nudges_empty_wiki(tmp_path, home):
    """require_adoption=false nudges even an empty wiki (the fleet's choice)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(3):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    out = _run(repo, home, require_adoption="false")
    assert "[memorize-nudge]" in out


def test_bookkeeping_commits_do_not_count(tmp_path, home):
    """Memory writes, TRDD/design edits, and release commits are NOT substantive."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_note(repo, "old.md", age_s=7200)
    _commit(repo, ".claude/project/memory/n1.md", "a\n", "docs(memory): note")
    _commit(repo, "design/tasks/TRDD-x.md", "b\n", "docs(trdd): plan")
    _commit(repo, "CHANGELOG.md", "c\n", "chore(release): v1.2.3")
    assert _run(repo, home) == ""


def test_a_note_about_something_ELSE_does_not_silence_the_nudge(tmp_path, home):
    """THE DEFECT THIS DETECTOR SHIPPED WITH (fixed 2026-08-04). A note newer than the
    commits used to collapse the window to zero — regardless of what the note was ABOUT — so
    memorizing topic A hid topic B permanently, and the more diligently the agent wrote, the
    blinder the detector got.

    Measured miss: seven commits landed on the keystroke injector interleaved with eight
    memory commits on other subjects; each pushed the cutoff past the injection commits, so
    the nudge never fired and the mechanism was re-derived from scratch two days later.

    A fresh note that never names `f0`..`f3` must NOT buy silence for them."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(4):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    _write_note(repo, "fresh.md", age_s=-300, body="something entirely unrelated")
    out = _run(repo, home)
    assert "[memorize-nudge]" in out, "an unrelated note still silences the nudge"
    assert "f0" in out, "the nudge must NAME the uncovered module, not just count commits"


def test_a_note_that_MENTIONS_the_module_does_silence_it(tmp_path, home):
    """The other half, so the fix is a real gate and not just 'always nudge': coverage is per
    MODULE. A note naming every changed module leaves nothing uncovered → silent. Without
    this the detector would be unsilenceable, which is how a nudge becomes noise and gets
    turned off.

    The note names the FILES (`f0.py`), not the bare stems: coverage matches on the basename
    WITH its extension, because a bare stem that is also an ordinary English word made any
    prose mention count as coverage and silenced the nudge forever (`state` matched 32 of this
    repo's 48 PROJECT notes). See `_uncovered_modules`."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    for i in range(4):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    _write_note(repo, "fresh.md", age_s=-300, body="covers f0.py f1.py f2.py f3.py in detail")
    assert _run(repo, home) == ""


def test_silent_outside_git_repo(tmp_path, home):
    """Not a git work tree → silent (nothing to nudge about)."""
    bare = tmp_path / "plain"
    bare.mkdir()
    (bare / ".claude" / "project" / "memory").mkdir(parents=True)
    (bare / ".claude" / "project" / "memory" / "n.md").write_text("x\n")
    assert _run(bare, home) == ""


def test_unatomized_corpus_routes_to_atomize_not_a_blocked_write(tmp_path, home):
    """janitor#151 item 5: every LOCAL/PROJECT note has 0 atom markers (pre-atomization
    free prose) — add-atom/add-lesson have nothing to anchor a new entry to, so the
    nudge must say the scope needs atomizing rather than blindly point at
    /janitor-memory-write's normal 'update an existing page' routing, which is exactly
    the path that is blocked."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_note(repo, "old.md", age_s=7200, body="plain free-prose note, no atom marker")
    for i in range(3):
        _commit(repo, f"src/f{i}.py", f"x = {i}\n", f"feat: thing {i}")
    out = _run(repo, home)
    assert "[memorize-nudge]" in out
    assert "predate atomization" in out
    assert "Recall first" not in out


def test_atomized_corpus_keeps_the_recall_first_routing(tmp_path, home):
    """The counterpart: as soon as ANY note in scope has at least one atom, the
    normal 'recall first, update an existing page' routing is still correct and
    must not be replaced by the atomize caveat."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_note(
        repo, "old.md", age_s=7200,
        body='^some-fact [keywords: x] this page already has a real atom.',
    )
    for i in range(3):
        _commit(repo, f"src/f{i}.py", f"x = {i}\n", f"feat: thing {i}")
    out = _run(repo, home)
    assert "[memorize-nudge]" in out
    assert "Recall first" in out
    assert "predate atomization" not in out


def test_dedupe_second_run_in_same_interval_silent(tmp_path, home):
    """Two runs in the same interval/session → exactly one nudge (no per-commit spam)."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _write_note(repo, "old.md", age_s=7200)
    for i in range(3):
        _commit(repo, f"src/f{i}.py", f"x={i}\n", f"feat: thing {i}")
    assert "[memorize-nudge]" in _run(repo, home)
    assert _run(repo, home) == ""


def _import():
    """Load the detector as a module so its pure helpers can be unit-tested."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("memorize_nudge_under_test", _DETECTOR)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- janitor#256: nudging about code that no longer exists -----------------------


def test_a_trashcan_path_is_never_nudged(tmp_path):
    """`.trashcan/` is safe-delete's own staging area, so nudging about code in it asks the
    reader to memorize what they just deleted."""
    mod = _import()
    p = tmp_path / ".trashcan" / "20260802_030918+0200" / "scripts" / "main.rs"
    p.parent.mkdir(parents=True)
    p.write_text("fn main() {}\n", encoding="utf-8")
    rel = str(p.relative_to(tmp_path))
    assert mod._is_gone_or_staged_for_deletion(tmp_path, rel), "trash must not be nudged"


def test_a_deleted_file_is_never_nudged(tmp_path):
    """The general defect the report exposed: the detector reads `git log --name-only` and
    never asked whether the file is still THERE, so EVERY deletion nudged for the full 14-day
    window — naming a file the reader cannot open. A nudge you cannot act on teaches you to
    ignore the next one, which is the only thing this detector has."""
    mod = _import()
    assert mod._is_gone_or_staged_for_deletion(tmp_path, "scripts/deleted_yesterday.py")


def test_a_live_file_is_still_nudged(tmp_path):
    """The fix must not buy precision by silencing the detector — the failure mode this repo
    keeps hitting."""
    mod = _import()
    p = tmp_path / "scripts" / "alive.py"
    p.parent.mkdir(parents=True)
    p.write_text("x = 1\n", encoding="utf-8")
    assert not mod._is_gone_or_staged_for_deletion(tmp_path, "scripts/alive.py")


# --- janitor#256, second half: the "no note mentions it" predicate itself ---------


def test_a_DOTTED_module_mention_counts_as_coverage() -> None:
    """The defect the peer report measured: an atom that names the symbol literally, in the
    dotted form prose about code actually uses, did not count — so the detector reported
    memorized code as unmemorized (their visible-sample precision was 0 of 6, not 1 of 6)."""
    mod = _import()
    blob = ("ATOM-JONB-6FIU  prrd_lib.prrd_lock mirrors ai-maestro withJsonLock byte-for-byte "
            "(<file>.lock mkdir-dir, 30s/20s/50ms) and must span each edit's whole parse-to-write")
    assert mod._is_mentioned("prrd_lib.py", blob), \
        "a dotted module reference names the module as plainly as the filename does"


def test_the_FILENAME_form_still_counts() -> None:
    """The original form must keep working — this is an ADDED acceptance, not a replacement."""
    mod = _import()
    assert mod._is_mentioned("state.py", "the guard lives in scripts/lib/state.py near the top")


def test_a_BARE_english_word_is_still_not_coverage() -> None:
    """The hole the extension requirement exists to close, and the reason the fix is the DOTTED
    form rather than the bare stem: `state`/`posture` are ordinary words, and accepting them
    silences the nudge for those modules forever. False SILENCE is invisible; a false nudge is
    not, so the predicate must keep failing in the noisy direction."""
    mod = _import()
    prose = "the session state was unclear and our security posture improved after the audit"
    assert not mod._is_mentioned("state.py", prose)
    assert not mod._is_mentioned("posture.py", prose)


def test_a_dotted_match_needs_an_IDENTIFIER_after_the_dot() -> None:
    """`posture.` at the end of a sentence is prose, not a module reference. Requiring an
    identifier character after the dot is what keeps the dotted form code-shaped."""
    mod = _import()
    assert not mod._is_mentioned("posture.py", "we reviewed our security posture. It improved.")
