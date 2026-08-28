#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""/janitor-doctor backing script — Python port of doctor.sh.

Runs a series of named pass/fail checks and prints a unicode-bordered
table. Exits 0 if all pass, 1 if any fail. Stdout is structured for
direct rendering inside Claude Code's markdown surface; no ANSI colour
(the user's terminal may not support it; the unicode markers carry the
signal alone).

Each check returns (status, detail, fix) where status is PASS, FAIL, or
WARN.

Status taxonomy:
  PASS — check passed, no action needed
  FAIL — hard failure: the janitor cannot operate at all (missing
         scripts, unreadable state dir, plugin.json corrupt). Exits 1.
  WARN — soft failure: a specific subsystem is degraded but the rest of
         the janitor still works (e.g. gh not authenticated → only
         pr-reconciler / task-pr-mismatch silently skip). Counted, fix
         hint shown, but does NOT change the exit code.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_PLUGIN_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_PLUGIN_ROOT / "scripts" / "lib"))

import state  # noqa: E402

CheckResult = tuple[str, str, str, str]  # (name, status, detail, fix)


_DETECTORS = (
    "pr-reconciler", "worktree-janitor", "trdd-drift", "trdd-reminder",
    "task-pr-mismatch", "stale-task", "dirty-tree", "subagent-report",
    "version-update", "trashcan-purge", "remote-credentials", "stale-stash",
    "nested-git-safety", "tracked-ignored", "plugin-updates",
    "mcp-config-drift", "settings-scope-drift", "subagent-scope-drift",
    "claude-md-scope-drift", "cross-scope-reference-drift",
)


def _check_restricted_mode() -> CheckResult:
    """CC 2.1.248+ `--restricted` (or `CLAUDE_CODE_RESTRICTED=1`) strips Bash and ignores
    settings-file hooks. Every janitor surface — the heartbeat dispatcher stub, every hook
    guard, most skills — shells out or relies on a settings-file hook, so under restricted
    mode the janitor is inert. A silently-absent guardian is worse than one that says so.

    The predicate lives in `state.restricted_mode()` so this row and `arm_prepare`'s refusal
    can never disagree about what counts as restricted."""
    if not state.restricted_mode():
        return ("restricted-mode", "PASS", "session is not in --restricted mode", "")
    return (
        "restricted-mode", "FAIL",
        "--restricted mode active — Bash removed, settings-file hooks ignored",
        "The heartbeat, dispatcher stub, and every hook guard cannot run this session; "
        "relaunch without --restricted / CLAUDE_CODE_RESTRICTED to restore protection",
    )


def _check_state_dir_writable() -> CheckResult:
    sd = state.state_dir()
    if sd.is_dir() and os.access(sd, os.W_OK):
        return ("state-dir-writable", "PASS", f"{sd} exists and is writable", "")
    return (
        "state-dir-writable",
        "FAIL",
        f"{sd} not writable",
        "Run /janitor-arm to bootstrap state, or check directory permissions",
    )


def _check_log_dir_writable() -> CheckResult:
    ld = state.log_dir()
    if ld.is_dir() and os.access(ld, os.W_OK):
        return ("log-dir-writable", "PASS", f"{ld} exists and is writable", "")
    return (
        "log-dir-writable",
        "FAIL",
        f"{ld} not writable",
        "Run /janitor-arm to bootstrap, or check directory permissions",
    )


def _check_dispatch_executable() -> CheckResult:
    p = _PLUGIN_ROOT / "scripts" / "dispatch.py"
    if p.is_file() and os.access(p, os.X_OK):
        return ("dispatch-executable", "PASS", "scripts/dispatch.py is executable", "")
    return (
        "dispatch-executable",
        "FAIL",
        "scripts/dispatch.py missing or not executable",
        "Reinstall the plugin via /plugin install ai-maestro-janitor",
    )


