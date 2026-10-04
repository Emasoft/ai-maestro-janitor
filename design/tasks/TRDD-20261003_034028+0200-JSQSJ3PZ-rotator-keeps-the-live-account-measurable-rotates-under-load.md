---
trdd-id: JSQSJ3PZ
title: Rotator keeps the live account measurable, rotates under load, and warns before the wall
column: blocked
status: tasked
created: 2026-10-03T03:40:28+0200
updated: 2026-10-05T01:27:35+0200
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: manager
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-10-03T03:40:28+0200
project-id: ai-maestro-janitor
npt: [JY0OBQZ4, G9Z8PXCM, HL3WBA2Q, IT5GEZDZ]
eht: [3OS6AXV3, HSRERK5S]
blocked-by: [JY0OBQZ4, G9Z8PXCM, HL3WBA2Q, IT5GEZDZ]
pre-block-column: dev
blocker-probe: [trddgrep, why, JSQSJ3PZ]
blocker-holds-if: not-match:READY
---

# Rotator keeps the live account measurable, rotates under load, and warns before the wall

## Make the OAuth rotator work, and make a janitor /clear resume in one push with nothing lost

## Context

The owner hit two failures within 3 hours (2026-10-02 22:09 and 2026-10-03 00:37). Owner directive: "Include the rotator, it must work!"
Evidence markers: ✓ = verified tonight in logs, code at repo HEAD, the 3.6.3 cache, or the official docs; ? = still open, resolved inside a step.

### Failure 1 — "Login expired · Please run /login" at 00:37

**No spare account to rotate to.** ✓
- account A was the only usable account; its token expired 00:42 (`state.json` slot `expires_at`).
- account B: credential-dead since 09-25, 3154 refresh failures.
- account C: slot expired 09-29.

**The daemon is blind to the live account.** ✓
- Every tick logs "mirror holds a DIFFERENT credential … no usable slot twin … staying put", again at 00:52–00:56 after `/login`.
- Causes:
  - The 3.6.3 daemon forces `JANITOR_ROTATOR_HEADLESS=1` (`daemon.py:812`).
  - The session beacon stores only `{fp,email}`.
  - `cmd_auto` returns before any usage probe.
- Sources: `reports/oauth-rotator/20261002_195104+0200-rotation-failure-root-cause.md` §1–3, fact-checked in `…201700-measure-verify.md`.

**The daemon starves, then goes silent.** ✓
- LaunchAgent `ProcessType=Background` (`keepalive_install.sh:270`) puts it in darwinbg, priority 4. Load average was 335–403.
- Rotator ticks started on schedule but ran 137 s (23:55) and 210 s (00:13, killed at 00:16).
- 00:18:16: "foreground budget 30s exceeded (687s used this pass)".
- No daemon line from 00:18 to 00:49, when it restarted (pid 40680).

**No warning reached the owner before the wall.** ✓
After the expiry, every heartbeat turn just printed "Login expired", so any model-turn alert would have been unreadable.

**? Why Claude Code's own refresh failed at 00:37.** Three hypotheses, separated in R0:
- a janitor process spent account A's grant;
- another of the ~24 claude processes refreshed it first;
- the refresh call starved or timed out (the rotator logged "API is unreachable" at 00:38).

**Unreleased fixes at HEAD.** ✓
- IT5GEZDZ (files the outgoing account into its slot — what keeps a spare alive)
- TK529Q0F (rotation-stuck marker)
- OOZP38MN
- ZKXQXHBI (`3c48d054`, daemon reads the primary; its LaunchAgent probe was never run)

### Failure 2 — after the 22:09 janitor clear the agent sat idle: no plan, no goal or tasks, no skills

**Trigger.** ✓ The daemon's external lane fired `trigger=next-fire-misses` at 348,063 tokens.
- The lane is enabled by `CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_ENABLED=true` in `~/.claude/settings.json`.
- Its awaiting-user veto (`lib/fleet_scan.py:838 awaiting_user_decision`) sees only an unanswered `AskUserQuestion`/`ExitPlanMode` tool call, never a question asked in prose. Later heartbeat turns also count as "someone spoke".
- Clearing while waiting is cost-correct, provided the restore restates the question.

