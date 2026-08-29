---
name: plugin-cache-install-integrity
description: "the installed plugin is missing agents commands or hooks / Agent type not found but skills load fine / agents disappeared after a plugin reload / N agent types no longer available / agents missing but the plugin is installed and enabled / plugin cache incomplete after an update / how to verify an install against its release tag / cache extraction interrupted killed partway / hand-patched cache / every tool blocked machine-wide PreToolUse hook Errno 2 missing hook script / reload reports load errors after parking a quarantined broken copy inside a scanned cache tree / an install was killed by memory pressure not a bad release / how to diff a cache directory against a release tag / is a missing manifest-sha256.json a real finding / never hand-patch the plugin cache / a pid file in the cache dir looks suspicious is it damage / why does the plugin loader try to load a quarantined broken copy / how to root-cause a partially installed plugin / a quarantined broken plugin copy caused fleet-wide load errors / quarantine directory must sit outside every scanned tree"
ocd: 2026-08-07
lmd: 2026-08-29
metadata:
  node_type: memory
  type: project
  tier: component
publish-globally: false
---

# plugin-cache-install-integrity


^ATOM-1F78-3R1G [desc:"A plugin-cache install can be killed partway; verify any install by diffing the cache against the release tag — a hand-patched cache verifies against nothing.", keywords: install_interrupted_under_memory_pressure tag_vs_cache_file_diff surviving_vs_lost_dirs_signature cache_prune_exoneration_daemon_log reinstall_via_cli_never_hand_patch skills_survive_agents_missing a_plugin-cache_install_can_be_killed_partway_and_load_without_complaint 57_skills_loaded_normally_while_agents_were_missing_from_disk daemon_logged_free_924mb_less_than_1024mb_floor git_ls-tree_vs_find_is_the_only_check_that_counts_as_installed in_use_pid_files_are_claude_codes_reference_counting_not_damage the_tag_carried_all_1511_files_the_release_was_not_bad, ocd: 2026-08-07, lmd: 2026-08-07]