def _check_detectors_executable() -> CheckResult:
    missing: list[str] = []
    for name in _DETECTORS:
        p = _PLUGIN_ROOT / "scripts" / "detectors" / f"{name}.py"
        if not (p.is_file() and os.access(p, os.X_OK)):
            missing.append(name)
    if not missing:
        return ("detectors-executable", "PASS", "all detectors present and executable", "")
    return (
        "detectors-executable",
        "FAIL",
        f"missing/non-executable: {', '.join(missing)}",
        "Reinstall the plugin via /plugin install ai-maestro-janitor",
    )


def _check_libs_present() -> CheckResult:
    missing: list[str] = []
    for lib in ("state.py", "dedupe.py", "git_utils.py"):
        if not (_PLUGIN_ROOT / "scripts" / "lib" / lib).is_file():
            missing.append(lib)
    if not missing:
        return ("libs-present", "PASS", "scripts/lib/{state,dedupe,git_utils}.py all present", "")
    return (
        "libs-present",
        "FAIL",
        f"missing in scripts/lib/: {', '.join(missing)}",
        "Reinstall the plugin — detectors will fail to import missing libs",
    )


def _check_git_available() -> CheckResult:
    if shutil.which("git") is None:
        return ("git-available", "FAIL", "git not in PATH", "Install git — most detectors require it")
    # `--version` never touches a repo (no cwd, no .git/ involved), so it can never
    # take .git/index.lock either — but GIT_OPTIONAL_LOCKS=0 is harmless here too,
    # and setting it uniformly is what keeps this file's drift guard (janitor#245,
    # tests/test_git_optional_locks_guard.py) simple: every read-only git call in
    # this module carries it, with no "except this one, it's provably safe" carve-out.
    git_env = dict(os.environ)
    git_env["GIT_OPTIONAL_LOCKS"] = "0"
    proc = subprocess.run(
        ["git", "--version"], capture_output=True, text=True, check=False, env=git_env
    )
    version = proc.stdout.splitlines()[0] if proc.stdout else "unknown"
    return ("git-available", "PASS", f"git in PATH ({version})", "")


def _check_in_git_repo() -> CheckResult:
    # Read-only: GIT_OPTIONAL_LOCKS=0 so this never takes .git/index.lock and
    # collides with a concurrent `publish.py` commit (janitor#245).
    git_env = dict(os.environ)
    git_env["GIT_OPTIONAL_LOCKS"] = "0"
    proc = subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(state.project_root()),
        capture_output=True, text=True, check=False,
        env=git_env,
    )
    if proc.returncode == 0:
        return ("in-git-repo", "PASS", f"{state.project_root()} is a git repo", "")
    return (
        "in-git-repo",
        "FAIL",
        f"{state.project_root()} is NOT a git repo",
        "Most detectors will silently skip — run /janitor-doctor in a git project",
    )


def _check_gh_authenticated() -> CheckResult:
    if shutil.which("gh") is None:
        return (
            "gh-authenticated", "WARN", "gh CLI not in PATH",
            "Install gh + 'gh auth login' — pr-reconciler / task-pr-mismatch silently skip without it",
        )
    proc = subprocess.run(["gh", "auth", "status"], capture_output=True, text=True, check=False)
    if proc.returncode == 0:
        return ("gh-authenticated", "PASS", "gh CLI is authenticated", "")
    return (
        "gh-authenticated", "WARN", "gh CLI not authenticated",
        "Run 'gh auth login' — pr-reconciler / task-pr-mismatch silently skip without it",
    )


def _check_jq_available() -> CheckResult:
    """jq is no longer required (detectors use Python's stdlib json) but
    is still useful for the plugin-json-valid check fallback path. We
    surface it as a soft INFO only if missing, never a WARN."""
    if shutil.which("jq") is None:
        return (
            "jq-available", "PASS", "jq not in PATH (Python detectors use stdlib json — fine)",
            "",
        )
    proc = subprocess.run(["jq", "--version"], capture_output=True, text=True, check=False)
    version = proc.stdout.splitlines()[0] if proc.stdout else "unknown"
    return ("jq-available", "PASS", f"jq in PATH ({version})", "")