**The hold blocked the resume.** ✓
- `summary-pending.json` (`external_handoff_clear.py:671`, 15-min TTL) makes `dispatch.py:4279-4290` abort the whole fire before `_phase_clear_resume` (`:4314`).
- The release fix (c1fce671) is not in 3.6.3, so `/janitor-resume` at 22:09:48 was silently deferred.
- This has happened after every janitor clear since 09-29.

**Wrong NEXT ACTION.** ✓ It is generic (`lib/external_clear.py:1662-1678`) and pointed at card IT5GEZDZ.

**Official docs** (code.claude.com/docs/en/hooks, /goal, /interactive-mode, /env-vars, /scheduled-tasks):
- hooks.md:1114, verbatim: "or run `/clear`, SessionStart hooks run in the background. You can type right away … Claude's first response still waits for the hooks to finish, so their context reaches Claude." So **no typing race exists for injected context.**
- `additionalContext` is capped at 10,000 characters. All matching hooks run in parallel.
- "Running `/clear` … removes any active goal." `/goal X` "starts a turn immediately, with the condition itself as the directive"; the condition is at most 4,000 characters; an authentication failure clears the goal; resume restores an unmet goal and resets its counters.
- "Tasks persist across context compactions." A list is shared across sessions only through `CLAUDE_CODE_TASK_LIST_ID`. Task tools are off on Opus 5.x unless `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` (settable in the settings `env` block).
- Queued commands "run one at a time" after the turn ends. Scheduled tasks fire only while idle.

**Codebase.** ✓
- `hooks/pre-compact-handoff.py:1040` `_build_continuity_record` (skills, open files, cards, live agents) is used only on the native-compaction path. No test references it and none monkeypatches it.
- `_continuity_nudge` (`on-session-start.py:693`) has a 15-line cap and is called for source=compact only.
- SessionStart timeouts: `on-session-start.py` 5 s; the post-clear hook 90 s.
- `--force` does not bypass the 300k floor.

**Binding rulings.**
- 7MGJYLY5 R2/R3: restore active skills only; files are mentioned, never read; subagents survive; the native-compaction path gets only a machine-readable nudge.
- QZVAEWQH: resume after the summary is injected.

### Delivery
Nothing ships without a release. HEAD is 336 commits past v3.6.3. RAEGS1D5 is in `human_review` (2 owner decisions) and about 24 cards are in dev/testing (CLAUDE.md: finish them first).
The plan is therefore split into three stages:
- **Tonight**: host-only, no release.
- **Release 1**: the minimum that makes both things work.
- **Release 2**: everything else.

## How the work runs
- **Main session (Opus)** plans, reviews, commits by file name, and talks to the owner. A background `lean-worker` makes every edit, given absolute paths, the exact change, the check to run, and the four CLIs spelled out: `tldr`, `jgrep`, `node ~/.claude/skills/quicksilver/scripts/qs.mjs`, `fastedit`.
- **One step = one card**, one or more commits. The WHY goes in the commit body and in a code comment; the card id goes in the subject.
- **SC (standard check)** after every code step: `uv run pytest <touched tests>`, `uv run ruff check scripts tests`, `uv run mypy scripts/ --ignore-missing-imports`, `uvx --with pyright pyright`. Expected: everything passes, 0 errors. Any failure stops the step.
- **"Fails before"** means the new test fails at HEAD *before* the change. The worker shows that failing run in its report.
- **Fixtures are synthetic.** They reproduce structure (keys, `captured`, header lines, heartbeat interleaving) with placeholder text and no real e-mails or prose. Real incident files are copied only to a gitignored `tests_dev/` for a one-off local replay.
- **Advisor**: before R2 and C2, run `agentlenspro model-headroom fable -q`. On exit 0, consult `fable-advisor:advisor`. Otherwise record why in the card.
- After every worker report, spawn one adversarial review fork.

## Cards
A lean-worker creates each card with `trddgrep new` and links it with `trddgrep set`. It runs `trddgrep help` first and picks `--authority`/`--min-approval` so the card lands in `design/tasks/` at `todo`. The umbrella bodies carry this plan verbatim.

