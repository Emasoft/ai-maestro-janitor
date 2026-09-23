---
name: reference_macos_security_keychain_gotchas
description: "Storing a secret in the macOS keychain via `security` came back TRUNCATED (only 128 bytes) or as a HEX string / garbled — value doesn't round-trip. Two `security add/find-generic-password` gotchas: stdin 128-byte getpass cap, and hex-dump on non-printable/unicode values. / why is my stored secret truncated to 128 bytes / security add-generic-password -w with no value uses getpass with a hard 128 byte buffer / why does find-generic-password -w return a hex string instead of my value / how to store a non-ASCII or multi-KB secret in the macOS keychain / should I pass the secret on argv or via stdin to security / does base64-wrapping a secret avoid the hex-dump gotcha / an 8.8KB OAuth blob was stored as 128 bytes of corrupt JSON / value read back does not match what was stored / are these gotchas visible under a mocked keychain / what is safe_storage.py StoreResult / trailing newline ambiguity in keychain values / secret-tool and DPAPI backends and base64 uniformity / see also macos-keychain aspect page for the ACL prompt flood"
ocd: 2026-06-09
lmd: 2026-09-23
metadata:
  node_type: memory
  type: reference
  tier: component
  functionality: oauth-rotator
publish-globally: false
---

Two non-obvious `security` (macOS keychain CLI) behaviors that silently corrupt a stored
secret. Both caught by REAL round-trip tests building `safe_storage.py` (TRDD-dfc0959a);
both invisible to a mocked keychain.

^DNC46Y1O [desc: "security add-generic-password -w with no value reads via getpass with a hard 128-byte cap, silently truncating a larger secret; fix by passing the value on argv", keywords: why_is_my_stored_secret_truncated_to_128_bytes security_add-generic-password_-w_no_value_uses_getpass getpass_hard_128_byte_buffer stdin_form_truncates_secret an_8.8kb_oauth_blob_stored_as_128_bytes_of_corrupt_json should_i_pass_the_secret_on_argv_or_via_stdin fix_pass_value_on_argv_not_stdin rotator_never_worked_bug_TRDD-5539cd6e brief_ps_exposure_is_acceptable_for_these_items keychain_secret_truncated_to_128_bytes, ocd: 2026-06-09, lmd: 2026-09-23]
**1. stdin form truncates at 128 bytes (getpass cap).** `security add-generic-password -w`
with **no value** reads the password from stdin via macOS `getpass()`, whose buffer is a
hard **128 bytes** → it SILENTLY TRUNCATES any larger secret. This was the original
"rotator never worked" bug (TRDD-5539cd6e): an 8884-byte OAuth blob stored as 128 bytes of
corrupt JSON. **Fix:** pass the value ON ARGV (`security add-generic-password -U -s <svc>
-a <acct> -w <data>`). The brief `ps` exposure is acceptable for these items (they're already
readable by any same-user process via `find-generic-password -w` with no prompt).

^I4M17P5G [desc: "find-generic-password -w hex-dumps any non-printable or unicode stored value instead of the raw value; fix by base64-wrapping the secret at the store/retrieve boundary", keywords: why_does_find-generic-password_-w_return_a_hex_string value_read_back_does_not_match_what_was_stored non-printable_or_unicode_values_hex_dumped does_base64-wrapping_a_secret_avoid_the_hex-dump_gotcha how_to_store_a_non-ascii_or_multi-kb_secret fix_base64-wrap_the_secret_at_store_retrieve_boundary sidesteps_trailing_newline_ambiguity uniform_across_linux_secret-tool_and_windows_dpapi value_came_back_as_hex_or_garbled two_security_keychain_gotchas_stdin_cap_and_hex_dump, ocd: 2026-06-09, lmd: 2026-09-23]
**2. `find-generic-password -w` HEX-DUMPS non-printable / unicode values.** When a stored
generic-password contains bytes that aren't plain printable ASCII (newlines, tabs, UTF-8,
binary), `security ... -w` returns a **hex string** (`6c696e6531…`) instead of the raw value
→ the read-back doesn't match what you stored. **Fix:** base64-wrap the secret at your
store/retrieve boundary so the keychain only ever holds printable ASCII (decode on read).
This also sidesteps trailing-newline ambiguity and is uniform across Linux `secret-tool` /
Windows DPAPI backends.

**See also `[[macos-keychain]]`** — the aspect page holding the SAFE KEYCHAIN PROTOCOL
(single choke-point + timeout + headless fail-fast + one-shot denied-latch) and **gotcha 3,
the ACL-prompt FLOOD** (the 2026-07-09 incident: hundreds of "Security wants to use the login
keychain" dialogs after an account rotation). These two storage gotchas are gotchas 1 & 2 of
that page.

**How to apply:** any code that puts a non-trivial / non-ASCII secret into the macOS keychain
via `security` MUST (a) put the value on argv, not stdin, and (b) base64-wrap it. The
canonical impl is `scripts/oauth_rotator/safe_storage.py` (store/retrieve, three-valued
fail-closed `StoreResult`). Symptom to recall from: "keychain secret truncated to 128 bytes"
or "value came back as hex / garbled". See also [[oauth-rotation-renew-reauth-operations]] (the
rotator component page that uses this keychain layer).

## Notes and lessons learned

(none yet)
