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
publish-globally: true
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


^ATOM-14GY-NESV [desc:"a live ai-maestro server ABSORBS the update chore, so the janitor daemon correctly stands down — and if the server never consumes the request, the machine silently keeps running the old plugin", keywords: I_published_a_fix_but_the_cache_is_still_on_the_old_version the_janitor_daemon_is_dead_and_the_heartbeat_is_fine version-update-requested_stays_true_forever detectors_still_report_the_pre-fix_numbers_after_a_release who_actually_performs_the_plugin_update, type: project, ocd: 2026-08-01, lmd: 2026-08-01]

**A stalled update can be nobody's bug in progress.** When an ai-maestro server is alive
(`harness_backend.server_is_alive()`, from a fresh `~/.aimaestro/server-liveness.json`), it
ABSORBS the update trio, so `server_runs_chores()` is true and the janitor daemon deliberately
does not run. A dead daemon is then CORRECT, not a failure — and the per-session detector still
raises `version-update-requested`. If the server never consumes it, the flag simply stays set
and the machine keeps running the old plugin with no error anywhere.

Observed 2026-08-01: v2.2.0 published and green, and 71 minutes later the cache was still
2.1.0, the request still pending, daemon heartbeat 20h stale, server alive. The tell is that
DETECTORS KEEP REPORTING PRE-FIX NUMBERS — the memory-librarian still said 120 conflict
candidates when the shipped fix makes it 28, because the heartbeat runs the CACHED detector.
Confirm it directly rather than inferring: grep the new symbol in
`~/.claude/plugins/cache/.../<version>/scripts/...` and compare with the working tree.

Do NOT add a janitor-side fallback: the binary coordination rule (TRDD-LU0C5KAR) removed
exactly that guard, and this repo's contract says a running server that does not execute an
absorbed chore is a SERVER bug. Do NOT hand-run `claude plugin update --scope user` either —
user-scope writes belong to the single writer (issue #7 / PRRD S2.1). Escalate to the server
side; the pending flag is the evidence.


^ATOM-RGRE-T1Z7 [desc:"/reload-plugins does NOT re-point already-loaded skills — only a new session does; the cron path rolls forward while skills stay pinned", keywords: I_ran_reload-plugins_and_the_skill_is_still_the_old_version session_runs_new_detectors_but_old_skills two_plugin_versions_live_in_one_session reload_markers_delivered_but_nothing_changed only_a_new_session_picks_up_the_new_plugin skill_base_directory_shows_the_old_version, ocd: 2026-08-06, lmd: 2026-08-06]

**A live session can run TWO plugin versions at once, and `/reload-plugins` does not fix it.** The auto-rolling dispatcher stub always resolves the NEWEST cached version, so the CRON/detector path rolls forward on its own — but SKILLS stay on whatever was current when the session loaded them. Result: new detectors and old skills in the same session, which reads as "the fix is published and the bug still happens".

MEASURED 2026-08-06 from `"Base directory for this skill:"` lines (real load markers, not prose):

| session | skill loads | `/reload-plugins` runs |
|---|---|---|
| overnight | 66 x 2.3.0, ZERO 2.4.1 | 27 |
| next day | 9 x 2.3.0, ZERO 2.4.1 | **23** |
| after `/clear` | 2 x 2.4.1, ZERO 2.3.0 | — |

Not one skill load resolved to the new version in either pre-clear session, though it had been cached for hours and one session ran `/reload-plugins` **23 times** — via a `janitor-reload-plugins` skill that was ITSELF loaded from the old tree. The fresh session after `/clear` picked up the new version on its first load.

So the janitor's convergence chain is NOT the suspect: cache update, reload-generation stamp, `[janitor-reload]` markers and the reload command all worked. **Only a NEW SESSION re-points skills** — which makes `/clear` + bootstrap the ONLY reliable version-convergence mechanism available, not merely a cost optimisation (TRDD-PXP08ZQC, TRDD-5C42VCUX).


^ATOM-RGRE-DIAG [desc:"to learn which plugin version a session is really running, read the skill LOAD MARKER's path — never ask a claim-state API", keywords: how_do_I_tell_which_plugin_version_a_session_runs which_version_is_this_session_actually_using claim_state_api_disagreed_with_reality base_directory_for_this_skill_path proving_what_actually_loaded, ocd: 2026-08-06, lmd: 2026-08-06]

To establish which plugin version a session is ACTUALLY running, grep its transcript for `Base directory for this skill:` and read the version out of the PATH. That line is emitted at load time by the thing that did the loading, so it is evidence; a claim-state or install-registry helper describes INTENT and can disagree with what a live session holds.

Learned the expensive way on the same investigation: I first concluded the daemon had "stood down" for server-claimed update chores because `claimed_chores()` listed them — then found the daemon's own log showed it RAN the chore, with zero yield lines anywhere. The published root cause had to be withdrawn. An API that reports ownership is not a record of execution.

## See also

- [[plugin-cache-install-integrity]] — the sibling failure: there the CACHE itself is
  incomplete (an install killed partway), so components are missing on disk; here the cache
  is complete and only the LOADED skills are stale. Tag-diff the cache to tell them apart.

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
