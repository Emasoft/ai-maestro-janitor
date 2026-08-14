---
trdd-id: IAJS6M9Z
title: The 5000-token SKILL.md budget has no local gate — every breach costs a full publish to discover
column: complete
created: 2026-08-12T13:35:50+0200
updated: 2026-08-12T14:13:41+0200
current-owner: janitor-main-session
task-type: infra
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: []
---

# A local gate for the per-skill token budget

## Why (measured 2026-08-12, twice in one session)

Two context-budget surfaces bound this plugin. Only ONE of them fails fast:

| budget | enforced by | cost of a breach |
|---|---|---|
| shipped-rules floor (53 700 B) | `tests/test_rules_installer.py` — LOCAL | ~2 s |
| per-skill body (5 000 Claude tokens) | remote CPV, at publish stage 4/11 | **~10 min** (lint + the full 11k-test suite run first) |

Both were breached by the same small edit today. The rules floor said so in seconds; the
skill limit cost a complete publish run to surface — after the suite had already passed.
`MAJOR: SKILL.md body is ~5232 estimated Claude tokens (limit 5000)`.

**The whole family sits at the ceiling** — measured across the shipped skills:
`memory-write 4999 · memory-split 4985 · memory-consolidate 4969 · memory-conflict 4930 ·
memory-repair 4925 · memory-harvest 4899`. With ~1–75 tokens of headroom apiece, ANY
addition to a memory skill is odds-on to breach, so this is a recurring cost, not a one-off.

## What

Add a local test mirroring `test_shipped_rules_stay_under_the_context_floor_cap`, asserting
every `skills/*/SKILL.md` body stays ≤5000 Claude tokens.

**The measure is already reproduced exactly** (validated 2026-08-12 against CPV's own
number — 5232 / 15605 chars, matching byte for byte): strip the YAML frontmatter, encode
the remainder with `o200k_base`, multiply by 1.3, round up.

```python
body = re.sub(r"\A---\n.*?\n---\n", "", src, flags=re.S)
claude_tokens = math.ceil(len(tiktoken.get_encoding("o200k_base").encode(body)) * 1.3)
```

**The one real decision: `tiktoken` is NOT currently a declared dependency.**

- **Option A — add `tiktoken` to the dev group.** Exact parity with CPV; the test means what
  it says. Cost: a new dev dependency (and a BPE data download on first use).
- **Option B — a char-count proxy** (~14 900 chars). No dependency, but it is NOT the metric
  CPV enforces; it would drift, and a gate that disagrees with the authority it proxies is
  the kind of check that trains people to ignore it.

Prefer A. A test that approximates the gate it is standing in for is worse than no test,
because a green run stops being evidence.

Do NOT `skip` the test when `tiktoken` is absent — a skipped budget test looks identical to
a passing one, which is the exact failure mode this card exists to remove.

## Acceptance

- [x] Every `skills/*/SKILL.md` body is asserted ≤5000 Claude tokens by a LOCAL test
- [x] The computed number matches CPV's reported number for at least one known-over file
      (falsify it: a deliberately oversized fixture must FAIL the test)
- [x] The failure message names the offending skill and points at `references/` as the fix,
      mirroring the rules-floor test's wording
- [x] The test does not silently skip when its dependency is missing

## Approval log

- 2026-08-12T13:35:50+0200 — QUEUED by janitor-main-session (tier 0, own scope). Derived
  task: filed while unblocking a publish that this gate would have made unnecessary. Not
  built inline, because adding a dependency mid-unblock is a decision that deserves its own
  change rather than a rider on someone else's.
- 2026-08-12T14:13:41+0200 — COMPLETE by janitor-main-session. Implemented by a delegated
  lean-worker (`d31fd809`), then VERIFIED first-hand rather than on the worker's report:
  - the gate is real — an oversized body makes it FAIL and the message names the offending
    skill (re-falsified independently here, not just taken from the worker's claim, then the
    filler reverted and the tree confirmed clean);
  - Option A was taken — `tiktoken` as a dev dep, exact parity with CPV (4999 / 4985 match
    its reported numbers), no char-count proxy, no skip-when-missing;
  - the editor's `Import "tiktoken" could not be resolved` (Pyright) is NOT a publish
    blocker: publish lints `scripts/` only, with `--ignore-missing-imports`, and
    `uv run mypy scripts` reports Success across 465 files. Checked because a type error in
    the lint gate would have blocked the next release — the diagnostic looked alarming and
    was, on inspection, an editor-env artifact.
  One nit fixed on review: the comprehension encoded every skill TWICE (once in the value,
  once in the predicate), doubling the BPE work each run.
