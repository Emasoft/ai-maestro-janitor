---
name: macos-keychain-testing
description: "how do I test keychain code without mocks or a real prompt / real isolated throwaway keychain autouse fixture / stdin 128-byte getpass truncation / hex-dump of non-printable keychain values / where do gotcha 1 and 2 storage corruption live / JANITOR_ROTATOR_KEYCHAIN test env var / prove timeout is honored / prove latch trips after one denial / prove headless skips the primary read / assert zero login keychain access in a test"
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

## Gotcha 1 & 2 — storage corruption (see the sibling note)

^C2VJQR0E [desc:"Gotcha 1 (stdin 128-byte getpass truncation) and Gotcha 2 (hex-dump of non-printable values) live on the sibling reference_macos_security_keychain_gotchas page, invisible to a mocked keychain.", keywords:"stdin_128_byte_getpass_truncation hex_dump_of_non_printable_values pass_value_on_argv_not_stdin base64_wrap_at_store_retrieve_boundary sibling_gotchas_page_reference mocked_keychain_hides_this_bug real_round_trip_test_only_catches_it"]
`[[reference_macos_security_keychain_gotchas]]` — the stdin **128-byte getpass truncation**
(pass the value on argv, not stdin) and the **hex-dump of non-printable values**
(base64-wrap at the store/retrieve boundary). Both invisible to a mocked keychain; caught
only by REAL round-trip tests.

## Testing keychain code (no-mocks, no-prompt)

^AGP6F3R9 [desc:"Test keychain code against a REAL but ISOLATED throwaway keychain, never a mock or the login keychain; autouse fixture creates/deletes it, real_state tests opt out and skip on prompt.", keywords:"real_isolated_keychain_no_mocks throwaway_keychain_autouse_fixture janitor_rotator_keychain_env_var teardown_deletes_throwaway_keychain real_state_marked_tests_opt_out skip_when_keychain_is_prompting prove_timeout_is_honored prove_latch_trips_after_one_denial prove_headless_skips_primary_read zero_login_keychain_access_assert"]
Use a REAL but ISOLATED keychain — never a mock, never the login keychain. The
session-default autouse fixture `create-keychain`s a throwaway, points
`JANITOR_ROTATOR_KEYCHAIN` at it, and deletes it on teardown; `real_state`-marked tests opt
out AND are skipped when the real keychain is prompting. Prove: timeout honored, latch trips
after one denial, headless skips the `-w` primary, zero login-keychain access (assert no
`security … login.keychain` proc via a `ps` before/after guard).

## Governed by

- [[macos-keychain]] — the aspect overview this page details; see it for the model, the
  write-side protocol, and the flood/dead-session incidents.

## Notes and lessons learned


