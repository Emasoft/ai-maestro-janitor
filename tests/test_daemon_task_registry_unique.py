"""The daemon's chore registry must hold ONE task per name (TRDD-5G66S0HK follow-up).

A DUPLICATE `Task("memory-guard", ...)` was shipped in e67f9b0c — the runaway-kill
commit added the line twice, once by mistake, while inserting the `runaway-guard`
chore next to it. The duplicate is LATENT rather than loud today, and the reason is
worth writing down, because it is the kind of thing that hides until a later change
makes it real:

  * the cadence stamp is KEYED BY NAME (`gs.last_run_path(name)`), not by instance, so
    the two `memory-guard` objects share ONE `memory-guard.last-run.ts`;
  * `_run_due_tasks` re-checks `task.is_due()` per instance, and the first instance to
    run stamps the shared file — so the second instance reads a fresh stamp and is
    skipped for the rest of the interval.

So today the duplicate costs a registry entry and nothing else. It is still a defect:
the registry's contract is one task per name, and the code that makes it harmless is
the code that would make a DIFFERENT duplicate dangerous. A future change that gives
a task per-instance state (a per-instance counter, a per-instance child handle, a
per-instance lease) turns "shared stamp" into "two workers with one lease", and the
double-run appears with no diff that looks related.

The invariant is therefore pinned here, and it is pinned on the REGISTRY rather than
on a symptom: the defect class this test exists for is a double-run, and a
double-run cannot be observed while the shared stamp hides it.

WHAT THIS TEST PINS:
  1. `_build_tasks()` returns no duplicate task names.
  2. The registry still contains the chores it must — so a "fix" that deletes a
     chore to satisfy (1) fails here.
  3. `memory-guard` is present exactly once, and `runaway-guard` is present — the
     two the duplicate sat between.

No mocks: the registry is read from the real module, and the state seam
(`JANITOR_CONTROL_DIR` / `JANITOR_GLOBAL_STATE_DIR`) is redirected by conftest, so
this test cannot touch the host's real cadence stamps.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts"))
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

import daemon  # type: ignore[import-not-found]  # noqa: E402


def test_no_duplicate_task_names_in_the_registry() -> None:
    """Every chore name appears at most once in `_build_tasks()`.

    A duplicate is a defect even when it is currently harmless: the cadence stamp is
    name-keyed, so the second instance of a duplicated chore shares the first's
    stamp and is silently skipped — the duplication is invisible in the logs, and it
    becomes a real double-run the moment any task grows per-instance state.
    """
    tasks = daemon._build_tasks()
    counts = Counter(t.name for t in tasks)
    duplicates = {name: n for name, n in counts.items() if n > 1}
    assert not duplicates, (
        f"duplicate chore names in the registry: {duplicates}. "
        f"Every chore name must be unique — a duplicated chore shares the other's "
        f"name-keyed cadence stamp, so the duplication is invisible until a task "
        f"grows per-instance state."
    )


def test_the_registry_still_holds_the_chores_it_must() -> None:
    """The unique-names rule must not be satisfied by DELETING a chore.

    A "fix" that removes `memory-guard` — or any other chore — to make the
    uniqueness assertion pass would satisfy (1) and silently disable a default-ON
    chore. This test pins the membership so that trade is impossible.
    """
    names = {t.name for t in daemon._build_tasks()}
    for required in (
        "memory-guard",
        "runaway-guard",
        "oauth-rotator-tick",
        "oauth-rotator-supervisor",
        "cache-prune",
        "session-liveness",
        "cold-cache-clear",
    ):
        assert required in names, f"chore {required!r} is missing from the registry"


def test_memory_guard_and_runaway_guard_each_appear_once() -> None:
    """The two chores the duplicate sat between, each exactly once.

    `memory-guard` is the default-ON Tier-1 OOM killer; `runaway-guard` is the
    opt-in runaway-kill beat (TRDD-5G66S0HK). The shipped duplicate was a second
    `memory-guard` line inserted next to the `runaway-guard` registration, so this
    names the exact pair involved rather than asserting the general invariant
    twice.
    """
    counts = Counter(t.name for t in daemon._build_tasks())
    assert counts["memory-guard"] == 1, (
        f"memory-guard appears {counts['memory-guard']} times; it must appear once"
    )
    assert counts["runaway-guard"] == 1, (
        f"runaway-guard appears {counts['runaway-guard']} times; it must appear once"
    )
