---
name: oauth-rotation-renew-reauth-keychain
description: "Where the rotator's OAuth tokens and cookies actually live — the cross-platform safe-storage backends (macOS Keychain, Linux Secret Service, Windows DPAPI), StoreResult's fail-closed OK/NO_BACKEND/FAILED semantics, base64-wrapping, the four keychain services (live credential, per-account slots, redundant mirrors, state.json metadata-only), and why an absent plaintext slots/ directory is correct by design, not a bug."
ocd: 2026-06-13
lmd: 2026-09-17
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: oauth-rotator
  globs:
    - "scripts/lib/rotator_usage.py"
publish-globally: false
split-lineage: 9870cb5403f14c3b8f062f0bc8cebb5d
---

Where the rotator's credentials live: the keychain architecture (machine-
private values, project-knowledge shape). Part of
[[oauth-rotation-renew-reauth]] — the component overview.

## Where credentials live (keychain architecture — machine-private = LOCAL scope)

^D0ZYQLAI [desc:"Cookies and OAuth tokens are both stored encrypted in the OS safe-storage (macOS Keychain, Linux Secret Service, Windows DPAPI), auto-selected per platform, never plaintext-on-disk.", keywords:"where_are_oauth_tokens_and_cookies_stored safe_storage_backend_per_platform macos_security_add_generic_password linux_secret_tool_libsecret windows_dpapi_powershell_not_round_trip_verified no_backend_present_never_silently_drop_plaintext", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
Per USER directive #2, **cookies AND OAuth tokens are BOTH stored ENCRYPTED in the OS
safe-storage, cross-platform — never plaintext-on-disk Chrome-profile sqlite.** The
keychain-stored cookie is the source used to switch profiles (inject into the Chrome
profile before a capture, scrub after). Backends (auto-selected,
`scripts/oauth_rotator/safe_storage.py`; override for tests via
`CLAUDE_SAFE_STORAGE_BACKEND`):
- macOS — `security add/find/delete-generic-password` (Keychain).
- Linux — Secret Service / libsecret (`secret-tool`).
- Windows — per-user DPAPI via PowerShell (implemented, not yet round-trip-verified).
- none present → `store` returns `NO_BACKEND` so the caller decides its fallback; it MUST
  NEVER silently drop a plaintext secret.

^HIUGT3MA [desc:"StoreResult is a three-valued fail-closed type (OK/NO_BACKEND/FAILED) so a write never drops a plaintext secret; every secret is base64-wrapped; cookie_vault.py never decrypts Chrome's cookie blobs.", keywords:"store_result_ok_no_backend_failed why_base64_wrap_the_secret_before_storing cookie_vault_never_decrypts_chrome_cookies fail_closed_never_drop_plaintext_token", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
`StoreResult` is three-valued for fail-closed semantics: `OK` (accepted), `NO_BACKEND`
(no store present — documented plaintext fallback is legit), `FAILED` (a store IS present
but the write failed — the caller MUST fail closed, NEVER drop a plaintext token). Every
secret is base64-wrapped at the public API (see the hex-dump lesson). The cookie path
(`cookie_vault.py`) extracts/injects Chrome cookie rows without ever decrypting them (it
carries Chrome's OSCrypt-encrypted blobs, faithfully copying all NOT-NULL columns).

^HZF6CKW1 [desc:"Four keychain services hold rotator data: the live credential, per-account slot backups, redundant corruption-recovery mirrors, and a metadata-only state.json, never the secret token.", keywords:"which_keychain_services_does_the_rotator_use claude_code_credentials_vs_claude_code_rotator_slot redundant_keychain_mirrors_livebak state_json_holds_metadata_only_never_the_token integrity_repair_runs_every_tick", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
Keychain services used (the values are LOCAL/machine-private; only the SHAPE is project
knowledge):
- LIVE credential: service `Claude Code-credentials` (what Claude Code itself reads).
- SLOTS (per-account backups): service `Claude Code-rotator-slot`, encrypted at rest.
- Redundant mirrors (TRDD-7100178d, Pillar 2): `…-rotator-slot`-backup + `…-livebak`
  (live-cred mirror); `_repair_integrity` / `read_live_blob` restore the primary from
  these on corruption (the integrity-repair pass runs at the start of every tick).
- `state.json` holds slot **metadata only** (`fp`, `expires_at`, `captured_at`,
  `live_email`, `live_fp`) — NEVER the secret token.

^IIMB4R89 [desc:"A missing plaintext slots/<email>.json dir is correct by design; legacy slots are migrated into the keychain then deleted; state dir is the plugin DATA dir with a legacy-root fallback.", keywords:"why_is_there_no_slots_directory_is_that_a_bug plaintext_slots_migrated_into_keychain_then_deleted state_dir_is_claude_plugin_data_oauth_rotator resolve_chrome_profiles_via_print_profiles_root", type: project, ocd: 2026-06-13, lmd: 2026-09-01]
An **ABSENT plaintext `slots/<email>.json` dir is CORRECT, not a bug** — the legacy
plaintext slots (`$HOME/.claude/account-rotator/slots/`, and the data-dir
`oauth-rotator/slots/`) are migrated INTO the keychain then DELETED by design
(`migrate-slots` / `delete-plaintext-slots`). Do not chase the missing dir. The
0600-file fallback is reachable ONLY when no keychain/keyring exists (off-mac without
libsecret). State dir is `${CLAUDE_PLUGIN_DATA}/oauth-rotator/` (canonical), with a read
fallback to the legacy standalone root + one-time migration. [^5] Resolve Chrome profiles via
`rotator.print-profiles-root` / `_profiles_root()`, never a hardcoded path.


## Governed by

- [[oauth-rotation-renew-reauth]] — the rotator component overview this page
  details.

## Notes and lessons learned

[^5]: [id:ATOM-MG05-0005, status:valid, keywords:"rotator_creds_in_os_keychain no_slots_dir_is_by_design stop_re_deriving_architecture", ocd:2026-06-06, lmd:2026-06-13] **The keychain-storage design is re-derived every
  session (the cost this page removes).** An `ls` of the data dir shows no `slots/` and no
  tokens, which repeatedly leads a fresh session to suspect "the rotator has no
  credentials" — wrong: they are in the OS keychain by design. Verified 2026-06-06 by
  reading the `rotator.py` header after wrongly chasing the missing `slots/` dir. Recall
  from the symptom "rotator failed / where are the creds", land here, and read
  `oauth-health` for live state rather than re-deriving the architecture.