| Card | Title (no colons) | Release | Links |
|---|---|---|---|
| **R** | Rotator keeps the live account measurable, rotates under load, and warns before the wall | 1 | npt [R1, R2, R3, IT5GEZDZ]; eht [R4, R5] |
| R0 | Root-cause the 00.38 Login expired on account A | tonight | read-only |
| R1 | Daemon runs at normal priority | 1 | npt |
| R1b | Daemon went silent for 31 minutes after a 687 s pass | 1 | joins QJ5LP4W2 if it is the same cause |
| R2 | Session beacon mirrors the live token so the daemon can probe usage | 1 | npt |
| R3 | Daemon never refreshes the live account's slot twin | 1 | npt |
| R4 | Owner warned out of band when no rotation target exists or the rotator stalls | 1 | eht; builds on TK529Q0F |
| R5 | Rotator tick output and latch visible in daemon log | 2 | eht |
| R6 | ZKXQXHBI primary read off by default until its LaunchAgent probe passes | 1 | standalone |
| R8 | Spare accounts stop decaying (account B root cause, spare-age alert) | 2 | standalone |
| **C** | Janitor clear keeps what native compaction keeps and resumes in one push | 1 | npt [C1, C2]; eht [C3, C4, C7]; supersedes K8YF2WQ5 |
| C1 | Summary hold ends once its handoff is on disk and is never re-taken over one | 1 | npt |
| C2 | Clear path injects a continuity block with the last request and own reply | 1 | npt |
| C3 | Task list carried into the new session after a janitor clear | 2 | eht |
| C4 | Session goal re-set after a janitor clear | 2 | eht |
| C5 | Clear chain stops typing janitor-arm | 2 | standalone |
| C6 | Summarizer holds every pane on a sibling's live transcript | 2 | standalone bugfix |
| C7 | Docs, memory pages and stale comments for the clear chain and rotator | 1/2 | eht |
| T | Enable task tools on Opus 5 | 2 | backburner, owner decision |

**Verify**:
- `trddgrep --design-dir <repo>/design` lists every new card in `todo`.
- `trddgrep lint` reports 0 errors.
- `git show --stat HEAD` shows only card files.

## Stage 0 — tonight, no release (host only)

**N1 (owner).** Re-capture account B and account C with `/janitor-capture-all-logins`. Without a spare nothing can rotate, whatever code ships.
- **Verify**: `rotator.py list` shows both with a future `token-expiry`.

**N2 (main, after owner approval).** Put the LaunchAgent at normal priority.
1. Copy `~/Library/LaunchAgents/com.ai-maestro-janitor.daemon.plist` to `<repo>/builds_dev/` as a backup.
2. `plutil -replace ProcessType -string Standard <plist>`.
3. `launchctl bootout gui/$UID <plist>; launchctl bootstrap gui/$UID <plist>`.
- **Verify**:
  - `plutil -extract ProcessType raw <plist>` prints `Standard`.
  - `ps -o pri,command -p <new daemon pid>` shows priority above 4.
  - The next three `oauth-rotator-tick` lines in `daemon.log` say `done in` under 30 s.

**R0 (worker, read-only).** Separate the three hypotheses.
1. Search the `fd932daa` transcript and `~/.claude/debug/` for Claude Code's refresh error text around 00:30–00:40: `invalid_grant` vs. a timeout.
2. Search `rotator.log`/`daemon.log` for any janitor touch of account A's grant between 16:42 (its last keepalive refresh) and 00:38, especially `_refresh_and_heal_slot` after the 19:26 switch.
3. Check whether a running Claude Code picks up a credential switched into the keychain after "Login expired", or needs `/login`. Look at the binary strings for the 401 handling path.
- **Verify**: a one-line verdict with evidence for each hypothesis, written to R0. If the evidence cannot separate them, say so; R1–R3 still ship.

## Release 1 — rotator works, resume is one push

### R1 — normal priority (`scripts/keepalive_install.sh:270`, `oauth_rotator/rotator.py claude_running()`)
1. Change `ProcessType` to `Standard`.
2. Add `timeout=10` to the `ps` call in `claude_running()`.
3. No `taskpolicy` demotion of plugin-update chores: at load 400 it would stop `claude plugin update` from finishing, and that is the path that installs this release.
- **Test**: render the plist through `keepalive_install.sh` into a temp dir and assert `plutil -extract ProcessType raw` ≠ `Background`. Fails before.
- **Verify**: SC.

