---
trdd-id: fe45babc-6567-4622-862b-de19db908ad5
title: Autonomous overnight session — OAuth survival + memory-system + immortality GROUP C + issue coordination
column: dev
created: 2026-06-22T02:20:07+0200
updated: 2026-06-23T10:13:41+0200
current-owner: claude-janitor-dev
assignee: claude-janitor-dev
task-type: infra
release-via: none
relevant-rules: []
test-requirements: [unit]
impacts: []
external-refs: ["github.com/Emasoft/ai-maestro-janitor/issues"]
---

# Autonomous overnight session — the night brain (read on every wake)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; the task queue + next action) — 2026-06-22

USER directive (verbatim, 2026-06-22 ~02:15): *"i will go to sleep. You must work all
night to fix all the issues and complete the immortality and the memory system. be sure
to keep reading and writing to issues on github and coordinating with the other claudes.
… use any means necessary to continue. … the current window of the current oauth is soon
going to finish. so you must switch oauth token soon."* Then `/go-on-yourself`.

### STANDING CONSTRAINTS (never violate)
- **This IS a plugin project → PUSH + PUBLISH are AUTHORIZED via `scripts/publish.py`.**
  (Updated `/go-on-yourself` 2026-06-22: *"Do not push unless you are working on a plugin
  project. … If it is a plugin, publish using the publish.py script. It has strict quality
  and security gates."*) Publish COHERENT, TESTED milestones only — never half-done work.
  Do NOT hand-`git push` / `gh release`; `publish.py` OWNS the version bump + tag + release
  + all gates (validate --strict, lint, tests). After a publish: daemon auto-updates →
  `/reload-plugins` → `/janitor-arm` (activates new hooks/skills/the subconscious agent).
- **GitHub issue WRITES are ALLOWED** (the user explicitly asked to read+write issues and
  coordinate). Comment + close issues as their fix ships.
- No changes outside the project dir + `/tmp`. TRDD per change. TDD where possible.
  Commit often, stage by name (never `git add -A`). Never relax security/quality gates.
- Per PRRD G1.1: every GitHub post starts with a one-line self-identification.

### OAUTH SURVIVAL (check FIRST on every wake — this is the lifeline)
- Rotator opted-in; daemon alive (manages 60s ticks). Two accounts:
  `emanuele.sabetta@gmail.com` + `fmuaddib@gmail.com`. BOTH near 7d limits (~90-93%).
- **At 02:20 force-rotated LIVE → `fmuaddib` (5h=0% fresh); `emanuele` 5h≈95% recovering.**
- Rule each wake: `ROT=…/0.15.0/scripts/oauth_rotator/rotator.py`;
  `uv run --script --quiet "$ROT" usage`. If the LIVE account is **>88% on 5h OR 7d**,
  `… "$ROT" switch <other-email>`. The built-in auto-rotate NEAR threshold is too lax
  (said "within limits" at 92%) — manage manually until that's fixed (queue item M0).
- Budget is TIGHT (both ~90%+ on 7d). Prioritize high-value work; commit often so a
  mid-night stall loses nothing.

### CONTINUATION MECHANISM
- Heartbeat cron (`*/5`, session-only) = janitor dispatch (silent).
- **Work-driver cron** (separate, ~15 min) fires `[night-work]` turns that re-read THIS
  TRDD's STATE and do the next queue item. Fresh context each wake — so this STATE block
  is the ONLY memory; keep it current (update the done-log + NEXT ACTION every commit).

### NEXT ACTION (post-reset — weekly budget EXHAUSTED ~03:30)
All cheap M1 inline fixes are DONE+committed+coordinated (#54/#55/#59/#53 fixed; #56
decided+answered). Weekly budget is now spent: fmuaddib 7d=100% (dead), emanuele 7d=95%
(live, ~5% left). **STOP starting new work — wind down clean.** The [night-work] cron keeps
firing; turns die on the weekly limit until **Jun 23 17:00 Europe/Rome**, then auto-resume.

POST-RESET, in order:
1. **PUBLISH** — ⚠️ **BLOCKED on a USER DECISION** (discovered 2026-06-23 10:13, post-compaction).
   `publish.py --minor --dry-run` FAILS CPV --strict (`CRITICAL=6 MAJOR=4`). Disposition:
   - **4 persistence CRITICALs = THE REAL BLOCKER.** `scripts/daemon-launcher.py:63` +
     `scripts/lib/launchd_keepalive.py:71/176/186` are the IMMORTALITY OS-keepalive (GROUP
     A/B, on main). CPV's security gate flags them `skillaudit:persistence` and **refuses
     suppression** — `_intentional_validator_false_positives` is NOT honored for security
     findings (upstream CPV **#40** open for exactly this). They are LOAD-BEARING (CPV's own
     `plugin-devitalizer` REFUSES to neutralize a genuine persistence feature), and the
     immortality plan says *"No push until USER approves."* → cannot pass --strict by any
     legitimate means tonight. **USER DECISION NEEDED — pick one, do NOT relax the gate / do
     NOT devitalize (would break immortality):**
       (a) WAIT for CPV #40 (an honored by-design exemption), then publish the whole batch; OR
       (b) SEPARATE the release — gate the OS-keepalive behind an unshipped flag / move
           `daemon-launcher.py`+`launchd_keepalive.py` out of the published tree so v0.16.0
           ships the MEMORY work alone; immortality ships later as its own reviewed release.
           (CARE: the daemon imports launchd_keepalive — real release-eng, not a delete.)
   - **2 injection CRITICALs (plugin.json:703-704) — FIXED this turn:** they were OUR OWN
     unicode allowlist strings tripping the injection scanner; pruned (the array doesn't
     suppress anyway). 6→4 CRIT.
   - **2 unicode MAJORs (fleet_status.py:706-707) — CLEAN-FIXABLE, not yet done:** the JS
     sanitizer's `.replace()` needles are raw U+2028/U+2029; rewrite as Python ` `/` `
     escapes (identical runtime, ASCII source). Edit can't match the invisible chars → needs a
     careful full-function Write (read exact bytes, reconstruct).
   - **2 skill-size MAJORs (split ~5350, consolidate ~5100):** CPV's "bpe estimate" ≈30% >
     tiktoken (I trimmed against tiktoken: 4092/3909). Need body < ~14,650 chars → trim more /
     move detail to references/. Moot while persistence blocks.
   Bundles (when unblocked): memory FP fixes (42099f5,903e293,d0eaeb9), subconscious-agent
   (619cedd), fail-safe seam-split (9ef9da1,a0f1fab), size raise (8cecaff), trims (04ab8a5).
   Then `/reload-plugins` + `/janitor-arm`.
2. **CLOSE** #54, #55, #59, #53, #60 (all fixed; #60 = the subconscious-agent dispatch).
   Comment the published version on each.
3. **#56** the real fix (repair serializer → top-level ocd/lmd + migration) — see its
   investigation pointer above. Then close #56.
4. Then M3 (granular subconscious-agent skills) / M4 (#57/#58 un-splittable) / C (#228
   self-integrity) as budget allows.

### BUDGET REALITY (critical)
WEEKLY limit was hit ~02:30 on fmuaddib (7d was 93%). User did manual `/login` → both
accounts now 5h≈1% (fresh) but **7d=91%, resets Jun 23 17:00 Europe/Rome**. So only ~9%
weekly budget until then. NO subagents (4-way burst throttled; a single one then hit the
weekly wall). Inline, frugal, commit often. A 4-parallel-spark burst = instant throttle.

### TASK QUEUE (priority order — budget-aware: cheap+certain first)
- **M0** — Make the rotator auto-rotate NEAR threshold configurable + lower the default
  (it said "within limits" at 92% → overnight stall risk). TRDD + test. (HIGH value for
  survival, but careful — don't break the rotator; do AFTER M1 once on fresh token.)
- **M1** — Memory detector/serializer FALSE-POSITIVE fixes (independent, parallelizable):
  - #53 memory-scope-leak: `machine-host` FP on GitHub `action@sha` pin syntax.
  - #54 memory-librarian: flags sibling `*-proposed.md` detector outputs as malformed notes.
  - #55 memory-librarian: MEMORY.md-sync flags every note "missing from MEMORY.md" but
    MEMORY.md is the deprecated stub.
  - #56 memory repair serializer nests ocd/lmd under `metadata:` — diverges from the
    write-skill top-level shape (two frontmatter shapes coexist). **DECISION MADE
    (verified, posted to #56): TOP-LEVEL is canonical** — memgrep reads top-level
    `ocd`/`lmd` (`scripts/memgrep/src/memory.rs:195`, `has(["ocd","created"])`); a nested
    page is seen as MISSING `ocd` (date lost), and the live corpus + the doc are top-level.
    INVESTIGATION POINTER for the fix: grep found NO Python re-serializer building a nested
    metadata dict — `_REQUIRED_FM_KEYS` (memory_edit_verify.py:524) lists ocd/lmd but
    `parse_frontmatter` likely FLATTENS metadata→top-level so verify_repair passed on BOTH
    shapes. So the nesting is either the repair-SKILL checklist wording leading the agent to
    nest, OR a round-trip in parse/emit. FIX (post-reset): (a) make the repair skill +
    verify_repair ENFORCE top-level ocd/lmd so a nested stage is rejected→repaired; (b) a
    one-time migration moving metadata.ocd/lmd → top-level on existing nested pages. Needs
    care (don't break already-nested pages mid-flight) → not a near-wall task.
  - #59 trdd-reminder: reports `backburner` proto-TRDDs as "active"; age is
    days-since-updated not true age.
- **M2** — #60 (background-dispatch wikimem passes): ALREADY built (commit 619cedd, the
  janitor-memory-subconscious-agent). Comment on #60 that it's addressed + publish-pending.
- **M3** — Granular memory skills (the subconscious-agent toolkit), on DEFAULTS since the
  user is asleep: keep `merge` inside `consolidate`, keep `conflict` (not rename to
  harmonize). AUTHOR new txn-gated skills + their verify_* + tests: `create-expander`,
  `create-reducer`, `verifier`, `deduplicate`, `check-references`, `scope-validation`.
  Inject each into `agents/janitor-memory-subconscious-agent.md` `skills:` as it lands.
  (LARGE — do in batches, TDD, commit per skill.)
- **M4** — #57/#58 un-splittable convergence: a type:reference archive with no `##` seams
  over split_max_bytes abstains every cycle. Build the seam-synthesizing auto-split.
- **C** — Immortality GROUP C (self-integrity, #228): ship `.integrity/manifest-sha256.json`,
  flip self-integrity ENFORCING, verify-before-exec gate in dispatcher-stub, pin-good/
  quarantine-bad rollback. (LARGE — careful; don't brick the janitor.)
- **COORD** — As each item lands: comment on its issue (self-identify per G1.1), close
  when fully fixed+committed (note "committed not pushed; ships in next publish").

### DONE LOG (append; most recent last)
- 02:20 — OAuth force-rotated → fmuaddib (fresh 5h). Night infra set up (this TRDD).
- 02:30 — hit WEEKLY limit (4-spark burst throttled, then 1 spark hit weekly wall). User
  did manual /login. Lesson: NO subagent bursts; inline-only under budget.
- 02:45 — #54+#55 librarian FP fixes DONE+committed (42099f5): completed the dying spark's
  work, retired _collect_memory_sync_findings to no-op, removed 3 dead helpers, +6 tests,
  56/56 green, ruff clean. Commented on #54+#55.
- 03:05 — #59 trdd-reminder DONE+committed (903e293): trimmed _ACTIVE_COLUMNS to the 4 WORK
  columns (backburner/todo/dispatch no longer "active"); age now from created: not mtime
  (_created_epoch parser); +4 tests, 17/17 green, ruff clean.
- BUDGET: 7d climbed to 94% on BOTH accounts (~6% weekly left until Jun 23 17:00 reset).
  Rotation can't help (both equal on 7d). If [night-work] turns start dying on the weekly
  limit, that's EXPECTED — the cron keeps firing; turns resume automatically after the
  reset. Everything is committed clean; nothing is lost.
- 03:20 — #56 DECIDED+answered (f9a2070): top-level ocd/lmd canonical (memgrep reads
  top-level); real fix deferred post-reset with investigation pointer. Commented on #56.
- 03:30 — #53 scope-leak action@sha FP FIXED+committed (d0eaeb9): _allow_ssh_host suppresses
  a pure-hex 7-40 char SHA right-side; +2 tests, 30/30 green, ruff clean.
- 03:30 — WEEKLY BUDGET EXHAUSTED: fmuaddib 7d=100% (dead), emanuele 7d=95% (live). Night
  fixes COMPLETE for this budget window. Winding down clean. NEXT WAKE WITH BUDGET: publish
  + close issues (see NEXT ACTION). 4 issues fixed (#54/#55/#59/#53), 1 decided (#56), all
  committed, all coordinated on GitHub. A productive night despite the early weekly wall.
- 2026-06-23 10:13 (post-COMPACTION continuation) — BUDGET STILL CAPPED: both accounts
  7d=100% (reset Jun 23 **17:00** Europe/Rome, ~7h out). Actions: (1) Re-armed the EXPIRED
  heartbeat — CronList was empty, the stacked `[janitor-renew]`s were correct; re-created
  session-only `8f2ee482` WITH the `[night-work]` block preserved (a stock /janitor-arm would
  have dropped the overnight loop). (2) Stopped the stale skill-trim spark `a3a1fab4` — it was
  burning capped quota in a tiktoken-install retry loop; its trims were already on disk +
  verified (tiktoken cl100k: split body 4092 / consolidate 3909 / record-recent 2889 / desc
  147 — all under caps; the step-3a SEAM-SYNTHESIS fail-safe survived the trim, verified).
  Committed trims + .markdownlintignore (**04ab8a5**). (3) Ran `publish.py --minor --dry-run`
  → **DISCOVERED THE CPV --strict PUBLISH BLOCKER** (see NEXT ACTION §1): the immortality
  launchd persistence can't pass CPV's security gate, can't be suppressed (CPV #40), can't be
  devitalized → **USER DECISION needed (wait-for-#40 vs separate-the-release).** (4) Pruned the
  2 self-inflicted injection CRITICALs (plugin.json:703-704). Did NOT publish (capped budget
  AND the blocker). **M4 (#57/#58 seam-synthesis split) is DONE** (9ef9da1 is_legal_split
  oversized + a0f1fab skill step-3a + 8cecaff size raise) — the M4 queue line is stale.
  Winding down per the prior session's directive; the loop auto-resumes after the 17:00 reset.

### SUPERSEDED — do NOT carry forward
- The earlier idea of waiting for the user's naming calls on the granular skills — the
  user is asleep + said "complete the memory system"; proceed on the M3 defaults above.

## Durable artifacts to read before acting
- `design/tasks/TRDD-…-aebedbff-…md` — the 3-tier memory architecture (subconscious agent).
- `design/tasks/TRDD-…-324223a6` + the immortality plan — GROUPS A/B done, C pending.
- The 3 OAuth memory notes (rotator 3-layer architecture + design directives + renew transport).
- Open issues: `gh issue list --repo Emasoft/ai-maestro-janitor --state open`.
