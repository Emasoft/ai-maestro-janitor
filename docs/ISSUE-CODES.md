# Janitor issue codes

**Generated from `scripts/lib/issue_catalog.py` — do not edit by hand.**
Regenerate with `uv run scripts/issue_catalog_doc.py --write`; a test fails if this file drifts.

Every issue the janitor's scanners and validators can detect has a stable code, `<SCANNER>-<NNN>`.
A code is **immutable once shipped** (like a schema version): never renumbered, never reused — so a
citation in a closed ticket, a report, or a TRDD still resolves years later.

A code decides **who may fix it**, and that is the load-bearing property of this table:

| Domain | What it is | What the janitor does |
|---|---|---|
| **HARNESS** | the janitor's OWN machinery — its index, its migrations, its daemon, its state | opens a ticket and **dispatches a repair agent automatically**. It is fixing itself; nobody else owns that machinery and the blast radius is its own regeneratable state. |
| **PROJECT** | the USER's code, repo, workflows, rulesets | **proposes only.** It authors a proposal TRDD under `design/proposals/` and recommends the exact command. Running `/janitor-support-open-ticket TRDD-<id>` **is** the approval — until then nothing is dispatched and nothing is touched. |

The domain comes from the code, not from the finding's text, so a detector cannot grant itself
unattended access to your repository.


## HARNESS — the janitor repairs itself (automatic)

14 code(s).

| Code | Scanner | Severity | Issue |
|---|---|---|---|
| `DAEMON-001` | daemon-supervisor | critical | the global janitor daemon has died and respawned {count} times in the guard window |
| `MEMCORP-001` | memory-librarian | medium | the wikimem corpus in {scope} has structural damage: {detail} |
| `MEMGREP-001` | memgrep-validate | high | the FTS index in {scope} does not match its content table |
| `MEMGREP-002` | memgrep-validate | critical | the memgrep database in {scope} fails SQLite's own integrity check |
| `MEMGREP-003` | memgrep-validate | critical | an FTS table in {scope} has the wrong column set: {table} |
| `MEMGREP-004` | memgrep-validate | critical | a migration left `{table}` without column `{column}` in {scope} |
| `MEMGREP-005` | memgrep-validate | high | orphaned rows in {scope}: {table} references memories that no longer exist |
| `MEMGREP-006` | memgrep-validate | high | the schema version stamp in {scope} disagrees with the database's actual shape |
| `MEMGREP-007` | memgrep-validate | critical | a base table is missing entirely from the memgrep database in {scope} |
| `MEMGREP-008` | memgrep-validate | critical | an FTS index is missing entirely from the memgrep database in {scope} |
| `MEMGREP-009` | memgrep-index-health | high | the memgrep index in {scope} has needed self-repair {count} times in {window} |
| `SELFINT-001` | janitor-self-integrity | critical | a janitor file failed attestation against the shipped manifest: {path} |
| `SELFINT-002` | janitor-self-integrity | high | the janitor's audit chain no longer verifies: {detail} |
| `STATE-001` | state-guard | high | a janitor state file is unreadable: {path} |

### `DAEMON-001` — the global janitor daemon has died and respawned {count} times in the guard window

- **Scanner:** `daemon-supervisor` · **Severity:** `critical` · **Kind:** `daemon-crash-loop`
- **What it is:** The machine-wide singleton keeps exiting shortly after spawn. The crash-loop breaker is tripped, so the janitor has stopped trying to restart it.
- **Why it matters:** The daemon owns every user-scope mutation — plugin updates, OAuth keepalive, the fleet guardian. With it dead, unattended sessions stop recovering from rate limits.
- **Fix attempted:** Read the daemon log for the exception, reproduce it, and fix the crash. If the cause is a bad plugin version, the last-good rollback is already available — verify it engaged.

### `MEMCORP-001` — the wikimem corpus in {scope} has structural damage: {detail}

- **Scanner:** `memory-librarian` · **Severity:** `medium` · **Kind:** `memory-corpus`
- **What it is:** Pages are malformed, links dangle, or footnote refs do not resolve.
- **Why it matters:** A corpus whose links do not resolve cannot be navigated, and the LINK LAW (every link is bidirectional) is what makes recall work at all.
- **Fix attempted:** Run the memory curator's repair pass under the edit transaction, which proves no knowledge was lost before it commits.

