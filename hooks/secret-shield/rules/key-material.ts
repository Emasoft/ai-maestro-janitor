// Key material and generic credentials. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

// WHY the header is one character class between lookarounds, not a loop over a group (TRDD-AGOEWF2E): in the plugin engine
// (JavaScriptCore) a greedy loop over a GROUP returns no match, silently, past an iteration ceiling. The old header loop missed
// at 1,474,557 iterations, which left the whole key visible. The header accepts exactly what the old group loop accepted, words
// each followed by one space and then PRIVATE KEY, through lookarounds over one class, so no group repeats: (?! ) refuses a
// leading space, (?![A-Z0-9 ]*  ) refuses a double space in the run, and (?<= ) needs a space right before PRIVATE, which refuses
// a word glued to it. Group 1 and the \1 END back-reference are unchanged. Keep that language exact: a wider header would take
// text the old pattern left alone, and its END could land inside another block and leave that block's tail visible.
// Measured in the plugin engine: this header class, unit 'A ', observed with no miss up to 6,291,456 iterations (a header of
// 12,582,923 characters, the header alone).
export const privateKey: Rule = { kind: 'private-key', pattern: /-----BEGIN ((?! )(?![A-Z0-9 ]*  )[A-Z0-9 ]*(?<= )PRIVATE KEY(?: BLOCK)?)-----[\s\S]*?(?:-----END \1-----|$)/g }
export const jwt: Rule = { kind: 'jwt', pattern: /\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/g, group: 1 }
export const bearerToken: Rule = { kind: 'bearer-token', pattern: /\b(?:Authorization|Proxy-Authorization)["']?\s*[:=]\s*["']?(?:Bearer|Basic|token|Token)\s+([A-Za-z0-9._~+/=-]{16,})/g, group: 1 }
