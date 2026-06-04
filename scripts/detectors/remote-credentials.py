#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Remote-credentials detector — Python port of remote-credentials.sh.

Flags git remotes whose URL embeds a password in the userinfo component
(e.g. `https://user:…@github.com/...`). These leak the secret into
`git remote -v` output (visible in screen-shares, paste-bins, CI logs),
into any clone of the repo that copies the local config, and into shell
history when the URL was set via `git remote add`.

Detection is intentionally cheap (one `git remote -v`, no network) and
the nudge is unconditional — there is no legitimate reason to keep
credentials in a remote URL when SSH keys, OAuth tokens via the
credential helper, or a `~/.netrc` entry all do the same job without
leaking.
"""

from __future__ import annotations

import re
import shlex
import subprocess
import sys
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402

# Pattern A — explicit basic-auth: `scheme://user:secret@host/...` with a
# non-empty password component after the `:`. Matches the historical
# "username + password" format. Userinfo char class excludes `@` and `/`
# so we stop at the userinfo→host boundary.
_PATTERN_A = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://[^/@]*:[^@/]+@[^/]+")
# Pattern B — token-as-username over HTTP(S): `https://<token>@host/...`.
# Canonical GitHub PAT form (`https://ghp_xxxxxx@github.com/...`). The
# userinfo class excludes `:` (so we don't double-match A) and `@`/`/`
# (boundary). We do NOT flag this pattern for `ssh://` because
# `ssh://git@host` is the legitimate SSH form (the `git` user component
# carries no secret).
_PATTERN_B = re.compile(r"^https?://[^:@/]+@[^/]+")
# Strip credentials from `scheme://user:pass@host/...` → `scheme://host/...`.
_STRIP_USERINFO = re.compile(r"^([a-zA-Z][a-zA-Z0-9+.\-]*://)([^/@]*@)?")


def _has_password_in_url(url: str) -> bool:
    return bool(_PATTERN_A.match(url)) or bool(_PATTERN_B.match(url))


def _strip_userinfo(url: str) -> str:
    return _STRIP_USERINFO.sub(r"\1", url, count=1)


def _crc32(s: str) -> int:
    """Match cksum's CRC-32 stable-fingerprint shape (lowercase hex would be
    fine too, but we keep parity with the bash port for log readability)."""
    return zlib.crc32(s.encode("utf-8")) & 0xFFFFFFFF


def main() -> int:
    # Hard self-scan guard — see state.is_self_scan_target() docstring.
    if state.is_self_scan_target():
        return 0
    state.init_state()

    seen = state.state_dir() / "remote-credentials-seen.txt"

    if subprocess.run(
        ["git", "rev-parse", "--git-dir"],
        cwd=str(state.project_root()),
        capture_output=True, text=True, check=False,
    ).returncode != 0:
        state.log_line("remote-credentials", "not a git repo — skipping")
        return 0

    proc = subprocess.run(
        ["git", "remote", "-v"],
        cwd=str(state.project_root()),
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        return 0

    seen_remotes: set[str] = set()
    for line in proc.stdout.splitlines():
        # Format: `<name>\t<url> (fetch|push)` — split on whitespace, take
        # first two columns. The third column is direction; we don't need it.
        parts = line.split()
        if len(parts) < 2:
            continue
        name, url = parts[0], parts[1]
        if not name or not url:
            continue

        # `git remote -v` lists each remote twice (fetch + push). Skip the
        # second row for the same name+url pair so we don't double-emit.
        key = f"{name}@{url}"
        if key in seen_remotes:
            continue
        seen_remotes.add(key)

        if not _has_password_in_url(url):
            continue

        clean_url = _strip_userinfo(url)
        safe_name = shlex.quote(name)
        safe_clean = shlex.quote(clean_url)
        # Sanitize the remote name for human-readable rendering. Git
        # remote names can legitimately contain weird chars (control
        # bytes, `[`/`]`) via a manually-edited config; without this
        # defang a remote literally named `[janitor-resume]` would mimic
        # our marker convention in the cron-forwarded line.
        display_name = state.sanitize_for_drift_line(name)

        # Use a hash of url+name as the dedup key so rotating the secret
        # (which changes the URL) re-fires the alert with the new value.
        fp = _crc32(key)

        out = dedupe.emit_once(
            seen,
            f"creds@{name}@{fp}",
            f"[remote-credentials] URGENT: git remote '{display_name}' embeds a secret in its URL — anyone with read "
            f"access to the repo, CI logs, or your screen can see it. Strip with: git remote set-url {safe_name} "
            f"{safe_clean}. Then rotate the leaked credential immediately.",
        )
        if out is not None:
            print(out)

    state.rotate_log_if_big("remote-credentials")
    return 0


if __name__ == "__main__":
    sys.exit(main())
