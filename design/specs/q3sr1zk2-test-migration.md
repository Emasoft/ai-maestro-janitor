# Spec: migrate test_jev_compact_cli.py from make_client/FakeJevClient to score_items_via_llm_ext

TRDD-Q3SR1ZK2 changed `scripts/jev_compact.py::cmd_compact` to call
`jc.score_items_via_llm_ext(items, digest, relevance_threshold=...)` instead of
`jc.score_items(items, digest, client, relevance_threshold=...)`. The `probe` command
STILL uses `make_client` — do NOT touch probe tests.

## Goal

Make all 29 failing `compact` tests pass by monkeypatching
`jev_compact.jc.score_items_via_llm_ext` instead of `jev_compact.make_client`.

## The helper to define

A previous worker referenced `_fake_scorer` in 14+ test call sites but never defined it.
Define it near `_keep_only` (around line 651). It wraps an answer function into the
`score_items_via_llm_ext` signature:

```python
def _fake_scorer(answer_fn):
    """Wrap a FakeJevClient-style answer_fn(state, questions, key)->float into a
    score_items_via_llm_ext-shaped callable (items, digest, *, relevance_threshold)->dict[str,Scores].

    Replaces the FakeJevClient(_keep_only('bug')) + make_client pattern: the old path
    called client.ask(state, questions) per batch with keys '<ref>:rel'; the new path
    calls score_items_via_llm_ext(items, digest) once. This helper preserves the
    per-item relevance decision by reading each item's text against answer_fn."""
    def _score(items, digest, *, relevance_threshold=0.5):
        from jev_compaction import Scores
        scored = {}
        for it in items:
            # answer_fn expects (state, questions, key); build a minimal state so
            # _keep_only (which reads state['items'][i]['text']) still works.
            state = {"items": [{"ref": it.id, "text": it.text}]}
            p = answer_fn(state, {}, f"{it.id}:rel")
            scored[it.id] = Scores(relevance=p, oversized=False, kept=p >= relevance_threshold)
        return scored
    return _score
```

IMPORTANT: verify `Scores` is imported/accessible at the call site. The test file already
does `import jev_compaction as jc`, so `jc.Scores` is available — use that instead of a
local import if cleaner.

## Migration patterns

### Pattern A: happy-path compact tests (most common)

BEFORE:
```python
client = FakeJevClient(_keep_only("bug"))
monkeypatch.setattr(jev_compact, "make_client", lambda: client)
```
AFTER:
```python
monkeypatch.setattr(jev_compact.jc, "score_items_via_llm_ext", _fake_scorer(_keep_only("bug")))
```

### Pattern B: _must_not_be_called tests (fast decline / no digest)

These assert scoring is never reached. BEFORE mocks `make_client` with a function that
raises AssertionError. AFTER: monkeypatch `score_items_via_llm_ext` with a function that
raises AssertionError (same intent — if called, fail the test):
```python
def _must_not_be_called(*_args, **_kwargs):
    raise AssertionError("score_items_via_llm_ext must not be called on a fast decline")
monkeypatch.setattr(jev_compact.jc, "score_items_via_llm_ext", _must_not_be_called)
```

### Pattern C: error-path tests (_FailingScoreClient / _BudgetBustingClient)

These raise JevUnavailableError / JevBudgetError from the client's `.ask()`. The new code
catches `JevBudgetError` and `JevError` (parent of JevUnavailableError) in cmd_compact —
same branches. So the patched `score_items_via_llm_ext` must raise the SAME exception:

BEFORE:
```python
class _FailingScoreClient:
    def ask(self, state, questions):
        raise JevUnavailableError("simulated 503", status=503, cause="HTTP 503")
monkeypatch.setattr(jev_compact, "make_client", lambda: _FailingScoreClient())
```
AFTER:
```python
def _failing_score(*_args, **_kwargs):
    raise JevUnavailableError("simulated 503", status=503, cause="HTTP 503")
monkeypatch.setattr(jev_compact.jc, "score_items_via_llm_ext", _failing_score)
```

Same for _BudgetBustingClient → raise JevBudgetError.

### Pattern D: test_compact_inject_out_scores_exactly_once

This wraps the real `jc.score_items` to count calls. Change to wrap
`jc.score_items_via_llm_ext`:
```python
real_score = jc.score_items_via_llm_ext
def _counting_score(*args, **kwargs):
    calls.append(1)
    return real_score(*args, **kwargs)
monkeypatch.setattr(jev_compact.jc, "score_items_via_llm_ext", _counting_score)
```
But this test ALSO sets `make_client` — remove that line and replace with a
`_fake_scorer(_keep_only("bug"))` patch on `score_items_via_llm_ext` FIRST, then wrap it.
Actually simpler: just use `_fake_scorer` and count calls on the wrapper:
```python
calls = []
real_scorer = _fake_scorer(_keep_only("bug"))
def _counting_score(*a, **kw):
    calls.append(1)
    return real_scorer(*a, **kw)
monkeypatch.setattr(jev_compact.jc, "score_items_via_llm_ext", _counting_score)
```

### Pattern E: test_compact_never_sends_prose_to_jev (trickiest)

This test asserts (1) only tool items are scored (`asked == ["u-2:0"]`) and (2) prose
text never appears in what's sent to Jev, by inspecting `client.calls`.

With `score_items_via_llm_ext` there is no client. The spy must capture items directly:
```python
asked = []
real_scorer = _fake_scorer(lambda *_a: 0.9)  # stands in for FakeJevClient.constant(0.9)
def spy(items, digest, *, relevance_threshold=0.5):
    asked.extend(it.id for it in items)
    sent_texts.extend(it.text for it in items)
    return real_scorer(items, digest, relevance_threshold=relevance_threshold)
monkeypatch.setattr(jev_compact.jc, "score_items_via_llm_ext", spy)
```
Then assert `asked == ["u-2:0"]` and `not {owner, reply, control} & set(sent_texts)`.

### Pattern F: test with _score_items_with_one_blocked (line ~790)

This wraps `jc.score_items` to mark one item blocked. Change to wrap
`score_items_via_llm_ext`:
```python
real_score = jc.score_items_via_llm_ext  # or _fake_scorer(_keep_only("bug"))
def _score_with_one_blocked(items, digest, *, relevance_threshold=0.5):
    scores = real_score(items, digest, relevance_threshold=relevance_threshold)
    # mark one item blocked
    ...
    return scores
monkeypatch.setattr(jev_compact.jc, "score_items_via_llm_ext", _score_with_one_blocked)
```

## Tests NOT to migrate (probe tests)

Lines 576-650, 968-986: `test_probe_ok`, `test_probe_make_client_raises`,
`test_probe_ask_raises`, `test_probe_ask_raises_429`, `test_probe_ask_raises_unreachable`.
These test `cmd_probe` which STILL uses `make_client`. Leave them unchanged.

## Cleanup

- Remove the `from jevctx.testing import FakeJevClient` import IF no test uses it after
  migration. Check first — if any probe test or other test still uses it, keep it.
- Remove stale `client = FakeJevClient(...)` + `make_client` lines from already-migrated
  tests (lines ~1290, 1325, etc.) IF they still have them alongside the
  `score_items_via_llm_ext` patch.
- Update the module docstring (line 6) that says tests monkeypatch `make_client`.

## Verification

```bash
cd /Volumes/EmaUITEK4TBSSD/Code/AI-MAESTRO-JANITOR/ai-maestro-janitor
uv run ruff check tests/test_jev_compact_cli.py
uv run pytest tests/test_jev_compact_cli.py -q
```
All 75 tests must pass, ruff must be clean.
