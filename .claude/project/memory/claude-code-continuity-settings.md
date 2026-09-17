---
name: claude-code-continuity-settings
description: "claude stopped on an api error instead of retrying / AskUserQuestion dialog blocked an unattended session forever / which settings.json entries keep claude working in my absence / askUserQuestionTimeout ignored in project settings / CLAUDE_AFK_TIMEOUT_MS vs askUserQuestionTimeout which wins — the ensured continuity settings stack / why did an unattended overnight session freeze on a dialog / CLAUDE_AFK_TIMEOUT_MS=0 does not disable auto-continue it dismisses instantly / does the retry watchdog make claude survive rate-limit errors / ENABLE_BACKGROUND_TASKS CLAUDE_AUTO_BACKGROUND_TASKS CLAUDE_CODE_FORK_SUBAGENT env vars / what env vars does the janitor add to settings.json / two writers janitor and ai-maestro server must enforce the same askUserQuestionTimeout value / why is my project .claude/settings.json askUserQuestionTimeout having no effect / what is CLAUDE_AFK_COUNTDOWN_MS / lockstep invariant between janitor settings_ensurer and the ai-maestro server / how to make claude keep working while I'm away"
ocd: 2026-07-18
lmd: 2026-09-17
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: continuity
publish-globally: true
---

^FO0I6VZN [desc:"the continuity settings stack: ~/.claude/settings.json entries the owner ratified so claude keeps working unattended; ensured by both the janitor settings_ensurer and ai-maestro server, in lockstep", keywords:what_is_the_continuity_settings_stack who_writes_the_continuity_settings janitor_settings_ensurer_vs_ai_maestro_server which_file_holds_continuity_settings settings_ensurer_py_sessionstart, ocd:2026-07-18, lmd:2026-07-18]
The **continuity settings stack** — the `~/.claude/settings.json` entries the owner ratified
(2026-07-18) "to ensure the continuity even in user absence". Ensured automatically by BOTH
writers — the janitor (`scripts/lib/settings_ensurer.py`, SessionStart) and the ai-maestro
server — which MUST enforce IDENTICAL values (lockstep invariant, below). Governed by
[[claude-code-continuity-engineering]].

## The canonical payload

