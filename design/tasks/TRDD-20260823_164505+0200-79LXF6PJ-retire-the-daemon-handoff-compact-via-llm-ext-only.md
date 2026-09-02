---
trdd-id: 79LXF6PJ
title: retire the daemon-composed handoff and route every compaction through the llm-externalizer
column: blocked
pre-block-column: testing
blocked-by: [TRDD-O7UCNNN2]
created: 2026-08-23T16:45:05+0200
updated: 2026-09-02T03:09:00+0200
current-owner: janitor-main-session
task-type: refactor
severity: high
scope: project
approval-tier: 3
release-via: publish
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-XCJFCJUX, TRDD-1QJIZFFW]
implementation-commits: [155833b3]
---

# Retire the daemon-composed handoff; compact only via the llm-externalizer

> **2026-09-02 — re-blocked on TRDD-XCJFCJUX.** Code shipped (3.4.3 installed, daemon restaged);
> the one open box (an idle unattended session proven resumable after an AUTOMATED clear) is the
> same drill TRDD-1QJIZFFW box 2 needs, and that drill cannot fire: the launchd daemon reads no
> `CLAUDE_PLUGIN_OPTION_*` (measured), so the enabled lever never reaches it. Nothing to do here
> until XCJFCJUX's loader is published and restaged; then one drill closes this card too.

## ⏵ STATE — READ THIS FIRST ON RESUME

### ⏵ 2026-08-26 — "Not started" is WRONG. Both concrete asks already landed.

Found by cross-check: TRDD-5RXBI65T's STATE says the daemon writer was *"retired entirely —
TRDD-79LXF6PJ; it no longer composes a handoff at all"*, while this card claimed nothing had
begun. Verified in the artifacts, not from either card:

| the directive's ask | state | evidence |
|---|---|---|
| remove the daemon's cheap autocompose | **DONE** | `external_handoff_clear.py:19-22` — *"the composed handoff that used to be the network-free fallback is gone"*, citing this card's own id, with the consequence made explicit: **no summary means NO CLEAR** |
| disable Claude Code's auto-compaction | **DONE** | `~/.claude/settings.json` → `"autoCompactEnabled": false` |

**What is NOT reached is the directive's END STATE** — *"if all compactions are done via the
llm-externalizer, we don't need any handoff anymore"*. Not all compactions go through it today,
because the external-clear lever is OFF (`EXTERNAL_IDLE_CLEAR_ENABLED=false`) pending the 3.4.0
publish. So the removals are done and the claim they enable cannot yet be verified.

**Worth stating plainly: the current configuration is the risky middle of this migration.**
Claude Code's auto-compaction is disabled AND the llm-ext replacement is disabled, so right now
nothing rescues a session that fills its context — the fallback was removed before its
replacement was switched on. That is a deliberate, temporary consequence of the resume-storm
lever pull, not an oversight, but it should not be left standing longer than the publish.

`todo` → `blocked` on the same 3.4.0 publish. A card whose code has shipped is not "todo", and
one whose remaining verification nobody can perform is not in progress either.

### The USER directive, 2026-08-23 — verbatim, because paraphrase has already cost this
line of work several retractions:

> are you saying that the daemon is tasked to generate an autocompose handoff? the cheap
> autocompose is useless. remove such function from the daemon. only use the good one written by
> the agent. in case of forced compaction, when there is no time or no remaining tokens to write
> an handoff by the agent/claude (the very scenario for which the daemon cheap handoff was
> introduced), we already have a solution: never use the claude code compaction again, but always
> use the llm-externalizer compaction. the auto compaction can be disabled using an env var added
> to the ~/.claude/settings.json. If all compactions are done via the llm-externalizer, we don't
> need any handoff anymore. The generated summarized context injected by the hook after the
> /clear include already a section in the end with the most important tasks still pending, a sort
> of concise handoff. this will also save lots of token otherwise used by the compaction, since we
> use instead the free models of the llm-externalizer to compact instead.

**USER chose option 1 (2026-08-23), after being shown option 2:** remove the daemon's handoff
composition entirely, paired with the llm-ext compaction replacement. Option 2 (keep the free
mechanical index, strip only `session-summary` + the raw `Recent turns` tail) was offered
explicitly and declined. Do not re-litigate it.

**DONE:** Q1 settled and applied — `"autoCompactEnabled": false` is in `~/.claude/settings.json`
(backup `/tmp/settings.json.bak-20260823_165008+0200`, JSON re-validated).

