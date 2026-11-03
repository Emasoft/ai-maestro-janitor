---
trdd-id: 8FYNVBWL
title: Hand the 3-pillars rules, detectors and hook over to the 3-pillars plugin
column: backburner
status: tasked
created: 2026-11-04T00:00:42+0100
updated: 2026-11-04T00:56:10+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: refactor
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T00:00:42+0100
---

# Hand the 3-pillars rules, detectors and hook over to the 3-pillars plugin

## User directive (verbatim, 2026-11-03, given to the 3-pillars-tasks-management session and repeated to this session)

> this plugin is being developed to replace the scattered 3-pillars rules that were scattered between 3 different plugins (ai-maestro project scope, ai-maestro-plugin and ai-maestro-janitor). so you must move all the rules, skills and hooks/agents (if any) here, in this plugin. no more things left in other plugins that are related to the 3-pillars-rules. this plugin will be then installed at user scope, and all agents will have full access to the rules, the skills and the 4 tools of the 3-pillars system. in addition to a mod that we are going to create soon that will display the kanban board of the whole fleet.

## Janitor side

- Starts only after the 3-pillars plugin is published on the Emasoft emasoft-plugins marketplace and installed at user scope (USER ruling 3, 2026-10-21). Until then the janitor keeps shipping its copies unchanged.
- Drop rules/prrd-design-rules.md, rules/trdd-design-tasks.md, rules/universal-kanban.md and rules/references/prrd-design-rules-full.md, trdd-design-tasks-full.md, universal-kanban-3p300-columns.md.
- Drop the detectors scripts/detectors/trdd-drift.py, trdd-reminder.py, trdd-state-reconciliation.py, trdd-cross-card-blindspot.py, report-to-trdd-drift.py and the hook scripts/hooks/on-session-start-trdd-state.py, with their tests and registrations, once the 3-pillars plugin ships their replacements.
- scripts/lib/rules_installer.py: stop installing those files, and never overwrite or remove a rules file whose provenance marker is not the janitor's.
- Janitor code that stays and reads cards (dispatch.py _blocked_reason, tests/test_secret_shield_wiring_gate.py) moves off scripts/lib/trdd_common.py onto the global trddgrep the 3-pillars plugin installs at user scope (trddgrep --porcelain). USER ruling 2026-11-04, verbatim: "the trddgrep as all the other tools must migrate in the 3-pillars plugin now. it will install them at user scope (in the path or symlinked in bin)  when it will be installed, so they will be available globallly. what it needs me for? ask the claude of the 3-pillars plugin with sendmessage instead."
- The moved detector must keep: the fixes of TRDD-OEEH2W28, the hold test from 842a8835, and the blocked-by DONE_COLUMNS hold that TRDD-2V7OAUPE relies on.
- The 3-pillars session sends the final file list and the installer hand-over before anything is removed.
- Firm contract (everything else in the 3-pillars plan stays provisional until the owner reviews it): the janitor resolves trddgrep from PATH, runs trddgrep --version, and fails unless the output contains 3-pillars-tasks-management (the name in that plugin.json, as reported by the 3-pillars session). --version does not exist yet; the 3-pillars session reports it will add it in its phase P1, so this check stays off until that plugin is installed. Where trddgrep is installed is provisional: the 3-pillars session reports a stable shim in its DATA dir as the likely design, pending a hand-over with ai-maestro, whose installer it reports writes the same tool names into the user bin dir today.
- Release N+1: the janitor package ships the same files on every machine, so dropping them from the package removes them everywhere; only the installer run-time cleanup of installed copies can depend on the machine. Options for the owner and the 3-pillars session: (a) N+1 drops the files and declares the 3-pillars plugin as a plugin.json dependency (that dependency mechanism is not yet verified), the option consistent with the owner directive that nothing 3-pillars stays in other plugins; (b) as a transition only, N+1 keeps the files, switched off by the release N stand-down while the 3-pillars plugin is enabled. The janitor rules cleanup deletes any rules file containing the janitor installed-rule marker, so the 3-pillars copies must not carry it (agreed: they drop the janitor guard block).
- If D2 moves the detectors, these move with them: tests/test_trdd_drift_unblock_when.py, the trdd_common.py checks (Check 4 included) and the open defect card TRDD-OEEH2W28; if D2 keeps them in the janitor, they stay and OEEH2W28 is worked here. Either way dispatch.py and the secret-shield wiring gate test need a column reader: trddgrep --porcelain, or trddgrep show --json (which the 3-pillars session reports it will add in phase P1) where STATE blocks, blocked-by, npt, eht or implementation-commits are needed.
- Source of truth for everything outside the janitor: the 3-pillars migration plan, in the 3-pillars-tasks-management repo at design/specs/proposals/20261104_001734+0100-3pillars-migration-plan.md, with its card TRDD-53GAE0MO. The 3-pillars session states that its plan wins over its own card. Owner rulings win over both that plan and this card.
- Also in N+1: the further janitor items the plan lists for N+1 (the writers that create cards, the LOCAL design mirror, janitor-footprint.md, and the tests and userConfig keys tied to these rules). Read them from the plan; this card does not copy the list, so it cannot drift.
- The release N stand-down applies only if the owner decides (3-pillars plan decision D2) that the five detectors and the STATE hook move to the 3-pillars plugin. If they stay in the janitor, they keep running and nothing stands down.

