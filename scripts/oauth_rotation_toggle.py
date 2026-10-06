#!/usr/bin/env python3
"""Flip BOTH sides of OAuth rotation at once (#321): `oauth_rotation_toggle.py on|off`.

Janitor side: ``${CLAUDE_PLUGIN_DATA}/oauth-rotator/opt-in.flag`` (set / removed).
Server side (ai-maestro R16 gate, lib/oauth-rotator/server-tick.ts): the file
``~/.aimaestro/oauth-rotator-tick.enabled`` — its PRESENCE enables the server tick (the server
only does ``existsSync``, content is ignored). OFF renames it to ``<name>.DISABLED-<date>-janitor-toggle``,
the same convention the owner already uses, so nothing is deleted.

Both sides move or neither does. WHY: the two halves used to be toggled by commands in two repos,
so a half-state (janitor owns the tick, server disclaimed, or the reverse) was easy to reach. A
disagreeing start is simply driven to the requested state; ownership of the chore while both are
ON is decided by the ORH lease, not by this script. If the second write fails the first is undone.
"""

from __future__ import annotations

import datetime
import os
import sys
from pathlib import Path

SERVER_FLAG_NAME = "oauth-rotator-tick.enabled"


def _janitor_flag() -> Path:
    data = os.environ.get("CLAUDE_PLUGIN_DATA")
    if not data:
        raise SystemExit("CLAUDE_PLUGIN_DATA is unset (Claude Code v2.1+ required)")
    return Path(data) / "oauth-rotator" / "opt-in.flag"


def _write_janitor(flag: Path, content: str | None) -> None:
    """Set the flag to ``content`` atomically, or remove it when ``content`` is None."""
    if content is None:
        flag.unlink(missing_ok=True)
        return
    flag.parent.mkdir(parents=True, exist_ok=True)
    tmp = flag.with_name(f"{flag.name}.tmp.{os.getpid()}")
    tmp.write_text(content)
    os.replace(tmp, flag)


def _set_server(on: bool) -> None:
    flag = Path.home() / ".aimaestro" / SERVER_FLAG_NAME
    if on:
        flag.parent.mkdir(parents=True, exist_ok=True)
        flag.touch()
    elif flag.exists():
        stamp = datetime.date.today().strftime("%Y%m%d")
        # os.rename silently REPLACES an existing target on POSIX, so a second "off" the same
        # day would destroy the first renamed file; pick a free name (-2, -3, ...) instead.
        target = flag.with_name(f"{flag.name}.DISABLED-{stamp}-janitor-toggle")
        n = 2
        while target.exists():
            target = flag.with_name(f"{flag.name}.DISABLED-{stamp}-janitor-toggle-{n}")
            n += 1
        flag.rename(target)


def main(argv: list[str]) -> int:
    if len(argv) != 1 or argv[0] not in ("on", "off"):
        print("usage: oauth_rotation_toggle.py on|off", file=sys.stderr)
        return 2
    on = argv[0] == "on"
    janitor = _janitor_flag()
    previous = janitor.read_text() if janitor.is_file() else None
    _write_janitor(janitor, "on" if on else None)
    try:
        _set_server(on)
    except OSError as exc:
        # Undo the janitor side so we never leave exactly one owner flag flipped.
        _write_janitor(janitor, previous)
        print(f"server flag change failed ({exc}); janitor flag restored", file=sys.stderr)
        return 1
    print(f"OAuth rotation: {'ON' if on else 'OFF'} on both sides (janitor opt-in flag + server R16 flag).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
