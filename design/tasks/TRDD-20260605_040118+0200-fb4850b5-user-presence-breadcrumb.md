---
trdd-id: fb4850b5-9443-4600-a9e0-038598db7d40
title: Host-level user-presence breadcrumb for MANAGER degraded-mode fallback
column: blocked
created: 2026-06-05T04:01:18+0200
updated: 2026-06-05T04:01:18+0200
current-owner: janitor-dev-session
assignee: janitor-dev-session
priority: 4
severity: LOW
effort: S
labels: [cross-plugin, presence, hooks, coordination]
task-type: feature
parent-trdd: null
blocked-by: []
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit, lint]
impacts: []
runtime-targets: [macos, linux]
last-test-result: not-run
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues/15"]
---

# TRDD-fb4850b5 — User-presence breadcrumb for MANAGER degraded-mode fallback

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-05

**What this is:** the MANAGER (assistant-manager) plugin asked the janitor (janitor#15,
a *proposal*, not a directive) to write a host-level user-presence breadcrumb the
`amama-presence-tracker` can read as a **server-unreachable fallback**. The janitor is the
natural writer — host-wide heartbeat, no main agent, survives when no MANAGER session is
open. Janitor **accepted** the contract (janitor#15 comment 4627474910).

**Agreed contract:**
- Path: `~/.aimaestro/state/user-presence.json`
- Shape: `{"last_user_input_epoch": <int>, "source": "janitor", "written_at_epoch": <int>}`
- `last_user_input_epoch` — bumped ONLY on genuine user input (NOT cron heartbeat).
- `written_at_epoch` — refreshed each heartbeat tick (liveness), independent of input recency.
- MANAGER tracker read order: (1) server `/api/users/me/presence` authoritative →
  (2) this breadcrumb if server down AND `written_at_epoch` < 30min stale → (3) `unknown`.
  MANAGER says step (2) is already wired on its side, pending this file existing.

**NEXT ACTION (BLOCKED — see "Why blocked"):** do NOT write the first byte until the
MANAGER confirms the final schema. The janitor's #15 reply explicitly asked whether they
want an extra `source_pid` or schema `version` field for forward-compat. Implementing
before that reply risks a redo. When they confirm (or decline extras), restore to `dev`
and implement.

**Implementation plan (when unblocked):**
1. `scripts/hooks/on-prompt-submit.py` (currently a clean no-op): read the prompt from
   stdin JSON; if it starts with a janitor/cron marker (`[janitor-heartbeat]`, any
   `[janitor-…]` directive) → return 0 WITHOUT bumping (cron-injected prompts are not user
   presence — the load-bearing trap the MANAGER flagged). Otherwise atomic-write
   (`tmp + os.replace`) the breadcrumb with `last_user_input_epoch = written_at_epoch = now`,
   `mkdir -p ~/.aimaestro/state` first.
2. `scripts/dispatch.py` heartbeat: refresh `written_at_epoch` (and `source`) each tick
   WITHOUT touching `last_user_input_epoch` — preserving the existing `last_user_input_epoch`
   if the file exists, seeding it absent/0 if the file is new. This is the liveness signal.
3. Test (`tests/test_user_presence_breadcrumb.py`): prove (a) a genuine prompt bumps
   `last_user_input_epoch`; (b) a `[janitor-heartbeat]` prompt does NOT bump it; (c) a
   heartbeat refresh updates `written_at_epoch` but leaves `last_user_input_epoch` intact;
   (d) atomic write (no partial file on failure). Real fs via tmp `HOME`, no mocks.
4. ruff clean; ride the next janitor release; ping janitor#15 with the commit SHA so the
   MANAGER confirms the on-disk shape before either side ships.

**Load-bearing facts:**
- The cron `[janitor-heartbeat]` prompt arrives as a UserPromptSubmit-shaped event —
  IDENTICAL channel to genuine typing. The ONLY discriminator is the prompt TEXT prefix.
  Get this wrong and the breadcrumb reports the user "present" every 5 min forever.
- `~/.aimaestro/state/` is a deliberate cross-plugin host path — NOT `${CLAUDE_PLUGIN_DATA}`
  (which is janitor-private and the MANAGER can't locate). Documented exception to the
  "prefer PLUGIN_DATA" principle precisely because this is a shared contract.
- UserPromptSubmit hooks receive the prompt via stdin JSON (`{"prompt": "..."}`). Verify
  the exact key name against the live hook payload before relying on it.

## Why blocked
`blocked-by` is empty by UID — the blocker is the MANAGER's external confirmation of the
final breadcrumb schema (janitor#15), not a janitor TRDD. Column is `blocked` because the
janitor publicly committed (#15) to NOT writing the first byte until the peer confirms
whether it wants `source_pid` / `version` fields. Restore to `dev` when they reply.

## Approval log
- 2026-06-05T04:01:18+0200 — Accepted the MANAGER's janitor#15 proposal (Tier-0 coordination
  reply; consensus-seeking per peer-agent protocol). Implementation is a small reversible
  local feature in the janitor's own plugin (Tier 0), gated only on the peer's schema
  confirm to avoid rework. No MANAGER-approval needed for the feature itself.
