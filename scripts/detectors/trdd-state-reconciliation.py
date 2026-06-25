#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""trdd-state-reconciliation — SURFACE shipped-but-open kanban board drift.

The gap this closes (TRDD-15ECPBSA): none of the existing TRDD detectors
(trdd-drift, trdd-reminder, report-to-trdd-drift) cross-check a TRDD's CLAIMED
`column:` against the GROUND TRUTH of whether its code is already in a released
git tag. A TRDD whose work SHIPPED but whose column never advanced past `dev`
(or that sits in `blocked` behind a now-resolved blocker) is invisible to those
detectors, accumulates silently, and misleads every later reader — exactly the
incident that motivated this (TRDD-3b9b2040 sat at `dev` for weeks after its
work was in released tags, then got summarised as "close" while its own STATE
prose still claimed a now-STALE block).

Four checks (each a PURE function in trdd_common, unit-tested with a fake
commit->tags map). The keystone (commits-in-a-released-tag) is NECESSARY but NOT
SUFFICIENT — it over-includes partially-shipped TRDDs that still have in-scope
work — so it is PAIRED with a remaining-work gate. Output is SURFACE-ONLY: a
candidate report + ONE drift line. This detector NEVER mutates a TRDD's
`column:` — a conscious pass (a session/agent) does the close after reading the
full STATE, exactly as the memory-librarian surfaces but never mutates.

Project-scoped; READ-ONLY on the repo except its own report + drift line; no
network beyond the local `git tag --contains` / `git log` it already needs.
Low cadence (≈ daily); per-(TRDD,verdict) seen-file dedupe so a still-open
candidate is not re-nagged every heartbeat.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402
import trdd_common  # noqa: E402

# Cap how many flagged TRDDs we name inline in the single drift line — the full
# list always lives in the report. Keeps the heartbeat line short.
_MAX_LISTED = 8


