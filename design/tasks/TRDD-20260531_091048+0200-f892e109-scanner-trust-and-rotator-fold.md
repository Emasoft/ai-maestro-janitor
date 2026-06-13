---
trdd-id: f892e109-3105-4bfe-9978-f23b9bb3378c
title: Janitor security-scan trust model (keep-in-janitor) + fold OAuth rotation into the daemon (remove launchd)
column: complete
current-owner: amama
task-type: refactor
release-via: publish
created: 2026-05-31T09:10:48+0200
updated: 2026-06-13T16:08:43+0200
---

# TRDD-f892e109 — Janitor security-scan trust model (keep-in-janitor) + fold OAuth rotation into the daemon (remove launchd)

**Filename:** `design/tasks/TRDD-20260531_091048+0200-f892e109-scanner-trust-and-rotator-fold.md`
**Tracked in:** this repo (design/tasks/ is git-tracked)

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-05-31

> ✅ **CLOSED 2026-06-13 (column → complete).** Both deliverables shipped: scanner-trust
> "keep-in-janitor" decided, and the launchd→daemon-fold landed (launchd retired). The
> "### NEXT ACTION — publish BLOCKED on CPV-FP MINORs / DECISION PENDING" note below is
> **SUPERSEDED and RESOLVED** — the fleet publish policy is now CPV-only + devitalize-or-remove
> (never exempt/suppress, per PRRD S5.1), and v0.7.5 ships with CPV `--strict` passing. No open action.

> Captured just before a forced /compact so the decisions can't be garbled by the
> lossy summary. These are DECIDED with the user (Emasoft) across a long design
> dialogue + a cross-check with the CPV-side Claude. Do NOT re-litigate.

