---
trdd-id: K1RJUYGK
title: The janitor's own PreToolUse hooks are the machine's #1 prompt-cache breaker
column: dev
created: 2026-07-13T10:17:16+0200
updated: 2026-07-13T12:05:00+0200
current-owner: janitor-session
task-type: bugfix
severity: critical
relevant-rules: [3]
supersedes-approach-of: YRPUSIFY
---

# The janitor's own PreToolUse hooks are the machine's #1 prompt-cache breaker

## ⛔ ATTRIBUTION RETRACTED (2026-07-13, same day) — READ THIS BEFORE THE NUMBERS BELOW

**The FIX is right. The BLAME is not proven.** Everything below attributing `hook:
PreToolUse:Bash` ($23.05 machine-wide / $8.60 in one session / "the #1 cache-break offender") to
the janitor is **NOT ESTABLISHED**, and the early-session breaks are **provably NOT ours**:

1. `agentlenspro`'s `hook: <Event>` label names the **event BOUNDARY at which a changed block was
   observed — NOT the component that emitted it.** Proof (deductive, no measurement needed): the
   hooks spec says `StopFailure` output *"and exit code are ignored"*, so no StopFailure hook can
   inject anything — yet AgentLens reports a `hook: StopFailure:rate_limit`
   `INJECTED_BLOCK_CHANGED` break ($5.45). A label that can name a boundary where injection is
   *impossible* is not an accusation against a hook. (Full argument: TRDD-SLFMG704.)
2. **Our two PreToolUse hooks are SILENT at low context** — the advisory is gated at ≥60% and
   token-budget is silent on an idle turn (both verified by running them against synthetic
   payloads: empty stdout). Yet the `hook: PreToolUse:Bash` breaks in session c8a95d7e begin at
   **turn 3**, when context was low. **They cannot have been ours.**
3. Claude Code injects its OWN `<system-reminder>` blocks around tool calls (e.g. the recurring
   *"The task tools haven't been used recently…"* reminder, and a large skills catalogue) — those
   are strippable blocks from no hook at all, and they are a far better fit for the early breaks.

**What SURVIVES, and why the fix still ships:** our hooks *did* emit `additionalContext` on every
tool call above 60% (verified in source). Per-tool-call injection is dangerous on first
principles — the host strips the block later and the strip re-bills the cached suffix — so
bounding the injection COUNT is correct regardless of how much of that $23 was ours. The fix
costs nothing and removes a real hazard. It is the *headline attribution* that was unearned.

**THE ONLY PROOF that settles it:** publish the fix, then re-run
`agentlenspro get_cache_break_report --sessionId <new session>` and see whether
`hook: PreToolUse:*` leaves `topOffenders`. If it does NOT, the remaining breaks at that
boundary are the host's and we were never the cause. Do not claim this fixed until then.

## ⏵ STATE — the original (over-claimed) finding, kept for the record — 2026-07-13

**MEASURED, not theorized** — the NUMBERS below are real (they come from Anthropic's own
`cache_creation`/`cache_read` figures via `agentlenspro get_cache_break_report`). It is the
ATTRIBUTION of them to the janitor that is retracted above. Read both.

- **Machine-wide #1 offender:** `hook: PreToolUse:Bash` — cause `INJECTED_BLOCK_CHANGED` —
  **893 occurrences, 4,959,149 wasted tokens, $23.05.** Larger than `IDLE_TTL_EXPIRY`
  ($13.47) and the `skill catalog` ($9.50).
- **This session alone** (c8a95d7e, opus-4-8): 2,406 breaks, 22.6M wasted tokens, **$129.91**
  (98% hit rate — the breaks are a costly tail). Janitor-owned share ≈ **$19**:
  `PreToolUse:Bash` $8.60 (712x), `SessionStart:compact` $6.31, `PreToolUse:Write` $4.48.
- **Attribution is airtight.** `INJECTED_BLOCK_CHANGED` appears under SIX different tool
  labels (Bash, Monitor, WebFetch, Edit, Read, Write) → the injector is a **no-matcher**
  PreToolUse hook. An enumeration of every PreToolUse hook registered machine-wide (user
  settings + all 35 plugins) shows the **only** no-matcher ones are ours:
  `pre-tool-context-usage.py` and `pre-tool-token-budget.py`. Both emit `additionalContext`
  (verified in source).