### R1b — the 31-minute silence (`scripts/daemon.py` chore coordination)
1. Read the beat loop around the "foreground budget … deferring" path, and find what blocked from 00:18:16 to 00:49:59. Separate a blocked subprocess, the bulk lane (`daemon.py:302+`), and a dead process restarted by session b545353a.
2. If the cause is QJ5LP4W2's (unbounded foreground occupancy), finish that card instead of a new fix.
3. Either way, the rotator tick must keep its 60 s cadence. Give it a deadline-first slot in the beat, so a deferral pass never delays it.
- **Test**: drive the real beat scheduler with a fake slow workload (a real `sleep 40` subprocess) and assert the rotator tick still starts within its interval. Fails before, if the cause is confirmed.
- **Verify**: SC, plus `daemon.log` evidence quoted in the card.

### R2 — the beacon mirrors the live token (`rotator.py` HEAD `refresh_beacon_if_stale` ~1097, `_live_backup_write` ~926)
1. After a successful primary read in the session context, write the same blob to `-livebak`. The daemon's existing `b_fp == mirror_fp` branch then probes `/api/oauth/usage` (read-only) with the real live token.
2. Call it from the Stop hook too (`hooks/on-stop-token-meter.py`, mtime-gated by the existing staleness check). Today it runs only from the 300 s detector on idle heartbeat fires, so a busy session leaves the daemon blind.
3. **Before the first production write**:
   - Inspect the real `-livebak` item's ACL with an attribute-only lookup (no `-w`).
   - Make the first write with `may_prompt=False` and stop after one failure.
   - The update path emits no ACL flag (measure-verify 8a). V5RXQ4NB and ATOM-HDUR-IWRS are the known prompt risks.
- **Test** (isolated real-keychain fixture, no mocks):
  1. Seed the primary with L1 and `-livebak` with L0.
  2. Run `refresh_beacon_if_stale()` with HEADLESS unset; assert `-livebak` holds L1's fingerprint.
  3. With `HEADLESS=1`, assert `_resolve_untrusted_live` returns L1 and the isolated `rotator.log` has no "no usable slot twin". Fails before.
- **Verify**: SC.

### R3 — never refresh the live twin
1. Remove `_refresh_and_heal_slot(b_email, twin, state)` from `_resolve_untrusted_live` (HEAD ~2218-2224). Once an account is live, Claude Code owns its rotating grant (memory 53KFOJEI).
2. Every remaining caller passes `on_failure`.
- **Test**: same fixture, plus a local HTTP server on a real socket that counts POSTs to the token URL. Assert 0 refresh POSTs. Fails before (1 POST).
- **Verify**: SC.

### IT5GEZDZ — ship the existing fix
It files the outgoing account into its slot at every switch, which is what keeps a spare alive.
- **Verify**: its card's own acceptance, plus SC at HEAD.

### R4 — out-of-band warning (daemon side, builds on TK529Q0F `rotation-stuck.json`)
1. **Conditions:**
   - (a) **No rotation target**: no slot has a future expiry and no refresh succeeded. Fires once, then hourly.
   - (b) **Live token past expiry and not refreshed** for 5 minutes.
   - (c) **No completed tick** for 10 minutes.
   - (d) **`rotation-stuck.json` exists.**
2. **Channel**: a macOS notification from the daemon. Reuse an existing notifier if `grep -rn "display notification" scripts` finds one; otherwise use `osascript -e 'display notification …'`.
   - It is not a heartbeat drift line, because after expiry every model turn is "Login expired".
   - Also write `rotator-alert.json`, which the heartbeat surfaces when a turn can run.
   - The text names the one action (for example "run /janitor-capture-all-logins") and never includes a token.
3. **Ordering**: the dispatch phase that surfaces `rotator-alert.json` runs **before** the summary-hold gate.
- **Test**: real temp state for each condition; assert the notifier argv and the debounce. Fails before.
- **Verify**: SC.

### R6 — ZKXQXHBI primary read off by default
Gate `3c48d054`'s daemon primary read behind an opt-in env var. R2 makes it unnecessary, and it carries prompt risk.
- **Test**: with the default config, assert the tick's `security` argv never contains `-w` for the primary. Fails before.
- **Verify**: SC.

### C1 — the hold ends with its handoff and is never re-taken over one
1. `external_handoff_clear.py:161` `summary_hold_active` returns False once any `agent-handoff-<key>-*.md` exists for the record's key with mtime ≥ `captured`, via `handoff_files.parse`/`_entries` (`lib/handoff_files.py:115,159`).
   - A template counts, because it was injected; a later real summary is named by `_fresh_summary_note` (`dispatch.py:1819`).
   - This reverses K8YF2WQ5's "template keeps the hold" (owner decision 3).
