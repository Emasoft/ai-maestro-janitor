// WHY this file exists (TRDD-BAQB9SYO): redactJsonLine decodes every string of a transcript line before the rules read it, so a secret behind an escape (`\n`, `\t`, `\"`, `\/`, a backslash-u sequence, a JSON
// document inside a string) is hidden like a plain one. The table below is the measured outcome of 134 cases (13 kinds x the forms of the escape measurement, reports_dev/sonnet-worker/json-line/): each cell
// asserts the outcome measured for the shipped function, three generated values per kind, on every view of the output line a reader could decode.
// The fakes are built at run time from generated bodies; a vendor prefix or a PEM marker is split in the source, and no assertion prints a value.
import { describe, expect, test } from 'claude-code/testing'

import { countOf, mapJsonLineStrings, propagates, redact, redactJsonLine } from '../patterns'

const j = (...parts: string[]) => parts.join('')
const BASE62 = '0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'

/** A deterministic stream of 32-bit numbers from a seed (a string hash feeding mulberry32): a hooks module may import nothing but relative files and "claude-code", so no crypto module. */
function stream(seed: string): () => number {
  let h = 2166136261
  for (let i = 0; i < seed.length; i++) h = Math.imul(h ^ seed.charCodeAt(i), 16777619)
  let a = h
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return (t ^ (t >>> 14)) >>> 0
  }
}
const pick = (alphabet: string, seed: string, n: number): string => {
  const next = stream(seed)
  let out = ''
  for (let i = 0; i < n; i++) out += alphabet[next() % alphabet.length]
  return out
}

/** A deterministic base62 body of `n` characters from a seed, never a literal in this source. */
const b62 = (seed: string, n: number): string => pick(BASE62, seed, n)
const hex = (seed: string, n: number): string => pick('0123456789abcdef', seed, n)
const b64url = (text: string): string => btoa(text).replaceAll('+', '-').replaceAll('/', '_').replaceAll('=', '')

type Kind = { name: string; pre: string; s: string; units: string[]; post: string; p3?: string; pem?: boolean }

function kinds(seed: string): Kind[] {
  const q = '"'
  const pw = b62(`${seed}:pg-pw`, 16)
  const webhook = j('T', b62(`${seed}:wh-a`, 8).toUpperCase(), '/B', b62(`${seed}:wh-b`, 10).toUpperCase(), '/', b62(`${seed}:wh-c`, 24))
  const jwt = [b64url(JSON.stringify({ alg: 'HS256', typ: 'JWT' })), b64url(JSON.stringify({ sub: 'user-' + b62(`${seed}:jwt-s`, 6), iat: 1700000000, jti: b62(`${seed}:jwt-j`, 20) })), b62(`${seed}:jwt-sig`, 43)].join('.')
  const pemLines = [0, 1, 2].map(i => pick(BASE62 + '+/', `${seed}:pem:${i}`, 64).replace(/^(.{10})./, '$1/'))
  const pem = j('-----BEGIN ', 'RSA ', 'PRIVATE KEY-----\n') + pemLines.join('\n') + j('\n-----END ', 'RSA ', 'PRIVATE KEY-----')
  const aws = b62(`${seed}:aws-a`, 19) + '/' + b62(`${seed}:aws-b`, 20)
  const npmPre = '//registry.example.test/:_authToken='
  const github = j('gh', 'p_') + b62(`${seed}:gh`, 36)
  const akid = j('AK', 'IA') + b62(`${seed}:akid`, 16).toUpperCase()
  const slack = j('xo', 'xb-') + b62(`${seed}:slack`, 40)
  const stripe = j('sk_', 'live_') + b62(`${seed}:stripe`, 30)
  const hook = j('https://hooks.', 'slack.com/services/') + webhook
  const dsn = j('postgres', '://u_', b62(`${seed}:pg-user`, 8), ':', pw, '@db.internal.example:5432/appdb')
  const bearer = b62(`${seed}:bearer`, 40)
  const assign = b62(`${seed}:assign`, 20)
  const npm = b62(`${seed}:npm`, 36)
  const jsonpw = b62(`${seed}:jsonpw`, 20)
  return [
    { name: 'github-token', pre: '', s: github, units: [github], post: '' },
    { name: 'aws-access-key-id', pre: '', s: akid, units: [akid], post: '' },
    { name: 'aws-secret-key', pre: 'aws_secret_access_key=', s: aws, units: [aws], post: '' },
    { name: 'slack-token', pre: '', s: slack, units: [slack], post: '' },
    { name: 'slack-webhook', pre: '', s: hook, units: [webhook], post: '' },
    { name: 'stripe-key', pre: '', s: stripe, units: [stripe], post: '' },
    { name: 'jwt', pre: '', s: jwt, units: [jwt], post: '' },
    { name: 'pem-private-key', pre: '', s: pem, units: pemLines, post: '', pem: true },
    { name: 'url-user-password', pre: '', s: dsn, units: [pw], post: '' },
    { name: 'bearer-token', pre: 'Authorization: Bearer ', s: bearer, units: [bearer], post: '' },
    { name: 'name-assignment', pre: 'password=', s: assign, units: [assign], post: '' },
    { name: 'npmrc-auth-token', pre: npmPre, s: npm, units: [npm], post: '', p3: q + npmPre },
    { name: 'json-pair-password', pre: j('{', q, 'password', q, ': ', q), s: jsonpw, units: [jsonpw], post: q + '}' },
  ]
}

