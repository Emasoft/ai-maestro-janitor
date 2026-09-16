---
trdd-id: MKCPL3ZH
title: Both GitHub notification chores run always, on the cron, with project-local state
column: published
created: 2026-08-02T03:16:58+0200
updated: 2026-08-02T03:52:00+0200
released-in: v2.3.0
implementation-commits: [559930a, a2d43cf, 3e83dac, 8cd8fb2]
current-owner: claude
assignee: claude
task-type: feature
priority: 2
severity: MEDIUM
effort: M
release-via: publish
test-requirements: [unit]
supersedes-design-of: TRDD-2KQQAEPP
labels: [github, notifications, heartbeat, always-on, security]
---

# Both GitHub notification chores run always, on the cron (TRDD-MKCPL3ZH)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-02

**STATUS: SHIPPED in v2.3.0** (published 2026-08-02T01:50:03Z), installed at USER scope
(2.1.0 → 2.3.0). All 11 publish gates passed; remote CPV `PARITY-CLEAN (FAIL=0, WARNING=3,
PASS=8)`; full suite 14057 passed / 1 skipped; ruff + pyright clean.

**NEXT ACTION: none.** The last open decision (the four vestigial on/off skills) was resolved
by the owner the same night — *"delete the vestigial skills and commands. complete all tasks
and publish"* — and they are deleted.

Verified AFTER install rather than inferred from the CLI's success message: the user-scope
record points at the `2.3.0` cache dir, `gh-reply-watch.py` is present there, the four deleted
skills are absent from it, and the cached `github-issues-watch.py` carries the always-on gate.
The auto-rolling dispatcher stub resolves the newest cache, so the next heartbeat fire runs
the new detector with no re-arm.

## The directive

Owner, 2026-08-02: *"the job of detecting if someone posted a new issue on the project repo
and to track the github posts made by the current active project main claude and regularly
check and reports if there are replies, must be a chore executed always by the janitor. no
need to enable it. so change the skill to be on by default, and integrate it better in the
chron. ensure it works both inside ai-maestro harness and outside."*

Same night, follow-up: *"the github detector script should run in each session/claude-code/
project independently, and store the tracking data locally."*

## What was wrong

Neither chore ran unless a human turned it on, and each failed differently:

