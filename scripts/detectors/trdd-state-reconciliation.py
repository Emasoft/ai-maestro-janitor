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

import dataclasses
import io
import os
import re
import subprocess
import sys
import tarfile
from datetime import datetime
from pathlib import Path

# This detector is READ-ONLY over git. Every invocation through `state.run_subprocess`
# (which takes no env argument) needs this set process-wide, once, rather than per-call — a
# plain git takes `.git/index.lock` and can kill a concurrent writer (janitor#245); five
# sibling detectors already set this per-call, and this one set it nowhere. `_corpus_at_head`
# below calls `git archive` directly (its tar output is binary; `run_subprocess` forces
# `text=True`) and inherits this same process env, so the flag still covers it.
#
# Check 5 used to run ONE `git grep` subprocess per candidate TOKEN per card (~2985 unique
# tokens measured on this board — the actual CI 60s-cap killer, TRDD-TWF7DXXR: even a fast
# `git grep -q` costs ~30ms of pure process-startup overhead, and 2985 * 30ms alone is ~90s).
# A single `git grep -F -f <patternfile>` batching all tokens into ONE call was tried and
# rejected: measured 31s for just 500 patterns — git's multi-pattern fixed-string matcher
# scales with patterns * corpus size, not patterns * process-count, so it traded one
# bottleneck for a worse one. `_tokens_absent_at_head` instead loads the whole `scripts/`
# corpus ONCE (`_corpus_at_head`, one `git archive` call, ~0.1s) and resolves every token's
# presence with Python's `in` (measured 2985 tokens over a 12.8MB corpus: ~15.6s total) — only
# the (much smaller) genuinely-absent subset then pays the per-token `git log -G` history walk.
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


def _commit_at_head(sha: str, root: Path) -> bool:
    """True iff `sha` is reachable from HEAD (`git merge-base --is-ancestor <sha> HEAD`).

    The Check-8 seam (TRDD-4ZSYW21E): broader than `_released_tags_for` — every tagged commit
    is also at HEAD, but the reverse is not true between releases. Exit 0 = ancestor (reachable),
    1 = not an ancestor, anything else (bad sha, corrupt repo) is UNKNOWN and fails CLOSED (never
    flag on an inconclusive read — the opposite bias from `_commit_touches_impl`, because Check 8
    is already the weaker rung and a false "shipped" here would out-rank nothing worse to trust).
    """
    proc = state.run_subprocess(
        ["git", "-C", str(root), "merge-base", "--is-ancestor", sha, "HEAD"],
        timeout=8,
        detector_name="trdd-state-reconciliation",
    )
    if proc is None:
        return False
    return proc.returncode == 0


def _idle_days(path: Path) -> float | None:
    """Days since this card was LAST TOUCHED by any evidence we have, or None when unknown.

    Two independent signals, and the FRESHEST wins (TRDD-F4IBIDB6): the frontmatter `updated:`
    stamp, and the file's real mtime. Either alone produces the false positive that would get
    check 7 switched off wholesale — an agent mid-work edits the body without bumping `updated:`
    (mtime is fresh, stamp is old), while a mechanical repair pass bumps neither reliably. Taking
    the minimum means any recent evidence of activity keeps the card quiet, which is the correct
    bias: check 7 exists to catch cards nobody is touching AT ALL.

    None (both unreadable) is passed through as None and check 7 declines to fire — an unknown
    age is not evidence of a stall.
    """
    ages: list[float] = []
    try:
        head = path.read_text(encoding="utf-8", errors="replace")[:2048]
        m = re.search(r"^updated:[ \t]*(\S+)", head, re.MULTILINE)
        if m:
            stamped = datetime.strptime(m.group(1), "%Y-%m-%dT%H:%M:%S%z")
            ages.append((datetime.now(stamped.tzinfo) - stamped).total_seconds() / 86400.0)
    except (OSError, ValueError):
        pass
    try:
        ages.append((datetime.now().timestamp() - path.stat().st_mtime) / 86400.0)
    except OSError:
        pass
    if not ages:
        return None
    return max(0.0, min(ages))


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