## Found during

- Cross-session messages from the 3-pillars-tasks-management session, 2026-11-03, during TRDD-M1218EMH.

## Approval log

- 2026-11-04T00:00:42+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Provisional contract with the 3-pillars session (pending USER review of the 3-pillars migration plan)

- Marker: a rules file containing 3-pillars-tasks-management:installed-rule is not the janitor's; release N never overwrites or removes it.
- Stand-down (only if decision D2 moves the detectors to the 3-pillars plugin): while the plugin named 3-pillars-tasks-management (from any marketplace) is enabled in any enabledPlugins scope, the five TRDD detectors and on-session-start-trdd-state.py stand down (release N). Expected marketplace emasoft-plugins, not verified until it is published.
- Order: janitor release N, then the 3-pillars publish and user-scope install, then janitor release N+1. Nothing is published on either side without the owner's word, and release N is not built before the owner approves the migration plan.
- PROVISIONAL (depends on where trddgrep is installed): CI: once the gate test calls trddgrep, it fails loudly when trddgrep is missing, and the janitor CI installs the 3-pillars plugin's trddgrep (not the copy in ai-maestro).
- Answered by the 3-pillars session on 2026-11-04 (see the plan): the references go to the user rules-reference dir under the same file names, each carrying the 3-pillars marker; its installer takes over a janitor-stamped file once; it also takes over three owner-written files that carry no marker, once each after saving a backup (see the takeover bullet below; open: 3-pillars plan decision D7); it never touches any other file that lacks its marker; version= is the plugin semver, and an installed copy is replaced only by a newer one; uninstall removes only files carrying the 3-pillars marker, through a command that plugin ships.
- Takeover of owner files (open: 3-pillars plan decision D7; answers from the 3-pillars session on 2026-11-04, nothing built yet): (1) governance-trdd-kanban.md and trdd-read-whole-card.md are taken over in the user rules dir, and governance-trdd-kanban-full.md in the user rules-reference dir. (2) Before overwriting a file that lacks the 3-pillars marker, the installer always writes a new <name>.bak-<YYYYMMDD_HHMMSS±HHMM> in the same directory, and skips it only when the current bytes match an existing <name>.bak* exactly; for a file that already carries the 3-pillars marker, a backup is written only when its bytes differ from the SHA-256 the installer recorded at its last write, so an edit made after the takeover is never lost. (3) Restoring the newest pre-takeover backup brings back the owner-approved text; only the oldest backup, .bak-20261103_233825+0100, holds the pre-edit text; whether uninstall restores a backup, and which one, is the owner's decision. (4) In both directories a file is written only when it is absent, carries the 3-pillars marker at an older version, or carries the janitor stamp or marker without the 3-pillars marker; any other same-named file is never touched. The takeover is an explicit exception to point 4, by exact file name: the installer carries a fixed list of these three names and no pattern.
