---
trdd-id: HREGVXYP
title: reload-plugins --force strips agents from plugins it did not reload and the heartbeat rule misdiagnoses it
column: backburner
blocked-by: []
created: 2026-08-29T16:13:56+0200
updated: 2026-08-29T16:33:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 3
severity: HIGH
effort: S
min-approval-requirement: none
task-type: bugfix
labels: [reload, agents, dispatch, heartbeat-protocol, diagnosis]
release-via: publish
test-requirements: [unit]
---

# TRDD-HREGVXYP — `/reload-plugins --force` strips agents from plugins it did not reload, and the heartbeat rule misdiagnoses it

## What happened, measured

A `[janitor-reload]` marker fired legitimately (daemon generation `1788012323`, reason
`plugin-update@perfect-skill-suggester@emasoft-plugins`). I ran `/janitor-reload-plugins`, which
typed `/reload-plugins --force`. It reported:

```
Reloaded: 1 plugin · 1 skill · 43 agents · 0 hooks · 0 plugin MCP servers · 0 plugin LSP servers
```

and the harness immediately announced **36 agent types no longer available**, spanning **nine
enabled plugins** — including all three of the janitor's own:

- `ai-maestro-janitor:janitor-memory-subconscious-agent`
- `ai-maestro-janitor:janitor-repair-agent`
- `ai-maestro-janitor:janitor-security-agent`

plus every `claude-plugins-validation:*` agent (17), every `llm-externalizer:*` agent (6),
`fable-advisor:advisor`, the three `plugin-dev:*`, the six `pr-review-toolkit:*`,
`code-simplifier:code-simplifier`, `code-auditor-agent:*`, and
`perfect-skill-suggester:pss-agent-profiler` — the agent of the very plugin the reload was for.

### It is a registry loss, not an install loss — verified three ways

1. **Settings**: `~/.claude/settings.json` `enabledPlugins` has **38 entries set `true`**,
   `ai-maestro-janitor@ai-maestro-plugins` among them. Nothing was disabled.
2. **Disk**: every dropped agent's definition file is still in the plugin cache —
   `ai-maestro-janitor/3.3.26/agents` (3 files), `fable-advisor/1.4.0/agents` (1),
   `claude-plugins-validation/5.13.0/agents` (14).
3. **The reload's own count**: it reloaded **1** plugin out of 38 enabled, then rebuilt the
   session's agent list to 43 — dropping the agents of the 37 it did not rescan.

So the reload is not additive. It appears to REPLACE the agent registry with what the single
rescanned plugin contributes, rather than merging into what was already registered.

## Why this is HIGH and not cosmetic

**The janitor's own dispatch cannot execute.** `janitor-heartbeat-protocol.md` routes every
`[janitor-memory-*]` and `[janitor-ticket]` marker to exactly these agents. After a reload they
are unspawnable, so the next such marker fails.

**And the heartbeat rule then diagnoses it WRONG.** Its instruction reads:

