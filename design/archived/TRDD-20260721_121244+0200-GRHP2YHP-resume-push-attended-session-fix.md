---
trdd-id: GRHP2YHP
title: resume-push must not surprise an attended-but-reading session after compaction
column: complete
created: 2026-07-21T12:12:44+0200
updated: 2026-07-21T14:25:00+0200
current-owner: claude-ai-maestro-janitor
task-type: bugfix
scope: project
related-trdd: [HI0BGQGJ, 6Q0OYYYH]
implementation-commits: [b041ffd]
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-21

**INCIDENT (owner, 2026-07-21):** after a compaction the janitor typed `/janitor-resume` into the
owner's pane; they were PRESENT (reading a long reply) and had to delete the enqueued command with
arrow-up. "You are already resumed from the handoff, why resume again?"

**SHIPPED (b041ffd, 2026-07-21):** decoupled — the HID 20 s grace stays as the "don't type under
fingers" floor; a NEW attended-SESSION window `_push_prompt_window_s` (default 5 min, knob
`CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_PROMPT_WINDOW_S`) reads the genuine-prompt breadcrumb.
29 tests green (incl. the reproduced incident: last prompt 120 s ago → NO push; and its
falsification: window collapsed to 20 s → would have fired), ruff clean.
**NEXT ACTION:** none for code — awaiting end-of-run full-suite confirmation, then → `complete`.
CAVEAT: a plugin-hook change needs a session restart to take effect.

**ROOT CAUSE:** `_maybe_push_resume` (post-compact-resume.py:310) fires `/janitor-resume` via
`resume_trigger.py` unless `_user_recently_active` (:273) is true. That gate uses a 20 s window
(`_PUSH_GRACE_DEFAULT_S`, :258) — deliberately shrunk to match the HID "don't-type-under-fingers"
injection gate (TRDD-6Q0OYYYH). 20 s is CORRECT for "don't type while they key", but WRONG for "is
this session attended": a user READING a reply for >20 s with no keystroke is misclassified as away,
so the push fires. It does NOT re-arm the cron (that is `/janitor-arm`); it only fires one dispatcher
stub run — pure redundancy when the user is present and already driving.

## Approach

Separate the two questions the one 20 s window is conflating:
- **"don't type under the user's fingers"** (the injection gate) → keep the 20 s HID window.
- **"is this session attended?"** (the resume-push decision) → a LONGER interactive window on the
  genuine-user-PROMPT breadcrumb (`last_user_input_epoch`, bumped only on a real submit, never on a
  cron). Suppress the push whenever a real prompt landed within, say, a few minutes.

Net effect: an attended dev session (you talked to me minutes ago, now reading) → push suppressed; an
unattended overnight session (no genuine prompt for hours) → push STILL fires (the whole point of
TRDD-HI0BGQGJ — resume in seconds instead of the up-to-30-min demoted-cron wait). NOT a removal —
removing the push would break the unattended-overnight loop.

## Derived tasks

- New knob `CLAUDE_PLUGIN_OPTION_POSTCOMPACT_PUSH_ATTENDED_PROMPT_WINDOW_S` (default a few minutes),
  distinct from the existing `..._ATTENDED_GRACE_S` (the HID window). Keep the existing
  `..._PUSH_ENABLED=false` hard opt-out.
- The HID rung stays as an ADDITIONAL "attended" signal (any keystroke in 20 s ⇒ attended); the new
  prompt-window is the primary "attended session" signal.

## Verification

Unit test: an attended session (a genuine prompt within the window) suppresses the push; an unattended
session (no genuine prompt for hours, HID idle) still fires it. Existing `post-compact-resume` tests
stay green. `uv run pytest tests/ -k post_compact` + `ruff check` green. NOTE: a project-scoped hook
change needs a session restart to take effect (CLAUDE.md caveat) — call it out on delivery.

## Notes and lessons learned
