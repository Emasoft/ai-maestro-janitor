"""The ISSUE-CODE CATALOG — every incident the janitor can detect, with a stable id (TRDD-CGYMUKO6).

One registry, one entry point:

    raise_issue("WFSEC-001", where="ci.yml:42", evidence=[".github/workflows/ci.yml"], expr="github.event.issue.title")

`raise_issue` is the ONLY call a detector needs to turn a finding into work. It looks the code up,
resolves `kind` → (domain, agent) through `tickets.KIND_REGISTRY`, renders OUR template with the
detector's SANITIZED data, and routes by domain:

    HARNESS  → tickets.open_ticket()      — the janitor's own machinery; it fixes itself, unattended.
    PROJECT  → ticket_proposal.propose()  — the user's repo; it may only propose + recommend.

**THE CODE DECIDES THE DOMAIN.** A detector cannot pass a `kind`, a `domain`, or an `agent`, so no
producer can accidentally (or maliciously) grant itself unattended dispatch into the user's code. That
is the whole reason this indirection exists rather than each detector calling `open_ticket` directly.

**THE TEMPLATE IS OURS; ONLY THE DATA IS THEIRS.** Every value a detector interpolates is
attacker-influenceable (a filename, a dependency name, a workflow line, a GitHub issue title), so it is
run through `tickets._clean` — which defangs `[`/`]` so a payload cannot mimic a `[janitor-…]` marker
in heartbeat stdout, where the model reads lines AS INSTRUCTIONS. The surrounding prose — the title,
the explanation, the fix the agent is told to attempt — is authored here, in our source.

**A CODE IS IMMUTABLE ONCE SHIPPED**, like a schema version: `<SCANNER>-<NNN>`, never renumbered,
never reused. A citation in a closed ticket, a report, or a TRDD must still resolve years later.
`docs/ISSUE-CODES.md` is GENERATED from this file (`scripts/issue_catalog_doc.py --write`) and a test
fails when the two drift — a stale list of what the janitor can see is worse than no list, because it
is a document that lies.
"""

from __future__ import annotations

import re
import string
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import findings_ledger  # noqa: E402
import issue_codes_gen  # noqa: E402
import state  # noqa: E402
import ticket_proposal  # noqa: E402
import tickets  # noqa: E402

CODE_RE = re.compile(r"^[A-Z][A-Z0-9]{1,9}-\d{3}$")

# How many proposals ONE detector may author in ONE fire. A proposal is a file in the user's
# git-tracked design board, so a scanner that trips over a vendored tree full of matches must not be
# able to commit a hundred of them. The ones over the cap are not lost — the finding is still printed,
# and the next fire proposes them (dedupe means the earlier ones do not repeat). Any detector that
# caps MUST log what it dropped: a silent truncation reads as "that was everything".
MAX_RAISES_PER_FIRE = 5


@dataclass(frozen=True)
class Issue:
    """One detectable issue. `kind` is the ONLY thing that decides domain + agent (via KIND_REGISTRY)."""

    scanner: str  # the detector/validator that emits it — the grep handle
    kind: str  # must exist in tickets.KIND_REGISTRY
    severity: str  # default; a producer may override only with another known severity
    title: str  # ONE line, `{placeholder}`s filled from the detector's sanitized data
    what: str  # what the condition IS (the user-facing description in the TRDD and the docs)
    why: str  # why it matters — why this is worth an agent's time
    fix: str  # what the dispatched agent is told to ATTEMPT (never "what it will do")


# --------------------------------------------------------------------------- #
# THE CATALOG. Append only: a shipped code is immutable.
# --------------------------------------------------------------------------- #

# Built from the generated module (design/specs/issue-codes.toml is the source). Catalog rows are those
# carrying a `kind`; the TOML uppercases severity, the catalog spells it lowercase.
ISSUE_CATALOG: dict[str, Issue] = {
    c.code: Issue(scanner=c.emitter.split(":", 1)[1], kind=c.kind, severity=c.severity.lower(), title=c.summary, what=c.what, why=c.why, fix=c.fix_text) for c in issue_codes_gen.ISSUE_CODES if c.kind
}


# --------------------------------------------------------------------------- #
# retired codes — a code that stops being raised must take its proposals with it
# --------------------------------------------------------------------------- #

