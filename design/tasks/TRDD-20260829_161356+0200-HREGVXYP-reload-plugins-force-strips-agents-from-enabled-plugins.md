---
trdd-id: HREGVXYP
title: reload-plugins --force strips agents from plugins it did not reload and the heartbeat rule misdiagnoses it
column: backburner
blocked-by: []
created: 2026-08-29T16:13:56+0200
updated: 2026-08-29T21:52:00+0200
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

## ⏵ 2026-08-29 21:40 — CONTROLLED RELOAD, before-state recorded (scope item 1)

Doing the measurement the card asks for, because the cost of NOT doing it has become concrete:
**four** memory markers (`split`, `enrich`, `repair`, `atomize`) have now been emitted this
session and none could run. That is no longer a hypothetical registry gap, it is a chore backlog.

The hypothesis worth testing: the reload that stripped the registry rescanned exactly ONE plugin
(`perfect-skill-suggester`, the one with an update). Since then **the janitor itself went
3.3.26 → 3.4.1**, so a reload now should rescan the janitor — and if the registry is REPLACED by
what the rescanned plugins contribute, this one should bring its three agents back.

**BEFORE-STATE, recorded now so the after is comparable:**

- 43 agent types available; **zero** `ai-maestro-janitor:*` among them.
- `enabledPlugins` — 38 true, janitor included. Cache — `ai-maestro-janitor/3.4.1/agents/` holds
  all three `.md` files. So: install intact, registry thin (the card's own three-branch verdict).
- Also absent: every `claude-plugins-validation:*`, `llm-externalizer:*`, `plugin-dev:*`,
  `pr-review-toolkit:*`, `fable-advisor:advisor`, `code-simplifier`, `code-auditor-agent`.

**Predictions, so the result cannot be rationalised after the fact:**

- If REPLACE-by-rescanned-set is right, the janitor's 3 agents return and most others stay gone.
- If reload is ADDITIVE and the first loss was something else, all 36 return.
- If nothing returns, the loss is not reload-scoped at all and the card's model is wrong.

### ✅ RESULT — all 36 returned, and the mechanism is now clear

```
reload #1   Reloaded:  1 plugin  ·   1 skill ·  43 agents ·  0 hooks · 0 MCP · 0 LSP
reload #2   Reloaded: 39 plugins · 379 skills · 79 agents · 50 hooks · 1 MCP · 9 LSP
```

**The registry is REPLACED by whatever the rescan produces — the variable is HOW MANY PLUGINS
GET RESCANNED, and that is not stable between invocations.** Reload #1 rescanned ONE plugin (the
only one with a pending update) and replaced the whole registry with its single agent set;
reload #2 rescanned all 39 and restored everything, the janitor's three included.

**I under-reported the first loss.** The card said "36 agent types" — but reload #1 also reported
**0 hooks, 0 MCP servers and 0 LSP servers**, against 50 / 1 / 9 now. The session had been
running with NO plugin hooks since 16:12. Agents were merely the visible casualty because
spawning one fails loudly; a missing hook fails silently, which is worse and went unnoticed for
five hours. **Read every column of that line, not the one you are looking for.**

Prediction 2 was closest, but "additive" is the wrong word for it: nothing merged. A full rescan
happened to reproduce the full set.

**What this does NOT settle:** why a reload rescans 1 plugin sometimes and 39 others. The
plausible reading is that #1 took an incremental "changed plugins only" path (fired seconds
after `perfect-skill-suggester` updated) while #2 came after the janitor itself moved
3.3.26 → 3.4.1. That is a hypothesis, not a measurement, and this card has already had two
confident hypotheses fail — do not write it up as fact.

## Scope

1. ~~**Establish the harness behaviour before designing around it.**~~ **DONE 2026-08-29 —
   measured, see the RESULT above. Replace-not-merge is confirmed; the variable is how many
   plugins a given reload rescans (1 vs 39), and THAT remains unexplained.**

   **Static inspection is a DEAD END — do not retry it (measured 2026-08-29).** The CLI at
   `~/.local/share/claude/versions/2.1.251` is a 197 MB Mach-O binary, not readable JS. `strings`
   yields 317,926 lines of minified blobs, and the `Reloaded: ` format string sits on a line of
   its own (11 bytes, no surrounding code) — the literals are pooled away from the logic that
   uses them, so there is no context to slice. The only method left is the controlled reload,
   which degrades whichever session runs it; that is why this item is still open rather than
   merely unattempted.
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
  a recoverable session becomes a lost one. **(2026-08-29 21:40: step 1 is now being RUN — a
  deliberate, recorded measurement with predictions written down first, not a hopeful retry.
  The difference is that this one has a before-state and cannot be rationalised afterwards.)**
- **Do not read only the agent count on the `Reloaded:` line.** The first reload also reported
  0 hooks / 0 MCP / 0 LSP and this card recorded only the agents, so a five-hour window with NO
  plugin hooks went unnoticed. A missing agent fails loudly; a missing hook fails silently.
- **Do not judge plugin health with `claude plugin list`'s Status column.** Run from `/tmp`
  during this investigation it reported **every** plugin — including ones whose hooks had just
  fired in this very session — as `✘ disabled`. It answers some narrower question than "is this
  plugin active for that session". `enabledPlugins` in `settings.json` was the reliable source.

## Acceptance

- [x] The replace-vs-merge registry behaviour is measured, not assumed, and written down —
      REPLACE confirmed by a before/after with predictions committed first (`fda5d5e8`).
- [ ] Why a reload rescans 1 plugin vs 39 is explained. Still open, and explicitly NOT to be
      written up from the plausible-sounding incremental-path guess.
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
