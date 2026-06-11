# Changelog

All notable changes to this project will be documented in this file.

## [0.7.0] - 2026-06-11

### Bug Fixes

- Filter required-checks to PR-triggered workflows (janitor#14)
- Ruleset UPDATE is PUT not PATCH (latent 404, janitor#14)
- Self-heal live-account state drift before rotation decisions
- CRITICAL — keychain slot write truncated every blob to 128B (TRDD-5539cd6e)
- Resolve [[TRDD-<id8>]] wikilinks via filename id8 alias (5b-1)
- Die quietly on broken pipe (SIGPIPE), never panic on '| head'
- Harden recursion/OOM/semijoin + exclude index files from recall
- Renew transport = CDP-attach to real Chrome (not Playwright mock-keychain)
- Phase 0 consistency — detectors+reauth use canonical _profiles_root; add print-profiles-root/oauth-health subcommands (TRDD-dfc0959a)
- SKILL.md M1 + account-count via keychain; TRDD-dfc0959a Phase 0 DONE
- Isolate cmd_tick tests from real keychain/log (cascade-log leak)
- Token-endpoint requests need a User-Agent (Cloudflare 1010) — VERIFIED LIVE
- Run cargo clippy on subfolder crates via --manifest-path
- Scope markdown lint to shipped docs (exclude TRDDs + test fixtures)
- Build clippy artifacts in a temp CARGO_TARGET_DIR, not in-tree
- Simulation-driven hardening — 2 librarian bugs + scope-local links + rename protocol (TRDD-bc16d602)
- Real findings — malformed-YAML frontmatter, phantom file-ref, dead allow_root_dirs key
- Clear MAJOR findings — skill descriptions ≤200 tokens, memgrep build.sh, +x bits
- Refresh-on-err in cmd_auto so a stale slot token can't deadlock rotation
- Clear 2 pre-existing mypy errors in rotator.py
- Audit pass — refresh-on-err heal now updates the state index in lockstep
- Clear the strict-gate findings — relocate memgrep, devitalize, doc fixes (USER publishing directive)
- Round 2+3 — CPV --strict now EXIT 0 (0 CRITICAL/MAJOR/MINOR/NIT)

### Documentation

- Add 8546a187 — baseline-ruleset reconcile + 2 shared follow-ups (janitor#14)
- Add fb4850b5 — user-presence breadcrumb for MANAGER degraded-mode (janitor#15)
- 32acd15f — live evaluation addendum (state-drift fix + refresher verified)
- 8546a187 — record tag-protection 3rd baseline ruleset (maintainer#7, Tier-2)
- 8546a187 — tag-protection consensus CLOSED, final byte-identical spec
- Add 5539cd6e — CRITICAL keychain slot write 128-byte truncation
- 5539cd6e — keychain truncation FIXED + proven (655a870), column->testing
- 5539cd6e — post-compaction re-verification (47 tests pass, fmuaddib slot healthy ~6.3h, emanuele slot dead -121h)
- Add 924645bb — rotator leaves no durable decision log; add persistent rotator.log
- 924645bb — decision log IMPLEMENTED+PROVEN (50496e5), column->testing
- Add d151fe52 — memgrep, a markdown-AST-aware grepper + agent-memory helpers (Rust)
- D151fe52 — memgrep Phase 1 DONE+VERIFIED (0dfbbdd, 10/10 tests, clippy clean)
- D151fe52 — memgrep Phase 2 DONE+VERIFIED (ed68e8e, 16/16 tests)
- D151fe52 — memgrep Phase 3 DONE+VERIFIED (9d030cb, 20/20 tests)
- D151fe52 — memgrep Phase 4 DONE+VERIFIED (21d9bf5, 22/22 tests)
- D151fe52 — memgrep Phase 5a DONE (eedaada); capture Phase 6 boolean composition (find-style + --where)
- D151fe52 — Phase 6a+6b done (boolean Expr tree + --where DSL)
- D151fe52 — 5b-1 wikilink id8-alias done (commit 5b6a6f5)
- D151fe52 — 5b-2 link semijoin done (commit 063a610)
- Add minimal SKILL.md + memory-system measurement TRDD (ce195129)
- Ce195129 — iter 3: precision layer measured (6→2, 100% precision)
- Ce195129 — iter 8: efficiency+precision proven at scale
- Ce195129 — iter 9: skill 25/25 forms execute; goal CONVERGED
- Ce195129 — memory-system phase 2 done (audit + protocol layer + 13 integration issues filed)
- Dfc0959a — rotator 3-layer cascade + keychain-encrypted cross-platform cookies redesign + 17-finding consistency audit
- Dfc0959a — Phase 1 cascade DONE + live manual-rotation diagnosis
- Dfc0959a — Phase 2 mechanics (safe_storage+cookie_vault) DONE
- Dfc0959a — Phase 2c-wiring DONE (opt-in, default off); scrub deferred to Phase 3
- 8546a187 — verified state; baseline-tag-protect impl+tested+USER-ratified; reconcile still gated on maintainer SHA exchange
- 3e1e9b12 — stale-task #151 triage; derived-bug #1 verified already-fixed
- Reflow prose so a wrapped '+ ' doesn't read as a list bullet
- Add TRDD-c77dae09 — memory librarian (background per-topic auto-aggregation)
- C77dae09 — separation of powers + non-destructive correction + read-notes rule
- C77dae09 — lesson WHY is load-bearing + memgrep auto-resolves footnotes
- C77dae09 — memgrep resolved-notes render format (token-economical)
- C77dae09 — per-element OCD/LMD datetimes + notes are searchable elements
- C77dae09 — notes follow their memory on moves + git-backed incremental index
- Add TRDD-4334aad0 — user private memories (/to-user-mem + /search-user-mem)
- 4334aad0 — full invisibility (systemMessage results) + immutable numbering + /share-user-mem
- Teach agents the shipped memory system — read-the-notes rule, correction protocol, memgrep find/dates/index CLI
- Memory-system build status — memgrep engine complete, librarian surface-only landed
- De731408 — monitors: research done, migration SHELVED; v2 frontmatter
- C77dae09 — THREE-SCOPE wiki layers (user/project/local) per USER directive
- Close authoring-schema drift + canonicalize lessons-section spelling (slice B rank 7, TRDD-c77dae09)
- 631fa3de — resolve drift; v2 frontmatter + dated park (guard-mode evaluation)
- 8546a187 — baseline-tag-protect applied LIVE (id 17545495, readback byte-identical)
- Refresh CLAUDE.md project map — add project-map-drift + repomap_generate
- 32acd15f — ROOT CAUSE of the 429-instead-of-rotate incident (CF-1010 keepalive)
- Narrow the stale '1M auto-compact unreliable' claim (CC 2.1.172)
- Close 3e1e9b12 remainders + record 31095269 docs-done

### Features

- Shared orphan-delete UNION + emergency-scrub doc (janitor#14)
- Add ratified baseline-tag-protect (3rd ruleset)
- Persistent decision log so unattended ticks leave a durable trail
- Phase 1 — markdown-AST-aware grep core (TRDD-d151fe52)
- Phase 2 — heading-numbering ranges, --depth, --fm frontmatter (TRDD-d151fe52)
- Phase 3 — inline emphasis, Quarto span-class metadata, lists (TRDD-d151fe52)
- Phase 4 — GFM structure kinds (--node/--no-node + sugar) (TRDD-d151fe52)
- Phase 5a — link graph + index/links/fact subcommands (TRDD-d151fe52)
- Phase 6a — lower flat filters to a boolean Expr tree
- Phase 6b — --where boolean DSL + path/name/fm predicates
- 5b-2 link filters as --where semijoin (links-to/linked-from)
- Add 'recall' subcommand — one-command symptom-ranked memory recall
- Recall precision-first + log convergence (iter 7)
- Recall protocol rule + reference recall/write skills
- Phase 1 — ROTATE→RENEW→REAUTH cascade SSOT (TRDD-dfc0959a)
- Phase 2a — safe_storage cross-platform secret abstraction (TRDD-dfc0959a)
- Phase 2b — cookie_vault sqlite<->jar<->json mechanics (TRDD-dfc0959a)
- Phase 2c-mechanics — keychain cookie snapshot/materialize (TRDD-dfc0959a)
- Phase 2c-wiring — opt-in keychain cookies in the capture flow (TRDD-dfc0959a)
- Footnote capture + resolution + token-economical --with-notes (slice 1)
- Per-element OCD/LMD dates + recall sort & date-range (slice 2)
- Persistent SQLite+FTS5 git-incremental query index (slice 3)
- Add `find`+/- query DSL (mandatory/exclude/wildcard/phrase) + --only-notes
- Private user-memory subsystem with +/- search DSL (TRDD-4334aad0)
- Add memory-librarian detector — SURFACE-only aggregation/conflict candidates
- Host-level user-presence breadcrumb for MANAGER degraded-mode (janitor#15, TRDD-fb4850b5)
- Memgrep release-binaries CI + opt-in auto-recall hook (#16)
- Three-scope wiki layers + scope-leak enforcement (slice A, TRDD-c77dae09)
- Librarian page-shape validator (slice B rank 3, TRDD-c77dae09)
- Librarian broken-links + orphans + MEMORY.md sync (slice B rank 4, TRDD-c77dae09)
- Correction-protocol advisory PostToolUse hook (slice B rank 5, TRDD-c77dae09)
- Librarian scheduled reindex per root (slice B rank 8, TRDD-c77dae09)
- The 3 core wiki skills — MEMORIZE / UPDATE / RECALL (TRDD-bc16d602)
- Directional edges — radiating suns vs receiving terminals (TRDD-bc16d602)
- THE LINK LAW + worked-example wiki + librarian reciprocity audit (TRDD-bc16d602)
- Wiki-by-default rule section + librarian tier-shape checks (TRDD-bc16d602)
- Auto-maintained CLAUDE.md project map — generator + nudge detector + on/off skills (TRDD-e247a349)
- Pillar-1 per-task supervision + subprocess retry (TRDD-7100178d Phase 4)
- Pillar-0 self-resurrection — wedged-daemon kill + crash-loop breaker (TRDD-7100178d Phase 4)

### Miscellaneous

- Devitalize CPV detector-needle FPs — CRITICAL 16→0 (plugin-devitalizer)

### Tests

- Fragment keychain-write fixture secret to clear hygiene gate

