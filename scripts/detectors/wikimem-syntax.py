#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""wikimem-syntax — surface memory pages memgrep can no longer PARSE (TRDD-VPTQ4067).

The 3 memory-authoring skills disagreed on the lesson schema and the corpus drifted; `memgrep
lint` catches the ERROR-class breakages — an atom whose `⟦`-bracket makes it invisible to
recall, an atom with no `keywords:` (un-findable → "the memory does not exist"), props segments
the parser silently DISCARDS, a page with no `description:`, and corpus-wide DUPLICATE atom ids
(which make a `recall` on that id ambiguous). Until now that linter was wired into NOTHING; this
detector is the wiring — the heartbeat surfaces an ERROR the moment any page goes malformed, and
goes silent again the moment it is fixed.

The checks live in memgrep, not here (plan Phase 1b): the write gate and this heartbeat MUST
enforce the same rule set, and two implementations of one grammar drift apart — they already had.

Only ERROR is surfaced (a broken or invisible element). The hundreds of WARN/INFO advisories
(lean lessons, missing ocd/lmd, one-sided links) stay for the on-demand
`uv run scripts/wikimem_syntax_lint.py`, so the heartbeat line is never noise.

Scope: the SAME three memory roots recall reads — LOCAL (this project's), PROJECT (this repo's),
USER (the user's own global) — in ONE invocation, because atom-id uniqueness is corpus-wide and a
per-scope run cannot see a cross-scope collision. These are all the USER's own memory; no other
project's data is touched, so the per-project channeling invariant holds.

THIS DETECTOR WRITES, AND THAT IS REQUIRED — do not "fix" it. It shells out to `memgrep lint`,
which since TRDD-RY0IJBJI autofixes publish-globally/symlink state on every page it visits, so a
heartbeat fire (~5 minutes, every armed session on this machine) reconciles the corpus.

That reads like a separation-of-powers violation — the janitor SURFACES, an agent FIXES — and it
was treated as one on 2026-08-29 and switched to `lint --no-fix`, then reverted the same day on an
owner ruling that reframes it as DATA INTEGRITY: a memgrep edit executed on a malformed page
corrupts it and loses data, so keeping pages continuously well-formed is a PRECONDITION for the
librarians' writes, not housekeeping. The frequent cadence is the point — it is what shrinks the
window in which an editor can meet a malformed page.

What was actually wrong was the NOISE, not the write. TRDD-VJL1YTCG Part C says maintenance must
be carried "in background invisibly … not by the main agent" — a statement about who SEES it, not
about whether it happens. Fixed where it belongs, in the heartbeat's quiet filter
(`_OTHER_ACTOR_DETECTORS` in dispatch.py): this detector's lint summary no longer rides the
urgency override into the main conversation, while the reconciliation continues underneath.

Two lessons, both paid for:
  1. A verb this file merely CALLS grew a side effect, and no test or type here could notice. When
     a dependency's contract changes from report to write, every caller's read-only claim silently
     becomes false.
  2. "Invisible" and "absent" are not the same requirement, and reading the first as the second
     turned a noise complaint into a proposal to remove a safety property. When a directive says a
     chore must not DISTRACT someone, ask whether it is asking you to stop DOING it or to stop
     TELLING them — the cheap fix is almost always the second.

What it still does NOT do itself: it never edits a page in its OWN code (RULE 0) — an agent fixes
findings via /janitor-memory-update, EXCEPT `link-downward-cross-scope`: no editor chore re-homes
a page across scopes, so that rule's remedy is a scope decision the agent makes itself
(janitor#138).
Fail-open: any error → silent exit 0, never breaks the heartbeat.
Per-set content-hash dedupe: re-emits only when the set of ERRORs CHANGES (bounded — fix the
corpus and it converges to silence).
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

_SCRIPTS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SCRIPTS / "lib"))
sys.path.insert(0, str(_SCRIPTS))  # for the top-level linter module

