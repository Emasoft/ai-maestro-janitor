---
trdd-id: WP7TCRME
title: The janitor FIXES instead of notifying — loudness gate, own-project-only warnings, and cross-project issue filing
column: blocked
created: 2026-08-12T20:13:28+0200
updated: 2026-09-03T11:08:56+0200
current-owner: janitor-main-session
task-type: refactor
approval-tier: 0
scope: project
severity: high
implementation-commits: [b8dbc254, 7ad7c0ee, da249936, d4d9f726]
relevant-rules: []
npt: []
eht: []
blocked-by: [user-decision-exempt-subset-applier]
unblock-when: [decision:user]
pre-block-column: todo
external-refs: [TRDD-FENWWB4E, TRDD-CGYMUKO6]
---

# The janitor fixes instead of notifying

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-12

**USER directive, 2026-08-12.** Recorded because it reverses the janitor's default posture:
today it DETECTS and TELLS; it must DETECT and FIX, and interrupt only when a human decision
is genuinely required.

**Landed already (partial, `adcd8af1`):** the quiet heartbeat — advisory detector output goes
to the findings ledger instead of stdout, markers and self-tagged urgent lines still surface,
default LOUD so a new security detector is never silenced by omission. That is the FILTER
half. This card is the rest, and the rest is the harder half: the filter makes noise
invisible, it does not make the work get done.

**NOT STARTED:** everything in "The four rules" below.

**Rule 2 was ALREADY DONE** (see Acceptance) — assumed a leak, found none. Verifying cost one
command; building it would have cost a day and changed nothing.

**LANDED so far on this card:**
  - `adcd8af1` quiet heartbeat (the FILTER half — see the measurement section: it fixes none of
    the COST, only the noise)
  - `b8dbc254` Rule 3 #1 — a non-executable detector is chmod'd, not reported
  - `da249936` Rule 4 — `cross_project_issue.py`, the owned-repo issue filer.
  - `7ad7c0ee` + `254df25f` Rule 3 #2 — the `reports/` gitignore guard, library AND wired as a
    daily detector. Verified live.
  - `d4d9f726` Rule 4 **WIRED** — the daemon's fleet GitHub-config audit files each repo's gaps
    on that repo's own tracker. The caller is the DAEMON, not a detector, and that is the
    load-bearing part: a project session is forbidden to speak about another repo at all, so the
    only component allowed to file cross-repo is the one that is not a project session. Owning
    repo is the finding's own slug — never inferred from a path. One issue per repo, keyed on the
    GAP SET (an unchanged set dedupes forever; a NEW gap is not swallowed by the stale marker),
    5 filings per beat with the deferred count LOGGED.

**NEXT ACTION — BLOCKED ON A USER DECISION, and the block is the finding.** I went to build
Rule 3's last two categories and found them already built, as PROPOSE → user approves → agent
fixes. Verified in the source, 2026-08-13:

  - **Workflow hardening** — `detectors/workflow-security.py:246` raises one proposal per finding
    CLASS (`by_code`), and the code states the reason it does not just fix: *"These are the
    USER's workflows, so the janitor may only offer… the user may well want the injection fixed
    and the permissions left alone — approval is per class, so it has to be a real choice."*
  - **Dependency bumps** — `DEP-001/002/003` in `lib/issue_catalog.py:313-338` already encode the
    exact policy the directive asks for: bump to the fixed version and run the full suite; if no
    fixed version exists FLAG it, never silently pin; and for a KNOWN-MALICIOUS version, *"Report
    to the user IMMEDIATELY — do not quietly bump"*.
  - Both route to `janitor-security-agent`, and `lib/tickets.py:478` REFUSES to open either
    without an approved TRDD, because *"the janitor is a guest in the user's repo"*.

**So the remaining work is not code — it is one governance question.** `branch-protection`
already has a guarded auto-applier (`scripts/guard/branch_protection_apply.py`, default-ON,
vetoed by `/janitor-autofix-off`) that applies the ratified baseline with NO ticket and NO
approval, because `manager-approval-defaults.md` §F classes applying that baseline as-is as
EXEMPT. SHA-pinning third-party actions is listed as EXEMPT in the same table — but it has no
such applier, so it goes through the approval gate anyway.

