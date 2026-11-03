---
trdd-id: 0Y3UW1NF
title: Secret-shield write-back guard
column: design
status: tasked
created: 2026-11-03T22:42:37+0100
updated: 2026-11-04T00:00:04+0100
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
approval-datetime: 2026-11-03T22:42:37+0100
---

# Secret-shield write-back guard

## Problem
With secret-shield on, Read shows a secret as a [JANITOR-REDACTED:<kind>] marker. A later Write, Edit, MultiEdit or NotebookEdit that restates that line, or an agent write through Bash (a heredoc, fastedit, a redirect), writes the marker over the real secret. The mod must not be wired into hooks/hooks.json before this guard exists.
## Candidate design
- Deny a Write, Edit, MultiEdit or NotebookEdit whose new content holds more janitor markers than the current file does (count rule), using the full marker pattern built from MARK_BODY in hooks/secret-shield/patterns.ts.
- Deny a Bash command whose text holds a janitor marker.
- A gate check that fails when a tracked file gains a line with a janitor marker (git diff).
- The deny message tells Claude to ask the user for the real value or leave the line untouched.
Count per tool, not per file: Write compares the new content against the current file; Edit and MultiEdit compare old_string against new_string in each hunk; NotebookEdit compares per cell. A whole-file count would let a marker into one hunk while another is removed.
Files that legitimately hold markers (the secret-shield tests): a hunk that adds no marker passes; a new test that needs a marker builds it by concatenation, as the existing tests do. No path allowlist.
Bash: deny a command holding a full marker, and say in the deny message to search for JANITOR-REDACTED without the brackets. Writing tool output to disk is not a gap: redaction only changes what Claude sees.
The git-diff check: decide whether it guards only this repository or runs as a janitor pre-commit check in every project. The second changes every project, so the owner decides.
This guard denies writes in every project, so the owner sees the design before the card reaches dev.
## Done when
Tests show each tool path is denied when it would write a marker and allowed otherwise, including a file that legitimately already holds a marker.
Found during TRDD-M1218EMH.

## Approval log

- 2026-11-03T22:42:37+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Design, revised 2026-11-03 after review and measurement (supersedes Candidate design)

- Threat model: Claude accidentally restating a marker it saw through redaction. Deliberate reconstruction (concatenation, python -c, base64) is out of scope.
- Where: hooks/secret-shield/register.ts, a tool.call handler registered BEFORE the secret_shield_enabled === false return, so the guard runs whenever the module loads; markers already in a session outlive the option. It uses MARK_BODY from patterns.ts, the one source of the marker grammar.
- Rule, flat, no counting and no file read: deny before next(e) when a full marker appears in Edit old_string or new_string, Write content, NotebookEdit new_source (edit_mode delete is allowed), or Bash command. A full marker is what MARK_BODY matches; the placeholder written with <kind> in angle brackets does not match, so docs and cards use that form.
- Prerequisite, same change: replace the literal markers in hooks/secret-shield/tests/patterns.test.ts (22) and shield.test.ts (5) with mark(kind) from patterns.ts or concatenation, and reword the one literal marker on TRDD-M1218EMH to the placeholder form. Then no tracked file holds a literal marker, so the flat rule blocks no legitimate edit.
- Deny message, under the 4096-character limit: "secret-shield: this text holds a marker that stands for a hidden secret; the real file holds the secret, not the marker. Ask the user for the value or leave that line unchanged. To search for markers, use JANITOR-REDACTED without the brackets."
- Tripwire: a pytest in tests/ that fails when any tracked file holds a full literal marker (git grep with the pattern split so the test holds none). No allowlist. An every-project pre-commit version is a separate owner decision, not part of this card.
- Tests (claude plugin test, shield.test.ts): each tool path denied when its payload holds a marker and allowed when not; NotebookEdit delete allowed; the guard active with secret_shield_enabled false; a mutation check per rule. Count with match or matchAll, never .test on the global MARKS regex; a non-string or absent field counts as empty.
- Dropped: MultiEdit (not a native tool: absent from the mods tool type definitions); the count rule and $.fs.read (not needed once the literals are gone); the prior-corruption message (not computable).
- Open, to measure before dev or in TRDD-TEP6F3A3: E, whether mod tool.call hooks fire for subagent and Workflow tool calls (if redaction reaches them but the guard does not, the guard has a gap); F, whether any janitor Python hook rewrites tool output with a placeholder of another shape.
