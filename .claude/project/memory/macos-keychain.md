---
name: macos-keychain
description: "macOS keychain dialog opened hundreds of times / 'Security wants to use the login keychain' with no Always Allow button / cannot type — a keychain prompt FLOOD, often right after rotating/re-logging a Claude account. Prompts KEEP coming even after I paused the rotator / iCloudNotificationAgent is ALSO asking for the login keychain / I typed my password (or ran `security unlock-keychain`) and it is NOT sticking / how do I stop the keychain popups and keep them from coming back. The safe `security` protocol every keychain interaction MUST follow so this is structurally impossible: single choke-point, hard timeout, headless fail-fast, one-shot denied-latch, opt-in gate on EVERY keychain-reading path (detectors included), temp-keychain test isolation; plus the user-side fix for a LOCKED login keychain: `security unlock-keychain` + `set-keychain-settings` no-auto-lock (in a real terminal — the Claude lean-ctx wrapper blocks `security`). / all Claude agents on the machine suddenly report Not logged in / security list-keychains says parameters not valid / does /login fix a dead security session / what is a dangling keychain entry from dotenclave unlock / why does the search list get replaced in my shell rc / SecKeychainItemSetAccess prompts on every write / add-generic-password -U with -A or -T on an existing item hangs / why did rotation die overnight after one transient keychain error / what is the denied-latch TTL half-open circuit breaker / does pausing the rotator opt-in stop every detector from reading the keychain / why did the flood come back days after I published the fix / what is a staged launchd keepalive closure and why does it revive the old flooder / keychain-health detector reachability check every heartbeat / where is the write-side ACL prompt fix / where is the dead security session gotcha / where is the keychain testing discipline"
ocd: 2026-07-09
lmd: 2026-09-23
metadata:
  node_type: memory
  type: reference
  tier: aspect
  functionality: keychain-safety
publish-globally: false
split-lineage: 633457257a6c4a5882f1ed46b06af84a
---

^1TJAEIDZ [desc:"The macOS keychain is a shared ACL-guarded GUI-prompting store; items keyed by service/account, ACLs gate secret reads, and why a uv-cached python path never earns a durable Always-Allow.", keywords:"keychain_model login_keychain_default search_list generic_password_item service_account_label acl_gates_secret_read always_allow_never_sticks uv_cached_python_path_changes_every_version claude_code_credentials_label rotator_slot_label security_wants_to_use_login_keychain"]
The macOS keychain (`/usr/bin/security` CLI + the `Security.framework` under it) is the
only place the janitor persists secrets (OAuth account-rotator slots + the live Claude
credential mirror). It is a **shared, ACL-guarded, GUI-prompting** store — three properties
that each have bitten this project. This aspect page is the SAFE PROTOCOL every keychain
interaction MUST follow, plus the three known gotchas. It **governs** every element that
touches the keychain (see `## Applies to`).

## The model (what you're actually talking to)

- **Keychains** are files: the **login** keychain (`~/Library/Keychains/login.keychain-db`,
  the default) + any named keychain you `security create-keychain`. `security` operates on
  the **search list**; the trailing positional arg pins a specific keychain.
- **Items** are `generic-password` records keyed by service (`-s`) + account (`-a`). The
  janitor uses labels `Claude Code-credentials` (the live login, **Claude-only ACL**) and
  `Claude Code-rotator-slot` (per-account rotator slots).
- **ACLs** gate each item: which binaries may read the SECRET without a GUI prompt. An item
  created by Claude's own `/login` gets a **Claude-Code-only** ACL. A `-w` secret read by any
  *other* binary raises the **"Security wants to use the login keychain"** password/allow
  dialog. macOS can only offer **"Always Allow"** for a **stable binary identity** — a
  uv-cached python (`~/.cache/uv/builds-*/bin/python`, path changes every version) NEVER gets
  a durable Always-Allow, so it **re-prompts forever**.

This page is a MAP — the safe protocol at a glance plus where the detail lives:

- [[macos-keychain-write-protocol]] — the WRITE-side ACL prompt gotcha (3b) and the mandatory
  SAFE KEYCHAIN PROTOCOL every `security` interaction must follow (denied-latch circuit
  breaker, hard timeout, headless fail-fast, scope lever, `-T`-accessible mirrors).
- [[macos-keychain-incidents]] — the two fleet-down incidents this page's protocol was built
  from: Gotcha 3 (the ACL-PROMPT FLOOD after rotating an account) and Gotcha 4 (the DEAD
  SECURITY SESSION, `Not logged in` fleet-wide), the full `## Governed by` / `## Applies to`
  edge list, and the superseded pre-consolidation write-up.
- [[macos-keychain-testing]] — the sibling storage-corruption gotchas (1 & 2) and the no-mocks,
  no-prompt discipline for testing keychain code.

## Governed by

- `[[debugging-methodology]]` (USER scope) — the general debugging discipline this page's
  incidents kept teaching the hard way. Those lessons are NOT restated here: a case page holds
  facts about ITS case, and a transferable way of working belongs to the one page that owns it,
  or it ends up scattered across every page that happened to teach it and owned by none.

## Applies to

- The rotator's slot/mirror keychain layout is covered by a LOCAL-scope note, deliberately NOT
  linked from here: this page is pushed, so naming a machine-private page would publish that
  name. The relationship belongs on that note's own `## Governed by`, which may legally point UP.
- `[[oauth-rotation-renew-reauth-keychain]]` — the ROTATE→RENEW→REAUTH component that reads
  these items.
- `[[reference_macos_security_keychain_gotchas]]` — the storage-corruption sibling (gotchas 1
  & 2); see also [[macos-keychain-testing]].
- `[[janitor-keepalive-test-isolation-fsevents]]` — the OS-keepalive staging mechanism; see
  [[macos-keychain-incidents]] for the root-cause detail of the STALE staged closure that kept
  the pre-fix flooder alive, and the full byte-for-byte `## Applies to` edge list.

## Superseded


## Notes and lessons learned


