// Pure secret detection and redaction: no `$`, so tests and other mods can import it.

import { anthropicKey, huggingfaceToken, openaiKey48, openaiLegacyKey, openaiProjectKey } from './rules/ai'
import { awsAccessKey, awsSecretKeyAssignment, awsSecretKeyJson, awsSessionToken, digitaloceanOAuthToken, digitaloceanPat, digitaloceanRefreshToken, googleApiKey, googleOAuthAccessToken, googleOAuthClientSecret, googleOAuthRefreshToken } from './rules/cloud'
import { githubTokenClassic, githubTokenFineGrained, gitlabAgentToken, gitlabCicdJobToken, gitlabDeployToken, gitlabFeatureFlagClientToken, gitlabFeedToken, gitlabIncomingMailToken, gitlabOAuthAppSecret, gitlabPat, gitlabRunnerRegistrationToken, gitlabRunnerToken, gitlabScimToken, gitlabSessionCookie, gitlabSessionCookieValueFirst, gitlabTriggerToken, gitlabWorkspaceToken } from './rules/code-hosts'
import { npmToken, pypiToken, sendgridKey } from './rules/dev-services'
import { bearerToken, jwt, privateKey } from './rules/key-material'
import { slackAppToken, slackConfigAccessToken, slackConfigRefreshToken, slackToken, slackWebhook, stripeSecretKey, stripeWebhookSecret } from './rules/messaging-payments'
import type { Rule } from './rules/rule'

export type Hits = Record<string, number>

/** What a redacted secret is replaced with. */
export const mark = (kind: string): string => `[JANITOR-REDACTED:${kind}]`

