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

// WHY ssh-public-key (TRDD-L1I0FP5T): report-sanitizer hides `ssh-rsa AAAA...` blobs and the shield did not, so a row that passed the shield could still be hidden by the sanitizer. The blob is group 1; the algorithm name stays visible, like every
// other rule keeps its context. WHY linear: the algorithm is a fixed literal list, one `\s+` run and one class loop follow it, and nothing after the loop can fail, so there is no backtracking past the whitespace run.
// Prose such as "the ssh-rsa algorithm" has no AAAA blob after the name and stays visible. Runs right after privateKey: nothing inside a key blob should be matched by another rule first.
// WHY no leading \b or lookbehind: a rule that starts with one misses a key right after a backslash-n in a JSON string, after %22 or after a backslash-t (KNOWN-MISSES.md escape-boundary, TRDD-5VZTPXBJ, pinned by the rule count in tests/known-misses.test.ts); the unanchored literal hides it there, and a prefix glued to the name only hides more.
export const sshPublicKey: Rule = { kind: 'ssh-public-key', pattern: /(?:ssh-rsa|ssh-ed25519|ssh-dss|ecdsa-sha2-nistp\d+)\s+(AAAA[A-Za-z0-9+/=]+)/g, group: 1 }

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
// WHY jwtWide is a separate rule applied as the last pass of redact() (see redactInto) and not a replacement of jwt (TRDD-6A3XW3VO): jr (the reference redactor) hides eyJ + 8 characters, any
// second segment, 8+ characters in the second and third; jwt above needs 10-character segments and an eyJ second segment, so it misses every
// jr-only shape (15 of 15 jr-only samples were hidden by the wide shape, none by jwt) and a payload that does not start with eyJ (a space or
// a newline after the opening brace gives eyAi or ewoi). The wide shape found 0 new matches in the three corpora measured (counted, not judged).
// A single leftmost-consuming rule cannot be a superset of jwt: in a 5-segment string whose last three segments are a real JWT, the wide shape
// starts at segment 1 and its greedy third segment swallows the first segment of the token jwt hides, and the 2-segment remainder matches
// nothing, so text jwt hides today would show. Sequential application is a superset: jwt runs first, its marker has no dot, and no other pass's marker holds eyJ
// followed by a dot, so jwtWide cannot touch any of them. Linear for the same reason as jwt: the first segment's class excludes the dot, so every start inside one run of token characters
// shares one tail, which the atomic lookahead asserts once from the run start; the lazy loop then skips to the leftmost start with a word
// boundary before eyJ. Differential against the plain candidate /\b(eyJ[c]{8,}\.[c]{8,}\.[c]{8,})/g: 0 mismatches over 500000 seeded strings;
// the plain candidate is quadratic on a run of eyJ- (640-700 ms at 64 KB), this rule takes 17-40 ms per MB. NOT covered: a header with a space
// after the opening brace (first segment eyAi); widening the first segment beyond eyJ needs its own measured change. tests/patterns.test.ts
// ('jwt tokens with shorter segments ...') pins the spans, the superset against a copy of jwt, the floors, the timing and the context table (pass order).
export const jwtWide: Rule = { kind: 'jwt', pattern: /(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})[A-Za-z0-9_-]*?(?<![A-Za-z0-9_])(eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})/g, group: 1 }
export const bearerToken: Rule = { kind: 'bearer-token', pattern: /\b(?:Authorization|Proxy-Authorization)["']?\s*[:=]\s*["']?(?:Bearer|Basic|token|Token)\s+([A-Za-z0-9._~+/=-]{16,})/g, group: 1 }
