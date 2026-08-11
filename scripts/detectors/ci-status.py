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

import findings_ledger  # noqa: E402
import state  # noqa: E402

# The conclusions that mean "the run did not pass". `skipped`/`neutral`/`success` are NOT
# failures. `action_required` is NOT a failure either — but it is NOT a clean pass: a run
# carrying it has status `completed` yet is BLOCKED awaiting a human (a deployment-approval
# gate, a first-time-contributor gate), so it is treated as UNSETTLED below (kept under
# watch, bounded by the max-wait window) rather than silently stamped green.
TERMINAL_FAIL = frozenset({"failure", "timed_out", "cancelled", "startup_failure"})
_BLOCKED_CONCLUSION = "action_required"
# A push can legitimately trigger NO workflow (path filters, docs-only). After this long
# with no run for the SHA, stop waiting and stamp it resolved so we never poll it forever.
_DEFAULT_NO_RUN_GRACE_S = 1800
# Absolute cap on how long we keep re-checking a run set that never reaches a clean terminal
# state (a job stuck in `queued`/`waiting`, or blocked on manual approval). Past this we give
# up — report anything already failed, else stamp resolved — so a stuck run is never polled
# forever (the module docstring's bounded, fail-open promise).
_DEFAULT_MAX_WAIT_S = 21600  # 6h


def classify_ci_runs(
    runs: list[dict[str, Any]],
    *,
    now: int,
    first_seen_ts: int,
    no_run_grace_s: int,
    max_wait_s: int = _DEFAULT_MAX_WAIT_S,
) -> tuple[str, list[dict[str, Any]]]:
    """Decide what to do about the CI runs for one pushed SHA. PURE (no I/O).

    Returns (action, failed_runs):
      * "wait"     — not resolvable yet (no runs but still within the grace window, OR a run
                     is still queued/in_progress/blocked and the max-wait window has not
                     elapsed) → re-check next heartbeat; do NOT stamp the SHA.
      * "resolved" — every run is terminal and NONE failed, OR no run ever appeared and the
                     grace window elapsed, OR the max-wait window elapsed with nothing failed
                     → stamp the SHA, emit nothing.
      * "failed"   — at least one run FAILED (and either the whole set settled, or the
                     max-wait window elapsed) → stamp + emit one drift line per failed run.
    """
    if not runs:
        if now - first_seen_ts >= no_run_grace_s:
            return ("resolved", [])  # give up — this push triggered no CI
        return ("wait", [])

    # A run is "settled" only when completed AND not blocked awaiting a human. Any
    # queued/in_progress/waiting run, or a completed-but-`action_required` run, means the
    # outcome is not final — do not stamp (and do not cry failure early)…
    def _unsettled(r: dict[str, Any]) -> bool:
        return (r.get("status") or "") != "completed" or (
            r.get("conclusion") or ""
        ) == _BLOCKED_CONCLUSION

    if any(_unsettled(r) for r in runs):
        # …but bound the total wait, so a set that never settles is not polled forever.
        # Past the cap we fall through and judge on whatever HAS concluded.
        if now - first_seen_ts < max_wait_s:
            return ("wait", [])
    failed = [r for r in runs if (r.get("conclusion") or "") in TERMINAL_FAIL]
    if failed:
        return ("failed", failed)
    return ("resolved", [])


def _clean(raw: str) -> str:
    """Sanitize ONE untrusted gh string for a single drift line: defang marker chars AND
    collapse ALL whitespace to single spaces. `sanitize_for_drift_line` intentionally KEEPS
    embedded `\\n`/`\\t`, so a workflow name / title carrying a newline would otherwise split
    our one-line notification into a SECOND, attacker-influenced physical line fed to the
    main Claude — `.split()`/join flattens that back to one line (TRDD-AKH7JRAA review)."""
    return " ".join(state.sanitize_for_drift_line(raw or "").split())


