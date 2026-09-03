#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Compose the CURRENT session's handoff with ZERO model tokens (TRDD-2F3I2P18 follow-on).

WHY THIS EXISTS. `janitor-write-handoff` today asks the MODEL to author the semantic handoff
prose — real tokens, spent inside the very turn that is about to be compacted/cleared. This
script replaces that authorship with the same out-of-process `llm-ext` summarizer the daemon
already uses for the PREVIOUS session (`summarize_previous_session.py`), pointed at THIS
session's own transcript instead.

WHY IT IS A SEPARATE SCRIPT, NOT A FLAG ON THE SIBLING. `summarize_previous_session.py` exists
specifically to EXCLUDE the live session's transcript (`previous_transcript` filters it out by
stem) — that exclusion is load-bearing there, because summarizing your own still-growing
transcript from a background daemon would race the very session it targets. Here the model is
asking for its OWN handoff, synchronously, mid-turn: there is no race to guard against and no
resume-hold to coordinate (unlike the daemon path, nothing here is deciding whether to `/clear`
or waiting out a TTL before resuming blind) — so the hold/pending machinery in
`external_handoff_clear.py` does not apply and is deliberately not used.

NOTHING HERE COSTS CLAUDE TOKENS. `llm-ext` runs out of process against its own models; this
script's whole job is to name the source, summarize, and write.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import external_clear as ec  # noqa: E402
import handoff_files  # noqa: E402
import state  # noqa: E402

_LOG = "agent-handoff-compose"

# Same budget as the sibling's hold TTL (`external_handoff_clear._HOLD_TTL_S`) — there is no
# hold here to derive a deadline FROM, so this is a plain constant instead of a read-off-disk
# value. 15 minutes is long enough for llm-ext's retry/backoff to ride out a transient failure,
# short enough that a genuinely broken summarizer degrades within one skill invocation.
_SUMMARY_BUDGET_S = 15 * 60


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", required=True, help="absolute path to the project root")
    parser.add_argument(
        "--dry-run", action="store_true", help="print the composed text; write nothing"
    )
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    # Built from `--project-root` directly (`root / ".janitor" / "state"`), not
    # `state.state_dir()` — that helper resolves from `CLAUDE_PROJECT_DIR`/cwd, which need not
    # agree with an explicitly-passed root (same reasoning as `external_handoff_clear.py:446`).
    sd = root / ".janitor" / "state"
    now = int(time.time())

    import cold_cache_compact  # noqa: PLC0415 - only this path needs it

    transcript = cold_cache_compact.newest_transcript(root)
    if transcript is None:
        print("NO_TRANSCRIPT")
        state.log_line(_LOG, "no transcript found for this session — nothing to summarize")
        return 0

    got = ec.summarize_with_retry(str(transcript), deadline=time.time() + _SUMMARY_BUDGET_S)
    text = (got.text or "").strip()
    if not text:
        reason = f"{got.outcome}: {got.detail}"
        print(f"SUMMARY_FAILED {reason}")
        state.log_line(_LOG, f"llm-ext produced no summary ({reason}) — degrading, nothing written")
        return 0

    if args.dry_run:
        print("DRY_RUN")
        print(text)
        return 0

    key = handoff_files.in_session_key()
    path = handoff_files.write(sd, key, text, now=now)

    # Same one-line pointer the model-authored path writes (janitor-write-handoff SKILL.md
    # step 3) — the PostCompact hook and the heartbeat's resume nudge only know to look here.
    directive = (
        "read the newest .janitor/state/agent-handoff-*.md FIRST (rich agent handoff), "
        "then continue the in-flight work"
    )
    state.atomic_write(sd / "resume-directive.txt", directive + "\n")

    print(f"HANDOFF_READY {len(text.encode('utf-8'))}")
    state.log_line(_LOG, f"wrote {path.name} ({len(text)} chars) and the resume directive")
    return 0


if __name__ == "__main__":
    sys.exit(main())
