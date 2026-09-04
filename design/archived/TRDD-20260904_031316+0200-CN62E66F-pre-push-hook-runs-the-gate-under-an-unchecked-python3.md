---
trdd-id: CN62E66F
title: the pre-push hook runs the release gate under an unchecked python3 that may violate requires-python
column: complete
created: 2026-09-04T03:13:16+0200
updated: 2026-09-04T04:02:00+0200
current-owner: main-session
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
relevant-rules: []
npt: []
eht: []
blocked-by: []
external-refs: [TRDD-S7FIQTCO]
implementation-commits: []
---

# the pre-push hook runs the release gate under an unchecked python3

## Symptom

`git-hooks/pre-push` runs the full release gate through a two-branch helper:

```sh
run_release_gate() {
    if command -v uv >/dev/null 2>&1; then
        uv run python scripts/publish.py --gate
    else
        python3 scripts/publish.py --gate     # git-hooks/pre-push:25
    fi
}
```

The fallback takes whatever `python3` is first on PATH, which may be any
version. That half is not in doubt — it is what the branch literally does. The
fallback exists precisely for machines WITHOUT `uv`, i.e. the least-controlled
environments, where a mismatch is most likely.

**The `uv` branch is only ASSUMED safe, and the assumption is not fully
verified.** It runs `uv run python scripts/publish.py --gate` — note `uv run
python <script>`, not `uv run <script>` or `uv run --script`. On this host it
resolves to 3.12.13, which satisfies `requires-python = ">=3.11"`, but that
shows the local venv happens to conform; it does NOT prove `uv run python`
would REFUSE a non-conforming interpreter. Settling it needs a host where the
project venv is below the floor. The defect below stands either way, because it
is about the branch that demonstrably performs no check at all.

## Reachability — WIDER than the header comment implies

An earlier draft of this section said the gate fires "only for a DEFAULT-BRANCH
or TAG push", sourced from the hook's own header comment
(`# default branch (main/master) or any tag -> full publish.py --gate`). That
was inferring control flow from a comment. The dispatch (`git-hooks/pre-push`
lines 62-88) is broader:

```sh
case "$remoteref" in
    refs/tags/*|refs/heads/main|refs/heads/master) release_push=1 ;;
    refs/heads/*)  # default branch -> release_push=1, else feature -> scan
    *)             release_push=1 ;;   # unknown ref shape — gate conservatively
esac
...
if [ "$release_push" -eq 1 ] || [ "$saw_feature" -eq 0 ]; then
    run_release_gate
```

So `run_release_gate` runs on FOUR classes, not one:

1. a tag, `main`, `master`, or the resolved default branch;
2. **any unknown ref shape** — the `*)` arm gates conservatively by design;
3. **any push where nothing parsed as a feature branch** (`saw_feature -eq 0`),
   which includes a push consisting only of ref DELETIONS: those hit
   `[ "$localsha" = "$ZERO" ] && continue` before either flag is set, so both
   stay 0 and the gate runs;
4. a push whose refs could not be read at all, for the same reason.

That is the correct design for a fail-safe — when the hook cannot classify a
push, gating is the safe default. But it means the unchecked-interpreter path is
NOT the narrow "someone pushes main directly" case. On a host without `uv`,
deleting a remote branch is enough to run the full release gate under whatever
`python3` is on PATH.

## …but the CONSEQUENCE is milder than that makes it sound

Two reviews reached opposite-sounding conclusions here and both are correct,
because they are about different things: the set of pushes that CALL the gate
is wide (above), while the damage when it fails is small (here). Recorded
together so neither is inherited alone.

Trace the normal path. The hook's gate runs `publish.py` in a CHILD process,
but a release push is itself started by an OUTER `publish.py` that already
loaded. If `uv` is absent, that outer invocation was also a bare `python3` —
so it would have hit the identical `ImportError` first, and no push would ever
have begun. The hook's call is therefore never the FIRST load on the supported
path.

The one case where it is first is a direct `git push origin main` bypassing
`publish.py` — and that push is refused anyway, by the process-ancestry check
inside the very gate that is failing to import.

**THE REF-DELETION PATH BREAKS THAT ARGUMENT, and it is the one case that is a
genuine regression.** A deletion (`git push origin --delete <branch>`) is never
started by `publish.py` — the user types it directly — so there is no outer
invocation that already loaded, and the "it would have failed earlier" reasoning
simply does not apply. On a no-`uv`, sub-3.11 host:

- BEFORE `assert_never`: the gate imported fine, ran, and refused the deletion
  via the ancestry check with a message naming the actual reason. **VERIFIED,
  not assumed** — `--gate` dispatches to `run_gate`, whose Gate 0
  (`scripts/publish.py:1062`) calls `_called_by_publish_orchestrator` and on a
  false answer prints `BLOCKED: Direct push not allowed` with the three
  `publish.py` invocations to use instead, then `return 1`. A review raised the
  possibility that `--gate` skipped the ancestry check entirely — which would
  have meant deletions previously RAN the full 16k-test suite and were then
  ALLOWED, a worse pre-existing bug. It does not; the check is the gate's first
  action.
