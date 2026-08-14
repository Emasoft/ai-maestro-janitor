---
trdd-id: SE7TP1EU
title: One predicate answers two questions with opposite safe-failure directions
column: todo
created: 2026-08-14T20:47:01+0200
updated: 2026-08-14T20:47:01+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
approval-tier: 0
severity: medium
npt: []
eht: []
external-refs: [TRDD-ZM5LZ24Y, TRDD-RYZCVVKA]
implementation-commits: []
---

# `is_plugin_source_checkout` cannot tell a dev tree from an installed plugin

## The defect (MEASURED 2026-08-14, on this machine)

`scripts/lib/keepalive_stage.py:87` returns True iff some ancestor carries `.git`
**and** that same root carries `.claude-plugin/plugin.json`. Verified live: for
`~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/3.2.0` it returns
**True** — because the plugin installer CLONES, so an installed version is a git
work tree whose root carries a plugin manifest. That is the exact shape the
function uses to mean "developer's source checkout".

Consequence in `scripts/detectors/janitor-self-integrity.py`: `_check_manifest`
and `_check_last_good_pin` both open with this guard and so `return None` before
doing any work **on every installed instance** — which is the only place they were
ever meant to run.

Measured corroboration: this machine's C3 pin names `0.59.0` while the running
version is `3.2.0` (and `0.59.0` is no longer even in the cache — the oldest
present is `0.60.1`). That is the most extreme possible instance of the condition
`_check_last_good_pin` exists to report, and the detector is silent.

**Not a security hole, and NOT publish-blocking.** C2 verifies every exec
regardless; what is lost is the VISIBILITY that C3 has gone dormant. Also note
`_check_last_good_pin` is not in the shipped 3.2.0 at all (it landed in `a8982a03`,
unpublished), so for that check the guard bug is not yet live — it would bite on
the release after this one, which is the argument for fixing it before then rather
than after.

## Root cause — the part worth keeping

The two callers ask DIFFERENT questions whose safe failure directions are
OPPOSITE:

| caller | real question | safe direction |
|---|---|---|
| `stage_closure` | "would writing here destroy a developer's files?" | must **over**-trigger — a refused write costs nothing; TRDD-RYZCVVKA is the 39 GB / reverted-work incident it prevents |
| the two detectors | "are version/pin comparisons meaningless here?" | must **under**-trigger — over-triggering silently disables the audit |

A single predicate cannot fail safe in both directions. Sharing it guarantees that
tightening it for one caller loosens it for the other. The docstring reasons
carefully about `~/.claude` dotfiles repos and the DATA dir — it is thoughtful, and
it simply never considered that the plugin CACHE is itself a clone.

## The fix

**Split the predicate. Do NOT touch `stage_closure`'s guard** — it is deliberately
broad, its breadth is load-bearing, and loosening it re-opens a destructive class.

Add a separate discriminator for the detectors that tests LOCATION rather than
inferring dev-ness from git: a path under `~/.claude/plugins/cache/` or
`~/.claude/plugins/data/` is an INSTALLED instance, whatever VCS metadata it
carries. Location is what actually distinguishes the two, and unlike a `.git` probe
it cannot be confused by how the installer happens to fetch.

## Acceptance criteria

- [ ] `stage_closure`'s guard is unchanged, and a test asserts it still refuses a
      destination inside a plugin source checkout (the RYZCVVKA class stays closed).
- [ ] A test that FAILS on today's code: the detector-side predicate reports
      "installed" for a version dir under the plugin cache **that also contains a
      `.git` and a plugin manifest** — the live shape measured above. Without this
      fixture the bug reappears the next time someone reasons from the docstring.
- [ ] `_check_manifest` and `_check_last_good_pin` actually execute against an
      installed layout, proven by a test that observes a FINDING (not by observing
      silence — silence is what the bug produces).
- [ ] The stale-pin condition on this machine (pin `0.59.0` vs running `3.2.0`) is
      reported once the fix is in, or the card records why it legitimately is not.
- [ ] `uv run pytest`, `uv run ruff check scripts tests`,
      `uv run mypy scripts/ --ignore-missing-imports` clean.

## Notes and lessons learned

Found while trying to close TRDD-ZM5LZ24Y's last acceptance box. That box asks
whether `_check_last_good_pin` "goes quiet on a machine where the fix has run" —
and the detector WAS quiet, which would have ticked it. It was quiet for the wrong
reason twice over: first because I ran the source-tree copy (where the guard
correctly disables it), then because the shipped copy has no such function at all.

**A box phrased as "the detector goes quiet" is unfalsifiable by construction** —
a working invariant, a disabled check, an unshipped check, and a crashed detector
all produce identical silence. ZM5LZ24Y's box must be re-phrased to require a
POSITIVE observation (the pin advancing, seen directly) before it can ever be
ticked honestly.
