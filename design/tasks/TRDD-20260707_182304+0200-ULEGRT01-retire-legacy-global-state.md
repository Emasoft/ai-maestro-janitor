---
trdd-id: ULEGRT01
title: Retire the legacy janitor-global-state read-fallback (EHT of TRDD-2U8AH82F)
column: planned
blocked-by: []
created: 2026-07-07T18:23:04+0200
updated: 2026-08-28T16:09:43+0200
current-owner: ai-maestro-janitor
assignee: ai-maestro-janitor
priority: 6
severity: LOW
effort: S
approval-tier: 0
task-type: refactor
parent-trdd: TRDD-2U8AH82F
labels: [daemon, state-migration, cleanup]
release-via: publish
test-requirements: [unit]
---

# TRDD-ULEGRT01 — Retire the legacy `~/.claude/janitor-global-state/` read-fallback

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-08-28

**⏵ STEP 0 IS DONE (2026-08-28). THE GATE WAS REWRITTEN AND IT NOW PASSES.** `§Gate` below carries
the runnable replacement and its measured run (`step1 PASS · step2 PASS · GATE PASS: no
non-excluded legacy write in 14d`). **The old-code-writer question is answered: none is live.**
The card is unblocked; the next box is fixing `keepalive_install.sh:34`.

The rest of this block is the DIAGNOSIS that produced that gate. Read it for the reasoning and the
traps, not for the status — the status is the line above.

*(Historical framing kept because it is the card's most reusable lesson: the ORIGINAL gate could not
pass while the legacy dir existed, and would have answered "wait another release" indefinitely.)*

Wording matters here and an earlier draft of this block got it wrong: the claim is **NOT**
"unsatisfiable by construction". The legacy rung comes from `_legacy_read_path`, which returns
`None` unless the legacy dir **already exists** — so the condition is self-referential to this
card's own scope, and removing the dir removes the writer. That is a materially different
situation from a permanent blocker: this card is potentially SELF-UNBLOCKING.

Measured 2026-08-28 12:42: `daemon.heartbeat.ts` is **0 minutes old in all three eras at once** —
`~/.claude/janitor-control/`, `<DATA>/global-state/`, AND the legacy
`~/.claude/janitor-global-state/`. The legacy dir has a LIVE, CORRECT, INTENTIONAL writer.

**Why, and why it is not a bug:** a LATER card, **TRDD-QK7M2B0X phase B step 2**, moved the daemon
singleton to `control_dir()` and made the new writer **DUAL-WRITE** the older locations, because
that move inverted the skew direction — the writer is NEW and the readers are OLD, so an old
session's `daemon_is_alive()` would read only its own era, find nothing, conclude DEAD, and
spawn-churn against a lock it can never take. `_singleton_paths()`
(`scripts/lib/global_state.py:562-590`) therefore enumerates a **legacy** rung and is used for
reading, writing AND locking — one list, deliberately not three.

**VERIFIED AGAINST THE CODE THAT ACTUALLY RUNS, not the source tree.** The daemon executes from
the plugin CACHE, so a source read proves nothing about it. Interrogated
`~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/3.3.26` directly:
`_legacy_read_path('daemon.heartbeat.ts')` → the legacy path, and `_singleton_paths` emits all
three rungs (`control`, `global-state`, `legacy`). So the dual-write is the writer, established
rather than inferred from a coincidence of mtimes. (Interrogating the cache creates a `.venv`
inside it — remove it afterwards; a stray dir in a cached plugin is exactly what
`janitor-self-integrity` is built to notice.)

**So the gate's inference broke.** It reads "a legacy file newer than the marker" as PROOF that an
old-code writer is still active. That proxy was sound when written and false the moment QK7M2B0X
shipped: the predicate now also matches new code doing exactly its job, every heartbeat, forever.
The gate does not measure what it claims to measure. It is the same failure shape this card's own
"Verification lesson" warns about — one step further out.

**Snapshot 2026-08-28:** 178 legacy files, 19 newer than the marker
(`<DATA>/global-state/migrated-from-legacy.ts`, mtime 2026-07-08 20:48:27, content `1783536507`).
Of the 19: sixteen are the known Jul-9 pre-rollforward batch, and **three are live** —
`daemon.pid` (2026-08-23, matches all eras byte-for-byte in mtime), `daemon.heartbeat.ts` (now),
`daemon-keepalive.err.log` (2026-08-25). Stop-class flags in legacy: **none**
(`kill-switch.flag` / `global-pause.flag` / `maintenance-mode.flag` all absent), so the original
step-2 safety check still passes and dropping the dual-read would not silently re-arm the fleet.

**NEXT ACTION — box 2: fix `keepalive_install.sh:34`** (both `install_macos` and `install_linux`),
regenerate the plist, then delete the four `daemon-keepalive.*` names from the gate's `EXCLUDE`.
Step 0 is complete; see `§Gate`.

**Step 0's own history, kept because each wrong turn is a trap for the next reader.** Draft 1 of the
replacement excluded only the three QK7M2B0X singleton names and still compared against the marker
— it FAILED with 17 files. Draft 2 kept the marker comparison and added the keepalive names — it
FAILED with 14, newest 2026-07-09 09:12, **fifty days stale**. Both were written onto this card as
"PASS" before being run.

**The fix was changing the QUESTION, not the exclusion list.** "Newer than the migration marker"
tests a permanent historical fact — anything written after 2026-07-08 20:48 stays newer forever, so
on any host whose daemon was running the next day the predicate can never clear. "Is an old writer
ACTIVE" is a RECENCY question, and only a quiet-window test asks it. That is the same defect as the
original gate, reproduced twice inside its own replacement: **when a check cannot pass, look at what
it asks before you tune what it excludes.**

**SECOND LIVE LEGACY WRITER, and this one IS a real bug — the same class as the 7ceab3f keychain
latch.** `daemon-keepalive.err.log` (2026-08-25) lands in the legacy dir because
`scripts/keepalive_install.sh:34` **hardcodes** `LOG_DIR="$HOME/.claude/janitor-global-state"`,
and that string is baked into the launchd plist as the stdout/stderr capture target. Its own
adjacent comment states the intent — *"The daemon pins its own log dir to the global-state dir
(daemon.py setdefault); point launchd's stdout/stderr capture at the same"* — and that premise is
now STALE: `global_state_dir()` resolves to `<DATA>/global-state/`, so the two no longer point at
the same place. Self-consistent, nothing visibly broken, which is exactly why it survived — the
identical signature as the latch bug this card already caught once.

**STALE-BY-OMISSION, established by dates — not "a deliberate literal aimed at the wrong dir".**
The alternative reading is tempting and was raised in review: `control_dir()` is literal BY DESIGN
(QK7M2B0X ATOM-QK7M-0001 — never publish a cross-process contract on a ladder-resolved path, and
launchd is the canonical foreign reader that can only hardcode one rung), so a hardcoded literal in
a plist generator could be that pattern correctly applied and merely pointed at the wrong dir. The
git record rules it out:

| event | commit | date |
|---|---|---|
| `LOG_DIR` literal introduced | `0c8929d5` (TRDD-71ABD7V7 phase 2b) | **2026-06-24** |
| 2U8AH82F migration lands | `ba58ebbb` | **2026-07-07** |
| `~/.claude/janitor-control/` first appears in `global_state.py` | `9116b22b` (TRDD-QK7M2B0X) | **2026-07-21** |

Every row is a commit date. (A first pass left the third row unmeasured, carrying QK7M2B0X's
frontmatter `created:` — the date a CARD was written, not when code landed — formatted beside two
rows that did have hashes. **The search that came back empty was the wrong search:**
`git log --diff-filter=A -S "def control_dir"` filters for commits that ADD THE FILE, and
`global_state.py` already existed, so it can only ever return nothing. Drop `--diff-filter=A` and
`-S` answers immediately. An empty result from a malformed query is not evidence of absence.)

**`LOG_DIR`'s VALUE was written once and never rewritten** — which is what the stale-by-omission
argument actually needs, since a rewrite dated after 2026-07-07 would revive the deliberate-literal
hypothesis with a later commit behind it. Established by scanning every revision of the line:

```bash
git log --follow -M -p --date=short -- scripts/keepalive_install.sh | grep -E '^[+-].*LOG_DIR='
# → exactly one line, ever:  +LOG_DIR="$HOME/.claude/janitor-global-state"   (0c8929d5, 2026-06-24)
```

Eight commits in HEAD's ancestry have touched that file (through 2026-08-16) — `--follow` walks
the checked-out branch, so read that as "the history reachable from HEAD", not "every commit that
ever touched the path". None added or removed a `LOG_DIR=` line after the first.