const kindNamed = (seed: string, name: string): Kind => {
  const k = new Map(kinds(seed).map(x => [x.name, x] as const)).get(name)
  if (k === undefined) throw new Error('no kind ' + name)
  return k
}

const FORMS = ['1', '2n', '2t', '3', '4', '5a', '5b', '5c', '6', '7', '7b', 'C'] as const
type Form = (typeof FORMS)[number]

const esc = (s: string): string => JSON.stringify(s).slice(1, -1)
const uesc = (s: string): string => [...s].map(c => '\\u' + c.charCodeAt(0).toString(16).padStart(4, '0')).join('')

/** The JSON-string content (already escaped) for one kind and one form, or null when the form does not apply to the kind. */
function build(k: Kind, form: Form): string | null {
  const { pre, s, post } = k
  const q = '"'
  switch (form) {
    case '1':
      return k.pem ? null : esc('output: ' + pre + s + post)
    case '2n':
      return esc('done\n' + pre + s + post)
    case '2t':
      return esc('done\t' + pre + s + post)
    case '3':
      return post ? null : esc('val ' + (k.p3 ?? pre + q) + s + q + ' end')
    case '4':
      return (pre + s).includes('/') ? esc('output: ' + pre + s + post).replaceAll('/', '\\/') : null
    case '5a':
      return esc('output: ' + pre) + uesc(s.slice(0, 4)) + esc(s.slice(4) + post)
    case '5b':
      return esc('output: ' + pre) + uesc(s) + esc(post)
    case '5c': {
      const whole = pre + s
      const at = whole.indexOf(k.units[0]) + Math.floor(k.units[0].length / 2)
      return esc('output: ' + whole.slice(0, at)) + uesc(whole[at]) + esc(whole.slice(at + 1) + post)
    }
    case '6':
      return k.pem ? esc('key: ' + s) : null
    case '7':
      return esc(JSON.stringify({ command: 'run ' + pre + s + post }))
    case '7b':
      return esc(JSON.stringify({ input: JSON.stringify({ value: pre + s + post }) }))
    case 'C':
      return esc('first: ' + pre + s + post + '\ndone\n' + pre + s + post)
  }
}

