---
trdd-id: OZNG3N2D
title: Injection gate corroborator — consume the hub's aimaestro-session activity verb as a second presence signal
column: backburner
created: 2026-08-20T16:09:19+0200
updated: 2026-08-28T11:40:00+0200
current-owner: janitor-main-session
task-type: feature
priority: high
approval-tier: 0
scope: project
external-refs: [TRDD-D2DD5GO8, TRDD-AM8JD9SG]
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

## This also closes two orphaned audit findings (added 2026-08-20, verified)

TRDD-AM8JD9SG has carried F3 and F4 as design-needed since 2026-07-16 with nobody knowing what
would resolve them. This card is the answer to both, which raises its priority above
"nice-to-have corroborator":

- **F4 — "the self-compact presence gate is HOST-wide, not per-pane."** Confirmed at HEAD:
  `user_intent.hid_idle_seconds()` documents itself as *"machine-wide"* and reads macOS
  IOHIDSystem, i.e. the machine's input devices. No call-site care can make that per-pane, so F4
  is unfixable in place and needs a different SOURCE. The hub verb is per-session — the exact
  granularity F4 asks for.
- **F3 — "transcript freshness is conflated with human presence."** The verb reports
  `last_user_input_epoch` (server-observed human input) as a field distinct from the transcript
  epoch, and documents that the transcript epoch is one sample. The conflation is resolved at the
  source instead of being inferred downstream.

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

## ⏵ PRECONDITION — measured 2026-08-28, and it is why this card stays `backburner`

It sat in `backburner` with no stated reason, while its own text above argues for raising its
priority. That contradiction is now resolved with a measurement rather than a guess:

```
$ ~/.local/bin/aimaestro-session.sh activity dummy ; echo $?
Error: HTTP 401 — Authentication required. … strict routes need AIMAESTRO_SUDO_TOKEN (user) or AID_AUTH (agent).
1
$ env | grep -c 'AID_AUTH\|AIMAESTRO_SUDO_TOKEN'
0
```

**The verb is installed and the janitor cannot call it.** Neither credential is in a janitor
session's environment, so the corroborator would return `None` on every invocation on this host —
and `None + None` still defers, which is exactly today's behaviour. Building it now ships
machinery that never reaches its case: the same shape as F11's `instance_is_server_owned`
mitigation, which was correct, load-bearing by its docstring, and covered 0 of 20 real instances.
**Do not build the corroborator until the credential question is answered**, or it will pass
review, pass its tests, and change nothing.

One thing DID check out: the verb exits **1** on the 401, so a caller can tell failure from an
answer. That is not the CLI-exit-0 hazard F2/F8 describe. (Measured carefully — a first reading
showed `exit=0`, which was `head`'s status through a pipe, not the verb's.)

**PRECONDITION TO CLEAR BEFORE PULLING THIS:** establish how a janitor hook/daemon context is
meant to obtain `AID_AUTH` for a read-only presence query — or get an auth-free presence route.
That is ai-maestro's side; it is the same missing-credential root as janitor F6/F11 and
ai-maestro#100, so it should ride that thread rather than open a fourth one. When it is answered,
F3 and F4 on TRDD-AM8JD9SG unblock with it.

## Acceptance

- [ ] Blind HID + hub says user-present ⇒ defer (as today)
- [ ] Blind HID + hub affirmatively idle ⇒ inject permitted
- [ ] `in_turn` NULL or backend absent ⇒ behaves exactly as today (defer)
- [ ] pytest, ruff, mypy, pyright clean
- [ ] **PRECONDITION (see above):** a janitor context can actually CALL the hub verb — today it
      401s with no credential in env, so every acceptance box above would pass vacuously

## Approval log
