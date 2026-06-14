---
trdd-id: db169d9e-32db-414e-89d6-96c81c84cc2b
title: Janitor portability — context-aware gating, terminal abstraction, user-level-only, no ai-maestro auto-upgrade
column: design
created: 2026-06-14T11:59:28+0200
updated: 2026-06-14T13:18:48+0200
current-owner: amama
assignee: amama
task-type: feature
release-via: publish
test-requirements: [unit, lint]
relevant-rules: [4]
labels: [portability, context-awareness, scope, terminal, daemon, install]
---

# TRDD-db169d9e — Janitor portability + context-awareness

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-06-14

The janitor is installed at **USER level**, so it runs in EVERY project — ai-maestro
or not. It must be CONTEXT-AWARE: ai-maestro-specific behavior auto-deactivates outside
ai-maestro, terminal self-triggers work beyond iTerm, and it never touches the
ai-maestro fleet's own plugin versions. Captured as a design spec; awaiting USER
decisions (§Decisions) before implementation. NOT started.

## USER directive (verbatim, 2026-06-14)

> the janitor plugin is special and it is installed at user level. so it should work on
> all projects, even those that are NOT part of ai-maestro. So you must ensure that the
> functionalities that does not make sense in a non ai-maestro plugin are being
> automatically deactivated if the project is not part of ai-maestro-plugins marketplace.
> Even the ai-maestro project itself is not an agent of ai-maestro, and so the janitor
> must avoid doing things like attempting to upgrade ai-maestro-plugin or any other
> ai-maestro-plugins marketplace plugin. You must let the janitor skills detect if they
> are inside iterm or if they are executed inside another terminal program, and in case
> use a different way to run commands like compact, reload-all-plugins, etc. If the
> janitor command/skill/etc. detects that it is inside an ai-maestro agent running inside
> ai-maestro, then it can use directly the ai-maestro API (there is an API command to
> send direct instructions to the agent terminal). and ensure that the janitor is only
> installed at user level and never locally/project level.

## Requirements (5 distinct pillars)

- **R1 — Context gate.** A single shared predicate `project_is_ai_maestro()` (is the
  current project a plugin of the `ai-maestro-plugins` marketplace?) that the
  ai-maestro-SPECIFIC per-session detectors/skills consult and **self-deactivate** when
  false. Generic detectors (dirty-tree, worktree, branch-protection, supply-chain,
  secrets, workflow-doctor, trashcan/screenshot purge, …) keep running everywhere.
- **R2 — No ai-maestro fleet auto-upgrade.** The daemon's `task_user_plugins_update`
  currently updates EVERY user-scope plugin (`claude plugin update <id> --scope user`).
  EXCLUDE every plugin whose id is `@ai-maestro-plugins` (the fleet — versions are
  owned by their own release pipelines; auto-bumping causes fleet version skew). The
  janitor's OWN self-update (`task_version_update`) is unaffected.
- **R3 — Terminal abstraction.** `compact_trigger.py` / `reload_trigger.py` are
  iTerm-ONLY (osascript→iTerm2, gated on `$ITERM_SESSION_ID`; otherwise prints NO_ITERM
  and asks the human). Add terminal DETECTION (`$TERM_PROGRAM`, WezTerm, kitty, tmux,
  Apple Terminal, VS Code) and a per-terminal send mechanism, with a clean graceful
  degrade (print a marker + ask the human) when none is automatable.
- **R4 — ai-maestro API path.** When running INSIDE an ai-maestro agent (inside
  ai-maestro), use the ai-maestro API "send instruction to agent terminal" command for
  compact/reload self-triggers instead of osascript. (Needs the API surface — see
  Decision D3.)
- **R5 — User-level-only.** Ensure/verify the janitor is installed ONLY at user scope,
  never project/local. Add a detector that WARNS if a project/local-scope janitor
  install is found, and make `/janitor-arm` refuse to arm a non-user install.

## Current-state audit (2026-06-14, verified)

- **R1:** No unified `project_is_ai_maestro()` gate exists. `is_self_scan_target()`
  (state.py:331 — "is this the janitor's own repo") is the only adjacent guard. Scattered
  `ai-maestro` string refs in dispatcher-stub/autorecall/version_update_lib/oauth/librarian,
  none a reusable context gate.
- **R2:** `daemon.py::task_user_plugins_update` (≈283) updates ALL `scope=="user"` plugins
  — INCLUDING `@ai-maestro-plugins` ones. This is the gap. `marketplace-refresh` is bulk
  (all marketplaces) — acceptable (refresh ≠ upgrade), but the per-plugin UPDATE is the
  fleet-skew risk.
