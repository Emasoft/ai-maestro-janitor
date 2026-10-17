---
trdd-id: 9ORKPQCX
title: Janitor-typed slash commands may mint the owner's consent tokens
column: dev
status: tasked
created: 2026-10-16T22:29:03+0200
updated: 2026-10-17T06:51:02+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-16T22:29:03+0200
---

# Janitor-typed slash commands may mint the owner's consent tokens

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-16

- MEASURED 2026-10-16 (docs_dev/20261016_224414+0200-9ORKPQCX-measure.md, gitignored): every command the janitor types except /janitor-pause mints a token when given to record_intent_from_prompt (/clear gives clear, /janitor-arm arm, /janitor-resume resume, "/reload-plugins --force" reload, /reload-skills reload-skills, /janitor-disarm disarm). The hook does fire on typed plugin slash commands: user-intent-arm.ts and user-intent-resume.ts match the typed /ai-maestro-janitor:janitor-arm and janitor-resume records of session f2f4f95e to the second. Built-in commands (/clear, /reload-plugins) are unknown. The tokens injection_allowed reads are never read today, because all four typers pass respect_user_presence=False; the one live consumer is disarm_guard.authority via fleet_stop's /janitor-disarm (off by default), for the same action, recorded as "user-asked" instead of "global-stop".
- REAL INCIDENT 2026-10-16 22:27:33 local: the installed 3.8.11 hook's _is_cron_marker skips only "[janitor-" lines, so a <task-notification> carrying a worker report that quoted "please disarm the janitor", "global-disarm" and similar phrases minted user-intent-clear, -compact, -disarm, -global-disarm, -reload and -reload-skills tokens in this project's state folder (all stamped 1792182453, the second of that notification record in session f2f4f95e). For INTENT_TTL_S (600 s) a disarm_guard or global_control_cli run here would have read "a human authorized this", including the machine-wide stop. Checked afterwards: no disarmed.flag, no kill-switch.flag, and no disarm or global entry in .janitor/logs for that window. TRDD-W4IZA704 (9b2b1299, unreleased) makes _is_cron_marker skip <task-notification> and [SYSTEM NOTIFICATION, which closes this channel once released.
- NEXT ACTION (2026-10-16): (1) The incident channel closes with the W4IZA704 release; the owner's release decision is pending (see TRDD-0TSG80CL). (2) Then propose, with MEASURE + REVIEW, either a machine-typed breadcrumb (the typer records command and epoch before typing, and record_intent_from_prompt spends it and mints nothing for that command) or documenting the limit and dropping the verbs nobody reads.

Found by the round-2 review of TRDD-0TSG80CL's consent guard (2026-10-16). The janitor's own triggers type commands into the pane: clear_trigger types /clear or /janitor-handoff-and-clear, reload_trigger types /reload-plugins, resume_trigger types /janitor-resume. If the UserPromptSubmit hook sees janitor-typed pane input as an ordinary prompt and a typed command is in user_intent._VERB_COMMANDS, the machine mints a consent token for its own action, the same forged-consent class as the /goal case (TRDD-B3PY3HV7). Unverified: whether the hook sees typed pane input as a prompt, which typed commands match _VERB_COMMANDS, and whether any consumer (disarm_guard.authority, global_control_cli._authorized, terminal_trigger's injection_allowed calls near lines 2357 and 2363) reads a token minted that way before it expires. reload_trigger.py:176 and clear_trigger.py:87 now hold only comments, not injection_allowed calls. First step: measure, read-only, then propose.
2026-10-17 scope: docs_dev/20261017_043703+0200-9ORKPQCX-scope.md (gitignored). TRDD-W4IZA704 (9b2b1299, unreleased) only filters task notifications. Janitor-typed slash commands still stamp presence and mint verb tokens (user_intent.py _VERB_COMMANDS 99-125, `cmd in prompt` 208-209). The only live harm path: fleet_stop's /janitor-disarm (default off) mints `disarm`, so disarm_guard reports user-asked instead of global-stop. The other tokens are minted but have no reader today (all four self typers pass respect_user_presence=False).
Evidence, correlated but not yet discriminated: user-intent-arm.ts 02:21:02 and user-intent-resume.ts 02:21:36 appeared right after the janitor typed /janitor-arm and /janitor-resume post-clear. Other writers have not been ruled out, and the namespaced /ai-maestro-janitor:janitor-arm does not contain the substring /janitor-arm, so a match needs the hook's prompt to be the raw typed text.
NEXT, before any proposal: (1) grep every writer of user-intent- / record_intent in scripts/; (2) ask claude-code-guide what UserPromptSubmit `prompt` carries for a namespaced plugin slash command, and whether it fires for built-in /clear; (3) read disarm_guard.py:55-75 and global_control_cli.py:65-80: does user-asked change an ACTION?; (4) list what on-prompt-submit.py does after line 165, and skip only presence+intent for a machine-typed prompt (not return 0); (5) explain why the existing self-send stamps are not reused (written after the send, double as a 300 s dedupe, and the fleet path writes into another project's state dir); (6) decide the crumb lifetime against wedged panes (tie it to the verified-send outcome, or justify a TTL). Then the proposal, a MEASURE fork and a REVIEW fork. Cross-card: the fix also closes W4IZA704's NOT COVERED presence item. The card stays in todo until the proposal is approved.
DISCRIMINATED 2026-10-17 (docs_dev/20261017_063131+0200-9ORKPQCX-prechecks.md and docs_dev/20261017_063507+0200-9ORKPQCX-measure.md): the only writer of user-intent-<verb>.ts is record_intent_from_prompt (user_intent.py:213), called only from on-prompt-submit.py:165; the hook receives the typed line (Claude Code hooks docs); the clear chain types the short /janitor-arm and /janitor-resume (clear_trigger.py:76-78), which match the substring matcher. So the 02:21 tokens were minted by the janitor's own typing.
CORRECTION: the fleet_stop harm is a LABEL, not an action. fleet_stop types /janitor-disarm only when the kill-switch is set (global_state.py:1093-1101); disarm_guard.authority() (57-71) returns user-asked when a token exists and global-stop otherwise, and main() takes the same action either way. No fleet_stop code change is needed.
DESIGN (proposal, review, measure and advisor): one crumb per logical send, a file machine-typed/<uuid>.json holding the text and an epoch, rewritten before each type attempt. It is written (a) inside terminal_trigger.inject_until_sent right before type_fn(), with state_dir a REQUIRED parameter threaded from send_verified, run_verified_send and run_chained_inject, and (b) in pane_actuate._type before fire(), via target_state_dir(project_dir) and plan['command'] (the fleet iTerm path bypasses _run_steps). The hook calls spend_machine_typed after the state import and before bump_user_presence, and skips only presence and intent (no early return). TTL is a 2 h module constant, each crumb is consumed once, and a spend prunes expired files. Normalization: the first line, stripped, with any <pasted_content> wrapper removed. NEXT: dispatch the build worker (one commit; no sed or redirects; fastedit only).
UNKNOWNS AND NOTES: it is unknown whether UserPromptSubmit fires at enqueue or at dequeue for a soft-sent command, and whether it fires for built-ins (/clear, /reload-plugins); the design is correct either way. Mixed-version fleet: crumbs written into projects whose sessions still run the old hook expire unspent. Security: anything that can write the state dir can already forge consent through user-intent-*.ts; a crumb only adds a one-shot denial, so machine-typed/ is not a security boundary.

## Approval log

- 2026-10-16T22:29:03+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
