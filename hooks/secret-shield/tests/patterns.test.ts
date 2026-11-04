import { describe, expect, test } from 'claude-code/testing'

import { applyRule, countOf, isSecretFile, label, mark, redact, redactBlocks, redactDeep, TOKEN_ORDER, withhold } from '../patterns'
import { pypiToken } from '../rules/dev-services'

// Fake secrets are assembled at run time so no scanner mistakes this file for a leak.
const j = (...parts: string[]) => parts.join('')
const A36 = 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5'

describe('finds each kind of token', () => {
  const cases: Array<[string, string]> = [
    ['aws-access-key', j('AKIA', 'Q3EGRVJ4Z7XWLP2N')],
    ['aws-access-key', j('ASIA', 'Q3EGRVJ4Z7XWLP2N')],
    ['github-token', j('gh', 'p_', A36)],
    ['github-token', j('gh', 's_', A36)],
    ['github-token', j('github', '_pat_', '11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz')],
    ['anthropic-key', j('sk-', 'ant-', 'api03-', 'x'.repeat(10), A36)],
    ['openai-key', j('sk-', 'proj-', A36, 'abcd')],
    ['openai-key', j('sk-', 'aB3dE5fG7hJ9kL1mN3pQ', 'T3BlbkFJ', 'aB3dE5fG7hJ9kL1mN3pQ')],
    ['slack-token', j('xo', 'xb-', '1234567890-0987654321-', 'aB3dE5fG7hJ9kL1mN3pQ')],
    ['slack-webhook', j('https://hooks.slack', '.com/services/', 'T0ABCDEF1/B0ABCDEF2/', 'aB3dE5fG7hJ9kL1mN3pQ')],
    ['stripe-key', j('sk', '_live_', 'aB3dE5fG7hJ9kL1mN3pQ5rS7')],
    ['stripe-key', j('whsec', '_', 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU')],
    ['google-api-key', j('AI', 'za', 'SyA1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q')],
    ['jwt', j('eyJ', 'hbGciOiJIUzI1NiJ9', '.', 'eyJ', 'zdWIiOiIxMjM0NTY3ODkwIn0', '.', 'dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U')],
    ['npm-token', j('npm', '_', A36)],
    ['pypi-token', j('pypi', '-AgE', 'IcHlwaS5vcmc', 'x'.repeat(50))],
    ['huggingface-token', j('hf', '_', 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3z')],
    ['sendgrid-key', j('SG', '.', 'aB3dE5fG7hJ9kL1mN3pQ5r', '.', 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7dE9f')],
  ]
  for (const [kind, secret] of cases) {
    test(`${kind}: ${secret.slice(0, 8)}…`, () => {
      const { text, hits } = redact(`value: ${secret} end`)
      expect(hits[kind]).toBe(1)
      expect(text).not.toContain(secret)
      expect(text).toContain(`[JANITOR-REDACTED:${kind}]`)
    })
  }
})

test('a PEM private key is hidden whole, even when cut off', () => {
  const begin = j('-----BEGIN ', 'RSA PRIVATE KEY-----')
  const end = j('-----END ', 'RSA PRIVATE KEY-----')
  const whole = redact(`key:\n${begin}\nMIIEpAIBAAKCAQEA\nabc\n${end}\ndone`)
  expect(whole.text).toBe('key:\n[JANITOR-REDACTED:private-key]\ndone')
  const cut = redact(`${j('-----BEGIN ', 'OPENSSH PRIVATE KEY-----')}\nb3BlbnNzaC1rZXktdjEAAAAA`)
  expect(cut.text).toBe('[JANITOR-REDACTED:private-key]')
})

test('AWS secret keys and STS output', () => {
  const secret = j('wJalrXUtnFEMI/K7MDENG/', 'bPxRfiCYEXAMPLEKEY')
  expect(redact(`aws_secret_access_key = ${secret}`).text).toBe('aws_secret_access_key = [JANITOR-REDACTED:aws-secret-key]')
  const sts = `{"Credentials": {"SecretAccessKey": "${secret}", "SessionToken": "${'F'.repeat(120)}"}}`
  const done = redact(sts)
  expect(done.hits['aws-secret-key']).toBe(1)
  expect(done.hits['aws-session-token']).toBe(1)
})

// Fake connection strings, joined at run time so secret scanners don't flag the repo.
const withPassword = (scheme: string, user: string, password: string, rest: string) => `${scheme}://${user}:${password}@${rest}`

test('a password in a URL is hidden, the user and host are kept', () => {
  expect(redact(`DATABASE_URL=${withPassword('postgres', 'app', 's3cret' + 'Pass', 'db.acme.io:5432/app')}`).text).toBe(
    'DATABASE_URL=postgres://app:[JANITOR-REDACTED:url-password]@db.acme.io:5432/app',
  )
  expect(redact(withPassword('mongodb+srv', 'u', 'p4' + 'ss', 'cluster0.x.example')).hits['url-password']).toBe(1)
  expect(redact('postgres://app:${DB_PASSWORD}@db/app').hits['url-password']).toBeUndefined()
  expect(redact('see https://example.com/a:b@c').hits['url-password']).toBeUndefined()
})

describe('secret assignments are hidden, the name is kept', () => {
  const cases: Array<[string, string]> = [
    ['API_KEY=abcd1234efgh', 'API_KEY=[JANITOR-REDACTED:assignment]'],
    ['export GITHUB_TOKEN="xyz12345abc"', 'export GITHUB_TOKEN="[JANITOR-REDACTED:assignment]"'],
    ['DB_PASSWORD=hunter2!x', 'DB_PASSWORD=[JANITOR-REDACTED:assignment]'],
    ['password: hunter22', 'password: [JANITOR-REDACTED:assignment]'],
    ['  client_secret: "abc123def"', '  client_secret: "[JANITOR-REDACTED:assignment]"'],
    ['SECRET_KEY_BASE=3f9a8b7c6d5e4f3a2b1c', 'SECRET_KEY_BASE=[JANITOR-REDACTED:assignment]'],
    ['const apiKey = "abc123def456";', 'const apiKey = "[JANITOR-REDACTED:assignment]";'],
    ['const apiKey: string = "abc123def456"', 'const apiKey: string = "[JANITOR-REDACTED:assignment]"'],
    ['  accessToken: \'q1w2e3r4t5\',', '  accessToken: \'[JANITOR-REDACTED:assignment]\','],
    ['{"api_key": "q1w2e3r4t5y6"}', '{"api_key": "[JANITOR-REDACTED:assignment]"}'],
    ['STRIPE_WEBHOOK_SECRET=abc#123def', 'STRIPE_WEBHOOK_SECRET=[JANITOR-REDACTED:assignment]'],
    ['TOKEN=abc123def  # rotate monthly', 'TOKEN=[JANITOR-REDACTED:assignment]  # rotate monthly'],
  ]
  for (const [line, want] of cases) test(line, () => expect(redact(line).text).toBe(want))
})

describe('leaves lookalikes alone', () => {
  const cases = [
    'MAX_TOKENS=1024',
    'max_tokens: 4096',
    'TOKEN_URL=https://auth.example.com/token',
    'GITHUB_TOKEN_PATH=/run/secrets/gh',
    'tokenizer = "bert-base-uncased"',
    'password = get_password()',
    'token = self.config.token',
    'PASSWORD=${DB_PASSWORD}',
    'password: changeme',
    'API_KEY=<your-api-key>',
    'API_KEY=',
    'API_KEY=your_api_key_here',
    'token_type: "Bearer"',
    '"password_hint": "your pet\'s name"',
    'if (password == "") return',
    'Use a token to authenticate; see the password docs.',
    'commit 4f2c1e9a8b7d6c5e4f3a2b1c0d9e8f7a6b5c4d3e',
    'PORT=3000',
    'SECRET_LENGTH=32',
    'pass_through: true',
  ]
  for (const line of cases) test(line, () => expect(redact(line).text).toBe(line))
})

test('a token already redacted is not counted twice', () => {
  const once = redact(`GITHUB_TOKEN=${j('gh', 'p_', A36)}`)
  expect(once.text).toBe('GITHUB_TOKEN=[JANITOR-REDACTED:github-token]')
  expect(once.hits).toEqual({ 'github-token': 1 })
  expect(redact(once.text).hits).toEqual({})
})

test('redactBlocks scrubs text blocks and tool results, nothing else', () => {
  const token = j('gh', 'o_', A36)
  const { content, hits } = redactBlocks([
    { type: 'tool_result', tool_use_id: 't1', content: `out ${token}` },
    { type: 'tool_result', tool_use_id: 't2', content: [{ type: 'text', text: token }, { type: 'image', source: {} }] },
    { type: 'text', text: `hi ${token}` },
    { type: 'tool_use', id: 'u1', name: 'Bash', input: { command: token } },
  ])
  expect(hits['github-token']).toBe(3)
  expect(content[0]).toEqual({ type: 'tool_result', tool_use_id: 't1', content: 'out [JANITOR-REDACTED:github-token]' })
  expect(content[1]).toEqual({ type: 'tool_result', tool_use_id: 't2', content: [{ type: 'text', text: '[JANITOR-REDACTED:github-token]' }, { type: 'image', source: {} }] })
  expect(content[2]).toEqual({ type: 'text', text: 'hi [JANITOR-REDACTED:github-token]' })
  expect(content[3]).toEqual({ type: 'tool_use', id: 'u1', name: 'Bash', input: { command: token } })
})

test('withhold keeps the blocks, not their text', () => {
  expect(withhold([{ type: 'tool_result', tool_use_id: 't', content: 'x' }, { type: 'text', text: 'y' }], 'gone')).toEqual([
    { type: 'tool_result', tool_use_id: 't', content: 'gone' },
    { type: 'text', text: 'gone' },
  ])
})

describe('isSecretFile', () => {
  const secret = ['.env', '.env.local', 'app/.env.production', 'server.pem', 'tls.key', '/home/User/.ssh/id_rsa', '/home/User/.ssh/id_ed25519', '/Users/User/.aws/credentials', '.npmrc', '.netrc', '.git-credentials', 'service-account-prod.json', 'config/secrets.yml', '/Users/User/.kube/config', '.envrc']
  const fine = ['.env.example', '.env.sample', 'src/env.ts', 'id_rsa.pub', '/home/User/.ssh/known_hosts', 'README.md', 'keyboard.ts', 'environment.yml', 'docs/secrets.md']
  for (const path of secret) test(`secret: ${path}`, () => expect(isSecretFile(path)).toBe(true))
  for (const path of fine) test(`fine: ${path}`, () => expect(isSecretFile(path)).toBe(false))
})

test('labels read naturally', () => {
  expect(label('aws-access-key')).toBe('1 AWS access key')
  expect(label('github-token', 2)).toBe('2 GitHub tokens')
  expect(label('url-password', 3)).toBe('3 passwords in URLs')
})

test('redactDeep walks a JSON value and returns it untouched when clean', () => {
  const clean = { a: ['x', { b: 'y' }], n: 1 }
  expect(redactDeep(clean).value).toBe(clean)
  const token = j('gh', 'p_', A36)
  expect(redactDeep({ a: [token, { b: `x ${token}` }], n: 1 })).toEqual({
    value: { a: ['[JANITOR-REDACTED:github-token]', { b: 'x [JANITOR-REDACTED:github-token]' }], n: 1 },
    hits: { 'github-token': 2 },
  })
})

describe('janitor marker', () => {
  test('a GitHub token becomes the exact janitor marker', () => {
    expect(redact('token ' + j('ghp_', 'A1b2C3d4E5f6G7h8I9j0', 'K1l2M3n4O5p6Q7r8')).text).toBe('token [JANITOR-REDACTED:github-token]')
  })
  test('no rule emits the upstream marker form', () => {
    const samples = ['API_KEY=' + j('abcd', '1234efgh'), j('ghp_', 'B2c3D4e5F6g7H8i9J0k1', 'L2m3N4o5P6q7R8s9'), 'DATABASE_URL=postgres://app:' + j('s3cret', 'Pass') + '@db.acme.io:5432/app']
    for (const s of samples) {
      const { text, hits } = redact(s)
      expect(text.includes('[' + 'REDACTED:')).toBe(false)
      expect(text.includes('[JANITOR-' + 'REDACTED:')).toBe(true)
      expect(countOf(hits)).toBeGreaterThan(0)
    }
  })
  test('an existing janitor marker is left untouched in an assignment', () => {
    const m = '[JANITOR-' + 'REDACTED:x]'
    const { text, hits } = redact('API_KEY=' + m)
    expect(text).toBe('API_KEY=' + m)
    expect(countOf(hits)).toBe(0)
  })
  test('an existing janitor marker is left untouched in JSON', () => {
    const m = '[JANITOR-' + 'REDACTED:x]'
    const { text, hits } = redact('{"password":"' + m + '"}')
    expect(text).toBe('{"password":"' + m + '"}')
    expect(countOf(hits)).toBe(0)
  })
  test('an existing janitor marker is left untouched in a bearer header', () => {
    const m = '[JANITOR-' + 'REDACTED:x]'
    const { text, hits } = redact('Authorization: Bearer ' + m)
    expect(text).toBe('Authorization: Bearer ' + m)
    expect(countOf(hits)).toBe(0)
  })
  test('an existing janitor marker is left untouched in a URL password', () => {
    const m = '[JANITOR-' + 'REDACTED:x]'
    const { text, hits } = redact('postgres://app:' + m + '@db.acme.io:5432/app')
    expect(text).toBe('postgres://app:' + m + '@db.acme.io:5432/app')
    expect(countOf(hits)).toBe(0)
  })
  test('a marker kind with capitals or underscores is still recognised', () => {
    const v = 'API_KEY="' + mark('Some_Kind') + '"'
    const r = redact(v)
    expect(r.text).toBe(v)
    expect(countOf(r.hits)).toBe(0)
  })
})

describe('URL passwords containing a slash', () => {
  const marker = '[JANITOR-' + 'REDACTED:url-password]'
  test('a password whose digits are followed by # is hidden, not read as a port', () => {
    expect(redact('postgres://app:' + j('2024#', 'Spring') + '@db.acme.io/app').text).toBe('postgres://app:' + marker + '@db.acme.io/app')
  })
  test('a password whose digits are followed by ? with no = is hidden', () => {
    expect(redact('redis://app:' + j('12?', 'abc') + '@cache.acme.io').text).toBe('redis://app:' + marker + '@cache.acme.io')
  })
  test('a slash in the password is still hidden, the user and host are kept', () => {
    expect(redact('postgres://app:' + j('ab/', 'cdefgh') + '@db.acme.io:5432/app').text).toBe('postgres://app:' + marker + '@db.acme.io:5432/app')
  })
  test('a port followed by a path with an at-sign is not a password', () => {
    const url = 'https://cdn.acme.io:8080/pkg/' + '@scope/name'
    expect(redact(url).text).toBe(url)
    expect(redact(url).hits['url-password']).toBeUndefined()
  })
  test('an all-digit password is still hidden', () => {
    expect(redact('redis://app:' + j('1234', '5678') + '@cache.acme.io:6379').text).toBe('redis://app:' + marker + '@cache.acme.io:6379')
  })
  test('a bracketed IPv6 host is not read as a user', () => {
    for (const url of ['http://[::1]:4873/@scope/pkg', 'http://[fe80::1]/a@b']) {
      const { text, hits } = redact(url)
      expect(text).toBe(url)
      expect(hits).toEqual({})
    }
  })
  test('a port followed by a query with an at-sign is not a password', () => {
    const url = 'http://localhost:3000?email=a' + '@' + 'b.com'
    expect(redact(url).text).toBe(url)
  })
  test('localhost:3000#a@b is a known false positive, the fragment is read as a password', () => {
    expect(redact('http://localhost:3000#a@b').hits['url-password']).toBe(1)
  })
  test('a second URL after a password is not read into it', () => {
    expect(redact('redis://h1:abc/0,redis://u:' + j('pw', '99x') + '@h2').text).toBe('redis://h1:abc/0,redis://u:' + marker + '@h2')
  })
  test('a password starting with digits then a slash is not hidden (known miss, kept)', () => {
    const url = 'postgres://u:' + j('9/', 'Kxq7') + '@db.acme.io/app'
    expect(redact(url).text).toBe(url)
  })
  test('an scp-like ssh host:path read as a password (known false positive, kept)', () => {
    expect(redact('ssh://github.com:org/repo.git@v1.2').hits['url-password']).toBe(1)
  })
  test('a known false positive: a fragment with an at-sign is read as a password', () => {
    expect(redact('http://localhost:8080#/users/' + '@alice').hits['url-password']).toBe(1)
  })
  test('a value of 6 or more digits then a slash is not a port, so it is hidden', () => {
    expect(redact('http://h:123456/x' + '@y').hits['url-password']).toBe(1)
  })
  test('a marker followed by more user text still hides the password', () => {
    expect(redact('https://' + mark('github-token') + 'abc:' + j('pw', '99x') + '@h.acme.io').text).toBe('https://' + mark('github-token') + 'abc:' + marker + '@h.acme.io')
  })
})

describe('URL passwords are hidden whatever comes before the scheme', () => {
  const marker = '[JANITOR-' + 'REDACTED:url-password]'
  const pw = j('s3cret', 'Pw1')
  const cases: Array<[string, string, string]> = [
    ['https with user and password', 'https://user:', '@host'],
    ['postgres', 'postgres://u:', '@h/db'],
    ['git+ssh, a plus in the scheme', 'git+ssh://u:', '@h'],
    ['jdbc:postgresql, a colon before the scheme', 'jdbc:postgresql://u:', '@h'],
    ['after a hyphen', '-https://u:', '@h'],
    ['after two hyphens', '--url=https://u:', '@h'],
    ['after an opening parenthesis', '(https://u:', '@h)'],
    ['after a double quote', '"https://u:', '@h"'],
    ['after an equals sign', 'url=https://u:', '@h'],
    ['after a space', 'see https://u:', '@h'],
    ['after a dot, a dotted scheme', 'foo.https://u:', '@h'],
    ['a scheme 20 characters long', 'abcdefghijklmnopqrst://u:', '@h'],
    ['40 letters glued to https', 'abcdefghijklmnopqrstuvwxyzabcdefghijklmnhttps://u:', '@h'],
    ['a long scheme with hyphens', 'a-b-c-d-e-f-g-h-i-j-k-l-m-n-o-p-q-r-s-t-u-v-w-x-y-z-https://u:', '@h'],
  ]
  for (const [name, head, tail] of cases) {
    test(`${name}: the password is hidden, the rest is kept`, () => {
      const { text, hits } = redact(head + pw + tail)
      expect(text).toBe(head + marker + tail)
      expect(hits['url-password']).toBe(1)
    })
  }
})

// WHY: the scheme used to be a prefix `\b([a-z][a-z0-9+.-]*:\/\/)` that started at every word boundary and scanned the whole run of
// scheme characters, so a long run with no `://` was quadratic (16 KB of `A1-` took 0.5-1.4 s). These tests fail on that regex
// because of time, and assert a count or a duration, never toContain on a big string.
describe('a long run of scheme characters is redacted in linear time', () => {
  const rep = (unit: string, length: number) => unit.repeat(Math.ceil(length / unit.length)).slice(0, length)
  const timed = (text: string): number => {
    const started = performance.now()
    redact(text)
    return performance.now() - started
  }
  test('32 KB of A1- finishes in under 200 ms', () => {
    expect(timed(rep('A1-', 32 * 1024))).toBeLessThan(200)
  })
  test('https:// at the start, then 256 KB of A1- with no at-sign, finishes in under 1 s', () => {
    expect(timed('https://' + rep('A1-', 256 * 1024))).toBeLessThan(1000)
  })
  test('256 KB of A1- and of base64-like text, each with one :// in the middle, finishes in under 1 s', () => {
    for (const unit of ['A1-', 'aB3dE5fG7hJ9kL1mN3pQ+r/S7tU9vW1xY3z=']) {
      const half = rep(unit, 128 * 1024)
      expect(timed(half + 'https://u:' + j('s3cret', 'Pw1') + '@h ' + half)).toBeLessThan(1000)
    }
  })
  test('the password in that one URL is still hidden', () => {
    const half = rep('A1-', 32 * 1024)
    const { text, hits } = redact(half + ' https://u:' + j('s3cret', 'Pw1') + '@h ' + half)
    expect(hits['url-password']).toBe(1)
    expect(text.split(j('s3cret', 'Pw1')).length - 1).toBe(0)
  })
})

describe('redacting twice changes nothing', () => {
  const cases: Array<[string, string]> = [
    ['an AWS key in the user part', 'https://' + j('AKIA', 'IOSFODNN7EXAMPLE') + ':' + j('secret', 'pw123') + '@host.acme.io'],
    ['a secret after a token in an assignment', 'API_TOKEN="' + j('ghp_', 'A1b2C3d4E5f6G7h8I9j0', 'K1l2M3n4O5p6Q7r8') + ':' + j('hunter', '2pass') + '"'],
    ['a secret after a token in a URL password', 'postgres://app:' + j('ghp_', 'A1b2C3d4E5f6G7h8I9j0', 'K1l2M3n4O5p6Q7r8') + '.extra9' + '@' + 'db.acme.io/app'],
    ['two comma-joined redis URLs', 'redis://h1:abc/0,redis://u:' + j('pw', '99x') + '@h2'],
  ]
  for (const [name, input] of cases) {
    test(name, () => {
      const once = redact(input)
      expect(countOf(once.hits)).toBeGreaterThan(0)
      const twice = redact(once.text)
      expect(twice.text).toBe(once.text)
      expect(countOf(twice.hits)).toBe(0)
    })
  }
})

describe('a secret next to a hidden token', () => {
  test('a password after an AWS key in the user part is hidden', () => {
    const r = redact('https://' + j('AKIA', 'IOSFODNN7EXAMPLE') + ':' + j('secret', 'pw123') + '@host.acme.io')
    expect(r.text).not.toContain('secretpw123')
    expect(r.hits['url-password']).toBe(1)
    expect(r.hits['aws-access-key']).toBe(1)
  })
  test('a secret written after a hidden token in an assignment is hidden', () => {
    expect(redact('API_TOKEN="' + j('ghp_', 'A1b2C3d4E5f6G7h8I9j0', 'K1l2M3n4O5p6Q7r8') + ':' + j('hunter', '2pass') + '"').text).toBe('API_TOKEN="' + '[JANITOR-' + 'REDACTED:assignment]' + '"')
  })
  test('a secret written after a hidden token in a URL password is hidden', () => {
    expect(redact('postgres://app:' + j('ghp_', 'A1b2C3d4E5f6G7h8I9j0', 'K1l2M3n4O5p6Q7r8') + '.extra9' + '@' + 'db.acme.io/app').text).toBe('postgres://app:' + '[JANITOR-' + 'REDACTED:url-password]' + '@db.acme.io/app')
  })
})

describe('Slack app-level and configuration tokens are hidden with no name before them', () => {
  // Fixtures are built at run time: no whole fake token sits in this file.
  const run = (n: number) => '7K3Q9ZM2X5'.repeat(Math.ceil(n / 10)).slice(0, n)
  const appToken = j('xa', 'pp-', '1-', 'A0123456789-', '1234567890123-', 'abcdef0123456789abcdef')
  const configAccess = (kind: 'b' | 'p', n: number) => j('xo', 'xe.', 'xo', 'x' + kind, '-1-', run(n))
  const configRefresh = (n: number) => j('xo', 'xe-', '1-', run(n))
  const APP = mark('slack-app-token')
  const CONFIG = mark('slack-config-token')

  test('slack-app-token: an app-level token is one marker, counted once', () => {
    const done = redact(`see ${appToken} end`)
    expect(done.text).toBe(`see ${APP} end`)
    expect(done.hits).toEqual({ 'slack-app-token': 1 })
  })

  for (const kind of ['b', 'p'] as const) {
    test(`slack-config-token: a whole xoxe.xox${kind}- config access token is ONE marker, no prefix or tail left`, () => {
      for (const n of [163, 166]) {
        const done = redact(`x ${configAccess(kind, n)} y`)
        expect(done.text).toBe(`x ${CONFIG} y`)
        expect(done.hits).toEqual({ 'slack-config-token': 1 })
      }
    })
  }

  test('slack-config-token: a refresh token is one marker', () => {
    const done = redact(`refresh ${configRefresh(146)} end`)
    expect(done.text).toBe(`refresh ${CONFIG} end`)
    expect(done.hits).toEqual({ 'slack-config-token': 1 })
  })

  test('a config access token with a too-short tail is not a config token, the older Slack rule still hides the token inside it', () => {
    const done = redact(`x ${configAccess('p', 162)} y`)
    expect(done.hits['slack-config-token']).toBeUndefined()
    expect(done.hits['slack-token']).toBe(1)
  })

  test('a refresh token with a too-short tail is left as it is', () => {
    const input = `refresh ${configRefresh(145)} end`
    const done = redact(input)
    expect(done.text).toBe(input)
    expect(done.hits).toEqual({})
  })

  test('an app-level token without its last segment is left as it is', () => {
    const input = j('xa', 'pp-', '1-', 'A0123456789-', '1234567890123')
    expect(redact(input).text).toBe(input)
  })

  test('the bare prefixes in prose are left as they are', () => {
    const lines = [
      'Slack app-level tokens start with xapp- and configuration tokens with xoxe- or xoxe.xoxp-.',
      'xapp-1-A0123',
      'the xoxe. prefix is followed by xoxb- or xoxp-',
    ]
    for (const line of lines) expect(redact(line).text).toBe(line)
  })

  test('the false-positive corpus is left as it is', () => {
    const lines = [
      'commit 4f2c1e9a8b7d6c5e4f3a2b1c0d9e8f7a6b5c4d3e',
      'id 123e4567-e89b-12d3-a456-426614174000',
      j('integrity sha512', '-', 'Zm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFyZm9vYmFy'),
      j('data:image/png;base64,', 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk'),
      j('ssh-rsa ', 'AAAAB3NzaC1yc2EAAAADAQABAAABAQC7'),
      j('pk', '_live_', 'aB3dE5fG7hJ9kL1mN3pQ5rS7'),
    ]
    let changed = 0
    for (const line of lines) if (redact(line).text !== line) changed++
    expect(changed).toBe(0)
  })
})
describe('token rule order', () => {
  // The rules live in rules/ but run in the order patterns.ts lists them, and the first match wins.
  // This pins each rule by kind, pattern source and flags, so moving a rule between category files, reordering
  // the list, swapping two rules of the same kind (the three openai-key rules, say), or a rule losing its g
  // flag or gaining i or u fails here. The expected values come from regex literals, so both sides are
  // normalized by the same engine.
  const id = (kind: string, pattern: RegExp) => [kind, pattern.source, pattern.flags]
  test('the rules run in this exact order', () => {
    expect(TOKEN_ORDER).toEqual([
      id('private-key', /-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?)-----[\s\S]*?(?:-----END \1-----|$)/g),
      id('aws-access-key', /\b((?:AKIA|ASIA)[A-Z0-9]{16})\b/g),
      id('aws-secret-key', /\b(?:aws_?secret_?(?:access_?)?key|secret_?access_?key)["']?\s*[=:]\s*["']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])/gi),
      id('aws-secret-key', /"SecretAccessKey"\s*:\s*"([A-Za-z0-9/+=]{40})"/g),
      id('aws-session-token', /"SessionToken"\s*:\s*"([A-Za-z0-9/+=]{100,})"/g),
      id('github-token', /\b(gh[pousr]_[A-Za-z0-9]{36,255})\b/g),
      id('github-token', /\b(github_pat_[A-Za-z0-9_]{22,255})\b/g),
      id('anthropic-key', /\b(sk-ant-[A-Za-z0-9_-]{20,})/g),
      id('openai-key', /\b(sk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,})/g),
      id('openai-key', /\b(sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})\b/g),
      id('openai-key', /\b(sk-[A-Za-z0-9]{48})\b/g),
      id('slack-app-token', /(?i:xapp-\d-[A-Z0-9]+-\d+-[a-z0-9]+)/g),
      id('slack-config-token', /(?i:xoxe.xox[bp]-\d-[A-Z0-9]{163,166})/g),
      id('slack-config-token', /(?i:xoxe-\d-[A-Z0-9]{146})/g),
      id('slack-token', /\b(xox[abposr]-[A-Za-z0-9-]{10,})/g),
      id('slack-webhook', /(https:\/\/hooks\.slack\.com\/services\/T[A-Z0-9]+\/B[A-Z0-9]+\/[A-Za-z0-9]+)/g),
      id('stripe-key', /\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,})\b/g),
      id('stripe-key', /\b(whsec_[A-Za-z0-9]{24,})\b/g),
      id('google-api-key', /\b(AIza[0-9A-Za-z_-]{35})(?![0-9A-Za-z_-])/g),
      id('jwt', /\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/g),
      id('npm-token', /\b(npm_[A-Za-z0-9]{36})\b/g),
      id('pypi-token', /\b(pypi-AgE[A-Za-z0-9_-]{50,})/g),
      id('huggingface-token', /\b(hf_[A-Za-z0-9]{34,})\b/g),
      id('sendgrid-key', /\b(SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43})(?![A-Za-z0-9_-])/g),
      id('bearer-token', /\b(?:Authorization|Proxy-Authorization)["']?\s*[:=]\s*["']?(?:Bearer|Basic|token|Token)\s+([A-Za-z0-9._~+/=-]{16,})/g),
    ])
  })
  test('a PEM private key whose body holds an AWS access key is one private-key hit', () => {
    // Order-dependent: the private-key rule runs first, so the block is hidden before the AWS rule sees it.
    // Moved below the AWS rule, the key inside would be counted as an aws-access-key hit too; the text
    // alone cannot tell, because the private-key rule then swallows the marker with the rest of the block.
    const begin = j('-----BEGIN ', 'RSA PRIVATE KEY-----')
    const end = j('-----END ', 'RSA PRIVATE KEY-----')
    const awsKey = j('AKIA', 'Q3EGRVJ4Z7XWLP2N')
    const { text, hits } = redact(`key:\n${begin}\nMIIEpAIBAAKCAQEA\n${awsKey}\nabc\n${end}\ndone`)
    expect(text).toBe(`key:\n${mark('private-key')}\ndone`)
    expect(hits).toEqual({ 'private-key': 1 })
  })
  test('an sk-ant- key is matched by the Anthropic rule', () => {
    const key = j('sk-', 'ant-', 'api03-', A36, 'abcd')
    const { text, hits } = redact(`key ${key} end`)
    expect(text).toBe(`key ${mark('anthropic-key')} end`)
    expect(hits['anthropic-key']).toBe(1)
    expect(hits['openai-key']).toBeUndefined()
  })
})

describe('a rule whose secret is a capture group hides every copy of it inside the match', () => {
  // Shape of a corpus rule: key name, a lazy gap of up to 40 characters, then a quoted captured value.
  const rule = { kind: 'test-dup', pattern: /api_key[\s\S]{0,40}?"([A-Z0-9]{16,})"/g, group: 1 }
  const value = j('ABCD1234', 'EFGH5678')

  test('a copy in the gap before the capture is hidden too', () => {
    const hits: Record<string, number> = {}
    const out = applyRule(`api_key ${value} = "${value}"`, rule, hits)
    expect(out).not.toContain(value)
    expect(hits).toEqual({ 'test-dup': 1 })
    expect(out).toBe(`api_key ${mark('test-dup')} = "${mark('test-dup')}"`)
  })

  test('a single copy is hidden and nothing else changes', () => {
    const hits: Record<string, number> = {}
    const out = applyRule(`api_key = "${value}" end`, rule, hits)
    expect(out).toBe(`api_key = "${mark('test-dup')}" end`)
    expect(hits).toEqual({ 'test-dup': 1 })
  })
})

describe('a secret found once is hidden wherever it repeats', () => {
  // No token shape: only the assignment rule can find it, so any other copy is hidden by propagation alone.
  const v = j('q7Wm', 'X2Lp9Rt4Zk')
  const input = `DB_PASSWORD=${v}\nconnecting with ${v} now`

  test('a copy on another line of the same text is hidden, and counted once', () => {
    const { text, hits } = redact(input)
    expect(text).not.toContain(v)
    expect(hits).toEqual({ assignment: 1 })
  })

  test('a copy in another block of the same row is hidden', () => {
    expect(redact(`echo ${v}`).text).toContain(v)
    const { content } = redactBlocks([
      { type: 'text', text: `DB_PASSWORD=${v}` },
      { type: 'text', text: `echo ${v}` },
    ])
    expect(String(content[1]?.text)).not.toContain(v)
  })

  test('a copy in another string of the same structured value is hidden', () => {
    const { value } = redactDeep({ a: `DB_PASSWORD=${v}`, b: [`run ${v}`] }) as { value: { b: string[] } }
    expect(value.b[0]).not.toContain(v)
  })

  test('a URL-encoded copy is hidden too', () => {
    const w = j('p', '@ss/w0rd!', 'Zq9x')
    const { text } = redact(`DB_PASSWORD="${w}"\nhttps://h.example/?pw=${encodeURIComponent(w)}`)
    expect(text).not.toContain(w)
    expect(text).not.toContain(encodeURIComponent(w))
  })

  // Guards: these pass on the code without propagation too, and must keep passing with it. Each first checks that
  // line 1 (the defining line) was really hidden and counted, so the value WAS recorded and only propagates() can
  // keep it off line 2; without that, a guard would pass even if propagates() accepted everything. Then they assert
  // line 2 only, so they do not depend on how line 1 reads.
  const guarded = (text: string, val: string): string => {
    const { text: out, hits } = redact(text)
    const lines = out.split('\n')
    expect(hits).toEqual({ assignment: 1 })
    expect(lines[0]).toContain(mark('assignment'))
    expect(lines[0]).not.toContain(val)
    return lines[1] ?? ''
  }

  test('guard: a path value is not hidden elsewhere', () => {
    const val = '/run/secrets/db_password'
    expect(guarded(`SECRET_KEY=${val}\ncat ${val}`, val)).toBe(`cat ${val}`)
  })

  test('guard: an env-var name used as a value is not hidden elsewhere', () => {
    const val = 'MY_SERVICE_SECRET_KEY'
    expect(guarded(`API_TOKEN = "${val}"\nos.environ["${val}"]`, val)).toBe(`os.environ["${val}"]`)
  })

  test('guard: a short value is not hidden elsewhere', () => {
    expect(guarded('PASSWORD="ab12cd"\nab12cd', 'ab12cd')).toBe('ab12cd')
  })

  // A name-shaped value in a secret-named assignment is hidden where it is defined, but is not spread.
  const nameShapes: Array<[string, string]> = [
    ['a lowercase slug', 'my-app-db-credentials'],
    ['a vault-style path', 'prod/db/password'],
    ['a secrets-engine path', 'secret/data/myapp'],
    // Not a slug (the digit), not an identifier, no leading slash, no upper case: only the slash rule refuses it.
    ['a lowercase path with a digit', 'config/v2/settings'],
    ['an email address', j('user@', 'example.com')],
    ['a host and port', 'cache-01.example.com:6379'],
  ]
  for (const [shape, val] of nameShapes) {
    test(`guard: ${shape} is not hidden elsewhere`, () => {
      expect(guarded(`DB_PASSWORD=${val}\nconnect ${val}`, val)).toBe(`connect ${val}`)
    })
  }

  test('redacting the output again changes nothing', () => {
    const once = redact(input)
    expect(once.text).not.toContain(v)
    const again = redact(once.text)
    expect(again.text).toBe(once.text)
    expect(countOf(again.hits)).toBe(0)
  })

  test('a value that reads like a marker leaves every marker whole', () => {
    // The value is the marker's own word, so a naive copy hider would split every marker of the text.
    const token = j('gh', 'p_', A36)
    const { text } = redact(`SOME_SECRET=JANITOR-REDACTED\nkey ${token} end\nSOME_SECRET=JANITOR-REDACTED`)
    // Exact output: a split marker would leave a marker inside a marker, which no count of whole spans can tell from a good one.
    expect(text).toBe(`SOME_SECRET=${mark('assignment')}\nkey ${mark('github-token')} end\nSOME_SECRET=${mark('assignment')}`)
    expect(text).not.toContain('[[')
    expect(text).not.toContain(token)
  })

  test('a value with a lone surrogate does not make redact throw, and its raw copy is hidden', () => {
    const w = j('Ab3x', '\ud800', 'Kq9ZmWp2')
    expect(w.isWellFormed()).toBe(false)
    const { text } = redact(`DB_PASSWORD=${w}\nuse ${w}`)
    expect(text.split(w).length - 1).toBe(0)
    expect(text.split(mark('assignment')).length - 1).toBe(2)
  })

  test('1 MB with 50 secrets, each copied twice, finishes well under the hook limit and hides every copy', () => {
    const values = Array.from({ length: 50 }, (_, i) => j('Vq', String(i).padStart(2, '0'), 'Lm8Rt', String((i * 7919) % 100000).padStart(5, '0')))
    const filler = 'lorem ipsum dolor sit amet '.repeat(400)
    const text = values.map((val, i) => `DB_PASSWORD_${i}=${val}\n${filler}${val}\n${filler}${val}\n`).join('')
    expect(text.length).toBeGreaterThanOrEqual(1_000_000)
    const started = performance.now()
    const done = redact(text)
    const ms = performance.now() - started
    console.log(`propagation over ${text.length} characters and ${values.length} secrets took ${ms.toFixed(0)} ms`)
    expect(ms).toBeLessThan(5000)
    // Counts, not toContain on the whole text: a failure is reported by name instead of printing a megabyte.
    const count = (haystack: string, needle: string) => haystack.split(needle).length - 1
    expect(values.reduce((sum, val) => sum + count(done.text, val), 0)).toBe(0)
    expect(count(done.text, mark('assignment'))).toBe(values.length * 3)
  })
})

describe('a name that says the value is a file or an env-var name is not a secret name', () => {
  // The exclusion is in NOT_SECRET_NAME (_file, _env): the value is secret-shaped, the name says it is not one.
  test('SECRET_FILE and TOKEN_ENV lines with secret-looking values are left as they are', () => {
    const text = `SECRET_FILE=${j('Aq7Zk9', 'Lm2Xp4Rt8Vw')}\nTOKEN_ENV=${j('Bn3Yc5', 'Qd7Hs1Fg6Jk')}`
    const { text: out, hits } = redact(text)
    expect(out).toBe(text)
    expect(hits).toEqual({})
  })
})

describe('a rule pattern run directly does not break redact', () => {
  // The rule files export each Rule, so an importer can run .test() on a shared /g pattern and leave its
  // lastIndex mid-text. redact() must still find a token placed before that offset in a new text.
  test('a token before a stale lastIndex is still hidden', () => {
    const token = j('pypi-', 'AgE', A36, 'x'.repeat(20))
    try {
      expect(pypiToken.pattern.test(`${'filler '.repeat(10)}${token} end`)).toBe(true)
      expect(pypiToken.pattern.lastIndex).toBeGreaterThan(token.length)
      const { text, hits } = redact(`${token} end`)
      expect(text).toBe(`${mark('pypi-token')} end`)
      expect(hits).toEqual({ 'pypi-token': 1 })
    } finally {
      pypiToken.pattern.lastIndex = 0
    }
  })
})


// Run-together and kebab names, Azure keys and connection strings (TRDD-Q6LPJTPO). Fake values are made at run time
// with an upper-case letter, a lower-case letter and a digit, and a DIFFERENT one on every call: a test cannot pass
// because another value was hidden before it, and every positive uses its own redact() call so known-secret
// propagation cannot hide a value the rules missed.
const ALNUM = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
let fakeCount = 0
const fake = (length = 32): string => {
  fakeCount += 1
  const tail = Array.from({ length }, () => ALNUM[Math.floor(Math.random() * ALNUM.length)]).join('')
  return `Zq${String(fakeCount).padStart(3, '0')}${tail}`.slice(0, length)
}
// An Azure storage key: 88 base64 characters ending in ==.
const fakeAzureKey = (): string => j(fake(86), '==')
const ASSIGNED = mark('assignment')
const CONN_KEY = mark('connection-string-key')
// The quote of a pair stringified twice: three backslashes, then the quote.
const Q3 = '\\'.repeat(3) + '"'

// The three entry points, each a fresh call on the same text.
const threeWays = (input: string): string[] => {
  const viaRedact = redact(input).text
  const viaDeep = (redactDeep({ k: input }).value as { k: string }).k
  const viaBlocks = String(redactBlocks([{ type: 'text', text: input }]).content[0]?.text)
  return [viaRedact, viaDeep, viaBlocks]
}

describe('run-together, kebab and header names are hidden, the name is kept', () => {
  const cases: Array<[string, (v: string) => [string, string]]> = [
    ['accesstoken=V', v => [`accesstoken=${v}`, `accesstoken=${ASSIGNED}`]],
    ['accesstoken="V"', v => [`accesstoken="${v}"`, `accesstoken="${ASSIGNED}"`]],
    ['secretkey=V', v => [`secretkey=${v}`, `secretkey=${ASSIGNED}`]],
    ['secretkey: "V"', v => [`secretkey: "${v}"`, `secretkey: "${ASSIGNED}"`]],
    ['YAML secretkey: V', v => [`secretkey: ${v}`, `secretkey: ${ASSIGNED}`]],
    ['YAML accesstoken: V', v => [`accesstoken: ${v}`, `accesstoken: ${ASSIGNED}`]],
    ['api-key: V', v => [`api-key: ${v}`, `api-key: ${ASSIGNED}`]],
    ['"api-key": "V"', v => [`"api-key": "${v}"`, `"api-key": "${ASSIGNED}"`]],
    ['escaped JSON \\"api-key\\":\\"V\\"', v => [`\\"api-key\\":\\"${v}\\"`, `\\"api-key\\":\\"${ASSIGNED}\\"`]],
    ['header X-Api-Key: V', v => [`X-Api-Key: ${v}`, `X-Api-Key: ${ASSIGNED}`]],
  ]
  for (const [name, build] of cases) {
    test(name, () => {
      const [input, want] = build(fake())
      for (const out of threeWays(input)) expect(out).toBe(want)
    })
  }

  test('control: api_key=V is hidden, with or without the new rules', () => {
    const [input, want] = [`api_key=${fake()}`, `api_key=${ASSIGNED}`]
    for (const out of threeWays(input)) expect(out).toBe(want)
  })
})

describe('Azure storage keys and connection strings are hidden', () => {
  test('AZURE_STORAGE_KEY=K', () => {
    const k = fakeAzureKey()
    expect(k.length).toBe(88)
    for (const out of threeWays(`AZURE_STORAGE_KEY=${k}`)) expect(out).toBe(`AZURE_STORAGE_KEY=${ASSIGNED}`)
  })

  test('"AccountKey": "K"', () => {
    const k = fakeAzureKey()
    for (const out of threeWays(`"AccountKey": "${k}"`)) expect(out).toBe(`"AccountKey": "${ASSIGNED}"`)
  })

  const azure = (k: string) => `DefaultEndpointsProtocol=https;AccountName=a;AccountKey=${k};EndpointSuffix=h.example`
  const azureShapes: Array<[string, (k: string) => [string, string]]> = [
    ['a bare Azure connection string', k => [azure(k), azure(CONN_KEY)]],
    ['inside AZURE_STORAGE_CONNECTION_STRING="..."', k => [`AZURE_STORAGE_CONNECTION_STRING="${azure(k)}"`, `AZURE_STORAGE_CONNECTION_STRING="${azure(CONN_KEY)}"`]],
    ['inside JSON escaped twice', k => [`{${Q3}AZURE_STORAGE_CONNECTION_STRING${Q3}:${Q3}${azure(k)}${Q3}}`, `{${Q3}AZURE_STORAGE_CONNECTION_STRING${Q3}:${Q3}${azure(CONN_KEY)}${Q3}}`]],
  ]
  for (const [name, build] of azureShapes) {
    test(name, () => {
      const [input, want] = build(fakeAzureKey())
      for (const out of threeWays(input)) expect(out).toBe(want)
      expect(redact(input).hits).toEqual({ 'connection-string-key': 1 })
    })
  }

  test('a copy of the key elsewhere is hidden too, in a text, a structured value and a row', () => {
    const k = fakeAzureKey()
    const cs = azure(k)
    const text = redact(`${cs}\necho ${k}`)
    expect(text.text).toBe(`${azure(CONN_KEY)}\necho ${CONN_KEY}`)
    expect(text.hits).toEqual({ 'connection-string-key': 1 })
    const deep = redactDeep({ a: cs, b: [`echo ${k}`] }) as { value: { b: string[] } }
    expect(deep.value.b[0]).toBe(`echo ${CONN_KEY}`)
    const block = redactBlocks([{ type: 'text', text: cs }, { type: 'text', text: `echo ${k}` }])
    expect(String(block.content[1]?.text)).toBe(`echo ${CONN_KEY}`)
  })

  const keys: Array<[string, (v: string) => [string, string]]> = [
    ['SQL Server: Password=V; after other settings', v => [`Server=tcp:h,1433;Database=d;User ID=u;Password=${v};`, `Server=tcp:h,1433;Database=d;User ID=u;Password=${CONN_KEY};`]],
    ['Password=V;Server=h at the start of a line', v => [`Password=${v};Server=h`, `Password=${CONN_KEY};Server=h`]],
    // WHY (TRDD-Q6LPJTPO): a lone line with no setting after the `;` is hidden when the value looks like a secret on its own; 7c79e3c0 had made it visible. AccountKey is used because the assignment rule already hides a lone Password/Pwd/AccessKey/SharedAccessKey line (as 'assignment'), so only AccountKey reaches this branch.
    ['AccountKey=V; alone on a line', v => [`AccountKey=${v};`, `AccountKey=${CONN_KEY};`]],
    ['ODBC: Pwd=V;', v => [`Driver={ODBC};Server=h;Uid=u;Pwd=${v};`, `Driver={ODBC};Server=h;Uid=u;Pwd=${CONN_KEY};`]],
    ['endpoint=https://h/;accesskey=<value>', v => [`endpoint=https://h/;accesskey=${v}`, `endpoint=https://h/;accesskey=${CONN_KEY}`]],
    [
      'Service Bus: SharedAccessKey=V, the key name stays visible',
      v => [`Endpoint=sb://h/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=${v}`, `Endpoint=sb://h/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=${CONN_KEY}`],
    ],
  ]
  for (const [name, build] of keys) {
    test(name, () => {
      const [input, want] = build(fake())
      for (const out of threeWays(input)) expect(out).toBe(want)
    })
  }

  test('a token already hidden in a connection string is counted once, as a token', () => {
    const { text, hits } = redact(`Server=h;Password=${j('gh', 'p_', fake(36))};`)
    expect(text).toBe(`Server=h;Password=${mark('github-token')};`)
    expect(hits).toEqual({ 'github-token': 1 })
  })
})

describe('names and values that look like keys but are not stay visible', () => {
  const guards = [
    "const STORAGE_KEY = 'todos-vuejs'",
    'account_key: "acct_12345"',
    'primary_key: "user_id"',
    'sort-key: "created_at"',
    'cache.key: "user_prefs"',
    'hotkey: "ctrl+k"',
    'a=1;password=getPw()',
    'x;password=input.value',
    'Password=${DB_PASS};Server=h',
    'Password=changeme;Server=h',
    'password=abc',
    // WHY (TRDD-Q6LPJTPO): code statements, slugs and ids that commit dd145aa4 hid by mistake; each must stay visible.
    '    password = hashed;',
    'a = 1; password = pw;',
    'Pwd = encoded;',
    "const STORAGE_KEY = 'user-preferences-v2-2024'",
    'account_key: "acct_1A2b3C4d5E6f7G8h"',
    // Line start with no key after the `;`: the end of a code statement. Only guard 2b keeps it visible.
    'password=hashed;',
    // No spaces in the second pair, so only guard 2c (the segment before the `;` holds no `Name=`) keeps it visible.
    'a = 1;password=pw;',
    // A `Name=value` pair before it, so guard 2c passes; the spaced `=` with a plain word is what only guard 2a keeps visible.
    'x=1; password = hashed;',
    // WHY (TRDD-Q6LPJTPO): the segment before it, `Server=h`, holds a `\w=`, so guard 2c passes and the value has no spaced `=`; only the dotted-identifier check (a property access, not a literal) keeps it visible.
    'Server=h;Password=cfg.dbPassword;',
  ]
  for (const line of guards) {
    test(line, () => {
      for (const out of threeWays(line)) expect(out).toBe(line)
    })
  }
})


// False-positive fixes for the name rules (TRDD-Q6LPJTPO). The values are made at run time, as above.
describe('a STRONG_NAME needs a mixed-case base64 key; a spaced connection-string pair needs a secret-looking value', () => {
  test('storage_key = "<40 lowercase hex>" (a SHA) stays visible', () => {
    const hex = Array.from({ length: 40 }, () => '0123456789abcdef'[Math.floor(Math.random() * 16)]).join('')
    const line = `storage_key = "${hex}"`
    for (const out of threeWays(line)) expect(out).toBe(line)
  })

  test('storage_key = "<44 mixed-case base64 characters>" is hidden', () => {
    const key = fake(44)
    expect(key.length).toBe(44)
    for (const out of threeWays(`storage_key = "${key}"`)) expect(out).toBe(`storage_key = "${ASSIGNED}"`)
  })

  test('Server=h; Password = V; with spaces around the = is hidden through looksSecret', () => {
    const [input, want] = [`Server=h; Password = ${fake()};`, `Server=h; Password = ${CONN_KEY};`]
    for (const out of threeWays(input)) expect(out).toBe(want)
  })
})
