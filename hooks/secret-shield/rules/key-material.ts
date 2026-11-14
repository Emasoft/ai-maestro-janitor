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
// WHY the jwt rule is anchored at the start of a run of token characters, tests the tail once, and only then looks for the
// token start (TRDD-A7RII4DN): the old rule, /\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ.../g, tried every eyJ inside a run, and `-` is both a token
// character and a \b boundary, so a run of `eyJ-` repeated had n/4 starts and each one scanned to the end of the run: n * n / 4
// steps. Measured as single runs on an uncontrolled host, not a threshold: 9.8 s at 256 KB and more than 60 s at 1 MB under bun,
// about 2.7 s at 256 KB in the plugin engine. Every start in one run shares one fate, because the first segment's class excludes
// the dot: it must reach the run end, and what follows the run (`.eyJ`, 10+ characters, `.`, 10+ characters) is the same for all of
// them. So the old match is exactly: the leftmost start in the run with a \b before eyJ and 10+ characters between eyJ and the run
// end, if that tail matches. This rule asserts the tail once from the run start ((?<![A-Za-z0-9_-]) is the run start, the lookahead is
// atomic), skips to that leftmost start with a lazy class loop (each step is one cheap check), and then matches the old token
// unchanged as group 1. The match may start earlier than the token (at the run start); applyRule hides only group 1 and keeps the
// prefix, so the output is identical. Keep it exact: widening it needs its own change. tests/patterns.test.ts ('jwt rule runs in
// linear time with the same matches') pins the equivalence against the old regex on hand cases and 400 seeded strings, the timing
// at 256 KB, and the hide of a valid token after a 1 MB run.
export const jwt: Rule = { kind: 'jwt', pattern: /(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})[A-Za-z0-9_-]*?(?<![A-Za-z0-9_])(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/g, group: 1 }
export const bearerToken: Rule = { kind: 'bearer-token', pattern: /\b(?:Authorization|Proxy-Authorization)["']?\s*[:=]\s*["']?(?:Bearer|Basic|token|Token)\s+([A-Za-z0-9._~+/=-]{16,})/g, group: 1 }
