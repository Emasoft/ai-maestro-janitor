---
trdd-id: X6I04SAO
title: the daemon's Python has no CA bundle, so every slot refresh fails TLS and the rotator stays put while the user rotates by hand
column: testing
created: 2026-09-02T15:57:54+0200
updated: 2026-09-03T11:09:13+0200
review-after: 2026-09-05
current-owner: main-session
task-type: bugfix
scope: project
severity: critical
relevant-rules: []
implementation-commits: [c3beaf04, 301fbcec]
npt: []
eht: []
---

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-03T11:09:13+0200

**Board reconciliation (2026-09-03 11:09):** boxes 1-3 remain proven (unchanged, self-consistent
with STATE). Box 4 stays open: `rotator.log:806` shows a fresh SCOPED wall today
(`2026-09-03T10:15:46+0200 auto: switched emanuele.sabetta@gmail.com -> ipazia.emasoft@gmail.com
… +SCOPED[7d/Fable=90%] -> rotate`), and it rotated cleanly — but `daemon.log` in the same
`oauth-rotator-tick` window (10:15:43-10:15:53) shows only `rotation-esc: cannot read the pane
for IOSVoice_bak — skipped`, no `rotation-esc: FIRED ESC` for any pane. This was a proactive
scoped switch (util still healthy, no pane was actually wedged/blocked at the time), not the
"scoped wall + paired ESC" pairing the box needs — genuinely still unobserved.
`review-after: 2026-09-05` set.

## ⏵ PRIOR STATE — 2026-09-02 16:12

