---
name: plugin-cache-install-integrity
description: "the installed plugin is missing agents commands or hooks / Agent type not found but skills load fine / plugin cache incomplete after an update / how to verify an install against its release tag / cache extraction interrupted killed partway / hand-patched cache"
ocd: 2026-08-07
lmd: 2026-08-07
metadata:
  node_type: memory
  type: project
  tier: component
---

# plugin-cache-install-integrity


^ATOM-1F78-3R1G [desc:"A plugin-cache install can be killed partway; verify any install by diffing the cache against the release tag — a hand-patched cache verifies against nothing.", keywords: install_interrupted_under_memory_pressure tag_vs_cache_file_diff surviving_vs_lost_dirs_signature cache_prune_exoneration_daemon_log reinstall_via_cli_never_hand_patch skills_survive_agents_missing, ocd: 2026-08-07, lmd: 2026-08-07]

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


^ATOM-8WQI-G751 [desc:"Remedy order: CLI reinstall + tag-diff the NEW dir; a hand-patch restores function but verifies against nothing. Since v2.7.2 a missing manifest on an installed root is a finding.", keywords: never_hand_patch_the_cache reinstall_via_claude_plugin_update verify_new_version_dir_against_tag missing_manifest_is_a_finding_since_2.7.2 guard_deleted_by_the_event_it_detects, ocd: 2026-08-07, lmd: 2026-08-07]

Remedies, in order of trust: a hand-patch from the tag restores function but VERIFIES AGAINST
NOTHING (owner directive 2026-08-07: never trust the cache) — the durable fix is `claude
plugin update` via the CLI followed by the tag-diff on the NEW version dir. Detector side:
`janitor-self-integrity.py` used to return None on an absent manifest, so the one check built
for a partial install was deleted BY the event it detects (the general design lesson lives in
the USER-scope page a-guard-disarmed-by-the-event-it-guards); since v2.7.2 an installed root
with no manifest is a FINDING naming the interrupted-install cause. See
[[claude-code-plugin-rollout-staleness]] for the sibling failure: a COMPLETE cache whose
already-loaded skills stay stale until a new session.

## Notes and lessons learned