A Claude Code plugin-cache install (`~/.claude/plugins/cache/<marketplace>/<plugin>/<ver>/`)
can be KILLED PARTWAY and the result loads without complaint: measured 2026-08-07 (janitor#232),
v2.7.1's cache was missing `agents/`, `commands/`, `hooks/`, `assets/`, `docs/`, `git-hooks/`,
`.claude-plugin/plugin.json` AND `.integrity/manifest-sha256.json` while `skills/` survived —
so 57 skills loaded normally and every `[janitor-memory-*]` marker named an agent that was not
on disk. The daemon logged `free 924MB < 1024MB floor` one minute after the install: memory
pressure, not a bad release (the tag carried all 1511 files). Diagnostic method that settled
it, in order: (1) `git ls-tree -r --name-only <release-tag> | sort` vs `find <cache-dir>
-type f` — the ONLY check that counts as "installed" (files missing = not installed, whatever
loads); (2) the surviving-vs-lost dir split distinguishes an interrupted WRITE from a partial
download; (3) exonerate the janitor's own `cache-prune` from the daemon log's removal lines
before suspecting it. `.in_use/` pid files in a cache dir are Claude Code's reference
counting — normal, not damage.


^ATOM-8WQI-G751 [desc:"Remedy order: CLI reinstall + tag-diff the NEW dir; a hand-patch restores function but verifies against nothing. Since v2.7.2 a missing manifest on an installed root is a finding.", keywords: never_hand_patch_the_cache reinstall_via_claude_plugin_update verify_new_version_dir_against_tag missing_manifest_is_a_finding_since_2.7.2 guard_deleted_by_the_event_it_detects a_hand-patch_restores_function_but_verifies_against_nothing owner_directive_2026-08-07_never_trust_the_cache the_durable_fix_is_claude_plugin_update_via_the_cli janitor-self-integrity.py_used_to_return_none_on_absent_manifest an_installed_root_with_no_manifest_is_now_a_finding a_complete_cache_can_still_serve_stale_already-loaded_skills tag-diff_the_new_dir_after_a_cli_reinstall, ocd: 2026-08-07, lmd: 2026-08-07]

Remedies, in order of trust: a hand-patch from the tag restores function but VERIFIES AGAINST
NOTHING (owner directive 2026-08-07: never trust the cache) — the durable fix is `claude
plugin update` via the CLI followed by the tag-diff on the NEW version dir. Detector side:
`janitor-self-integrity.py` used to return None on an absent manifest, so the one check built
for a partial install was deleted BY the event it detects (the general design lesson lives in
the USER-scope page a-guard-disarmed-by-the-event-it-guards); since v2.7.2 an installed root
with no manifest is a FINDING naming the interrupted-install cause. See
[[claude-code-plugin-rollout-staleness]] for the sibling failure: a COMPLETE cache whose
already-loaded skills stay stale until a new session. [^1]


^ATOM-LFPX-9QX5 [desc: "Agents missing with an INTACT install: /reload-plugins replaces the session agent registry, so a reload for one plugin drops other plugins' agents — restart, do not reinstall", keywords: agents_missing_after_reload agent_type_not_found_but_plugin_installed agent_types_no_longer_available reload-plugins_dropped_agents janitor_agent_not_found fable-advisor_advisor_not_found plugin_unavailable_but_enabledPlugins_true 43_agents_reloaded reload_replaced_agent_registry do_not_reinstall_a_good_cache thin_session_registry restart_restores_agents claude_plugin_list_says_disabled_for_everything enabledPlugins_is_the_reliable_source, trdd: TRDD-HREGVXYP, ocd: 2026-08-29, lmd: 2026-08-29]

`/reload-plugins` REPLACES this session's agent registry rather than merging into it, so a
reload fired for ONE updated plugin drops the agents of every plugin it did not rescan — a
DIFFERENT cause of this page's symptom than a damaged cache, with a different remedy.

MEASURED 2026-08-29 (Claude Code 2.1.251): a reload for a single plugin reported
`1 plugin · 1 skill · 43 agents` and the harness dropped **36 agent types across 9 ENABLED
plugins**, including `ai-maestro-janitor:janitor-{memory-subconscious,repair,security}-agent`,
`fable-advisor:advisor`, and every `claude-plugins-validation:*` agent.

TELL IT APART FROM A BROKEN INSTALL with two cheap reads: `enabledPlugins` in
`~/.claude/settings.json`, and the plugin cache's `agents/` dir. **Both intact ⇒ the install is
fine and only the session's registry is thin** — a RESTART restores it. Do NOT reinstall or
tag-diff the cache (this page's remedy for the other cause: you would be diffing a good cache
against itself), and do NOT `/reload-plugins` again — that is the cause.

`claude plugin list`'s Status column is NOT a check here: run from outside the project it
reported all 76 plugins `✘ disabled`, including ones whose hooks had fired that same turn.

## Notes and lessons learned

[^1]: [id: ATOM-X3NR-20M8, status: valid, desc: "2026-08-19 fleet-bricking recovery: first quarantine mv landed inside the marketplace cache dir", keywords: "reload_reports_load_errors_after_quarantine plugin_surface_missing_after_reload quarantine_location_inside_scanned_tree mv_aside_broken_cache_dir broken_plugin_copy_loaded_as_plugin", ocd: 2026-08-19, lmd: 2026-08-19] DO NOT park a quarantined broken plugin copy inside any tree the plugin scanner walks (the marketplace cache dir, any ~/.claude/plugins/cache/... subdir), BECAUSE the loader tries to load it as a plugin — measured 2026-08-19: the parked broken 3.3.16 produced 7 load errors and the janitor surface failed to register on the user's own /reload-plugins. DO move it OUTSIDE every scanned tree (e.g. ~/.claude/.broken-cache-quarantine/) before re-extracting.