import dedupe  # noqa: E402
import global_state  # noqa: E402
import issue_catalog  # noqa: E402
import memory_scopes  # noqa: E402
import state  # noqa: E402
import tickets  # noqa: E402
import wikimem_syntax_lint as lint  # noqa: E402

# The one rule (janitor#138) whose remedy the blanket "/janitor-memory-update" line
# CANNOT satisfy: a page linking DOWN across scopes (LOCAL from PROJECT/USER, or
# PROJECT from USER) has no editor chore that can fix it — no chore re-homes a page
# across scopes (janitor-memory-repair §8: "cross-scope re-homing is SURFACED, not
# done"; janitor-memory-consolidate: "promotion is a deliberate human act"). The scope
# decision is the agent's own: promote the target deliberately, or remove the downward
# reference. Every other code keeps pointing at /janitor-memory-update.
_CROSS_SCOPE_CODE = "link-downward-cross-scope"


def _error_findings() -> list[lint.Finding]:
    """Every ERROR finding across the 3 memory scopes. FIXING, deliberately — do NOT pass
    `read_only=True` here.

    OWNER RULING 2026-08-29, and it is a DATA-INTEGRITY rule, not a tidiness preference:
    "executing a memgrep command/edit on a malformed wikimem page containing errors will corrupt
    the file and lose data. This is why fixing both BEFORE and AFTER executing the wikimem page
    edit is MANDATORY, NO EXCEPTIONS. --no-fix can only be used for debug or diagnostic use
    cases."

    So the autofix on this ~5-minute cadence is not a side effect to be cleaned up — it is what
    keeps the corpus continuously in a state where the next editor write cannot corrupt a page.
    Removing it does not make the janitor tidier, it opens a corruption window between librarian
    runs.

    This was briefly changed to `read_only=True` (2026-08-29) on a misreading of TRDD-VJL1YTCG
    Part C, and reverted the same day. Part C requires maintenance to be INVISIBLE to the main
    agent, not ABSENT — "carried in background invisibly by the wikimem librarians agents" is a
    statement about WHO SEES it, not about whether it happens. The visibility half is solved
    where it belongs, in the heartbeat's quiet filter (`_OTHER_ACTOR_DETECTORS` in dispatch.py):
    the fixing continues, and the main agent simply is not told about it. Both halves of the
    owner's intent hold at once; suppressing the write satisfied neither.

    A1 (TRDD-XI10BA5D step B): the mode is a recorded OWNER DEFAULT (card, "Owner questions
    asked 2026-09-23", item 3 — unanswered, recommended default adopted), never ratified, and
    the four-letters verdicts did not cover lint mode. Preserved here unchanged; the landing
    record pins it with that status.
    """
    _code, _stdout, findings = lint.run_lint()
    return [f for f in findings if f.sev == "ERROR"]


