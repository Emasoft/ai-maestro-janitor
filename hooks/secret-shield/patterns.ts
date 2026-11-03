// Pure secret detection and redaction: no `$`, so tests and other mods can import it.

export type Hits = Record<string, number>

type Rule = {
  kind: string
  pattern: RegExp
  /** Which capture group is the secret; 0 (the default) is the whole match. */
  group?: number
}

/** What a redacted secret is replaced with. */
export const mark = (kind: string): string => `[JANITOR-REDACTED:${kind}]`

const MARK = /\[JANITOR-REDACTED:[a-z0-9-]+\]/

// Specific, high-confidence token formats. Order matters: the more specific
// prefix (sk-ant-) runs before the more general one (sk-).
const TOKENS: Rule[] = [
  { kind: 'private-key', pattern: /-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?)-----[\s\S]*?(?:-----END \1-----|$)/g },
  { kind: 'aws-access-key', pattern: /\b((?:AKIA|ASIA)[A-Z0-9]{16})\b/g, group: 1 },
  { kind: 'aws-secret-key', pattern: /\b(?:aws_?secret_?(?:access_?)?key|secret_?access_?key)["']?\s*[=:]\s*["']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])/gi, group: 1 },
  { kind: 'aws-secret-key', pattern: /"SecretAccessKey"\s*:\s*"([A-Za-z0-9/+=]{40})"/g, group: 1 },
  { kind: 'aws-session-token', pattern: /"SessionToken"\s*:\s*"([A-Za-z0-9/+=]{100,})"/g, group: 1 },
  { kind: 'github-token', pattern: /\b(gh[pousr]_[A-Za-z0-9]{36,255})\b/g, group: 1 },
  { kind: 'github-token', pattern: /\b(github_pat_[A-Za-z0-9_]{22,255})\b/g, group: 1 },
  { kind: 'anthropic-key', pattern: /\b(sk-ant-[A-Za-z0-9_-]{20,})/g, group: 1 },
  { kind: 'openai-key', pattern: /\b(sk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,})/g, group: 1 },
  { kind: 'openai-key', pattern: /\b(sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})\b/g, group: 1 },
  { kind: 'openai-key', pattern: /\b(sk-[A-Za-z0-9]{48})\b/g, group: 1 },
  { kind: 'slack-token', pattern: /\b(xox[abposr]-[A-Za-z0-9-]{10,})/g, group: 1 },
  { kind: 'slack-webhook', pattern: /(https:\/\/hooks\.slack\.com\/services\/T[A-Z0-9]+\/B[A-Z0-9]+\/[A-Za-z0-9]+)/g, group: 1 },
  { kind: 'stripe-key', pattern: /\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,})\b/g, group: 1 },
  { kind: 'stripe-key', pattern: /\b(whsec_[A-Za-z0-9]{24,})\b/g, group: 1 },
  { kind: 'google-api-key', pattern: /\b(AIza[0-9A-Za-z_-]{35})(?![0-9A-Za-z_-])/g, group: 1 },
  { kind: 'jwt', pattern: /\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/g, group: 1 },
  { kind: 'npm-token', pattern: /\b(npm_[A-Za-z0-9]{36})\b/g, group: 1 },
  { kind: 'pypi-token', pattern: /\b(pypi-AgE[A-Za-z0-9_-]{50,})/g, group: 1 },
  { kind: 'huggingface-token', pattern: /\b(hf_[A-Za-z0-9]{34,})\b/g, group: 1 },
  { kind: 'sendgrid-key', pattern: /\b(SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43})(?![A-Za-z0-9_-])/g, group: 1 },
  { kind: 'bearer-token', pattern: /\b(?:Authorization|Proxy-Authorization)["']?\s*[:=]\s*["']?(?:Bearer|Basic|token|Token)\s+([A-Za-z0-9._~+/=-]{16,})/g, group: 1 },
]

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
  if (/^\d{1,7}$/.test(value)) return false
  if (isQuoted) return value.length >= 3 && !/\s/.test(value)
  // Unquoted: a code expression (`get_token()`, `self.token`) is not a secret.
  if (/[\s()[\]{};,]/.test(value)) return false
  if (/^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+$/.test(value)) return false
  return (value.length >= 6 && /\d/.test(value)) || value.length >= 16
}

/** Replaces each match of `rule` with its mark, counting into `hits`. */
function applyRule(text: string, rule: Rule, hits: Hits): string {
  return text.replace(rule.pattern, (match: string, ...groups: unknown[]) => {
    const group = rule.group ?? 0
    const secret = group === 0 ? match : String(groups[group - 1] ?? '')
    if (secret === '' || MARK.test(secret)) return match
    hits[rule.kind] = (hits[rule.kind] ?? 0) + 1
    return group === 0 ? mark(rule.kind) : match.replace(secret, mark(rule.kind))
  })
}

/** A password in a URL's userinfo part: keeps the scheme, user and host, hides the password. */
function redactUrlPasswords(text: string, hits: Hits): string {
  // The password may contain a slash. A password that starts with digits then a slash is a
  // host:port followed by a path (`host:8080/pkg/@scope`), not a password, so the lookahead skips it.
  return text.replace(/\b([a-z][a-z0-9+.-]*:\/\/)([^\s:/@'"`]+):((?!\d+\/)[^\s@'"`]+)@/gi, (match, scheme: string, user: string, password: string) => {
    if (MARK.test(password) || PLACEHOLDER.test(password)) return match
    hits['url-password'] = (hits['url-password'] ?? 0) + 1
    return `${scheme}${user}:${mark('url-password')}@`
  })
}

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
  // JSON: `"api_key": "..."`.
  out = out.replace(/"([A-Za-z0-9_.-]+)"(\s*:\s*)"((?:[^"\\]|\\.){3,})"/g, (match, name: string, sep: string, value: string) => {
    if (!isSecretName(name) || !looksSecret(value, true)) return match
    hits.assignment = (hits.assignment ?? 0) + 1
    return `"${name}"${sep}"${mark('assignment')}"`
  })
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
