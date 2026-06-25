# Low-priority subprocess throttling for the global janitor daemon (TRDD-TY2EZ8ZH,
# task #244). The daemon's `task_marketplace_refresh` runs a CPU+IO-heavy
# `claude plugin marketplace update` every ~20 min; un-throttled it starves the
# user's foreground work. This module yields that one subprocess to the
# foreground by prefixing it with the OS low-priority launcher AND lowering its
# CPU baseline via a POSIX preexec.
#
# Imported (not invoked as a script) so no PEP 723 metadata block here.
# Stdlib-only — os + sys + shutil.
#
# FAIL-OPEN is the load-bearing invariant: the daemon is a machine-wide singleton,
# so a throttle defect must NEVER break marketplace-refresh or wedge the daemon.
# Every detection/build path degrades to "run un-throttled, exactly as before".

from __future__ import annotations

import os
import shutil
import sys
from typing import Callable, Optional


def low_priority_prefix(
    platform: str,
    *,
    has_taskpolicy: bool,
    has_nice: bool,
    has_ionice: bool,
) -> list[str]:
    """Return the command-prefix that launches a subprocess at LOW CPU+IO priority.

    PURE — no I/O, no env reads. The caller passes the platform string
    (``sys.platform``) and three tool-availability booleans, so this is fully
    unit-testable without mocking.

      * macOS (``platform == 'darwin'``) WITH ``taskpolicy`` → ``['taskpolicy', '-b']``.
        ``-b`` puts the process in the BACKGROUND QoS band, which throttles CPU,
        disk IO, AND network together — exactly the foreground-yielding behavior we
        want for the marketplace re-clone.
      * Linux (``platform`` starts with ``'linux'``) → ``['nice', '-n', '19']`` when
        ``nice`` is present, followed by ``['ionice', '-c', '3']`` when ``ionice``
        is present (idle IO class). Either may be absent on a stripped image; the
        present ones are still applied.
      * Anything unavailable → that part is dropped. Nothing available (e.g. macOS
        without ``taskpolicy``, Windows, an unknown platform) → ``[]`` (FAIL-OPEN:
        the subprocess runs un-throttled, identical to the pre-throttle behavior).

    The order matters on Linux: ``nice`` first so ``ionice`` runs UNDER the
    already-reniced shell — both still apply to the final child either way, but
    keeping ``nice`` outermost mirrors the common ``nice -n 19 ionice -c 3 cmd``
    incantation and is the clearest reading of "low CPU, then idle IO".
    """
    if platform == "darwin":
        if has_taskpolicy:
            return ["taskpolicy", "-b"]
        return []
    if platform.startswith("linux"):
        prefix: list[str] = []
        if has_nice:
            prefix += ["nice", "-n", "19"]
        if has_ionice:
            prefix += ["ionice", "-c", "3"]
        return prefix
    # Unknown platform (or macOS-without-taskpolicy fell through above): no
    # cross-platform launcher we trust → run un-throttled.
    return []


def _low_priority_prefix() -> list[str]:
    """Detect the host's low-priority launchers and build the prefix.

    The thin I/O wrapper around :func:`low_priority_prefix`: reads
    ``sys.platform`` and probes ``shutil.which`` for each tool. FAIL-OPEN — any
    unexpected error returns ``[]`` so the caller runs the subprocess un-throttled
    rather than crashing the daemon.
    """
    try:
        return low_priority_prefix(
            sys.platform,
            has_taskpolicy=shutil.which("taskpolicy") is not None,
            has_nice=shutil.which("nice") is not None,
            has_ionice=shutil.which("ionice") is not None,
        )
    except Exception:  # noqa: BLE001 — a throttle probe must NEVER break the daemon
        return []


def nice_preexec() -> Optional[Callable[[], None]]:
    """Return a ``preexec_fn`` that lowers the child's CPU priority, or ``None``.

    A POSIX-only CPU baseline that applies EVEN when no external launcher exists
    (macOS without ``taskpolicy``, a stripped Linux): the returned callable runs in
    the forked child just before ``exec`` and calls ``os.nice(19)`` to renice it to
    the lowest priority. Returns ``None`` where ``os.nice`` is unavailable (Windows),
    which ``subprocess.Popen`` treats as "no preexec".

    FAIL-OPEN at both layers:
      * if ``os.nice`` is missing here, return ``None`` (no preexec);
      * the returned callable wraps ``os.nice`` in try/except so a renice failure in
        the child (e.g. ``EPERM``) is swallowed and the process still ``exec``s the
        command. A throttle hiccup must never abort the marketplace refresh.
    """
    if not hasattr(os, "nice"):
        return None

    def _renice() -> None:
        try:
            os.nice(19)
        except Exception:  # noqa: BLE001 — never abort the exec over a failed renice
            pass

    return _renice