> Both names fail + the error lists NO `ai-maestro-janitor:*` agents ⇒ the PLUGIN is unavailable
> (stale/partial install, janitor#232) — not a naming bug: report it, try `/reload-plugins`,
> leave the pending JSON so the marker re-fires.

Every clause of that antecedent is TRUE here, and the conclusion is FALSE: the plugin is
installed, enabled, and complete on disk. Worse, the prescribed remedy is **`/reload-plugins` —
the very operation that caused the loss.** An agent following the rule faithfully would reload
again, plausibly stripping the registry a second time, and report a stale install that does not
exist.

That rule was written to tell a missing plugin apart from a mistyped agent name. It does it by
asking whether the error lists any `ai-maestro-janitor:*` agents — a test that cannot see this
third case, where the plugin is present and only the session's registry is thin.

## Scope

1. **Establish the harness behaviour before designing around it.** Is the replace-not-merge
   registry a `--force` effect, a bug, or intended? One controlled reload with the agent list
   captured before and after answers it. Do not build a workaround on top of an unverified model
   of someone else's tool.
2. **Give the heartbeat rule a third branch.** Distinguish *plugin missing* from *registry thin*
   with a check that can actually tell them apart — the agent files on disk plus the
   `enabledPlugins` entry — and prescribe different remedies. Today both roads lead to
   `/reload-plugins`.
3. **Do not prescribe a reload as the remedy for a reload-induced fault.** Whatever the third
   branch recommends, it must not be the operation under suspicion.
4. **Reconsider what the reload skill promises.** `janitor-reload-plugins` says a reload "does
   NOT discard the conversation — it swaps plugin code in place — so there is no resume directive
   and nothing is lost." Measured here, something IS lost: 36 agent types. The skill's own
   cost model weighs cache invalidation only, and this is a capability cost it does not mention.

## What NOT to do

- **Do not reload again to "fix" it** until step 1 has established what a reload does to the
  registry. Repeating the operation that caused a fault, hoping for a different outcome, is how
  a recoverable session becomes a lost one.
- **Do not judge plugin health with `claude plugin list`'s Status column.** Run from `/tmp`
  during this investigation it reported **every** plugin — including ones whose hooks had just
  fired in this very session — as `✘ disabled`. It answers some narrower question than "is this
  plugin active for that session". `enabledPlugins` in `settings.json` was the reliable source.

## Acceptance

- [ ] The replace-vs-merge registry behaviour is measured, not assumed, and written down.
- [x] `janitor-heartbeat-protocol.md` distinguishes *plugin absent* from *registry thin*, with a
      disk + `enabledPlugins` check, and does not send either case to `/reload-plugins` blindly.
      Done 2026-08-29, and it cost NEGATIVE bytes: the shipped-rules floor went 53,696 → 53,694 B
      (headroom 4 → 6 under the 53,700 cap, `test_rules_installer.py` green, 36 passed). The old
      text spent most of its length explaining how to tell TWO cases apart; stating three
      outcomes plainly was shorter than arguing for two. **A rule that grew a case does not have
      to grow — the floor cap is a real constraint and it was satisfiable by writing better, not
      by moving the text to `references/`.**
- [x] The `janitor-reload-plugins` skill states the capability cost alongside the cache cost.
      Done 2026-08-29 — it also now says not to reload again to fix it, and names the two
      checks (`enabledPlugins`, the cache `agents/` dir) that tell a thin registry from a
      missing install. Done AHEAD of scope item 1 deliberately: the skill asserted "nothing is
      lost", and that is false as measured regardless of WHY the registry is replaced. A false
      assertion in a skill an agent follows unattended does not get to wait for a root cause.
- [x] Regression test: a dispatch marker whose agent is unregistered but whose plugin is
      installed reports "registry thin", not "plugin unavailable".
      Done 2026-08-29 — `test_missing_agents_branch_never_prescribes_the_reload_that_causes_it`
      (37 passed). It pins BOTH halves, since either can rot alone: the two discriminating
      reads must be named, and the reload must not be prescribed in that row. **Verified it
      fails on the pre-fix text** — all four assertions trip. A regression test never run
      against the bug it describes is a decoration.

## Notes and lessons learned

- 2026-08-29 — **A remedy that is also the cause is worse than no remedy.** The heartbeat rule's
  answer to "no janitor agents in the error" is `/reload-plugins`, and a reload is what emptied
  the registry. A rule that prescribes the suspected cause turns one failure into a loop, and it
  reads as authoritative while doing it. **Whenever a rule prescribes an action, ask what happens
  if that action is what produced the symptom.**
- 2026-08-29 — **`claude plugin list` Status said `disabled` for 76/76 plugins, including live
  ones.** I nearly reported the janitor as disabled on it. The tell was internal contradiction:
  the janitor's hooks had fired that same turn. **A measurement that contradicts something you
  just watched happen is wrong about the measurement, not about the world** — check the method
  before believing the number. `enabledPlugins` in `settings.json` answered it in one read.
- 2026-08-29 — **The reload was still the right call, and this does not retract that.** The
  marker was legitimate, the ack was already spent, and post-compaction was genuinely the cheapest
  moment. The defect is that the skill's cost model priced only the prompt cache, so a real cost
  it does not model went unweighed. **Knowing an operation's price is not the same as knowing its
  effects.**
