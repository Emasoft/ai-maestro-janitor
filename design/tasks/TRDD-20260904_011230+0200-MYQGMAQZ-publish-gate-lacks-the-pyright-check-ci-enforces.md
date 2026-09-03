---
trdd-id: MYQGMAQZ
title: the publish gate lacks the pyright check CI enforces so a release can be tagged before CI rejects it
column: todo
created: 2026-09-04T01:12:30+0200
updated: 2026-09-04T01:52:00+0200
current-owner: main-session
task-type: infra
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
priority: high
relevant-rules: []
npt: []
eht: []
implementation-commits: []
---

## Symptom
`scripts/publish.py`'s release gate runs ruff + mypy. GitHub CI's Lint job additionally runs `uvx --with pyright pyright` with no `continue-on-error`. So the gate can pass, tag, push, publish a GitHub release and install the plugin, and only THEN have CI reject the commit.

## What actually happened (2026-09-04, release 3.4.14)
- publish.py reported all gates green and published 3.4.14 from commit `4326519d`.
- CI run 33814952562 on `4326519d` FAILED: job "Lint", step "Pyright (type check)", `7 errors, 0 warnings, 0 informations`.
- 6 errors in `tests/test_pane_actuate.py` (lines 88, 89, 185, 270, 307, 460 — `reportOptionalSubscript`), 1 in `tests/test_capture_all_logins.py:253` (`reportArgumentType`, `Popen[bytes]` vs `Popen[str]`).
- The release was already tagged, released, and installed to the user scope before this was noticed.

## Why "just drop pyright" is the wrong fix
`pyproject.toml` (around lines 45-58) documents the split as DELIBERATE, citing TRDD-BMDZK4RA: mypy does NOT check calls between `scripts/lib/` siblings, because those modules import each other bare (`import state`) and under `mypy_path = "scripts"` that name cannot resolve, so `ignore_missing_imports` degrades it to `Any`. Pyright owns that class instead via `extraPaths` in `pyrightconfig.json`. It caught a real `atomic_write(str)` vs `Path` mismatch that mypy passed clean (fixed in `a08d14fd`). The two checkers cover different classes on purpose.

`CLAUDE.md` says "the publish gate runs ruff + mypy, not pyright" — that describes the gate as it is, and is the text that made this look intentional. It is describing the hole, not defending it.

## Why the fix belongs in stage 4b specifically
`publish.py` already has a MANDATORY, no-skip stage `[4b/11] CI-parity preflight` (see `stage_ci_preflight`, publish.py:1655 onward), whose stated purpose is to catch CI-parity defects before the push. Pyright — the one CI check that blocks a merge and that mypy structurally cannot replace — is simply absent from it. This is a hole in a stage built for exactly this job, not a missing stage.

