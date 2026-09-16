---
trdd-id: H8WRCW0I
title: the branch-protection detector and applier identify the repo by different mechanisms so one can fire while the other is permanently inert
column: complete
created: 2026-08-30T00:46:14+0200
updated: 2026-09-01T19:55:00+0200
current-owner: janitor-main-session
task-type: bugfix
scope: project
project-id: ai-maestro-janitor
severity: high
min-approval-requirement: none
blocked-by: []
npt: []
eht: []
relevant-rules: []
external-refs: [TRDD-7KRF99WI]
---

# Two resolvers, one repo: the detector can see it, the applier cannot

## The defect

The two halves of branch protection answer "which repo am I looking at?" **by different
mechanisms**, and nothing reconciles them:

| half | how it resolves the repo | file:line |
|---|---|---|
| **detector** (`branch-protection.py`) | `gh repo view` — infers from the **origin remote** of the cwd's git repo, or `CLAUDE_PLUGIN_OPTION_GITHUB_REPO` | `scripts/detectors/branch-protection.py:108-113` |
| **applier** (`branch_protection_apply.py`) | `detect_repo_slug(plugin_root)` — reads `repository` out of **`.claude-plugin/plugin.json`**, regex `^https?://github\.com/owner/repo$` | `scripts/guard/branch_protection_apply.py:138` → `branch_protection_lib.py:479-492` |

`detect_repo_slug` has **no git-remote fallback**: no manifest, no `repository` key, or a URL in
any other shape returns `None`, and gate 3 then `return 0`s.

So on any project where the resolved project root does not contain `.claude-plugin/plugin.json` —
a repo nested under a workspace parent, a non-plugin project, a manifest one level down — the
**detector works and files findings while the applier can never act at all.** The janitor
correctly reports the problem forever and is structurally unable to fix it.

## Measured in the wild (AMAMA peer, 2026-08-29/30) — this is not hypothetical

`CLAUDE_PROJECT_DIR` unset ⇒ `state._resolve_project_root` falls to cwd =
`…/EMASOFT-ASSISTANT-MANAGER`, the **parent**. The manifest lives one level down in
`ai-maestro-assistant-manager-agent/`. Their applier log, one line per pass, for days:

```
[2026-08-28T17:08:40+0200] skip: cannot resolve owner/repo slug from plugin.json
[2026-08-28T23:11:24+0200] skip: cannot resolve owner/repo slug from plugin.json
[2026-08-29T05:13:01+0200] skip: cannot resolve owner/repo slug from plugin.json
[2026-08-29T11:15:19+0200] skip: cannot resolve owner/repo slug from plugin.json
[2026-08-29T17:17:31+0200] skip: cannot resolve owner/repo slug from plugin.json
[2026-08-30T00:01:41+0200] skip: cannot resolve owner/repo slug from plugin.json
```

Four passes a day, every one declining, deterministically, since at least 2026-08-28. Meanwhile
the detector half filed a real finding against that repo, so the *problem* was surfaced while the
*inertness of the fixer* was not.

## The part that makes it severity-high: it reports success

`scripts/guard/branch_protection_apply.py:139-144` — the skip writes ONE `state.log_line` and
returns 0. It raises no finding, emits nothing on stdout, and advances its `last-run` stamp
exactly like a successful pass. So every user-facing surface says healthy:

- the heartbeat fires and reports normally,
- `last-run-guard-branch-protection.ts` is minutes old,
- the findings ledger carries other detectors' entries,
- and the ONE dissenting signal is a log line in a file nobody reads.

The peer found it only after being wrong twice and going looking. **A lane that runs, declines
deterministically, and reports success is worse than a lane that is visibly dead**, because
"act, don't ask" (the USER's standing security directive that made `guard_mode_enabled` default
True) promises the janitor FIXES branch protection — and a user reading that promise plus a green
heartbeat has no way to learn it has never once applied.

## Acceptance

- [x] the applier's repo resolution matches the detector's, or falls back to it — `detect_repo_slug`
      now falls back to `_slug_from_git_remote` (origin, accepting BOTH https and ssh shapes,
      since a repo cloned over SSH is not a different repo). Manifest stays FIRST and
      authoritative: it is a deliberate declaration; `origin` is whatever the clone points at.
      PROVEN load-bearing against HEAD on one fixture — `OLD: None` vs
      `NEW: Emasoft/ai-maestro-janitor`. Three tests added, incl. manifest-beats-a-divergent-remote
- [x] an unresolvable slug on a project that HAS a GitHub remote raises a FINDING, not just a log
      line — new code **BRPROT-003** (severity high), raised from gate 3, gated on
      `_project_has_github_remote`. That gate is deliberately CRUDER than `detect_repo_slug`'s
      parser (it asks only whether `github.com` appears in the origin URL): matching the parser
      would make the two agree by construction and the finding could never fire. No remote ⇒ no
      finding, which is the card's own "do not make gate 3 loud" warning honoured
- [x] the skip does not advance the `last-run` stamp, OR the stamp is not the health signal —
      **resolved as the second branch, deliberately.** `dispatch.py:2159` writes the stamp
      unconditionally after the subprocess, and that is CORRECT: it is a cadence marker meaning
      "a pass was attempted", so making it conditional on success would make a declining project
      retry every heartbeat forever instead of every 6 h. The real defect was that a decline
      produced no OTHER signal — which BRPROT-003 above now supplies. **Nothing should read
      `last-run-*.ts` as health**; it answers "when was this last attempted", never "did it
      work" — the exact confusion that cost two sessions an investigation tonight
- [x] a test asserts an applier skip is visible — two tests, and the pair is the point: one
      proves a GitHub repo the applier cannot name RAISES BRPROT-003 (fixture: a URL git accepts
      and the parser rejects, the only interesting case once the remote fallback exists), the
      other proves a non-GitHub project stays SILENT. Load-bearing by construction: BRPROT-003
      did not exist before this change, so the assertion could not have passed
- [x] `uv run pytest -q` + `ruff check scripts tests` + `mypy scripts/ --ignore-missing-imports`
      — full suite GREEN 2026-09-01 19:30 (15,939 passed, 0 failed) + full ruff clean + mypy
      clean over all 495 files. (The suite's `_state` alias guard hit in this card's own
      `branch_protection_lib.py` was fixed in `e3299d8d` on the way.)

## Notes and lessons learned

- **ORDER MATTERS AND IS LOAD-BEARING: fix TRDD-7KRF99WI FIRST.** The moment this resolution is
  repaired, the applier starts acting on repos it has never touched — and on any repo with a
  PR-triggered matrix job its first act is to install an unsatisfiable required context. Fixing
  this card alone converts a silent no-op into an active breakage across the fleet at once.
- **Do NOT fix this by making gate 3 loud without fixing resolution.** A finding per pass on every
  non-plugin project is noise that trains its reader to ignore the channel.
- The peer's own summary is the transferable form: *"not a dark lane nobody watches, but a lane
  that runs, declines deterministically, and reports success."* Both halves of that sentence are
  needed — the running is what makes the stamps fresh, and the declining is what makes the work
  never happen.
- This repo cannot reproduce it: its manifest sits at the project root, so `detect_repo_slug`
  succeeds and the applier runs. **Third finding tonight that this repo could not have produced
  about itself** — see the same note on TRDD-7KRF99WI.
