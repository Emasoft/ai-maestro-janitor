---
trdd-id: L1I0FP5T
title: Shield and report-sanitizer share one rule core and never mask a path except the home prefix
column: dev
status: tasked
created: 2026-11-16T19:10:40+0100
updated: 2026-11-16T19:58:28+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-16T19:10:40+0100
---

# Shield and report-sanitizer share one rule core and never mask a path except the home prefix

Owner 2026-11-16 (verbatim): they most cover the same set of secrets types.
Owner 2026-11-16 (verbatim): both must detect and redact all 62 types of secrets
Owner 2026-11-16 (verbatim): then change both to never mask file paths. the only path at risk is the home dir with the user name. simply replace all user paths prefixes with the prefix ~/ and you have not lost any information.
Owner 2026-11-16 (verbatim): do the same for windows users (is there a shorthand for it too i think, verify)

Windows home prefix: %USERPROFILE%. Reverses report-sanitizer TRDD-ZADXHV6W design point 2 (path and identity rules stay in Python). Related: TRDD-NRF7OJ5H, TRDD-QM8YRCZ5. The owner ordered this rule (quotes above); only the decisions under "Pending owner decisions" are open.

## Approval log

- 2026-11-16T19:10:40+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-16T19:52:56+0100 main-agent: owner asked "what are you waiting for?"; proceeding on the recommended defaults: (e) card rule on in report-sanitizer; (a) and the live half of (e) wait for mod wiring, the home rule gets a caller-side switch.
- 2026-11-16T19:58:23+0100 — column → dev by main-agent@ai-maestro-janitor.
- 2026-11-16T19:58:28+0100 main-agent: step 1 done: ssh-public-key rule in the shield core (no leading word boundary, so a key after an escape is hidden; it also hides xssh-rsa AAAA..., which hides more, never less). cookie as a secret name is deferred: adding it broke 11 pinned tests because the assignment pass swallows the gitlab-session-cookie kind; it needs a cookie-aware assignment pass and a false-match measurement first.

## Design

- Remove from report-sanitizer sanitize_reports.py: the project-root mask to $CLAUDE_PROJECT_DIR (lines 258-260), the plugin root and data masks (262-266), the project folder-name mask (268-269), TMP_VAR to $TMPDIR (67, 276), TMP_CLAUDE, the claude temp-folder mask (68, 277), VOLUME, the volume-name mask (70, 279).
- Keep and move into the shared core: USER_PATH (69, 278) and the home literal (272-274), both to the tilde prefix; SLUG_OTHER (66, 271), which turns a Users-<name> project folder name into Users-USER; the Windows home becomes %USERPROFILE% with the original separator kept.
- Count: the earlier 62 was 45 shield kinds plus 17 sanitizer rules; 3 rules repeat a type, so 59 distinct types; removing the 5 path types leaves 54 types, all in the shared core, detected and redacted by both tools.
- Secret gaps to close in the core: cookie values; a bare Bearer token holding a digit; lower gh_ and hf_ minimum lengths; SSH public key blobs; payment cards; the email rule keeps git-over-SSH clone addresses readable; account name and hostname passed in by the caller.
- Card rule, measured 2026-11-16 on 50,487 text files: no match after a decimal point; separators count only in real card groupings (4-4-4-4, 4-6-5, 4-6-4, 4-4-4-4-3) at every length; a bare run over 16 digits needs a card word. On the recorded hit shapes these remove all 190 false matches (180 hashes, 8 decimal fractions, 2 process-listing columns) and keep the 50 fixture hits. Cost: a real 17-19 digit card written as one bare run with no card word, or with a non-standard grouping, is not hidden. Not yet re-run as code.
- One source per rule within the shield core and report-sanitizer; the janitor Python files secret_names.py and privacy_patterns.py stay separate until TRDD-NRF7OJ5H scope 4. Parity test: one fixture set, built from fragments, run in both repos with byte-identical output.

## Pending owner decisions

- (a) Apply the home rewrite in the live mod, as ordered for both tools (tool results and stored rows both return to context, so a tilde path can be written back into a file), or keep it off for the live mod, which departs from the order.
- (e) Card rule default: on in report-sanitizer with the three changes above; off in the live mod until a re-measurement on tool-output-like text shows zero false matches.

## Acceptance checklist

- [ ] report-sanitizer rewrites no path except the home prefix, with tests
- [ ] the secret gaps and the card rule changes are in the shield core, each with a KNOWN-MISSES entry, and the 800-test floor holds
- [ ] report-sanitizer is re-pinned to the new core and both tools give byte-identical output on one shared fixture set covering all 54 types
