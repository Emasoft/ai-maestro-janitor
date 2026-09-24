---
name: janitor-hooks-two-import-conventions
description: "writing a new janitor hook / ModuleNotFoundError: No module named 'state' / my hook dies on import but the detectors work / from lib import X fails at runtime / which sys.path entries does a hook need / why does dispatch.py import differently than the hooks / why do detectors use bare import state but hooks use from lib import state / what two sys.path entries must a hook add / global_state.py bare-imports its sibling state module / on-session-start.py died silently for three weeks over this / why does the CPV hook validator require the from lib import form / how to write a lib module safe under both import conventions / trdd_common.py try except import pattern / does tests/test_hooks_execute.py catch a missing sys.path entry / on-stop-proactive-compact.py patched bare state instead of lib.state and typed /compact into the developer's pane"
ocd: 2026-07-11
lmd: 2026-09-24
metadata:
  node_type: memory
  type: project
  tier: component
  originSessionId: c8a95d7e-048f-4c47-ae33-1dfacbcab3b1
publish-globally: false
---

# This codebase has TWO import conventions — a hook must put BOTH dirs on sys.path

^JQAFHJ75 [desc:"Two import conventions coexist: detectors/dispatch.py bare-import scripts/lib modules; hooks use from-lib-import; a lib module bare-importing a sibling breaks only under the hook form.", keywords:"two_import_conventions_scripts_lib bare_import_vs_from_lib_import detectors_dispatch_bare_import hooks_from_lib_import_package_form global_state_bare_imports_sibling_state modulenotfounderror_no_module_named_state hook_dies_at_import_before_first_statement"]
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

^WF1IT6NN [desc:"Fix: a hook must add BOTH sys.path entries (scripts/ and scripts/lib/), not just the package-form one; dropping the second line killed on-session-start.py for weeks (TRDD-EG2HSPMQ).", keywords:"hook_must_add_both_syspath_entries sys_path_insert_scripts_and_scripts_lib do_not_drop_the_second_line on_session_start_py_died_three_weeks trdd_eg2hspmq commit_b28c53a cpv_hook_validator_requires_from_lib_import_form"]
**So a hook MUST add BOTH entries:**

```python
sys.path.insert(0, str(Path(plugin_root) / "scripts"))          # for `from lib import …`
sys.path.insert(0, str(Path(plugin_root) / "scripts" / "lib"))  # for a lib module's bare sibling import
```

Do not "simplify" by dropping the second line. It is not a lint nit — omitting it is what
killed `on-session-start.py` for three weeks (TRDD-EG2HSPMQ, commit `b28c53a`). The first
line is also load-bearing for a different reason: the CPV hook validator's local-sibling
detector recognises the `from lib import …` package form, which is why hooks use it at all. [^1]

^1J023A3O [desc:"Why both forms look valid: scripts/lib/__init__.py makes lib a package, so nothing signals which convention a module tolerates; stdlib-only modules are safe under both, sibling-importers are not.", keywords:"why_both_forms_look_valid lib_init_py_makes_lib_a_package no_signal_which_convention_tolerated stdlib_only_module_safe_under_both sibling_bare_importer_not_safe_under_both memory_scopes_safe_global_state_not_safe"]
**Why:** `scripts/lib/__init__.py` makes `lib` a package, so both forms *look* valid. Nothing
in the code says which convention a given module tolerates — a module that only imports stdlib
(`memory_scopes`) is safe under both; one that bare-imports a sibling (`global_state`) is not.

^QKZECOMJ [desc:"How to apply: new hooks paste both sys.path lines; new lib modules a hook may import guard sibling imports with trdd_common.py's try/except pattern; every hook runs as a subprocess in tests.", keywords:"how_to_apply_writing_a_new_hook paste_both_syspath_lines guard_sibling_imports_try_except_pattern trdd_common_py_import_guard_pattern test_hooks_execute_py_subprocess_check catches_regression_loudly_if_wrong_again"]
**How to apply:**
- Writing a new hook → paste both `sys.path` lines.
- Writing a new `lib` module that a hook may import → guard its sibling imports the way
  `trdd_common.py` does (`try: from lib import X / except ImportError: import X`), so it is
  safe under BOTH conventions regardless of who loads it.
- `tests/test_hooks_execute.py` executes every hook as a subprocess and will fail loudly if
  this is ever gotten wrong again — see [[feedback-test-the-entry-point-the-way-the-platform-runs-it]].


^ATOM-ZXLI-IB5B [desc: "A hook's cheap early-return check (e.g. the cron marker) should run BEFORE any heavy import, not after; on-prompt-submit.py used to import state before checking _is_cron_marker, paying ~50-60ms per no", keywords: hook_is_slow_on_a_cron_fire cheap_early_return_before_heavy_imports why_does_a_heartbeat_fire_cost_extra_milliseconds is_cron_marker_check_placement import_state_at_module_top_wastes_time_on_a_no-op hook_startup_cost_under_load should_a_hook_import_lazily where_should_the_cron_marker_check_go fail-fast_on_a_broken_state.py_import hook_authoring_performance_checklist, ocd: 2026-09-24, lmd: 2026-09-24]

