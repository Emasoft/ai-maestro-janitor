// Messaging and payment service credentials. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const slackToken: Rule = { kind: 'slack-token', pattern: /\b(xox[abposr]-[A-Za-z0-9-]{10,})/g, group: 1 }
export const slackWebhook: Rule = { kind: 'slack-webhook', pattern: /(https:\/\/hooks\.slack\.com\/services\/T[A-Z0-9]+\/B[A-Z0-9]+\/[A-Za-z0-9]+)/g, group: 1 }
export const stripeSecretKey: Rule = { kind: 'stripe-key', pattern: /\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,})\b/g, group: 1 }
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
