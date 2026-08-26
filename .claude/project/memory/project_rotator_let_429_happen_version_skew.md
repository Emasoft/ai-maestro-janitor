---
name: project_rotator_let_429_happen_version_skew
description: "the oauth rotator let a 429 happen instead of rotating / had to rotate manually again / proactive rotation didn't fire / rotator log says 'all paid accounts maxed' but an account is actually fresh / rotation deadlocked / a model-scoped wall did not trigger rotation / agents hung on a fable-only limit / total continuity failure across the fleet / oauth-health reports every slot as latched refresh no / a server-owned agent did not recover from a wedge / model fallback did not fire when it should have / why does the janitor stay put instead of rotating on a scoped wall / the candidate loop deadlocked with an empty selection / an alternate account slot token expired and looked maxed / a handoff to a dark receiver is a silent no-op / read oauth-health live never trust a stale summary / did I have to rotate accounts manually again"
ocd: 2026-06-11
lmd: 2026-06-13
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: oauth-rotator
---

When the rotator **lets a 429 land instead of rotating** (the user has to rotate
manually), the usual root cause is NOT "the rotator didn't notice." It DOES
notice — `rotator.log` shows `auto: live <acct> exhausted … but no alternate is
healthy + below safe threshold — all paid accounts maxed; waiting for a window
to reset`, every 60s, forever. The trap: the "maxed" alternate is often actually
**fresh** (its real utilization well below its own limit). The rotator excluded it
because it could not READ its usage — the alternate's SLOT access token was
**expired**, so `cmd_auto`'s probe `usage_request(b)` returned non-200 ("err") and
the candidate loop did `continue` → `select_drain_first([])` → deadlock.

**Why the slot lapsed (the load-bearing cause, 2026-06-11):** the slot should be
kept fresh by `_keepalive_refresh`, but the **RUNNING daemon was v0.6.1, which
PREDATES the CF-1010 User-Agent fix** (`[[reference_oauth_token_cloudflare_1010_useragent]]`,
commit `6fdbeaa`). v0.6.1's `refresh_oauth_token` sent no `User-Agent` → every
token-refresh POST got Cloudflare 403 "error code: 1010" → the keepalive
**silently failed for EVERY slot** → all alternates inexorably lapsed → deadlock.

**The systemic lesson (bigger than this one bug):** *a fix committed to SOURCE
does not run in production until it is PUBLISHED and the daemon auto-rolls to the
new version.* Here the fix existed since 2026-06-09 but was stranded in unpushed
commits because the janitor **publish was CPV-blocked**
(`[[project_janitor_publish_blocked_cpv_fps]]`). So a "known-fixed" rotator bug kept
biting because the daemon runs the old cached v0.6.1. **When the rotator
misbehaves, ALWAYS check whether the RUNNING daemon version predates the relevant
fix** (`git merge-base --is-ancestor <fixsha> <running-tag>`), not just whether
source is correct. The new Claude Code rate-limit MENU makes this worse: on a 429
it freezes the SESSION (and the cron heartbeat), so post-429 recovery is dead —
rotation MUST happen proactively, which means the daemon-side keepalive MUST work.

**How to apply (diagnostic + immediate fix):**
1. `tail rotator.log` — "no alternate healthy / all accounts maxed" = this bug.
2. `uv run <repo-root>/scripts/oauth_rotator/rotator.py oauth-health` (working-tree
   rotator has `oauth-health`; installed v0.6.1 does NOT) — if both accounts show
   `refresh=yes` yet the rotator says "maxed", the slots are lapsing, not maxed.
3. Confirm version skew: the daemon runs `<cached>/<ver>/scripts/daemon.py` and
   subprocesses `<ver>/oauth_rotator/rotator.py` fresh every 60s. If `<ver>`
   predates the fix sha → that's it.
