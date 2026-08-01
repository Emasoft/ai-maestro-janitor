---
name: claude-code-plugin-rollout-staleness
description: "the fix is published but the bug keeps happening / a session still injects the old behavior after the plugin updated / which sessions run stale hooks / an installed rule file went BACKWARD to an older version's content / why did /compact fire at the old threshold after the release — plugin code is SESSION-LOADED and a running session is a ghost of the old version until it reloads"
ocd: 2026-07-18
lmd: 2026-07-31
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

**The asymmetry bites twice.** A ghost session does not merely READ old code — its
SessionStart also WRITES. `install_rules` compared bytes and overwrote on ANY difference,
in EITHER direction, so the installed `~/.claude/rules/*.md` converged on whichever
session started LAST. Found live 2026-07-31: the installed heartbeat-protocol rule was
**0.60.1's** with 0.66.1 cached (26 versions on the host), so it did not document
`[janitor-quiet]` that the dispatcher emits — and the rule's own security clause tells an
agent to refuse an unlisted marker. Fixed in `442864c` (v1.0.0): each installed file leads
with `<!-- ai-maestro-janitor:rule-stamp version=X.Y.Z -->` and an install is REFUSED when
the installed stamp is newer. Every unknown fails toward INSTALLING — see [^2]. [^3]

## The ghost symptom

After v0.53.0 shipped the harness-relative compact threshold, a session still on 0.52.0
hooks injected `/compact` at the OLD 350k threshold — indistinguishable from "the fix
doesn't work" unless you know that session's LOADED version. Rule: **before declaring a
shipped fix broken, establish the misbehaving session's loaded plugin version.** [^1]

## Diagnosis

- A session's live loaded version is embedded in its hook execution paths:
  `~/.claude/plugins/cache/<marketplace>/<plugin>/<VERSION>/scripts/hooks/…` — the most
  recent hook exec per session IS its loaded version.
- Fleet-wide tooling requested from AgentlensPro (issue Emasoft/AgentlensPro#5, filed
  2026-07-18): `agentlenspro sessions --plugin <name>` → per-session loaded vs newest-cached
  + STALE flag; the janitor will consume it fail-open (`agentlens_probe`) to verify a pushed
  `[janitor-reload]` actually landed and to raise a per-project stale-hooks drift finding.

See also [[status-lines-to-autonomous-readers-cause-escalation]] — a fix published but not
installed is exactly the stranded-flag shape that page generalizes: a status line with
readers and no writers is where automatic remediation piles up.

## Notes and lessons learned

[^1]: [id:ATOM-ROLL-GHOST, status:valid, keywords:"fix published but bug still happening stale hooks session loaded old version reload-plugins ghost", ocd:2026-07-18, lmd:2026-07-18]
  DO NOT debug a "still-broken after the release" report against the new code, BECAUSE hooks
  are session-loaded and the misbehaving session may be a ghost running the previous version
  until its reload lands. DO check the session's loaded version first (hook exec paths embed
  it), then re-test only if the ghost hypothesis fails.

[^2]: [id:ATOM-ROLL-M0N0, status:valid, keywords:"installed_file_went_backward older_session_overwrote_newer byte_compare_overwrites_either_direction contract_not_monotonic rule_stamp", ocd:2026-07-31, lmd:2026-07-31]
  DO NOT decide "install or skip" by comparing BYTES when the executable half auto-rolls
  FORWARD, BECAUSE a byte difference is direction-blind: any older session on the host then
  reverts the newer contract, making every shipped rule fix revertible rather than merely
  late. DO stamp the writer's version into the artifact and refuse an older writer.

[^3]: [id:ATOM-ROLL-UNKN, status:valid, keywords:"unknown_version_fail_direction guard_froze_the_file placeholder_0_0_0_outranked_unknown", ocd:2026-07-31, lmd:2026-07-31]
  DO NOT let a monotonic guard fail toward REFUSING on an unreadable version, BECAUSE a file
  it can never overwrite again is the same permanent-staleness failure the guard exists to
  prevent, inverted. DO fail toward INSTALLING on every unknown, and write the literal
  `unknown` rather than `0.0.0` — a placeholder that PARSES would outrank a genuinely unknown
  source on the next install and freeze the file for real.