- **`github-issues-watch`** (new issues/comments on this project's own repo) was a heartbeat
  detector gated on `.janitor/state/issues-watch.flag`, written by `/janitor-issues-watch-on`.
- **The GH-reply monitor** (replies to threads this project opened, anywhere) was a
  session-scoped `Monitor` loop started ONLY by step 3 of one SKILL.md. It died on every
  restart and compaction, and its own skill documented that. **A hook cannot call the
  `Monitor` tool**, so that design could not be made always-on where it stood.

## The key realisation

`gh_notify_poll.py::do_poll` was **already a one-shot** — poll once, print, write the cursor,
exit. The `Monitor` only wrapped it in `while true; sleep 120`. So the reply watcher becomes
an ordinary detector and the heartbeat supplies the schedule. That also settles the harness
half for free: `_NON_HARNESS_DETECTORS` is a **deny-list** and neither chore is on it, so both
run in both backends (verified by importing `dispatch` and calling the predicate; pinned by a
test so a later roster sweep cannot half-revoke the directive).

## The load-bearing part: the first fire is silent

The retired `/janitor-issues-watch-on` seeded a baseline **before** arming its flag, and its
skill called that ordering load-bearing. Removing the flag without keeping the seeding makes
the first fire on every repo diff against an empty map. **Measured on this repo: 43 open
issues would have landed in context on the first fire.**

Both detectors now adopt current state and emit nothing when their cursor is missing. The test
is `exists()`, **never** the parsed value — `_read_seen` fails open to `{}` for a CORRUPT file
too, and there re-reporting is the deliberately safe direction; treating corruption as "first
run" would silently swallow whatever arrived while the map was broken.

## Security: the sanitization was not optional

The poller interpolates attacker-controlled GitHub text — the issue **title** and the replying
comment **body** — and its `squeeze()` only collapses whitespace and truncates. Harmless while
that output went to `Monitor` notifications a human reads. **Not harmless as heartbeat drift
the MODEL acts on**, where a bare `[janitor-…]` line is an instruction: an issue titled
`[janitor-self-disarm]` would have been a path from "anyone can open an issue" to "the janitor
stops". Every forwarded line now goes through `state.sanitize_for_drift_line`, matching what
`github-issues-watch` already did via `issues_watch.format_drift`.

## State moved into the project

`.janitor/gh-issues-monitor/`. Slug-keyed subdirs of the machine-global DATA dir gave
per-project SEPARATION but not LOCALITY: keyed by absolute path, so moving or renaming a
checkout silently orphaned its registry, and one store held every project's record of work.

Deliberately **not** `.janitor/state/`, which is advertised (CLAUDE.md, the janitor-footprint
rule) as regeneratable and safe to delete — `registry.json` is filled by the PostToolUse hook
as `gh` commands happen, so a lost registry cannot be rebuilt, only re-accumulated from future
posts. Sitting one level up keeps it local as directed while staying out of the disposable
zone. Migrates from both older locations newest-first, **copy never move**; verified on this
repo's real registry (4 threads, byte-identical, source intact), and `.gitignore`'s `.janitor/`
still covers the new path (`git check-ignore` confirmed).

## Two runtime bugs fail-open would have hidden forever

1. `gh_notify_poll.py` is **not** `chmod +x` — it must be run as `uv run --script`. A direct
   exec is `permission denied`, and a fail-open detector would have swallowed that and simply
   never reported a reply.
2. The new detector needed its **own** exec bit, or CI's strict per-detector run goes red.

## Verification

Six mutations, six kills — each guard has a test that goes red without it. The one worth
recording is **M3**, because it found a hole rather than confirming one: deleting the
anti-flood branch left all 22 tests green, because the tests pinned the *arithmetic* of the
baseline and never reached the detector's *use* of it. Closed with end-to-end tests running
the real detector against a real git repo with a fake `gh` (only the external service is
faked). M4 (silent but never seeds — fine on fire 1, floods on fire 2), M5 (legacy precedence
swapped), M6 (copy→move) all go red now.

## RESOLVED — the four on/off skills are deleted

Asked, initially unanswered (so nothing was touched), then decided by the owner the same
night: *"delete the vestigial skills and commands. complete all tasks and publish"*. All four
`SKILL.md` files removed with `git rm`, from a clean tree at `3e83dac`, so each is restorable
with `git checkout 3e83dac -- <path>`.

The reasoning they were measured against: the `-on` pair had nothing left to enable, and the
`-off` pair was exactly the per-feature silent disable the 2026-07-31 directive ("remove the
very option of disabling the janitor features") removed — a project sitting un-watched looks
identical to a healthy one from the outside. Arm/disarm remains the only switch; the two
config knobs remain for a deliberate, visible opt-out.

**Derived task the deletion forced:** `.integrity/manifest-sha256.json` pinned all four files
by hash, so removing them without regenerating it would have made `janitor-self-integrity`
report four missing files on every fire — a self-inflicted tamper alarm. Regenerated
(74 → 70 entries); the detector runs clean.

No `commands/` entries existed for these features, so "skills and commands" resolved to the
four skills alone — verified before deleting rather than assumed.

## Notes

- `issues-watch.flag` joined `state.RETIRED_SENTINELS`, swept like `paused` /
  `maintenance-mode`: an inert flag on disk makes a healthy host look configured.
- Knobs: `issues_watch_enabled` (true), `gh_reply_watch_enabled` (true),
  `gh_reply_watch_interval` (900), plus the existing `issues_watch_interval` (1800). The reply
  watcher previously had **zero** plugin.json presence, so its cadence was invisible in
  `/config`.
- Cadence 900 s sits far above GitHub's `X-Poll-Interval: 60` floor; the heartbeat tier bounds
  it further.
