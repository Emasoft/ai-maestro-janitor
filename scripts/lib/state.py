# Shared state helpers for ai-maestro-janitor hooks and detectors —
# Python port of scripts/lib/state.sh. Keep the surface AS CLOSE to the
# bash original as possible so a detector can call the same names.
#
# Imported (not invoked as a script) so no PEP 723 metadata block here.
# Stdlib-only — pathlib + os + subprocess + datetime are all that's used.

from __future__ import annotations

import os
import subprocess
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Optional


# --- path resolution -------------------------------------------------------

def _resolve_project_root() -> Path:
    """Equivalent to bash's resolve_project_root.

    Priority:
      1. $CLAUDE_PROJECT_DIR
      2. `git rev-parse --show-toplevel`
      3. cwd
    """
    explicit = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if explicit:
        return Path(explicit)
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            check=True,
        )
        return Path(proc.stdout.strip())
    except (subprocess.CalledProcessError, FileNotFoundError):
        return Path.cwd()


# Cached so repeated imports/calls don't re-run git. The cache is keyed
# on the bound function (no args) so it's effectively a module-level
# singleton — but it's recomputed if the module is re-imported in a
# fresh process (which is the lifetime we care about).
@lru_cache(maxsize=1)
def project_root() -> Path:
    return _resolve_project_root()


@lru_cache(maxsize=1)
def janitor_root() -> Path:
    return project_root() / ".janitor"


@lru_cache(maxsize=1)
def state_dir() -> Path:
    return janitor_root() / "state"


@lru_cache(maxsize=1)
def log_dir() -> Path:
    return janitor_root() / "logs"


# --- public API ------------------------------------------------------------

def init_state() -> None:
    """Create state/ and logs/ directories if missing. Idempotent."""
    state_dir().mkdir(parents=True, exist_ok=True)
    log_dir().mkdir(parents=True, exist_ok=True)


def atomic_write(target: Path, value: str) -> None:
    """Atomic-by-rename write: write to tmp, then os.replace into place.

    `os.replace` is atomic on POSIX and Windows (per Python docs), so a
    concurrent reader sees either the old content or the new — never a
    half-written file.
    """
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_suffix(target.suffix + f".tmp.{os.getpid()}")
    tmp.write_text(value)
    os.replace(tmp, target)


def read_int_state(path: Path | str, default: int = 0) -> int:
    """Read a non-negative int from a state file.

    Falls back to `default` on any read error or non-numeric content.
    Detector arithmetic runs under guard rails — a corrupted state file
    must NOT abort the whole heartbeat (the bash port had `set -u`
    crashes on `$(( now - abc ))`; Python doesn't have that footgun
    but we still want graceful degradation).
    """
    try:
        content = Path(path).read_text().strip()
    except (FileNotFoundError, OSError):
        return default
    if content.isdigit():
        return int(content)
    return default


def coerce_int(value: Optional[str], default: int = 0) -> int:
    """Coerce a (possibly user-supplied) value to a non-negative int.

    Accepts None, empty string, and non-numeric text — all return
    `default`. Used for `CLAUDE_PLUGIN_OPTION_*` env vars where a typo
    like "900 seconds" should not crash the heartbeat.
    """
    if value is None:
        return default
    s = value.strip()
    if not s.isdigit():
        return default
    return int(s)


def file_mtime(path: Path | str) -> int:
    """Return file mtime in epoch seconds, or 0 on error.

    Cross-platform replacement for the `stat -c %Y` / `stat -f %m`
    dance the bash port had to do.
    """
    try:
        return int(Path(path).stat().st_mtime)
    except (FileNotFoundError, OSError):
        return 0


def log_line(name: str, message: str) -> None:
    """Append one log line with a local-time timestamp + GMT offset.

    Format mirrors the bash port:
        [YYYY-MM-DDTHH:MM:SS±HHMM] [s:<8-char-prefix>] <message>

    The `[s:<prefix>]` block is included only when CLAUDE_CODE_SESSION_ID
    is set (Claude Code 2.1.132+). Without it, the format degrades
    gracefully to the original `[ts] <message>` shape.
    """
    init_state()
    # Local time + GMT offset — never UTC, per the project rule.
    ts = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")
    sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    if sid:
        line = f"[{ts}] [s:{sid[:8]}] {message}\n"
    else:
        line = f"[{ts}] {message}\n"
    log_path = log_dir() / f"{name}.log"
    with log_path.open("a", encoding="utf-8") as f:
        f.write(line)


def rotate_log_if_big(name: str, max_bytes: int = 1_048_576) -> None:
    """Rotate <name>.log to <name>.log.1 when it exceeds `max_bytes`.

    Only one rotation level — we don't keep .log.2 / .log.3. The
    log-retention prologue in dispatch.py prunes both .log and .log.1
    after `log_retention_days`.
    """
    log_path = log_dir() / f"{name}.log"
    try:
        if log_path.stat().st_size > max_bytes:
            backup = log_path.with_name(log_path.name + ".1")
            os.replace(log_path, backup)
    except (FileNotFoundError, OSError):
        return


def sanitize_for_drift_line(text: str) -> str:
    """Defang `[` `]` and strip control characters from untrusted text.

    Defends against prompt-mimicry where a user-controlled string
    (stash subject, PR title, server name, env var name) tries to
    impersonate a janitor marker like `[janitor-resume]`. Replacements:

      * 0x00–0x1F (except tab + newline) → stripped
      * `[` → `⟦` (U+27E6 MATHEMATICAL LEFT WHITE SQUARE BRACKET)
      * `]` → `⟧` (U+27E7 MATHEMATICAL RIGHT WHITE SQUARE BRACKET)

    The Unicode lookalikes still read as brackets but are visually
    distinct from anything we emit ourselves (our markers always use
    ASCII `[]`).
    """
    cleaned = "".join(
        c for c in text
        if c in ("\t", "\n") or ord(c) >= 0x20
    )
    cleaned = cleaned.replace("[", "⟦").replace("]", "⟧")
    return cleaned