def _check_uv_available() -> CheckResult:
    """uv is required: every Python script uses `uv run --script` shebang."""
    if shutil.which("uv") is None:
        return (
            "uv-available", "FAIL", "uv not in PATH",
            "Install uv (https://docs.astral.sh/uv/) — every detector uses uv run --script",
        )
    proc = subprocess.run(["uv", "--version"], capture_output=True, text=True, check=False)
    version = proc.stdout.splitlines()[0] if proc.stdout else "unknown"
    return ("uv-available", "PASS", f"uv in PATH ({version})", "")


def _check_gitignore_reports() -> CheckResult:
    gi = state.project_root() / ".gitignore"
    if not gi.is_file():
        return (
            "gitignore-reports", "FAIL", ".gitignore missing at project root",
            "Create .gitignore and add /reports/ + /reports_dev/",
        )
    try:
        lines = set(gi.read_text().splitlines())
    except OSError:
        lines = set()
    missing = [r for r in ("/reports/", "/reports_dev/") if r not in lines]
    if not missing:
        return ("gitignore-reports", "PASS", "/reports/ and /reports_dev/ both gitignored", "")
    return (
        "gitignore-reports", "FAIL", f"missing in .gitignore: {', '.join(missing)}",
        "Add the missing entries to .gitignore — agents write reports there and they may contain private data",
    )


def _check_plugin_json_valid() -> CheckResult:
    pj = _PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    if not pj.is_file():
        return ("plugin-json-valid", "FAIL", ".claude-plugin/plugin.json missing", "Reinstall the plugin")
    try:
        with pj.open("r", encoding="utf-8") as f:
            json.load(f)
    except (OSError, json.JSONDecodeError):
        return ("plugin-json-valid", "FAIL", "plugin.json is not valid JSON", "Restore from a clean install")
    return ("plugin-json-valid", "PASS", "plugin.json parses as valid JSON", "")


def _render_table(rows: list[CheckResult]) -> None:
    """Render a unicode-bordered table sized for an 80-col terminal."""
    HDR_TOP = "┏━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓"
    HDR_MID = "┡━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩"
    HDR_BOT = "└──────────────────────┴────────┴──────────────────────────────────────────────┘"
    ROW_SEP = "├──────────────────────┼────────┼──────────────────────────────────────────────┤"

    print(HDR_TOP)
    print(f"┃ {'Check':<20} ┃ {'Status':<6} ┃ {'Detail':<44} ┃")
    print(HDR_MID)
    for i, (name, status, detail, _fix) in enumerate(rows):
        if i > 0:
            print(ROW_SEP)
        print(f"│ {name[:20]:<20} │ {status:<6} │ {detail[:44]:<44} │")
    print(HDR_BOT)


def main() -> int:
    state.init_state()

    rows: list[CheckResult] = [
        _check_restricted_mode(),
        _check_state_dir_writable(),
        _check_log_dir_writable(),
        _check_dispatch_executable(),
        _check_detectors_executable(),
        _check_libs_present(),
        _check_uv_available(),
        _check_git_available(),
        _check_in_git_repo(),
        _check_gh_authenticated(),
        _check_jq_available(),
        _check_gitignore_reports(),
        _check_plugin_json_valid(),
    ]

    pass_count = sum(1 for _, s, _, _ in rows if s == "PASS")
    warn_count = sum(1 for _, s, _, _ in rows if s == "WARN")
    fail_count = sum(1 for _, s, _, _ in rows if s == "FAIL")
    total = pass_count + warn_count + fail_count

    _render_table(rows)

    if fail_count > 0 or warn_count > 0:
        print("\nFix hints:")
        for name, status, _detail, fix in rows:
            if status != "PASS" and fix:
                print(f"  • [{status}] {name}: {fix}")

    # Exit code is gated on FAIL only — WARN rows surface in the report
    # but do not block.
    if fail_count == 0 and warn_count == 0:
        print(f"\n{pass_count}/{total} passed. All green.")
        return 0
    if fail_count == 0:
        print(f"\n{pass_count}/{total} passed, {warn_count} warning(s) — janitor still operational.")
        return 0
    suffix = f", {warn_count} warned" if warn_count else ""
    print(f"\n{pass_count}/{total} passed ({fail_count} failed{suffix}).")
    return 1


if __name__ == "__main__":
    sys.exit(main())