### `MEMGREP-001` — the FTS index in {scope} does not match its content table

- **Scanner:** `memgrep-validate` · **Severity:** `high` · **Kind:** `index-corruption`
- **What it is:** An external-content FTS5 table holds no data of its own, so its rows can silently fall out of step with the table they index. `PRAGMA integrity_check` returns `ok` and a `SELECT count(*)` reads the CONTENT table — both lie. Only `INSERT INTO t(t, rank) VALUES('integrity-check', 1)` compares index against content.
- **Why it matters:** Recall degrades to nothing while every surface reports a healthy database, so a memory the agent depends on is simply never found — and nothing says so.
- **Fix attempted:** Rebuild the index from its content tables (`INSERT INTO t(t) VALUES('rebuild')`), then re-validate. If a FRESH index still fails, the bug is in the schema code, not the data.

### `MEMGREP-002` — the memgrep database in {scope} fails SQLite's own integrity check

- **Scanner:** `memgrep-validate` · **Severity:** `critical` · **Kind:** `index-corruption`
- **What it is:** `PRAGMA integrity_check` reports structural damage: the file itself is corrupt, not merely out of step with its content.
- **Why it matters:** Every read can return wrong rows or throw. Unlike an FTS desync, this cannot be repaired by a rebuild — the pages are damaged.
- **Fix attempted:** Delete the database AND its `-wal`/`-shm` siblings (a fresh db beside a stale WAL is REAL corruption), then reindex the corpus from the markdown notes, which are the source of truth.

### `MEMGREP-003` — an FTS table in {scope} has the wrong column set: {table}

- **Scanner:** `memgrep-validate` · **Severity:** `critical` · **Kind:** `migration-failure`
- **What it is:** A migration recreated an FTS table with columns that no longer match what the code queries.
- **Why it matters:** Queries fail or — worse — silently match the wrong column, so recall returns confidently wrong results.
- **Fix attempted:** Recreate the table with the current column set and rebuild it from the content tables. The migration step that produced this shape is the real defect; fix it too.

### `MEMGREP-004` — a migration left `{table}` without column `{column}` in {scope}

- **Scanner:** `memgrep-validate` · **Severity:** `critical` · **Kind:** `migration-failure`
- **What it is:** A base table does not have the shape the current schema version claims it has.
- **Why it matters:** The database is stamped as migrated but is not. Every later migration builds on a false premise, so the damage compounds silently.
- **Fix attempted:** Read the migration ladder, find the step that failed to add the column, and repair it so it is transactional and self-validating. Then rebuild the database from the notes.

### `MEMGREP-005` — orphaned rows in {scope}: {table} references memories that no longer exist

- **Scanner:** `memgrep-validate` · **Severity:** `high` · **Kind:** `index-corruption`
- **What it is:** Child rows survived the deletion of their parent memory — a foreign-key invariant the schema depends on is broken.
- **Why it matters:** Recall surfaces notes and lessons that belong to a page that is gone, so the agent acts on knowledge the corpus no longer contains.
- **Fix attempted:** Delete the orphans, then find the delete path that failed to cascade — the orphans are a symptom, the missing cascade is the defect.

### `MEMGREP-006` — the schema version stamp in {scope} disagrees with the database's actual shape