**And the line is still there, live and CLEAN — verified in the working tree, not in history.**
`grep -n LOG_DIR scripts/keepalive_install.sh` → `34:LOG_DIR="$HOME/.claude/janitor-global-state"`,
with `git status --porcelain` on that path returning empty. This repo carries ~82 uncommitted
paths, so an uncommitted repoint would have been invisible to every `git log` above while making
this card instruct the next session to fix something already fixed. History is a proxy for the
working tree; the instruction acts on the working tree.

**THE INSTALLER ITSELF RECREATES THE DIR — this supersedes the launchd speculation above.** The
same read settles the resurrection question outright, with no appeal to launchd internals:

```
 34:  LOG_DIR="$HOME/.claude/janitor-global-state"
221:  mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"      # macOS path
248:  <key>StandardOutPath</key><string>$LOG_DIR/daemon-keepalive.out.log</string>
249:  <key>StandardErrorPath</key><string>$LOG_DIR/daemon-keepalive.err.log</string>
269:  mkdir -p "$UNIT_DIR" "$LOG_DIR"                        # Linux/systemd path
```

Two things follow, both measured rather than reasoned. First, the plist is **generated from** this
variable — lines 248-249 interpolate `$LOG_DIR` into the heredoc — so the earlier finding no longer
rests on the plist and the script merely naming the same string. Second, the installer runs
`mkdir -p "$LOG_DIR"` on **both** platform paths (`install_macos()` at 221, `install_linux()` at
269, dispatched by a `case` on `detect_platform` under the `install` verb).

**AND THE INSTALLER RUNS AUTOMATICALLY — traced to the call site, because "the file contains a
mkdir" is not the same claim as "that mkdir fires".** The chain:

```
daemon.py:2700-2709  (every daemon startup, singleton-only, after the flock is held)
  ka.opted_in()                      → gate       [MEASURED on this host: True]
  ka.restage(src)                    → always; refreshes the DATA closure (no mkdir of LOG_DIR)
  if not ka.is_installed():                       [MEASURED on this host: True → activate() does
      ka.activate()                  →             NOT fire right now]
          bash <staged>/keepalive_install.sh install
              → mkdir -p "$LOG_DIR"   ← recreates the legacy dir
```

**Evaluate the gates, do not just note that they exist** — a gate's presence in code says nothing
about its runtime value, and the whole chain below `opted_in()` is dead code if it returns False.
Measured against the CACHED 3.3.26 plugin (`opted_in() = True`, `is_installed() = True`), so the
chain is LIVE on this host and merely not firing at this moment. `opted_in()` is default-**ON**
(`CLAUDE_PLUGIN_OPTION_DAEMON_OS_KEEPALIVE` defaults `"1"`), so assume it is True on any host
unless someone explicitly set it — it is not an opt-in in practice.

So the trigger is **automatic on daemon startup, gated on the OS service not being LOADED** — not
"only on a manual reinstall". Two consequences worth keeping straight, because they are different
failure modes:

- Removing the legacy DIR alone does **not** trigger a reinstall. The dir stays gone while the
  service stays loaded.
- **But `is_installed()` is weaker than "the plist exists", and that widens the risk.** Read its
  body rather than its name: it shells out to `keepalive_install.sh status` and reports whether the
  job is **LOADED/ACTIVE with the service manager** — explicitly *not* whether the definition file
  is on disk (its docstring cites janitor#217: an operator-driven unload leaves the file in place
  while unloading the job). So a plain `launchctl unload` flips `is_installed()` to False with the
  plist still present, and the next daemon startup calls `activate()` and recreates the dir. An
  earlier draft said this hinges on "a removed plist"; it does not, and the file-present case is
  the one to plan for. **This rests on the `is_installed()` body, which is sufficient on its own —
  it needs no host anecdote.**

  **Still do NOT cite `…daemon.plist.DISABLED-flood-20260715` as an instance of it** — but for the
  right reason. The name does not end in `.plist`, so it is a file RENAMED out of the loadable
  namespace, which is a different mechanism from an unload with the definition intact. That is
  what disqualifies it as evidence for THIS path; it is not disqualified for lacking a history.

  **July flood history EXISTS but does NOT tie to this file — and note that both of the previous
  two drafts of this paragraph were wrong, in opposite directions.** Draft A said the incident was
  "nowhere in the repo": a null result from `git log --grep`, which matches commit MESSAGES and
  cannot see file contents, while this repo records incidents in TRDD bodies and wikimem pages.
  Draft B over-corrected to "the artifact's name is grounded in a real incident". Searching the
  right corpora (`grep -rn -i flood design/tasks/ design/archived/ .claude/project/memory/
  <LOCAL memory>` — **35 files**) shows why neither holds:

  - **`TRDD-K3WQ7XM9`** (2026-07-09, `…-daemon-keepalive-crashloop-repair.md`) — a daemon-keepalive
    crashloop with a **keychain** flood, fixed in v0.35.1.
  - **`TRDD-P7WU40G9`** — the *"2026-07-18 disaster"* (`X07E7HTN:47`), a `/janitor-arm` command
    flood.
  - **`TRDD-28XF77X6`** (2026-07-17, `:100`) — lists "the keepalive items (test-isolation leak,
    **flood breaker**)" as DEFERRED, awaiting a USER call. A breaker contemplated is not a flood
    recorded.
  - **`TRDD-DB1P25S4`** (2026-08-05, `:175`) — uses **"July-flood shape"** as shorthand for a prior
    incident: a launchd entry that *"could not re-take the held singleton … and launchd had already
    dropped it (`No such process` on bootout)"*.

  **`"July-flood"` occurs EXACTLY ONCE in the whole corpus — that DB1P25S4 line — and is never
  defined or dated anywhere.** So there are at least three distinct July flood events, **none of
  them dated 2026-07-15**. Reading DB1P25S4's undated shorthand as *this* file's incident means
  supplying the date from the very filename you are trying to explain — circular. The artifact
  remains untied to any documented incident, and the same goes for the two
  `.bak-pre-signed-python-…` siblings.

  **THE FILENAME'S DATE IS WRONG — `stat` the file instead of reading its name.** Every draft above
  chased 2026-07-**15** because the filename says `flood-20260715`. The filesystem says otherwise:

  | file | real birth / mtime |
  |---|---|
  | `…daemon.plist.DISABLED-flood-20260715` | **2026-07-09 12:35:40** |
  | `…daemon.plist.bak-pre-signed-python-20260805` | 2026-08-05 10:06:15 |
  | `…daemon.plist.bak-pre-signed-python-20260816_105336` | 2026-08-16 10:53:16 |
  | `…daemon.plist` (live) | 2026-08-16 10:53:36 |

  The two `.bak` names match their own timestamps to the second; the `DISABLED` one is **six days
  off**. So the 2026-07-15 hunt was chasing a label, and `TRDD-EQJPPZ2L` (2026-07-15) is NOT this
  file's incident — its only launchd action that day was removing a THIRD-PARTY agent
  (`com.cookiemonster.usage`, `:196-197`), which refutes the identification independently.

  **2026-07-09 has its own dedicated card, and it fits exactly: `TRDD-K3WQ7XM9`**
  (`…-daemon-keepalive-crashloop-repair.md`, dated 2026-07-09) — a **daemon-keepalive crashloop**
  with a flood, fixed in v0.35.1. A keepalive job disabled by rename during a keepalive crashloop
  repair, on the day that card was written. Read K3WQ7XM9, not EQJPPZ2L.

  **Did the recreation mechanism already fire here? NOT ESTABLISHED — and the reason is worth
  keeping, because the first answer written here was "demonstrably yes".** The live plist was born
  **2026-08-16 10:53:36**, twenty seconds after the `.bak` at 10:53:16. The tempting three-step
  inference is *plist rewritten → `keepalive_install.sh install` ran → `mkdir -p "$LOG_DIR"`
  executed*, and only the FIRST link is measured.

  For it: `plist_bake_interpreter "$PLIST"` is called at **`keepalive_install.sh:256`, inside
  `install_macos()`** (220-**266**), whose FIRST statement is the `mkdir -p … "$LOG_DIR"` at 221.
  The live job's baked absolute interpreter (`launchctl print` →
  `program = /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12`) is exactly what
  that helper produces.

  **The bake ⟹ mkdir implication is sound BY POSITION, and needs no facts about the interior.**
  The mkdir is the function's FIRST statement, so entering `install_macos()` executes it; any
  guard, early return or failure later can only prevent the BAKE, never retroactively un-create the
  directory (`set -e` included). Observing a baked plist therefore implies control passed 221. The
  open question is only whether the SCRIPT baked it — not whether the mkdir would have followed.

  *(Lines 222-255 are in fact comments plus a single `cat > … <<EOF` heredoc, verified by READING
  them. A first pass instead ran a hand-written grep for `mkdir|return|exit|if |fi$|else|…` and
  reported "no branches" — but that pattern is not a branch detector: it cannot see `[ … ] && cmd`,
  `case`, `||` chains, loops, `trap`, or a `die` helper. Proof it was blind: the one branch it DID
  surface, `[ -n "${KEEPALIVE_SKIP_ACTIVATION:-}" ] && return 0` at 259, matched only incidentally
  via `return` and a variable name already in the pattern — no branch construct matched anything.
  A silent grep over 35 lines that a single Read covers is a malformed instrument's null result
  read as absence, the same shape as the `--diff-filter=A` error above. The conclusion here does
  not depend on it, which is exactly why it would have gone unchecked.)*

  Against it: **`bak-pre-signed-python` appears NOWHERE in the repo's code** — only in TRDD prose
  (`grep -rn 'pre-signed-python' --include='*.py' --include='*.sh'` → no hits). No shipped script
  generates that backup name, so a HUMAN was driving on 2026-08-16, mid-way through
  `TRDD-DB1P25S4`'s signed-python migration (`TRDD-EZ3PMQYX:71` notes the 2026-08-05 backup still
  named `/opt/homebrew/bin/uv`). Whether they invoked the `install` verb or hand-edited the plist
  is unrecorded, and a hand-edit reaches the same baked-interpreter end state without ever calling
  `install_macos()`.

  So: the ordering constraint stands on the `is_installed()` body and the traced call chain, both
  measured. It does NOT get to be upgraded to observed history. **A file's existence is not
  evidence of the process that wrote it** — the same substitution as reading a plist file for the
  loaded job, one layer down. Meanwhile the legacy dir has been continuously alive regardless
  (born 2026-06-11 18:23:57; newest file `daemon.heartbeat.ts`, mtime 2026-08-28 13:03:28), so
  nothing here needed recreating in the first place.

  **The durable lesson is the search, not the verdict:** "not in `git log`" is not "not in the
  repo" — commit-message search cannot see file contents, and in this repo the incidents live in
  the files. But finding *adjacent* history is not finding *the* history. This paragraph was
  rewritten THREE times — "nowhere in the repo" (null result from a blind search), "grounded in a
  real incident" (two word-matches), and now this — and each intermediate version read as settled.
  A matching month, a matching word, and even a matching DAY are not an identification.

