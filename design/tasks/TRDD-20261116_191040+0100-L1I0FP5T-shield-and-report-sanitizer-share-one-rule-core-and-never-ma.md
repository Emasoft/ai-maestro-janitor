---
trdd-id: L1I0FP5T
title: Shield and report-sanitizer share one rule core and never mask a path except the home prefix
column: dev
status: tasked
created: 2026-11-16T19:10:40+0100
updated: 2026-11-16T23:33:28+0100
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-16

Done: steps 1 and 2 (shield core), report-sanitizer home-prefix-only (8039916), --project-root removed (8d7b2a6), janitor caller fixed (c611d3e7), and the re-pin (report-sanitizer commit 953ec92 pins its vendored core to janitor 49a9d171; home.ts and its test join the vendored file list; sanitize_reports.py LEGACY_KINDS now names every core kind: ssh-public-key maps to the ssh label and counter, every other kind to [REDACTED TOKEN]/token, the label they already got through the fallback). Nothing calls redactHome yet. NEXT ACTION: route the home prefix through redactHome in report-sanitizer (B2 commit 2), then the shared fixture parity run (checklist items 3 and 4 stay open). Behaviour changes of the re-pin, found by the old-against-new comparison (old 8d7b2a6, sampled corpora; no case where the new output hides less; evidence in private reports_dev/shield-parity: repin-diff and differ-trace of 20261116): (1) an SSH key keeps its type visible, ssh-rsa [REDACTED SSH KEY] where it was [REDACTED SSH KEY]; (2) a JWT after Bearer whose second segment does not start with eyJ is labelled [REDACTED], not [REDACTED TOKEN], because bearerBare runs before the last-pass jwtWide; (3) a value found by bearerBare is hidden at every other place it appears in the same text (core found-value propagation); (4) bearerBare (hooks/secret-shield/rules/key-material.ts:56), like the old Python BEARER, uses \s+, which crosses a line break, so a path or identifier at the start of the line after a line ending in Bearer is masked: an inherited false positive, fix pending a measurement of newline-crossing matches; (5) a ghp_ value with a 20-character body after api_key = is now [REDACTED TOKEN] (github-token, floor 30 lowered to 20) where it was [REDACTED] (assignment). Test note: report-sanitizer core/tests/patterns.test.ts (801 tests, the vendored copy) failed timing assertions in 2 of 4 runs, both under a 1-minute load average of 60 to 72 on 14 CPUs, and passed on a quiet-host rerun: load sensitivity, not settled by repetition.

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
- 2026-11-16T21:13:51+0100 main-agent: step 2 done, shield floors widened to the report-sanitizer floors (owner order: same secret types in both tools): GitHub classic body 30 to 20, Hugging Face 34 to 30 with no trailing word boundary, and a new bare Bearer rule (8+ characters holding a digit, any case, no leading word boundary so a token after an escape is hidden, TRDD-5VZTPXBJ). Candidates of the new floors, counted before the change in 95,006 plugin-cache and 4,891,492 code-tree files: GitHub 14 / 293, Hugging Face 0 / 2, bare Bearer 27 / 208, short Authorization values 15 / 1,043, other Bearer forms 0 / 137; mostly placeholders and test tokens, judged by file location and masked shape (94 of 208 bare and 87 of 137 other-form hits look random). Differential through redact(), HEAD against the new core on the plugin cache: 0 spans no longer hidden, 0 kind changes, 56 new spans plus 25 repeats; shield gate 1001 pass. Accepted over-hide: placeholders in docs and tests, a value after a word ending in bearer, a sentence-final period after a Bearer value; a short-segment JWT after Bearer is now labelled bearer-token. Cost once the shield is wired: an agent can write a marker over a test token; TRDD-0Y3UW1NF (write-back guard) blocks the wiring card TRDD-2V7OAUPE, so the guard lands first.
- 2026-11-16T21:53:59+0100 main-agent: report-sanitizer now masks only the home prefix (8039916); the janitor caller stopped passing --project-root (c611d3e7). A local measurement (not in git) of the current home rule found these misses: about 12,600 Windows backslash paths and about 4,200 paths after a literal backslash-n or backslash-t in the code tree, Git Bash and WSL drive paths, and about 1,000 C:/Users/<name> paths rewritten to C:~. Its false-rewrite counts come from an unvalidated context heuristic and are not a rate. The core home rule (next step) handles the drive forms, the escape boundary and the C:~ mangling.
- 2026-11-16T22:12:14+0100 main-agent: plan change: the --project-root flag was first kept for cached janitor 3.9.x copies (58668bf); a hook scan then showed no hook runs them, so the flag is removed now (8d7b2a6) instead of after a release.
- 2026-11-16T23:33:10+0100 main-agent: re-pin done: report-sanitizer 953ec92 pins its vendored core to janitor 49a9d171 (home.ts and its test added, LEGACY_KINDS names every core kind); old-against-new comparison found five behaviour changes and no case that hides less (listed in the STATE block); nothing calls redactHome yet, next is B2 commit 2; report-sanitizer patterns.test.ts failed timing assertions in 2 of 4 runs under a load average of 60 to 72 and passed on a quiet host.

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

- [x] report-sanitizer rewrites no path except the home prefix, with tests (evidence: report-sanitizer commit 8039916 removes every path mask except the home prefix and the -Users-<name>- slug; its tests pin that project-root, plugin-cache, /Volumes, temp and uid paths stay as written; janitor commit c611d3e7 stops passing --project-root)
- [x] report-sanitizer has no --project-root flag (evidence: report-sanitizer commit 8d7b2a6 removes it from the code, README and spec, and a test pins exit 2; a bounded scan (pre-commit and pre-push files of every hook folder up to depth 5 in the code tree, skipping _dev, worktree, node_modules and .venv folders, plus the global git hooks folder) found only the janitor's own pre-commit calling sanitize-reports, which stopped passing the flag in c611d3e7; cached janitor copies contain the old call but no hook runs them)
- [ ] the secret gaps and the card rule changes are in the shield core, each with a KNOWN-MISSES entry, and the 800-test floor holds
- [ ] report-sanitizer is re-pinned to the new core and both tools give byte-identical output on one shared fixture set covering all 54 types
- [x] the path-floor CPV check ran on the pinned CPV v5.16.2 against a sample plugin, with PLUGIN_SKIP_GITHUB_INTEGRITY=1 (the variable the standing publish command exports and publish.py lets through): tilde, /Volumes/ and /private/tmp/ paths are not flagged in reports/ or design/, and a path holding the current account name under the macOS Users folder is CRITICAL there; whether an ancestor .gitignore changes this was not tested (evidence: a local report, path-floor-check of 2026-11-16, not in git: this repo still ignores reports/, issue 348)