const lineFor = (content: string, n: number): string =>
  `{"type":"user","uuid":"00000000-0000-4000-8000-${String(n).padStart(12, '0')}","timestamp":"2026-11-18T10:00:00.000Z","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"toolu_${String(n).padStart(8, '0')}","content":"${content}"}]}}`

// Every readable form of an output line: the line, its decoded strings, the inner JSON when a string parses, and each of those unescaped up to 3 more times.
const tryParse = (text: string): unknown => {
  try {
    return JSON.parse(text)
  } catch {
    return undefined
  }
}
const stringsOf = (value: unknown): string[] => {
  if (typeof value === 'string') return [value]
  if (Array.isArray(value)) return value.flatMap(stringsOf)
  if (value !== null && typeof value === 'object') return Object.values(value).flatMap(stringsOf)
  return []
}
const unescapeOnce = (v: string): string =>
  v
    .replace(/\\u([0-9a-fA-F]{4})/g, (_m, hex: string) => String.fromCharCode(parseInt(hex, 16)))
    .split('\\/').join('/')
    .split('\\n').join('\n')
    .split('\\t').join('\t')
    .split('\\"').join('"')
    .split('\\\\').join('\\')
function viewsOf(outLine: string): string {
  const views = [outLine, ...stringsOf(JSON.parse(outLine))]
  for (const v of [...views]) views.push(...stringsOf(tryParse(v)))
  for (const v of [...views]) {
    let w = v
    for (let i = 0; i < 3; i++) {
      w = unescapeOnce(w)
      views.push(w)
    }
  }
  return views.join('\0')
}

type Outcome = 'removed' | 'partly left' | 'fully left'
const WINDOW = 12
function outcomeOf(units: string[], out: string): Outcome {
  const big = viewsOf(out)
  const whole = units.filter(u => big.includes(u)).length
  if (whole === units.length) return 'fully left'
  const windowed = units.some(u => {
    for (let i = 0; i + WINDOW <= u.length; i++) if (big.includes(u.slice(i, i + WINDOW))) return true
    return false
  })
  return windowed ? 'partly left' : 'removed'
}

// KNOWN MISSES, not a guarantee: the cells the function leaves whole, as measured (8 of 134 cases); plain-text redact() leaves the same text whole, so the transcript lane inherits the gap, it is not closed here. name-assignment: the assignment pass is anchored to a line start, so a `password=<value>` right after an escaped newline
// (forms 2n, C) or at the start of a JSON string (7b) is hidden, and one after other text on the same line is not (forms 1, 2t, 3, 5a, 5b, 5c, 7), exactly as in plain text. bearer-token form 3:
// `Bearer "<value>"` with a quote between the word and the value is not hidden in plain text either (the rule has no room for a quote). A fix turns the cell red: move it out of this list.
const LEFT_WHOLE = new Set(['name-assignment|1', 'name-assignment|2t', 'name-assignment|3', 'name-assignment|5a', 'name-assignment|5b', 'name-assignment|5c', 'name-assignment|7', 'bearer-token|3'])

const SEEDS = ['a', 'b', 'c']

describe('redactJsonLine hides a secret behind each escape form', () => {
  let n = 0
  for (const name of kinds('x').map(k => k.name)) {
    for (const form of FORMS) {
      if (build(kindNamed('x', name), form) === null) continue
      const expected: Outcome = LEFT_WHOLE.has(`${name}|${form}`) ? 'fully left' : 'removed'
      test(`${name}, form ${form}: ${expected}`, () => {
        for (const seed of SEEDS) {
          const k = kindNamed(seed, name)
          const line = lineFor(build(k, form)!, n++)
          JSON.parse(line)
          const out = redactJsonLine(line)
          JSON.parse(out.text)
          expect(outcomeOf(k.units, out.text)).toBe(expected)
        }
      })
    }
  }
})

