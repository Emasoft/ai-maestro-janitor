---
prrd-version: 1.1
updated: 2026-06-13T15:46:17+0200
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

## 🥈 SILVER — MANAGER-mutable (agents propose via COS)

- **S2.1** — Scope invariant (issue #7): every user/global-scope mutation (bulk marketplace update, `claude plugin update --scope user`, janitor self-update) runs through the global daemon ONLY; project/local-scope work runs as per-session detectors that hard-filter to project scope and never touch user scope.
- **S3.1** — A cheap idempotent user-scope FILE write (e.g. installing rule files) may stay per-session instead of the daemon, but MUST be atomic (write to a temp file, then `os.replace`) — the file analogue of the daemon's single-writer lock.
- **S4.1** — Persistent state lives in `${CLAUDE_PLUGIN_DATA}`, never in a new `~/.claude/<custom>/` folder: only the data dir is guaranteed to survive plugin/version updates, be picked up by backups, and be cleanly purged on uninstall.
- **S5.1** — The publish pipeline invokes ONLY the CPV plugin for validation (no local validator-script copies); a CPV finding is cleared by devitalizing or removing the offending code, NEVER by exempting/suppressing a rule or relaxing `--strict` (the exempt-list mechanism was dropped fleet-wide as trivially exploitable).
- **S6.1** — Every detector is fail-soft: a detector that raises, or whose optional dependency is missing, degrades to zero findings and logs once — it MUST NOT crash the heartbeat or block the other detectors.

