---
trdd-id: KSUIEPTQ
title: reports dir is git-tracked, the janitor stops gitignoring and purging it
column: testing
status: tasked
created: 2026-11-01T02:44:18+0100
updated: 2026-11-15T09:10:58+0100
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
approval-datetime: 2026-11-01T02:44:18+0100
implementation-commits: [010be429, 64768ab7]
---

# reports dir is git-tracked, the janitor stops gitignoring and purging it

USER 2026-11-01 verbatim: "can you please stop putting the reports/ folder in the gitignore? reports_dev must be git ignored. reports/ is essential to a project and must be project scoped. just use the report sanitizer script to redact private data and paths." and "the janitor is making a mess in every project ... publish asap and install". Spec = GitHub issues #348 (items 1,2,3,4) and #350. Item 5 of #348 (local design path revert) is OUT of scope, separate card.

Changes:
1. scripts/lib/reports_gitignore.py + scripts/detectors/reports-gitignore.py: REQUIRED_DIRS = (reports_dev,). Undo the fleet mess: remove a /reports/ line ONLY when it sits in the janitor's own _BLOCK_HEADER block; if git check-ignore -v names any other rule, emit one deduped advisory naming source:line, never edit a user-authored line.
2. scripts/lib/gitignore_coverage.py: reports is no longer a private class.
3. scripts/detectors/reports-purge.py: retire the reports/ age-purge half (reports/ is tracked work, *_dev contents are never deleted per RULE 0); keep the seen-file cap. Fixes #350.
4. scripts/detectors/screenshot-purge.py + dispatch.py comment: screenshots live in reports_dev/<component>/screenshots/.
5. scripts/commands/doctor.py + skills/janitor-doctor: check reports_dev ignored and reports NOT ignored.
6. Docs: rules/janitor-footprint.md, rules/trdd-design-tasks.md rule 11, rules/references/trdd-design-tasks-full.md, skills/janitor-gitignore-fix, agents (security, repair, memory curator): machine/harness state reports go to reports_dev/<agent>/, anything bound for reports/ is sanitized first with sanitize-reports.
7. This repo: drop /reports/ from .gitignore; move the 862 existing untracked reports/<c>/<f> to reports_dev/<c>/<f> (written under the private regime; not reviewable for publication now).

## Approval log

- 2026-11-01T02:44:18+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
2026-11-04 main-agent: the working-tree .gitignore again carries '/reports/' under the comment 'janitor: report dirs carry private data' (git diff, 2026-11-04). It is re-added by the installed 3.8.13 janitor, which predates 010be429. Restore .gitignore to HEAD right before publish.py runs (a dirty tree blocks it). After 3.8.14 is installed, check that the line does not come back.
- 2026-11-11T14:22:00+0100 — column → testing by user. code complete (010be429+bb9dc94b), release pending — dev-cards assessment 2026-11-11
2026-11-15 owner directive on the reports folder, verbatim, relayed by the llm-externalizer session: "reports folder is always git tracked and sanitized from secrets before committing. reports folder only contains final reports and complete/merged reports, or updated checklists with some progress tracking. while reports_dev is always gitignored and it contains intermediate artifacts, partial reports or temporary scratch files. In general the *_dev version of a folder is the gitignored one, the other without the _dev suffix is git tracked. Make sure to instruct the subagents to save their temporary or scratch files in the *_dev folders, and the final files in the other ones." This card is its home: 010be429 built the rules text and the agents report paths; no release tag contains it yet.
- 2026-11-15T09:10:58+0100 — OWNER DECISION 2026-11-15: 'Ignore now, revert later' for the CPV --strict MAJOR '.gitignore missing coverage for reports/'; full verbatim question, answer and costs in TRDD-W5GXPT7T; upstream issue https://github.com/Emasoft/claude-plugins-validation/issues/275. CORRECTS the previous RELEASE PROGRESS item (c): PLUGIN_SKIP_GITHUB_INTEGRITY=1 is set on the CPV and publish.py command line only, never exported (publish.py:1697-1700, TRDD-CWKM5218; memory ATOM-N44N-KU9B, releases 3.7.1 to 3.8.11; the installed CPV 5.16.2 wheel's 152 shipped scripts/ files match the v5.16.2 tag manifest by sha256). With it, --strict on fdc5273d gave CRITICAL 0, MAJOR 1 (reports/), NIT 1 (MD011 in archived TRDD-1T0W2ZVW line 33, added by its closing commit 6f394297; trddgrep refuses edits to archived cards, TRDD-MQE5D28T D8), log reports_dev/release/20261115_085311+0100-cpv-strict-fdc5273d.log. The NIT is handled by design/archived/.markdownlint.json (extends the root config, MD011 off for the archive only), option (b) of TRDD-POWY0X9G: a config scope change for immutable history, not a suppression on live content; markdownlint-cli2 0.23.3 shows MD011 at line 33 on an out-of-tree copy and none under design/archived/; trddgrep validate output byte-identical before and after; the next CPV --strict run is the proof.

