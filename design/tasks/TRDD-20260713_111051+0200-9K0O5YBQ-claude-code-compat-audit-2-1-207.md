---
trdd-id: 9K0O5YBQ
title: Claude Code compatibility audit at v2.1.207 — the janitor uses 10 of 31 hook events and 1 of 5 handler types
column: todo
created: 2026-07-13T11:10:51+0200
updated: 2026-07-13T11:10:51+0200
current-owner: janitor-session
task-type: audit
severity: MEDIUM
relevant-rules: []
---

# Claude Code compatibility audit at v2.1.207

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-13

Audited the janitor's Claude-Code assumptions against the LIVE docs
(`https://code.claude.com/docs/llms.txt`, local CC **2.1.207**, latest release notes Week 28).
Everything below was READ FROM THE DOC or GREPPED FROM OUR SOURCE — nothing recalled.

## ✓ VERIFIED SAFE — no action

- **Hook matchers.** v2.1.198 made hyphenated matchers exact-match instead of substring.
  Our five matchers are `Bash|Edit|Write`, `Bash`, `Edit|Write|MultiEdit|NotebookEdit`,
  `Edit|Write|MultiEdit`, `mcp__.*`. Per the spec's matcher table, a value of "only letters,
  digits, `_`, `-`, spaces, `,`, `|`" is an exact list, and anything containing another
  character is an unanchored JS regex — so `mcp__.*` is already the doc-prescribed form. The
  default-ON MCP prompt-injection sanitizer still fires. Nothing broke.
- **`StopFailure` output/exit code are IGNORED** (spec, verbatim). Our `on-stop-failure.py`
  works purely by side effect (`rate-limited.flag` touch + timestamp write); its only `print`
  is a stderr diagnostic. Unaffected.
- **Auto mode now blocks tampering with session transcript files** (Week 28). We READ
  transcripts in three places; grep found ZERO write sites. Unaffected.
- **v2.1.196: a scheduled fire only runs skills Claude may self-invoke**; built-ins arrive as
  plain text. This FORMALIZES our issue-#70 workaround rather than breaking it — our cron
  prompt invokes no skill, and the markers route to `/janitor-*` plugin skills, which are
  model-invocable.
- **Scheduled tasks are session-scoped, and there is NO `durable` parameter.** The doc says it
  outright: *"Tasks are session-scoped: they live in the current conversation and stop when you
  start a new one."* This CONFIRMS the retraction already committed (a4d6995, a87ad58, 92e2953).

## ✗ CORRECTED — a claim I made from memory and had to retract

I asserted `/goal` cannot survive a rate limit because it is a Stop hook and `StopFailure`
fires *instead of* `Stop`. The USER contradicted me from direct observation, and the doc
proved them right: **changelog v2.1.207 — *"Transient server rate-limit errors (429s unrelated
to your usage limit) are now retried automatically with backoff for subscribers instead of
failing the turn."*** A transient 429 never ends the turn, so `Stop` fires and `/goal`
continues; compaction likewise doesn't end a turn. The only surviving (and still UNVERIFIED,
`? INFERRED`) case is a genuine usage-limit exhaustion. Do not restate it as fact.

## THE FINDING — our hook surface is 10/31 events and 1/5 handler types

The spec lists **31 hook events** and **5 handler types** (`command`, `http`, `mcp_tool`,
`prompt`, `agent`). We register **10 events** and use **only `command`**. High-value gaps:

| Event (unused) | Why it matters to the janitor |
|---|---|
| `FileChanged` | *"When a watched file changes on disk. The `matcher` field specifies which filenames to watch."* Paired with `SessionStart`'s `watchPaths`, this makes several POLLING detectors event-driven (dirty-tree, tracked-ignored, project-memory-tracked). |
| `ConfigChange` | *"When a configuration file changes during a session."* Directly replaces the `settings-scope-drift` / `mcp-config-drift` polling. |
| `SessionEnd` | *"When a session terminates."* We have no teardown hook at all — the USER-memory mirror sync and state cleanup belong here. |
| `PostToolBatch` | *"After a full batch of parallel tool calls resolves, before the next model call."* A far cheaper place for the token-budget guard than PreToolUse-on-every-call (see TRDD-K1RJUYGK). |
| `PostToolUseFailure`, `PermissionDenied`, `Notification`, `CwdChanged`, `InstructionsLoaded` | Unevaluated; each is a candidate to replace a poll. |

Also unused and directly relevant:
- **`SessionStart` decision fields** — `initialUserMessage`, `watchPaths`, `sessionTitle`,
  **`reloadSkills`**. `reloadSkills` overlaps our entire `[janitor-reload-skills]` +
  keystroke-injection machinery (at session start, at least).
- **`Stop`/`SubagentStop` accept `hookSpecificOutput.additionalContext`** for *"non-error
  feedback that continues the conversation"* — this is exactly how `/goal` is built, and it is
  a zero-idle-gap alternative to `janitor-keep-going`'s heartbeat nudge. **CAUTION:** per
  TRDD-K1RJUYGK, a Stop-hook `additionalContext` is a strippable block; `hook: Stop` is the #2
  cache-break offender on this machine ($17.90/session). Do NOT adopt it without bounding the
  injection count.
- **`terminalSequence`** — the sanctioned way to emit a bell/notification/window-title
  (*"Use this instead of writing to `/dev/tty`, which is unavailable to hooks"*).

## Cron jitter — our cadence math is optimistic

Doc: *"Recurring tasks fire up to 30 minutes after the scheduled time (or up to half the
interval, for tasks that run more often than hourly)."* So `*/5` can drift +2.5 min and `*/30`
up to +15 min. TRDD-0QQX9H0G claims the FAST tier leaves recovery latency unchanged — true for
FREQUENCY, but the worst-case GAP is 7.5 min, not 5. (Note: the `CronCreate` tool description
says 10%/max-15-min, which CONTRADICTS the docs page. Do not depend on either number.)

## Channels — CLOSED, do not pursue

Channels looked like the sanctioned replacement for `fleet_inject`'s keystroke injection.
**The USER ruled them out: "channels are not very stable now. let's count on ai-maestro
messaging system, that never fails."** The fleet-injection replacement path is **AMP**, not
channels. Do not re-open without new user direction.

## NEXT ACTION

Nothing is shipped by this TRDD — it is the audit record. Spawn NPTs for the items worth
doing, in this order:
1. `SessionEnd` teardown hook (we have none).
2. `ConfigChange` / `FileChanged` to retire the polling scope-drift detectors.
3. Reconcile the jitter claim in TRDD-0QQX9H0G's docs.
Do NOT adopt any new `additionalContext`-emitting hook until TRDD-K1RJUYGK's injection-budget
discipline is applied to it.
