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
  gate. No other byte differs. The eight upstream test files kept under
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
