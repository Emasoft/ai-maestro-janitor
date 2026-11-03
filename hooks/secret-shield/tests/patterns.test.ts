import { describe, expect, test } from 'claude-code/testing'

import { countOf, isSecretFile, label, mark, redact, redactBlocks, redactDeep, withhold } from '../patterns'

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