Meanwhile the launchd-held stderr fd (measured above, PID 8368 FD `2u`) keeps the *file* alive
continuously, independently of any of this.

This supersedes the earlier speculation: whether launchd itself recreates the dir, and whether a
missing parent blocks job spawn, are no longer load-bearing — those were the unmeasured halves,
and the installer chain above replaces them with a traced one.

**Use `-G`, not `-S`, and neither `-L` — the three instruments answer different questions.**
`git log -L 30,40:<file>` pins a FIXED line range against the CURRENT file, so a moved assignment
drifts out of range silently. `git log -S 'LOG_DIR'` is the PICKAXE: it reports commits where the
OCCURRENCE COUNT of the string changed, so it is blind to exactly the edit that matters here — a
commit rewriting `LOG_DIR="…"` to a different value leaves the count at one and never appears.
Both were used in earlier passes of this card and both returned "one commit", which read as
corroboration and was really the same blind spot twice. `-G` (regex match against the diff text)
and a `-p` line scan see content changes; they agree here, and only they could have disagreed.

The literal predates the migration by two weeks and `control_dir()` by a month, so its author
could not have been applying a pattern that did not yet exist. **And the adjacent comment was TRUE
when written** — on 2026-06-24 `global_state_dir()` really did resolve to the legacy dir, so
*"point launchd's capture at the same"* accurately described reality; the migration silently
falsified it two weeks later. That is what makes it the SAME class as the 7ceab3f keychain latch
and not merely similar: a pre-migration hardcode, self-consistent at the time, missed by the
migration, invisible because nothing broke.

**So the fix is "repoint it, the migration missed it" — not a redesign.** Which literal to repoint
at is still a real decision (`control_dir()` per ATOM-QK7M-0001 vs `<DATA>/global-state/`), and a
shell script cannot resolve a Python ladder, so it must be a literal either way.

**CPV-#152 CHECKED — it does NOT block repointing `LOG_DIR`.** Worth recording, because the fix
edits a value that lands inside a heredoc a validator scans, and the authors deliberately routed
an interpreter path *around* that block rather than through it — which looks like a gate until you
read what it governs. Two separate constraints live there, and neither touches this:

- **The invariant is scoped to the PROGRAM token — confirmed in CPV'S OWN SOURCE, not in our
  comments about it, and checked at BOTH the version I first opened and the newest installed.**
  `_plist_program()` (`<cpv>/scripts/cpv_persistence_target.py:319-330`) returns
  `ProgramArguments[0]` or `Program` and nothing else — **identical in 5.9.0 and 5.12.0**. CPV does
  read one other plist key, `EnvironmentVariables` (`_plist_extra_sources`, a code-injection
  check), so the accurate claim is not "CPV ignores other keys" but: **`StandardOutPath` /
  `StandardErrorPath` appear NOWHERE in CPV's entire tree** — a full-tree
  `grep -rI` over every file type (`scripts/ skills/ agents/ commands/ templates/ references/ …`)
  returns **0 files** at 5.9.0 AND at 5.12.0.
  *(Why go to the source: `keepalive_install.sh:228`/`:275` and `TRDD-71ABD7V7:63` are the
  SCANNED party's June-dated description of the scanner, not the scanner. Same evidence class as
  reading source for the cached daemon, or a plist file for the loaded job.)*
  **`.cpv-version` IS what G3 resolves — verified in `publish.py`, not assumed from the file's
  name.** `_CPV_VERSION_FILE = … / ".cpv-version"` (`:235`), read by a helper that *"Raises rather
  than guess a default"* (`:239`), interpolated as
  `_CPV_SPEC = f"git+…/claude-plugins-validation@{_CPV_PIN}"` (`:261`). **And `_CPV_SPEC` is
  actually PASSED at both invocation sites** — read the argv construction, not the argv fragment:

  ```python
  ["uvx", "--from", _CPV_SPEC, "--with", "pyyaml",
   "cpv-remote-validate", "plugin", ".", "--strict"]
  ```

  **Cite the FUNCTION, not the line — there are TWO such sites and they are different code paths:**

  | site | enclosing function | dispatched from — the CALLER, which is what defines the path |
  |---|---|---|
  | ~1181-1185 | **`run_gate()`** (def @889) | `:2806` `if args.gate: return run_gate(root)` — *"--gate mode: run quality checks only (called by pre-push hook)"*. Own `subprocess.run` + exit-code table, `sys.exit(1)` on 1-4. |
  | ~1429-1434 | **`stage_validate()`** (def @1410) | `:2862`, inside the sequential publish pipeline (`stage_lint → stage_tests → stage_validate → stage_ci_preflight → …`). Delegates to the `run()` helper, prints "Validation passed". |

  **Only `stage_validate` runs during a publish. The pre-push hook does NOT invoke `run_gate`.**
  Read `.githooks/pre-push` whole (69 lines): it walks the ancestor process tree for a
  `*python*scripts/publish.py*` invocation, and that is ALL it does — no ancestor ⇒ print a refusal
  and `exit 1`; ancestor found ⇒ bare `exit 0`. It runs no lint, no tests, no CPV.

  **That file IS the hook git executes** — `git config --get core.hooksPath` → `.githooks`, mode
  `-rwxr-xr-x`, and no `.git/hooks/pre-push` shadowing it.

  **BUT IT IS THE STALE ONE, AND THAT MAKES THE ABOVE A DRIFT, NOT A DESIGN — filed as
  `TRDD-I8AE6C8D`.** Its `Apr 24` mtime did not fit a header claiming "every publish.py run
  rewrites this file" across ~48 tags, and chasing that discrepancy found **two tracked,
  executable hooks**: `.githooks/pre-push` (2832 B, Apr 24 — the ACTIVE one, no gate) and
  `git-hooks/pre-push` (3847 B, Jul 25, commit `60e1b6be` "land the v3.11.0 canonical-pipeline
  migration"), which DOES run `uv run python scripts/publish.py --gate`. `install_hook()`
  (`publish.py:724-744`) reads `git-hooks/pre-push` and sets `core.hooksPath=git-hooks` — so the
  live config names the superseded directory. So "the pre-push hook runs no CPV" is true of what
  executes today and FALSE of what the pipeline intends. Filed separately; it does not change this
  card's clearance (both CPV sites pass `_CPV_SPEC` regardless of which hook runs).

  *(A draft of this table asserted "both run during a publish, because the push at the end fires
  the pre-push hook". Wrong, and instructively so: the hook's own REFUSAL MESSAGE says every push
  must go through `publish.py` "so that lint, tests, and CPV --strict are re-verified immediately
  before the push" — that describes what **publish.py** does, not what the hook does. CLAUDE.md
  carries the same compressed phrasing ("a pre-push hook enforces this … it re-runs lint, tests and
  CPV --strict"), which is what I had internalised. An error message describing a policy is not an
  implementation of that policy. Every other row in this table came from a caller I read; this one
  was two believed facts joined by an unverified edge, and it inherited its neighbours'
  credibility.)*

  **Consequence, small but worth stating:** `stage_validate` alone carries CPV validation on the
  publish path. `run_gate` runs only when something invokes `publish.py --gate` explicitly — and
  **what does so was NOT established here** (not the hook; possibly CI or a manual call). Both
  still pass `_CPV_SPEC`, so the version clearance is unaffected either way.

  `:1472` is a third site, `ci-preflight`, in the stage-4b path. An uncapped
  `grep -n cpv-remote-validate scripts/publish.py` finds exactly these three — no others.
  *(An earlier draft cited "`:1432`" as **G3**, sourced from the header at `:57`. A second draft
  "corrected" it using the SAME headers (`:20` vs `:57`) — swapping one comment-derived
  attribution for another, in the very edit that named comment-sourced attribution as the
  unreliable class. The callers above are what actually settle it, and they are facts about code:
  `run_gate` IS the pre-push gate because `args.gate` dispatches to it; `stage_validate` IS a
  pipeline stage because the pipeline calls it in sequence. `"G3"` appears nowhere in either
  function's body — only in the header listing. **Both pass the same `_CPV_SPEC`, so the VERSION
  clearance was never affected**; only the citation was. Cite the FUNCTION and its CALLER: names
  survive edits that shift line numbers, and landing in the wrong caller is how a gate gets edited
  into a no-op.)*

  So the pin file → spec → both invocation paths chain is closed, with no floating ref and no
  silent default. *(A grep matching only `"cpv-remote-validate", "plugin", ".", "--strict"` CANNOT
  tell this apart from a bare PATH-resolved `cpv-remote-validate` — the distinguishing
  `uvx --from _CPV_SPEC` tokens sit on the lines ABOVE the match. That mattered: a PATH resolution
  would have run one of the CACHED 5.7.1-5.12.0, none of which is the pinned v5.4.0, making the
  whole tag fetch measure the wrong tree. A variable's definition is not evidence of its use.)*

  **NOT investigated, and out of scope for this card — but worth a look by whoever touches
  `publish.py`:** `stage_validate` delegates to a `run()` helper that was never read. If that
  helper does not raise on a non-zero exit, that path would print "Validation passed" regardless
  of what CPV reported. `run_gate` handles its own exit codes explicitly and does not have this
  question. This is a claim about whether a gate BLOCKS, not about which version it runs, so it
  does not touch the clearance above. *(This was the last assumed link: "the pin from
  `.cpv-version`" had been MY gloss on the invocation shape, never read out of `publish.py` — a
  config file's contents standing in for the command that consumes it.)*

  **THE PINNED TAG THE GATE ACTUALLY RUNS WAS READ TOO — `v5.4.0`, and it is identical.**
  `.cpv-version` pins `v5.4.0`, which is NOT in the plugin cache, so reading 5.9.0/5.12.0 measured
  versions the publish gate never invokes. Fetched the tag directly
  (`git clone --depth 1 --branch v5.4.0 https://github.com/Emasoft/claude-plugins-validation`,
  tag → commit `189f87c9`): `_plist_program` at `cpv_persistence_target.py:319` reads
  `ProgramArguments` then `Program`, nothing else, and `Standard*Path` appears in **0 files** in
  that tree. So the clearance is now measured at the version that gates the publish, not inferred.

  *(An earlier draft justified skipping this with "checks accrete, so an older 5.4.0 is unlikely to
  have such a check". That is a claim about how software evolves, not a reading of the tag — and
  the pin, the repo URL and the fetch invocation were all already in hand. The asymmetry is what
  made it worth one call: a wrong clearance here surfaces at `publish.py` G3, the one gate this
  repo cannot absorb a surprise at — see TRDD-X4LJFTB4.)*

  *(**Pick a version with `sort -V`, never `ls | tail -1`.** That idiom sorts LEXICALLY, so it
  returns 5.9.0 whenever 5.12.0 is also present — `9` beats `1` at the second component. It
  silently selected a mid-range validator on the first pass here. Cache holds 5.7.1, 5.8.0, 5.9.0,
  5.10.0, 5.11.0, 5.12.0 — and note that NONE of them is the pinned `v5.4.0`: "newest installed"
  and "what the gate runs" are different questions.)*
- **The extractor keys on the heredoc OPENER, not the body's values.** Per `TRDD-71ABD7V7:63`,
  `_extract_heredoc_body(full_content, ".plist")` requires the opener line to contain the literal
  `.plist`, which is why `:233` hard-codes the full literal path instead of a shell variable, and
  why `:222-226` warns against putting a heredoc-opener shape in a nearby comment.

**And the decisive point makes CPV's rules IRRELEVANT here, whichever version runs — so the
version skew above does not gate the fix: `LOG_DIR` is assigned at `:34`, OUTSIDE the heredoc.** The scanned body
contains the unexpanded token `$LOG_DIR` (the delimiter is unquoted, so the SHELL expands it when
writing the runtime file, while CPV scans the literal text). Repointing the variable therefore
leaves the scanned body byte-identical — there is nothing for the validator to notice. Do NOT
"work around" CPV here by adopting the `plist_bake_interpreter` prepend-afterward pattern: that
exists for `ProgramArguments[0]`, which genuinely is constrained, and copying it for a value that
is not would add a second writer to the runtime file for no reason.

Fixing it is a one-line source change, but NOT a free one and deliberately not done here: the
live plist only regenerates on reinstall, so source and installed wiring would disagree until
then, and the target dir's existence at launchd-start time has not been verified. Note also that
the fix is **two** sites, not one — `install_macos()` and `install_linux()` both `mkdir -p
"$LOG_DIR"`, and the Linux twin carries the same CPV invariant at `:275`. Scope it as its own
derived task with that verification in it.

**THERE IS NO BLOCKER. The retirement is OVERDUE, and that is the actual finding.**

Two earlier drafts of this block got this wrong in opposite directions, both by naming a
dependency instead of reading one — recorded because the next reader will be tempted by the same
shortcut. Draft 1: "downstream of QK7M2B0X's transition window closing" (a card never read).
Draft 2: "CO-SCHEDULED — treating ULEGRT01 as waiting on QK7M2B0X would deadlock both" (built on
step 5 read out of a grep window; the deadlock was constructed, not observed).

What QK7M2B0X actually says, read whole:

- **Step 5's "the transitional fallback" is the FLAG dual-read of step 3**, not the singleton
  rung. Step 3 is explicitly flags — *"each presence check falls back to the old
  `global_state_dir()/<name>` … Writers write ONLY the new path."* The singleton is the opposite
  shape (dual-**WRITE**) and arrived later, in phase B step 2 (2026-08-02), from advisor item 1.
  Two different objects; one clause does not govern both.
- **But both are on the same clock anyway.** The card's own NEXT ACTION says *"the transitional
  fallback**s** retire two releases out (step 5)"* — plural — and advisor item 6 independently
  gives the singleton the same referent: *"'retirement' is a code event two releases out, not a
  runtime step."* `acquire_singleton_dual` was deliberately not built on `_acquire_dual_flock`
  precisely because *"the singleton must hold new ACROSS retirement of old."*
- **"Two releases out" from 2026-08-02 elapsed long ago: 48 PUBLISHED TAGS since**, measured with
  `git tag --sort=creatordate --format='%(creatordate:short) %(refname:short)' | awk '$1>="2026-08-02"' | grep -v 'ai-maestro-janitor--' | wc -l`
  (window runs v2.3.0 → v3.3.25).
  **Count tags, not bump commits.** A first pass here cited "65 version bumps" from
  `git log --since=… | grep -c "bump version"` — commit SUBJECTS, which is a proxy and an upper
  bound only: it includes every abandoned bump and every re-bump after a failed publish. On THIS
  repo that gap is live and known — TRDD-X4LJFTB4 records the 3.4.0 publish blocked at the push
  gate — so bump commits and published releases demonstrably diverge here. The conclusion happens
  to survive (48 ≫ 2), which is exactly why the wrong measurement would have gone unre-checked.

So nothing is waiting on anything. Both rungs were scheduled for retirement ~65 releases ago and
simply never retired. Scope them together — the 2U8AH82F legacy read-fallback and QK7M2B0X's
legacy rung in `_singleton_paths` — in one pass with the dir removal, so no intermediate state
exists where one half reads a path the other stopped writing. Not because either blocks the other,
but because they touch the same list.

**Self-unblocking holds for ONE writer. A SECOND writer, OUTSIDE that predicate, WILL recreate the
dir — measured, not reasoned.** QK7M2B0X line 50 sources the first half: the legacy rung *"reuses
`_legacy_read_path`'s predicate, so a WRITE can never resurrect the tombstoned legacy dir."* That
governs `_singleton_paths`' own writers and nothing else.

**The LaunchAgent is the second writer, it is RUNNING RIGHT NOW, and it is not subject to any
janitor predicate.** Ask launchd what it is executing — do NOT settle for reading the `.plist`,
which is only a file on disk and may not be the job launchd holds loaded:

```
launchctl print gui/$(id -u)/com.ai-maestro-janitor.daemon
  path        = ~/Library/LaunchAgents/com.ai-maestro-janitor.daemon.plist
  state       = running
  stdout path = ~/.claude/janitor-global-state/daemon-keepalive.out.log
  stderr path = ~/.claude/janitor-global-state/daemon-keepalive.err.log
  properties  = keepalive | runatload | …
```

`state = running` is the TOP-LEVEL job state — read it unfiltered (`… | head -12`), not through a
grep, because nested stanzas further down also carry `state = active` and a substring match cannot
tell them apart. The job's arguments confirm the program:
`daemon_keepalive_entry.py --keepalive`, run from the plugin DATA dir.

**The file handle is held RIGHT NOW — verified, not inferred from `runatload`:**

```
lsof ~/.claude/janitor-global-state/daemon-keepalive.err.log
COMMAND  PID   USER  FD  TYPE  …  NAME
Python  8368   …     2u  REG   …  …/janitor-global-state/daemon-keepalive.err.log
```

**FD 2 = stderr**, held read/write by the live keepalive process. So the writer is not merely
*configured* to use that path — it has the file open as its standard error this instant, which no
janitor-side tombstone predicate can affect. An earlier draft said "launchd holds these open …
`runatload` means they are re-opened every login": the first half was asserting launchd internals
rather than measuring them (`lsof` above is the measurement), and the login-reopen half remains
unmeasured — plausible from the `runatload` property, but do not lean on it.

That also settles the earlier open question properly: launchd holding
`daemon-keepalive.err.log` as the running job's stderr is the measured explanation for it being
fresh (2026-08-25) in a supposedly retired directory. An intermediate draft called the on-disk
plist "definitive" for this — that was filename-matched-to-plist-key, i.e. causation asserted from
a name collision. The `launchctl print` above is the version that actually identifies the writer.

**Why the on-disk read was not enough, recorded because the directory listing invites the mistake:**
`~/Library/LaunchAgents/` also holds `com.ai-maestro-janitor.daemon.plist.DISABLED-flood-20260715`
and two `.bak-pre-signed-python-*` copies (20260805, 20260816) — a live plist beside a disabled
twin and two dated rewrites is exactly the shape where the file read and the job loaded diverge.
(Those three never end in `.plist`, so a `*janitor*.plist` glob silently skips them; "no matching
keys" there means "never inspected", not "has none".)

**Therefore, MEASURED: fix the hardcode and regenerate the plist BEFORE removing the dir.**
Removing it first means the next daemon launch recreates it — a resurrection indistinguishable
from the original problem, which would restore the legacy rung the removal exists to retire.
And note the sharper failure mode: launchd requires the PARENT DIR of a stream target to exist or
the job fails to spawn. Deleting the dir under an unchanged plist risks not merely a resurrected
directory but a **keepalive that will not start**. Verify that claim about launchd's spawn
behaviour before relying on the strong form of it; the path-in-plist fact above is measured, that
consequence is not.

**Two earlier drafts of this paragraph were wrong, in the shape this whole session kept repeating.**
Draft 1 asserted self-unblocking flatly, citing a predicate that covers only the writer it was
written about — while this same session had already found the other writer touching the dir three
days earlier. Draft 2 hedged correctly ("plausibly yes") and then issued a bolded ordering
constraint anyway. A hedge two sentences above a bolded imperative does not survive being read in
a hurry, and a STATE block supersedes the body. The plist was a file on disk the whole time and
one command away.

**Noted, not acted on:** QK7M2B0X is `column: complete` (2026-08-05) while carrying an unretired
step 5 and an unperformed "NEXT ACTION (testing)". Terminal columns are frozen, so it is recorded
here rather than by reopening it — but that is live work no open card owns except this one.

**A third location exists that this card never mentions:** `control_dir()` resolves to
`~/.claude/janitor-control/` — a separate era introduced by QK7M2B0X. The scope section below
still describes a two-era world (legacy → DATA). Re-scope it against three eras before editing
`global_state.py`.

---

### Superseded by the measurement above — do NOT carry forward

The 2026-07-11 STATE block read **"GATE RE-ARMED. Do NOT do the removal in the release that ships
7ceab3f."** That framing is retained below for history but is no longer the operative reason to
wait: 7ceab3f (the keychain-latch fix) has long since published, and the blocker is now the
QK7M2B0X dual-write, not an unpublished latch fix.

## ⏵ Historical STATE — 2026-07-11 (superseded; kept for the verification lesson)

**GATE RE-ARMED. Do NOT do the removal in the release that ships 7ceab3f.**

Checked the gate on 2026-07-11 and it FAILED — for a reason worth keeping:

- Release count: PASSES. `ba58ebb` shipped in v0.32.0; HEAD is past v0.39.0 (7 releases).
- "No legacy file newer than the migration marker": **FAILED.** The legacy dir had been
  written **that same day at 03:34**. The writer was `safe_storage._keychain_latch_path()`,
  which **hardcoded** `~/.claude/janitor-global-state` — TRDD-2U8AH82F migrated global
  state to `<DATA>/global-state/` but MISSED this latch. It was self-consistent (same wrong
  path read and written), so nothing user-visible broke — which is precisely why it went
  unnoticed and would have kept the legacy dir alive, and this gate shut, forever.

**Fixed in 7ceab3f** (the last live legacy writer is gone): the latch now resolves through
`global_state.global_state_dir()`, keeps the legacy path as a READ-ONLY fallback (an old
build's latch must still protect the user), and `clear_keychain_denied()` removes BOTH.

**Why the removal must wait one more release:** 7ceab3f is committed but NOT yet published.
Until it is live, a session/daemon on the older cached code can still WRITE a legacy latch.
Removing the read-fallback in the same release would make the new code blind to a latch the
old code just wrote — re-opening the prompt-flood this whole subsystem exists to prevent.

**NEXT ACTION (re-check the gate AFTER 7ceab3f is published):**
1. Re-run the gate: `<DATA>/global-state/migrated-from-legacy.ts` exists AND no file under
   `~/.claude/janitor-global-state/` has an mtime newer than it. (Snapshot at the time of
   writing: 19 of 180 legacy files were newer, all Jul-9 daemon writes from before the
   daemon rolled forward, plus the Jul-11 latch that 7ceab3f fixes.)
2. Verify no stop-class flag lives in the legacy dir before dropping the dual-read —
   `kill-switch.flag`, `global-pause.flag`, `maintenance-mode.flag`. If one were there and
   the read-fallback went away, the janitor would silently RE-ARM machine-wide. (Checked
   2026-07-11: none present; only `reload-needed.flag`, which is generation-stamped and
   harmless, and the keychain latch.)
3. Then do the scope below.

**Verification lesson:** the gate is not paperwork. It caught a real, silent bug that had
been live for 7 releases. Do not wave it through on the release count alone — actually
stat the legacy dir and find out WHO is still writing to it.

**EHT of TRDD-2U8AH82F** (staged migration to `${CLAUDE_PLUGIN_DATA}/global-state/`,
shipped in ba58ebb). The migration deliberately kept two version-skew crutches that
must be removed once the fleet has rolled forward **two releases** past the
migration release:

## Scope — THREE eras, not two (re-scoped 2026-08-28)

This section was written before `control_dir()` existed and described a two-era world. There are
now three, and **only ERA-1 is being retired here.** Naming them apart is the whole point: ERA-2
is the live store for everything that is not a control flag (daemon pid/logs/locks), so "drop the
old path" applied uniformly would delete a location still in use.

| era | location | resolver | status |
|---|---|---|---|
| **1 — legacy** | `~/.claude/janitor-global-state/` | `_legacy_global_state_dir()` | **RETIRE (this card)** |
| **2 — DATA/XDG** (TRDD-2U8AH82F) | `<DATA>/global-state/`, or `$XDG_STATE_HOME/janitor` | `global_state_dir()` | **KEEP** — still canonical for non-flag state |
| **3 — control plane** (TRDD-QK7M2B0X) | `~/.claude/janitor-control/` | `control_dir()` | canonical for the six MODE flags |

**The READ LADDER is contained to `scripts/lib/global_state.py`. THE LEGACY PATH IS NOT.**
Corrected 2026-08-28, same day, after this section first claimed full containment — that claim
came from grepping four private HELPER NAMES with `--include=*.py`, two proxies stacked: helper
names standing in for the legacy PATH, and `*.py` standing in for all source. The honest measure
is `grep -rn "janitor-global-state"` over the whole tree. It finds **three independent live
touchpoints outside `global_state.py`**, none of which the helper-name grep could ever have
returned:

| file | what it is | why it must retire in the same pass |
|---|---|---|
| `scripts/memgrep/src/write_gate.rs:105-117` | a **second copy of the whole 4-rung ladder**, in Rust, self-described as "a byte-for-byte clone of `global_state_dir()`" | dropping rung 4 in Python leaves Rust still resolving to legacy — the two languages disagree about where state lives, silently |
| `scripts/oauth_rotator/safe_storage.py:175` (`_legacy_keychain_latch_path`) | a READ-ONLY compatibility path consumed by `keychain_denied_latched()` | a latch written by an older build still protects the user from keychain prompt-flooding; retiring it early re-opens `macos-keychain`'s incident |
| `scripts/lib/keepalive_boot.py:87` (`_state_dir` fallback) | returns legacy when the `global_state` import fails | **fallback BACKWARD** — the identical shape just removed from `keepalive_install.sh`; it must fall forward to the DATA dir |

**Method, because the first two attempts at this measurement were both wrong.** The number above
comes from a FILTERLESS per-file count —
`grep -rIn "janitor-global-state" --exclude-dir=.git --exclude-dir=target --exclude-dir=.venv
--exclude-dir=node_modules . | awk -F: '{print $1}' | sort | uniq -c | sort -rn` — which drops
nothing and forces every file to be triaged by name. The two earlier attempts each substituted a
proxy for that: first the private helper NAMES for the literal path, then a hardcoded
four-directory allowlist (`^(scripts|hooks|commands|agents)/`) for "all code". The allowlist is
blind BY CONSTRUCTION to any directory not named in it — including `rules/`, which step 5 below
already claims as required scope. **Do not re-derive this list with a filter chain.**

The remaining `scripts/` hits — `daemon.py`, `version_update_lib.py`, `pre-tool-pkg-guard.py`,
and `keepalive_install.sh`'s own new comment — really are inert prose (docstrings and comments).
But "everything else is prose" was ALSO too generous: `.claude-plugin/plugin.json`'s option
descriptions and the `rules/` INERT-guard probes are **operative text an agent or a user acts
on**, not decoration. They are step-5 work and they are enumerated there by measurement, not by
recollection.

1. **ERA-1 reads (the retirement proper).** Remove `_legacy_global_state_dir()`,
   `_legacy_read_path()`, and the legacy element of every tuple that sweeps all three:
   `_flag_present_dual`, the clear sweep, `read_flag_provenance`, `last_run_ts`'s max-scan,
   `_generation_from_flag`, and `_singleton_paths`' legacy rung.
2. **ERA-1 in the ladder.** `global_state_dir()` drops rung 4 — resolution becomes env → XDG →
   DATA dir unconditionally. Keep `migrate_global_state_to_data_dir()` one more release as a
   no-op guard, then delete it and its `daemon.main` call site together.
3. **ERA-2's CONTROL-FLAG fallback (`_old_global_state_path`) retires WITH era 1, in one pass** —
   it is a QK7M2B0X transition-window read, not part of era 2's live role, and it appears in the
   same six tuples as the legacy rung. Splitting the two passes means touching those six sites
   twice. **This retires the flag fallback only; `global_state_dir()` itself stays.**
3b. **The three NON-`global_state.py` touchpoints in the table above, in the SAME pass as 1+3** —
   `write_gate.rs` (drop rung 4 from the Rust clone, keeping the two ladders byte-identical),
   `safe_storage.py::_legacy_keychain_latch_path` (delete the read-only latch fallback), and
   `keepalive_boot.py::_state_dir` (fall forward to the DATA dir, never back to legacy).
   Retiring the Python ladder without these leaves a Rust write-gate and a keychain latch
   pointing into a directory step 4 is about to tell the user to delete.
4. The legacy DIR itself: per RULE 0 never auto-delete — surface a one-time drift line suggesting
   the user remove `~/.claude/janitor-global-state/` (its README-MOVED.txt explains), or fold it
   into `/janitor-audit`. Nothing may recreate it first — see the `keepalive_install.sh` box.
5. Update: **two `.claude-plugin/plugin.json` OPTION DESCRIPTIONS** (lines ~309 and ~694 — user-
   facing text naming the legacy path, easy to miss because they are JSON strings, not prose
   files), README `<global-state>` note, CLAUDE.md state-locations bullet,
   `rules/janitor-footprint.md`'s legacy row, **the DISARMED dual-path probe in TEN files, not
   four** — `rules/{commit-discipline,janitor-footprint,prrd-design-rules,markdown-memory-recall,
   trdd-design-tasks,universal-kanban,use-safe-delete}.md` plus
   `rules/references/{markdown-memory-recall,prrd-design-rules,trdd-design-tasks}-full.md` (drop
   the legacy OR-branch; the "4" here was a remembered number, corrected 2026-08-28 by counting) —
   and the wikimem pages `janitor-architecture`, `janitor-keepalive-test-isolation-fsevents`,
   `oauth-rotation-renew-reauth`, `project_janitor_cc_changelog_currency` (correction protocol —
   demote the fallback fact to a dated lesson, never delete it).
6. Tests: drop the dual-read tests in `tests/test_global_state_migration.py`; keep the ladder +
   handover tests for the historical migration path until the function itself is deleted.

## Gate (do NOT start before)

**REWRITTEN 2026-08-28 (step 0 of the STATE block).** The original is preserved below because its
failure is the card's most reusable lesson.

The gate asks ONE question: **is any OLD-CODE writer still writing to the legacy dir?** Two writers
touch it that are NOT old code, so both must be excluded before the mtime test means anything:

```bash
DATA="$HOME/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins"
M="$DATA/global-state/migrated-from-legacy.ts"
L="$HOME/.claude/janitor-global-state"

# 1. The migration marker must exist.
[ -f "$M" ] || { echo "GATE FAIL: no migration marker"; exit 1; }

# 2. No stop-class flag may live in legacy — dropping the dual-read with one
#    present would silently RE-ARM the fleet machine-wide.
for f in kill-switch.flag global-pause.flag maintenance-mode.flag; do
  [ -e "$L/$f" ] && { echo "GATE FAIL: stop-class flag in legacy: $f"; exit 1; }
done

# 3. Is an old-code writer still ACTIVE? That is a RECENCY question, not a
#    marker comparison — see the note below on why. Excluding the two
#    known-current writers:
#      - QK7M2B0X's deliberate singleton dual-write (daemon.pid/heartbeat/flock)
#      - the keepalive logs, until keepalive_install.sh:34 is repointed (box 2)
uv run python - <<'PY'
import pathlib, datetime, time
L = pathlib.Path.home() / ".claude/janitor-global-state"
EXCLUDE = {"daemon.pid", "daemon.heartbeat.ts", "daemon.flock",
           "daemon-keepalive.err.log", "daemon-keepalive.out.log",
           "daemon-keepalive.boot.log", "daemon-keepalive.restage-stamp"}
QUIET_DAYS = 14          # see "why 14" below — derived, not picked
cut = time.time() - QUIET_DAYS * 86400
bad = [p for p in L.rglob("*")
       if p.is_file() and p.stat().st_mtime > cut and p.name not in EXCLUDE]
for p in sorted(bad, key=lambda q: q.stat().st_mtime):
    print(f"  {datetime.datetime.fromtimestamp(p.stat().st_mtime):%Y-%m-%d %H:%M}  {p.name}")
print(f"GATE PASS: no non-excluded legacy write in {QUIET_DAYS}d" if not bad
      else f"GATE FAIL: {len(bad)} recent legacy writes — an old writer is LIVE")
PY
```

**Why 14 days — the window IS the definition of "active", so it must be derived, not chosen.**
A legacy-era writer is a process still executing PRE-MIGRATION code. Such a process is killed by
`global_state.daemon_needs_restart()` (`:2185`) on the next **local cache** version change — that
function exists precisely to close "the OLD daemon process is still running its OLD daemon.py from
the old cache". So the window must exceed the interval at which THIS HOST's cache rolls forward.

**The quantity is REPLACEMENT LATENCY — how long a pre-migration process keeps running once a newer
version exists. Not the gap between daemon spawns.** Measure it by pairing cache-dir birth times
against the next entry in `<DATA>/global-state/daemon.spawn-history` (a 20-entry ring,
`_SPAWN_HISTORY_KEEP = 20`, spanning 2026-08-15 23:14 → 2026-08-23 19:00):

| version lands in cache | next daemon spawn | latency |
|---|---|---|
| 3.3.22 — 2026-08-20 20:08 | 2026-08-20 20:09 | **+1 min** |
| 3.3.25 — 2026-08-20 23:33 | 2026-08-20 23:38 | **+5 min** |
| 3.3.26 — 2026-08-28 06:40 | **none yet** | **≥7 h, OPEN** |

**Causal arrow — CHECKED, because the pairing is reversible.** A cache dir born a minute before a
spawn is equally consistent with the RESPAWN creating it: `keepalive_boot.verify_or_restage` and
`_keepalive_self_heal` fetch the newest cache *during* startup, so the dir could be an artifact of
the restart rather than its trigger. Resolved by content, not timestamps: the DATA-staged
`scripts/daemon.py` is byte-identical to **3.3.26**'s and differs from 3.3.22's and 3.3.25's
(`cmp -s`), so a restage to 3.3.26 HAS occurred — while the newest spawn remains 2026-08-23, before
3.3.26 existed. **Restage happened; respawn did not.** That is `_keepalive_self_heal`'s documented
shape (restage, then exit so launchd respawns onto the fresh code) stopping half-done.

*(Do NOT date the staging from the staged file's mtime — it reads 2026-08-23 19:00:34, five days
BEFORE 3.3.26's cache dir was born, because the restage copy preserves source mtimes. Content
comparison is the only reliable version probe here.)*

When it works it is MINUTES, which is why 14 days is ample. **But the current one is unresolved:**
3.3.26 landed at 06:40 today and the ring's newest spawn is still 2026-08-23 19:00 (matching
`daemon.pid`'s mtime), so the running daemon is executing PRE-3.3.26 code seven hours later. That is
literally the case `daemon_needs_restart()` exists to close, not firing. **Worth its own look —
recorded here, not chased, because it does not change this gate's verdict** (the stale writer that
matters is pre-*migration*, not pre-3.3.26).

*(A first pass used the gaps BETWEEN spawns — maxima 1.04d, 1.05d, 2.69d — and concluded "14 is ~5×".
**That measures the opposite quantity.** A 2.69d gap means the daemon ran 2.69 days *without needing
a respawn*: the healthy steady state, a lower bound on uptime, not an upper bound on staleness
latency. A daemon that never goes stale never respawns and would show an arbitrarily large gap,
which that metric would misread as "slow replacement". The tell was my own caveat — I wrote that
5 days without a restart was a risk, when under the correct reading it is just a healthy daemon on a
current version. **A metric that makes the healthy case look alarming is measuring the wrong
thing.**)*

*(A first pass derived this from the three cached version DIRECTORIES — 3.3.22, 3.3.25, 3.3.26,
gaps 0.1d and 7.3d — and argued those were an "upper bound" because `cache-prune` purges
intermediate versions. **That was backwards in the half that mattered.** Pruning cuts BOTH tails:
it can hide an intermediate install (shortening the true gap, as claimed) but it has also removed
everything before 3.3.22, so the interval preceding the sample is unmeasured and could be anything.
Three survivors with both ends cut bound nothing, and at a 2× margin an unrepresentative sample is
not slack. The spawn ring has no such selection problem.)*

**Corroboration, from the gate's own "unexplained" files — and NOT the circular version.** The 14
files the marker-comparison flagged are 13 independent legacy writers plus one trap:

```
07-08 20:48  README-MOVED.txt
07-09 04:17 → 08:36   ten memory-maint-*.last-run.ts stamps (repair/atomize/harvest/
                      consolidate/conflict × LOCAL+USER), memory-maint-rr-cursor.ts,
                      fleet-attribution.json
07-09 09:12  daemon.spawn-history        ← the ring ITSELF
```

The thirteen chore stamps are genuine independent evidence: separate writers, separate scopes, all
last written on **2026-07-09**, none since. That is the old writer's last activity, and it is why a
14-day quiet window reads clean.

*(A first pass claimed the LEGACY `daemon.spawn-history` freezing at 09:12 "matches the newest
flagged file" and called that a death record confirming the PASS. **Circular** — the ring is
itself the newest flagged file, so its freeze timestamp IS that mtime. Citing a file's last write
as confirmation of its own last write proves nothing. The thirteen other stamps do the work; the
ring never could.)*

*(An earlier draft derived this from **48 published tags in 26 days ≈2/day** and concluded "a
pre-migration process dies within a DAY; 14 days is an order of magnitude of headroom". That was
the wrong quantity: a tag is PUBLISHED, a cache rolls forward only when something INSTALLS it. This
session holds the counterexample — the `version-update` chore is absorbed by the ai-maestro server,
its janitor-side stamp is frozen, and the C3 anchor sat at 0.59.0 while 3.3.9 ran. Upstream cadence
is not local cadence, and the real margin is ~2×, not ~14×.)*

**What would falsify it:** a legacy-era writer whose natural cadence exceeds 14 days would read as
quiet. None is known here — the writers that touch this dir (daemon loop ticks ≤60 s, keepalive
restage, the memory/chore stamps) all fire sub-daily. That enumeration is from the writers this
card identified, NOT an audit of all 178 files, so treat it as corroboration rather than proof. If
a >14-day-cadence writer is ever added — or if local roll-forward slows past ~7 days — widen the
window, or this gate goes blind in the same direction the original one did.

**NOT borrowed from the repo's other 14.** `trdd-drift.py:145` defaults
`CLAUDE_PLUGIN_OPTION_TRDD_STALENESS_DAYS` to 14, and reusing that number here would be false
precision — it measures how long a TRDD CARD may sit untouched, which has nothing to do with
process liveness. The agreement is a coincidence; the derivation above is the reason.

*(Recorded because the first version of this line read `# > any plausible session/daemon
roll-forward window`, with "plausible" doing all the work — and the number was chosen AFTER seeing
that the newest non-excluded write was 50 days stale, i.e. any value from ~1 to ~49 would have
printed PASS. **A threshold selected so the check clears is not a check**, and it looks measured
precisely because it sits inside a script that prints PASS.)*

**Why RECENCY and not "newer than the marker".** The marker records when the migration ran
(2026-07-08 20:48). A file written on 2026-07-09 is newer than it — but it was written by old code
that was still running *then* and has long since rolled forward. Comparing against the marker
therefore answers "was anything written after the migration", which is permanently YES on any host
that had a running daemon that day, and it never decays. The question the gate needs answered is
"is an old writer running NOW", and only a recency window asks that. **Measured: a
marker-comparison run returns 14 files and FAILS; the newest is 2026-07-09 09:12, fifty days
stale.** This is the SAME defect class as the original gate one level down — a predicate that can
never clear because it tests a permanent historical fact, and I wrote it into the replacement
before running it.

**The exclusions are the whole point, and each is provisional in a different way.** The singleton
trio is excluded PERMANENTLY-until-retired: QK7M2B0X mandates that write, so its presence is health,
not drift. The keepalive names are excluded TEMPORARILY: they are there because of the bug box 2
fixes, so **once box 2 lands, delete those four from `EXCLUDE`** — leaving them would blind the gate
to a regression of the very bug it documents. A gate whose exclusions are never revisited becomes
the next version of the failure below.

**RUN 2026-08-28 — GATE PASSES, all three steps, measured not asserted:**

```
step1 PASS: marker exists
step2 PASS: no stop-class flags
GATE PASS: no non-excluded legacy write in 14d
```

So the old-code-writer question is answered: **none is live.** What remains is the keepalive
hardcode (box 2), which is a known-current writer, not evidence of an old one — and it is why those
four names sit in `EXCLUDE`.

<details><summary>ORIGINAL GATE (broken — kept for the lesson)</summary>

> Two published releases AFTER the release that ships ba58ebb, so every
> long-running session on this machine has restarted on post-migration code.
> Check: `<DATA>/global-state/migrated-from-legacy.ts` exists AND no file under
> the legacy dir has an mtime newer than the marker (proves no old-code writer
> is still active).

**Why it could never pass.** Its release count was satisfied long ago (48 published tags since
2026-08-02 alone). Its mtime test read "a legacy file newer than the marker" as PROOF that an
old-code writer lives — sound when written, and false from the moment QK7M2B0X shipped a NEW writer
to the same directory. The predicate then matched new code doing exactly its job, every heartbeat,
forever. **The gate did not fail loudly; it answered "wait another release" indefinitely.** When a
gate has returned the same answer for months, suspect the gate before the schedule.
</details>

## Acceptance

Step 0 (rewrite the gate) is the entry point; nothing below may start before it.

- [x] **Rewrite the gate** — DONE 2026-08-28, and RUN (passes) so it measures the thing, not the proxy — exclude the QK7M2B0X
      singleton names, and expect the keepalive residue until the hardcode is fixed.
- [x] **Fix `keepalive_install.sh:34`** (BOTH `install_macos` and `install_linux`) — DONE
      2026-08-28. The hardcoded legacy `LOG_DIR` is replaced by `resolve_log_dir()`, which asks
      the staged `global_state.global_state_dir()` (the module that OWNS the 4-rung ladder) and
      falls back FORWARD to the DATA dir, never back to legacy. Pinned by two tests that no
      single hardcoded constant can satisfy together
      (`test_installer_never_resurrects_the_legacy_global_state_dir` asserts the DATA answer with
      nothing staged; `test_installer_honours_the_resolved_global_state_dir` asserts the LEGACY
      answer on an un-migrated host). **The plist on THIS machine is still the old one** —
      regenerating it is part of the USER-surfaced removal step below, not this box.
- [x] **Re-scope §Scope against THREE eras** — DONE 2026-08-28. §Scope now names era 1 / 2 / 3
      apart, states that **only era 1 retires** (era 2 stays canonical for non-flag state), and
      — after a first, WRONG containment claim was caught the same day — enumerates the three
      live legacy touchpoints OUTSIDE `global_state.py` as their own step (3b).
- [ ] Retire the 2U8AH82F legacy read-fallback AND QK7M2B0X's legacy rung in `_singleton_paths`
      **in one pass** — they touch the same list. The six call sites are enumerated in §Scope 1+3.
- [ ] Surface the dir removal to the USER (RULE 0 — never auto-delete).
- [ ] Update the consumers named in §Scope step 4 (README, CLAUDE.md, `janitor-footprint.md`, the
      4 rules' dual-path probe, the architecture wikimem page).
- [ ] `uv run pytest` + `ruff` + `mypy` green.

## Notes and lessons learned

- 2026-08-28 — **A gate can rot into a proxy that no longer tracks its referent.** This card's gate
  read "a legacy file newer than the marker" as proof an old-code writer lives. That was sound when
  written and false once QK7M2B0X shipped a legitimate new writer to the same dir. The gate did not
  fail loudly; it just answered "wait another release" forever. **When a gate has said the same
  thing for months, suspect the gate before the schedule.**
- 2026-08-28 — **A filename is not an event, and a header is not a behaviour.** Two instances on
  this card's own evidence: `…daemon.plist.DISABLED-flood-20260715` was born **2026-07-09** (six
  days off its name), and `.githooks/pre-push`'s "every publish.py run rewrites this file" header
  sat above a four-month-old mtime — which, chased, exposed a whole separate defect
  (`TRDD-I8AE6C8D`). **When a name or a header tells a story, `stat` the file and see if the
  filesystem agrees.**
- 2026-08-28 — **Ask the runtime, not the file.** The daemon runs from the plugin CACHE, so a
  source read proves nothing about it; the loaded launchd job is what `launchctl print` reports,
  not what a `.plist` on disk contains; a config file's contents are not the command that consumes
  it. Each of those was wrong here before it was measured.
- 2026-08-28 — **`-L`, `-S`, `-G` answer different questions.** `git log -L a,b:file` pins a FIXED
  range against the CURRENT file (a moved line drifts out silently); `-S` is the PICKAXE, reporting
  occurrence-COUNT changes, so it is blind to a value rewrite that keeps the token present once —
  exactly the edit that would have mattered here. Both returned "one commit" and that read as
  corroboration when it was one blind spot twice. Use `-G` or a `-p` line scan for content.
- 2026-08-28 — **An empty result from a malformed query is not evidence of absence.**
  `git log --diff-filter=A -S "…" -- <file>` can only ever return nothing for a pre-existing file
  (the flag filters on the FILE being added). `git log --grep` cannot see file CONTENTS, so it
  cannot find an incident this repo records in TRDD bodies and wikimem pages. `ls | tail -1` sorts
  LEXICALLY (5.9.0 beats 5.12.0) — use `sort -V`. Each produced a confident wrong answer here.
- 2026-08-28 — **"Newest installed" and "what the gate runs" are different questions.** The cache
  held 5.7.1→5.12.0; `publish.py` pins `v5.4.0` via `.cpv-version`, which is in the cache at no
  version. Reading the newest installed validator would have measured a tree the gate never
  invokes.
- 2026-08-28 — **A retirement cannot succeed while something rebuilds its subject, and a
  RESOLUTION LADDER copied into a second language always drifts to the wrong rung.**
  `keepalive_install.sh` hardcoded the ladder's LAST rung, so its `mkdir -p` re-created the very
  directory this card is waiting to see go quiet — the gate was measuring a dir the installer
  kept resurrecting. Worse, on an already-migrated host it pointed launchd's stdout capture at a
  directory the daemon no longer logs to, which fails SILENTLY (an empty log looks like a quiet
  daemon). DO NOT re-implement a multi-rung path resolution in a second language, BECAUSE the
  copy cannot track the original and its failure mode is a silently wrong path, never an error.
  DO call the module that owns the ladder and fall back FORWARD — a fallback that names the
  deprecated rung reintroduces exactly what the fix removed.
- 2026-08-28 — **A grep for the HELPERS is not a grep for the THING, and `--include=*.py` is not
  "all source".** §Scope briefly asserted that every legacy touchpoint lived in
  `global_state.py`, on the strength of `grep -rn "_legacy_read_path\|_flag_present_dual\|…"
  --include=*.py` returning empty. Both halves were proxies, and a broader grep run EARLIER IN
  THE SAME SESSION had already printed the counter-evidence — the narrow query overwrote the wide
  one in my head. The truth is three live touchpoints outside that module, one of them in RUST,
  which `*.py` cannot see by construction. DO NOT grep for the identifiers you expect a thing to
  be reached through, BECAUSE a second implementation reaches it by a different name, in a
  different language, or by spelling the literal path. DO grep for the THING ITSELF — the literal
  path/string — across the whole tree, and only then narrow. The cost of getting this wrong here
  was concrete: step 4 tells the USER to delete a directory a Rust write-gate and an OAuth
  keychain latch would still be pointing at.
- 2026-08-28 — **The fix for a bad grep PATTERN was a bad grep FILTER — the same substitution, one
  stage downstream.** Having corrected the pattern to the literal path, I then narrowed the 100
  hits with `grep -E "^(scripts|hooks|commands|agents)/"` — a hardcoded four-directory watch-list
  that cannot see a directory it does not name, and `rules/` (which step 5 of this very section
  claims as scope) is not one of the four. Worse, the preceding `grep -v "^\./design/"`
  exclusions were VACUOUS: the paths carried no `./` prefix, so those filters matched nothing and
  I never noticed, because the positive allowlist happened to do the selecting. **A filter that
  silently matches nothing is indistinguishable from a filter that worked.** DO NOT triage a
  corpus through a chain of `grep -v`/allowlist filters, BECAUSE what it DISCARDS is invisible and
  unaudited. DO run the filterless per-file count (`… | awk -F: '{print $1}' | sort | uniq -c |
  sort -rn`) and triage every filename by hand — the list is short, and nothing can hide in it.
  Corollary, learned the same day: a REMEMBERED count ("the 4 rules") is itself a proxy; it was
  ten.
