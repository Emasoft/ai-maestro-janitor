---
trdd-id: 8VNDKCEG
title: repo_digest misses a second edit to an already dirty file so the drift detector can stay silent on a stale map
column: backburner
status: tasked
created: 2026-11-15T12:57:23+0100
updated: 2026-11-15T13:08:34+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-15T12:57:23+0100
parent-trdd: FADYLSQB
---

# repo_digest misses a second edit to an already dirty file so the drift detector can stay silent on a stale map

repo_digest (scripts/repomap_generate.py) hashes `git status --porcelain` plus HEAD, so a second edit to a file already listed as modified (` M path`) does not change the digest. The drift detector (scripts/detectors/project-map-drift.py) caches a per-digest verdict in `project-map-fresh-at.digest`: once a digest has been judged structure-fresh, a later STRUCTURAL edit that leaves the digest unchanged is suppressed by that stamp, so the detector stays silent on a stale map while `repomap_generate.py --check` reports STALE.

Pre-existing, not introduced by TRDD-FADYLSQB. Found by the increment-3 worker; its test commits between the two edits to avoid the path (see the comment in test_detector_stays_silent_on_a_comment_only_change_when_the_map_has_a_coverage_note).

Reproduced 2026-11-15 on a throwaway git repo: generate the map, opt in, append a comment to a tracked source file (detector silent, correct, stamp written), then append a new function to the same file without committing (detector silent, WRONG; `--check` prints STALE; `git status --porcelain` unchanged: ` M pkg/a.py`).

Reproduce first, as a failing test, before any fix. Candidate directions (decide after reproducing): fold a content signal of the modified files into the digest (for example `git diff` hash or the files mtimes/sizes), or stop caching the verdict per digest. Constraint: the digest must stay cheap (it runs every heartbeat, zero extraction cost).

## Approval log

- 2026-11-15T12:57:23+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-15T13:00:10+0100 — CAUSE ISOLATED (worker): on a throwaway repo, recorded digest cb3563151400; after a comment edit the digest was 5387f4ed0a39, the detector was silent and the stamp took 5387f4ed0a39; after a second structural edit to the same file the digest was STILL 5387f4ed0a39, the detector was silent and --check printed STALE; CONTROL: deleting the stamp file made the same detector print the STALE nudge. So the per-digest stamp is what suppresses it, and the digest not moving is what lets the stamp apply.
- 2026-11-15T13:08:30+0100 — RELATED silent degradation in the same function (main agent read the code): repo_digest treats a failed `git status --porcelain` as empty (`or ""`) after HEAD succeeded, so the digest can equal an older clean-tree digest and the fresh stamp holds with nothing logged; a failed `git rev-parse HEAD` silently falls back to a source-mtime digest. Pre-existing; decide together with the dirty-file blind spot.