2. `_capture_summary_source` (`:96`) takes **no** hold when a handoff for that key already exists. This closes the re-hold by the detached retry lane (`summarize_previous_session.py:224`).
3. Delete the now-redundant release calls (`post-clear-compact.py:485-491`, `summarize_previous_session.py:310,356`) and `_release_summary_hold` if unused (`tldr references`).
4. **No chain wait**: per hooks.md:1114, Claude's first response waits for every SessionStart hook. The post-clear hook writes the handoff before it exits, so the resume turn always sees it.
5. Update the existing hold tests to the new contract: `test_dispatch_phases.py:1074,1089`, `test_external_handoff_clear.py`, `test_summarize_previous_session.py`, `test_on_session_start_post_clear_compact.py:1531-1614`.
- **Tests:**
  - Synthetic replay of 22:09: a hold with key K, then a handoff for K written 6 s later. `dispatch.py` prints `[janitor-resume]`. Fails before.
  - An older handoff, or a different key, leaves the hold active.
  - The retry lane does not take a hold when a template exists.
  - Then the local one-off replay with the real files in `tests_dev/`.
- **Verify**: SC; `grep -rn "summary hold active" scripts` shows only the log string.

### C2 — continuity block on the clear path
1. **Dead code first**: `tldr dead hooks/pre-compact-handoff.py`, committed alone.
2. **Move** `_build_continuity_record` and its helpers, with their constants, to `scripts/lib/session_continuity.py` using `fastedit move-to-file`. Update the test imports in `tests/test_precompact_handoff_hook.py` (`_hook()` :46 loads by path; only `_TRANSCRIPT_ROLES_IMPORT_ERROR` and `_MAX_BACKWARD_SEEK_SECONDS` are monkeypatched). No compatibility re-exports.
3. **Clear-only fields** (everything through `state.sanitize_for_drift_line`):
   - `last_user` = the last human record, via `jev_compaction.is_human_record` (`:450`), excluding heartbeat prompts (`transcript_roles.HEARTBEAT_PREFIX`) and automation commands.
   - `own_reply` = the **first** assistant text after it, up to ~800 chars. This skips later heartbeat replies without classifying them.
   - `goal` = the last `goal_status` with `met:false`.
   - `plan_file` = included only if it exists; mentioned, not read.
   - `open_tasks` = from `~/.claude/tasks/<oldStem>/*.json`, where status is not completed.
4. **NEXT ACTION**: add a `HandoffInputs.next_action` field (`lib/external_clear.py:1607`, rendered at `:1662-1678`) with no heuristic:
   > "The user's last message was «last_user». Your reply was «own_reply». If your reply asked the user something, ask it again and stop. Otherwise continue from it."

   Card STATE is the fallback only when `last_user` is empty.
5. **`## Continuity` block**, placed ahead of the Jev text: goal, open tasks, "re-invoke skills: …", plan file, live agents, open-file paths.
   - It has its own budget inside `LANE_INJECTION_MAX_BYTES` (8192 < the documented 10,000), applied through `jcl.trim_cards_for_room` (`:775`).
   - The native-compaction `_continuity_nudge` stays untouched (R2 ruling).
- **Tests:**
  - A synthetic fixture shaped like 89d835ac: human "have you fixed the rotator?", an assistant reply ending "reply go …", then 4 heartbeat turns. NEXT ACTION quotes that reply and never "janitor heartbeat". Fails before.
  - Goal, task and skill fixtures.
  - The block survives a large Jev text within budget.
  - No sidecar (a user-typed `/clear`) produces no block.
  - The source=compact output is byte-identical before and after.
- **Verify**: SC, plus the real hook run as a subprocess with a temp HOME, with stdout inspected.

### C7 (part 1)
- Correct memory ATOM-RQDO-2SJE ("UNREADABLE is the designed path").
- Update the `jev-compaction` and `janitor-compaction-floor-gate*` pages (hold contract).
- Update `skills/janitor-compact-context/SKILL.md`: stale `:240` reference; `--force` does not pass the floor.
- **Verify**: `memgrep validate <page> && memgrep lint <page>` reports 0 errors.