def _corpus_at_head(root: Path, *, timeout_s: float = 15) -> str | None:
    """Concatenated text content of every tracked file under `scripts/` at HEAD, loaded in
    ONE `git archive` call — the seam `_tokens_absent_at_head` uses so the many token
    substring checks run as in-process string search instead of one `git grep` each.

    Bypasses `state.run_subprocess` on purpose: `git archive`'s tar stream is binary, and
    that helper forces `text=True` (fine for the plumbing every other call here reads, wrong
    for tar framing). This inherits the same `GIT_OPTIONAL_LOCKS=0` process env set at import
    time, so it is not weaker than the calls that go through the helper.

    Fails open (`None`) on any git/tar error — exactly like every other seam in this file, an
    error must never read as "the tree is empty" (which would make everything look absent).
    """
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "archive", "HEAD", "--", "scripts"],
            capture_output=True, timeout=timeout_s, check=False,
        )
    except (subprocess.TimeoutExpired, OSError):
        return None
    if proc.returncode != 0:
        return None
    try:
        with tarfile.open(fileobj=io.BytesIO(proc.stdout)) as tar:
            parts = [
                fh.read()
                for member in tar.getmembers()
                if member.isfile() and (fh := tar.extractfile(member)) is not None
            ]
    except tarfile.TarError:
        return None
    return b"\n".join(parts).decode("utf-8", errors="replace")


def _tokens_absent_at_head(tokens: set[str], root: Path) -> set[str] | None:
    """Which of `tokens` appear NOWHERE in `scripts/` at HEAD, as a plain substring —
    resolved for the WHOLE batch by loading the corpus ONCE instead of one `git grep`
    subprocess per token.

    Replaces the old per-token `_symbol_absent_at_head`: that call cost one `git`
    subprocess PER unique backtick token on the board (~2985 measured here — mostly pure
    process-startup overhead, ~30ms each), which was the actual CI 60s-cap killer
    (TRDD-TWF7DXXR). A single `git grep -F -f <patternfile>` batching all tokens into one
    call was tried and rejected: measured 31s for just 500 patterns, because git's
    multi-pattern fixed-string matcher scales with patterns * corpus size — it just moves
    the same cost into one slow call instead of many fast ones. Loading the corpus once and
    testing membership with Python's `in` (measured: 2985 tokens over a 12.8MB corpus in
    ~15.6s total, vs ~90s+ for either git-side approach) is the actual win.

    `git archive` reads the committed HEAD tree (not the working copy), so a dirty tree
    mid-refactor never produces a false "still there" — same guarantee `git grep HEAD` gave.
    Fails open (returns `None`) when the corpus can't be loaded at all, so the caller never
    flags a token off an inconclusive read (same fail-open contract as before; see the
    tri-state note on `_symbol_in_history` below).

    The corpus and the matching MUST mirror `_symbol_in_history` exactly (same `scripts`
    pathspec, same substring semantics — no word-boundary), because the two together form
    ONE predicate: "existed once, gone now" (measured 2026-08-12; the corrected pair fixes
    4 of 10 verdicts, 0 regressions — history in git blame).
    """
    if not tokens:
        return set()
    corpus = _corpus_at_head(root)
    if corpus is None:
        return None
    return {t for t in tokens if t not in corpus}


