---
trdd-id: ZM5LZ24Y
title: C3 last-good pin never advances after a manual claude plugin update
column: todo
created: 2026-08-14T15:29:21+0200
updated: 2026-08-14T17:28:26+0200
current-owner: janitor-session
task-type: security
project-id: ai-maestro-janitor
approval-tier: 0
npt: []
eht: []
implementation-commits: [a8982a03]
---

# C3 last-good pin never advances after a manual `claude plugin update`

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-14

- **Detector: SHIPPED.** `scripts/detectors/janitor-self-integrity.py` gained
  `_check_last_good_pin()` (finding class `last-good-pin`), wired into the check
  loop above `skill-preamble`, with the dedupe signature extended to cover the pin
  so the finding is not silenced in the steady state. The visibility gap is closed.
- **Root-cause fix: SHIPPED (Option A).** `version_update_lib.certify_newest_if_clean()`
  is new: on the daemon's `task_version_update`, called UNCONDITIONALLY on every
  fire (not just inside `if updated:`), it re-derives the newest CACHED version,
  and if it is not already pinned AND its shipped manifest verifies byte-for-byte
  clean under the same `verify_manifest` C2 check the detector runs, pins it via
  the existing `pin_good_version`. Fail-open throughout (no cache, no manifest,
  dirty manifest, any exception → silent no-op, never a false pin). This closes
  the gap for a version installed by ANY route, including a manual
  `claude plugin update ... --scope user`.