4. **Hot-patch the cached running rotator** (the daemon picks it up next tick, NO
   restart): add `"User-Agent": "claude-account-rotator"` to
   `refresh_oauth_token`'s token-POST headers. Back it up first
   (`rotator.py.pre-…-hotpatch.bak`). Verify with
   `ROTATOR_KEEPALIVE_AHEAD_H=999 uv run <cached> tick` → log must show
   `keepalive: refreshed <alt-acct>`. The auto-updater won't clobber the patch
   while the latest *published* version == the cached one; a real publish
   supersedes it cleanly.
5. **Durable:** the fix ships on the next CPV-unblocked publish. Source hardening
   (logged in TRDD-32acd15f): `cmd_auto` does **refresh-on-err** — refresh an
   unreadable (non-200, non-429) alternate that has a refresh token and re-probe
   BEFORE excluding it, so one stale access token can never deadlock rotation even
   if the keepalive has a gap.

**STATUS (RESOLVED by the v0.7.x publish):** the CF-1010 fix + the `cmd_auto`
refresh-on-err hardening now ship natively and the daemon auto-rolls — the hotpatch
in step 4 is OBSOLETE on a current install. Kept above as the diagnostic recipe for
the symptom should a version-skew recur.

Full record: TRDD-32acd15f §STATE 2026-06-11 addendum. Don't trust a compaction
summary's claim about which account is healthy — it time-varies; read
`oauth-health` live (the rotator resume protocol lives in a LOCAL-scope note). See
also [[oauth-rotation-renew-reauth]] (the component overview; this page is the
incident record behind its 429 lesson) and `[[project_janitor_cc_changelog_currency]]`
(the rate-limit MENU that freezes the session on 429 — why rotation must be proactive).


^ATOM-PH7Z-4FY8 [desc:"2026-08-15 Fable-wall continuity failure: why nothing rotated or fell back, and the scoped rotation trigger that fixed the janitor half", keywords: fable_exhausted_no_rotation model_scoped_window_rotation_trigger agents_hung_on_fable scoped-only_wall_stay_put rotate_to_account_with_fable_headroom server_owned_handoff_dark model_fallback_did_not_fire cmd_auto_had_no_rotation_trigger_for_a_model-scoped_wall fixed_in_commit_f185e521 a_scoped-only_wall_rotates_only_onto_a_scoped-clear_target every_hung_agent_was_server_owned_so_the_janitor_stood_down oauth-health_from_a_non-daemon_cli_reports_a_fail-closed_latch, type: project, ocd: 2026-08-15, lmd: 2026-08-15]

2026-08-15 Fable-wall incident (owner: "total continuity failure"). Three stacked causes, only one a janitor code gap:
(1) `cmd_auto` had NO rotation trigger for a MODEL-scoped wall — Fable spent while 5h/7d fine read as "within limits". Fixed in `f185e521`: it reuses `token_burn.model_fallback_verdict` (scoped>=90, account<=90, `ROTATOR_SCOPED_SWITCH_AT`/`ROTATOR_SCOPED_ACCOUNT_HEADROOM`); a scoped-only wall rotates ONLY onto a scoped-clear target (preserve Fable), and with none it STAYS PUT — tiers 1b/degraded are skipped because they would trade one Fable wall for the same wall — leaving `/model opus` to the model-fallback detector.
(2) Every hung agent was `server_owned`, so the janitor's shipped wedge-ESC recovery (WKTD5JTC, in v3.3.1) and the per-session fallback detector correctly stood down — and the ai-maestro server's receiving leg ships DARK behind `AIM_FLEET_MODEL_FALLBACK=1` pending the USER ruling (ai-maestro TRDD-DPPYVLVH). A handoff to a dark receiver is a silent no-op; escalated to the hub 2026-08-15.
(3) `oauth-health` from a NON-daemon CLI process reports every slot `status=latched refresh=no` — that is the keychain fail-closed latch, NOT slot death; only the daemon's own alerts describe real slot health.

## Notes and lessons learned

(none yet)