def _signatures(findings: list[lint.Finding]) -> list[str]:
    """Findings as short stable signatures, sorted.

    A signature is `<basename>:<line>:<check-code>` — the check's stable IDENTITY, so the dedupe
    hash changes when the defect SET changes and not when someone improves a message's wording.
    (It used to hash the message, which made every reworded message look like a new defect.)
    Neither the message nor the path is carried: a duplicate-id report names every colliding
    absolute location, and a drift signature must never be a channel for one.

    A binary predating codes yields an empty `code`; fall back to a message hash there, so an old
    memgrep degrades to the previous behaviour instead of collapsing every finding on a line into
    one signature.
    """
    sigs = {
        f"{Path(f.path).name}:{f.line}:"
        + (
            f.code
            or hashlib.sha1(f.msg.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
        )
        for f in findings
    }
    return sorted(sigs)


def _error_signatures() -> list[str]:
    """Every ERROR finding's signature, sorted — `_signatures(_error_findings())`.

    A standalone zero-arg entry point (distinct from `main`'s own call sequence,
    which needs the findings themselves too — for the per-rule remedy — and must
    not run `lint.run_lint()` a second time to get them).
    """
    return _signatures(_error_findings())


def _remedy_for(codes: set[str]) -> str:
    """The remedy clause for the drift line, PER-RULE rather than blanket (janitor#138).

    A `link-downward-cross-scope` ERROR cannot be fixed via `/janitor-memory-update` —
    that instrument delegates COMPLEX re-editing to the six editor chores
    (split/consolidate/conflict/repair/atomize/harvest), and NONE of them re-homes a
    page across scopes. Naming the blanket remedy for this rule reads as "a chore owns
    this, wait for it" when no chore does, so it must say the scope decision is the
    agent's own instead. Every other code keeps the generic remedy.
    """
    cross_scope_clause = (
        f"for `{_CROSS_SCOPE_CODE}`: the scope decision is yours — no editor chore "
        "re-homes a page across scopes (see janitor-memory-repair §8); either promote "
        "the target deliberately or remove the downward reference"
    )
    generic_clause = "fix via /janitor-memory-update (never hand-edit the .md)"
    has_cross_scope = _CROSS_SCOPE_CODE in codes
    has_other = bool(codes - {_CROSS_SCOPE_CODE})
    if has_cross_scope and has_other:
        return f"{cross_scope_clause}; everything else: {generic_clause}."
    if has_cross_scope:
        return f"{cross_scope_clause}."
    return f"{generic_clause}."


def _verb_for(code: str) -> str:
    """The maintenance chore that owns a lint rule's remedy, named IN the ticket (TRDD-FVYV6RSG).

    A ticket that only says "the corpus needs repair" sends the curator to guess the pass;
    naming the chore up front is what makes the dispatch a decision instead of a question.
    Unknown codes get the generic update remedy rather than a guess.
    """
    if code in ("atom-oversized", "atom-oversized-critical"):
        return "/janitor-memory-atomize (decompose the oversized atom)"
    if code == "link-one-sided":
        return "/janitor-memory-update (wire the reciprocal link)"
    if code == _CROSS_SCOPE_CODE:
        return "no chore — the scope decision is the agent's own (janitor#138)"
    return "/janitor-memory-update"


# Pages under another project's corpus (its notes published into USER scope) are NOT the
# janitor's to repair — the owner held them out (TRDD-FVYV6RSG). A ticket filed on one would
# dispatch an agent that edits another project's memory.
_HELD_PAGE_MARKERS = ("agentlenspro", "ghbook")


def _held(path: str) -> bool:
    low = path.lower()
    return any(m in low for m in _HELD_PAGE_MARKERS)


# ── scope resolution (step B): which of the three roots a finding's page lives in ────────────

def _scope_of(path: str, roots: list[tuple[str, Path]]) -> tuple[str, str]:
    """`(scope, relpath)` for a finding's page path, resolved against `roots` — the same three
    roots `lint.run_lint()`'s `default_roots()` lints (memory_scopes.resolve_scope_dirs()).

    The relpath is the page's path relative to its OWN scope root — the dedupe key's page
    component. A basename would collide for same-named pages in different dirs (the
    adversarial-review reason step B re-keys); the relpath keeps the key stable under line
    edits (no line number in it) while being unique across the whole corpus.

    A page under none of the three roots (should not happen — run_lint only walks those roots,
    but a fixture or a racing root swap can produce one) maps to `("", path)` with the FULL path
    as its relpath: the finding still tickets, keyed by a path that cannot collide.
    """
    p = Path(path)
    try:
        rp = p.resolve()
    except OSError:
        rp = p
    for label, root in roots:
        try:
            rel = rp.relative_to(root.resolve())
        except (ValueError, OSError):
            continue
        return label, rel.as_posix()
    return "", path


# ── the USER-scope machine-wide claim (step B): cross-project dedupe for a shared corpus ──────
#
# The ticket STORE is per-project (`<project>/.janitor/state/tickets`), but USER-scope pages are
# ONE corpus shared by every project on this machine. Without a machine-wide claim, two armed
# projects linting the same USER page each open their own ticket — N projects, N agents editing
# the same page. The claim file lives under `global_state.global_state_dir()` (the daemon's
# singleton dir) and is flock-protected read-modify-write, the same discipline as
# `gs.ticket_dispatch_lock()`.
#
# Claim semantics (A9): the claim key EQUALS the dedupe key triple (scope:page:code:anchor). A
# claim is `{"project": <project root>, "ts": <epoch>}`; TTL 7 days, swept at every fire; claims
# FAIL OPEN — an unreadable/vanished file just means nobody holds the key, so a worst case is
# one cross-project duplicate, never a lost finding.

_CLAIM_FILE = "memgrep-ticket-claims.json"
_CLAIM_TTL_S = 7 * 24 * 3600
_CLAIM_LOCK = "memgrep-ticket-claims.lock"


def _claim_project() -> str:
    """The identity a claim records: this project's root.

    Read from the env DIRECTLY, not `state.project_root()` (which is `lru_cache`d): the claim
    identity must follow the CURRENT session's project, and a cache filled by an earlier
    resolution in this process (the heartbeat imports many detectors) would mis-attribute the
    claim. `CLAUDE_PROJECT_DIR` is the same first-priority source `state` resolves.
    """
    return os.environ.get("CLAUDE_PROJECT_DIR") or str(Path.cwd())


def _claim_path() -> Path:
    return global_state.global_state_dir() / _CLAIM_FILE


def _claim_lock_path() -> Path:
    return global_state.global_state_dir() / _CLAIM_LOCK


def _sweep_claims(claims: dict[str, dict], now: int) -> dict[str, dict]:
    """Drop claims past their TTL. Pure given `now` — the caller owns the file IO."""
    return {k: v for k, v in claims.items() if now - int(v.get("ts", 0)) < _CLAIM_TTL_S}


def claim_user_key(key: str, *, now: int | None = None) -> bool:
    """Atomically claim a USER-scope dedupe key machine-wide. True iff THIS project holds it.

    Flock-protected read-modify-write (single producer per key, first project wins). Any
    failure — unreadable global state dir, an OSError mid-write — fails OPEN with True: a
    claim is an optimization over per-project stores, and refusing to ticket a real finding
    because bookkeeping broke would trade a possible duplicate for a certain silence.
    """
    ts = int(time.time()) if now is None else int(now)
    try:
        global_state.init_global_state()
        fd = os.open(str(_claim_lock_path()), os.O_RDWR | os.O_CREAT, 0o644)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX)  # blocking: ticketing is not cadence-critical
            p = _claim_path()
            claims: dict[str, dict] = {}
            if p.is_file():
                try:
                    claims = json.loads(p.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    claims = {}  # fail open: a corrupt file holds no keys
            claims = _sweep_claims(claims, ts)
            holder = claims.get(key)
            if holder is not None and holder.get("project") != _claim_project():
                return False  # another live project owns this finding
            claims[key] = {"project": _claim_project(), "ts": ts}
            tmp = p.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(claims, indent=1), encoding="utf-8")
            os.replace(tmp, p)
            return True
        finally:
            try:
                fcntl.flock(fd, fcntl.LOCK_UN)
            finally:
                os.close(fd)
    except OSError:
        return True  # fail open — see the doc comment


