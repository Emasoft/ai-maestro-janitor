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
the sentinel and commits the file ITSELF via porcelain
`git commit --only -- .claude/settings.json`. Committing a file the janitor
just wrote is a zero-judgment mechanical action — it does not need the main
Claude turn (owner directive 2026-08-11). The commit is refused (never
forced) whenever the repo is mid-merge/mid-rebase/mid-cherry-pick or HEAD is
detached, since an unexpected commit in that state could do real harm; the
janitor never pushes.

No flock coordination, no hook installation, no signing detection logic —
each commit runs with `GIT_OPTIONAL_LOCKS=0` (janitor#245) and only ever
touches the one whitelisted path.

Architecture:
  - Detector parent (every heartbeat):
    1. If commit-pending sentinel exists AND settings.json is dirty
       → refuse-check the repo state; if safe, commit `.claude/settings.json`
       directly (silent on success); if unsafe, print one drift line and
       leave the file uncommitted → delete sentinel → return.
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

  - Whitelist: ONLY `.claude/settings.json` is ever committed. The user's
    other staged/unstaged files are untouched. The janitor never pushes.

Output:
  Silent on a successful commit. Prints exactly one drift line only when
  the commit was refused (unsafe repo state). Logs every spawn/skip/
  sentinel/commit event to `.janitor/logs/project-plugins-update.log`.
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
        # Read-only: GIT_OPTIONAL_LOCKS=0 so `git status` never takes
        # .git/index.lock and collides with a concurrent `publish.py` commit
        # (janitor#245 — the named repro site for exactly this call shape).
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        proc = subprocess.run(
            ["git", "-C", str(project_root), "status", "--porcelain",
             "--", SETTINGS_REL_PATH],
            capture_output=True, text=True, timeout=15, check=False,
            env=git_env,
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


def _resolve_git_dir(project_root: Path) -> Path | None:
    """The repo's `.git` dir (resolved through worktrees), or None on
    any failure to ask git. Read-only; used only to inspect state files
    (MERGE_HEAD, rebase-merge/, ...), never written to."""
    try:
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        proc = subprocess.run(
            ["git", "-C", str(project_root), "rev-parse", "--git-dir"],
            capture_output=True, text=True, timeout=15, check=False,
            env=git_env,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    raw = proc.stdout.strip()
    if not raw:
        return None
    git_dir = Path(raw)
    if not git_dir.is_absolute():
        git_dir = project_root / git_dir
    return git_dir


def _commit_blocked_reason(project_root: Path) -> str | None:
    """None iff it is safe to commit right now. Otherwise a short,
    human-readable reason the commit must be refused (mid-merge,
    mid-rebase, mid-cherry-pick, or a detached HEAD) — fail safe toward
    NOT committing when repo state can't be established cleanly."""
    git_dir = _resolve_git_dir(project_root)
    if git_dir is None:
        return "could not resolve git dir"
    if (git_dir / "MERGE_HEAD").exists():
        return "a merge is in progress"
    if (git_dir / "rebase-merge").exists() or (git_dir / "rebase-apply").exists():
        return "a rebase is in progress"
    if (git_dir / "CHERRY_PICK_HEAD").exists():
        return "a cherry-pick is in progress"
    try:
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        proc = subprocess.run(
            ["git", "-C", str(project_root), "symbolic-ref", "-q", "HEAD"],
            capture_output=True, text=True, timeout=15, check=False,
            env=git_env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return f"could not determine HEAD state ({exc})"
    if proc.returncode != 0:
        return "HEAD is detached"
    return None


def _commit_settings(project_root: Path, plugin_ids: list[str]) -> tuple[bool, str]:
    """Commit ONLY `.claude/settings.json`, scoped via `--only --`, with
    the formulaic message. Never pushes. `(ok, detail)` — detail is a
    log-friendly reason on failure, or "committed" on success."""
    msg_body = "janitor chore: commit the updated plugins"
    if plugin_ids:
        msg_body += "\n\nplugins updated:\n" + "\n".join(f"  - {p}" for p in plugin_ids)
    try:
        git_env = dict(os.environ)
        git_env["GIT_OPTIONAL_LOCKS"] = "0"
        proc = subprocess.run(
            ["git", "-C", str(project_root), "commit", "--only", "-m", msg_body,
             "--", SETTINGS_REL_PATH],
            capture_output=True, text=True, timeout=30, check=False,
            env=git_env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, f"git commit failed to run: {exc}"
    if proc.returncode != 0:
        detail = (proc.stderr.strip() or proc.stdout.strip() or f"exit {proc.returncode}")
        return False, f"git commit exited {proc.returncode}: {detail}"
    return True, "committed"


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
            blocked = _commit_blocked_reason(project_root)
            if blocked is not None:
                # Fail safe toward NOT committing — surface it so a human
                # can resolve the repo state, then leave the file dirty.
                print(
                    f"[project-plugins-commit-skipped] .claude/settings.json left "
                    f"uncommitted — {blocked}"
                )
                state.log_line("project-plugins-update", f"commit refused: {blocked}")
            else:
                ok, detail = _commit_settings(project_root, plugin_ids)
                if ok:
                    state.log_line(
                        "project-plugins-update",
                        f"committed settings.json for {len(plugin_ids)} plugin(s)",
                    )
                else:
                    print(
                        f"[project-plugins-commit-failed] could not commit "
                        f".claude/settings.json — {detail}"
                    )
                    state.log_line("project-plugins-update", f"commit failed: {detail}")
            # Remove sentinel either way; if the file is still dirty (refused
            # or failed), the next worker run will re-detect it and write a
            # fresh sentinel, so nothing is silently dropped.
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
                # detached_uv_env: the worker's `uv run --script` shebang must not
                # inherit this process's (possibly ephemeral) VIRTUAL_ENV — a dangling
                # one kills the worker before its first line (TRDD-UO93APWN).
                env=state.detached_uv_env(),
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