### THE HARD PRINCIPLE (write this into the design as a rule)
**Relocation / annotation / role-claim is NEVER an exemption from security scanning.**
A `# this is for the scanner` comment, moving code into an `install.sh`, or moving
attack strings into a `references/*.md` are ALL forgeable — a malicious actor would
do exactly the same. References/*.md ARE part of the skill bundle the scanner walks.
The ONLY honest moves for a flagged item are:
1. **Remove** the dangerous capability (finding genuinely disappears).
2. **Reclassify genuinely-inert data** into a layer the scanner *verifies* as inert
   (a signature string compared against input is inert detection-data; this is why
   CPV v2.112.0 cleared 95/99 pattern-lib findings). NEVER reclassify *live* behavior.
3. **Inform, not suppress** — scanner flags it, surfaces it at opt-in, the USER consents
   (transparency). Nothing is allowlisted on the author's say-so.
Corollary (the solo-dev trust ceiling): "CPV signs/verifies the janitor" is
self-attestation one level up — Emasoft owns both repos, so there is no independent
signer. Honest anchors for solo OSS = transparency, verifiable
artifact-equals-source, and tamper-evident hashes (CPV already ships these). NO
notarization/signing scheme.

### DECISIONS
1. **Security scanning stays in the janitor — Option C (keep-in-janitor).** Do NOT
   migrate the ~222 `*_patterns.py` + scanner detectors into CPV. Rationale: the FP
   fire is already out (CPV v2.112.0 took the janitor 99→2 CRITICAL); CPV is a
   plugin-PUBLISH validator while the janitor scanners are continuous ENV monitors
   (different cadence/domain); and CPV-scan vs janitor-env-scan signatures barely
   overlap, so a merge (A) or shared engine (B) isn't justified. (B) only if real
   overlap ever appears.
2. **Attack-signal docs (skill-bundle-audit SKILL.md, CRITICAL #1 remaining):**
   RECLASSIFY the literal injection example strings (`<!-- system: … -->` etc.) out of
   agent-loadable PROSE into the inert signature-DATA layer (pattern-lib regex) that
   CPV already verifies as inert. The SKILL.md *references* them; it must not *contain*
   injectable prose, and must NOT just move them to another `.md`.
3. **OAuth rotator launchd installer (CRITICAL #2 remaining): REMOVE it** by folding
   the rotation into the existing janitor **daemon** (`daemon.py`, the always-on
   standalone singleton that already does marketplace-refresh and already owns
   user/global-scope mutations per issue #7 — a keychain swap IS a global mutation).
   - Add a daemon Task `oauth-rotator-tick` (~60s cadence) running the existing
     `rotator.cmd_tick` logic (poll /api/oauth/usage, drain-first swap on 429/expiry).
   - DELETE the launchd agent + plist template + the install/bootout machinery.
     `/janitor-auto-manage-oauth-on|off` become FLAG-ONLY (set/clear the opt-in flag).
   - Shrink the P2 `oauth-rotator-supervisor` Task to "verify opt-in flag + daemon
     health" (no plist to heal).
   - This is resolution by REMOVAL (honest) → the persistence-installer CRITICAL
     vanishes, AND it retires the TRDD-32acd15f persistence-gap defect #1 (the launchd
     agent was never in ~/Library/LaunchAgents, so it never survived reboot anyway —
     zero real loss).

### CAVEATS / DEFERRED (acknowledged, not blockers)
- Daemon liveness is tied to Claude Code running periodically (the heartbeat lazy-
  respawns it). Fine for unattended-overnight; reboot-with-Claude-closed loses the
  daemon until next launch — same as today's real behavior.
- **Tier-3 re-auth** (both refresh chains dead): run `claude login` in an already-
  trusted folder (skip the trust prompt, or find a skip flag), `tmux send-keys` the
  two Enters, puppeteer the Authorize click, kill the session. Still needs ONE account
  kept logged into claude.ai (the cookie/credentials-replacement problem we have NOT
  solved — DEFERRED). Rare path.
- The cookie/credentials replacement (so we don't need a human-seeded browser session)
  is DEFERRED — see TRDD-32acd15f §STATE for the seed-via-clean-Chrome state.

### PROGRESS (2026-05-31)
- ✅ **Decision (2) DONE** — committed `cd944a7`. `skills/janitor-skill-bundle-audit/SKILL.md`
  defanged: 4 injection-example literals (`<!-- system: … -->` ×2, an
  ignore-previous-instructions imperative, an `openai_api_base:<attacker>` base-URL
  override) replaced by rule-name references. Signatures already live inert in
  `agent_config_patterns.py` (`_HTML_COMMENT_DIRECTIVE` / rule `html-comment-impersonation`).
  VERIFIED on the real janitor: `cpv-remote-validate plugin . --strict` CRITICAL **3 → 2**.
- ⚠️ **Count correction:** baseline was **3** CRITICAL, not 2 — the launchd item is TWO
  findings: `scripts/oauth_rotator/com.emasoft.claude-account-rotator.plist.template:7`
  AND `skills/janitor-auto-manage-oauth-on/SKILL.md:90`. Both are cleared by decision (3).
  After (3): expect CRITICAL → **0**.
- ✅ **Decision (3) DONE** — daemon-fold landed (user said "go"). Sub-phase A `46e8ad9`
  (daemon `oauth-rotator-tick` @60s timed subprocess; supervisor → alert-only +
  `opt_in_present()`; on-session-start fast-path; 30 tests green). Sub-phase B: `-on`/`-off`
  skills flag-only (one-time legacy launchd teardown in `-off`); deleted plist.template
  and rotator-stub.py; tightened `-on` description (<200 tok, no YAML colon-space); fixed
  this TRDD's MD004/MD031. VERIFIED: CPV `--strict` **CRITICAL 0, MAJOR 0**.

### NEXT ACTION
**Publish v0.5.2 is BLOCKED on 5 pre-existing CPV-FP MINORs** (NOT from the daemon-fold —
inert detection data CPV mis-flags as live ops): `.bashrc`/`.profile` filename tuple
(build_reproducibility_patterns.py:852 FS_WRITE), a Lua byte-signature
(binary-magic-scanner.py:86 SHELL_EXEC), system npm scan paths
(historical-cache-scan.py:148-149), and the `/var/tmp/` danger-prefix tuple
(sandbox_escape_patterns.py:1154). publish.py `run()` `sys.exit(3)`s on CPV's MINOR exit,
so these block the release. Same FP class as the 95/99 CPV v2.112.0 already cleared.
DECISION PENDING (user owns CPV-FP judgment): (a) file 5 CPV FP issues + wait for a CPV
demote-to-NIT fix; (b) reclassify where feasible; (c) transparent documented suppression
to ship now. Do NOT auto-suppress.

## Problem
A security/maintenance plugin inevitably contains threat-shaped content (attack
signatures; an opt-in launchd installer). Self-attestation ("trust me, I'm a scanner")
can't clear it, and neither can relocation. This TRDD records the honest resolutions
(remove / reclassify-inert / inform) and the keep-in-janitor + daemon-fold decisions.

## Out of scope
- Migrating scanning to CPV (rejected — Option C chosen).
- Any signing/notarization scheme (rejected — self-attestation for a solo owner).
- Comment/location/role-claim suppression (forbidden by the hard principle).

## Implementation plan (phase 3 — daemon-fold; removes launchd)

8 files: delete 2, rewrite 2 skills, edit `daemon.py` + `supervisor.py`, edit/add tests,
update TRDD-32acd15f. Split into **sub-phase A = code** (daemon + supervisor + deletions +
tests) and **sub-phase B = skills + TRDDs + CPV-verify + publish**. Verify after A before B.

Key facts gathered (verified this session): daemon main loop ceiling `_LOOP_CEILING_SEC = 60`
(so a 60s Task matches the old plist `StartInterval 60`); `rotator.cmd_tick(only_if_running)`
= `if only_if_running and not claude_running(): return 0; cmd_capture(False); return cmd_auto()`;
the daemon auto-rolls (dispatcher-stub re-execs latest `<ver>/scripts`), so `_HERE/oauth_rotator/
rotator.py` is always the latest version → **no `rotator-stub.py` needed**. The supervisor's
launchd heal lives in `_agent_loaded()` / `_restore_stub()` / `_restore_and_load_agent()` /
`_which_python()`; `_rotator_root()` resolves `${CLAUDE_PLUGIN_DATA}/oauth-rotator/`.

### A1. `daemon.py` — add the 60s tick Task
- New constant after `_INTERVAL_OAUTH_SUPERVISOR`:
  `_INTERVAL_OAUTH_TICK = int(os.environ.get("CLAUDE_PLUGIN_OPTION_DAEMON_OAUTH_TICK_INTERVAL", "60"))`
- New task fn near `task_oauth_rotator_supervisor` — runs as a TIMED SUBPROCESS (not in-process)
  so a hung keychain/usage call can't wedge the loop; gated on the opt-in flag:

  ```python
  def task_oauth_rotator_tick() -> None:
      if not oauth_supervisor.opt_in_present():
          return  # rotator not activated on this machine -> silent no-op
      rotator_py = _HERE / "oauth_rotator" / "rotator.py"
      _run_workload([sys.executable, str(rotator_py), "tick",
                     "--only-if-claude-running"], timeout=120)
  ```

- `_build_tasks()` += `Task("oauth-rotator-tick", _INTERVAL_OAUTH_TICK, task_oauth_rotator_tick),`
- Confirm `sys` is imported (it is).

### A2. `supervisor.py` — shrink (remove launchd heal) + add `opt_in_present()`
- DELETE `_agent_loaded()`, `_restore_stub()`, `_restore_and_load_agent()`, `_which_python()`,
  and every `Facts` field / `diagnose` finding / `apply` branch that references the launchd
  agent (agent-loaded, plist presence, bootstrap heal). Supervisor becomes ALERT-ONLY.
- ADD `def opt_in_present() -> bool: return (_rotator_root() / "opt-in.flag").exists()` (the
  daemon tick gate). KEEP: opt-in-flag fact, slot-readiness (≥2) alert, pinning-env-var alert.
- `task_oauth_rotator_supervisor` in `daemon.py`: still calls gather/diagnose/apply; fix its
  log string if it claims "healed" (heal set is now empty/alert-only).

### A3. Delete launchd artifacts (`git rm` — tracked+committed → recoverable)
- `git rm scripts/oauth_rotator/com.emasoft.claude-account-rotator.plist.template` (clears CRITICAL #1)
- `git rm scripts/oauth_rotator/rotator-stub.py` (launchd-only; daemon calls `rotator.py` directly)
- BEFORE rm: `grep -rn "rotator-stub\|plist.template"` → confirm only the (about-to-be-rewritten)
  skills + TRDDs reference them; no live code path does.

### A4. tests
- `tests/test_oauth_supervisor.py`: drop `_agent_loaded`/`_restore_*`/plist-heal asserts; keep/adjust
  opt-in + slot-readiness + pinning-env; add `opt_in_present()` test.
- Add daemon test: `oauth-rotator-tick` present in `_build_tasks()` with interval 60; monkeypatch
  `_run_workload` to assert NOT called without the opt-in flag, IS called with it. Isolate via
  `JANITOR_GLOBAL_STATE_DIR` + `CLAUDE_PLUGIN_DATA` like the other daemon tests.
- `python3 -m unittest tests.test_oauth_supervisor …` green.

### B1. `janitor-auto-manage-oauth-on/SKILL.md` → flag-only
- KEEP: refuse-on-pinning-env, refuse-off-macOS (keychain swap is macOS `security`), set
  opt-in flag (now the PRIMARY action), report.
- REMOVE: stub install (step 3), plist render (step 4), `launchctl bootstrap` (step 5), and the
  `~/Library/LaunchAgents` + plist.template + rotator-stub Resources lines.
- Rewrite Overview + frontmatter `description`: "sets an opt-in flag; the always-on janitor
  daemon's 60s `oauth-rotator-tick` Task does the rotation" — NO launchd agent. The daemon is
  lazy-spawned by the heartbeat (`/janitor-arm`).

### B2. `janitor-auto-manage-oauth-off/SKILL.md` → flag-clear (+ one-time legacy teardown)
- Primary: clear `opt-in.flag` (daemon tick then no-ops).
- KEEP a best-effort LEGACY teardown for pre-fold installs (CPV-safe — removal, not persistence;
  baseline never flagged -off): `launchctl bootout gui/$(id -u)/com.emasoft.claude-account-rotator
  2>/dev/null || true` + `rm -f ~/Library/LaunchAgents/com.emasoft.claude-account-rotator.plist`,
  commented as one-time migration cleanup. Update Overview/Resources (flag is now authoritative).

### B3. TRDD-32acd15f — record the launchd→daemon migration
- STATE block: launchd agent RETIRED; rotation now = daemon `oauth-rotator-tick` (60s,
  opt-in-flag-gated). Mark persistence-gap defect #1 (plist never in `~/Library/LaunchAgents`)
  RESOLVED-by-removal. Bump `updated:`.

### B4. verify + publish
- `uvx --from git+https://github.com/Emasoft/claude-plugins-validation --with pyyaml
  cpv-remote-validate plugin . --strict` → expect **CRITICAL=0**.
- Full unittest suite green; `tldr diagnostics scripts/` clean.
- `uv run scripts/publish.py` (v0.5.1 → v0.5.2) — its Step 4 re-runs CPV --strict as the gate.

### Caveat to honor during impl
- The flag path the daemon reads (`supervisor._rotator_root()/opt-in.flag`) MUST equal the path
  `-on` writes (`${CLAUDE_PLUGIN_DATA}/oauth-rotator/opt-in.flag`). If the DETACHED daemon lacks
  `CLAUDE_PLUGIN_DATA` in its env, resolve the data dir the same way the daemon resolves its other
  state (check `spawn_daemon_detached` env) — verify before trusting `_rotator_root()` in the daemon.