def _memcorp_002_comment() -> str:
    """The owner's verbatim rule (A8) — why a WARN-tier finding tickets at all."""
    return (
        "Owner ruling 2026-09-23 (size-ticket rule, verbatim): \"warn but also open a ticket "
        "with the janitor to lazily refactor the atom into 2 atoms.\" Ticketing this WARN needs "
        "no further ratification (TRDD-XI10BA5D A8)."
    )


def _issue_for(f: lint.Finding) -> str | None:
    """The MEMCORP code a finding tickets under, or None. MEMCORP-002 collects EXACTLY
    `atom-oversized-critical` (A3); every other ERROR-tier finding goes to 001."""
    if f.sev == "ERROR":
        return "MEMCORP-001"
    if f.sev == "WARN" and f.code == "atom-oversized-critical":
        return "MEMCORP-002"
    return None


def _ticket_key(issue: str, scope: str, relpath: str, f: lint.Finding) -> str:
    return f"{issue}:{scope}:{relpath}:{f.code}:{f.anchor}"


def _live_keys(findings: list[lint.Finding], roots: list[tuple[str, Path]]) -> set[str]:
    """Dedupe keys of every finding that WOULD ticket right now, regardless of the USER-scope
    claim (a finding another project holds is still live)."""
    keys: set[str] = set()
    for f in findings:
        issue = _issue_for(f)
        if not f.code or _held(f.path) or issue is None:
            continue
        scope, relpath = _scope_of(f.path, roots)
        keys.add(_ticket_key(issue, scope, relpath, f))
    return keys