As of 2026-09-24 (measurement reports: LOCAL scope). A cron-marker check (_is_cron_marker in on-prompt-submit.py) is a CHEAP early-return: on a bare heartbeat cron fire the hook should do nothing and exit fast. But import state sat at module top, BEFORE that check, so every heartbeat fire paid the ~50-60ms cost of state.py's own imports for a pure no-op -- small alone, but on a host running many armed sessions in the same burst this is exactly the per-hook cost that a CPU-run-queue-wait burst turns into a spurious timeout (see the load-average-50-117 fact on janitor-beat-tasks-and-limitations). Fixed and LANDED in commit 9efd5df3 (part of 7ed4cdeb's stagger follow-up): the state import was moved BELOW the _is_cron_marker check AND OUTSIDE the try/except that guards the best-effort state.bump_user_presence() write -- not inside it -- because state.py failing to import at all should surface as a real error (fail-fast), not silently no-op like the write it guards. [^2] [^3]

## See also

- [[janitor-compaction-floor-gate]] — `on-stop-proactive-compact.py` and its tests sit on this
  exact fault line: patching bare `state` instead of `lib.state` let a test run the REAL
  compact_trigger and type `/compact` into the developer's own pane (2026-07-17).
- [[jev-compaction]]

## Notes and lessons learned

[^1]: [id:ATOM-MG05-0017, status:valid, keywords:"comment_explaining_absence_needs_consequence constraint_vs_preference_comment scripts_on_syspath_not_lib", ocd:2026-07-11, lmd:2026-07-11] The omission was DELIBERATE and documented: a comment
  said "Put scripts/ on sys.path (NOT scripts/lib/)" to satisfy the CPV hook validator. It read
  as a style choice, so nobody questioned it — but it was load-bearing in the opposite
  direction. Lesson: when a comment explains why something is ABSENT, it should also say what
  breaks if it is added back, or the next reader cannot tell a constraint from a preference.
  Adding the path is additive: the package form the validator wants is unchanged.
[^2]: [id: ATOM-H673-OO2L, status: valid, desc: "Guardrail: put a hook's cheap early-return check before any heavy import, and import lazily inside the branch that needs it.", keywords: "do_not_import_heavy_modules_before_the_cheap_check hook_pays_import_cost_on_every_no-op_fire cron_marker_check_must_come_first why_is_my_hook_slow_under_load hook_timeout_under_contention lazy_import_in_a_hook state.py_import_ordering writing_a_new_janitor_hook_performance fail_loud_on_a_broken_required_import best-effort_try_except_swallows_import_errors", ocd: 2026-09-24, lmd: 2026-09-24] DO NOT import a heavy lib module (state, global_state, etc.) at a hook's module top before its cheap early-return check, BECAUSE every no-op fire (e.g. a bare cron heartbeat) then pays that import's full cost for nothing -- on-prompt-submit.py paid ~50-60ms per fire this way, and under a contended host that is exactly the per-hook margin a CPU-run-queue-wait burst turns into a spurious 2-3s timeout. DO put the cheap check (the cron-marker test) first, and import only inside the branch that actually needs it -- except a module whose absence must fail loudly (state.py here), which stays outside the best-effort try/except it would otherwise silently disappear into.
[^3]: [id: ATOM-KKIF-OJLA, status: valid, supersedes: ATOM-ZXLI-IB5B, desc: "Correction: 9efd5df3 moved the state import OUTSIDE the best-effort try/except, not inside it -- a broken state.py now fails loudly.", keywords: "is_the_state_import_inside_or_outside_the_try does_a_broken_state.py_fail_loudly_now 9efd5df3_landed_commit import_after_the_cheap_check never_import_inside_a_swallowing_except fail_loud_on_a_broken_required_import hook_is_slow_on_a_cron_fire cheap_early_return_before_heavy_imports on-prompt-submit_import_ordering writing_a_new_janitor_hook", ocd: 2026-09-24, lmd: 2026-09-24] DO NOT claim the state import moved INSIDE the breadcrumb try/except, BECAUSE 9efd5df3 did the opposite: it moved the import OUTSIDE that try/except entirely (still after the cheap cron-marker check), precisely so a broken state.py fails LOUDLY instead of being silently swallowed. DO import after the cheap check, but never inside an except that swallows everything -- a module that fails to import must fail loudly (9efd5df3). SUPERSEDED BODY: reports/hook-timeout/20260924_184119+0200-stagger-followup.md item 3, and reports/hook-timeout/20260924_175736+0200-startup-timing.md. A cron-marker check (_is_cron_marker in on-prompt-submit.py) is a CHEAP early-return: on a bare heartbeat cron fire the hook should do nothing and exit fast. But import state sat at module top, BEFORE that check, so every heartbeat fire paid the ~50-60ms cost of state.py's own imports for a pure no-op -- small alone, but on a host running many armed sessions in the same burst this is exactly the per-hook cost that a CPU-run-queue-wait burst turns into a spurious timeout (see the load-average-50-117 fact on janitor-beat-tasks-and-limitations). Fixed (part of 7ed4cdeb's stagger follow-up, still uncommitted as of 2026-09-24): the state import was moved BELOW the _is_cron_marker check -- but only inside the try/except that already guarded the best-effort state.bump_user_presence() write, not above it, because state.py failing to import at all should surface as a real error (fail-fast), not silently no-op like the write it guards.
