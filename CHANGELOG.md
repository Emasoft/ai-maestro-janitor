# Changelog

All notable changes to this project will be documented in this file.

## [3.3.15] — 2026-08-18

### Bug Fixes

- **test:** The refusal-guard tests stubbed the runner but not the BINARY LOOKUP (TRDD-IFZQ98BA) (88db92d)

### Features

- **cold-resume:** INJECT the handoff at /clear instead of pointing at it (TRDD-IFZQ98BA) (9ad66ab)
## [3.3.14] — 2026-08-18

### Documentation

- **memory:** The handoff that authorised a destructive clear was never validated (TRDD-IFZQ98BA) (a2f4bc3)

### Features

- **external-clear:** Record WHAT the process said, not just our verdict (TRDD-IFZQ98BA) (617e3fc)

### Miscellaneous Tasks

- Bump version to 3.3.14 (74f2e45)
## [3.3.13] — 2026-08-18

### Bug Fixes

- **external-clear:** A model REFUSAL was accepted as a summary and a context was cleared on it (TRDD-IFZQ98BA) (8310965)

### Documentation

- **TRDD-IFZQ98BA:** MD004 — standardize bullets to asterisk (publish gate) (3905067)

### Miscellaneous Tasks

- Bump version to 3.3.13 (7ead90f)
## [3.3.12] — 2026-08-18

### Bug Fixes

- **tcc:** The osascript interpreter needs a stable IDENTITY, not just a stable path (48c524a)
- **automation:** Sign the interpreter, stop deriving llm-ext's data dir (TRDD-CEWVQ8DG) (38d2a34)
- **clear:** A cancel must falsify the TRIGGER's own premise (TRDD-CEWVQ8DG) (11f176a)
- **test:** The ordering spy must mirror _fire's real signature (TRDD-CEWVQ8DG) (268322a)
- **detectors:** The alarm shipped a FALSE claim about its own metric, pinned by a test (80ce577)
- **detectors:** Three MORE sites carried the disproved %cpu mechanism (TRDD-JEEQCHFG) (1cf988e)
- **cold-resume:** The one-shot must record FIRES, not ATTEMPTS (28b3e7a)
- **tcc:** The chain child must run under the automation interpreter, not inherit blindly (9b4ee41)
- **cold-resume:** The hook now actually BLOCKS, as its own comment always claimed (783af50)

### Documentation

- **baseline:** The module docstring asserted the pre-ruling payload (f8aa684)
- Add TRDD-JEEQCHFG — supersede 8QSLYMGU, whose premise about %cpu was false (80ce577a) (92495e2)
- **TRDD-JEEQCHFG:** The retracted metric fails in BOTH directions, and my own discriminator was wrong (22729dc)
- **TRDD-JEEQCHFG:** The metric measures AGE, and the RAM half is refuted (6fed349)
- **TRDD-JEEQCHFG:** RETRACT the "measures AGE" section — it describes time/etime, not %cpu (144d1a5)
- **TRDD-JEEQCHFG:** The RAM "refutation" is retracted — memory was the root cause all along (d3d3ca1)
- **TRDD-JEEQCHFG:** MD004 — standardize bullets to asterisk (publish gate) (13c1698)

### Miscellaneous Tasks

- Bump version to 3.3.12 (c58812e)
## [3.3.11] — 2026-08-16

### Bug Fixes

- **trdd-drift:** Report an `updated:` stamp that is in the future (TRDD-TUVQWLJF) (fe8590c)

### Documentation

- **memory:** A publish-gate timeout has a THIRD cause — host saturation (1470ba5)
- **design:** ZM5LZ24Y — an absent decline line proves nothing until 2 preconditions hold (836a314)
- **design:** G4BCRUP7 C2 audit — candidate cleared, inventory built, box stays open (b1f7f0e)
- **design:** G4BCRUP7 — the C2 inventory is COMPLETE; the 9-site gap was my own grep (f36f350)
- **design:** G4BCRUP7 C2 audit CLOSED — 75 drift lines, zero violations (8c02c04)
- **design:** 9MCGBPR7 CLOSED; ZM5LZ24Y preconditions measured; 3 fabricated timestamps corrected (3779955)
- **design:** Add TRDD-TUVQWLJF — a future-dated updated: pins a card to the top of the board unnoticed (3c11437)
- **design:** G4BCRUP7 CLOSED — 16/16 rows swept, no manual bootstrap beyond the known three (852f619)
- **design:** UQW5IOAE — refuse the triage row that would have closed it, and say why (a015b8f)
- **design:** XM3FPJC0 soak — autonomous fire OBSERVED; the other half cannot be observed at all (29c4bbe)
- **design:** CEWVQ8DG field check FAILS its second half — the fix moved the failure, not removed it (058d6a9)
- **design:** Add TRDD-PGN5XSHA — a KILLED subagent stays pending and the directive says resume it (74bbfdb)
- **design:** TUVQWLJF — log the advisor attempts on the card the advisor is blocking (eaf7c44)
- **design:** TUVQWLJF dev -> testing — all 5 boxes ticked, fe8590c3 recorded (8d59e3c)
- **design:** XM3FPJC0 — match the file's asterisk bullets (MD004, publish blocker) (1b5f3e7)

### Miscellaneous Tasks

- Bump version to 3.3.11 (770b02d)
## [3.3.10] — 2026-08-16

### Bug Fixes

- **system-daemon-runaway:** Gate CPU findings on persistence (TRDD-8QSLYMGU) (540ee8e)

### Documentation

- **kanban:** EZ3PMQYX — probe the launchd branch before building it, and the probe killed the obvious predicate (ef1412e)
- RETRACT the signed-python "reverted migration" claim — it was wrong, and fix the wording that caused it (4292d5b)
- **memory:** A findings COUNT is only comparable within one linter version (a64ac18)
- File TRDD-8QSLYMGU — the runaway alarm fires on a lifetime average with no persistence test (6b2a5dd)
- **design:** Settle TRDD-8QSLYMGU's shape before coding — gate CPU, never RSS (59458f8)
- **design:** Close TRDD-8QSLYMGU — CPU persistence gate shipped in 540ee8ed (c582580)
- **design:** ZM5LZ24Y soak — the C3 anchor cannot advance on a server-owned host (e500259)
- **design:** ZM5LZ24Y — instrumentation shipped in 11e925c0; next action is to read one log line (61b3f2d)
- **claude-md:** The stale C3 pin is not transient on a server-owned host (cbfa77c)

### Features

- **c3:** Name WHICH predicate declined a re-pin (TRDD-ZM5LZ24Y) (11e925c)

### Miscellaneous Tasks

- Bump version to 3.3.10 (ec75e09)
## [3.3.9] — 2026-08-16

### Bug Fixes

- **memgrep:** The build stamp watched a file a commit never writes (TRDD-9XMPS8OZ) (a698f16)
- **findings:** Date every finding line — a resurfaced alarm read as a current measurement (TRDD-D6RDPZIU) (d692074)
- **memgrep:** Lint must not raise a body-shape finding on a superseded atom (TRDD-3K8SVX2H) (d54b755)
- **iterm-alarm:** The SCOPE clause claimed more than the evidence supports (TRDD-EZ3PMQYX) (580d134)

### Documentation

- **kanban:** Close TRDD-KVS6K7P9 — per-dispatch memory dispatch state is fully shipped (d2bda4e)
- **kanban:** Close TRDD-9XMPS8OZ and TRDD-2OUMEVDS (4259e72)
- **memory:** Merged is not delivered — the PATH check, and why a version stamp is not proof (fb10881)
- **kanban:** Close TRDD-3PWQK8NM, hand its one open item to TRDD-5C1PFDM5 (f996e7c)
- **kanban:** Close TRDD-9PDH8G0W and TRDD-KU3ERYFX — both were publish-gated on an answer already owed (1b47fbd)
- **kanban:** Close TRDD-3QIQ2E6J — the awaited split happened, and it disproved the expectation (52a63bf)
- **kanban:** Refresh TRDD-RG4IUZ6I state — 3QIQ2E6J closed, and this card's framing shrank (1ef9897)
- **kanban:** AZ6QRK0D todo -> blocked, and prove the breakage instead of arguing it (1a4c28c)
- **kanban:** AZ6QRK0D -> human_review as the decision site, JPL0JU86 -> blocked behind it (cc3c15b)
- **cache:** Record the forensic verdict IJ94O8YD was waiting on, and file TRDD-3K8SVX2H (53c76b5)
- **kanban:** WN7M829Y -> human_review, and correct the 240-findings headline (b51c588)
- **kanban:** RG4IUZ6I -> human_review; item 3 judged not worth building, advisor failure recorded (a98b087)
- **kanban:** Give AM8JD9SG acceptance criteria — it had none for a month, and its status was 4 findings stale (ef35bd2)
- **kanban:** LFSWY0C6's "zero work today" premise expired — and how it expired is the card's own argument (b3dd249)
- **skill:** Janitor-findings documents the measurement age it now renders (2403e24)

### Features

- **iterm-alarm:** Size the exposure the tmux remedy asks a human to fix (TRDD-EZ3PMQYX) (e4f82cb)

### Miscellaneous Tasks

- Bump version to 3.3.9 (efff300)

### Testing

- **memgrep:** Pin the build stamp to the commit it claims (TRDD-9XMPS8OZ) (a9d067d)
## [3.3.8] — 2026-08-15

### Documentation

- **board:** CLI-verify the v3.3.7 install against its tag (TRDD-G4BCRUP7) (54b262f)

### Miscellaneous Tasks

- Bump version to 3.3.8 (cfa9a37)

### Testing

- **clear:** Pin that /clear is never typed without a handoff on disk (TRDD-UQW5IOAE) (4310081)
## [3.3.7] — 2026-08-15

### Bug Fixes

- **handoff:** Compose against the budget the contract enforces (TRDD-PXP08ZQC) (cac8b55)

### Documentation

- **board:** Record the live re-alert proof and the v3.3.6 gate findings on XM3FPJC0 (b182411)
- **roster:** Document all 73 detectors and defend the inventory with a test (TRDD-IEW2K659) (eb0cdfe)
- **board:** Tick IEW2K659's own acceptance boxes and unmix its list markers (1094f42)

### Miscellaneous Tasks

- Bump version to 3.3.7 (9aa5eda)

### Testing

- **exfil:** Pin the alarm/ledger routing and close HYV0SOC6 (8f8b032)
## [3.3.6] — 2026-08-15

### Bug Fixes

- **tests:** Repair the v3.3.5 CI break my own rename caused, and guard the category (TRDD-CEWVQ8DG) (feb2d4c)
- **detector:** Make runaway-file-growth executable in git (TRDD-XM3FPJC0) (3b85963)
- **detector:** Annotate the B108 false positive on the scan root (TRDD-XM3FPJC0) (d92a135)

### Features

- **detector:** Name a file that grows without bound (TRDD-XM3FPJC0) (199f548)

### Miscellaneous Tasks

- Bump version to 3.3.6 (74ec122)
## [3.3.5] — 2026-08-15

### Bug Fixes

- **cold-resume:** Answer the cache question with arithmetic, and find llm-ext where it lives (TRDD-CEWVQ8DG) (904ddef)

### Documentation

- **memory:** Record the cold-resume incident and move its shipped card to testing (TRDD-CEWVQ8DG) (14adabf)
- **board:** Unblock the publish NIT and record the hub-armed receiver on WKTD5JTC (3f4d386)

### Miscellaneous Tasks

- Bump version to 3.3.5 (f0d2122)
## [3.3.4] — 2026-08-15

### Features

- **stop-failure:** Route the StopFailure payload by error type (owner directive 2026-08-15 — use the events more) (b146a64)

### Miscellaneous Tasks

- Bump version to 3.3.4 (6a4bfa1)
## [3.3.3] — 2026-08-15

### Documentation

