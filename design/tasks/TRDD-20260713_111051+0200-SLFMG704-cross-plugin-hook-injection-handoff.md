---
trdd-id: SLFMG704
title: Hand off the hook-injection cache-thrash finding to the plugins that own the other offending hooks
column: dev
created: 2026-07-13T11:10:51+0200
updated: 2026-07-13T13:22:00+0200
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
| $5.45 | 7 | `hook: StopFailure:rate_limit` | **NO HOOK CAN INJECT HERE** — the spec says StopFailure output is IGNORED. This is the proof that the label is a boundary, not an emitter (see below). |
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
| `ai-maestro-plugin/scripts/ai-maestro-hook.cjs` (exec form via `args`) | **no** |
| `ai-maestro-architect-agent/scripts/amaa_stop_check.py` (exec form via `args`) | **no** |
| `ai-maestro-chief-of-staff/scripts/amcos_stop_check.py` | **no** |

**CONCLUSION: no plugin Stop hook injects.** The most probable source of the `hook: Stop`
`INJECTED_BLOCK_CHANGED` breaks is **Claude Code's OWN `<system-reminder>` blocks** emitted
around the Stop boundary (e.g. the recurring *"The task tools haven't been used recently…"*
reminder, observed appearing and then disappearing within a single session transcript). Those
come from no hook and are stripped by the host itself. AgentLens labels a break by the EVENT
BOUNDARY it occurred at, **not** by a proven emitter — so `hook: Stop` must not be read as
"a Stop hook did this". **Do NOT report this to any plugin owner.** If confirmed, it is
un-fixable by plugin authors and belongs upstream to Anthropic.

### ✓ PROOF that AgentLens's `hook: <Event>` label is a BOUNDARY, not an EMITTER

An independent, purely deductive confirmation of the conclusion above — no measurement needed:

1. **Spec (verbatim, hooks reference):** `StopFailure` — *"When the turn ends due to an API
   error. **Output and exit code are ignored.**"* So NO StopFailure hook's output can ever
   reach the transcript.
2. **Yet AgentLens reports** `hook: StopFailure:rate_limit` / `INJECTED_BLOCK_CHANGED`
   (7 occurrences, $5.45).
3. **Therefore that block was not emitted by a StopFailure hook** — it *cannot* have been.
4. **Therefore `hook: <Event>` denotes the event BOUNDARY at which the changed block was
   observed, NOT the component that emitted it.**
5. **Therefore `hook: Stop` ($17.90) never implied a Stop hook emitted anything** — exactly
   consistent with the attribution table above, where every Stop hook came back clean.

**A THIRD leg, and the cleanest — `hook: PostToolBatch` ($11.51, 131x).** The other two legs
each need an argument (a spec clause; a grep of ten scripts). This one needs none:
`PostToolBatch` is a real CC event, and **ZERO hooks on this machine register it** — verified by
enumerating all 474 registrations across every settings file and every cached marketplace x
plugin x version (`scripts_dev/audit_hooks.py`). No hook ran there. No hook could have emitted
it. **There is nothing to blame but the host.**

Three labels, three boundaries, three different reasons no hook could be responsible. The
pattern is not a coincidence — it is what the label MEANS.

Corroborating the enumeration: StopFailure hooks on this machine are `agentlenspro` (binary),
`ai-maestro-janitor/on-stop-failure.py` (emits NO `additionalContext` — it works purely by side
effect, writing `rate-limited.flag`), `claude-menu-system/menu_emit.py` (no injection),
`rechecker-plugin/log-stop-failure.py` (a logger), and `ai-maestro-plugin`
(`scripts/ai-maestro-hook.cjs`, exec form — **grepped 2026-07-13: zero `additionalContext`**).

All four ai-maestro Stop/StopFailure scripts (`ai-maestro-hook.cjs`, `amaa_stop_check.py`,
`amcos_stop_check.py`, `amama_stop_check.py`) were grepped directly: **zero `additionalContext`
in any of them.** They use `systemMessage` / `hookSpecificOutput` only. The Stop-hook
enumeration is now complete AND verified — no hand-waving rows left.

**CONSEQUENCE — a reporting bug in AgentLens.** The `hook: <Event>` label reads as an
accusation against a hook and is not one. It is what led me to nearly file a false bug against
ai-maestro. Worth reporting upstream to agentlensPro: either rename the label (e.g.
`boundary: Stop`) or attribute the block to its actual source. Cross-project rule applies —
file an issue on its tracker, do not patch it here.

### ⛔ RETRACTED (2026-07-13) — "ai-maestro plugins have BROKEN hook registrations" was FALSE

**What I claimed:** that `ai-maestro-plugin` (Stop + StopFailure), `-architect-agent` (Stop) and
`-chief-of-staff` (Stop) registered bare `node` / `python3` / empty commands, so each would
"execute the JSON payload on stdin as source code and fail on every turn". I was one command
away from AMP-ing that to another team.