# Every code this catalog USED to raise and no longer does, mapped to why.
#
# A PROJECT-domain finding becomes a proposal TRDD that only a human can approve, and the only thing
# that can withdraw one is `reconcile(code, live)` — called BY the detector that raises that code.
# So the moment a detector stops raising a code, its in-flight proposals become unreachable: nothing
# raises them, nothing withdraws them, and they sit on the board forever awaiting approval for a
# finding whose producer no longer exists. The janitor then nags about work nobody can clear.
#
# That is not hypothetical — it is how this entry got here. Splitting AICTX-001 into AICTX-002
# (d89eca8) moved the raise and the reconcile together, correctly, and silently stranded every
# AICTX-001 proposal already on a host's board. Reported from the field as two "hallucinated"
# proposals that could not be made to go away.
#
# Retiring a code therefore has two obligations, and this map is how the second one is discharged:
#   1. stop raising it (delete the catalog entry — an unraisable entry is dead code and, worse,
#      `issue_domain`/ISSUE-CODES.md advertise it as a live code that never fires), and
#   2. list it HERE, so `reconcile_retired` withdraws its orphans on every host that has any.
# `test_issue_catalog.py` enforces both directions: no live code may be listed here, and no catalog
# code may be unraised without being listed here.
RETIRED_CODES: dict[str, str] = dict(issue_codes_gen.RETIRED)


def reconcile_retired(*, project_dir: str | None = None) -> list[tuple[str, str]]:
    """Withdraw every pending proposal raised under a RETIRED code. Returns `(code, trdd_id)` pairs.

    Deliberately keyed on the proposal's own key prefix and NOT on `ISSUE_CATALOG`, because a retired
    code is normally DELETED from the catalog — `reconcile()` returns early for an unknown code, so
    it cannot clean up after a retirement even if someone remembers to call it.

    Cheap and safe to call on every fire: one pass over the pending proposals, and a no-op on the
    overwhelmingly common case where none of them names a retired code.
    """
    if not RETIRED_CODES:
        return []
    withdrawn: list[tuple[str, str]] = []
    for p in ticket_proposal.pending(project_dir):
        code = p.key.split(":", 1)[0]
        if code not in RETIRED_CODES:
            continue
        uid = ticket_proposal.retract(p.key, project_dir=project_dir)
        if uid:
            withdrawn.append((code, uid))
    return withdrawn


# --------------------------------------------------------------------------- #
# raising an issue — the ONE entry point a detector needs
# --------------------------------------------------------------------------- #


class _SafeDict(dict):
    """Missing placeholder → a visible marker, never a KeyError.

    A detector that forgets one `{key}` must not crash the heartbeat: the finding is worth more than
    the formatting. The marker NAMES the absent key (`<?table?>`) rather than being a bare `<?>`:
    both are loud enough to catch in review, but only the named one tells the reader WHICH field the
    detector forgot — and the alternative is reading the catalog template to work it out. It stays
    harmless inside a ticket either way.
    """

    def __missing__(self, key: str) -> str:  # pragma: no cover - exercised via _render
        return f"<?{key}?>"


def _render(template: str, data: dict[str, str]) -> str:
    """Fill OUR template with the detector's ALREADY-SANITIZED data. Never formats the data itself.

    A value supplied as the EMPTY STRING is treated exactly like a missing one, so it renders as the
    self-naming `<?key?>` marker. That equivalence is the safeguard: an empty field used to render as
    nothing at all, which turned a critical ticket's title into `a migration left `…` without column
    `` ` — technically filled, visibly nonsense, and impossible to attribute to a producer. A
    detector that does not KNOW a field must leave it out or say so; it must not be able to quietly
    erase part of our sentence.
    """
    return string.Formatter().vformat(
        template, (), _SafeDict({k: v for k, v in data.items() if v != ""})
    )


# A template field is an IDENTIFIER slot — a table, a column, a scope, a package. Not a sentence.
# Measured 2026-07-28 (T-FATU6QPI): a detector passed an entire 120-char validator message as
# `table=` and an empty `column=`, producing a CRITICAL ticket whose title was unreadable. Capping
# short and marking the overflow makes that a LOUD producer bug instead of a quiet garbled string.
# `where`, `detail` and `evidence` are deliberately exempt — those ARE prose slots.
_FIELD_CAP = 200
_IDENTIFIER_FIELD_CAP = 64
_PROSE_FIELDS = frozenset({"where", "found", "detail", "advisory", "reason", "window"})


