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

## 2026-07-11 (later) — ATTRIBUTED. And my "suite is EXONERATED" claim above was WRONG.

**RETRACTION.** The section above says "the test suite is EXONERATED — on the merits". That
was false, and the way I reached it is the lesson. I instrumented `stage_closure`'s refusal
and ran all 12,479 tests — but that run was AFTER `fef258c`, which REFUSES the write. I proved
"the fix works" and reported it as "the suite never did this". A guard installed before the
experiment invalidates the experiment.

**The keepalive's own boot log named the mechanism** (`global-state/daemon-keepalive.boot.log`
— a file I never opened until asked to keep digging, and had wrongly claimed was last touched
Jul 9):

- Its LAST entry: `staged closure is corrupt/incomplete (6 file(s): daemon.py,
  lib/fleet_inject.py, lib/fleet_recovery.py, lib/rules_installer.py, lib/terminal_trigger.py,
  oauth_rotator/safe_storage.py); restaging from …/cache/…/0.39.0/scripts`.
- Beside it, `daemon-keepalive.restage-stamp` = epoch 1783773340 = **2026-07-11 14:35:40 +0200**
  — the clobber instant to the second — carrying that same 6-file list.
- Those 6 files are EXACTLY the files this repo had changed since v0.39.0 (the 0GPQROC1
  soft-injection work, the 460aad0 rules work, the 7ceab3f keychain latch).

So the boot gate compared **the REPO** against **the cached release**, concluded my newer
committed code was "corrupt", and "repaired" it by overwriting the repo with v0.39.0. The lost
exec bits follow: `stage_closure` writes a fresh tmp at the 0644 umask, then `os.replace`s.

**The invoker: a process running `<repo>/scripts/daemon_keepalive_entry.py` with the REAL env.**
`verify_or_restage` is called from exactly one place — that entry, on its OWN directory — so a
repo destination means the repo's copy was executed. It was NOT under pytest (pytest_configure
redirects `JANITOR_GLOBAL_STATE_DIR`, so the stamp would have landed in tmp, not the real dir)
and NOT launchd (its plist points at the DATA copy — verified via PlistBuddy). Beyond that the
trail is cold; the exact caller stays unattributed, and I am not going to invent one.

**But the log ALSO proves a chronic, separate leak:** of its 432 lines, **296 name a pytest tmp
dir as the restage SOURCE**. Tests have been writing into REAL production state for a long
time — straight through per-module `_isolate_janitor_state` fixtures that each claim to prevent
exactly that. And S1b, the detector meant to catch this, EXCLUDES `.log` and `.restage-stamp`
as "daemon liveness" — the two files this incident wrote. **The guard was blind to its own
incident.**

## The fix — three layers, because every opt-in layer here has been escaped at least once

1. **`fef258c` — the write path.** `stage_closure` refuses a destination inside a plugin SOURCE
   checkout. Closes the repo-clobber for ANY caller, test or not.
2. **`05b1a38` — the S1e HARD WRITE SANDBOX (the user's ask: "block any test attempting to
   write outside of its boundaries").** `pytest_configure` wraps the write syscalls
   (`builtins.open`, `io.open`, `os.open`, `replace`/`rename`/`symlink`/`link`,
   `remove`/`unlink`/`rmdir`/`mkdir`/`makedirs`/`chmod`/`truncate`, `shutil.rmtree`) and RAISES
   on any write into the real `~/.claude` tree or this repo's source. Not a fixture — nothing
   to opt into, nothing to forget.
3. **`05b1a38` — S1c repaired.** The guard I added in `56bf46d` built its BEFORE manifest with
   `_source_manifest` (*.py/*.sh) and re-snapshotted with `_manifest` (everything), so the
   vendored Rust tree read as ~15k "ADDED" files. It would have drowned any real signal in
   noise. Now both ends use the same function.

**The sandbox caught two bugs in itself while being written** — which is the whole argument for
writing positive controls instead of trusting a guard's docstring:
- `io.open` is a SEPARATE binding from `builtins.open`; `pathlib` writes go through `io`, so
  patching only builtins let every `Path.write_text` straight through.
- For `os.replace(src, dst)` the file DESTROYED is `dst`. I guarded `src` — policing the
  harmless tmp file and waving the clobber through. **It overwrote `scripts/daemon.py` a second
  time, mid-fix**, and only the positive control caught it.
- Honoring `dir_fd`: `shutil.rmtree` walks with `os.rmdir("design", dir_fd=…)` — a bare relative
  name. Resolving it against the cwd made a `TemporaryDirectory` cleanup look like an attack on
  the real `design/` and failed 68 innocent tests. Fixed by skipping fd-relative calls and
  guarding `rmtree` at its entry point (which is what actually bounds the recursive delete).

**Verified:** 12,490 passed / 1 skipped; zero sandbox blocks outside the sandbox's own tests;
`git status scripts/ design/ hooks/ rules/` clean after a full run; the real boot log's mtime
still reads 14:35:40, i.e. the suite no longer touches it.

**Do NOT dismiss this as a one-off.** It silently reverted committed source. Had it landed
on a file that was then edited and committed, it would have shipped a regression of already
published fixes — and the only reason it was caught at all is that it happened to clear an
executable bit the tests depend on.

**REMAINING (lead 3, still open):** audit every caller of `restage` / `install` /
`verify_or_restage` for a path where the destination could resolve to the repo. The write is
refused now, so this is hardening, not risk.

## Notes and lessons learned

[^1]: [ocd:2026-07-11 lmd:2026-07-11] I reported "the test suite is EXONERATED — on the merits,
  not by the guard" after instrumenting the suite and seeing no hits. The instrumented run was
  AFTER the guard that refuses the write had landed, so the experiment could only ever come back
  clean. Lesson: an experiment run after installing the fix proves the fix, never the innocence
  of the suspect. Reconstruct the incident from artifacts written AT THE TIME (here: the boot log
  and restage-stamp, which were sitting on disk the whole time and which I asserted, without
  looking, were stale).
[^2]: [ocd:2026-07-11 lmd:2026-07-11] A detector that excludes the very files an incident writes
  cannot see that incident. S1b excluded `.log` and `.restage-stamp` as "daemon liveness churn";
  those are precisely what the clobber wrote. When adding an exclusion to silence noise, ask what
  class of failure the exclusion makes invisible.
[^3]: [ocd:2026-07-11 lmd:2026-07-11] Opt-in isolation fails silently and forever. Three layers
  (per-module fixtures, session-default env redirect, manifest guards) all claimed to prevent
  tests touching real state, and 296 log lines say they did anyway. Only refusing the write at
  the syscall — with no opt-in — actually holds.