^MQOF5EWT [desc:"the canonical continuity payload: an ADD-IF-MISSING env block (background tasks, retry watchdog, AFK timeout/countdown) plus an ENFORCE top-level askUserQuestionTimeout of 60s", keywords:what_env_vars_does_the_janitor_add_to_settings_json ENABLE_BACKGROUND_TASKS_CLAUDE_AUTO_BACKGROUND_TASKS_CLAUDE_CODE_FORK_SUBAGENT CLAUDE_CODE_RETRY_WATCHDOG_value CLAUDE_AFK_COUNTDOWN_MS_CLAUDE_AFK_TIMEOUT_MS_defaults askUserQuestionTimeout_60s_enforced_value, ocd:2026-07-18, lmd:2026-07-18]
`env` block — **ADD-IF-MISSING** (a user's own value always wins; `ENV_ADD_IF_MISSING`):

```
ENABLE_BACKGROUND_TASKS=1          ENABLE_TOOL_SEARCH=false
CLAUDE_CODE_FORK_SUBAGENT=1        CLAUDE_AUTO_BACKGROUND_TASKS=1
CLAUDE_CODE_RETRY_WATCHDOG=1       CLAUDE_AFK_COUNTDOWN_MS=20000
CLAUDE_AFK_TIMEOUT_MS=300000       CLAUDE_ASYNC_AGENT_STALL_TIMEOUT_MS=2000000
```

Top level — **ENFORCE** (set when missing OR different; `TOP_LEVEL_ENFORCE`):
`"askUserQuestionTimeout": "60s"`.

## Why each matters for continuity

^VMMZJ1IF [desc:"why each continuity setting matters: retry watchdog keeps the process alive on API errors, AFK timeout auto-continues a blocked question after 5 min, askUserQuestionTimeout is the safe fallback", keywords:why_does_the_retry_watchdog_matter why_does_CLAUDE_AFK_TIMEOUT_MS_matter does_the_env_var_override_the_setting what_happens_on_an_unanswered_askuserquestion retrying_in_Xm_instead_of_stopping, ocd:2026-07-18, lmd:2026-07-18]
- `CLAUDE_CODE_RETRY_WATCHDOG=1` — on API errors the session RETRIES ("Retrying in Xm")
  instead of stopping; the process never dies, only the turn. This is the failure shape the
  whole freeze-recovery layer assumes ([[claude-code-esc-input-semantics]]) — and because the
  janitor ensures the setting itself, the assumption is self-fulfilling fleet-wide.
- `CLAUDE_AFK_TIMEOUT_MS=300000` — an unanswered AskUserQuestion auto-continues after 5 min,
  so a question can never permanently block an unattended session.
- `askUserQuestionTimeout: "60s"` — the SETTING half of the same feature (default `"never"` =
  block forever). Safe fallback only: the env var overrides it whenever set.

## The precedence + scope traps (doc-verified 2026-07-18)

^BNKVYSBU [desc:"three precedence/scope traps: CLAUDE_AFK_TIMEOUT_MS (env) beats askUserQuestionTimeout (setting); that setting is user-scope-only (project copy ignored); the env var set to 0 dismisses, not disables", keywords:why_is_my_project_settings_json_askUserQuestionTimeout_having_no_effect does_CLAUDE_AFK_TIMEOUT_MS_0_disable_auto_continue askUserQuestionTimeout_scope_user_only_not_project which_setting_wins_env_or_json accepted_values_60s_5m_10m_never, ocd:2026-07-18, lmd:2026-07-18]
1. **Precedence**: `CLAUDE_AFK_TIMEOUT_MS` (env) > `askUserQuestionTimeout` (setting). The env
   var "turns auto-continue on even when the setting is unset or never". Effective timeout on
   the fleet: 5 min.
2. **Scope**: `askUserQuestionTimeout` is read ONLY from user settings / `--settings` /
   managed settings — a copy in a project's `.claude/settings.json` is SILENTLY IGNORED.
   Ensure it in `~/.claude/settings.json`, nowhere else. Accepted values: `"60s"|"5m"|"10m"|"never"`.
3. **The zero footgun**: `CLAUDE_AFK_TIMEOUT_MS=0` does NOT disable auto-continue — it
   dismisses the dialog IMMEDIATELY. Never "disable by zeroing". [^1]

## The lockstep invariant (two writers)

^K2UIEROE [desc:"the lockstep invariant: janitor and ai-maestro server both ensure the continuity payload; ADD-IF-MISSING keys never conflict but ENFORCE oscillates if writers disagree, so changes ship together", keywords:lockstep_invariant_two_writers_janitor_ai_maestro_server does_askUserQuestionTimeout_oscillate_between_writers why_must_both_writers_enforce_the_same_value janitor_100_outcome_parity_contract, ocd:2026-07-18, lmd:2026-07-18]
Both the janitor and the ai-maestro server ensure this payload. ADD-IF-MISSING keys cannot
fight; the ENFORCE key (`askUserQuestionTimeout`) WOULD oscillate if the two writers ever
enforce different values — any change to the ENFORCE set must ship on both sides in lockstep.
Parity deltas are coordinated on janitor#100 (outcome-parity contract, owner 2026-07-18).

## Notes and lessons learned

[^1]: [id:ATOM-SET-SCOPE, status:valid, keywords:"askUserQuestionTimeout ignored project settings silently user scope only afk timeout zero dismisses immediately", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT put `askUserQuestionTimeout` in a project's `.claude/settings.json` or "disable" AFK
  auto-continue with `CLAUDE_AFK_TIMEOUT_MS=0`, BECAUSE the setting is user-scope-only (project
  copies are silently ignored) and 0 means dismiss-immediately, not off. DO ensure it in
  `~/.claude/settings.json` and disable only by removing the env var (setting default `never`).
