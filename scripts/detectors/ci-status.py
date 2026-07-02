#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""ci-status — after a push, watch the pushed commit's GitHub CI/CD runs; notify on failure.

Invoked by scripts/dispatch (the cron heartbeat) or the /janitor-audit skill.

The job (TRDD-AKH7JRAA, USER ask): "check github after every push to see if the ci/cd run
was completed without errors, and if not, immediately notify the main claude."

How it works:
  * Push detection — track `git rev-parse @{push}` (exactly where HEAD was last pushed).
    When it advances past the stored `ci-status-checked-sha.txt`, there is a NEW pushed
    commit whose CI we have not yet resolved.
  * Poll — `gh run list --commit <SHA> ...` (via state.run_subprocess: timeout-bounded,
    never raises). Re-checked each heartbeat until EVERY run for that SHA is terminal.
  * Notify — if any run's conclusion is a failure, print ONE drift line per failed run
    (deduped by run id). A printed drift line IS the notification the main Claude sees on
    the heartbeat. Then stamp the SHA as checked (one notification per push). All-green,
    or no run within the grace window, → silent + stamp.

Fail-open everywhere: not a git repo / no GitHub origin / no `gh` / not authed / network
error → silent no-op (log only), retried on the next heartbeat. Runs in FULL mode only
(detectors are skipped in maintenance/stop), which is correct — CI-watching is
active-development work, not idle keep-warm.
"""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402

# The conclusions that mean "the run did not pass". `skipped`/`neutral`/`success` are NOT
# failures; `action_required` is treated as non-terminal by the status check below.
TERMINAL_FAIL = frozenset({"failure", "timed_out", "cancelled", "startup_failure"})
# A push can legitimately trigger NO workflow (path filters, docs-only). After this long
# with no run for the SHA, stop waiting and stamp it resolved so we never poll it forever.
_DEFAULT_NO_RUN_GRACE_S = 1800


def classify_ci_runs(
    runs: list[dict[str, Any]],
    *,
    now: int,
    first_seen_ts: int,
    no_run_grace_s: int,
) -> tuple[str, list[dict[str, Any]]]:
    """Decide what to do about the CI runs for one pushed SHA. PURE (no I/O).

    Returns (action, failed_runs):
      * "wait"     — not resolvable yet (no runs but still within the grace window, OR a
                     run is still queued/in_progress) → re-check next heartbeat; do NOT
                     stamp the SHA.
      * "resolved" — every run is terminal and NONE failed, OR no run ever appeared and
                     the grace window elapsed → stamp the SHA, emit nothing.
      * "failed"   — every run is terminal and at least one FAILED → stamp + emit one
                     drift line per failed run. `failed_runs` is that subset.
    """
    if not runs:
        if now - first_seen_ts >= no_run_grace_s:
            return ("resolved", [])  # give up — this push triggered no CI
        return ("wait", [])
    # Wait for the WHOLE set to settle: any queued/in_progress/requested/waiting run means
    # the outcome is not final yet, so we must not stamp (and must not cry failure early).
    if any((r.get("status") or "") != "completed" for r in runs):
        return ("wait", [])
    failed = [r for r in runs if (r.get("conclusion") or "") in TERMINAL_FAIL]
    if failed:
        return ("failed", failed)
    return ("resolved", [])


def build_ci_failure_line(pushed_sha: str, branch: str, failed_runs: list[dict[str, Any]]) -> str:
    """Build the one-line drift notification for a failed CI run set. Every gh-derived
    string is UNTRUSTED (a workflow name / title could embed `[`/`]`, control, or bidi
    chars to mimic a janitor marker), so each piece is sanitized individually — the
    literal `[ci-status]` prefix stays ASCII so the line still reads as our own marker."""
    short = pushed_sha[:9]
    parts: list[str] = []
    url = ""
    for r in failed_runs:
        wf = state.sanitize_for_drift_line(
            (r.get("workflowName") or r.get("displayTitle") or "run").strip()
        )
        concl = state.sanitize_for_drift_line((r.get("conclusion") or "?").strip())
        parts.append(f"{wf}={concl}")
        if not url:
            url = state.sanitize_for_drift_line((r.get("url") or "").strip())
    br = state.sanitize_for_drift_line((branch or "?").strip())
    detail = ", ".join(parts)
    tail = f" — {url}" if url else ""
    return f"[ci-status] CI FAILED for {short} ({br}): {detail}{tail}"


def _git(args: list[str], cwd: str) -> Optional[str]:
    proc = state.run_subprocess(
        ["git", *args], timeout=10, cwd=cwd, capture=True, detector_name="ci-status"
    )
    if proc is None or proc.returncode != 0:
        return None
    return (proc.stdout or "").strip()


def _resolve_pushed_sha(cwd: str) -> Optional[str]:
    # `@{push}` is exactly "where HEAD was last pushed" — the precise "after a push"
    # signal. Fall back to `@{upstream}` for a branch configured without a distinct push
    # remote. Both fail (return None) on a detached HEAD or an un-tracked branch → skip.
    for ref in ("@{push}", "@{upstream}"):
        sha = _git(["rev-parse", ref], cwd)
        if sha:
            return sha
    return None


def main() -> int:
    state.init_state()
    if not state.is_truthy_env("CLAUDE_PLUGIN_OPTION_CI_STATUS_ENABLED", True):
        return 0

    cwd = str(state.project_root())
    origin = _git(["remote", "get-url", "origin"], cwd)
    if not origin or "github.com" not in origin:
        state.log_line("ci-status", "no github origin — skipping")
        return 0

    pushed_sha = _resolve_pushed_sha(cwd)
    if not pushed_sha:
        state.log_line("ci-status", "no pushed ref (@{push}/@{upstream}) — skipping")
        return 0

    sd = state.state_dir()
    checked_file = sd / "ci-status-checked-sha.txt"
    checked = checked_file.read_text(encoding="utf-8").strip() if checked_file.exists() else ""
    if pushed_sha == checked:
        return 0  # already fully resolved this SHA's CI — cheap no-op (one rev-parse)

    proc = state.run_subprocess(
        [
            "gh", "run", "list", "--commit", pushed_sha, "--limit", "30",
            "--json", "databaseId,status,conclusion,workflowName,url,displayTitle,headBranch",
        ],
        timeout=30,
        cwd=cwd,
        capture=True,
        detector_name="ci-status",
    )
    if proc is None or proc.returncode != 0:
        # No gh / not authed / network hiccup — fail-open, retry next heartbeat.
        state.log_line("ci-status", "gh run list unavailable (no gh/auth/network?) — retry next fire")
        return 0
    try:
        runs = json.loads(proc.stdout or "[]")
    except (json.JSONDecodeError, ValueError) as exc:
        state.log_line("ci-status", f"gh JSON parse failed: {exc}")
        return 0
    if not isinstance(runs, list):
        return 0

    # First-seen bookkeeping bounds the no-runs-yet wait (grace window). Stored as
    # "<sha>\t<epoch>"; reset whenever the tracked SHA changes.
    first_seen_file = sd / "ci-status-first-seen.txt"
    now = int(time.time())
    first_seen_ts = now
    prev_raw = first_seen_file.read_text(encoding="utf-8").strip() if first_seen_file.exists() else ""
    prev_sha, _, prev_ts = prev_raw.partition("\t")
    if prev_sha == pushed_sha and prev_ts.isdigit():
        first_seen_ts = int(prev_ts)
    else:
        state.atomic_write(first_seen_file, f"{pushed_sha}\t{now}")

    grace = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_CI_STATUS_NO_RUN_GRACE"), _DEFAULT_NO_RUN_GRACE_S
    )
    action, failed = classify_ci_runs(
        runs, now=now, first_seen_ts=first_seen_ts, no_run_grace_s=grace
    )

    if action == "wait":
        return 0  # do NOT stamp — the run set has not settled; re-check next heartbeat

    if action == "failed":
        seen = sd / "ci-status-seen.txt"
        for r in failed:
            branch = str(r.get("headBranch") or "")
            key = f"ci-fail:{pushed_sha}:{r.get('databaseId')}"
            out = dedupe.emit_once(seen, key, build_ci_failure_line(pushed_sha, branch, [r]))
            if out:
                print(out)

    # "resolved" or "failed" → stamp so a future fire treats this SHA as done (one
    # notification per push; a CI re-run on the SAME SHA is the user's own action).
    state.atomic_write(checked_file, pushed_sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
