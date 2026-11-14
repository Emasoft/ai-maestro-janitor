// WHY this file exists: known-quadratic regexes kept only as a test fixture for TRDD-OD5Z90YL's load harness; never imported by the shield. Scanners may flag them.
// Known-quadratic regexes, copied verbatim from git history, as constants. Each is the reference a timing check must reject.
import type { Rule } from '../../rules/rule'

const MARK_BODY = String.raw`\[JANITOR-REDACTED:[A-Za-z0-9_-]+\]`
const MARKS = new RegExp(MARK_BODY, 'g')
const PLACEHOLDER = /^(\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\$\(.*\)|\{\{.*\}\}|<[^>]*>|\*+|x+|X+|\.{3}|…|changeme|change_me|password|passwd|secret|token|your[-_ a-z]*|example|dummy|test|none|null|nil|undefined|true|false|empty|redacted|process\.env\.\w+|os\.environ.*|env\(.*\))$/i

// jwt as in 4970ff1f^ (hooks/secret-shield/rules/key-material.ts): \b start, greedy run, backtracks from every eyJ start.
export const oldJwt: Rule = { kind: 'jwt', pattern: /\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/g, group: 1 }

// JSON_ESCAPED as in f38c30c8^ (patterns.ts jsonPair(String.raw`\\+`, String.raw`[^"\\\r\n]{3,}`)), which is also OLD_ESCAPED of patterns.test.ts.
export const OLD_JSON_ESCAPED = new RegExp(String.raw`(\\+)"([A-Za-z0-9_.-]+)\1"(\s*:\s*)\1"([^"\\\r\n]{3,})(\1"|\\*$)`, 'gm')
export const oldJsonEscaped = (text: string): string => text.replace(new RegExp(OLD_JSON_ESCAPED.source, OLD_JSON_ESCAPED.flags), (match) => match)

// URL_PASSWORD before 133a766a (V1): scheme as a \b prefix, quadratic on a run of scheme characters with no ://.
const V1 = new RegExp(
  String.raw`\b([a-z][a-z0-9+.-]*:\/\/)((?:` + MARK_BODY + String.raw`|[^\s:/@'"` + '`' + String.raw`\[])+):((?!\d{1,5}(?:\/|\?[^\s@#]*=))(?:(?!:\/\/)[^\s@'"` + '`' + String.raw`])+)@`,
  'gi',
)
// URL_PASSWORD before 6decd71d (V2): scheme found at the ://, port-skip query scan [^\s@#]* runs past later ://.
const V2 = new RegExp(
  String.raw`(?=:\/\/)(?<=\b[a-z][a-z0-9+.-]*)(:\/\/)((?:` + MARK_BODY + String.raw`|[^\s:/@'"` + '`' + String.raw`\[])+):((?!\d{1,5}(?:\/|\?[^\s@#]*=))(?:(?!:\/\/)[^\s@'"` + '`' + String.raw`])+)@`,
  'gi',
)
// URL_PASSWORD before 7d54b062 (V3): query scan stops at ://, linear at 4-32 KB, red only from the 63.8K-iteration step (32 KB to 256 KB of grown()).
const V3 = new RegExp(
  String.raw`(?=:\/\/)(?<=\b[a-z][a-z0-9+.-]*)(:\/\/)((?:` + MARK_BODY + String.raw`|[^\s:/@'"` + '`' + String.raw`\[])+):((?!\d{1,5}(?:\/|\?(?:(?!:\/\/)[^\s@#])*=))(?:(?!:\/\/)[^\s@'"` + '`' + String.raw`])+)@`,
  'gi',
)
// The callback of the old redactUrlPasswords, with the marker spelled out; the old code ran text.replace(URL_PASSWORD, cb).
const oldUrl = (pattern: RegExp) => (text: string): string =>
  text.replace(new RegExp(pattern.source, pattern.flags), (match, separator: string, user: string, password: string) => {
    const rest = password.replace(MARKS, '')
    if (rest === '' || PLACEHOLDER.test(rest)) return match
    return `${separator}${user}:[JANITOR-REDACTED:url-password]@`
  })
export const urlV1 = oldUrl(V1)
export const urlV2 = oldUrl(V2)
export const urlV3 = oldUrl(V3)