def build_ci_failure_line(pushed_sha: str, branch: str, failed_runs: list[dict[str, Any]]) -> str:
    """Build the one-line drift notification for a failed CI run set. Every gh-derived
    string is UNTRUSTED (a workflow name / title could embed `[`/`]`, control, whitespace,
    or bidi chars to mimic a janitor marker or split the line), so each piece is cleaned
    individually — the literal `[ci-status]` prefix stays ASCII so the line still reads as
    our own marker."""
    short = pushed_sha[:9]
    parts: list[str] = []
    url = ""
    for r in failed_runs:
        wf = _clean(r.get("workflowName") or r.get("displayTitle") or "run")
        concl = _clean(r.get("conclusion") or "?")
        parts.append(f"{wf}={concl}")
        if not url:
            url = _clean(r.get("url") or "")
    br = _clean(branch or "?")
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


def _read_text_safe(path: Path) -> str:
    """Fail-open text read of a state file: an unreadable/corrupt file must never crash the
    heartbeat (the module's fail-open contract), so any error degrades to '' and the detector
    re-checks/re-stamps and self-heals (TRDD-AKH7JRAA — /code-review)."""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


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
    checked = _read_text_safe(checked_file)
    if pushed_sha == checked:
        return 0  # already resolved this SHA's CI — cheap no-op (~2 git rev-parses: origin + push ref)

    proc = state.run_subprocess(
        [
            "gh", "run", "list", "--commit", pushed_sha, "--limit", "100",
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
    prev_raw = _read_text_safe(first_seen_file)
    prev_sha, _, prev_ts = prev_raw.partition("\t")
    if prev_sha == pushed_sha and prev_ts.isdigit():
        first_seen_ts = int(prev_ts)
    else:
        state.atomic_write(first_seen_file, f"{pushed_sha}\t{now}")

    grace = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_CI_STATUS_NO_RUN_GRACE"), _DEFAULT_NO_RUN_GRACE_S
    )
    max_wait = state.coerce_int(
        os.environ.get("CLAUDE_PLUGIN_OPTION_CI_STATUS_MAX_WAIT"), _DEFAULT_MAX_WAIT_S
    )
    action, failed = classify_ci_runs(
        runs, now=now, first_seen_ts=first_seen_ts, no_run_grace_s=grace, max_wait_s=max_wait
    )

    if action == "wait":
        return 0  # do NOT stamp — the run set has not settled; re-check next heartbeat

    if action == "failed":
        # Print IS the delivery; the SHA-stamp below is the real one-per-push dedup. The
        # prior code emitted via dedupe.emit_once() then stamped UNCONDITIONALLY — when that
        # emit silently returned None on lock-dir contention, the failure was dropped AND the
        # SHA marked resolved, violating "immediately notify on failure" with no trace. So we
        # print directly and drop the redundant lock (TRDD-AKH7JRAA — /code-review).
        #
        # A dead/expired heartbeat cron (or a fire nobody reads) meant this print() was the
        # ONLY record of the failure — lost forever the moment it scrolled past. Also record
        # it into the findings ledger (survives via SessionStart re-surfacing) — mirroring
        # model-fallback.py's pattern: print our own richer line, and separately call
        # `record()` for its ledger side-effect WITHOUT using its returned `[findings]`
        # line, so the failure is emitted to the terminal exactly once.
        for r in failed:
            branch = str(r.get("headBranch") or "")
            line = build_ci_failure_line(pushed_sha, branch, [r])
            print(line)
            try:
                findings_ledger.record(
                    sev="HIGH",
                    code="CI-FAILED",
                    src="ci-status",
                    msg=line,
                    ref=pushed_sha[:9],
                    now=now,
                )
            except Exception:  # noqa: BLE001 -- the mailbox must never break the alarm
                pass

    # "resolved" or a delivered failure → stamp so a future fire treats this SHA as done (one
    # notification per push; a CI re-run on the SAME SHA is the user's own action).
    state.atomic_write(checked_file, pushed_sha)
    return 0


if __name__ == "__main__":
    sys.exit(main())
