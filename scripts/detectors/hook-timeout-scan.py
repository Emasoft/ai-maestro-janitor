#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""hook-timeout-scan — record hooks the harness killed, or that came close (TRDD-QX59MA4H).

The harness kills a hook that exceeds its timeout and leaves ONLY a transcript record; nothing
else notices, so the hook's work is silently lost on every run. This reads the CURRENT project's
session transcripts (`~/.claude/projects/<slug>/*.jsonl`) and records:

  HOOK-001  `attachment.type == hook_cancelled` with `attachment.timedOut == true`; one per
            (session, hookName). The text "timed out after" is NOT the signal — it occurs in
            unrelated prose and tool output (measured, TRDD-DSN035UN card C00/U4).
  HOOK-002  a `hook_success` / `hook_cancelled` record whose `durationMs` is >= 80% of the hook
            budget; one per (hook command, hour). JANITOR hooks only: the budget is the record's
            `timeoutMs` (hook_cancelled carries it, hook_success does not), else the timeout
            configured for that exact command in this plugin's hooks/hooks.json. The record holds
            the literal `${CLAUDE_PLUGIN_ROOT}` text, so the match is on the script path relative
            to the plugin root. No known budget means skipped, never guessed.

Bounded: only transcripts touched in the last 24 h, and only the last 4 MiB of each (transcripts
reach gigabytes). Non-UTF-8 bytes and a torn last line are skipped line by line, never fatal.
Findings name the hook and the session id, never a path (the home path carries the user name).

NOT DONE HERE (still owed, TRDD-U32EVMI9): replaying a cancelled guard's own check over the
recorded input to tell a harmless cancellation from a real miss.
Subagent transcripts in subfolders and sessions run from a worktree (different slug) are not
scanned.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import findings_ledger  # noqa: E402
import state  # noqa: E402

_NAME = "hook-timeout-scan"
_THRESHOLD = 0.8
_MAX_AGE_S = 86400
_TAIL_BYTES = 4 * 1024 * 1024
_MAX_PRINTED = 5
_ROOT_VAR = "${CLAUDE_PLUGIN_ROOT}/"


def _script_rel(command: str) -> str | None:
    """Script path of a hook command, relative to the plugin root, or None if not janitor-shaped."""
    parts = command.split()
    if not parts:
        return None
    last = parts[-1]
    return last[len(_ROOT_VAR):] if last.startswith(_ROOT_VAR) else None


def _configured_timeouts(plugin_root: Path) -> dict[str, float]:
    """script-relative-path -> timeout seconds, from this plugin's own hooks.json."""
    data = json.loads((plugin_root / "hooks" / "hooks.json").read_text(encoding="utf-8"))
    out: dict[str, float] = {}
    for groups in data.get("hooks", {}).values():
        for group in groups:
            for hook in group.get("hooks", []):
                rel = _script_rel(str(hook.get("command", "")))
                if rel is not None and "timeout" in hook:
                    out[rel] = float(hook["timeout"])
    return out


def _tail_lines(path: Path) -> list[bytes]:
    size = path.stat().st_size
    with path.open("rb") as fh:
        if size > _TAIL_BYTES:
            fh.seek(size - _TAIL_BYTES)
            fh.readline()  # drop the partial line the seek landed in
        return fh.read().split(b"\n")


def _records(path: Path):
    for raw in _tail_lines(path):
        if b'"hook_' not in raw:
            continue
        try:
            rec = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError:  # torn last line or garbage: skip, never crash
            continue
        # WHY: a line can be valid JSON yet not an object (a string or list that merely
        # mentions hook_); rec.get below would raise AttributeError and kill the detector.
        if not isinstance(rec, dict):
            continue
        att = rec.get("attachment")
        if rec.get("type") == "attachment" and isinstance(att, dict):
            yield rec, att


def _hour_bucket(rec: dict, now: int) -> int:
    ts = rec.get("timestamp")
    if isinstance(ts, str):
        try:
            from datetime import datetime

            return int(datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()) // 3600
        except ValueError:
            pass
    return now // 3600


def main() -> int:
    state.init_state()
    home = os.environ.get("HOME", "").strip() or os.path.expanduser("~")
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(state.project_root()))
    tdir = Path(home) / ".claude" / "projects" / slug
    if not tdir.is_dir():
        return 0
    plugin_root = Path(os.environ.get("CLAUDE_PLUGIN_ROOT") or Path(__file__).resolve().parent.parent.parent)
    now = int(time.time())
    seen = state.state_dir() / "hook-timeout-scan-seen.txt"
    lines: list[str] = []

    try:
        configured = _configured_timeouts(plugin_root)
    except (OSError, ValueError) as exc:
        state.log_line(_NAME, f"hooks.json unreadable, HOOK-002 skipped: {exc}")
        configured = {}

    for path in sorted(tdir.glob("*.jsonl")):
        try:
            if now - path.stat().st_mtime > _MAX_AGE_S:
                continue
            records = list(_records(path))
        except OSError as exc:
            state.log_line(_NAME, f"transcript unreadable, skipped: {exc}")
            continue
        for rec, att in records:
            sid = str(rec.get("sessionId") or path.stem)
            hook = str(att.get("hookName") or "?")
            command = str(att.get("command") or "")
            dur = att.get("durationMs")
            tmo = att.get("timeoutMs")

            if att.get("type") == "hook_cancelled" and att.get("timedOut") is True:
                if dedupe.emit_once(seen, f"HOOK-001@{sid}@{hook}", "x"):
                    ran = f"{dur}ms" if dur is not None else "duration unknown"
                    spent = f"{ran} of {tmo}ms" if tmo is not None else f"{ran}, timeout unknown"
                    line = findings_ledger.record(
                        sev="HIGH", code="HOOK-001", src=_NAME,
                        msg=f"hook {hook} was killed for exceeding its timeout ({spent}) in session {sid}",
                    )
                    if line:
                        lines.append(line)
                # WHY: a killed hook is fully described by HOOK-001; its duration sits at the
                # budget by construction, so falling through would add a redundant HOOK-002.
                continue

            if att.get("type") not in ("hook_success", "hook_cancelled") or not isinstance(dur, (int, float)):
                continue
            rel = _script_rel(command)
            if rel is None or rel not in configured:
                continue  # not a janitor hook: its budget is not ours to judge
            budget_ms = float(tmo) if isinstance(tmo, (int, float)) and tmo > 0 else configured[rel] * 1000
            if dur < _THRESHOLD * budget_ms:
                continue
            if dedupe.emit_once(seen, f"HOOK-002@{rel}@{_hour_bucket(rec, now)}", "x"):
                line = findings_ledger.record(
                    sev="MEDIUM", code="HOOK-002", src=_NAME,
                    msg=f"hook {hook} ({rel}) used {dur / budget_ms:.0%} of its {budget_ms / 1000:g}s budget",
                )
                if line:
                    lines.append(line)

    # WHY: every finding is already in the ledger; stdout reaches the agent's context, so a
    # flood (one stuck hook across many sessions) is capped to keep that channel bounded.
    for line in lines[:_MAX_PRINTED]:
        print(line)
    if len(lines) > _MAX_PRINTED:
        print(f"{_NAME}: {len(lines) - _MAX_PRINTED} more recorded, see /janitor-findings")

    state.rotate_log_if_big(_NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
