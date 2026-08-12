---
trdd-id: WP7TCRME
title: The janitor FIXES instead of notifying — loudness gate, own-project-only warnings, and cross-project issue filing
column: dev
created: 2026-08-12T20:13:28+0200
updated: 2026-08-12T20:36:57+0200
current-owner: janitor-main-session
task-type: refactor
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
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

**NEXT ACTION:** implement Rule 2 (own-project-only) first — it is the smallest, it is
purely subtractive, and it is the one currently leaking other repos' problems into this
project's conversation. Then Rule 4 (cross-project issue filing), which is what makes Rule 2
safe: without it, "don't tell this Claude" would silently drop a real finding.

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
- [ ] No finding about a project other than `CLAUDE_PROJECT_DIR` reaches this session's
      stdout. Pinned by a test.
- [ ] A finding for another OWNED repo is filed as an issue on that repo by a script, with
      dedupe so a recurring detector cannot open the same issue every fire.
- [ ] The auto-fixable findings are enumerated, and each is fixed by a script or a background
      agent rather than surfaced. Each carries a test proving the fix runs.
- [ ] Decision-margin findings are enumerated and still escalate — with the reason they
      cannot be automated stated in the code, so nobody later "helpfully" automates them.
- [ ] Measured: the number of stdout lines a quiet fire emits, before and after.

## Approval log

- 2026-08-12T20:13:28+0200 — QUEUED by janitor-main-session (tier 0, own scope) directly at
  `dev`, not `backburner`: it is the USER's own directive, given in-session, and the filter
  half already shipped — leaving the card outside a WORK column would make an in-flight
  change look unstarted.
