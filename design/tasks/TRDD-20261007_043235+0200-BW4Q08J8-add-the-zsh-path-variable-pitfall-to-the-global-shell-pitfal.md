---
trdd-id: BW4Q08J8
title: Add the zsh path variable pitfall to the global shell-pitfalls rule
column: human_review
status: tasked
created: 2026-10-07T04:32:35+0200
updated: 2026-10-07T04:32:43+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: docs
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-07T04:32:35+0200
---

# Add the zsh path variable pitfall to the global shell-pitfalls rule

## Problem
In zsh the lowercase variable `path` is an array tied to `PATH`. A one-liner that used `path` as a loop variable overwrote PATH and the next command failed. Where it bit: a session on 2026-10-07 used `path` as a loop variable in zsh, which overwrote PATH, and a second try produced no files. The handoff of that session asked that the lesson belong in the global shell-pitfalls rule.

## Demonstration (zsh -c in a subshell, harmless, run 2026-10-07)
- `zsh -c 'for path in a b; do :; done; echo "PATH=$PATH"; command -v ls || echo NOT FOUND'` printed `PATH=b` then NOT FOUND (exit 1).
- Control, same loop with `p`: `command -v ls` printed the real path.
- Control in bash with `path` as the loop variable: `command -v ls` printed the real path (bash has no such tie).
- `zsh -c 'path=/nowhere; echo "PATH=$PATH"; command -v ls || echo NOT FOUND'` printed `PATH=/nowhere` then NOT FOUND.
- `zsh -c 'echo ${(t)path}'` printed `array-tied-special`.
The same loop with another name works and bash with the same name works, so the cause is the name, not the loop.

## Draft paragraph for the user global shell-pitfalls rule file
Placement: a new section after "Counting or listing files with a glob" and before "Absolute paths only, never cd". Heading and text:

    ## Never name a zsh variable path

    In zsh the lowercase variable path is an array tied to PATH: assigning path, or using it as a loop variable, rewrites PATH itself, and the next command lookup fails (ls, grep and git all report "command not found"). The same holds for fpath, cdpath, manpath and module_path. The Bash tool shell is zsh, so this bites in an ordinary one-liner, and the failure looks like a missing tool, not a bad variable name. Name loop variables for what they hold (file, card_file, target), never path:

        for path in a b; do :; done; command -v ls   # WRONG - PATH is now "b", ls is not found
        for target in a b; do :; done; command -v ls # RIGHT

The target is the owner global rule file outside this repo: the owner approves and the change is applied there. Unverified: the tie was demonstrated for path only, not for fpath, cdpath, manpath, module_path.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-10-07
2026-10-07: waiting for the owner to approve the paragraph; it is applied to the global rule file, outside this repo. NEXT ACTION: owner decision.

## Approval log

- 2026-10-07T04:32:35+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-07T04:32:43+0200 — column → human_review by main-agent@ai-maestro-janitor. the target is the owner global rule file; the owner approves the paragraph
