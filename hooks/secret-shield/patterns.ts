// Pure secret detection and redaction: no `$`, so tests and other mods can import it.

import { anthropicKey, huggingfaceToken, openaiKey48, openaiLegacyKey, openaiProjectKey } from './rules/ai'
import { awsAccessKey, awsSecretKeyAssignment, awsSecretKeyJson, awsSessionToken, googleApiKey } from './rules/cloud'
import { githubTokenClassic, githubTokenFineGrained } from './rules/code-hosts'
import { npmToken, pypiToken, sendgridKey } from './rules/dev-services'
import { bearerToken, jwt, privateKey } from './rules/key-material'
import { slackToken, slackWebhook, stripeSecretKey, stripeWebhookSecret } from './rules/messaging-payments'
import type { Rule } from './rules/rule'

export type Hits = Record<string, number>

/** What a redacted secret is replaced with. */
export const mark = (kind: string): string => `[JANITOR-REDACTED:${kind}]`

const MARK_BODY = String.raw`\[JANITOR-REDACTED:[A-Za-z0-9_-]+\]`
/** A value that IS a marker, whole. Anchored: a value that only contains one is judged on the rest. */
const MARK = new RegExp('^' + MARK_BODY + '$')
const MARKS = new RegExp(MARK_BODY, 'g')
// Built from MARK_BODY so the marker grammar has one source.
const URL_PASSWORD = new RegExp(
  String.raw`\b([a-z][a-z0-9+.-]*:\/\/)((?:` + MARK_BODY + String.raw`|[^\s:/@'"` + '`' + String.raw`\[])+):((?!\d{1,5}(?:\/|\?[^\s@#]*=))(?:(?!:\/\/)[^\s@'"` + '`' + String.raw`])+)@`,
  'gi',
)

