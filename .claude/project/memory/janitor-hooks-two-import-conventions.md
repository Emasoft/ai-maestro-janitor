---
name: janitor-hooks-two-import-conventions
description: "writing a new janitor hook / ModuleNotFoundError: No module named 'state' / my hook dies on import but the detectors work / from lib import X fails at runtime / which sys.path entries does a hook need / why does dispatch.py import differently than the hooks"
ocd: 2026-07-11
lmd: 2026-07-17
metadata:
  node_type: memory
  type: project
  tier: component
  originSessionId: c8a95d7e-048f-4c47-ae33-1dfacbcab3b1
---

# This codebase has TWO import conventions — a hook must put BOTH dirs on sys.path

`scripts/lib/` is importable two ways, and they are **not interchangeable**:

| caller | `sys.path` gets | import form |
|---|---|---|
| detectors, `dispatch.py`, `fleet_status.py` | `scripts/lib/` | `import state`, `import global_state` (bare) |
| hooks | `scripts/` | `from lib import state, global_state` (package) |

The trap: **a `lib` module may bare-import a sibling** — `global_state.py` does `import
state`. That is an ABSOLUTE import, and it resolves only if `scripts/lib/` is *itself* on
`sys.path`. Detectors get that for free. A hook loading the same module as `lib.global_state`
does **not** — so the module raises `ModuleNotFoundError: No module named 'state'` at IMPORT
time, and the hook dies before its first statement.

**So a hook MUST add BOTH entries:**

```python
sys.path.insert(0, str(Path(plugin_root) / "scripts"))          # for `from lib import …`
sys.path.insert(0, str(Path(plugin_root) / "scripts" / "lib"))  # for a lib module's bare sibling import
```

Do not "simplify" by dropping the second line. It is not a lint nit — omitting it is what
killed `on-session-start.py` for three weeks (TRDD-EG2HSPMQ, commit `b28c53a`). The first
line is also load-bearing for a different reason: the CPV hook validator's local-sibling
detector recognises the `from lib import …` package form, which is why hooks use it at all.

**Why:** `scripts/lib/__init__.py` makes `lib` a package, so both forms *look* valid. Nothing
in the code says which convention a given module tolerates — a module that only imports stdlib
(`memory_scopes`) is safe under both; one that bare-imports a sibling (`global_state`) is not.

**How to apply:**
- Writing a new hook → paste both `sys.path` lines.
- Writing a new `lib` module that a hook may import → guard its sibling imports the way
  `trdd_common.py` does (`try: from lib import X / except ImportError: import X`), so it is
  safe under BOTH conventions regardless of who loads it.
- `tests/test_hooks_execute.py` executes every hook as a subprocess and will fail loudly if
  this is ever gotten wrong again — see [[feedback-test-the-entry-point-the-way-the-platform-runs-it]].

## See also

- [[janitor-compaction-floor-gate]] — `on-stop-proactive-compact.py` and its tests sit on this
  exact fault line: patching bare `state` instead of `lib.state` let a test run the REAL
  compact_trigger and type `/compact` into the developer's own pane (2026-07-17).

## Notes and lessons learned

[^1]: [ocd:2026-07-11 lmd:2026-07-11] The omission was DELIBERATE and documented: a comment
  said "Put scripts/ on sys.path (NOT scripts/lib/)" to satisfy the CPV hook validator. It read
  as a style choice, so nobody questioned it — but it was load-bearing in the opposite
  direction. Lesson: when a comment explains why something is ABSENT, it should also say what
  breaks if it is added back, or the next reader cannot tell a constraint from a preference.
  Adding the path is additive: the package form the validator wants is unchanged.
