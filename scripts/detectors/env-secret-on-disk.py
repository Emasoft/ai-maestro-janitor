#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""env-secret-on-disk: find the live secret values of this session's environment in the folders agents write to.

WHY (janitor issue #354, second event of its class): a command that prints a process environment, with its
output redirected into a scratch file, left the whole session environment on disk. The Bash guard lowers the
rate of that; this sweep catches what passes the guard, and it needs no pattern: the session knows its own
secrets exactly, so it searches for those bytes (scripts/lib/env_secrets.py).

REPORT-ONLY. It never rewrites, moves or deletes a file: in-place redaction of untracked files was left to the
owner (it is irreversible), and a hit in a tracked or staged file must be handled by a human anyway. A finding
carries the variable NAME, the path, the line and a keyed fingerprint, never the value. Rotating the secret is
the human's decision.

Limits, stated in every finding: an overwritten file can survive in snapshots and backups; a value that was
already printed into a conversation has already been sent; a secret that was transformed (compressed, split,
encrypted) is not found; the sweep reads files changed since the last pass, a few at a time, so a file moved
in with an old modification time is not seen until the cursor is reset.

It does NOT use state.is_self_scan_target(): that guard exists because pattern scanners flag the janitor's own
fixtures, and an exact-value matcher has no fixtures to match. Skipping the janitor's own repo would blind the
sweep exactly where agents write the most scratch.

ON DEMAND, right after a slip: run this file directly (`uv run <plugin>/scripts/detectors/env-secret-on-disk.py`). For a full pass
from the oldest file, delete `.janitor/state/env-secret-on-disk.cursor.json` first (regenerated state); each run
still reads at most one budget of files, so repeat it until the log line says 0 left for the next pass.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import env_secrets  # noqa: E402
import global_state  # noqa: E402
import issue_catalog  # noqa: E402
import state  # noqa: E402

_NAME = "env-secret-on-disk"
_SALT_FILE = "env-secret-fingerprint.salt"
# Folders that a cloud client mirrors to other machines: a copy of a secret there has left this host.
_SYNCED_MARKERS = ("/Library/Mobile Documents/", "/Dropbox", "/Google Drive", "/GoogleDrive", "/OneDrive", "/iCloud")
_PATH_SHOWN = 60  # issue_catalog rejects an identifier field over 64 characters
_GIT_RETRY_KEY = "git ls-files"  # the retries entry of a failing git: not a path, so no file can collide with it


def _load_salt() -> bytes:
    """A random salt per installation, created once with owner-only permissions in the machine-wide state
    directory, so two findings of one secret can be joined without a hash that anyone can look up."""
    target = global_state.init_global_state() / _SALT_FILE
    if not target.exists():
        # Written to a private temp name and linked into place: a concurrent heartbeat of another project
        # either finds no file (and races to link its own, the loser keeps the winner's) or a COMPLETE one,
        # never a half-written salt.
        temporary = target.with_name(f"{_SALT_FILE}.{os.getpid()}")
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(os.urandom(32).hex())
        try:
            os.link(temporary, target)
        except FileExistsError:
            pass
        finally:
            temporary.unlink()  # this run's own temp file
    return bytes.fromhex(target.read_text(encoding="utf-8").strip())


def _git(project: Path, *args: str) -> subprocess.CompletedProcess[str]:
    # GIT_OPTIONAL_LOCKS=0: read-only, never takes .git/index.lock (janitor#245).
    return subprocess.run(
        ["git", *args], cwd=str(project), capture_output=True, text=True, check=False,
        env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )


def _untracked_files(project: Path) -> tuple[list[str], int | None]:
    """The untracked files, and the exit code of a `git ls-files` that failed in a project that HAS a .git.

    A failure used to read as "no untracked files", and the cursor moved past a leaking file that was never read.
    A folder with no .git has no untracked files to list, so that case is no failure."""
    proc = _git(project, "ls-files", "--others", "--exclude-standard", "-z")
    if proc.returncode != 0:
        return [], (proc.returncode if (project / ".git").exists() else None)
    return [str(project / name) for name in proc.stdout.split("\0") if name], None


def _file_status(project: Path, path: str) -> str:
    """Whether the file is in git: tracked, staged, untracked and ignored, untracked, or outside the project."""
    try:
        relative = os.path.relpath(path, project)
    except ValueError:
        return "outside the project"
    if relative.startswith(".."):
        return "outside the project"
    if _git(project, "ls-files", "--error-unmatch", "--", relative).returncode == 0:
        staged = _git(project, "diff", "--cached", "--name-only", "--", relative).stdout.strip()
        return "tracked and staged" if staged else "tracked"
    return "untracked and ignored" if _git(project, "check-ignore", "-q", "--", relative).returncode == 0 else "untracked"


def _portable(project: Path, path: str) -> str:
    """The path as a tracked proposal may carry it: relative inside the project, with the home folder written
    as ~ outside it, so no user name reaches design/proposals (git-tracked, pushed)."""
    relative = os.path.relpath(path, project)
    if not relative.startswith(".."):
        return relative
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def _display(project: Path, path: str) -> str:
    shown = _portable(project, path)
    return shown if len(shown) <= _PATH_SHOWN else "…" + shown[-(_PATH_SHOWN - 1):]


def _read_cursor(file: Path) -> dict:
    fresh: dict = {"cursor": [0.0, ""], "retries": {}, "flagged": []}
    if not file.exists():
        return fresh
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
        data["cursor"] = [float(data["cursor"][0]), str(data["cursor"][1])]
        data["retries"] = {str(k): int(v) for k, v in data["retries"].items()}
        data["flagged"] = [str(p) for p in data["flagged"]]
    except (OSError, ValueError, KeyError, TypeError, IndexError, AttributeError) as exc:
        state.log_line(_NAME, f"cursor file unreadable ({type(exc).__name__}): starting a fresh pass from the oldest file")
        return fresh
    return data


def main() -> int:
    state.init_state()
    project = state.project_root()
    sdir = state.state_dir()
    cursor_file = sdir / f"{_NAME}.cursor.json"
    seen = sdir / f"{_NAME}-seen.txt"
    saved = _read_cursor(cursor_file)
    since: env_secrets.Key = (saved["cursor"][0], saved["cursor"][1])
    give_up = frozenset(p for p, n in saved["retries"].items() if n >= env_secrets.MAX_FAIL_RETRIES)

    secrets = env_secrets.live_secrets(os.environ)
    matcher = env_secrets.Matcher(secrets) if secrets else None
    if matcher is None:
        state.log_line(_NAME, "this environment has no secret-named variable with a usable value: the exact matcher is off, only the dump-shape test runs")
    salt = _load_salt()
    untracked, git_exit = _untracked_files(project)
    git_retries = saved["retries"].get(_GIT_RETRY_KEY, 0)
    hold_for_git = git_exit is not None and git_retries < env_secrets.MAX_FAIL_RETRIES  # bounded: git failing for good must not stall the sweep for good
    roots = env_secrets.agent_writable_roots(project, os.getuid()) + untracked
    report = env_secrets.sweep(roots, matcher, salt, since=since, give_up=give_up)

    holds: list[env_secrets.Key] = list(report.failed)
    retries = {key[1]: saved["retries"].get(key[1], 0) + 1 for key in report.failed}
    if git_exit is not None:
        retries[_GIT_RETRY_KEY] = git_retries + 1
    keys = {path: (mtime, path) for mtime, path in [*report.processed, *report.failed]}

    by_path: dict[str, list[env_secrets.Hit]] = {}
    for hit in report.hits:
        by_path.setdefault(hit.path, []).append(hit)
    raised = 0
    # Oldest change first, the order the cursor moves in: sorted by path, the same files won the per-fire cap on every
    # pass while the cursor sat in front of the others, and those were never raised.
    for path, hits in sorted(by_path.items(), key=lambda item: keys[item[0]]):
        if raised >= issue_catalog.MAX_RAISES_PER_FIRE:  # checked before the three git calls of _file_status
            holds.append(keys[path])  # over the per-fire cap, not a failure: retried next pass without counting a retry
            continue
        names = sorted({h.name for h in hits})
        first = min(hits, key=lambda h: h.line)
        status = _file_status(project, path)
        synced = any(marker in path for marker in _SYNCED_MARKERS)
        display = _display(project, path)
        shown_names = state.sanitize_for_drift_line(", ".join(names))
        raised += 1
        r = issue_catalog.raise_issue(
            "CRED-002",
            where=f"file:{_portable(project, path)}",
            path=display,
            found=f"{', '.join(names)} at line {first.line} (form {first.form}, fingerprint {first.fingerprint}); the file is {status}"
                  + ("; inside a synced folder" if synced else ""),
            evidence=[f"file:{_portable(project, path)}:{first.line}"],
        )
        if r.first_seen and r.line:
            print(r.line)
        elif not r.ok:
            state.log_line(_NAME, f"could not raise CRED-002: {r.why}")
            holds.append(keys[path])
            retries[path] = saved["retries"].get(path, 0) + 1
        line = (
            f"[{_NAME}] URGENT: the value of {shown_names} (a secret of this session's environment) is written in {display}, line {first.line} "
            f"({status}{', inside a synced folder' if synced else ''}). Nothing was changed. Rotating the secret is YOUR decision: an overwritten file "
            "can survive in snapshots and backups, and a value already printed into a conversation has already been sent."
        )
        out = dedupe.emit_once(seen, f"{first.fingerprint}:{path}", line)
        if out is not None:
            print(out)


    # A file whose NAME holds the value: never printed, logged or kept by path; reported by its folder (the sweep left it
    # out of the pass, so it is seen again on every pass and the dedupe line keeps it from repeating).
    for folder, name in sorted(set(report.secret_named)):
        if raised >= issue_catalog.MAX_RAISES_PER_FIRE:
            break
        raised += 1
        shown_folder = _display(project, folder)
        r = issue_catalog.raise_issue(
            "CRED-002",
            where=f"name:{_portable(project, folder)}",
            path=shown_folder,
            found=f"{name}: the value is written in a file name in this folder; the file was not read",
            evidence=[f"folder:{_portable(project, folder)}"],
        )
        if r.first_seen and r.line:
            print(r.line)
        elif not r.ok:
            state.log_line(_NAME, f"could not raise CRED-002 for a file name: {r.why}")
        out = dedupe.emit_once(
            seen, f"name:{name}:{folder}",
            f"[{_NAME}] URGENT: the value of {state.sanitize_for_drift_line(name)} (a secret of this session's environment) is written in the NAME of a file in "
            f"{shown_folder}. The path is not shown or stored, and the file was not read. Nothing was changed. Rotating the secret is YOUR decision.",
        )
        if out is not None:
            print(out)
    flagged = set(saved["flagged"]) | set(by_path)
    for path in sorted(flagged - set(by_path)):
        if path in keys:  # rescanned and clean now: withdraw the finding
            issue_catalog.clear_issue("CRED-002", where=f"file:{_portable(project, path)}")
            flagged.discard(path)

    # The heartbeat stdout is read by the model: a folder of dump copies must not print one line each.
    for path, names in report.dump_shaped[: issue_catalog.MAX_RAISES_PER_FIRE]:
        shape_key = f"shape:{path}:{zlib.crc32(','.join(names).encode()) & 0xFFFFFFFF}"
        line = (
            f"[{_NAME}] a file has the shape of an environment dump: {_display(project, path)} holds secret-named entries "
            f"({state.sanitize_for_drift_line(', '.join(names[:8]))}) with token-like values. Report-only, nothing was changed: check whether the values are live."
        )
        out = dedupe.emit_once(seen, shape_key, line)
        if out is not None:
            print(out)
    more = report.dump_shaped[issue_catalog.MAX_RAISES_PER_FIRE :]
    if more:
        state.log_line(_NAME, "dump-shaped files not listed on stdout: " + "; ".join(path for path, _ in more[:50]))
        out = dedupe.emit_once(
            seen, f"shape-more:{zlib.crc32(chr(0).join(path for path, _ in more).encode()) & 0xFFFFFFFF}",
            f"[{_NAME}] {len(more)} more dump-shaped file(s) not listed here, report-only (paths in this detector's log).",
        )
        if out is not None:
            print(out)

    if git_exit is not None:
        out = dedupe.emit_once(
            seen, f"git:{git_exit}:{git_retries}",
            f"[{_NAME}] sweep coverage: untracked files were not listed (git ls-files exited {git_exit}); "
            f"the cursor stays where it was for up to {env_secrets.MAX_FAIL_RETRIES} passes so that they are read once git works.",
        )
        if out is not None:
            print(out)
    uncovered = sorted(report.unreadable) + sorted(report.too_big) + sorted(report.shape_not_checked) + sorted(report.not_regular)
    if uncovered:
        coverage = (
            f"[{_NAME}] sweep coverage: {len(report.too_big)} file(s) over {env_secrets.MAX_FILE_BYTES // (1024 * 1024)} MiB not read, "
            f"{len(report.unreadable)} unreadable, {len(report.not_regular)} not regular files (pipes, devices), "
            f"{len(report.shape_not_checked)} over {env_secrets.MAX_SHAPE_BYTES // (1024 * 1024)} MiB "
            "not checked for the dump shape (paths in this detector's log)."
        )
        out = dedupe.emit_once(seen, f"coverage:{zlib.crc32(chr(0).join(uncovered).encode()) & 0xFFFFFFFF}", coverage)
        if out is not None:
            print(out)
        state.log_line(_NAME, "not fully covered: " + "; ".join(uncovered[:20]))

    new_cursor = since if hold_for_git else env_secrets.advance_cursor(since, report.processed, holds)
    state.atomic_write(cursor_file, json.dumps({"cursor": list(new_cursor), "retries": retries, "flagged": sorted(flagged)}))
    state.log_line(
        _NAME,
        f"pass: {report.scanned} file(s) read ({report.bytes_read // 1024} KiB), {report.left_for_next_pass} left for the next pass, "
        f"{len(report.hits)} hit(s) in {len(by_path)} file(s), {len(report.dump_shaped)} dump-shaped",
    )
    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
