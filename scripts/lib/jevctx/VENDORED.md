# Vendored: jevctx

- Source: https://github.com/Waxmell114514/jev-compaction
- Commit: `6d33376a759b95dc53b2169eed2cad32842036ca`
- Vendored: 2026-09-22
- License: MIT (`LICENSE` in this directory, copied verbatim)
- Scope: `jevctx/*.py` only — `tools/`, `docs/`, `demo.py` and the upstream
  `tests/` tree were NOT copied (out of scope for this project; see
  `tests/jevctx/` in the repo root for the subset of upstream tests that
  passed unchanged under this project's pytest and were kept). Three upstream
  test files were left out because they import `demo.py`, which was not
  vendored: `test_demo.py`, `test_showcase_data.py`, `test_check.py`.
- Modified: `jev.py` — one blank line removed between two import groups
  (`ruff check --fix`, rule I001, import-sort) to pass this project's lint
  gate; and (2026-09-22, commit 40cc06d1 follow-up) `types.py`'s
  `JevUnavailableError` gained three public `__init__` kwargs/attributes —
  `status: int | None`, `cause: str`, `retry_after: float | None` — see the
  "unavailable-vs-unreachable-vs-rate-limited" section below for why. The
  eight upstream test files kept under
  `tests/jevctx/` (see below) got the same one-line fix for the same reason
  (`test_context.py`, `test_jev.py`, `test_ledger.py`, `test_pipeline.py`,
  `test_scorer.py`, `test_segments.py`, `test_shadow.py`, `test_store.py`).
  Two more fixes, both mypy (`uv run mypy scripts/ --ignore-missing-imports`):
  `check.py:123` got a `# type: ignore[arg-type]` on the nested
  `getattr(usage, "input_tokens", 0)` call — mypy's overload resolution for a
  3-arg `getattr` on an `Any`-typed first argument here picks an overload
  requiring a `bool` default and flags the literal `0`; this is a mypy
  false positive against otherwise-correct code, not a real type error, so a
  narrow ignore was the minimal fix. `shadow.py:186`'s `by_action =
  dict.fromkeys(_ACTIONS, 0)` got an explicit `: dict[str, int]` annotation —
  without it mypy infers the dict's key type as the narrow
  `Literal["kept","elided","injected","skipped"]` from `_ACTIONS`, and then
  correctly rejects indexing it with the plain `str` `action` variable two
  lines below (a real type mismatch upstream, `action` legitimately can be
  any `str` via `actions.get(entry.item_id, entry.action)`); widening the
  annotation to `str` keys is the accurate fix, not a suppression. One more
  fix, pyright only (`uvx --with pyright pyright scripts/`): `check.py`'s
  `run_check` sample asks one `Noul`/`Choice`/`Score` question each and reads
  back `answers["is_question"].noul` / `.topic.choice` / `.urgency.score` —
  each `answers[key]` is typed as the `Answer` union
  (`NoulAnswer | ChoiceAnswer | ScoreAnswer`), which pyright cannot narrow
  from the question type it was asked with (mypy passed this file clean; a
  weaker union-attribute check on its side, not a real difference in
  correctness). Added three `typing.cast()` calls naming which concrete
  `Answer` subtype each of this SPECIFIC sample's three keys is known to
  return — the same assumption the original code already made silently.
  None of these four fixes were reported upstream (no issue filed against
  https://github.com/Waxmell114514/jev-compaction) — they are local-only,
  vendored-copy patches; re-vendoring a future commit should re-check whether
  upstream has since fixed the same spots independently before re-applying.
- Additions: `openrouter.py` (`OpenRouterJevClient`, not upstream — added here
  for TRDD-541CBN36) and `provider.py` (provider-selection helper, not
  upstream — added here for TRDD-541CBN36).

Why vendored instead of a dependency: `jevctx` is not published to PyPI: it
ships as a plain package inside its own repo. This project's hook/detector
scripts are PEP-723 stdlib-only single files that vendor their own
dependencies rather than pull them from a registry — vendoring `jevctx`
(source-only, MIT) matches that existing convention instead of introducing a
new one.

## Trimmed to card 3's needs (2026-09-22, TRDD-541CBN36 card 2 follow-ups)

Removed `check.py`, `context.py`, `ledger.py`, `pipeline.py`, `segments.py`,
`shadow.py`, `store.py` — the agent-loop / context-buffer half of upstream
(`ContextBuffer`, `CacheLedger`, `admit`/`retrieve`/`expand` gate pipeline,
segment detection, shadow-mode logging, the in-memory/JSONL stores). Card 3
(the compacted-context scorer + CLI) only needs the scoring half: `budget.py`,
`jev.py`, `scorer.py`, `tokens.py`, `types.py`, `testing.py`, plus this
project's own `openrouter.py`/`provider.py`. Removed for scope, not for a
defect in the removed code — `git log` recovers commit `4b8ba762` (the one
that added all of it) if a later card needs the agent-loop half after all;
re-vendor from the same upstream commit `6d33376a759b95dc53b2169eed2cad32842036ca`
rather than resurrecting the deleted copy, in case upstream has moved since.

Matching test files removed from `tests/jevctx/`: `test_check.py` (already
absent, see above), `test_context.py`, `test_ledger.py`, `test_pipeline.py`,
`test_segments.py`, `test_shadow.py`, `test_store.py`, and `test_end_to_end.py`
(exercised the removed modules together). Kept: `test_budget.py`, `test_jev.py`,
`test_scorer.py`.

`RETRIEVE_QUESTION` (a `Noul` constant card 3's spec names directly) lived only
in the now-removed `pipeline.py` — it is NOT available from this trimmed
package. Whoever implements card 3 either re-vendors `pipeline.py` or defines
an equivalent `Noul` locally; this is a known gap, not an oversight.

`__init__.py`'s import list and `__all__` were trimmed to match (kept:
`Batch`, `BudgetPlanner`, `HttpJevClient`, `RateLimiter`, `RetryPolicy`,
`build_state`, `score_items`, `score_map`, `FakeJevClient`, `estimate_tokens`,
and the `types.py` re-exports still referenced by the kept modules); the two
mypy/pyright fix notes above for `check.py`/`shadow.py` are now moot (the
files are gone) but left in place as history rather than deleted, per this
project's commit-discipline convention of superseding rather than erasing.

## `jev.py`/`openrouter.py`: unavailable-vs-unreachable-vs-rate-limited (2026-09-22, commit 40cc06d1 follow-up, supersedes the private-subclass approach below)

**Superseded 2026-09-22.** The original fix (commit 1e36e9bc, kept verbatim
further down for history) avoided touching `types.py`'s "report rather than
edit" convention by raising a local, additive subclass,
`_JevUnavailableDetail(JevUnavailableError)`, from `jev.py`/`openrouter.py`.
That subclass turned out to be the wrong tradeoff: a private class defined in
one vendored module and imported by a sibling vendored module crosses the
same "written against `types.py` in parallel" boundary the convention exists
to protect, just one file over instead of in `types.py` itself, and
`jev_compact.py` had to read the two fields defensively
(`getattr(exc, "status", _MISSING)`) because nothing guaranteed every
`JevUnavailableError` carried them. The owner's follow-up instruction was to
put the fields on the base class instead: `JevUnavailableError` itself (in
`types.py`) now takes `status: int | None = None`, `cause: str = ""`, and
`retry_after: float | None = None` as `__init__` kwargs, all stored as
public attributes with safe defaults — so *every* `JevUnavailableError`
instance carries them, no subclass, no `getattr`, no `_MISSING` sentinel.
`jev.py` and `openrouter.py` raise `JevUnavailableError` directly at every
site that used to raise `_JevUnavailableDetail`; `_detail_from_last_error()`
(defined once in `jev.py`, imported by `openrouter.py`) now returns a
3-tuple (`status, cause, retry_after`) instead of 2, reading them straight
off `isinstance(last_error, JevUnavailableError)` — the legitimate public-API
check that check remains, since `jev_compact.py`'s classifier still has to
tell a `JevUnavailableError` apart from `JevAuthError`/`JevBudgetError`/a
bare transport exception. `retry_after` is new: it carries the server's own
`Retry-After` header value (seconds) for a 429/5xx response so
`jev_compact.py` can give a `kind="rate_limited"` (429, a per-key limit, not
a whole-endpoint outage) probe stamp a much shorter fast-decline TTL than a
real `kind="unavailable"` (5xx) outage earns — see `jev_compact.py`'s own
module docstring for the exit-code/kind table. Not reported upstream — this
diverges from upstream's `JevUnavailableError` (which takes no kwargs at
all), but the defaults mean every upstream call site
(`JevUnavailableError("message")`) still works unchanged; re-vendoring a
future upstream commit needs to re-apply this `__init__` addition to
`types.py` the same way the import-sort fix above is re-applied.

### Superseded text, kept for history (commit 1e36e9bc, no longer accurate)

`jevctx.types.JevUnavailableError` (upstream, unmodified) collapses two
different failure shapes into one exception: a 429/5xx *response* (Jev itself
is degraded — a true, machine-wide outage) and a *transport* failure — no
response at all (`httpx.TransportError`: connect/DNS/TLS/read timeout — can be
local to this one machine or lane, e.g. the daemon's Python missing a CA
bundle, TRDD-X6I04SAO). `jev_compact.py`'s probe-stamp decline gate needs to
tell these apart (declining every other shell's compaction over a purely
local networking problem is wrong), but `types.py` says of itself "if
something here is wrong or missing, report it rather than editing it" — so
rather than editing the shared `JevUnavailableError` base in `types.py`, both
`jev.py` and (separately) `openrouter.py` now raise a **local, additive**
subclass, `_JevUnavailableDetail(JevUnavailableError)`, carrying `status: int
| None` (the HTTP status when a response existed, `None` for a transport
error) and `cause: str` (the exception class + message). `except
JevUnavailableError` callers are unaffected (subclass instances still match);
`jev_compact.py` reads the two new fields defensively via `getattr(...,
"status", _MISSING)`, so a bare `JevUnavailableError` raised by test code or a
future jevctx version without the attribute still falls back to the old,
conservative "assume outage" classification. `_detail_from_last_error()`
carries the inner status/cause forward to the final "retries exhausted"
raise instead of losing it, in both `jev.py::HttpJevClient.ask` and
`openrouter.py::OpenRouterJevClient.ask` (which has its own, separate retry
loop — not shared with `jev.py`, so it needed the same treatment twice). Not
reported upstream — this is a local-only addition, not a divergence from
upstream's `JevUnavailableError` semantics, and does not change any upstream
byte.

## Local changes to vendored tests (2026-09-23, pyright-gate fix)

`tests/jevctx/test_jev.py` and `tests/jevctx/test_scorer.py` needed
typing-only fixes to pass this project's `uvx --with pyright pyright` gate;
none change what any test asserts or its ability to fail. Re-applying these
after a future re-vendor: grep each file for the symbol named below.

- `test_jev.py::test_request_shape_matches_spec` — pyright
  `reportIndexIssue` (`"__getitem__" method not defined on type "object"`) on
  `body["model"]`/`body["state"]`/`body["questions"]`: `body` came from a
  `dict[str, object]`-typed `captured` dict, so its value type was `object`.
  Added `assert isinstance(body, dict)` right after `body =
  captured["body"]`, before the three subscripts — same assertions, same
  three equality checks, now type-narrowed first.
- `test_jev.py::test_429_then_200_succeeds_request_sent_twice`,
  `test_retry_after_seconds_is_honoured`,
  `test_retry_after_is_capped_at_the_timeout_budget`,
  `test_529_is_retried_like_429` — pyright `reportAssignmentType` (`Type
  "Handler" is not assignable to declared type "(request: Request) ->
  Response"`) on `handler, calls = _counting(handler)`: pyright infers the
  local `handler`'s declared type from its own `def handler(request: ...)
  -> ...` statement (named, non-positional-only parameter), and rejects
  reassigning it to `_counting`'s `Handler = Callable[[Request], Response]`
  return value (positional-only parameters). Renamed the reassignment
  target to `counting_handler` in each of the four tests and used that name
  in the following `httpx.MockTransport(...)` call instead of reusing
  `handler` — same object, same call, no assertion changed.
- `test_scorer.py::test_question_instructions_name_the_ref` — pyright
  `reportAttributeAccessIssue` (`Cannot access attribute "true"` on
  `Choice`/`Score`) on `question.true`: `question` comes from
  `client.calls[0].questions.items()`, typed as the `Question = Noul |
  Choice | Score` union, but the test's `QUESTION` fixture is always a
  `Noul` in this Question, so the assertion was always true; pyright just
  couldn't see that from the union type. Added `assert isinstance(question,
  Noul)` immediately before `assert question.true == QUESTION.true` — the
  equality check itself is unchanged.
