---
trdd-id: MF10XF87
title: The janitor-reload marker fires on __pycache__ churn and never clears after a manual reload
column: backburner
created: 2026-08-26T05:58:43+0200
updated: 2026-08-26T16:55:00+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: minor
min-approval-requirement: none
labels: [heartbeat, markers, plugin-cache, noise]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# `[janitor-reload]` fires when nothing reloadable changed

## What was observed (reported by the CORE session, 2026-08-25/26)

- **8 `[janitor-reload]` fires** where the only files newer than the stored ack
  were `__pycache__/*.pyc` — compiled bytecode, which no reload consumes. The
  marker is emitted, the session runs `/reload-plugins --force`, the prompt-cache
  prefix is destroyed and the whole window is re-billed (see TRDD-VHPYSN56 for why
  that cost is not academic), and nothing was actually reloaded.
- **A MANUAL `/reload-plugins` advances no ack.** The slash command fires no hook,
  so the detector's "you have reloaded, stand down" signal is never written. A
  session the user reloaded by hand therefore keeps receiving the marker forever.

## ⛔ 2026-08-26 16:45 — MY "REPRODUCTION" BELOW IS FALSE. The probe was broken, not the detector.

**`find -newermt '-24 hours'` does not mean what this card assumed.** On BSD/macOS find that
relative form does not parse as "24 hours ago" — it silently yields a near-empty result instead
of an error. Every "0 files changed" in the section below came from it.

The same directory, measured three ways at 16:40 today:

```
find . -type f -newermt '-24 hours'        →     10      ← the broken probe
find . -type f -newermt '2026-08-25 17:00' →  6,475
os.walk + st_mtime > time.time()-86400     →  6,490      ← ground truth
newest file mtime                          →  2026-08-26 16:38:31
```

**So the plugin cache HAD changed — 6,490 files in 24 h — and the `[janitor-reload]` markers
were LEGITIMATE.** I declined three of them today (this card's 06:14 fire, and two more at
~16:30 and ~16:38) on the strength of a probe that cannot report the positive case. The
detector was doing its job throughout.

**This is the exact failure class I catalogued in USER memory the same afternoon** —
`ATOM-XNZ8-BEBF` / `ATOM-W99A-N60G`, *"a check that cannot produce the negative result has not
been run"* — with the sign flipped: a check that could not produce the POSITIVE. Writing the
lesson four hours earlier did not stop me running the broken probe twice more, which is worth
recording plainly: a lesson in the corpus is not a guard in the path.

**What survives of this card, and it is not nothing:**

- The SECOND observation is untouched and still real: a MANUAL `/reload-plugins` fires no hook,
  so it advances no ack, so a hand-reloaded session keeps receiving the marker. That half was
  never measured with the broken probe.
- The CORE session's original report (8 fires whose only newer files were `__pycache__/*.pyc`)
  is THEIRS, measured independently, and this correction does not touch it. Bytecode churn
  advancing a reload generation is still a plausible defect worth keying off the version set.

**What is retracted:** the "worse than reported" escalation, the claim that a current ack fails
to suppress, and the inference that the detector keys on something other than the cache. All
three rested on the broken probe.

**Column stays `backburner` and severity stays `minor`** — but for a different reason than
before: the remaining defect is the no-ack-on-manual-reload half, not a phantom never-suppressing
detector.

## ⏵ 2026-08-26 16:55 — SEPARATE DEFECT, verified: a DECLINED marker still advances the ack

Independent of the broken probe above, and it is the reason today's staleness became silent.

`dispatch.py::_phase_plugin_reload` writes the ack and THEN emits:

```python
state.atomic_write(acked_path, str(gen))
_emit_decision("[janitor-reload]")
```

So the ack records **that the marker was SENT**, never that a reload HAPPENED. A session that
declines the marker — for a good reason or a bad one — silently converts "needs reload" into
"reloaded". Measured on this project at 16:55, after three declines:

```
server generation : 1787754771  (16:32:51)
project ack       : 1787754926  (16:35:26)
ack >= gen        : True  → marker permanently SUPPRESSED
```

The plugin cache had changed (6,490 files in 24 h, newest 16:38:31), this session did not
reload, and the janitor now believes it did. **Nothing will re-raise it**, so the staleness is
now invisible to every surface — which is strictly worse than the noisy over-firing this card
was originally about.

This is the same shape as TRDD-A8DPTDOU's false CLEARED and TRDD-FB84YUGT's expired-correct
decline: a state transition recorded on the ATTEMPT rather than on the OUTCOME. The fix has the
same shape too — advance the ack on evidence that a reload occurred, not on the decision to ask
for one. Note the constraint that makes it hard, already recorded above: a `/reload-plugins`
fires no hook, so "a reload occurred" has no direct signal. A version-set comparison after the
fact is the obvious candidate and is the same key this card already proposes.

Not fixed here — the marker's ack semantics are load-bearing for every project on the machine,
and the CORE session's report plus this one should be reconciled before changing them.

## ~~Reproduced first-hand, 2026-08-26 06:14 — and it is WORSE than reported~~ ⛔ RETRACTED — broken probe

The CORE session's report was "8 fires with only `__pycache__` churn newer than the ack".
Measured on this machine at the moment of a live fire, there was not even that:

```
find ~/.claude/plugins/cache -type f -newermt '-24 hours' | wc -l   → 0
.janitor/state/reload-acked.ts                                      → 1787717450 (06:10:50)
[janitor-reload] emitted at                                          → 06:14
```

**Zero plugin-cache files changed in 24 hours, the ack was 3.7 minutes old, and the marker
fired anyway.** So the bytecode-churn story is at most a contributing cause and cannot be the
whole one — a mtime-vs-ack comparison with nothing newer than the ack should suppress, and it
did not. Whatever the detector keys on, it is not "something under the plugin cache is newer
than the ack".

That widens the fix rather than changing it: keying on the cached VERSION SET is still right,
but the change must also explain why the CURRENT ack is not suppressing, or the same
never-suppressing bug will simply reappear behind a new key.

The fire was NOT actioned. A reload destroys the prompt-cache prefix and re-bills the whole
window (TRDD-VHPYSN56) — paying that for a provable no-op is the cost this card exists to
stop, and the project CLAUDE.md already directs sessions away from `/reload-plugins`.

## Root cause (hypothesis — NOT yet traced in code)

Change detection is keyed on **file mtimes under the plugin cache**, so any write
into that tree — including a Python interpreter writing `.pyc` files as a side
effect of merely *importing* janitor code — looks like "a plugin changed".

## The fix

Key the detector on the **cached VERSION SET** (the set of
`<plugin>@<marketplace> -> version` currently resolved) rather than on file
mtimes. A reload is warranted exactly when that set differs from the set the
session last loaded; bytecode churn cannot change it, and a manual reload
converges because the loaded set catches up on its own.

Derived consequence to handle in the same change: with a version-set key, the
"ack" stops being a timestamp and becomes the set itself, so the manual-reload
gap closes without needing a hook on the slash command.

## Relates to

- janitor#101 (same detector family)
- TRDD-VHPYSN56 — why a needless `/reload-plugins` is expensive, not merely noisy

## Notes

Carried out of the 2026-08-26 session handoff, where it was listed as an
uncarded defect. Reported second-hand by the CORE session; the 8-fire count and
the `__pycache__`-only delta are **their** measurement, not one I reproduced —
reproduce before fixing.
