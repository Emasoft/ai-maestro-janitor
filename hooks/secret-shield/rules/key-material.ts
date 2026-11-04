// Key material and generic credentials. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const privateKey: Rule = { kind: 'private-key', pattern: /-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?)-----[\s\S]*?(?:-----END \1-----|$)/g }
export const jwt: Rule = { kind: 'jwt', pattern: /\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/g, group: 1 }
export const bearerToken: Rule = { kind: 'bearer-token', pattern: /\b(?:Authorization|Proxy-Authorization)["']?\s*[:=]\s*["']?(?:Bearer|Basic|token|Token)\s+([A-Za-z0-9._~+/=-]{16,})/g, group: 1 }