def _close_stale_tickets(*, live_keys: set[str], now: int) -> int:
    """Close OPEN memory-corpus tickets this detector filed whose finding no longer reproduces.

    janitor#324: an open ticket was never re-validated, so a page fixed after the ticket was
    filed kept its ticket (and, before memory-corpus stopped being dispatched, was sent to an
    agent for a condition that was already gone). `invalid` is the terminal state for "proven
    not a defect"; it is not `resolved`, which would claim a fix this code did not make.
    """
    closed = 0
    for t in tickets.load_all():
        if (
            t.kind != "memory-corpus"
            or t.origin != "wikimem-syntax"
            or t.status != tickets.OPEN
            or t.dedupe_key in live_keys
        ):
            continue
        tickets.save(tickets.mark_invalid(t, now=now, why="finding no longer reproduces in the lint pass"))
        closed += 1
    return closed


def _file_tickets(
    findings: list[lint.Finding], *, roots: list[tuple[str, Path]] | None = None
) -> int:
    """Open tickets for held-out lint findings, and return how many were newly filed.

    `roots` overrides the scope resolution (tests inject their fixture roots); default is the
    same three roots the lint pass walked (`memory_scopes.resolve_scope_dirs()`).

    TWO ticket paths, split by severity (step B):

    - MEMCORP-001 — every ERROR finding (the grandfathered classes that land without refusing a
      write; NOTE-2 made executable). Replaces the per-path no-op path.
    - MEMCORP-002 — EXACTLY `atom-oversized-critical` WARN findings (the >2x-size atoms). No
      other WARN tickets, ever (A3): the ERROR-only filter stays for 001 and 002's collector
      accepts one code and no more.

    The dedupe key is `MEMCORP-00X:<scope>:<relpath>:<code>:<anchor>` — scope-stamped, page
    relative to its scope root, and NEVER the line number (adversarial review 2026-09-25: the
    line shifts on every edit above the finding, and a line-sensitive key would file a fresh
    durable ticket for the SAME defect after each such edit). The ledger still shows the newest
    line via `where`.

    Both paths apply the held-page exclusion (`_held`) and, for USER-scope pages, the
    machine-wide claim (USER pages are one corpus across every project; LOCAL/PROJECT pages are
    project-relative — the per-project store IS their right place, no claim).
    """
    if roots is None:
        roots = memory_scopes.resolve_scope_dirs()
    filed = 0
    for f in findings:
        if not f.code or _held(f.path):
            continue
        scope, relpath = _scope_of(f.path, roots)
        issue = _issue_for(f)
        if issue is None:
            continue  # INFO never tickets (spec req 3); other WARNs never ticket (A3)
        key = _ticket_key(issue, scope, relpath, f)
        if scope == "USER" and not claim_user_key(key):
            continue  # another project already holds this finding machine-wide
        where = f"{scope}:{relpath}:{f.line}" if scope else f"{f.path}:{f.line}"
        data: dict[str, object] = {
            "detail": f"{f.code} — remedy: {_verb_for(f.code)}",
            "found": (
                f"rule {f.code} anchor ⟦{f.anchor}⟧ at {f.path}:{f.line}"
                if f.anchor
                else f"rule {f.code} at {f.path}:{f.line}"
            ),
        }
        if issue == "MEMCORP-002":
            data["advisory"] = _memcorp_002_comment()
        # `Any` per value, not `object`: raise_issue's named params (evidence, severity, ...)
        # are typed, and pyright fails a `dict[str, object]` **-unpack into them (the publish
        # gate runs pyright fail-closed, TRDD-MYQGMAQZ). The values are all our own strings.
        typed_data: dict[str, Any] = data
        raised = issue_catalog.raise_issue(
            issue,
            where=where,
            dedupe_key=key,
            # The `{scope}` title slot takes the SSOT label verbatim (UPPERCASE, exactly what
            # resolve_scope_dirs emits and memgrep-index-health passes); "unknown" for a page
            # under no root, matching that sibling's convention.
            scope=scope or "unknown",
            origin="wikimem-syntax",
            **typed_data,
        )
        if raised.ok:
            filed += 1
    return filed


