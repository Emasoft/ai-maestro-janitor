---
trdd-id: 6FB7PKU2
title: Clear the open publish-gate findings before the next janitor release
column: proposal
status: proposed
created: 2026-11-05T00:23:08+0100
updated: 2026-11-05T02:02:21+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: infra
min-approval-requirement: user
scope: project
project-id: ai-maestro-janitor
approved: false
relevant-rules: [5.1]
---

# Clear the open publish-gate findings before the next janitor release

## Release blockers

State as of 2026-11-05; the facts tied to a commit were measured at 0ff8f2e5. Done when every box below is ticked. PRRD S5.1 applies: a CPV finding is cleared by devitalizing or removing the offending code, never by exempting a rule or relaxing --strict.

- [ ] Four cards hold absolute paths, found in design/tasks; design/proposals and design/archived not scanned. Genericize them. Each card has exactly one hit (count of lines holding a macOS home-directory or volume prefix). origin/main is as of the last fetch (its last commit is 3b81287f of 2026-10-23, 279 commits behind HEAD), so "pushed" below means "present in that ref". A pushed path is not un-leaked by a redaction. A card in a terminal column is frozen, so its redaction needs an owner ruling.
  - TRDD-M5BRPISQ: column backburner; not in origin/main (count not available, the file is absent there); the hit is a local absolute path.
  - TRDD-ZNN0UK5K: column complete (terminal, frozen); in origin/main, count 1; the hit is a system volume name.
  - TRDD-5CGPEK4V: column blocked; in origin/main, count 1; the hit is a local absolute path inside this project.
  - TRDD-ZIKYQQY0: column todo; in origin/main, count 1; the hit is a system swap-file volume path.
- [ ] CPV, run exactly as publish.py runs it, exits 0. publish.py does not set PLUGIN_SKIP_GITHUB_INTEGRITY: it only exempts that variable, and CPV_SKIP_GH_AUTH_CHECK, from its refusal of skip variables (scripts/publish.py:1625-1643; the other hits are the docstring and line 18), so the variable must come from the caller's environment. Worker-measured on 2026-11-04 on the 317d6a9e tree: exit 2. First: an integrity-manifest mismatch in CPV's own cache. With PLUGIN_SKIP_GITHUB_INTEGRITY=1: 0 CRITICAL, 2 MAJOR (patterns.ts:453 CREDENTIAL_DISCOVERY; an absolute path in a design card), 3 MINOR, 1 NIT, 42 WARNING. Take a baseline at HEAD first. Find out whether --strict fails on warnings. Clear the mismatch in CPV's regenerable cache (find where it lives before clearing anything). Setting PLUGIN_SKIP_GITHUB_INTEGRITY=1 in the caller's environment would instead turn off CPV's own cache-integrity check. That is not a plugin finding under S5.1, but it is a bypass, so use it only with the owner's yes.
- [ ] trufflehog reports one SQLServer finding at hooks/secret-shield/tests/patterns.test.ts:942, marked unverified (Verified=false, checked 2026-11-05). It was present before 317d6a9e and that line is unchanged since. Check it against the publish gate's trufflehog scope.
- [ ] The working tree carries an uncommitted .gitignore change, and publish.py step 1 refuses a dirty tree. Its git diff holds no local path (checked 2026-11-05):

      diff --git a/.gitignore b/.gitignore
      @@ -111,3 +111,6 @@ llm_externalizer_output/
       tests/agent_context_bench/reports/
      +
      +# janitor: report dirs carry private data (paths, hostnames, pasted secrets)
      +/reports/

  It matches the installed janitor 3.8.13 exactly: its scripts/lib/reports_gitignore.py sets REQUIRED_DIRS = ("reports", "reports_dev") and writes this header line, and its reports-gitignore detector runs once a day. The owner already decided on 2026-11-01 (TRDD-KSUIEPTQ) that reports/ is tracked. Commit 010be429 changed the source writer to require only reports_dev/ and removed the line, but the running 3.8.13 adds it back. Do not commit the line. The line is janitor-generated and quoted in full above, so dropping it loses nothing while the diff is exactly that hunk. Right before publish.py, check that git diff -- .gitignore shows only the quoted hunk, then run git restore -- .gitignore; if the diff holds anything else, remove only the three added lines (the blank line, the header and /reports/), and commit or resolve the other edits before publish.py, which refuses a dirty tree. Check again just before the run, because 3.8.13 can add it back on its next daily run, even during a long publish. Start the publish soon after a reports-gitignore run, or expect one retry. After the release is installed, check that the line stays absent after one reports-gitignore run.
- [ ] After the .gitignore line is dropped, the reports/ files it hid become untracked, and publish.py counts untracked files as a dirty tree (it reads git status --porcelain). Sweep them with sanitize-reports, then commit them or move them to reports_dev/ before publish.py. Sweep the tracked reports/ tree too.
- [ ] The owner has said yes to the publish.
 - [ ] Until TRDD-T36Z4ACR lands, run the secret-shield TS suite by hand before publish.py: (cd /tmp && claude plugin test <plug>) in a scratch shell with the real plugin.json, hooks/secret-shield/ copied and a hooks.json listing ./secret-shield/register.ts; require exit 0 and 0 fail (342 pass at 28b42512).

## Approval log
