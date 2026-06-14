# Janitor architecture — heartbeat dispatcher design

Deep reference for how `/janitor-arm` wires the heartbeat cron, why the
auto-rolling stub indirection exists, and how the pieces interact across
plugin updates. Load this file when the SKILL.md summary isn't enough —
e.g. when debugging "why didn't the cron pick up the new version?" or
when designing a follow-up change to the dispatcher contract.

## Table of Contents

- [Why the stub exists](#why-the-stub-exists)
- [Operational rules](#operational-rules)
- [Responsibility split and safety](#responsibility-split-and-safety)
- [Known limitations](#known-limitations)

## Why the stub exists

Before v0.4.11, `/janitor-arm` baked an absolute, version-stamped path into the cron prompt:

```text
[janitor-heartbeat]
/Users/<u>/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/0.4.10/scripts/dispatch.py
Surface stdout verbatim. ...
```

Two failure modes followed:

1. **The cron kept firing the OLD code after a plugin update.** When `claude plugin update` landed `0.4.11` in the cache, the cron's baked path still pointed at `0.4.10/scripts/dispatch.py`. The user had to run `/janitor-arm` again to switch.
2. **Cache GC could remove the cron-referenced version.** Per the Claude Code plugin spec, orphaned version directories are cleaned up about 7 days after they stop being the active version. If a user didn't re-arm within that window, the cron's path 404'd and every heartbeat failed.

From v0.4.11 the cron points at a stable intermediate file — `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py` — that lives outside the version-stamped cache and survives every plugin update. The stub's only job is to find the latest cached version and `os.execv` into its `scripts/dispatch.py`:

```
cron prompt (baked at /janitor-arm)
  → ${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py
      1. list versions under
         ~/.claude/plugins/cache/ai-maestro-plugins/ai-maestro-janitor/
      2. semver-sort, pick highest
      3. os.execv into that version's dispatch.py
        → <latest cached version>/scripts/dispatch.py
            (real per-version dispatcher with detectors)
```

`${CLAUDE_PLUGIN_DATA}` resolves to `~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/` per the Claude Code plugin-data contract. It is **persistent** across plugin updates (spec guarantee), **auto-created** on first reference, and **auto-cleaned** only when the plugin is uninstalled from the last scope.

**Survival contract.** The stub is fire-and-forget — zero arguments, no state, no logging. Its interface is `dispatcher-stub.py` (no args) → `os.execv` → `dispatch.py` (no args). As long as future versions of `dispatch.py` stay zero-argument fire-and-forget (which they have been since v0.1.0), the stub never needs updating. If we ever break this contract in a future janitor release, that release becomes a "users must re-arm" version — the same UX as pre-stub, applied once.

## Operational rules

**When re-arming is still needed.** Three cases, only three:

1. **First install of the plugin in this session.** Before `/janitor-arm` runs the first time, no cron exists. The skill creates the cron AND installs the stub in one go.
2. **Upgrade from pre-stub (≤ v0.4.10) to v0.4.11+ — exactly once.** The pre-stub cron's prompt has a versioned `dispatch.py` path hardcoded; nothing in the v0.4.11 install flow touches the existing cron, so the cron keeps firing the old `0.4.10/scripts/dispatch.py` until the user runs `/janitor-arm` once with v0.4.11+. After that the cron points at the stub and rolls forward forever.
3. **Cron auto-expiry approaches.** CronCreate jobs auto-expire after 7 days; `dispatch.py` emits `[janitor-renew]` at day 6 (configurable via `heartbeat_renewal_threshold_days`). Claude reads the nudge and re-runs `/janitor-arm`, which idempotently replaces the cron AND refreshes the stub.

Future plugin version bumps require **zero** user action — the next heartbeat after the new version lands in the cache automatically targets it.

**Atomic stub install.** `/janitor-arm` installs the stub via `cp → chmod +x → mv` rather than writing directly to the destination, because:

- A heartbeat that fires while the stub is being rewritten could read a partial / non-executable file and fail.
- `mv` on the same filesystem is atomic — the cron either sees the old stub or the new stub, never a half-written one.
- The `chmod +x` happens on the temp file BEFORE the rename, so the destination is always executable when it appears.

This pattern matches how `dispatch.py` writes `last-run-<detector>.ts` state files, by the same atomicity argument applied to detector re-entrancy.

## Responsibility split and safety

**Stub vs. `dispatch.py` — division of responsibility.**

| Concern | Stub | `dispatch.py` |
|---|---|---|
| Path stability | ✓ (stable forever) | ✗ (version-stamped) |
| Detector logic | — | ✓ |
| Drift line emission | — | ✓ |
| State file writes | — | ✓ |
| Version resolution | ✓ | — |
| `os.execv` into latest | ✓ | — |
| Reads `${CLAUDE_PLUGIN_OPTION_*}` | — | ✓ |

The stub is intentionally tiny (~50 lines of stdlib-only Python). Adding logic here means coupling it to a specific `dispatch.py` API or runtime, which is exactly what the stub was designed to avoid.

**Path-traversal safety.** The Claude Code plugin spec documents a hard limit: plugin files cannot use `..` to reach files outside their cache directory. The stub design respects this:

- The stub is **not a plugin file** in the spec's sense. It is written *to* `${CLAUDE_PLUGIN_DATA}` at runtime by `/janitor-arm` (which IS a plugin file, but its action is `cp + chmod + mv`, not a relative reference to a path outside the plugin tree).
- The stub uses **absolute paths only** — `Path.home() / ".claude/..."` — no `..` traversal anywhere.
- The cron prompt references the stub by **absolute** path.

Per the spec's "Path traversal limitations" section, the design is fully compliant.

**See also.**

- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatcher-stub.py` — the stub source.
- `${CLAUDE_PLUGIN_ROOT}/scripts/dispatch.py` — the per-version dispatcher the stub `execv`'s into.
- `${CLAUDE_PLUGIN_ROOT}/scripts/detectors/` — the drift detectors `dispatch.py` invokes each fire.
- `$CLAUDE_PROJECT_DIR/.janitor/state/` — per-project state and dedupe seen-files (separate from `${CLAUDE_PLUGIN_DATA}`).
- Top-level README — user-facing summary of the heartbeat, detectors, and configuration.

## Known limitations

Two harness-provided guarantees this design depends on do NOT hold on some
Claude Code builds (verified empirically on 2.1.173 and 2.1.177). The
`janitor-arm` skill passes every flag correctly — these are **upstream**
(Claude Code runtime) gaps the janitor must detect/work-around rather than
source bugs. Tracked in ai-maestro-janitor#23.

### 1. `durable: true` may be silently downgraded to session-only

`CronCreate(durable: true, recurring: true)` is the contract the whole
overnight rate-limit-recovery design rests on: the cron is supposed to persist
in `~/.claude/scheduled_tasks.json` and survive a Claude Code restart
(`--continue`, crash, OOM, manual relaunch). On the affected builds the runtime
accepts `durable: true` but creates a **session-only** job — nothing is written
to `~/.claude/scheduled_tasks.json` (the file is often absent entirely), and
`CronList` reports `[session-only]`.

**Consequence.** A session restart loses the heartbeat; the janitor stops firing
until something re-arms it.

**Mitigation in place.** The SessionStart hook surfaces a `/janitor-arm` nudge on
every new session, so the heartbeat is re-armed (freshly, session-scoped) each
session — the residual exposure is only a *mid-session* restart, recovered at the
next SessionStart. The `janitor-arm` skill (step 7) now **reads back durability
and reports session-only honestly** instead of claiming "survives restarts".

**Open (needs decision / upstream).** A true durable heartbeat requires the
Claude Code runtime to honor `durable: true`; this should be escalated upstream
if it persists. The janitor cannot make a session-only cron durable from its
side.

### 2. `${CLAUDE_PLUGIN_DATA}` is not stable across load-source changes

The stub indirection exists so the cron target survives plugin **version**
updates without re-arming — it anchors at `${CLAUDE_PLUGIN_DATA}/dispatcher-stub.py`,
documented as "the path that survives every plugin update". But
`${CLAUDE_PLUGIN_DATA}` is harness-derived and its trailing segment tracks the
plugin's **load source**: `…/ai-maestro-janitor-inline` for an inline/local load
vs `…/ai-maestro-janitor-ai-maestro-plugins` for the marketplace load. Re-arming
under a different load source than the first arm writes a *second* stub dir and
leaves the prior cron firing the old path; if the stale dir is ever cleaned, the
still-scheduled cron `os.execv`-fails.

**Consequence.** Orphaned `…-inline` / `…-ai-maestro-plugins` data dirs
accumulate; an armed cron can point at a path no longer being updated.

**Mitigation in place.** Each `/janitor-arm` re-bakes the *current*
`${CLAUDE_PLUGIN_DATA}` into the cron, so the active heartbeat self-corrects on
the next arm. Orphaned dirs are otherwise harmless (byte-identical stubs).

**Open (needs USER decision).** The report's suggested fix — anchor the stub at a
source-independent fixed path the janitor controls (e.g.
`~/.claude/plugins/data/ai-maestro-janitor/dispatcher-stub.py`, no suffix) —
conflicts with the project principle to *prefer `${CLAUDE_PLUGIN_DATA}`* (the
suffixed dir is the only one the harness guarantees to back up, preserve across
updates, and purge on uninstall). A fixed non-`${CLAUDE_PLUGIN_DATA}` path is an
unofficial folder that backups miss and purge orphans. Resolving this is a
deliberate design trade-off for the USER, not an autonomous change to the
survival path.