### Release 1 ship (owner decision 1)
1. The owner authorizes release 1, with unrelated open cards re-columned, or clears the board first. Resolve RAEGS1D5's 2 decisions.
2. Run `uv run scripts/publish.py --minor`. Do not watch CI.
3. When the janitor reports green: update the installed plugin with `claude plugin update <plugin>@<marketplace> --scope user`, plugin `ai-maestro-janitor`, marketplace `ai-maestro-plugins` (exact command: CLAUDE.md Working rules). Re-stage the plist via `keepalive_install.sh`.
- **Deploy verify:**
  - The cache directory carries the new version.
  - The DATA `rotator.py`/`daemon.py` sha256 equals the cache copy.
  - `daemon.pid` mtime is later than the install.
  - `ProcessType` is `Standard`.
- **Field acceptance, rotator (on this host):**
  - Each idle fire is followed within one tick by `live <email> 5h=… 7d=…`.
  - No "no usable slot twin" line more than 5 min after a Stop-hook stamp.
  - Tick wall time under 30 s with load above 200.
  - An R4 notification observed once (e.g. temporarily expire a throwaway slot).
  - A daemon-initiated `auto: switched` is opportunistic: it is recorded when a real wall happens.
- **Field acceptance, clear (throwaway pane):**
  - Run with `CLAUDE_PLUGIN_OPTION_EXTERNAL_IDLE_CLEAR_MIN_CONTEXT_TOKENS` lowered for that pane. First verify whether the settings `env` value or the launch env wins; if settings wins, use a ≥300k pane.
  - End a turn with a prose question, run `/janitor-compact-context`, and expect:
    - one push;
    - NEXT ACTION restates the question;
    - the block lists the skills and tasks;
    - no "summary hold active" line in `dispatch.log`.

## Release 2
- **R5**: log the tick's rc and stderr tail in `daemon.log`. No latch change: a hung `security` prompt also uses ~0 CPU, so "starved" cannot be told apart from it.
- **R8**: root-cause account B's decay (grant age, refresh cadence, revocation). Keepalive alerts when a spare's last successful refresh is older than N hours.
- **C3**: copy the task directory only when all of these hold:
  - this is a janitor chain (a sidecar exists);
  - `CLAUDE_CODE_TASK_LIST_ID` is unset;
  - the old directory holds `*.json` (the file backend, not storageV5);
  - the new directory is empty.

  Skip `*.lock`, keep `.highwatermark`, and label it as relying on undocumented internals. Tests: copy, lock skipped, no overwrite, env set, no sidecar.
- **C4**: when an unmet goal existed, the chain types `/goal <sanitized>` **instead of** `/janitor-resume`.
  - It is one push and one turn, and it mirrors native compaction, which keeps the goal active. The goal's kickoff turn waits for the SessionStart context, which includes the Continuity block and NEXT ACTION.
  - The flag left by `/janitor-resume` is consumed by the next idle fire.
  - Sanitizer: no control characters or newlines, collapsed whitespace, at most 4,000 chars, no leading `/`, `[janitor-` defanged.
  - Check whether `user_intent.record_intent_from_prompt` (`lib/user_intent.py:191`) records a janitor-typed `/goal` as owner intent.
  - Tests: the keystroke plan for an unmet, met and absent goal; a sanitizer table.
- **C5**: the clear chain's bootstrap becomes `(RESUME_CMD,)` (crons survive `/clear`, verified). The reload triggers keep `/janitor-arm`. Test: the dry-run keystroke plan.
- **C6**: `jev_compaction_lane.previous_transcript` skips sessions live in `~/.claude/sessions/<pid>.json` (pid alive and the sessionId matches). Test with a temp sessions directory.
- **C7 part 2**: the rotator memory pages, and the stale comments (`external_handoff_clear.py:66-72`, `on-session-start-cold-cache-clear.py:227-250`, `on-session-start.py:381-383`, the `spawn_shrink_chain` docstring, `dispatch.py:4252-4278`).
- **T**: owner decision on `CLAUDE_CODE_ENABLE_TODO_TOOLS=1` via `lib/settings_ensurer.py` `ENV_ADD_IF_MISSING`.
- Each step: SC, plus its tests failing before the change.

## Owner decisions
1. N2 tonight: put the daemon at normal priority on this Mac (plist backed up first). Recommended.
2. Release 1 route: ship with unrelated cards re-columned (recommended), or clear the board first.
3. C1: template handoffs end the hold (recommended; reverses K8YF2WQ5).
4. R6: ZKXQXHBI primary read off by default (recommended).
5. T: task tools on Opus 5.
6. N1: re-capture account B and account C (owner action, tonight).