- AFTER: the gate dies at import with `ImportError: cannot import name
  'assert_never'`, and the operator is told nothing about why their branch
  deletion was blocked.

Same outcome (refused), materially worse diagnostic. And the operation is not
some exotic corner: deleting a merged feature branch is ROUTINE CLEANUP, which
makes it the most frequent thing that reaches this gate at all — and the case
where an operator has the least context for interpreting an ImportError about
`typing`. That is the honest worst case, and an earlier
draft of this section missed it by reusing the outer-publish.py argument
everywhere instead of checking it per path. It does not raise the priority to
urgent — it still needs a host both without `uv` and below the floor — but it
is a real behaviour change on an innocuous command, which "a worse message on a
path that already fails" undersold.

**So the defect is: an unsupported interpreter produces a misleading diagnostic
on a path that already fails.** Not a new broken capability. `requires-python`
says `>=3.11`, so 3.10 failing is CORRECT behaviour — only the message is
wrong. Priority: LOW.

**FIXED 2026-09-04 anyway, and sooner than "LOW" implied, because it turned out
to be cheap** — the generator this card told the implementer to find does not
exist (see below), so the fix was a guard in a tracked source file rather than a
change to a code-generation path. The estimate was inflated by a stale header,
not by the work.

The underlying property this card names — a fallback branch that inherits none
of the enforcing branch's guarantees — is what the fix addresses directly, and
it will outlive the `assert_never` that exposed it.

## How it surfaced, and why the trigger is a red herring

Found 2026-09-04 while reviewing TRDD-S7FIQTCO. That card added
`from typing import Literal, assert_never` to `publish.py`, and `assert_never`
is 3.11+. A grep for the 3.11 additions I could name (`tomllib`,
`ExceptionGroup`, `except*`, `Self`, `LiteralString`, `TypeVarTuple`,
`assert_never`) matched only `assert_never`, so on that evidence the module
loaded on 3.10 before the change and does not now.

**That grep is a NAMED-FEATURE check, not a proven version floor.** What it
misses splits two ways, and the split is the point:

- **Importable names a longer grep COULD catch** — `asyncio.TaskGroup`,
  `asyncio.timeout`, `enum.StrEnum`, `datetime.UTC`, `contextlib.chdir`,
  `typing.Never`/`Required`/`NotRequired`/`assert_type`/`dataclass_transform`,
  `hashlib.file_digest`, `BaseException.add_note`. Of these, `file_digest`
  (this file has `_refresh_integrity_manifest`), `datetime.UTC` and
  `contextlib.chdir` are the plausible ones.
- **Pure SYNTAX that NO name-grep can ever find** — `except*`, `re` atomic
  groups `(?>...)` and possessive quantifiers inside a pattern string, PEP 695
  `type` statements, PEP 701 nested f-string quotes. These have no name in the
  source. (`except*` was even in my pattern, which does not help: `*` is a
  regex metacharacter, and `except *` with a space is legal.)

So a longer grep does not close this — only an AST-based checker does. It also
**checked one FILE, not the import closure**: any `scripts/lib/*` module
imported at `publish.py`'s module scope breaks the load identically.

**The remedy is `vermin`, NOT `ruff`.** An earlier draft of this line offered
"`vermin`, or `ruff` with `target-version`" — the ruff half is wrong and was
exactly the false-backstop shape this session spent its time deleting from
`publish.py`'s skip warnings. `target-version` selects which lint rules apply
and how autofixes are written; the relevant family (`UP`/pyupgrade) modernizes
*toward* the target and does not reject constructs *newer* than it. With
`target-version = "py310"`, ruff does NOT flag `from typing import
assert_never` — no rule checks stdlib-symbol availability. `vermin` computes a
minimum version from an AST walk and catches both halves of the split above.

Neither is configured here. That claim rests on: no `.pre-commit-config.yaml`
(established earlier this session), `.mega-linter.yml` dormant and running
nothing, and ci.yml's five jobs enumerated by `yaml.safe_load` — none runs a
version-floor check. Not exhaustively re-verified for a stray `vermin.ini`.

On a 3.10 host with no `uv`, the gate therefore dies with an `ImportError` on a
typing symbol, during a push, and takes EVERY entry point with it — `--gate`,
`--install-hook`, `--install-branch-rules` — because the import is at module
scope. That failure names `typing`, not the interpreter version, which is about
as misleading as a diagnostic gets.

**But `assert_never` is the trigger, not the defect.** The fallback would run
the gate under a 3.8 interpreter just as willingly, and `publish.py` is free to
adopt any 3.11 feature the project already declares support for. A hook that
can run the gate under an interpreter violating the project's own
`requires-python` is wrong independently of what the file happens to import
today. Fixing it by avoiding 3.11 constructs would be treating the symptom, and
would forfeit a construct (`assert_never`) whose static-exhaustiveness guarantee
was measured and is load-bearing.

## THERE IS NO GENERATOR — the header is stale prose

The hook's header says *"Auto-generated by scripts/publish.py's"*, and an
earlier draft of this card took that at face value and told the implementer to
find the generator first.