- **Scanner:** `memgrep-validate` · **Severity:** `high` · **Kind:** `migration-failure`
- **What it is:** `PRAGMA user_version` was stamped without the migration that earns it (or the database is NEWER than this build's schema).
- **Why it matters:** A wrong stamp makes every future migration skip or repeat. A newer-than-expected database must never be 'migrated' downward — that mangles data written by a build we do not know.
- **Fix attempted:** If the stamp is ahead of this build's schema, REFUSE to touch it and tell the user to update. Otherwise rebuild from the notes and re-run the ladder transactionally.

### `MEMGREP-007` — a base table is missing entirely from the memgrep database in {scope}

- **Scanner:** `memgrep-validate` · **Severity:** `critical` · **Kind:** `migration-failure`
- **What it is:** A table the schema requires does not exist at all — the schema was never fully applied, or something dropped it.
- **Why it matters:** Every query against that table throws. Unlike a missing column (which fails quietly), this fails loudly — but only once something reads it, which may be days later.
- **Fix attempted:** Re-apply the schema and reindex from the markdown notes, which are the source of truth. Then find what dropped the table — a table does not vanish on its own.

### `MEMGREP-008` — an FTS index is missing entirely from the memgrep database in {scope}

- **Scanner:** `memgrep-validate` · **Severity:** `critical` · **Kind:** `migration-failure`
- **What it is:** A full-text index the schema requires does not exist — a DROP without the matching CREATE, the shape a half-applied migration leaves behind.
- **Why it matters:** Search silently returns nothing rather than failing, so the corpus looks empty instead of broken. That is the worst failure mode there is: it is indistinguishable from having no memories.
- **Fix attempted:** Recreate the FTS table and rebuild it from its content table, then fix the migration step that dropped it without recreating it.

### `MEMGREP-009` — the memgrep index in {scope} has needed self-repair {count} times in {window}

- **Scanner:** `memgrep-index-health` · **Severity:** `high` · **Kind:** `index-corruption`
- **What it is:** The index keeps failing validation on open, and the self-heal keeps repairing it. The data is fine — something is RE-BREAKING it.
- **Why it matters:** This is the signal the original incident had no way to produce. The self-heal RACES any observer and wins: every process that opens the index (the autorecall hook on every prompt, the librarian, a memory agent) repairs it in passing, so a probe that inspects the DATABASE always finds it pristine. A corruption re-manufactured daily is invisible to state inspection — and that is exactly how the 2026-07-14 migration bug hid for days. The repair EVENT is the only durable evidence.
- **Fix attempted:** Do NOT just rebuild it again — that is what has been happening. Read `.memgrep/self-heal.log` for what failed and when, then find the WRITER that keeps corrupting it (a migration step, a schema change, a concurrent writer without the busy timeout). The index is the victim; the code that breaks it is the defect.

### `SELFINT-001` — a janitor file failed attestation against the shipped manifest: {path}

- **Scanner:** `janitor-self-integrity` · **Severity:** `critical` · **Kind:** `self-integrity`
- **What it is:** A plugin file's sha256 does not match the manifest published with its release — it was modified after install.
- **Why it matters:** The janitor runs with the user's full privileges on every project on this machine. A tampered detector is a tampered guardian, and it would be the last thing to report itself.
- **Fix attempted:** Do NOT self-heal by overwriting: preserve the modified file as evidence FIRST, then reinstall the plugin from its release and diff the two. Report to the user before anything else.

### `SELFINT-002` — the janitor's audit chain no longer verifies: {detail}

- **Scanner:** `janitor-self-integrity` · **Severity:** `high` · **Kind:** `self-integrity`
- **What it is:** The HMAC-chained audit log has a break that is not the known concurrent-fork artifact.
- **Why it matters:** The audit chain is how the janitor proves what it did to this machine. A chain that cannot be verified is not evidence.
- **Fix attempted:** Preserve the chain, identify the break point, and determine whether it is a lost update (a concurrency bug to fix) or a rewrite (a security event to report).

### `STATE-001` — a janitor state file is unreadable: {path}

- **Scanner:** `state-guard` · **Severity:** `high` · **Kind:** `state-corruption`
- **What it is:** A file under `.janitor/state/` cannot be parsed — truncated, or half-written by a process that died mid-write.
- **Why it matters:** State drives the heartbeat's decisions (cadence, resume, dedupe). A file that fails to parse is usually treated as absent, so the janitor silently forgets something it knew.
- **Fix attempted:** Find the write site and make it ATOMIC (tmp + `os.replace`). A non-atomic write to state is the defect; the corrupt file is only its symptom.


## PROJECT — your repo (proposed, never automatic)

16 code(s).

| Code | Scanner | Severity | Issue |
|---|---|---|---|
| `AICTX-001` | ai-context-poisoning | critical | an agent-context file may be poisoned: {path} |
| `BRPROT-001` | branch-protection | high | the default branch of {slug} is unprotected |
| `BRPROT-002` | branch-protection | high | the branch-protection baseline on {slug} has drifted: {detail} |
| `CRED-001` | remote-credentials | critical | a credential appears to be exposed in {path} |
| `DEP-001` | supply-chain | high | {package} {version} carries a known advisory: {advisory} |
| `DEP-002` | historical-cache-scan | critical | a KNOWN-MALICIOUS package version is present: {package} {version} |
| `DEP-003` | typosquat-watcher | high | `{package}` is one edit away from the popular package `{target}` |
| `GHCFG-001` | fleet-github-config | medium | the GitHub config of {slug} is off-baseline: {detail} |
| `MCPSEC-001` | mcp-rugpull | high | an installed MCP server changed its fingerprint: {server} |
| `PKGPOL-001` | package-manager-policy | medium | a package-manager safety knob is disabled in {path}: {detail} |
| `WFSEC-001` | workflow-security | high | a workflow lets attacker-controlled input reach an executable position in {where} |
| `WFSEC-002` | workflow-security | critical | a workflow runs fork-controlled code with the base repo's privileges in {where} |
| `WFSEC-003` | workflow-security | medium | a workflow's token or permission scope is wider than the job needs in {where} |
| `WFSEC-004` | workflow-security | medium | a workflow depends on a MUTABLE reference in {where} |
| `WFSEC-005` | workflow-security | critical | a workflow exposes a secret in {where} |
| `WFSEC-006` | workflow-security | medium | a workflow's own safety rail is missing or defeated in {where} |

### `AICTX-001` — an agent-context file may be poisoned: {path}

- **Scanner:** `ai-context-poisoning` · **Severity:** `critical` · **Kind:** `security-workflow`
- **What it is:** A file the AI reads as INSTRUCTIONS (CLAUDE.md, a skill, an agent definition, a rule) contains authority impersonation, invisible unicode, or a jailbreak pattern.
- **Why it matters:** This is the highest-leverage attack on an agentic system: the payload does not exploit the code, it exploits the reader — and the reader has the user's full privileges.
- **Fix attempted:** Do not 'clean it up' silently. Preserve the file, show the user the exact payload and where it came from, and strip the covert unicode only after they have seen it.

### `BRPROT-001` — the default branch of {slug} is unprotected

- **Scanner:** `branch-protection` · **Severity:** `high` · **Kind:** `branch-protection`
- **What it is:** No active ruleset protects the default branch against deletion, force-push, or unreviewed merges.
- **Why it matters:** A single mistaken force-push rewrites history that other clones have already fetched, and there is no server-side record of what was there before.
- **Fix attempted:** Apply the ratified baseline ruleset pair (`baseline-history-protect` + `baseline-pr-and-checks`). Applying the baseline AS-IS is pre-approved; any DEVIATION from it needs the user.

### `BRPROT-002` — the branch-protection baseline on {slug} has drifted: {detail}

- **Scanner:** `branch-protection` · **Severity:** `high` · **Kind:** `branch-protection`
- **What it is:** A ruleset that was part of the ratified baseline has been weakened, disabled, or given a new bypass actor.
- **Why it matters:** Protection that silently degrades is worse than none, because everyone still believes the branch is protected.
- **Fix attempted:** Restore the ruleset to the ratified baseline. If the deviation was deliberate, it needs an explicit decision from the user — do not re-apply over it without asking.

### `CRED-001` — a credential appears to be exposed in {path}

- **Scanner:** `remote-credentials` · **Severity:** `critical` · **Kind:** `leaked-credential`
- **What it is:** A high-entropy secret matching a known credential shape is present in a file that is (or could be) committed or transmitted.
- **Why it matters:** A secret in a repo is a secret in every clone, every fork, and every CI log — forever, even after the commit is 'removed'.
- **Fix attempted:** FLAG IT — do NOT rotate anything automatically. Confirm whether it is live, tell the user to rotate it, and only then remove it from the file and purge it from history.

### `DEP-001` — {package} {version} carries a known advisory: {advisory}

- **Scanner:** `supply-chain` · **Severity:** `high` · **Kind:** `dependency-advisory`
- **What it is:** An installed dependency matches a published security advisory.
- **Why it matters:** The vulnerable code is already on disk and in the build. An advisory is public, so exploit code usually is too.
- **Fix attempted:** Bump to the fixed version and run the project's full test suite. If no fixed version exists, FLAG it for the user with the exposure — never silently pin to a vulnerable release.

### `DEP-002` — a KNOWN-MALICIOUS package version is present: {package} {version}

- **Scanner:** `historical-cache-scan` · **Severity:** `critical` · **Kind:** `dependency-advisory`
- **What it is:** A dependency version that was published as malware (a compromised maintainer account, a hijacked release) is in the tree or the package cache.
- **Why it matters:** This is not a latent vulnerability — it is code that was written to steal credentials, and it may have already run in a postinstall hook.
- **Fix attempted:** Remove it, purge the package cache, and treat every credential reachable from this machine as potentially exposed. Report to the user IMMEDIATELY — do not quietly bump the version.

### `DEP-003` — `{package}` is one edit away from the popular package `{target}`

- **Scanner:** `typosquat-watcher` · **Severity:** `high` · **Kind:** `dependency-advisory`
- **What it is:** A declared dependency's name is within a small edit distance of a widely-used package — the signature of a typosquat.
- **Why it matters:** Typosquats exist to be installed by accident and to run code at install time. The cost of checking is one lookup; the cost of missing one is a compromised machine.
- **Fix attempted:** Verify the package is the one that was intended (registry, repo, download counts). If it is a squat, remove it and audit what its install scripts did.

### `GHCFG-001` — the GitHub config of {slug} is off-baseline: {detail}

- **Scanner:** `fleet-github-config` · **Severity:** `medium` · **Kind:** `github-config`
- **What it is:** A repository's settings, workflows, or rulesets diverge from the ratified fleet baseline.
- **Why it matters:** Drift accumulates silently until an incident proves the protection everyone assumed was in place is not.
- **Fix attempted:** Bring the repo back to the baseline. Applying the baseline AS-IS is pre-approved; any deviation from it needs the user's decision.

### `MCPSEC-001` — an installed MCP server changed its fingerprint: {server}

- **Scanner:** `mcp-rugpull` · **Severity:** `high` · **Kind:** `security-workflow`
- **What it is:** A server's tool definitions or code changed after installation — the rug-pull shape, where a benign server is updated into a malicious one.
- **Why it matters:** MCP tool descriptions are injected into every turn's context. A server that silently rewrites its own tool descriptions is rewriting the agent's instructions.
- **Fix attempted:** Diff the old and new definitions, show the user what changed, and do not re-enable the server until they have approved the change.

### `PKGPOL-001` — a package-manager safety knob is disabled in {path}: {detail}

- **Scanner:** `package-manager-policy` · **Severity:** `medium` · **Kind:** `github-config`
- **What it is:** Configuration disables a supply-chain safeguard — lockfile enforcement, integrity checking, or install-script sandboxing.
- **Why it matters:** These knobs are the only thing standing between a compromised transitive dependency and arbitrary code execution at install time.
- **Fix attempted:** Restore the safeguard and re-run the install to confirm nothing depended on it being off. If something did, that dependency is the real finding.

### `WFSEC-001` — a workflow lets attacker-controlled input reach an executable position in {where}

- **Scanner:** `workflow-security` · **Severity:** `high` · **Kind:** `security-workflow`
- **What it is:** A GitHub Actions workflow interpolates `${{ github.event.* }}` (or another attacker-controllable expression) directly into something that gets EXECUTED or EVALUATED — a shell `run:` body, a `github-script` block, `runs-on:`, a matrix, `$GITHUB_ENV`, `$GITHUB_OUTPUT`, or an AI tool's config.
- **Why it matters:** Anyone who can open an issue or a PR can put shell metacharacters in that field and execute code on the runner — with the workflow's secrets and token in scope. The title of an issue is not data the workflow gets to trust.
- **Fix attempted:** Pass the value through an `env:` variable and reference it as `"$VAR"` inside the script — the value then arrives as data, not as source. Never interpolate an expression into anything that will be parsed as code.

### `WFSEC-002` — a workflow runs fork-controlled code with the base repo's privileges in {where}

- **Scanner:** `workflow-security` · **Severity:** `critical` · **Kind:** `security-workflow`
- **What it is:** A workflow that holds the BASE repo's write token and secrets executes code the contributor controls — checking out a PR head under `pull_request_target`, re-running a `workflow_run` head, acting on an `issue_comment`, or handing a fork's artifact/cache to a privileged job.
- **Why it matters:** This is the single most exploited GitHub Actions pattern: it executes untrusted code with full write access to the base repository. There is no sandbox — the token is right there.
- **Fix attempted:** Use `pull_request` (no secrets, no write token) for anything that runs contributor code, or split into an UNTRUSTED build job and a PRIVILEGED job that never checks out fork code and only consumes verified inputs.

### `WFSEC-003` — a workflow's token or permission scope is wider than the job needs in {where}

- **Scanner:** `workflow-security` · **Severity:** `medium` · **Kind:** `security-workflow`
- **What it is:** The workflow inherits (or explicitly grants) more privilege than it uses: no `permissions:` block, a broad grant, `secrets: inherit`, an unscoped app token, an ungated `id-token: write`, or a checkout that leaves the token persisted on disk.
- **Why it matters:** Every excess grant is blast radius. A compromised step — or one malicious dependency in one action — inherits whatever the job holds, and 'write to contents' is enough to rewrite the repository.
- **Fix attempted:** Declare least privilege: start from an EMPTY `permissions:` map and grant only what each job actually needs; scope app tokens; gate `id-token: write` behind an environment; stop persisting credentials.

### `WFSEC-004` — a workflow depends on a MUTABLE reference in {where}

- **Scanner:** `workflow-security` · **Severity:** `medium` · **Kind:** `security-workflow`
- **What it is:** A step pulls something that can change under it without the repo changing: an action on a tag or branch, an unpinned Docker image, an unfrozen lockfile, a `curl | sh`, or a build that publishes from the same job it built in.
- **Why it matters:** Tags move. An upstream account takeover or a rewritten tag silently changes what runs in CI — with the repo's secrets — and the diff that would have shown it does not exist, because nothing in the repo changed.
- **Fix attempted:** Pin it: a full commit SHA (with the version in a trailing comment — `pinact run` automates this), an image digest, a frozen lockfile. What ran yesterday must be what runs today.

### `WFSEC-005` — a workflow exposes a secret in {where}

- **Scanner:** `workflow-security` · **Severity:** `critical` · **Kind:** `security-workflow`
- **What it is:** A credential is present where it can escape: hard-coded in the workflow, a static cloud key, a token in a URL or a Docker build-arg, a secret interpolated bare into a `run:` body, or the whole secrets object dumped via `toJSON`.
- **Why it matters:** A secret in a workflow is a secret in every fork, every log, and every cached layer. Build-args and env dumps end up in artifacts that outlive the run.
- **Fix attempted:** Move it behind `secrets:` (or OIDC, which mints a short-lived token and stores nothing). If it was ever COMMITTED, it is burned: tell the user to ROTATE it — do not rotate it yourself — and only then remove it and purge it from history.

### `WFSEC-006` — a workflow's own safety rail is missing or defeated in {where}

- **Scanner:** `workflow-security` · **Severity:** `medium` · **Kind:** `security-workflow`
- **What it is:** A guard that was supposed to catch failures is absent or neutered: no `timeout-minutes`, an `if:` condition that is always true, `continue-on-error` on a SECURITY step, or a global git config that rewrites what later steps fetch.
- **Why it matters:** A defeated guard is worse than no guard: the job reports success, the security step's failure is swallowed, and everyone downstream believes the check ran. A hung job with no timeout burns the runner budget until someone notices by hand.
- **Fix attempted:** Restore the guard — set `timeout-minutes`, make the condition mean something, and let a failing security step FAIL the job. A check whose result is ignored is not a check.


## How a finding becomes work

A detector raises a code — that is the entire producer-side API:

```python
raise_issue("WFSEC-001", where="ci.yml:42", evidence=[".github/workflows/ci.yml"])
```

`raise_issue` looks the code up, renders **our** template with the detector's **sanitized** data, and
routes by domain: a HARNESS code opens a ticket the scheduler will dispatch; a PROJECT code writes a
proposal TRDD and hands back the approval command.

Ticket text is treated as **untrusted data**, never instructions: values interpolated from filenames,
dependency names, workflow lines, and issue titles are defanged on ingest (a payload cannot mimic a
`[janitor-…]` marker), and the dispatched agent's instructions come from the janitor's own skills —
never from the ticket.

## Inspecting the queue

```
/janitor-support-tickets              # the queue, with severity, attempts, and budget
/janitor-support-open-ticket TRDD-…   # approve a proposed PROJECT fix
```
