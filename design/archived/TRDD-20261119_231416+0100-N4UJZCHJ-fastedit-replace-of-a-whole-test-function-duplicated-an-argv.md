---
trdd-id: N4UJZCHJ
title: fastedit replace of a whole test function duplicated an argv line and dropped a decorator
column: complete
status: archived
created: 2026-11-19T23:14:16+0100
updated: 2026-11-19T23:24:11+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-19T23:14:16+0100
---

# fastedit replace of a whole test function duplicated an argv line and dropped a decorator

2026-11-19, B607 finish worker: fastedit edit --replace on test functions in tests/test_pre_push_python_floor.py and tests/test_keepalive_install.py left the old argv line beside the new one (subprocess.run got two positional lists) and removed the @pytest.mark.real_subprocess decorator, exit 0 both times. Caught only by the harness review of git diff. Reproduce on a scratch copy, then file the bug on the fastedit repo (Emasoft-owned) with the reproducer; meanwhile worker prompts must say: use --replace-literal or --lines for line-level edits and always fastedit diff. Related: TRDD-6NMQ95TQ.

## Approval log

- 2026-11-19T23:14:16+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-19 main-agent: reproduced on fastedit 0.5.0 (report reports_dev/sonnet-worker/20261119_231657+0100-n4ujzchj.md). Defect A (old line kept when the snippet also adds a line) filed as Emasoft/fastedit#34. The inline --snippet-is-literal failure that leads agents to omit decorators, plus the silent decorator drop, filed as Emasoft/fastedit#35. The fix belongs to fastedit; this repo's side is done: worker prompts now forbid whole-function --replace for line-level changes and require fastedit diff after each edit. Closing.
- 2026-11-19T23:24:11+0100 — COMPLETE by main-agent@ai-maestro-janitor. bugs reproduced and filed upstream (fastedit#34, #35); janitor-side mitigation in worker prompts.

## Acceptance

- [x] Both defects reproduced on a scratch copy with exact commands and fastedit diff output (report 20261119_231657+0100-n4ujzchj.md)
- [x] Bugs filed on the Emasoft-owned fastedit repo with reproducers (fastedit#34, fastedit#35)
- [x] Worker prompts in this repo forbid whole-function --replace for line-level edits and require fastedit diff after each edit
