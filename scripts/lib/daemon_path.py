"""Restore a usable tool PATH for the OS-keepalive daemon (TRDD-VQ4LX7ND).

WHY THIS EXISTS — a launchd/systemd child does NOT inherit the login shell's PATH.
The macOS LaunchAgent hands the daemon a bare
``/usr/bin:/bin:/usr/sbin:/sbin`` (plus the uv python dir); Homebrew's
``/opt/homebrew/bin`` — where ``tmux`` lives — is absent. Every fleet probe and
every keystroke injection shells out by BARE NAME (``tmux list-panes``,
``tmux send-keys``), and ``fleet_scan._run`` swallows the resulting
``FileNotFoundError`` into an empty string. So the guardian resolved ZERO tmux
panes, logged ``UNREACHABLE ({})``, and skipped the rearm — silently, 254 times
in a row, while the identical code fired 93 injections from a session-spawned
daemon that had a normal PATH.

The repair belongs in the PROCESS, not in each argv: augmenting ``os.environ``
once at daemon start fixes the scan probes, the send steps, and every future
tool, and it is inherited by children for free. It also survives a plugin update
(a plist ``EnvironmentVariables`` block would not — that needs a reinstall).

APPEND, never prepend: the launcher's own PATH entries keep priority, so we can
only ever make a previously-unresolvable tool resolvable — never shadow one the
host deliberately chose.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Callable, Iterable, Mapping

# Standard user/package-manager prefixes a login shell would have contributed.
# Ordered most-likely-first; every one is probed for existence before use.
_MACOS_PREFIXES: tuple[str, ...] = (
    "/opt/homebrew/bin",  # Homebrew (Apple Silicon) — where tmux lives
    "/opt/homebrew/sbin",
    "/usr/local/bin",  # Homebrew (Intel) / manual installs
    "/usr/local/sbin",
    "/opt/local/bin",  # MacPorts
    "~/.local/bin",
    "~/.cargo/bin",  # memgrep
)

_LINUX_PREFIXES: tuple[str, ...] = (
    "/home/linuxbrew/.linuxbrew/bin",
    "/usr/local/bin",
    "/usr/local/sbin",
    "~/.local/bin",
    "~/.cargo/bin",
)

# Tools whose absence silently disables a whole recovery channel. Logged once at
# daemon start so a future PATH regression is VISIBLE instead of degrading into a
# mute `UNREACHABLE ({})` loop — the exact failure this module was written to end.
#
# `aimaestro-agent.sh` matters most of the three: unlike tmux/osascript keystrokes,
# the ai-maestro channel ENQUEUES a command that a hibernated agent executes on
# wake, and it needs no GUI session and no TCC Automation grant. It is therefore
# the only channel that reaches a wedged agent from a headless launchd daemon — and
# `terminal_trigger._resolve_aimaestro_cli` finds it with a bare `shutil.which`, so
# launchd's stripped PATH disabled it exactly as it disabled tmux.
INJECTION_TOOLS: tuple[str, ...] = ("tmux", "osascript", "aimaestro-agent.sh")


def default_prefixes(platform: str) -> tuple[str, ...]:
    """The candidate dirs for a platform. Unknown platforms get none (no guessing)."""
    if platform == "darwin":
        return _MACOS_PREFIXES
    if platform.startswith("linux"):
        return _LINUX_PREFIXES
    return ()


def augmented_path(
    current: str,
    *,
    candidates: Iterable[str],
    exists: Callable[[str], bool],
) -> tuple[str, list[str]]:
    """Return ``(new_path, added_dirs)`` — ``current`` with every candidate that
    exists on disk and is not already present APPENDED, in candidate order.

    PURE: `exists` is injected so the decision is testable without a filesystem.
    `~` is expanded before both the dedupe check and the append, so a PATH that
    already carries the expanded form is not re-appended in its `~` spelling.
    """
    have = [p for p in current.split(os.pathsep) if p]
    seen = set(have)
    added: list[str] = []
    for raw in candidates:
        d = os.path.expanduser(raw)
        if d in seen or not exists(d):
            continue
        seen.add(d)
        added.append(d)
    if not added:
        return current, []
    return os.pathsep.join(have + added), added


def ensure_tool_path(env: Mapping[str, str] | None = None) -> list[str]:
    """Augment ``env['PATH']`` in place with the platform's standard tool prefixes.

    Returns the dirs added (empty when the PATH was already complete). Mutates the
    real ``os.environ`` by default so every subprocess this daemon spawns inherits
    the repaired PATH. Idempotent: a second call adds nothing.
    """
    target = os.environ if env is None else env
    new_path, added = augmented_path(
        target.get("PATH", ""),
        candidates=default_prefixes(sys.platform),
        exists=lambda d: Path(d).is_dir(),
    )
    if added:
        target["PATH"] = new_path  # type: ignore[index]  # a real MutableMapping at runtime
    return added


def resolve_injection_tools(env: Mapping[str, str] | None = None) -> dict[str, str | None]:
    """``{tool: absolute path or None}`` for each tool the fleet injector needs.

    Call AFTER ``ensure_tool_path``. A ``None`` here is the early-warning signal
    that a recovery channel is dead: it is a fact about this daemon's environment,
    not about the host (the tool may well exist for the user's login shell).
    """
    import shutil

    path = (env or os.environ).get("PATH")
    return {tool: shutil.which(tool, path=path) for tool in INJECTION_TOOLS}