describe('the detector of this file can see a leak', () => {
  test('the plain-text pass redact() leaves a github token whole after an escaped newline and when written as backslash-u escapes; redactJsonLine hides both', () => {
    for (const form of ['2n', '5b'] as const) {
      const k = kindNamed('control', 'github-token')
      const line = lineFor(build(k, form)!, 7000)
      expect(outcomeOf(k.units, redact(line).text)).toBe('fully left')
      expect(outcomeOf(k.units, redactJsonLine(line).text)).toBe('removed')
    }
  })
})

describe('redactJsonLine is stable', () => {
  // WHY timeoutMs 60000: the loop (3 seeds x kinds x 12 forms, 2 calls each) took 5367 ms under host load and failed on Bun's default 5000 ms (TRDD-5J3ITQXY); it has no timing bound, only correctness.
  test('running the output through it again changes nothing and finds nothing, in every case', { timeoutMs: 60000 }, () => {
    let n = 0
    for (const seed of SEEDS) {
      for (const k of kinds(seed)) {
        for (const form of FORMS) {
          const content = build(k, form)
          if (content === null) continue
          const first = redactJsonLine(lineFor(content, n++))
          const second = redactJsonLine(first.text)
          expect(second.text === first.text).toBe(true)
          expect(countOf(second.hits)).toBe(0)
        }
      }
    }
  })
})