## Correction 2026-11-01

Item 1's fleet-wide undo is DROPPED (review finding): other projects' reports/ hold content written under the private regime, so removing the janitor's ignore line there would expose it as untracked and leave a dirty .gitignore in every repo. The detector now only stops requiring reports/ and never edits an existing /reports/ line; removing the old lines elsewhere is the owner's call. Added item 8: the janitor's own generated output (a worker is enumerating which scripts and skills write machine, harness, security or memory state under reports/; the first grep was polluted by pattern files, so no count is claimed) moves to reports_dev/<component>/, or every project would collect untracked private files. Screenshot purge stays retargeted to reports_dev/<component>/screenshots/ because the owner's testing rule says those are auto-purged; the reports age purge is retired because reports/ is tracked and *_dev contents are never deleted. Moving this repo's old reports means card citations of reports/<x>/ now resolve under reports_dev/<x>/.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-01

Release in flight (owner: publish asap and install). Covers this card and TRDD-HM8WOCOO. Workers (lean-worker, background): reports-code (reports_gitignore/detector/gitignore_coverage/reports-purge/screenshot-purge/doctor/dispatch comment/report-to-trdd-drift + tests) STILL RUNNING; auto-clear master switch (clear_trigger, external_clear senders, plugin.json, pre-tool-context-usage, pre-tool-token-budget, post-compact-resume, transcript_roles, user_intent, compact-context + reload-plugins skills) STILL RUNNING; docs + this repo's reports move DONE (reports_dev/lean-worker/20261101_024735+0100-ksuieptq-docs-move.md); janitor writers moved to reports_dev DONE but resumed with follow-ups (reports_dev/lean-worker/20261101_025808+0100-ksuieptq-writers.md). Card corrections staged, NOT committed (pre-commit real-state guard trips while workers edit). NEXT: when all workers report, verify each report, check agents/ still writing reports/janitor-memory-* and report-to-trdd-drift readers, confirm .gitignore has no re-appended janitor /reports/ block (old 3.8.x detector may re-add it), commit by name, run uv run scripts/publish.py --minor in background with LLM_EXT_OUTPUT_DIR pointing at reports_dev, then the user-scope claude plugin update of ai-maestro-janitor from the ai-maestro-plugins marketplace. Four dev cards (JY0OBQZ4, FQVEILVK, S6GX1DHN, F3LVCQ39) stay open; publish proceeds anyway under the owner's asap. OPEN USER DECISIONS: compaction ownership (janitor context_autocompact/cold_cache_compact/PreCompact handoff vs context-harness), the EXTERNAL_IDLE_CLEAR_ENABLED=true line in settings, removing janitor /reports/ lines in other projects, jr-pkg-guard vs janitor pkg guard.
- NEXT ACTION before publish (2026-11-04): (1) move reports/janitor-memory-subconscious-agent/20261104_195953+0100-repair-local.md to reports_dev/ (it is LOCAL-scope; once .gitignore is restored it shows as untracked, and publish.py refuses untracked files); (2) restore .gitignore to HEAD right before publish.py runs, and record the exact command and time; the /reports/ line comes from the installed 3.8.13's scripts/lib/reports_gitignore.py (its comment text is in that file); (3) publish.py stages an explicit file list (publish.py:3008), so a line re-added mid-gate is not committed by the release; whether the run then fails is not traced; (4) after the release commit, diff .gitignore in it; after 3.8.14 installs, check that the line does not come back.
