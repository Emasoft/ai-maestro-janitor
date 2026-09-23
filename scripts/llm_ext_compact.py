#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Thin llm-ext fallback CLI (TRDD-RAEGS1D5, owner decision 3 of 2026-09-23).

WHY THIS EXISTS. The owner's ruling: "if jev is not working after 5 minutes retries, the
llm-ext compaction function must be called as a fallback ... but llm-ext must be used if jev
is unavailable after 5 minutes." The AUTOMATIC Jev-compaction lane
(`scripts/summarize_previous_session.py`, via `scripts/lib/jev_compaction_lane.py`) is the
caller that owns that 5-minute retry budget and the fallback decision — but that lane is
stdlib-only PEP-723 (`tests/test_jev_boundary.py` forbids it, and every other automatic-lane
file, from importing `llm_ext_summary` in-process — the SAME reason `jev_compact.py` is its
own separate httpx-carrying process rather than an in-process import). This script is the
llm-ext equivalent: its OWN PEP-723 process, EXEC'd BY PATH (like `jev_compact.py`), never
imported by the automatic lane. The automatic lane may EXEC this script, but must NEVER
`import llm_ext_summary` itself — that boundary is enforced by
`tests/test_jev_boundary.py::test_no_hook_or_named_lib_script_imports_jevctx_or_httpx`, and
THIS file is one of the two entries `_LLM_EXT_SUMMARY_ALLOWED` names as an allowed importer
(the other is `compose_agent_handoff.py`, the pre-existing manual-lane composer).

Contract: `--transcript PATH --timeout-s N`. Prints the summary text on stdout and exits 0 on
`llm_ext_summary.OUTCOME_OK`; otherwise prints `<outcome>: <detail>` on stderr and exits 1.
ONE attempt, no retry loop in here — `jev_compaction_lane.run_compact_with_fallback` already
owns the retry-vs-fallback decision, and retrying inside both layers would double the budget
the summary hold's 15-minute ceiling was sized around.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(_SCRIPTS / "lib"))

import llm_ext_summary as les  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--timeout-s", type=int, default=les.ec.LLM_EXT_TIMEOUT_S)
    args = parser.parse_args()

    attempt = les.attempt_llm_ext_summary(args.transcript, timeout_s=args.timeout_s)
    if attempt.outcome == les.OUTCOME_OK and attempt.text:
        print(attempt.text)
        return 0
    print(f"{attempt.outcome}: {attempt.detail}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
