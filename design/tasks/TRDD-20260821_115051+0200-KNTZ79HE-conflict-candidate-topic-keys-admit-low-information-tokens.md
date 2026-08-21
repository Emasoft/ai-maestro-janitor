---
trdd-id: KNTZ79HE
title: memory-librarian conflict candidates are 3-for-3 false positives because the topic key admits low-information tokens
column: testing
created: 2026-08-21T11:50:51+0200
updated: 2026-08-21T11:59:35+0200
current-owner: janitor-main-session
task-type: bugfix
priority: normal
approval-tier: 0
scope: project
npt: []
eht: []
---

# Conflict candidates pair on words like `did` and `own`

## Why

`memory-librarian` reports `3 conflict` on every heartbeat, and has for weeks (the findings
ledger shows the same `2 aggregation + 3 conflict + 2 page-shape` triple against a link count
climbing 44 → 45 → 46 → 49). **All three were verified first-hand on 2026-08-21 and all three
are FALSE POSITIVES.** The verification is the evidence; the count is not.

| pair | topic key | verdict |
|---|---|---|
| `janitor-publish-pipeline` vs `project_janitor_publish_blocked_cpv_fps` | `blocked+cpv+gate+own` | not a conflict — already cross-linked both ways |
| `janitor-has-no-off-switch-but-disarm` vs `janitor-skills-and-agents-roster` | `did+disappear+disarm+pause` | not a conflict — both say PAUSE was retired and its flags are inert; they AGREE on every fact |
| `feedback_user_memory_in_plugin_data` vs `project_janitor_cc_changelog_currency` | `claude+did+janitor+plugin` | not a conflict — entirely different subjects (where USER memory is STORED vs whether the janitor tracks the CC changelog) |

**The topic keys name the defect.** `did` appears in two of the three keys and `own` in a
third. Those are low-information tokens: `did` is a bare auxiliary that shows up in any
description phrased as a question ("did we decide…", "why did … disappear"), which is exactly
how this corpus's `description:` fields are written by convention — they are SYMPTOM QUERIES.
So the recall style the memory system deliberately adopted is the thing feeding the false
pairs.

**Why it is worth fixing rather than ignoring.** The finding is advisory and the quiet filter
keeps it out of the conversation, so it costs nothing until someone takes it seriously — and
then it costs them a full verification pass to learn it was noise. It cost one this morning.
A detector whose every hit is false trains its reader to skip it, which is worse than silence
because the day a REAL contradiction appears it will look identical.

## What

1. Filter low-information tokens out of the conflict-candidate topic key before pairing:
   auxiliaries and bare verbs (`did`, `does`, `is`, `has`, `own`, `use`, `add`, `get`), not
   just a classic stopword list — the corpus's descriptions are question-shaped, so
   interrogative scaffolding is the main contaminant.
2. Require a higher bar than shared tokens: e.g. an overlap that survives removing the
   filtered set, or a minimum count of INFORMATION-BEARING shared terms.
3. Re-run against the current corpus and confirm the three known-false pairs no longer fire.
4. Do NOT simply raise the threshold until the count reaches zero — that would hide a real
   contradiction just as effectively. The bar must be on token QUALITY, not on count alone.

## Acceptance

- [x] the three pairs above no longer appear as conflict candidates

      Measured before/after by re-running the detector: **conflicts 3 → 0**, with aggregation
      candidates unchanged at 2 (so legitimate clusters were not collateral).
- [x] a fixture pair that genuinely CONTRADICTS (same subject, opposite claims) still fires —
      proving the fix narrowed noise rather than disabling the check

      `test_a_real_contradiction_still_fires_after_the_stopword_widening` — same subject,
      differing number, phrased throughout with `did`/`does` so it would go silent if the
      widening were doing anything coarser than dropping subject-free scaffolding. Passes.
- [x] the filter list is data, not scattered literals, so the next contaminant is one edit

      Already true and the reason this fix is 5 tokens rather than a new mechanism: `_STOPWORDS`
      is a single `frozenset`. **The card's original premise was wrong and is corrected here** —
      it proposed adding a filter, implying none existed. One did, complete with the
      interrogatives and `has`/`had`/`have`; it simply had a hole for `do`/`did`/`does` and
      `own`. Reading the code before building shrank this from a mechanism to a list entry.
- [x] pytest, ruff, mypy clean

      86 librarian tests (84 + 2 new), ruff clean, mypy clean across 486 files.
- [x] **MUTATION-PROVEN, and the first attempt was VACUOUS.** The no-conflict test must RED on
      the unfixed detector or it proves nothing. My first fixture paired two unrelated notes with
      no opposing-claim signal and passed against BOTH detectors — it could never have fired,
      because the contract needs an antonym or number clash ON TOP of a shared token. Rebuilt
      with an `enable`/`disable` split: now **fails without the fix, passes with it**, while the
      real-contradiction test passes both ways. That pair is the actual proof — one test reddens
      on the bug, one stays green to show the check still works.

## Approval log
