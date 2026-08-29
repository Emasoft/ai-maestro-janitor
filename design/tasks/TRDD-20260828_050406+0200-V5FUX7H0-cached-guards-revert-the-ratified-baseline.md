---
trdd-id: V5FUX7H0
title: Cached branch-protection guards are reverting the USER-ratified baseline repo by repo
column: testing
created: 2026-08-28T05:04:06+0200
updated: 2026-08-29T22:35:00+0200
current-owner: janitor-session
task-type: infra
project-id: ai-maestro-janitor
min-approval-requirement: user
blocked-by: []
relevant-rules: [2]
---

# The fleet apply is being undone as each armed session's heartbeat fires

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-29

**UNBLOCKED, and the "Do NOT re-apply" instruction below has INVERTED — do not follow it blind.**
TRDD-X4LJFTB4 cleared and v3.4.0/v3.4.1 shipped, so the corrected payload is now in the CACHED
code every guard runs from. Verified by reading the published copy, not the working tree:
`3.4.1/scripts/lib/branch_protection_lib.py:334` emits `{"type": "deletion"}` with an explicit
comment that `non_fast_forward` is deliberately absent (USER Tier-3 ruling 2026-08-27). The guards
are now REVERTERS TOWARD the ratified shape. That is the whole fix — the card was right that the
only fix was to publish.

**NOT converged yet, measured live 2026-08-29 (`gh api repos/Emasoft/<r>/rulesets/<id>`):**

| repo | `baseline-history-protect` rules |
|---|---|
| ai-maestro-janitor | `deletion` ✅ |
| ai-maestro-webdesign | `deletion` ✅ |
| ai-maestro-plugin | `deletion, non_fast_forward` ❌ |
| ai-maestro-maintainer-agent | `deletion, non_fast_forward` ❌ |

**NEXT ACTION: nothing, deliberately — wait and re-measure.** Convergence is now the guards' own
job: each repo corrects itself the first time an armed session running ≥3.4.0 fires its guard.
Re-running the fleet apply from here is still not the move, but for the OPPOSITE reason to the
one below — it is redundant, not futile. A session still on cached 3.3.26 would re-revert its own
repo, so the honest completion test is per-repo, not one apply:

```bash
gh api repos/Emasoft/<repo>/rulesets --jq '.[]|select(.name=="baseline-history-protect").id'
gh api repos/Emasoft/<repo>/rulesets/<id> --jq '[.rules[].type]|sort|join(",")'
# want: "deletion"   — "deletion,non_fast_forward" means that repo's session is still pre-3.4.0
```

Close this card when every fleet repo reads `deletion`. Do NOT close it on the strength of the
publish alone: shipping the fix and the fleet having APPLIED it are two different facts, and this
card exists precisely because the gap between them was invisible.

**This supersedes TRDD-7EXBJB03's "the fleet IS now repaired" line.** That was TRUE when written
and verified live; it stopped being true within the hour. 7EXBJB03 is terminal and is left
untouched — this card carries the correction.

## What happened

Tonight's `github_config_fix.py --all --apply` set `baseline-history-protect` to `deletion`
only on 14 repos, per the USER's Tier-3 ruling that history rewrite must be allowed everywhere.
Verified live at the time.

Then this project's own heartbeat guard fired and announced:

> `baseline-history-protect (deletion + non_fast_forward)` … `pull_request 1-approval`

— the OLD payload. Live check immediately after: `non_fast_forward` is back on this repo.

## Measured spread (11 repos sampled, 2026-08-28)

| reverted to `deletion+non_fast_forward` | still `deletion` only |
|---|---|
| ai-maestro-janitor, ai-maestro-plugin, ai-maestro-maintainer-agent, ai-maestro-visual-communicator-plugin, ai-maestro-assistant-role-agent, ai-maestro-autonomous-agent | ai-maestro-webdesign, ai-maestro-orchestrator-agent, ai-maestro-programmer-agent, ai-maestro-web-scenario-tester, ai-maestro-assistant-manager-agent |

**6 reverted, 5 held.** The reverted set matches the repos with a LIVE armed Claude session
(seen in `ListAgents`): each session's guard runs from the CACHED plugin (3.3.26), whose
`branch_protection_lib.baseline_ruleset_payloads` still carries the pre-ruling shape. The 5 that
held have no armed session that has fired yet. **The remaining 5 will revert as their sessions
fire** — this is a race the cached code wins on a ~5-minute cadence.

## Root cause, and why re-applying is futile

The corrected payload is UNCOMMITTED and UNPUBLISHED. Guards do not read a working tree; they run
the newest CACHED version (the rollout-staleness law — `[[claude-code-plugin-rollout-staleness]]`,
ATOM-ARO4-DFBY). Re-running the fleet apply now would be undone again on the next heartbeat, per
repo, forever. **The only fix is to publish.**

## Blocked on

`TRDD-X4LJFTB4` — the 3.4.0 publish is refused by GitHub push protection over two SYNTHETIC
fixtures. That is an owner decision (unblock-URL vs history rewrite; a history rewrite is
explicitly not mine to perform). Until it clears, a USER-ratified baseline is being actively
reverted on a 5-minute cadence, and the ruling is unenforced on more than half the fleet.

## Do NOT

- Do NOT re-run the fleet apply as a "fix" — it loses the race and produces churn plus a
  misleading audit log full of successful applies that were immediately undone.
- Do NOT disable the guard to win the race: it also enforces PR review and required checks, and
  turning off a security control to make a config stick is the wrong trade.

## Notes and lessons learned

- A self-healing guard is a REVERTER for any change that has not shipped to it. The stronger the
  guard, the harder it fights a correct-but-unpublished fix — the property that makes drift
  self-repair is the same one that makes an unshipped ruling unenforceable.
- 2026-08-29 — **A "Do NOT do X" written under a blocker can INVERT the moment the blocker
  clears, and it does not announce that it has.** "Do NOT re-run the fleet apply" was correct
  because the apply would lose a race against unpublished code; after the publish it is merely
  redundant, and the guard it was warning about is now the thing doing the fix. The prohibition
  reads identically in both worlds. **When a card is unblocked, re-derive its Do-NOTs against the
  new state instead of inheriting them** — a stale prohibition is more dangerous than a stale
  fact, because it stops work rather than misinforming it, and nothing ever fails to make it
  visible.
- 2026-08-29 — **`~/.claude/rules/manager-approval-defaults.md` §F still lists the ratified
  `baseline-history-protect` as `deletion, non_fast_forward`**, which contradicts the 2026-08-27
  Tier-3 ruling the shipped code implements. That file's own text warns about exactly this
  (the TRDD-88LDC7E0 stale-reference finding) and says to build payloads from the code SSOT
  `branch_protection_lib.baseline_ruleset_payloads`, never from its prose. Flagged, not edited —
  it is not this repo's file to change.
