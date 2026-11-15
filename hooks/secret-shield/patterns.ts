// Pure secret detection and redaction: no `$`, so tests and other mods can import it.

import { anthropicKey, huggingfaceToken, openaiKey48, openaiLegacyKey, openaiProjectKey } from './rules/ai'
import { awsAccessKey, awsSecretKeyAssignment, awsSecretKeyJson, awsSessionToken, digitaloceanOAuthToken, digitaloceanPat, digitaloceanRefreshToken, googleApiKey, googleOAuthAccessToken, googleOAuthClientSecret, googleOAuthRefreshToken } from './rules/cloud'
import { githubTokenClassic, githubTokenFineGrained, gitlabAgentToken, gitlabCicdJobToken, gitlabDeployToken, gitlabFeatureFlagClientToken, gitlabFeedToken, gitlabIncomingMailToken, gitlabOAuthAppSecret, gitlabPat, gitlabRunnerRegistrationToken, gitlabRunnerToken, gitlabScimToken, gitlabSessionCookie, gitlabSessionCookieValueFirst, gitlabTriggerToken, gitlabWorkspaceToken } from './rules/code-hosts'
import { npmToken, pypiToken, sendgridKey } from './rules/dev-services'
import { bearerToken, jwt, jwtWide, privateKey } from './rules/key-material'
import { slackAppToken, slackConfigAccessToken, slackConfigRefreshToken, slackToken, slackWebhook, stripeApiKey, stripeWebhookSecret } from './rules/messaging-payments'
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
// WHY URL-password redaction reads the text by hand and no regex repeats a group over it (TRDD-AGV84UGC; the measurements are TRDD-HF7GNHNF and TRDD-AGOEWF2E): measured under claude plugin test, a greedy loop over a GROUP
// (a group that repeats a character run and a colon or a marker, as the user part, the password and the port-skip query once did) has two iteration-count ceilings in that engine: the loop
// runs about 35 times slower per character once one run passes about 63.8K iterations (last fast run 63,808, first slow 63,824; still linear), and it returns no match at all, silently,
// from about 553K iterations (last hidden 552,896, first missed 552,960). A loop over a single character class has neither ceiling (hidden at 4 MB). Node (V8) and the system Bun 1.3.14
// show no step (Bun misses from about 360K, Node throws a RangeError at 2^23), so the regex itself and backtracking are ruled out. The engine is inferred to be the JavaScriptCore inside
// Claude Code, whose binary names Bun v1.4.4: not asserted. So the user part is walked as runs of user characters and whole markers, the password is the run up to PASSWORD_END, and the
// port-skip query is read up to QUERY_STOP: every scan is one character class, and each ends at or before the next `://`, so the spans never overlap and the cost is linear.
// WHY hasScheme is the only scheme gate and reads back from each `://`: a prefix that starts at every word boundary and scans the whole run of scheme characters (letters, digits, `+`, `.`, `-`) looking for
// `://` is quadratic on a long run with none (base64, hex, a hyphenated blob; 16 KB of `A1-` took 0.5-1.4 s, 64 KB did not finish in 10 minutes). Reading back over the run once per `://` is
// linear, because the runs before two `://` never overlap. It gives up nothing: the scheme may be of any length. Do not cap the scheme length: a cap would stop hiding a scheme of more than N unbroken letters.
// WHY QUERY_STOP ends the port-skip query scan at `://` and the scan does not look for an `=` with indexOf or a class that crosses it: that scan would run on past every later `://` up to the next whitespace, `@` or `#`,
// at the latest the end of the text, so `b://u:1?` repeated k times and followed by n characters cost O(k*n) (k=4000, n=64 KB took 18.5 s in system Bun under load). Stopping at `://` changes no result:
// the `@` that would end the password cannot lie past the next `://`, because a password cannot cross one, and both readings hide nothing there.
// WHY the counts of markers and colons are still taken (redactUrlPasswords): they were the iteration counts the group loops ran. Past URL_PASSWORD_BOUND of either, the port skip is not applied and the
// password is not propagated, and the password region that ends at `@` is hidden whole, so it fails closed. A port followed by a longer query would be read as a password, which hides more, never less.
// The bound governs only that behaviour now; it is kept because tests/url-password-walk.test.ts pins it. "Do not cap the scan length" still holds: a cap on a scan would stop reading and FAIL OPEN, so none exists.
// Disclosed over-hide above the bound, for security first: (1) a port followed by a path, a `?query` or a `#fragment` that holds more than the bound of colons before an `@` is read as a password and hidden,
// because the port skip is not applied there; (2) markers (tokens hidden earlier) inside the hidden region collapse into one url-password marker, their hits stay counted; (3) such a value is not
// added to `found`, so it is not hidden elsewhere in the row (a value that long is not propagated). Not guarded: the scheme and the user part must be valid as the walk reads them, so `1://`, `_a://`
// and `.://` shapes are not touched. Placeholder and marker-only passwords (`x`, `${VAR}`, or markers alone) are left alone above the bound, the same as below it.
const NOT_USER = String.raw`[^\s:/@'"${'`'}\[]`
// A password that starts with 1-5 digits and then `/` or `?` may be a port followed by a path or a query (the port-skip test).
const PORT_START = /\d{1,5}[/?]/y
// Ends the port-skip query scan: an `=` first means a query, not a password; whitespace, `@`, `#` or `://` first means there is no `=` before the end.
const QUERY_STOP = /[=\s@#]|:\/\//g
/** The most markers in a URL's user part, and the most colons in its password span, up to which a port is told from a password and the password is recorded for propagation. Above it the password is hidden without the port skip and is not propagated. Kept because tests/url-password-walk.test.ts pins that behaviour. */
export const URL_PASSWORD_BOUND = 4096
// The pieces the walk reads a `://` with: a run of user characters, a whole marker, the end of the span whose colons are counted, the end of the password.
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
  stripeApiKey,
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

// WHY two flat checks and not one regex with a repeated group: the slug and dotted-name shapes were each written as a run, then a group of a joiner
// and a run, repeated. That form was linear (each repeat starts on a joiner the run before it cannot take), but skillaudit's REGEX_DOS rule flags
// every repeated group that holds a quantifier, and the CPV release gate blocks on it. These checks accept exactly the same strings (the exhaustive
// differential in tests/patterns.test.ts compares them with the old regexes) and use only flat class loops. Exported for that test.
/** A lowercase-word slug (`my-app-db-credentials`, `secret/data/myapp`): runs of a-z joined by single `-`, `_`, `.` or `/`, at least one joiner. */
export function isLowercaseSlug(value: string): boolean {
  return /^[a-z][a-z./_-]*[a-z]$/.test(value) && /[./_-]/.test(value) && !/[./_-]{2}/.test(value)
}
/** A dotted name (`api.example.com`, `build-01.example.net`): runs of letters, digits and `-` joined by single dots, at least one dot. */
export function isDottedName(value: string): boolean {
  return /^[A-Za-z0-9-][A-Za-z0-9.-]*[A-Za-z0-9-]$/.test(value) && value.includes('.') && !value.includes('..')
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
  if (isLowercaseSlug(value)) return false
  if (value.startsWith('/') || value.startsWith('~/') || value.startsWith('./') || value.startsWith('../')) return false
  // A path or vault key (`prod/db/password`) holds a slash; a base64 secret does too, but only with all three kinds of character.
  if (value.includes('/') && !(/[A-Z]/.test(value) && /[a-z]/.test(value) && hasDigit)) return false
  if (value.includes('://')) return false
  if (/^[^@\s]+@[A-Za-z0-9.-]+\.[A-Za-z]+$/.test(value)) return false
  if (/^[A-Za-z0-9.-]+:\d{1,5}$/.test(value)) return false
  if (isDottedName(value) && /^[A-Za-z]+$/.test(value.slice(value.lastIndexOf('.') + 1))) return false
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

/** Whether the text before the `://` at `end` ends in a scheme, the only scheme gate: a letter, with no word character before it, inside the run of scheme characters (letters, digits, `+`, `-`, `.`). */
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
  // query (`host:8080/pkg/@scope`, `localhost:3000?email=a@b`), so the port-skip test skips both. Other digits
  // (`2024#Spring`, `12?abc`) are a password and are hidden. The user part may contain whole markers
  // (a token hidden first, such as an AWS access key used as the user name) but no other [,
  // so a bracketed IPv6 host is never read as a user. A password cannot contain :// so it never runs
  // into a second URL. Known false positive: `localhost:3000#a@b` reads its fragment as a password.
  // WHY a loop over each `://` that reads the text by hand and no regex over the whole text: see the first WHY block above. hasScheme is the only scheme gate. The user part, the password
  // (up to PASSWORD_END) and the port-skip query (up to QUERY_STOP) are each read by a scan over a single character class that stops at the next `://`, so the spans never overlap
  // and the cost is linear. The counts of markers and colons below only decide the port skip and the propagation, as URL_PASSWORD_BOUND says.
  let next = 0
  let done = 0
  const parts: string[] = []
  for (let idx = text.indexOf('://'); idx !== -1; idx = text.indexOf('://', next)) {
    next = idx + 1
    if (!hasScheme(text, idx)) continue
    // The user part: runs of non-separator characters and whole markers. A marker holds a `:` and a `[`, so it is read whole first.
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
    // The bound no longer guards a regex (none runs over the span). It governs only the port skip and the propagation below, which are kept as the tests pin them.
    const underBound = markers <= URL_PASSWORD_BOUND && colons <= URL_PASSWORD_BOUND
    // The password is the run up to the first whitespace, quote, backtick, `@` or `://`, and it must end at `@`. No regex repeats a group over it: a loop over a group meets the engine ceilings (the first WHY block above).
    PASSWORD_END.lastIndex = colon + 1
    const end = PASSWORD_END.exec(text)?.index ?? text.length
    if (text[end] !== '@' || end === colon + 1) continue
    // Port skip, only up to the bound: above it a port followed by a long query is read as a password and hidden (fail closed, disclosed over-hide). The first terminator after the `?` decides: an `=` means a query.
    if (underBound) {
      PORT_START.lastIndex = colon + 1
      const port = PORT_START.exec(text)
      if (port !== null) {
        if (port[0].endsWith('/')) continue
        QUERY_STOP.lastIndex = colon + 1 + port[0].length
        if (QUERY_STOP.exec(text)?.[0] === '=') continue
      }
    }
    const password = text.slice(colon + 1, end)
    // WHY the placeholder check applies at every size: without it a password that is only markers or a placeholder (`x`, `${VAR}`) was hidden above the bound but not at or under it,
    // so redact() on its own output (the region is one marker) counted a phantom hit and was not idempotent. Every other region that ends at `@` is hidden (fail closed).
    const rest = password.replace(MARKS, '')
    if (rest === '' || PLACEHOLDER.test(rest)) continue
    hits['url-password'] = (hits['url-password'] ?? 0) + 1
    // A password above the bound is not recorded, so it is not hidden elsewhere in the row (a value that long is not propagated).
    if (underBound && propagates(password)) found.set(password, 'url-password')
    parts.push(text.slice(done, colon + 1), mark('url-password'))
    done = end
    next = end + 1
  }
  if (parts.length === 0) return text
  parts.push(text.slice(done))
  return parts.join('')
}


// GitLab session cookie windows (TRDD-Q6LPJTPO, option B). The two rules in rules/code-hosts.ts read the value from the text right after the name; the review of eb370f5e listed
// the forms they cannot read (Python keyword arguments, a Ruby hash rocket, a compact Rails hash, a key of 16 or more characters after the name in compact JSON, `defaultvalue`, a
// value nested under the name in JSON or YAML, a Ruby symbol in a positional call, a tab before `=`, a Go raw string). Every one of them keeps the VALUE next to the NAME, and the
// value has a fixed shape, so this pass looks for the shape in a window around each name instead of parsing the syntax between them.
// The shape (read in GitLab master): lib/gitlab/sessions/cache_store.rb:57-59 builds the stored id as `prefix + DELIMITER("-") + super.public_id`, and the Rails compatibility
// generate_sid is `SecureRandom.hex(16)`, so a value is an optional `<prefix>-` followed by exactly 32 lowercase hex characters. The prefix is free text (empty by default,
// `cell-<id>` with Cells), so it is any run of 1 to 40 of `[0-9A-Za-z_.-]` ending in a hyphen. Both old rules stay: they hide values of other shapes (any 16 or more characters).
// WHY a window and not a syntax: the window is the text AFTER the name (up to the first `;` or `}`, the next name, or 512 characters) and the text BEFORE it (back to the nearest
// `;`, `{` or `}`, the previous name, or 512 characters). It does NOT stop at a line break (the YAML form puts the value on the next line) and it does NOT stop at a JANITOR marker:
// the old rules run first and, for the forms above, may have hidden the wrong text between the name and the value, so a marker there says nothing about where the value is.
// `;` ends a cookie in a header, `{` and `}` end the object that holds the name, and 512 characters cover the widest real export (about 150 between name and value).
// WHY the hex is lowercase only: Rails and Rack write lowercase, so an upper-case 32-hex run after the name is not a session id of GitLab (it is disclosed as a miss in
// KNOWN-MISSES.md gitlab-session-cookie-uppercase-hex); accepting it would hide upper-case hashes and GUIDs for nothing. The value must not be followed by a letter or a digit
// (a 40-hex commit id or a 64-hex Geo suffix is not a value), and it starts at the start of the window, after a character that is not a letter or a digit (and not `%`), or right
// after a `%XX` URL escape (`%3D`, `%22`), so the `3D` of an escape is never taken for the start of a prefix.
// Disclosed over-hide: any other run of 32 lowercase hex characters inside a window (an MD5, an ETag, a trace id) is hidden too; the window is short and the name says session.
// Windows are merged where they overlap, and each value is scanned once, so the cost is O(n + names x 1024) and a second pass finds nothing (a hidden value is a marker).
// The windows exclude the name itself: a prefix that reached back over the name would hide the name. A value is counted under the same kind as the old rules, and is added to
// `found` when propagates() accepts it, as applyRule does.
const SESSION_NAME_ANY = /_gitlab_session/i
const SESSION_NAME_EACH = /_gitlab_session/gi
const SESSION_NAME_LENGTH = 15
const SESSION_WINDOW = 512
const SESSION_VALUE = /(?:(?<![0-9A-Za-z%])|(?<=%[0-9A-Fa-f]{2}))(?:[0-9A-Za-z_.-]{1,40}-)?[0-9a-f]{32}(?![0-9A-Za-z])/g
const isAlnum = (code: number): boolean => (code >= 48 && code <= 57) || (code >= 65 && code <= 90) || (code >= 97 && code <= 122)
function redactGitlabSessionWindows(text: string, hits: Hits, found: Map<string, string>): string {
  if (!SESSION_NAME_ANY.test(text)) return text
  const names: number[] = []
  for (const match of text.matchAll(SESSION_NAME_EACH)) names.push(match.index)
  // Whether a value may start at `at`: after a character that is not a letter, a digit or `%`, or right after a `%XX` escape. Used where a window starts in the middle of the text.
  const startOk = (at: number): boolean => {
    if (at === 0) return true
    const before = text.charCodeAt(at - 1)
    if (at >= 3 && text.charCodeAt(at - 3) === 37 && /^[0-9A-Fa-f]{2}$/.test(text.slice(at - 2, at))) return true
    return !isAlnum(before) && before !== 37
  }
  const endOk = (at: number): boolean => at >= text.length || !isAlnum(text.charCodeAt(at))
  // Windows in text order: for each name its BEFORE and its AFTER, never the name itself. A window that overlaps or touches the previous one is merged into it.
  const windows: Array<{ start: number; end: number; checkStart: boolean }> = []
  const add = (start: number, end: number, checkStart: boolean): void => {
    if (start >= end) return
    const last = windows[windows.length - 1]
    if (last !== undefined && start <= last.end) last.end = Math.max(last.end, end)
    else windows.push({ start, end, checkStart })
  }
  names.forEach((at, i) => {
    const previousEnd = i > 0 ? names[i - 1] + SESSION_NAME_LENGTH : 0
    let start = at
    for (const floor = Math.max(previousEnd, at - SESSION_WINDOW); start > floor; start--) {
      const code = text.charCodeAt(start - 1)
      if (code === 59 || code === 123 || code === 125) break
    }
    add(start, at, start > previousEnd)
    const end = at + SESSION_NAME_LENGTH
    const ceiling = Math.min(i + 1 < names.length ? names[i + 1] : text.length, end + SESSION_WINDOW, text.length)
    let stop = end
    for (; stop < ceiling; stop++) {
      const code = text.charCodeAt(stop)
      if (code === 59 || code === 125) break
    }
    add(end, stop, false)
  })
  const kind = 'gitlab-session-cookie'
  const parts: string[] = []
  let done = 0
  for (const span of windows) {
    const piece = text.slice(span.start, span.end)
    SESSION_VALUE.lastIndex = 0
    for (let match = SESSION_VALUE.exec(piece); match !== null; match = SESSION_VALUE.exec(piece)) {
      const at = span.start + match.index
      const stop = at + match[0].length
      // A window cut by the 512-character cap may start or end inside a longer run of letters and digits; the real neighbours decide, and a rejected match retries one character on.
      if ((match.index === 0 && span.checkStart && !startOk(at)) || !endOk(stop)) {
        SESSION_VALUE.lastIndex = match.index + 1
        continue
      }
      hits[kind] = (hits[kind] ?? 0) + 1
      if (propagates(match[0])) found.set(match[0], kind)
      parts.push(text.slice(done, at), mark(kind))
      done = stop
    }
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
// WHY JSON_ESCAPED is anchored on the opening quote and not on the backslash run (TRDD-U5O72MGA): the form `(\\+)"name"...` took the whole rest of a run of n backslashes
// from every backslash of the run and backtracked it, O(n) per start and O(n^2) overall: measured under bun (JavaScriptCore, the engine of claude plugin test), this pass
// alone took 278, 1,115 and 4,477 ms at 27K, 54K and 108K backslashes (ratio 4.0 per doubling) and was 99% of redact(), for a run of backslashes and for a quote followed by escaped pairs alike.
// The escape run of a match is not free: the run after the key name must be exactly the run before its opening quote (`\1"`), and only the last `\1` backslashes of a longer run
// before the quote are group 1 (a run of 2 before the quote and one after the name matches from the second backslash). So the match is found from the quote: the lookahead
// reads `"name` and the run after it once, atomically, and takes that run as group 1; the lookbehind `(?<=\1)` then checks that the same number of backslashes stands before the quote.
// Each quote costs the name and the run after it, and a name and a run contain no quote, so the whole pass is linear. The match starts at the quote, not at the run, so the
// text in front of it is not part of it: hideEscapedPair drops the run from what hideJsonPair builds. Checked against the old pattern on 500,000 seeded strings of
// backslashes, quotes, escape pairs, JSON fragments and secrets in escaped JSON with 0 differences, and at 1 MB redact() takes about 16 ms on each shape, 57 ms with a secret after the run (the tests of TRDD-U5O72MGA).
export const JSON_ESCAPED = new RegExp(String.raw`(?="[A-Za-z0-9_.-]+(\\+)")(?<=\1)"([A-Za-z0-9_.-]+)\1"(\s*:\s*)\1"([^"\\\r\n]{3,})(\1"|\\*$)`, 'gm')
// WHY JSON_ESCAPE_BOUND (TRDD-AGOEWF2E): the escape loop of JSON_PLAIN, which takes one escape pair and the run of plain characters after it per iteration, repeats once per escape pair, so it has the iteration-count ceilings
// described in the first WHY block of this file (URL-password redaction) in the engine of claude plugin test: about 35 times slower per character past about 63.8K iterations, and no match at all, silently, from
// 589,823 iterations (measured), so a secret-named value with that many escapes was not hidden. The loop is bounded to `{0,JSON_ESCAPE_BOUND}` iterations. The bound sits below
// the slow step: measured under claude plugin test (2026-11-13), the exact bounded regex took the same time per character at 16,384, 32,768 and 49,152 escape pairs
// (ratio 1.00, 1.00, 0.99), and 41 times longer per character at 65,536. A value with more escapes than the bound is not read by this regex at all (redactOverBoundJson).
export const JSON_ESCAPE_BOUND = 49152
const JSON_PLAIN = jsonPair('', String.raw`[^"\\\r\n]*(?:\\.[^"\\\r\n]*){0,${JSON_ESCAPE_BOUND}}`)
// The opening of a pair `"name": "`, found for every pair of the text: redactOverBoundJson then walks the value and counts its escape pairs itself.
// WHY no lookahead for the escape count (TRDD-MC895I0A): this was `"(name)"(sep)"(?=(?:[^"\\\r\n]*\\.){JSON_ESCAPE_BOUND + 1})`. That lookahead is linear (measured under claude plugin test,
// 2026-11-13: the same time per character at 16,385, 32,769 and 49,153 escape pairs) but it is a quantified group with an inner quantifier, a shape the CPV skillaudit REGEX_DOS
// scanner refuses by design, so the gate blocked on it. Counting in the walk the function already does gives the same result with no such group, and the engine's own
// retry after a failed lookahead is written out in the function as `lastIndex = match.index + 1`.
const JSON_OVER_BOUND = /"([A-Za-z0-9_.-]+)"(\s*:\s*)"/gm
const JSON_RUN = /[^"\\\r\n]*/y

/**
 * Hides each secret-named plain JSON value that holds more than JSON_ESCAPE_BOUND escape pairs, which JSON_PLAIN cannot read.
 * WHY a linear scan with the grammar of JSON_PLAIN and no regex loop: a value this long is past the ceilings of a group loop. The scan takes a run of
 * ordinary characters, steps over a backslash and the character after it (anything but a line end, the same `.` as the regex), and stops at a bare quote,
 * at a line end, or at a backslash followed by a line end or the end of the text; `end` is what JSON_PLAIN's end group would have kept (the quote, or that last backslash).
 * WHY it FAILS CLOSED: looksSecret and the STRONG_NAME gate are NOT applied, nor is any placeholder exemption: a value of a secret-named key that long is hidden whole.
 * Over-hide, disclosed: a secret-named value with more than the bound of escapes is hidden without those checks, including values of 49,153 to 589,822 escapes that
 * were judged by them before. The output is one marker with no escapes, so a second redact() leaves it alone (idempotent).
 * Not covered, and unchanged: escaped (nested) JSON over the bound, `\"name\":\"...\"` with that many escapes, which JSON_ESCAPED never read (a known miss).
 * The fast path counts backslashes: a text with no more than the bound of them cannot hold a value over it, since every escape pair holds at least one.
 */
function redactOverBoundJson(text: string, hits: Hits, found: Map<string, string>): string {
  let backslashes = 0
  for (let at = text.indexOf('\\'); at !== -1 && backslashes <= JSON_ESCAPE_BOUND; at = text.indexOf('\\', at + 1)) backslashes++
  if (backslashes <= JSON_ESCAPE_BOUND) return text
  const parts: string[] = []
  let done = 0
  JSON_OVER_BOUND.lastIndex = 0
  for (let match = JSON_OVER_BOUND.exec(text); match !== null; match = JSON_OVER_BOUND.exec(text)) {
    // WHY `match.index + 1` and not the end of the match, on every path that does not hide a value (TRDD-MC895I0A): the old regex carried a lookahead for more than the bound of escape pairs, and when it
    // failed the engine retried at the next position. This is that retry, and it must stay one position: the closing quote of a value is the opening quote of the next pair (`"a":"x"token":"...`),
    // and a match that ended at the value start would skip it. A name that is not secret takes no walk at all.
    // WHY +1 is also right where the old code, after a match whose lookahead had held, resumed at the value start (a non-secret name over the bound): the walk of an over-bound value stops first at a
    // backslash, never at a quote (a quote before its first backslash would end it with no escape pair), so no `"name"` opening can begin at the value's opening quote (`start - 1`, the quote this match
    // shares with its value), and none can begin inside the name or the separator either; the positions between `match.index + 1` and the value start find nothing, and the scan goes on from the value start as before.
    if (!isSecretName(match[1])) {
      JSON_OVER_BOUND.lastIndex = match.index + 1
      continue
    }
    const start = match.index + match[0].length
    let at = start
    let end = ''
    let resume = 0
    let pairs = 0
    for (;;) {
      JSON_RUN.lastIndex = at
      at += JSON_RUN.exec(text)?.[0].length ?? 0
      const char = text[at]
      if (char === '"') {
        end = '"'
        resume = at + 1
        break
      }
      if (char === undefined || char === '\r' || char === '\n') {
        resume = at
        break
      }
      // A backslash: the regex pairs it with any character `.` matches, which is not a line end (\r, \n, U+2028 and U+2029 count as one too); otherwise the value stops and the backslash is the end.
      const after = text.charCodeAt(at + 1)
      if (Number.isNaN(after) || after === 13 || after === 10 || after === 0x2028 || after === 0x2029) {
        end = '\\'
        resume = at + 1
        break
      }
      at += 2
      // A counted pair is one the old lookahead counted: a run, a backslash, and a character that is not a line end. The last backslash of a value cut at a line end is not one.
      pairs++
    }
    // At most the bound of pairs: JSON_PLAIN reads this value (it reads up to the bound), so it is not this pass's to hide.
    if (pairs <= JSON_ESCAPE_BOUND) {
      JSON_OVER_BOUND.lastIndex = match.index + 1
      continue
    }
    const value = text.slice(start, resume - end.length)
    hits.assignment = (hits.assignment ?? 0) + 1
    if (propagates(value)) found.set(value, 'assignment')
    parts.push(text.slice(done, start), mark('assignment'), end)
    done = resume
    JSON_OVER_BOUND.lastIndex = resume
  }
  if (parts.length === 0) return text
  parts.push(text.slice(done))
  return parts.join('')
}

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
  const hideJsonPair = (match: string, esc: string, name: string, sep: string, value: string, end: string): string => {
    // A value that never closed (it ran to the end of the line) is judged as unquoted: without its closing quote
    // nothing says where it ends, so a short word such as `"password": "notasecret` is not hidden.
    if (!isSecretName(name) || !looksSecret(value, end.endsWith('"'))) return match
    // WHY: the same STRONG_NAME gate as the line pass above (TRDD-Q6LPJTPO).
    if (isStrongName(name) && !strongValue(value)) return match
    hits.assignment = (hits.assignment ?? 0) + 1
    if (propagates(value)) found.set(value, 'assignment')
    // `end` is the closing quote, or what was left of it (nothing, or some of its backslashes) when the value ran to the end of the line.
    return `${esc}"${name}${esc}"${sep}${esc}"${mark('assignment')}${end}`
  }
  // JSON_ESCAPED matches from the opening quote, so the backslash run in front of the pair is outside the match and is not written again (TRDD-U5O72MGA).
  const hideEscapedPair = (match: string, esc: string, name: string, sep: string, value: string, end: string): string => {
    const hidden = hideJsonPair(match, esc, name, sep, value, end)
    return hidden === match ? match : hidden.slice(esc.length)
  }
  // WHY three statements and not a loop over the two patterns: the over-bound pass must run between them, and BEFORE JSON_PLAIN. With its
  // `{0,JSON_ESCAPE_BOUND}` and the `\\*$` end alternative, JSON_PLAIN claims a PREFIX of an over-bound value when the rest of its line is only
  // backslashes (more than the bound of `\\` pairs, cut off at the end of the line): it hides the prefix and leaves the backslashes visible. The pass
  // hides the whole value first, so JSON_PLAIN never sees it (TRDD-AGOEWF2E).
  out = out.replace(JSON_ESCAPED, hideEscapedPair)
  out = redactOverBoundJson(out, hits, found)
  out = out.replace(JSON_PLAIN, hideJsonPair)
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
  // Right after the provider tokens, so every provider rule wins first and its own kind stays; before the URL passwords, which never see a session value.
  out = redactGitlabSessionWindows(out, hits, found)
  out = redactUrlPasswords(out, hits, found)
  out = redactAssignments(out, hits, found)
  out = redactConnectionStrings(out, hits, found)
  // WHY jwtWide is the LAST pass and not a TOKENS entry (TRDD-6A3XW3VO): measured over 39072 contextual inputs (22 contexts x 8 tails x 222 tokens), jwtWide in
  // TOKENS regressed 10962 of them. It pre-empts the bearer-token rule and the assignment and connection-string passes (cookies and URL userinfo were unaffected): they then see a marker, not the
  // whole value, and leave the value's tail visible (an Authorization header holding `Bearer <jr-shape token>+/=xyz` became `Bearer [mark]+/=xyz`). As the last pass it only hides what
  // every other rule left, so those values keep their kind and their whole hide (0 regressions over the same inputs). The jwt rule keeps its TOKENS position; its own
  // pre-emption of current-shape tokens in those contexts is older and tracked separately.
  // It must stay the final applyRule before return: a pass added below it would be pre-empted the same way and re-create the regression,
  // pinned by tests/test_secret_shield_jwtwide_last_pass.py.
  out = applyRule(out, jwtWide, hits, found)
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
  /^\.(?:npmrc|pypirc|git-credentials)$/,
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
