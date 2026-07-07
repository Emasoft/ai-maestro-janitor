#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Backing script for the /janitor-memory-*-frequency-{set,get} + -maxsize commands
(TRDD-c1397102) and the shell-reachable cadence gate (issue #68 P1, TRDD-UENXDA8P).

Reads / writes the GLOBAL wikimem-editor settings store (machine-wide, not
per-repo). `set <key>` with NO value reverts that key to its default. Every
frequency is a times-per-day float (0.5 = once/48h; 0 = disabled). Fail-fast: a
bad value exits non-zero with a clear message, never silently coerces.

Cadence verbs (so skills/agents self-gate + stamp from Bash instead of a fragile
inline lib import — the import failed from agent shells in real editorial runs):

    is-due  <intervention> <scope> [--root PATH] [--now EPOCH]  → `due` (exit 0) | `not-due` (exit 1)
    mark-ran <intervention> <scope> [--root PATH] [--now EPOCH] → stamps the cadence (exit 0)

Scope labels are the scheduler's (LOCAL / PROJECT / USER, case-insensitive here —
normalized to UPPERCASE because the stamp filename embeds the label verbatim and a
lowercase variant would fork the cadence). Without --root the scope's root is
resolved via memory_scopes.resolve_scope_dirs(); --root pins a specific corpus
(and keeps tests hermetic). --now is a test/debug escape hatch (defaults to the
wall clock).
"""

from __future__ import annotations

import argparse
import sys
import time
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


def _resolve_scope_root(scope: str, root_arg: str | None) -> tuple[str, Path]:
    """Normalize the scope label to the scheduler's UPPERCASE form and resolve its
    memory root (explicit --root wins; else resolve_scope_dirs)."""
    label = scope.strip().upper()
    if label not in ("LOCAL", "PROJECT", "USER"):
        raise ValueError(f"unknown scope {scope!r} (expected LOCAL, PROJECT or USER)")
    if root_arg:
        return label, Path(root_arg)
    import memory_scopes  # noqa: PLC0415 — lazy: only the cadence verbs need it

    for found_label, root in memory_scopes.resolve_scope_dirs():
        if found_label == label:
            return label, root
    raise ValueError(f"scope {label} has no existing memory root on this machine (pass --root)")


def main() -> int:
    ap = argparse.ArgumentParser(prog="memory_settings_cli")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get", help="print a setting")
    g.add_argument("key")
    s = sub.add_parser("set", help="set a setting; no value reverts to default")
    s.add_argument("key")
    s.add_argument("value", nargs="?", default=None)
    for verb, help_text in (
        ("is-due", "print due/not-due for an intervention (exit 0 = due, 1 = not due)"),
        ("mark-ran", "record the cadence stamp for an intervention"),
    ):
        c = sub.add_parser(verb, help=help_text)
        c.add_argument("intervention")
        c.add_argument("scope")
        c.add_argument("--root", default=None, help="pin the memory root (else resolved from the scope)")
        c.add_argument("--now", type=int, default=None, help="epoch override (tests/debugging)")
    args = ap.parse_args()

    try:
        if args.cmd == "get":
            print(_describe(args.key, memory_settings.get(args.key)))
        elif args.cmd in ("is-due", "mark-ran"):
            label, root = _resolve_scope_root(args.scope, args.root)
            now = int(args.now if args.now is not None else time.time())
            # interval_s_for validates the intervention name (raises ValueError on junk)
            memory_settings.interval_s_for(args.intervention)
            if args.cmd == "is-due":
                due = memory_settings.is_due(args.intervention, label, root, now)
                print("due" if due else "not-due")
                return 0 if due else 1
            memory_settings.mark_ran(args.intervention, label, root, now)
            print(f"marked {args.intervention} @ {label} ({root}) at {now}")
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