**There isn't one.** `publish.py::install_hook` is documented and implemented as
*"Copy git-hooks/pre-push to .git/hooks/pre-push and set core.hooksPath"* — it
reads `root / "git-hooks" / "pre-push"` as a SOURCE file and copies it. Nothing
emits that text. A grep for the literal `python3 scripts/publish.py --gate` in
`publish.py` finds nothing, which is consistent.

So `git-hooks/pre-push` is a tracked source file, the fix goes DIRECTLY in it,
and there is no regeneration that could revert it.

This is the fourth stale-documentation claim this session — after `CLAUDE.md`
asserting the gate runs "ruff + mypy, not pyright", the divergence table naming
no CI job, and `.mega-linter.yml` reading as live config for a runner nothing
invokes. The pattern is worth more than any one instance: **prose that describes
a file's provenance ages badly and nothing type-checks it.** Correcting the
header is part of this card's work, not a nicety.

## Candidate fixes, not yet chosen

1. **Version-check in the fallback** — cheapest. `python3 -c 'import sys;
   sys.exit(0 if sys.version_info >= (3,11) else 1)'` before invoking, with a
   clear message naming the required version and pointing at `uv`. Keeps the
   no-uv path working on conforming hosts.
2. **Refuse without `uv`** — simplest to reason about, and CLAUDE.md already
   documents `uv run scripts/publish.py` as the invocation. But it hard-blocks
   a push on any host without `uv`, which the fallback was presumably written
   to avoid.
3. **Read the floor from `pyproject.toml`** rather than hardcoding 3.11, so the
   check cannot drift from `requires-python`. More moving parts in a shell hook.

Preference is (1) with the floor read from `pyproject.toml` if that is cheap in
POSIX sh, else (1) with the version written once and a comment naming
`requires-python` as its source of truth.

## Acceptance criteria

- [x] The generator is located and the fallback no longer invokes `publish.py`
      under an interpreter that violates `requires-python`.
      — The first clause is satisfied by DISPROOF: there is no generator (see
      above; `install_hook` copies, nothing emits). The box was written on the
      stale header's authority and could not have been satisfied as worded.
      The second clause is done: the fallback now runs
      `python3 -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 11)
      else 1)'` and refuses with a message before invoking `publish.py`.
      The `uv` branch gained an explicit `return $?` so the two paths cannot fall
      through into each other.
- [x] A host below the floor gets a message naming the required version and the
      `uv` remedy — not an `ImportError` on a typing symbol.
      — The refusal prints, to stderr: that it is refusing to run the release
      gate; that `uv` is absent AND `python3` is older than 3.11; that
      `pyproject.toml` `requires-python >=3.11` is the source of that floor; and
      both remedies (install `uv`, or put a >=3.11 `python3` on PATH). It returns
      1 before `publish.py` is invoked, so the `ImportError` is never reached.
      The predicate was proven in BOTH directions on this host, since a check
      that cannot fail is not a check: with the real floor → exit 0; with an
      unreachable floor `(99, 0)` → exit 1.
- [x] Regenerating the hook reproduces the fix (i.e. it was made in the
      generator, not in the generated file).
      — VACUOUSLY SATISFIED, and saying so beats silently ticking it: there is no
      regeneration step, so nothing can revert the edit. The box existed only
      because the file's header claimed a generator that does not exist. The
      stale header is corrected in the same commit — it had teeth, because "do
      NOT edit by hand; the pipeline rewrites it" is precisely the belief that
      leaves a bug in place.
      `publish.py --install-hook` still COPIES this file into `.git/hooks/`, so
      the operator-facing step after editing is a re-install, and the header now
      says that.
- [x] A test covers the below-floor path without needing a second interpreter
      installed.
      — `tests/test_pre_push_python_floor.py`, 9 tests. A FAKE `python3` shim on
      PATH supplies the below-floor case, which is the honest substitute: the
      guard IS a `python3 -c` subprocess, so what it depends on is that command's
      exit status, and a shim controls exactly that.
      Covers: below-floor (3.10) fails; AT the floor (3.11) passes and above
      (3.13) passes — a guard that refuses everything is not a guard; the guard
      textually PRECEDES the bare-python3 invocation, since a guard after it
      would not prevent the ImportError; the `uv` branch `return $?`s rather than
      falling through; the refusal names the floor, its pyproject source, and
      both remedies; and the shim self-checks by exiting 99 on any argv shape the
      guard never uses, so a test bug is loud rather than silently passing.
      One test pins the predicate copied into the test file against the hook's
      own text — a copy that drifted silently would void every other test here.
      MUTATION-PROBED: replacing the guard with `if false; then` fails 2 of the 9
      (the predicate-match and the ordering test); `git-hooks/pre-push` restored
      byte-identically, sha256 verified.
      shellcheck clean (CI lints this exact file) and `sh -n` parses.

## Notes and lessons learned

- The lesson worth keeping: a fallback branch inherits none of the guarantees
  of the branch it substitutes for. `uv run` enforcing `requires-python` says
  nothing about what `python3` does, and the fallback is reached exactly when
  the enforcing path is unavailable — so the guarantee is weakest where it is
  needed most.