## Proposed fix
Add `uvx --with pyright pyright` to stage 4b, invoked the same way CI invokes it (no path argument — `pyrightconfig.json`'s `include` covers `scripts/` and `tests/`), with the same `uv sync --extra dev` precondition CI performs so imports resolve. Treat a non-zero exit as BLOCKED, like the rest of 4b.

## Acceptance criteria
- [x] The gate runs pyright with the same invocation as ci.yml's Lint job — 2026-09-04,
      landed in `stage_lint` (step 2) rather than 4b, because that is where the other
      linters already live and the cheap fails belong before the test suite. Invoked
      `uvx --with pyright pyright` with no path and no extra flags, exactly as CI does;
      and it FAILS CLOSED: a pyright that cannot run BLOCKS the publish, exactly as a
      pyright that finds errors does.
      This started as a WARN+skip copying the jscpd/actionlint pattern beside it, and that
      was wrong on review: those degrade gracefully because a missed copy-paste report is
      an inconvenience, whereas pyright is the check CI blocks a merge on and whose absence
      here IS this card. A cold-cache fetch hiccup — rare, silent, correlated with nothing
      anyone would notice — would have skipped it on the very run that publishes, rebuilding
      the incident with extra steps. The error costs are not close: a false BLOCK refuses
      the publish with a message on screen, while a false PASS ships a public artifact CI
      then rejects. "Could not verify" is not "verified".
      Failing closed also DELETED the `--version` availability probe — it existed only to
      feed the skip branch, and with both outcomes blocking there is nothing to tell apart.
      No env-var escape hatch either: publish.py's stated contract is "no exceptions and no
      bypass flags", and Gate 0 exists to catch exactly that shape.
- [x] The gate's ruff scope matches CI's — now `ruff check scripts/ tests/`.
- [ ] The remaining rows of the divergence table are each either adopted into the
      gate or explicitly declared out of scope ON THIS CARD with a reason — an
      undocumented gap is what produced this defect.
- [ ] The GitHub release is not created until CI is green for the pushed sha
      (the ordering defect above), or that ordering is explicitly rejected here
      with a reason.
- [x] A tree with a deliberate pyright error is BLOCKED by publish.py before any tag or push.
      — 2026-09-04, verified by invoking `stage_lint(root)` DIRECTLY (not by running a
      publish), three paths: (a) clean tree → returns, pyright reported `0 errors`;
      (b) a deliberate `x: int = "not an int"` appended to a tracked test file →
      `BLOCKED: pyright failed`, `SystemExit code=1`; (c) `uvx` made unlaunchable (OSError)
      → `BLOCKED: pyright could not be run`, `SystemExit code=1`. All three re-run after
      the fail-closed change. The probe file was restored byte-identically (sha match,
      clean `git status`). The happy path alone would have proved nothing — the value of
      this change is entirely in (b) and (c).
- [x] A test pins that the gate's checker set is not a strict subset of CI's Lint job, so a
      future CI check added without a gate counterpart is caught.
      — `tests/test_publish_gate_ci_parity.py`, 2026-09-04. It `yaml.safe_load`s
      `.github/workflows/ci.yml`, extracts the tools the Lint job's `run:` steps actually
      invoke, `ast.parse`s `publish.py` and walks ONLY the `stage_lint` FunctionDef for
      `run(...)`/`subprocess.run(...)` argv literals, and asserts `ci_tools - gate_tools`
      is empty. Scoped to the function by AST rather than grepping the file, so an
      unrelated mention of a tool's name elsewhere cannot satisfy it. The gate running
      MORE than CI stays legal (mypy is deliberately gate-only). A second test asserts the
      gate's ruff paths are a superset of CI's.
      PROVED IN THE DIRECTION THAT MATTERS: injecting a new CI-only step
      (`uvx bandit -r scripts/`) into ci.yml fails it with
      `CI's Lint job runs ['bandit'] but publish.py's stage_lint does not` — ci.yml
      restored, `git status` clean. A probe that only mutates the TEST proves much less,
      because the failure being guarded against is CI gaining a check.
      KNOWN LIMITS, both deliberate and both worth writing down because a guard's blind
      spots are what make it trustworthy:
      1. It compares tool NAMES, so it cannot catch SCOPE divergence — the
         `ruff scripts/` vs `ruff scripts/ tests/` half of this very incident. The second
         test covers ruff specifically; a general argv comparison is the follow-up if
         another tool grows path arguments.
      2. It only extracts tools invoked through a uv/uvx runner (`uvx`, `uv run`,
         `uv tool run`) — a BARE command in ci.yml is skipped. Today that is exactly one
         step, `shellcheck scripts/dispatch.sh git-hooks/pre-push`, and it is NOT a
         divergence: publish.py Gate 2f runs shellcheck already. But a FUTURE bare-command
         check added to CI would slip past this test silently, which is the same shape as
         the defect it exists to catch. Widening `_tool_from_tokens` to treat a bare
         first token as a tool (with an explicit non-tool skip set) is the fix when that
         happens.

      SEPARATE FINDING while checking limit 2 — another false parity claim, same family
      as the mypy one this card already corrected: publish.py's Gate 2f describes itself
      as "parity with ci.yml **Mega-Linter BASH_SHELLCHECK**", but ci.yml's Lint job runs
      a plain `shellcheck` step, not Mega-Linter. The gate is doing the right thing
      against the wrong stated counterpart. Gate 2f also WARNs+skips when shellcheck is
      unavailable — the fail-open pattern rejected for pyright above; whether it should
      change is the same open question, with lower stakes.
- [ ] The CLAUDE.md sentence describing the gate's checkers is updated once the gate changes.

## The divergence is wider than pyright — measured 2026-09-04

Pyright is what bit, but it is not the only gap. Comparing what publish 3.4.14
actually ran (`/tmp/publish6.txt`, the `$` command echoes) against
`.github/workflows/ci.yml`:

| check | publish gate | CI |
|---|---|---|
| ruff | `scripts/` only | `scripts/ tests/` |
| pyright | **absent** | `uvx --with pyright pyright` (whole project, blocks merge) |
| mypy | `scripts/ --ignore-missing-imports` | **absent** (gate-only, fine — a superset) |
| pytest | `tests/ -x -q -n auto --dist loadgroup` | `-m "not integration"` PLUS a separate serial `-m integration` run |
| shellcheck | absent | "Lint shell scripts" |
| hooks.json validation, dispatch smoke-run, per-hook smoke-run, per-detector strict-run | absent | present |
| memgrep build + staged-binary run | absent | present |

SCOPE OF THIS MEASUREMENT: the gate column comes from ONE invocation — the
`--patch` run on `main` of 2026-09-04 — read from that run's own `$` command
echoes, which is the gate's record of what it executed rather than a reading
of what it intends to. It is NOT verified invariant across bump types,
branches, or env overrides; if `publish.py` branches its check set on any of
those, other paths may differ. The load-bearing claim needs no such
generalisation: on the run that produced the release CI rejected, the gate
ran no pyright at all.

So the gate is NOT a superset of CI, and "add pyright" fixes one row of a
seven-row table. The ruff row matters immediately: the gate lints only
`scripts/`, and all seven of today's pyright errors were in `tests/` — the
directory the gate's ruff does not read either.

## The ordering defect, which is the bigger half

`publish.py` bumps, tags, pushes, creates the GitHub release, and runs an
install smoke test — all before CI has rendered a verdict on the pushed
commit. So every defect CI catches is caught after the artifact is public and
installable. On 2026-09-04 the release existed, was installed to user scope,
and the janitor daemon had already respawned onto it before anyone knew CI
was red.

Making the gate a superset of CI narrows the window; it does not close it,
because the gate runs on a local tree and CI runs on the pushed commit under
different load — which is exactly how the other post-publish defect this day
(a load-dependent `git_utils` probe timeout) slipped through a green gate.
The closing move is to gate the RELEASE (not the push) on CI green for the
pushed sha.

Note this does not conflict with the working rule "after publish.py, do NOT
sit and watch CI" — that rule governs the operator's attention, not the
pipeline's ordering. A pipeline that waits costs the human nothing to watch.

## The pyright timeout — 900s, and two dead ends not to retry

The ceiling rests on ASYMMETRY, not measurement: the check fails closed on the only
sanctioned push path, so a tight value can kill a WORKING pyright and block the release,
while a generous one binds only when something is already wrong. A warm full analysis of
504 source files plus `tests/` takes 13-14s here; there is NO cold-cache measurement, so
do not tune the ceiling toward the warm figure.

Two cheap cold-path proxies were tried and both failed — don't repeat them:
- **`uvx --with pyright --refresh pyright`** measures nothing. It timed 13s against 14s
  for the same command without the flag, so it added no download at all. Why remains
  UNEXPLAINED — an open question, not a closed one.
- **Reading one cached archive** to conclude the analyzer is fetched at runtime was
  wrong: six pyright archives are cached and the "newer" version is among them. The wheel
  in fact bundles the analyzer (`pyright-internal.js`, 3M) plus 27M of `typeshed-fallback`
  stubs, all inside uv's cache; only the Node runtime is separate, provisioned by
  `node.py` via nodeenv into `get_cache_dir()/pyright-python/<version>`.

**The wider lesson this cost is on the USER-scope debugging-methodology page**: the
asymmetry argument was sufficient from the start, and every empirical justification
written after the number was chosen turned out false. See [[debugging-methodology-verify-before-concluding-mechanism-and-rule-claims]].

## Why the false CI-parity claims survived — an ORPHANED `.mega-linter.yml`

`.mega-linter.yml` is present and git-tracked at the repo root, and NO workflow runs
Mega-Linter (verified 2026-09-04 — `grep -rn mega-linter .github/workflows/` is empty).
So the gate's long-standing "parity with ci.yml Mega-Linter COPYPASTE_JSCPD" /
"BASH_SHELLCHECK" claims were never fabricated: they pointed at a real config file that is
still sitting there looking live, while the job that executed it was removed at some point
(`git log -S "Mega-Linter" -- .github/workflows/` finds the commits that touched it).

That is the mechanism behind the whole class: a config outliving its runner reads as
evidence the runner exists. Anyone auditing by looking for the config — rather than for a
workflow step that invokes it — concludes CI enforces it.

FOLLOW-UP, not done here: decide whether `.mega-linter.yml` should be deleted (nothing
runs it) or a workflow restored to run it. Leaving an orphaned linter config is drift that
will re-seed this exact confusion. NOT deleted tonight because it is a deliberate
repo-config decision, and because a `.gitignore`d-or-not config may still be consumed by
something outside this repo's workflows.

Coverage note measured while checking this: 8 shell files are tracked; ci.yml's
"Lint shell scripts" step names only `scripts/dispatch.sh` and `git-hooks/pre-push`, while
the gate's G2f rglobs every `*.sh`/`*.bash`. So 7 of 8 shell files are checked by the gate
or nowhere — the corrected warning text says exactly that.

## OPEN QUESTION FOR THE USER — should an unavailable pyright block the publish?

As shipped (2026-09-04, `82944b56`), a pyright that CANNOT RUN blocks the publish,
with no override. That is right for a check whose absence caused this card. But
`publish.py` is the ONLY sanctioned push path, so a degraded uv/PyPI registry now
means the project cannot ship at all until it recovers — and the pressure to hand-edit
`publish.py` would be highest exactly when that is most dangerous.

The argument FOR an override (`PUBLISH_PYRIGHT_UNAVAILABLE_OK=1`, default off,
registered in `stage_bypass_guard`'s documented exemptions so `[0/11]` prints it):
line 76's "no exceptions and no bypass flags" is about QUALITY — do not ship known-bad
code — not about operational controls, and the file already carries
`CPV_SKIP_GH_AUTH_CHECK=1` for exactly this shape, described in Gate 0's own docstring
as a bypass "on flaky networks". A tool's CDN being unreachable is a different category
from "my code has type errors, ship anyway", and only the latter is what line 76 forbids.

The argument AGAINST: both existing Gate 0 exemptions are documented as
"read-only overrides ... and never skip a gate" — `CPV_SKIP_GH_AUTH_CHECK` skips only a
PRECHECK, and auth must still work for the real push, so nothing is actually
unverified. A pyright override WOULD skip a real gate, deferring enforcement to CI on
the pushed commit — which is precisely the failure this card documents. It would also
be reachable on a night when someone wants it to be reachable.

NOT decided unilaterally: this is a policy call about the release pipeline, not a
defect with a right answer, and the fail-closed default is the safe state to leave it
in while it is undecided.

## Follow-up noted, not yet acted on

Clearing the 6 `reportOptionalSubscript` errors took five `assert x is not
None` narrowings in `tests/test_pane_actuate.py`, because `scripts/` was held
out of scope for that fix. No coverage was lost — those lines already
subscripted, so a genuine `None` would have raised `TypeError` and the tests
pass identically before and after, and no test in that file asserts a `None`
plan. Stated precisely, because the repetition is the whole argument: FOUR of the
five are the same narrowing on `fired[0][1]` in four different tests, and the
fifth is structurally different (`hard_plan`, i.e. `fired[-1][1]`, in a test
that first asserts an exact fire count). So it is four copies plus one, not
five copies — still the "enumerating call sites" shape this project keeps
getting bitten by. If `build_step_plan` cannot return `None` on those paths,
the honest fix is its ANNOTATION in `scripts/` and the four are standing in
for it. Read the sites and decide before the next publish.

(Five asserts clear six pyright errors because the one at line 88 narrows two
adjacent subscripts of the same expression — the counts differ legitimately.)

## Related
- The 7 errors themselves are being fixed separately; this card is about the GATE, not those errors.
- `pyproject.toml` lines ~45-58 and TRDD-BMDZK4RA for the deliberate mypy/pyright split.