// Specific, high-confidence token formats, defined by category under rules/ and listed here one by one.
// The order is load-bearing: rules run in this order and the first match wins, because a hidden token is
// skipped by every later rule. The private key runs first, so nothing inside a key block is matched on its
// own, and the more specific prefix (sk-ant-) runs before the more general one (sk-). Never build this list by
// concatenating the category files: their order is not this order. tests/patterns.test.ts pins it through TOKEN_ORDER.
// Never run these patterns directly: see rules/rule.ts.
const TOKENS: readonly Rule[] = [
  privateKey,
  awsAccessKey,
  awsSecretKeyAssignment,
  awsSecretKeyJson,
  awsSessionToken,
  githubTokenClassic,
  githubTokenFineGrained,
  anthropicKey,
  openaiProjectKey,
  openaiLegacyKey,
  openaiKey48,
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
const SECRET_NAME = /(^|[_.-])(secrets?|token|password|passwd|passphrase|pwd|pass|api_?key|apikey|private_?key|access_?key|auth_?key|auth_?token|client_?secret|credentials?|signing_?key|encryption_?key|session_?key|master_?key)([_.-]|$)/
// ...unless they are about the secret rather than the secret itself.
const NOT_SECRET_NAME = /[_.-](url|uri|endpoint|path|file|dir|name|type|expiry|expires|expires_at|ttl|length|header|id|count|limit|size|prefix|env|var|mode|enabled|required|policy|hint|prompt|label|placeholder|field|format)$/

function isSecretName(name: string): boolean {
  const snake = name.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toLowerCase()
  return SECRET_NAME.test(snake) && !NOT_SECRET_NAME.test(snake)
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

/** Replaces each match of `rule` with its mark, counting into `hits`. Exported so tests can drive a synthetic rule. */
export function applyRule(text: string, rule: Rule, hits: Hits): string {
  // String.prototype.replace with a /g pattern sets lastIndex to 0 before it starts, so a lastIndex left behind by
  // anyone who ran .test() or .exec() on this shared RegExp cannot make it skip text. Keep it a replace (no exec loop).
  return text.replace(rule.pattern, (match: string, ...groups: unknown[]) => {
    const group = rule.group ?? 0
    const secret = group === 0 ? match : String(groups[group - 1] ?? '')
    if (secret === '' || MARK.test(secret)) return match
    hits[rule.kind] = (hits[rule.kind] ?? 0) + 1
    // Hide every non-overlapping copy of the captured text inside the match. A string replace hides the first copy
    // only, and the first copy can sit in the gap before the capture (key name, gap, then the quoted value), which
    // leaves the captured secret in view. Hiding the group by its index would leak the other copy instead (found
    // during the UBS triage of 2026-11-04; UBS did not report it; TRDD-Q6LPJTPO). The hit is still counted once per
    // match. The `secret === ''` guard above must stay before the split: `match.split('')` splits into single
    // characters, and the join would put a marker between every pair.
    return group === 0 ? mark(rule.kind) : match.split(secret).join(mark(rule.kind))
  })
}

/** A password in a URL's userinfo part: keeps the scheme, user and host, hides the password. */
function redactUrlPasswords(text: string, hits: Hits): string {
  // The password may contain a slash. A value of up to 5 digits followed by / is a port followed by a
  // path, and up to 5 digits followed by a ? query with an = before the at-sign is a port followed by a
  // query (`host:8080/pkg/@scope`, `localhost:3000?email=a@b`), so the lookahead skips both. Other digits
  // (`2024#Spring`, `12?abc`) are a password and are hidden. The user part may contain whole markers
  // (a token hidden first, such as an AWS access key used as the user name) but no other [,
  // so a bracketed IPv6 host is never read as a user. A password cannot contain :// so it never runs
  // into a second URL. Known false positive: `localhost:3000#a@b` reads its fragment as a password.
  return text.replace(URL_PASSWORD, (match, scheme: string, user: string, password: string) => {
    const rest = password.replace(MARKS, '')
    if (rest === '' || PLACEHOLDER.test(rest)) return match
    hits['url-password'] = (hits['url-password'] ?? 0) + 1
    return `${scheme}${user}:${mark('url-password')}@`
  })
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
function redactAssignments(text: string, hits: Hits): string {
  const line = /^([ \t]*(?:export[ \t]+)?(?:(?:const|let|var|readonly|final|static|private|public)[ \t]+)*["']?)([A-Za-z_][A-Za-z0-9_.-]*)(["']?[ \t]*(?::[ \t]*[A-Za-z<>[\]|]+[ \t]*)?[=:][ \t]*)(["'`]?)([^\n\r]*?)\4([,;]?(?:[ \t]+(?:#|\/\/).*)?[ \t]*)$/gm
  let out = text.replace(line, (match, lead: string, name: string, sep: string, quote: string, value: string, tail: string) => {
    if (!isSecretName(name)) return match
    // `x == y` is a comparison, not an assignment.
    if (value.startsWith('=')) return match
    if (!looksSecret(value, quote !== '')) return match
    hits.assignment = (hits.assignment ?? 0) + 1
    return `${lead}${name}${sep}${quote}${mark('assignment')}${quote}${tail}`
  })
  for (const pair of [JSON_ESCAPED, JSON_PLAIN]) {
    out = out.replace(pair, (match, esc: string, name: string, sep: string, value: string, end: string) => {
      // A value that never closed (it ran to the end of the line) is judged as unquoted: without its closing quote
      // nothing says where it ends, so a short word such as `"password": "notasecret` is not hidden.
      if (!isSecretName(name) || !looksSecret(value, end.endsWith('"'))) return match
      hits.assignment = (hits.assignment ?? 0) + 1
      // `end` is the closing quote, or what was left of it (nothing, or some of its backslashes) when the value ran to the end of the line.
      return `${esc}"${name}${esc}"${sep}${esc}"${mark('assignment')}${end}`
    })
  }
  return out
}

/** Every secret in `text` replaced by its mark, and how many of each kind. */
export function redact(text: string): { text: string; hits: Hits } {
  const hits: Hits = {}
  let out = text
  for (const rule of TOKENS) out = applyRule(out, rule, hits)
  out = redactUrlPasswords(out, hits)
  out = redactAssignments(out, hits)
  return { text: out, hits }
}

export function countOf(hits: Hits): number {
  return Object.values(hits).reduce((sum, n) => sum + n, 0)
}

export function addHits(into: Hits, from: Hits): Hits {
  for (const [kind, n] of Object.entries(from)) into[kind] = (into[kind] ?? 0) + n
  return into
}

/**
 * Redacts every string inside a plain JSON value (a tool's structured result),
 * keeping its shape; the value itself comes back when nothing was hidden.
 */
export function redactDeep(value: unknown): { value: unknown; hits: Hits } {
  const hits: Hits = {}
  const walk = (node: unknown, depth: number): unknown => {
    if (typeof node === 'string') {
      const done = redact(node)
      if (countOf(done.hits) === 0) return node
      addHits(hits, done.hits)
      return done.text
    }
    if (depth > 12 || node === null || typeof node !== 'object') return node
    if (Array.isArray(node)) return node.map(item => walk(item, depth + 1))
    const out: Record<string, unknown> = {}
    for (const [key, item] of Object.entries(node)) out[key] = walk(item, depth + 1)
    return out
  }
  const out = walk(value, 0)
  return { value: countOf(hits) === 0 ? value : out, hits }
}

type Block = { type: string; [field: string]: unknown }

/**
 * Redacts the text a row's blocks carry: text blocks and each tool_result's
 * content (a string or text blocks). Every other block is passed as it is.
 */
export function redactBlocks(content: readonly Block[]): { content: Block[]; hits: Hits } {
  const hits: Hits = {}
  const scrub = (text: string): string => {
    const done = redact(text)
    addHits(hits, done.hits)
    return done.text
  }
  const blocks = content.map((block): Block => {
    if (block.type === 'text' && typeof block.text === 'string') return { ...block, text: scrub(block.text) }
    if (block.type === 'tool_result') {
      const inner = block.content
      if (typeof inner === 'string') return { ...block, content: scrub(inner) }
      if (Array.isArray(inner)) {
        return {
          ...block,
          content: inner.map((part: Block) => (part.type === 'text' && typeof part.text === 'string' ? { ...part, text: scrub(part.text) } : part)),
        }
      }
    }
    return block
  })
  return { content: blocks, hits }
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
  'anthropic-key': 'Anthropic API key',
  'openai-key': 'OpenAI API key',
  'slack-token': 'Slack token',
  'slack-webhook': 'Slack webhook',
  'stripe-key': 'Stripe key',
  'google-api-key': 'Google API key',
  jwt: 'JWT',
  'npm-token': 'npm token',
  'pypi-token': 'PyPI token',
  'huggingface-token': 'Hugging Face token',
  'sendgrid-key': 'SendGrid key',
  'bearer-token': 'bearer token',
  'url-password': 'password in a URL',
  assignment: 'secret value',
}

const PLURALS: Record<string, string> = {
  'url-password': 'passwords in URLs',
  'bearer-token': 'bearer tokens',
  jwt: 'JWTs',
}

/** A kind's name for people, with its count: `1 AWS access key`, `2 GitHub tokens`. */
export function label(kind: string, n = 1): string {
  const name = LABELS[kind] ?? kind
  return n === 1 ? `1 ${name}` : `${n} ${PLURALS[kind] ?? `${name}s`}`
}
