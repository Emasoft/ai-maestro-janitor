---
trdd-id: LQU7OXXV
title: /janitor-compact-context --soft and --handoff flags + /janitor-write-handoff skill
column: todo
created: 2026-07-01T03:25:25+0200
updated: 2026-07-01T03:25:25+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: MEDIUM
effort: M
task-type: feature
parent-trdd: null
relevant-rules: []
release-via: publish
delivery: direct-push
target-branch: main
test-requirements: [unit]
impacts: []
attempts: 0
implementation-commits: []
---

# /janitor-compact-context --soft and --handoff flags + /janitor-write-handoff skill

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-01

- **USER SPEC (verbatim intent):** add two flags to `/janitor-compact-context`:
  - **`--soft`** — the janitor WAITS for the agent to finish its turn before compacting. It does
    NOT press ESC immediately; instead it ENQUEUES the `/compact` command (just TYPES it and presses
    Enter). Because there is no ESC, the agent finishes its current turn and the queued `/compact`
    runs when the turn ends.
  - **`--handoff`** — the janitor FIRST runs a NEW skill `/janitor-write-handoff`; WHEN THAT
    COMPLETES it runs `/compact`. (Default/hard mode.)
  - **`--handoff --soft` COMBINED** — the two commands (`/janitor-write-handoff` then `/compact`)
    are just TYPED and ENQUEUED one after another, WITHOUT pressing ESC, so the agent does not
    interrupt its turn but processes the queued commands after the turn ends (handoff first, then
    compact). [User wrote "/janitor-compact-context and /compact" — read as /janitor-write-handoff
    then /compact, the two enqueued commands.]
- **CURRENT BEHAVIOR (baseline to extend):** `scripts/compact_trigger.py` records a resume
  directive then fires a DETACHED keystroke sender (iTerm osascript by `$ITERM_SESSION_ID` UUID /
  tmux `send-keys` by `$TMUX_PANE`) that sends **ESC then `/compact`** to THIS pane after ~2 s
  (the ESC interrupts the in-flight turn → immediate compaction). The `--directive` arg + the
  PostCompact `post-compact-resume.py` hook already handle auto-resume. Read
  `scripts/compact_trigger.py` + `scripts/lib/terminal_trigger.py` (the ESC→settle→command send
  sequence, `build_tmux_steps`, `send_self_command`) FIRST — that is the seam to modify.
- **DESIGN — the three modes as keystroke sequences:**
  - default (hard, unchanged): `ESC → /compact⏎`
  - `--soft`: `/compact⏎` (NO ESC → enqueues; runs at turn end)
  - `--handoff` (hard): `ESC → /janitor-write-handoff⏎`, then the HANDOFF SKILL itself chains to
    `/compact` on completion (see "sequencing" below) — do NOT make the detached sender "wait", it
    cannot observe skill completion.
  - `--handoff --soft`: `/janitor-write-handoff⏎` then `/compact⏎` typed back-to-back, NO ESC (both
    enqueue; the input queue runs handoff first, then compact — no chaining needed).
- **SEQUENCING (the load-bearing subtlety):** a detached keystroke sender CANNOT know when
  `/janitor-write-handoff` finished. So in HARD `--handoff` the ordering is delegated to the
  handoff skill: `compact_trigger --handoff` types `/janitor-write-handoff`; the skill writes the
  handoff and, as its FINAL step, itself fires `/compact` (e.g. re-invokes `compact_trigger` in
  soft mode to enqueue `/compact`). In SOFT `--handoff --soft` no chaining is needed — both are
  enqueued and the queue serialises them. Pick ONE consistent mechanism and document it.
- **NEW skill `/janitor-write-handoff`:** the agent writes a RICH, SEMANTIC handoff (what it was
  doing, the plan, in-flight TRDDs, next concrete action, load-bearing facts) to a durable path
  before compaction — complementing the MECHANICAL `scripts/hooks/pre-compact-handoff.py` PreCompact
  hook (which already auto-writes a filesystem-grounded handoff: git status, TRDD board). Decide the
  output path (reuse the pre-compact handoff location, or a sibling) so `post-compact-resume.py` /
  the next turn reads it. The skill ends by triggering `/compact` ONLY when invoked via `--handoff`
  (pass a flag/arg so a bare `/janitor-write-handoff` just writes the handoff and stops).
- **IMPLEMENTATION TOUCHPOINTS:**
  1. `scripts/compact_trigger.py` — argparse `--soft` (skip ESC) + `--handoff` (prepend the
     handoff command / chain). Thread the mode into the keystroke builder.
  2. `scripts/lib/terminal_trigger.py` — allow a NO-ESC send + a two-command send (already sends
     ESC+cmd; parameterise `esc_first` — note `iterm_osascript` in `fleet_inject.py` already has an
     `esc_first` param to mirror).
  3. `skills/janitor-compact-context/SKILL.md` — document `--soft` / `--handoff` / combined + when
     the agent should choose each (soft = don't lose the current turn's work; handoff = write a rich
     handoff first).
  4. `skills/janitor-write-handoff/SKILL.md` (NEW) + optional `scripts/write_handoff.py` backing.
  5. Tests: `tests/test_compact_trigger*.py` — `--soft` omits ESC from the sent sequence;
     `--handoff` sends `/janitor-write-handoff`; combined sends both, no ESC; the resume directive
     is still recorded. Real (no mocks) — assert the built keystroke steps, mirror
     `test_terminal_trigger` if present.
  6. Docs: CLAUDE.md (hooks/skills map), README.
- **NEXT ACTION:** read `compact_trigger.py` + `terminal_trigger.py`; implement 1-2 (soft/no-ESC
  first, simplest), then 3-4 (handoff skill + chaining), then tests + docs. ruff + pyright + tests.
  Commit; publish via publish.py (USER already wants publishes for this plugin — confirm at ship).

## Why

Hard compaction (ESC now) discards the CURRENT turn's in-flight work — bad when the agent is
mid-task. `--soft` lets a compaction wait for a safe boundary (turn end). `--handoff` guarantees a
rich, agent-authored state handoff is written BEFORE the context is compacted, so the resume is
high-fidelity, not just the mechanical PreCompact snapshot.

## Acceptance

- `/janitor-compact-context --soft` → the sent keystrokes contain NO ESC; `/compact` is typed +
  Enter; the resume directive is still recorded.
- `/janitor-compact-context --handoff` → runs `/janitor-write-handoff` first, then `/compact`
  (ordering guaranteed by the chosen sequencing mechanism).
- `--handoff --soft` → `/janitor-write-handoff` then `/compact` enqueued back-to-back, NO ESC.
- `/janitor-write-handoff` (bare) writes a handoff and does NOT trigger `/compact`.
- Real tests assert the built keystroke sequences; ruff + pyright clean.

## Notes and lessons learned
