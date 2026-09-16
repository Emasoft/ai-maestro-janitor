---
trdd-id: 7B1THXTB
title: UserPromptSubmit hook — invite the agent to proactively memgrep-recall before acting
column: published
published-version: 0.45.0
created: 2026-07-15T19:55:48+0200
updated: 2026-07-16T04:31:06+0200
current-owner: janitor-session
task-type: feature
scope: project
severity: major
labels: [wikimem, memgrep, memory-recall, hooks]
parent-trdd: AP2X9A0H
relevant-rules: []
---

# UserPromptSubmit hook — invite the agent to proactively memgrep-recall before acting

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-15

Split out of TRDD-AP2X9A0H (the `desc`-field task) so each is one atomic task.

**The ask (USER, 2026-07-15):** after each user prompt is submitted, the janitor injects a short
INVITATION for the agent to proactively `memgrep recall`/`find` for memories related to the prompt —
using keywords/keyphrases derived from the prompt — BEFORE acting. It must **NOT** name or suggest
specific memories itself; it only PROMPTS the agent to search on its own.

**Motivating failure (the case that proves the need):** this session (2026-07-15) I re-hit a trap that
was ALREADY documented in the `macos-keychain.md` wikimem page (`[^2]`, 2026-07-09 — the
cache-vs-repo / L0-keepalive staged-closure trap) and it broke the user's own Claude Code `/login`,
because I did not RECALL that page before the go-live. The memory existed; nothing prompted me to
read it. See `macos-keychain.md [^8]` (ATOM-MX20-QO8S).

**For-now vs future:**
- THIS TRDD ships only the INVITE (a static nudge to search). No keyword extraction, no suggestions.
- FUTURE (separate TRDD, not this one): a more powerful Rust hook that extracts keywords/keyphrases
  from the prompt PROGRAMMATICALLY and auto-suggests the most relevant ATOMS and whole-topic WIKIMEM
  PAGES.

## NEXT ACTION
**IMPLEMENTED 2026-07-16 — decision (a): the invite is part of the EXISTING autorecall hook** (no
parallel UserPromptSubmit hook — one injection surface per prompt). `on-prompt-submit-autorecall.py`:
- constant `_INVITE` (one line, from OUR code, names no memory: the agent derives its own keywords);
- HIT → notes first, invite appended last; MISS → invite ALONE (the miss is the motivating case);
- EMPTY corpus / no memgrep / trivial-cron-slash prompts → still fully silent (unchanged no-ops);
- separate opt-out `CLAUDE_PLUGIN_OPTION_MEMORY_RECALL_INVITE` (default ON), declared as
  `memory_recall_invite` in plugin.json userConfig; `memory_autorecall=false` kills the whole hook.
Tests: 20/20 green in `tests/test_autorecall_hook.py` (3 new: miss→invite-only + no memory named,
hit→notes-then-invite ordering, invite opt-out restores miss-silence).

**REMAINING:** publish (the hook lives in the plugin → release + cache update to deploy, per
`macos-keychain.md [^2]` / TRDD-EQJPPZ2L: repo ≠ deployed). FUTURE (separate TRDD, not this one):
the Rust keyword-extraction hook that auto-suggests atoms/pages.

## Verification
- On any user prompt, the agent sees a short invite to `memgrep recall` before acting; the hook names
  no specific memory. Plugin tests + publish gates green.

## Notes and lessons learned
