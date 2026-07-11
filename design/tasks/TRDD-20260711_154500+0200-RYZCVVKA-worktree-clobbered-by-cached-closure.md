---
trdd-id: RYZCVVKA
title: The repo working tree was overwritten with the CACHED plugin closure — writer unidentified
column: todo
created: 2026-07-11T15:45:00+0200
updated: 2026-07-11T16:30:00+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 1
severity: HIGH
effort: M
labels: [safety, tooling, keepalive, data-loss-risk]
task-type: bugfix
relevant-rules: []
release-via: none
test-requirements: [unit]
external-refs: []
---

# The repo working tree was overwritten with the CACHED plugin closure

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-07-11

**What happened.** During the 2026-07-11 session, this repo's working tree was silently
overwritten with the files from the **installed plugin cache (v0.39.0)**. Fully recovered;
**no committed work was lost** — git HEAD was intact, only the working tree was touched,
and no commit made that day included a clobbered file.

**The evidence (verified, not inferred):**

- The overwritten set is EXACTLY `keepalive_stage.daemon_closure()` — `daemon.py`,
  `daemon_keepalive_entry.py`, `lib/{fleet_scan,fleet_inject,fleet_recovery,
  terminal_trigger,rules_installer,memory_scopes,keepalive_boot,daemon_path,dedupe,
  version_update_lib,launchd_keepalive,__init__}.py`, `oauth_rotator/{rotator,
  safe_storage}.py`. That is the signature of `stage_closure(cache → <repo>/scripts)`.
- Every clobbered file was **byte-identical to the released tag `v0.39.0`** — the tree was
  REVERTED past every commit made since that release, silently stripping (among others)
  the keychain-latch fix `7ceab3f` and the rules-floor work `460aad0` from the working
  tree.
- They all share one mtime: **14:35:40**.
- The **executable bit was cleared** (100755 → 100644) on `daemon.py`,
  `terminal_trigger.py`, `rotator.py` — published copies are 644. That is what actually
  surfaced the incident: 22 tests began failing with
  `PermissionError: .../scripts/daemon.py`, because the suite spawns it directly.

**The mechanism is known; the CALLER is not.** `launchd_keepalive.data_dir()` honors
`JANITOR_DATA_DIR`, and `data_scripts_dir()` is `data_dir()/scripts`. If that ever
resolves to the repo, `restage()` / `verify_or_restage()` copy the cached closure straight
into `<repo>/scripts`. **This exact failure class has happened before**: `data_dir()`'s own
docstring records TRDD-ZNN0UK5K, where the keepalive TESTS resolved to the REAL data dir
and restaged the real closure, driving a 39 GB fseventsd runaway.

**The test suite is EXONERATED.** After the tree was restored, a full `pytest` run left the
repo byte-identical (canary: sha of `daemon.py` + `safe_storage.py` before and after), and
the keepalive test files alone also left it intact. The conftest's session-default
isolation and its S1b write-guard both work. So something OUTSIDE the suite did this, once,
at 14:35:40.

## 2026-07-11 — THE WRITE PATH IS FOUND AND CLOSED. The one-off INVOKER is not.

**The mechanism (exact, read from the code):**

```
daemon_keepalive_entry.py:39   _HERE = dirname(abspath(__file__))     # the entry's OWN dir
daemon_keepalive_entry.py:55   keepalive_boot.verify_or_restage(_HERE)
keepalive_boot.py:204            else: keepalive_stage.stage_closure(cache, staged)
                                 # "keeps the gate self-consistent if ever invoked from a non-DATA dir"
```

`verify_or_restage` compares the closure in the dir it is GIVEN against the trusted cache
and, on any mismatch, copies the cache OVER that dir. The entry hands it its own directory.
So **running the REPO's copy of the entry overwrites the repo with the installed plugin's
files** — and `_repair`'s `else` branch was written to do exactly that on purpose, for a
"non-DATA dir" that was never supposed to be a source checkout.

Every symptom follows: whole-closure overwrite; byte-identical to the cached v0.39.0; and
the lost exec bits (`stage_closure` writes a fresh tmp file at the 0644 umask, then
`os.replace`s it over the original — only the entry itself gets a chmod 755).

**CLOSED (`fef258c`):** `stage_closure` now REFUSES a destination inside a plugin source
checkout (git work tree + `.claude-plugin/plugin.json` at its root). `verify_or_restage`
catches everything and fails open, so the refusal degrades to a loud log instead of a
silent clobber. The predicate is narrow on purpose — "inside any git repo" would refuse the
LEGITIMATE production stage for anyone who keeps `~` or `~/.claude` in a dotfiles repo, and
that would silently kill the L0 keepalive (a test covers exactly that false positive).

**The test suite is EXONERATED — on the merits, not by the guard.** The suite was run with
the refusal instrumented to dump a stack on every hit: across all 12,479 tests the ONLY
refusal was the guard's own fixture. Nothing in the suite stages into the repo. Independent
corroboration: the REAL keepalive boot log's last entry is Jul 9, so the production
keepalive never restaged on Jul 11 either.

**Backstop (`56bf46d`):** conftest S1c now snapshots a sha manifest of `scripts/**` (*.py +
*.sh, 401 files) and FAILS the suite if any of it changes.

**STILL OPEN — who ran the repo's entry at 14:35:40?** Not the suite, not launchd (its plist
points at the DATA copy — verified), not the daemon (it never calls `verify_or_restage`).
Something executed `<repo>/scripts/daemon_keepalive_entry.py` once. Note the self-limiting
shape that made it a single event: after the clobber the repo == cache, so the mismatch
that triggers a restage was gone and it could not fire again.

**It can no longer cause damage** — the write is refused and any recurrence inside the suite
fails loudly. What remains is attribution, not risk.

**NEXT ACTION — remaining leads:**

1. ~~Add a repo-tree write guard to `conftest.py`~~ — DONE (`56bf46d`, S1c). — the mirror of the existing S1b
   DATA-dir guard: snapshot a sha manifest of `scripts/**` at session start and FAIL the
   suite if it changes. Cheap, and it catches a recurrence instantly, with a stack. Do this
   regardless of what the investigation finds.
2. ~~Make `stage_closure()` REFUSE a source-checkout destination~~ — DONE (`fef258c`). The closure is
   only ever staged into the DATA dir, so a repo destination is ALWAYS a bug. This is the
   real fix — it makes the whole class impossible instead of merely detectable — and the
   TRDD-ZNN0UK5K recurrence is the argument for building it.
3. Audit every caller of `restage` / `install` / `verify_or_restage` for any path where
   `JANITOR_DATA_DIR` (or a cwd-relative fallback) could resolve to the repo — including
   the SessionStart hook and any subprocess that inherits a partially-isolated env.

**Do NOT dismiss this as a one-off.** It silently reverted committed source. Had it landed
on a file that was then edited and committed, it would have shipped a regression of already
published fixes — and the only reason it was caught at all is that it happened to clear an
executable bit the tests depend on.

## Notes and lessons learned
