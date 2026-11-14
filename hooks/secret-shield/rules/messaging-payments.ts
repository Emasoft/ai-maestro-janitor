// Messaging and payment service credentials. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const slackToken: Rule = { kind: 'slack-token', pattern: /\b(xox[abposr]-[A-Za-z0-9-]{10,})/g, group: 1 }
export const slackWebhook: Rule = { kind: 'slack-webhook', pattern: /(https:\/\/hooks\.slack\.com\/services\/T[A-Z0-9]+\/B[A-Z0-9]+\/[A-Za-z0-9]+)/g, group: 1 }
// WHY the floor is 16 and there is no trailing \b on stripeSecretKey (TRDD-6A3XW3VO, widened 2026-11-14): the old floor (20) has no recorded reason and no test pinned it. jr-redact hid shorter keys the shield left visible;
// the TRDD-6A3XW3VO evidence report measured 7 such samples (bodies of 16 to 18 characters, all four prefixes sk_live, sk_test, rk_live, rk_test; synthesized from other tools' catalog regexes), all hidden by the 16 floor, and 0 new matches in the three file corpora it scanned (repo text, 40 MB; third-party plugin-cache text, 100 MB, every 8th file).
// Those are matches in files, not a judgement of false hits and not live tool output. The trailing \b is dropped because a key whose tail continues with an underscore (a word character) never reaches a boundary, so the old rule left the whole key visible.
// stripeWebhookSecret below is deliberately unchanged.
export const stripeSecretKey: Rule = { kind: 'stripe-key', pattern: /\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,})/g, group: 1 }
export const stripeWebhookSecret: Rule = { kind: 'stripe-key', pattern: /\b(whsec_[A-Za-z0-9]{24,})\b/g, group: 1 }

// Slack app-level and configuration tokens, standalone (no secret name before them needed).
// Provenance (a): word for word from gitleaks v8.30.1 (MIT, credited in NOTICE), read from the unmodified vendored copy
// _corpus_dev/secret-patterns/repos/lelouchB_cc-scrub/vendor/gitleaks.toml, rules slack-app-token (line 2966),
// slack-config-access-token (line 2980) and slack-config-refresh-token (line 2990). Only change: the leading (?i) flag is
// written as the scoped (?i:...) group, because a leading (?i) throws in Bun. The whole match is the secret, so no capture group.
// These run BEFORE slackToken in patterns.ts: xoxe.xoxp-... holds an xoxp- token that slackToken would otherwise hide
// alone, leaving the xoxe. prefix in view.
export const slackAppToken: Rule = { kind: 'slack-app-token', pattern: /(?i:xapp-\d-[A-Z0-9]+-\d+-[a-z0-9]+)/g }
export const slackConfigAccessToken: Rule = { kind: 'slack-config-token', pattern: /(?i:xoxe.xox[bp]-\d-[A-Z0-9]{163,166})/g }
export const slackConfigRefreshToken: Rule = { kind: 'slack-config-token', pattern: /(?i:xoxe-\d-[A-Z0-9]{146})/g }
