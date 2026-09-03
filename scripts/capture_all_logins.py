#!/usr/bin/env python3
"""Walk every configured rotator account and run the OAuth capture for each, in
sequence — the "top up all logins" flow the `/janitor-capture-all-logins` skill
drives (TRDD-GZXTSJSR P3).

Lists the roster via `rotator.py known-emails` (the same source the reauth flow
uses — state.json's slot index, keychain-agnostic), then runs
`slot_capture_browser.py <email>` for each account in turn, printing progress.

Assumes each account already has a saved claude.ai session (from
`/janitor-refresh-cc-logins`'s `open-login.sh` step) — this script MINTS OAuth
tokens from that saved session; it does not perform the human login itself.

Fails FAST (aborts the whole walk) only on an INFRASTRUCTURE error: the rotator
engine or capture script missing, or the roster call itself failing/timing out —
those mean nothing can proceed. A single account's capture failing (non-zero
exit or timeout) is an expected per-account outcome (e.g. its saved session has
lapsed) — reported and the walk continues, so one bad account never blocks
topping up the rest.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROT = _HERE / "oauth_rotator"
_ROTATOR_PY = _ROT / "rotator.py"
_CAPTURE_PY = _ROT / "slot_capture_browser.py"

sys.path.insert(0, str(_ROT))
# rotator.py is stdlib-only; reused here ONLY for its bootstrap PID-lock helpers
# (F3, TRDD-GZXTSJSR) so this walker's manual capture and the daemon's own detached
# auto-bootstrap (rotator._invoke_slot_capture) can never race on the SAME email's
# Chrome --user-data-dir.
import rotator  # noqa: E402

KNOWN_EMAILS_TIMEOUT_S = 15.0
# 400s (F2, TRDD-GZXTSJSR): the capture legitimately polls the consent page up to 300s
# (slot_capture_browser.py); the old 120s cap fired routinely on a slow/real login.
CAPTURE_TIMEOUT_S = 400.0
_GRACE_KILL_S = 5.0


def _child_env() -> dict[str, str]:
    """The environment every child runs under: `env -u CLAUDE_PLUGIN_DATA` (a foreign
    value from another plugin's context would mis-route the rotator's own data-dir
    guard — TRDD-7100178d / TRDD-5EUYV08H)."""
    env = dict(os.environ)
    env.pop("CLAUDE_PLUGIN_DATA", None)
    return env


def _capture_timeout() -> float:
    """Per-account capture timeout (seconds). Env-overridable
    (`CLAUDE_PLUGIN_OPTION_CAPTURE_TIMEOUT_S`); a bad value falls back to the default
    so a typo never crashes the walk or silently shrinks the budget below what a real
    consent-page login needs."""
    raw = os.environ.get("CLAUDE_PLUGIN_OPTION_CAPTURE_TIMEOUT_S", "").strip()
    if not raw:
        return CAPTURE_TIMEOUT_S
    try:
        val = float(raw)
    except ValueError:
        return CAPTURE_TIMEOUT_S
    return val if val > 0 else CAPTURE_TIMEOUT_S


def known_emails(*, env: dict[str, str] | None = None) -> list[str]:
    """The rotator's known-account roster, one email per line, via `rotator.py
    known-emails` (stdlib-only engine — invoked with `python3`, never `uv run`).

    Raises RuntimeError on any hard failure: no roster means nothing to walk."""
    if not _ROTATOR_PY.is_file():
        raise RuntimeError(f"rotator engine missing: {_ROTATOR_PY}")
    proc = subprocess.run(
        ["python3", str(_ROTATOR_PY), "known-emails"],
        capture_output=True,
        text=True,
        timeout=KNOWN_EMAILS_TIMEOUT_S,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"rotator.py known-emails failed (rc={proc.returncode}): {proc.stderr.strip()}")
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def capture_already_running(email: str) -> int:
    """The PID of a daemon-launched auto-bootstrap capture already in flight for
    `email`, or 0 if none (F3). Checked BEFORE this walker launches its own capture
    for the same account — a manual + an auto-bootstrap capture racing on the same
    Chrome `--user-data-dir` corrupts the profile."""
    pid_path = rotator._bootstrap_pid_path(email)
    try:
        prior = int(pid_path.read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return 0
    return prior if rotator._bootstrap_pid_alive(prior) else 0


def _capture_cmd(email: str) -> list[str]:
    """The real capture invocation — its own function so a test can substitute a
    lightweight fake in place of `uv run --with playwright python …` without
    changing `capture_one`'s process-lifecycle logic (F2/F3)."""
    return ["uv", "run", "--with", "playwright", "python", str(_CAPTURE_PY), email]


def capture_one(
    email: str, *, env: dict[str, str] | None = None, timeout: float = CAPTURE_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    """Run the WORKING capture for one account:
    `uv run --with playwright python slot_capture_browser.py <email>` from the
    rotator dir (the PEP-723 header alone is not enough without `--with playwright` —
    see slot_capture_browser.py's own docstring).

    Runs in its OWN process group (F2, TRDD-GZXTSJSR): the capture polls the consent
    page for up to 300s via a grandchild Chrome process spawned by `uv run`. A plain
    `subprocess.run(timeout=...)` SIGKILLs only the `uv` process on timeout, orphaning
    `slot_capture_browser.py` + headful Chrome forever — the exact hazard
    `rotator.py`'s `_invoke_slot_capture` docstring warns about for the daemon's own
    detached launch. `start_new_session=True` puts the whole tree in one process
    group so a timeout can `killpg` all of it, not just the direct child.

    Writes/clears a per-email PID lockfile the same way the daemon's own
    `rotator._invoke_slot_capture` does (F3), so the two capture paths never wedge on
    the state each other's PID files hold — even though only THIS process's pidfile
    lifetime is managed here (the daemon manages its own separately)."""
    if not _CAPTURE_PY.is_file():
        raise RuntimeError(f"capture script missing: {_CAPTURE_PY}")
    cmd = _capture_cmd(email)
    proc = subprocess.Popen(  # noqa: S603 -- explicit argv list, no shell
        cmd,
        cwd=str(_ROT),
        env=env,
        start_new_session=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    pid_path = rotator._bootstrap_pid_path(email)
    try:
        pid_path.write_text(str(proc.pid), encoding="utf-8")
    except OSError:
        pass  # best-effort; a failed pidfile write must never block the capture itself
    try:
        try:
            stdout, stderr = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _kill_process_group(proc)
            stdout, stderr = proc.communicate()  # drain + reap after the kill
            raise subprocess.TimeoutExpired(cmd, timeout, output=stdout, stderr=stderr) from None
        return subprocess.CompletedProcess(cmd, proc.returncode, stdout, stderr)
    finally:
        try:
            if pid_path.is_file() and pid_path.read_text(encoding="utf-8").strip() == str(proc.pid):
                pid_path.unlink()
        except OSError:
            pass


def _kill_process_group(proc: subprocess.Popen[str]) -> None:
    """SIGTERM the whole process group `proc` leads, escalate to SIGKILL if it
    hasn't exited after a short grace period. Never raises — a timeout is already
    the caller's error to report."""
    try:
        pgid = os.getpgid(proc.pid)
    except ProcessLookupError:
        return  # already gone
    try:
        os.killpg(pgid, signal.SIGTERM)
        proc.wait(timeout=_GRACE_KILL_S)
    except (ProcessLookupError, subprocess.TimeoutExpired):
        try:
            os.killpg(pgid, signal.SIGKILL)
            proc.wait(timeout=_GRACE_KILL_S)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            pass


def main(argv: list[str] | None = None) -> int:
    env = _child_env()
    timeout = _capture_timeout()

    try:
        emails = known_emails(env=env)
    except (RuntimeError, subprocess.TimeoutExpired) as exc:
        print(f"[capture-all-logins] FAILED to list accounts: {exc}", file=sys.stderr)
        return 1

    if not emails:
        print("[capture-all-logins] no known accounts — nothing to capture.")
        return 0

    n = len(emails)
    failures: list[str] = []
    for i, email in enumerate(emails, 1):
        running_pid = capture_already_running(email)
        if running_pid:
            print(
                f"[capture-all-logins] {i}/{n} — {email}: SKIPPED "
                f"(a capture is already running, pid={running_pid})"
            )
            failures.append(email)
            continue
        print(f"[capture-all-logins] {i}/{n} — capturing {email} ...")
        try:
            proc = capture_one(email, env=env, timeout=timeout)
        except subprocess.TimeoutExpired:
            print(f"[capture-all-logins] {i}/{n} — {email}: TIMED OUT", file=sys.stderr)
            failures.append(email)
            continue
        except RuntimeError as exc:
            # The capture script itself is missing — an infra failure, not a
            # per-account one. Nothing downstream can succeed either; stop now.
            print(f"[capture-all-logins] FAILED: {exc}", file=sys.stderr)
            return 1
        if proc.returncode == 0:
            print(f"[capture-all-logins] {i}/{n} — {email}: OK")
        else:
            print(
                f"[capture-all-logins] {i}/{n} — {email}: FAILED (rc={proc.returncode})\n"
                f"{proc.stderr.strip()}",
                file=sys.stderr,
            )
            failures.append(email)

    if failures:
        print(
            f"[capture-all-logins] done — {n - len(failures)}/{n} captured, "
            f"{len(failures)} failed: {', '.join(failures)}"
        )
        return 1
    print(f"[capture-all-logins] done — {n}/{n} accounts captured.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