**NEXT ACTION:** read TRDD-1QJIZFFW's STATE block, then make the post-`/clear` payload the
llm-ext **session-summary** instead of the composed handoff. The removal may not land before that
payload works — see "The load-bearing risk".

## Amendment, USER 2026-08-23 — skills re-injection, and who owns compaction

> as i said, lets make the compaction always handled by the janitor instead than by the claude
> code harness. and do it always via the llm-externalizer. the session summary already includes a
> concise handoff-like section at the end, so its completely self sufficient. also the active
> skills must still be re-injected in the clean context in full, and right before the summarized
> context (since the context summary certainly will reference them).

Two requirements, one of them new:

1. **The janitor owns compaction; the harness never does.** Satisfied on the harness side by
   `autoCompactEnabled: false` (applied). The janitor's external-clear + llm-ext summary is now
   the ONLY compaction path.
2. **NEW — the post-`/clear` injection is ORDERED: active skills IN FULL, then the summary.**
   Rationale given: the summary will reference the skills, so a summary injected without them
   dangles. This makes the injection a two-part document with a mandatory order, not a blob.

**INTERPRETATION, stated because it is load-bearing and was not specified:** "active skills" is
read as *the skills that were INVOKED in the pre-`/clear` session* — those whose `SKILL.md` was
actually in the context the summary describes, recoverable from the transcript's `Skill` tool
calls. The alternative reading (every enabled skill on the machine) is rejected: it would inject
tens of thousands of tokens of skills the session never touched, which defeats the point of
clearing. **If the owner meant the broader reading, this is the line to correct.**

## One correction the directive should be read against

**The daemon's handoff is ALREADY llm-externalizer-composed.** `lib/external_clear.py` carries a
full progress-gate around llm-ext summarization — `LLM_EXT_CONFIG_DIR`,
`session-summary-checkpoints`, per-chunk no-progress retry — and the live log shows real llm-ext
calls (`summary: ok on attempt 5`, preceded by five 600 s timeouts on 2026-08-22). It falls back
to a bare template ONLY when llm-ext fails (`:317 handoff degraded to template`).

So "cheap autocompose vs good agent handoff" is not the actual axis. Both use a model; the daemon
uses the free external one. The real differences:

| | daemon handoff | agent handoff |
|---|---|---|
| composed by | llm-ext, from the transcript on disk | the model, from what it was thinking |
| costs session tokens | no | yes |
| runs when the session is idle/unattended | yes | no — there is nobody to write it |
| ends in a `/clear` | yes | only if asked |

The directive is still coherent — the claim "we don't need any handoff anymore" rests on the
llm-ext SUMMARY replacing it, not on the daemon's index being bad. But anyone implementing this
should know they are removing an llm-ext-composed artifact, not a dumb template.

## The load-bearing risk

The daemon's compose exists so an **idle, unattended** session can be cleared with *something* to
resume from. A `/clear` is the one unrecoverable operation in this system. **Removing the compose
while the external clear still fires would clear sessions with nothing at all** — strictly worse
than the bug that started this. Therefore:

**The removal MUST land in the same change as the replacement, never before it.** Sequencing is
the whole risk here; the deletion is trivial.

## Effect on TRDD-5RXBI65T (this directive largely DISSOLVES it)

5RXBI65T is "two writers on one path". Option D (shipped in `0581b940`) gave each daemon write its
own filename. This directive proposes **removing the second writer entirely** — call it option E,
*eliminate the writer* — which is strictly stronger: with one writer there is nothing to clobber.

D is not wasted and should not be reverted: two sessions of ONE project share a state dir, so the
surviving agent-authored writer can still destroy its own predecessor (measured claim, not
theory — see 5RXBI65T). But 5RXBI65T must not be closed as "solved by D" if E lands.

## Open questions — all blocking, none guessed

1. ~~What actually disables auto-compaction?~~ **ANSWERED + APPLIED 2026-08-23.** Three surfaces:
   the settings key **`autoCompactEnabled`** (docs list its scope as "Any file"; it is what
   `/config` → *Auto-compact* writes), a per-session env var `DISABLE_AUTO_COMPACT` (named only in
   a search summary, **absent from the settings-reference page — lower confidence**), and the
   `/config` toggle itself. Whichever surface turns it off wins; the other cannot turn it back on.
   `/compact` keeps working manually. Applied as `"autoCompactEnabled": false` in
   `~/.claude/settings.json`. The directive said "env var" — it is a settings KEY; the env var is
   a separate surface.
