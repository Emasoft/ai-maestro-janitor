---
prrd-version: 1.2
updated: 2026-08-04T20:10:00+0200
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

- **G1.1** — Every agent that writes to GitHub (issue, issue comment, PR, PR comment, PR review, discussion, release note) MUST begin the body with a one-line self-identification of which agent/role/plugin authored it, because all AI Maestro agents share the single human-owner GitHub identity (the owner's gh CLI auth). Recommended leading line: _Posted by the Claude developing **<plugin-or-role>** (via the shared @owner gh auth)._ Commit messages SHOULD carry an `Agent: <role>` trailer.
- **G7.1** — `CLAUDE.md` is an INDEX, not a knowledge store. It MUST contain exactly five elements and nothing else: (1) a one-paragraph project description, (2) the project URLs, (3) the dev-ops commands, (4) the janitor-generated project-map fence, (5) the janitor-generated wikimem index fence. Every line is re-read into every session's context on every turn, so prose parked here is paid for forever by every agent, whether or not it is relevant to the task at hand.
- **G8.1** — Any line added to `CLAUDE.md` outside G7.1's five elements MUST be migrated out by the janitor's scheduled chores into the wikimem page that owns its subject — created as a new atom, or folded into an existing atom plus a new `[^N]` lesson learned. The migration is AUTOMATIC and mandatory, not an advisory nudge: a rule that depends on an agent noticing a reminder is the failure mode this replaces.
- **G9.1** — The ONLY content exempt from G8.1 is basic dev-ops command knowledge: git, commit, branching, merging, linting, building, testing, tagging, pushing, CI, publishing, installing, deploying. Everything else — architecture, gotchas, incident history, design rationale, conventions — MUST live in a wikimem page and be reached by recall.
- **G10.1** — Every ROOT topic of the PROJECT wikimem MUST appear in `CLAUDE.md`'s wikimem index, and the project-map fence MUST be present and regenerated when the code structure changes. An index that omits a root topic makes that topic unreachable for any agent that does not already know it exists, which defeats the purpose of moving knowledge out under G8.1.

## 🥈 SILVER — MANAGER-mutable (agents propose via COS)

- **S2.1** — Scope invariant (issue #7): every user/global-scope mutation (bulk marketplace update, `claude plugin update --scope user`, janitor self-update) runs through the global daemon ONLY; project/local-scope work runs as per-session detectors that hard-filter to project scope and never touch user scope.
- **S3.1** — A cheap idempotent user-scope FILE write (e.g. installing rule files) may stay per-session instead of the daemon, but MUST be atomic (write to a temp file, then `os.replace`) — the file analogue of the daemon's single-writer lock.
- **S4.1** — Persistent state lives in `${CLAUDE_PLUGIN_DATA}`, never in a new `~/.claude/<custom>/` folder: only the data dir is guaranteed to survive plugin/version updates, be picked up by backups, and be cleanly purged on uninstall.
- **S5.1** — The publish pipeline invokes ONLY the CPV plugin for validation (no local validator-script copies); a CPV finding is cleared by devitalizing or removing the offending code, NEVER by exempting/suppressing a rule or relaxing `--strict` (the exempt-list mechanism was dropped fleet-wide as trivially exploitable).
- **S6.1** — Every detector is fail-soft: a detector that raises, or whose optional dependency is missing, degrades to zero findings and logs once — it MUST NOT crash the heartbeat or block the other detectors.

