#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for the /janitor-memory-*-frequency-{set,get} + -maxsize commands
(TRDD-c1397102).

Reads / writes the GLOBAL wikimem-editor settings store (machine-wide, not
per-repo). `set <key>` with NO value reverts that key to its default. Every
frequency is a times-per-day float (0.5 = once/48h; 0 = disabled). Fail-fast: a
bad value exits non-zero with a clear message, never silently coerces.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import memory_settings  # noqa: E402


def _describe(key: str, value) -> str:
    """One human line for a setting: a per-day rate shows its cadence; 0 shows
    DISABLED; other keys show the raw value."""
    if key in memory_settings._PER_DAY_KEYS:
        rate = float(value)
        if rate <= 0:
            return f"{key} = 0 (DISABLED)"
        hours = memory_settings.interval_s(key) / 3600.0
        return f"{key} = {rate:g}/day (~every {hours:.1f}h)"
    return f"{key} = {value}"


def main() -> int:
    ap = argparse.ArgumentParser(prog="memory_settings_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get", help="print a setting")
    g.add_argument("key")
    s = sub.add_parser("set", help="set a setting; no value reverts to default")
    s.add_argument("key")
    s.add_argument("value", nargs="?", default=None)
    args = ap.parse_args()

    try:
        if args.cmd == "get":
            print(_describe(args.key, memory_settings.get(args.key)))
        else:
            # An empty-string arg (from a bare `... set <key> ` invocation with no
            # number) means "revert to default", same as omitting it.
            raw = args.value if (args.value is not None and args.value.strip() != "") else None
            value = memory_settings.set_value(args.key, raw)
            suffix = " (reverted to default)" if raw is None else ""
            print(f"set {_describe(args.key, value)}{suffix}")
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
