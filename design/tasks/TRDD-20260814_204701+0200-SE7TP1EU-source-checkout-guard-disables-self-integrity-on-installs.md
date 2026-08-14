---
trdd-id: SE7TP1EU
title: One predicate answers two questions with opposite safe-failure directions
column: backburner
created: 2026-08-14T20:47:01+0200
updated: 2026-08-14T20:56:00+0200
current-owner: janitor-session
task-type: bugfix
project-id: ai-maestro-janitor
approval-tier: 0
severity: low
npt: []
eht: []
external-refs: [TRDD-ZM5LZ24Y, TRDD-RYZCVVKA]
implementation-commits: []
---

# `is_plugin_source_checkout` cannot tell a dev tree from an installed plugin

## ⚠ CORRECTION 2026-08-14, SAME DAY — the central claim below is FALSE

**Severity drops from medium to LOW; this is a narrow fragility, not a universal
defect.** The section below asserts the guard misfires on EVERY installed instance.
It does not.

The USER emptied `~/.claude/plugins/cache/` entirely and Claude Code re-cloned it
(no crash — the install manifests live outside the cache and are authoritative).
Re-measured on the FRESH clone:

```
no-git  MANIFEST  3.2.0
```

The freshly installed plugin dir carries `.claude-plugin/plugin.json` but **no
`.git`**, and no ancestor has one either — so `is_plugin_source_checkout()` returns
**False** and both self-integrity checks run exactly as designed on a normal
install.

The `.git` I measured in that directory was real (observed directly), but it was an
**artifact of that one install**, not something the installer creates. My inference
"the installer clones, therefore every cache dir is a git work tree" was wrong, and
I generalized it from a single host without ever checking a clean one.

**What survives, narrowly:** IF a cache dir acquires a `.git` by any route (a manual
clone into the cache, a dev experiment, an older installer), the guard silently
disables `_check_manifest` and `_check_last_good_pin` for that install, with no
signal — the tamper detector goes dark exactly when the tree has been touched by
hand, which is not the moment you want it dark. That is worth a cheap defence, and
it is why this card is corrected rather than withdrawn.

**USER, same day — the guard fails in the OTHER direction too, and that half is
worse.** "It is perfectly valid to publish a plugin that has no git at all." So a
plugin SOURCE tree may legitimately carry no `.git`, and then
`is_plugin_source_checkout()` returns False — meaning **`stage_closure` does not
refuse the write**. That is the destructive direction: the TRDD-RYZCVVKA class
(2026-07-11, this repo's closure reverted to the v0.39.0 release, surfaced only
because a lost +x bit broke 22 tests) is re-openable against any git-less plugin
checkout.

`.git` is therefore a poor discriminator in BOTH directions — present on some
installs, absent from some sources — which is a stronger argument for the
location-based test than the one I originally filed. **Raise the write-guard half
back up if it is ever confirmed reachable**; it is only `low` because
`stage_closure`'s destination is the DATA dir in every current caller, so the guard
is defence-in-depth rather than the sole barrier.

**What does NOT survive:** any claim that self-integrity is inert in production, and
the urgency that came with it. The "one predicate, two opposite failure directions"
analysis stays a valid design observation, but it is no longer evidence of a live
outage.

**The lesson, which is the reusable part:** I measured one host, found a startling
result, and filed it as a general defect without testing a clean install — the
cheapest possible control. A finding whose blast radius is "every machine" deserves
at least one second machine, or one clean state, before it is written down as fact.

---

## The defect as originally filed (SUPERSEDED by the correction above — retained
## verbatim as the record, do NOT act on it)

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