# A token was a SYMBOL here only if it was once DEFINED in `scripts/`: a `def`/`class` at any
# indent (so methods count), a plain assignment at COLUMN 0 (`name = value`), or an annotated
# assignment at COLUMN 0 with a value (`name: Type = value`).
#
# The asymmetry is deliberate and measured. An INDENTED assignment (`^\s*foo:`) is
# indistinguishable from a YAML/frontmatter line quoted inside a docstring — which is exactly
# what produced the reported `modified` false positive. `def`/`class` carry their own keyword,
# so they cannot collide with prose and are safe to accept at any indent. The cost is an
# indented dataclass FIELD (`last_rearm_ts: int = 0`), which this no longer sees: one stale
# citation occasionally, versus a false finding that costs trust in every other finding the
# detector makes. That trade runs the same direction as the fail-silent rule below.
#
# A bare `name:` (colon, no required `=`) was ALSO accepted here until janitor found `context`
# flagged as a symbol: a module docstring line, left-flush at column 0, read "context: with the
# default ``on_error=...``, anything that goes wrong scores the affected..." — ordinary English
# sentences routinely start `word: rest of sentence`, and that shape is indistinguishable from a
# bare annotation (`name: Type`) by indentation alone, the same collision the comment above
# already solved for the indented case. The fix: require the COLON form to look like a real
# annotated assignment (`name: <type-expression> = value`), never a bare annotation — the
# type-expression charset excludes anything prose would contain (spaces beyond single word
# separators are fine, but backticks, quotes-as-markdown, and multi-clause punctuation are not).
# Every real module-level annotated constant in this repo already carries a `= value` (checked:
# 656 hits for the tightened shape, 0 for the old bare-colon shape that weren't prose/CSS), so
# nothing legitimate is lost.
#
# Python `re`, not git's POSIX ERE (`-G`) — janitor#255's `\b`/`\s` bug class (git's ERE
# silently matches NOTHING on those escapes, so a per-token `-G` regex went permanently
# dead) cannot recur here: this now runs as ONE Python-side scan of the history text, so
# `\s` and `\b` behave exactly as documented.
_HISTORY_DEFINITION_RE = re.compile(
    r"^[ \t]*(?:def|class|async def)[ \t]+([A-Za-z_][A-Za-z0-9_]*)[^A-Za-z0-9_]"
    r"|^([A-Za-z_][A-Za-z0-9_]*)[ \t]*="
    r"|^([A-Za-z_][A-Za-z0-9_]*)[ \t]*:[ \t]*[A-Za-z_][A-Za-z0-9_.\[\], |]*[ \t]*="
)

# Memoized per project root: the expensive part (walking the FULL `scripts/` history once) runs
# on the first `_symbol_in_history` call only; every later call for the same root is an O(1) set
# lookup. This is what turned "one `git log -G<regex>` PER absent token" (measured ~1s each —
# 140 absent tokens on this board cost ~140s on their own, the CI 60s-cap killer that survived
# the presence-check batching above, TRDD-TWF7DXXR) into one shared ~1s history walk. Keyed by
# `root`, not process-global, so two different repos in the same test run never share state; a
# failed load is deliberately NOT cached (see `_symbol_in_history`), so a transient git error
# doesn't wrongly poison every later lookup for the rest of the run.
_ever_defined_cache: dict[Path, set[str]] = {}


def _load_ever_defined_symbols(root: Path, *, timeout_s: float) -> set[str] | None:
    """Every identifier ever DEFINED in `scripts/` history, in ONE pass over ONE `git log -p`.

    A symbol's DEFINING commit always ADDS the line that introduces it, so scanning only
    `+`-prefixed lines (never the `+++` file-header line) across the whole history is a
    faithful substitute for running `-G<def-regex>` once per token: a later removal-only
    commit contributes nothing a prior addition didn't already cover.

    janitor#255's lesson still applies to the MATCH shape, just no longer to the engine: this
    was `git log -S<token>` once (a raw substring search over diffs, matching prose, dict
    keys, docstrings — `queue` and `modified` both got flagged as "deleted symbols" for being
    ordinary words). `_HISTORY_DEFINITION_RE` asks the narrower question the check actually
    means — was this ever a `def`/`class`/module-level assignment — not "did this text ever
    change anywhere".

    Returns `None` (undetermined) on any git failure. The caller does not cache `None` —
    conflating "the read failed" with "never defined anywhere" would suppress every future
    finding for the rest of the run over one transient error.
    """
    proc = state.run_subprocess(
        ["git", "-C", str(root), "log", "-p", "--", "scripts"],
        timeout=timeout_s,
        detector_name="trdd-state-reconciliation",
    )
    if proc is None or proc.returncode != 0:
        return None
    names: set[str] = set()
    for line in proc.stdout.splitlines():
        if not line.startswith("+") or line.startswith("+++"):
            continue
        m = _HISTORY_DEFINITION_RE.match(line[1:])
        if m:
            names.add(m.group(1) or m.group(2) or m.group(3))
    return names


