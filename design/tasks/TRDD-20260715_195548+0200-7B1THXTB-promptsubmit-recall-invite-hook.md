---
trdd-id: 7B1THXTB
title: UserPromptSubmit hook — invite the agent to proactively memgrep-recall before acting
column: backburner
created: 2026-07-15T19:55:48+0200
updated: 2026-07-15T19:55:48+0200
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
1. **Audit the existing hook first** — `scripts/hooks/on-prompt-submit-autorecall.py` (issues #16/#45)
   already runs on UserPromptSubmit and, per the SessionStart breadcrumb, auto-surfaces relevant notes
   by symptom. DECIDE: is the user's INVITE (a) a lighter mode of that hook, or (b) a new hook? The
   existing one auto-SURFACES; the user asked for an INVITE (Claude searches itself). Prefer
   extending/aligning the existing hook over adding a parallel one — two UserPromptSubmit hooks both
   injecting context each prompt is token waste and confusing.
2. Implement the invite injection (via `additionalContext`), kept SHORT (it rides every prompt — token
   economy). No specific memory named.
3. Test: a fresh prompt shows the invite; no specific memory is named by the hook.
4. Publish (the hook lives in the plugin → needs a release + cache update to deploy, per
   `macos-keychain.md [^2]` / TRDD-EQJPPZ2L: repo ≠ deployed).

## Verification
- On any user prompt, the agent sees a short invite to `memgrep recall` before acting; the hook names
  no specific memory. Plugin tests + publish gates green.

## Notes and lessons learned