- **User report 15:50:** "I had to rotate the account manually again." Diagnosed, not guessed.
- **Root cause (verified first-hand):** the launchd daemon runs
  `/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12` (python.org build, first
  switched to on 2026-08-05 and re-applied 08-16 — the two `bak-pre-signed-python-*` plists
  are the PRE-switch snapshots; the onset of the TLS failure itself is UNKNOWN because rotator.log rotates daily; the oldest
  evidence is `rotation-stuck.json`, written once on 2026-08-25). That build ships with
  `etc/openssl/cert.pem` MISSING until its "Install Certificates.command" is run, and
  `ssl.get_default_verify_paths()` points nowhere else. Reproduced with the daemon's exact
  interpreter and env (`env -i HOME=… PATH=/usr/bin:/bin:/usr/sbin:/sbin`): a POST to the OAuth
  token endpoint dies with `[SSL: CERTIFICATE_VERIFY_FAILED] unable to get local issuer
  certificate`. `classify_refresh_failure` labelled that URLError `network — retryable,
  benign`, so the two rotated logs show ≥878 `[keepalive] <slot>: refresh failed (network)`
  lines on 2026-09-02 alone (454 in `rotator.log.1` 06:33–11:23 + 424 in `rotator.log` by
  15:50; the code comment and the fix commit say "454" — that was one file's count, the
  review fork's correction), both spare slots every minute, both slot access tokens expired
  (`oauth-health` days −4.0 / −3.7), and every `auto:` tick ended `has no usable slot twin to
  probe — staying put this tick (fail-safe)`. A fail-safe that always refuses is no guard. The
  token endpoint is reachable from a shell (uv-managed Python has a bundle), which is why it
  never reproduced outside the daemon. `rotation-stuck.json` has said
  `all-accounts-maxed … refresh-failed` since 2026-08-25.
- **Mitigation applied on this machine 15:54** — the exact symlink python.org's own installer
  creates: `etc/openssl/cert.pem → site-packages/certifi/cacert.pem`. The same probe then
  returns HTTP 400 (TLS OK). Reversible: remove the symlink.
- **Durable fix (this card):** shared `scripts/lib/tls_context.verifying_context()` — defaults,
  then certifi, then the OS bundles; never disables verification — passed as `context=` at
  every daemon-side https `urlopen` (rotator ×2, usage_probe, notify, slot_capture_token,
  slot_capture_browser exchange). New cause `REFRESH_FAIL_TLS = "tls"` so a trust-store
  failure is named, not filed under "network". Tests: `tests/test_tls_context.py` (fallback
  proven with an empty default store) + a classify test.
- **Confirmed causal, not confounded by the 15:48:54 manual login** (the review fork's
  challenge, settled from the log): from 15:49:06 to 15:54:41 — AFTER the manual login and
  BEFORE the symlink took effect — every tick still ended `live account ema***…
  has no usable slot twin to probe — staying put`. The first tick after the symlink,
  15:55:50, logged `keepalive: refreshed fmu***, ipa***` (the two spare-slot accounts)
  (emitted only after `refresh_oauth_token` returned an access token AND `write_slot`
  succeeded — read in `_keepalive_refresh`), and at 15:55:53 the same tick ended `live
  ema*** 5h=25% 7d=4% — within limits`. `oauth-health` moved from
  `days=−4.0 / −3.7` to `0.3` on both spare slots. The twin path is the same TLS call: `read_slot`
  → `_blob_locally_expired` → `_refresh_and_heal_slot` → `refresh_oauth_token` → `urlopen`
  (rotator.py 1827–1840), so a fresh login could not have unblocked it on its own.
- **Not a second fault:** the `primary live credential UNREADABLE from this context` line on
  every tick is the DESIGNED headless path (TRDD-7PYTX4E9 F1 — the daemon never `-w`-reads the
  live keychain item so it never raises a GUI prompt; it uses the `-livebak` mirror and probes
  the live account through its slot twin). It appeared 226 times before the incident, identical.
  `auto: no live credential` 13:06–14:21 coincided with the manual re-login. Nothing to fix; the
  wording is alarming for a normal state and could be softened later.
- **Criterion 4 (the wall the user actually hit was MODEL-scoped — Fable):** the review fork
  asked whether the rotator evaluates that bucket at all, since the `auto:` line prints only
  5h/7d. It does: `cmd_auto` carries the model-scoped trigger from `f185e521` (owner report
  2026-08-15; rotator.py ~384–391 and ~1956–2012 — `token_burn.model_fallback_verdict`,
  scoped ≥ `SCOPED_SWITCH_AT` rotates ONLY onto a scoped-clear alternate and appends
  `+SCOPED[label=util%]` to the live description; with no scoped-clear target it stays put and
  leaves `/model opus` to the fallback detector — the scoped half per f185e521's record and
  the `scoped_only` block, not re-traced line by line here). That evaluation never ran today:
  `cmd_auto` returns before it when the live account's slot twin cannot be read or refreshed
  (rotator.py 1827–1840, read), and the refresh was the TLS call. So today's failure was
  upstream of the trigger, not the trigger. Still UNOBSERVED on a real wall since the fix —
  the box stays open until a scoped wall rotates on its own.
- Wikimem: ATOM-V316-ZKU6 on `oauth-rotation-renew-reauth` (recall: "had to rotate manually
  again", "refresh failed (network) every tick").
- **20:55 — shipped in v3.4.11 (c3beaf04 is in the tag) but CI is RED on it**, so it is NOT
  installed: CPV's CI pyright has no `certifi`, and the optional `import certifi` in
  `tls_context.py` was one MINOR (`reportMissingImports`) — exit 3 under `--strict`. The
  local publish gate passed because this box's venv happens to carry certifi. Fixed in
  `301fbcec` (`# type: ignore[import-not-found]`, the repo's existing form for optional
  imports; proven against a fresh certifi-less venv: 1 error before, 0 after). Ships in 3.4.12.
- **Mixed-commit note:** `c7a8d46a` (this card + its wikimem) ALSO carries the Sonnet
  atomize chore's rewrite of three unrelated memory pages (macos-keychain,
  janitor-fleet-control-plane, three-pillars-rules-ownership) — validated NONE, only `lmd:`
  lines dropped, but a `git show c7a8d46a` is not a clean read of this card's change.
- **Tonight's wall (20:38–20:47) is evidence for box 4, split:** the rotator DID rotate on its
  own twice (20:38:45 5h burn, 20:39:50 `SCOPED[7d/Fable=100%]` → emanuele; slot refreshes
  succeeding, so THIS card's fix holds on this machine via the symlink). The user still ended
  up rotating by hand because the blocked panes never got the ESC — the typing gate, a
  different defect, filed as TRDD-NACCL0CB (proposal, needs USER ruling).
- **21:42 — v3.4.12 shipped (CI green ×5), installed, daemon restaged 21:28:04 onto it.**
  Boxes 1–3 verified against the DATA copy under the daemon's own interpreter + env:
  `verifying_context()` → 136 CAs (default store also 136, the symlink stands); an SSL-wrapped
  URLError classifies `tls`, a plain one `network`; 0 `refresh failed (network)` lines since
  the restage and `oauth-health` shows all three slots `refresh=yes status=ok`.
- **NEXT ACTION:** box 4 only — the next scoped wall on this host rotates AND the panes get
  their ESC (TRDD-NACCL0CB's live box) with no human keystroke; then `published`.

## Acceptance criteria

- [x] Under the daemon's interpreter + env, `verifying_context().cert_store_stats()["x509_ca"] > 0`.
      (2026-09-02 21:42: 136 — and, with the default store EMPTIED via `SSL_CERT_FILE`/
      `SSL_CERT_DIR` so the 15:54 symlink is out of the picture, default = 0 while
      `verifying_context()` = 136: the code's fallback itself, not the symlink. The 136 is
      certifi's bundle (certifi alone 136, `/etc/ssl/cert.pem` alone 128); with certifi
      hidden from the import the OS rung alone gives 128 — both rungs exercised.)
- [x] A URLError wrapping an SSLError classifies as `tls`, a plain URLError still as `network`.
      (2026-09-02 21:42: verified on the 3.4.12 DATA copy under the daemon's interpreter.)
- [x] `rotator.log` shows slot refreshes succeeding again (no `(network)` line on a tick
      after the fix) and `oauth-health` shows both spare slots with `days=` > 0.
      (2026-09-02 21:42: 0 `(network)` lines since the 21:28 restage; all slots `days=0.3 status=ok`.)
- [ ] The next scoped wall rotates automatically — the user does not rotate by hand.
      (2026-09-02 20:39:50: the rotation half is OBSERVED; the by-hand half failed for the
      TRDD-NACCL0CB reason, not this card's. Box stays open until both halves hold.)

## Approval log

## Notes and lessons learned
