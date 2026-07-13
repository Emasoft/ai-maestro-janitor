---
trdd-id: SLFMG704
title: Hand off the hook-injection cache-thrash finding to the plugins that own the other offending hooks
column: dev
created: 2026-07-13T11:10:51+0200
updated: 2026-07-13T11:34:00+0200
current-owner: janitor-session
task-type: infra
severity: HIGH
parent-trdd: K1RJUYGK
relevant-rules: []
---

# Cross-plugin handoff of the hook-injection cache-thrash finding

This is an **EHT of TRDD-K1RJUYGK** — it handles the CONSEQUENCES of that finding for code the
janitor does not own. K1RJUYGK fixed the janitor's own two hooks; this TRDD carries the same
mechanism to the other offenders, which belong to OTHER projects.

**Cross-project rule applies** (`~/.claude/rules/how-to-fix-issues-of-other-projects.md`): the
janitor MUST NOT edit another project's source. Route the finding; do not patch it here.

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-13

**The mechanism (measured, not theorized).** Claude Code STRIPS stale `<system-reminder>`
blocks retroactively, in place, mid-transcript. The prompt cache is a PREFIX cache, so that
deletion mutates the cached prefix and re-bills every token after it as `cache_creation`. Any
hook returning `additionalContext` seeds a strippable block. **"No injection → nothing to strip
→ no break."** Bucketing the injected TEXT does not help — the block is deleted regardless of
what it said (TRDD-YRPUSIFY's approach; falsified by data).

**Measured on this machine** with `agentlenspro get_cache_break_report` (Anthropic's own
`cache_creation`/`cache_read` numbers from raw API bodies). ONE session (c8a95d7e, opus-4-8):
2,406 breaks, 22.6M wasted tokens, **$129.91**. Top `INJECTED_BLOCK_CHANGED` offenders:

| Waste | Occurrences | Block | Owner |
|---|---|---|---|
| $17.90 | 151 | `hook: Stop` | **NO PLUGIN** — every Stop hook checked, none injects (see the attribution table below). Probably Claude Code's own system-reminders. **Do not report to a plugin owner.** |
| $11.51 | 131 | `hook: PostToolBatch` | **UNATTRIBUTED** — no `hooks.json` on this machine registers `PostToolBatch` at all |
| $12.30 | 7 | `skill catalog` | Claude Code itself (skill set changing mid-session) |
| $8.60 | 712 | `hook: PreToolUse:Bash` | ai-maestro-janitor — **FIXED**, TRDD-K1RJUYGK / d50fe8c |
| $6.31 | 7 | `hook: SessionStart:compact` | ai-maestro-janitor — *not yet assessed*, see NPT below |
| $5.45 | 7 | `hook: StopFailure:rate_limit` | ai-maestro-janitor — *not yet assessed* |
| $4.48 | 37 | `hook: PreToolUse:Write` | ai-maestro-janitor — FIXED (same no-matcher hooks) |

### ✓ ATTRIBUTION DONE (2026-07-13) — `hook: Stop` belongs to NO PLUGIN

Every Stop hook registered on this machine was checked for an `additionalContext` emission:

| Stop hook | Emits `additionalContext`? |
|---|---|
| `claude-menu-system/scripts/menu_emit.py` | **no** — uses `systemMessage`, exactly as its docs claim |
| `codex/scripts/stop-review-gate-hook.mjs` | **no** |
| `ai-maestro-assistant-manager-agent/scripts/amama_stop_check.py` | **no** |
| `ai-maestro-janitor/scripts/hooks/on-stop.py` | **no** |
| `ai-maestro-janitor/scripts/hooks/on-stop-token-meter.py` | **no** |
| `agentlenspro hook` (compiled binary, user settings) | **no** — probed with a synthetic Stop payload, emitted nothing |
| `$HOME/.agentlens/pending-prompt.txt` cat-hook (user settings) | file absent; Stop stdout is NOT injected per the spec (only UserPromptSubmit/UserPromptExpansion/SessionStart stdout becomes context) |
| `ai-maestro-plugin`, `-architect-agent`, `-chief-of-staff` | **broken registrations** — see below |

**CONCLUSION: no plugin Stop hook injects.** The most probable source of the `hook: Stop`
`INJECTED_BLOCK_CHANGED` breaks is **Claude Code's OWN `<system-reminder>` blocks** emitted
around the Stop boundary (e.g. the recurring *"The task tools haven't been used recently…"*
reminder, observed appearing and then disappearing within a single session transcript). Those
come from no hook and are stripped by the host itself. AgentLens labels a break by the EVENT
BOUNDARY it occurred at, **not** by a proven emitter — so `hook: Stop` must not be read as
"a Stop hook did this". **Do NOT report this to any plugin owner.** If confirmed, it is
un-fixable by plugin authors and belongs upstream to Anthropic.

### ⛔ SEPARATE BUG FOUND — three ai-maestro plugins have BROKEN Stop hooks

Their registered Stop `command` values are, verbatim: `node` (ai-maestro-plugin), `python3`
(ai-maestro-architect-agent), and **the empty string** (ai-maestro-chief-of-staff). A hook is
invoked with its JSON payload on **stdin** — so bare `node` and bare `python3` will attempt to
**execute that JSON payload as source code** and fail every turn. This is unrelated to the
cache issue but is a real misconfiguration. **This one IS an ai-maestro item — route it.**

### ⚠ The trap I nearly walked into (keep this lesson)

I initially wrote "`hook: Stop` is owned by ai-maestro" because ai-maestro plugins register
Stop hooks, and I was one command away from AMP-ing that to another team. **It is not
established.** `Stop` hooks on this machine are registered by: `agentlenspro` (user
settings), a `pending-prompt.txt` shell hook (user settings), `ai-maestro-plugin`,
`ai-maestro-chief-of-staff`, `ai-maestro-architect-agent`,
`ai-maestro-assistant-manager-agent`, `claude-code-settings`, `claude-menu-system`, `codex`,
and the janitor. I checked exactly ONE of them —
`ai-maestro-assistant-manager-agent/scripts/amama_stop_check.py` — and it emits **NO**
`additionalContext`. That is one ruled out, nine unchecked.

**Registering a Stop hook is not evidence of injecting `additionalContext`.** Attribution
requires proving the specific hook emits the block. Handing a team a bug that is not theirs
is worse than saying nothing.

**Keep it in proportion (do not oversell).** TRDD-YRPUSIFY already measured, via
`investigate_burn`, that prefix churn is only ~**2% of TOTAL burn** — premium-model subagent
fan-out dominates. This is the #1 *avoidable cache-break* cause, not the #1 burn cause.

## The fix pattern to hand over (what K1RJUYGK actually did)

1. Bound the injection **COUNT**, never its text. Latch each advisory to at most once per
   session per tier.
2. Make the repeat-suppression **fail CLOSED**. Failing open means "I cannot remember warning
   you, so warn again" → warn on EVERY tool call, the worst possible outcome.
3. Prefer a non-model-context channel: `systemMessage` (user-visible), the statusline, a log.
   **Decision fields (`permissionDecision`) are safe** — they are not strippable blocks.
4. A **no-matcher** hook fires on every tool; that is the shape that turns a small advisory
   into a four-figure token bill. Scope the matcher, or latch hard.

## NEXT ACTION

1. ~~ATTRIBUTE `hook: Stop`~~ **DONE 2026-07-13 — no plugin injects.** See the attribution
   table above. Probable source is Claude Code's own system-reminders. Do NOT report to any
   plugin owner. Optional follow-up: confirm with Anthropic (a reproducible transcript showing
   a host-emitted reminder present in turn N and absent in turn N+M with no other prefix delta).
2. **`PostToolBatch` ($11.51) — IDENTIFY THE OWNER.** It is not in any `hooks.json` on this
   machine, so it is registered by some other mechanism (or is Claude Code's own injection at
   that boundary). Do not report until attributed.
3. **AMP IS NOT USABLE FROM THIS SESSION — solve that first if AMP is the chosen channel.**
   `amp-send` returns `HTTP 404 not_found` on routing, and the sender identity is ambiguous:
   44 agents are registered on this host and NONE is a janitor identity (auto-registration
   claimed success but produced nothing routable). Sending as one of the other 44 would be
   impersonation. The USER believes AMP "never fails" — from here it does; tell them. The
   documented cross-project fallback is a GitHub issue on the owning plugin's tracker
   (`~/.claude/rules/how-to-fix-issues-of-other-projects.md`); the owning repos are
   `Emasoft/ai-maestro-plugin`, `-chief-of-staff`, `-architect-agent`,
   `-assistant-manager-agent`.
4. **NPT — the janitor's OWN remaining two:** `SessionStart:compact` ($6.31) and
   `StopFailure:rate_limit` ($5.45) were NOT fixed by K1RJUYGK (which only touched the two
   no-matcher PreToolUse hooks). SessionStart legitimately injects once per session (the memory
   breadcrumb + TRDD STATE), so the cost may be irreducible — but it must be MEASURED, not
   assumed. `StopFailure`'s output is documented as IGNORED, so a break attributed to it is
   suspicious and needs explaining before any change.

## Falsification required

Do not mark any of this complete on a green test. Re-run
`agentlenspro get_cache_break_report --sessionId <new session>` and show the named hook has
LEFT `topOffenders`. The prior fix (YRPUSIFY) had passing tests and was still wrong.
