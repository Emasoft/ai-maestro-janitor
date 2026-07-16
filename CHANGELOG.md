# Changelog

All notable changes to this project will be documented in this file.

## [0.46.0] - 2026-07-16

### Bug Fixes

- Safe half of the ai-maestro preparedness audit — F5 + F8 (TRDD-AM8JD9SG)
- Keep-going continue-nudge is ON by default in every mode (TRDD-93TKV769)
- Self-trigger presence is PER-PANE, 5-min window (TRDD-T7N67AQP)
- Gate agentlens cause on materiality — stop mis-blaming a workspace (TRDD-3KDN6O9Z)

### Documentation

- Mark the v0.45.0 memory-series TRDDs published
- Capture the v0.45.0 release lessons on the publish-pipeline pages
- Record impl commit eb9faa1 on TRDD-AM8JD9SG
- AM8JD9SG blocked-by ai-maestro#68 — coordination filed, publish gated
- CPV v2.159.0 fixes the resolver-tag detector FPs (#167/#168) — verify before bumping the pin
- AM8JD9SG — record ai-maestro#68 direction (R42 ground-shift + 8 verdicts + F11)
- AM8JD9SG — USER ruled F1+F6 = scoped daemon principal + provenance root
- AM8JD9SG — daemon-migration architecture coordination (janitor#100)
- Add TRDD-PZLVT2RN — ai-maestro-tailored janitor (#J) + #N scope-flip + two-backend split
- PZLVT2RN — ack landed on janitor#100 (aligned; awaiting owner direction)
- 93TKV769 — code complete + committed (7cd8ea0); column complete, publish held
- T7N67AQP — record impl commit 001bb3e (per-pane presence complete)
- T7N67AQP — record commit e5888b2 (kitty/WezTerm terminal coverage)
- Capture WHY of keep-going default-on + per-pane presence (TRDD-93TKV769, T7N67AQP)
- 3KDN6O9Z — record impl commit 6a56d63 (burn materiality gate complete)
- Fix MD004 markdownlint NIT — no wrapped line starts with '+ ' (issue #113)

### Features

- Detect kitty + WezTerm panes; namespace pane keys by source (TRDD-T7N67AQP)