- **board:** Redact a committed home path in the 6CRC9SQQ card (janitor#274 item 2) (c3bdd4c)

### Features

- **model-fallback:** Owner-ratified TRUE-ERROR switch sequence (owner spec 2026-08-15) (d20e3e9)

### Miscellaneous Tasks

- Bump version to 3.3.3 (286c8c1)
## [3.3.2] — 2026-08-15

### Bug Fixes

- **ci:** The two v3.3.1 reds — white-box loader typed Any, full history for check5's probe (c68340d)
- **git-guard:** Widen the lsof probe window 5s -> 15s — load turned 'held' into 'no-probe' (7894e6e)

### Documentation

- **board:** 2026-08-15 Fable-wall field notes on WKTD5JTC + QE390SJA (TRDD-QE390SJA) (8258ba6)
- **memory:** 2026-08-15 Fable-wall incident atom on the rotator page (ATOM-PH7Z-4FY8) (c2bd51f)

### Features

- **rotator:** A model-scoped wall on the LIVE account now triggers rotation (owner report 2026-08-15) (f185e52)
- **guard:** Deny gh publishes targeting a repo the gh auth user does not own (owner rule 2026-08-14) (def961f)

### Miscellaneous Tasks

- Bump version to 3.3.2 (10c74c8)
## [3.3.1] — 2026-08-14

### Bug Fixes

- **memory:** A publish-globally symlink is a sanctioned escape, not drift (janitor#249) (c2686c0)
- **cold-cache-clear:** A disabled refusal must leave a trace (TRDD-PXP08ZQC incident 2026-08-15) (e0f9605)
- **memgrep:** A mid-line [^N]: is a reference, not a swallowed definition (janitor#270) (4a02d8e)
- **presence:** Tri-state user_presence() — one boolean cannot serve injectors and the push gate (61667ef)
- **integrity:** Publish the minted key by hardlink — visible only when complete (b9d9bb8)

### Miscellaneous Tasks

- Give pyright a venv, name any hanging test, probe memgrep candidates for executability (3678227)
- Bump version to 3.3.1 (b4dbbb3)

### Testing

- **sandbox:** Gate macOS-only binaries so Linux CI asserts the guard's real contract (072d301)
- **ci:** Pin the environment CI cannot supply — memgrep, claude, notify-send, the window var (run 31844013197 triage) (af47f6f)
## [3.3.0] — 2026-08-14

### Bug Fixes

- **trdd-drift:** An obituary is not a stale citation (TRDD-Q4AMWYCY) (29acfb2)
- **tickets:** Allow ticket_cli close --status needs_human (janitor#213) (3a04899)
- **rotator:** Distinguish 'all measured as maxed' from 'nothing to measure' (janitor#221) (6383337)
- **github-config-audit:** Treat unresolved ruleset detail as indeterminate (janitor#244) (31c22cd)
- **memory-maintenance:** Give each dispatch its own pending-state file (janitor#242) (d5df92a)
- **arm:** Fall back to a full CronList sweep when a targeted delete fails (janitor#239) (7c933b1)
- **memory-librarian:** Drop the project-specific path from the shared orphan notice; exempt overview hubs from globs (janitor#243) (03ce7fb)
- **memgrep:** Demote atom-oversized to INFO — no chore gate can ever act on it (janitor#200) (6b57a04)
- **bench:** Disambiguate two class descriptions that produced off-class samples (janitor#226) (a2c7850)
- **pending-agents:** Sweep never-nudged ghost entries after 1h, not 7 days (janitor#253) (1bda133)
- **bench:** Gate on PER-CLASS recall — a growing corpus is not a regression (janitor#226) (1f6f625)
- **security:** The 19% FP figure was worst-case, not typical — ordinary code scores 0% (janitor#226) (16495b0)
- **bench:** Generate at concurrency 2 — the free pool is the bottleneck (janitor#226) (3754f73)
- **security:** Security-doc FP rate is 8%, not 19% — and the class is far narrower (janitor#254) (1a394fe)
- **security:** Make crypto-clipper-triad match the BEHAVIOUR, not one library (janitor#226) (f0c2aa0)
- **security:** Tool-wildcard-grant — match the wildcard VALUE, not the tool vocabulary (janitor#226) (dcb4845)
- **security:** Authority-override was written in jailbreak-forum English (janitor#226) (959e308)
- **security:** Cross-skill-shadowing implemented one of the attack's two shapes (janitor#226) (71974e9)
- **security:** The two MCP rules were dead on the only files they exist for (janitor#226) (221e5b3)
- **security:** Mcp-annotation-lying required the lie be told in one exact place (janitor#226) (b5defab)
- **security:** Dns-exfil-long-subdomain measured volume, not the act (janitor#226) (b7f107c)
- **external-clear:** The watcher crashed on every run — and wire the reactive expiry trigger (TRDD-1QJIZFFW) (169d967)
- **external-clear:** The expiry probe's 5s bound made the trigger dead on arrival (TRDD-1QJIZFFW) (295c124)
- **bench:** Corpus credential fixtures are generated at load, not stored at rest (janitor#226) (e342239)
- **memory-maintenance:** Give a dispatch a CONSUMED flag — claim it, don't read a shared slot (janitor#242) (7e0b411)
- **dispatch:** A /clear consumes the resume DIRECTIVE, not just its flag (janitor#224 defect 1) (8b2521a)
- **verify:** Two verdicts that misreported a healthy /clear (janitor#224 defects 2 and 3) (94cc343)
- **memory:** Stop offering chores pages they can never write (janitor#249) (2ebef80)
- **trdd:** TRDD-DEAD-SYMBOL asked "did this substring ever appear", not "was this a symbol" (janitor#255) (56032f9)
- **memorize-nudge:** Never nudge about code that no longer exists (janitor#256) (0f9ea53)
- **reload:** A presence decline no longer CONSUMES the reload signal (janitor#257) (cea1e3f)
- **skills:** All seven chore skills now CLAIM their scope instead of picking one (TRDD-EBQVHTP4) (9b88559)
- **rotator:** An UNKNOWN previous identity is not a changed identity (TRDD-UA4FAX67) (624c63a)
- **memorize-nudge:** A DOTTED module mention is coverage too (janitor#256, second half) (102061a)
- **context:** Omit a context reading that predates the compaction (TRDD-G043V3V0) (2ec63fe)
- **fleet-github-config:** Age every surfaced line, withhold a stale audit (TRDD-88ZVEQY7) (cda30a2)
- **oauth:** Resolve every path the login nudges name, never the legacy literal (janitor#258) (8f2b956)
- **memory:** End the no-op-exclusion series with a machine field, not a fourth regex (janitor#259) (469ef32)
- **daemon:** Report a task that RUNS and FAILS — a fresh stamp is not health (TRDD-3GF9PSQB) (0cc466d)
- **fleet:** A one-shot `claude` subcommand is not a recoverable session (TRDD-R3D5YRQJ) (c7063a7)
- **board:** A partial dataclass copy silently disarmed check 6 (TRDD-F4IBIDB6) (75f6607)
- **board:** A shared TRDD-ref is structure, not blindness (TRDD-XFPOAF2I) (c4f1173)
- **detectors:** The blindspot detector was committed non-executable (TRDD-XFPOAF2I) (30d9ddc)
- **claudemd:** Conforming files plan nothing — PARTIAL, the defect survives (TRDD-LFSWY0C6) (20f226b)
- **agents:** Populate the respawn handle lazily, so recovery can find a transcript (TRDD-KTXZJC6E part A) (e81ac46)
- **claudemd:** A dev-ops exemption now needs a COMMAND, not just a word (TRDD-LFSWY0C6) (c88776c)
- **security:** Exfil-webhook-sink now STATES that it is a blocklist (TRDD-HYV0SOC6) (6ab6cc0)
- **split:** Keep the headroom rule under the skill token cap (TRDD-RG4IUZ6I item 3) (c9b4441)
- **security:** Two-step-code-injection sees a variable, and exec stops meaning .exec (janitor#226) (a969390)
- **security:** The fence is not the signal — dynamic-exec-in-body goes 1/3 to 3/3 (TRDD-XOITBRIZ) (3bf80fd)
- **security:** A dropper picks the token ORDER, not us — two-step goes 3/9 to 5/9 (janitor#226) (b11c237)
- **state:** Atomic_write accepts Path | str — the annotation was untrue of its own body (TRDD-BMDZK4RA) (a08d14f)
- **ci:** Pyright could not resolve tests/_fake_secrets — CI Lint was RED since e3422397 (a25f706)
- **security:** Dynamic-exec-in-body could not fire on PowerShell at all (TRDD-XOITBRIZ) (e46c9d3)
- Apply code-review findings, incl. the 3 the review itself skipped (1f1ac98)
- **baseline:** The ruleset must fit the project's governance, not impose a PR on a repo that reviews itself (36f05aa)
- **iterm-alarm:** A busy-pane read is channel evidence too — the alarm was aging a WORKING channel into looking dead (janitor#261) (174865c)
- **iterm-alarm:** The alarm's PROSE still stated the FIRED-only evidence rule, and named uv as the grantee (385d699)
- **iterm-alarm:** Record each FIRE, not just the dedupe marker — the alarm was the one detector with no history (299f775)
- **triggers:** Presence DEFERS, never cancels — the last 4 triggers (janitor#257) (f2a7f71)
- **agentlens-probe:** The cache-expiry timeout silently deleted the trigger (3b1f120)
- **tests:** Clear the @lru_cache path resolvers between tests (TRDD-TSTISOL1) (a749dfc)
- **findings:** Record the human-only directive at DELIVERY, not in the message (679a8b2)
- **trdd:** NEXT ACTION spans the whole bullet, not the line it starts on (30994c1)
- **memory-precheck:** The footer is the TRAILING run, not the first footer heading (janitor#260) (f6ecc6c)
- **keep-going:** Age out a stale resume directive (janitor#264 part a) (b83f00d)
- **memory-dispatch:** The claim retires the legacy mirror it makes obsolete (janitor#264 part b) (b4cad1a)
- **pyright:** Strip the JSONC comments — CPV parses this file as strict JSON (d43c605)
- **daemon:** Submit our OWN queued command instead of declining forever (janitor#261) (02b9cce)
- **memory:** Resolve PROJECT scope when the repo sits BELOW the project dir (janitor#263) (3452489)
- **memgrep:** One block-props spelling, and page `lmd` is finally maintained (janitor#266, #265) (ae7f32a)
- **repomap:** Drop `lmd` from corpus_digest — it just became a churn source (janitor#265) (22ed55f)
- **memgrep:** Per-page lint can finally see the cross-page rules (janitor#262) (88390fc)
- **memgrep:** `atom-after-footer` gets one owner — the Rust linter (janitor#260 endgame) (5c09ffd)
- **agent-context:** Mask `sensitive-secret-ref` in prose the way exec already is (janitor#254) (e4ad22c)
- **reports:** Anchor the report-root resolution so one chore cannot split across two trees (janitor#264c) (9d696f5)
- **tests:** The write sandbox silently protected the WRONG home under sharding (855adf5)
- **rules:** Safe-delete never said an ask is unnecessary — the whole point of it (2c014be)
- **tests:** Daemon deadlines were tuned on an idle machine, so -n 12 failed them (a0d3438)
- **git:** An EXITED git pid must not block stale-lock recovery (janitor#245) (440e859)
- **claude-md:** The project map is opt-in, so its absence is not a violation (458ddcd)
- **security:** Input redirection bypassed the exfil guard entirely (91540ee)
- **session:** CC 2.1.214 reports source 'fork' — seed the reload ack for it (fd43765)
- **context:** The fallback window must follow CC's 1M hold (2.1.223) (226afce)
- **memory:** Back up LOCAL design/ TRDDs against the session sweep (TRDD-9DLBHWGV) (c054012)
- **security:** Revive a dead credential-path branch; add GitLab coverage (CC 2.1.232) (35e81d7)
- **types:** Stop shadowing a drift string with a line number (4227493)
- **hooks:** Bound the cold-cache SessionStart hook; close TSTISOL1 (b524bfe)
- **daemon:** Self-heal the C3 last-good pin on every fire (TRDD-ZM5LZ24Y) (cc42698)
- **pre-compact-handoff:** Find in-flight TRDDs in a nested repo ([#267](https://github.com/Emasoft/ai-maestro-janitor/issues/267)) (a65331c)
- **version-update:** Certify the version the stub EXECS, not newest-on-disk (TRDD-ZM5LZ24Y) (f6be3d1)
- **fleet-scan:** Unconditional-negative discriminator (TRDD-9PDH8G0W) (b01d1b1)
- **external-clear:** Veto the clear when the session is blocked on a human (TRDD-OO301H7D) (fde1bf4)
- **memory-scopes:** A scope-escaping page is a finding, not silence ([#249](https://github.com/Emasoft/ai-maestro-janitor/issues/249)) (2295a5c)
- **iterm-alarm:** The grant advice carries the human-only marker (TRDD-KU3ERYFX) (d24591a)
- **external-clear:** The retry budget could never spend itself (TRDD-YOZ9TS3W) (e4ec23b)
- **agent-context-integrity:** Separate mentioning a threat from using it (TRDD-XCRTJ1C9) (adcadee)
- **skill:** Janitor-memory-recall was 5372 tokens against the 5000 cap (8b6ccf3)
- **skill:** Reload-skills description was 214 tokens over CPV's 200 cap (b8ff855)
- **memory:** Declare publish-globally on the 4 pages whose symlinks already existed ([#249](https://github.com/Emasoft/ai-maestro-janitor/issues/249)) (fba278d)
- **publish:** The sharding flag only reached ONE of two pytest call sites (b5b42ce)
- **trdd-state-reconciliation:** A timeout must not be spelled the same as "not found" (4e61690)
- **publish:** Clear the 3 MINOR + 4 NIT blocking CPV --strict (be4edec)
- **publish:** Wrap the subprocess entry point so it is CALLED, never passed (255ee7a)
- **publish:** Enumerate the runner's parameters -- a *args forward is itself dynamic (911abcb)

### Documentation

- TRDD-1QJIZFFW — the llm-ext CLI has landed; record the integration traps (ce967fc)
- Fix 1QJIZFFW's stale head; queue TRDD-Q4AMWYCY (obituary != stale citation) (f4206d4)
- Refresh the CLAUDE.md project map + wikimem index (auto-generated blocks) (cd20389)
- TRDD-IAJS6M9Z todo -> complete; measure each skill once (TRDD-IAJS6M9Z) (33438d2)
- TRDD-Q4AMWYCY todo -> complete — obituary suppression verified both ways (41c455b)
- TRDD-E8LNOXLQ backburner -> complete — the defect was already fixed elsewhere (dbcc2bd)
- Close 3 stale TRDDs whose premises died elsewhere (053SGT7N, 76XSELZ7, DLI76AUC) (8d69400)
- TRDD-1QJIZFFW — record the USER's handoff-payload spec (hook-injected, budgeted) (4cee9f1)
- **global-arm:** Make the skill doc say plainly it arms no per-project cron (janitor#77) (9219d6a)
- **board:** Re-column 8 stalled cards — a WORK column must assert real work (221228e)
- **memory:** Record the measured 28% agent-context rule coverage (ATOM-8ANO-T80F, janitor#226) (2112524)
- **pending-agents:** State the cost the 1h ghost sweep accepts (janitor#253) (a9cae8c)
- **memory:** Record the 19% false-positive finding (ATOM-T1UU-0DNF, janitor#254) (9ce847e)
- **TRDD-G4BCRUP7:** Record the guard flip verified on the REAL path, and what it does NOT prove (cc82953)
- **bench:** The dev/holdout split is too small to tune against yet (janitor#226) (da6263e)
- **bench:** The two authoring channels are not interchangeable (janitor#226) (3e66de2)
- **security:** Make the rule descriptions match what the patterns now claim (janitor#226) (fa27dd7)
- **security:** Record WHY exfil-webhook-sink stays falsified at 0/8 (janitor#226) (905cbe3)
- TRDD-1QJIZFFW backburner -> dev — the owner's go-ahead landed and the core shipped (TRDD-1QJIZFFW) (4350245)
- TRDD-1QJIZFFW — reactive trigger wired; the two remaining boxes need a real /clear (TRDD-1QJIZFFW) (a93f81e)
- Add TRDD-WP7TCRME — the janitor FIXES instead of notifying (USER directive) (TRDD-WP7TCRME) (8c6c751)
- **memory:** Publish-globally is a REQUIRED PROJECT-page field, and the symlink is its mechanism (25013e6)
- **memory:** Publish-globally normalization is ALWAYS ON, not a lint flag (USER correction) (a51e3d8)
- TRDD-WP7TCRME — measure the heartbeat's real cost; the quiet filter fixes none of it (TRDD-WP7TCRME) (e31c6f6)
- TRDD-WP7TCRME — Rule 2 was already done; next is Rule 4 (TRDD-WP7TCRME) (90db6ba)
- Add TRDD-3QIQ2E6J — split siblings re-litigate forever (janitor#241) (TRDD-3QIQ2E6J) (43b686a)
- TRDD-WP7TCRME STATE — what landed, and the one library still unwired (TRDD-WP7TCRME) (0068db7)
- TRDD-WP7TCRME — Rule 4 is wired and its acceptance box is earned (TRDD-WP7TCRME) (c9053e5)
- **skills:** Three memory skills back under the CPV token cap, by moving detail out (ec28365)
- Add TRDD-EBQVHTP4 — 5 of 7 chore skills never got the claim step (TRDD-EBQVHTP4) (bd75439)
- **rules:** Shipped-rules corpus back under the context-floor cap, by moving detail out (29121d8)
- **rules:** Collapse the 7 duplicated INERT preambles — 15 B of headroom becomes 1646 B (83a6867)
- TRDD-EBQVHTP4 todo -> complete — shipped at 9b885599 (TRDD-EBQVHTP4) (36f1b41)
- TRDD-WP7TCRME dev -> blocked — Rule 3's last two categories are already built (TRDD-WP7TCRME) (c75e368)
- Make five column claims true — a WORK column that nobody is working is a lie (451e3f2)
- AZ6QRK0D — correct my own NEXT ACTION; the privacy gate is a design choice, not wiring (TRDD-AZ6QRK0D) (e22013e)
- **arm:** A crashed arm self-heals — say so where a reader hits it (TRDD-9MCGBPR7) (6b4e28f)
- UA4FAX67 — option (a) shipped; reviewing it found the fail-open hole (TRDD-UA4FAX67) (3b2f06b)
- DB1P25S4 — the iTerm-automation grant is OBSERVED to apply to the daemon (TRDD-DB1P25S4) (c26a23e)
- Add TRDD-R3D5YRQJ — the fleet scan counts CLI subcommands as sessions (TRDD-R3D5YRQJ) (2619ad1)
- R3D5YRQJ — record the two traps that stopped the obvious fix (TRDD-R3D5YRQJ) (d3b248f)
- Add TRDD-F4IBIDB6 — nothing detects a WORK column nobody is working (TRDD-F4IBIDB6) (8bd298c)
- F4IBIDB6 — Check 6 shipped at 3f15a8ee (TRDD-F4IBIDB6) (126cc8e)
- **memory:** The post-compaction context reading is the PRE-compaction one (TRDD-G043V3V0) (57adaa0)
- CGOV2XO4 todo -> blocked — the sketched schema would lose data (janitor#167) (65355e1)
- 9MQ25PNH todo -> complete — the last box measured, and it proves nothing (TRDD-9MQ25PNH) (6f6f1bf)
- KVS6K7P9 — item 2 is not standalone and the gate belongs machine-global (TRDD-KVS6K7P9) (b4dcc3a)
- Add TRDD-3GF9PSQB — a failed task stamps a fresh last-run (TRDD-3GF9PSQB) (d753128)
- Refresh the fenced CLAUDE.md project map (TRDD-88ZVEQY7, TRDD-G043V3V0) (9e8d9a0)
- TRDD-3GF9PSQB todo -> complete — shipped at 0cc466d2 (TRDD-3GF9PSQB) (9e22386)
- TRDD-2112XCKO todo -> complete — shipped 9e75a7d9, was done-but-unclosed for 5 days (TRDD-2112XCKO) (7fe39f9)
- **protocol:** The memory chore's CONTENT decision belongs to the skill, not the receiving agent (janitor#260) (3095e43)
- TRDD-UA4FAX67 todo -> blocked — both remaining boxes are outside anyone's effort (TRDD-UA4FAX67) (a4bad78)
- TRDD-R3D5YRQJ todo -> complete — shipped at c7063a79 (TRDD-R3D5YRQJ) (435f11b)
- TRDD-F4IBIDB6 todo -> complete — check 7 shipped at 6a0066d7 (TRDD-F4IBIDB6) (b313f36)
- TRDD-IJ94O8YD second measurement REFUTES its headline (TRDD-IJ94O8YD) (e52e94d)
- TRDD-KVS6K7P9 STATE was false — items 1, 4, 5 already shipped (TRDD-KVS6K7P9) (2383352)
- TRDD-PXP08ZQC readiness audit — built, but nothing calls it (TRDD-PXP08ZQC) (c0f7750)
- TRDD-KVS6K7P9 — two boxes closed, one retired as moot (TRDD-KVS6K7P9) (c123b50)
- TRDD-3QIQ2E6J design settled, scope cut to Python-only (TRDD-3QIQ2E6J) (863501e)
- Two open cards prescribe opposite fixes for janitor#241 (TRDD-RG4IUZ6I) (854259d)
- Add TRDD-XFPOAF2I — detect cards attacking one defect blind to each other (TRDD-XFPOAF2I) (2f96788)
- TRDD-XFPOAF2I todo -> complete — shipped 20a1c14e, self-fixed c4f11738 (TRDD-XFPOAF2I) (98fa3b5)
- TRDD-KI6OWCZT todo -> human_review — shipped 3890d7b1, only the reply is left (TRDD-KI6OWCZT) (767fcf8)
- Add TRDD-4ZSYW21E — the keystone check is blind during a freeze (TRDD-4ZSYW21E) (46b7758)
- TRDD-KU3ERYFX — a live human-only alarm landed in an agent session (TRDD-KU3ERYFX) (5d73aec)
- Cross-link the two symlink cards with a DIRECTION constraint (TRDD-AZ6QRK0D) (4d159b5)
- WKTD5JTC 1a/1b answered from on-disk evidence, no wedge needed (TRDD-WKTD5JTC) (2916860)
- Add TRDD-4EKZ81MV — the blindspot detector is blind where it is needed (TRDD-4EKZ81MV) (64ed0bb)
- Add TRDD-KTXZJC6E — the agent respawn path is always empty (TRDD-KTXZJC6E) (d819ae1)
- WKTD5JTC todo -> testing; withdraw a confounded claim on 4EKZ81MV (9a2ee97)
- LFSWY0C6 — pre-check says zero work today; split decision from delivery (TRDD-LFSWY0C6) (2b3535c)
- LFSWY0C6 — the shipped planner is WRONG on real input (TRDD-LFSWY0C6) (b751100)
- LFSWY0C6 — the real blocker is a missing primitive (TRDD-LFSWY0C6) (5fa80f7)
- LFSWY0C6 — the missing primitive is built; only DELIVERY remains (TRDD-LFSWY0C6) (357df2f)
- KTXZJC6E — three corrections; nothing calls respawn_prompt at all (TRDD-KTXZJC6E) (e88c319)
- LFSWY0C6 — cite the two agent reports, annotated with why each conclusion misled (TRDD-LFSWY0C6) (448bce3)
- KTXZJC6E part A shipped; review caught an unresolvable-path defect (TRDD-KTXZJC6E) (ad4723c)
- LFSWY0C6 delivery part 1 — the removal engine, falsified per guard (TRDD-LFSWY0C6) (a5c046d)
- KTXZJC6E part B — scoped from the code; no script can be the consumer (TRDD-KTXZJC6E) (972271a)
- LFSWY0C6 — this card's own scheduler plan is probably wrong (TRDD-LFSWY0C6) (3941e74)
- Propagate plan/apply to the surfaces that enumerate them (TRDD-LFSWY0C6) (65d70d7)
- LFSWY0C6 — the §CM-3 exemption FP was a defect, not the bias (TRDD-LFSWY0C6) (38d5b2a)
- Add TRDD-HYV0SOC6 — exfil-webhook-sink is a domain blocklist, 0/8 (TRDD-HYV0SOC6) (86753d6)
- Add TRDD-XOITBRIZ — the fence mask hides dynamic-exec-in-body's primary threat (TRDD-XOITBRIZ) (353d38d)
- Repair three cards the board was lying about (TRDD-DB1P25S4, TRDD-87RKBYJ8, TRDD-LFSWY0C6) (81581bd)
- AZ6QRK0D's mechanism already shipped — in the direction JPL0JU86 forbade (TRDD-AZ6QRK0D) (d9f9d8c)
- **detector:** The cross-card blindspot detector names its own blind spot (TRDD-4EKZ81MV) (5b3b9d0)
- XOITBRIZ settles at 6/9, and the acceptance box that said 3/3 is RETIRED (TRDD-XOITBRIZ) (1d4ed45)
- PXP08ZQC's STATE headline claimed `dev` while the board said `todo` (TRDD-PXP08ZQC) (c86d2f7)
- 4ZSYW21E was already fixed 18 minutes after it was filed (TRDD-4ZSYW21E) (c4dc0eb)
- IJ94O8YD — a third measurement window opened today and could NOT be taken (TRDD-IJ94O8YD) (3b54d96)
- WN7M829Y's backlog does not empty — it REFILLS, and the loop is closed by design (TRDD-WN7M829Y) (4a5f55c)
- EZ3PMQYX records the landed plumbing and that the alarm text still ignores it (TRDD-EZ3PMQYX) (40f5c02)
- Park 3QIQ2E6J instead of leaving it in a work column nobody works (TRDD-3QIQ2E6J) (3a69db4)
- BMDZK4RA resolved — pyright already owns the class mypy cannot see (TRDD-BMDZK4RA) (f31e197)
- **bench:** Regenerate COVERAGE.md — dynamic-exec-in-body 6/9 -> 7/9 (TRDD-XOITBRIZ) (96723f1)
- IJ94O8YD records attempt 1 as ABANDONED, with why the delegation failed (TRDD-IJ94O8YD) (441c050)
- IJ94O8YD records the on-disk forensic paths + dispatches attempt 2 (TRDD-IJ94O8YD) (9a735b6)
- **agents:** TaskStop does not fire SubagentStop — a killed agent rides the nudge path (c74614e)
- WN7M829Y — the non-draining backlog is a property of the INFO TIER, not of oversized atoms (TRDD-WN7M829Y) (196631e)
- WN7M829Y correction — PROJECT's backlog is a GATE, not the INFO tier (TRDD-WN7M829Y) (b901ec5)
- IJ94O8YD — pinned incident unmeasurable, but the break MECHANISM is localised (TRDD-IJ94O8YD) (dd55344)
- DB1P25S4 — the iTerm automation gap is STILL LIVE, with the ambiguity now resolved (TRDD-DB1P25S4) (9fa07ff)
- DB1P25S4 correction — the iTerm channel ANSWERED today, so 'denied grant' is unsupported (TRDD-DB1P25S4) (e01d902)
- EZ3PMQYX — the load hypothesis explains why janitor#92's eliminations all come back null (0641b7d)
- File TRDD-TSTISOL1 — the test suite leaks state between tests (USER-directed) (945c307)
- Refresh the fenced project map (TRDD-e247a349 machinery) (ff8c233)
- Add TRDD-FE6W36WL — memgrep block-props spelling, page lmd bump, per-page lint blindness (e37abdd)
- **TRDD-FE6W36WL:** All three parts delivered — record the commits and the two measurements (1767184)
- Refresh both fenced CLAUDE.md blocks (project map + wikimem index) (53d9949)
- **TRDD-FE6W36WL:** Record the residual atom-after-footer FP found while dogfooding (9051506)
- **TRDD-HYV0SOC6:** USER ruling — detect wide, VERIFY, then alarm; backburner -> todo (11bac57)
- File 3 safeguard TRDDs from the advisor review (janitor#245) (0755ece)
- **TRDD-1QJIZFFW:** The re-fire policy verdict + a floor-staleness gap (c8cba39)
- The tldr instruction must not assume tldr exists (95b12c0)
- Settle the cache_prune symlink question in the CC audit atom (aefc266)
- **CLAUDE.md:** Five more USER working rules (2026-08-14) (7bff3c4)
- Record which surfaces auto-roll without /reload-plugins (TRDD-G6QWQUV6) (5082e7b)
- File TRDD-TVDK9Q1Y — the isolation guard cannot see heartbeat writes (71c2932)
- Correct TRDD-FE6W36WL column dev -> complete (9fa56f9)
- **TRDD-ZM5LZ24Y:** Record the two unshipped review recommendations with measurements (6cd713f)
- **TVDK9Q1Y:** Record two REFUTED hypotheses; recall skill gains reconstruction triggers (ff2d740)
- File TRDD-2OUMEVDS — make memgrep ENFORCE the recall technique (USER 2026-08-14) (20d514e)
- CANCEL TRDD-TVDK9Q1Y — the premise was false, there is no publish blocker (0059e67)
- **TRDD-2OUMEVDS:** Add the write->recall gap, measured rather than theorised (cd1ec13)
- **TRDD-ZM5LZ24Y:** Decide F1 and F2 — provenance gate fail-closed, shipped WITH the escape hatch (1dc86ab)
- **TRDD-ZM5LZ24Y:** Record F1+F2 implementation commit SHA (8ac28ac)
- **TRDD-ZM5LZ24Y:** Todo -> testing; record why an agent must not self-tick the last box (3407ad0)
- **board:** Release two stale blocks whose blockers are verifiably resolved (24ae3ce)
- Add TRDD-YOZ9TS3W — per-attempt llm-ext timeout shorter than one chunk (0855e94)
- Add TRDD-OO301H7D — external clear discards the blocked-on-human signal (P1) (fc834c8)
- **TRDD-UQW5IOAE:** Record advisor verdict; rewrite two unfalsifiable boxes (89cbcf2)
- **TRDD-KTXZJC6E:** Todo -> complete; all 13 boxes ticked AND falsified (cd0d603)
- Add TRDD-XCRTJ1C9 — mention vs use in agent-context-integrity (janitor#254) (13a00bf)
- **board:** Close 3 cards whose work landed this session, with their commits recorded (7eb417d)
- **TRDD-AM8JD9SG:** Dev -> todo — the WORK column was asserting work nobody was doing (ef10b1c)
- **TRDD-3QIQ2E6J:** Reword the last box — proven-by-construction, not 'Measured' (ed27bd8)
- **TRDD-OO301H7D:** Todo -> complete; all 6 boxes verified, commit recorded (5d35e0e)
- **board:** Close 4EKZ81MV; HK7IZ21Z -> testing with the acceptance list it never had (1c7b6d4)
- **memory:** Correct the detector count 39 -> 72; file TRDD-IEW2K659; close HK7IZ21Z (755c836)
- **board:** Close YOZ9TS3W and XCRTJ1C9 — decisions recorded, boxes ticked to evidence (2d2bb29)
- **board:** File SE7TP1EU; ZM5LZ24Y -> blocked, its last box was unfalsifiable (1010f54)
- **board:** Correct SE7TP1EU -- I generalized a one-host anomaly into a defect (6eeb2cd)
- **SE7TP1EU:** The guard fails BOTH ways -- a git-less plugin source is unguarded (eb62dbf)

### Features

- **security:** A blind-corpus bench for agent-context rule COVERAGE (janitor#226) (06ac918)
- **security:** First MEASURED coverage of the agent-context rules — 28% (janitor#226) (c06a44b)
- **security:** Branch-protection guard is ON by default (TRDD-G4BCRUP7) (09bb957)
- **security:** Measure the FALSE-POSITIVE half — 19% (janitor#226) (f0debad)
- **security:** Extend the coverage corpus to 13 of 21 rules — recall holds at 28% (janitor#226) (15ace48)
- **detectors:** Alarm on an orphaned memory-maintenance pending dispatch (TRDD-2112XCKO) (9e75a7d)
- **security:** Publish per-rule MEASURED coverage — 6 rules are FALSIFIED, not untested (janitor#226) (ebdbac9)
- **security:** Dns-exfil-long-subdomain measured — FALSIFIED 0/7 (janitor#226) (fc4ae19)
- **handoff:** Zero-token compaction via llm-externalizer — wire the dark switch (TRDD-1QJIZFFW) (df7d4cb)
- **heartbeat:** A fire prints "janitor heartbeat" and nothing else unless it matters (adcd8af)
- **memgrep:** Publish-globally normalization is a pre- AND post-condition of every page write (9ddb3cf)
- **janitor:** File a finding as an issue on the repo it belongs to (TRDD-WP7TCRME Rule 4) (da24993)
- **dispatch:** Restore a detector's executable bit instead of reporting it (TRDD-WP7TCRME Rule 3) (b8dbc25)
- **janitor:** Enforce the reports/ gitignore invariant, and FIX it (TRDD-WP7TCRME Rule 3) (7ad7c0e)
- **detectors:** Wire the reports/ gitignore guard — a library with no caller is the bug I keep fixing (254df25)
- **daemon:** Fleet config gaps are filed on the repo that HAS them (TRDD-WP7TCRME Rule 4) (d4d9f72)
- **trdd:** Check 6 — `blocked` that names no blocker is surfaced (TRDD-F4IBIDB6) (3f15a8e)
- **board:** Check 7 — a WORK column claiming activity nobody is providing (TRDD-F4IBIDB6) (6a0066d)
- **memory:** Defer a dispatch whose root is still in flight (TRDD-KVS6K7P9) (1051ed8)
- **board:** Detect open cards attacking one defect blind to each other (TRDD-XFPOAF2I) (20a1c14)
- **board:** Shipped-unreleased rung + JPL0JU86's fix is undone by a live mechanism (7b2c64e)
- **daemon:** Break the CC retry-watchdog wedge with an ESC (TRDD-WKTD5JTC) (3517836)
- **claudemd:** Migration PLANNER — the decision half, which writes nothing (TRDD-LFSWY0C6) (d82dc15)
- **claudemd:** The missing primitive — a per-block permitted-element classifier (TRDD-LFSWY0C6) (7b7b37e)
- **claudemd:** The DELIVERY half — a removal that refuses (TRDD-LFSWY0C6) (64b8283)
- **claudemd:** Apply POINTS at the index refresh it deliberately does not do (TRDD-LFSWY0C6) (e448b65)
- **split:** Headroom rule — never emit a sibling within ~10% of the cap (TRDD-RG4IUZ6I item 3) (7930ab2)
- **memory:** Split siblings stop re-litigating — a lineage marker, not a refusal (TRDD-3QIQ2E6J) (18cf018)
- **findings:** A human-only finding stops asking an agent to do the impossible (TRDD-KU3ERYFX) (2a6b8ed)
- **agents:** Wire the respawn fallback to a real caller (TRDD-KTXZJC6E part B) (8996e19)
- **fleet:** Record iTerm-automation probe outcome + rearm evidence age (TRDD-EZ3PMQYX, partial) (a0dfb90)
- **cold-cache:** Compaction that survives outages, capped fleet-wide, blocking (df8cf6a)
- **security:** The exfil ALARM verification ladder (TRDD-HYV0SOC6, owner ruling) (31aa2a9)
- **git:** Recover an orphaned .git/index.lock instead of stalling forever (janitor#245) (dc1af1e)
- **security:** Ship exfil-structural-probe UNMASKED behind the alarm ladder (TRDD-HYV0SOC6) (ec40533)
- **reload:** Shrink context before reloading plugins (TRDD-VHPYSN56) (f96cb58)
- **reload:** Extend shrink-before-reload to /reload-skills (TRDD-VHPYSN56) (9a26d14)
- **ci-status:** Signal CI SUCCESS, not just failure (USER rule 2026-08-14) (70403b8)
- **self-integrity:** Report a stale C3 last-good pin (TRDD-ZM5LZ24Y) (be8f525)
- **skills:** Add /janitor-externalized-compaction — the skill surface over the external clear (6476f2b)
- **version-update:** F1 provenance gate + F2 manual re-pin (TRDD-ZM5LZ24Y) (a8982a0)
- **blindspot:** Content-similarity signal so two cards on one mechanism can be linked (TRDD-4EKZ81MV) (155ee55)
- **memgrep:** Add-atom --supersedes — correct a fact without inventing a lesson (TRDD-3PWQK8NM) (81f38c4)
- **memgrep:** Recall EXPANDS the query and add-lesson warns on unfindable keywords (TRDD-2OUMEVDS) (9f1876f)
- **detector:** System-daemon-runaway — catch the fseventsd class at ~4GB, not 39GB (TRDD-HK7IZ21Z) (fe2c68e)

### Miscellaneous Tasks

- **repomap:** Refresh the project map — picks up classify_permitted/is_project_url_line (LFSWY0C6) and resolve_transcript/respawn_prompt_for (KTXZJC6E) (046cfe3)
- Type-check tests/ too — 176 real errors had accumulated unseen there (450151d)
- Run the test suite on every push — it only ran at release before (1b02a49)
- Bump version to 3.3.0 (1ef20a2)

### Performance

- **context:** Drop the auto repo map — ~45,600 tokens off EVERY turn (fe697c7)
- **publish:** Shard the test gate across cores -- 21:20 -> 2:45 (7.8x) (906cd93)

### Testing

- Gate the per-skill token budget locally (TRDD-IAJS6M9Z) (d31fd80)
- **global-control:** Drop three fixtures the doc-pinning test never uses (janitor#77) (5f88f0d)
- **security:** Re-baseline the agent-context bench after the rule repairs (janitor#226) (cbf7e92)
- Enforce execution-class inertness of the attack corpus and pattern modules (a2fa7fe)
- Re-anchor two guards their own fix had made stale (e8255ae)
- The $ROOTS guard no longer fails on a rewording of the warning it wants (ff7c293)
- **librarian:** Pin that the orphan notice never carries an absolute path (TRDD-YWMKNKVT) (2b18897)
- **memory:** Pin the AMOA case — three dropped passes alarm ONCE, not never (TRDD-2112XCKO) (7442087)
- **token:** Pin R11's lean-worker suggestion — reachable is not guarded (TRDD-G4BCRUP7) (6526704)
- **security:** Measure the five agent-context rules nobody had ever tested (janitor#226) (9138e98)
- **security:** Blind-authored attack sets cut dynamic-exec-in-body from 3/3 to 6/9 (TRDD-XOITBRIZ) (3a7c53d)
- **bench:** Devitalize 5 RC-70 corpus payloads without changing what fires (9a0472a)
- Classify the new `atom-after-footer` lint code as repair-covered (janitor#260) (87181cd)
- Split real-daemon-spawn tests to a serial lane; real e2e index.lock test (3cde6a8)
- **git-utils:** Literal return type + a refusal-reachability meta-test (TRDD-W0XT5B3B) (3eccb27)
- **daemon:** Prove R6/R9's session-liveness gate is DEFAULT-ON (TRDD-G4BCRUP7) (8c660d2)

### Spike

- **cost:** The 47% IDLE_TTL_EXPIRY figure does not reproduce — the avoidable cost moved (TRDD-B07VPT2G) (915cef5)
## [3.2.0] — 2026-08-12

### Bug Fixes

- **trdd-drift:** The two dead-symbol probes must share corpus and matching (TRDD-FDV1RQEB) (c23e9e4)
- **skill:** Keep janitor-memory-write under the 5000-token CPV budget (1183f8b)

### Documentation

- **memory:** A claimed chore transfers the ACT but not the BREADCRUMB (TRDD-UA4FAX67) (14fe80c)
- TRDD-5ZVS1DDP speculated about two other cards' states; both guesses were wrong (b1731a9)
- TRDD-FDV1RQEB complete — check 5 shipped at 9a9bf0fa, acceptance verified (900c521)
- Repair the FDV1RQEB approval log — my heredoc ate three backticked symbol names (5dd259a)
- TRDD-G4BCRUP7 STATE — 2026-08-12 session outcomes, so a compaction resumes from the card not the summary (9c325a9)
- **memory-update:** Authorship confers NO ownership — the wiki is collaborative (USER directive) (4ba8d12)
- **memory:** The wiki is collaborative — authorship confers no ownership (USER directive) (7707a42)

### Features

- **trdd-reconciliation:** Check 5 — a STATE block citing a symbol the tree no longer has (9a9bf0f)

### Miscellaneous Tasks

- Bump version to 3.2.0 (1129ffa)
## [3.1.5] — 2026-08-12

### Bug Fixes

- **rotator:** A live-identity change IS a rotation, whoever performed it (TRDD-UA4FAX67) (674c960)

### Documentation

- TRDD-631fa3de asserted the branch-protection auto-apply RUNS; it does not (default off) (18b4edd)
- Archive TRDD-VXFNDHXT → superseded — the TTL probe it is about no longer exists (d981051)
- Add TRDD-FDV1RQEB — detect a STATE block citing a symbol the tree no longer has (f4e1f65)
- Prototype TRDD-FDV1RQEB's dead-symbol check — 1 new find, 0 false positives (1d60e36)
- Add TRDD-B07VPT2G — IDLE_TTL_EXPIRY (47% of one session's cache waste) finally gets a card (99b57dc)
- TRDD-I6ZZWVDN testing -> backburner; its incidental finding finally has a card (4806ef3)
- Correct TRDD-B07VPT2G's own premise — EUWIHP0G did own this, and is complete (281203d)
- TRDD-B07VPT2G title said "never had a card" while its own body refutes that (21ca705)
- TRDD-UA4FAX67 — the post-rotation wake trigger cannot fire on a server-owned host (bdcf895)

### Miscellaneous Tasks

- Bump version to 3.1.5 (d79da5e)
## [3.1.4] — 2026-08-12

### Bug Fixes

- **memory-librarian:** A block-sequence globs: is a PRESENT globs: (janitor#252) (3fc40eb)
- **orphaned-resume-flag:** Day-bucket the LEDGER write, not just the drift line (ac741b6)

### Documentation

- Close TRDD-MADJ00KA and TRDD-842PBES7 — shipped 28 days ago, never closed (8d73535)
- TRDD-G4BCRUP7 — I re-asked a question the owner had already answered (3d2d0c8)
- TRDD-G4BCRUP7 — branch-protection auto-apply is shipped dark (verified) (9e89ad8)
- TRDD-JPL0JU86 — record the report-to-trdd false positive so it stops costing investigations (629866f)
- TRDD-AR9IUGIJ option C is void — af499ee3 deleted the machinery it would tune (2206bff)
- TRDD-50V256RH root cause falsified — /reload-plugins --force DOES re-point live skills (5ee1172)

### Miscellaneous Tasks

- Regenerate the fenced project map (465 files, 1630 lines) (3d5d968)
- Bump version to 3.1.4 (7d4b439)

### Styling

- **trdd:** One list marker per file — my `*` bullets blocked the 3.1.4 publish (d8a6dfa)

### Testing

- **qe390sja:** Prove the ESC+/model trace on iTerm, not just tmux (TRDD-QE390SJA) (ce9eb88)
## [3.1.3] — 2026-08-12

### Miscellaneous Tasks

- Refresh the CLAUDE.md project map and wikimem index (72f89c0)
- Bump version to 3.1.3 (786573d)

### Performance

- **memory:** Don't pay 200k to re-derive that nothing changed (janitor#140) (7f44d95)
## [3.1.2] — 2026-08-11

### Bug Fixes

- **fleet:** Never type a command over a non-empty input field (2026-07-17, closed) (3931f44)

### Miscellaneous Tasks

- Bump version to 3.1.2 (0ccae82)
## [3.1.1] — 2026-08-11

### Bug Fixes

- **memgrep:** Treat link sections as footers when inserting an atom (janitor#250) (7edbb75)
- **memgrep:** `## See also` is a footer too — completing the janitor#250 anchor (36a416e)

### Documentation

- TRDD-G4BCRUP7 STATE — released as v3.1.0, CLI-verified, two owner decisions left (88994ef)
- Correct TRDD-G4BCRUP7 — a permission-blocked session is ALREADY ESC'd (79489cb)
- **memory:** Record the twin footer-anchor invariant (ATOM-Q2PU-PYE0) (b72fd5e)

### Miscellaneous Tasks

- Bump version to 3.1.1 (32c1573)
## [3.1.0] — 2026-08-11

### Bug Fixes

- **hooks:** The token advisory must be actionable and anomalous (janitor#246, TRDD-KI6OWCZT) (3890d7b)
- **hooks:** Make the baseline advisory REACHABLE, and stop the hook crashing on its own log (6410277)
- **hooks:** Make the output advisory reachable on a heartbeat-dominated log (TRDD-KI6OWCZT) (03253c6)
- **hooks:** Stop the SessionStart re-plumb nudge from firing mid-session (TRDD-BRHJHWW0) (d104081)
- **publish:** Raise the CPV gate bound to 2x the LOADED run, not 3.8x an idle one (42add9e)
- **ci-status:** A CI failure must outlive the heartbeat that found it (R16) (27b190c)
- **agents:** Stop agents COMPOSING report paths, and fix a space-unsafe root (janitor#248) (24ed51a)

### Documentation

- Add TRDD-KI6OWCZT — token-spike advisory must clear the noise bar (janitor#246) (afec741)
- TRDD-KVS6K7P9 — the clobber can change SCOPE+ROOT, and the contract invites the re-read (f0581f0)
- Add TRDD-G4BCRUP7 — armed once means autonomous forever (owner directive 2026-08-11) (129c53d)
- Add TRDD-JPL0JU86 — an unmaintainable page must not abstain silently (janitor#249) (0b27122)
- TRDD-G4BCRUP7 STATE — audit done, 6 of 16 shipped, two hard constraints named (99bf7b7)

### Features

- **model:** Switch models automatically when a window is spent (TRDD-G4BCRUP7 R7) (04065cb)
- **alerts:** Tell the reader what to DO about a token spike (R11) (cb182b6)
- **rate-limit:** Rotate on a 429 instead of waiting out the window (R9) (04a8fdf)
- **memory:** Background wikimem curation is ON again, at 1/day (R14) (dd26f27)
- **daemon:** Actually run the fleet-wide plugin updater (R3) (fddbbe2)
- **plugins:** Commit the settings file in the script, not via the model (C2) (4037b1f)
- **fleet:** Dismiss a blocked session when nobody is there to answer (R6) (870cddb)

### Miscellaneous Tasks

- Bump version to 3.1.0 (5a98fbd)

### Testing

- **chores:** Fleet-plugins-update is the SEVENTH unabsorbed chore — and that is a finding (5631950)
## [3.0.0] — 2026-08-08

### Bug Fixes

- **publish:** Bound the release-notes body — run 12's HTTP 422 (b789109)
- **detectors:** Read-only git never takes index.lock — GIT_OPTIONAL_LOCKS=0 (janitor#245, TRDD-76XSELZ7) (846fd20)

### Documentation

- Align the last two artifacts with the linear-history removal (USER Tier-3 ruling) (2216360)
- Add TRDD-88ZVEQY7 + TRDD-76XSELZ7 — stale fleet-audit payload; detector optional-locks (365eac8)
- Add TRDD-BRHJHWW0 — one arm per session, no tier renews (USER directive) (4fdbe31)
- Add TRDD-TUIBWHT7 — arm once, persistent state, silent session plumbing (USER directive) (3feca4a)
- TRDD-EZ3PMQYX REVISED — launch-context cause retracted; call-site error-vs-timeout is the fix (26ab182)
- TRDD-BRHJHWW0 dev -> complete — tier renews deleted at af499ee3 (TRDD-BRHJHWW0) (71e2e1c)
- Complete CI6ZTNB9's archival frontmatter (column: superseded) — the mv-stages-only-the-rename gotcha struck again (84223e3)
- TRDD-TUIBWHT7 todo -> complete — shipped at 65e537dc (TRDD-TUIBWHT7) (b26efe5)

### Features

- **cadence:** One arm per session — tier-driven renews deleted (USER directive, TRDD-BRHJHWW0) (af499ee)
- **arm:** Arm once, armed forever — persistent machine claim + silent re-plumb (USER directive, TRDD-TUIBWHT7) (65e537d)

### Miscellaneous Tasks

- Bump version to 3.0.0 (62143b2)

### Testing

- Re-anchor the cost-phase order guard — its old anchor was the deleted tier phase (TRDD-BRHJHWW0) (b47c099)
## [2.8.2] — 2026-08-08

### Bug Fixes

- **publish:** Test-gate bound 1800s -> 3600s — load-unsatisfiable, not strict (0a82eac)

### Documentation

- Add TRDD-2112XCKO — orphaned memory-maint-pending detector (15bd5cc)
- Add TRDD-9PDH8G0W — iTerm alarm unconditional-negative discriminator (2b4a585)
- Add TRDD-9MCGBPR7 — arm sweep on failed CronDelete (janitor#239) (b35965f)
- Add TRDD-EZ3PMQYX + TRDD-KU3ERYFX — launch-context alarm branch; human-only findings class (ec1e917)
- TRDD-2112XCKO — LOCAL scope is the load-bearing case (janitor#238) (f1f192f)
- **memory:** The fleet ownership directive — iTerm automation is janitor-owned, peers file issues (a7217ea)
- TRDD-EZ3PMQYX — surface per-instance host type in the alarm (janitor#240 ask 2, #235) (6edab75)
- Add TRDD-RG4IUZ6I + TRDD-KVS6K7P9 — split carries refusals forward; per-dispatch pending state (cdea3a9)
- Add TRDD-YWMKNKVT — librarian notice channeling fix + overview globs exemption (janitor#243) (d25122d)
- Refresh the CLAUDE.md project map (466 files) — cleared project-map-drift (fa704d7)

### Miscellaneous Tasks

- **pipeline:** Align to CPV canon 5.4.0 — pin bump, 4 canon deltas, needle-inert nosec (65078ef)
- Bump version to 2.8.2 (2ed243f)
## [2.8.1] — 2026-08-08

### Bug Fixes

- **fleet:** The alarm now LOOKS for the positive evidence it names (peer finding, #92/#229) (13b3e24)

### Documentation

- **memory:** The second-view enumerator, recallable by symptom (TRDD-DFKEXO79) (6e781d3)
- TRDD-DFKEXO79 component 3 decision lines; card dev -> complete (TRDD-DFKEXO79) (20bd653)
- Refresh CLAUDE.md wikimem index + project map (new page, enumerator lib) (31fd9fc)
- Archive TRDD-DFKEXO79 → completed (7a4a641)
- **memory:** Devitalize the backtick-injection lesson — words, not executable shape (ba36a4f)

### Miscellaneous Tasks

- Bump version to 2.8.1 (9838ffe)

### Testing

- **memory:** Pin the CC 2.1.224 slug-truncation risk — which is PROVEN live, not latent (TRDD-DFKEXO79) (55e4435)
## [2.8.0] — 2026-08-08

### Documentation

- **memory:** The interrupted-install incident, as recallable PROJECT knowledge (f52f4e9)
- Add TRDD-DFKEXO79 — CC 2.1.224 alignment implementation card (13e2018)
- TRDD-DFKEXO79 todo -> dev — component 1 pure lib delegated (TRDD-DFKEXO79) (ac38d28)

### Features

- **fleet:** Cwd-keyed `claude agents --json` enumerator — the grant-free second view (TRDD-DFKEXO79) (942f6f1)
- **fleet:** The iTerm alarm now states which way the second view discriminated (TRDD-DFKEXO79) (f4ad016)

### Miscellaneous Tasks

- Bump version to 2.8.0 (8046f6e)
## [2.7.2] — 2026-08-07

### Bug Fixes

- **tests:** The publish-lock test no longer DELETES the live lock mid-publish (a52d519)
- **fleet:** Report what the iTerm probe MEASURED, not what it implied (janitor#229) (7e9d9d9)
- **memory:** One definition of "needs work" for atomize + consolidate too (janitor#227) (b74a3ea)
- **publish:** Re-arm the publish lock after the test gate (2f556f3)
- **self-integrity:** A missing manifest on an INSTALLED root is a finding, not silence (58cc3df)
- **memory:** Accept any Sequence in the refusal ledger's read paths (unblocks publish) (0b08139)
- **cadence:** The pending-agents count reads the manifest of the sd it was GIVEN (7c40116)
- Apply the 9 verified findings of the pre-release review (/code-review high) (83d83e5)

### Miscellaneous Tasks

- Bump version to 2.7.2 (efbedc3)
## [2.7.1] — 2026-08-07

### Bug Fixes

- **telemetry:** Stop PUSHING account-window usage into agent context (janitor#230) (0bf6e5b)

### Documentation

- **memory:** The publish tree-freeze is now ENFORCED, and it recurred before it was (f8c2caa)

### Miscellaneous Tasks

- Bump version to 2.7.1 (66e7d78)
## [2.7.0] — 2026-08-07

### Features

- **publish:** Make editing the tree mid-publish IMPOSSIBLE, not merely discouraged (ee5b5d6)

### Miscellaneous Tasks

- Bump version to 2.7.0 (fa4cda0)
## [2.6.0] — 2026-08-07

### Bug Fixes

- **rotator:** Tell a Cloudflare refusal apart from a dead refresh token (janitor#228) (9f988b1)
- **memory:** One definition of "needs repair", consumed by the skill (janitor#227) (c075312)

### Features

- **window-burn-rate:** Stop pushing account-window usage at agents — opt-in now (dc2084c)

### Miscellaneous Tasks

- Bump version to 2.6.0 (01b0703)
## [2.5.2] — 2026-08-07

### Bug Fixes

- **memory:** Wire the refusal WRITE side so an abstain is remembered (janitor#212) (619efd0)
- **memory:** Keep the consolidate skill body under the CPV token cap (janitor#212) (794bd4c)

### Miscellaneous Tasks

- Bump version to 2.5.2 (44c47fe)
## [2.5.1] — 2026-08-07

### Bug Fixes

- **detectors:** Claimed-chore-stale calibrates its bound from the EXECUTOR's stamps, not our roster (janitor#225) (3becd9a)

### Documentation

- **TRDD-7PYTX4E9:** Complete -> published (v2.5.0) — the 29-day gap is closed (89024fc)
- **TRDD-6CRC9SQQ:** Dev -> human_review — item 1 is released, only the owner's item remains (44f5ab3)

### Miscellaneous Tasks

- Bump version to 2.5.1 (167443a)

### Testing

- **keepalive:** Status test no longer depends on the host's real launchd domain (c13807d)
## [2.5.0] — 2026-08-07

### Bug Fixes

- **dispatch:** Bound the heartbeat's presence wait to 9s, not the 120s default (24c2567)
- **daemon:** Stable TCC identity + never evict own version-less daemon + quarantine symmetry (TRDD-DB1P25S4) (75332ba)
- **terminal_trigger:** The verified injector could never send a command WITH ARGUMENTS; add send_verified + ESC-only builder (TRDD-QE390SJA) (dd72291)
- **terminal_trigger:** A selection-menu row is no longer read as the input field (janitor#222) (70afff5)
- **token-burn:** A model-fallback verdict requires a PROVEN-FRESH snapshot (janitor#222) (b08c2d6)
- **rotator:** Stop rotating onto an account whose model window is already spent (TRDD-QE390SJA) (674fe78)
- **agent-context-integrity:** Never aim the auto-fixer at locally-authored safety docs (janitor#167) (30b666a)
- **idle-clear:** Use the ratified injector — the lever was structurally dead on iTerm (TRDD-5C42VCUX) (71e65e9)
- **memory:** Lint wikimem pages AT WRITE TIME — the enforcement never existed (c7089dd)
- **detectors:** Make claimed-chore-stale executable in git (mode 100644 -> 100755) (5ca35d8)
- **daemon:** The crash-loop breaker no longer quarantines a healthy version for orderly restarts (janitor#216, #217) (747c202)
- **detectors:** Narrow three noisy detectors without blinding any of them (janitor#189, #214, #215) (aa24709)
- **memory:** Flow-style frontmatter made harvest treat every curated overview as RAW forever (janitor#212, #210, #201) (4bbe7b3)
- **clear:** Scope CLAUDE_PROJECT_DIR to the spawned child, and redact private paths from two TRDDs (3a224c8)

### Documentation

- **board:** Close FQXBURNR and restore the provenance link it lost (c4e0c34)
- **board:** REOPEN dfc0959a and 5ZVS1DDP — I closed two cards that said they were not done (8771685)
- **TRDD-5ZVS1DDP:** The silent safety gap is CLOSED — deployment chain verified link by link (0cdcfb6)
- **rotator:** OWNER supersedes "the login half must never be automated" (5ac2a5a)
- **TRDD-dfc0959a:** Unbrowse cannot select Chrome profiles — the folder swap is part of every replay (75ebfa7)
- **TRDD-dfc0959a:** The swap folders are unbrowse's OWN clones, not Chrome's profile dirs (ffc90dd)
- **board:** AWXK0RFT resolved as the owner predicted; KQ9WM4TZ unblocked with its stopgap now running (feb92fd)
- Add TRDD-DB1P25S4 — run the daemon under the signed python3.12 so the iTerm TCC grant applies (c4442e6)
- **TRDD-DB1P25S4:** Owner correction — the granted client is uv's MANAGED cpython; the mechanism is PATH STABILITY (1b23d6c)
- **TRDD-DB1P25S4:** The grant is PROVEN and the hot-apply is not durable — stop-rule + the 3-part code fix (c4546b3)
- **TRDD-DB1P25S4:** STATE — 3-part code fix landed in 75332ba0; checklist updated, end-to-end observation + publish remain (07d1663)
- **fleet_inject:** Pin the ai-maestro CLI channel's reachability contract (janitor#218) (d449b5a)
- **TRDD-KQ9WM4TZ:** Testing evidence — one gate-clean dark-window beat proven (stamp 18:33:45, mid eviction-loop); quiet gates are artifact-free so the 300s-window criterion is unobservable now that DB1P25S4 fixed the daemon (d6d2333)
- **TRDD-KQ9WM4TZ:** Testing -> ai_review — breadcrumb shipped (ac419694), dark-window evidence accepted; review focus recorded (055eb24)
- **TRDD-KQ9WM4TZ:** Ai_review PASSED -> human_review — dedupe-vs-pacing, no-peers log line (rejected as duplicate), and the cross-session write race each reviewed with verdicts recorded (2cc0434)
- **repomap:** Refresh the fenced project map — picks up _managed_python_path, _is_own_stable_daemon, record_outcome from today's daemon/detector work (a16c687)
- Add TRDD-5C42VCUX, TRDD-PXP08ZQC, TRDD-UA4FAX67 — the owner's 2026-08-06 janitor failure report as three atomic cards (idle auto-clear never engages; external zero-turn handoff via llm-ext; post-rotation ESC unblock) (ebe5baf)
- Add TRDD-50V256RH, TRDD-AR9IUGIJ, TRDD-6CRC9SQQ — owner failure report items 5-7 (self-update convergence; eliminate re-arm; server-delegation alignment contract) (c17db60)
- Add TRDD-QE390SJA — model-scoped window exhaustion must fall back to another model, not rotate the account (janitor#222; owner typed /model opus by hand today) (0331753)
- **repomap:** Refresh the fenced project map — picks up send_verified, build_esc_only_steps, model_fallback_verdict from the QE390SJA work (f9280a2)
- **TRDD-9MQ25PNH:** Testing -> ai_review — the 05:22 LOCAL dispatch verified BOTH halves in production (read-back consulted; content-hash re-arm fired on a real 08-05 edit, stored 4062c90a vs current 1296d0a5), agent re-judged and re-recorded (3c45896)
- **TRDD-QE390SJA:** Correct the derived task — the scoped-window eviction was the SERVER's rotator, and the janitor's gap is the MIRROR of it (04b8cf1)
- **memory:** Capture the daemon process-IDENTITY + restart-gate lessons (TRDD-DB1P25S4, janitor#211/#219/#216) (27ace42)
- **TRDD-QE390SJA:** Todo -> testing — both halves code-complete; the one open box is the owner-watched live switch (674fe785 closed the rotator mirror gap) (038f1bb)
- **TRDD-UA4FAX67:** Todo -> testing — rotation now triggers the wake (f3f664de); wake-pass default decided (periodic stays dormant, a rotation overrides) (27980a4)
- **TRDD-PXP08ZQC:** Phases 1-2 done — gate + watcher + template handoff; daemon wiring is the one open box (c02906a)
- **TRDD-PXP08ZQC:** Record the llm-ext composer as tried-and-rejected-on-evidence (c8a0f36)
- **memory:** Capture the external zero-turn clear + correct a rationale it outdated (56457ba)
- **TRDD-AR9IUGIJ:** Spike decided — A + C; B was already shipped and cannot do what the card asked (15b6e5c)
- **TRDD-50V256RH:** Root cause found — the reload stamp is a side-effect of a task the daemon SKIPS (0c59765)
- **TRDD-50V256RH:** WITHDRAW my root cause — I inferred it from an API instead of reading the log (32c28eb)
- **TRDD-50V256RH:** Retire the NEXT ACTION written for the withdrawn cause (3e7ff34)
- **TRDD-50V256RH:** Root cause established — /reload-plugins does not re-point live SKILLS (89fde6b)
- **TRDD-50V256RH:** NEXT ACTION is now an owner decision, not a code step (b38f1df)
- **memory:** Capture live-skill staleness — /reload-plugins does not re-point loaded skills (be5186b)
- **TRDD-6CRC9SQQ:** A confirmed contradiction blocks item 1 — the yield path may never have run (f985203)
- **TRDD-6CRC9SQQ:** The 'zero yield lines' evidence is unsafe — log provenance never established (9f7830b)
- **CLAUDE.md:** Refresh the project map + wikimem index (drift I introduced) (e9a93bf)
- **TRDD-6CRC9SQQ:** Record the lsof dead end so it is not repeated (de01185)
- **TRDD-6CRC9SQQ:** The "contradiction" was a wrong log file — daemon DOES yield; item 1 unblocked (1ebdfe6)
- **memory:** Where the global daemon logs, what [s:] means, and why an empty grep proved nothing (eae64fb)
- **TRDD-6CRC9SQQ:** Item 1 shipped (1e803e47) — acceptance box 2 ticked, next action is the un-yield decision (0af7d52)
- **TRDD-6CRC9SQQ:** Un-yield decision recorded (NO — alarm only) + the #221 replay argument (c777d12)
- **TRDD-7PYTX4E9:** Planned -> complete — the column lied for 28 days about finished work (82fbdbb)
- **TRDD-CI6ZTNB9:** Record a withdrawn "live reproduction" — the fix is already shipped (a685cca)
- **memory:** The #212 abstain-burn root cause — a misparsed flow-style frontmatter, not a missing gate (b438b23)
- **TRDD-QE390SJA:** Rewrap a continuation line so markdownlint stops reading it as a list marker (cf3cc34)

### Features

- **peer-freeze-recovery:** Trace every beat outcome, quiet gates included (TRDD-KQ9WM4TZ) (ac41969)
- **token-burn:** Model_fallback_verdict — the pure gate for switching model instead of rotating (TRDD-QE390SJA, janitor#222) (d7d8e9c)
- **terminal_trigger:** Three-state model-switch confirmation (TRDD-QE390SJA, janitor#222) (491a2c3)
- **model-fallback:** The pure planner — decide whether to type /model <target> (TRDD-QE390SJA, janitor#222) (251056e)
- **model-fallback:** The detector — wire the gate to the typist, dark by default (TRDD-QE390SJA, janitor#222) (ab00a40)
- **fleet:** A successful rotation now unblocks the panes it just fixed (TRDD-UA4FAX67) (f3f664d)
- **external-clear:** The zero-model-turn clear gate + template handoff (TRDD-PXP08ZQC) (def783f)
- **external-clear:** The watcher — decide, compose and fire without a model turn (TRDD-PXP08ZQC) (95a5bed)
- **6CRC9SQQ:** Watch the chores the SERVER claimed — and repair the seam 71e65e91 broke (1e803e4)

### Miscellaneous Tasks

- Adopt CPV canon where divergence was accidental; declare it where it is deliberate (eaaaabd)
- Bump version to 2.5.0 (b0790d0)

### Revert

- **external-clear:** Drop the llm-ext handoff composer — the template IS the answer (TRDD-PXP08ZQC) (07e8d98)

### Testing

- **idle-clear:** Guards that bite on the iTerm-blind injector (TRDD-5C42VCUX) (99b9e82)

### Experiment

- **external-clear:** Llm-ext handoff composer + its real measurement (TRDD-PXP08ZQC) (73a426c)
## [2.4.1] — 2026-08-05

### Bug Fixes

- **memory-scope-leak:** A git ref and a file path are not leaks ([#209](https://github.com/Emasoft/ai-maestro-janitor/issues/209)) (65705f5)

### Documentation

- **board:** Close the 13 TRDDs that v2.4.0 actually released (da07f3f)

### Miscellaneous Tasks

- Bump version to 2.4.1 (3d8929a)

### Testing

- **209:** Fragment the fake token literal per the secret-hygiene gate (fab6666)
## [2.4.0] — 2026-08-05

### Miscellaneous Tasks

- Align version to the remote's 2.3.1 before re-cutting the release (4175e59)
- README badge to 2.3.1 — completes the version alignment (31ea21d)
- Bump version to 2.4.0 (c48fe81)
## [2.3.1] — 2026-08-05

### Bug Fixes

- **trdd:** A DONE next-action line no longer masks the pending ones (TRDD-N7NZOYAK) (77b9ba2)
- **trdd:** Scope prose-named blockers to the paragraph, not the whole body (TRDD-FR4NS7I4) (7786f14)
- **memory-librarian:** Anchor the antonym branch to the shared subject (janitor#106) (7840742)
- **detectors:** Stop scoring gitignored trees as the project's supply chain (janitor#99) (8229eb0)
- **memgrep:** Lint must skip non-pages when named explicitly (janitor#165) (77a193c)
- **fleet:** Never type into a session that is awaiting a HUMAN answer (TRDD-8IZ8COQ8) (d4498ff)
- **fleet:** The awaiting-user guard must not fire on a long-running tool (TRDD-8IZ8COQ8) (b60f07a)
- **detectors:** Git decides what the project ships, not a hardcoded name list (janitor#99) (34c14f7)
- **security:** A gitignored CLAUDE.md is still auto-loaded — scan it (janitor#167) (b9a34b0)
- **security:** Delete the severity filter — a neuter proved it pinned nothing (98161b6)
- **safety:** Block gh publishes carrying emails or third-party @mentions (2ace1f0)
- **bench:** Refuse a corpus/baseline mispairing instead of scoring it (TRDD-DO6X4ZF8) (f0ef029)
- **TRDD-8IZ8COQ8:** Land the closure text 79f3063 claimed but did not commit (7f00753)
- **rules:** The PRRD byline shipped a bare mention that paged a real org ([#171](https://github.com/Emasoft/ai-maestro-janitor/issues/171)) (37a3b4c)
- **cadence:** A stale resume-directive pinned idle sessions to FAST forever (TRDD-UQW5IOAE) (d2a5204)
- **intent:** Add the missing `clear` verb — the user's own command was refused (a2fac71)
- **rules:** Retract two false mention claims I shipped this morning ([#172](https://github.com/Emasoft/ai-maestro-janitor/issues/172)) (2f5125f)
- **memory:** Break the lesson-id deadlock between the oracle and memgrep's grammar (9f7ec64)
- **inject:** The iTerm scripts targeted a WINDOW id — AppleScript rejected them (61252a9)
- **skills:** Stop globbing the ephemeral plugin cache (owner directive) (818c2f8)
- **ghcfg:** Stage remote workflow files so fleet repos get required checks (TRDD-157OH2D7) (baec104)
- **memgrep:** Migrate refuses malformed atom props + already-on-dest atoms (TRDD-VJCMZ2OP) (34a430d)
- **resume:** Re-check the pending flags at TYPE time, not just fire time (TRDD-DXM75JB2) (9711e15)
- **memory:** Normalize load-bearing tokens with the haystack's whitespace collapse (c05ab94)
- **librarian:** A prose line starting with an inline code span is not a fence delimiter ([#178](https://github.com/Emasoft/ai-maestro-janitor/issues/178)) (fa1a2ed)
- **review:** Apply verified findings 1,2,6,7,8,9 from the xhigh code review (c669107)
- **review:** Findings 3,4,5,10 of the xhigh code review — the remaining four (dddce72)
- **rotator:** Check-login/lifetime-status stop asserting an identity they never check (TRDD-X6N7I8CA, janitor#179) (35eaf8c)
- **project-memory-tracked:** Roll back the trial append when the negations are inert (janitor#180) (fcf51ce)
- **memory:** P3 of the write-concurrency gate — Python-side realpath lock parity + bridge append under the scope lock (TRDD-7YHT3FNK) (70fd8a1)
- **tests:** Raise the daemon-closure cap to 45 — burn_gate.py legitimately joined it (20173a4)
- **compact:** Fire the cold-cache compact on last-turn AGE, not context size (TRDD-HCGI143H) (169bd32)
- **memory:** No_dangling_refs must exempt the survivor slug (janitor#183) (c125b9f)
- **memory:** A merge must redirect the MEMORY.md pointer too (janitor#182) (e3cdf74)
- **memgrep:** Don't let one panicking test poison ENV_MUTEX for its siblings (13e4c7b)
- **memgrep:** The lesson metadata scan must ignore brackets inside a quoted desc (janitor#184) (745e27c)
- **agents:** Never store the parent session's transcript as an agent's respawn handle (4c4e3c6)
- **cadence:** A dead background agent no longer pins the heartbeat to FAST for a week (51ffb05)
- **memory:** Nudge on COVERAGE, not on when a note was last written (db7a6c5)
- Unblock the publish gate — 3 CRITICALs, all introduced by today's own work (7a4aff9)
- **skills:** Clear 4 of 7 publish MAJORs — 2 over-long descriptions, 2 oversized bodies (0a28138)
- **skills:** Rename to janitor-project-cld-md-optimizer + trim consolidate under budget (d07790c)
- **skills:** Clear the last 2 publish MAJORs (1170be5)
- Apply 10 verified code-review findings — 4 HIGH, 5 MEDIUM, 1 LOW (d63a9b4)
- **trdd:** Clear 5 markdownlint MD004 NITs that blocked the publish gate (adb88d2)
- **memgrep:** A [^N] inside an HTML comment is not a live footnote ref (janitor#173) (c7923b3)
- **detectors:** Clear 5 false-positive classes (janitor#174 #170 #159 #163 #126) (def81c3)
- **memory:** 4 real defects in the memory subsystem (janitor#176 #162 #158 #182) (a33ab90)
- **resume:** Stop re-issuing a SHIPPED task forever (janitor#185 #186 #129 #136 #154) (550bab0)
- **memory:** Code-span parity, per-rule remedy, merge write-count (janitor#187 #138 #145) (9bae23c)
- **governance:** Correct a FALSE claim in a shipped guard + 5 rule defects (janitor#172 #144 #143 #139 #132 #103) (c80945e)
- **infra:** Repomap honesty + rotator.log rotation under two writers (janitor#175 #177) (2fdea42)
- **harness/bench:** Realpath asymmetry + bench lint gate + issue-code docs (janitor#142 #119 #127) (4e26e36)
- **rules:** Bring the shipped corpus back under the context-floor cap (f263f36)
- Last issue cluster — provenance, FP classes, ticket gap (janitor#164 #99 #151 #127) (08bb823)
- **memgrep:** Resolve wikilinks same-scope-first (janitor#192 #151 #145) (54dee6f)
- **memgrep:** A clean lint says "0 finding(s)" instead of nothing (janitor#191) (e4e5ff1)
- **daemon:** Alarm on global chores a live server displaces but never absorbs (95f2664)
- **fleet_status:** Never render a failed scan as "0 running instances" (e2270b3)
- **detectors:** Make global-chore-blackout executable (4fe295e)
- **fleet_status:** Five reporting defects the owner found in the dashboard (768be76)
- **fleet_status:** Write the dashboard inside the project, not the system temp dir (71a791b)
- **detectors:** Ask which chores NOBODY will run, not which ones were never absorbed (1acbde2)
- **memory-librarian:** A stale proposal in a non-LOCAL root must not read as live (50f41dc)
- **daemon:** Gate the loop exit on the SAME decision as the spawn gate, or it flaps (88e6f45)
- **skill:** Bring janitor-memory-consolidate under the CPV token cap and complete its TOC (6da93e1)
- **cadence:** A failed TTL probe must not overwrite a measurement with a guess (TRDD-VXFNDHXT) (869a014)
- **ci:** Align the workflow CPV pins with .cpv-version — I bumped half the SSOT (2b214c9)
- **memory:** Consolidate's gate skips changes confined to already-refused groups (TRDD-9MQ25PNH) (da36c68)
- **memory:** TRDD citations were wrapped in wikilink brackets — unwrap all four (1642153)
- **tests:** Assert spec/loader non-None so mypy accepts the dynamic import (7e55aa5)
- **dirty-tree:** Stop recommending 'git stash' — it silently swallows other agents' work ([#188](https://github.com/Emasoft/ai-maestro-janitor/issues/188)) (83d38a5)
- **report-to-trdd:** Accept the abstain marker the curator ACTUALLY writes ([#121](https://github.com/Emasoft/ai-maestro-janitor/issues/121)) (5312a2a)
- **trigger:** The presence gate DEFERS to a busy pane instead of abandoning the send (62ff1ca)
- **rules:** De-vendor lean-ctx from the shipped heartbeat-protocol rule ([#10](https://github.com/Emasoft/ai-maestro-janitor/issues/10)) ([#202](https://github.com/Emasoft/ai-maestro-janitor/issues/202)) (5bab427)
- **tickets:** A human-refused proposal suppresses re-proposal until its evidence changes ([#203](https://github.com/Emasoft/ai-maestro-janitor/issues/203)) (3c565fe)
- **detectors:** Two structural false-positive modes in the memory detectors ([#204](https://github.com/Emasoft/ai-maestro-janitor/issues/204)) (a2ad775)
- **rules:** The shipped byline template must carry no @ — a bare handle pages a real account ([#198](https://github.com/Emasoft/ai-maestro-janitor/issues/198)) ([#205](https://github.com/Emasoft/ai-maestro-janitor/issues/205)) (d7bb754)
- **detectors:** The dirty-tree nudge must never recommend a bare git stash ([#206](https://github.com/Emasoft/ai-maestro-janitor/issues/206)) (812da1d)
- **tests:** The suite must pass from a clean /tmp clone — three env-coupled defects ([#207](https://github.com/Emasoft/ai-maestro-janitor/issues/207)) (413723c)

### Documentation

- **TRDD-MKCPL3ZH:** Close the card — shipped in v2.3.0, installed at user scope (468d91d)
- **memory:** The consolidate candidate gate — measured, and why NOT to add one (6c18ca0)
- **TRDD-WUUR2DFX:** Correct a stale STATE claim; backburner is right (TRDD-WUUR2DFX) (54deb32)
- **kanban:** Close 4 delivered cards that were held open by non-blockers (487d129)
- **kanban:** Reconcile 3 cards whose STATE prose and frontmatter disagreed (1cd0d44)
- **kanban:** 3XS3PDCF -> published, 32acd15f -> testing (cb511fd)
- **kanban:** VQ4LX7ND -> testing; its CPV blocker was already dead when it was filed (c3fd6e3)
- Add TRDD-FR4NS7I4 — check4 treats any mentioned id on a held card as a blocker (7f08b88)
- **FR4NS7I4:** Stop the card about block-detection from tripping block-detection (4077386)
- **kanban:** SLFMG704 -> complete; extract its NPT as TRDD-I6ZZWVDN (55445ad)
- **kanban:** Advance EFTQB9RR and K3WQ7XM9 to published, together as they asked (47a13e8)
- **kanban:** Empty the dev column of cards nobody is working (e977349)
- **TRDD-HI0BGQGJ:** The final hop ran live — mechanism proven, latency not (06275e0)
- **TRDD-I6ZZWVDN:** Measured — SessionStart answered, StopFailure not measurable yet (d8a9281)
- **kanban:** RDFWQIFA -> complete; its acceptance list run rather than assumed (81b6c8d)
- **memory:** The merge docs said the verifier does not guard body facts — it does (d2027af)
- **kanban:** File 9K0O5YBQ's three NPTs and close the audit (fc4a349)
- **rules:** Name BOTH keyword syntaxes — the verb's and the stored form's (0216175)
- **TRDD-LI7ENU2A:** The jitter data does not exist — I was wrong an hour ago (9624deb)
- **memory:** Record that memgrep version-skews per host (janitor#165) (c86f479)
- **TRDD-8IZ8COQ8:** Both open questions answered by measurement (todo -> testing) (c133444)
- **TRDD-8IZ8COQ8:** Record b60f07a — the correction's own SHA (d65515c)
- **TRDD-2C8XFOW9:** The blocker's two artifacts exist; the guessed verb did not (3962dbc)
- **boundary:** Skills must INSTRUCT the ai-maestro CLI rule, not merely obey it (ecb0485)
- **TRDD-8IZ8COQ8:** Close it — fix shipped and verified; the deferral becomes DXM75JB2 (79f3063)
- **TRDD-DO6X4ZF8:** Ai_review performed at current HEAD -> human_review (eae94c0)
- **TRDD-YBOZW3ES:** Ai_review performed against the LIVE corpus -> human_review (dfd6d6e)
- **TRDD-EUWIHP0G:** Correct a prose/frontmatter mismatch in the STATE block (1acaa1a)
- **TRDD-CI6ZTNB9:** Perform the asked-for AI review; record the commits -> human_review (51cae3b)
- **kanban:** Record the commits that N7NZOYAK and FR4NS7I4 actually shipped (97a691b)
- **TRDD-QK7M2B0X:** Phase B step 2 first half shipped; the singleton is what remains (777c1dc)
- **TRDD-QK7M2B0X:** Mark the "only the MODE flags move" bullet stale, don't delete it (365fe21)
- Add TRDD-OR527LNW — propose fixing G1.1's bare mention (golden, user-only) (c46aa05)
- Add TRDD-UQW5IOAE — force handoff-and-clear on an idle keep-warm session (8ab8c28)
- **TRDD-QK7M2B0X,UQW5IOAE:** Record the advisor verdict — one gap found, one premise falsified (4c8741b)
- **TRDD-UQW5IOAE:** Step 1 found a BUG, not a missing feature — record d2a5204 (ace5216)
- **TRDD-UQW5IOAE:** Shipped 67802e0 — record that my 'superseded' call was wrong (5ef4829)
- File TRDD-0BVF4K7E (blind phase-B splice) + measure UQW5IOAE's gate (d614b5f)
- **5ZVS1DDP:** Close the soak with live evidence; split out the gap it exposed (d08d9ce)
- **K1RJUYGK:** Run the falsification it waited 20 days for — PARTIAL, not a pass (bed70e6)
- **K1RJUYGK:** The falsification SETTLES it — the retraction was right, close (20463c2)
- **VJCMZ2OP:** 1e shipped; migrate verified on clean input; bullet 3 fails (3dc9581)
- **0BVF4K7E:** Phase 2 shipped — chained child, owner chose Option 1 (4a70c99)
- File TRDD-AWXK0RFT (publish blocker) + record 157OH2D7's applied fleet fix (96aa940)
- **AWXK0RFT:** The blocker's real impact — every fix shipped today is INERT (aefb7ca)
- **TRDD-0BVF4K7E:** Close on an OBSERVED chain, not on the test suite (6abe385)
- **TRDD-EUWIHP0G:** Record the passed AI review — card waits only on a real >=716k cold resume (0d911e9)
- **TRDD-H12K9JYX:** Migrate CLAUDE.md narrative into the project wikimem (1f42f77)
- **TRDD-H12K9JYX:** Close — both phases shipped, Phase B re-verified first-hand (4febfcf)
- **repomap:** Refresh the project map after today's symbol changes (ff6febb)
- **TRDD-MQBV844P:** Close as shipped-but-open — 3103dee8 answered it 19 days ago (85951c6)
- **TRDD-87RKBYJ8:** Fold the verified duty-coverage re-audit — 6/10/4, row 19 now COVERED (a308ca1)
- **cadence:** State recovery latency as period+jitter range; stamp fire times (TRDD-LI7ENU2A) (e0299af)
- **TRDD-LI7ENU2A:** Record the implementing commit e0299af3 in the card ledger (c01e510)
- **TRDD-WN7M829Y:** Re-measure (41 oversized only; mechanical classes clean) + dispatch first bounded pass (afea774)
- **TRDD-TL6NL7MK:** Record the implementing commit 33a89b17 in the card ledger (27a19b8)
- **memory:** Decompose oversized atoms (TRDD-WN7M829Y) (834f9e2)
- **board:** WN7M829Y pass-1 verified + MN7ZU3RY commit ledger (a690f36c) (e25da62)
- Split TRDD-87RKBYJ8 into 4 child cards; parent blocked on them (57c4e4c)
- **TRDD-WN7M829Y:** Pass 2a verified — LOCAL+PROJECT fully clean, verifier fix proven end-to-end (6388103)
- **TRDD-57WJL5L2:** Design refinement — key the exclude on the atom status prop, not body position (7d85525)
- **TRDD-3SOO1RWE:** Record the implementing commit b26440a9 in the card ledger (e9f50f1)
- **TRDD-WN7M829Y:** USER batch 1 verified 33->22; batches 2-3 held by the burn throttle (8bfa5b3)
- **TRDD-3VW434Q8:** Triage the idle-19d reminder — item 2 verified done, card honestly gated (b774c89)
- Queue TRDD-X6N7I8CA (#179 check-login identity) + TRDD-CGOV2XO4 (#167 context-integrity file) (5d2e851)
- **rules:** Github-mentions must not claim enforcement its installed version may lack ([#171](https://github.com/Emasoft/ai-maestro-janitor/issues/171)) (c48c82d)
- **X6N7I8CA:** Close the card — identity-honesty fix landed as 35eaf8c (janitor#179) (7a00c6a)
- **J3ZH3RSI:** Close the card — retro-lesson chore landed as 009af29 (30d4240)
- **AZ6QRK0D:** Blocked — the #52 coordination forbids building the publish verbs here (677492a)
- **57WJL5L2:** Todo → dev — memgrep filter half in flight (background worker, status-keyed design) (f1d2a4f)
- **57WJL5L2:** Close — correctness layer landed as cceb229; readability layer split to TRDD-QKWU26ZG (6cbb9af)
- **repomap:** Refresh the fenced project map — retro-lesson chore + superseded filter + rollback fix landed since digest 0f2669f88bd2 (7989dc1)
- **memory:** Capture the superseded default-exclude + the 7th retro-lesson chore in the PROJECT wiki (cceb229, 009af29) (78ab9ea)
- **QKWU26ZG:** Close — readability pass landed as 5b5816e (repair chore is the home) (fe04d44)
- Add TRDD-7YHT3FNK — wikimem write-concurrency gate (USER directive: locks + CAS on every edit path) (3c488e3)
- **7YHT3FNK:** STATE — P1+P3 landed, P2 in flight, P4 waits on P2's shipped surface (e8f4e44)
- **memory:** P4 of the write-concurrency gate — the gated primitives are the ONLY sanctioned edit path (TRDD-7YHT3FNK) (954ba2a)
- **7YHT3FNK:** Close — all four phases of the write-concurrency gate landed (ea05bc5, 70fd8a1, c7cd177, 954ba2a) (75abdee)
- **memory:** Capture the wikimem write-concurrency gate in the PROJECT wiki (TRDD-7YHT3FNK) (1e473b2)
- **spec:** Spec the write-concurrency gate and the edit verb (TRDD-7YHT3FNK follow-up) (8fa0cc2)
- **memory:** Capture the cold-compact age rule + the guard>trigger invariant (TRDD-HCGI143H) (30f5543)
- **memory:** Capture memgrep's recurring parser-defect CLASS (janitor#138/#152/#184) (1a87ed8)
- **memory:** The keystroke-injection mechanism is SOLVED — record it before re-deriving it again (0f07d5f)
- **memory:** Backfill the merge-verifier survivor-slug defect (janitor#183) (872941a)
- **memory:** Backfill clear_trigger atomicity + the already-poisoned-context vector (58bf718)
- **memory:** The heartbeat cost law, MEASURED — context x tool calls, not context (5621c4b)
- CLAUDE.md canonical form becomes governed — PRRD golden rules, spec, atoms, TRDD (2af92c3)
- **spec:** WM-ATOM-09/10 — a spec-stage atom cites its TRDDs, and is SUPERSEDED on landing (d76f1d9)
- **spec:** WM-LES-09/10 — supersession is a CHANGELOG, and a lesson is only for what went wrong (785eb1e)
- **TRDD-3PWQK8NM:** Correct the design — supersession is a MOVE below `## Superseded` (6ced8bf)
- **skills:** Supersession is a MOVE, not a lesson — with the owner's blue/green example (ffffec2)
- **memory:** Wire the missing reverse links — THE LINK LAW, 8 violations mine (3316e26)
- **spec:** WM-AUTH-02 lints BEFORE and after, and WM-AUTH-02a checks link DIRECTION (d077bbf)
- **memory:** Capture the cross-scope wikilink resolution defect (janitor#192) (e50fb86)
- **memory:** A checker must state its coverage — silence is not a verdict (bebb0f6)
- **prrd:** G1.1 -> G1.2 byline de-mentioned + new G11.1 GitHub write scope (USER-authorized) (93b6671)
- **OR527LNW:** Close the proposal — USER approved, G1.2 + G11.1 landed (e883198)
- **OR527LNW:** Record the resolution in the card's STATE block (cbb5274)
- **prrd:** G11.1 -> G11.2 — a collaborator's post must name the collaborator (USER-authorized) (7768b10)
- **claude-md:** Refresh the project map for the blackout detector (1cd05a2)
- **board:** KQ9WM4TZ is blocked on the publish, not awaiting an observation (ec11f60)
- **AWXK0RFT:** The publish blocker moved from a finding to a HANG (e365bd0)
- **AWXK0RFT:** Bump updated: for the 2026-08-05 STATE rewrite (85f3465)
- **memory:** Record the claim gate and the daemon_responses contract (b85fb68)
- **memory:** The janitor CAN compact itself — record the lever and the false claim it corrects (54342a3)
- **5ZVS1DDP:** The exit had two gates that disagreed — record it, and scope the relief honestly (6a49a79)
- **5ZVS1DDP:** Retract the "restored" claim — the repo daemon lived 8 minutes (a554a6d)
- Add TRDD-VXFNDHXT — the TTL probe times out, and its fallback disables the guard (7050884)
- **VXFNDHXT:** Part 1 shipped, and correct this card's own cost argument (45ca46b)
- **VXFNDHXT:** Tick the acceptance boxes part 1 satisfied, retire the stale NEXT ACTION (23334b3)
- **repomap:** Refresh the fenced project map — it had drifted past today's chore-ownership work (1297ada)
- Add TRDD-9MQ25PNH — consolidate re-dispatches already-refused candidates (~279k each) (3df9db9)
- **memory:** Record the lesson-uncited adjudication verdict so it is not re-derived (654b77e)
- **memory:** Lesson-uncited on a ZERO-ATOM page is impossible advice — atomize owns it (fd36ce2)
- **9MQ25PNH:** Option 1 is UNSOUND — the fix is a refusal-aware fingerprint (option 3) (f299998)
- **9MQ25PNH:** Correct my own design — a narrowed fingerprint buys one spurious dispatch (ac41551)
- **9MQ25PNH:** Card to testing — shipped, falsified, and the win narrowed to what it is (1f0919a)
- **skill:** Trim janitor-memory-consolidate under the REAL token limit (CPV v5.1.3) (22246f9)
- Rephrase 5 prose sites CPV skillaudit reads as live threats (b013fb6)

### Features

- **security:** Scan the files the agent loads AS INSTRUCTIONS (janitor#167) (a572460)
- **security:** Build the contextPoisonedReason string (janitor#167 interface) (f4b4ec0)
- **rules:** Forbid bare @name in GitHub prose, and enforce it at the wire (6a1cd69)
- **control-plane:** Move the per-chore last-run stamps to control_dir (TRDD-QK7M2B0X) (2b2be24)
- **cadence:** Nudge a long-idle fat session to handoff-and-clear (TRDD-UQW5IOAE) (67802e0)
- **inject:** Read back and verify the prompt field before pressing Enter (0f7181c)
- **inject:** Presence DEFERS, never cancels — the owner's three injector rules (a335622)
- **inject:** Split typing from Enter + a fresh-session gate (TRDD-0BVF4K7E ph1) (9652096)
- **memory:** Atom-lesson travel check — the hand-move safety net (TRDD-VJCMZ2OP 1e) (1530145)
- **inject:** Chain the clear sequence on a VERIFIED submit, not a clock (TRDD-0BVF4K7E ph2) (e17ff17)
- **control-dir:** Dual-era daemon singleton + double-daemon detector (TRDD-QK7M2B0X) (4446fcd)
- **repomap:** Slim janitor-managed CLAUDE.md — wikimem index + contract (TRDD-H12K9JYX) (2544d16)
- **fleet:** Peer freeze-recovery for the daemon's dark window (TRDD-KQ9WM4TZ) (9b0206b)
- **rotator:** Burn-rate-aware proactive rotation (TRDD-FQXBURNR) (2f32dbc)
- **hooks:** SessionEnd teardown — mirror sync + clean-exit breadcrumb (TRDD-TL6NL7MK) (33a89b1)
- **hooks:** Event-driven fast path for the scope-drift detectors (TRDD-MN7ZU3RY) (a690f36)
- **memory:** Repair backfills + validates atom-level desc (TRDD-3SOO1RWE) (b26440a)
- **memory:** RETRO-LESSON — the 7th wikimem chore backfills lesson form onto already-superseded atoms (TRDD-J3ZH3RSI) (009af29)
- **memgrep:** Default-exclude status:superseded atoms from search (TRDD-57WJL5L2) (cceb229)
- **memory:** Repair pass moves superseded atoms below the ## Superseded delimiter (TRDD-QKWU26ZG) (5b5816e)
- **memgrep:** Write-concurrency gate — scope locks + base-hash CAS on every write verb (TRDD-7YHT3FNK P1) (ea05bc5)
- **memgrep:** `edit` — the sanctioned replace-X-with-Y primitive (TRDD-7YHT3FNK P2) (c7cd177)
- **idle-clear:** Fire handoff-and-clear after 1h of nothing but heartbeats (0b81c32)
- **daemon:** A chore is the server's only when it is CLAIMED, not merely alive (d45a843)
- **fleet_status:** Consume the server's hibernation answer instead of refusing to guess (16195eb)
- **fleet_status:** --no-open and --out, so a headless caller needs no shim (janitor#197) (d21366b)
- **fleet-github-config:** Read the server's findings file too (janitor#197 ask 2) (f652648)

### Miscellaneous Tasks

- **repomap:** Refresh the fenced CLAUDE.md project map (46667c4)
- **claude-md:** Refresh both fences — map (454 files) + wikimem index (47 pages) (e28c12d)
- **cpv:** Bump the pinned validator v4.2.0 -> v5.1.0 (1358f08)
- **board:** Promote TRDD-HK7IZ21Z backburner -> todo after full board triage (janitor#181 #120 #102) (c7e3dfd)
- **cpv:** Bump the validator pin v5.1.0 -> v5.1.2 to test the gate-hang fix (a94d2b3)
- **cpv:** Pin v5.1.3 — it fixes every issue I filed against the validator today (d5ee1b1)
- **cpv:** Pin v5.1.4 — a second release overtook the pin mid-publish (ff3118f)
- **manifest:** Declare cpv.canon none — RC-SHIP-BINARY-ONLY-STRICT does not fit this plugin (1e787ac)
- Bump version to 2.4.0 (b209238)
- Lock pyyaml in the dev extra (follow-up to #207 — the resolution moved with pyproject and the publish gate refuses a dirty tree) ([#208](https://github.com/Emasoft/ai-maestro-janitor/issues/208)) (b33c55a)
- Bump version to 2.4.0 (2482bfe)
- Bump version to 2.3.1 (cf0de33)

### Revert

- **compact:** Remove the cache-expired auto-compact entirely — its premise is false (fb649f4)

### Styling

- **tests:** Fix E702 I committed in f6526484 — the lint ran BESIDE the commit, not before it (dba6c81)

### Testing

- **keepalive:** The boot gate must survive the repo-clobber refusal (TRDD-RYZCVVKA) (a42b993)
- **detectors:** Pin the janitor#99 walk rule so the next scanner inherits it (1950a8b)
- **rules:** Pin that every FULL REFERENCE pointer resolves (TRDD-none) (c468a92)
- **memory:** Record the falsification result — 1 of the 5 new tests proves the filter (03b09b7)
- **issue-catalog:** Reconcile the refused-suppression assertion with the merged contract (feb3002)
## [2.3.0] — 2026-08-02

### Documentation

- **memory:** Record why the CPV pin is literal, and how an absorbed chore stalls a rollout (0963018)
- **TRDD-56d24c02:** Move dev -> blocked; the daemon stand-down is by design (2d62129)
- **memory:** Record how to tell a stood-down daemon from a dead one (8ba0740)
- **github:** The always-on chores, and TRDD-MKCPL3ZH recording why (TRDD-MKCPL3ZH) (3e83dac)

### Features

- **github:** Both GitHub notification chores run always, on the cron (559930a)

### Miscellaneous Tasks

- **github:** Delete the four vestigial on/off skills (TRDD-MKCPL3ZH) (8cd8fb2)
- Bump version to 2.3.0 (3570bab)

### Testing

- **github:** Cover the guards that make always-on safe, and prove they fail (a2d43cf)
## [2.2.0] — 2026-08-01

### Bug Fixes

- **memory:** Let the mirror shed redundant orphans without shedding knowledge (b1b9439)
- **workflow-security:** Cite the job that is actually at fault (janitor#157) (291fa91)
- **report-to-trdd:** Follow the curator when it moves (janitor#121) (8b46660)
- **memgrep:** Tell the author WHY a visible citation does not count (janitor#152) (40c480e)
- **memgrep:** Never anchor a lesson inside an indented code block (4126058)
- **window-burn-rate:** Stop alarming about an idle account's window, name whose it is, and read model-scoped limits (8e4b10d)
- **usage-probe:** Retire stranded cache entries, and name the sample every reading came from (d0317d3)
- **memory-librarian:** A shared DOMAIN is not a conflict — land the other half of #35 (92ae356)
- **cpv:** Pin CPV literally in the workflows — a static validator cannot read a variable (e48f8b1)

### Documentation

- **memory:** Cite the page-level lessons from the atoms they belong to (e07c238)
- Refresh the fenced project map (3b41fb8)
- **memory:** Record the burn-alarm contract in PROJECT scope (142549a)

### Features

- **token-report:** Show model-scoped windows, live/alternate, and idle in --live (276a79b)

### Miscellaneous Tasks

- Bump version to 2.2.0 (3b03230)

### Security

- **cpv:** One pin, in .cpv-version — not eight copies of a tag (348014b)

### Testing

- **daemon:** Kill the process GROUP, so the suite stops orphaning daemons (c7e7b56)
## [2.1.0] — 2026-08-01

### Bug Fixes

- **memgrep:** Stop truncating the page description — it is the recall-ranking field (dfddea1)
- **memory:** Keep transaction scratch out of git, and land the link-law backlinks (bfd2753)
- **test:** Stop asserting an exact second across two independent clock reads (f303c86)

### Documentation

- **memory:** Honor the LINK LAW — backticked wikilinks do not link (efa0ab1)

### Features

- **plugins:** Harness-adaptive install/uninstall/upgrade skills (7c69b0d)
- **continuity:** Make an interrupted subagent respawnable, not just resumable (804cbb6)

### Miscellaneous Tasks

- **cpv:** Bump the release-gate pin v3.19.0 -> v4.2.0 (54cb55e)
- Bump version to 2.1.0 (04a4efd)

### Testing

- **daemon:** Stop measuring machine load instead of the daemon (b310449)
## [2.0.0] — 2026-07-31

### Bug Fixes

- **resume:** A PRE-marker is not subsumable — stop eating the post-/clear cue (TRDD-Z582IKIR) (c917eb8)
- **resume:** Bound an abandoned pre-/clear flag, and fix the test that hid a cache pin (b2acaf7)

### Documentation

- **memory:** Record WHY the janitor has no off-switch but disarm (7e8345e)
- **memory:** An older session could revert a NEWER installed rule, not just read stale code (4edd5e2)
- **handoff-and-clear:** The pre-clear marker is armed by clear-observed.ts (3d514ee)

### Features

- Remove MAINTENANCE MODE and the self-budget actuation (d9a7189)
- **gh:** Port the GitHub reply monitor in as janitor-* skills (4285a84)

### Miscellaneous Tasks

- Bump version to 2.0.0 (749c654)

### Testing

- **session-start:** Run the hook as a subprocess, the way Claude Code runs it (9c65bb0)
## [1.0.0] — 2026-07-31

### Bug Fixes

- **librarian:** A link to another SCOPE is not a missing file ([#115](https://github.com/Emasoft/ai-maestro-janitor/issues/115)) (5ae79ff)
- **memory:** Name the assignment sidecar ABSOLUTELY, and stop guessing ([#150](https://github.com/Emasoft/ai-maestro-janitor/issues/150)) (1fe17f2)
- **dirty-tree:** Stop nagging about the janitor's own proposal files (8e2d984)
- **rules:** The installed contract may only move FORWARD ([#141](https://github.com/Emasoft/ai-maestro-janitor/issues/141)) (442864c)
- **tickets:** Retiring an issue code must take its proposals with it (ccf1fb2)
- **skills:** Bring the two oversized memory skills back under the cap (94a4e88)

### Documentation

- **ticket-skill:** Teach the agent the close it was missing ([#128](https://github.com/Emasoft/ai-maestro-janitor/issues/128)) (6dfef96)
- **conflict-skill:** Write down every skip, or pay to re-derive it ([#131](https://github.com/Emasoft/ai-maestro-janitor/issues/131)) (d8592e4)

### Features

- **tickets:** Let an agent prove a finding false, once, and be believed ([#128](https://github.com/Emasoft/ai-maestro-janitor/issues/128)) (0728eb1)
- **memory:** A refusal ledger keyed on the CANDIDATE, not the corpus ([#131](https://github.com/Emasoft/ai-maestro-janitor/issues/131)) (a777cda)
- **memory:** An unfixable page must stop out-ranking the fixable ones ([#124](https://github.com/Emasoft/ai-maestro-janitor/issues/124)) (6854fd5)
- **plugins:** Fleet plugin-update core — the missing cwd (Phase 1 of 5) (29dd781)
- The never-stop nudge has no off-switch any more (d3ec698)
- Remove PAUSE, local and global (95533b9)

### Miscellaneous Tasks

- Bump version to 1.0.0 (11bbc14)

### Testing

- **memory:** Pin BOTH halves of the content-hash claim ([#131](https://github.com/Emasoft/ai-maestro-janitor/issues/131)) (f1f5db7)
- **env:** Budget the live probe for a loaded machine, not an idle one (e4423a6)
## [0.66.1] — 2026-07-30

### Bug Fixes

- **update,scope:** Read the install REGISTRY, not settings.json ([#147](https://github.com/Emasoft/ai-maestro-janitor/issues/147)) (bdf58f8)
- **pkg-policy:** Propose pnpm settings where pnpm actually reads them ([#148](https://github.com/Emasoft/ai-maestro-janitor/issues/148)) (804a856)
- **provenance:** BuildKit's native provenance IS an in-toto attestation (#99.3) (bc6542b)
- **ai-context:** Report the STATE, not the shape (#110, #99.4) (d89eca8)
- **update:** Annotate the scope list — a Literal inference CI rejects (92534ba)

### Documentation

- Refresh the CLAUDE.md project map (registry scope helpers) (40c6f2a)
- **memory:** Gate 4's timeout has TWO causes — record the discriminator (85f0086)

### Miscellaneous Tasks

- Bump version to 0.66.1 (63eb7c7)
## [0.66.0] — 2026-07-30

### Bug Fixes

- **trdd,cache:** A v2 column outranks body prose; pins are a SET (#135, #137) (0e0e07b)
- **trdd:** Status: is a DISTINCT field — gate on the VALUE, never the field name ([#135](https://github.com/Emasoft/ai-maestro-janitor/issues/135)) (83be111)
- **trdd-drift:** Name the field the line actually read, not always "status=" (5572d9c)
- **presence:** Find the cron marker on any early LINE, not at offset 0 ([#113](https://github.com/Emasoft/ai-maestro-janitor/issues/113)) (6a734cb)
- **librarian:** A cluster must share a topic, not merely be connected (#140, #121) (6603a5d)
- **agentlens:** Locate a burn cause from its OWN evidence, never a parallel list ([#121](https://github.com/Emasoft/ai-maestro-janitor/issues/121)) (b2f1c46)
- **publish:** One CPV timeout, stated once, with real headroom (a168149)

### Documentation

- Record the argv-mirroring relaunch on TRDD-56d24c02 (supersedes the hardcoded line) (e9ec6f2)
- **memory:** The server-owns-host handover leaves six chores unowned (44481f3)
- Refresh the CLAUDE.md project map (437 files) (dcd43c5)

### Features

- **resume:** Notice a session whose wake-up chain silently failed ([#125](https://github.com/Emasoft/ai-maestro-janitor/issues/125)) (40bcc1c)

### Miscellaneous Tasks

- Bump version to 0.66.0 (fc8fd8b)
## [0.65.0] — 2026-07-29

### Bug Fixes

- **report-to-trdd:** The abstain exclusion had never once fired (c92fa61)
- **fleet:** Mirror the original claude argv on relaunch instead of hardcoding flags (d09243d)

### Documentation

- Move TRDD-EUWIHP0G and TRDD-HI0BGQGJ testing -> ai_review (75705b6)
- **memory:** Record the same-tab restart rules + correct a stale machine fact (8713965)
- Record today's rung changes on TRDD-56d24c02 + backfill implementation-commits (959d9df)
- Refresh the CLAUDE.md project map (435 files) (8c978c1)

### Features

- **fleet:** Relaunch unattended-capable — skip permissions, allow temp dirs (62cfa76)
- **fleet:** Restart in the ORIGINAL tab; resurrect opens a tab, not a window (9fd2c61)

### Miscellaneous Tasks

- Bump version to 0.65.0 (534e894)

### Testing

- **compact:** Retire the stale 270k acceptance criterion (TRDD-EUWIHP0G, TRDD-HI0BGQGJ) (00768bd)
## [0.64.1] — 2026-07-29

### Bug Fixes

- **package-manager-policy:** Stop proposing npm-only knobs on a yarn repo ([#130](https://github.com/Emasoft/ai-maestro-janitor/issues/130)) (49baa78)
- **package-manager-policy:** Close the false negative my own #130 fix opened (08ec253)

### Documentation

- **trdd:** DLI76AUC item #1 is half done — the re-arm cooldown already shipped (f834da8)

### Miscellaneous Tasks

- Bump version to 0.64.1 (d9c2f5e)
## [0.64.0] — 2026-07-28

### Documentation

- **memory:** The publish freezes the tree — my own edits failed two runs (29f373d)

### Features

- **trdd-drift:** Honour a stated park with an EXPIRING review-after date (d511dc5)

### Miscellaneous Tasks

- Bump version to 0.64.0 (df748af)
## [0.63.5] — 2026-07-28

### Bug Fixes

- **session-start:** Make an import death audible on a broken deployment ([#80](https://github.com/Emasoft/ai-maestro-janitor/issues/80)) (709bd74)
- **oauth-rotator:** Report latched keychain as UNKNOWN, degrade gracefully ([#82](https://github.com/Emasoft/ai-maestro-janitor/issues/82)) (03ac965)
- **pr95:** Bring the #82 branch up to 14 days of main (1e2454e)
- **memory:** Seed the overview entry pages so the wikimem bridge can resolve ([#112](https://github.com/Emasoft/ai-maestro-janitor/issues/112)) (062802f)

### Documentation

- **memory:** Route the SLOW-vs-STUCK method to the page that owns it (f8caffe)

### Miscellaneous Tasks

- Bump version to 0.63.5 (9cb47b2)
## [0.63.4] — 2026-07-28

### Bug Fixes

- **publish:** Stop `git add -A` sweeping the release commit (ed5fabb)
- **publish:** Regenerate the self-integrity manifest on every release (f0416a5)

### Documentation

- **trdd:** Close TRDD-CGYMUKO6 — the ticket system shipped 14 days ago (14f6b00)

### Miscellaneous Tasks

- Bump version to 0.63.4 (711cc8f)
## [0.63.3] — 2026-07-28

### Bug Fixes

- **memory:** Stop dispatching a 260k-token agent to re-derive the same refusal (bacf677)

### Documentation

- **memory:** Record why unattended sessions were stranded after a compaction (bbf2b7f)
- **memory:** Gate 4 timing out is CPV's worker-pool race, not a tight cap (2024cea)

### Miscellaneous Tasks

- Bump version to 0.63.3 (2046a63)
## [0.63.2] — 2026-07-28

### Bug Fixes

- **memgrep:** A database BEHIND the ladder is not a database that is broken (06a5b46)
- **tickets:** A template slot a producer got wrong must be LOUD, not silent (a919196)
- **resume:** One busy pane was stranding every other session on the machine (eb52843)

### Miscellaneous Tasks

- Bump version to 0.63.2 (6c755d0)
## [0.63.1] — 2026-07-28

### Bug Fixes

- Close the two gaps the v0.63.0 publish reported about itself (4c90bb9)
- **memgrep:** A stale binary blamed the database it could not read (T-DMGDWWE0) (6d2f501)
- **tickets:** Our own title colon made the proposal frontmatter unparseable (a906069)
- **rules:** -iname, and the three clauses that make §12 implementable (6226bbd)
- **readme:** The platform badge linked to nothing (652176e)

### Documentation

- **architecture:** The status line said rev 4 while the title said rev 7 (c4283b3)

### Miscellaneous Tasks

- Bump version to 0.63.1 (2d50e1b)

### Testing

- The recall locator is the page NAME, and nine assertions still said .md (ecca06d)
## [0.63.0] — 2026-07-28

### Bug Fixes

- **memgrep:** Documenting the atom grammar was declaring atoms (plan 1c) (4db511b)

### Documentation

- **map:** Refresh the fenced project map after the lint FP/FN benchmark (691408e)
- **memory:** Record why the "lint false positive" was a parser bug (4db511b) (786bc14)

### Features

- **memgrep:** Measure the linter — false positives and false negatives, gated (37028f8)

### Miscellaneous Tasks

- Bump version to 0.63.0 (bd15e31)
## [0.62.0] — 2026-07-27

### Bug Fixes

- **wikimem-bench:** Move the fixture README out of the corpus dir; re-baseline (400bdba)
- **ci:** Time CPV validation, not the uvx build that precedes it (81ed5a0)
- **memory:** Remove the two downward PROJECT->LOCAL links (privacy) (f4ddef7)
- **memory:** Recover 19 dropped keyword phrases in PROJECT scope (873f11e)
- **rules:** Restore the context-floor cap, and track the two-hop contract in the fixture test (3409ae2)
- **tests:** Pin the benchmark gate to the binary under test (dca3050)
- **memgrep:** Reindex the SCOPE that owns a page, not the directory it sits in (cb64121)
- **docs:** The merge txn refuses a backlink-holder write — say so, and pin it (4ca2992)
- **memgrep:** One file, one memory row — a respelled path duplicated the corpus (f04fcd7)
- **memgrep:** A backticked shell-command name in a comment trips the CMD_INJECTION scanner (a42f132)

### Documentation

- Add TRDD-DO6X4ZF8 — wikimem retrieval benchmark (accuracy + token cost) (9ef241d)
- **map:** Refresh the CLAUDE.md project map after the wikimem bench + migration (108df1c)
- **memgrep:** Retire the always-rich-output claims from the shipped skills (83fac1d)
- Refresh TRDD-DO6X4ZF8 STATE — dev -> testing, and retire three superseded claims (c8d29cc)
- Promote TRDD-DO6X4ZF8 to ai_review — the whole gate is green (6515ee8)
- Add TRDD-YBOZW3ES — a page result's locator is an absolute path (f723606)
- TRDD-YBOZW3ES shipped — todo -> ai_review (6bea87f)
- **map:** Refresh the fenced project map after the wikimem bench + locator work (b329379)
- **memory:** Capture the retrieval engine's contract as a PROJECT wiki page (5d021d9)
- **memory:** Record the two index-migration failure modes found this session (d7d4121)

### Features

- **wikimem:** Retrieval benchmark — accuracy + end-to-end tokens (TRDD-DO6X4ZF8) (7e0707c)
- **wikimem:** Recover atom keyword phrases the parser silently drops (Phase 1.3) (55c3020)
- **wikimem:** Detect atom props the parser silently discards (Phase 1.3) (d108474)
- **memgrep:** Layered recall output + exact atom-id second hop (-44% retrieval tokens) (5b03519)
- **memgrep:** Keyphrase-aware tiered scorer — perfect MRR on a conformant corpus (de1a89f)
- **memgrep:** Break equal recall scores by RECENCY, not alphabetical path order (d6f271f)
- **memgrep:** Lint downward cross-scope links, and stop the LINK LAW punishing legal upward ones (0dff13e)
- **memgrep:** Make the score observable, and retire a tie-break the data says can never fire (abd48b4)
- **memgrep:** Give lint a severity model, so the gate names 8 problems instead of 161 (2d08feb)
- **memgrep:** One linter, one grammar — port the Python-only checks into Rust (e852431)
- **memgrep:** Read atom retirement back — `status` was write-only (a208990)

### Miscellaneous Tasks

- Bump version to 0.62.0 (d34bffa)

### Performance

- **memgrep:** A page row's locator is its name, not its path (TRDD-YBOZW3ES) (5ed8155)

### Testing

- **wikimem:** Guard the spec against drifting from the CLI, in both directions (d4c5b49)

### Spec

- **wikimem:** Add the retrieval-engine contract — WM-SCORE, WM-IDX, WM-BENCH, WM-ATOM-07 (5f98788)
- **wikimem:** Specify the index machinery an audit found entirely unspecced (cf3f67a)
- **wikimem:** Cover the base grep mode and `fact` — and resolve a contradiction I had just introduced (ff4625a)
## [0.61.1] — 2026-07-26

### Bug Fixes

- **rotator:** Claude-code UA + throttle on /api/oauth/usage (TRDD-WEBA1RMF) (b9d9c75)
- **repomap:** Track the exclude list + refuse an oversized map block (36307e1)
- **rules:** Fit the two recall corollaries inside the context-floor cap (d3d8db3)
- **skills:** Fit the wikimem practices inside the 5000-token SKILL.md cap (81946f1)
- **trdd:** Surface a TRDD whose frontmatter is unreadable (TRDD-WEBA1RMF) (11d476b)

### Documentation

- **usage-probe:** Document the throttle, the two-host UA rule, the knobs (TRDD-WEBA1RMF) (15d06ca)
- **wikimem:** Three practices the corpus proved it needed today (7c079f1)

### Miscellaneous Tasks

- Bump version to 0.61.1 (7512d68)
## [0.61.0] — 2026-07-26

### Bug Fixes

- **rules:** Keep markdown-memory-recall under the shipped-rule floor cap (d53b15c)
- **memgrep:** Use repeat_n for inline-code masking (clippy manual_repeat_n, Rust 1.97) (7522c71)
- **spec:** Pymarkdown-clean wikimem-memgrep-spec (MD007/MD031) + repair a mis-flagged prose '+' (914d4d1)
- **publish:** Exclude design/specs/ from the Step-3 pymarkdown scope (9420a42)
- **trdd:** Unwrap 8 prose lines whose leading '+' was read as a list bullet (c2af384)
- **agent:** Reword the repair-agent's attack-example list so it stops tripping prompt_injection scanners (791fbc2)
- **trdd:** Rejoin a code span wrapped across 3 lines that parsed as a bogus H1 (d68c7c6)
- **mypy:** Point mypy at scripts/ so 'from lib import X' resolves (kills 19 false errors) (125a94e)
- **types:** Clear mypy type debt + actionlint SC2129 + shfmt (v3.11 ci-preflight) (cf2fc1c)
- **bandit:** Declare the 11 detector SHA1 digests non-security (B324 -> usedforsecurity=False) (337d103)
- **bandit:** Justified per-site # nosec for 25 verified false-positives -> bandit -ll = 0 (759d3e8)
- **jscpd:** Scope out the deliberate uniform catalog + design docs -> under 5% threshold (acdf2c1)
- **ci,release:** Drop the stale scanner-finding narrative from the pin comments (407b0f1)
- **memory:** Accept a str scope_root; stop the bootstrap doc from faking a file reference (6f5dea2)
- **mypy:** Silence two optional-import type errors that blocked the publish gate (11df106)
- **daemon:** Make the bulk-lane recheck beat env-tunable like every sibling cadence (3d778ff)
- **daemon:** Give the bulk lane a fair, starvation-free winner (1c8e773)
- **publish:** Let the test gate run to completion instead of timing out at 300s (948ca7f)
- **repomap:** Stop a torn read from destroying the human CLAUDE.md narrative (7639afb)

### Documentation

- **memory:** Capture the arm-nudge escalation loop as a PROJECT wiki page (fe49fa0)
- **memory:** Record the control-dir test-isolation and publish write-guard traps (TRDD-QK7M2B0X) (40e4188)
- **TRDD-QK7M2B0X:** Record 78879d4 as the phase-B step-1 implementation commit (b3cadff)
- **map:** Refresh the fenced CLAUDE.md project map (68a8c39)
- **rules:** Name the TRDD overlay by its pinned filename (ai-maestro#83) (6417b47)
- **memory:** Capture the fleet control plane and the 3-pillars rules ownership (e02debf)
- Add TRDD-E8LNOXLQ — merge-protocol.md contradicts memory_txn_cli.py (df989f0)
- Add TRDD-4ZTNMQL3/DOJ2LE1G/WN7M829Y/VJCMZ2OP — wikimem atom-authoring correctness design set (5cefced)
- **TRDD:** Record impl commits f469f07/d9ef41f + binary-live state (DOJ2LE1G, VJCMZ2OP) (0058cdb)
- **rules:** Add the AUTHORING-integrity contract to markdown-memory-recall (TRDD-4ZTNMQL3) (ebd7445)
- **TRDD-4ZTNMQL3:** Rule + gate shipped (ebd7445, 33a1f7f) → column testing (78ce538)
- **TRDD-WN7M829Y:** Unblock retroactive repair; scope it as deliberate editorial work (94da87a)
- Add 4 proposal TRDDs — janitor heartbeat-cost improvements D1/D2/D4/D5 (068b5e9)
- Revise D1/D2/D4/D5 proposals against their must-fix lists (Stage A) (2503128)
- Promote TRDD-B0SABNP8 proposal -> complete (D4 implemented in 959a1e2) (373b622)
- **TRDD-B0SABNP8:** Apply the promotion content git mv left unstaged (80fcc39)
- **spec:** Add the wikimem + memgrep conformance SPEC (design/specs/) (714d021)
- **spec:** Make the wikimem+memgrep SPEC complete + add the anti-deletion guardrail (v1.1.0) (bf61cd3)
- Promote TRDD-X07E7HTN proposal -> complete (D1 v1 shipped in 3c18208) (d350058)
- Promote TRDD-ZCODD6YS proposal -> complete (D2 shipped in efb2781) (396337f)
- Promote TRDD-82JRK0CY proposal -> complete (D5 shipped in 0ae6256) (21c61d9)
- Add TRDD-GZXTSJSR — proactive all-accounts OAuth login nudge (real notification, capture before crisis) (42a04f6)
- Add proposal TRDD-739N4CUF — close the janitor↔server OAuth-rotation ownership gap (verified live root cause) (7a7cdcd)
- Add proposal TRDD-D1UKVNUY — cache-thrash detector + marathon-session root cause (token-burn incident) (63ab43c)
- **daemon:** Clarify server-alive binary-exit supersedes the per-chore yield (c555deb)
- **ci:** Record the exhaustive CPV pin bisect (v2.153.2 … v3.5.0) (e976f05)
- Add TRDD-6WM4BFKF — gitignore-coverage chore (tracked == shipped) (21435d0)
- Add TRDD-WKTD5JTC — daemon injects ESC to break the CC 429-retry-watchdog wedge (2af7243)
- **TRDD-WKTD5JTC:** Split retry-wedge ESC recovery across both backends + server contract (ARCHITECTURE §8 rev 6) (3e18bf7)
- **TRDD-WKTD5JTC:** Alt-screen correction — detect the RENDERED frame, not raw PTY (ARCHITECTURE §8 rev 7) (1ded32f)
- **TRDD-WKTD5JTC:** Pin the server detection surface to the dashboard's xterm.js (§8.1) (43b751f)
- **TRDD-WKTD5JTC:** §8.1 — read buffer directly (not addon-search), API source-verified (7213ebe)
- **TRDD-WKTD5JTC:** Wedge is cause-agnostic (session-limit too) + ESC-before-rotation + onWriteParsed (d97ed69)
- **TRDD-WKTD5JTC:** Statusline % is a lagging indicator — never a detection gate (3bcf176)
- **TRDD-WKTD5JTC:** Fold advisor (Fable 5) review — approve-with-changes (7a79494)
- **TRDD-WKTD5JTC:** Record server notification via ai-maestro#90 (63cc0a3)
- **memory:** MEMORY.md is the harness's — the janitor maintains ONE bridge line (d11e516)
- **memgrep:** State the coexistence memory model in --help; add overview exit-code regression test (c89daa3)

### Features

- **control-plane:** Publish the three coordination locks to the fixed control dir (TRDD-QK7M2B0X) (78879d4)
- **memgrep:** Add-lesson --supersedes + four authoring-integrity lint checks (TRDD-DOJ2LE1G) (f469f07)
- **memgrep:** Add the migrate verb — move an atom + baggage between pages (TRDD-VJCMZ2OP) (d9ef41f)
- **memory-txn:** Delta authoring-integrity gate on commit (TRDD-4ZTNMQL3) (33a1f7f)
- **harness-selftest:** SessionStart CC-drift self-test (TRDD-B0SABNP8) (959a1e2)
- **daemon-wake:** The daemon owns the rate-limit resume wake, v1 (TRDD-X07E7HTN) (3c18208)
- **security:** Guard against dependency CLIs that write agent-context files without consent (janitor#110) (c71f8d1)
- **self-budget:** The janitor meters + self-throttles its OWN heartbeat cost (TRDD-ZCODD6YS) (efb2781)
- **heartbeat:** Funnel dispatch markers through one auto-flushed decision helper (TRDD-82JRK0CY) (0ae6256)
- **memory:** Implement the MEMORY.md bridge line — verify + re-add, append-only (b44c4cd)

### Miscellaneous Tasks

- **config:** Register the agent_generator_guard_enabled knob in plugin.json (janitor#110) (61a60a6)
- Bump version to 0.61.0 (f57ecea)

### Revert

- **spec:** Undo the pymarkdown auto-format of the wikimem spec (0b035e7)

### Styling

- **memgrep:** Shfmt stage.sh so the CI-parity preflight passes (d1eb81c)
- **oauth_rotator:** Shfmt the remaining two shell scripts (0c074db)

### Testing

- **daemon:** Pin the chore-ownership signal so a live ai-maestro server can't break the suite (c8a7392)

### Build

- **pipeline:** Land the v3.11.0 canonical-pipeline migration (60e1b6b)
- **pipeline:** Upgrade canonical pipeline to CPV v3.16.0 (all three pin sites) (c7abd34)
- **pipeline:** Bump CPV pin v3.16.0 -> v3.19.0 (all three sites) — clears the last --strict finding (71bbfa5)
## [0.60.1] — 2026-07-21

### Bug Fixes

- **maintenance:** Stop the arm→nudge loop that ratcheted the fleet into GLOBAL maintenance (22c8380)
- **tests:** The write-guard's "only we touch this state" premise is no longer true (1f939ea)
- **tests:** The live-actor probe silently answered False on an import error (4c73e45)
- **tests:** Resolve the live-actor probe from the REAL home, not the sandbox (b20f3a4)
## [0.60.0] — 2026-07-21

### Bug Fixes

- **tests:** A daemon that EXITED mid-run is not a test leak (3f892ec)

### Documentation

- **trdd:** TRDD-5ZVS1DDP shipped in v0.59.0 — column testing (bb39f65)

### Features

- **control-plane:** Publish the six mode flags at a fixed ~/.claude/janitor-control/ (9116b22)
## [0.59.0] — 2026-07-21

### Bug Fixes

- **tests:** Write-guard must not call a daemon respawn a test leak (3edcf0c)

### Features

- **daemon:** ONE DAEMON PER HOST — exit while an ai-maestro server runs (TRDD-5ZVS1DDP) (419a470)
## [0.58.1] — 2026-07-21

### Bug Fixes

- **dispatch:** The maintenance nudge must name WHICH scope is suppressing (743a275)

### Documentation

- **trdd:** Resolve TRDD-5ZVS1DDP's open question — chores split by capability (4bbe335)
## [0.58.0] — 2026-07-21

### Bug Fixes

- **architecture:** Widen the control plane to everything two daemons share (778d729)

### Documentation

- **trdd:** Close TRDD-UO93APWN — flaky e2e worker race verified fixed (e63c748)
- **architecture:** Fix the control plane at ~/.claude/janitor-control/ (473c88d)

### Features

- **arm:** Clear LOCAL maintenance on arm, and REPORT the global flag (3333e0c)
- **maintenance:** Split LOCAL and GLOBAL onto independent commands (4237fcf)
- **architecture:** Require provenance on every global control flag (66ec5f1)
## [0.57.0] — 2026-07-21

### Bug Fixes

- **resume:** Post-compact push must not surprise an attended-but-reading session (TRDD-GRHP2YHP) (b041ffd)
- **reload-guard:** Remove the dead UserPromptSubmit reload-guard hook — /reload-plugins fires no hook (TRDD-Z582IKIR) (75b2860)
- **oauth:** Rename refresh-claude-logins skill -> refresh-cc-logins (CPV N11) (TRDD-EBVZJ6GU) (1da0edb)
- **cpv:** Clear all CPV --strict blockers surfaced by the v0.57.0 release (47b00e6)

### Documentation

- **trdd:** 6Q0OYYYH shipped in v0.56.0 -> published (e295409)
- **trdd:** Capture wikimem-writer initiative — R02HTRUD 6RO0L3M0 VPTQ4067 5FNZ7ZKO + GRHP2YHP (0a7f7ba)
- **trdd:** GRHP2YHP → testing, shipped b041ffd (resume-push attended fix) (b2ae769)
- **trdd:** Z582IKIR provenance — F1 (c3bde7d) + P1 (224da88) shipped, F0/F2/F3 remain design (f5ee852)
- **trdd:** VPTQ4067 → testing, detector shipped 2077d2d (memgrep-lint fold is the A1-dependent follow-up) (d00c587)
- **trdd:** R02HTRUD→testing (a133ff0 verified); unblock 6RO0L3M0+5FNZ7ZKO; ratify 5-key lesson schema (8e49937)
- **trdd:** 6RO0L3M0 → testing, skills converted bc43f1b (supersede/rename verbs = R02HTRUD follow-up) (495f912)
- **trdd:** Board sweep — 5 wikimem-overhaul TRDDs → complete (ff0ad22)
- **memory:** Record the memgrep-verb authoring discipline (ATOM-9AWW-4NCO) (570b695)
- **trdd:** Add TRDD-EBVZJ6GU — convert 7 agent-relevant commands to skills (keep 3 user-mem for privacy) (03d8a32)
- **trdd:** EBVZJ6GU → complete — 7 commands converted to skills (63637d9, 4d0e31c) (1aea052)
- **trdd:** Z582IKIR — F1 reload-guard hook removed (75b2860), premise refuted; auto-defer survives (f4b09cd)
- **skills:** Agent-visible reload/compact guards replace removed hook (TRDD-Z582IKIR) (28c1777)
- **trdd:** Z582IKIR STATE — F1 intent moved to agent-side skill warnings (28c1777) (b0e4cf6)

### Features

- **continuity:** /janitor-handoff-and-clear + cross-clear verify harness (TRDD-Z582IKIR) (224da88)
- **reload-guard:** Block /reload-plugins above a context threshold (TRDD-Z582IKIR/F1) (c3bde7d)
- **memory:** Self-validating wikimem syntax audit + heartbeat detector (TRDD-VPTQ4067) (2077d2d)
- **memgrep:** Mechanical wikimem write verbs — add-atom, new-page, add-lesson (TRDD-R02HTRUD) (a133ff0)
- **skills:** Add 7 skills converting agent-relevant commands (TRDD-EBVZJ6GU) (63637d9)

### Refactor

- **memory-skills:** Route authoring through memgrep verbs, keep judgment as prose (TRDD-6RO0L3M0) (bc43f1b)
- **memory:** Migrate PROJECT lean lessons to canonical 5-key form (TRDD-5FNZ7ZKO) (6f9d818)
- **commands:** Remove 7 commands now shipped as skills (TRDD-EBVZJ6GU) (4d0e31c)

### Styling

- **skills:** Fix MD004 plus-bullet markdown lint (unblocks publish lint gate) (8ace88c)
## [0.56.0] — 2026-07-18

### Bug Fixes

- **presence:** Real typing signal — HID idle probe gates every injection surface (TRDD-6Q0OYYYH) (ee93553)

### Documentation

- **trdd:** WBYFTU2L shipped in v0.55.0 -> published (66ac4ac)
## [0.55.0] — 2026-07-18

### Bug Fixes

- **rotator:** Debounce alternate-probe 429 + per-alternate verdicts + cookie-leg human alert (TRDD-WBYFTU2L) (dcd9d4d)

### Documentation

- Add TRDD-WBYFTU2L — rotation deadlock 2 (alternate-429 debounce, per-alternate verdict logging, cookie-leg alert) (2cd4791)
## [0.54.1] — 2026-07-18

### Documentation

- **trdd:** P7WU40G9 all 3 fixes shipped (v0.53.0 + v0.54.0) -> published (d15fa1a)
- **memory:** Claude-code-continuity-engineering wiki topic — hub + 3 components + rotation-page correction (TRDD-P7WU40G9) (dec46ff)
## [0.54.0] — 2026-07-18

### Bug Fixes

- **fleet:** ESC-only recovery for rate-limited sessions — kill the /janitor-arm flood (TRDD-P7WU40G9) (637e12e)
- **fleet:** Keep the DEFAULT-OFF hard-restart rung for frozen — only the command-typing ladder is removed (TRDD-P7WU40G9) (599dc26)
## [0.53.0] — 2026-07-18

### Bug Fixes

- **resume:** Shrink the self-trigger presence window 5min/3min -> 10s (owner directive) (2cbbfb6)
- **rotator,compact:** Window-asymmetric rotation thresholds + harness-relative compact (TRDD-P7WU40G9) (dd96db2)

### Documentation

- **trdd:** 8DR0X08A + LU0C5KAR shipped in v0.52.0 -> published; rev 4 + RATIFIED posted on #100 (7ca5f7d)

### Testing

- **compact:** Pin the compact threshold in the 3 cold-cache fixtures (TRDD-P7WU40G9) (6145a23)
## [0.52.0] — 2026-07-17

### Bug Fixes

- **daemon:** Stop the fleet-recovery injection loop — substantive liveness + wedged short-circuit (TRDD-8DR0X08A) (db9c2f0)

### Documentation

- **trdd:** FENWWB4E + 4649ZLE0 + N9YAH5E7 shipped in v0.51.0 -> published (f6322f7)
- Add TRDD-8DR0X08A — fleet-recovery injection loop (self-refreshing probe) (ee05bfc)
- **trdd:** 8DR0X08A implemented (db9c2f0) -> testing; F4 cadence-aware staleness added; ships v0.51.1 (a2f9378)

### Refactor

- **chores:** Binary server-liveness switch — server running owns ALL absorbed chores (TRDD-LU0C5KAR) (76fef0b)
## [0.51.0] — 2026-07-17

### Bug Fixes

- **chores:** Per-class capability gating — wire the server-liveness probe (TRDD-N9YAH5E7) (616ab18)
- **tokens:** Window-burn-rate alarms only in the culprit project's own sessions (token-quietness) (db99022)
- **tokens:** Context-advisory default 60 -> 80 — one runway band below enforcement (token-quietness audit) (b8da784)
- **detectors:** Strip VIRTUAL_ENV from detached uv-script workers (TRDD-UO93APWN root cause) (11f8dc1)

### Documentation

- **trdd:** PZLVT2RN + X92VBFNF + H7NVKSAX shipped in v0.50.0 -> published (release 103c84a) (197bdd8)
- Two-harness ARCHITECTURE.md rev 1 + TRDD-FENWWB4E findings ledger (plan Phase 1) (4c3347b)
- ARCHITECTURE.md rev 2 — fold ai-maestro round 1 (per-class §2 matrix, §6 delivered contracts) (7ef80d2)
- ARCHITECTURE.md rev 3 — §6.4 factual fix (session-command verb is deployed, no verb owed) (ca22004)
- ARCHITECTURE.md rev 3 RATIFIED by both sides — FINAL; FENWWB4E -> todo (Phase 4 unblocked) (bb9c9d8)
- **trdd:** FENWWB4E Phase 4 implemented -> testing (5 commits, full suite green); Phase 5 + doc pass ride v0.51.0 (d81200c)
- V0.51.0 doc pass — findings ledger + notify channel + per-class chore gating + token-quietness (repomap regen) (5037162)

### Features

- **findings:** Per-project findings ledger core — record() choke point, cursor reader (TRDD-FENWWB4E) (831beb7)
- **findings:** Wire issue_catalog.raise_issue through the findings ledger (TRDD-FENWWB4E) (1708bf0)
- **findings:** SessionStart inbox surfacing + /janitor-findings browser (TRDD-FENWWB4E) (db7cea7)
- **notify:** Daemon-to-human notification channel — tiered, severity-gated, capped (TRDD-4649ZLE0) (fe864d5)

### Mem

- **project:** Janitor-daemon-bulk-lane — symptom-indexed page for the v0.50.0 bulk-lane fix + the lru-cache test-isolation lesson (memorize-nudge) (2b42fad)
## [0.50.0] — 2026-07-17

### Bug Fixes

- **resume-push:** Self-cancel when nothing is pending (TRDD-8IZ8COQ8) (cbfd43c)
- **security:** Per-project channeling — no automatic surface carries another project's findings (TRDD-X92VBFNF) (41eecae)
- **daemon:** Background bulk lane — never starve the 60s survival beats (TRDD-H7NVKSAX) (0bbd2ff)

### Documentation

- **trdd:** 28XF77X6 complete -> published (v0.49.1 shipped) (6931e7f)
- Add TRDD-4649ZLE0 — daemon-to-human notification channel (user directive: findings must reach a human when no session is alive) (7ea11d1)
- **trdd:** H7NVKSAX record implementation commit 0bbd2ff (e9e475b)
- Two-backend architecture section + README harness note + repomap refresh (TRDD-PZLVT2RN Phase E) (a88ddd4)
- **trdd:** PZLVT2RN — rewrap NEXT ACTION so no line starts with '#100' (markdownlint MD018 NIT-blocked the strict gate, same class as 3fde74d) (76a3015)

### Features

- **harness:** The two-world backend SSOT — harness_backend.py (TRDD-PZLVT2RN Phase A) (0874122)
- **daemon:** Harness-exclusion — never actuate on a server-owned ai-maestro agent (TRDD-PZLVT2RN Phase B) (e613314)
- **harness:** #J thin mode — no daemon, no outside-world writes inside an ai-maestro agent (TRDD-PZLVT2RN Phase C) (47926b3)
- **daemon:** Yield once-only chores to an active ai-maestro server (TRDD-PZLVT2RN Phase B2) (27684dc)
- **harness:** #J delegation + self-trigger hardening (TRDD-PZLVT2RN Phase D) (2758241)
## [0.49.1] — 2026-07-17

### Bug Fixes

- **compact:** Learn the post-compaction floor BEFORE the action gates (TRDD-28XF77X6) (87c8b56)

### Documentation

- **trdd:** D3PROACT + CCCOMPAT dev -> published (shipped v0.49.0) (e3b5d0b)
- **memory:** Stamp the floor-gate page with its ship version (v0.49.0) (b1e31d6)
- Add TRDD-28XF77X6 — v0.49.0 floor gate never engages (refresh_floor placed behind action gates the compaction itself stamps) (b25efb2)
- **trdd+memory:** TRDD-28XF77X6 complete in 87c8b56; wikimem correction — floor measured before the action gates (0f9974e)
- **trdd:** PZLVT2RN — owner directive received (2026-07-17): go for the janitor-side build; packaging settled = ONE plugin runtime-branched; explicit daemon-side harness-exclusion deliverable; continuity.sh verified on disk (8bf3b12)
- **trdd:** 28XF77X6 — rewrap a hard-wrapped line starting '+ ' (poisoned markdownlint MD004 ul-style, NIT-blocked the v0.49.1 publish) (3fde74d)

### Miscellaneous Tasks

- **lint:** Re-sync .markdownlint.json with the CPV canonical template (add MD052:false) — the --strict gate NIT-blocked v0.49.1 on this drift (64fc85d)
## [0.49.0] — 2026-07-17

### Bug Fixes

- **compact:** Stop the infinite compact loop — floor gate + 350k threshold (TRDD-D3PROACT) (1a69ec6)

### Documentation

- Add TRDD-D3PROACT — proactively compact an idle large context to prevent the cold burn (14d4357)
- Add TRDD-CCCOMPAT — align the janitor with Claude Code through 2.1.212 (8f04f95)
- Refresh CLAUDE.md project map (D3PROACT + CCCOMPAT symbols) (3ac01e0)
- **trdd:** D3PROACT — record the infinite-compact-loop finding + 4 lessons; refresh map (4b2c15c)
- **memory:** Wikimem — the compaction floor gate and why a size-only gate can't terminate (69fc797)
- **trdd:** Record implementation-commits for the batch; QW6RVAKN dev -> published (3b863d5)

### Features

- **dispatch:** Proactively compact an idle large context to prevent the cold burn (TRDD-D3PROACT) (432d800)
- **state:** Accept CC's integer env-var spellings (1e6, 64_000) in config knobs (TRDD-CCCOMPAT) (2b6b1d8)
- **hooks:** Compact a large idle context at Stop — the event that CAN beat the burn (TRDD-D3PROACT) (fa8687d)
## [0.48.1] — 2026-07-17

### Bug Fixes

- **dispatch:** Don't echo a resume cue with a keep-going nudge (TRDD-QW6RVAKN) (0b5e37e)

### Documentation

- **trdd:** 6AABK2BG shipped v0.48.0 -> published (cache updated + daemon closure re-staged, deployed code proven silent) (2548e30)
- Add TRDD-QW6RVAKN — a compaction emits two back-to-back janitor-resume cues (830c846)
## [0.48.0] — 2026-07-17

### Bug Fixes

- **rotator:** Re-stamp the live-identity beacon when the credential changes (TRDD-6AABK2BG) (b597355)

### Documentation

- **trdd:** EQ792YPX shipped v0.47.0 -> published; spin out restart EHT TRDD-2C8XFOW9 (blocked on ai-maestro#75 + user confirm) (c214acd)
- **trdd:** 2C8XFOW9 architecture correction — settings-enforce+restart is a DAEMON global command (#N standalone daemon vs #J server-as-daemon, no agent-group overlap) (3c8bf83)
- Refresh CLAUDE.md project map (v0.47.0 — settings_ensurer + global_state.settings_ensurer_lock) (a548a1c)
- Add TRDD-6AABK2BG — a stale live-identity beacon blinds proactive rotation (8eed48e)
- **trdd:** Fix MD018 markdownlint NIT — no wrapped line starts with '#75' (c13a275)
## [0.47.0] — 2026-07-17

### Documentation

- **trdd:** Move 93TKV769, T7N67AQP, 3KDN6O9Z complete -> published (shipped in v0.46.0) (46190aa)
- Refresh CLAUDE.md project map (v0.46.0 symbols — per-pane presence, keep-going default, burn gate) (dcac964)
- Add TRDD-EQ792YPX — ensure recommended settings in ~/.claude/settings.json (TRDD-EQ792YPX) (725ae74)

### Features

- **session-start:** Ensure recommended Claude Code settings in ~/.claude/settings.json (TRDD-EQ792YPX) (523ec4a)

### Harden

- **settings-ensurer:** Supersecure verify-before-swap write (TRDD-EQ792YPX) (91bb4ec)
## [0.46.0] — 2026-07-16

### Bug Fixes

- **fleet:** Safe half of the ai-maestro preparedness audit — F5 + F8 (TRDD-AM8JD9SG) (eb9faa1)
- **dispatch:** Keep-going continue-nudge is ON by default in every mode (TRDD-93TKV769) (7cd8ea0)
- **presence:** Self-trigger presence is PER-PANE, 5-min window (TRDD-T7N67AQP) (001bb3e)
- **window-burn:** Gate agentlens cause on materiality — stop mis-blaming a workspace (TRDD-3KDN6O9Z) (6a56d63)

### Documentation

- **trdd:** Mark the v0.45.0 memory-series TRDDs published (7bad680)
- **memory:** Capture the v0.45.0 release lessons on the publish-pipeline pages (5f34409)
- **trdd:** Record impl commit eb9faa1 on TRDD-AM8JD9SG (bba2472)
- **trdd:** AM8JD9SG blocked-by ai-maestro#68 — coordination filed, publish gated (b4ab883)
- **memory:** CPV v2.159.0 fixes the resolver-tag detector FPs (#167/#168) — verify before bumping the pin (e630c33)
- **trdd:** AM8JD9SG — record ai-maestro#68 direction (R42 ground-shift + 8 verdicts + F11) (d1eb354)
- **trdd:** AM8JD9SG — USER ruled F1+F6 = scoped daemon principal + provenance root (c0c9851)
- **trdd:** AM8JD9SG — daemon-migration architecture coordination (janitor#100) (7387eaf)
- **trdd:** Add TRDD-PZLVT2RN — ai-maestro-tailored janitor (#J) + #N scope-flip + two-backend split (b04dd92)
- **trdd:** PZLVT2RN — ack landed on janitor#100 (aligned; awaiting owner direction) (9655176)
- **trdd:** 93TKV769 — code complete + committed (7cd8ea0); column complete, publish held (cebc17c)
- **trdd:** T7N67AQP — record impl commit 001bb3e (per-pane presence complete) (9e9e1e6)
- **trdd:** T7N67AQP — record commit e5888b2 (kitty/WezTerm terminal coverage) (8b1378b)
- **memory:** Capture WHY of keep-going default-on + per-pane presence (TRDD-93TKV769, T7N67AQP) (9202d59)
- **trdd:** 3KDN6O9Z — record impl commit 6a56d63 (burn materiality gate complete) (4a72fe2)
- **trdd:** Fix MD004 markdownlint NIT — no wrapped line starts with '+ ' ([#113](https://github.com/Emasoft/ai-maestro-janitor/issues/113)) (3f03a57)

### Features

- **presence:** Detect kitty + WezTerm panes; namespace pane keys by source (TRDD-T7N67AQP) (e5888b2)
## [0.45.0] — 2026-07-16

### Bug Fixes

- **self-integrity:** Skip manifest attestation in git source checkouts (T-DTTXJGC7, SELFINT-001 false positive) (3d3ab8e)
- **fleet:** #77 bounded parts — global-arm output honesty + advisory armed-stamp in fleet_status (e32e620)
- **rules:** Compress the #81 point-9 addition under the 52KB shipped-rules floor cap (99a611e)
- **rules:** Final 2 prose snips to clear the 52KB floor cap (the corpus sat AT the cap pre-#81) (53a2408)
- **cadence:** Re-arm dwell window kills the renew oscillation (#89, TRDD-CI6ZTNB9) (78e413d)
- **hooks:** Throttle PreToolUse additionalContext to tier TRANSITIONS ([#79](https://github.com/Emasoft/ai-maestro-janitor/issues/79)) (659a2d8)

### Documentation

- **trdd:** EQJPPZ2L LIVE on published+deployed code (v0.44.1) — full go-live chain verified (TRDD-EQJPPZ2L) (3870d30)
- **memory:** Capture the 2026-07-15 keychain lessons + author the desc-field/recall-invite TRDD (c004f9f)
- **trdd:** Capture the USER's memory-system directives as a 3-TRDD series (76ec073)
- **trdd:** 0NGYP3IG — memgrep atom-id resolution (id->page-path navigation, id->atom content) (ef273f6)
- **trdd:** 0NGYP3IG — atoms are mobile, so the index is the sole atom→page source + ids are corpus-wide unique (57e80b8)
- **trdd:** 87RKBYJ8 — capture the ROOT principle (one page = one topic) behind duties 10/14/15 (95e7ab2)
- **trdd:** NM4TPCQ9 — enforce topic-named pages (agents make description-named ones) (56abc67)
- **rules:** Re-import IND trdd-design-tasks from ai-maestro governance-rules ([#81](https://github.com/Emasoft/ai-maestro-janitor/issues/81)) (4e8b2df)
- **trdd:** W8KDPT2M (adopt AI Maestro CLI layer, #76 epic) + V5RXQ4NB (keychain READ partition-list flap, #82) (891a186)
- **config:** Declare the three new userConfig options from #89/#79 (dwell + the two nudge repeat intervals) (580de52)
- **map:** Refresh the auto-generated CLAUDE.md project map (project-map-drift) (4455784)

### Features

- **memory:** Require a <=200-char prose desc on every atom (upgrade from optional <=64 slug) (TRDD-AP2X9A0H) (383ddac)
- **memory:** Topic-named pages rule (NM4TPCQ9 prong 1) + desc<=200 prose sync in references (AP2X9A0H a) (1566375)
- **memory:** Recall INVITE on every non-trivial prompt (TRDD-7B1THXTB) (409aced)
- **memory:** Sync subconscious procedures — desc<=200, corpus-wide atom ids, topic-naming corrective (AP2X9A0H b, NM4TPCQ9 prong 2, 87RKBYJ8 gap list) (3179af3)
- **memgrep:** Atom-id navigation (atom-page/atom) + desc in listings (TRDD-0NGYP3IG, TRDD-AP2X9A0H c) (877de7d)
- **publish:** Push the {plugin}--v{version} dependency-resolver twin tag (#85, #90) (7b47f7c)
- **memory:** Load-bearing-token fidelity gate in the verify oracle ([#91](https://github.com/Emasoft/ai-maestro-janitor/issues/91)) (1a4ec54)

### Styling

- **rules:** Blank lines around 4 fences in the imported reference (MD031 publish-gate) (631d0ec)
- **docs:** Clear 4 publish-gate NITs — MD056 escaped pipes in the imported table, MD004 wrapped lines reading as plus-markers (bfe3217)
- **skills:** Compress janitor-memory-write + consolidate bodies under the 5000-token CPV cap (83add31)
- **skills:** Two more shaves — write body was 5007 vs the 5000-token cap (fd175b5)
- **memgrep:** Reword a doc comment the skillaudit scanner read as CMD_INJECTION (publish-gate NIT) (b7dca2d)
## [0.44.1] — 2026-07-15

### Bug Fixes

- **tickets:** A retried ticket was in the queue AND the archive (TRDD-CGYMUKO6) (9731c2d)
- **disarm:** The checklist told the agent to forge the flag the guard exists to gate (48523ca)
- **compat:** Guard the ≥85% context hardstop against CC 2.1.208's false 100%; doc the 2.1.207 plugin-option scope break (3ad6ebe)
- **review:** Heartbeat-filter the anomaly detector + spike threshold; drop the false durable narrative (45ccc57)
- **cadence:** Exclude the janitor's own agents from the FAST probe (TRDD-CI6ZTNB9) (1516fee)
- **wikimem:** Stop extract_lessons at an atom marker (TRDD-MADJ00KA) (bf7fc89)
- **wikimem:** _body_minus_lessons fails loud on a multi-page concatenation (TRDD-842PBES7) (d7acf90)
- **rotator:** Pin allow-ALL (-A) ACL on slot-token keychain writes (TRDD-EQJPPZ2L) (fa46a49)
- **rotator:** Set keychain ACL only at CREATE, data-only UPDATE thereafter (TRDD-EQJPPZ2L) (1cedf28)
- **rotator:** Self-healing keychain-denied latch (half-open circuit breaker) (TRDD-EQJPPZ2L) (59c9f3b)

### Documentation

- Refresh the fenced project map (the ticket system's new modules) (f6a46ef)
- TRDD-CGYMUKO6 — the CLI had no tests, and that is where the bug was (e3869d5)
- **memory:** The tool-call cost law, and why the cadence's own re-arm is billed (dfe3e03)
- **tokens:** A cache write costs 2x, not 1.25x — the main agent runs a 1h TTL (1959abc)
- **TRDD-DLI76AUC:** Items 2, 3, 4 done; record the grep-as-proof and moving-failure lessons (2827b59)
- Add TRDD-CI6ZTNB9, TRDD-MADJ00KA, TRDD-842PBES7 — 3 verified issues from the GitHub triage (f6f1fca)
- Add TRDD-EQJPPZ2L — rotator keychain WRITE triggers an ACL prompt (the recurring rotation-death root cause) (2294205)
- **trdd:** EQJPPZ2L part 1 landed (fa46a49) + correct the fix target (432cfad)
- **trdd:** EQJPPZ2L definitive root cause — ACL flag on -U update prompts (SecKeychainItemSetAccess) (f56972e)
- **trdd:** EQJPPZ2L code fix landed (1cedf28) — items 1+2 done; login validation gated on user (97c0341)
- **trdd:** EQJPPZ2L — rotation GO-LIVE, validated on the real login keychain (TRDD-EQJPPZ2L) (cba5aba)
- Clear publish gate — TRDD list-marker NIT ([#113](https://github.com/Emasoft/ai-maestro-janitor/issues/113)) + janitor-arm TOC embed MINOR (TRDD-EQJPPZ2L) (4c9b69b)

### Features

- **meter:** Log every turn, not just heartbeats — the arm was unmeasurable (TRDD-DLI76AUC #4) (a66c7a5)

### Performance

- **arm:** The re-arm was six billed tool calls, not a config write (TRDD-DLI76AUC) (ea6a3b9)
## [0.44.0] — 2026-07-14

### Bug Fixes

- **catalog:** Describe the pipe-to-shell installer without spelling it (a022ac3)

### Documentation

- TRDD-CGYMUKO6 — record Phase 3 and the two counterparts the raise path was missing (e8319b8)
- TRDD-CGYMUKO6 — Phase 3 complete; the reconcile inversion and why clear_issue was the wrong shape (3d90284)

### Features

- **tickets:** Withdraw a cleared proposal, and remind from ONE place (TRDD-CGYMUKO6) (10de6e0)
- **tickets:** The GitHub scanners now PROPOSE a fix, not just a nag (TRDD-CGYMUKO6) (80fd10e)
- **tickets:** The HARNESS producers open their own tickets (TRDD-CGYMUKO6) (9c9fd6f)
- **tickets:** The supply-chain scanners propose too, and stale findings sweep themselves (TRDD-CGYMUKO6) (3226ec7)
## [0.43.0] — 2026-07-14

### Bug Fixes

- **resume:** Push /janitor-resume after a compaction so an idle session wakes in seconds, not up to 30 min (TRDD-HI0BGQGJ) (307427a)
- **review:** 4 code-review findings on the fleet-audit + cold-cache work (b4b2064)
- **branch-protection:** Omit required_status_checks when no CI contexts — GitHub 422s an empty array (f6b08d3)
- **fleet:** The ai-maestro inject channel reported success on spawn, not delivery (TRDD-3VW434Q8) (e7c4624)
- **memgrep:** The schema migration manufactured the FTS corruption it was meant to fix (7c91dbf)
- **inject:** Never type into the user's pane while they are present unless they asked (0bdd3d4)
- **disarm:** Disarmed.flag now requires real human authority (TRDD-RDFWQIFA) (05e60c4)
- **wikimem:** The two merge gates were mutually unsatisfiable (TRDD-MQBV844P) (3103dee)
- **skills:** Janitor-github-config-fix had unparseable frontmatter (fd9ed00)
- **skills:** Tighten janitor-github-config-fix description under the token limit (6097488)
- Clear the three --strict NITs blocking the release (a90df1d)

### Documentation

- **trdd:** K1RJUYGK shipped in v0.42.0 → column testing; falsification (re-measure) still pending (27653a0)
- **memory:** Record the self-update bootstrap gap — a fast-updater can't accelerate its own first release (b60032d)
- **trdd:** HI0BGQGJ implemented in 307427a → column testing; falsification of the attended gate verified (ce2d3c5)
- **trdd:** 157OH2D7 implemented in 8bd2949 → column testing (f235be7)
- **trdd:** EUWIHP0G implemented in dc059f3 → column testing (184dad5)
- **map:** Refresh the fenced CLAUDE.md project map (7d25bc7)
- **trdd:** 3VW434Q8 implemented in e7c4624 → column testing; falsification verified (9533b76)
- Add TRDD-RDFWQIFA — disarmed.flag is a forgeable user opt-out (4f8dd46)
- **memory:** Record the memgrep FTS-desync corruption, indexed by its symptom (1ac25b9)
- Add TRDD-MQBV844P — the two merge gates are mutually unsatisfiable (6442bd8)
- Add TRDD-CGYMUKO6 — janitor support-ticket system (incident management) (3350019)
- **TRDD-CGYMUKO6:** The issue-code catalog + resume state (f0e7b24)
- **TRDD-CGYMUKO6:** Publish the issue-code catalog as docs/ISSUE-CODES.md (b3451e9)
- TRDD-CGYMUKO6 — record the finding that changed the design (f6e94d2)

### Features

- **github-config:** Fleet-wide GitHub-config audit + on-demand fix skill (TRDD-157OH2D7) (8bd2949)
- **resume:** Cold-cache auto-compact on resume after a >1h idle gap (TRDD-EUWIHP0G) (dc059f3)
- **memgrep:** Validated, transactional schema migrations — a migration must prove its own output (2b5ca2c)
- **tickets:** The support-ticket core — incident queue + the ownership boundary (TRDD-CGYMUKO6) (9b66a98)
- **tickets:** The scheduler + the CLI — dispatch across heartbeats (TRDD-CGYMUKO6) (cf18e8d)
- **tickets:** The issue-code catalog — one entry point every scanner raises through (TRDD-CGYMUKO6) (fc1cffa)
- **tickets:** Memgrep emits issue codes; the health detector turns them into work (TRDD-CGYMUKO6) (b8f17f7)
- **tickets:** Arm the incident queue — the self-heal ledger, the agent, the wiring (TRDD-CGYMUKO6) (d7706e3)

### Miscellaneous Tasks

- Refresh the fenced CLAUDE.md project map (stale digest) (4631971)

### Styling

- **memgrep:** Apply cargo fmt (29d9871)
## [0.42.0] — 2026-07-13

### Bug Fixes

- **keychain-health:** Restore the missing exec bit on the detector (84fe8da)
- **identify-environment:** Mask git remote credentials in the report (TRDD-ULYUOP0Y) (391da59)
- **env-detect:** Stop misclassifying local FUSE mounts as network (TRDD-ULYUOP0Y) (f8fe737)
- **global-state:** Lock the plugin-update-requests RMW against lost updates (TRDD-YMTUPQER) (bec2f54)
- **test-sandbox:** Git -c arg-skip in verb parse; drop unreachable python-deny branch (TRDD-DQJVVMFN) (dbaaaf2)
- **test-sandbox:** Launchd witness compares labels, not volatile PID column (TRDD-DQJVVMFN) (e4e7001)
- **manifest:** Plugin description claimed a 'durable' cron and 'No external daemons' — both false (a4d6995)
- **memgrep:** A lesson had no keywords, so it was unreachable — give it its address back (d842a92)
- **security:** Four guards that did not guard (audit findings #1/#4/#5/#6) (9fb748a)
- **memory:** CRITICAL — a crash-recovery could DELETE a page and lose it forever (F1) (07c4de3)
- **memory:** The conflict pass could never commit, and harvest never converged (F2) (7d1fe1f)
- **memory:** A "new page" write could silently overwrite an existing memory (F3) (2b83d5c)
- **security:** The audit chain broke ITSELF, then cried tampering forever (F4) (ed7785a)
- **oauth:** A captured account could be silently orphaned by the daemon tick (24be5a9)
- **security:** Racing key-minters orphaned a key, breaking chain verification (F6, F7) (220fd0c)
- **memory:** The USER-memory backup mirrored a live transaction, and an index could block restore (F10) (8fb66a3)
- **daemon:** The recovery audit log destroyed its own tamper-evidence, then buried itself in noise (F8, F9) (5803e71)
- **memory:** "staged file is gone" is not proof a write applied (F5) (bee7266)
- **memory:** A lesson could be silently truncated, and the crash journal was not durable (F11, F12) (b51056d)
- **daemon:** Harden the iTerm AppleScript sink; share the robust update matcher (findings 3, 4) (790d570)
- **oauth:** Stop writing the OAuth authorization code to disk and to the log (finding 2) (e5f52f5)
- **memgrep:** 20 lessons were silently missing from the index (two bugs, both mine) (49a352d)
- **hooks:** Our own context guard was the machine's #1 prompt-cache breaker (TRDD-K1RJUYGK) (d50fe8c)
- **hooks:** The injection guard was still injecting on its own hot path (TRDD-K1RJUYGK) (6245379)
- **memgrep:** Collapse the nested if in raw_footnote_defs (clippy 1.97 -D warnings) (ed9f5a8)
- **env:** Clear CPV strict-validate gate — 1 CRITICAL + 3 real findings (not scanner appeasement) (9da474e)

### Documentation

- **trdd:** Add Y9KM5RCJ — release-triggered janitor self-update (2fdc411)
- **trdd:** Y9KM5RCJ complete — record impl commit 5554a51 + test pass (f3e17cf)
- **trdd:** Add YMTUPQER — universal per-heartbeat plugin auto-update (083a5b6)
- **trdd:** YMTUPQER complete — impl 92bb9af + tests 38cb35d, suite pass (84cf6a8)
- **memory:** Add janitor beat-tasks + limitations wikimem (PROJECT scope) (d9264b7)
- **map:** Refresh CLAUDE.md project map for YMTUPQER symbols (091f36f)
- **memory:** Record the DEAD SECURITY SESSION gotcha + its lesson (2026-07-12) (e535db7)
- **memory:** Stay on topic — a case page holds case facts, methodology lives in one page (54f12a8)
- Add TRDD-DQJVVMFN — test process sandbox (complete) (e03c282)
- Add TRDD-ULYUOP0Y — environment detection expansion (complete) (10dae1f)
- TRDD-ULYUOP0Y wave-2 addendum + implementation-commits (231259f)
- **memory:** Capture the identify-environment prober design + the "anchor a subprocess loses" lesson (c8a7889)
- TRDD-ULYUOP0Y wave-3 addendum + implementation-commits (gh/CI/releases/registries/homebrew/fork/topology) (1be5a03)
- Refresh CLAUDE.md project map after the code-review source edits (c909b34)
- **memory:** The heartbeat cron is session-scoped BY DESIGN — 'durable' was never a real param (92e2953)
- The heartbeat cron is session-scoped by design — retract the 'durable downgrade' claim (a87ad58)
- **memory:** A lesson is a guardrail, not a story — prescribe the terse form (0518a22)
- **trdd:** YRPUSIFY's bucketing approach is falsified — the strip, not the text, breaks the cache (6e29e31)
- **map:** Refresh the CLAUDE.md project map after the cache-thrash fix (d64c605)
- Add TRDD-9K0O5YBQ (Claude Code compat audit) + TRDD-SLFMG704 (cross-plugin handoff) (c8e6342)
- **trdd:** SLFMG704 — hook: Stop belongs to NO plugin; and three ai-maestro Stop hooks are broken (d7f79eb)
- **trdd:** SLFMG704 — reconcile the offender table with the completed attribution (b875905)
- **trdd:** SLFMG704 — prove AgentLens's "hook: <Event>" label is a boundary, not an emitter (b4e8609)
- **trdd:** K1RJUYGK — RETRACT the attribution; the fix stands, the blame does not (2b179f1)
- **trdd:** Retitle K1RJUYGK — a retraction that leaves the headline standing is not a retraction (31c6e96)
- **trdd:** SLFMG704 — RETRACT the "broken ai-maestro hooks" finding; it was my query that was broken (0eebf2e)
- **trdd:** SLFMG704 — PostToolBatch has no owner; the boundary-not-emitter proof gets its cleanest leg (b0153a1)
- **skills:** Split the two oversized memory SKILL.md bodies under the CPV token gate (lossless) (2f4a7e9)

### Features

- **version-update:** Release-triggered janitor self-update (TRDD-Y9KM5RCJ) (5554a51)
- **plugin-updates:** Universal user-scope auto-update via daemon signal (TRDD-YMTUPQER) (92bb9af)
- **keychain-health:** Detect a security session that cannot reach the keychain (92c6417)
- **identify-environment:** Full secret-safe environment prober (TRDD-ULYUOP0Y) (eca37bb)
- **identify-environment:** Add Claude auth-mode / subscription detection (TRDD-ULYUOP0Y) (e2a929a)
- **identify-environment:** Git/GitHub/wikimem/plugins detection + JSON-to-disk (TRDD-ULYUOP0Y) (1ad7a5b)
- **identify-environment:** Count standalone (non-plugin) skills (TRDD-ULYUOP0Y) (2eb64aa)
- **identify-environment:** Gh user, CI actions/Claude-action, releases, registries, homebrew-tap-trust, fork, topology (TRDD-ULYUOP0Y) (fbd1ef6)
- **memgrep:** A lesson is an ATOM — give it id, status, key-phrases (schema v4) (4558b1e)

### Miscellaneous Tasks

- Bootstrap .trashcan (gitignore + survival markers) after first safe-delete (3c53ec3)

### Performance

- **commands:** 14 memory-frequency knobs -> 1 command (-1262 tok EVERY session) (ffb2608)

### Testing

- **plugin-updates:** Real no-mock tests for universal user-scope auto-update (TRDD-YMTUPQER) (38cb35d)
- **sandbox:** Add audit mode — record every process spawn (Phase 0) (dc102a0)
- **sandbox:** Deny-by-default process + signal guard (S1h) (fd0b482)
- **sandbox:** Prove the process guard guards (35 tests + falsification) (12633c8)
- **sandbox:** Witness the two states that are not files (S1i) (2863a51)
## [0.41.0] — 2026-07-12

### Bug Fixes

- **memory:** Keep write SKILL.md under the CPV 5000-token gate (8754c12)

### Documentation

- **trdd:** EG2HSPMQ published in v0.40.0 — SessionStart hook restored fleet-wide (007c628)
- **trdd:** 0QQX9H0G published in v0.40.0 — board said complete, code was live (e9073dd)
- **config:** Register the two agentlensPro burn probes + document the enrich (e0aca0a)
- **trdd:** Agentlens adoption complete — correct the stale "switch" premise (53f8d10)
- **memory:** AgentlensPro integration page + the capacitySource:none finding (d2f47cd)
- **memory:** Wikimem authoring gains the Wikipedia proactive-linking discipline (ed6517c)

### Features

- **agentlens:** Shared config-gated probe lib for burn-rate + culprit (TRDD-WUUR2DFX) (e2e4e89)
- **window-burn:** Prefer agentlensPro investigate_burn culprit, native fallback (TRDD-90B47EM9) (e107a57)
- **token-anomaly:** AgentlensPro cross-check — corroborate + attribute (TRDD-HL8H3XCV) (f18e233)
## [0.40.0] — 2026-07-11

### Bug Fixes

- **fleet-stop:** ESC-interrupt a FROZEN target so a machine-wide stop actually lands (109c7d2)
- **cadence:** The resume FAST signals were unreachable — stamp last-resume.ts (39feb86)
- **rotator:** The keychain denied-latch was still writing to the LEGACY global-state dir (7ceab3f)
- **keepalive:** Refuse to stage the daemon closure over a plugin SOURCE checkout (TRDD-RYZCVVKA) (fef258c)
- **trdd:** The roots SSOT must honor CLAUDE_PLUGIN_OPTION_TRDD_PATH (50e07a0)
- **hooks:** SessionStart hook died on import 2026-06-20 — restore it, and prove hooks run (b28c53a)
- **tests:** The write guard failed the suite for the LIVE daemon's own work (S1f) (d2b8c69)
- **publish:** Clear the 3 CPV strict gates the guard/scope work tripped (dbfbac9)

### Documentation

- Add TRDD-0GPQROC1 — soft-by-default command injection (6a2ec62)
- **trdd:** Record TRDD-0GPQROC1 implementation commit + test pass (3dc9d2e)
- Add TRDD-0QQX9H0G — TTL-aware dynamically-tiered heartbeat cadence ([#83](https://github.com/Emasoft/ai-maestro-janitor/issues/83)) (9fc65e3)
- **trdd:** Close out 0GPQROC1 + 0QQX9H0G; open the agentlensPro adoption trio (7dadff9)
- **trdd:** Close 7 shipped-but-open TRDDs — board drift, not unfinished work (52e5f04)
- **trdd:** P4 answered by measurement; YXY992BN superseded by agentlensPro (a3fc766)
- **trdd:** TRDD-2KQQAEPP → complete (551531c) (788afce)
- **trdd:** ULEGRT01 blocked on publishing 7ceab3f — the gate caught a real bug (4c8114a)
- **trdd:** VQ4LX7ND part-2 silence fixed; file TRDD-RYZCVVKA — working tree clobbered by the cached closure (5483dab)
- **trdd:** RYZCVVKA — write path found and closed; suite exonerated by instrumentation; invoker still unattributed (6e08f24)
- **trdd:** YRPUSIFY P2 shipped — always-loaded floor 270,596 -> 200,259 B (-26%) (2bad0e3)
- **trdd:** RYZCVVKA attributed — and retract the false "suite exonerated" claim (76f6440)
- **memory:** Record the RYZCVVKA recurrence on the keepalive-isolation wiki page (ce74434)
- **claude-md:** Refresh the fenced project map (picks up the iTerm TCC detectors) (9569778)
- **rules:** TRDD spec gains LOCAL scope, and the id-collision check stops infinite-looping (d9a3c91)
- **memory:** Record the two-import-conventions trap that killed the SessionStart hook (53670d4)

### Features

- **injection:** Soft-by-default — commands enqueue at the turn boundary (TRDD-0GPQROC1) (84c4564)
- **heartbeat:** TTL-aware dynamically-tiered cadence — 6x cheaper idle, zero recovery regression (TRDD-0QQX9H0G, #83) (431982f)
- **issues-watch:** Notify main Claude of new GitHub issues and comments (TRDD-2KQQAEPP) (551531c)
- **memory:** Session-start breadcrumb + stop the manifest lying about two default-ON hooks (TRDD-98ISATJZ) (b92e388)
- **rotator:** Verify-before-scrub — never destroy cookies we cannot prove we can restore (TRDD-dfc0959a) (0028c1e)
- **memory:** Scope-migration --apply — publish a reviewed plan, and refuse everything else (TRDD-47df698b) (ea5fae3)
- **fleet:** Stop the iTerm TCC denial from being a silent skip loop (TRDD-VQ4LX7ND part 2) (43f3f2a)
- **trdd:** LOCAL design scope — the roots SSOT (3-pillars spec) (723c37f)
- **trdd:** Wire trdd-drift + trdd-reminder to BOTH design scopes (2/8 consumers) (562132d)
- **trdd:** Wire trdd-state-reconciliation to BOTH design scopes (3/8 consumers) (25b9335)
- **trdd:** Wire the last 5 consumers to BOTH design scopes (8/8 — LOCAL scope complete) (ecd9af0)

### Performance

- **rules:** Cut the machine-wide context floor 56% — move reference material off the prefix (460aad0)
- **memory:** Stop consolidate re-spawning a 260k-token agent on an unchanged corpus (473e417)
- **rules:** Keep the LOCAL-scope rule under the context-floor ratchet, and cut 2.9 KB of boilerplate (b78e6f3)

### Testing

- **conftest:** S1c — fail the suite if any test writes the source tree (TRDD-RYZCVVKA) (56bf46d)
- **sandbox:** BLOCK any test writing outside its boundary (TRDD-RYZCVVKA, S1e) (05b1a38)
- **sandbox:** Extend the write sandbox into every CHILD process (S1g) (af8a272)
## [0.39.0] — 2026-07-09

### Features

- **dispatch:** Token monitoring survives maintenance mode; every reload sends --force (TRDD-8Q0OYVWM) (f9d6bd9)
## [0.38.0] — 2026-07-09

### Features

- **compaction:** Dedupe the post-compact injection; open-issues section in the rich handoff (TRDD-498LEWZ4) (ebfa1e6)
## [0.37.0] — 2026-07-09

### Documentation

- **memory:** The opt-out flag with no writer, and the shared file disarm deleted (1a1409e)
- **trdd:** TRDD-EFTQB9RR published as v0.36.0 and verified live (eea7f98)

### Features

- **dispatch:** Opt-in per-fire cost series via a user-configured CLI (36aeca4)

### Miscellaneous Tasks

- **repomap:** Refresh the CLAUDE.md project map after v0.36.0 (aace5c1)
## [0.36.0] — 2026-07-09

### Bug Fixes

- **fleet:** Give disarmed.flag a writer, and stop disarm deleting a shared file (57bfe31)
- **session-start:** Re-arm on every wake; the armed stamp was never trustworthy (b2be32b)

### Documentation

- **memory:** Capture today's WHYs — fleet reachability + the CPV gate (869892d)

### Features

- **daemon:** Sweep stale rate-limited flags so a quiet session is not read as frozen (9e6fa2b)
## [0.35.9] — 2026-07-09

### Miscellaneous Tasks

- **release:** Wrap the CPV gate in the hang timeout+retry ci.yml already had (99612af)
## [0.35.8] — 2026-07-09

### Miscellaneous Tasks

- Pin the THIRD CPV call site — ci.yml was left resolving the default branch (f00b9a6)
## [0.35.7] — 2026-07-09

### Bug Fixes

- **agents:** Bound the resume nudges so a dead fork is not pinged for a week (dfe5913)
## [0.35.6] — 2026-07-09

### Bug Fixes

- **daemon:** The PATH repair fixes tmux only — drop the false ai-maestro claim (ef28e02)

### Documentation

- **trdd:** TRDD-VQ4LX7ND — launchd guardian channel blindness (d569388)
- **trdd:** Spell the observed PATH without leading separators (ce4f7a9)
## [0.35.5] — 2026-07-09

### Bug Fixes

- **fleet:** Gentle rungs must reach ai-maestro agents and Linux GUI terminals (b684571)
- **daemon:** Repair the tool PATH so the launchd guardian can reach the fleet (2ff5c7c)

### Documentation

- **ci:** Correct the release-timeout rationale — 30m is headroom, not the fix (6582700)
- **memory:** Record why the janitor carries no role plugin, and what survives takeover (62147c6)
- **fleet:** Instance.terminal documents all four identity keys (612f97f)
## [0.35.4] — 2026-07-09

### Documentation

- **trdd:** Carry 3 memory-pass decisions into TRDD-3XS3PDCF STATE (b659def)
- **trdd:** Reflow a line that poisoned markdownlint MD004 (6b9d050)

### Miscellaneous Tasks

- **repomap:** Refresh the fenced CLAUDE.md project map (381cc98)
- **release:** Pin CPV to v2.153.1 and raise the release bound to 30m (c7c4613)
## [0.35.3] — 2026-07-09

### Bug Fixes

- **dispatch:** Driver-aware keep-going nudge fallback ([#74](https://github.com/Emasoft/ai-maestro-janitor/issues/74)) (7aeca22)

### Documentation

- **design:** TRDD-98ISATJZ — own the memory-discoverability design (janitor#62) (c40b79f)
## [0.35.2] — 2026-07-09

### Bug Fixes

- **rules:** MD031 blanks-around-fences in the shipped trdd-design-tasks IND rule ([#73](https://github.com/Emasoft/ai-maestro-janitor/issues/73)) (6c88fc2)
- **rules:** Escape literal pipes in trdd-design-tasks transition table ([#73](https://github.com/Emasoft/ai-maestro-janitor/issues/73)) (0e76197)

### Documentation

- **trdd,memory:** SECOND flood root cause + v0.35.1 fix + user-side unlock (TRDD-K3WQ7XM9) (7fd1668)
- **footprint:** List the 3 IND governance rules in the shipped-rules footprint ([#73](https://github.com/Emasoft/ai-maestro-janitor/issues/73)) (5c16e5d)

### Features

- **rules:** Ship the 3 IND governance rules via rules_installer ([#73](https://github.com/Emasoft/ai-maestro-janitor/issues/73)) (053a169)
## [0.35.1] — 2026-07-09

### Bug Fixes

- **rotator:** Gate keychain-reading detectors on the rotator opt-in (TRDD-K3WQ7XM9) (1140208)

### Documentation

- **trdd:** Keychain flood RESOLVED + guardian re-armed (TRDD-K3WQ7XM9) (22224db)
- **memory:** Keepalive-staging trap — a published fix isn't deployed while the OS-keepalive runs a STALE staged daemon (TRDD-K3WQ7XM9) (97a7c34)
## [0.35.0] — 2026-07-09

### Bug Fixes

- **state:** Init_state must not crash the OS-keepalive daemon on read-only "/" (d939110)
- **keepalive:** Staged_is_current compares whole closure, drops filecmp (TRDD-K3WQ7XM9) (a39cf84)
- **rotator:** Isolate keychain tests to a real temp keychain via JANITOR_ROTATOR_KEYCHAIN (TRDD-K3WQ7XM9 FIX B) (5862e50)
- **daemon:** Mark the rotator tick HEADLESS so it never prompts on the primary read (TRDD-K3WQ7XM9 FIX B2) (1cf0b6c)
- **rotator:** Safe Keychain Protocol — a denied-latch choke-point makes a prompt-flood impossible (TRDD-K3WQ7XM9 P1/P2) (3e5c36a)

### Documentation

- **trdd:** Add K3WQ7XM9 — daemon crash-loop repair (init_state/staged_is_current/test-isolation/keychain) (498b623)
- **trdd:** K3WQ7XM9 bug #3 verified, bug #4 documented, keychain-test note (3c0a795)
- **memory:** Macos-keychain wikimem — safe keychain protocol + ACL-prompt-flood gotcha (8fc1154)

### Testing

- **tmux:** Gate real-tmux E2E behind JANITOR_TEST_REAL_TMUX, skip by default (TRDD-K3WQ7XM9 FIX A) (6d3fefa)
- **conftest:** Strip leaked JANITOR_ROTATOR_HEADLESS + latch before every test (85e6d17)
## [0.34.0] — 2026-07-09

### Bug Fixes

- **rotator:** Never consume the -livebak mirror as live identity (TRDD-7PYTX4E9 F1/F3/F5) (af68a6e)
- **rotator:** Tick-liveness alert + session-context live-identity beacon (TRDD-7PYTX4E9 F2/F4) (c740a5a)
- **oauth-rotator:** Bound the 3 unbounded macOS `security` slot calls (headless hang) (c717743)

### Documentation

- **trdd:** 82OP4EN9 published in v0.33.0 + activation record (1173c82)
- Add TRDD-7PYTX4E9 — rotator daemon blind-spot (silent mirror fallback masquerades as live identity) (8a2d86f)
- **trdd:** 3XS3PDCF — harvest precheck UNBLOCKED (coexistence model live in v0.33.0) (548a7df)
- **trdd:** 3XS3PDCF — harvest precheck implemented (10f899b); precheck set complete (287b135)
- **trdd:** 3XS3PDCF — conflict precheck implemented (f2056ca); all six chores gated (f987803)
- **trdd:** 7PYTX4E9 — F1-F5 implemented (af68a6e + c740a5a), tests 331/331 green, not yet published (8ea9956)

### Features

- **scheduler:** Harvest content-precheck — suppress no-op harvest spawns (TRDD-3XS3PDCF) (10f899b)
- **scheduler:** Conflict content-precheck — suppress no-op conflict spawns (TRDD-3XS3PDCF) (f2056ca)

### Testing

- **conftest:** Exclude daemon fleet-recovery dir from the S1b write-guard (caf9597)
- Skip real_state keychain tests when the macOS keychain is prompting (unblock publish) (75b7ce3)
- **oauth-rotator:** Mock _primary_live_item_absent in the stale F1-era restore test (c4ab682)
- **guard:** Exclude daemon spawn-history + keepalive restage-stamp from the S1b write-guard (c3c08a5)
## [0.33.0] — 2026-07-08

### Bug Fixes

- **daemon:** Recency-gate daemon_needs_restart so an older cache can't seize a newer daemon (TRDD-FVO2KSSO) (63dca7a)
- **arm:** Map [janitor-reload] to /janitor-reload-plugins in the cron prompt (issue #70, TRDD-GB3Z9U9J) (ddfc4f6)
- **token-meter:** Count usage ONCE per message id — per-entry summing inflated turns 2.1-3.7x (user bug report) (29d2506)
- **memory-verify:** Verify_repair accepts tier-less pages — absent means component (issue #68 P3, TRDD-UENXDA8P) (6a1c04b)
- **tests:** S1b guard excludes daemon-owned runtime churn (code-review xhigh finding) (c67191d)
- **cleanup:** Executable bit on reports-purge.py — the heartbeat exec()s detectors directly (caught by test_detector_executable_bits) (cc6a482)
- **wikimem:** H-1 merge-into-survivor verify blind spot + H-2 abort destroying a committing journal (wikimem audit) (001f656)
- **user-mem:** Close the 3 privacy-leak HIGHs — memgrep walk exclusion + fail-closed hook + fitted time budgets (wikimem audit F8-F11) (a443c92)
- **wikimem-skills:** The 5 instruction-surface HIGHs from the wikimem audit (H1-H5) (3d08a75)
- **wikimem:** Enforce is_legal_merge/is_legal_split at commit time (wikimem audit libs M-2) (85c1aa2)
- **wikimem:** Roll-forward preserves concurrent edits — hash-guard _apply writes/deletes (wikimem audit libs M-1) (d4d8a94)
- **wikimem:** Harden resume_pending — per-journal isolation, orphan-staging sweep, mtime-based staleness (wikimem audit libs M-7, M-8, M-9) (45f83ad)
- **wikimem:** Validate txn rel-paths against scope-root escape (wikimem audit libs M-10) (e83e591)
- **wikimem:** Parse_frontmatter supports block-style YAML lists (wikimem audit libs M-4) (359875e)
- **wikimem:** Settings robustness — float-modulo phase + coerce-on-load (wikimem audit libs M-5, M-6) (410190c)
- **wikimem:** Route scope-root re-derivations through the memory_scopes SSOT (wikimem audit libs M-11) (3cd610d)
- **wikimem:** Autorecall sanitizes injected lines + filters non-note files (wikimem audit runtime F14, F15) (750ea33)
- **wikimem:** Memgrep walk excludes the non-note family — *-proposed.md reports filtered engine-side (wikimem audit runtime F16) (c4dcb5d)
- **wikimem:** Scope-leak detector — tracked-only bounded LOCAL-shape scan + stale proposal clearing (wikimem audit runtime F18, F19) (d1a4b04)
- **wikimem:** Librarian recurses via the SSOT scan + keys notes/links on rel paths (wikimem audit runtime F20) (4565b74)
- **wikimem:** Central defang of forged reserved markers in detector stdout (wikimem audit runtime F6) (010938d)
- **wikimem:** Pending-pick sidecar pins the stamped (scope, root) for the fanned-out agent (wikimem audit runtime F1) (9b7f997)
- **wikimem-skills:** Execution-context banners say Sonnet, not opus (wikimem audit skills M1) (655a9f8)
- **wikimem-skills:** Txn CLI invocations resolve via $CLAUDE_PLUGIN_ROOT (wikimem audit skills M2) (c545637)
- **wikimem-skills:** Conflict skill matches the real CLI ops + executor toolset (wikimem audit skills M3, M7) (0a5584b)
- **wikimem-skills:** Consolidate step-1 recency listing actually works (wikimem audit skills M4) (fe327c1)
- **wikimem-skills:** Harvest stamps claude_mem_ref/hash provenance; split backlink query uses the slug (wikimem audit skills M6, M11) (b9fee46)
- **wikimem-skills:** Main-agent skills declare page bodies untrusted (wikimem audit skills M10) (2f79f4c)
- **wikimem:** Per-project rr-cursor + fail-open catch-all + flushed marker (wikimem audit runtime F2, F3, F5) (253b5f3)
- **wikimem:** Flock-serialize memory_settings' two read-modify-write sites (wikimem audit runtime F4 = libs L-12) (9959dc8)
- **wikimem:** Edit-verify LOW batch — L-2 heading-stop, L-3 full-line heading, L-4 fence mask, L-5 per-id dangling refs, L-6 fence-state dupes (wikimem audit libs) (400c1d0)
- **wikimem:** Txn CLI — L-7 op cross-check, L-8 --unsplittable, L-9 overview pick, L-10 abort-on-shape-error (wikimem audit libs) (92baeaf)
- **wikimem:** Migrate plan records skipped notes (L-13) + regression tests for the libs LOW batch (ee9fd4c)
- **memgrep:** Trdd_id8_re accepts 8-char base36 ids, not hex-only (wikimem audit skills L5) (0409175)
- **wikimem-skills:** Wikimem/ home unified across write/bootstrap/harvest + LOWs L1-L9 (wikimem audit skills, M5 USER decision 2026-07-08) (40e5d09)
- **janitor:** [janitor-resume] gets the whole-line-only marker contract (wikimem audit runtime F7) (191dc77)
- **user-mem:** Close the whitespace-bypass + argv-exposure privacy gaps (wikimem audit runtime F12, F13) (119d1c2)
- **hooks:** Memory-correction advisory covers MultiEdit (wikimem audit runtime F22) (a53bff5)
- **janitor:** Daily state-dir sweep bounds seen-file/stamp growth (wikimem audit runtime F21) (09dd040)
- **lint:** MD029 audit-skill 1b indent + MD004 harvest plus-prose (publish gate) (cc0fb53)
- **daemon:** Restructure the log-dir re-pin as an audited read-modify-write (CPV ENV_INJECTION, TRDD-82OP4EN9 publish gate) (fac2e61)
- **lint:** Clear 3 CPV NITs - TRDD wrapped plus-line + missing TOCs (publish gate, TRDD-82OP4EN9) (df3a544)
- **lint:** Embed merge-page-rules full TOC in consolidate Resources (CPV MINOR, publish gate) (18d35cf)
- **wikimem-skills:** Restore M9 marker name + forged-marker section lost in history linearization (c885b4d)

### Documentation

- **trdd:** Add TRDD-FVO2KSSO — align janitor with CC 2.1.181->2.1.200 (plan only) (d72b9a3)
- **cc-align:** D-G alignment notes for CC 2.1.181-2.1.200 (TRDD-FVO2KSSO) (c16a671)
- **trdd:** 2026-07-04 evaluation — 8 TRDDs for the open shortcomings (993936a)
- **trdd:** Board-reconciliation sweep steps 1+2 — close 12 shipped TRDDs, merge dup pair (TRDD-GB3Z9U9J) (26d02a9)
- **trdd:** TRDD-GB3Z9U9J complete — steps 3+4 done, issues #67/#70 closed with evidence (6f1e8c5)
- **trdd:** A8DRPZFM complete — safeguards shipped in 97e1ed2 (7a54eea)
- **trdd:** Add DILR8G11 (meter double-count, completed) + YXY992BN (token-waste origin attribution, planned) (eadfe55)
- **wikimem:** Canonical key placement — top-level ocd/lmd, metadata-or-top tier, no bare-grep presence checks (issue #68 P4, TRDD-UENXDA8P) (2f6063b)
- **trdd:** UENXDA8P complete — issue #68 all four items resolved (0c0f64d, 6a1c04b, 2f6063b; P2 was #50) (dcd35d1)
- **trdd:** YF4NDYYE complete — freshness helper shipped in 0146d9d (cc01e96)
- **trdd:** LCO8229M complete — reports-purge shipped in 79957c7 (9a0427e)
- **trdd:** 1T53EKTN complete — S6+S7 shipped in 3e1f107 (0ad08e3)
- **trdd:** 7IUTRX29 complete — S3+S4 shipped in aa789c7; audit report in reports/trdd-7IUTRX29/ (90558ec)
- Daemon-state canonical home is the plugin DATA dir (TRDD-2U8AH82F) (efaed0f)
- **trdd:** 2U8AH82F complete (ba58ebb + docs); add EHT TRDD-ULEGRT01 — retire legacy fallback 2 releases out (213c0f8)
- **wikimem:** M1 mirrors — detector docstring + CLAUDE.md say Sonnet, not opus (632bb67)
- **trdd:** 56d24c02 increment 2 wired — record USER approval + substring-gate lesson (aca7c0f)
- **trdd:** 3XS3PDCF — record repair/atomize prechecks shipped (50ff80f)
- **wikimem:** Sync the shipped recall rule + memgrep SKILL with the full command surface (wikimem audit runtime F17) (a2b7bdd)
- Add TRDD-82OP4EN9 — night-continuity hardening (maintenance mode guarantees unattended work) (f826322)
- **trdd:** 82OP4EN9 STATE — W1-W4 landed, next action publish+arm (95a4889)

### Features

- **tests:** Session-default state isolation + real-state write guard + frozen-home-path guard (TRDD-A8DRPZFM) (97e1ed2)
- **memory-cli:** Is-due / mark-ran cadence verbs (issue #68 P1, TRDD-UENXDA8P) (0c0f64d)
- **freshness:** Plugin-freshness helper — verify cached-vs-live before cache-based audits (issue #69, TRDD-YF4NDYYE) (0146d9d)
- **cleanup:** Reports-purge detector — 30d reports/ retention + seen-file line caps (S8, TRDD-LCO8229M) (79957c7)
- **guard:** S6 unkillable-runaway alert + S7 dual disk metric (TRDD-1T53EKTN) (3e1f107)
- **boundedness:** S3+S4 audit — structural log rotation + AuditChain trim-anchor (TRDD-7IUTRX29) (aa789c7)
- **daemon:** Staged global-state migration → plugin DATA dir (TRDD-2U8AH82F) (ba58ebb)
- **wikimem-skills:** Frequency get/set commands for repair, harvest, atomize (wikimem audit skills M8) (435aeeb)
- **daemon:** Wire A5 hard-restart rungs into session-liveness — DEFAULT-OFF (TRDD-56d24c02) (ef24608)
- **memory:** Repair/atomize content-prechecks (TRDD-3XS3PDCF) (c065959)
- **wikimem:** Curated-page home renamed wiki/ -> wikimem/ + L-1 curated-shape fix (USER decision 2026-07-08) (fc650bc)
- **heartbeat:** Slim cron prompt to a 356-char stub; marker protocol ships as an installed rule (TRDD-82OP4EN9 W3) (88e0095)
- **continuity:** Pending-agents manifest — deterministic fork resume after a kill (TRDD-82OP4EN9 W1+W4) (73af35e)
- **continuity:** SessionStart cron-liveness nudge (TRDD-82OP4EN9 W2) (3515aa6)

### Miscellaneous Tasks

- **pytest:** Pin testpaths=tests — bare pytest was collecting downloads_dev foreign projects (73d3333)

### Refactor

- **consolidate-skill:** Move steps 6-9 executable sequence to the merge-protocol reference (CPV 5000-token cap, TRDD-82OP4EN9) (7cd2127)
- **write-skill:** Move worked examples to references/write-examples.md (CPV 5000-token cap, TRDD-82OP4EN9) (d8d8dda)

### Testing

- **user-mem:** Shared tree-built memgrep resolver in conftest (F13 follow-on) (9ce5a24)
## [0.31.0] — 2026-07-03

### Documentation

- **trdd:** ZNN0UK5K records the completed fseventsd safeguards plan (disk findings + S1-S8) + S9 shipped v0.30.0 (TRDD-ZNN0UK5K) (a2d3dc5)

### Features

- **hooks:** Retire S9 Bash-output-cap hook — adopt native BASH_MAX_OUTPUT_LENGTH (TRDD-ZNN0UK5K) (e07fc31)
## [0.30.0] — 2026-07-03

### Bug Fixes

- **review:** Compaction-id regexes, slug SSOT, daemon knobs, wedge-kill match, stale locks (TRDD-E9LMBNPE) (0d8a521)
- **review:** Wave 2 — schedule token-usage-anomaly, maintenance-wins arm nudge, specific pane match, AWS exfil regex (TRDD-E9LMBNPE) (31c4c39)
- **cache:** Suppress repeat token-budget nudges + Phase-4 audit verdicts (TRDD-4MMXTJFB) (bb8a4b2)
- **review:** Wave 3 — dead v2 STATE injector, 3 zero-division knobs, id-case corruption, perpetual map-drift false nudge, 2 context-flooding skill blocks (TRDD-4MMXTJFB) (0aaedf4)
- **keepalive:** Bound L0-keepalive restage churn + isolate its tests from real state (TRDD-ZNN0UK5K) (33ef7eb)

### Documentation

- **trdd:** Mark 0NRVNDSZ published in v0.29.1 (window-aligned + subagent-recursive attribution) (ae6beb2)
- **trdd:** E9LMBNPE review-fix batch complete — waves 1+2 recorded, awaiting next release (af9f9c9)
- **trdd:** 4MMXTJFB records wave 3 — 9 token-waste review fixes ride the release (TRDD-4MMXTJFB) (5c41611)
- **trdd:** Clear MD004 NIT in 4MMXTJFB + add 2KQQAEPP github-issues-watch spec (cb8e96a)
- **trdd:** ZNN0UK5K — fseventsd 39GB runaway root-caused to L0-keepalive restage churn (TRDD-ZNN0UK5K) (fbc1b24)
- **memory+trdd:** Fseventsd/keepalive test-isolation lessons + record the 4× recheck (TRDD-ZNN0UK5K) (d284970)
- **trdd:** ZNN0UK5K permanent solution complete — A(test isolation)+B(bounded restage), FIX C already shipped (ThrottleInterval=30); file HK7IZ21Z runaway-detector EHT (TRDD-ZNN0UK5K) (7dd0dac)

### Features

- **token:** Per-category accounting + --window 5h|7d selectors + terminal graphs (TRDD-4MMXTJFB) (b795aaf)
- **hooks:** Opt-in PostToolUse hook to cap Bash output + protect context (TRDD-ZNN0UK5K) (96bf8a4)
- **hooks:** Exempt token-saving tools (tldr/distill/lean-ctx) from the Bash-output cap (TRDD-ZNN0UK5K) (21661b4)

### Testing

- **autorecall:** Fix over-broad user-mem privacy assertion (fixture-path collision) (24c01cc)
- **memory:** Sync 2 divergent _slug helpers to the SSOT (project_slug non-alnum dashing) (4dab388)
- **token:** Update source-breakdown test for real 4-category shares (TRDD-4MMXTJFB) (8ef5eb6)
## [0.29.1] — 2026-07-02

### Bug Fixes

- **attribution:** Count subagent transcripts + exact-interval query + local-tz bounds (TRDD-0NRVNDSZ) (173cabf)

### Features

- **attribution:** Window-ALIGNED 5h/7d sums — bounds from resets_at, not trailing (TRDD-0NRVNDSZ) (f5d6e2e)
## [0.29.0] — 2026-07-02

### Bug Fixes

- **rotator:** Test log-isolation + bootstrap fixture-account guard (TRDD-56374Z36) (028409f)
- **dispatch:** Maintenance mode respawns a dead daemon — survival ops survive maintenance (TRDD-8PH8YOIJ) (bffd533)
- **attribution:** Culprit min_share 0.2 -> 0.1 — validated on the first real fleet run (TRDD-OY0W6LX5) (391f1aa)
- **detector:** Make window-burn-rate.py executable (TRDD-OY0W6LX5) (e2a5c22)
- **publish-gate:** Devitalize SHELL_EXEC FP shape + MD004 prose wrap (TRDD-OY0W6LX5) (ba01603)
- **attribution:** Dedupe transcript usage by message.id — kill the 1.5-2.1x over-count (TRDD-OY0W6LX5) (10471c2)
- **publish-gate:** Pyright narrowing in dedupe + markdownlint config drift (TRDD-OY0W6LX5) (605bc28)

### Documentation

- **trdd:** Add OY0W6LX5 — window burn-rate early-exhaustion alarm (proposal, Tier-3) (46b282d)
- **trdd:** OY0W6LX5 — reframe around FLEET ATTRIBUTION (which project over-consumes) + spike-source; burn-rate is the trigger (48e2d3b)
- **trdd:** OY0W6LX5 approved (USER 'go', tier 3) — usage payload confirmed (resets_at both windows; live 7d burn 1.53x); column dev (db45fe0)
- **trdd:** Add 56374Z36 (rotator test log-isolation leak + bootstrap guard) + 8PH8YOIJ (maintenance survival gap) — USER-approved (3e06483)
- **trdd:** 56374Z36 — cite the TRDD-14IY6MAD precedent (v0.18.2 autouse log-redirect fixture); today's leak is the same class from the bootstrap test module (a36cb17)
- **trdd:** Add YRPUSIFY — cache-optimize hooks/agents/skills/rules (USER: 'immediately'); measured 7.6x cache rewrite factor + 160k/agent floor (2525dcb)
- **trdd:** Land OY0W6LX5/56374Z36/8PH8YOIJ complete + YRPUSIFY P1 commit recorded (e0fd76d)

### Features

- **tokens:** Fleet attribution + window burn-rate alarm (TRDD-OY0W6LX5) (a4d2ff7)

### Refactor

- **hooks:** Cache-stable injected text — bucketed counts, fixed templates (TRDD-YRPUSIFY P1) (5687848)
## [0.28.2] — 2026-07-02

### Bug Fixes

- **token-meter:** Kill the post-compact false runaway + predict the exact auto-compact point (TRDD-TKNSTP82) (a1b8f5f)

### Documentation

- **trdd:** Add TKNSTP82 — post-compact token false-alarm fix + never-stop maintenance nudge (v0.28.2) (98e7f60)
- **trdd:** Land TKNSTP82 — never-stop nudge (4a9749e) + token estimation (a1b8f5f); tested, column complete (0ab9491)

### Features

- **heartbeat:** Never-stop continue-nudge — maintenance + opt-in keep-going (TRDD-TKNSTP82) (4a9749e)
## [0.28.1] — 2026-07-02

### Bug Fixes

- **review:** Correct maintenance-mode + ci-status defects (TRDD-FPL60EKV, TRDD-AKH7JRAA) (690b7f4)
- **daemon:** Run OAuth keepalive under global maintenance (TRDD-FPL60EKV, code-review B3) (f71895a)
- **leanctx:** Resolve mypy no-redef on state — unblock publish gate (bf13fea)

### Documentation

- **memory:** Capture maintenance-mode in the architecture wikimem hub (TRDD-FPL60EKV) (1581fef)
- **trdd:** Close ME8V2YJF complete — fleet disarm/pause core (eeb4aa8) + ai-maestro/Linux channels #251 (1d057f2); DORMANT, tested, not pushed (budget freeze) (481ffdd)

### Features

- **fleet:** Wire ai-maestro CLI + Linux GUI recovery channels (TRDD-ME8V2YJF) (1d057f2)
## [0.28.0] — 2026-07-02

### Documentation

- **trdd:** Mark TRDD-FPL60EKV published in v0.27.0 (maintenance-mode) (4d246c7)

### Features

- **detector:** Ci-status — after a push, watch the commit's CI and notify the main Claude on failure (TRDD-AKH7JRAA) (25a1dee)
## [0.27.0] — 2026-07-02

### Documentation

- **trdd:** Mark TRDD-L87BQ2Y9 published in v0.26.1 (double-ESC self-trigger fix) (d4ab0d1)

### Features

- **heartbeat:** Maintenance-mode — cache-warm cheap fires between full and disarm (TRDD-FPL60EKV) (11458b5)
## [0.26.1] — 2026-07-01

### Bug Fixes

- **self-trigger:** Hard interrupt sends TWO ESCs — one clears the tool, one ends the turn (TRDD-L87BQ2Y9) (072e161)
## [0.26.0] — 2026-07-01

### Bug Fixes

- **publish:** Cache cargo target off the auto-purged macOS tempdir (clippy flake) (24a3b77)
- **cpv:** Tighten 3 skill descriptions <=200 tokens + clear skillaudit/markdownlint FPs (bc00a30)
- **cpv:** Trim janitor-reload-skills description under the 200-token limit (1681299)

### Documentation

- Add TRDD-LQU7OXXV — /janitor-compact-context --soft and --handoff flags + /janitor-write-handoff skill (69238b5)
- **trdd:** Add TRDD-GFT33HT9 — relocate USER memory out of the auto-deleted data dir (survives uninstall) (cda0dd7)
- **trdd:** Standardize TRDD-ME8V2YJF list markers to clear CPV MD004 NIT (TRDD-ME8V2YJF) (a63888c)

### Features

- **self-trigger:** --soft/--handoff compaction, /janitor-write-handoff, /reload-skills (0cfa0ef)
- **rules:** Disarm/uninstall inert-guard on shipped rules + provenance orphan cleanup (0e37b69)
- **memory:** USER memory survives uninstall via a synced backup mirror (TRDD-GFT33HT9) (7b8e252)
- **token-guard:** Real-time token-spike + cache-miss monitor with stop-the-subagents nudge (TRDD-KI24GR5Z) (ae578b7)
- **token-anomaly:** Adaptive per-5-min baseline + anomaly detector + 5h/7d window report (TRDD-EDSFEQ5C) (ae9ea63)
- **token-anomaly:** Log window-exhaustion events at rate-limits → empirical 5h/7d cap discovery (TRDD-EDSFEQ5C) (9666585)
- **fleet-stop:** Daemon-driven fleet disarm/pause — reach every armed session, no human (TRDD-ME8V2YJF) (eeb4aa8)
- **session-start:** Rich disarmed-state reminder — a temporary global stop can't silently persist (TRDD-3MEUT9VW) (9a4a16e)

### Miscellaneous Tasks

- Mark reload_skills_trigger.py executable (has shebang) (54e7029)
## [0.25.0] — 2026-06-30

### Bug Fixes

- **memory:** Autonomous wikimem curation OFF by default + curator off Opus (TRDD-KTP79T8P) (9d47e67)
- **global-disarm:** Silence per-session heartbeats, not just the daemon (TRDD-NJ22HNC3) (447bfcf)
- **oauth-rotator:** Gate auto-bootstrap browser behind opt-in + cap per-slot launches (TRDD-5OJX3SCF) (b35121c)
- **heartbeat:** Disarm/pause now DELETE the cron (self-disarm), not just silence (TRDD-RQ9FIFX6) (b3a60fd)
- Clear CPV skillaudit CROSS_TOOL_ACCESS false-positive blocking publish (7187e15)

### Documentation

- **trdd:** Mark 8UD3Q7K5 (v0.24.15) + TY2EZ8ZH (v0.24.16) published (26c125a)
- **trdd:** Record implementation commit ee26d69 for TRDD-ZGLCGC6A (f291558)
- **trdd:** Record implementation commit 3f76b65 for TRDD-SMZFJVZ3 (a260bd4)
- Add TRDD-5OJX3SCF — OAuth auto-bootstrap surprise-browser + uncapped relaunch fix (d75e3e5)
- **trdd:** Mark TRDD-5OJX3SCF complete + record implementation commit b35121c (47b2926)
- Add TRDD-RQ9FIFX6 — disarm must STOP the heartbeat fire, not just silence (4181746)
- **heartbeat:** Document disarm/pause self-disarm semantics (TRDD-RQ9FIFX6) (238e6df)
- Mark TRDD-RQ9FIFX6 complete + record implementation commit b3a60fd (9798892)
- Add TRDD-ME8V2YJF — daemon-driven fleet disarm/pause (janitor controls all sessions itself, no human) (a09aa61)

### Features

- **session-start:** Self-heal lean-ctx shell allowlist additively (TRDD-ZGLCGC6A) (ee26d69)
- **context-guard:** Default-ON context-size runaway guard + enforce near cap (TRDD-SMZFJVZ3) (3f76b65)

### Testing

- **context-guard:** Repair orphaned pre-rewrite tests (TRDD-SMZFJVZ3 follow-up) (c7cacb4)
## [0.24.16] — 2026-06-25

### Bug Fixes

- **trdd:** Standardize TY2EZ8ZH list markers — MD004 NIT blocked publish ([#244](https://github.com/Emasoft/ai-maestro-janitor/issues/244)) (7321470)

### Documentation

- **trdd:** Add TRDD-TY2EZ8ZH — throttle daemon marketplace-refresh to low CPU+IO priority ([#244](https://github.com/Emasoft/ai-maestro-janitor/issues/244)) (22fc199)
- **trdd:** Record implementation commit ca0198e for TRDD-TY2EZ8ZH ([#244](https://github.com/Emasoft/ai-maestro-janitor/issues/244)) (4bfeaf7)

### Features

- **daemon:** Throttle marketplace-refresh to low CPU+IO priority ([#244](https://github.com/Emasoft/ai-maestro-janitor/issues/244)) (ca0198e)
## [0.24.15] — 2026-06-25

### Bug Fixes

- **memory:** Cheap structural precheck stops consolidate no-op agent spawns ([#64](https://github.com/Emasoft/ai-maestro-janitor/issues/64)) (636e7df)

### Documentation

- **trdd:** Add TRDD-8UD3Q7K5 — consolidate structural precheck to kill ~226k no-op spawns ([#64](https://github.com/Emasoft/ai-maestro-janitor/issues/64)) (d549553)
- **trdd:** TRDD-8UD3Q7K5 STATE — consolidate structural precheck implemented + tested (636e7df) ([#64](https://github.com/Emasoft/ai-maestro-janitor/issues/64)) (c8f1cb7)
## [0.24.14] — 2026-06-25

### Bug Fixes

- **report-to-trdd:** Stop nagging memory-curator abstain/no-op reports ([#63](https://github.com/Emasoft/ai-maestro-janitor/issues/63)) (172dc06)
## [0.24.13] — 2026-06-25

### Bug Fixes

- **pre-compact-handoff:** Discover git root in subdir-repo layouts ([#66](https://github.com/Emasoft/ai-maestro-janitor/issues/66)) (d9fcf4c)

### Documentation

- **trdd:** TRDD-6F7F7D60 -> published v0.24.12 (a2f5936)
## [0.24.12] — 2026-06-25

### Bug Fixes

- **detector:** Stop trdd-reconciliation false-flagging code-tag/terminal TRDDs ([#65](https://github.com/Emasoft/ai-maestro-janitor/issues/65)) (256aa2e)

### Documentation

- **changelog:** Record CC v2.1.170-191 compat audit + 2.1.183 heartbeat note (TRDD-6F7F7D60) (463426e)
## [0.24.11] — 2026-06-25

### Documentation

- **trdd:** TRDD-7C787DUS published v0.24.10 -- doc-commit false-shipped fix shipped (00a676f)

### Miscellaneous Tasks

- Bound release-class workflows with timeout-minutes ([#243](https://github.com/Emasoft/ai-maestro-janitor/issues/243)) (a32914b)
## [0.24.10] — 2026-06-25

### Bug Fixes

- **detector:** Exclude a TRDD's own design-only commits from the shipped check (TRDD-7C787DUS) (1279054)

### Documentation

- **trdd:** Close TRDD-15ECPBSA -- reconciliation detector published v0.24.9 (9e7218e)
- **trdd:** Add TRDD-7C787DUS -- reconciliation detector counts a TRDD's own spec commit as shipped (d63aaca)
- **trdd:** TRDD-7C787DUS implemented + tested (column complete) -- publish held on transit (e81c064)
## [0.24.9] — 2026-06-25

### Bug Fixes

- **detector:** Exclude terminal TRDDs from trdd-reconciliation Check 3 (TRDD-15ECPBSA) (5602d92)
## [0.24.8] — 2026-06-25

### Bug Fixes

- **detector:** Scope trdd-reconciliation Check 2 done-marker to the NEXT-ACTION line (TRDD-15ECPBSA) (708d198)
## [0.24.7] — 2026-06-25

### Documentation

- **memory:** Capture the markdownlint MD004 +-wrap publish-gate trap (janitor-publish-pipeline) (5dcd9f7)
- **trdd:** Close TRDD-3b9b2040 -> published (atom engine Phase g complete + shipped) (a7f46cf)
- **trdd:** Add TRDD-15ECPBSA -- TRDD state-reconciliation detector (board-drift prevention) (2454e26)

### Features

- **detector:** Trdd-state-reconciliation -- surface shipped-but-open board drift (TRDD-15ECPBSA) (bf95575)
## [0.24.6] — 2026-06-25

### Documentation

- **trdd:** TRDD-WQAJZ5V6 → published (v0.24.5, CI green, no flake this run) (3eeb569)

### Refactor

- **memory:** SSOT note-filter + close consolidate user-mem privacy gap (TRDD-87935f21) (6e96960)
## [0.24.5] — 2026-06-25

### Documentation

- **trdd:** TRDD-056384eb → published (v0.24.4) (1b62665)
- **trdd:** TRDD-056384eb — v0.24.4 CI green (flaky CPV REPO-LINT hang cleared on re-run) (81f045f)

### Miscellaneous Tasks

- Retry CPV validate up to 3x on the flaky REPO-LINT hang (TRDD-WQAJZ5V6) (e63e4b8)
## [0.24.4] — 2026-06-25

### Documentation

- **trdd:** TRDD-786efe85 → published (v0.24.3, commit f227c2d) (8f5a1f6)
- **trdd:** Add TRDD-056384eb — atom desc slug field (memgrep + handoff one-line summary) (77508d6)
- **memory:** Document + author the atom `desc` slug field (TRDD-056384eb Phases 3+4) (734c807)
- **trdd:** TRDD-056384eb → complete — atom desc field Phases 1-4 done (6bc1a27)

### Features

- **memgrep:** Atom `desc` slug field — one-line summary in recall (TRDD-056384eb) (7f1f980)
- **precompact:** Handoff shows atom `desc` one-line summary (TRDD-056384eb Phase 2) (7d7135b)
## [0.24.3] — 2026-06-25

### Documentation

- **trdd:** Night-brain STATE — record v0.24.2 (README immortality docs) + the cpv-remote-validate CI flake (a9c0cc3)
- **trdd:** Reconcile board (2 of 9) — 31095269->published, ce195129->complete (e3d5472)
- **trdd:** Reconcile board (5 of 9) — c77dae09/bc16d602/a4e41e89 -> published (b161468)
- **trdd:** Reconcile board (9 of 9) — a6d2fdaf/c1b0affc/5858ad0b/378c85da -> published (2964d60)
- **trdd:** Night-brain STATE — v0.24.2 CI Validate flake RESOLVED (re-run green) (e808bd7)
- **trdd:** Add TRDD-786efe85 — PreCompact handoff carries last N verbatim turns (3fe42c1)

### Features

- **precompact:** Handoff carries recent verbatim turns + recent memory ids (TRDD-786efe85) (f227c2d)
## [0.24.2] — 2026-06-25

### Documentation

- Night-brain STATE → IMMORTALITY COMPLETE milestone + capture the KEEPQRTN cross-group lesson (e155036)
- **readme:** Add Immortality (self-healing daemon) section — document the v0.21-24.1 architecture (fe69927)
## [0.24.1] — 2026-06-25

### Bug Fixes

- **keepalive:** Extend C4 auto-rollback to the daemon/L0 path — quarantine-aware keepalive + OS-respawn crash signal (TRDD-KEEPQRTN) (e67244b)

### Documentation

- **trdd:** TRDD-KEEPQRTN — extend C4 auto-rollback to the daemon/L0 keepalive path (final-review HIGH) (ca55266)

### Miscellaneous Tasks

- **map:** Refresh CLAUDE.md project-map digest — KEEPQRTN (keepalive quarantine-aware + spawn-attempt) (bced947)
## [0.24.0] — 2026-06-25

### Documentation

- **trdd:** Umbrella STATE refresh (A/B/C/D done, v0.21-23 CI-green) + TRDD-F3AUDLOG (F3 recovery audit log) (84074c5)

### Features

- **fleet:** Immortality F3 — tamper-evident recovery audit log + F2 dashboard augments (TRDD-F3AUDLOG) (d5accac)

### Miscellaneous Tasks

- **map:** Refresh CLAUDE.md project-map digest — recovery_audit module (F3) (f26ab4a)
## [0.23.0] — 2026-06-25

### Bug Fixes

- **self-integrity:** Resolve detector key + audit chain via the FIXED janitor dir, not $CLAUDE_PLUGIN_DATA (TRDD-DKEYCHN7) (a0f6777)

### Documentation

- **trdd:** TRDD-DKEYCHN7 — track detector key+chain $CLAUDE_PLUGIN_DATA foot-gun (C3/C4 review INFO) (2ff54a7)
- **trdd:** TRDD-DGROUPAB — GROUP D scope (ship only D-alpha + D-beta; ~85% already covered) (f9be3f3)

### Features

- **keepalive:** GROUP D — interpreter fallback (D-alpha) + verify-or-restage gate (D-beta) (TRDD-DGROUPAB) (2b2a996)

### Miscellaneous Tasks

- **map:** Refresh CLAUDE.md project-map digest — keepalive_boot module (GROUP D D-beta) (b15d90a)

### Testing

- **stub:** Constant-parity guard for the C3 trust-anchor paths (TRDD-T198DT1W, NIT-1) (2c18a5e)
## [0.22.0] — 2026-06-25

### Bug Fixes

- **skill:** Tighten janitor-memory-bootstrap description under the 200-token limit (TRDD-ab232dbd) (bfdc2b8)

### Features

- **dispatch:** GROUP C C4 — bad-self-update crash-loop auto-rollback (TRDD-T198DT1W) (63ae1c5)
- **memory:** MEMORY.md⇄Wikimem coexistence harvest (TRDD-ab232dbd) (041b136)

### Miscellaneous Tasks

- **map:** Refresh CLAUDE.md project-map digest (project-map-drift nudge) (cbf5426)
## [0.21.0] — 2026-06-25

### Bug Fixes

- **oauth:** Reset refresh_failures=0 on a successful cmd_auto refresh (TRDD-HJGR4I5W) (9cf894a)
- **trdd:** MD004 ul-style — rephrase a '+ '-prefixed wrapped line in fe45babc STATE (TRDD-fe45babc) (d1f0ea8)

### Documentation

- **trdd:** Resolve TRDD-e247a349 → complete (trdd-drift: 14d stale in dev) (e01bbed)
- **trdd:** Night-brain STATE — bring fe45babc current (TRDD-fe45babc) (b7086d0)

### Features

- **memory:** Scope-migration classifier — Phase 1 of the corpus-migration helper (TRDD-47df698b) (4aa8613)
- **stub:** GROUP C C3 — pin-last-good + quarantine-bad-version (TRDD-T198DT1W) (e6a6d93)
- **hooks:** PreCompact ground-truth handoff — anti-hallucination resume (TRDD-7DVNHLOP) (6a060c4)

### Miscellaneous Tasks

- **map:** Refresh CLAUDE.md project-map digest (project-map-drift nudge) (2da0614)
## [0.20.1] — 2026-06-24

### Bug Fixes

- **oauth:** Recheck refinements on the v0.20.0 wrapper fold (TRDD-3T4DZWXA) (7dd1536)

### Documentation

- **trdd:** TRDD-3T4DZWXA published in v0.20.0 — record skill→command resolution (0f22fea)

### Miscellaneous Tasks

- **map:** Refresh CLAUDE.md project-map digest (project-map-drift nudge) (633c59a)
## [0.20.0] — 2026-06-24

### Documentation

- **memory:** OAuth wikimem — agent-browser RENEW driver, dead-refresh→cookie routing, REAUTH passkey decision, janitor OAuth command list (TRDD-J9TM3WQK) (b4e64e9)
- Add TRDD-3T4DZWXA — complete the rotator fold (user-scope OAuth wrapper → plugin) (5b9ed39)

### Features

- **oauth:** Fold the rotator's user-scope REAUTH wrapper into the plugin (TRDD-3T4DZWXA) (2a87a03)
## [0.19.1] — 2026-06-24

### Bug Fixes

- **oauth:** Dead-refresh + live-cookie alternate → RENEW_COOKIE, not REAUTH (TRDD-J9TM3WQK) (0acd523)
## [0.19.0] — 2026-06-24

### Bug Fixes

- **trdd:** MD004 ul-style — unwrap two prose lines starting with '+ ' (unblocks publish) (f68e16f)

### Documentation

- **memory:** Record the detector state-divergence + test-log-pollution lessons (TRDD-5EUYV08H, TRDD-14IY6MAD) (4850573)
- **trdd:** Night-brain STATE — OAuth triad COMPLETE + shipped v0.18.1/2/3, hold is over (TRDD-fe45babc) (2569e27)
- **trdd:** Design GROUP C exec-path — verify-before-exec/quarantine/rollback, fail-open cardinal rule (TRDD-T198DT1W) (e9ff072)
- **map:** Refresh CLAUDE.md project map (project-map-drift nudge) (a7a9ccb)
- **trdd:** GROUP C design — add the stub-not-auto-rolling rollout caveat (TRDD-T198DT1W) (9abe0d1)
- **trdd:** T198DT1W — record C2 self-review channel nuance for the C3 author (fe7bc70)
- **trdd:** Night-brain STATE — GROUP C C2 implemented + committed (9773ff3), phased checkpoint before C3 (2bd0980)

### Features

- **stub:** GROUP C C2 — verify-before-exec gate in dispatcher-stub (TRDD-T198DT1W) (9773ff3)
## [0.18.3] — 2026-06-24

### Bug Fixes

- **rotator:** Oauth detectors must read the daemon's canonical state, not a stale legacy one (TRDD-5EUYV08H) (66c11fe)
## [0.18.2] — 2026-06-24

### Testing

- **rotator:** Isolate ROOT/LOG_FILE to tmp so the suite stops polluting the production rotator.log (TRDD-14IY6MAD) (cb29e89)
## [0.18.1] — 2026-06-24

### Bug Fixes

- **rotator:** Refresh-retry a locally-expired alternate before excluding it (TRDD-1IKF0A6D) (46da1ba)

### Documentation

- **trdd:** L0 keepalive published (v0.18.0) + night-brain TIER-1-complete/wind-down (TRDD-71ABD7V7, TRDD-fe45babc) (8a35a25)
- **trdd:** GROUP C C1 self-integrity manifest SHIPPED in v0.18.0 (TRDD-53a00e44) (573fdbd)
- **memory:** Add the L0-L3 immortality model to the architecture hub (TRDD-324223a6) (cb0ea25)
- **repomap:** Refresh CLAUDE.md project map for the v0.18.0 immortality files (0c32340)
- **trdd:** Scheduler cheap content-precheck to kill ~240k no-op memory spawns (TRDD-3XS3PDCF) (727af59)
- **trdd:** Night-brain STATE — resume after wind-down, 6 pieces committed (TRDD-fe45babc) (cf3f584)
- **trdd:** Night-brain STATE — 3XS3PDCF split content-precheck landed (441d467), still holding (b816eb1)
- **trdd:** Harvest precheck is BLOCKED on in-flux harvest behavior, not merely deferred (TRDD-3XS3PDCF) (3d68f13)
- **map:** Refresh CLAUDE.md project map — add memory_content_precheck module (cc4e910)
- **trdd:** Correct 3XS3PDCF publish-deferral WHY — release-risk, not budget (TRDD-3XS3PDCF) (f5c8b2b)
- **trdd:** Add TRDD-1IKF0A6D — cmd_auto refresh-retry locally-expired alternate (RENEW residual) (5986558)

### Performance

- **memory:** Split content-precheck so a cadence-due-but-empty scheduler no longer spawns a 240k no-op agent (TRDD-3XS3PDCF) (441d467)
## [0.18.0] — 2026-06-24

### Bug Fixes

- **l0:** Executable installer + blocking-flock no-churn for the keepalive daemon (TRDD-71ABD7V7 Phase 3b) (8d2cb64)

### Features

- **l0:** SHAPE-2 OS-keepalive installer + token-free orchestrator (TRDD-71ABD7V7 Phase 2b) (0c8929d)
- **l0:** Wire OS-keepalive into the daemon lifecycle + fix restart-loop (TRDD-71ABD7V7 Phase 3) (40c473c)
## [0.17.3] — 2026-06-24

### Bug Fixes

- **memory:** Remove the agent-side cadence double-gate from atomize/conflict/repair (TRDD-VJ8L465M) (29c9eea)
- **oauth:** Escalate a dead-but-present refresh token to the REAUTH nudge (TRDD-HJGR4I5W) (bc7ccab)

### Documentation

- **trdd:** Night-brain STATE — v0.17.2 shipped (memory-settings deviation-filter) (30566d7)
- **trdd:** Add TRDD-71ABD7V7 — L0 keepalive as fixed DATA-path scanned entry (SHAPE 2) (7b67acf)
- **trdd:** TRDD-71ABD7V7 → dev; Phase 1 shipped (184b61c) (914b3e4)
- **trdd:** TRDD-71ABD7V7 — Phase 2a shipped (closure-stager 0345000) (85bae21)
- **trdd:** TRDD-HJGR4I5W — OAuth cascade gap, dead-but-present refresh never escalates to REAUTH (70b29e8)
- **trdd:** Night-brain STATE — L0 SHAPE 2 Phases 1+2a + OAuth gap (TRDD-fe45babc) (41828bf)
- **trdd:** Correct stale L0 Phase-2b file refs — old launchd files already removed (TRDD-71ABD7V7) (6875ffc)
- **trdd:** Memory scheduler double-gates the cadence stamp → no-op spawns (TRDD-VJ8L465M) (92bc24d)
- **trdd:** Night-brain — USER mandate to finish + harden (CPV #152 live, L0 unblocked) (TRDD-fe45babc) (0674bc3)
- **trdd:** Clear MD004 lint NIT in the VJ8L465M TRDD (unblock publish --strict) (56db5ca)

### Features

- **keepalive:** Add L0 daemon_keepalive_entry — thin static-import entry (TRDD-71ABD7V7) (184b61c)
- **keepalive:** Add closure-stager for the L0 DATA mirror (TRDD-71ABD7V7) (0345000)
## [0.17.2] — 2026-06-23

### Bug Fixes

- **memory:** Persist only setting deviations so a default-raise isn't masked (TRDD-378c85da) (552d925)

### Documentation

- **trdd:** Night-brain STATE — v0.17.1 shipped, #56+#61 closed, queue clear except blocked #52 (0f9bd7a)
## [0.17.1] — 2026-06-23

### Bug Fixes

- **memory-repair:** Normalize nested ocd/lmd → top-level ([#56](https://github.com/Emasoft/ai-maestro-janitor/issues/56)) (ced38b4)

### Documentation

- **trdd:** TRDD-f12cae1a → published (v0.17.0) (1dd1e95)
- **trdd:** Night-brain STATE — v0.17.0 PUBLISHED, CI green, security agent shipped (TRDD-fe45babc) (ee53827)
- **security-agent:** Add dispatch examples (clears CPV trigger-quality WARNING) (7433d35)
- **trdd:** Reconcile 2 stale testing TRDDs → complete (#61 weekly-audit drift) (7d81cf3)
## [0.17.0] — 2026-06-23

### Bug Fixes

- **security:** Clear CPV --strict on the new security agent (TRDD-f12cae1a) (95984d6)
- **publish:** Escape '#NN'-leading CHANGELOG bullets — git-cliff postprocessor for MD018 (2df36fe)

### Documentation

- **trdd:** Night-brain STATE — v0.16.0 PUBLISHED, blocker resolved, 8 issues closed (TRDD-fe45babc) (c5f159d)
- Add TRDD-f12cae1a — janitor-security-agent (one agent, detect+fix, heartbeat-suggested) (a917f98)

### Features

- **security:** Janitor-security-agent — ONE agent for all security skills, detect+fix, heartbeat-suggested (TRDD-f12cae1a) (e35cff2)
## [0.16.0] — 2026-06-23

### Bug Fixes

- **watchdog:** An ACTIVE session is never flagged broken (false-positive guard) (a60c41a)
- **watchdog:** ITerm TTY resolution — literal '|' delimiter, not the broken tab constant (831c9e3)
- **memory-librarian:** Stop false page-shape + MEMORY.md-sync findings (#54, #55) (42099f5)
- **trdd-reminder:** Exclude parked columns + age from created, not mtime ([#59](https://github.com/Emasoft/ai-maestro-janitor/issues/59)) (903e293)
- **memory-scope-leak:** GitHub action@sha pin is not a machine-host ([#53](https://github.com/Emasoft/ai-maestro-janitor/issues/53)) (d0eaeb9)
- **cpv:** Allowlist by-design persistence + sanitizer-unicode FPs; fix agent ref path (e36e18f)
- **cpv:** Trim split/record-recent skills under token caps + markdownlint ignore for internal docs (04ab8a5)
- **cpv:** Prune self-inflicted injection FPs + record the v0.16.0 publish blocker (30698b4)
- **memgrep:** Notes/lessons/see-also are PER-ATOM — recall aggregates the full atom record (TRDD-3b9b2040) (3a235cd)
- **trdd-reminder:** Show idle+age label, both metrics + first test ([#59](https://github.com/Emasoft/ai-maestro-janitor/issues/59)) (8a3b3a1)
- **memory-docs:** Clear MD004 false-positive in wikimem-model.md (unblock publish lint gate) (b03208d)
- **memory:** Quote two frontmatter descriptions that broke YAML parsing (CPV CRITICAL) (9b09f34)
- **memory:** Trim two over-cap descriptions under the CPV token limits (MAJOR) (254f38f)
- **memgrep:** Devitalize the ATOM_PAGE test-fixture RESOURCE_ABUSE CPV false-positive (608ceb7)
- **immortal:** Extract GROUP B launchd L0 OS-keepalive from the published plugin (eb109fb)
- **cpv:** Clear the MAJOR/MINOR/NIT debt blocking publish (post-L0-extraction) (5c380a0)
- **cpv:** Give atom-authoring.md a TOC + embed it in write SKILL (clear last NIT) (b64d1e5)

### Documentation

- **trdd:** Add TRDD-dccb0b8a — daemon session-liveness watchdog (out-of-session freeze recovery) (b4e18c5)
- **trdd:** Add TRDD-324223a6 — immortal janitor (layered self-resurrection + fault matrix) (072fc38)
- **trdd:** A3+A2 operational — record the working recovery loop (TRDD-324223a6) (9a63e0c)
- **trdd:** GROUP B done + audited — A+B operational immortality (TRDD-324223a6) (c477f84)
- Control-command matrix + Wikimem terminology (TRDD-a3fa4d5d) (1073626)
- **trdd:** TRDD-a3fa4d5d complete — control matrix + Wikimem record shipped (committed, not pushed) (35d0bd1)
- **trdd:** Autonomous overnight session brain (TRDD-fe45babc) (3af73f5)
- **trdd:** Night-brain — #54+#55 done, budget reality, inline-only (TRDD-fe45babc) (be8566d)
- **trdd:** Night-brain — #59 done, weekly-wall near, post-reset plan (TRDD-fe45babc) (6099d58)
- **trdd:** #56 decision (top-level ocd/lmd canonical) + fix pointer (TRDD-fe45babc) (f9a2070)
- **trdd:** Night-brain — #53 done, budget exhausted, post-reset publish plan (TRDD-fe45babc) (2954c72)
- **memory-rule:** Leave editorial work to the janitor subconscious agent (#58, #60) (aac974f)
- **trdd:** Adopt the-skills-menu progressive-discovery architecture — backburner (TRDD-cf15d412) (6476c16)
- **trdd:** Record #56 root-cause refinement + budget-restored hold state (4795d69)
- **memory:** Capture the CPV never-exempt policy lesson (the v0.16.0 re-block) (523532c)
- **trdd:** Policy resolves the publish decision to (b) — separate the release (def8c26)
- **trdd:** Add TRDD-ab232dbd — MEMORY.md buffer ⇄ Wikimem coexistence (harvest-mirror) (5e6ebfd)
- **trdd:** Record memory-coexistence architecture — separate wiki/ namespace, forward-only (TRDD-ab232dbd) (1f75d8f)
- **trdd:** Atom-indexing redesign — wikimem atoms as first-class index elements (TRDD-3b9b2040) (49447cd)
- **trdd:** Night-brain — record memory-redesign pivot + fresh budget (TRDD-fe45babc) (f253d93)
- **trdd:** Add verified atom-indexing blueprint — mirror the lesson-row precedent (TRDD-3b9b2040) (76cd06e)
- **memory:** Document the atom contract — block-properties, atom recall, find-claude-mem-ref — Phase E foundations (TRDD-3b9b2040) (a3bd5a4)
- **memory:** Teach atom authoring + atom recall in the write/recall skills (TRDD-3b9b2040) (0d96b99)
- **trdd:** Mark 3b9b2040 phases e+f done + record per-atom-notes correction (7778c30)
- **agent:** Make the ONE-memory-agent identity + dynamic single-skill loading explicit (7c62098)
- **trdd:** Record the USER's refined wikimem model (leading blocks, 4 element kinds, one agent) (5dc7e41)
- **trdd:** Overnight brain — wake 15:09, memory model refined+memorized, phase g held on USER confirm (6283bfd)
- **trdd:** Refine 3b9b2040 model — notes/lessons/see-also are markdown footnotes + shared-footnote move rule (4b80eef)
- **trdd:** 3b9b2040 phase g — g1 (leading parser) + g2 (footnote groups) DONE; g3-g6 remain (1e551b3)
- **atomize:** Leading markers + footnote-grouped see-also (TRDD-3b9b2040 phase g5) (64bd48f)
- **memory:** Align recall/write/memgrep/rule docs to leading+footnote-group model (TRDD-3b9b2040 phase g6) (f59f2ed)
- **trdd:** 3b9b2040 phase g — g4/g5/g6 DONE; only g3 (footnote-resolve verify) remains (141476a)
- **trdd:** Mark phase-g COMPLETE (g3 done) + record the publish blocker; clear MD004/MD053 (6b48ee2)
- **trdd:** Refresh overnight STATE — phase-g DONE supersedes the stale "HOLD"; clear MD004 (beb48fb)
- **trdd:** Clear MD004 +-prose-wrap NITs in immortal + control-commands TRDDs (6821a5e)
- **trdd:** Record GROUP C C1 (self-integrity manifest) landed; deferred remainder (88b29da)
- **trdd:** Accurately diagnose the publish blocker — option-b is dead (CPV #63 won't-fix) (f02b4d7)
- **trdd:** Record memgrep RESOURCE_ABUSE FP cleared (CPV MAJOR 6→5) (9b18565)
- **trdd:** Correct option-a scope — cd9c251 is entangled, so it's a forward-removal not a revert (1e3a5ad)
- **trdd:** Map the publish-blocker stakes — 8/11 open issues are fixed-but-unpublished (1e47d62)
- **trdd:** Record OAuth crunch (both accounts MAX) + #52 as the ready next-build (d7d4e54)

### Features

- **watchdog:** Session-liveness detection core — pure, tested (TRDD-dccb0b8a Phase 1) (12d8ded)
- **watchdog:** Session records its terminal identity for the daemon (TRDD-dccb0b8a NPT) (172dc2e)
- **watchdog:** Full 7-rung recovery ladder + crash-loop guard (TRDD-324223a6) (db61e39)
- **watchdog:** Fleet janitor-health diagnosis core (TRDD-324223a6) (506639f)
- **watchdog:** Fleet scanner — enumerate+diagnose every claude instance (TRDD-324223a6) (13ffac5)
- **status:** /janitor-show-global-status HTML fleet dashboard + transcript-signal fix (TRDD-324223a6) (ccdee58)
- **status:** Emoji/color legend + per-project TRDD kanban modal (TRDD-324223a6) (6d9e894)
- **status:** Tooltips on every icon/column/cell + readability styling (TRDD-324223a6) (4346261)
- **fleet:** A3 terminal-env-aware recovery injector (TRDD-324223a6) (b140f99)
- **status:** Kanban cards w/ uuid + copy buttons + TRDD-file markdown modal (TRDD-324223a6) (2877add)
- **daemon:** A2 fleet-guardian task — autonomous freeze recovery (TRDD-324223a6) (af708bb)
- **daemon:** GROUP B OS-keepalive — the daemon itself becomes immortal (TRDD-324223a6) (cd9c251)
- **fleet:** A5 nuclear recovery rungs — built INERT + default-OFF (TRDD-56d24c02) (74663b1)
- **janitor:** /janitor-stop — clean machine-wide STOP of the immortal daemon (TRDD-56d24c02) (27e0d68)
- **control:** Global-pause mechanism + global_control_cli (disarm/arm/pause/unpause) (TRDD-a3fa4d5d) (216d995)
- **skills:** Control-command surface (global disarm/arm/pause/unpause) + memory-record-recent (TRDD-a3fa4d5d) (720b065)
- **memory:** Janitor-memory-subconscious-agent — 3-tier Wikimem editorial architecture (TRDD-aebedbff) (619cedd)
- **memory-split:** Fail-safe seam synthesis — is_legal_split permits oversized seamless pages (#57, #58) (9ef9da1)
- **janitor-memory-split:** Fail-safe seam-synthesis recipe — seamless pages always converge (#57, #58) (a0f1fab)
- **memory:** Raise split_max_bytes 12k→36k + flow-style agent frontmatter (8cecaff)
- **memory:** Recall rule — MEMORY.md is the coexisting BUFFER, not a deprecated stub (TRDD-ab232dbd) (61ca557)
- **memgrep:** Add find-claude-mem-ref — the harvest provenance query (TRDD-ab232dbd) (4ebd891)
- **memory:** Wiki/ namespace resolver + buffer-vs-wiki discriminator (TRDD-ab232dbd) (5acdd8f)
- **memgrep:** Atom block-properties parser + resolver — Phase A1 of atom indexing (TRDD-3b9b2040) (e188fc8)
- **memgrep:** Atoms/atoms_fts index table + schema-v2 migration — Phase A2 (TRDD-3b9b2040) (ada9398)
- **memgrep:** Atom-level recall — atoms interleave with pages by score — Phase C (TRDD-3b9b2040) (9eb5161)
- **memgrep:** Find-claude-mem-ref reads the indexed atoms.claude_mem_ref column — Phase D (TRDD-3b9b2040) (054382a)
- **memory:** Janitor-memory-atomize pass — migrate free-prose pages into atoms (TRDD-3b9b2040 Phase f) (8ba718e)
- **memgrep:** Flip atom parser to LEADING block markers (TRDD-3b9b2040 phase g1) (a4e5d74)
- **memgrep:** Atom record groups footnotes by section — notes/lessons/see-also (TRDD-3b9b2040 phase g2) (3da1240)
- **memory:** Enforce the shared-footnote move-rule in verify_split/merge (TRDD-3b9b2040 g3) (7ace046)
- **self-integrity:** Ship the file-hash manifest as a per-release artifact (TRDD-53a00e44) (9d53bfb)

### Miscellaneous Tasks

- Set +x on fleet_status.py + global_control_cli.py per shebang-script convention (12ab07f)

### Refactor

- **fleet:** Rename recovery term "nuclear" → "hard-restart" (TRDD-56d24c02) (fbfff71)

### Testing

- **memory:** Cover the atomize marker in the scheduler tests + fix 6 regressions (bc01db7)
- **memgrep:** Flip the index test ATOM_PAGE to leading markers — completes g1 (TRDD-3b9b2040) (aadda1c)
- **memory-scope-leak:** Regression coverage for the #53 action-pin FP (09b8628)
- **trdd-reminder:** Fix test_trdd_detectors regression from the #59 label change (d2fe1d1)
## [0.15.0] — 2026-06-20

### Bug Fixes

- **reload:** Per-session reload nudge so concurrent/fleet sessions aren't starved (TRDD-a6d2fdaf) (4df60fc)
- **guard:** Drop required_linear_history from the baseline — it jams multi-agent merges (9fb8745)
- **oauth:** Degraded-rotate fallback + wider keepalive so token exhaustion never deadlocks (TRDD-a6d2fdaf) (8607d10)

### Documentation

- Add TRDD-a6d2fdaf — janitor plugin-update reliability (per-session reload + cache prune) (744fe97)
- **map:** Refresh CLAUDE.md project map — cache_prune + reload-generation + oauth degraded-rotate (29fa943)

### Features

- **daemon:** Cache-prune task — bound the plugin-cache bloat safely (TRDD-a6d2fdaf) (257b802)

### Miscellaneous Tasks

- **cpv:** Clear 6 fixable validation warnings — exec bits + skill terminating-conditions (6600854)
## [0.14.0] — 2026-06-20

### Bug Fixes

- **binary-magic-scanner:** Gate gzip findings on inner bytes; allowlist tokenizer vocab; skip pkg-cache ([#40](https://github.com/Emasoft/ai-maestro-janitor/issues/40)) (6d3d3bf)
- **rules-installer:** Content-exact idempotency so a same-size rule edit still refreshes ([#37](https://github.com/Emasoft/ai-maestro-janitor/issues/37)) (71b92fd)
- **memory-librarian:** Conflict needs a contradiction signal; aggregation skips coarse tags (#35, #38, #43) (351f12a)
- **terminal-trigger:** Repoint ai-maestro self-trigger to the shipped CLI, not the server API ([#42](https://github.com/Emasoft/ai-maestro-janitor/issues/42)) (ca76d9c)
- **docs:** De-poison MD004 — no wrapped prose line may start with '+ ' (25f906b)
- **daemon:** Install SIGTERM handlers before publishing the pid file (startup race) (4d39e3a)

### Documentation

- **trdd:** Memory-index re-architecture (A/B/C + overview + #49) SHIPPED in v0.13.0; gated re-enable remains (TRDD-a5780c23) (ae6c9b8)
- **memory:** Memory-system page — index is memgrep-only (MEMORY.md retired) + overview + harvest (TRDD-a5780c23) (54daefd)
- **map:** Refresh CLAUDE.md project map — harvest skill, memgrep overview, body-fidelity verify (v0.13.0) (34fa090)
- **trdd:** Gated re-enable DONE — wikimem editor live on v0.13.0 (TRDD-a5780c23) (ecf433e)
- **trdd:** Daily memory-system migration — staggered harvest + gitignore enforcer (TRDD-3f7b6807) (f67a129)
- **trdd:** Daily-migration P1+P2+P3(LOCAL) done; PROJECT scope surfaced (TRDD-3f7b6807) (c155a6f)
- **memory:** Metadata.type is organizational-only, not retrieval-affecting ([#46](https://github.com/Emasoft/ai-maestro-janitor/issues/46)) (40c3832)
- **map:** Refresh CLAUDE.md project map for v0.14.0 — memgrep lint, librarian/scanner fixes (2d4c74c)

### Features

- **memory:** Per-project phase staggering for editor cadences (TRDD-3f7b6807) (848f1c6)
- **memory:** PROJECT-memory gitignore-exception enforcer (TRDD-3f7b6807, Phase 2) (8ea5265)
- **memory:** Auto-recall hook ON by default with a triviality guard ([#45](https://github.com/Emasoft/ai-maestro-janitor/issues/45)) (ea300ff)
- **memgrep:** Add 'lint' subcommand — deterministic note-integrity gate ([#47](https://github.com/Emasoft/ai-maestro-janitor/issues/47)) (c6e0bc3)

### Testing

- **marketplace-refresh:** Widen detached-worker wait to de-flake the full suite (14a6fcd)
## [0.13.0] — 2026-06-20

### Bug Fixes

- **memory:** Split candidate-scan excludes private/generated files + portable (TRDD-87935f21) (c3372c5)
- **memgrep:** Resolve [[name]] wikilinks by frontmatter name:, not just file-stem ([#49](https://github.com/Emasoft/ai-maestro-janitor/issues/49)) (6cc42ac)
- **memory:** Clear CPV --strict on the new harvest skill + index-rule content (TRDD-a5780c23) (779c29a)

### Documentation

- **trdd:** Scope-migration helper design — ai-maestro corpus option b (TRDD-47df698b) (81f08f2)
- **trdd:** Memgrep-managed index + editor anti-corruption (TRDD-a5780c23) (cd2646f)
- **trdd:** Part A done (MEMORY.md retired in rule+skills); remaining 3 itemized (TRDD-a5780c23) (586382b)
- **trdd:** Harvest chore — incorporate stray memory artifacts (MEMORY.md + loose .md) into the wiki daily, non-destructive (TRDD-a5780c23) (b5f3c17)

### Features

- **memory:** Retire the context-loaded MEMORY.md — recall is memgrep-only (TRDD-a5780c23) (4c8272d)
- **memgrep:** Add `overview` command — print the <project>-overview.md entry page (TRDD-a5780c23) (acbddf3)
- **memory:** <project>-overview.md entry page + wire `memgrep overview` into the stub (TRDD-a5780c23) (7e747c8)
- **memory:** Verify body-fact fidelity — passes can no longer paraphrase/drop a fact (TRDD-a5780c23, #48) (494d5f3)
- **memory:** Harvest chore — daily non-destructive incorporation of stray memory into the wiki (TRDD-a5780c23 Part C) (a16fdc6)
## [0.12.1] — 2026-06-20

### Bug Fixes

- **memory:** Clear CPV --strict blockers in the v0.12.1 changeset (TRDD-87935f21) (fad7eed)

### Documentation

- **trdd:** Record v0.12.0 ship (P6) + flaky-clippy detour; refocus on P5 (TRDD-87935f21) (ea7ecf3)
- **memory:** Merge/split — mandate a lead + preserve-every-body-fact guardrail (TRDD-87935f21) (f0c0502)
## [0.12.0] — 2026-06-20

### Bug Fixes

- **trdd:** Consistent dash list markers — clear MD004 publish blocker (TRDD-87935f21) (9b5e931)

### Documentation

- **memory:** Record P6 detectors + memory_scopes SSOT; TRDD STATE (TRDD-87935f21) (c38b4ee)

### Features

- **memory:** Memorize-nudge detector — keep the wiki populated (TRDD-87935f21) (d14510a)
- **memory:** Why-in-commits detector — enforce the WHY in commit messages (TRDD-87935f21) (aa4c593)

### Refactor

- **memory:** Extract three-scope resolver to shared SSOT (TRDD-87935f21) (10ee8d1)
## [0.11.0] — 2026-06-19

### Documentation

- **trdd:** P1-P4 done; P5/P6 next (TRDD-87935f21) (b7d196c)

### Features

- **memory:** Repair txn op — single-page page-shape/metadata backfill verifier + CLI (TRDD-87935f21) (0e1b608)
- **memory:** Schedule the repair pass — repair_per_day cadence + [janitor-memory-repair] marker (TRDD-87935f21) (aedaab4)
- **memory:** Janitor-memory-repair skill — the autonomous page-shape repair executor (TRDD-87935f21) (b9f3a96)
## [0.10.1] — 2026-06-19

### Bug Fixes

- **memgrep:** --where leading-dot no longer walks cwd; walk_and dedups overlapping paths (TRDD-87935f21) (8d28686)
- **memory:** Verify guards read flow-style metadata; lesson-prefix + user-mem number hardening (TRDD-87935f21) (71dbb70)
- **memory-skills:** Decisive PROJECT scope routing + tier/metadata enforcement + clean memgrep cmd (TRDD-87935f21) (f6c94e8)

### Documentation

- **trdd:** Memory curation is the janitor's core self-maintaining mission (TRDD-87935f21) (8be7d25)
## [0.10.0] — 2026-06-18

### Documentation

- **wikimem:** CPV --strict skill-quality cleanup of the 3 executor skills (5cc6d9c)
- **trdd:** Complete the wikimem-editor epic (54b25d7e + D/E/F/G) (59b4d41)

### Features

- **wikimem:** Split/merge/conflict executor skills + txn CLI + composite verifiers (TRDD-E/F/G) (62e1043)
- **wikimem:** Scheduler detector + cron-prompt marker wiring (TRDD-D) (dfd0c30)
- **user-mem:** Rename commands to /janitor-memory-user-{add,search,share} ([#196](https://github.com/Emasoft/ai-maestro-janitor/issues/196)) (88fda8f)

### Styling

- **wikimem:** Markdown lint fixes in the executor skills (MD031/MD028/MD004/MD009) (ebdb126)
## [0.9.4] — 2026-06-18

### Bug Fixes

- **memory-librarian:** Df-gate clustering to kill issue-#35 over-clustering (TRDD-b3eae1cd) (4be887e)

### Documentation

- **trdd:** Record ready-to-implement design for NPT b3eae1cd (librarian precision) (f40fc0e)
## [0.9.3] — 2026-06-18

### Features

- **wikimem:** Global settings store + 8 frequency commands + scheduler stamps (TRDD-c1397102) (cafe0e2)
## [0.9.2] — 2026-06-18

### Features

- **wikimem:** Commit-discipline rule + model provenance fields (TRDD-9e4851fc) (1c3618d)
## [0.9.1] — 2026-06-18

### Bug Fixes

- **trdd:** Redact absolute plan path + MD004 NIT in wikimem TRDD backlog (ce78ab0)

### Documentation

- Author wikimem-editor TRDD backlog (b3eae1cd NPT + A-G) (a2579af)

### Features

- **wikimem:** Memory-edit safety core — txn + lock + verify (TRDD-b92a9dd0) (23f6f67)
## [0.9.0] — 2026-06-17

### Bug Fixes

- **repomap:** Balance backticks when a docstring first line wraps mid-code-span (37ae031)
- **publish:** Clear 3 CPV --strict NITs blocking the release (61a91fc)

### Documentation

- **trdd:** Add TRDD-21944209 — CPV strict-gate unblock RESOLVED (report→TRDD conversion) (a54f797)
- **trdd:** TRDD-a4e41e89 STATE — Phase 1 meter COMPLETE/shipped, Phase 2 decision-pending (5c0eb47)
- **trdd:** Re-scope token-meter Phase 2 + author wikimem-editor librarian TRDD (45bdcc1)
- **trdd:** Capture USER's detailed wikimem-editor spec (merge/split/conflict + cadences) (52abb7c)
- Refresh auto-generated project map (pre-release, cache-cheap moment) (fbdcfa1)

### Features

- **mcp-sanitizer:** Strip injected payloads via updatedToolOutput, on by default (25381ce)
- **token-budget:** PreToolUse self-consumption warning hook (token-meter Phase 2 v1) (80d4de2)
## [0.8.10] — 2026-06-14

### Bug Fixes

- **version-update:** Never run a scope-less `claude plugin update` (preserve install scope) (afeef6a)
## [0.8.9] — 2026-06-14

### Bug Fixes

- **token-meter:** Step over tool_result user messages when finding the turn boundary (691b5d6)
## [0.8.8] — 2026-06-14

### Features

- **token-meter:** Log each heartbeat's token cost + /janitor-token-report (TRDD-a4e41e89 Phase 1) (6a24b82)
## [0.8.7] — 2026-06-14

### Documentation

- **janitor-arm:** Honest durability reporting + document CC survival gaps ([#23](https://github.com/Emasoft/ai-maestro-janitor/issues/23)) (7dc9239)
## [0.8.6] — 2026-06-14

### Documentation

- Add TRDD-b3eae1cd — librarian conflict/aggregation heuristic tuning ([#35](https://github.com/Emasoft/ai-maestro-janitor/issues/35)) (c1c6c8c)

### Miscellaneous Tasks

- Add timeout-minutes to all jobs + self-heal the flaky CPV validate step (dc53b48)
## [0.8.5] — 2026-06-14

### Bug Fixes

- **workflow-doctor:** Don't flag attestation id-token: write as unscoped ([#30](https://github.com/Emasoft/ai-maestro-janitor/issues/30)) (0b22bb0)
## [0.8.4] — 2026-06-14

### Bug Fixes

- **memory-librarian:** Accept ocd/lmd nested under metadata: ([#33](https://github.com/Emasoft/ai-maestro-janitor/issues/33)) (d63f31a)
## [0.8.3] — 2026-06-14

### Bug Fixes

- **detectors:** Silence two fleet-wide heartbeat false positives (#32, #34) (b056f43)
## [0.8.2] — 2026-06-14

### Bug Fixes

- **ci:** Make janitor-install-scope.py executable — CI exit 126 + heartbeat skip (1421afe)
## [0.8.1] — 2026-06-14

### Documentation

- **rules:** Add janitor-footprint — concise always-injected machine-footprint rule (00e562e)
## [0.8.0] — 2026-06-14

### Bug Fixes

- **memory:** USER scope → ${CLAUDE_PLUGIN_DATA}/memory (not ~/.claude/memory) (3b3cf52)
- **memory:** USER scope resolves to the janitor's FIXED data dir, never ${CLAUDE_PLUGIN_DATA} (e86f8e7)
- **memory:** Zsh-safe array form for recall ROOTS — was silently returning 0 hits on zsh (df2e563)
- **publish:** Scope doc-lint out of the memory corpus + all TRDD-lifecycle folders (6736144)
- **memory:** Make bootstrap skill CPV-clean (only the .claude/ gitignore FP #120 remains) (1ae8fa6)
- **rules:** User-scope wins — no redundant project-local rule copies ([#36](https://github.com/Emasoft/ai-maestro-janitor/issues/36)) (9f1c182)
- **identify-env:** Clear CPV CRITICAL+MINOR on the env-report script (dd321e3)

### Documentation

- **3-pillars:** Complete #172 — PRRD silver rules, 4-zone design folders, v1→v2 TRDD migration (0eaf67c)
- **trdd:** Close f892e109 STATE — resolve stale "DECISION PENDING" vs complete (c44054b)
- Add TRDD-4c3733d9 — memory scope storage locations (3-scope redesign) (1ab57df)
- **memory:** Install PROJECT-scope wikimem pages + 8 promoted notes (.claude/project/memory) (dd19c40)
- **trdd:** Close TRDD-4c3733d9 — memory scope redesign complete (all phases + tested) (cba41da)
- **memory:** Record CPV #120 .claude/ gitignore FP (PROJECT scope) (d303f50)
- Add TRDD-db169d9e — janitor portability + context-awareness (f58f053)
- **trdd:** Answer D3 (ai-maestro send-to-terminal API) by research — TRDD-db169d9e (ca13a2c)

### Features

- **memory:** PROJECT scope → <repo>/.claude/project/memory (namespaced, collision-proof) (b75f250)
- **memory:** Proactive-use directives + /janitor-memory-bootstrap (fleet rollout) (4b47aaa)
- **portability:** Context-gate + process-ancestry terminal detection (TRDD-db169d9e Phase 1) (afac362)
- **portability:** Gate TRDD-framework detectors on the ai-maestro context (TRDD-db169d9e Phase 2) (3125b5f)
- **portability:** Exclude the ai-maestro fleet from daemon auto-update (TRDD-db169d9e Phase 3) (ff4e8b9)
- **portability:** Terminal-aware self-trigger send-abstraction + tmux backend (TRDD-db169d9e Phase 4) (8d9e7bb)
- **portability:** Ai-maestro API send + subprocess gate-test harness (TRDD-db169d9e Phase 5) (848b700)
- **command:** /janitor-identify-environment — full runtime-environment report (c992406)
- **portability:** R5 user-level-only — install-scope detector + arm refusal (TRDD-db169d9e Phase 6, COMPLETE) (ace52fc)

### Miscellaneous Tasks

- **repomap:** Refresh after memory-system build (bootstrap skill + scope migration) (ee1dbaf)
- **trdd:** Close TRDD-8546a187 — baseline reconcile shipped v0.7.0 ([#157](https://github.com/Emasoft/ai-maestro-janitor/issues/157)) (343ca55)

### Testing

- **branch-protection:** Tighten gh-stub to method->path routing semantics ([#182](https://github.com/Emasoft/ai-maestro-janitor/issues/182)) (d7dcb6e)
## [0.7.5] — 2026-06-13

### Bug Fixes

- **workflow-doctor:** Scope secret-env-bare-in-run structurally ([#24](https://github.com/Emasoft/ai-maestro-janitor/issues/24)) (5fbad1d)

### Miscellaneous Tasks

- **repomap:** Refresh CLAUDE.md map after v0.7.4 (memory_guard + reload_trigger) (5c799a4)
## [0.7.4] — 2026-06-13

### Features

- **skill:** /janitor-reload-plugins — agent-invocable /reload-plugins trigger (96521b7)
## [0.7.3] — 2026-06-11

### Features

- **daemon:** Tier-1 OOM memory-guard task (TRDD-7100178d Phase 5 — pillar set complete) (7ff3fc9)
## [0.7.2] — 2026-06-11

### Bug Fixes

- **detectors:** Heartbeat crash + 2 silently-skipped detectors; strict per-detector CI gate (de4746d)
## [0.7.1] — 2026-06-11

### Bug Fixes

- **ci:** Memgrep release staging path + permanent recurrence guard (230fadc)
- **ci:** Reference the smoke job's staged binary via env var, not a literal path (708bbe3)

### Documentation

- **trdd:** Add 3ab0397e — heartbeat survival on CC 2.1.173 (issue #23 triage) (6872084)
## [0.7.0] — 2026-06-11

### Bug Fixes

- **branch-protection:** Filter required-checks to PR-triggered workflows (janitor#14) (8c63ad3)
- **branch-protection:** Ruleset UPDATE is PUT not PATCH (latent 404, janitor#14) (874cdd7)
- **oauth-rotator:** Self-heal live-account state drift before rotation decisions (4b2f414)
- **oauth-rotator:** CRITICAL — keychain slot write truncated every blob to 128B (TRDD-5539cd6e) (655a870)
- **memgrep:** Resolve [[TRDD-<id8>]] wikilinks via filename id8 alias (5b-1) (5b6a6f5)
- **memgrep:** Die quietly on broken pipe (SIGPIPE), never panic on '| head' (38f5905)
- **memgrep:** Harden recursion/OOM/semijoin + exclude index files from recall (84c74dc)
- **oauth-rotator:** Renew transport = CDP-attach to real Chrome (not Playwright mock-keychain) (d05b94c)
- **oauth-rotator:** Phase 0 consistency — detectors+reauth use canonical _profiles_root; add print-profiles-root/oauth-health subcommands (TRDD-dfc0959a) (3316e44)
- **oauth-rotator:** SKILL.md M1 + account-count via keychain; TRDD-dfc0959a Phase 0 DONE (a852cb8)
- **oauth-rotator:** Isolate cmd_tick tests from real keychain/log (cascade-log leak) (2b094f8)
- **oauth-rotator:** Token-endpoint requests need a User-Agent (Cloudflare 1010) — VERIFIED LIVE (6fdbeaa)
- **publish:** Run cargo clippy on subfolder crates via --manifest-path (df02a90)
- **publish:** Scope markdown lint to shipped docs (exclude TRDDs + test fixtures) (1b5d632)
- **publish:** Build clippy artifacts in a temp CARGO_TARGET_DIR, not in-tree (b52a748)
- **memory:** Simulation-driven hardening — 2 librarian bugs + scope-local links + rename protocol (TRDD-bc16d602) (46e8326)
- **cpv:** Real findings — malformed-YAML frontmatter, phantom file-ref, dead allow_root_dirs key (056db3b)
- **cpv:** Clear MAJOR findings — skill descriptions ≤200 tokens, memgrep build.sh, +x bits (2285a59)
- **rotator:** Refresh-on-err in cmd_auto so a stale slot token can't deadlock rotation (a6e5a34)
- **rotator:** Clear 2 pre-existing mypy errors in rotator.py (d61da87)
- **rotator:** Audit pass — refresh-on-err heal now updates the state index in lockstep (734f427)
- **cpv:** Clear the strict-gate findings — relocate memgrep, devitalize, doc fixes (USER publishing directive) (f7104d6)
- **cpv:** Round 2+3 — CPV --strict now EXIT 0 (0 CRITICAL/MAJOR/MINOR/NIT) (216ee03)

### Documentation

- **trdd:** Add 8546a187 — baseline-ruleset reconcile + 2 shared follow-ups (janitor#14) (ed97e91)
- **trdd:** Add fb4850b5 — user-presence breadcrumb for MANAGER degraded-mode (janitor#15) (0a8d6ec)
- **trdd:** 32acd15f — live evaluation addendum (state-drift fix + refresher verified) (fb11c63)
- **trdd:** 8546a187 — record tag-protection 3rd baseline ruleset (maintainer#7, Tier-2) (0fd8a5f)
- **trdd:** 8546a187 — tag-protection consensus CLOSED, final byte-identical spec (a427852)
- **trdd:** Add 5539cd6e — CRITICAL keychain slot write 128-byte truncation (36db639)
- **trdd:** 5539cd6e — keychain truncation FIXED + proven (655a870), column->testing (900f7f8)
- **trdd:** 5539cd6e — post-compaction re-verification (47 tests pass, fmuaddib slot healthy ~6.3h, emanuele slot dead -121h) (b45ea00)
- **trdd:** Add 924645bb — rotator leaves no durable decision log; add persistent rotator.log (d0dbc6f)
- **trdd:** 924645bb — decision log IMPLEMENTED+PROVEN (50496e5), column->testing (9d6a6cf)
- **trdd:** Add d151fe52 — memgrep, a markdown-AST-aware grepper + agent-memory helpers (Rust) (7183bc9)
- **trdd:** D151fe52 — memgrep Phase 1 DONE+VERIFIED (0dfbbdd, 10/10 tests, clippy clean) (ba157af)
- **trdd:** D151fe52 — memgrep Phase 2 DONE+VERIFIED (ed68e8e, 16/16 tests) (34eb9f0)
- **trdd:** D151fe52 — memgrep Phase 3 DONE+VERIFIED (9d030cb, 20/20 tests) (a83e47b)
- **trdd:** D151fe52 — memgrep Phase 4 DONE+VERIFIED (21d9bf5, 22/22 tests) (b9e581a)
- **trdd:** D151fe52 — memgrep Phase 5a DONE (eedaada); capture Phase 6 boolean composition (find-style + --where) (a78d7c0)
- **trdd:** D151fe52 — Phase 6a+6b done (boolean Expr tree + --where DSL) (84834fe)
- **trdd:** D151fe52 — 5b-1 wikilink id8-alias done (commit 5b6a6f5) (9abdc64)
- **trdd:** D151fe52 — 5b-2 link semijoin done (commit 063a610) (d846a1a)
- **memgrep:** Add minimal SKILL.md + memory-system measurement TRDD (ce195129) (6e4564e)
- **trdd:** Ce195129 — iter 3: precision layer measured (6→2, 100% precision) (cea9226)
- **trdd:** Ce195129 — iter 8: efficiency+precision proven at scale (b7e5c4d)
- **trdd:** Ce195129 — iter 9: skill 25/25 forms execute; goal CONVERGED (fe3f8af)
- **trdd:** Ce195129 — memory-system phase 2 done (audit + protocol layer + 13 integration issues filed) (5189c25)
- **trdd:** Dfc0959a — rotator 3-layer cascade + keychain-encrypted cross-platform cookies redesign + 17-finding consistency audit (f4b0bf7)
- **trdd:** Dfc0959a — Phase 1 cascade DONE + live manual-rotation diagnosis (e0db288)
- **trdd:** Dfc0959a — Phase 2 mechanics (safe_storage+cookie_vault) DONE (77a7f3b)
- **trdd:** Dfc0959a — Phase 2c-wiring DONE (opt-in, default off); scrub deferred to Phase 3 (70fd349)
- **trdd:** 8546a187 — verified state; baseline-tag-protect impl+tested+USER-ratified; reconcile still gated on maintainer SHA exchange (ec1ada0)
- **trdd:** 3e1e9b12 — stale-task #151 triage; derived-bug #1 verified already-fixed (5e896f1)
- **memory-write:** Reflow prose so a wrapped '+ ' doesn't read as a list bullet (fef147b)
- **trdd:** Add TRDD-c77dae09 — memory librarian (background per-topic auto-aggregation) (6e5cb5c)
- **trdd:** C77dae09 — separation of powers + non-destructive correction + read-notes rule (cca75bb)
- **trdd:** C77dae09 — lesson WHY is load-bearing + memgrep auto-resolves footnotes (fc72a01)
- **trdd:** C77dae09 — memgrep resolved-notes render format (token-economical) (5e2f5e2)
- **trdd:** C77dae09 — per-element OCD/LMD datetimes + notes are searchable elements (08d7b19)
- **trdd:** C77dae09 — notes follow their memory on moves + git-backed incremental index (91cbe30)
- **trdd:** Add TRDD-4334aad0 — user private memories (/to-user-mem + /search-user-mem) (4df8234)
- **trdd:** 4334aad0 — full invisibility (systemMessage results) + immutable numbering + /share-user-mem (28f7dae)
- **memory:** Teach agents the shipped memory system — read-the-notes rule, correction protocol, memgrep find/dates/index CLI (6407138)
- **trdd:** Memory-system build status — memgrep engine complete, librarian surface-only landed (3f7f67b)
- **trdd:** De731408 — monitors: research done, migration SHELVED; v2 frontmatter (466670b)
- **trdd:** C77dae09 — THREE-SCOPE wiki layers (user/project/local) per USER directive (24edd4a)
- **memory:** Close authoring-schema drift + canonicalize lessons-section spelling (slice B rank 7, TRDD-c77dae09) (f46c97a)
- **trdd:** 631fa3de — resolve drift; v2 frontmatter + dated park (guard-mode evaluation) (3033a96)
- **trdd:** 8546a187 — baseline-tag-protect applied LIVE (id 17545495, readback byte-identical) (7f32353)
- **repomap:** Refresh CLAUDE.md project map — add project-map-drift + repomap_generate (f3ed750)
- **trdd:** 32acd15f — ROOT CAUSE of the 429-instead-of-rotate incident (CF-1010 keepalive) (005bca6)
- **watchdog:** Narrow the stale '1M auto-compact unreliable' claim (CC 2.1.172) (86502a6)
- **trdd:** Close 3e1e9b12 remainders + record 31095269 docs-done (b845a06)

### Features

- **branch-protection:** Shared orphan-delete UNION + emergency-scrub doc (janitor#14) (5922c1a)
- **branch-protection:** Add ratified baseline-tag-protect (3rd ruleset) (3671909)
- **oauth-rotator:** Persistent decision log so unattended ticks leave a durable trail (50496e5)
- **memgrep:** Phase 1 — markdown-AST-aware grep core (TRDD-d151fe52) (0dfbbdd)
- **memgrep:** Phase 2 — heading-numbering ranges, --depth, --fm frontmatter (TRDD-d151fe52) (ed68e8e)
- **memgrep:** Phase 3 — inline emphasis, Quarto span-class metadata, lists (TRDD-d151fe52) (9d030cb)
- **memgrep:** Phase 4 — GFM structure kinds (--node/--no-node + sugar) (TRDD-d151fe52) (21d9bf5)
- **memgrep:** Phase 5a — link graph + index/links/fact subcommands (TRDD-d151fe52) (ae24784)
- **memgrep:** Phase 6a — lower flat filters to a boolean Expr tree (a88c915)
- **memgrep:** Phase 6b — --where boolean DSL + path/name/fm predicates (0f1741a)
- **memgrep:** 5b-2 link filters as --where semijoin (links-to/linked-from) (063a610)
- **memgrep:** Add 'recall' subcommand — one-command symptom-ranked memory recall (e502ad3)
- **memgrep:** Recall precision-first + log convergence (iter 7) (2171f8f)
- **memory:** Recall protocol rule + reference recall/write skills (894c9c7)
- **oauth-rotator:** Phase 1 — ROTATE→RENEW→REAUTH cascade SSOT (TRDD-dfc0959a) (f4cba4f)
- **oauth-rotator:** Phase 2a — safe_storage cross-platform secret abstraction (TRDD-dfc0959a) (a7506d3)
- **oauth-rotator:** Phase 2b — cookie_vault sqlite<->jar<->json mechanics (TRDD-dfc0959a) (9986f7e)
- **oauth-rotator:** Phase 2c-mechanics — keychain cookie snapshot/materialize (TRDD-dfc0959a) (def438f)
- **oauth-rotator:** Phase 2c-wiring — opt-in keychain cookies in the capture flow (TRDD-dfc0959a) (21da98c)
- **memgrep:** Footnote capture + resolution + token-economical --with-notes (slice 1) (54400d3)
- **memgrep:** Per-element OCD/LMD dates + recall sort & date-range (slice 2) (10dbc7c)
- **memgrep:** Persistent SQLite+FTS5 git-incremental query index (slice 3) (a3150f8)
- **memgrep:** Add `find` +/- query DSL (mandatory/exclude/wildcard/phrase) + --only-notes (0953897)
- **user-mem:** Private user-memory subsystem with +/- search DSL (TRDD-4334aad0) (b9dfea9)
- **memory:** Add memory-librarian detector — SURFACE-only aggregation/conflict candidates (6575e04)
- **presence:** Host-level user-presence breadcrumb for MANAGER degraded-mode (janitor#15, TRDD-fb4850b5) (f69d52b)
- **memory:** Memgrep release-binaries CI + opt-in auto-recall hook ([#16](https://github.com/Emasoft/ai-maestro-janitor/issues/16)) (5889f94)
- **memory:** Three-scope wiki layers + scope-leak enforcement (slice A, TRDD-c77dae09) (339c8c0)
- **memory:** Librarian page-shape validator (slice B rank 3, TRDD-c77dae09) (8aa8e0c)
- **memory:** Librarian broken-links + orphans + MEMORY.md sync (slice B rank 4, TRDD-c77dae09) (e44fdd7)
- **memory:** Correction-protocol advisory PostToolUse hook (slice B rank 5, TRDD-c77dae09) (602b7ce)
- **memory:** Librarian scheduled reindex per root (slice B rank 8, TRDD-c77dae09) (8d6a8e7)
- **memory:** The 3 core wiki skills — MEMORIZE / UPDATE / RECALL (TRDD-bc16d602) (3658f0e)
- **memory:** Directional edges — radiating suns vs receiving terminals (TRDD-bc16d602) (3989ea2)
- **memory:** THE LINK LAW + worked-example wiki + librarian reciprocity audit (TRDD-bc16d602) (68118a1)
- **memory:** Wiki-by-default rule section + librarian tier-shape checks (TRDD-bc16d602) (b98b9da)
- **repomap:** Auto-maintained CLAUDE.md project map — generator + nudge detector + on/off skills (TRDD-e247a349) (351366b)
- **daemon:** Pillar-1 per-task supervision + subprocess retry (TRDD-7100178d Phase 4) (1c74921)
- **daemon:** Pillar-0 self-resurrection — wedged-daemon kill + crash-loop breaker (TRDD-7100178d Phase 4) (2ac4a18)

### Miscellaneous Tasks

- **security:** Devitalize CPV detector-needle FPs — CRITICAL 16→0 (plugin-devitalizer) (0b9af54)

### Testing

- **oauth:** Fragment keychain-write fixture secret to clear hygiene gate (bb63fc1)
## [0.6.1] — 2026-06-04

### Bug Fixes

- **oauth-rotator:** Cross-platform audit fixes — bootstrap B1-B3 + P1-P3 (TRDD-32acd15f) (3fedd0a)

### Documentation

- **trdd:** 477eb7fb published — v0.6.0 via squash (be57abd/c124f49); record the 110-backup-only / 4-already-published correction (0d8f924)
- **oauth-rotator:** Document ask-to-login + auto-bootstrap (skill + README) (9930baa)
- **trdd:** 32acd15f session addendum — ask-login + bootstrap + audit fixes (B1-B3/P1-P3); #142 still open (9d6b4bc)

### Features

- **oauth-rotator:** Ask-to-login nudge + post-login auto-bootstrap (TRDD-32acd15f P4c/P4d) (b4cf85b)
## [0.6.0] — 2026-06-04

### Features

- V0.6.0 — detector waves, Sentinel/zizmor workflow auditor, daemon hardening, runtime-generated secret fixtures (be57abd)
## [0.5.1] — 2026-05-27

### Bug Fixes

- **skills:** Split workflow-{doctor,create} SKILL.md into references (c245f05)
- **skills:** Add TOC to workflow-set-generation.md reference (68746de)
- **skills:** Clear 4 SkillAudit FPs in instruction-loadable files (db38abb)
- **scanner:** Complete Sentinel coverage (32/32) + self-audit fixes (c27609d)
- **docs:** Align Sentinel recipe severities with emitted labels (fc8bef1)
- **dispatch:** Make heartbeat auto-renewal silent (no more 6-day reminder) (35ee546)
- **lint:** Drop unused pytest imports + split combined import line (d3b54bf)
- **lint:** Clear pymarkdown findings blocking the publish pipeline (6f19eec)
- **cpv:** Clear CRITICAL path leak + MAJOR ruff/PEP-723/typing findings (220ba4c)
- **cpv:** Clear remaining MAJOR + MINOR + NIT findings (5b7b51c)
- **cpv:** Kill remaining ReDoS in rules_injection.py JQ_PATTERN (3b6f1ee)
- **recheck:** Align docstrings + README with the actual #65/#66/#71 code (ab77cdc)
- **lint:** Unify list markers in branch-protection-setup SKILL.md (MD004) (bedacdf)
- **cpv:** Rephrase guard_mode_enabled description to clear MCP_SCHEMA_POISON NIT (eaff131)

### Documentation

- Add TRDD-ca754708 — port Sentinel GitHub-Actions rule set into janitor workflow auditor (334d71c)
- Add TRDD-631fa3de — evaluate janitor security guard mode (1715624)

### Features

- **skills:** Add janitor-github-workflow-{doctor,create} (d4c79fb)
- **skills:** Add 5 supply-chain skills + restructure for CPV strict gate (07aa80b)
- **scanner:** Single-pass google-re2 RegexSet classifier (Python re fallback) (ed48a8f)
- **scanner:** Port Sentinel GitHub-Actions rule set into workflow-doctor (e9d8a6a)
- **security:** Add workflow-security + branch-protection heartbeat detectors (382d1e5)
- **daemon:** Single global janitor daemon owns marketplace-refresh + user-plugins-update ([#7](https://github.com/Emasoft/ai-maestro-janitor/issues/7)) (88385f6)
- **guard:** PreToolUse hook blocks package-manager safety bypasses ([#8](https://github.com/Emasoft/ai-maestro-janitor/issues/8)) (72ce77e)
- **detect:** Package-manager-policy detector — supply-chain hardening audit (d81c042)
- **autonomy:** [janitor-reload] + daemon self-restart on plugin upgrade (2b1d4ed)
- **autofix:** /janitor-autofix-on + /janitor-autofix-off opt-out toggle (ff0284e)
- **daemon:** Move version-update auto-update branch into the daemon ([#66](https://github.com/Emasoft/ai-maestro-janitor/issues/66)) (63031ff)
- **guard:** Security guard mode Option B — branch-protection baseline ([#65](https://github.com/Emasoft/ai-maestro-janitor/issues/65)) (5ac3506)
- **marketplace-refresh:** Scope per-session to local+project, lower daemon to 20 min ([#71](https://github.com/Emasoft/ai-maestro-janitor/issues/71)) (1f434a9)

### Miscellaneous Tasks

- **workflows:** Add zizmor security audit + fix 11 of 12 findings (9e2ac3f)

### Testing

- **scanner:** Fix ruff I001 import-sort in zizmor classifier tests (1d8b310)
## [0.5.0] — 2026-05-20

### Bug Fixes

- **publish:** Respect gitignore in Step 11 py-file staging discovery (88897a4)

### Features

- **detectors:** Add screenshot-purge for reports/screenshots/ (4b5f84c)

### Miscellaneous Tasks

- Revert pre-emptive 0.5.0 bump — publish.py drives the release (15cc352)

### Testing

- **screenshot-purge:** Add 29-test pytest suite + sync README/uv.lock (2f49280)
## [0.4.13] — 2026-05-16

### Documentation

- **readme:** Add CC v2.1.143 entry to "Recent Claude Code fixes" (47e4363)
## [0.4.12] — 2026-05-15

### Bug Fixes

- **arm:** Use markdown link format for references/janitor-architecture.md (CPV TOC discovery) (96fc3f1)
- **arm:** Add TOC to references/janitor-architecture.md (CPV progressive discovery) (1fbf55b)
- **arm:** Consolidate reference-file TOC to 3 sections + embed in SKILL.md (CPV progressive discovery) (0b19df0)
- **arm:** Further trim SKILL.md to fit 5000-char CPV cap with TOC embed (699fb87)
- **arm:** Restore required Examples section (CPV strict mode) (f9c415b)

### Documentation

- **arm:** Move dispatcher architecture detail to references/janitor-architecture.md (cffca32)
## [0.4.11] — 2026-05-15

### Bug Fixes

- **arm:** Remove MD038 leading-space inside inline-code span (0c02f9a)
- **arm:** Trim SKILL.md under CPV 5000-char threshold (ebf93c9)
- **arm:** Restore 'Use when...' phrase + Resources section for CPV strict mode (34826e3)

### Features

- **arm:** Install auto-rolling dispatcher stub in ${CLAUDE_PLUGIN_DATA} (cc8d7e3)
## [0.4.10] — 2026-05-15

### Features

- **detectors:** Add project-plugins-update — Phase 3 of auto-update directive (027fcec)
## [0.4.9] — 2026-05-15

### Features

- **detectors:** Add local-plugins-update — Phase 2 of auto-update directive (23a2d41)
## [0.4.8] — 2026-05-15

### Features

- **detectors:** Add user-plugins-update — Phase 1 of auto-update directive (90c43d0)
## [0.4.7] — 2026-05-15

### Features

- **detectors:** Add marketplace-refresh — bulk update every heartbeat (644d158)
## [0.4.6] — 2026-05-15

### Features

- **detectors:** Default version-update + plugin-updates to 5-min cadence (41fdb7a)
## [0.4.5] — 2026-05-15

### Documentation

- **readme:** Note Claude Code 2.1.142 cache-GC + sleep-wake fixes (f7c31c7)
## [0.4.4] — 2026-05-13

### Documentation

- **readme:** Note Claude Code 2.1.133/136/139 fixes the janitor benefits from (b6b1f20)

### Miscellaneous Tasks

- **cliff:** Preprocess trailing space inside inline-code spans (17819c1)
## [0.4.3] — 2026-05-10

### Bug Fixes

- **rules:** Drop trailing space inside `safe-deleted: ` code span (MD038) (89314a1)
- **rules-installer:** Refresh on size mismatch, not just on first install (ad366e3)

### Documentation

- **rules:** Rewrite use-safe-delete around risk judgement (f287cba)

### Features

- **rules:** Ship use-safe-delete rule + scope-aware installer hook (c6f910e)
## [0.4.2] — 2026-05-09

### Bug Fixes

- **ci:** Align workflow with the bash → Python port (50b9885)
## [0.4.1] — 2026-05-09

### Bug Fixes

- **branch-detection:** Squash-merge support + worktree safety gates (a1f4339)
- **detectors:** Self-review pass — close 6 real gaps in v0.4 changes (cbcdea7)
- **mcp-config-drift:** Correct the MCP storage layout (2158e53)
- **audit:** Mechanical cleanup from plugin-audit-2026-05-08 (1411ed5)
- **audit:** Defang [/] in untrusted text emitted by 9 detectors (f8471c7)
- **detectors:** Bound external commands with timeout via state.run_subprocess (079dfdb)
- **detectors:** Substantive correctness bugs across 8 detectors + publish.py (6934411)
- **plugin-validation:** Clear all 9 MAJOR + 1 MINOR from CPV validate-plugin (3e0d6e5)
- **publish:** Drop Step 4 (CPV lint) — subcommand retired in CPV v2.71.0+ (94d7667)
- **publish:** Use git ls-files for *.py walk so .gitignore is honored (bdea0a8)

### Documentation

- **readme:** Document the 9 new features from catalogue audit (0812d22)
- **plugin-updates:** Make the git-tracking ↔ scope mapping explicit (839ee06)

### Features

- **logging:** Annotate log_line entries with CLAUDE_CODE_SESSION_ID (eba79e4)
- **detectors:** Add 4 security + drift detectors from catalogue audit (eb34a66)
- **ops:** /janitor-pause /janitor-resume /janitor-doctor + log retention (c3ed8d1)
- **detectors:** Add plugin-updates — auto-install project-scoped plugin updates (2cbe9f9)
- **detectors:** Add mcp-config-drift — audit project MCP configuration (202a90d)
- **detectors:** Add 3 scope-tracking-drift detectors + extract shared helper (ba05046)
- **detectors:** Cross-scope-reference-drift — catch silent-clone-break (915cf35)
- **cross-scope-reference:** Enforce SCOPE PARITY both directions (b88374a)
- **cross-scope-reference:** Scan YAML frontmatter for skill/agent refs (4400843)
- **publish:** Drive lint step by file extension, not project kind (8e2ad3c)

### Refactor

- **scripts:** Port plugin internals from bash to Python (PEP 723 + uv) (12263f2)
- Shared helpers + drop dead state writes (audit Phase 5) (15ed872)

### Styling

- Remove blank line after late-imports block (ruff I001) (d083919)
## [0.3.15] — 2026-05-03

### Bug Fixes

- **safe-delete:** Cpv strict-mode compliance + ignore INPUT_DEV (304931e)

### Features

- **safe-delete:** Recoverable rm alternative for agents (1cf24c5)
- **detectors:** Trashcan-purge auto-removes old safe-delete batches (2cd94a9)
## [0.3.14] — 2026-05-02

### Miscellaneous Tasks

- **release:** Skip Create-GitHub-Release step when release already exists (99ae839)
## [0.3.13] — 2026-05-02

### Bug Fixes

- **detectors:** Worktree-janitor — guard against fresh and locked worktrees (a1067b1)
## [0.3.12] — 2026-05-02

### Features

- **detectors:** Version-update auto-updates plugin + detects stale cron (8aeffd7)
## [0.3.11] — 2026-05-02

### Documentation

- **readme:** Note v2.1.110 resume-resurrects-cron behavior (6485162)
- Add TRDD-de731408 — monitors:-manifest migration plan (4634435)

### Features

- **detectors:** Nudge on a newer plugin release available on GitHub (d3e7eb0)
## [0.3.10] — 2026-05-02

### Bug Fixes

- **detectors:** Walk parent dirs when matching subagent-report files (6e5246a)
## [0.3.9] — 2026-04-26

### Bug Fixes

- **detectors:** Skip sibling TaskCreate IDs when scanning #N PR refs (c41d9c8)
## [0.3.8] — 2026-04-26

### Bug Fixes

- **detectors:** Scope task UUID to current project's session log (56dd5df)
- **publish:** Stage uv.lock in release commit (4dfb757)

### Miscellaneous Tasks

- Update uv.lock (ee89ec6)
## [0.3.7] — 2026-04-24

### Features

- **heartbeat:** Auto-renew before 7-day expiry + /janitor-disarm skill (1465b89)

### Miscellaneous Tasks

- Update uv.lock (573d747)
## [0.3.6] — 2026-04-24

### Documentation

- Add centered logo to README header (8c68655)

### Miscellaneous Tasks

- Update uv.lock (1160242)
## [0.3.5] — 2026-04-24

### Bug Fixes

- **ci:** Rename monitors→detectors in workflows; run all 8 detectors (9db1390)
- **shell:** Harden dispatch + detectors against set -u, races, and paste injection (84cfe91)
- **publish:** Drop unused gitignore_filter dep; anchor pre-push glob; polish (d13c46f)

### Documentation

- Sync with 8 detectors, correct heartbeat_cron, trim skills (260f007)

### Miscellaneous Tasks

- Update uv.lock (9372f5b)
- Ignore .rechecker/ runtime state (2e4ce10)
- Ignore reports/ and reports_dev/ for agent output hygiene (5d6567e)
- Ignore .tldrignore; resync uv.lock for requires-python >=3.11 (90917d9)
## [0.3.4] — 2026-04-22

### Miscellaneous Tasks

- **security:** Pin third-party actions by SHA and sanitise audit issue body (baaab7e)
- Update uv.lock (c528349)
- Update uv.lock (ea7d1b5)
## [0.3.2] — 2026-04-19

### Miscellaneous Tasks

- Update uv.lock (0313025)

### Performance

- **heartbeat:** 5-min cadence + compact prompt (~80 tokens saved per fire) (b922a15)
## [0.3.1] — 2026-04-19

### Bug Fixes

- **stale-task:** Lower in_progress staleness threshold from 4h to 2h (30af878)

### Miscellaneous Tasks

- Update uv.lock (edecb40)
## [0.3.0] — 2026-04-19

### Bug Fixes

- **subagent-report:** Quote $root inside ${..} to silence shellcheck SC2295 (961e757)

### Features

- Add stale-task + dirty-tree + subagent-report detectors (ef9608e)
## [0.2.2] — 2026-04-19

### Documentation

- Verify end-to-end rate-limit recovery (89s offline → [janitor-resume] cue) (f038106)
## [0.2.1] — 2026-04-19

### Bug Fixes

- **ci:** Rename scripts/monitors → scripts/detectors + add dispatch.sh, drop monitors.json check (v0.2.0 refactor follow-up) (89b696a)

### Miscellaneous Tasks

- Update uv.lock (6c4fa27)
## [0.2.0] — 2026-04-19

### Documentation

- **skill:** Trim janitor-arm SKILL.md for CPV strict (5124→4034 chars, desc 338→220, add Resources) (ae4821c)
- **skill:** Satisfy CPV strict (Use when phrase + checklist boilerplate) (c8b4713)

### Features

- Pivot to CronCreate heartbeat architecture (v0.2.0 prep) (d9e71e8)
## [0.1.4] — 2026-04-19

### Bug Fixes

- Worktree-janitor primary-worktree skip on macOS (b2d4871)

### Documentation

- Tighten janitor-audit SKILL.md under 5000-char limit (390e0b3)

### Miscellaneous Tasks

- Update uv.lock (07f548e)
- **lint:** Disable MD012 to accept cliff-generated multi-blank lines (4188aef)
## [0.1.3] — 2026-04-18

### Bug Fixes

- Add required userConfig.type fields (unblocks claude plugin install) (f70ee26)
- **changelog:** Collapse double blanks in cliff template + regen CHANGELOG.md (a351136)

### Miscellaneous Tasks

- Update uv.lock (f21c0ef)
## [0.1.2] — 2026-04-18

### Bug Fixes

- **ci:** Use uvx ruff instead of uv sync --extra dev (no dev deps defined in pyproject) (e711743)
- **changelog:** Remove trailing spaces and fix heading indent in cliff template (5155a3f)

### Miscellaneous Tasks

- Update uv.lock (0f17e15)
## [0.1.1] — 2026-04-18

### Bug Fixes

- Resolve CPV strict-validation issues (63935d4)
- Clear remaining CPV MINOR issues (b090692)
- **lint:** Add shebangs to lib scripts, add .shellcheckrc for monitor constraints (a6419ca)
- **lint:** Add .markdownlint.json to use project-local config for CPV lint (ffc5a1b)

### Features

- Initial ai-maestro-janitor v0.1.0 (3610530)

### Miscellaneous Tasks

- Add notify-marketplace workflow (2034ac1)
- Add publish.py pipeline + strict pre-push hook + cliff/pyproject (327bbaa)
- Add ci.yml + release.yml; gitignore docs_dev/uv.lock/.tldr (b9c4e9c)
- Track uv.lock; remove from .gitignore (ca6a25a)
---
*Generated by [git-cliff](https://git-cliff.org)*
