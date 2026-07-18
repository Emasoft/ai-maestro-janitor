---
name: claude-code-plugin-rollout-staleness
description: "the fix is published but the bug keeps happening / a session still injects the old behavior after the plugin updated / which sessions run stale hooks / why did /compact fire at the old threshold after the release — plugin code is SESSION-LOADED and a running session is a ghost of the old version until it reloads"
ocd: 2026-07-18
lmd: 2026-07-18
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: continuity
---

**Plugin rollout staleness** — why a shipped fix is NOT live everywhere the moment it is
published, and how to tell which sessions are ghosts. Governed by
[[claude-code-continuity-engineering]].

## The split (load-bearing)

| Surface | Rolls forward | When the fix lands |
|---|---|---|
| Heartbeat dispatcher (`dispatch.py` via the DATA-dir stub) | **auto** — the stub re-resolves the newest cached version on EVERY cron fire | next fire (~minutes), no reload needed |
| Global daemon | auto — `daemon_needs_restart()` restarts it from the new cache | ~minutes |
| **Hooks + skills + commands** | **SESSION-LOADED** — a running session keeps executing the OLD cached code | only after that session runs `/reload-plugins --force` (driven by the `[janitor-reload]` marker, per session) |

## The ghost symptom

After v0.53.0 shipped the harness-relative compact threshold, a session still on 0.52.0
hooks injected `/compact` at the OLD 350k threshold — indistinguishable from "the fix
doesn't work" unless you know that session's LOADED version. Rule: **before declaring a
shipped fix broken, establish the misbehaving session's loaded plugin version.**

## Diagnosis

- A session's live loaded version is embedded in its hook execution paths:
  `~/.claude/plugins/cache/<marketplace>/<plugin>/<VERSION>/scripts/hooks/…` — the most
  recent hook exec per session IS its loaded version.
- Fleet-wide tooling requested from AgentlensPro (issue Emasoft/AgentlensPro#5, filed
  2026-07-18): `agentlenspro sessions --plugin <name>` → per-session loaded vs newest-cached
  + STALE flag; the janitor will consume it fail-open (`agentlens_probe`) to verify a pushed
  `[janitor-reload]` actually landed and to raise a per-project stale-hooks drift finding.

## Notes and lessons learned

[^1]: [id:ATOM-ROLL-GHOST, status:valid, keywords:"fix published but bug still happening stale hooks session loaded old version reload-plugins ghost", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT debug a "still-broken after the release" report against the new code, BECAUSE hooks
  are session-loaded and the misbehaving session may be a ghost running the previous version
  until its reload lands. DO check the session's loaded version first (hook exec paths embed
  it), then re-test only if the ghost hypothesis fails.
