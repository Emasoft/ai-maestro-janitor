# Changelog

All notable changes to this project will be documented in this file.

## [0.5.0] - 2026-05-20

### Features

- New `screenshot-purge` detector for `<project_root>/reports/screenshots/` —
  the canonical browser-UI screenshot folder per
  `~/.claude/rules/browser-ui-test-techniques.md` §19. Runs on a 1-hour
  cadence with two independent policies:
  - **Age-based**: removes files older than `screenshot_max_age_hours`
    (default 72 h). Uses file mtime — test runners control it correctly,
    unlike `.trashcan/` batches where folder-name timestamps defeat
    accidental `touch`.
  - **Low-disk override**: when free space drops below
    `screenshot_lowdisk_min_free_gb` (default 5 GiB), deletes oldest
    screenshots first regardless of age until free space recovers above
    `screenshot_lowdisk_target_free_gb` (default 10 GiB). The min/target
    hysteresis prevents oscillation at the threshold.
  - Only files with `.png .jpg .jpeg .webp .gif` extensions inside
    `reports/screenshots/` are touched. `.gitkeep`, `README.txt`, and the
    directory itself are never removed.
  - Screenshots bypass `safe-delete` / `.trashcan/` because they are
    regeneratable test artefacts per `~/.claude/rules/use-safe-delete.md`.

### Configuration

New userConfig keys (all with sensible defaults — zero config required):

- `screenshot_purge_enabled` (boolean, default true)
- `screenshot_max_age_hours` (number, default 72)
- `screenshot_lowdisk_min_free_gb` (number, default 5; set 0 to disable
  low-disk mode)
- `screenshot_lowdisk_target_free_gb` (number, default 10)
- `screenshot_purge_interval` (number, default 3600 seconds)

## [0.4.13] - 2026-05-16

### Documentation

- Add CC v2.1.143 entry to "Recent Claude Code fixes"

