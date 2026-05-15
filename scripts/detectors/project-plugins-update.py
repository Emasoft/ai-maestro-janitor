#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Project-plugins-update detector — Track 2b of the auto-update directive.

Updates PROJECT-scope plugins enabled in `<project>/.claude/settings.json`
every heartbeat. Per-project, per-janitor.

This is the only track that may need to commit to git — `.claude/settings.json`
is git-tracked (project scope = team-shared infrastructure). When the worker
detects that `claude plugin update --scope project` changed settings.json, it
writes a sentinel file; the parent detector on a subsequent heartbeat reads
the sentinel and emits a drift line containing the EXACT git commit command
that Claude should execute, using porcelain `git commit --only -- ...`. Claude
running the command uses the user's git config naturally:
  - Signing happens if `commit.gpgsign = true` is set.
  - Pre-commit / commit-msg hooks fire normally.
  - Branch protection rules (signed commits, signed tags) are honored
    because we never bypass git's normal commit infrastructure.

No flock coordination, no hook installation, no signing detection logic —
the AI agent in the heartbeat turn is the writer, and it shares the user's
git config + branch protection rules transparently.

Architecture:
  - Detector parent (every heartbeat):
    1. If commit-pending sentinel exists AND settings.json is dirty
       → emit drift line + delete sentinel + return (don't spawn another
       worker until this commit lands).
    2. If sentinel exists but settings.json clean (commit already done)
       → delete sentinel + return.
    3. If prior worker still alive → log skip + return.
    4. Else → spawn detached worker → return.

  - Detector worker (detached child):
    1. Read settings.json, filter `enabledPlugins` to entries with true.
    2. For each enabled plugin: `claude plugin update <id> --scope project`.
    3. After all updates: `git status --porcelain -- .claude/settings.json`.
       If dirty: write commit-pending sentinel + plugin-list file.
    4. Exit.

  - Whitelist: ONLY `.claude/settings.json` is ever named in the drift
    line. The user's other staged/unstaged files are untouched.

Output:
  Silent except when commit-pending sentinel resolves to a real
  drift line. Logs every spawn/skip/sentinel-event to
  `.janitor/logs/project-plugins-update.log`.
