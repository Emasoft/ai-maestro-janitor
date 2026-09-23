---
name: reference_oauth_token_cloudflare_1010_useragent
description: "OAuth rotator can't mint or renew a slot — token exchange / refresh FAILS with HTTP 403 'error code: 1010' / Cloudflare 'banned browser signature' / capture clicks Authorize then dies / renew silently does nothing. The urllib token POST is missing a User-Agent. / why does the token exchange fail after clicking Authorize / what does error code 1010 mean from Cloudflare / does urllib default to Python-urllib user agent / how to fix HTTP 403 banned browser signature on platform.claude.com / does the keepalive refresh also fail with 1010 / how to diagnose a Cloudflare block versus an app error with a bogus grant_type POST / what User-Agent string fixes the rotator token POST / is the browser side a red herring for this failure / tests/test_oauth_token_useragent.py regression guard / commit 6fdbeaa fix reference"
ocd: 2026-06-09
lmd: 2026-09-23
metadata:
  node_type: memory
  type: reference
  tier: component
  functionality: oauth-rotator
publish-globally: false
---

^N68ALRBR [desc: "OAuth rotator token exchange (and keepalive refresh) fails with HTTP 403 Cloudflare error code 1010 because the urllib POST sends no User-Agent, defaulting to Python-urllib which Cloudflare bans", keywords: why_does_the_token_exchange_fail_after_clicking_authorize what_does_error_code_1010_mean_from_cloudflare does_urllib_default_to_python-urllib_user_agent cloudflare_banned_browser_signature capture_clicks_authorize_then_dies renew_silently_does_nothing does_the_keepalive_refresh_also_fail_with_1010 browser_side_is_a_red_herring_for_this_failure token_exchange_fails_with_http_403 rotator_never_mints_or_renews_a_slot, ocd: 2026-06-09, lmd: 2026-09-23]
**Symptom:** the OAuth rotator's browser capture works up to the consent page (CDP-attach
launches real Chrome, cookies decrypt, it clicks **Authorize**) but then the **token
exchange fails with HTTP 403 and `error code: 1010`** (Cloudflare "banned browser
signature"). Same failure on the **keepalive refresh** — so the rotator silently never
mints a new slot and never renews an expiring one (the cascade's RENEW legs are dead).

**Root cause:** the urllib POST to the OAuth token endpoint (`platform.claude.com`) sent **no
`User-Agent`** header → urllib defaults to `Python-urllib/<ver>`, which Cloudflare bans at
that endpoint with 1010. (The browser side is a red herring — the failure is the
script-side urllib request, not the Chrome flow.)

^Q2TAJYB2 [desc: "fix: send User-Agent claude-account-rotator on the token POST in both slot_capture_browser._exchange and rotator.refresh_oauth_token, verified live 2026-06-09, commit 6fdbeaa", keywords: what_user-agent_string_fixes_the_rotator_token_post fix_send_user-agent_claude-account-rotator_on_token_post same_ua_rotator_py_already_uses_for_roles_and_usage regression_guard_tests_test_oauth_token_useragent_py commit_6fdbeaa_fix_reference verified_live_2026-06-09 capture_filed_a_refresh-bearing_slot_after_the_fix account_had_failed_4x_with_1010_before_fix how_to_fix_http_403_banned_browser_signature_on_platform_claude_com fix_applies_to_both_capture_and_keepalive_refresh, ocd: 2026-06-09, lmd: 2026-09-23]
**Fix (verified LIVE 2026-06-09):** send `User-Agent: claude-account-rotator` on the token
POST in BOTH `slot_capture_browser._exchange` and `rotator.refresh_oauth_token` — the SAME
UA `rotator.py` already uses for its `/roles` + `/usage` calls (which pass CF). After the
fix, the capture filed a refresh-bearing slot for the account that had failed 4× with 1010.
Regression guard: `tests/test_oauth_token_useragent.py`. Committed `6fdbeaa`.

^QRMELY03 [desc: "diagnostic probe: POST a bogus grant_type=refresh_token to the token URL — no-UA gives HTTP 403 error code 1010 (Cloudflare block), any real UA gives HTTP 400/429 (past Cloudflare, into the app)", keywords: how_to_diagnose_a_cloudflare_block_versus_an_app_error bogus_grant_type_refresh_token_post_probe no-ua_gives_http_403_error_code_1010 non-default_ua_gives_http_400_invalid_grant_or_429_rate_limit fast_diagnostic_probe_no_real_creds isolates_a_cf_block_from_an_app_response diagnostic_probe_for_1010_vs_app_error distinguish_cloudflare_block_from_app_response who_answers_the_bogus_token_post probe_does_not_need_real_credentials, ocd: 2026-06-09, lmd: 2026-09-23]
**Diagnostic probe (fast, no real creds — isolates a CF block from an app response):** POST a
bogus `grant_type=refresh_token` to the token URL and read WHO answers:
- no-UA → HTTP 403, body contains `error code: 1010` → **Cloudflare block**.
- any non-default UA (`claude-account-rotator` / a browser UA) → HTTP 400 `invalid_grant`
  or 429 `rate_limit_error` → **got past CF to the app** (= the UA is the fix).

^RZEAUK26 [desc: "any new urllib call to a platform.claude.com or claude.ai endpoint behind Cloudflare must set a non-default User-Agent or it 1010s; see also the renew CDP-attach transport and the 429 deadlock this bug caused", keywords: any_urllib_call_behind_cloudflare_needs_a_non-default_user-agent if_you_see_1010_in_rotator_logs_add_the_ua dont_chase_the_browser_cookie_path oauth-rotation-renew-reauth-cascade_cdp-attach_transport 429_deadlock_this_1010_bug_caused every_keepalive_refresh_silently_1010d_slots_lapsed rotator_log_bootstrap_log_1010_symptom is_the_browser_side_a_red_herring_for_this_failure how_to_apply_this_lesson_to_a_new_endpoint related_page_project_rotator_let_429_happen_version_skew, ocd: 2026-06-09, lmd: 2026-09-23]
**Why this matters / how to apply:** any new urllib call to a `platform.claude.com` /
`claude.ai` endpoint behind Cloudflare MUST set a non-default User-Agent or it 1010s. If you
see `1010` anywhere in rotator logs (`rotator.log` / `bootstrap-*.log`), it is THIS — add the
UA, don't chase the browser/cookie path. See also [[oauth-rotation-renew-reauth-cascade]] (the
component page; the CDP-attach transport — the OTHER half of a working renew — is detailed
there and in the LOCAL-scope renew browser-transport note). See also
`[[project_rotator_let_429_happen_version_skew]]` — the 429 deadlock this 1010 bug
caused (every keepalive refresh silently 1010'd → all slots lapsed).

## Notes and lessons learned

(none yet)