**THE DECISION (USER's):** should the EXEMPT subset — SHA-pin actions, add job timeouts, tighten
`permissions:` to least-privilege — get a guarded applier like branch-protection's, bypassing
per-finding approval? It is defensible either way and the difference is not technical:
  - **YES** — the governance rules already call it exempt, and Rule 3 says an obvious fix should
    not wait on a human.
  - **NO** — a CI file is the user's, a wrong pin breaks every build in the repo, and the
    existing per-class approval is one keystroke.
Do NOT decide this by inferring it from Rule 3; the two rules genuinely point different ways,
which is what makes it a decision rather than an oversight.

**Do it in a SMALL context.** This card's own measurement: a fire costs ~398k weighted against
a 3.5M session versus ~17k against a fresh one. Building the cost fix inside the expensive
session is the one way to make it not worth having.

## The four rules (USER, verbatim intent)

**RULE 1 — a warning may be LOUD only if ALL of:**
  1. it is urgent that the USER know, because only they can solve it; OR urgent that the MAIN
     CLAUDE know, because only it can solve it;
  2. it cannot be silently filed as a ticket to solve later;
  3. it is truly solvable IMMEDIATELY by some action.

A structural problem needing a code rewrite is NEVER a warning. It is a ticket.

**RULE 2 — a warning must concern the CURRENT project.** Never another project's state. The
janitor runs in every project on the machine and today reports fleet-wide findings into
whichever conversation happens to be open, which is both a distraction and, per
`janitor-per-project-channeling`, a leak of one repo's state into another's session.

**RULE 3 — tickets and chores must FIX, not notify.** A ticket that is only a read-only
message to the main Claude "in the hope it will fix the issue" is not a ticket. Where the
course of action is obvious and there is no choice to make, a background script (zero model
tokens) or a subconscious agent must DO it.

**RULE 4 — another project's problem becomes an ISSUE ON THAT PROJECT.** When the finding
belongs to a repo the user owns (the gh-auth login matches the repo owner), the script files
the issue there directly. It must not be pushed into the current project's Claude, which
cannot fix it anyway.

## The decision margin — when the janitor must NOT act alone

Rule 3 is bounded by this, and the boundary is the whole safety story. Act directly when the
course of action is OBVIOUS AND UNIQUE. Escalate when there is a real choice between
defensible options, e.g.:

  - merge conflicts (which side wins is a judgement about intent),
  - stale worktrees / stashes (is that abandoned work or unfinished work?),
  - a security finding in an updated plugin — uninstall it, or attempt to clean it?
  - anything destructive or irreversible.

The test is not "is it risky" but "is there more than one defensible answer". A single
defensible answer means the janitor should already have done it.

## The measurement that sizes this card (2026-08-12, this host's own token meter)

Read from `.janitor/state/token-meter.jsonl`, not estimated:

| quantity | value |
|---|---|
| heartbeat fires logged | 1999 |
| mean weighted tokens per fire, all-time | 199,929 |
| **mean per fire, last 50** | **398,459** |
| janitor heartbeat, rolling 7d | 110.7M weighted — **~68% of the window's 163.6M** |
| turns logged | 3349 — of which **2717 are heartbeat**, 632 interactive |

**A quiet fire is not cheap; it is the most expensive thing on the machine.** At `*/5` that is
288 fires/day × ~398k = **~115M weighted per day**, and the per-fire figure has DOUBLED against
the all-time mean purely because this session's context grew — the cost scales with context,
not with what the fire finds.

**This is why the quiet-heartbeat work (`adcd8af1`) does not, by itself, fix anything.** It cut
what a fire PRINTS. The cost is the TURN — the transcript re-read at the cache-read rate — and
printing nothing still pays it in full. Three variables (`turns × per-turn-context × output`)
and that change touched only the smallest one.

The three real levers, measured rather than guessed:

1. **Context size — ~23×.** A fire against this session (3.5M cached) costs ~398k weighted; a
   fire against a freshly-cleared session (~166k floor) costs ~17k. This is the dominant term
   and the reason TRDD-1QJIZFFW is a cost card, not a convenience card.
2. **Cadence — 3×.** `*/5` → `*/15` is 288 → 96 fires/day. Has a real trade (responsiveness),
   so it is a USER decision, not an autofix.
3. **Not waking the model at all — the structural one, and this card's actual subject.** A cron
   fire IS a model turn by construction, so no amount of filtering makes a quiet fire free. The
   only way to stop paying for a fire with nothing to say is for the DAEMON (free, no model) to
   run the detectors and for the model to be woken only when something needs it. The injection
   machinery for that already exists (`fleet_inject` / `terminal_trigger` can type into a pane);
   what does not exist is the inversion — today the model wakes on a schedule and asks "is there
   anything?", when it should sleep until the daemon says "there is".

## Why (the cost being paid today)

Every advisory line the janitor prints lands in a main Claude's context: it interrupts the
model's current reasoning, costs tokens on that turn AND on every later turn (the transcript
is re-read), and very often describes something the reader cannot act on — another project's
drift, or a structural problem needing a rewrite. The janitor has scripts, a daemon, and
background agents; a finding it can fix with any of those and instead narrates is spending
the most expensive resource in the system to avoid using the cheapest.

