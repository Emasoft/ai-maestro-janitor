// Messaging and payment service credentials. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const slackToken: Rule = { kind: 'slack-token', pattern: /\b(xox[abposr]-[A-Za-z0-9-]{10,})/g, group: 1 }
export const slackWebhook: Rule = { kind: 'slack-webhook', pattern: /(https:\/\/hooks\.slack\.com\/services\/T[A-Z0-9]+\/B[A-Z0-9]+\/[A-Za-z0-9]+)/g, group: 1 }
export const stripeSecretKey: Rule = { kind: 'stripe-key', pattern: /\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,})\b/g, group: 1 }
export const stripeWebhookSecret: Rule = { kind: 'stripe-key', pattern: /\b(whsec_[A-Za-z0-9]{24,})\b/g, group: 1 }
