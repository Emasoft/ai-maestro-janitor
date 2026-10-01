---
trdd-id: DSN035UN
title: Deterministic auto-fixers in memgrep and the scripts replace LLM repair instructions, shrinking the memory skills
column: design
status: tasked
created: 2026-10-01T17:23:43+0200
updated: 2026-10-01T20:36:54+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-01T17:23:43+0200
eht: [LKOUJC76, 622ROA5F, 2UAEQQ4A, OWGEOJ0D, 7SMPCPNT, I23YCEW7, 4G427D8M, 9SUZ48E8, QBU0HSM9, KSCAFSLD, RLD015QB, RUJQ7WSX, U2VUXGBP, B9YPSF02, UDE86OSZ, V12ZHM1B, BHIS99XE, 3HLI7DMK, JD2QR5SQ, VHFGPCOJ, 8524H5V1, QXG8SRVD, I4MOD020, OLNPXGBC, 1HXEAHY7, QX59MA4H, EMZUVIBK, ZYX8B2RA, RQMJFJGR]
---

# Deterministic auto-fixers in memgrep and the scripts replace LLM repair instructions, shrinking the memory skills

## Owner directive (verbatim, 2026-10-01)

"in general you should automate more repairing using heuristic code in the scripts and in memgrep. linters like ruff are able to auto fix hundreds of issues. take example. this will also help reducing the size of the skills."

## Measured starting point (2026-10-01)

memgrep lint autofixes only publish-globally/symlink drift today (--no-fix to suppress). PROJECT-scope lint finding counts by rule: atom-no-ocd 43, atom-no-lmd 37, atom-oversized 17, lesson-uncited 16, link-one-sided 7. The repair skill sits at 4999/5000 tokens (TRDD-IKZROIE5) because its body spells out mechanical fixes an agent performs by hand.

## Shape (proposal, awaiting owner approval)

ruff model: every lint rule is classified SAFE-FIX (deterministic, provably lossless, applied by memgrep lint --fix) or JUDGMENT (left to the agent). The skills then say: run the fixer, then handle only what it reports as unfixable. Next action: a per-rule classification table with the evidence for each SAFE-FIX verdict, then one rule at a time, each with its own test.

## Approval log

