---
name: janitor-gh-reply-monitor
description: "how does the janitor notice a reply to a github thread it opened / why did the standalone github-issues-monitor skill die on restart / gh-reply-watch vs github-issues-watch difference / where does the gh issues monitor registry live / why is gh_register_hook a plugin hook not a settings.json hook / a hook cannot call the Monitor tool / how does the janitor avoid replaying every old thread as new / how is a GitHub reply injection defended against / what does sanitize_for_drift_line do / how does the registry know which threads this project opened / why does the poller run as uv run --script not chmod +x / where does registry.json and state.json actually live / does moving a checkout orphan the gh-reply registry / why did the standalone skill's hook die after a plugin update / does gh-reply-watch work outside the ai-maestro harness / how often does the gh reply poller run / what triggers a baseline-only first fire for gh-reply-watch"
ocd: 2026-08-02
lmd: 2026-08-02
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: gh-reply-monitor
publish-globally: false
---

# janitor-gh-reply-monitor



^ATOM-NALH-OSIM [desc:"GH-REPLY MONITOR overview: distinct from github-issues-watch; why it moved from a persistent Monitor loop (which died on restart/compaction) to an always-on cron-driven detector", keywords: gh-reply-watch_always_on_cron_driven monitor_tool_died_on_restart distinct_from_github-issues-watch why_did_the_standalone_github-issues-monitor_skill_die a_hook_cannot_call_the_Monitor_tool the_heartbeat_supplies_the_schedule_nothing_forgets_to_arm_it cadence_900_seconds_above_githubs_poll_interval_floor first_fire_is_silent_baseline runs_in_both_the_harness_and_non-harness_backends _NON_HARNESS_DETECTORS_deny-list do_poll_was_already_a_one-shot_function replays_every_already-read_thread_on_the_next_poll, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

**GH-REPLY MONITOR (`scripts/detectors/gh-reply-watch.py` + `scripts/gh_issues_monitor/`)**
— notifies when someone REPLIES to a thread THIS project opened, on ANY repo.
**Distinct from the `github-issues-watch` DETECTOR above**, which reports NEW issues on this
project's OWN repo — different question, different mechanism, no shared state.

**ALWAYS ON and CRON-DRIVEN since the 2026-08-02 owner directive** ("must be a chore executed
always by the janitor. no need to enable it. […] integrate it better in the chron. ensure it
works both inside ai-maestro harness and outside"). It was a persistent `Monitor` looping
`gh_notify_poll.py` every 120 s, started ONLY by step 3 of the now-retired
`/janitor-github-issues-monitor-on` — so it died on every restart and compaction, and a hook
could not revive it because **a hook cannot call the `Monitor` tool**. The fix was available
all along: `do_poll` was ALREADY a one-shot (poll, print, write cursor, exit) and the Monitor
only wrapped it in `while true; sleep 120`. As a detector the heartbeat supplies the schedule,
nothing can forget to arm it, and it runs in BOTH backends — `_NON_HARNESS_DETECTORS` is a
deny-list and neither GitHub chore is on it. Cadence 900 s, far above GitHub's
`X-Poll-Interval: 60` floor. **First fire is silent** (`--baseline`), else the first poll
replays every already-read registered thread as a fresh reply.


^ATOM-188U-X9IE [desc:"The injection defense (sanitize_for_drift_line) and the registry-intersection filter that scopes watching to threads THIS project opened", keywords: sanitize_for_drift_line_injection_defense registry_intersection_not_reason_filter gh_register_hook_fills_registry_from_creating_commands how_is_a_github_reply_injection_defended_against anyone_can_open_an_issue_reaches_the_janitor_stops registry_intersection_not_a_reason_filter shared_gh_identity_owner_personal_traffic_same_reason gh_issue_create_pr_create_comment_review_fill_the_registry list_and_view_never_fill_the_registry plugin_hook_not_settings.json_hook_because_of_ephemeral_cache_paths whitespace_squeeze_alone_is_not_enough_defense_for_a_drift_line a_bare_janitor-...-line_reads_as_an_instruction, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

**Every forwarded line is `sanitize_for_drift_line`d.** The poller interpolates
attacker-controlled text (issue TITLE, comment BODY) and its `squeeze()` only collapses
whitespace and truncates — harmless while the output went to Monitor notifications a human
reads, NOT harmless as heartbeat drift the model acts on, where a bare `[janitor-…]` line is
an instruction. Without it, "anyone can open an issue" reaches "the janitor stops".

The filter is a **registry intersection**, not a `reason` filter: on a shared `gh` identity the
owner's personal open-source traffic carries the same `reason: author` (measured 5-of-6
emitted threads), so a thread is watched only because this project OPENED it.
`gh_register_hook.py` fills that registry from GH-**creating** commands' printed URLs
(`gh issue create`, `pr create|comment|review`, `api -X POST …/comments` — never
`list`/`view`, which would watch everything merely READ). It ships as a PLUGIN hook, NOT
installed into `~/.claude/settings.json` as the standalone skill did: that baked an ABSOLUTE
path to the script, which inside a plugin is the EPHEMERAL versioned cache dir → the hook dies
silently at the next update when the version dir is GC'd.


^ATOM-LDK4-Y0YR [desc:"Where the GH-reply monitor's state lives (in-project .janitor/gh-issues-monitor/) and the copy-never-move migration from older locations", keywords: registry.json_state.json_lives_in_project gitignored_janitor_gh-issues-monitor poller_run_as_uv_run_script where_does_the_gh_reply_registry_actually_live moving_a_checkout_orphaned_the_old_slug-keyed_registry a_lost_registry_cannot_be_rebuilt_only_re-accumulated older_locations_migrated_copy-never-move not_placed_under_.janitor/state_because_that_is_regeneratable poller_is_not_chmod_+x_run_it_as_uv_run_--script gitignored_via_the_janitor_folder_entry state.json_holds_the_cursor_registry.json_holds_the_record where_is_the_gh_reply_monitor_cursor_stored, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

State (`registry.json` = a RECORD OF WORK, `state.json` cursor) lives **in the project** at
`.janitor/gh-issues-monitor/` (owner directive, same night: "store the tracking data
locally"). Slug-keyed subdirs of the global DATA dir gave per-project SEPARATION but not
LOCALITY — keyed by absolute path, so moving a checkout orphaned its registry, and one store
held every project's record of work. Deliberately NOT `.janitor/state/`, advertised as
regeneratable and safe to delete: the registry is filled by the hook as `gh` commands happen,
so a lost one cannot be rebuilt, only re-accumulated. Both older locations
(`<DATA>/gh-issues-monitor/<slug>/`, then the pre-port
`~/.claude/state/github-issues-monitor/<slug>/`) are migrated newest-first, **copy never
move** — a rollback must still find its registry. Gitignored via `.gitignore`'s `.janitor/`.
The poller is NOT `chmod +x`; run it as `uv run --script`, never by path.

## Governed by

- [[janitor-architecture]] — the architecture hub.

## See also

- [[janitor-detector-and-hook-roster]] — the `github-issues-watch` detector this page
  is distinct from (new issues on THIS repo, vs replies to threads this project opened).

## Notes and lessons learned
