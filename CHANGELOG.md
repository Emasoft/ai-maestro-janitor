# Changelog

All notable changes to this project will be documented in this file.

## [0.57.0] - 2026-07-21

### Bug Fixes

- Post-compact push must not surprise an attended-but-reading session (TRDD-GRHP2YHP)
- Remove the dead UserPromptSubmit reload-guard hook — /reload-plugins fires no hook (TRDD-Z582IKIR)
- Rename refresh-claude-logins skill -> refresh-cc-logins (CPV N11) (TRDD-EBVZJ6GU)
- Clear all CPV --strict blockers surfaced by the v0.57.0 release

### Documentation

- 6Q0OYYYH shipped in v0.56.0 -> published
- Capture wikimem-writer initiative — R02HTRUD 6RO0L3M0 VPTQ4067 5FNZ7ZKO + GRHP2YHP
- GRHP2YHP → testing, shipped b041ffd (resume-push attended fix)
- Z582IKIR provenance — F1 (c3bde7d) + P1 (224da88) shipped, F0/F2/F3 remain design
- VPTQ4067 → testing, detector shipped 2077d2d (memgrep-lint fold is the A1-dependent follow-up)
- R02HTRUD→testing (a133ff0 verified); unblock 6RO0L3M0+5FNZ7ZKO; ratify 5-key lesson schema
- 6RO0L3M0 → testing, skills converted bc43f1b (supersede/rename verbs = R02HTRUD follow-up)
- Board sweep — 5 wikimem-overhaul TRDDs → complete
- Record the memgrep-verb authoring discipline (ATOM-9AWW-4NCO)
- Add TRDD-EBVZJ6GU — convert 7 agent-relevant commands to skills (keep 3 user-mem for privacy)
- EBVZJ6GU → complete — 7 commands converted to skills (63637d9, 4d0e31c)
- Z582IKIR — F1 reload-guard hook removed (75b2860), premise refuted; auto-defer survives
- Agent-visible reload/compact guards replace removed hook (TRDD-Z582IKIR)
- Z582IKIR STATE — F1 intent moved to agent-side skill warnings (28c1777)

### Features

- /janitor-handoff-and-clear + cross-clear verify harness (TRDD-Z582IKIR)
- Block /reload-plugins above a context threshold (TRDD-Z582IKIR/F1)
- Self-validating wikimem syntax audit + heartbeat detector (TRDD-VPTQ4067)
- Mechanical wikimem write verbs — add-atom, new-page, add-lesson (TRDD-R02HTRUD)
- Add 7 skills converting agent-relevant commands (TRDD-EBVZJ6GU)

### Refactor

- Route authoring through memgrep verbs, keep judgment as prose (TRDD-6RO0L3M0)
- Migrate PROJECT lean lessons to canonical 5-key form (TRDD-5FNZ7ZKO)
- Remove 7 commands now shipped as skills (TRDD-EBVZJ6GU)

### Styling

- Fix MD004 plus-bullet markdown lint (unblocks publish lint gate)