## Acceptance

- [ ] A detector's output is classified LOUD only against Rule 1's three-part test, and the
      classification is greppable (not per-detector prose).
- [x] No finding about a project other than `CLAUDE_PROJECT_DIR` reaches this session's
      stdout. **Already true, and already pinned — verified 2026-08-12 rather than rebuilt.**
      Of the 7 detectors that scan fleet-wide, only 3 print at all, and all 3 gate on the
      current project; `orphaned-resume-flag` (the one whose findings looked cross-project)
      prints only for its own root and routes other projects' findings into THEIR ledgers.
      Pinned by `test_format_finding_names_no_other_project`,
      `test_two_orphaned_projects_do_not_suppress_each_other`, and the ledger isolation
      contract in `test_findings_ledger.py`. Adding a fourth test would have ticked this box
      without changing any behaviour — the box was already earned by
      `janitor-per-project-channeling`'s lesson, which is why that page exists.
- [x] A finding for another OWNED repo is filed as an issue on that repo by a script, with
      dedupe so a recurring detector cannot open the same issue every fire. **Landed
      `d4d9f726`** — the daemon's fleet GitHub-config audit is the first caller. Dedupe is a
      hidden marker keyed on `(code, gap set)` and searched BEFORE filing; a failed search
      refuses to file, because "the search broke" is not evidence that nothing was filed. Zero
      model tokens: the daemon files it, no session is interrupted.
- [ ] The auto-fixable findings are enumerated, and each is fixed by a script or a background
      agent rather than surfaced. Each carries a test proving the fix runs.
- [x] Decision-margin findings are enumerated and still escalate — with the reason they
      cannot be automated stated in the code, so nobody later "helpfully" automates them.
      **Already true, verified 2026-08-13 rather than rebuilt.** The enumeration is
      `KIND_REGISTRY`'s PROJECT-domain rows (`lib/tickets.py:71-76`); the reason is at the gate
      (`:478` — "the janitor is a guest in the user's repo") and per-finding in the catalog
      (DEP-002: *"Report to the user IMMEDIATELY — do not quietly bump the version"*;
      `workflow-security.py:246`: approval is per CLASS so the user can fix the injection and
      leave the permissions alone). Writing a fifth statement of it would have ticked the box
      without changing anything.
- [ ] Measured: the number of stdout lines a quiet fire emits, before and after.

## Approval log

- 2026-08-12T20:13:28+0200 — QUEUED by janitor-main-session (tier 0, own scope) directly at
  `dev`, not `backburner`: it is the USER's own directive, given in-session, and the filter
  half already shipped — leaving the card outside a WORK column would make an in-flight
  change look unstarted.
