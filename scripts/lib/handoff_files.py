"""Per-write handoff filenames — the single source of truth for TRDD-5RXBI65T option D.

WHY THIS MODULE EXISTS. `.janitor/state/agent-handoff.md` was ONE fixed path with several
independent writers and no coordination between them:

  * the machine-wide daemon, via `external_handoff_clear.py:428` — an unconditional
    `atomic_write`, no read-before-write, no merge, running in NO Claude turn at all;
  * the `/janitor-write-handoff` skill, where the MODEL authors the expensive semantic handoff
    at a delicate juncture.

The cheap automatic artifact therefore destroyed the costly deliberate one, silently: there was
no `.prev`, and `.janitor/state/` is gitignored, so nothing recovered it. Measured twice —
2026-08-22 17:38:10 and 2026-08-23 09:22 — both by the daemon.

THE FIX IS STRUCTURAL, NOT A POLICY. Every write lands on its OWN path, so there is no shared
path to lose a race on. Readers load every file belonging to one session and replay them in
timestamp order. A guard telling a writer to check before clobbering would still leave the
clobber *possible*; removing the shared path leaves it *unrepresentable*.

WHAT THIS BUYS AND WHAT IT COSTS. The failure MOVES rather than disappears: from "a writer
destroys another writer's bytes" to "a reader selects the wrong group". That is strictly better —
the bytes still exist on disk, so a wrong selection is recoverable and a clobber never was — but
`newest_group` is now the load-bearing part and is commented accordingly.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

import state

# `agent-handoff-<key8>-<YYYYMMDD_HHMMSS±HHMM>-<pid>.md`
#
# The PID is not decoration. Two writers can land in the SAME SECOND — the daemon fires on its
# own schedule and a session can be asked for a handoff at any moment — and a design whose entire
# claim is "no shared path" must not quietly reintroduce one at the second boundary. The pid is
# what makes two same-second writes two files.
_NAME_RE = re.compile(
    r"^agent-handoff-(?P<key>[0-9a-z]{1,16})-"
    r"(?P<ts>\d{8}_\d{6}[+-]\d{4})-"
    r"(?P<pid>\d+)\.md$"
)
_TS_FMT = "%Y%m%d_%H%M%S%z"

# The pre-D path. Still READ (a handoff written by an older plugin version, or by a session that
# has not rolled forward yet, is real knowledge and losing it would be the very bug this module
# fixes). Never WRITTEN any more.
LEGACY_NAME = "agent-handoff.md"
LEGACY_KEY = "legacy"

# The key to use when the TARGET session cannot be resolved. It exists so that "I don't know who
# this belongs to" still produces a PER-WRITE path instead of falling back to the shared one.
# Falling back to `LEGACY_NAME` would have re-created the exact defect this module removes — an
# unconditional write to a path other writers use — for every run that cannot resolve a
# transcript, including one that would land on the model's only handoff. An unkeyed handoff
# groups slightly wrong; a clobbered handoff is gone.
UNKEYED_KEY = "unkeyed"


def session_key(target: str | Path | None) -> str:
    """The group key: the first 8 chars of the TARGET session's id.

    TARGET, emphatically — not the writer's. `state.log_line` tags lines from the WRITER's
    `CLAUDE_CODE_SESSION_ID` (`state.py:903`), and the daemon is a long-lived singleton that
    inherits that variable from whichever session happened to launch it — one id stood for three
    days across every project it served. Keying on the writer would therefore file the daemon's
    handoff under a stranger's id, in a directory where the session that needs it never looks:
    a lost write traded for an unreadable one.

    `target` is a transcript path (`<session-id>.jsonl`) or a bare session id. Returns "" when
    it cannot be resolved, which callers must treat as "do not write a keyed file".
    """
    if not target:
        return ""
    stem = Path(str(target)).name
    if stem.endswith(".jsonl"):
        stem = stem[: -len(".jsonl")]
    key = re.sub(r"[^0-9a-zA-Z]", "", stem).lower()[:8]
    return key


def handoff_name(key: str, *, now: int | None = None, pid: int | None = None) -> str:
    when = datetime.fromtimestamp(now).astimezone() if now else datetime.now().astimezone()
    return f"agent-handoff-{key}-{when.strftime(_TS_FMT)}-{pid or os.getpid()}.md"


def parse(name: str) -> tuple[str, int, int] | None:
    """(key, epoch, pid) for a per-write handoff filename, else None."""
    m = _NAME_RE.match(name)
    if not m:
        return None
    try:
        ts = int(datetime.strptime(m.group("ts"), _TS_FMT).timestamp())
    except ValueError:
        return None  # a well-shaped name carrying an impossible date is not a handoff
    return m.group("key"), ts, int(m.group("pid"))


def write(state_dir: Path, key: str, text: str, *, now: int | None = None) -> Path:
    """Write ONE handoff to its own path. Never overwrites: the pid+timestamp make it unique."""
    path = Path(state_dir) / handoff_name(key, now=now)
    state.atomic_write(path, text)
    return path


def _entries(state_dir: Path) -> list[tuple[str, int, Path]]:
    """(key, epoch, path) for every handoff present, legacy included."""
    out: list[tuple[str, int, Path]] = []
    sd = Path(state_dir)
    try:
        names = list(sd.iterdir())
    except OSError:
        return out
    for p in names:
        parsed = parse(p.name)
        if parsed:
            out.append((parsed[0], parsed[1], p))
        elif p.name == LEGACY_NAME:
            # mtime is the only timestamp a legacy file carries. Using it to ORDER is fine;
            # using it to attribute a WRITER is what cost this card four retractions.
            out.append((LEGACY_KEY, state.file_mtime(p), p))
    return out


def newest_group(state_dir: Path) -> list[Path]:
    """Every handoff of the most recently written session, oldest write FIRST.

    Group by key, rank groups by their NEWEST member, return that group in ascending time so a
    reader replays a session's handoffs in the order they were authored.

    Ranking on the newest member (not the oldest, not the count) is what makes a second handoff
    written minutes after the first keep its group current, instead of a fresh single-file group
    from an unrelated session outranking it.
    """
    groups: dict[str, list[tuple[int, Path]]] = {}
    for key, ts, path in _entries(state_dir):
        groups.setdefault(key, []).append((ts, path))
    if not groups:
        return []
    best = max(groups.values(), key=lambda g: max(ts for ts, _ in g))
    return [p for _, p in sorted(best)]


def in_session_key() -> str:
    """The key for a writer running INSIDE the session it is handing off.

    Here — and ONLY here — `CLAUDE_CODE_SESSION_ID` is the right source: the writer IS the
    target, so the writer's own id is the target's id. The daemon must never use this (it is a
    long-lived singleton carrying whichever session launched it); it derives the key from the
    target's transcript instead. Same function name would have invited exactly that mistake, so
    the two paths are deliberately separate and each says why.

    Falls back to `UNKEYED_KEY` rather than "" so a caller always has a usable filename: an
    unkeyed handoff groups imprecisely, a missing one is lost.
    """
    return session_key(os.environ.get("CLAUDE_CODE_SESSION_ID", "")) or UNKEYED_KEY


def newest(state_dir: Path) -> Path | None:
    """The single most recent handoff — for callers asking only "does one exist, is it concise".

    Deliberately NOT "the newest group's first file": the concision contract is judged PER FILE
    (each handoff is one artifact a reader must swallow on its own), so the right question for a
    gate is about one file, and per-file keeps the ratified constants in
    `clear_trigger.check_handoff_concise` untouched.
    """
    entries = _entries(state_dir)
    if not entries:
        return None
    return max(entries, key=lambda e: e[1])[2]


def _main() -> int:
    """`handoff_files.py --path` — print the filename an in-session writer should Write to.

    Exists because the `/janitor-write-handoff` skill is executed by the MODEL, which cannot be
    asked to build a timestamp+pid filename by hand every time and get it right. One command,
    one absolute path, no room to improvise the grammar.
    """
    import sys

    if "--path" not in sys.argv[1:]:
        print("usage: handoff_files.py --path", file=sys.stderr)
        return 2
    project = os.environ.get("CLAUDE_PROJECT_DIR", "").strip()
    if not project:
        print("CLAUDE_PROJECT_DIR unset — cannot locate the janitor state dir", file=sys.stderr)
        return 1
    sd = Path(project) / ".janitor" / "state"
    sd.mkdir(parents=True, exist_ok=True)
    print(str(sd / handoff_name(in_session_key())))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