def _fields(where: str, data: dict[str, object]) -> dict[str, str]:
    """Sanitize every value a detector interpolates. The ONE place untrusted text is defanged."""
    fields: dict[str, str] = {}
    for k, v in data.items():
        cleaned = tickets._clean(str(v), _FIELD_CAP)
        if k not in _PROSE_FIELDS and len(cleaned) > _IDENTIFIER_FIELD_CAP:
            # Loud, attributable, and still bounded — the reader sees WHICH field the producer
            # over-filled instead of reading a sentence wedged into a noun slot.
            cleaned = f"<?{k}:overlong?>"
        fields[k] = cleaned
    fields["where"] = tickets._clean(where, _FIELD_CAP)
    return fields


def _finding_key(code: str, issue: Issue, fields: dict[str, str], dedupe_key: str) -> str:
    """The identity of ONE finding: per code + LOCATION.

    The same defect found on every fire is ONE ticket; the same defect in two different files is
    genuinely two. `raise_issue` and `clear_issue` MUST derive this identically — a clear that
    computed the key even slightly differently would silently never match, and the retract would look
    like it worked while the proposal stayed on the board forever.
    """
    return dedupe_key or f"{code}:{fields['where'] or _render(issue.title, fields)}"


def dedupe_key_for(code: str, where: str) -> str:
    """The exact dedupe key `raise_issue(code, where=where)` (no other data) will persist.

    Mirrors `_finding_key`'s composition plus `ticket_proposal.propose`'s own `_dedupe_key`
    canonicalization (`_yaml_plain` + `_clean`) — the SAME two-stage pipeline `raise_issue` walks
    a `where` value through before it lands in `ticket-dedupe-key:`. A caller that needs to
    PREDICT a key before actually raising (e.g. `migrate_legacy_where`'s re-keying, which must
    compare its guess against already-persisted keys) has to walk the identical pipeline or the
    comparison silently never matches — see janitor QNMBH3ES follow-up.
    """
    return ticket_proposal._dedupe_key(f"{code}:{tickets._clean(where, _FIELD_CAP)}")


@dataclass(frozen=True)
class Raised:
    """The outcome of `raise_issue`. `line` is a ready-to-print heartbeat line (empty when silent).

    The two domains are deliberately NOT symmetric about that line, because only one of them can act:

      HARNESS — announced ONCE, on open. The janitor is about to fix it itself; repeating the line
                every five minutes would be pure nag, and a nag that recurs forever trains its reader
                to ignore it.
      PROJECT — re-announced on EVERY raise, until someone approves. Nothing is fixed until the main
                Claude runs the command, so a reminder that stops is a finding silently dropped — and
                the one line that WAS printed may well have landed inside a compaction. The user asked
                for exactly this: "proactively recommend and remind".

    `first_seen` tells a caller which raise actually created something, so a detector with its own
    cadence can still choose to be quieter than this default.
    """

    code: str
    domain: str
    ok: bool
    ticket_id: str = ""
    trdd: str = ""
    command: str = ""
    line: str = ""
    why: str = ""
    first_seen: bool = False


