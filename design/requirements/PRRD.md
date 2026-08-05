---
prrd-version: 1.3
updated: 2026-08-05T06:14:05+0200
project: ai-maestro-janitor
canonical-source: design/requirements/PRRD.md
mirrors: []
---

# Project Requirements & Rules — ai-maestro-janitor

Janitor plugin (no main agent) — drift detection, heartbeat, repo hardening skills.

## §0. Canonical source + copies

| Path | Role | Update strategy |
|---|---|---|
| `design/requirements/PRRD.md` | **CANONICAL** for this project | Edit first. Bump `prrd-version:`. Update `updated:`. |

## §I. How to read this document

Rule citation form: `PRRD G<n>.<v>` (golden, user-set) or `PRRD S<n>.<v>`
(silver, manager-mutable). Rule numbers are globally unique across G/S;
promote/demote flips the letter without changing the number. The
`get-prrd.py <n>` script returns a rule's text by bare number. Full
spec: `~/.claude/rules/prrd-design-rules.md`.

## 🥇 GOLDEN — set by the USER (immutable to MANAGER)

- **G1.2** — Every agent that writes to GitHub (issue, issue comment, PR, PR comment, PR review, discussion, release note) MUST begin the body with a one-line self-identification of which agent/role/plugin authored it, because all AI Maestro agents share the single human-owner GitHub identity (the owner's gh CLI auth). Recommended leading line: _Posted by the Claude developing **<plugin-or-role>** (via the shared gh CLI auth user name)._ Commit messages SHOULD carry an `Agent: <role>` trailer. The self-identification line MUST NOT contain a bare `@name`: GitHub linkifies one outside a code span, so a template every agent copies verbatim would page whatever real account holds that name on every post.
- **G7.1** — `CLAUDE.md` is an INDEX, not a knowledge store. It MUST contain exactly five elements and nothing else: (1) a one-paragraph project description, (2) the project URLs, (3) the dev-ops commands, (4) the janitor-generated project-map fence, (5) the janitor-generated wikimem index fence. Every line is re-read into every session's context on every turn, so prose parked here is paid for forever by every agent, whether or not it is relevant to the task at hand.
- **G8.1** — Any line added to `CLAUDE.md` outside G7.1's five elements MUST be migrated out by the janitor's scheduled chores into the wikimem page that owns its subject — created as a new atom, or folded into an existing atom plus a new `[^N]` lesson learned. The migration is AUTOMATIC and mandatory, not an advisory nudge: a rule that depends on an agent noticing a reminder is the failure mode this replaces.
- **G9.1** — The ONLY content exempt from G8.1 is basic dev-ops command knowledge: git, commit, branching, merging, linting, building, testing, tagging, pushing, CI, publishing, installing, deploying. Everything else — architecture, gotchas, incident history, design rationale, conventions — MUST live in a wikimem page and be reached by recall.
- **G10.1** — Every ROOT topic of the PROJECT wikimem MUST appear in `CLAUDE.md`'s wikimem index, and the project-map fence MUST be present and regenerated when the code structure changes. An index that omits a root topic makes that topic unreachable for any agent that does not already know it exists, which defeats the purpose of moving knowledge out under G8.1.
- **G11.1** — An agent MAY open issues and post comments ONLY on GitHub repositories owned by the account currently authenticated in the `gh` CLI. Writing to any repository NOT owned by that account requires EXPLICIT authorization from the MANAGER, granted per case, never standing. The MANAGER may grant it in exactly two situations: (a) it is absolutely needed to fix a VERIFIED bug that is blocking the development of a project — verified meaning reproduced, not suspected; or (b) the current `gh` CLI auth user is an ai-maestro USER whom the MANAGER authorized to collaborate on a project owned by the MAESTRO USER, and the work requires writing or commenting on a MAESTRO-USER-owned repository. Rationale: every agent on this host writes through ONE shared human identity, so a post on a repository the human does not own is published in their name to a third party, is visible immediately, and cannot be unpublished — deletion does not undo notification, and GitHub retains edit history. The blast radius of a wrong call therefore lands on the human, not the agent, which is why the default is refuse-and-ask rather than judge-for-yourself.

## 🥈 SILVER — MANAGER-mutable (agents propose via COS)

- **S2.1** — Scope invariant (issue #7): every user/global-scope mutation (bulk marketplace update, `claude plugin update --scope user`, janitor self-update) runs through the global daemon ONLY; project/local-scope work runs as per-session detectors that hard-filter to project scope and never touch user scope.
- **S3.1** — A cheap idempotent user-scope FILE write (e.g. installing rule files) may stay per-session instead of the daemon, but MUST be atomic (write to a temp file, then `os.replace`) — the file analogue of the daemon's single-writer lock.
- **S4.1** — Persistent state lives in `${CLAUDE_PLUGIN_DATA}`, never in a new `~/.claude/<custom>/` folder: only the data dir is guaranteed to survive plugin/version updates, be picked up by backups, and be cleanly purged on uninstall.
- **S5.1** — The publish pipeline invokes ONLY the CPV plugin for validation (no local validator-script copies); a CPV finding is cleared by devitalizing or removing the offending code, NEVER by exempting/suppressing a rule or relaxing `--strict` (the exempt-list mechanism was dropped fleet-wide as trivially exploitable).
- **S6.1** — Every detector is fail-soft: a detector that raises, or whose optional dependency is missing, degrades to zero findings and logs once — it MUST NOT crash the heartbeat or block the other detectors.

