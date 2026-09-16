---
trdd-id: AWXK0RFT
title: Publish is blocked by a CRITICAL false positive on cfg(test) Rust in memgrep
column: complete
pre-block-column: todo
blocked-by-external: [Emasoft/claude-plugins-validation#189]
created: 2026-08-02T17:24:47+0200
updated: 2026-08-05T18:26:46+0200
current-owner: claude-ai-maestro-janitor
task-type: infra
scope: project
severity: high
blocked-by: []
relevant-rules: []
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

### 2026-08-05 evening — RESOLVED exactly as the owner said it would be. CLOSING.

"wait for CPV to fix. its almost done." — it was. CPV v5.1.4 shipped the #189 fix; verified
first-hand (the cfg(test) gate that never terminated on v5.1.2 completed in 50.9 s), pinned
across the three SSOT sites (ff3118fc), and the publish then succeeded TWICE the same day:
v2.4.0 and v2.4.1 are Latest on GitHub. The wait resolved the block with neither forbidden
shortcut touched. Nothing remains in this card's scope.

### The parked entry (kept; superseded above)

### 2026-08-05 — USER DECISION: WAIT for CPV. Parked, not abandoned.

Owner, verbatim: **"wait for CPV to fix. its almost done."** So this card is parked pending an
external event, and nothing here is to be forced in the meantime. The two forbidden shortcuts in
the N block below remain forbidden while we wait — a wait is not a licence to relax the gate.

**On the column, stated plainly because it bends a rule.** `column: blocked` with
`blocked-by: []` — the kanban rule says `blocked` applies when `blocked-by:` is non-empty, but
that field takes TRDD ids and the blocker here is another project's issue, which has no card on
this board. The alternative was leaving it in `todo`, which asserts "ready to pull" about work
that provably cannot start — an untrue column is worse than an unstarted card. So the external
blocker is recorded in a `blocked-by-external:` field instead, greppable and honest.
**This is an open-schema extension, not an established field** — if the schema should name
external blockers properly, that is a rule question for the USER, not something to settle here.
Restore to `pre-block-column: todo` when CPV ships.

### 2026-08-05 — the blocker MOVED: it is now a HANG, not a finding

Attempted the release (`publish.py --patch --dry-run`). Everything the janitor owns is green:
**ruff + mypy clean, 14349 tests passed / 1 skipped in 498s.** It dies in ONE place:

```
[cpv-phase] validate_manifest / validate_structure / check_tracked_gitignored_files
[cpv-phase] validate_layout_c_consistency        all DONE 0.0s
[cpv-phase] skillaudit_native                    DONE 66.0s
[cpv-phase] security_execclass_gate              Command timed out after 900s
```

So the gate no longer REPORTS the cfg(test) false positive this card was named for — it never
gets that far. `_CPV_PIN` is `v5.1.0`, and **v5.1.1 (published 2026-08-04) does not fix it**:
its changelog carries one entry, a CI-canon fix. Bisection stands: **v4.2.0 143.6s ✓,
v4.3.0 49.9s ✓, v5.0.0 / v5.1.0 / v5.1.1 never complete.** Reproduction + per-phase timing
posted to Emasoft/claude-plugins-validation#189.

**BOTH doors are shut, which is why this still needs the USER:**
- **Forward (v5.1.x)** — the gate hangs. Nothing to fix on our side; upstream bug.
- **Backward (v4.3.0)** — the gate completes, but leaves 1 MINOR + 4 NITs, and under
  `--strict` MINOR(3) and NIT(4) both BLOCK (`publish.py:1323`). They are CPV false positives.

**N — the two things NOT to do**, both of which would "work":
1. Suppress the findings or relax `--strict`. **PRRD S5.1** forbids it: a CPV finding is
   cleared by devitalizing or REMOVING the offending code, never by exempting a rule.
2. Rewrite `write_gate.rs`'s concurrency test so the scanner stops reading it as SHELL_EXEC.
   That is load-bearing test code; devitalizing it to dodge a scanner FP breaks the thing the
   test exists to prove. Refusing to devitalize load-bearing code is the same principle CPV's
   own devitalizer applies.

**What unblocks this:** CPV ships the pool fix, or a `v4.3.1` backport onto the last version
whose gate terminates. Asked for exactly that on #189. Alternatively the USER may direct a
different course — that decision is theirs, not mine.

### ⚠️ THE COST IS NOW MEASURED — 193+ commits, not 79

HEAD is **193+ commits** ahead of the `v2.3.0` tag. Verified 2026-08-05 that NO cached version
(all 19, `0.41.0` → `2.3.0`) contains `peer-freeze-recovery.py` or `global-chore-blackout.py`,
so both ship in nothing and have never executed. This card therefore also gates TRDD-KQ9WM4TZ,
which is now `column: blocked, blocked-by: [AWXK0RFT]` for exactly this reason.

---

**SUPERSEDED — do NOT carry forward:** *"Not started — AWAITING A USER DECISION … The blocker
is a false positive"*. The awaiting-a-decision part is still true; the BLOCKER is not — since
CPV v5.0.0 the gate hangs before it can emit any finding at all. Original text below.

### ⚠️ IMPACT IS NOT "79 UNPUSHED COMMITS" — EVERY FIX SHIPPED TODAY IS INERT

Skills invoke their backing scripts via **`${CLAUDE_PLUGIN_ROOT}`**, which resolves at load
time to `~/.claude/plugins/cache/…/<ver>/` — the PUBLISHED version, never the working tree.
So until a release lands, the repo fixes do not exist as far as any `/janitor-*` skill is
concerned.

*(Corrected 2026-08-02: I first wrote that SKILL.md "hard-codes an absolute versioned path".
It does not — the source uses the variable, and it auto-rolls correctly; I had read the
RESOLVED text the harness substitutes and mistaken it for the source. The CONCLUSION below
is unaffected — the variable still points at the published cache — but the mechanism was
wrong, and a false claim about how skills resolve paths would send the next reader hunting a
bug that isn't there.)*

Measured 2026-08-02 (grep counts, cached v2.3.0 vs repo):

| symbol | cached v2.3.0 (what the skill RUNS) | repo (fixed) |
|---|---|---|
| `_run_chain_payload` / `CLEAR_CHAIN_SPAWNED` (chained injector) | **0** | 3 |
| `_user_present()` presence CANCEL | **PRESENT** (`:320`, `USER_PRESENT` at `:385`) | removed |
| `_iterm_session_script` (the AppleScript fix) | **0** | 4 |

**Consequence, observed live:** invoking `/janitor-handoff-and-clear` while the owner is at
the keyboard still prints `USER_PRESENT` and does nothing — the very complaint that started
this work ("*why the hell the agents are refusing to execute /janitor-handoff-and-clear when
i gave the command myself???*"). The fix exists and is committed; the skill cannot reach it.

Running `uv run --script scripts/clear_trigger.py` from the repo DOES use the fixed code —
that is the only current workaround, and it bypasses the skill entirely.

**So this card gates: TRDD-0BVF4K7E's fix reaching users, the injector's iTerm fix, the
memory oracle/parser deadlock fix, and 77 commits.** It is the critical path, not a
housekeeping item.

### The blocker, verbatim

```
SUMMARY: CRITICAL=1 MAJOR=0 MINOR=0 NIT=4 WARNING=38
[CRITICAL] [skillaudit:agent_manipulation AGENT_MEMORY_MOD]
  Agent memory/config modification (scripts/memgrep/src/memory.rs):6431
```

`publish.py --dry-run` exits 1 at the CPV validate gate. Nothing downstream runs.

### Why it is a FALSE POSITIVE (verified first-hand, not inferred)

- `#[cfg(test)]` begins at `memory.rs:5394`; the nearest `#[test]` above the finding is
  `:6424`. **Line 6431 is 7 lines inside a test function** — `cfg(test)` code is compiled
  only for `cargo test` and is **never in the shipped binary**.
- The flagged statement is `std::fs::write(dir.join("MEMORY.md"), …)` where `dir` is a
  **tmpdir** — creating a FIXTURE for
  `lint_of_only_non_pages_does_not_fall_back_to_linting_the_cwd`. The test needs the name
  `MEMORY.md` specifically, because the code under test must SKIP non-page files and
  `MEMORY.md` is the canonical non-page.
- It is **not new**: it arrived with `77a193c`, which `git branch -r --contains` shows on no
  remote branch. So it has been blocking this release the entire time the 79 commits
  accumulated — the backlog is a SYMPTOM of this, not a coincidence.

### Why I did not just fix it

`scripts_dev/cpv_cands_memmod*.json` (5 files, 2026-06-11) show this exact rule
(`AGENT_MEMORY_MOD`) was probed before against `memory-librarian.py`, hypothesis by
hypothesis (`h1_no_append_same_line`, `h3_control_append_inline`, …) — i.e. the previous
resolution was **rephrasing code until the regex stopped matching**.

Doing that here means rewriting a test so a scanner stops seeing it, when the test
deliberately names `MEMORY.md` because that is what it must prove gets skipped. That
weakens a real test to satisfy a tool, and **suppressing a CRITICAL to force a release is
the one thing not to do unasked**. Hence this card instead.

### The three options put to the owner (2026-08-02) — awaiting the choice

1. **File upstream on CPV** — the `AGENT_MEMORY_MOD` rule should not match inside
   `#[cfg(test)]` Rust. Correct per `~/.claude/rules/how-to-fix-issues-of-other-projects.md`
   (CPV is a DIFFERENT project: file an issue, or fork→/tmp→PR; never edit its tree).
   Holds the release until upstream moves.
2. **Dispatch `cpv-plugin-devitalizer-agent`** — CPV's own output recommends it, and its
   documented contract FLAGS load-bearing code rather than breaking it. Using the vendor's
   sanctioned tool is not gaming the scanner.
3. **Override** — proceed and state plainly in the release notes that a CRITICAL was
   accepted as a false positive, with this card as the justification.

**NEXT ACTION:** get the owner's choice, then execute it. Do NOT re-derive the analysis —
it is above and was verified against the file.

### Also on the publish run, NOT blocking

`Cache audit: 3 WARNING(s) (CA-01..CA-07, non-blocking)` and `NIT=4 WARNING=38`. Untriaged;
none gate the release.

## Provenance

Found running `publish.py --dry-run` after the owner chose "push via a release" over a bare
push. The dry-run is why this surfaced safely — a bare `git push` would have succeeded and
left the gate un-run.
