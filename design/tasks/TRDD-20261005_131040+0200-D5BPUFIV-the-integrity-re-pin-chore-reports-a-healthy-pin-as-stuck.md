---
trdd-id: D5BPUFIV
title: the integrity re-pin chore reports a healthy pin as stuck
column: testing
status: tasked
created: 2026-10-05T13:10:40+0200
updated: 2026-10-05T13:36:28+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T13:10:40+0200
implementation-commits: [8a5619f7]
---

# the integrity re-pin chore reports a healthy pin as stuck

Symptom: the daemon filed the stuck-anchor finding SELFINT-004 (janitor ticket T-JWYHOMMV) against an integrity pin that was healthy: it already named the running version.

Cause, read in the code on 2026-10-05: the certify function returns nothing both when it refuses to pin and when the pin is already current, and the re-pin chore counted every such return as a decline. Three fires, eighteen hours, after a successful pin the chore reported it stuck.

Fix, in scripts/daemon.py (task_integrity_repin): the chore collects the refusal reasons certify logs. A return with no refusal reason is the already-current case and ends a decline streak. The one other silent return, no version cached at all, is counted as a decline with its own reason. The certify function itself is unchanged: what gets pinned and how the manifest is checked are untouched.

Origin: written by the janitor repair agent working the ticket, which died before reporting. Verified afterwards by a read-only worker and by the main agent reading the test file and every return path of certify: every refusing path logs; the two silent returns are the ones the fix assumes.

## Approval log

- 2026-10-05T13:10:40+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Acceptance

- [ ] A pin that already names the running version is never counted as a decline (test in tests/test_daemon_integrity_repin.py).
- [ ] A real refusal is still ticketed once, on the third fire (same test file).
- [ ] LIVE: on an install carrying the fix, the daemon log shows no stuck-anchor finding across four consecutive re-pin fires while the pin names the running version.

## STATE

2026-10-05 — Column testing. The fix and four tests are in the working tree, verified: the four tests pass and two of them fail against the previous daemon code; ruff and mypy clean; the type checker pyright and the full suite were not run on it yet. NAMED LIVE EVENT: the third acceptance box.
2026-10-05 — KNOWN LIMIT, not fixed: the chore infers 'already current' from the absence of a logged reason. A future refusing branch in certify that returns without logging would read as current and hide a stuck pin; an informational log line on the current path would bring the false alarm back. The robust shape is for certify to return a tagged result; that touches its other caller and is left for a later card.
2026-10-05 — OPEN, existed before this change: when certify raises, the chore logs 'skipped' and counts nothing, so a certify that always raises is never ticketed.
2026-10-05 — changed behaviour to know: a host with no cached version at all is now counted as a decline and ticketed after three fires; before, it raised nothing.
2026-10-05 — the janitor ticket T-JWYHOMMV still reads dispatched because its agent died; it must be closed through the ticket workflow with a status naming the fix commit.
2026-10-05 — the fix and tests are committed as 8a5619f7 and this card as d30d68d4.
2026-10-05 — who the new empty-cache decline can reach, read in the cache-location function: when the plugin root's parent lists no versions (the daemon running from its staged copy), the function falls back to the standard user-scope cache folder. So a normal install is never seen as empty. A host where the plugin is loaded without any user-scope cache entry (for example straight from a development folder) is seen as empty and will be ticketed after three fires. Accepted for now; say so if that host shape matters.
2026-10-05 — NOT gated yet: the type checker pyright and the full suite have not run on 8a5619f7. A publish dry-run on the head containing it stopped at the type-check step because pyright timed out after fifteen minutes on a heavily loaded machine; ruff and mypy had passed. Rerun when the machine is idle.
2026-10-05 — the janitor ticket is still open (dispatched, its agent dead). Not closed by hand. Route to take: the ticket workflow's own close with a status naming 8a5619f7 and this card; if a ticket marker is re-offered, a fresh repair agent must be told the fix exists so it does not write a second one.
