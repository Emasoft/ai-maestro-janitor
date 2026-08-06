"""Tests for the write-time wikimem lint gate (owner directive 2026-08-06).

Real, no mocks: the pure helpers run against captured `memgrep lint` output, and the end-to-end
cases drive the hook as a REAL subprocess over a REAL page on disk, linted by the REAL memgrep.

WHAT IS BEING PINNED. A USER-scope page acquired a downward cross-scope wikilink through the
plain Edit tool, passed the author's own `memgrep validate`, and was only caught ~15 minutes later
by the heartbeat detector. Three facts made that possible, and each has a test here:
  * the write VERBS lint, but the Edit tool is a sanctioned bypass that memgrep never sees;
  * `validate` does not check what `lint` checks (link law / scope / footnotes);
  * `validate` prints NONE and exits 0 even for a path that DOES NOT EXIST.
"""

import json
import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "hooks"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import importlib.util  # noqa: E402


def _import_hook():
    """Load the hyphenated hook script by path — the repo's standard idiom (mirrors
    tests/test_reload_trigger.py), with the None-guards that keep type checking honest."""
    spec = importlib.util.spec_from_file_location(
        "wikimem_lint_hook", _ROOT / "scripts" / "hooks" / "post-edit-wikimem-lint.py"
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


hook = _import_hook()

HOOK = _ROOT / "scripts" / "hooks" / "post-edit-wikimem-lint.py"

# Captured verbatim from a real `memgrep lint` run on this corpus (2026-08-06).
LINT_OUT = (
    "INFO /x/memory/a.md:173 [lesson-uncited] — page-level lesson `[^4]:`\n"
    "ERROR /x/memory/a.md:16 [link-downward-cross-scope] — USER page links DOWN to a PROJECT page\n"
    "WARN /x/memory/b.md:155 [link-one-sided] — links to c.md but it does not link back\n"
    "ERROR /x/memory/a.md:141 [footnote-dangling-ref] — footnote reference `[^7]` has no definition\n"
    "memgrep lint: 4 finding(s), 2 at or above ERROR (1 scope(s): USER)\n"
)


# --- pure helpers ------------------------------------------------------------


def test_only_error_level_findings_are_surfaced():
    """WARN/INFO are usually pre-existing and corpus-wide; surfacing them trains the author to
    ignore the hook, and an ignored hook is a disabled one."""
    errors = hook.error_findings(LINT_OUT)
    assert len(errors) == 2
    assert all(e.startswith("ERROR ") for e in errors)
    assert any("link-downward-cross-scope" in e for e in errors)


def test_a_clean_lint_surfaces_nothing():
    """The silent path must be genuinely silent — no summary line mistaken for a finding."""
    assert hook.error_findings("memgrep lint: 0 finding(s), none at or above ERROR\n") == []
    assert hook.error_findings("") == []


def test_memory_pages_are_recognised_and_non_pages_are_not():
    """The gate must cover every scope root's pages and skip everything else."""
    assert hook.is_memory_page("/h/.claude/project/memory/janitor-architecture.md")
    assert hook.is_memory_page("/h/.claude/plugins/data/x/memory/reference_foo.md")
    assert hook.is_memory_page("/h/.claude/projects/slug/memory/note.md")
    assert not hook.is_memory_page("/h/Code/proj/scripts/lib/state.py")
    assert not hook.is_memory_page("/h/Code/proj/design/tasks/TRDD-x.md")


def test_the_index_the_private_store_and_the_sidecar_are_excluded():
    """MEMORY.md is the harness's index, user-mem is the PRIVATE store, .memgrep is the sidecar —
    none is a wikimem page and linting them would emit findings nobody can act on."""
    assert not hook.is_memory_page("/h/.claude/projects/slug/memory/MEMORY.md")
    assert not hook.is_memory_page("/h/.claude/projects/slug/memory/user-mem/0007.md")
    assert not hook.is_memory_page("/h/.claude/project/memory/.memgrep/index.db.md")


def test_the_edited_path_is_read_from_any_payload_shape():
    assert hook.gather_file_path({"file_path": "/a/memory/x.md"}) == "/a/memory/x.md"
    assert hook.gather_file_path({"path": "/b/memory/y.md"}) == "/b/memory/y.md"
    assert hook.gather_file_path({}) == ""


# --- end to end, real subprocess + real memgrep -------------------------------


def _run_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(HOOK)], input=json.dumps(payload),
        capture_output=True, text=True, timeout=120,
    )