"""

from __future__ import annotations

import errno
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import state  # noqa: E402

PID_FILENAME = "project-plugins-update.pid"
SENTINEL_FILENAME = "project-plugins-update.commit-pending"
LAST_UPDATED_FILENAME = "project-plugins-update.last-updated.txt"
SETTINGS_REL_PATH = ".claude/settings.json"


def _read_pid(pid_path: Path) -> int | None:
    try:
        raw = pid_path.read_text(encoding="utf-8").strip()
    except (FileNotFoundError, OSError):
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        if exc.errno in (errno.ESRCH, errno.EPERM):
            return False
        return False
    return True


def _write_pid_atomic(pid_path: Path, pid: int) -> None:
    tmp = pid_path.with_suffix(pid_path.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(str(pid), encoding="utf-8")
    os.replace(tmp, pid_path)


def _settings_is_dirty(project_root: Path) -> bool:
    """True iff git considers `.claude/settings.json` modified vs HEAD."""
    settings = project_root / SETTINGS_REL_PATH
    if not settings.is_file():
        return False
    try:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain",
             "--", SETTINGS_REL_PATH],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return False
    if proc.returncode != 0:
        return False
    return bool(proc.stdout.strip())


def _enabled_project_plugins(settings_path: Path) -> list[str]:
    try:
        raw = settings_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    except OSError as exc:
        state.log_line("project-plugins-update", f"settings.json read failed: {exc}")
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        state.log_line(
            "project-plugins-update",
            f"settings.json malformed JSON ({exc}) — skipping",
        )
        return []
    if not isinstance(data, dict):
        return []
    enabled_plugins = data.get("enabledPlugins")
    if not isinstance(enabled_plugins, dict):
        return []
    result: list[str] = []
    for plugin_id, flag in enabled_plugins.items():
        if isinstance(plugin_id, str) and plugin_id and flag is True:
            result.append(plugin_id)
    return result


def _run_worker() -> int:
    """Detached worker: update enabled project-scope plugins; on
    settings.json change, write a commit-pending sentinel for the
    parent detector to surface on the next heartbeat."""
    state.init_state()
    project_root = state.project_root()
    settings_path = project_root / SETTINGS_REL_PATH
    log_path = state.log_dir() / "project-plugins-update.log"
    sentinel_path = state.state_dir() / SENTINEL_FILENAME
    last_updated_path = state.state_dir() / LAST_UPDATED_FILENAME

    plugin_ids = _enabled_project_plugins(settings_path)
    if not plugin_ids:
        state.log_line(
            "project-plugins-update",
            "[worker] no enabled project-scope plugins (settings.json missing or empty)",
        )
        return 0

    state.log_line(
        "project-plugins-update",
        f"[worker] updating {len(plugin_ids)} enabled project-scope plugin(s)",
    )

    updated_ids: list[str] = []
    for plugin_id in plugin_ids:
        try:
            with log_path.open("a", encoding="utf-8") as logf:
                logf.write(f"--- {plugin_id} ---\n")
                proc = subprocess.run(
                    ["claude", "plugin", "update", plugin_id, "--scope", "project"],
                    stdout=logf, stderr=subprocess.STDOUT,
                    timeout=120, check=False,
                )
            if proc.returncode == 0:
                updated_ids.append(plugin_id)
        except subprocess.TimeoutExpired:
            state.log_line("project-plugins-update", f"[worker] update timed out: {plugin_id}")
        except OSError as exc:
            state.log_line("project-plugins-update", f"[worker] update failed: {plugin_id} ({exc})")

    if _settings_is_dirty(project_root):
        state.log_line(
            "project-plugins-update",
            f"[worker] settings.json dirty after sweep — writing commit-pending sentinel "
            f"for {len(updated_ids)} plugin(s)",
        )
        try:
            last_updated_path.write_text("\n".join(updated_ids) + "\n", encoding="utf-8")
            sentinel_path.write_text("1", encoding="utf-8")
        except OSError as exc:
            state.log_line("project-plugins-update", f"[worker] sentinel write failed: {exc}")
    else:
        state.log_line(
            "project-plugins-update",
            "[worker] settings.json clean after sweep — no commit needed",
        )

    return 0


def _emit_commit_drift(plugin_ids: list[str]) -> None:
    """Write the drift line to stdout so the heartbeat surfaces it to
    Claude, who will then run the exact git commit command."""
    plugin_list_inline = ", ".join(plugin_ids) if plugin_ids else "(unknown)"
    # Single-line drift line for parseability + the exact command on its
    # own line below so Claude can copy-paste-execute. Stay within the
    # convention of other janitor drift lines ([detector] message).
    summary = (
        f"[project-plugins-commit-needed] {len(plugin_ids)} project-scope plugin(s) "
        f"updated: {plugin_list_inline}. Commit `.claude/settings.json` now with the "
        f"formulaic message. Run exactly:"
    )
    msg_body = "janitor chore: commit the updated plugins"
    if plugin_ids:
        msg_body += "\n\nplugins updated:\n" + "\n".join(f"  - {p}" for p in plugin_ids)
    # Use $'...' bash quoting so embedded newlines survive the shell.
    msg_bash = msg_body.replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n")
    command = (
        f"git commit --only -- {SETTINGS_REL_PATH} -m $'{msg_bash}'"
    )
    print(summary)
    print(command)


def main() -> int:
    if "--worker" in sys.argv[1:]:
        return _run_worker()

    state.init_state()
    project_root = state.project_root()
    log_path = state.log_dir() / "project-plugins-update.log"
    pid_path = state.state_dir() / PID_FILENAME
    sentinel_path = state.state_dir() / SENTINEL_FILENAME
    last_updated_path = state.state_dir() / LAST_UPDATED_FILENAME
    settings_path = project_root / SETTINGS_REL_PATH

    if shutil.which("claude") is None:
        state.log_line("project-plugins-update", "claude CLI not in PATH — skipping")
        return 0

    # Pending-commit sentinel takes priority — surface it before
    # spawning another worker, so the heartbeat turn can commit the
    # previous round before we kick off the next.
    if sentinel_path.is_file():
        if _settings_is_dirty(project_root):
            try:
                raw = last_updated_path.read_text(encoding="utf-8")
                plugin_ids = [line for line in raw.splitlines() if line.strip()]
            except OSError:
                plugin_ids = []
            _emit_commit_drift(plugin_ids)
            state.log_line(
                "project-plugins-update",
                f"surfaced commit-needed drift for {len(plugin_ids)} plugin(s)",
            )
            # Remove sentinel; if Claude doesn't commit before next
            # heartbeat (e.g. user rejected the command), the next
            # worker run will re-detect and re-emit if still dirty.
            try:
                sentinel_path.unlink()
            except OSError:
                pass
        else:
            # Sentinel stale (commit already happened) — clear it.
            state.log_line(
                "project-plugins-update",
                "sentinel present but settings.json clean — clearing stale sentinel",
            )
            try:
                sentinel_path.unlink()
            except OSError:
                pass
            try:
                last_updated_path.unlink()
            except OSError:
                pass
        return 0

    # Settings file missing → no project-scope plugins → bail.
    if not settings_path.is_file():
        state.log_line(
            "project-plugins-update",
            "no .claude/settings.json — nothing to update",
        )
        return 0

    prior_pid = _read_pid(pid_path)
    if prior_pid is not None and _pid_alive(prior_pid):
        state.log_line(
            "project-plugins-update",
            f"prior worker still running (pid {prior_pid}) — skipping",
        )
        return 0

    state.log_line("project-plugins-update", "spawning detached worker")
    try:
        logf = log_path.open("a", encoding="utf-8")
        try:
            proc = subprocess.Popen(
                [str(Path(__file__).resolve()), "--worker"],
                stdout=logf,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        finally:
            logf.close()
    except OSError as exc:
        state.log_line("project-plugins-update", f"spawn failed: {exc}")
        return 0

    try:
        _write_pid_atomic(pid_path, proc.pid)
    except OSError as exc:
        state.log_line("project-plugins-update", f"pid-file write failed: {exc}")

    state.log_line(
        "project-plugins-update",
        f"spawned worker (pid {proc.pid}) — will run async",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
