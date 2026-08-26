---
name: plugin-cache-install-integrity
description: "the installed plugin is missing agents commands or hooks / Agent type not found but skills load fine / plugin cache incomplete after an update / how to verify an install against its release tag / cache extraction interrupted killed partway / hand-patched cache / every tool blocked machine-wide PreToolUse hook Errno 2 missing hook script / reload reports load errors after parking a quarantined broken copy inside a scanned cache tree / an install was killed by memory pressure not a bad release / how to diff a cache directory against a release tag / is a missing manifest-sha256.json a real finding / never hand-patch the plugin cache / a pid file in the cache dir looks suspicious is it damage / why does the plugin loader try to load a quarantined broken copy / how to root-cause a partially installed plugin / a quarantined broken plugin copy caused fleet-wide load errors / quarantine directory must sit outside every scanned tree"
ocd: 2026-08-07
lmd: 2026-08-19
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

## Notes and lessons learned

[^1]: [id: ATOM-X3NR-20M8, status: valid, desc: "2026-08-19 fleet-bricking recovery: first quarantine mv landed inside the marketplace cache dir", keywords: "reload_reports_load_errors_after_quarantine plugin_surface_missing_after_reload quarantine_location_inside_scanned_tree mv_aside_broken_cache_dir broken_plugin_copy_loaded_as_plugin", ocd: 2026-08-19, lmd: 2026-08-19] DO NOT park a quarantined broken plugin copy inside any tree the plugin scanner walks (the marketplace cache dir, any ~/.claude/plugins/cache/... subdir), BECAUSE the loader tries to load it as a plugin — measured 2026-08-19: the parked broken 3.3.16 produced 7 load errors and the janitor surface failed to register on the user's own /reload-plugins. DO move it OUTSIDE every scanned tree (e.g. ~/.claude/.broken-cache-quarantine/) before re-extracting.
