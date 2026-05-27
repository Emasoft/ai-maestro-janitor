# Changelog

All notable changes to this project will be documented in this file.

## [0.5.1] - 2026-05-27

### Bug Fixes

- Split workflow-{doctor,create} SKILL.md into references
- Add TOC to workflow-set-generation.md reference
- Clear 4 SkillAudit FPs in instruction-loadable files
- Complete Sentinel coverage (32/32) + self-audit fixes
- Align Sentinel recipe severities with emitted labels
- Make heartbeat auto-renewal silent (no more 6-day reminder)
- Drop unused pytest imports + split combined import line
- Clear pymarkdown findings blocking the publish pipeline
- Clear CRITICAL path leak + MAJOR ruff/PEP-723/typing findings
- Clear remaining MAJOR + MINOR + NIT findings
- Kill remaining ReDoS in rules_injection.py JQ_PATTERN
- Align docstrings + README with the actual #65/#66/#71 code
- Unify list markers in branch-protection-setup SKILL.md (MD004)
- Rephrase guard_mode_enabled description to clear MCP_SCHEMA_POISON NIT

### Documentation

- Add TRDD-ca754708 — port Sentinel GitHub-Actions rule set into janitor workflow auditor
- Add TRDD-631fa3de — evaluate janitor security guard mode

### Features

- Add janitor-github-workflow-{doctor,create}
- Add 5 supply-chain skills + restructure for CPV strict gate
- Single-pass google-re2 RegexSet classifier (Python re fallback)
- Port Sentinel GitHub-Actions rule set into workflow-doctor
- Add workflow-security + branch-protection heartbeat detectors
- Single global janitor daemon owns marketplace-refresh + user-plugins-update (closes #7)
- PreToolUse hook blocks package-manager safety bypasses (closes #8)
- Package-manager-policy detector — supply-chain hardening audit
- [janitor-reload] + daemon self-restart on plugin upgrade
- /janitor-autofix-on + /janitor-autofix-off opt-out toggle
- Move version-update auto-update branch into the daemon (#66)
- Security guard mode Option B — branch-protection baseline (#65)
- Scope per-session to local+project, lower daemon to 20 min (#71)

### Tests

- Fix ruff I001 import-sort in zizmor classifier tests

### Ci

- Add zizmor security audit + fix 11 of 12 findings

