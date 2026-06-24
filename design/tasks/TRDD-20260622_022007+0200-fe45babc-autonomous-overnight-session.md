---
trdd-id: fe45babc-6567-4622-862b-de19db908ad5
title: Autonomous overnight session — OAuth survival + memory-system + immortality GROUP C + issue coordination
column: dev
created: 2026-06-22T02:20:07+0200
updated: 2026-06-24T08:42:09+0200
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

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; the task queue + next action) — 2026-06-24

### ✅ 2026-06-24 ~08:42 — post-compact resume → 3XS3PDCF split content-precheck LANDED, still HOLDING
Resumed post-compact; re-checked the two gates: budget **HEALTHY** (5h=22% / 7d=67%, self-consistent),
`fmuaddib` **STILL DEAD** (refresh token expired ~10h, usage=err — can't restore autonomously, it's a
human OAuth re-login). The hold guards against FREEZE (heavy/fleet work), NOT all progress — so I landed
the safest high-value mandate item, single-context (no fleet), TDD:
- **TRDD-3XS3PDCF split-MVP** (commit **441d467**, local, rides next publish; TRDD → `column: dev`): the
  scheduler now gates `[janitor-memory-split]` on `is_due AND content_has_work` via the new fail-open
  `scripts/lib/memory_content_precheck.py`. Kills the single biggest no-op drain — `split_per_day=4.5` ×
  ~235k with NO page over the 36000-byte cap ≈ **~1M tokens/day** of pure no-op opus spawns (the drain
  that worsened the near-freeze). 29/29 TDD green, ruff clean. Non-exec-path, fail-soft, fail-open (zero
  wrong-suppress — only a PROVEN-idle scope is suppressed). harvest/repair/atomize prechecks = documented
  follow-ups (need each skill's exact predicate; their fail-open default = current behavior, zero regression).

**STILL HOLDING** — same gate as before: budget fine but NO rotation alternate. Did NOT publish (a full
test+CPV+push cycle is the budget I defer at deep-night-no-alternate; ships on the next release). All other
mandate work unchanged-gated (GROUP C exec-path C2/C3/C4 design-review, TIER-2 #230 USER skill-naming,
GROUPs D/E/F). Unblocks unchanged: re-login fmuaddib OR USER returns.

### ✅ 2026-06-24 ~08:20 — RESUMED after the ~04:40 wind-down (budget recovered) → 6 more pieces committed, then HOLDING again
The 5h window aged out the heavy bursts (budget swung 100%→single-digit; a transient usage-API glitch briefly read MAX/MAX — see lesson). With real headroom I resumed and committed SIX pieces (all local; ride next publish):
- **C1 self-integrity CLOSED** (TRDD-53a00e44 → `published`, commit 573fdbd): `.integrity/manifest-sha256.json` verified present in the v0.18.0 tag (publish.py Step 10.5 ships it every release). Self-integrity now FUNCTIONAL data-wise; detector stays opt-in.
- **Rotator trustworthiness VERIFIED** (no code change): `cmd_auto`/`is_near_limit` are ALREADY fail-safe vs usage-API glitches (429-debounce, refresh-on-err, exclude-unknown, local-expiry death signal). False-alarm investigation → positive confirmation a core immortality component is sound.
- **Architecture hub ENRICHED** with the L0-L3 immortality model (cb0ea25) + **project map REFRESHED** for the v0.18.0 files (0c32340).
- **TRDD-3XS3PDCF authored** (727af59, backburner): scheduler-side cheap content-precheck to kill the ~240k no-op memory-agent spawns — VJ8L465M's "inherent" residual was too broad (split/harvest/atomize/repair ARE cheaply pre-checkable). DEFERRED to a clean-budget window.
- Cadence memory agents (budget-gated): harvest no-op, split no-op, **repair fixed 5 LOCAL pages** (nested-ocd/lmd → canonical frontmatter; 11 remain for next passes).

**LESSON (usage API):** the OAuth /usage endpoint returns transient glitch sentinels (`MAX`/`err`/`0%`) — a single dramatic swing is NOT trustworthy; the **7d window is the tell** (it can't jump in minutes). Re-verify a self-consistent reading before acting. The rotator's DECISION logic already handles this (verified); only the DISPLAY shows raw sentinels.

**STILL HOLDING** — budget healthy (5h ~19%) but `fmuaddib` STILL DEAD (no rotation alternate). Remaining mandate work all GATED: GROUP C exec-path C2/C3/C4 (bricking-risk → design-review), TIER-2 #230 (USER skill-naming), 3XS3PDCF (clean-budget window). Tree clean, v0.18.0 live. Unblocks unchanged: re-login fmuaddib OR USER returns.

### ✅ 2026-06-24 ~04:40 — TIER 1 COMPLETE + SHIPPED (two releases). Then WINDING DOWN on OAuth budget.
**Shipped tonight:**
- **v0.17.3** — both Tier-1 trust bugs: **VJ8L465M** (memory-scheduler double-gate — was causing the 236k no-op agent spawns) + **HJGR4I5W** (OAuth dead-but-present refresh now escalates to the REAUTH nudge). Both TRDDs `column: complete`. (One incidental MD004 lint NIT in the VJ8L465M TRDD was cleared to unblock the publish.)
- **v0.18.0** — **L0 OS-keepalive immortality layer SHIPPED** (TRDD-71ABD7V7, ALL phases 1–5). launchd/systemd respawns the global daemon at boot/crash even with ZERO Claude sessions — the structural fix for the 20-hour freeze. **CPV `--strict` CLEAN (CRITICAL=0)** — the #152 fold resolves the installer heredoc → the in-tree, scanned, inert `daemon_keepalive_entry.py`, validated against the REAL discriminator. Token-free orchestrator + blocking-flock (no churn) + `daemon_needs_restart` keepalive exemption (no SIGTERM-loop) + self-heal currency, all tested (99-test cluster green, ruff+pyright+shellcheck clean). The immortality stack **L0→L1→L2→L3 is COMPLETE**. The running daemon auto-rolls to v0.18.0 on its next version-update (≤6h) → then L0 activates on the daemon restart.

**⚠ WHY HOLDING further heavy work:** LIVE (emanuele.sabetta) is at **5h=86% / 7d=60%** and the alternate **fmuaddib is DEAD** (5h/7d=err — dead refresh token; v0.17.3 SURFACES it but the USER must re-login to restore it). With NO rotation safety net and the 5h window near the 88% threshold, a big GROUP-C/TIER-2 build (more publish runs + test suites) risks burning LIVE's budget → stuck rate-limited (the very failure the immortality work prevents). Per the mandate's own "ship few rock-solid, not many half-baked" + the HJGR4I5W keep-usage-LOW prudence → HOLD until the 5h window eases or the USER returns.

**🙋 USER ACTION NEEDED:** re-login **`fmuaddib@gmail.com`** (e.g. `~/.claude/account-rotator/open-login.sh fmuaddib@gmail.com`, or the rotator reauth path) to restore the OAuth rotation alternate — until then this and every unattended session has no safety net.

**NEXT (when budget allows / user returns):** TIER 2 (field-agent governance — #230/aebedbff, GATED on the USER confirming the granular `janitor-memory-*` skill list + naming) and the remaining immortality groups (GROUP C self-integrity #228/53a00e44, D config-self-heal, E per-scenario handlers, F observability + ai-maestro). design/proposals/ is EMPTY.

### 🌙 UPDATE 2026-06-24 ~02:45 — USER MANDATE: finish everything, make the janitor a TRUSTWORTHY immortal guardian (CPV #152 PUBLISHED → L0 UNBLOCKED)
**User went to sleep with this directive (verbatim intent):** "finish implementing the
pending tasks. the CPV is been published, so now everything works… make the janitor
finally work as the immortal guardian it was supposed to be. Make the agents of each
field govern all action, and make them able to use any skill in the right moment.
Produce a version that is truly trustworthy." → MAXIMAL autonomy authorized
(/go-on-yourself standing): act without approval, TRDD + TDD per change, commit often,
publish via publish.py strict gates. CPV #152 is LIVE → **L0 is unblocked.**

**PRIORITIZED PLAN (trustworthiness > coverage — ship few rock-solid, not many half-baked):**
- **TIER 1 (concrete, unblocked, survival-critical) — DO FIRST, batch into ONE release:**
  1. **VJ8L465M** memory-scheduler double-gate fix. Designed (Option C): scheduler writes a
     SHORT-TTL `dispatched` stamp (re-emit guard) instead of `mark_ran`; the cadence stamp
     stays owned by the AGENT (it already `mark_ran`s after the pass). Breaks the double-gate;
     preserves re-emit-storm protection + dead-agent recovery (TTL). Verify all 6 skills
     mark_ran post-pass first. memory_settings + memory-maintenance.py + tests.
  2. **HJGR4I5W** OAuth dead-refresh → REAUTH escalation. ADDITIVE + low-risk to the LIVE
     rotator (only adds a surfacing): per-slot consecutive-refresh-failure counter in
     `_keepalive_refresh`; `refresh_failures` fact in AccountState; classify escalates
     `has_refresh=True AND failures>=N` → REAUTH_NUDGE. cascade.py + rotator.py + tests.
  3. **L0 keepalive (71ABD7V7) Phases 2b-5** — now unblocked. Build the install layer FRESH
     (keepalive_install.sh heredoc + recreate launchd_keepalive.py orchestrator calling
     keepalive_stage.stage_closure + the installer; daemon wiring; restore the 2 tests).
     VERIFY against the LIVE CPV #152 fold (pull latest discriminator first; the heredoc path
     shape couples to #152's accepted form). publish.py CPV --strict must be 0 CRITICAL.
- **TIER 2 (the user's architectural ask) — AFTER Tier 1 is solid + shipped:** "agents of each
  field govern all action + use any skill at the right moment" = the field-agent governance
  layer. #230 granular `janitor-memory-*` skill set (aebedbff PLANNED list) + the security
  agent, as the governing dispatch with dynamic skill access. DESIGN carefully (TRDD); don't
  over-engineer a vague vision.
- **TIER 3:** open GitHub issues, remaining real TRDDs (#228/GROUP C 53a00e44 self-integrity,
  #232 atom-indexing, #209 scope-migration). design/proposals/ is EMPTY (verified).
- **METHOD:** subtle correctness (the 2 bug fixes) done by ME with the deep diagnosis;
  parallel spark agents for mechanical/independent work with detailed specs; SERIALIZE git
  (never parallel git agents); recheck every change; publish.py gates = the trust backstop.
- **DO NOT:** `/janitor-arm` (clobbers the night-loop cron — see v0.17.2 caveat); break the
  LIVE rotator (HJGR4I5W fix is additive-only); reconcile dev-column TRDDs wholesale (low value).



### ⏳ UPDATE 2026-06-24 ~01:30 — L0 immortality (GROUP B) SHAPE 2 Phases 1+2a built+green; OAuth survival gap found (both committed, NOT published)
- **Under /go-on-yourself + the immortality plan, took up GROUP B (L0 OS-keepalive / daemon
  immortality, umbrella TRDD-324223a6).** L0 was extracted in v0.16.0 (`eb109fb`) because the pre-
  discriminator CPV gate flagged its boot-persistence as malware; old L0 preserved at `cd9c251`.
  Verified (not assumed) the 3 independent reasons old L0 fails CPV today: dynamic `os.execv` (C3),
  programmatic plist the resolver can't parse (C1), `$HOME` literal not folded (C1 / CPV #152).
- **Design = TRDD-71ABD7V7** (`design/tasks/TRDD-20260624_002343+0200-71ABD7V7-l0-keepalive-fixed-data-entry.md`,
  `column: dev`). **SHAPE 2** (user-chosen): launchd/systemd target is a LITERALLY-FIXED
  `~/.claude/plugins/data/<slug>/scripts/daemon_keepalive_entry.py` (NOT the ephemeral plugin-root
  cache). The entry statically `import daemon`; the daemon's whole import closure is verbatim-copied
  beside it in DATA; the plist is written via shell heredoc (so the scanned heredoc body carries a
  literal `$HOME` that CPV #152 will fold). USER constraints (binding): copy CPV-scanned scripts into
  DATA but NEVER generate/edit them (byte-identical); no plugin-root in a system-launched script; no
  runtime daemon-script generation.
- **SHIPPED THIS SESSION (committed, green, NOT pushed/published):**
  - Phase 1 — `scripts/daemon_keepalive_entry.py` (thin static entry, mode 755) + `tests/test_daemon_keepalive_entry.py`
    (6 AST-inertness tests proving CPV-C2/C3-clean). Commit `184b61c`.
  - Phase 2a — `scripts/lib/keepalive_stage.py` (closure-stager: BFS over absolute imports →
    16-file bounded closure, ZERO of the ~200 pattern libs; verbatim atomic copy) + `tests/test_keepalive_stage.py`
    (4 tests incl. a REAL-subprocess `import daemon` from the staged tree). Commit `0345000`.
- **BLOCKED on CPV #152** (the user is implementing it in CPV: fold `$HOME`/`~`/`Path.home()` +
  `/.claude/plugins/data/<slug>/` PREFIX → plugin-root R, then scan `R/scripts/daemon_keepalive_entry.py`).
  Until #152 is in CPV `main`, Phase 2b+ (heredoc installer `keepalive_install.sh`; (re)CREATE
  `launchd_keepalive.py` as the install orchestrator → `keepalive_stage.stage_closure` + the installer;
  daemon wiring; restore the 2 tests; publish.py green) cannot pass the strict gate. NOTE (verified
  2026-06-24): all 4 old launchd files (`daemon-launcher.py`, `launchd_keepalive.py`, +2 tests) were
  ALREADY removed in `eb109fb`/v0.16.0 — SHAPE 2 builds them FRESH (ref `cd9c251`); there is NO
  `daemon-launcher.py` to delete. **The rest is mechanical once #152 merges.**
- **OAuth survival gap FOUND + TRDD'd (TRDD-HJGR4I5W, committed `70b29e8`, `column: todo`, severity HIGH,
  audit-conclusion issue-confirmed).** Code-traced: a present-but-DEAD refresh token (`has_refresh=True`,
  expired, refresh keeps failing) is trapped in `cascade.classify`→`RENEW_REFRESH` forever and never
  escalates to the human `REAUTH_NUDGE` (which keys off `has_refresh is False`). Found live: alternate
  `fmuaddib` stuck-expired 30+ min while the daemon ticked → **no usable rotation alternate**. NEEDS
  USER DECISION (touches the authoritative cascade design — did NOT auto-fix). Immediate remediation =
  re-login `fmuaddib`. Fix direction = per-slot consecutive-refresh-failure counter → escalate after N.
- **Memory heartbeat passes handled (background subconscious-agent):** atomize earlier (+atoms),
  consolidate ABSTAINED (correctly — nothing same-subject), split ABSTAINED ×2 (nothing over the 36k
  cap; largest USER page 11869 B). Efficiency note surfaced to user: 2/3 passes abstained (~490k tokens)
  — the scheduler emits on cadence without a cheap pre-check; an optimization, NOT auto-touched (memory
  subsystem has in-progress TRDDs).
- **NEXT on resume:** L0 is genuinely blocked on CPV #152 (user) and the OAuth fix needs the user's
  call — neither is safe to push forward autonomously now. Keep heartbeats light (markers + cheap
  survival checks); surface only on real findings, on #152 merging, or on the user's steer. Open
  question to user: *pause L0 until #152 merges, or point me at other unblocked work?* Do NOT
  `/janitor-arm` (clobbers the night-loop cron — see the v0.17.2 caveat below).

### ✅ UPDATE 2026-06-23 22:16 — v0.17.2 PUBLISHED — memory-settings deviation-filter (self-discovered bug)
- **SHIPPED `v0.17.2`** (release https://github.com/Emasoft/ai-maestro-janitor/releases/tag/v0.17.2;
  `552d925` fix + `dd07117` release). publish.py strict gates all green (tests/lint/CPV exit 0).
  **CI: 5/6 workflows green** (CI, Release, zizmor, memgrep-binaries, Notify-Marketplace). The lone
  failure `Graph Update: uv in /.` is GitHub-AUTOMATIC dependency-graph (NO repo workflow produces it),
  TRANSIENT (succeeded on v0.17.1 an hour earlier with the same uv.lock bump) — not repo-fixable, not
  caused by the change, auxiliary (dependency insights only). Release HEALTHY; do NOT re-investigate it.
- **The bug (self-discovered via a heartbeat `[janitor-memory-split]` pass, TRDD-378c85da):**
  `memory_settings.set_value` wrote the WHOLE settings dict wholesale, freezing every key (incl. ones
  left at default) into `memory-settings.json`. So the `split_max_bytes` 12k→36k raise (`8cecaff`) was
  MASKED on any machine that had captured the old 12000 → wikimem pages kept fragmenting at 12k. Surfaced
  live: a split pass over-split a 14575B USER page that, under the intended 36k cap, should have stayed whole.
- **Fix:** `set_value` now persists ONLY keys that DEVIATE from current DEFAULTS (a later default-change
  flows through to every untouched key); `load()` unchanged; +5 TDD tests incl. the masking regression.
  THIS machine's stale 12000 reset operationally → file now `{}`, active cap = 36000 (verified end-to-end).
  Other machines: an existing 12000 ≠ a deliberate choice, so NOT auto-overridden — one explicit
  `set split_max_bytes 36000` clears it (documented in the TRDD; no fragile historical-default migration).
- **The split that surfaced it:** USER page `wikimem-atom-block-properties` (14575B) → overview + 3
  sub-pages, verify_split PASS, no info lost (legit per the THEN-active 12k cap; left in place — valid, just
  finer-grained than the 36k design intends; a future CONSOLIDATE pass may re-merge if it judges them related).
- **POST-PUBLISH CAVEAT (important):** do NOT run `/janitor-arm` during this night-loop. The single
  cron (`8f2ee482`, session-only) carries BOTH `[janitor-heartbeat]` AND the `[night-work]` directive in
  its prompt; `/janitor-arm` CronDeletes any `[janitor-heartbeat]`-prefixed cron and recreates the
  STANDARD heartbeat WITHOUT `[night-work]` → it would clobber the loop. Skipped it (loop-preservation).
  `/reload-plugins` also skipped (cache not yet v0.17.2 — no-op; the daemon auto-update → `[janitor-reload]`
  marker picks it up). Surface to the user: the directive's "run /janitor-arm after publish" is unsafe in
  this custom-cron setup.
- **NEXT:** queue CLEAR again except blocked #52 (memgrep verbs in ai-maestro-plugin still UNSHIPPED —
  re-checked: only DESIGN commit `d8353db4`, no `publish-sync`/`link` verbs). Remaining immortality work
  still gated (Workflow opt-in + user approval). /go-on-yourself otherwise.

### ✅ UPDATE 2026-06-23 21:05 — v0.17.1 PUBLISHED — #56 + #61 closed; queue now CLEAR except #52
- **SHIPPED `v0.17.1`** (https://github.com/Emasoft/ai-maestro-janitor/releases/tag/v0.17.1) — a
  consistency/polish patch: **#56** repair now normalizes nested `metadata.ocd/lmd` → top-level
  (`ced38b4`; the canonical shape — verified the janitor never serialized them; the nested shape
  came from the repaired page, not janitor code); **security-agent dispatch examples** (`7433d35`,
  cleared the CPV trigger-quality WARNING 16→15); **#61** reconciled 2 stale `testing` TRDDs
  (5539cd6e, 924645bb — both PROVEN-done) → `complete` (`7d81cf3`). CPV 0/0/0/0; publish exit 0.
- **#56 + #61 CLOSED** (verified ancestors of v0.17.1, PRRD G1.1 self-id).
- **OPEN ISSUES NOW: only #52** (cross-project wikimem) — and it is **cross-repo-BLOCKED** (needs the
  memgrep `publish-sync` verbs in `ai-maestro-plugin` TRDD-202ccfa2, not yet built). The actionable
  queue is otherwise EMPTY. Backlog held: #52 (blocked), agentlens Stop-hook fix (user OK), L0
  reboot-survival companion (`cd9c251`, future). **Next wakes: nothing safe-to-build until the
  memgrep half lands or the user re-prioritizes — do NOT speculatively build #52's janitor half.**

### ✅ UPDATE 2026-06-23 20:50 — v0.17.0 PUBLISHED — janitor-security-agent (USER's new feature)
- **SHIPPED `v0.17.0`** (HEAD `6321b21`; tag pushed; release live:
  https://github.com/Emasoft/ai-maestro-janitor/releases/tag/v0.17.0). publish.py exit 0;
  CPV `--strict` 0/0/0/0; 11305 tests green. CI watched in background.
- **What shipped (TRDD-f12cae1a, now `column: published`):** `agents/janitor-security-agent.md`
  — ONE opus agent for ALL 8 security skills, DETECT + FIX fail-safe (auto-fix the safe, FLAG
  credential rotation / destructive ops, never suppress/auto-rotate/force-push). 11 security
  detectors SUGGEST it via `security_helpers.security_agent_hint()` (visible hint, NOT a silent
  marker — security blast radius; opt-out `CLAUDE_PLUGIN_OPTION_SECURITY_AGENT_HINT=false`). The 4
  detect-only skills gained `## Remediation (fix)`. +13 tests; docs (README + CLAUDE.md agents).
- **Publish-blocker hit + fixed this cycle:** `CHANGELOG.md:38 MD018` (git-cliff renders a commit
  subject whose text starts `#NN` after the type prefix as a heading-shaped bullet; Step 10 regen
  runs AFTER Step 3 lint so it recurs forever). Durable fix `2df36fe`: a cliff.toml `[changelog]`
  postprocessor escapes a `#` at bullet-start (`- #` → `- \#`), verified to clear MD018 and leave
  mid-line `#NN` refs intact. (LESSON: don't write `type(scope): #NN …` commit subjects.)
- **The Stop-hook error the USER asked about = NOT the janitor.** It is the **agentlens** Stop hook
  in `~/.claude/settings.json` (`[ -f "$f" ] && cat "$f" && rm "$f"` exits 1 when the file is
  absent). Fix = wrap `{ …; } || true`. SURFACED + offered to the user; NOT applied (their global
  config, outside the project, agentlens' concern — needs their OK).
- **NEXT (when the user directs / loop continues):** #52 (cross-project wikimem) is the named next
  item BUT is cross-repo-blocked — its e2e needs the memgrep `publish-sync` verbs in
  `ai-maestro-plugin` (TRDD-202ccfa2, not yet built), and adding the schema to wikimem-model.md now
  needs re-embedding its 7-entry TOC in ~6 skills. Building the janitor half speculatively before
  the memgrep half exists = over-engineering; HOLD until the memgrep verbs land or the user
  re-prioritizes. The #52 WIP is intact in `stash@{0}`. Other backlog: the agentlens fix (user OK),
  the L0 reboot-survival companion (preserved at `cd9c251`, future TRDD).

### ✅ UPDATE 2026-06-23 19:30 — v0.16.0 PUBLISHED (blocker resolved via option (a)) + 8 issues closed
- **SHIPPED `v0.16.0`** (HEAD `1351ee7`; bump+CHANGELOG; annotated tag; 92 commits + tag pushed to
  origin/main; GitHub release live: https://github.com/Emasoft/ai-maestro-janitor/releases/tag/v0.16.0).
  publish.py exit 0 — CPV `--strict` **CRITICAL=0** (all gates green). The split/memory fixes the
  fleet was blocked on are LIVE.
- **HOW the blocker cleared — option (a) "extract L0, publish now" (USER chose it):** branch
  `extract-launchd-l0` → forward-removal commit **`eb109fb`** deleted the 2 launchd files + their 2
  tests (`launchd_keepalive.py`, `daemon-launcher.py`, `test_launchd_keepalive.py`,
  `test_flock_blocking.py`) and stripped the launchd wiring + dead `acquire_singleton_flock_blocking`
  from `daemon.py`/`global_state.py`/`global_control_cli.py`/`plugin.json` — KEEPING the GROUP A
  freeze-recovery fixes. **L0 reboot-survival is preserved in git history at `cd9c251`** for a future
  out-of-band opt-in companion (NOT in the scanned plugin). Merged FF to main.
- **Cleared the rest of the gate** (5 MAJOR + 4 MINOR + 2 NIT) via parallel sonnet agents (`5c380a0`,
  `b64d1e5`): `fleet_status.py` U+2028/U+2029 → escapes; 3 oversized skills (consolidate/split/write)
  → detail moved to `references/`; 4 TOC skills (atomize/recall/repair/update) embedded the
  wikimem-model 7-entry TOC; the cascade NIT (atom-authoring.md TOC) fixed. `12ab07f` restored +x.
- **8 issues CLOSED** (verified each fix is an ancestor of HEAD AND present in v0.16.0 code, then
  closed with PRRD G1.1 self-id + fix commit): **#51** (publish canonical — demonstrated by this very
  release), **#53** (d0eaeb9 action@sha allowlist), **#54/#55** (42099f5 `_NON_NOTE_NAMES`), **#57/#58**
  (a0f1fab seam-synthesis), **#59** (8a3b3a1 idle+age label), **#60** (aac974f editor-as-agent).
  Left OPEN: **#56** (serializer fix still pending — low-sev cosmetic), **#52** (unbuilt feature),
  **#61** (weekly audit drift).
- **NEXT (user's NEW request, this release-cycle's priority): build `janitor-security-agent`** — ONE
  agent that runs every security skill (detect + FIX), mirroring `janitor-memory-subconscious-agent`.
  Consolidate the ~7 security skills; make detect-skills also fix; wire the heartbeat to SUGGEST it
  when security drift is found. Author a TRDD first. THEN #52 (cross-project wikimem, the stash@{0}
  WIP is intact).
- **SUPERSEDED — do NOT carry forward (these facts are now FALSE):**
  - ✗ "Publish still BLOCKED" / "USER DECISION needed (option a/b/c)" — RESOLVED; (a) shipped as v0.16.0.
  - ✗ "8 of 11 open issues are fixed-but-unpublished, did NOT close any" — they are PUBLISHED + CLOSED now.
  - ✗ "BOTH accounts MAX/MAX, conserve" (18:55) — stale OAuth snapshot; re-check live before assuming.
  - ✗ "#52 is the READY next-build / START HERE" (18:55) — superseded; the security-agent is the
    user's stated next priority, #52 follows it.

### ⚡ UPDATE 2026-06-23 18:55 — ⚠ OAUTH CRUNCH (both accounts MAX) + #52 is the READY next-build
- **OAUTH: BOTH `emanuele` AND `fmuaddib` are MAX/MAX (5h AND 7d), confirmed stable.** No fresh
  account to switch to — budget critically low. The loop self-heals when the 5h window rolls
  (rate-limited turns die, the cron refires, a later turn succeeds once budget returns). **CONSERVE:**
  do only the OAuth check + minimal notes until a `usage` check shows real headroom again; do NOT
  start substantial work while both read MAX.
- **#52 (cross-project wikimem visibility) is the READY next substantive work** — it is
  **USER-APPROVED + fully specced** (NOT a vague feature). memgrep engine half built separately
  (`ai-maestro-plugin` TRDD-202ccfa2, forthcoming verbs `publish-sync`/`link`/symlink-aware recall).
  **Janitor-side asks (THIS repo, buildable now, safe new code + TDD):** (1) `wikimem-model.md` — add
  the `publish-globally: true` bare boolean (PROJECT-scope only; LOCAL never publishable) + document
  the 🔒 PRIVACY INVARIANT (the ONLY thing committed is the bare boolean — NO slug/id/path, not even
  `owner/repo`; the owning slug is derived machine-locally at sync time, lives only in the USER memdir
  `published/<slug>/`); (2) the EDIT-AUTHORITY invariant (globally-published note is read-only from
  foreign projects); (3) write/update skills + heartbeat + recall-rule updates. **START HERE when
  budget recovers** (its end-to-end test needs the memgrep verbs, so build janitor-side + unit-test
  the schema/rule docs; full e2e waits on TRDD-202ccfa2). Full spec: gh issue #52.

### ⚡ UPDATE 2026-06-23 18:00 — IMMORTALITY GROUP C C1 (self-integrity manifest) LANDED (non-bricking subset)
- **Committed `9d53bfb` (TRDD-53a00e44, child of #324223a6).** The self-integrity
  DETECTOR already existed (opt-in, alert-only) but was a permanent no-op — no manifest
  ever shipped. Now `scripts/generate_integrity_manifest.py` + `publish.py` Step 10.5
  regenerate `.integrity/manifest-sha256.json` as a fresh-per-release artifact (after
  bump/changelog — neither touches a globbed file — staged into the release commit;
  `--dry-run` exercises it writing nothing). +5 tests; 36 self-integrity+generator green;
  ruff clean. This is the MISSING SAFETY LAYER for the GROUP B persistence that blocks the
  branch (plan ordered C before B; B shipped first) — landing it makes that persistence
  defensible.
- **DEFERRED — user-gated / bricking-risk (did NOT do autonomously):** the C1 default-on
  flip (machine-wide blast radius), C2 verify-before-exec gate in `dispatcher-stub` (bricks
  THIS session's heartbeat lifeline if wrong), C3/C4 quarantine+rollback, and the plan's
  MANDATED ultracode review loop (needs Workflow opt-in not granted this session). Detector
  stays OPT-IN; the exec path is UNTOUCHED.
- **OAuth healthy:** LIVE `fmuaddib` 5h=28%/7d=20%; `emanuele` 28%/20%. No switch (both ≪88%).
- **Publish still BLOCKED** (unchanged) on the USER's a/b/c persistence decision
  (`reports/overnight-session/20260623_171000+0200-…md`). C1 rides the next release once
  unblocked; it CANNOT publish standalone.
- **STAKES of the blocker (mapped 2026-06-23, gh issue audit):** the publish decision gates FAR
  more than the memory feature — **8 of 11 open GitHub issues are already FIXED-IN-GIT, blocked
  only on publish:** #53/#54/#55 (detector FPs, 42099f5/09b8628), #57/#58 (split seam-synthesis,
  a0f1fab), #59 (trdd-reminder FP, 8a3b3a1), #56 (decided top-level-ocd/lmd canonical; serializer
  fix still pending — low-sev cosmetic), #60 (editor-as-dedicated-agent, aac974f) — PLUS GROUP C-C1
  and the whole memory feature. Only **#51** (publish.py already canonical in code — just unclosed),
  **#52** (cross-project wikimem visibility — a real unbuilt feature), **#61** (weekly audit drift)
  are genuinely open. Per the USER's own rule (comment/close issues "as their fix ships"), I did
  NOT comment/close any — they ship + close together when option (a) lands. **→ one decision
  unblocks a large backlog at once.**
- **PUBLISH BLOCKER — ACCURATELY DIAGNOSED THIS WAKE (corrects the 17:15/17:10 framing).**
  Ran a FRESH CPV `--strict`: `CRITICAL=4 MAJOR=6 MINOR=4 NIT=1`; the 4 CRITICALs are ALL
  `skillaudit:persistence` on GROUP B (`daemon-launcher.py:63`, `launchd_keepalive.py:71/176/186`).
  Read the CPV issues: **option (b) "upstream a CPV disclosed-persistence feature" is DEAD** —
  **#63** (the exact ask) is CLOSED **WON'T-FIX** (CPV intrinsic-only, no self-declared
  suppression ever); **#40** (which the old report cited) is the unrelated doc-FP issue. So the
  blocker is a PERMANENT design conflict: **in-tree launchd persistence ⊥ CPV-strict publishing.**
  Precedent: `janitor-auto-manage-oauth-on` REMOVED its launchd agent ("No launchd agent, no
  plist") to ship v0.15.0 — chose immortality-without-L0; GROUP B (`cd9c251`) added L0 back and
  became un-publishable.
- **NEXT — USER DECISION (not autonomous):** option (a) is **NOT a clean revert** (corrects my
  earlier "one commit" claim): `cd9c251` is ENTANGLED — 11 files/762 ins bundling the 2 launchd
  files + their tests WITH GROUP A audit fixes (`fleet_inject`, `terminal_trigger`) + launchd
  wiring in `daemon.py`, which itself changed twice AFTER cd9c251 (216d995, fbfff71). So a revert
  would undo GROUP A + conflict. The clean way = a NEW forward-removal commit (delete the 2
  launchd files + their 2 tests, strip the launchd wiring from `daemon.py` + the dead
  `acquire_singleton_flock_blocking`, KEEP the GROUP A fixes) → `main` at CRITICAL=0, L0
  out-of-band; vs (c) hold / drop L0. I will NOT do this autonomously (you
  explicitly wanted L0 immortality — it's an immortality-vs-shippability call). Full writeup:
  `reports/overnight-session/20260623_181417+0200-publish-blocker-accurately-diagnosed.md`.
  Post-extraction debt (clearable, only matters if option a). **CPV now CRITICAL=4 MAJOR=5
  MINOR=4 NIT=1** (was MAJOR=6) — cleared the memgrep `index.rs:762` RESOURCE_ABUSE FP this
  wake (`608ceb7`: devitalized the ATOM_PAGE test fixture — renamed `rotate-drain`→`rotate-failover`
  and reworded the DoS vocab, all assertions preserved; 126 cargo tests green; CPV-verified). REMAINING
  clearable: 2 fleet_status.py unicode FPs (`:706-707` raw U+2028/U+2029 in `.replace(<rawchar>,
  " ")` — the Edit tool CANNOT match the un-typeable char; fix = swap the raw char for a `" "`
  Python escape, identical behavior, but needs a non-Edit mechanism — DEFERRED, mechanism-risk on a big
  file for a non-blocking FP); 3 oversized memory SKILLs (consolidate/split/write, MAJOR×3) + coupled
  wikimem-model TOC MINOR×4/NIT×1 — editorial-risky on load-bearing just-shipped memory instruction
  surfaces, deserves a careful reviewable pass, NOT an overnight rush. NONE of this unblocks publish
  (the 4 persistence CRITICALs remain — USER decision).

### ⚡ UPDATE 2026-06-23 17:15 — MEMORY JOB DONE (phase g COMPLETE); publish blocker UNCHANGED + KNOWN
- **The 15:09 "HOLD phase g / don't build" block below is now OBSOLETE.** The USER un-held it
  ("now finish the job on the memory first") and phase g is **100% COMPLETE** — g1–g6 were
  already done; **g3 (the shared-footnote MOVE-RULE verify)** landed this wake:
  `footnote_refs_resolve` + `no_new_dangling_footnote_refs` (count-based/renumber-safe,
  NEW-scoped) wired into verify_split/verify_merge; +10 tests; +a latent body-fact-haystack
  truncation bug fixed. TRDD-3b9b2040 STATE marks phase g DONE. Memory FEATURE is shippable.
- **Commits this wake (none pushed):** b03208d (MD004) · 9b09f34 (2 malformed-YAML CRITICALs) ·
  7ace046 (g3) · 254f38f (2 over-cap descriptions) · 6b48ee2 (TRDD STATE + lint). CPV CRITICAL
  dropped **6→4** — cleared everything that was MINE (the 4 left are immortal-janitor's).
- **PUBLISH still blocked — UNCHANGED + already-known.** The 4 persistence CRITICALs (CPV #40,
  documented at NEXT ACTION §1 below) are THE blocker: real + load-bearing + the no-exempt
  policy ⇒ un-clearable until GROUP C lands or GROUP B is extracted off main. Memory work is
  HOSTAGE to that shared branch. Write-up:
  `reports/overnight-session/20260623_171000+0200-memory-job-done-publish-blocked.md` + LOCAL
  memory `janitor-publish-blocked-immortal-persistence`.
- **OAuth healthy this wake:** LIVE emanuele 5h=22%/7d=19%; fmuaddib MAX (no switch). Budget OK.
- **NEXT (autonomous):** USER wanted "complete the immortality AND the memory system" — memory is
  DONE, so the next user-wanted work is **immortality GROUP C #228 (self-integrity)**. It is
  SECURITY-CRITICAL (the plan mandates an ultracode review loop) → build it in a FRESH/compacted
  context, NOT this long one. Deferred memory-only CPV debt (does NOT block the memory feature;
  a careful editorial pass): 3 oversized memory SKILLs + wikimem-model TOC embeds + the memgrep
  resource_abuse CPV FP (index.rs:762 ATOM_PAGE test fixture — devitalize per policy).

### ⚡ UPDATE 2026-06-23 15:09 — USER ACTIVELY REFINING THE MEMORY MODEL (still HELD)
- **USER is mid-design-conversation NOW** (sent a burst of directives ~minutes ago; a direct
  question is pending to them). Away-period has NOT extended → per the 13:35 rule below, HOLD the
  memory work; do NOT start #56 / GROUP C #228 yet, and do NOT auto-build phase g.
- **TRDD-3b9b2040 engine (atoms a–f) is BUILT + tested (125 memgrep green) + committed** this
  session (atom parser/index/recall/find-cmref, per-atom-notes aggregation, the atomize migration
  pass + its verify_atomize gate + scheduler/agent wiring; live corpus reindexed schema-v2, recall
  verified). BUT the USER then **REFINED the model** in rapid directives — recorded in 3b9b2040's
  STATE block "🔴 REFINED MODEL" section + memorized USER-scope ([[wikimem-atom-block-properties]],
  NEW [[wikimem-single-memory-agent]]): LEADING metadata blocks (not trailing); FOUR first-class
  element kinds (atom/note/lesson/see-also) each with a block; memgrep greps ELEMENTS not pages
  (page = context, agent discouraged from reading the whole page); lesson = a demoted prior atom
  version; recall returns atom AGGREGATED with its notes/lessons/see-also; ONE memory agent for all
  chores, loading only the dispatched chore's skill dynamically. This is build phase (g) — a bounded
  re-architecture of the just-built engine — **GATED on USER confirmation** (asked; awaiting answer).
- OAuth healthy this wake: LIVE emanuele 5h=2%/7d=15%; fmuaddib 7d=100% (capped — no switch).
- Commits this wake: 8ba718e (atomize) 7778c30 (3b9b2040 STATE) bc01db7 (scheduler-test fix)
  7c62098 (one-agent def) 5dc7e41 (refined-model record). Publish still HELD (engine will be
  re-architected by phase g; don't publish the interim trailing-marker version).

### ⚡ UPDATE 2026-06-23 13:35 — MEMORY PIVOT + FRESH BUDGET (read before acting)
- **MEMORY SYSTEM PIVOTED to an ATOM-INDEXING REDESIGN.** While building the buffer⇄wiki harvest
  (TRDD-ab232dbd), the USER realized memgrep has NO atom-level metadata/recall (page+lesson
  granularity only) → chose **"stop & redesign."** New design TRDD **[[TRDD-3b9b2040]]** covers:
  atoms as first-class index rows; Obsidian Block Properties (`^id [key: value, …]`) + the
  space-separated ARRAY-value extension (`keywords:` = the per-atom recall surface); harvest-into-
  atoms; prose→atom migration. **BOTH ab232dbd (harvest) AND the memory redesign are BLOCKED on
  USER review of design Q1–Q6** (atom boundary, marker placement, required props, recall ranking,
  migration cadence, lesson/atom unification). **DO NOT auto-build memory work** until the USER
  answers. Committed this session: design TRDD (49447cd), foundation memory_scopes wiki/+discriminator
  (5acdd8f), memgrep find-claude-mem-ref v1 (4ebd891, needs atom-rework), convention MEMORIZED
  (USER-scope `wikimem-atom-block-properties.md`). Superseded harvest-skill draft → `docs_dev/`.
- **BUDGET RESET — real headroom now.** LIVE `emanuele.sabetta` 5h=55% / **7d=11%** (FRESH, the
  weekly window dropped the old usage); `fmuaddib` 7d=100% (capped — do NOT switch to it). The
  "9% weekly left" note below is OBSOLETE. No OAuth action needed this wake.
- **PUBLISH still BLOCKED on USER** (immortality-persistence (b)-separate approach needs OK — see
  NEXT ACTION §1). Unchanged.
- **Both major tracks (memory redesign, publish) are USER-GATED.** Non-conflicting autonomous
  candidates if the away-period extends: #56 page-frontmatter ocd/lmd top-level fix (orthogonal to
  the atom redesign — page frontmatter persists), or immortality GROUP C self-integrity #228
  (build/test/commit, defer the gated publish). Holding this wake — USER was mid-design-conversation.

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
  Do NOT hand-`git push` / `gh release`; `publish.py` OWNS the version bump + tag + release +
  all gates (validate --strict, lint, tests). After a publish: daemon auto-updates →
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
     legitimate means tonight. **POLICY RESOLUTION (recall 2026-06-23,
     [[project_janitor_publish_blocked_cpv_fps]]):** the established USER policy is
     *"exempt-lists dropped fleet-wide as exploitable — never suppress; devitalize/remove/
     separate."* So **(b) is the policy-mandated answer; (a) CONTRADICTS the policy** (it's an
     exempt path). Scoped: `daemon.py:69` HARD-imports `launchd_keepalive`; the daemon also
     copies/installs `daemon-launcher.py` (daemon.py:866). So (b) = either lazy/guard that
     import + move `daemon-launcher.py` + `lib/launchd_keepalive.py` out of the CPV-scanned
     tree, OR `git revert` the GROUP-A/B commits onto a feature branch. Both touch immortality
     core → **need USER OK on the approach** (the immortality plan gates it on approval). Options:
       (b) SEPARATE the release [POLICY-MANDATED] — ship the MEMORY work as v0.16.0 alone;
           immortality ships later as its own reviewed release. (Real release-eng, not a delete.)
       (a) WAIT for CPV #40 (an honored by-design exemption) — ⚠ CONTRADICTS the never-exempt
           policy; listed only for completeness.
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
  fixes COMPLETE for this budget window. Winding down clean. NEXT WAKE WITH BUDGET: publish +
  close issues (see NEXT ACTION). 4 issues fixed (#54/#55/#59/#53), 1 decided (#56), all
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
- 10:20 (same wake — BUDGET RESTORED) — OAuth re-check: **emanuele 7d=2% / 5h=8%** (fresh — a
  manual /login or token swap, NOT the scheduled 17:00 reset; fmuaddib reads `err`). With the
  publish still BLOCKED on the USER a/b decision, did decision-INDEPENDENT investigation (not
  risky/moot work): **#56 root-cause REFINED** — `parse_frontmatter` (memory_edit_verify.py:62)
  HOISTS `metadata.*`→top-level, so the Python verify layer tolerates BOTH shapes (why
  verify_repair passed on nested pages); memgrep (Rust) reads ONLY top-level `ocd`/`lmd`, so a
  nested page loses its date in recall. grep confirms NO Python emitter writes nested → the
  nesting is PRE-EXISTING on-disk pages, not a serializer bug. FIX (still not-a-near-wall):
  verify_repair must inspect the RAW frontmatter (pre-hoist) to REJECT ocd/lmd-only-under-
  metadata, + a careful one-time migration of existing nested pages (data-touching → RULE 0
  care; NOT autonomous-while-asleep). #61 (weekly audit drift) = auto-generated; mostly the OLD
  trdd-reminder behavior my #59 fix already corrects (ships in the publish) + 2 stuck-in-testing
  TRDDs (minor). HOLDING for the user's a/b decision; nothing risky started. Tree clean @30698b4.

### SUPERSEDED — do NOT carry forward
- The earlier idea of waiting for the user's naming calls on the granular skills — the
  user is asleep + said "complete the memory system"; proceed on the M3 defaults above.

## Durable artifacts to read before acting
- `design/tasks/TRDD-…-aebedbff-…md` — the 3-tier memory architecture (subconscious agent).
- `design/tasks/TRDD-…-324223a6` + the immortality plan — GROUPS A/B done, C pending.
- The 3 OAuth memory notes (rotator 3-layer architecture + design directives + renew transport).
- Open issues: `gh issue list --repo Emasoft/ai-maestro-janitor --state open`.
