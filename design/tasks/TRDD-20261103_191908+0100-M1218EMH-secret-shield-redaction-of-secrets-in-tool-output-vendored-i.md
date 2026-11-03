---
trdd-id: M1218EMH
title: secret-shield redaction of secrets in tool output, vendored into the janitor
column: dev
status: tasked
created: 2026-11-03T19:19:08+0100
updated: 2026-11-03T19:33:07+0100
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
approval-datetime: 2026-11-03T19:19:08+0100
---

# secret-shield redaction of secrets in tool output, vendored into the janitor

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-03

User request, verbatim (2026-11-03): "integrate this mod into the janitor: https://github.com/Singh-AP/awesome-claude-mods/tree/main/mods/safety/secret-shield" and "replace the message placeholder with [JANITOR-REDACTED:<type>]".

Decisions taken by the main agent while the owner was away (the AskUserQuestion prompt timed out after 300 s; the owner may overrule any of them): placement INSIDE the janitor (hooks/hooks.json gains "modules" beside the existing "hooks"); OFF by default (secret_shield_enabled=false); NO release from this card without the owner's explicit go-ahead. The auto_clear fix (commit 64768ab7, TRDD-HM8WOCOO) is a separate release decision and is still open.

Source: Singh-AP/awesome-claude-mods, folder mods/safety/secret-shield, version 1.0.0, MIT licence (repository-root LICENSE; the mod folder has none), last commit touching the folder 5bbf314ee1a8d3c5e519f4c28f070c308bd89da2 (2026-10-04). Pure TypeScript on the mods API: a tool.call hook rewrites every tool result, a session.append hook scrubs stored rows and withholds a row's text if scanning throws, a command.run hook serves /secret-shield, and $.store keeps all-time counts. Not installed on this machine, so there is no double redaction or command collision.

Measured 2026-11-03: claude plugin test on the upstream copy: 96 pass, 0 fail. A copy whose hooks/hooks.json holds both "modules" and a classic "hooks" PostToolUse entry: also 96/0, and claude plugin validate passes. trufflehog 3.97.9: 0 findings on the upstream files (its tests already build fake tokens with a join helper, the same convention as the janitor's tests/_fake_secrets.py). The janitor's GitHub CI installs no claude, node or bun, so the TypeScript tests can run only in the local publish gate.

UNVERIFIED: what Claude Code older than 2.1.287 does with a "modules" key (risk: the whole hooks.json fails to load, taking every janitor hook with it); the order of the mod's tool.call result rewrite against the janitor's PostToolUse updatedToolOutput (post-mcp-response-sanitizer.py builds its output from the raw payload and could put a redacted value back); whether CLAUDE_PLUGIN_OPTION_* keys in the settings.json env block reach a mod's options argument.

Plan (one bounded increment per commit, each done by a worker and verified before the next):
1. Copy register.ts, patterns.ts, rows.ts and both test files into hooks/secret-shield/, plus the upstream LICENSE and a NOTICE naming commit 5bbf314e. Do NOT wire hooks/hooks.json yet.
2. Placeholder: patterns.ts mark() returns [JANITOR-REDACTED:${kind}], and the MARK regex at patterns.ts:15 matches the new form; update the 27 test expectations; ADD one test asserting the exact literal [JANITOR-REDACTED:github-token] and one asserting that no output contains "[REDACTED:".
3. Options: plugin.json userConfig secret_shield_enabled (default false; false means register() registers nothing), secret_shield_block_files (default false), secret_shield_redact_prompts (default false); tests for the off path; verify which of userConfig and the settings.json env block reaches options.
4. Wire hooks/hooks.json "modules": ["./secret-shield/register.ts"] LAST, then a live probe with the mods probe tool (never claude -p on this account): Read a file holding a fake token, confirm the model sees the placeholder and the session .jsonl holds no raw copy; confirm a Read followed by an Edit near a redacted line fails loudly instead of silently corrupting the file.
5. Release gate: a separate card for a fail-closed claude plugin test step in publish.py.
6. A README section and an update to the project memory page.

Known risk (adversarial review, 2026-11-03): while it is on, Read shows the placeholder, and a later Write or Edit that restates that line can write the placeholder over the real value. This repository's own scripts/lib/*_patterns.py files and tests hold fake tokens on purpose. That is why the default is off.

NEXT ACTION: step 1.

## Approval log

- 2026-11-03T19:19:08+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Implementation notes

2026-11-03 step 1 vendored files: register.ts and rows.ts are byte-identical to upstream (git hash-object equals the upstream tree blob sha for all 8 upstream files). patterns.ts differs only at line 79, a doc comment reworded so the janitor privacy scan stops flagging an ssh-user-host example. Test files: imports ../hooks/patterns and ../hooks/rows became ../patterns and ../rows; the internal fixture hostname became db.acme.io and the fake home-directory user name became User (the privacy scan refuses hostnames and home paths in committed files). claude plugin test: 96 pass, 0 fail. trufflehog: 0 findings.
2026-11-03 reproducible transform for a future upstream sync (apply to the upstream test files): the sed command saved in reports_dev/secret-shield/upstream-sync.sed.txt (gitignored, since the privacy scan refuses the literal fixture values): fix the two import paths, set the internal hostname to db.acme.io, set the fake home user name to User. Then verify by bytes (cmp, grep -c), never by eye.
2026-11-03 FINDING: the enabled mod jr-redact (claude-code-mods marketplace) 0.1.0 already redacts tool output in this session. Its connection-string rule (hooks/redact.ts:16) captures any text between user: and @ and replaces it with a password marker, so it rewrote an upstream test expectation as displayed; a worker retyped the displayed text and broke 1 test. Consequences: (a) any edit of marker text must be a byte-level scripted transform verified with cmp and grep -c, a deliberate exception to the no-scripted-edit rule; (b) step 2 must decide what MARK recognises and test that both marker forms are left untouched; (c) the step 4 live probe must assert on the session .jsonl bytes and account for jr-redact; (d) the owner should decide whether secret-shield is still wanted alongside jr-redact.