def _memory_page(tmp_path: Path, body: str) -> Path:
    """A real page at a real `*/memory/*.md` path (a scratch dir, never the live corpus)."""
    d = tmp_path / "memory"
    d.mkdir(parents=True, exist_ok=True)
    p = d / "scratch-page.md"
    p.write_text(body, encoding="utf-8")
    return p


CLEAN_PAGE = """---
name: scratch-page
description: "a syntactically valid scratch page used only by this test"
ocd: 2026-08-06
lmd: 2026-08-06
metadata:
  node_type: memory
  type: reference
  tier: component
---

A body with no footnote references at all.

## Notes and lessons learned
"""

# A dangling `[^7]` reference with no `[^7]:` definition — a REAL, path-independent ERROR class
# (`footnote-dangling-ref`), so this exercises the gate without needing a live scope root.
BROKEN_PAGE = CLEAN_PAGE.replace(
    "A body with no footnote references at all.",
    "A body citing a footnote that was never defined. [^7]",
)


def test_a_broken_page_is_reported_in_the_same_turn(tmp_path):
    """THE REGRESSION: an Edit that breaks a page must surface immediately, not 15 min later."""
    p = _memory_page(tmp_path, BROKEN_PAGE)
    proc = _run_hook({"tool_name": "Edit", "tool_input": {"file_path": str(p)}})
    assert proc.returncode == 0, proc.stderr  # fail-open: never blocks the write
    assert "[wikimem-lint]" in proc.stderr
    assert "footnote-dangling-ref" in proc.stderr
    # It names the findings rather than telling the author to go run the linter themselves.
    assert "ERROR" in proc.stderr


def test_the_message_says_validate_would_not_have_caught_it(tmp_path):
    """The author's mistake was trusting `validate`; the message must correct that belief."""
    p = _memory_page(tmp_path, BROKEN_PAGE)
    proc = _run_hook({"tool_name": "Edit", "tool_input": {"file_path": str(p)}})
    assert "validate" in proc.stderr and "does not exist" in proc.stderr


def test_a_clean_page_is_silent(tmp_path):
    """No output on the happy path, or the gate becomes noise the author learns to skip."""
    p = _memory_page(tmp_path, CLEAN_PAGE)
    proc = _run_hook({"tool_name": "Edit", "tool_input": {"file_path": str(p)}})
    assert proc.returncode == 0
    assert proc.stderr.strip() == ""


def test_a_non_memory_edit_is_ignored(tmp_path):
    """The fast path: an ordinary source edit must cost one regex, not a memgrep invocation."""
    p = tmp_path / "state.py"
    p.write_text("x = 1\n", encoding="utf-8")
    proc = _run_hook({"tool_name": "Edit", "tool_input": {"file_path": str(p)}})
    assert proc.returncode == 0 and proc.stderr.strip() == ""


def test_garbage_stdin_and_unknown_tools_fail_open():
    """A guard that breaks editing gets disabled, and a disabled guard protects nothing."""
    assert subprocess.run(
        [sys.executable, str(HOOK)], input="not json",
        capture_output=True, text=True, timeout=60,
    ).returncode == 0
    assert _run_hook({"tool_name": "Read", "tool_input": {"file_path": "/a/memory/x.md"}}).returncode == 0


def test_a_vanished_path_is_not_linted(tmp_path):
    """A denied write or a rename target must not produce a finding about a file that isn't there."""
    proc = _run_hook({"tool_name": "Edit",
                      "tool_input": {"file_path": str(tmp_path / "memory" / "gone.md")}})
    assert proc.returncode == 0 and proc.stderr.strip() == ""


# --- the premise that made the incident possible ------------------------------


def test_validate_reports_clean_for_a_path_that_does_not_exist():
    """MEASURED 2026-08-06 and the reason this gate exists: `memgrep validate` prints NONE and
    exits 0 for a nonexistent path, so gating on validate alone gates on nothing.

    If memgrep ever fixes this, the test fails loudly — at which point the hook's message about
    validate should be revisited rather than left asserting something untrue.
    """
    import user_mem_lib

    binary = user_mem_lib.find_memgrep()
    if binary is None:
        import pytest

        pytest.skip("memgrep not installed")
    proc = subprocess.run(
        [binary, "validate", "/tmp/definitely-not-a-real-page-9f3a.md"],
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode == 0
    assert "NONE" in proc.stdout
