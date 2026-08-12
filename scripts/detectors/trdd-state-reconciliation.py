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
import re
import sys
from datetime import datetime
from pathlib import Path

# This detector is READ-ONLY over git, and every one of its six git invocations goes through
# `state.run_subprocess`, which takes no env argument — so set the flag process-wide, once,
# rather than wrapping each call. A plain git takes `.git/index.lock` and can kill a
# concurrent writer (janitor#245); five sibling detectors already set this per-call, and this
# one set it nowhere. Check 5 made that materially worse: it runs TWO git calls per candidate
# TOKEN per card, where the pre-existing checks ran a handful per card.
os.environ["GIT_OPTIONAL_LOCKS"] = "0"

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import findings_ledger  # noqa: E402  # per-project mailbox for Check 5's dead-symbol findings
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


def _citation_re(uid: str) -> re.Pattern[str]:
    """Compile the CANONICAL-citation matcher for `uid` in a commit subject.

    Commit-discipline cites a TRDD as `TRDD-<id8>` (subject) or the casual
    `#<id8>`. A bare substring match (the previous `f"trdd-{uid}" in subj`) wrongly
    attributed a commit whose subject merely EMBEDS the id inside a code
    identifier or filename — `fix_TRDD-<id>_path`, `trdd-<id>.bak`, `noTRDD-<id>` —
    making a never-implemented TRDD read as shipped (issue #65 class b). The
    look-arounds require the citation to stand on its own: not glued left to an
    identifier char / `<alnum><connector>`, and the id must END cleanly (no longer
    base36 run = a different id, and no trailing `<connector><alnum>` filename/path
    join). Matched case-insensitively so the verbatim-cased id still resolves.
    """
    return re.compile(
        r"(?<![A-Za-z0-9_])"            # not glued left to an identifier char (incl _)
        r"(?<![A-Za-z0-9][-./])"       # not <alnum><connector> before the prefix (mid-identifier)
        r"(?:TRDD-|#)"                  # canonical citation prefix: `TRDD-<id8>` or `#<id8>`
        + re.escape(uid) +
        r"(?![0-9A-Za-z])"             # id ends here (a longer base36 run = a different id)
        r"(?![-_./][A-Za-z0-9])",      # not joined right by <connector><alnum> (filename/path)
        re.IGNORECASE,
    )


def _subject_commits_for_uid(uid: str, log_lines: list[tuple[str, str]]) -> list[str]:
    """SHAs whose commit SUBJECT carries a CANONICAL `TRDD-<uid>` / `#<uid>` citation.

    Commit-discipline puts `TRDD-<id8>` in commit subjects, so a TRDD's commits
    are greppable even when `implementation-commits:` is unpopulated. `log_lines`
    is the pre-fetched `[(sha, subject)]` board log so we grep it once, not once
    per TRDD. The match is the canonical citation SHAPE (see `_citation_re`), not a
    bare 8-char run, so an id embedded inside a code token / filename does not
    falsely attribute the commit (issue #65 class b).
    """
    pat = _citation_re(uid)
    return [sha for sha, subj in log_lines if pat.search(subj)]


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


def _commit_touches_impl(sha: str, root: Path, trdd_prefix: str) -> bool:
    """True iff `sha` changes at least one file OUTSIDE the TRDD board (`trdd_prefix`).

    A TRDD's OWN authoring commits (`docs: add TRDD-<id8> …`, `docs(trdd): …`)
    touch only the spec under the board dir — that is authoring, not
    implementation. Once a release tags such a commit, the bare subject-grep
    would otherwise make a never-implemented `backburner` design doc read as
    "shipped" (TRDD-7C787DUS: TRDD-cf15d412 was flagged closeable purely because
    its `docs: add` commit landed in a tag). A commit that also touches code/docs
    elsewhere IS implementation and is kept.

    `trdd_prefix` is the board's repo-relative dir (e.g. `design/tasks/`), resolved by
    the caller from the SAME `trdd_common` resolver the board scan uses — so the
    exclusion follows a project that relocated its TRDDs via TRDD_PATH.

    Fail OPEN on any git error (return True): the detector is surface-only, so a
    stray false-"shipped" candidate is caught by the human verifier, whereas
    DROPPING a real implementation commit would MISS genuine drift — the worse
    error for a board-drift detector.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(root), "diff-tree", "--no-commit-id", "--name-only", "-r", sha],
        timeout=8,
        detector_name="trdd-state-reconciliation",
    )
    if proc is None or proc.returncode != 0:
        return True
    files = [ln.strip() for ln in proc.stdout.splitlines() if ln.strip()]
    if not files:
        return True
    return any(not f.startswith(trdd_prefix) for f in files)


def _symbol_absent_at_head(token: str, root: Path) -> bool:
    """True iff `token` is NOT a whole-word match anywhere in `scripts/`+`tests/` at HEAD.

    `git grep -w` searches the committed HEAD tree (not the working copy), so a
    dirty tree mid-refactor never produces a false "still there". Exit code 0 =
    found (not absent), 1 = no match (absent); any other code (bad pathspec,
    corrupt repo) is UNKNOWN and fails open — never flag on an inconclusive read.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(root), "grep", "-q", "-w", "-e", token, "HEAD", "--", "scripts", "tests"],
        timeout=8,
        detector_name="trdd-state-reconciliation",
    )
    if proc is None or proc.returncode not in (0, 1):
        return False
    return proc.returncode == 1


