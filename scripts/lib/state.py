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


def is_truthy_env(name: str, default: bool) -> bool:
    """Read a yes/no env var with friendly false-spellings.

    Empty / unset → `default`. Otherwise: `false`/`0`/`no`/`off`
    (case-insensitive) → False; anything else → True.

    Three detectors duplicated this function byte-for-byte; promoting it
    here keeps the spelling-of-false rules in one place so a future
    addition (e.g. `disabled`) doesn't drift between callers.
    """
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    return raw.lower() not in ("false", "0", "no", "off")


def coerce_int(
    value: Optional[str],
    default: int = 0,
    *,
    detector_name: Optional[str] = None,
    var_name: Optional[str] = None,
) -> int:
    """Coerce a (possibly user-supplied) value to a non-negative int.

    Accepts None, empty string, and non-numeric text — all return
    `default`. Used for `CLAUDE_PLUGIN_OPTION_*` env vars where a typo
    like "900 seconds" should not crash the heartbeat.

    If `detector_name` is provided AND a non-empty value failed to
    coerce, log a one-line note so the user can see in the detector
    log that their config knob is being ignored. The log fires only
    on the "had a value but it wasn't a number" case — empty/unset
    values (the common path) stay silent. `var_name` lets the log
    point at the offending env var.
    """
    if value is None:
        return default
    s = value.strip()
    if not s:
        return default
    if not s.isdigit():
        if detector_name:
            label = var_name or "config value"
            log_line(
                detector_name,
                f"coerce_int: {label}={s!r} is not a non-negative integer — using default {default}",
            )
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


def run_subprocess(
    cmd: list[str],
    *,
    timeout: float = 10.0,
    cwd: Path | str | None = None,
    capture: bool = True,
    detector_name: Optional[str] = None,
) -> Optional[subprocess.CompletedProcess[str]]:
    """Run a subprocess with a default timeout, never propagate exceptions.

    Returns the CompletedProcess on success, None on:
      * `subprocess.TimeoutExpired` — the command ran past `timeout` seconds.
        A network-stuck `gh` call is the canonical case; without a timeout
        the heartbeat would block forever.
      * `FileNotFoundError` — the binary isn't on PATH (e.g. `gh` not
        installed on a CI runner). doctor.py surfaces this upstream as
        WARN/FAIL; detectors can short-circuit on None and continue.
      * `OSError` — any other OS-level failure (permission, ENOMEM, etc.).

    Why None and not raise: detectors run in the cron-fire hot path and
    a single hung subprocess would park the whole heartbeat for 5 minutes.
    Returning None lets each call site decide whether to log + skip the
    branch or log + abort the detector.

    `detector_name` (optional): if provided, a one-line failure log goes
    to `<detector_name>.log` via `log_line`. Pass the detector's own name
    so post-mortem debugging can correlate the timeout to the right detector.

    Always passes `check=False` and `text=True`; never sets `shell=True`.
    Capture defaults on (`capture_output=True`); pass `capture=False` for
    detectors whose stdout must flow through to the cron prompt
    (dispatch.py's detector-invocation path uses that direct form).
    """
    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd is not None else None,
            capture_output=capture,
            text=True,
            check=False,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        if detector_name:
            cmd_short = " ".join(cmd[:3]) + ("..." if len(cmd) > 3 else "")
            log_line(detector_name, f"subprocess timed out after {timeout}s: {cmd_short}")
        return None
    except FileNotFoundError:
        if detector_name:
            log_line(detector_name, f"binary not in PATH: {cmd[0]}")
        return None
    except OSError as exc:
        if detector_name:
            cmd_short = " ".join(cmd[:3]) + ("..." if len(cmd) > 3 else "")
            log_line(detector_name, f"subprocess OSError ({exc}): {cmd_short}")
        return None


def sanitize_for_drift_line(text: str) -> str:
    """Defang `[` `]` and strip control characters from untrusted text.

    Defends against prompt-mimicry where a user-controlled string
    (stash subject, PR title, server name, env var name) tries to
    impersonate a janitor marker like `[janitor-resume]`. Replacements:

      * 0x00–0x1F (except tab + newline) → stripped
      * 0x7F (DEL) → stripped
      * U+202A–U+202E (Unicode bidi-override LRE/RLE/PDF/LRO/RLO) → stripped
      * U+2066–U+2069 (LRI/RLI/FSI/PDI isolate controls) → stripped
      * `[` → `⟦` (U+27E6 MATHEMATICAL LEFT WHITE SQUARE BRACKET)
      * `]` → `⟧` (U+27E7 MATHEMATICAL RIGHT WHITE SQUARE BRACKET)

    Bidi-override and isolate controls let attacker-controlled text
    visually reorder a downstream rendering — a PR title or stash subject
    that embeds them could disguise its real content from a human
    skimming the heartbeat output. Stripping them is safe: drift lines
    are short, single-direction prose; nobody's PR title legitimately
    needs to flip script direction.

    The Unicode lookalikes still read as brackets but are visually
    distinct from anything we emit ourselves (our markers always use
    ASCII `[]`).
    """
    def _keep(c: str) -> bool:
        if c in ("\t", "\n"):
            return True
        cp = ord(c)
        if cp < 0x20:
            return False
        if cp == 0x7F:                  # DEL
            return False
        if 0x202A <= cp <= 0x202E:      # bidi-override LRE/RLE/PDF/LRO/RLO
            return False
        if 0x2066 <= cp <= 0x2069:      # LRI/RLI/FSI/PDI
            return False
        return True

    cleaned = "".join(c for c in text if _keep(c))
    cleaned = cleaned.replace("[", "⟦").replace("]", "⟧")
    return cleaned