## THE LOAD-BEARING FINDING — TRDD-YRPUSIFY's bucketing CANNOT work

YRPUSIFY diagnosed this as "the injected TEXT is unique per call" and fixed it by BUCKETING
the volatile numbers (`_bucket_pct` → "~70%", `_bucket_tokens` → "~40k") so two calls in the
same band emit byte-identical text. **That is a misdiagnosis, and the data falsifies it:**
bucketing is live in EVERY cached version (0.31.0 … 0.41.0, verified by grepping the cache),
and this session still took **712 `PreToolUse:Bash` breaks**.

The mechanism (from our OWN upstream issue, yvgude/lean-ctx#778, which the janitor's sibling
Claude authored and which I failed to apply to ourselves):

> "The injection itself is cheap — it appends at the transcript tail. The damage comes later:
> Claude Code **strips stale system-reminder blocks retroactively, in place, mid-transcript**.
> That mutation lands deep inside the cached prefix. Everything after the mutated byte
> re-bills as `cache_creation`. … **No injection → nothing to strip → no break.**"

The cost is **Claude Code deleting the block later**, which mutates the prefix *no matter what
the text said*. Stabilising the wording of a block that gets stripped anyway changes nothing.
Bucketing addresses a property (text stability) that is not the cause.

**Corollary: there is no "cheap" per-tool-call `additionalContext`.** Any PreToolUse/PostToolUse
hook that injects context seeds a strippable block. The only safe injection budget is
approximately ZERO per tool call.

## The irony worth remembering

The janitor filed #778 against lean-ctx for exactly this, got it fixed (v3.9.5, default
`inject_context = false`), recorded a global rule about it — and shipped the same bug itself,
in a hook whose stated purpose is *to reduce token bleed*. The guard was feeding the fire it
was watching. (Related: [[feedback-a-check-that-can-never-pass]] — a mechanism that defeats
itself.)

## NEXT ACTION

Kill the per-tool-call `additionalContext` in both no-matcher PreToolUse hooks:

1. **`pre-tool-context-usage.py`** — the ADVISORY tier (`pct >= suggest_pct`, currently fires
   on EVERY tool call once ≥60%) must stop emitting `additionalContext`. Keep the ENFORCEMENT
   tier (`permissionDecision: deny` + auto-compact at ≥85%) — it is a decision field, fires at
   most once per compaction episode, and it is the part that actually saves the session.
2. **`pre-tool-token-budget.py`** — same: the advisory `additionalContext` nudge goes; the
   opt-in hard-tier `deny` of a `Task`/`Agent` spawn stays.
3. Preserve the human-facing signal via `systemMessage` (user-visible, NOT injected into model
   context → no strippable block) and/or the statusline, which already renders the %.
4. If a model-visible nudge is judged essential, it must be **latched to at most once per
   session per tier** — not per tool call. Budget: ≤2–3 strippable blocks per session, not 712.

**FALSIFICATION REQUIRED before claiming this fixed:** re-run
`agentlenspro get_cache_break_report --sessionId <new session>` after the change and show
`hook: PreToolUse:*` is GONE from `topOffenders`. A green unit test is not proof — the prior
fix had tests and was still wrong.

## NOT ours (do not "fix" these here)

Other large offenders in the same report belong to other components: `MODEL_SWITCHED` ($27.33),
`hook: Stop` ($17.90), `hook: PostToolBatch` ($11.51 — the janitor registers no PostToolBatch
hook), `skill catalog` ($12.30), `IDLE_TTL_EXPIRY` ($17.86). Worth reporting upstream/to the
owning plugins separately; out of scope for this TRDD.

## Notes

- AgentLens's own remediation hint: *"Move this volatile injected block (hook/file/rule/memory)
  into the message suffix, after the last cache breakpoint."*
- lean-ctx was investigated and CLEARED: fix present (installed 3.9.7 ≥ fixed-in 3.9.5), not
  registered as an MCP server, zero hooks in settings, and its proxy has served 0 requests.