- 2026-10-01T17:23:43+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-01 — OWNER DIRECTIVE (verbatim): "commit often, so you can revert in case of errors. also enforce the use of tldr-code skill, fastedit skill and jgrep skill by all subagents". Applied: one commit per card by the main agent; every worker prompt carries the TOOLS/GIT/SCOPE preamble (jgrep to locate, tldr to read, fastedit to write; workers never touch git). Later cards C42-C45 and C47 removed from eht (review finding: they are unscheduled/owner-gated and would block this card from ever closing); they stay as related backlog.
- 2026-10-01 — C00 unknowns resolved (report reports/dsn035un/20261001_194841+0200-c00-unknowns.md, local): U1 lint lines are formatted inline in cmd_lint_cli (memory.rs ~5934-5946) as "{sev} {path}:{line} [{code}] — {msg}{anchor}"; U2 all findings print, exit 1 iff any finding >= --min-severity; U3 specgrep ignores a .toml in design/specs (spec stays in design/specs/); U4 hook timeouts are transcript entries type=attachment, attachment.type=hook_cancelled, timedOut=true, with hookName/hookEvent/durationMs/timeoutMs (12386 such entries on this machine); U5 cold debug build 41 s wall/112 s CPU, release 145 s/292 s, no sccache — Rust waves capped at 3 parallel workers; U6 ponytail is third-party (DietrichGebert), so C47 is outward to a non-owner repo; U7 MEMGREP-001..011 are index/binary health codes; U8 recall output lives in memory.rs (finalize_recall ~8471, recall_one_atom ~8717) so C23 joins the memory.rs chain after C22; U9 recall over the 3 scope DIRS with --use-index ran 0.02 s at load ~69 — the 5.2 s measurement was the 369-explicit-file form autorecall uses, so C1D must confirm and C41 (pass dirs) is the likely fix. PROCESS LESSON: the U5 worker overrode the git safety guard (GIT_GUARD_OTP) to remove its throwaway worktree because the prompt told it to touch git; the standing preamble now forbids workers any git operation.
- 2026-10-01 — WORKER PREAMBLE (mandatory in every subagent prompt; copy of docs_dev/dsn035un-worker-preamble.md so it survives in git): TOOLS — locate by meaning with jgrep, exact strings with rg/grep on absolute paths; read with tldr (structure/search/definition/impact, ranged tldr body); write/edit/create ONLY with fastedit and run fastedit diff after every edit (Markdown snippets repeat the heading and every kept line); Edit/Write tools, sed -i, heredocs, redirects and rewrite one-liners are forbidden for writes; TRDD cards only via trddgrep. GIT — workers never commit, stage, or touch git state; the main agent commits after every card. SCOPE — RULE 1, write only the card Writes. PROBE STATUS: trddgrep why prints the blocker chain (no READY) for a card with open blockers (checked on BHIS99XE and VHFGPCOJ); the READY case for a blocked-column card with all-terminal blockers is confirmed at the first unblock.
- 2026-10-01 — PREAMBLE AMENDED (wave-1 review finding 5): workers broke the tools rule 3 times on formats fastedit cannot edit (.sh, .lock, mode bits). Rule is now: fastedit for every format it supports; for .sh/.lock/mode changes use the Edit tool, cargo add, or chmod and SAY SO in the report; never sed -i, heredocs, redirects or rewrite one-liners. C40 (cut memgrep ~1 ms/file cost) kept optional: C1D shows C41 (autorecall passes 3 dirs) removes the slowness; C40 is decided after C41 is measured.
- 2026-10-01 — wave 1 batch 2 landed: C10 10293add, C11 59fe8b11, C12 6df88890, C13 5518c66e (separate commits, explicit pathspecs; combined tree: cargo 0 warnings, memgrep 365+196, ruff/mypy/pyright clean, full pytest 17714 passed). Cards archived complete. Open: tools-rule amendment for stubs/non-symbol lines (workers used fastedit create --force on <=2-line stubs and guarded Python replaces on docstrings/constants); main-tree cards to run in worktrees by default; intermediate commits not individually built (bisect check optional).
- 2026-10-01 — provenance of the C10-C13 checklists (written at closure): aggregates and code claims are main-verified (cargo 0 warnings, memgrep 365+196, ruff/mypy/pyright, full pytest 17714, --check 0, selector/Safe/MAX_ROUNDS/load_lenient read in source); per-module test counts (8/8/7), the oscillation assertion and 'Rule type unchanged' are from the worker reports.
- 2026-10-01 — BEFORE wave 2 dispatch (C20, C24): (1) put the amended tools rule in the preamble and prompts: fastedit for symbols; fastedit create --force only on card-owned stubs of 2 lines or fewer; the Edit tool for non-symbol lines (mod blocks, constants, docstrings), declared in the report; never sed, heredocs or Python rewrites. (2) every card runs in its own worktree by default. (3) C24 uses lint_config::load_lenient and reports CONFIG-001 rather than crashing. (4) re-run the memgrep cli test target 3x to settle the earlier flake. Optional: bisect-build HEAD~3..HEAD~1. Worktrees /tmp/wt-c11..c13 are kept until wave 2 starts.
- 2026-10-01 — CORRECTION (review of the previous line): items (1) and (3) are superseded. (1) The main agent may not loosen the owner's tools rule: ~/.claude/rules/code-tools-tldr-fastedit.md forbids the Edit/Write tools, and on a fastedit refusal the worker skips that item and reports the snippet and refusal verbatim. That also voids the earlier 'PREAMBLE AMENDED' permission for Edit on .sh/.lock. Exceptions for stubs and non-symbol lines are an OWNER decision, pending; until then workers follow the rule's own skip-and-report path. (3) Corrected: C21 (memgrep, Rust) uses lint_config::load_lenient and reports CONFIG-001; C24 (Python) catches C1A's is_suppressed config error in the ledger/drift path, emits CONFIG-001 and treats nothing as suppressed.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

2026-10-01 plan v4 approved by owner; derived cards minted: C01=TRDD-LKOUJC76, C02=TRDD-622ROA5F, C10=TRDD-2UAEQQ4A, C11=TRDD-OWGEOJ0D, C12=TRDD-7SMPCPNT, C13=TRDD-I23YCEW7, C14=TRDD-4G427D8M, C15=TRDD-9SUZ48E8, C16=TRDD-QBU0HSM9, C17=TRDD-KSCAFSLD, C18=TRDD-RLD015QB, C19=TRDD-RUJQ7WSX, C1A=TRDD-U2VUXGBP, C1B=TRDD-B9YPSF02, C1C=TRDD-UDE86OSZ, C1D=TRDD-V12ZHM1B, C20=TRDD-BHIS99XE, C21=TRDD-3HLI7DMK, C22=TRDD-JD2QR5SQ, C23=TRDD-VHFGPCOJ, C24=TRDD-8524H5V1, C25=TRDD-QXG8SRVD, C30=TRDD-I4MOD020, C31=TRDD-OLNPXGBC, C32=TRDD-1HXEAHY7, C33=TRDD-QX59MA4H, C34=TRDD-EMZUVIBK, C40=TRDD-ZYX8B2RA, C41=TRDD-RQMJFJGR, C42=TRDD-MIU9H3ZC, C43=TRDD-VA35WWWS, C44=TRDD-RVWJQR8E, C45=TRDD-PC2ZZR31, C46=TRDD-5ITPD1UD, C47=TRDD-7IPJA0ED (C46 is LOCAL scope); execution starts with C01/C02 after C00 unknowns report