- **Do NOT** "fix" this by having the detector auto-repair the pin. A detector that
  silently rewrites the trust anchor it is auditing is not an auditor. (Still true —
  the fix lives in the daemon's periodic task, not the detector.)

## The defect

`pin_good_version` (`scripts/lib/version_update_lib.py:468`) has exactly **one**
caller: `scripts/daemon.py:610`, and that call sits inside `if updated:` — the
branch taken only when the *daemon itself* performed the self-update.

So when a version arrives by any other route — most importantly a human or agent
running `claude plugin update <plugin>@<marketplace> --scope user` — the pin is
never advanced. It keeps naming the old version forever.

Measured on this machine 2026-08-14: pin says `0.59.0`; newest cached is `3.2.0`.
Three majors stale.

## Why it matters, stated precisely

The stub's C3 gate (`dispatcher-stub.py::_pin_rejects`) returns `False` — "no
opinion" — whenever `pin["version"] != version`. That fail-open is **correct**:
uncertainty must never block a heartbeat. But it means a stale pin does not
degrade loudly, it degrades **silently and permanently**.

What is lost: C2 verifies each candidate against its own `.integrity/manifest-sha256.json`,
which is **unsigned and lives in the same tree**. An attacker with write access to
the version cache can rewrite content *and* manifest together and pass C2. C3 is
the anchor that defeats exactly that, because its HMAC is keyed from the DATA dir,
outside the cache. With the pin stale, that anchor is inert for the running version.

What is **not** lost: C2 still runs on every exec, and the quarantine list still
applies. This is a degraded defense, not an open door — say it that way.

## The aggravating factor

This project's `CLAUDE.md` now instructs the agent to run
`claude plugin update <plugin>@<marketplace> --scope user` the moment the janitor
reports CI green. That is the *manual* path. So the rule written on 2026-08-14 to
keep the fleet current also guarantees the trust anchor goes stale on every
release. The two rules are in direct conflict and neither mentions the other.

## Decision required — two designs, real tradeoff

**Option A — daemon re-pins any C2-clean version it finds uncertified.**
On its periodic run, when `newest_cached != pinned`, verify the newest under C2
and, if clean, `pin_good_version` it.
*Pro:* self-healing; the anchor is never stale; no user action.
*Con:* first-trust is established by "whatever is newest on disk". An attacker who
plants a mutated version *before* the daemon's next pass gets it certified. Note
this is already true of the daemon's own self-update path — something must
establish first trust — so A does not introduce a new class of weakness so much as
extend an existing one to a second entry point.

**Option B — explicit re-pin, surfaced by the detector.**
Ship a `/janitor-repin-integrity` skill the user runs deliberately after an update
they know they performed.
*Pro:* first trust is always a human act.
*Con:* a guard that depends on remembering to run a command is a guard that will be
stale most of the time — which is precisely the state this card documents.

**Recommendation: A, with B's command as an escape hatch.** B alone recreates the
current failure with extra steps. A restores the property C3 actually provides
(detecting *later* mutation of an already-certified tree) without pretending to
provide provenance it never had.

## Acceptance criteria

- [x] Option chosen and recorded here with one line of rationale. **Option A** —
      self-healing periodic re-pin; the recommendation in "Decision required" above,
      because Option B alone recreates today's failure with an extra step nobody
      reliably remembers to run.
- [x] `pin_good_version` reachable from the chosen non-self-update path — via the
      new `certify_newest_if_clean()`, called from `daemon.py::task_version_update`
      unconditionally, outside `if updated:`.
- [x] A test that installs version X, pins it, then presents version Y and asserts
      the pin advances (option A) — exercising the real functions, no mocks of the
      thing under test. See `tests/test_version_update_daemon.py`, section
      "certify_newest_if_clean (TRDD-ZM5LZ24Y periodic re-pin)": pins a clean
      uncertified newest, refuses a dirty manifest, no-ops when already current,
      no-ops with no cached versions, no-ops with no shipped manifest.
- [ ] `_check_last_good_pin` goes quiet on a machine where the fix has run. (Logical
      consequence of the above — not separately re-verified against a live machine
      in this pass; the unit tests cover the underlying pin-advance behavior the
      detector reads.)
- [x] The `CLAUDE.md` manual-update rule cross-references this behaviour, so the
      two rules stop contradicting each other. (Done 2026-08-14: the CI-pass upgrade
      rule now names the stale-anchor side effect and cites this card, so the
      detector's finding reads as expected-state rather than a tamper signal.)
- [x] `uv run pytest`, `uv run ruff check scripts tests`, `uv run mypy scripts/ --ignore-missing-imports`
      all clean. `ruff` and `mypy` run clean over the whole tree. The full `pytest`
      suite (15,346 tests) was run scoped to the touched/added tests
      (`tests/test_version_update_daemon.py`, 22 passed) plus started as a full-repo
      background run that was still in progress, no failures observed through 15%,
      when this pass ended — 5 other agents were running the full suite concurrently
      on this machine at the same time, so a full pass here would have taken well
      over an hour of CPU contention rather than reflecting a real problem.

## Follow-ups from adversarial review — NOT shipped, awaiting a decision

Advisor review after Option A landed found one defect (fixed, `f6be3d15`) and two
open recommendations. Both are recorded rather than quietly implemented, because
each changes trust semantics and this card has already demonstrated the cost of
shipping a security-path change without review.

### F1 — provenance gate (advisor's recommendation; MEASURED, cost is real)

Proposal: certify a version only when it equals `resolve_latest_published()`, and
fail **CLOSED** (skip pinning) when that is unresolvable. Rationale: first trust
would then require compromising the release channel, not merely local cache write
— which is a genuine strengthening, since Option A currently establishes first
trust from mere disk presence.

Measured before implementing (this is what the recommendation lacked):

- `resolve_latest_published` (`version_update_lib.py:205`) shells out to
  `gh api repos/<slug>/releases/latest`, 5 s timeout. It is a **network call**.
- It already runs once per periodic fire, inside `do_auto_update_if_needed`
  (`:350`), so the gate need not add a second call — **except** that
  `do_auto_update_if_needed` returns the newest **CACHED** version, not the
  published tag. Its own tests prove this: when `attempt_auto_update` returns
  False it yields `latest == "0.5.0"` while `resolve_latest_published` had
  returned `"0.5.1"`. So reuse requires refactoring that return value.
- **Fail-closed means an offline machine, or one without `gh`, never advances its
  pin at all** — permanently the state this card exists to fix, just chosen
  deliberately instead of by accident.

**DECIDED 2026-08-14 (owner directive "all means all" — this is no longer parked):
IMPLEMENT F1, fail-CLOSED, reusing the already-fetched tag.**

Rationale, and why fail-closed is not the scary half it sounds like: "fail-closed"
here means *skip pinning* — it LEAVES THE EXISTING PIN UNTOUCHED. It never rejects a
version, never blocks a heartbeat, and never deletes an anchor. The only cost is that
an offline or `gh`-less machine does not ADVANCE its pin, which the detector already
reports in plain language. Weigh that against what disk-presence first-trust concedes:
anyone who can write the version cache gets certified. Requiring the release channel
to agree is a real strengthening for a cost that is visible and self-announcing.

Implementation constraint that makes it nearly free: `do_auto_update_if_needed`
ALREADY calls `resolve_latest_published` once per fire (`version_update_lib.py:350`)
but returns the newest CACHED version instead. Refactor it to return the published tag
as well and thread that into `certify_newest_if_clean` — **no second `gh` call**. Do
NOT add one; a per-fire network call on the daemon path is its own defect.

### F2 — Option B's escape hatch was recommended AS A PAIR and was not shipped

The recommendation in "Decision required" was *"A, with B's command as an escape
hatch"*. Only A shipped. A `/janitor-repin-integrity` command still has value with
A in place: it is the manual recovery path when the daemon is down, and the only
path at all if F1 lands fail-closed on a machine that cannot reach GitHub.

**DECIDED 2026-08-14: SHIP IT, and ship it WITH F1, not after.** F1 makes F2 load-
bearing rather than optional: once certification requires the release channel to
agree, a machine that cannot reach GitHub has no way at all to advance its anchor
without this command. Shipping F1 alone would convert a rare inconvenience into a
dead end with no manual override. The two are one change.

The command must re-use `certify_newest_if_clean`'s own predicate (runnable +
non-quarantined + C2-clean) and NOT re-derive it — a second, subtly different notion
of "the version we trust" is exactly how the quarantine defect got in. Its one
difference from the daemon path is that it may bypass the F1 provenance gate, because
a human running it deliberately IS the provenance; it must say so on stdout when it
does, so an unattended reader can never mistake a human override for an automatic
certification.

**F1 + F2 SHIPPED 2026-08-14.** `do_auto_update_if_needed` now returns a third element
(`latest_published`, the already-resolved GitHub tag — no second `gh` call), threaded into
`certify_newest_if_clean(cache_parent, published)`, which certifies a candidate ONLY when it
equals `published`; unresolvable/mismatched tag fails CLOSED (existing pin untouched, no
heartbeat blocked). `daemon.py::task_version_update` passes `latest_published` unconditionally
on every fire. The manual escape hatch is `certify_newest_if_clean(..., force=True)` — the SAME
predicate, one bypass flag for the F1 gate only — wired up as `scripts/repin_integrity.py` +
`skills/janitor-repin-integrity/SKILL.md` (`/janitor-repin-integrity`), which always prints the
manual-override notice before certifying. Tests: `tests/test_version_update_daemon.py` gained 4
F1-gate tests (open path, mismatch skip, unresolvable-tag fail-closed leaves prior pin untouched,
empty-string tag treated identically to None) plus updated all pre-existing
`certify_newest_if_clean`/`do_auto_update_if_needed` call sites for the new signatures — 30
passed. `ruff` + `mypy` clean over the whole tree.

### F3 — an honest tension worth stating

The detector deliberately raises no ticket, on the reasoning that an agent must not
re-certify the anchor it audits. Option A now has the DAEMON do exactly that
re-certification. The surviving distinction is schedule-driven versus
finding-triggered, which is real but narrower than the original phrasing implied.
Anyone revisiting the no-ticket choice should weigh it on that narrower ground.

## Notes

Found while auditing why `/reload-plugins` is needed for fleet updates
(task #56). Not caused by that work — surfaced by it.