const MARK_BODY = String.raw`\[JANITOR-REDACTED:[A-Za-z0-9_-]+\]`
/** A value that IS a marker, whole. Anchored: a value that only contains one is judged on the rest. */
const MARK = new RegExp('^' + MARK_BODY + '$')
const MARKS = new RegExp(MARK_BODY, 'g')
// Cuts a text at its markers; the capture group keeps each marker as an odd entry. Not global: String.split ignores lastIndex.
const MARK_SPLIT = new RegExp('(' + MARK_BODY + ')')
// Built from MARK_BODY so the marker grammar has one source.
// WHY the scheme is a lookbehind at the `://` and not a prefix `\b([a-z][a-z0-9+.-]*:\/\/)`: that prefix starts at every word
// boundary and scans the whole run of scheme characters (letters, digits, `+`, `.`, `-`) looking for `://`, so a long run with
// none (base64, hex, a hyphenated blob; 16 KB of `A1-` took 0.5-1.4 s, 64 KB did not finish in 10 minutes) was quadratic. Here the
// lookahead `(?=:\/\/)` rejects every position that is not a `://` in O(1), and the lookbehind then reads back over the run once
// per `://` (the runs before two `://` never overlap), so the cost is linear. It gives up nothing: a match needs the same
// scheme in front of the `://`, of any length, and the text kept is the same, because the scheme was never changed. Do not cap the
// scheme length instead: a cap would stop hiding a scheme of more than N unbroken letters. Group 1 is `://` and the scheme stays
// outside the match (TRDD-Q6LPJTPO).
// WHY the port-skip lookahead scans its query with a loop that stops at `://` and not with `[^\s@#]*=`: the plain class does not stop at
// `://`, so for every `://` whose password starts with up to 5 digits then `?` it scanned on past every later `://` looking for an
// `=`, up to the next whitespace, `@` or `#`, at the latest the end of the line, and of the text when no newline follows.
// `b://u:1?` repeated k times and followed by n characters cost O(k*n) (k=4000, n=64 KB took 18.5 s in system Bun under load).
// Stopping the scan at `://` changes no result: the old class `[^\s@#]` already stopped at the first `@`, so an `=` it found past
// the next `://` means no `@` sits before that `://`. The password branch cannot cross `://`, so it cannot reach an `@` either,
// and both versions hide nothing there. Each scan now ends at the next `://`, so the scans themselves are linear.
// WHY the three loops (user, password, query) are unrolled so a group iterates only at a marker or a colon, never per character:
// measured under claude plugin test (TRDD-HF7GNHNF, TRDD-AGOEWF2E), a greedy loop over a GROUP such as `(?:(?!:\/\/)[^\s@'"`])+` has two
// iteration-count ceilings in that engine: the loop runs about 35 times slower per character once one run passes about 63.8K
// iterations (last fast run 63,808, first slow 63,824; still linear), and it returns no match at all, silently, from about 553K
// iterations (last hidden 552,896, first missed 552,960). A loop over a single character class has neither ceiling (hidden at 4 MB).
// Node (V8) and the system Bun 1.3.14 show no step (Bun misses from about 360K, Node throws a RangeError at 2^23), so the regex itself and
// backtracking are ruled out. The engine is inferred to be the JavaScriptCore inside Claude Code, whose binary names Bun v1.4.4: not asserted.
// Unrolled, a loop over a run of non-colon characters is a class loop, and the group repeats once per colon (password, query) or once per
// marker (user). The language is the same: every `:` not followed by `//` is still allowed; the differential fuzz found no difference.
// WHY a guard drives the matching (redactUrlPasswords): a password made of colons, or a user part made of markers, still has the
// group iterating once per colon or marker, so it reaches the ceilings again (a colon-dense password stepped at 65,536 colons and was
// missed between 589,824 and 1,048,576 characters). The guard reads each `://` before the regex may run: the scheme, the user part
// (counting its markers) and the colons up to the first whitespace, `@` or `://`. Past URL_PASSWORD_BOUND of either it runs no regex
// on that span at all, so the cost stays linear, and it fails closed: a password region that ends at `@` is hidden whole.
// Otherwise (up to the bound) the regex runs sticky at that `://`, and the result is the same as a global replace.
// "Do not cap the scan length" (the earlier rule for the query scan and the scheme) still holds for the regex: a cap inside the
// regex makes it fail to match, which FAILS OPEN, and a port with a longer query would be read as a password and hidden or a
// password missed. The guard is not that cap: above the bound it hides, which fails closed.
// Disclosed over-hide above the bound, for security first: (1) a port followed by a path, a `?query` or a `#fragment` that holds more than the bound
// of colons before an `@` is read as a password and hidden, because no regex tells the port from a password there; (2) markers (tokens
// hidden earlier) inside the hidden region collapse into one url-password marker, their hits stay counted; (3) such a value is not
// added to `found`, so it is not hidden elsewhere in the row (a value that long is not propagated). Not guarded: the scheme and the
// user part must be valid as the regex reads them, so `1://`, `_a://` and `.://` shapes are not touched. Placeholder and marker-only passwords
// (`x`, `${VAR}`, or markers alone) are left alone above the bound, the same as below it: the guard applies the PLACEHOLDER and MARKS check before it hides.
const NOT_USER = String.raw`[^\s:/@'"${'`'}\[]`
const NOT_PASSWORD = String.raw`[^\s@'"${'`'}:]`
const QUERY = String.raw`[^\s@#:]*(?::(?!\/\/)[^\s@#:]*)*`
const URL_PASSWORD = new RegExp(
  String.raw`(?=:\/\/)(?<=\b[a-z][a-z0-9+.-]*)(:\/\/)((?:${NOT_USER}|${MARK_BODY})${NOT_USER}*(?:${MARK_BODY}${NOT_USER}*)*):` +
    String.raw`((?!\d{1,5}(?:\/|\?${QUERY}=))(?!:\/\/)[^\s@'"${'`'}]${NOT_PASSWORD}*(?::(?!\/\/)${NOT_PASSWORD}*)*)@`,
  'iy',
)
/** The most markers in a URL's user part, and the most colons in its password span, that URL_PASSWORD is run on. Above it the guard hides the password without the regex. */
export const URL_PASSWORD_BOUND = 4096
// The pieces the guard reads a `://` with: a run of user characters, a whole marker, the end of the span the regex can reach, the end of the password.
const USER_RUN = new RegExp(`${NOT_USER}+`, 'y')
const MARK_AT = new RegExp(MARK_BODY, 'iy')
const SPAN_END = /[\s@]|:\/\//g
const PASSWORD_END = /[\s@'"`]|:\/\//g

// Specific, high-confidence token formats, defined by category under rules/ and listed here one by one.
// The order is load-bearing: rules run in this order and the first match wins, because a hidden token is
// skipped by every later rule. The private key runs first, so nothing inside a key block is matched on its
// own, and the more specific prefix (sk-ant-) runs before the more general one (sk-). Never build this list by
// concatenating the category files: their order is not this order. tests/patterns.test.ts pins it through TOKEN_ORDER.
// Never run these patterns directly: see rules/rule.ts.
const TOKENS: readonly Rule[] = [
  privateKey,
  // The Google OAuth rules run before every family except privateKey: an earlier \b-led rule (sk-, ghp_, AKIA, ...) firing inside a ya29. or 1//0
  // body after a dash would leave the rest of the Google token visible, the reason the Slack rules run before slackToken.
  googleOAuthClientSecret,
  googleOAuthAccessToken,
  googleOAuthRefreshToken,
  digitaloceanPat,
  digitaloceanOAuthToken,
  digitaloceanRefreshToken,
  awsAccessKey,
  awsSecretKeyAssignment,
  awsSecretKeyJson,
  awsSessionToken,
  githubTokenClassic,
  githubTokenFineGrained,
  gitlabPat,
  gitlabOAuthAppSecret,
  gitlabDeployToken,
  gitlabRunnerToken,
  gitlabRunnerRegistrationToken,
  gitlabCicdJobToken,
  gitlabTriggerToken,
  gitlabFeedToken,
  gitlabIncomingMailToken,
  gitlabAgentToken,
  gitlabWorkspaceToken,
  gitlabScimToken,
  gitlabFeatureFlagClientToken,
  gitlabSessionCookie,
  gitlabSessionCookieValueFirst,
  anthropicKey,
  openaiProjectKey,
  openaiLegacyKey,
  openaiKey48,
  slackAppToken,
  slackConfigAccessToken,
  slackConfigRefreshToken,
  slackToken,
  slackWebhook,
  stripeSecretKey,
  stripeWebhookSecret,
  googleApiKey,
  jwt,
  npmToken,
  pypiToken,
  huggingfaceToken,
  sendgridKey,
  bearerToken,
]

/** Each rule's kind, pattern source and flags, in run order: the data tests/patterns.test.ts pins, without the RegExps. */
export const TOKEN_ORDER: readonly (readonly [string, string, string])[] = TOKENS.map(rule => [rule.kind, rule.pattern.source, rule.pattern.flags] as const)

// A value that is obviously not a real secret: a reference, a placeholder.
const PLACEHOLDER = /^(\$\{?[A-Za-z_][A-Za-z0-9_]*\}?|\$\(.*\)|\{\{.*\}\}|<[^>]*>|\*+|x+|X+|\.{3}|…|changeme|change_me|password|passwd|secret|token|your[-_ a-z]*|example|dummy|test|none|null|nil|undefined|true|false|empty|redacted|process\.env\.\w+|os\.environ.*|env\(.*\))$/i

// Names that say "this value is a secret", matched on the snake_case form
// (`apiKey` reads `api_key`) so `tokenizer` and `max_tokens` do not count...
const SECRET_NAME = /(^|[_.-])(secrets?|token|password|passwd|passphrase|pwd|pass|api_?key|apikey|private_?key|access_?key|access_?token|auth_?key|auth_?token|client_?secret|secret_?key|credentials?|signing_?key|encryption_?key|session_?key|master_?key)([_.-]|$)/
// ...unless they are about the secret rather than the secret itself.
const NOT_SECRET_NAME = /[_.-](url|uri|endpoint|path|file|dir|name|type|expiry|expires|expires_at|ttl|length|header|id|count|limit|size|prefix|env|var|mode|enabled|required|policy|hint|prompt|label|placeholder|field|format)$/

// Names that are secrets only when the value is long and key-shaped. WHY: `AZURE_STORAGE_KEY` holds an 88-character
// Azure key, but `const STORAGE_KEY = 'todos-vuejs'` and `account_key: "acct_12345"` name a slot or an id in other
// projects, so for these names looksSecret alone is not enough: strongValue must hold too (TRDD-Q6LPJTPO).
const STRONG_NAME = /(^|_)(storage|account)_?key(_|$)/

// The snake_case form a name is matched on. WHY: `-` and `.` read as `_`, so `api-key`, `X-Api-Key` and `ssl.private-key`
// match like `api_key` (TRDD-Q6LPJTPO).
function snakeName(name: string): string {
  return name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase().replace(/[-.]/g, '_')
}

function isSecretName(name: string): boolean {
  const snake = snakeName(name)
  return (SECRET_NAME.test(snake) || STRONG_NAME.test(snake)) && !NOT_SECRET_NAME.test(snake)
}

/** A name that is secret only through STRONG_NAME: its value must also pass strongValue. */
function isStrongName(name: string): boolean {
  const snake = snakeName(name)
  return !SECRET_NAME.test(snake) && STRONG_NAME.test(snake)
}

/**
 * A value key-shaped enough for a STRONG_NAME: a base64 run of 40 or more characters with an upper-case letter, a lower-case letter and a digit (an Azure key is 88).
 * WHY no shorter branch: a "20 or more characters with a letter and a digit" rule hid `STORAGE_KEY = 'user-preferences-v2-2024'`, `account_key: "acct_1A2b3C4d5E6f7G8h"` and a lowercase hex SHA, which are slugs, ids and digests, not keys (TRDD-Q6LPJTPO).
 */
function strongValue(value: string): boolean {
  return /^[A-Za-z0-9+/]{40,}={0,2}$/.test(value) && /[A-Z]/.test(value) && /[a-z]/.test(value) && /\d/.test(value)
}

function looksSecret(value: string, isQuoted: boolean): boolean {
  if (value === '' || MARK.test(value) || PLACEHOLDER.test(value)) return false
  // A value partly made of markers (a token inside it was hidden first) is judged on what is left, so a secret written next to a token is not shown just because the token was hidden.
  const rest = value.replace(MARKS, '')
  if (rest !== value) return looksSecret(rest, isQuoted)
  if (/^\d{1,7}$/.test(value)) return false
  if (isQuoted) return value.length >= 3 && !/\s/.test(value)
  // Unquoted: a code expression (`get_token()`, `self.token`) is not a secret.
  if (/[\s()[\]{};,]/.test(value)) return false
  if (/^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$/.test(value)) return false
  return (value.length >= 6 && /\d/.test(value)) || value.length >= 16
}

// A value is worth hunting for elsewhere only when it is long and secret-shaped. WHY: the review of 2026-11-04
// found that propagation spreads every false positive of the looksSecret heuristic (paths, env-var names,
// identifiers, slugs, emails, host:port) over a whole row, and those values are usually 10 or more characters, so a
// length floor alone does not stop it. Each shape rejected here is usually a name, a location or a reference. Shapes
// of real credentials that are knowingly refused too: a diceware-style lowercase passphrase (slug rule), a password
// shaped like an email (email rule), user:12345 (host:port rule), base64 with a slash but no digit (slash rule).
// The defining line of such a value is always hidden by the passes that found it; only the spreading is refused.
function propagates(value: string): boolean {
  // Marker text is never a value to hunt for: hideKnown skips markers, and a value that holds one is not a secret.
  if (value.replace(MARKS, '') !== value || value.includes('JANITOR-REDACTED')) return false
  if (PLACEHOLDER.test(value) || value.length < 10) return false
  if (/^\d+$/.test(value) || /^(.)\1*$/s.test(value)) return false
  const hasDigit = /\d/.test(value)
  if (/^[A-Za-z_][A-Za-z0-9_]*$/.test(value) && !hasDigit) return false
  if (/^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$/.test(value)) return false
  // A lowercase-word slug (`my-app-db-credentials`, `secret/data/myapp`) names a thing.
  if (/^[a-z]+([-_./][a-z]+)+$/.test(value)) return false
  if (value.startsWith('/') || value.startsWith('~/') || value.startsWith('./') || value.startsWith('../')) return false
  // A path or vault key (`prod/db/password`) holds a slash; a base64 secret does too, but only with all three kinds of character.
  if (value.includes('/') && !(/[A-Z]/.test(value) && /[a-z]/.test(value) && hasDigit)) return false
  if (value.includes('://')) return false
  if (/^[^@\s]+@[A-Za-z0-9.-]+\.[A-Za-z]+$/.test(value)) return false
  if (/^[A-Za-z0-9.-]+:\d{1,5}$/.test(value)) return false
  if (/^[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$/.test(value) && /^[A-Za-z]+$/.test(value.slice(value.lastIndexOf('.') + 1))) return false
  return (/[A-Za-z]/.test(value) && hasDigit) || value.length >= 16
}
/** Replaces each match of `rule` with its mark, counting into `hits`; a hidden value that propagates() accepts is recorded in `found`. Exported so tests can drive a synthetic rule. */
export function applyRule(text: string, rule: Rule, hits: Hits, found?: Map<string, string>): string {
  // String.prototype.replace with a /g pattern sets lastIndex to 0 before it starts, so a lastIndex left behind by
  // anyone who ran .test() or .exec() on this shared RegExp cannot make it skip text. Keep it a replace (no exec loop).
  return text.replace(rule.pattern, (match: string, ...groups: unknown[]) => {
    const group = rule.group ?? 0
    const secret = group === 0 ? match : String(groups[group - 1] ?? '')
    if (secret === '' || MARK.test(secret)) return match
    hits[rule.kind] = (hits[rule.kind] ?? 0) + 1
    if (found && propagates(secret)) found.set(secret, rule.kind)
    // Hide every non-overlapping copy of the captured text inside the match. A string replace hides the first copy
    // only, and the first copy can sit in the gap before the capture (key name, gap, then the quoted value), which
    // leaves the captured secret in view. Hiding the group by its index would leak the other copy instead (found
    // during the UBS triage of 2026-11-04; UBS did not report it; TRDD-Q6LPJTPO). The hit is still counted once per
    // match. The `secret === ''` guard above must stay before the split: `match.split('')` splits into single
    // characters, and the join would put a marker between every pair.
    return group === 0 ? mark(rule.kind) : match.split(secret).join(mark(rule.kind))
  })
}

/** Whether the text before the `://` at `end` ends in what the URL_PASSWORD lookbehind `\b[a-z][a-z0-9+.-]*` accepts: a letter, with no word character before it, inside the run of scheme characters. */
function hasScheme(text: string, end: number): boolean {
  const isLetter = (code: number): boolean => (code >= 65 && code <= 90) || (code >= 97 && code <= 122)
  const isDigit = (code: number): boolean => code >= 48 && code <= 57
  let start = end
  // `+` `-` `.` are scheme characters but not word characters, so a letter right after one of them stands at a \b.
  while (start > 0) {
    const code = text.charCodeAt(start - 1)
    if (!(isLetter(code) || isDigit(code) || code === 43 || code === 45 || code === 46)) break
    start--
  }
  for (let at = start; at < end; at++) {
    if (!isLetter(text.charCodeAt(at))) continue
    if (at === 0) return true
    const before = text.charCodeAt(at - 1)
    if (!(isLetter(before) || isDigit(before) || before === 95)) return true
  }
  return false
}

/** A password in a URL's userinfo part: keeps the scheme, user and host, hides the password. */
function redactUrlPasswords(text: string, hits: Hits, found: Map<string, string>): string {
  // The password may contain a slash. A value of up to 5 digits followed by / is a port followed by a
  // path, and up to 5 digits followed by a ? query with an = before the at-sign is a port followed by a
  // query (`host:8080/pkg/@scope`, `localhost:3000?email=a@b`), so the lookahead skips both. Other digits
  // (`2024#Spring`, `12?abc`) are a password and are hidden. The user part may contain whole markers
  // (a token hidden first, such as an AWS access key used as the user name) but no other [,
  // so a bracketed IPv6 host is never read as a user. A password cannot contain :// so it never runs
  // into a second URL. Known false positive: `localhost:3000#a@b` reads its fragment as a password.
  // WHY a loop over each `://` and not text.replace(URL_PASSWORD, ...): see the WHY block above URL_PASSWORD. The guard reads each `://`
  // (scheme, user part, count of markers and colons) before the regex may run on it, and the regex runs only sticky at that `://`, so no
  // regex ever scans a span that holds more than URL_PASSWORD_BOUND iterations of a group loop. Every span read is bounded by the next
  // `://` (the user part, the password and the scheme run all stop at one), so the spans never overlap and the cost is linear.
  let next = 0
  let done = 0
  const parts: string[] = []
  for (let idx = text.indexOf('://'); idx !== -1; idx = text.indexOf('://', next)) {
    next = idx + 1
    if (!hasScheme(text, idx)) continue
    // The user part: runs of non-separator characters and whole markers, the same grammar as the regex. A marker holds a `:` and a `[`, so it is read whole first.
    let colon = idx + 3
    let markers = 0
    for (;;) {
      USER_RUN.lastIndex = colon
      const run = USER_RUN.exec(text)
      if (run !== null) colon += run[0].length
      MARK_AT.lastIndex = colon
      const marker = MARK_AT.exec(text)
      if (marker === null) break
      colon += marker[0].length
      markers++
    }
    if (colon === idx + 3 || text[colon] !== ':') continue
    // The span the password and the port-skip query can reach: up to the first whitespace, `@` or `://`. Its colons are the group iterations of the unrolled regex.
    SPAN_END.lastIndex = colon + 1
    const spanEnd = SPAN_END.exec(text)?.index ?? text.length
    let colons = 0
    for (let at = text.indexOf(':', colon + 1); at !== -1 && at < spanEnd && colons <= URL_PASSWORD_BOUND; at = text.indexOf(':', at + 1)) colons++
    if (markers <= URL_PASSWORD_BOUND && colons <= URL_PASSWORD_BOUND) {
      URL_PASSWORD.lastIndex = idx
      const match = URL_PASSWORD.exec(text)
      if (match === null) continue
      next = idx + match[0].length
      const [, separator, user, password] = match
      const rest = password.replace(MARKS, '')
      if (rest === '' || PLACEHOLDER.test(rest)) continue
      hits['url-password'] = (hits['url-password'] ?? 0) + 1
      if (propagates(password)) found.set(password, 'url-password')
      parts.push(text.slice(done, idx), `${separator}${user}:${mark('url-password')}@`)
      done = next
      continue
    }
    // Over the bound: no regex runs. A password region that ends at `@` is hidden whole; any other span is left as it is.
    PASSWORD_END.lastIndex = colon + 1
    const end = PASSWORD_END.exec(text)?.index ?? text.length
    if (text[end] !== '@' || end === colon + 1) continue
    // WHY the same placeholder check as below the bound: without it a password that is only markers or a placeholder (`x`, `${VAR}`) was hidden here but not at or under the bound,
    // so redact() on its own output (the region is one marker) counted a phantom hit and was not idempotent. Every other region that ends at `@` is still hidden (fail closed).
    const rest = text.slice(colon + 1, end).replace(MARKS, '')
    if (rest === '' || PLACEHOLDER.test(rest)) continue
    hits['url-password'] = (hits['url-password'] ?? 0) + 1
    parts.push(text.slice(done, colon + 1), mark('url-password'))
    done = end
    next = end + 1
  }
  if (parts.length === 0) return text
  parts.push(text.slice(done))
  return parts.join('')
}

// JSON pairs, `"api_key": "..."`. Group 1 is the run of backslashes written before every quote of the pair: none
// in plain JSON, one when the JSON sits inside another JSON string (`\"api_key\":\"...\"`), three when it was
// stringified twice (`\\\"api_key\\\":\\\"...\\\"`). A pm2 jlist dump nested that way leaked a Dropbox secret on
// 2026-11-03 because the plain pattern needs a bare quote next to the name (TRDD-Q6LPJTPO). A value may also end
// at the end of a line, with no closing quote or after any part of its closing escape (a cut between the
// backslashes and the quote), which is how a truncated dump ends; JSON strings hold no raw line break, so such a
// value never runs into the next line.
// The values are written so no group repeats once per character: JavaScriptCore gives up on a long match of
// `(?:a|b){3,}` (measured: no match at 500 KB, a silent miss), while a repeated character class runs 5 MB in
// milliseconds. An escaped value holds no backslash, because there the closing `\"` would read as an escape;
// a secret with an escape sequence inside escaped JSON is a known miss. A plain value is the unrolled form of
// "any character but a quote, or an escape pair", which repeats per escape pair, not per character.
const jsonPair = (escapes: string, value: string): RegExp =>
  new RegExp(String.raw`(${escapes})"([A-Za-z0-9_.-]+)\1"(\s*:\s*)\1"(${value})(\1"|\\*$)`, 'gm')
// The two passes are independent: each is its own replace over the whole text, and a pair that is not secret is
// returned unchanged, so the escaped pass still sees the pairs inside `"args": "{\"token\":...}"` whichever runs
// first. The order does not decide what is hidden. Escaped pairs run first only to refine the count when the outer
// key is itself secret-named: the inner secret is counted, then the outer value (swap measured 2026-11-04).
const JSON_ESCAPED = jsonPair(String.raw`\\+`, String.raw`[^"\\\r\n]{3,}`)
const JSON_PLAIN = jsonPair('', String.raw`[^"\\\r\n]*(?:\\.[^"\\\r\n]*)*`)

/** `.env`, shell, YAML and TOML lines: `API_KEY=...`, `export TOKEN="..."`, `password: ...`. */
function redactAssignments(text: string, hits: Hits, found: Map<string, string>): string {
  const line = /^([ \t]*(?:export[ \t]+)?(?:(?:const|let|var|readonly|final|static|private|public)[ \t]+)*["']?)([A-Za-z_][A-Za-z0-9_.-]*)(["']?[ \t]*(?::[ \t]*[A-Za-z<>[\]|]+[ \t]*)?[=:][ \t]*)(["'`]?)([^\n\r]*?)\4([,;]?(?:[ \t]+(?:#|\/\/).*)?[ \t]*)$/gm
  let out = text.replace(line, (match, lead: string, name: string, sep: string, quote: string, value: string, tail: string) => {
    if (!isSecretName(name)) return match
    // `x == y` is a comparison, not an assignment.
    if (value.startsWith('=')) return match
    if (!looksSecret(value, quote !== '')) return match
    // WHY: a STRONG_NAME (`STORAGE_KEY`) is hidden only for a key-shaped value, not for `'todos-vuejs'` (TRDD-Q6LPJTPO).
    if (isStrongName(name) && !strongValue(value)) return match
    hits.assignment = (hits.assignment ?? 0) + 1
    if (propagates(value)) found.set(value, 'assignment')
    return `${lead}${name}${sep}${quote}${mark('assignment')}${quote}${tail}`
  })
  for (const pair of [JSON_ESCAPED, JSON_PLAIN]) {
    out = out.replace(pair, (match, esc: string, name: string, sep: string, value: string, end: string) => {
      // A value that never closed (it ran to the end of the line) is judged as unquoted: without its closing quote
      // nothing says where it ends, so a short word such as `"password": "notasecret` is not hidden.
      if (!isSecretName(name) || !looksSecret(value, end.endsWith('"'))) return match
      // WHY: the same STRONG_NAME gate as the line pass above (TRDD-Q6LPJTPO).
      if (isStrongName(name) && !strongValue(value)) return match
      hits.assignment = (hits.assignment ?? 0) + 1
      if (propagates(value)) found.set(value, 'assignment')
      // `end` is the closing quote, or what was left of it (nothing, or some of its backslashes) when the value ran to the end of the line.
      return `${esc}"${name}${esc}"${sep}${esc}"${mark('assignment')}${end}`
    })
  }
  return out
}

// A key in a `;`-delimited connection string (Azure, SQL Server, ODBC, Service Bus): `AccountKey=...;`, `;Password=...;`.
// WHY: the assignment pass reads `Password=V;Server=h` as one value with a `;` in it and rejects it, and it never looks
// inside `a=b;Password=<value>`, so these leaked (TRDD-Q6LPJTPO). The value stops at `;`, whitespace, a quote, a backtick or a backslash,
// so it also works inside quoted and escaped JSON. The name must follow a `;` or start a line.
const CONN = /(^|;)([ \t]*(?:AccountKey|SharedAccessKey|AccessKey|Password|Pwd)[ \t]*=[ \t]*)([^;\s"'`\\]+)/gim

/**
 * The text before the `;` at `offset`, back to the previous `;` or the start of its line.
 * WHY the `;` is searched first: a newline search that ran first would scan back to the start of the text for every hit
 * when the text has no newline, which is quadratic (measured: 667 ms for 512 KB of `;Password=abc`). The previous `;`
 * bounds the slice, and each `;` is the bound of at most one hit. At offset 0 the search clamps to the `;` itself and
 * the segment is empty (TRDD-Q6LPJTPO).
 */
function settingBefore(whole: string, offset: number): string {
  const segment = whole.slice(whole.lastIndexOf(';', offset - 1) + 1, offset)
  return segment.slice(segment.lastIndexOf('\n') + 1)
}

/** Keys in `;`-delimited connection strings: keeps the name, hides the value. */
function redactConnectionStrings(text: string, hits: Hits, found: Map<string, string>): string {
  const kind = 'connection-string-key'
  return text.replace(CONN, (match: string, lead: string, prefix: string, value: string, offset: number, whole: string) => {
    // WHY: at the start of a line the value needs a `;` after it, and the text after that `;`, up to the next `;` or newline, must hold a word character right before an `=`. `password=abc` (a plain assignment) and `password=hashed;` (the end of a code statement) have no such setting after them; `Password=V;Server=h` does (TRDD-Q6LPJTPO).
    // Exception: a lone `AccountKey=<value>;` line, with no setting after the `;`, is also hidden when looksSecret accepts the value on its own. The assignment pass does not hide AccountKey for a value shorter than strongValue's 40 base64 characters, while Password, Pwd and SharedAccessKey it already hides (measured 2026-11-04); `password=hashed;` stays visible because looksSecret rejects a short word (TRDD-Q6LPJTPO).
    if (lead === '' && !/^;[^;\n]*\w=/.test(whole.slice(offset + match.length)) && !(whole[offset + match.length] === ';' && looksSecret(value, false))) return match
    // WHY: after a `;` the neighbouring setting must be `Name=value` too: in code the segment before it is `a = 1` or `x`, not a connection-string pair. The segment runs back to the previous `;` or the start of the line; at offset 0 the search clamps to the match itself and the segment is empty (TRDD-Q6LPJTPO).
    if (lead === ';' && !/\w=/.test(settingBefore(whole, offset))) return match
    // WHY: a value that holds a marker was hidden by an earlier rule, which already counted it; hiding it again would
    // count it twice and swap its kind. Never MARKS.test(): MARKS has the g flag and keeps lastIndex between calls.
    // A value that only partly holds a marker is a known miss.
    if (value.replace(MARKS, '') !== value) return match
    // WHY: `Password=changeme;` and `Password=<your-password>;` are placeholders, not credentials.
    if (PLACEHOLDER.test(value)) return match
    // WHY: `a=1;password=getPw()`, `x;password=input.value` and `Password=${DB_PASS}` are code, not a literal key.
    if (/[(){}]/.test(value) || value.startsWith('$') || /^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$/.test(value)) return match
    // WHY: a real connection string almost never spaces the `=`, a code statement does (`password = hashed;`, `a = 1; password = pw;`). With a space or tab next to the `=` the value must look like a secret on its own (TRDD-Q6LPJTPO).
    if (/[ \t]=|=[ \t]/.test(prefix) && !looksSecret(value, false)) return match
    hits[kind] = (hits[kind] ?? 0) + 1
    // WHY: record the key so a copy of it written elsewhere in the same text, row or value is hidden too.
    if (propagates(value)) found.set(value, kind)
    return lead + prefix + mark(kind)
  })
}

/** Every rule and pass over `text`, counting into `hits` and recording each hidden value that propagates() accepts in `found`. */
function redactInto(text: string, hits: Hits, found: Map<string, string>): string {
  let out = text
  for (const rule of TOKENS) out = applyRule(out, rule, hits, found)
  out = redactUrlPasswords(out, hits, found)
  out = redactAssignments(out, hits, found)
  out = redactConnectionStrings(out, hits, found)
  return out
}

// Hides every copy of an already hidden value that no rule matched on its own (a password written in an assignment,
// then typed again in a command). `found` holds raw secrets, so it never leaves this module: no function returns or
// stores it. The longest value goes first so a value that contains another is hidden whole. Each value is also
// hidden in its JSON-escaped and URL-encoded forms. split/join was measured 2-3x faster than one alternation in
// JavaScriptCore. WHY the text is cut at its markers first: a marker already in the text (or one this loop just
// wrote) must never be split by a copy of a value, or the marker stops matching MARK and the kind is lost; a value
// that equals marker text (`SOME_SECRET=JANITOR-REDACTED`) or a fragment of one would do exactly that. So copies are
// hidden only in the stretches between markers, and a marker written here is never searched again. propagates() also
// refuses such values. Known misses: copies in separate calls, copies split by a line break, truncated copies, base64
// forms such as Basic auth, and the JSON-decoded form of a JSON_PLAIN value that contains an escape (never searched).
// Copies are not counted in `hits`: they are the same secret, already counted once.
function hideKnown(text: string, found: Map<string, string>): string {
  if (found.size === 0) return text
  // Even entries are plain text, odd entries are whole markers (the capture group of the split keeps them).
  let pieces = text.split(MARK_SPLIT).map((piece, i) => ({ piece, hidden: i % 2 === 1 }))
  for (const [secret, kind] of [...found].sort((a, b) => b[0].length - a[0].length)) {
    const variants = new Set([secret, JSON.stringify(secret).slice(1, -1)])
    // WHY: encodeURIComponent throws URIError on a lone surrogate, and redact must never throw. The raw and the
    // JSON-escaped forms still hide such a value; only the URL-encoded form has no encoding to look for.
    if (secret.isWellFormed()) variants.add(encodeURIComponent(secret))
    for (const variant of variants) {
      const next: typeof pieces = []
      for (const part of pieces) {
        const bits = part.hidden ? [part.piece] : part.piece.split(variant)
        if (bits.length === 1) {
          next.push(part)
          continue
        }
        bits.forEach((bit, i) => {
          if (i > 0) next.push({ piece: mark(kind), hidden: true })
          next.push({ piece: bit, hidden: false })
        })
      }
      pieces = next
    }
  }
  return pieces.map(part => part.piece).join('')
}

/** Every secret in `text` replaced by its mark, and how many of each kind. */
export function redact(text: string): { text: string; hits: Hits } {
  const hits: Hits = {}
  const found = new Map<string, string>()
  const out = hideKnown(redactInto(text, hits, found), found)
  return { text: out, hits }
}

export function countOf(hits: Hits): number {
  return Object.values(hits).reduce((sum, n) => sum + n, 0)
}

export function addHits(into: Hits, from: Hits): Hits {
  for (const [kind, n] of Object.entries(from)) into[kind] = (into[kind] ?? 0) + n
  return into
}

// Maps every string of a plain JSON value through `f`, keeping its shape (nodes deeper than 12 levels are left as they are).
const mapStrings = (value: unknown, f: (text: string) => string): unknown => {
  const walk = (node: unknown, depth: number): unknown => {
    if (typeof node === 'string') return f(node)
    if (depth > 12 || node === null || typeof node !== 'object') return node
    if (Array.isArray(node)) return node.map(item => walk(item, depth + 1))
    const out: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(node)) out[key] = walk(item, depth + 1)
    return out
  }
  return walk(value, 0)
}

/**
 * Redacts every string inside a plain JSON value (a tool's structured result),
 * keeping its shape; the value itself comes back when nothing was hidden.
 * A value hidden in one string is hidden in every other string of the value too.
 */
export function redactDeep(value: unknown): { value: unknown; hits: Hits } {
  const hits: Hits = {}
  const found = new Map<string, string>()
  const first = mapStrings(value, node => {
    const done: Hits = {}
    const out = redactInto(node, done, found)
    if (countOf(done) === 0) return node
    addHits(hits, done)
    return out
  })
  if (countOf(hits) === 0) return { value, hits }
  // The second walk covers every string, also the ones that had no hit of their own.
  return { value: mapStrings(first, node => hideKnown(node, found)), hits }
}

type Block = { type: string; [field: string]: unknown }

// Maps the text a row's blocks carry through `f`: text blocks and each tool_result's content (a string or text blocks).
const mapBlockTexts = (content: readonly Block[], f: (text: string) => string): Block[] =>
  content.map((block): Block => {
    if (block.type === 'text' && typeof block.text === 'string') return { ...block, text: f(block.text) }
    if (block.type === 'tool_result') {
      const inner = block.content
      if (typeof inner === 'string') return { ...block, content: f(inner) }
      if (Array.isArray(inner)) {
        return {
          ...block,
          content: inner.map((part: Block) => (part.type === 'text' && typeof part.text === 'string' ? { ...part, text: f(part.text) } : part)),
        }
      }
    }
    return block
  })

/**
 * Redacts the text a row's blocks carry: text blocks and each tool_result's
 * content (a string or text blocks). Every other block is passed as it is.
 * A value hidden in one block is hidden in every other block of the row too.
 */
export function redactBlocks(content: readonly Block[]): { content: Block[]; hits: Hits } {
  const hits: Hits = {}
  const found = new Map<string, string>()
  const first = mapBlockTexts(content, text => {
    const done: Hits = {}
    const out = redactInto(text, done, found)
    addHits(hits, done)
    return out
  })
  // Nothing propagates when nothing was recorded: skip the second walk, which would only copy every block again.
  if (found.size === 0) return { content: first, hits }
  return { content: mapBlockTexts(first, text => hideKnown(text, found)), hits }
}

/** The same blocks with every text they carry withheld: what a failed scan stores. */
export function withhold(content: readonly Block[], note: string): Block[] {
  return content.map((block): Block => {
    if (block.type === 'text') return { ...block, text: note }
    if (block.type === 'tool_result') return { ...block, content: note }
    return block
  })
}

const SAFE_ENV = /^\.env\.(example|sample|template|dist|defaults|schema)$/i
const SECRET_FILES: RegExp[] = [
  /^\.env(\..+)?$/i,
  /^\.envrc$/,
  /\.(pem|key|p12|pfx|jks|keystore|asc|gpg)$/i,
  /^id_(rsa|dsa|ecdsa|ed25519)$/,
  /^\.?netrc$|^_netrc$/,
  /^\.npmrc$/, /^\.pypirc$/, /^\.git-credentials$/,
  /^credentials(\.json)?$/i,
  /^service[-_]?account.*\.json$/i,
  /^secrets?\.(ya?ml|json|toml|env)$/i,
  /^\.htpasswd$/,
]

/** Whether `path` names a file that usually holds secrets. */
export function isSecretFile(path: string): boolean {
  const parts = path.split(/[\\/]/)
  const name = parts.at(-1) ?? ''
  if (SAFE_ENV.test(name) || name.endsWith('.pub')) return false
  const parent = parts.at(-2) ?? ''
  if (parent === '.aws' && (name === 'credentials' || name === 'config')) return true
  if (parent === '.docker' && name === 'config.json') return true
  if (parent === '.kube' && name === 'config') return true
  if (parent === '.ssh' && name !== 'known_hosts' && name !== 'config' && name !== 'authorized_keys') return true
  return SECRET_FILES.some(pattern => pattern.test(name))
}

const LABELS: Record<string, string> = {
  'private-key': 'private key',
  'aws-access-key': 'AWS access key',
  'aws-secret-key': 'AWS secret key',
  'aws-session-token': 'AWS session token',
  'github-token': 'GitHub token',
  'gitlab-pat': 'GitLab personal access token',
  'gitlab-oauth-app-secret': 'GitLab OAuth application secret',
  'gitlab-deploy-token': 'GitLab deploy token',
  'gitlab-runner-token': 'GitLab runner authentication token',
  'gitlab-runner-registration-token': 'GitLab runner registration token',
  'gitlab-cicd-job-token': 'GitLab CI/CD job token',
  'gitlab-trigger-token': 'GitLab pipeline trigger token',
  'gitlab-feed-token': 'GitLab feed token',
  'gitlab-incoming-mail-token': 'GitLab incoming mail token',
  'gitlab-agent-token': 'GitLab agent for Kubernetes token',
  'gitlab-workspace-token': 'GitLab workspace token',
  'gitlab-scim-token': 'GitLab SCIM token',
  'gitlab-feature-flag-client-token': 'GitLab feature flag client token',
  'gitlab-session-cookie': 'GitLab session cookie',
  'anthropic-key': 'Anthropic API key',
  'openai-key': 'OpenAI API key',
  'slack-token': 'Slack token',
  'slack-app-token': 'Slack app-level token',
  'slack-config-token': 'Slack configuration token',
  'slack-webhook': 'Slack webhook',
  'stripe-key': 'Stripe key',
  'google-api-key': 'Google API key',
  'google-oauth-client-secret': 'Google OAuth client secret',
  'google-oauth-access-token': 'Google OAuth access token',
  'google-oauth-refresh-token': 'Google OAuth refresh token',
  'digitalocean-pat': 'DigitalOcean personal access token',
  'digitalocean-oauth-token': 'DigitalOcean OAuth token',
  'digitalocean-refresh-token': 'DigitalOcean refresh token',
  jwt: 'JWT',
  'npm-token': 'npm token',
  'pypi-token': 'PyPI token',
  'huggingface-token': 'Hugging Face token',
  'sendgrid-key': 'SendGrid key',
  'bearer-token': 'bearer token',
  'url-password': 'password in a URL',
  assignment: 'secret value',
  'connection-string-key': 'secret in a connection string',
}

const PLURALS: Record<string, string> = {
  'url-password': 'passwords in URLs',
  'bearer-token': 'bearer tokens',
  'slack-app-token': 'Slack app-level tokens',
  'slack-config-token': 'Slack configuration tokens',
  jwt: 'JWTs',
  'connection-string-key': 'secrets in connection strings',
}

/** A kind's name for people, with its count: `1 AWS access key`, `2 GitHub tokens`. */
export function label(kind: string, n = 1): string {
  const name = LABELS[kind] ?? kind
  return n === 1 ? `1 ${name}` : `${n} ${PLURALS[kind] ?? `${name}s`}`
}