2. **What happens at the context limit with auto-compaction off?** Error, refused turn, silent
   truncation? This decides whether the llm-ext path is a *replacement* or merely a *race*.
3. **Does the llm-ext summary really end with a pending-tasks section?** The directive says it
   does. Verify against real output before relying on it as the handoff.
4. **What triggers the llm-ext compaction if not the daemon?** If the answer is still the daemon,
   the daemon is not being removed — it is being repointed, which is a much smaller change.
5. **Does `/janitor-write-handoff` survive?** The directive says keep the agent handoff. If kept,
   writer #3 still writes the shared path unconditionally and still needs D's treatment.

## Acceptance

- [x] Q1 answered from documentation, not inference; the settings change applied only after that
      — `155833b3`; `~/.claude/settings.json` carries `"autoCompactEnabled": false`
- [x] the daemon's compose is removed ONLY in a change that also delivers the replacement path
      — one commit `155833b3` both retires `_compose`'s daemon call site and ships the
      skills-then-summary replacement + the hard "no summary → no clear" gate
      (`external_handoff_clear.py:250`, re-enforced in `main()`); 139 external-clear tests pass
- [ ] an idle unattended session is proven to still be resumable after the change (the drill that
      TRDD-1QJIZFFW box 2 already defines — an AUTOMATED run, not a hand-typed one)
      — **still open, and now UNBLOCKED**: 1QJIZFFW's gate (3.4.0 publishes + installs) discharged
      2026-08-29; the only remaining step is flipping
      `CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED` to `true` at a seam and letting one
      automated clear fire. This box closes when 1QJIZFFW box 2 closes — same run, one drill.
- [x] TRDD-5RXBI65T is re-columned or closed honestly against whichever option ends up shipping
      — 2026-08-29: option D shipped and is now INSTALLED (3.4.1 carries `lib/handoff_files.py`
      and the keyed-name skill); 5RXBI65T moved `dev` → `testing` with its 3.4.0 gate marked
      discharged and one observation left
- [x] token saving is MEASURED, not asserted — the directive's main benefit claim
      — **~693k–3.0M Claude-side input tokens per compaction event, ≈$4.33–$18.82 at Opus 5's
      $6.25/MTok.** The saving is ~100% because the new path issues **zero** Claude API calls:
      `_compose` → `ec.summarize_with_retry` → `run_llm_ext_summary`
      (`lib/external_clear.py:498`), whose only outbound call is a `subprocess` to the `llm-ext`
      CLI ($0 free-tier OpenRouter). Grepping both files for `anthropic|messages.create|claude
      api` returns nothing — verified here, not taken from the report.

      **Both bounds are bytes÷4 approximations, and both UNDERSTATE the real baseline.** Measured
      on a complete 12,042,268-byte transcript: ceiling 3,010,567 tokens (raw bytes), floor
      693,039 (message content only, 2,772,154 chars). The floor excludes the system prompt and
      tool definitions a real compaction turn also pays and which are not in the transcript at
      all. No exact tokenizer was available — `llm-ext` has no token-count verb.

      **The real run did NOT complete** (exit 124 at the 900 s budget), and it is still evidence:
      it produced 85,226 bytes of genuine partial summary, stderr shows real OpenRouter
      map-reduce progress and a 403 from a flaky free model with backoff. It stalled on free-tier
      flakiness — which does not touch the claim being measured, since the Claude-side cost is
      zero whether the external model finishes or not. Report:
      `reports/trdd-verify/20260829_224254+0200-79LXF6PJ-token-saving.md`

## Notes and lessons learned

[^1]: [id: LESSON-79LX-1, status: active, keywords: cheap_autocompose_handoff_is_useless daemon_writes_handoff remove_daemon_handoff llm_ext_compaction_instead disable_auto_compaction, ocd: 2026-08-23, lmd: 2026-08-23]
    DO NOT remove the daemon's handoff composer before its replacement is live, BECAUSE the
    composer is what makes an unattended `/clear` recoverable, and `/clear` cannot be undone. DO
    ship removal and replacement in one change, with the idle-session drill as the gate.

## Approval log

- 2026-08-29T22:30:00+0200 — UNBLOCKED. The blocker (TRDD-X4LJFTB4, GitHub push protection on the
  3.4.0 publish) was resolved and v3.4.0/v3.4.1 shipped; restored to the pre-block column.
