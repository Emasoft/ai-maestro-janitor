// AI provider keys. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const anthropicKey: Rule = { kind: 'anthropic-key', pattern: /\b(sk-ant-[A-Za-z0-9_-]{20,})/g, group: 1 }
export const openaiProjectKey: Rule = { kind: 'openai-key', pattern: /\b(sk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,})/g, group: 1 }
export const openaiLegacyKey: Rule = { kind: 'openai-key', pattern: /\b(sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})\b/g, group: 1 }
// WHY this rule is any sk- plus 20 or more of [A-Za-z0-9_-], with no trailing \b and no digit requirement (TRDD-6A3XW3VO, widened 2026-11-14): it was sk- plus exactly 48 letters and digits, which left every other length and every key with a hyphen or underscore in the body visible.
// jr-redact hid 31 catalog-shaped and suite sample keys the shield left visible (all 31 are hidden now); bodies were synthesized from other tools' catalog regexes. Corpus run, matches counted, not judged: 0 new matches in 40 MB of repo text; in 100 MB of third-party plugin-cache text (every 8th file) 6 matches the old rule left visible: 5 key-shaped (placeholders or doc examples, one OpenRouter sk-or-v1- family) and 1 hyphenated word run.
// That word run is the accepted over-hide, pinned by a test. The trailing \b is dropped because a key followed by an underscore never reaches a boundary. No digit lookahead: it would hide 1 fewer third-party match but leave a 48-letter key with no digit visible, which the old rule hid, so the widening would no longer be a superset.
// The export name stays openaiKey48 because patterns.ts and known-misses.test.ts key on it; the rule is no longer 48-specific. sk-ant- and the proj/svcacct/admin and legacy rules run before it (patterns.ts).
export const openaiKey48: Rule = { kind: 'openai-key', pattern: /\b(sk-[A-Za-z0-9_-]{20,})/g, group: 1 }
export const huggingfaceToken: Rule = { kind: 'huggingface-token', pattern: /\b(hf_[A-Za-z0-9]{34,})\b/g, group: 1 }