def raise_issue(
    code: str,
    *,
    evidence: list[str] | None = None,
    severity: str = "",
    dedupe_key: str = "",
    where: str = "",
    origin: str = "",
    project_dir: str | None = None,
    now: int | None = None,
    **data: object,
) -> Raised:
    """Turn a detected issue into WORK. The one call a detector makes; the code decides everything else.

    HARNESS codes open (and later dispatch) a ticket unattended — the janitor repairing its own
    machinery. PROJECT codes only author a proposal TRDD and hand back the exact approval command; no
    ticket exists, and nothing is dispatched, until a human or the main Claude runs it.

    Every `**data` value is sanitized before it touches a template, so a detector may pass a filename,
    a dependency name, or a workflow line straight from an attacker-influenceable source.
    """
    issue = ISSUE_CATALOG.get(code)
    if issue is None:
        # Fail LOUD but not fatal: a typo'd code must not silently swallow a real finding.
        return Raised(code=code, domain="", ok=False, why=f"unknown issue code `{tickets._clean(code, 24)}`")

    fields = _fields(where, data)
    title = _render(issue.title, fields)

    parts = [
        f"**{code}** ({issue.scanner}, severity `{severity or issue.severity}`)",
        "",
        f"**What:** {issue.what}",
        "",
        f"**Why it matters:** {issue.why}",
        "",
        f"**Fix to attempt:** {issue.fix}",
    ]
    # `found` carries THIS occurrence's specifics — the rule ids, the files, the lines. It is passed
    # as data (already sanitized) rather than rendered into the templates, because `what` and `fix`
    # quote real Actions syntax (`${{ github.event.* }}`) and running them through a formatter would
    # eat the braces and leave the ticket teaching the agent a syntax that does not exist.
    if fields.get("found"):
        parts += ["", f"**Found:** {fields['found']}"]
    detail = "\n".join(parts)
    key = _finding_key(code, issue, fields, dedupe_key)
    ev = list(evidence or [])
    org = origin or issue.scanner
    kind_spec = tickets.KIND_REGISTRY[issue.kind]

    if kind_spec.domain == tickets.HARNESS:
        t, why = tickets.open_ticket(
            kind=issue.kind,
            title=title,
            detail=detail,
            evidence=ev,
            severity=severity or issue.severity,
            dedupe_key=key,
            origin=org,
            now=now,
        )
        if t is None:
            return Raised(code=code, domain=tickets.HARNESS, ok=False, why=why)
        first_time = why.startswith("opened")
        if first_time:
            # Findings-ledger sink (TRDD-FENWWB4E): index the finding EVENT (once, at
            # birth — the ticket layer already dedupes re-raises) in the affected
            # project's per-project mailbox, ref'd by the ticket id so a later session
            # (or the dashboard) resolves the body on demand. The returned drift line
            # is deliberately ignored: `line` below is this call's richer surface.
            findings_ledger.record(
                sev=t.severity, code=code, src=org, msg=title, ref=t.id,
                project_dir=project_dir, now=now,
            )
        line = f"[ticket] {code} {t.id} ({t.severity}): {title} — the janitor will repair this itself" if first_time else ""
        return Raised(code=code, domain=tickets.HARNESS, ok=True, ticket_id=t.id, line=line, why=why, first_seen=first_time)

    proposed = ticket_proposal.propose(
        kind=issue.kind,
        title=title,
        detail=detail,
        evidence=ev,
        severity=severity or issue.severity,
        dedupe_key=key,
        origin=org,
        project_dir=project_dir,
        now=now,
    )
    if proposed is None:
        # The finding is ALREADY an open ticket — approved, and the queue owns it now. Silence here is
        # correct: re-recommending a fix that is already scheduled would be noise.
        return Raised(code=code, domain=tickets.PROJECT, ok=True, why="already an open ticket")
    uid, command, is_new = proposed
    if not command:
        # A HUMAN previously REFUSED this exact finding (same dedupe key, unchanged evidence — see
        # ticket_proposal.propose). The verdict is settled: surface NOTHING per fire, record nothing
        # in the ledger. A per-heartbeat "still refused" line would re-litigate a closed question 288
        # times a day, and a fresh approval request nearly caused a false-premise dispatch once
        # already (ai-maestro-plugins#15). The finding resurfaces by itself the moment its evidence
        # changes, and the refused TRDD (`column: refused`, still in design/proposals/ — no refused folder exists,
        # owner ruling 2026-09-24, janitor#309/#329) remains the auditable record.
        return Raised(
            code=code, domain=tickets.PROJECT, ok=True, trdd=uid,
            why=f"previously refused (TRDD-{uid}) — suppressed until the evidence changes",
        )
    if is_new:
        # Findings-ledger sink (TRDD-FENWWB4E) — same once-at-birth indexing as the
        # HARNESS branch, ref'd by the proposal TRDD id.
        findings_ledger.record(
            sev=severity or issue.severity, code=code, src=org, msg=title,
            ref=f"TRDD-{uid}", project_dir=project_dir, now=now,
        )
    line = f"[ticket] {code} ({severity or issue.severity}): {title} — approve the fix with: {command}"
    return Raised(
        code=code,
        domain=tickets.PROJECT,
        ok=True,
        trdd=uid,
        command=command,
        line=line,
        why="proposed" if is_new else "already proposed — still awaiting approval",
        first_seen=is_new,
    )


