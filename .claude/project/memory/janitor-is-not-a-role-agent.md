---
name: janitor-is-not-a-role-agent
description: "why are ai-maestro role plugins erroring in this repo / can I install chief-of-staff or maintainer-agent here / claude says 'enabled in project settings but isn't installed here' and offers --scope project / why is the janitor user-scope / what memory survives if another agent takes over this repo / can the janitor play a role like autonomous-agent or chief-of-staff / why does /janitor-arm refuse a project or local scope install / should I run claude plugin install role@ai-maestro-plugins --scope project here / why is there a stale enabledPlugins key for a role plugin / what happens to LOCAL and USER scope memory if a maintainer clones this repo into a container / why must project-scope memory carry no private data / does deleting an enabledPlugins key uninstall anything / is reports/ project-scoped / why are role plugins mutually exclusive / what is a purely functional plugin with no main agent"
ocd: 2026-07-09
lmd: 2026-11-14
metadata:
  node_type: memory
  tier: component
  type: project
publish-globally: false
---

^207VKBD4 [desc:"The janitor is a purely functional user-scope plugin with no main agent/role — it provides capabilities to agents rather than playing a role; /janitor-arm refuses a project/local-scope install.", keywords:"why_is_the_janitor_user_scope can_the_janitor_play_a_role_like_autonomous_agent_or_chief_of_staff why_does_janitor_arm_refuse_a_project_or_local_scope_install what_is_a_purely_functional_plugin_with_no_main_agent user_scope_required_guards_whole_machine"]
**The janitor is not an agent and has no role.** It is the ONE **user-scope**
AI-Maestro plugin: a purely *functional* plugin with no main agent, which provides
capabilities (heartbeat, memory system, drift detectors, the global daemon, the OAuth
rotator) *to* agents. User scope is required — it guards the whole machine, and
`/janitor-arm` refuses a project- or local-scope install.

^3MNZLSHF [desc:"AI-Maestro role plugins (autonomous-agent, chief-of-staff, maintainer-agent) install ONLY at local scope inside a harness agent's own dir, mutually exclusive per project — janitor repo has no role.", keywords:"can_i_install_chief_of_staff_or_maintainer_agent_here why_are_role_plugins_mutually_exclusive role_plugins_are_local_scope_only an_agent_plays_exactly_one_role two_role_plugins_can_never_coexist_in_one_project giving_the_janitor_repo_a_role_plugin_makes_zero_sense"]
**Role plugins are local-scope only, and mutually exclusive.** `ai-maestro-autonomous-agent`,
`ai-maestro-chief-of-staff`, `ai-maestro-maintainer-agent` (and the other roles) install
ONLY at `scope: local`, ONLY inside an AI-Maestro harness agent's own directory. An agent
plays exactly **one** role, so two role plugins can never coexist in one project. Giving
the janitor repo a role plugin makes zero sense — it has no agent to play the role.

^427HSC48 [desc:"When a stale role-plugin key lingers in user-scope enabledPlugins, Claude Code's UI wrongly suggests installing that role at project scope here — never follow it; delete the stale key instead.", keywords:"claude_says_enabled_in_project_settings_but_isnt_installed_here should_i_run_claude_plugin_install_role_scope_project_here why_is_there_a_stale_enabledplugins_key_for_a_role_plugin never_follow_claude_codes_suggestion_here the_fix_is_to_delete_the_stale_key does_deleting_an_enabledplugins_key_uninstall_anything"]
**Never follow Claude Code's suggestion here.** When a stale role-plugin key lingers in
user-scope `enabledPlugins` with no install record for the current project, the plugin UI
reports *"enabled in project settings but isn't installed here"* and offers
`claude plugin install <role>@ai-maestro-plugins --scope project`. Running that would
install a role plugin at project scope in a non-harness repo — exactly what is forbidden.
The message's "project settings" is misleading; no project settings file is involved. The
fix is to **delete the stale key** from user-scope `enabledPlugins` (done 2026-07-09).[^1]

## What survives a maintainer takeover — why PROJECT scope is load-bearing

^61M30BH1 [desc: "What survives a maintainer clone: PROJECT-scope memory and reports/ (both git-tracked); LOCAL/USER memory and reports_dev/ do NOT — plugin-dev knowledge MUST be PROJECT-scope, no private data.", keywords: what_memory_survives_if_another_agent_takes_over_this_repo what_happens_to_local_and_user_scope_memory_if_a_maintainer_clones_this_repo why_must_project_scope_memory_carry_no_private_data is_reports_project_scoped only_project_scope_memory_survives_the_clone would_a_fresh_agent_with_nothing_but_this_repo_need_it, lmd: 2026-11-14]
If a maintainer agent ever takes over development of this plugin, it will **clone the repo
from GitHub into a container**. It will NOT use a developer's local checkout. Therefore
everything not committed to the repo is **lost to it**:

| Artifact | Survives the clone? |
|---|---|
| PROJECT-scope memory (`.claude/project/memory/`, git-tracked via the gitignore exception) | **YES** — the only memory that survives |
| LOCAL-scope memory (per-project, outside the repo) | no |
| USER-scope memory (janitor plugin-data dir) | no |
| `reports/` (git-tracked, redacted by `sanitize-reports` before commit) | **YES** |
| `reports_dev/` (gitignored) | no |

