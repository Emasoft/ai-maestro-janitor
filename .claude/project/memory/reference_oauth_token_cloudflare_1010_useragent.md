---
name: reference_oauth_token_cloudflare_1010_useragent
description: "OAuth rotator can't mint or renew a slot — token exchange / refresh FAILS with HTTP 403 'error code: 1010' / Cloudflare 'banned browser signature' / capture clicks Authorize then dies / renew silently does nothing. The urllib token POST is missing a User-Agent. / why does the token exchange fail after clicking Authorize / what does error code 1010 mean from Cloudflare / does urllib default to Python-urllib user agent / how to fix HTTP 403 banned browser signature on platform.claude.com / does the keepalive refresh also fail with 1010 / how to diagnose a Cloudflare block versus an app error with a bogus grant_type POST / what User-Agent string fixes the rotator token POST / is the browser side a red herring for this failure / tests/test_oauth_token_useragent.py regression guard / commit 6fdbeaa fix reference"
ocd: 2026-06-09
lmd: 2026-06-13
metadata:
  node_type: memory
  type: reference
  tier: component
  functionality: oauth-rotator
publish-globally: false
---

**Symptom:** the OAuth rotator's browser capture works up to the consent page (CDP-attach
launches real Chrome, cookies decrypt, it clicks **Authorize**) but then the **token
exchange fails with HTTP 403 and `error code: 1010`** (Cloudflare "banned browser
signature"). Same failure on the **keepalive refresh** — so the rotator silently never
mints a new slot and never renews an expiring one (the cascade's RENEW legs are dead).

**Root cause:** the urllib POST to the OAuth token endpoint (`platform.claude.com`) sent **no
`User-Agent`** header → urllib defaults to `Python-urllib/<ver>`, which Cloudflare bans at
that endpoint with 1010. (The browser side is a red herring — the failure is the
script-side urllib request, not the Chrome flow.)

**Fix (verified LIVE 2026-06-09):** send `User-Agent: claude-account-rotator` on the token
POST in BOTH `slot_capture_browser._exchange` and `rotator.refresh_oauth_token` — the SAME
UA `rotator.py` already uses for its `/roles` + `/usage` calls (which pass CF). After the
fix, the capture filed a refresh-bearing slot for the account that had failed 4× with 1010.
Regression guard: `tests/test_oauth_token_useragent.py`. Committed `6fdbeaa`.

**Diagnostic probe (fast, no real creds — isolates a CF block from an app response):** POST a
bogus `grant_type=refresh_token` to the token URL and read WHO answers:
- no-UA → HTTP 403, body contains `error code: 1010` → **Cloudflare block**.
- any non-default UA (`claude-account-rotator` / a browser UA) → HTTP 400 `invalid_grant`
  or 429 `rate_limit_error` → **got past CF to the app** (= the UA is the fix).

**Why this matters / how to apply:** any new urllib call to a `platform.claude.com` /
`claude.ai` endpoint behind Cloudflare MUST set a non-default User-Agent or it 1010s. If you
see `1010` anywhere in rotator logs (`rotator.log` / `bootstrap-*.log`), it is THIS — add the
UA, don't chase the browser/cookie path. See also [[oauth-rotation-renew-reauth]] (the
component page; the CDP-attach transport — the OTHER half of a working renew — is detailed
there and in the LOCAL-scope renew browser-transport note). See also
`[[project_rotator_let_429_happen_version_skew]]` — the 429 deadlock this 1010 bug
caused (every keepalive refresh silently 1010'd → all slots lapsed).

## Notes and lessons learned

(none yet)
