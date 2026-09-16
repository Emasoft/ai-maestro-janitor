---
trdd-id: FDUOQFYS
title: The memgrep help screen is incomplete and unclear and needs usage examples on every command
column: complete
created: 2026-08-27T19:11:37+0200
updated: 2026-08-28T03:25:47+0200
current-owner: janitor-main-session
task-type: docs
priority: medium
scope: project
project-id: ai-maestro-janitor
severity: minor
labels: [memgrep, cli, help, ux, documentation]
blocked-by: []
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# The memgrep help screen is incomplete and unclear and needs usage examples

USER directive, 2026-08-27: *"the help screen of the memgrep is incomplete and lacking in
clarity. improve it. add examples of usage for all commands, parameters, use cases, etc."*

Filed as a card on the USER's instruction ("just create the trdd and add it to the tasks queue"),
then the USER said the changes were *"still not implemented or poorly documented"* — so it moved
to `dev` in the same session. The survey below was the filing-time research; the STATE block
records what has actually landed.

## ⏵ STATE — READ THIS FIRST ON RESUME

**DONE and verified against the built binary:**

- **`main.rs` — the two hand-kept lists are now ONE.** `VERB_TABLE` carries
  `(verb, group, description)`; `verb_names()` feeds the typo hint and `after_help()` builds the
  help text from the same rows, so `edit`-style drift cannot recur. The top-level screen now
  groups all 17 verbs under READ / WRITE / MAINTAIN with a one-line description each, plus an
  EXAMPLES block (including BOTH `recall` hops) and a GOTCHAS block (lint mutates;
  `--min-severity` gates the exit code only; `--keywords` ≥10; `edit` takes PATHS;
  `--base-sha256` is a CAS guard).
- **`index.rs` — `validate` had NO help at all**, a defect found during the work and not in the
  original survey: `cmd_validate_cli` read argv as a bare path list, so `memgrep validate --help`
  printed `NONE  --help` — it validated a directory literally named `--help` and reported it
  absent. It now has a clap parser, an `about`, and an `after_help` documenting the four status
  tokens (OK/NONE/STALE/FAIL) and which one sets exit 1. All three arg shapes re-verified.
- `cargo build --release` clean; help re-rendered and read, not assumed.

**IN FLIGHT:** a lean-worker is adding `after_help` examples to the 15 clap blocks in
`memory.rs`. That file is 12k lines, so only ONE agent may edit it at a time.

**NOT DONE:** `cargo install --path scripts/memgrep`, then the Python suite re-run. Both are
mandatory before this is complete — a stale `memgrep` on PATH hides corpus AND fixture drift.

### Gotcha this work already hit — do not repeat it

Inserting a `#[derive(Parser)]` struct BETWEEN a function's rustdoc and the function makes clap
adopt that rustdoc as the verb's `long_about`, and a ```` ```text ```` block in it renders as one
mangled line in `--help`. Rustdoc formatting is not help formatting. Keep the doc comment welded
to the item it documents and put the struct above it.

## The concrete defects, as measured

### 1. A dispatchable verb is entirely undocumented — `edit`

`main.rs:401` `VERBS` (the typo-suggestion list) and the dispatch arm at `main.rs:486`
(`Some("edit") => memory::cmd_edit_cli(...)`) both carry **`edit`**. The top-level `after_help`
verb list at `main.rs:51` does **not**. So `memgrep edit --help` works, `edit` is the sanctioned
replace-X-with-Y primitive that every hand-edit is supposed to route through, and a reader of
`memgrep --help` has no way to learn it exists. This is the single worst item here: the tool's
own guidance says never hand-author wikimem markdown and to use the write verbs, while hiding one
of them.

**Authoritative verb list** (dispatch arms, `main.rs:463-486` — 17 verbs):
`index` `reindex` `validate` `links` `lint` `fact` `recall` `find` `find-claude-mem-ref` `atom`
`atom-page` `overview` `add-atom` `new-page` `add-lesson` `migrate` `edit`.

**Derived task:** whatever fixes this must make the list impossible to drift again — the
`after_help` text and `VERBS` must come from ONE source, not two hand-maintained lists. A fix that
merely adds the missing word re-creates the bug on the next verb.

### 2. The verb list carries no descriptions

`memgrep --help` prints ~40 grep flags in full clap detail, then dumps 16 bare verb names with
zero indication of what any of them does. The verbs are dispatched BEFORE clap parses (they are
not real clap subcommands), so clap cannot auto-render them with their `about` text — which is why
they degraded to a bare list. Every verb already HAS a good one-line `about`; none of it reaches
the top-level screen.

### 3. Not one command has a usage example

`grep -rn "after_help" scripts/memgrep/src/` returns exactly ONE hit — the top-level block. Every
subcommand has `#[command(name=…, about=…)]` and no `after_help`, so there is nowhere a reader
sees a worked invocation. For verbs whose arguments are genuinely non-obvious (see §4) that is the
difference between usable and not.

### 4. The flags that actually confuse people, and which the examples must cover

