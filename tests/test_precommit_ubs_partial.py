"""Tests of the pre-commit ubs partial-scan gate (TRDD-H7884ERZ): git-hooks/ubs_partial_gate.py.

The decision tests call decide() / parse_allow() / main() directly with fixture ubs reports shaped like the
real ones (measured with ubs 5.5.26: status "partial", failed_modules[].message "... detector sql_injection: ...")
and fixture -U0 diffs; no ubs run is needed. One end-to-end test runs the real helper with real git and real
ubs on a tiny repo, and is skipped when ubs is not installed.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from exe_path import exe

REPO = Path(__file__).resolve().parent.parent
HELPER = REPO / "git-hooks" / "ubs_partial_gate.py"
ALLOW = REPO / "git-hooks" / "ubs-partial-allow.tsv"
ROTATOR = REPO / "scripts" / "oauth_rotator" / "rotator.py"
FILE = "scripts/mod.py"
ANCHOR = "refresh(blob, on_failure=causes.append)"
ANCHOR_LINE = 6
# Same message shape ubs 5.5.26 prints for the rotator.py partial scan.
SQL_MSG = "Python analysis did not complete: detector sql_injection: SQLFlowLimit: SQL list mutation capability escapes; analysis is incomplete"


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("ubs_partial_gate", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["ubs_partial_gate"] = module
    spec.loader.exec_module(module)
    return module


gate = _load()


def _partial(message: str = SQL_MSG, language: str = "python") -> dict[str, Any]:
    return {"status": "partial", "failed_modules": [{"language": language, "status": "partial", "module_error": "ANALYZER_ERROR", "message": message}], "totals": {"critical": 0, "warning": 0, "info": 1, "files": 1}}


def _clean() -> dict[str, Any]:
    return {"status": "ok", "failed_modules": [], "totals": {"critical": 0, "warning": 0, "info": 0, "files": 1}}


def _head_text() -> str:
    lines = [f"line {n}" for n in range(1, 11)]
    lines[ANCHOR_LINE - 1] = "    fresh = " + ANCHOR
    return "\n".join(lines) + "\n"


def _entry(detector: str = "sql_injection", anchor: str = ANCHOR) -> Any:
    return gate.Entry(FILE, detector, anchor, "TRDD-H7884ERZ test entry")


def _diff(*hunks: tuple[int, int]) -> str:
    """A -U0 diff with one hunk per (old_start, old_count); the body lines are irrelevant to the gate."""
    out = [f"diff --git a/{FILE} b/{FILE}", f"--- a/{FILE}", f"+++ b/{FILE}"]
    for start, count in hunks:
        header = f"@@ -{start} +{start} @@" if count == 1 else f"@@ -{start},{count} +{start},{count} @@"
        out.append(header)
        out.extend("-old" if count else "+new" for _ in range(max(count, 1)))
    return "\n".join(out) + "\n"


def _decide(diff: str, staged: dict[str, Any] | None = None, head: dict[str, Any] | None = None, entry: Any = "default", head_text: str | None = None) -> Any:
    return gate.decide(
        FILE,
        _entry() if entry == "default" else entry,
        _partial() if staged is None else staged,
        _partial() if head is None else head,
        _head_text() if head_text is None else head_text,
        diff,
    )


def test_partial_before_and_after_with_diff_above_anchor_passes() -> None:
    """Exempt file partial at HEAD and staged, diff only above the anchor: allowed, message names file, detector and line."""
    d = _decide(_diff((2, 1), (4, 2)))
    assert d.ok, d.message
    assert FILE in d.message and "sql_injection" in d.message and f"line {ANCHOR_LINE}" in d.message


def test_diff_ending_just_above_anchor_passes() -> None:
    """A hunk covering HEAD lines up to anchor-1 is still above the limit site."""
    assert _decide(_diff((ANCHOR_LINE - 2, 2))).ok


def test_insertion_directly_before_anchor_line_passes() -> None:
    """A pure insertion after line anchor-1 (before the anchor line) leaves the anchor line and everything below untouched."""
    assert _decide(_diff((ANCHOR_LINE - 1, 0))).ok


def test_empty_diff_passes() -> None:
    """A staged file with no textual change cannot touch the unscanned region."""
    assert _decide("").ok


def test_diff_at_anchor_line_blocks() -> None:
    """A hunk that changes the anchor line itself blocks."""
    d = _decide(_diff((ANCHOR_LINE, 1)))
    assert not d.ok and FILE in d.message and "sql_injection" in d.message


def test_diff_after_anchor_blocks() -> None:
    """A hunk below the anchor line blocks."""
    assert not _decide(_diff((ANCHOR_LINE + 3, 1))).ok


def test_hunk_spanning_the_anchor_blocks() -> None:
    """A hunk that starts above the anchor but runs through it blocks."""
    assert not _decide(_diff((ANCHOR_LINE - 2, 4))).ok


def test_insertion_after_anchor_line_blocks() -> None:
    """A pure insertion after the anchor line itself is below the limit site and blocks."""
    assert not _decide(_diff((ANCHOR_LINE, 0))).ok


def test_one_hunk_above_and_one_below_blocks() -> None:
    """Every hunk is checked: one clean hunk does not excuse a later one below the anchor."""
    assert not _decide(_diff((1, 1), (ANCHOR_LINE + 2, 1))).ok


def test_diff_without_hunks_blocks() -> None:
    """A non-empty diff with no parsable hunk (mode change, binary) cannot be proven to stay above the anchor."""
    assert not _decide("diff --git a/x b/x\nold mode 100644\nnew mode 100755\n").ok


def test_partial_file_without_entry_blocks() -> None:
    """A partial scan of a file with no allow entry blocks and names the file and detector."""
    d = _decide(_diff((1, 1)), entry=None)
    assert not d.ok and FILE in d.message and "sql_injection" in d.message


def test_other_detector_blocks() -> None:
    """A partial scan by a detector the entry does not name blocks."""
    other = _partial("Python analysis did not complete: detector taint_flow: Limit: x; analysis is incomplete")
    d = _decide(_diff((1, 1)), staged=other, head=other)
    assert not d.ok and "taint_flow" in d.message


def test_extra_detector_next_to_the_allowed_one_blocks() -> None:
    """Every partial detector must equal the entry detector: allowed plus another still blocks."""
    both = _partial("Python analysis did not complete: detector sql_injection: A; detector taint_flow: B")
    assert not _decide(_diff((1, 1)), staged=both).ok


def test_non_python_partial_module_blocks() -> None:
    """A partial module of another language is never covered by a python entry."""
    assert not _decide(_diff((1, 1)), staged=_partial(language="rust")).ok


def test_head_blob_not_partial_blocks() -> None:
    """If HEAD scans clean, the partial scan is new and not covered by the pre-existing exemption."""
    d = _decide(_diff((1, 1)), head=_clean())
    assert not d.ok and "HEAD" in d.message


def test_head_blob_partial_with_other_detector_blocks() -> None:
    """HEAD partial with a different detector than the entry blocks."""
    other = _partial("Python analysis did not complete: detector taint_flow: x")
    assert not _decide(_diff((1, 1)), head=other).ok


def test_missing_head_scan_blocks() -> None:
    """A new file (no HEAD blob, so no HEAD report or text) blocks."""
    d = gate.decide(FILE, _entry(), _partial(), None, None, _diff((1, 1)))
    assert not d.ok


def test_staged_report_not_partial_nor_clean_blocks() -> None:
    """An unrecognised status is neither a clean scan nor a partial one: block."""
    assert not _decide(_diff((1, 1)), staged={"status": "error", "failed_modules": []}).ok
    assert not _decide(_diff((1, 1)), staged={"status": "partial"}).ok


def test_partial_report_naming_no_detector_blocks() -> None:
    """A partial message without a detector name cannot be matched to an entry."""
    assert not _decide(_diff((1, 1)), staged=_partial("Python analysis did not complete")).ok


def test_anchor_matching_two_lines_blocks() -> None:
    """An ambiguous anchor (docstring plus call, like rotator.py) is refused instead of picking the first match."""
    text = _head_text() + "    docstring mentions " + ANCHOR + "\n"
    assert not _decide(_diff((1, 1)), head_text=text).ok


def test_anchor_matching_no_line_blocks() -> None:
    """An anchor that no longer exists in the HEAD blob blocks."""
    assert not _decide(_diff((1, 1)), head_text="nothing here\n").ok


def test_allow_file_parses_entries_and_comments() -> None:
    """Comments and blank lines are skipped; a well-formed line becomes an Entry."""
    entries = gate.parse_allow("# header\n\n" + "\t".join([FILE, "sql_injection", ANCHOR, "why"]) + "\n")
    assert entries[FILE].detector == "sql_injection" and entries[FILE].anchor == ANCHOR and entries[FILE].reason == "why"


@pytest.mark.parametrize(
    "bad",
    [
        "a.py\tsql_injection\tanchor\n",
        "a.py\tsql_injection\tanchor\treason\textra\n",
        "a.py\t\tanchor\treason\n",
        "a.py\tsql inj\tanchor\treason\n",
        "a.py\tsql_injection\tanchor\treason\na.py\tsql_injection\tanchor2\treason\n",
        "a.py sql_injection anchor reason\n",
    ],
)
def test_malformed_allow_file_raises(bad: str) -> None:
    """Wrong field count, empty field, bad detector name, duplicate path or spaces instead of tabs all raise GateError."""
    with pytest.raises(gate.GateError):
        gate.parse_allow(bad)


def test_main_blocks_on_malformed_allow_file(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """main() returns 1 (block) when the allow file is malformed, before it looks at anything else."""
    allow = tmp_path / "allow.tsv"
    allow.write_text("only one field\n", encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_partial()), encoding="utf-8")
    assert gate.main(["--allow", str(allow), "--report", str(report)]) == 1
    assert "allow file line 1" in capsys.readouterr().out


def test_main_blocks_on_missing_allow_file(tmp_path: Path) -> None:
    """main() returns 1 when the allow file cannot be read."""
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_partial()), encoding="utf-8")
    assert gate.main(["--allow", str(tmp_path / "absent.tsv"), "--report", str(report)]) == 1


def test_main_blocks_when_overall_report_is_not_partial(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Exit 2 with a clean or unparsable staged report is not a partial scan: block."""
    allow = tmp_path / "allow.tsv"
    allow.write_text("# empty\n", encoding="utf-8")
    report = tmp_path / "report.json"
    report.write_text(json.dumps(_clean()), encoding="utf-8")
    assert gate.main(["--allow", str(allow), "--report", str(report)]) == 1
    report.write_text("not json", encoding="utf-8")
    assert gate.main(["--allow", str(allow), "--report", str(report)]) == 1
    assert "not a partial scan" in capsys.readouterr().out