describe('redactJsonLine leaves a clean line alone', () => {
  const h = (s: string, len: number): string => hex(s, len)
  const texts = [
    '$ git log --oneline -5\n' + [0, 1, 2, 3, 4].map(i => `${h('c' + i, 7)} fix(parser): handle empty input (TRDD-${h('t' + i, 8).toUpperCase()})`).join('\n'),
    'commit ' + h('full1', 40) + '\nAuthor: Dev <dev@users.noreply.example.test>\nDate:   Tue Nov 17 10:00:00 2026 +0100\n\n    chore: bump version',
    'sha256 ' + h('digest1', 64) + '  dist/plugin.tar.gz',
    'sha512 ' + h('digest2', 128) + '  dist/other.tar.gz',
    'export API_KEY=\nexport GITHUB_TOKEN=\nexport PASSWORD=\n# set SECRET_KEY in the shell before running',
    "def check(password: str, token: str) -> bool:\n    return len(password) > 8 and token != ''\n",
    "const apiKey = process.env.API_KEY\nconst token = await getToken(user)\nif (!token) throw new Error('no token')",
    "/" + "Users" + "/someone/Code/project/src/main.ts:42:7 error TS2322: Type 'string' is not assignable to type 'number'.",
    'drwxr-xr-x  12 user  staff   384 Nov 17 10:00 node_modules\n-rw-r--r--   1 user  staff  2048 Nov 17 10:00 package.json',
    'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==',
    'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAUAAAAFCAYAAACNbyblAAAAHElEQVQI12P4//8/w38GIAXDIBKE0DHxgljNBAAO9TXL0Y4OHwAAAABJRU5ErkJggg==',
    '{"id": "00000000-0000-4000-8000-000000000001", "name": "build", "status": "completed", "conclusion": "success", "run_number": 1234567}',
    '{"uuid": "9f1c2d3e-4b5a-4c6d-8e7f-0a1b2c3d4e5f", "parentUuid": null, "sessionId": "11111111-2222-4333-8444-555555555555"}',
    'npm WARN deprecated left-pad@1.3.0: use String.prototype.padStart()\nadded 412 packages in 9s',
    'Run npm install\n##[group]Run actions/checkout' + '@' + 'v4\nwith:\n  repository: owner/repo\n  token: ***\n##[endgroup]',
    'tests/test_parser.py::test_empty PASSED\ntests/test_parser.py::test_unicode PASSED\n== 2 passed in 0.12s ==',
    `diff --git a/src/a.ts b/src/a.ts\nindex ${h('i1', 7)}..${h('i2', 7)} 100644\n--- a/src/a.ts\n+++ b/src/a.ts\n@@ -1,3 +1,3 @@`,
    'Authorization header is built from the token variable, never logged; see docs/auth.md section 3',
    'https://github.com/owner/repo/pull/123 https://example.test/path?page=2&per_page=50#frag',
    'user@example.test connected from 192.0.2.10 port 22 at 2026-11-17T10:00:00Z',
    `ETag: W/"${h('etag', 32)}"\nContent-Type: application/json; charset=utf-8\nContent-Length: 1024`,
    'docker pull registry.example.test/team/app' + '@' + 'sha256:' + h('img', 64),
    'pip install -r requirements.txt\nCollecting requests==2.32.3\n  Downloading requests-2.32.3-py3-none-any.whl (64 kB)',
    'key: value\nlist:\n  - one\n  - two\nsecret_name: db-credentials\npassword_file: /run/secrets/db_password',
    'PRIVATE KEY files are never committed; the pattern lives in .gitignore as *.pem',
    'lockfile hash: sha1-' + h('l1', 40) + ' integrity sha512-' + h('l2', 40),
    'Traceback (most recent call last):\n  File "app.py", line 12, in <module>\n    main()\nKeyError: \'token\'',
    "SELECT id, name FROM users WHERE created_at > now() - interval '1 day' ORDER BY id LIMIT 50;",
    '1234567890123456789012345678901234567890 is a long number, 3.14159265358979 a float, 0x7fffffffffff a hex address',
    'ls -la ~/.ssh shows id_ed25519 and id_ed25519.pub; the public key line starts with ssh-ed25519',
    'const re = /^[A-Za-z0-9_-]{20,}$/\nconst ok = re.test(input)',
    'build 2026-11-17 10:00 version 3.9.9 commit ' + h('v', 12) + ' arch arm64',
    'Set-Cookie: theme=dark; Path=/; Secure; HttpOnly; SameSite=Lax',
    'WARN token bucket refilled: 100 tokens, rate 10/s, burst 20',
    'see https://docs.example.test/api/authentication for how to create an access token in the dashboard',
    'The password field must be at least 12 characters; the API key is shown once in the UI.',
    `id=${h('i', 24)} ref=refs/heads/main sha=${h('r', 40)}`,
  ]
  test('at least 30 lines of realistic tool output with no secret come back byte for byte, with no hit', () => {
    expect(texts.length).toBeGreaterThanOrEqual(30)
    texts.forEach((text, i) => {
      const line = lineFor(esc(text), 9000 + i)
      const out = redactJsonLine(line)
      expect(out.text).toBe(line)
      expect(countOf(out.hits)).toBe(0)
    })
  })

  test('numbers keep their bytes and members keep their order next to a hidden secret', () => {
    const clean = '{"b":12345678901234567890,"a":1.0e5,"s":"hello","n":[1.50,2e3]}'
    expect(redactJsonLine(clean).text === clean).toBe(true)
    const token = j('gh', 'p_') + b62('numbers', 36)
    const line = `{"b":12345678901234567890,"a":1.0e5,"s":"x ${token}","n":[1.50,2e3]}`
    const out = redactJsonLine(line)
    expect(out.text).toBe('{"b":12345678901234567890,"a":1.0e5,"s":"x [JANITOR-REDACTED:github-token]","n":[1.50,2e3]}')
    expect(countOf(out.hits)).toBe(1)
  })

  test('a line that is not JSON goes through redact()', () => {
    const plain = 'output: ' + j('gh', 'p_') + b62('plain', 36) + ' and more'
    expect(redactJsonLine(plain)).toEqual(redact(plain))
  })
})

