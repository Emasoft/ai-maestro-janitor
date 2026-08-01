---
name: reference_macos_security_keychain_gotchas
description: "Storing a secret in the macOS keychain via `security` came back TRUNCATED (only 128 bytes) or as a HEX string / garbled — value doesn't round-trip. Two `security add/find-generic-password` gotchas: stdin 128-byte getpass cap, and hex-dump on non-printable/unicode values."
ocd: 2026-06-09
lmd: 2026-06-13
metadata:
  node_type: memory
  type: reference
  tier: component
  functionality: oauth-rotator
---

Two non-obvious `security` (macOS keychain CLI) behaviors that silently corrupt a stored
secret. Both caught by REAL round-trip tests building `safe_storage.py` (TRDD-dfc0959a);
both invisible to a mocked keychain.

**1. stdin form truncates at 128 bytes (getpass cap).** `security add-generic-password -w`
with **no value** reads the password from stdin via macOS `getpass()`, whose buffer is a
hard **128 bytes** → it SILENTLY TRUNCATES any larger secret. This was the original
"rotator never worked" bug (TRDD-5539cd6e): an 8884-byte OAuth blob stored as 128 bytes of
corrupt JSON. **Fix:** pass the value ON ARGV (`security add-generic-password -U -s <svc>
-a <acct> -w <data>`). The brief `ps` exposure is acceptable for these items (they're already
readable by any same-user process via `find-generic-password -w` with no prompt).

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
or "value came back as hex / garbled". See also [[oauth-rotation-renew-reauth]] (the
rotator component page that uses this keychain layer).

## Notes and lessons learned

(none yet)
