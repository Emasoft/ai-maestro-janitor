# PROJECT memory index (git-tracked + PUSHED — shared by every contributor)

One line per note: `- [Title](file.md) — hook`. Loaded each session as the canonical
index for the PROJECT scope (`<repo-root>/.claude/project/memory/`). This scope is the
ONLY one that leaves the machine — it carries NO machine-private data (the
`memory-scope-leak` detector enforces this).

## Architecture & subsystems

- [janitor architecture hub](janitor-architecture.md) — how the janitor works: heartbeat + global daemon, the scope invariant, the detector roster, pattern libs, resilience pillars, state conventions.
- [The wiki-memory system](memory-system.md) — how the markdown wiki-memory works: the 3-scope model, the note format, the memgrep engine, the three skills, the two heartbeat detectors, the install procedure.
- [janitor publish pipeline](janitor-publish-pipeline.md) — the fail-fast release pipeline (a CPV plugin): gate order, the CPV-only validate policy, the admin-bypass-for-publish branch model.
- [OAuth rotation — ROTATE→RENEW→REAUTH cascade](oauth-rotation-renew-reauth.md) — how the rotator keeps a session alive across N paid subs: the 3-layer cascade, keychain storage, the commands, the documented past failures.

## References & lessons

- [memgrep links --to/--from semantics](reference_memgrep_links_to_from_semantics.md) — `--to NOTE` = its OUT-links, `--from NOTE` = its BACKLINKS (intuition inverts them); `fm.KEY` matches any depth; `--where` is main-grep-only.
- [macOS `security` keychain gotchas](reference_macos_security_keychain_gotchas.md) — a secret stored via `security` truncates at 128 bytes (stdin getpass cap → put value on argv) or returns HEX for non-printable/unicode (→ base64-wrap).
- [OAuth token CF-1010 / missing User-Agent](reference_oauth_token_cloudflare_1010_useragent.md) — rotator can't mint/renew a slot; token POST dies with HTTP 403 "error code 1010" (Cloudflare). The urllib POST sent NO User-Agent → add `User-Agent: claude-account-rotator`.
- [CPV `.claude/` gitignore FP blocks publish](reference_cpv_dotclaude_gitignore_fp.md) — CPV `--strict` flags "`.gitignore` missing coverage for `.claude/`" because `git check-ignore .claude` can't pass while we track `.claude/project/memory/`. Filed CPV #120 (unsatisfiable, not our bug); publish auto-unblocks on the CPV fix.

## Project history & coordination

- [Peer-agent consensus](feedback_peer_agent_consensus.md) — coordinating with the maintainer/manager peer Claudes on GitHub: seek consensus, never directives; self-identify; poll janitor #14 ↔ maintainer #7.
- [Memory system is more than memgrep](feedback_memory_system_is_more_than_memgrep.md) — the memory system = {tool memgrep + rules + skills + optional hooks}, NOT just the binary; reference impl lives in this repo.
- [janitor publish — gate cleared, v0.7.x shipped](project_janitor_publish_blocked_cpv_fps.md) — RESOLVED: CPV --strict exit 0, v0.7.0+v0.7.1 published. The unblock recipe (devitalize-or-remove, never exempt; tools/→scripts/ move).
- [janitor CC-changelog currency](project_janitor_cc_changelog_currency.md) — triaged CC 2.1.98→2.1.173 vs the janitor: 0 BREAKS; rate-limit-survival + CronCreate floor re-verified; fixed the 1 stale fact; optional improvement backlog.
- [rotator let a 429 happen (version skew)](project_rotator_let_429_happen_version_skew.md) — rotator deadlocks "all accounts maxed" while an account is fresh because the RUNNING daemon predated the CF-1010 fix → slots lapse. RESOLVED by the v0.7.x publish.
- [wikimem — project overview](ai-maestro-janitor-overview.md) — the curated wiki that coexists with this file; recall by symptom: `memgrep recall "<symptom>" <memdir>`
