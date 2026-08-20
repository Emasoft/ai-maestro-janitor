---
trdd-id: OZNG3N2D
title: Injection gate corroborator — consume the hub's aimaestro-session activity verb as a second presence signal
column: backburner
created: 2026-08-20T16:09:19+0200
updated: 2026-08-20T16:09:19+0200
current-owner: janitor-main-session
task-type: feature
priority: normal
approval-tier: 0
scope: project
external-refs: [TRDD-D2DD5GO8]
npt: []
eht: []
---

# Consume `aimaestro-session.sh activity <tmux-session>` as an injection-gate corroborator

## Why

TRDD-D2DD5GO8 made the darwin-blinded HID probe defer (None ⇒ never inject). That is
safe but blunt: on hosts where the HID answer is unavailable, every injection defers
forever. The hub now ships `aimaestro-session.sh activity <tmux-session>`, which reports
`in_turn`, `last_user_input_epoch` (server-side presence), and a transcript epoch. When
the hub backend is present, that is an independent second signal the gate can consult
BEFORE giving up.

## Contract facts (from the hub's landing message, 2026-08-20 ~09:15)

- `in_turn` NULL means UNKNOWN — NEVER treat NULL as safe-to-inject.
- `last_user_input_epoch` is server-observed user presence.
- The transcript epoch is ONE sample; call twice, spaced, to establish "advancing".

## What

1. A small helper in `scripts/lib/user_intent.py` (or a sibling) that shells out to the
   hub verb when the harness backend is active, mapping its JSON to the same tri-state
   as `typing_now()`: recent `last_user_input_epoch` ⇒ True (user present, defer);
   `in_turn` false + stale input epoch ⇒ False; NULL/absent/backend-missing ⇒ None.
2. The injection probes consult it only when the HID verdict is None; None+None still
   defers (the D2DD5GO8 invariant is unchanged — this narrows the blind case, never
   widens the inject case).
3. Tests: NULL⇒None pin; backend-absent⇒None; the two-sample advancement rule if the
   transcript epoch is used at all.

## Acceptance

- [ ] Blind HID + hub says user-present ⇒ defer (as today)
- [ ] Blind HID + hub affirmatively idle ⇒ inject permitted
- [ ] `in_turn` NULL or backend absent ⇒ behaves exactly as today (defer)
- [ ] pytest, ruff, mypy, pyright clean

## Approval log
