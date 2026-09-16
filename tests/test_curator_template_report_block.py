"""Tests for the report-path/set-report bash block in janitor-memory-subconscious-agent.md.

Extracts the exact fenced ```bash block (the one calling report-path) from the agent
markdown, patches in a real header + PASS=repair, and runs it against a stub
memory_dispatch_claim.py to prove the read-back/retry/fallback/FATAL-guard logic behaves
as documented, without needing the real claim machinery.
"""

import os
import re
import stat
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
AGENT_MD = REPO_ROOT / "agents" / "janitor-memory-subconscious-agent.md"

HEADER_LINES = (
    "# repair pass — LOCAL scope\n"
    "Claim: dispatch_id=1000000-abcd1234, scope=LOCAL, root=/x"
)

PLACEHOLDER = "<PASTE THE TWO HEADER LINES YOUR CLAIM STEP PRINTED, VERBATIM, IN PLACE OF THIS LINE>"

STUB = '''#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
import os
import sys


def main() -> int:
    args = sys.argv[1:]
    mode = os.environ.get("STUB_MODE", "chore-ok")
    if not args:
        return 1
    cmd, rest = args[0], args[1:]
    if cmd == "report-path":
        has_chore = "--chore" in rest
        if mode == "none":
            return 1
        if mode == "chore-miss" and has_chore:
            return 1
        idx = rest.index("--state-dir") + 1
        state_dir = rest[idx]
        print(os.path.join(state_dir, "report.md"))
        return 0
    if cmd == "set-report":
        with open(os.path.join(os.environ["STUB_LOG_DIR"], "stub.log"), "a") as fh:
            fh.write(" ".join(args) + "\\n")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
'''


def _extract_block() -> str:
    """Pull the exact fenced bash block (the one calling report-path) out of the agent md."""
    text = AGENT_MD.read_text()
    for match in re.finditer(r"```bash\n(.*?)\n```", text, re.DOTALL):
        if "report-path" in match.group(1):
            return match.group(1)
    raise AssertionError("report-path bash block not found in agent markdown")


def _run(tmp_path: Path, *, stub_mode: str, precreate: bool, fill_placeholder: bool) -> subprocess.CompletedProcess:
    block = _extract_block()
    if fill_placeholder:
        block = block.replace(PLACEHOLDER, HEADER_LINES)
    block = block.replace("PASS=consolidate", "PASS=repair", 1)

    state_dir = tmp_path / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    reports_dir = tmp_path / "reports" / "janitor-memory-subconscious-agent"
    reports_dir.mkdir(parents=True)

    plugin_root = tmp_path / "plugin"
    (plugin_root / "scripts").mkdir(parents=True)
    stub_path = plugin_root / "scripts" / "memory_dispatch_claim.py"
    stub_path.write_text(STUB)
    stub_path.chmod(stub_path.stat().st_mode | stat.S_IEXEC)

    if precreate:
        (state_dir / "report.md").write_text(HEADER_LINES)

    script_path = tmp_path / "block.sh"
    script_path.write_text(block)
    env = dict(os.environ)
    env["CLAUDE_PROJECT_DIR"] = str(tmp_path)
    env["STATE_DIR"] = str(state_dir)
    env["CLAUDE_PLUGIN_ROOT"] = str(plugin_root)
    env["STUB_MODE"] = stub_mode
    env["STUB_LOG_DIR"] = str(tmp_path)

    return subprocess.run(
        ["bash", "-e", str(script_path)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_chore_ok_reads_back_precreated_report(tmp_path):
    """report-path --chore succeeds first try: one report file, no retry stderr, one set-report call."""
    result = _run(tmp_path, stub_mode="chore-ok", precreate=True, fill_placeholder=True)
    assert result.returncode == 0, result.stderr
    assert "retrying without --chore" not in result.stderr
    report = tmp_path / ".janitor" / "state" / "report.md"
    assert report.is_file()
    log = (tmp_path / "stub.log").read_text()
    assert log.count("set-report") == 1
    assert str(report) in log


def test_chore_miss_retries_without_chore(tmp_path):
    """report-path --chore fails but the bare retry finds the same claim: retry logged, one set-report."""
    result = _run(tmp_path, stub_mode="chore-miss", precreate=True, fill_placeholder=True)
    assert result.returncode == 0, result.stderr
    assert "retrying without --chore" in result.stderr
    log = (tmp_path / "stub.log").read_text()
    assert log.count("set-report") == 1


def test_none_falls_back_to_created_file(tmp_path):
    """Both read-backs fail: the fallback creates exactly one report with the pasted header."""
    result = _run(tmp_path, stub_mode="none", precreate=False, fill_placeholder=True)
    assert result.returncode == 0, result.stderr
    reports_dir = tmp_path / "reports" / "janitor-memory-subconscious-agent"
    created = list(reports_dir.glob("*.md"))
    assert len(created) == 1
    content = created[0].read_text()
    assert "dispatch_id=1000000-abcd1234" in content
    log = (tmp_path / "stub.log").read_text()
    assert log.count("set-report") == 1
    assert str(created[0]) in log


def test_none_with_unfilled_placeholder_fails_fatal(tmp_path):
    """An unfilled placeholder trips the FATAL guard: non-zero exit, FATAL on stderr."""
    result = _run(tmp_path, stub_mode="none", precreate=False, fill_placeholder=False)
    assert result.returncode != 0
    assert "FATAL" in result.stderr