- **R3:** CONFIRMED iTerm-only — `compact_trigger.py`/`reload_trigger.py` both hard-gate on
  `$ITERM_SESSION_ID` and build an iTerm2 osascript; "Outside iTerm self-trigger isn't
  available". No `$TERM_PROGRAM`/tmux/etc. detection.
- **R4:** No ai-maestro-API reference anywhere in the janitor.
- **R5:** No user-level-only enforcement; rules_installer handles all three scopes
  generically.

## Phased plan (each phase ≤ 5 files, verify before next)

1. **Phase 1 — the context gate (R1 core).** Add `state.project_is_ai_maestro()` +
   `terminal_kind()` helpers (pure, stdlib, tested). No behavior change yet — just the
   primitives + tests.
2. **Phase 2 — gate the ai-maestro-specific detectors (R1).** Per the Decision-D1 list,
   make each ai-maestro-specific detector early-return when `not project_is_ai_maestro()`.
3. **Phase 3 — exclude the fleet from auto-upgrade (R2).** Filter `@ai-maestro-plugins`
   out of `task_user_plugins_update`; add a regression test.
4. **Phase 4 — terminal abstraction (R3).** Refactor the two trigger scripts onto a shared
   `terminal_trigger.py` send-abstraction: iTerm (osascript), Apple Terminal (osascript),
   tmux (`tmux send-keys`), kitty (`kitty @ send-text`), WezTerm (`wezterm cli send-text`);
   graceful-degrade marker otherwise. Tests per backend (dry-run, no real keystrokes).
5. **Phase 5 — ai-maestro API path (R4).** Wire the in-ai-maestro send to the API command
   (pending D3). 6. **Phase 6 — user-level-only (R5):** the install-scope detector + arm refusal.

## Decisions needed from USER (blocking implementation)

- **D1 — the gate list.** Which per-session detectors are "ai-maestro-specific" (gate OFF
  outside ai-maestro)? Proposed OFF list: `subagent-report`, `subagent-scope-drift`,
  `trdd-drift`, `trdd-reminder`, `report-to-trdd-drift`, `task-pr-mismatch`, `stale-task`,
  `memory-librarian`, `memory-scope-leak`, `project-map-drift`. Everything else stays ON
  everywhere. (TRDD/PRRD/AMP/fleet-coordination = ai-maestro-specific; git/security/cleanup
  = universal.) Confirm or adjust.
- **D2 — auto-upgrade scope.** Exclude ONLY `@ai-maestro-plugins` from the daemon
  per-plugin update (proposed), or a broader "only self-update, never other plugins"
  policy? The directive says "ai-maestro-plugin or any other ai-maestro-plugins
  marketplace plugin" → exclude the `@ai-maestro-plugins` marketplace. Confirm.
- **D3 — the ai-maestro API. ✅ ANSWERED by research (2026-06-14), no longer blocking.**
  Source: `~/Code/AI-MAESTRO-PLUGIN/ai-maestro-plugin/scripts/ai-maestro-hook.cjs`
  (`sendMessageNotification`). The contract:
  - **inside-ai-maestro detection** — `GET http://localhost:23000/api/agents` succeeds
    AND an agent's `workingDirectory` (or `session.workingDirectory`) equals the cwd OR
    the cwd is a strict subdir of it. (`AMP_AGENT_ID` / `AID_AUTH` env vars are present in
    an ai-maestro agent and serve as a cheap pre-check, but the AUTHORITATIVE resolver is
    the CWD match against `/api/agents`.) ai-maestro agents run in a **tmux** session.
  - **send the instruction to the agent's own terminal** —
    `POST http://localhost:23000/api/sessions/<tmuxSessionName>/command`,
    `Content-Type: application/json`, body
    `{"command": "<e.g. /compact or /reload-plugins>", "requireIdle": false, "addNewline": true}`
    (`addNewline:true` submits it; `requireIdle:true` waits for the agent to be idle).
    Returns `{"success": bool}`. `<tmuxSessionName>` = the matched agent's
    `agent.session.tmuxSessionName`.
  - The server base is `AIMAESTRO_API` (default `http://localhost:23000`).
  Implication: R4's in-ai-maestro send is this POST; R3's **tmux** backend
  (`tmux send-keys`) is the graceful fallback when the server is unreachable but we ARE
  in tmux. D3 is recorded; D1 + D2 still want USER confirmation before behavior changes.

## Durable artifacts to read before acting
- The current-state audit above (verified greps, 2026-06-14).
- `scripts/lib/state.py` (`is_self_scan_target`), `scripts/daemon.py`
  (`task_user_plugins_update`), `scripts/compact_trigger.py` + `scripts/reload_trigger.py`.