## Approval log

- 2026-10-03T03:40:28+0200 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-10-03T06:25:09+0200 — column → dev by main-agent@ai-maestro-janitor.
- 2026-10-03T06:25:10+0200 — column → dev by main-agent@ai-maestro-janitor. children in dev/testing
- 2026-10-04T20:11:30+0200 — column → testing. Umbrella: no code is being written on it. Release-1 code shipped in 3.7.0; all four prerequisite cards are in testing. It waits on the rotator field acceptance on this machine and stays open until release 2 (its effects cards 3OS6AXV3 and the parked HSRERK5S). testing is not terminal, so the stays-open ruling holds.
- 2026-10-04T20:13:39+0200 — column → blocked. Correction of the same day's move to testing: the linter raised ORDER-NPT-VIOLATED, because a parent may not pass dev while its prerequisite cards are unfinished. Nobody is writing code on this umbrella, so dev was untrue as well; blocked on its prerequisite cards is the column that is both true and lint-clean.

## STATE

2026-10-03: stays open until release 2 — its eht includes the parked backburner card HSRERK5S (R5).
2026-10-03 06:12 STATE: committed R3 fe76d99c, R6+R3 follow-ups 2b18348f, R1 30d320eb, R4 b4ba693b, R4b b956914d, R2 415d1971. R1b (rotator tick in own thread, bounded plugin-update step) verified (166 passed, linters clean) and landed as e9b7622d. R4c in progress: exclude the live account from 'no rotation target' and add an 'auth-failed' condition written by the StopFailure hook (the alarm currently cannot fire before or at a repeat of the 00:37 wall). R0 report reports/oauth-rotator/20261003_034130+0200-R0-login-expired-root-cause.md. Owner decisions pending: N2 (re-stage the LaunchAgent at Standard on this Mac now), release route, one-off plain edit for fastedit-refused leftovers (listed on MMUSDJHQ), re-capture of the two dead spare accounts, real-notification field check (launchctl asuser $(id -u) osascript -e 'display notification "janitor R4 field check" with title "ai-maestro-janitor"'), and a Keychain Access look at the -livebak item's ACL. NEXT ACTION: R4c (TRDD-3OS6AXV3) verify+commit; full uv run pytest; deferred plugin reload; release-2 cards.
2026-10-03 06:15 correction: R1b is COMMITTED as e9b7622d (its subject line was lost to a git -F mix-up; the full message is in follow-up commit 346a557d, message-only; git notes are not pushed). Next: verify and commit R4c, then card updates and the full test suite.
TRDD-L2CCH9D5 and TRDD-JW8CWWNH (filed 2026-10-03 from R8) are non-blocking backlog: linked by parent-trdd only, not in npt/eht, so they do not hold this umbrella open.
2026-10-04 column testing (was dev). Correction to the move reason recorded in the approval log - it called HSRERK5S parked, but HSRERK5S and 3OS6AXV3 are both in testing. Verified with git merge-base against tag v3.7.0 - fe76d99c, 2b18348f, 30d320eb, b4ba693b, b956914d, 415d1971 and e9b7622d are all inside the 3.7.0 release. Whether R4c landed was not checked. Field evidence so far is negative - on 2026-10-04 the heartbeat printed the alert that account rotation is stuck nine times in one afternoon. NEXT ACTION - after 3.7.1 is installed, observe the field acceptance list in the plan, and treat the stuck alert as a failing result until it stops.
2026-10-05 column blocked (was testing for about two hours on 2026-10-04; that move raised ORDER-NPT-VIOLATED because a parent may not pass dev while its prerequisite cards are unfinished). blocked-by lists the same cards as npt. pre-block-column set to dev, the lint-clean place for a parent to wait. Probe measured 2026-10-05: trddgrep why prints the word READY for a card whose prerequisites are satisfied (seen on BHIS99XE) and does not print it for a blocked card (seen on 3HLI7DMK). The NEXT ACTION above is unchanged.

## Release status

2026-10-04 — The release published today ships this card's code committed so far (no implementation-commits recorded). The card stays in dev because its STATE says it stays open until release 2 (its eht includes the parked card HSRERK5S), and its children JY0OBQZ4, G9Z8PXCM, HL3WBA2Q, IT5GEZDZ (npt) and 3OS6AXV3, HSRERK5S (eht) are not all closed, with the rotator field acceptance still unobserved on this machine after an install.