def clear_issue(
    code: str,
    *,
    where: str = "",
    dedupe_key: str = "",
    project_dir: str | None = None,
    **data: object,
) -> str | None:
    """The finding is GONE — withdraw its unapproved proposal. Returns the withdrawn TRDD id, or None.

    Call this on the path where a detector can PROVE the condition is absent (the ruleset is back, the
    advisory is gone, the workflow was fixed by hand). Pass the SAME `code` + `where`/`dedupe_key` the
    raise used — the key is derived by the same function, so they cannot drift apart.

    It only ever touches an UNAPPROVED proposal, and that asymmetry is deliberate in both directions:

      PROJECT — nothing has happened yet. No ticket, no agent, no work. Withdrawing the proposal costs
                nothing and keeps the user's git-tracked board honest.
      HARNESS — an OPEN harness ticket is NEVER cancelled by a clear, even though it would be easy and
                would save a dispatch. That is precisely the trap this whole subsystem exists to avoid:
                the memgrep self-heal RACES any observer and wins, so a harness incident "clearing" is
                usually the damage being papered over, not repaired. Cancelling the ticket on that
                signal would reconstruct the exact blind spot that let the migration bug hide for days.
                An opened harness incident gets worked; the agent decides whether it was real.
    """
    issue = ISSUE_CATALOG.get(code)
    if issue is None or tickets.KIND_REGISTRY[issue.kind].domain != tickets.PROJECT:
        return None
    key = _finding_key(code, issue, _fields(where, data), dedupe_key)
    return ticket_proposal.retract(key, project_dir=project_dir)


def reconcile(
    code: str,
    live_wheres: Iterable[object],
    *,
    project_dir: str | None = None,
) -> list[str]:
    """Withdraw every proposal for `code` whose finding is NO LONGER THERE. Returns the withdrawn ids.

    `clear_issue` answers "this exact finding is gone" — which only works when the detector can still
    NAME the finding it wants to clear. Most scanners cannot: a scan produces the findings that EXIST,
    and the ones that vanished are, by definition, not in the result. Asking such a detector to clear
    what it no longer sees is asking it to remember every string it has ever emitted.

    So invert it. The detector passes the `where` of every finding it found THIS run, and anything else
    on the board under this code is stale by construction. That is also why it is one pass over the
    proposals rather than one pass per finding: a lockfile with 800 dependencies must not re-read the
    whole design board 800 times to discover that 799 of them are fine.

    Call it on EVERY run, including the clean one (with an empty set) — a scanner that only reconciles
    when it finds something can never withdraw its last proposal, which is precisely the one that
    matters.
    """
    issue = ISSUE_CATALOG.get(code)
    if issue is None or tickets.KIND_REGISTRY[issue.kind].domain != tickets.PROJECT:
        return []
    live = {_finding_key(code, issue, _fields(str(w), {}), "") for w in (live_wheres or [])}
    prefix = f"{code}:"
    withdrawn: list[str] = []
    for p in ticket_proposal.pending(project_dir):
        if not p.key.startswith(prefix) or p.key in live:
            continue
        uid = ticket_proposal.retract(p.key, project_dir=project_dir)
        if uid:
            withdrawn.append(uid)
    return withdrawn


_LEGACY_WHERE_RE = re.compile(r"^[^:]+:\d+$")

# A legacy `{rel}:{line}` entry and a live finding for the same rel are "the same finding" only
# when their line numbers are close: an edit above the span shifts it by a few lines, but a span
# hundreds of lines away is a different defect wearing the same rel. Never guess, never merge —
# proximity is the only evidence a legacy line and a live span are the same finding.
_LEGACY_LINE_SLACK = 25