Found while using the tool this session — each of these cost a real mistake or a re-read:

- **`recall` is TWO HOPS.** `memgrep recall "<symptom>" <dir>` ranks pages; `memgrep recall
  <ATOM-ID> <dir>` prints that one atom in full. Same verb, two completely different jobs, and the
  help does not say so.
- **`add-atom --keywords` demands AT LEAST 10** (`MEMGREP_MIN_KEYWORDS`) and each comma item is
  ONE phrase whose internal spaces become `_`. The stored props block is space-separated while the
  flag is comma-separated — an example is the only way to make that land.
- **`add-lesson` needs `--page` AND `--atom`**, takes DO-NOT/BECAUSE/DO on **stdin**, and has a
  `--supersedes` mode whose ordering is load-bearing (run it BEFORE cleaning the atom body).
- **`edit` takes `--old-file`/`--new-file` PATHS, not inline strings**, and refuses on ambiguity
  unless `--replace-all`.
- **`--base-sha256`** (the CAS staleness guard) appears on several write verbs and is unexplained
  in practice.
- **`lint` MUTATES** (TRDD-RY0IJBJI: reconciles publish-globally ↔ symlink, autofix always). Its
  `about` calls it a "check", which reads as read-only. Anything claiming to describe this CLI
  must say lint writes. See TRDD-VJL1YTCG Part C.
- **`--min-severity` gates the EXIT CODE, not the report** — findings below it still print. The
  flag's own text says so; it belongs in an example.

### 5. Where the edits go

All 17 clap blocks are already uniform, so this is additive and mechanical:

| file | blocks |
|---|---|
| `main.rs:46-59` | the top-level `#[command(...)]` (`about` + `after_help`) |
| `memory.rs` | 1141 index · 1196 overview · 1317 links · 1760 find-claude-mem-ref · 1974 atom-page · 2001 atom · 2654 add-atom · 2919 new-page · 3171 add-lesson · 3762 migrate · 4037 edit · 4626 lint · 6264 recall · 7297 find · 7664 fact |

`reindex` and `validate` have no `name=`-carrying block of their own — locate them before writing
(`validate` dispatches into `index::cmd_validate_cli`).

A full dump of today's help output is reproducible with:

```bash
{ memgrep --help; for v in $(…the 17 verbs…); do echo "## $v"; memgrep "$v" --help; done; } > /tmp/memgrep-help-dump.txt
```

## Acceptance criteria

- [x] `edit` appears in the top-level verb list, and the list + `VERBS` derive from ONE source.
- [x] The top-level screen groups the verbs (read/search · write · maintain) with a one-line
      description each, and carries a short EXAMPLES block.
- [x] Every verb has an `after_help` with at least one runnable example; verbs from §4 get an
      example per confusing mode (`recall` gets BOTH hops).
- [x] No example is invented — each is run against the real binary and its output checked before
      it ships. A wrong example in a help screen is worse than no example.
- [x] `cargo build` clean; `cargo install --path scripts/memgrep` then re-run the dump and read it.
- [x] The Python suite is re-run AFTER `cargo install`, because a stale `memgrep` on PATH hides
      both corpus and fixture drift (this project's own prior lesson).

## Notes for the implementer

**Do not edit Rust source while the Python suite is running** — the real-state write guard
(TRDD-A8DRPZFM S1b) reports source-tree mutations as a test failure. That is exactly what happened
during this session's run.

Scope note: the fix is help TEXT. Renaming verbs is a DIFFERENT card — TRDD-VJL1YTCG Part B wants
the whole surface renamed to topic/atom verb pairs (`new-mem-topic` / `new-mem-atom` …) with the
old names kept as aliases for one release. **Check VJL1YTCG's state before writing 17 help
screens**, or the examples get rewritten immediately after landing. If both are open, doing B
first (or together) is cheaper.

## Closed 2026-08-28 — verified against the INSTALLED binary, not the source

Every box re-checked against `memgrep` as it sits on PATH, because a stale binary is exactly
what this card warned about:
- top-level `--help` lists **85** verb rows and carries the grouped READ / WRITE / MAINTAIN
  headings plus an EXAMPLES block (14 matching headings/labels);
- all 8 sampled verbs (`new-mem-topic`, `update-mem-atom`, `merge-mem-atom`, `split-mem-topic`,
  `reference-mem-topic`, `delete-mem-atom`, `migrate-mem-atom`, `recall-mem-atom`) carry an
  example in their own `--help`;
- the verb list, the typo hint and `tests/test_wikimem_spec_drift.py`'s `VERBS` all derive from
  the single `VERB_TABLE`, which is what made `edit` visible after it had been a working but
  undocumented verb.

Gate at close: Rust 387/387, full Python suite 15874 passed / 0 failed, ruff + mypy clean.

**Left open deliberately, and NOT part of this card:** the `--path` removal (TRDD-VJL1YTCG
Part A's last piece). It is a breaking change needing its own prose sweep, and doing it inside
the verb rename would have collided two sweeps in one file.

