---
trdd-id: f12cae1a-1048-4c70-8acb-c7b59a84995a
title: janitor-security-agent — ONE agent for all security skills (detect + fix), heartbeat-suggested
column: published
created: 2026-06-23T20:14:03+0200
updated: 2026-06-23T20:48:39+0200
published-version: 0.17.0
published-at: 2026-06-23T20:47:00+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
priority: 2
severity: HIGH
effort: L
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
test-requirements: [unit]
audit-requirements: []
review-requirements: []
impacts: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor"]
---

# janitor-security-agent — the single security curator

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-23

**Goal (USER request, verbatim):** "when the janitor is armed, and finds security issues,
it should suggest to run the `janitor-security-agent`, a SINGLE AGENT FOR SECURITY able to
do every security skill (exactly like the janitor-memory-agent is ONE and able to execute
all memory skills)! If there is no such agent, or if you need to consolidate multiple agents
into one, do it! The skills that detect the security issues must also be able to fix them."

**The model to mirror:** `agents/janitor-memory-subconscious-agent.md` — ONE opus agent,
`skills: [...]` declaring every per-chore SKILL it loads, dispatched for ONE task at a time,
runs in its OWN context, returns one line + a report path. The `janitor-memory-*` skills are
PROCEDURES it loads, never separate agents.

**Survey facts (Explore agent, 2026-06-23):**
- 8 security skills: DETECT-only = supply-chain-watcher, credential-window-audit,
  fork-pr-cache-audit, skill-bundle-audit; DETECT+FIX = dependabot-doctor,
  github-workflow-doctor; FIX-only = github-workflow-create, branch-protection-setup.
- Only `workflow-security.py:226-230` currently suggests a skill (`/janitor-github-workflow-doctor`);
  the other 11 security detectors emit findings with NO remediation pointer.
- Memory dispatch: `memory-maintenance.py:14-19` emits a bare forge-proof `[janitor-memory-<chore>]`
  marker (own-line/exact; `state.sanitize_for_drift_line` defangs mimicry to `⟦…⟧`).

**Design decisions (load-bearing):**
1. **SUGGEST, do not silently auto-run.** Security fixes have real blast radius (workflows,
   branch protection, deps, credentials) — unlike memory edits. The heartbeat SURFACES a
   visible drift line ("→ Run /janitor-security-agent to triage + fix") rather than a bare
   silent-execute marker. (Auto-dispatch-when-autofix-on is a documented FOLLOW-UP, not v1.)
2. **The agent does detect + FIX, fail-safe.** It FIXES what is safe (dep bumps with tests,
   workflow hardening via zizmor, dependabot config, the ratified branch-protection baseline,
   prompt-injection sanitization) and FLAGS what needs a human (live credential ROTATION,
   anything destructive, anything touching production secrets / the shared owner identity).
   Never suppress a finding to pass a gate (CPV no-exempt philosophy); never auto-rotate creds;
   never force-push.
3. **One security domain per dispatch** (like memory's one-chore-per-launch) OR a full sweep —
   the caller names it; default to the domain that triggered the suggestion.
4. **"Skills must also fix":** the 4 DETECT-only skills get a `## Remediation (fix)` section so
   the fix capability is documented IN the skill (the agent + a human follow it), with the
   fail-safe gating above. The 2 detect+fix and 2 fix-only skills already fix.

## NEXT ACTION
Build in this order (TDD; parallel spark agents for the fan-out edits; orchestrator commits
sequentially):
1. **[me] `agents/janitor-security-agent.md`** — the consolidating agent (the core orchestration
   prompt). `skills:` = all 8 security skills. IRON RULES (fail-safe, no-suppress, never-rotate-
   creds-autonomously, one-domain-per-dispatch, own-context, report+one-line output).
2. **[me] `scripts/lib/security_helpers.py::security_agent_hint()`** — ONE source of truth for the
   canonical suggestion line + an opt-out gate (`CLAUDE_PLUGIN_OPTION_SECURITY_AGENT_HINT`,
   default on). + unit test.
3. **[parallel agents] wire `security_agent_hint()`** into the finding paths of the high-value
   security detectors (workflow-security — augment the existing pointer; mcp-rugpull,
   remote-credentials, supply-chain-fingerprints, repo-trust-score, package-manager-policy,
   historical-cache-scan, binary-magic-scanner, ai-context-poisoning, typosquat-watcher,
   provenance-audit). One line appended per detector when it has findings.
4. **[parallel agents] add `## Remediation (fix)`** to the 4 detect-only skills
   (supply-chain-watcher, credential-window-audit, fork-pr-cache-audit, skill-bundle-audit).
5. **[me] docs** — CLAUDE.md (agents inventory: now TWO agents; security-agent line), README,
   `dispatch.py` roster comment if needed.
6. **[me/agents] tests** — `tests/test_security_agent_hint.py` (the helper + gate); a structural
   test that `agents/janitor-security-agent.md` declares all 8 skills + valid frontmatter.
7. **publish.py --minor** (CPV --strict green) → /reload-plugins + /janitor-arm.

## DERIVED tasks / risks
- **Sprawl risk** (wiring 11 detectors): keep each edit to ONE appended line via the shared
  helper — no per-detector copies of the string. If sprawl grows, prefer a smaller high-value
  subset for v1 + document the rest as follow-up.
- **Agent frontmatter token caps** (CPV): description ≤ ~300 tokens; SKILL/agent body lean.
  Mirror the memory agent's length.
- **Forge-proofing:** the suggestion is a VISIBLE hint, NOT a bare silent-execute marker, so it
  needs no marker-mimicry defense — but the detector must still `sanitize_for_drift_line` any
  untrusted text it interpolates (paths/names) BEFORE appending the hint.
- **No new CRITICAL/MAJOR in CPV:** the agent .md + skills are prompt-only (no exec); the helper
  is pure. Re-run CPV --strict before publish.
- **"every security skill"** — verify the `skills:` list is the COMPLETE security set (8). Do not
  include non-security skills (memory/control/repomap).

## Durable artifacts to read before acting
- `agents/janitor-memory-subconscious-agent.md` — the exact ONE-agent pattern to mirror.
- `scripts/detectors/memory-maintenance.py` — the heartbeat dispatch/suggest template.
- `scripts/detectors/workflow-security.py:226-230` — the only existing security suggestion.
- `scripts/lib/security_helpers.py` — where `security_agent_hint()` lands.

## FOLLOW-UP (not v1)
- Auto-dispatch the agent as a background task when `autofix-on` (mirror memory's bare marker),
  gated separately from the suggest-default.
- Deepen each detect-only skill's remediation from "documented" to "executable script step".