def _symbol_in_history(token: str, root: Path, *, timeout_s: float = 30) -> bool | None:
    """True/False iff `token` was once DEFINED as a module-level symbol in `scripts/` history,
    or **None when that could not be determined** (git missing, timeout, non-zero exit).

    Delegates to `_load_ever_defined_symbols`, memoized per `root` in `_ever_defined_cache` —
    see that cache's own docstring for why this is now O(1) after the first call instead of
    one `git log -G` subprocess per token.

    Still deliberately conservative in the SAME direction as before the tri-state existed: the
    caller treats `None` exactly as it treats a confirmed "no" — no finding. A missed dead
    symbol costs a stale citation; a false one costs the reader's trust in every other finding
    the detector makes. That trade is unchanged.

    `timeout_s` stays a parameter (2026-08-18): raising a hardcoded bound is a losing game
    under load (a publish was blocked twice, at both 8s and 30s, by the same real-history call
    contending with the test suite's own parallel workers). 30s is the PRODUCTION bound (the
    heartbeat must abstain rather than stall); real-history tests pass a hang-only bound
    instead, because their subject is the definition-matching REGEX, not this timeout policy.
    """
    ever_defined = _ever_defined_cache.get(root)
    if ever_defined is None:
        ever_defined = _load_ever_defined_symbols(root, timeout_s=timeout_s)
        if ever_defined is None:
            return None  # undetermined — NOT "no". See the docstring. Not cached — see above.
        _ever_defined_cache[root] = ever_defined
    return token in ever_defined


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
        if r.get("unnamed_blocker"):
            evidence_bits.append(
                "column: blocked but blocked-by is empty — the one licence to sit still "
                "must NAME what it waits on"
            )
        if r.get("shipped_unreleased"):
            unreleased = r.get("unreleased_commits") or []
            example = f" e.g. {unreleased[0][:12]}" if unreleased else ""
            evidence_bits.append(
                f"WEAKER evidence than a tagged release: {len(unreleased)} commit(s) reachable "
                f"from HEAD but in NO released tag yet{example} — verify before acting"
            )
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
    idle_by_uid: dict[str, float | None] = {}
    for scope, f in trdds:
        rec = trdd_common.parse_trdd_record(f)
        records.append(rec)
        if rec.uid is not None:
            column_by_uid[rec.uid] = rec.column
            scope_by_uid[rec.uid] = scope
            # Computed HERE because this is the only pass that holds the path; check 7 wants
            # the age, not the file (TRDD-F4IBIDB6).
            idle_by_uid[rec.uid] = _idle_days(f)

    def column_of(uid: str) -> str:
        return column_by_uid.get(uid, "")

    # ── Check 5 — STATE block cites a symbol the tree no longer has (TRDD-FDV1RQEB) ──
    # Independent of checks 1-4: reported straight through the findings ledger
    # (per-project mailbox + this session's drift line), NOT folded into the
    # candidate-board rows/report those checks share.
    dead_symbol_cache: dict[str, bool] = {}
    # Tokens whose history lookup could not be COMPLETED (git missing, timeout, non-zero exit).
    # Counted, not silently folded into "not dead": an undetermined answer suppresses a finding
    # exactly as before, but a check that could not run must not be indistinguishable from a
    # check that ran and found nothing. Without this, the only observable difference between a
    # clean board and a dead check is that both print nothing.
    undetermined: set[str] = set()

    # Collect every candidate token across the WHOLE board first, then resolve
    # "present at HEAD?" in ONE batched call (see `_tokens_absent_at_head`) — this
    # is what turns ~2985 per-token `git grep` subprocesses into 1. Only the
    # (usually far smaller) genuinely-absent subset still needs the per-token
    # `git log -G` history walk below.
    all_candidate_tokens: set[str] = set()
    for rec in records:
        if rec.uid is None:
            continue
        all_candidate_tokens |= trdd_common.candidate_dead_symbol_tokens(rec)
    absent_tokens = _tokens_absent_at_head(all_candidate_tokens, root)
    if absent_tokens is None:
        # The batch call itself failed — fail open exactly as the old per-token call
        # did on error (never flag off an inconclusive read), and count every
        # candidate as undetermined so a degraded run is visible in the log.
        undetermined |= all_candidate_tokens
        dead_symbol_cache.update(dict.fromkeys(all_candidate_tokens, False))
    else:
        dead_symbol_cache.update(
            dict.fromkeys(all_candidate_tokens - absent_tokens, False)
        )

    def token_is_dead(token: str) -> bool:
        # ponytail: the full-history walk (`_load_ever_defined_symbols`, O(scripts/ history) —
        # ~0.8s/21MB today) only runs on the FIRST call to `_symbol_in_history` for this root,
        # and that only happens when a token is absent at HEAD (every present token is already
        # cached False above, so it never reaches this branch). When `absent_tokens` is empty
        # or None-handled above, this function is never called with an uncached token and the
        # walk never runs at all. Ceiling: if history-walk cost ever needs to be zero even when
        # SOME tokens are absent, gate explicitly on `if absent_tokens:` before defining this.
        if token not in dead_symbol_cache:
            in_history = _symbol_in_history(token, root)
            if in_history is None:
                undetermined.add(token)
            # None -> False here: SAME suppression as before the tri-state existed. The
            # value is unchanged; what changed is that we now know it happened.
            dead_symbol_cache[token] = bool(in_history)
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

    # Say so when Check 5 ran DEGRADED. Silence here would be indistinguishable from a clean
    # board, which is the whole defect this counter exists for: every dead-symbol lookup could
    # have failed and the detector would have printed exactly what it prints when all is well.
    #
    # A LOG line, not a drift line / ledger finding: an undetermined lookup is a fact about
    # THIS RUN's environment (a contended machine, a missing git), not a defect in the board the
    # reader is being asked to fix — promoting it to a finding would train them to ignore
    # findings. The post-mortem question "was the check actually running that day?" now has an
    # answer on disk.
    if undetermined:
        state.log_line(
            "trdd-state-reconciliation",
            f"check5 DEGRADED: {len(undetermined)} symbol(s) undetermined "
            f"(git missing/timeout/non-zero exit), suppressed as not-dead: "
            f"{', '.join(sorted(undetermined)[:10])}",
        )

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

    # Check 8's seam (TRDD-4ZSYW21E), memoized per SHA like the tag lookup above — the same
    # commit can be shared across TRDD authoring citations and is cheap to reuse.
    head_cache: dict[str, bool] = {}

    def commit_at_head(sha: str) -> bool:
        if sha not in head_cache:
            head_cache[sha] = _commit_at_head(sha, root)
        return head_cache[sha]

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
            # `dataclasses.replace`, NEVER a field-by-field rebuild. The hand-written
            # constructor this replaces listed six fields and silently dropped the seventh
            # (`declares_blocker`), which then fell back to its dataclass default False — so
            # Check 6 read every blocked card reaching this branch as "names no blocker" and
            # reported 8 such findings on the live board, ALL 8 wrong. A partial copy of
            # a dataclass is a bug waiting on the next field to be added; `replace` carries
            # every field by construction, including ones that do not exist yet.
            rec = dataclasses.replace(rec, impl_commits=merged)

        verdict = trdd_common.reconcile(
            rec, commit_in_released_tag, column_of,
            idle_days=idle_by_uid.get(rec.uid or ""),
            commit_at_head=commit_at_head,
        )
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
                "unnamed_blocker": verdict.unnamed_blocker,
                "shipped_unreleased": verdict.shipped_unreleased,
                "unreleased_commits": verdict.unreleased_commits,
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
