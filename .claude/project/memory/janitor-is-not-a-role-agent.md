---
name: janitor-is-not-a-role-agent
description: "why are ai-maestro role plugins erroring in this repo / can I install chief-of-staff or maintainer-agent here / claude says 'enabled in project settings but isn't installed here' and offers --scope project / why is the janitor user-scope / what memory survives if another agent takes over this repo / can the janitor play a role like autonomous-agent or chief-of-staff / why does /janitor-arm refuse a project or local scope install / should I run claude plugin install role@ai-maestro-plugins --scope project here / why is there a stale enabledPlugins key for a role plugin / what happens to LOCAL and USER scope memory if a maintainer clones this repo into a container / why must project-scope memory carry no private data / does deleting an enabledPlugins key uninstall anything / is reports/ project-scoped / why are role plugins mutually exclusive / what is a purely functional plugin with no main agent"
ocd: 2026-07-09
lmd: 2026-07-09
metadata:
  node_type: memory
  tier: component
  type: project
---

**The janitor is not an agent and has no role.** It is the ONE **user-scope**
AI-Maestro plugin: a purely *functional* plugin with no main agent, which provides
capabilities (heartbeat, memory system, drift detectors, the global daemon, the OAuth
rotator) *to* agents. User scope is required — it guards the whole machine, and
`/janitor-arm` refuses a project- or local-scope install.

**Role plugins are local-scope only, and mutually exclusive.** `ai-maestro-autonomous-agent`,
`ai-maestro-chief-of-staff`, `ai-maestro-maintainer-agent` (and the other roles) install
ONLY at `scope: local`, ONLY inside an AI-Maestro harness agent's own directory. An agent
plays exactly **one** role, so two role plugins can never coexist in one project. Giving
the janitor repo a role plugin makes zero sense — it has no agent to play the role.

**Never follow Claude Code's suggestion here.** When a stale role-plugin key lingers in
user-scope `enabledPlugins` with no install record for the current project, the plugin UI
reports *"enabled in project settings but isn't installed here"* and offers
`claude plugin install <role>@ai-maestro-plugins --scope project`. Running that would
install a role plugin at project scope in a non-harness repo — exactly what is forbidden.
The message's "project settings" is misleading; no project settings file is involved. The
fix is to **delete the stale key** from user-scope `enabledPlugins` (done 2026-07-09).[^1]

## What survives a maintainer takeover — why PROJECT scope is load-bearing

If a maintainer agent ever takes over development of this plugin, it will **clone the repo
from GitHub into a container**. It will NOT use a developer's local checkout. Therefore
everything not committed to the repo is **lost to it**:

| Artifact | Survives the clone? |
|---|---|
| PROJECT-scope memory (`.claude/project/memory/`, git-tracked via the gitignore exception) | **YES** — this is the only memory that survives |
| LOCAL-scope memory (per-project, outside the repo) | no |
| USER-scope memory (janitor plugin-data dir) | no |
| `reports/`, `reports_dev/` (gitignored) | no |

**So any knowledge required to develop or maintain this plugin MUST be written at PROJECT
scope.** That is not a stylistic preference — it is the difference between the next
maintainer having the knowledge and re-deriving it (badly) from scratch. When in doubt
about *where* a fact belongs, ask: "would a fresh agent, with nothing but this repo,
need it?" If yes → PROJECT scope, with no private data (paths, hostnames, tokens); the
`memory-scope-leak` detector polices exactly that.

**Open idea, not a decision:** making `reports/` project-scoped so audit findings would
also survive a takeover. Blocked on privacy — reports routinely carry absolute local
paths, credentials seen in logs, and internal notes. They would have to be **sanitized**
before anything is pushed. Nothing has been decided or built.

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
