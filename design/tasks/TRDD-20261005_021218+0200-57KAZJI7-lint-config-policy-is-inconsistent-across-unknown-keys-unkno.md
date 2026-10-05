---
trdd-id: 57KAZJI7
title: Lint config policy is inconsistent across unknown keys unknown selectors and several roots
column: backburner
status: tasked
created: 2026-10-05T02:12:18+0200
updated: 2026-10-05T02:12:18+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-05T02:12:18+0200
---

# Lint config policy is inconsistent across unknown keys unknown selectors and several roots

Found 2026-10-05 while reviewing C21 (TRDD-3HLI7DMK). Facts read in source. (1) scripts/memgrep/src/lint_config.rs RawLint has deny_unknown_fields, so an unknown KEY under the lint table makes the whole file fail to load (CONFIG-001, built-in defaults); C21 makes an unknown selector VALUE in a config file only a stderr warning. A config written for a newer memgrep therefore still breaks an older binary through a new key. scripts/lib/suppression.py reads the same table with dict get and ignores unknown keys, so the two tools already disagree on one file. Proposed single rule: in a DISCOVERED config anything unknown warns and is ignored; in an explicit --config anything unknown is an error. (2) lint_config_for in memory.rs discovers the config from the FIRST linted path only; scripts/detectors/wikimem-syntax.py lints the three memory scope roots in one call, so a config found above the first root applies to pages of the other two. (3) --ignore on the command line REPLACES the config ignore list (ruff adds); pinned by a C21 test as today's behaviour, not decided. (4) per-file-ignores globs are matched against the path as given on the command line, while suppression.py matches relative to the config directory. (5) CONFIG-001 is not in design/specs/issue-codes.toml, so it is a stderr line, cannot be selected or ignored, and is absent from --output-format json. None of this bites on this machine today: no .janitor.toml exists in the home directory or this repository (checked 2026-10-05). First step: decide the single rule in (1) and whether discovery is per page or per root, then register CONFIG-001.

## Approval log

- 2026-10-05T02:12:18+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
