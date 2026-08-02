---
trdd-id: AWXK0RFT
title: Publish is blocked by a CRITICAL false positive on cfg(test) Rust in memgrep
column: todo
created: 2026-08-02T17:24:47+0200
updated: 2026-08-02T17:41:00+0200
current-owner: claude-ai-maestro-janitor
task-type: infra
scope: project
severity: high
blocked-by: []
relevant-rules: []
implementation-commits: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body)

**Not started — AWAITING A USER DECISION. The owner asked for a release ("push via a
release", 2026-08-02) and `publish.py` REFUSES. The blocker is a false positive, and I
declined to clear it unilaterally.**

### ⚠️ IMPACT IS NOT "79 UNPUSHED COMMITS" — EVERY FIX SHIPPED TODAY IS INERT

Skills invoke their backing scripts by ABSOLUTE path into the **plugin CACHE**
(`~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/<ver>/scripts/…`), i.e. the
PUBLISHED version — never the working tree. So until a release lands, the repo fixes do not
exist as far as any `/janitor-*` skill is concerned. Measured 2026-08-02 (grep counts,
cached v2.3.0 vs repo):

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