**So any knowledge required to develop or maintain this plugin MUST be written at PROJECT
scope.** That is not a stylistic preference — it is the difference between the next
maintainer having the knowledge and re-deriving it (badly) from scratch. When in doubt
about *where* a fact belongs, ask: "would a fresh agent, with nothing but this repo,
need it?" If yes → PROJECT scope, with no private data (paths, hostnames, tokens); the
`memory-scope-leak` detector polices exactly that. [^2]

^6L0151TS [desc: "Decided and built: reports/ is project-scoped (git-tracked, redacted with sanitize-reports at commit) so findings survive a takeover; private raw output goes to the gitignored reports_dev/.", keywords: reports_project_scoped_decided_and_built reports_tracked_redacted_at_commit is_reports_project_scoped reports_dev_is_the_private_gitignored_dir sanitize-reports_before_commit would_reports_survive_a_maintainer_takeover reports_privacy_question_resolved precommit_redacts_staged_reports owner_ruled_reports_are_git_tracked reports_no_longer_an_open_idea, lmd: 2026-11-14]
**Decided and built (TRDD-KSUIEPTQ):** `reports/` is project-scoped, so audit findings
survive a takeover. Reports routinely carry absolute local paths, credentials seen in
logs, and internal notes, so they are **sanitized** (`sanitize-reports`; the pre-commit
hook redacts staged `reports/` files and blocks the commit if it cannot) before anything
is pushed. Raw or private material goes to the gitignored `reports_dev/`. [^3]

See also [[memory-system]].

## Notes and lessons learned

[^1]: [id:ATOM-MG06-0017, status:valid, keywords:"disabled_enabledplugins_key_not_harmless stale_key_drives_ui_remediation remove_key_not_set_false", ocd:2026-07-09, lmd:2026-07-09] Three role-plugin keys
  (`ai-maestro-autonomous-agent`, `-chief-of-staff`, `-maintainer-agent`) sat in
  user-scope `enabledPlugins` with value `false` and no install record for this repo.
  That alone made Claude Code list them as load errors and recommend a `--scope project`
  install — the one action that would actually break the rule. Lesson: a *disabled* stale
  key is not harmless; it still drives the UI's remediation advice. Remove the key rather
  than relying on `false`. Also: the autonomous-agent's legitimate `scope: local` install
  record for a harness agent lives in a different file (`installed_plugins.json`) and was
  deliberately left untouched — deleting an `enabledPlugins` key does not uninstall
  anything.
[^2]: [id: ATOM-3NVV-8OF1, status: valid, supersedes: 61M30BH1, keywords: "reports_survives_clone reports_tracked_in_git reports_dev_not_survive maintainer_clone_reports does_reports_survive_a_takeover reports_git_tracked_redacted reports_dev_gitignored_lost what_survives_a_maintainer_clone sanitize-reports_at_commit reports_dir_tracked", ocd: 2026-11-14, lmd: 2026-11-14] DO NOT say reports/ does not survive a maintainer clone, BECAUSE reports/ is git-tracked since TRDD-KSUIEPTQ (owner 2026-11-14) and is redacted by sanitize-reports at commit; only the gitignored reports_dev/ is lost. DO list reports/ as surviving and reports_dev/ as not. SUPERSEDED BODY: If a maintainer agent ever takes over development of this plugin, it will **clone the repo from GitHub into a container**. It will NOT use a developer's local checkout. Therefore everything not committed to the repo is **lost to it**: | Artifact | Survives the clone? | |---|---| | PROJECT-scope memory (`.claude/project/memory/`, git-tracked via the gitignore exception) | **YES** — this is the only memory that survives | | LOCAL-scope memory (per-project, outside the repo) | no | | USER-scope memory (janitor plugin-data dir) | no | | `reports/`, `reports_dev/` (gitignored) | no | **So any knowledge required to develop or maintain this plugin MUST be written at PROJECT scope.** That is not a stylistic preference — it is the difference between the next maintainer having the knowledge and re-deriving it (badly) from scratch. When in doubt about *where* a fact belongs, ask: "would a fresh agent, with nothing but this repo, need it?" If yes → PROJECT scope, with no private data (paths, hostnames, tokens); the `memory-scope-leak` detector polices exactly that.
[^3]: [id: ATOM-W09U-KWN9, status: valid, supersedes: 6L0151TS, keywords: "reports_project-scoped_decided reports_tracked_redacted_at_commit is_reports_project_scoped reports_idea_no_longer_open reports_git_tracked_decision sanitize-reports_pre-commit_stage_0 reports_dev_private owner_ruled_reports_tracked reports_survive_takeover_built reports_privacy_resolved", ocd: 2026-11-14, lmd: 2026-11-14] DO NOT call reports/ project-scoping an open, undecided idea, BECAUSE the owner decided it (2026-11-01, re-ordered 2026-11-14) and it is built: reports/ is git-tracked and redacted with sanitize-reports at commit (pre-commit Stage 0), while reports_dev/ stays gitignored (TRDD-KSUIEPTQ). DO treat reports/ as shared, sanitized content. SUPERSEDED BODY: **Open idea, not a decision:** making `reports/` project-scoped so audit findings would also survive a takeover. Blocked on privacy — reports routinely carry absolute local paths, credentials seen in logs, and internal notes. They would have to be **sanitized** before anything is pushed. Nothing has been decided or built. See also [[memory-system]].