def _symbol_in_history(token: str, root: Path) -> bool:
    """True iff `token` was ever introduced/touched in `scripts/` history (`git log -S`).

    This is the condition that holds the false-positive rate at zero (measured
    2026-08-12 prototype): a token that never existed anywhere is a typo or an
    external name, not a deleted symbol, and is silently skipped.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(root), "log", "--oneline", "-1", f"-S{token}", "--", "scripts"],
        timeout=8,
        detector_name="trdd-state-reconciliation",
    )
    if proc is None or proc.returncode != 0:
        return False
    return bool(proc.stdout.strip())


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
        "| TRDD | scope | column | verdict | checks fired | evidence |",
        "| --- | --- | --- | --- | --- | --- |",
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
            f"| TRDD-{uid} | {r.get('scope', trdd_common.PROJECT)} | {r['column'] or '?'} | "
            f"{r['label']} | {', '.join(r['fired'])} | {evidence} |"
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

    # BOTH design scopes — PROJECT and LOCAL. `trdd_common` owns the resolution and the
    # containment check that used to be copied here (see its module docstring).
    trdds = trdd_common.trdd_files("tasks", str(root))
    if not trdds:
        state.log_line("trdd-state-reconciliation", "no TRDDs in any design scope — skipping")
        return 0

    # The authoring-commit prefix for `_commit_touches_impl` — derived from the SAME
    # resolver the board uses, so a project that relocated its TRDDs via TRDD_PATH still
    # gets its authoring commits excluded. Hardcoding `design/tasks/` here (as this
    # detector used to) meant a relocated board's `docs: add TRDD-…` commits looked like
    # implementation, resurrecting the very false-"shipped" bug TRDD-7C787DUS fixed.
    # LOCAL TRDDs need no such exclusion: they live outside the repo and have NO authoring
    # commits at all, so only a real code commit can ever cite them.
    impl_prefix = "design/tasks/"
    project_tasks = trdd_common.project_tasks_dir(str(root))
    if project_tasks is not None:
        try:
            impl_prefix = f"{project_tasks.relative_to(root).as_posix()}/"
        except ValueError:
            pass

    # Pass 1 — parse every TRDD into a record + build the uid->column board so
    # Check 4 can resolve a blocker's CURRENT column without re-reading files. The board
    # spans BOTH scopes on purpose: a LOCAL TRDD can be blocked by a PROJECT one (and vice
    # versa), so a per-scope board would report a resolved blocker as still-blocking.
    records: list[trdd_common.TrddRecord] = []
    scope_by_uid: dict[str, str] = {}
    column_by_uid: dict[str, str] = {}
    for scope, f in trdds:
        rec = trdd_common.parse_trdd_record(f)
        records.append(rec)
        if rec.uid is not None:
            column_by_uid[rec.uid] = rec.column
            scope_by_uid[rec.uid] = scope

    def column_of(uid: str) -> str:
        return column_by_uid.get(uid, "")

    # ── Check 5 — STATE block cites a symbol the tree no longer has (TRDD-FDV1RQEB) ──
    # Independent of checks 1-4: reported straight through the findings ledger
    # (per-project mailbox + this session's drift line), NOT folded into the
    # candidate-board rows/report those checks share.
    dead_symbol_cache: dict[str, bool] = {}

    def token_is_dead(token: str) -> bool:
        if token not in dead_symbol_cache:
            dead_symbol_cache[token] = _symbol_absent_at_head(token, root) and _symbol_in_history(
                token, root
            )
        return dead_symbol_cache[token]

    for rec in records:
        if rec.uid is None:
            continue
        for finding in trdd_common.check5_dead_symbol_citations(rec, token_is_dead):
            key = f"deadsym@{rec.uid}@{finding.token}@{finding.severity}"
            if dedupe.emit_once(seen, key, "x") is None:
                continue
            where = "NEXT ACTION" if finding.severity == "high" else "STATE block"
            line = findings_ledger.record(
                sev="HIGH" if finding.severity == "high" else "LOW",
                code="TRDD-DEAD-SYMBOL",
                src="trdd-state-reconciliation",
                msg=(
                    f"TRDD-{rec.uid} {where} cites `{finding.token}` — absent from "
                    f"scripts/tests at HEAD, deleted per git history"
                ),
                ref=f"TRDD-{rec.uid}",
            )
            if line:
                print(line)

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
            # Exclude the TRDD's OWN authoring commits (which touch only its spec
            # under the board dir) so a never-implemented backburner design doc
            # does not read as "shipped" once a release tags it (TRDD-7C787DUS).
            subj_commits = [
                s
                for s in _subject_commits_for_uid(rec.uid, log_lines)
                if _commit_touches_impl(s, root, impl_prefix)
            ]
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
                "scope": scope_by_uid.get(verdict.uid or "", trdd_common.PROJECT),
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
        # Name the scope only when it is LOCAL — PROJECT is the default board and tagging
        # every id with it would be noise. TRDD ids are globally unique, so the dedupe key
        # (above) needs no scope qualifier.
        tag = " (local)" if r.get("scope") == trdd_common.LOCAL else ""
        by_label.setdefault(r["label"], []).append(f"TRDD-{r['uid']}{tag}")
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