def test_tracked_allow_file_entry_matches_exactly_one_rotator_line() -> None:
    """The shipped entry parses, and its anchor selects one line of rotator.py (the call, not the docstring mention)."""
    entries = gate.parse_allow(ALLOW.read_text(encoding="utf-8"))
    entry = entries["scripts/oauth_rotator/rotator.py"]
    assert entry.detector == "sql_injection" and "TRDD-H7884ERZ" in entry.reason
    assert gate.anchor_line(ROTATOR.read_text(encoding="utf-8"), entry.anchor) > 1000


_MINI = [
    "import sqlite3",
    "",
    "",
    "def refresh(blob, on_failure=None):",
    "    if on_failure:",
    "        on_failure(\"x\")",
    "",
    "",
    "def tick(db, blob):",
    "    causes: list[str] = []",
    "    fresh = refresh(blob, on_failure=causes.append)",
    "    con = sqlite3.connect(db)",
    "    return con.execute(\"SELECT 1\").fetchall(), causes, fresh",
]


@pytest.mark.real_subprocess("git", "ubs", os.path.basename(sys.executable))
def test_end_to_end_real_ubs_and_git(tmp_path: Path) -> None:
    """Real helper, real git, real ubs on a tiny repo: an edit above the anchor passes, an edit below it blocks."""
    if not (exe("ubs") != "ubs" and exe("git") != "git"):
        pytest.skip("ubs or git is not installed")
    repo = tmp_path / "repo"
    repo.mkdir()
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}

    def git(*args: str) -> None:
        subprocess.run([exe("git", env), *args], cwd=repo, env=env, capture_output=True, check=True)

    def run_gate() -> subprocess.CompletedProcess[str]:
        report = tmp_path / "staged.json"
        ubs = subprocess.run([exe("ubs", env), "--staged", "--format=json", f"--report-json={report}"], cwd=repo, env=env, capture_output=True, text=True, check=False, timeout=120)
        assert ubs.returncode == 2, ubs.stdout[-500:]
        return subprocess.run([sys.executable, str(HELPER), "--allow", str(allow), "--report", str(report)], cwd=repo, env=env, capture_output=True, text=True, check=False, timeout=240)

    git("init", "-q", "-b", "main")
    git("config", "user.name", "Test")
    git("config", "user.email", "test" + "@" + "users.noreply.github.com")
    git("config", "commit.gpgsign", "false")
    target = repo / "mod.py"
    target.write_text("\n".join(_MINI) + "\n", encoding="utf-8")
    git("add", "mod.py")
    git("commit", "-q", "-m", "base")
    allow = tmp_path / "allow.tsv"
    allow.write_text("\t".join(["mod.py", "sql_injection", "refresh(blob, on_failure=causes.append)", "TRDD-H7884ERZ end-to-end test"]) + "\n", encoding="utf-8")

    above = list(_MINI)
    above[0] = "import sqlite3  # edited above the anchor"
    target.write_text("\n".join(above) + "\n", encoding="utf-8")
    git("add", "mod.py")
    passed = run_gate()
    assert passed.returncode == 0, passed.stdout + passed.stderr
    assert "mod.py" in passed.stdout and "sql_injection" in passed.stdout

    below = list(_MINI)
    below[-1] = below[-1].replace("SELECT 1", "SELECT 2")
    target.write_text("\n".join(below) + "\n", encoding="utf-8")
    git("add", "mod.py")
    blocked = run_gate()
    assert blocked.returncode == 1, blocked.stdout + blocked.stderr
    assert "mod.py" in blocked.stdout and "sql_injection" in blocked.stdout