def main() -> int:
    try:
        state.init_state()
        # ONE lint pass (A1: fixing mode, unchanged — `_error_findings`' owner ruling stands),
        # feeding BOTH consumers: the drift line (ERROR-only, unchanged shape) and the step-B
        # ticket paths (ERROR→001, atom-oversized-critical→002), so tickets always file from the
        # findings of the FINAL pass over the POST-fix bytes — an auto-fix between passes can
        # never produce a phantom ticket.
        _code, _stdout, findings = lint.run_lint()
        errors = [f for f in findings if f.sev == "ERROR"]
        # Tickets file FIRST and regardless of the drift line: a corpus whose only finding is a
        # 2x-size WARN has no ERROR to report but still owes its MEMCORP-002 ticket, so the
        # early-return that used to precede ticketing cannot gate the ticket path on ERRORs.
        _file_tickets(findings)
        _close_stale_tickets(
            live_keys=_live_keys(findings, memory_scopes.resolve_scope_dirs()), now=int(time.time())
        )
        if not errors:
            return 0
        sigs = _signatures(errors)
        example = state.sanitize_for_drift_line(sigs[0])
        n = len(sigs)
        codes = {f.code for f in errors if f.code}
        remedy = _remedy_for(codes)
        msg = (
            f"[wikimem-syntax] {n} memory element(s) memgrep CANNOT parse (ERROR — "
            f"recall-invisible or ambiguous). e.g. {example}. Run "
            f"`uv run scripts/wikimem_syntax_lint.py` for the full list; {remedy}"
        )
        # Per-SET dedupe: the key is a hash of the whole ERROR set, so the line re-emits
        # ONLY when the set changes (a new break, or one fixed) — never on an unchanged corpus.
        key = "critset-" + hashlib.sha1("\n".join(sigs).encode("utf-8"), usedforsecurity=False).hexdigest()[:16]
        seen = state.state_dir() / "wikimem-syntax-seen.txt"
        line = dedupe.emit_once(seen, key, msg)
        if line is not None:
            print(line)
    # NO `except lint.MemgrepTooOld` here, deliberately. It was added alongside the `--no-fix`
    # switch and left behind when that switch was reverted the same day — `run_lint` raises it
    # ONLY under `read_only=True`, and `_error_findings` calls with the default False, so the
    # handler was unreachable and its "wikimem lint is NOT RUNNING" alarm could never fire.
    # Removed rather than made reachable: dead code that documents a guarantee it does not
    # provide is worse than no code, because the next reader budgets for the alarm. Re-add it
    # only together with a caller that actually passes `read_only=True`.
    except Exception:  # noqa: BLE001 -- a validator must never break the heartbeat
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
