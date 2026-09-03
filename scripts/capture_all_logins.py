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

import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROT = _HERE / "oauth_rotator"
_ROTATOR_PY = _ROT / "rotator.py"
_CAPTURE_PY = _ROT / "slot_capture_browser.py"

KNOWN_EMAILS_TIMEOUT_S = 15.0
CAPTURE_TIMEOUT_S = 120.0


def _child_env() -> dict[str, str]:
    """The environment every child runs under: `env -u CLAUDE_PLUGIN_DATA` (a foreign
    value from another plugin's context would mis-route the rotator's own data-dir
    guard — TRDD-7100178d / TRDD-5EUYV08H)."""
    import os

    env = dict(os.environ)
    env.pop("CLAUDE_PLUGIN_DATA", None)
    return env


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


def capture_one(
    email: str, *, env: dict[str, str] | None = None, timeout: float = CAPTURE_TIMEOUT_S
) -> subprocess.CompletedProcess[str]:
    """Run the WORKING capture for one account:
    `uv run --with playwright python slot_capture_browser.py <email>` from the
    rotator dir (the PEP-723 header alone is not enough without `--with playwright` —
    see slot_capture_browser.py's own docstring)."""
    if not _CAPTURE_PY.is_file():
        raise RuntimeError(f"capture script missing: {_CAPTURE_PY}")
    return subprocess.run(
        ["uv", "run", "--with", "playwright", "python", str(_CAPTURE_PY), email],
        cwd=str(_ROT),
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )


def main(argv: list[str] | None = None) -> int:
    env = _child_env()

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
        print(f"[capture-all-logins] {i}/{n} — capturing {email} ...")
        try:
            proc = capture_one(email, env=env)
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
