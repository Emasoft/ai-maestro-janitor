# Why `pyrightconfig.json` looks the way it does

The config file itself carries **no comments**, deliberately. The rationale lives here instead.

## `venvPath` + `venv` are load-bearing

Without them pyright resolves imports against its **own** interpreter and cannot see the project
venv. `import pytest` alone then accounts for 149 of 194 missing-import errors under `tests/` —
config noise that reads exactly like 149 real defects and would send someone "fixing" them.

`pythonVersion` stays `3.11` (the floor the scripts declare in their PEP 723 blocks) even though
the venv is 3.12, so the gate checks against the version the scripts promise to run on.

## Why there are no comments in the file

Two tools read this path and they disagree about what JSON is:

| form | pyright | CPV's validator |
|---|---|---|
| `"//": "note"` key | ⚠ `Config contains unrecognized setting "//"` on every run | fine |
| `// line comment` | fine | ✗ **MAJOR** — `JSON syntax error in pyrightconfig.json` |
| no comments | fine | fine |

Both were tried, in that order, on 2026-08-13. The `"//"` key printed a permanent warning on a
type-check gate — the kind of self-inflicted noise that teaches a reader to ignore the tool's
output. Replacing it with real line comments silenced pyright and **blocked the publish**: CPV
parses this file as strict JSON, and a MAJOR finding is a release blocker.

So the file is strict, comment-free JSON and the explanation lives in this document. Do not
re-add either comment form.

**The general lesson, which is the reason this page exists at all:** a config file read by more
than one tool has to satisfy the strictest parser among them, and "my linter accepts it" is not
evidence that the others do. The fix for tool-A noise was verified against tool A only, and it
broke tool B in a way that surfaced 20 minutes later at the release gate.