describe('redactJsonLine spreads a hidden value to its copies in the same line', () => {
  test('a bare copy in another string, before and after the member that names it, is hidden', () => {
    for (const seed of SEEDS) {
      const value = kindNamed(seed, 'json-pair-password').s
      expect(propagates(value)).toBe(true)
      const line = JSON.stringify({ first: `note ${value} here`, password: value, last: `again ${value}` })
      const out = redactJsonLine(line)
      expect(viewsOf(out.text).includes(value)).toBe(false)
      expect(countOf(out.hits)).toBeGreaterThan(0)
    }
  })

  test('a name-assignment right after an escaped newline is hidden, and its copy mid-line with it; one mid-line alone is not (state of the rule: anchored to a line start)', () => {
    for (const seed of SEEDS) {
      const value = kindNamed(seed, 'name-assignment').s
      expect(propagates(value)).toBe(true)
      const both = redactJsonLine(JSON.stringify({ text: `first: password=${value}\ndone\npassword=${value}` }))
      expect(viewsOf(both.text).includes(value)).toBe(false)
      const alone = redactJsonLine(JSON.stringify({ text: `first: password=${value}` }))
      expect(viewsOf(alone.text).includes(value)).toBe(true)
    }
  })
})

describe('redactJsonLine keeps a member whose key is a secret', () => {
  test('a key that is a token is hidden, its plain value is unchanged, and the text undefined never appears', () => {
    for (const seed of SEEDS) {
      const token = j('gh', 'p_') + b62(`${seed}:key`, 36)
      const line = JSON.stringify({ [token]: 'plain text' })
      const out = redactJsonLine(line)
      const parsed = JSON.parse(out.text) as Record<string, unknown>
      expect(viewsOf(out.text).includes(token)).toBe(false)
      expect(Object.values(parsed)).toEqual(['plain text'])
      expect(out.text.includes('undefined')).toBe(false)
      expect(countOf(out.hits)).toBeGreaterThan(0)
    }
  })

  test('a token that is a key and also the value of another member is hidden in both places, and the line stays JSON', () => {
    for (const seed of SEEDS) {
      const token = j('gh', 'p_') + b62(`${seed}:both`, 36)
      const line = JSON.stringify({ [token]: 'plain text', other: token })
      const out = redactJsonLine(line)
      const parsed = JSON.parse(out.text) as Record<string, unknown>
      expect(viewsOf(out.text).includes(token)).toBe(false)
      expect(parsed.other).toBe('[JANITOR-REDACTED:github-token]')
      expect(Object.values(parsed)).toContain('plain text')
      expect(out.text.includes('undefined')).toBe(false)
    }
  })
})

describe('mapJsonLineStrings', () => {
  test('a string f leaves alone keeps its escapes byte for byte, and only a changed token is rewritten', () => {
    // WHY built from a char code: the escape must reach the function as a backslash-u sequence, not as the character it decodes to.
    const esc = String.fromCharCode(92) + 'u00e9'
    const line = String.raw`{"a":"x\/y ${esc}","b":"keep","n":12}`
    expect(mapJsonLineStrings(line, s => s)).toBe(line)
    const out = mapJsonLineStrings(line, s => (s === 'keep' ? 'swap' : s))
    expect(out).toBe(String.raw`{"a":"x\/y ${esc}","b":"swap","n":12}`)
  })

  test('a JSON document carried as a string is walked, and the nested string is the one f sees', () => {
    const inner = JSON.stringify({ p: 'old-value' })
    const seen: string[] = []
    const out = mapJsonLineStrings(JSON.stringify({ input: inner }), s => {
      seen.push(s)
      return s.replace('old', 'new')
    })
    const outer = JSON.parse(out) as { input: string }
    expect(JSON.parse(outer.input)).toEqual({ p: 'new-value' })
    expect(seen.includes('old-value')).toBe(true)
    expect(seen.includes(inner)).toBe(false)
  })

  test('the result always parses, whatever f returns for a string (a quote, a backslash, a newline)', () => {
    const out = mapJsonLineStrings(JSON.stringify({ k: 'v' }), s => (s === 'v' ? 'v"\\\n' : s))
    expect(JSON.parse(out)).toEqual({ k: 'v"\\\n' })
  })
})
