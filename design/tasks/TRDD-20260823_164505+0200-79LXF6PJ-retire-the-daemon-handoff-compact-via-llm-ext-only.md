---
trdd-id: 79LXF6PJ
title: retire the daemon-composed handoff and route every compaction through the llm-externalizer
column: todo
created: 2026-08-23T16:45:05+0200
updated: 2026-08-23T16:45:05+0200
current-owner: janitor-main-session
task-type: refactor
severity: high
scope: project
approval-tier: 3
release-via: publish
relevant-rules: []
npt: []
eht: []
external-refs: []
implementation-commits: []
---

# Retire the daemon-composed handoff; compact only via the llm-externalizer

## ⏵ STATE — READ THIS FIRST ON RESUME

**Not started. USER directive, 2026-08-23 — verbatim, because paraphrase has already cost this
line of work several retractions:**

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

**NEXT ACTION:** settle the blocking unknown in "Open questions" #1 (the auto-compaction disable
mechanism) — everything else is downstream of it, and nothing should touch `~/.claude/settings.json`
until it is verified rather than guessed.

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

1. **What actually disables auto-compaction?** The directive says "an env var added to
   `~/.claude/settings.json`" — but env vars and settings keys are different surfaces, and a
   `claude-code-guide` lookup for this FAILED (`Prompt is too long`). **UNVERIFIED. Do not write a
   key into the user's settings.json on a guess.** Needed: exact name, type, scope, precedence.
2. **What happens at the context limit with auto-compaction off?** Error, refused turn, silent
   truncation? This decides whether the llm-ext path is a *replacement* or merely a *race*.
3. **Does the llm-ext summary really end with a pending-tasks section?** The directive says it
   does. Verify against real output before relying on it as the handoff.
4. **What triggers the llm-ext compaction if not the daemon?** If the answer is still the daemon,
   the daemon is not being removed — it is being repointed, which is a much smaller change.
5. **Does `/janitor-write-handoff` survive?** The directive says keep the agent handoff. If kept,
   writer #3 still writes the shared path unconditionally and still needs D's treatment.

## Acceptance

- [ ] Q1 answered from documentation, not inference; the settings change applied only after that
- [ ] the daemon's compose is removed ONLY in a change that also delivers the replacement path
- [ ] an idle unattended session is proven to still be resumable after the change (the drill that
      TRDD-1QJIZFFW box 2 already defines — an AUTOMATED run, not a hand-typed one)
- [ ] TRDD-5RXBI65T is re-columned or closed honestly against whichever option ends up shipping
- [ ] token saving is MEASURED, not asserted — the directive's main benefit claim

## Notes and lessons learned

[^1]: [id: LESSON-79LX-1, status: active, keywords: cheap_autocompose_handoff_is_useless daemon_writes_handoff remove_daemon_handoff llm_ext_compaction_instead disable_auto_compaction, ocd: 2026-08-23, lmd: 2026-08-23]
    DO NOT remove the daemon's handoff composer before its replacement is live, BECAUSE the
    composer is what makes an unattended `/clear` recoverable, and `/clear` cannot be undone. DO
    ship removal and replacement in one change, with the idle-session drill as the gate.