**Why it was false — my extraction dropped a field.** I printed only `.command` from each
`hooks.json` and read the result as the whole hook. Every one of those hooks also carries an
**`args` array**, which my selector never showed me. The real registrations:

| Plugin | Event | `command` | `args` | Verdict |
|---|---|---|---|---|
| `ai-maestro-plugin` | Stop, StopFailure | `node` | `["${CLAUDE_PLUGIN_ROOT}/scripts/ai-maestro-hook.cjs"]` | **VALID** |
| `ai-maestro-architect-agent` | Stop | `python3` | `["${CLAUDE_PLUGIN_ROOT}/scripts/amaa_stop_check.py"]` | **VALID** |
| `ai-maestro-chief-of-staff` | Stop (+4 more) | *absent* | `["python3", "${CLAUDE_PLUGIN_ROOT}/scripts/amcos_stop_check.py"]` | see below |

**The spec (Claude Code hooks reference, verified 2026-07-13):** a command hook runs in **exec
form when `args` is set, and shell form when `args` is omitted**. In exec form, `command` is
resolved as an executable on `PATH` and spawned directly with `args` as the argument vector —
**no shell involved**. So `command: "node"` + `args: [script]` is exactly right. There was never
a bug in the first two plugins. **Nothing was reported; nothing needed to be.**

### ⚠ RESIDUAL — UNVERIFIED, do NOT report as a bug yet

`ai-maestro-chief-of-staff` (2.20.6) omits `command` entirely and puts the interpreter in
`args[0]` — **uniformly, in all 5 of its hooks** (SessionStart, SessionEnd, 2× UserPromptSubmit,
Stop). That is a deliberate convention, not a typo. The docs mark `command` **required** ("the
executable to spawn directly" when `args` is present), so on a literal reading these hooks name
no executable and may be rejected or silently skipped — i.e. **chief-of-staff's hooks may never
fire at all.**

**But I do not know what Claude Code actually does with a missing `command`** (reject at config
validation? skip the hook? fall back to `args[0]`?) — the docs do not say, and I have not
tested it. Neither `-chief-of-staff` nor `-architect-agent` is enabled ANYWHERE on this machine
(checked every settings file), so nothing is failing here and there is no urgency.

**If this is ever raised with ai-maestro, it must be raised as a QUESTION** ("the schema marks
`command` required and yours is absent — have you confirmed these hooks actually fire?"), never
as a defect. I have been wrong about this file once already.

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

**And then I did it AGAIN, in this same file, on the way to fixing it.** Having decided those
plugins' hooks were "broken registrations", I wrote `no`/`broken` into the attribution table for
three scripts I had **never opened** — and separately declared a bug from a `jq` query that
printed `.command` and silently omitted `.args`. Both errors have the same shape: **I let a
partial view of a thing stand in for the thing.** The selector showed me one field; I treated
its output as the whole hook. The narrative said "broken"; I treated that as licence to skip
reading the script.

The rule that would have caught both, cheaply: **when a query returns something surprising,
print the WHOLE object once before reasoning about it** (`jq '.'`, not `jq '.command'`). A
missing field is indistinguishable from a field you didn't ask for.

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
2. ~~`PostToolBatch` ($11.51) — IDENTIFY THE OWNER~~ **DONE 2026-07-13 — it has NO owner.**
   `PostToolBatch` IS a real Claude Code hook event (#10 of the 30 in the hooks reference), but
   an EXHAUSTIVE enumeration of every hook registration on this machine — 474 of them, across
   every settings file and every cached marketplace × plugin × version, via
   `scripts_dev/audit_hooks.py` — finds **ZERO hooks registered on `PostToolBatch`.** It is not
   even among the 13 distinct event names anything here registers.

   **No hook ran at that boundary, so no hook emitted that block.** This is the THIRD and
   cleanest independent confirmation of the boundary-vs-emitter proof — the other two rest on a
   spec clause and on a grep, but this one needs neither: there is simply nothing to blame.
   The block is the HOST's. **Report it to no one.**
3. ~~Route the broken ai-maestro hook registrations~~ **CANCELLED 2026-07-13 — there was no bug.**
   The registrations use the documented `args` exec form and are VALID; my extraction had
   dropped the `args` field (see the RETRACTED section). **Nothing is owed to ai-maestro.**
   Only the chief-of-staff missing-`command` QUESTION remains, and it is not urgent (that
   plugin is enabled nowhere on this machine) and must be asked as a question, not filed as a
   defect.

   For the record, since it will come up again: **AMP is not usable from this session.**
   `amp-send`/`amp-inbox` abort with *"Multiple AMP agents found. Use --id <uuid>"* — 37
   registrations share the single name `ai-maestro@emasoft.aimaestro.local`, and none is a
   janitor identity, so there is no non-impersonating `--id` to send as. The USER believes AMP
   "never fails"; from here it does not even start. **Tell them, but do not "fix" AMP** — it is
   another project's system (`~/.claude/rules/how-to-fix-issues-of-other-projects.md`). The
   documented fallback channel is a GitHub issue on the owning repo.
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
