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

11 code(s).

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

14 code(s).

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
| `WFSEC-001` | workflow-security | high | attacker-controlled expression interpolated into a `run:` block at {where} |
| `WFSEC-002` | workflow-security | critical | `pull_request_target` checks out the fork's head at {where} |
| `WFSEC-003` | workflow-security | medium | a workflow declares no `permissions:` block at {where} |
| `WFSEC-004` | workflow-security | medium | a third-party action is not pinned to a commit SHA at {where} |

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

### `WFSEC-001` — attacker-controlled expression interpolated into a `run:` block at {where}

- **Scanner:** `workflow-security` · **Severity:** `high` · **Kind:** `security-workflow`
- **What it is:** A GitHub Actions workflow interpolates `${{ github.event.* }}` (or another attacker-controllable expression) directly into a shell `run:` body.
- **Why it matters:** Anyone who can open an issue or a PR can put shell metacharacters in that field and execute code on the runner — with the workflow's secrets and token in scope.
- **Fix attempted:** Pass the value through an `env:` variable and reference it as `"$VAR"` inside the script. Never interpolate an expression into shell source.

### `WFSEC-002` — `pull_request_target` checks out the fork's head at {where}

- **Scanner:** `workflow-security` · **Severity:** `critical` · **Kind:** `security-workflow`
- **What it is:** A workflow that runs with the BASE repo's write token and secrets explicitly checks out code from the pull request's head.
- **Why it matters:** This executes untrusted contributor code with full write access to the base repository. It is the single most exploited GitHub Actions pattern.
- **Fix attempted:** Use `pull_request` (no secrets, no write token) for anything that runs contributor code, or split into a build job (untrusted) and a privileged job that never checks out fork code.

### `WFSEC-003` — a workflow declares no `permissions:` block at {where}

- **Scanner:** `workflow-security` · **Severity:** `medium` · **Kind:** `security-workflow`
- **What it is:** The workflow inherits the repository's default token permissions instead of declaring least privilege.
- **Why it matters:** A compromised step (or a malicious dependency) inherits whatever the default grants — often write access to contents, packages, and issues.
- **Fix attempted:** Add a top-level `permissions:` block starting from `{}` and grant only what each job needs.

### `WFSEC-004` — a third-party action is not pinned to a commit SHA at {where}

- **Scanner:** `workflow-security` · **Severity:** `medium` · **Kind:** `security-workflow`
- **What it is:** A step uses a mutable ref (a tag or a branch) for an action outside `actions/` and `github/`.
- **Why it matters:** Tags can be moved. An upstream account takeover or a rewritten tag silently changes what runs in the repo's CI, with the repo's secrets.
- **Fix attempted:** Pin the action to a full commit SHA with the version in a trailing comment (`pinact run` automates this).


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