def _released_tags_for(sha: str, root: Path) -> list[str]:
    """Return the `v*` release tags that contain `sha` (empty if none / on error).

    `git tag --contains <sha>` lists every tag whose history includes the
    commit; we keep only the `v*`-prefixed release tags (the project's release
    tags are `v0.21.0` etc.). Bounded by a short timeout — a corrupt refs pack
    would otherwise hang the heartbeat.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(root), "tag", "--contains", sha, "v*"],
        timeout=8,
        detector_name="trdd-state-reconciliation",
    )
    if proc is None or proc.returncode != 0:
        return []
    return [ln.strip() for ln in proc.stdout.splitlines() if ln.strip().startswith("v")]


def _subject_commits_for_uid(uid: str, log_lines: list[tuple[str, str]]) -> list[str]:
    """SHAs whose commit SUBJECT references `TRDD-<uid>` (case-insensitive).

    Commit-discipline puts `TRDD-<id8>` in commit subjects, so a TRDD's commits
    are greppable even when `implementation-commits:` is unpopulated. `log_lines`
    is the pre-fetched `[(sha, subject)]` board log so we grep it once, not once
    per TRDD.
    """
    needle = f"trdd-{uid}".lower()
    return [sha for sha, subj in log_lines if needle in subj.lower()]


def _load_git_log(root: Path) -> list[tuple[str, str]]:
    """Return `[(sha, subject)]` for the whole repo history, or [] on error.

    Read once per run and reused for every TRDD's subject-grep. `%H` + `%s` with
    a NUL field separator so a subject containing spaces/tabs parses cleanly.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(root), "log", "--no-color", "--format=%H%x00%s"],
        timeout=20,
        detector_name="trdd-state-reconciliation",
    )
    if proc is None or proc.returncode != 0:
        return []
    out: list[tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if "\x00" in line:
            sha, subj = line.split("\x00", 1)
            if sha:
                out.append((sha, subj))
    return out


def _main_root(root: Path) -> Path:
    """Resolve the MAIN repo root (worktree-safe), falling back to `root`.

    `git worktree list` lists the main checkout first, even from a linked
    worktree — so reports always land under the primary working tree, never a
    branch's worktree that gets deleted (per agent-reports-location.md).
    """
    proc = state.run_subprocess(
        ["git", "-C", str(root), "worktree", "list"],
        timeout=8,
        detector_name="trdd-state-reconciliation",
    )
    if proc is not None and proc.returncode == 0:
        first = proc.stdout.splitlines()[0:1]
        if first:
            candidate = first[0].split()[0:1]
            if candidate:
                p = Path(candidate[0])
                if p.is_dir():
                    return p
    return root


def _write_report(main_root: Path, rows: list[dict]) -> Path | None:
    """Write the candidate board report; return its path (None if write failed).

    One row per flagged TRDD: id, column, which checks fired, the evidence
    (shipped commits/tags, stale blockers). Lands under the MAIN-repo
    `reports/trdd-reconciliation/` with a local-time + GMT-offset timestamp.
    """
    report_dir = main_root / "reports" / "trdd-reconciliation"
    ts = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S%z")
    report_path = report_dir / f"{ts}-board.md"
    iso = datetime.now().astimezone().strftime("%Y-%m-%dT%H:%M:%S%z")

    lines: list[str] = [
        "# TRDD state-reconciliation — candidate board",
        "",
        f"Generated: {iso}",
        "",
        "SURFACE-ONLY: these are CANDIDATES for a conscious close/unblock pass — "
        "this detector mutated ZERO TRDD files. Verify each TRDD's full STATE + "
        "git before acting (a shipped-but-blocked TRDD is review, NOT closeable).",
        "",
        "| TRDD | column | verdict | checks fired | evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        uid = r["uid"] or "?"
        evidence_bits: list[str] = []
        if r["shipped_commits"]:
            tags = ",".join(sorted(r["shipped_tags"])[:3]) or "released"
            evidence_bits.append(
                f"shipped in {tags} ({len(r['shipped_commits'])} commit(s) "
                f"e.g. {r['shipped_commits'][0][:12]})"
            )
        if r["prose_mismatch"]:
            evidence_bits.append("prose says blocked; frontmatter column != blocked & blocked-by: []")
        if r["stale_blockers"]:
            evidence_bits.append("stale blocker(s): " + ", ".join(r["stale_blockers"]))
        evidence = "; ".join(evidence_bits) or "—"
        lines.append(
            f"| TRDD-{uid} | {r['column'] or '?'} | {r['label']} | "
            f"{', '.join(r['fired'])} | {evidence} |"
        )
    lines.append("")

    try:
        report_dir.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(lines), encoding="utf-8")
    except OSError as exc:
        state.log_line("trdd-state-reconciliation", f"report write failed: {exc}")
        return None
    return report_path


def main() -> int:
    state.init_state()
    # Context gate (TRDD-db169d9e R1): TRDD enforcement is an ai-maestro/Emasoft
    # framework convention. The janitor runs at USER scope in EVERY project, so
    # stay silent in projects that aren't ai-maestro-plugins members. (Override
    # with JANITOR_FORCE_AI_MAESTRO=1 to use TRDDs in a non-ai-maestro project.)
    if not state.project_is_ai_maestro():
        return 0

    seen = state.state_dir() / "trdd-state-reconciliation-seen.txt"

    root = state.project_root()
    trdd_subpath = os.environ.get("CLAUDE_PLUGIN_OPTION_TRDD_PATH", "design/tasks").rstrip("/")
    trdd_dir = root / trdd_subpath

    # Containment check — see trdd-drift.py for the rationale. A misconfigured
    # TRDD path must NOT cause the detector to scan outside the project.
    try:
        resolved_trdd = trdd_dir.resolve()
        resolved_root = root.resolve()
        resolved_trdd.relative_to(resolved_root)
    except (ValueError, OSError):
        state.log_line(
            "trdd-state-reconciliation",
            f"TRDD path {trdd_subpath!r} resolves outside project root — refusing to scan",
        )
        return 0

    if not trdd_dir.is_dir():
        state.log_line("trdd-state-reconciliation", f"TRDD dir {trdd_dir} not present — skipping")
        return 0

    # Pass 1 — parse every TRDD into a record + build the uid->column board so
    # Check 4 can resolve a blocker's CURRENT column without re-reading files.
    records: list[trdd_common.TrddRecord] = []
    column_by_uid: dict[str, str] = {}
    for f in sorted(trdd_dir.glob("TRDD-*.md")):
        rec = trdd_common.parse_trdd_record(f)
        records.append(rec)
        if rec.uid is not None:
            column_by_uid[rec.uid] = rec.column

    def column_of(uid: str) -> str:
        return column_by_uid.get(uid, "")

    # The git seams — loaded lazily so a project with no candidate TRDDs (the
    # common case) pays nothing. `git log` is read once; `git tag --contains`
    # is memoized per SHA.
    log_lines: list[tuple[str, str]] | None = None
    tag_cache: dict[str, list[str]] = {}

    def released_tags(sha: str) -> list[str]:
        if sha not in tag_cache:
            tag_cache[sha] = _released_tags_for(sha, root)
        return tag_cache[sha]

    def commit_in_released_tag(sha: str) -> bool:
        return bool(released_tags(sha))

    rows: list[dict] = []
    for rec in records:
        # Only a NON-terminal TRDD can be "shipped but open" or "stale-blocked".
        # A terminal TRDD is already closed; skip the git work entirely (cheap
        # short-circuit so the common all-closed board does no git calls).
        candidate_for_keystone = not trdd_common.is_terminal_column(rec.column)

        # Merge commit sources for the keystone: frontmatter
        # `implementation-commits:` + any SHA whose subject references this uid.
        # Done only for non-terminal TRDDs so we don't `git log` a closed board.
        if candidate_for_keystone and rec.uid is not None:
            if log_lines is None:
                log_lines = _load_git_log(root)
            subj_commits = _subject_commits_for_uid(rec.uid, log_lines)
            merged = list(dict.fromkeys([*rec.impl_commits, *subj_commits]))
            rec = trdd_common.TrddRecord(
                uid=rec.uid,
                column=rec.column,
                status=rec.status,
                blocked_by=rec.blocked_by,
                impl_commits=merged,
                body=rec.body,
            )

        verdict = trdd_common.reconcile(rec, commit_in_released_tag, column_of)
        if not verdict.fires:
            continue

        shipped_tags: set[str] = set()
        for sha in verdict.shipped_commits:
            shipped_tags.update(released_tags(sha))
        rows.append(
            {
                "uid": verdict.uid,
                "column": verdict.column,
                "label": verdict.label,
                "fired": verdict.fired,
                "shipped_commits": verdict.shipped_commits,
                "shipped_tags": shipped_tags,
                "prose_mismatch": verdict.prose_mismatch,
                "stale_blockers": verdict.stale_blockers,
            }
        )

    if not rows:
        state.rotate_log_if_big("trdd-state-reconciliation")
        return 0

    # Per-(TRDD, verdict) dedupe: a still-open candidate with the SAME verdict is
    # not re-nagged every heartbeat, but a verdict CHANGE (e.g. it gained a stale
    # blocker, or flipped from review→closeable) re-surfaces. We only emit when
    # at least one row is NEW, and the report is written only then.
    new_rows: list[dict] = []
    for r in rows:
        key = f"recon@{r['uid']}@{r['label']}@{','.join(sorted(r['fired']))}"
        if dedupe.emit_once(seen, key, "x") is not None:
            new_rows.append(r)

    if not new_rows:
        state.rotate_log_if_big("trdd-state-reconciliation")
        return 0

    main_root = _main_root(root)
    report_path = _write_report(main_root, rows)

    # Summarise the NEW candidates in ONE drift line. Group by verdict so the
    # line is scannable; the report carries the full per-TRDD detail. The uids
    # come from our own filenames (safe), but defang the report path which sits
    # under a user-controlled project dir.
    by_label: dict[str, list[str]] = {}
    for r in new_rows:
        by_label.setdefault(r["label"], []).append(f"TRDD-{r['uid']}")
    parts: list[str] = []
    for label in sorted(by_label):
        ids = by_label[label]
        shown = ", ".join(ids[:_MAX_LISTED])
        if len(ids) > _MAX_LISTED:
            shown += f", +{len(ids) - _MAX_LISTED} more"
        parts.append(f"{len(ids)} {label} ({shown})")
    summary = "; ".join(parts)
    report_hint = ""
    if report_path is not None:
        try:
            rel = report_path.relative_to(main_root)
            report_hint = f" See {state.sanitize_for_drift_line(str(rel))}."
        except ValueError:
            report_hint = ""

    print(
        f"[trdd-state-reconciliation] {len(new_rows)} board-drift candidate(s) — "
        f"{summary}. SURFACE-ONLY (no TRDD mutated); verify full STATE + git "
        f"before closing/unblocking.{report_hint}"
    )

    state.rotate_log_if_big("trdd-state-reconciliation")
    return 0


if __name__ == "__main__":
    sys.exit(main())