def migrate_legacy_where(
    code: str,
    new_keys_by_rel: dict[str, list[tuple[str, int]]],
    *,
    scanned_rels: set[str] | None = None,
    project_dir: str | None = None,
) -> tuple[int, int, int]:
    """One-shot re-key of proposals still carrying a pre-content-addressed `{rel}:{line}` dedupe
    key (TRDD-QNMBH3ES). `new_keys_by_rel` maps each rel to `(new_key, line)` pairs for every live
    finding at that rel THIS run. Returns (migrated, dropped, ambiguous).

    `scanned_rels`, when given, is the set of rels the caller actually scanned THIS fire (the
    scan is budget-capped — janitor#291 follow-up). A legacy entry whose `rel` fell outside the
    cap is left COMPLETELY untouched: with no scan of that file this run, "no live match" is not
    evidence the finding is gone, only that we didn't look — migrating OR dropping it would be a
    claim this call cannot back. It stays legacy-keyed and is retried on the fire that scans it.

    Two or more legacy entries can independently proximity-match the SAME single live finding
    (an old bug minted one proposal per shifted line for what was really one finding, so `{rel}:40`,
    `{rel}:43`, `{rel}:47` all survive as separate proposals). Re-keying every one of them onto that
    finding's new key would leave several proposal files sharing one `ticket-dedupe-key` — a
    dedupe key stops deduping the moment two files claim it. `taken` tracks every new-shape key
    already spoken for (by an already-pending proposal, or by an EARLIER legacy entry migrated
    during this same call) so only the first claimant is re-keyed; every later one is dropped like
    a vanished finding — never merged into it, never left duplicating it.

    `reconcile()` treats "absent from the live set" as "the finding is gone" — correct for the new
    content-addressed keys, but a legacy-keyed entry for a finding that is STILL THERE would look
    absent too (its key never appears in a live set built from the new scheme) and get retracted,
    only to be re-proposed moments later as a "new" finding. So this runs first: an entry whose
    `rel` the caller says is still live gets rewritten to that finding's new key IN PLACE; one whose
    `rel` has no live match is a dead artifact of the old scheme and is deleted directly — never
    through `ticket_proposal.retract`, which would write "WITHDRAWN BY THE JANITOR" and assert the
    finding was seen and cleared, a claim this code cannot actually back (the old key never told us
    which rule fired, so a caller-side "still live" miss here is not proof the finding is gone).

    A legacy key only ever named `{rel}:{line}` — no rule id, no column, nothing to disambiguate
    it — so when a `rel` now carries MORE THAN ONE live finding (two spans, same rule, same file)
    there is no honest way to pick which one the legacy entry meant. Guessing (e.g. "last wins")
    silently re-keys it to a finding it may never have been about. Same story with exactly one live
    finding whose line is far from the legacy line: that is not the finding the legacy entry named
    (the old one was fixed; a new, unrelated one appeared elsewhere in the file) — re-keying onto it
    would silently rewrite a proposal about A into one about B, wearing A's stale evidence. Both
    cases are dropped like a vanished one (never re-keyed, never merged); the far-line case counts
    as `dropped`, the multi-finding case as `ambiguous`, so a fire log can tell "the finding is
    gone", "a different one took its place", and "we could not tell which finding it was" apart.
    """
    prefix = f"{code}:"
    migrated = 0
    dropped = 0
    ambiguous = 0
    # Seed `taken` with every new-shape key already spoken for by a STANDING proposal, so a
    # legacy entry never re-keys onto a key some other file already carries.
    taken: set[str] = {
        p.key
        for p in ticket_proposal.pending(project_dir)
        if p.key.startswith(prefix) and not _LEGACY_WHERE_RE.match(p.key[len(prefix) :])
    }
    for _scope, path in ticket_proposal.trdd_common.trdd_files("proposals", project_dir):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        key = ticket_proposal._frontmatter(text).get("ticket-dedupe-key", "")
        if not key.startswith(prefix):
            continue
        where = key[len(prefix) :]
        if not _LEGACY_WHERE_RE.match(where):
            continue  # already new-shape, or not this migration's shape at all
        rel, _, legacy_line_str = where.rpartition(":")
        if scanned_rels is not None and rel not in scanned_rels:
            continue  # capped scan never looked at this file — absence is unprovable
        new_keys = new_keys_by_rel.get(rel, [])
        new_key = None
        if len(new_keys) == 1:
            live_key, live_line = new_keys[0]
            if live_key not in taken and abs(int(legacy_line_str) - live_line) <= _LEGACY_LINE_SLACK:
                new_key = live_key
        elif len(new_keys) > 1:
            ambiguous += 1
        if new_key is not None:
            new_text = re.sub(
                r"(?m)^ticket-dedupe-key: .*$",
                f"ticket-dedupe-key: {new_key}",
                text,
                count=1,
            )
            try:
                # Atomic (write-tmp + rename), not a plain `write_text` — this file is
                # git-tracked, so a crash mid-write must never leave it half-rewritten (A9).
                state.atomic_write(path, new_text)
            except OSError:
                continue
            taken.add(new_key)
            migrated += 1
        else:
            try:
                path.unlink()
            except OSError:
                continue
            dropped += 1
    return migrated, dropped, ambiguous


def issue_domain(code: str) -> str:
    """The domain a code resolves to, or `""` for an unknown code. For docs + tests."""
    issue = ISSUE_CATALOG.get(code)
    return tickets.KIND_REGISTRY[issue.kind].domain if issue else ""


def scanners() -> list[str]:
    """Every scanner that has at least one code, sorted. The coverage handle."""
    return sorted({i.scanner for i in ISSUE_CATALOG.values()})
