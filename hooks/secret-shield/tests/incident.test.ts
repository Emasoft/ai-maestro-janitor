// TRDD-Q6LPJTPO: replays the 2026-11-03 incident, where a pm2 jlist dump put PyPI tokens and a Dropbox app secret
// into a session. Every fake is assembled at run time, and every check compares booleans, so a failing test never
// prints a fake.
import { describe, expect, test } from 'claude-code/testing'

import { mark, redact } from '../patterns'

import { minMs } from './load/timing'

const j = (...parts: string[]) => parts.join('')

const PYPI_API = j('pypi-', 'AgE', 'A'.repeat(170))
const PYPI_PUBLISH = j('pypi-', 'AgE', 'B'.repeat(170))
// 15 lowercase letters and digits, no prefix: only the key name says it is a secret.
const DROPBOX = j('k7q', 'x2m9p4', 'w8z1r6')
const OPENAI = j('sk-', 'proj-', 'aB3dE5fG7hJ9kL1mN3pQ', '5rS7tU9vW1xY3zA5')
const FAKES: Array<[string, string]> = [
  ['PYPI_API_TOKEN', PYPI_API],
  ['PYPI_PUBLISH_TOKEN', PYPI_PUBLISH],
  ['OPENAI_API_KEY', OPENAI],
  ['DROPBOX_APP_SECRET', DROPBOX],
]

const env = (): Record<string, string> => ({
  NODE_ENV: 'production',
  PYPI_API_TOKEN: PYPI_API,
  PYPI_PUBLISH_TOKEN: PYPI_PUBLISH,
  OPENAI_API_KEY: OPENAI,
  DROPBOX_APP_SECRET: DROPBOX,
})

// The shape of `pm2 jlist`: one app, its env at the top and again under pm2_env.env. DROPBOX_APP_SECRET is the
// last value in the dump, so the truncated variant cuts inside it.
const PLAIN = JSON.stringify([
  {
    pid: 4242,
    name: 'publisher',
    pm2_env: { status: 'online', exec_mode: 'fork_mode', pm_id: 0, restart_time: 3, env: env() },
    env: env(),
  },
])

const cutAt = PLAIN.lastIndexOf(DROPBOX) + 10
const TRUNCATED = PLAIN.slice(0, cutAt)
const DROPBOX_HEAD = DROPBOX.slice(0, 10)

const VARIANTS: Array<[string, string]> = [
  ['(a) plain', PLAIN],
  ['(b) cut off mid-value', TRUNCATED],
  ['(c) stringified once, quotes escaped as \\"', JSON.stringify(PLAIN)],
  ['(d) stringified twice, quotes escaped as \\\\\\"', JSON.stringify(JSON.stringify(PLAIN))],
]

describe('the 2026-11-03 pm2 jlist incident', () => {
  for (const [variant, input] of VARIANTS) {
    for (const [name, fake] of FAKES) {
      test(`${variant}: ${name} is hidden`, () => {
        const { text } = redact(input)
        // In the truncated dump the last Dropbox value is only its first 10 characters.
        const truncated = variant.startsWith('(b)') && name === 'DROPBOX_APP_SECRET'
        expect(text.includes(truncated ? DROPBOX_HEAD : fake)).toBe(false)
      })
    }
    test(`${variant}: only the secret values are hidden`, () => {
      const { text, hits } = redact(input)
      for (const kept of ['publisher', 'NODE_ENV', 'production', 'fork_mode', ...FAKES.map(([name]) => name)]) {
        expect(`${kept} ${text.includes(kept)}`).toBe(`${kept} true`)
      }
      // Dropbox 2 as assignment (in (b) one is the truncated value), PyPI 4 as pypi-token, OpenAI 2 as openai-key.
      expect(hits).toEqual({ assignment: 2, 'pypi-token': 4, 'openai-key': 2 })
    })
  }
})

describe('an unterminated secret value does not make redact backtrack', () => {
  const MB = 1024 * 1024
  const cases: Array<[string, string]> = [
    ['escaped JSON', j('\\"password\\":\\"', 'a'.repeat(MB))],
    ['assignment', j('password=', 'a'.repeat(MB))],
  ]
  for (const [shape, input] of cases) {
    // WHY minMs N=3 and timeoutMs 30000: the single-shot timing flaked under host load (TRDD-5J3ITQXY); 1 warm-up + 3 timed runs + 1 untimed correctness call at the 2000 ms bound is 10 s worst case, so the runner limit (was 2000, equal to the bound) is raised; the bound stays 2000 ms.
    test(`1 MB after the ${shape} opener finishes well under the 10 s hook limit, and is hidden`, { timeoutMs: 30000 }, () => {
      expect(minMs(() => redact(input).text.length, 3).ms).toBeLessThan(2000)
      // A regex engine that gives up on a long match returns no match: fast, and a silent miss. Count the hit, on a separate untimed call.
      expect(redact(input).hits).toEqual({ assignment: 1 })
    })
  }
  // A closed plain value of 1 MB. The pattern before TRDD-Q6LPJTPO missed it (no match, about 60 ms): JavaScriptCore
  // gave up on its once-per-character group. Fix proof, measured 2026-11-04.
  // WHY minMs N=3 and timeoutMs 30000: the single-shot timing flaked under host load (TRDD-5J3ITQXY); 1 warm-up + 3 timed runs + 1 untimed correctness call at the 2000 ms bound is 10 s worst case, so the runner limit (was 2000, equal to the bound) is raised; the bound stays 2000 ms. The hit count is asserted on that separate untimed call.
  test('1 MB inside a closed plain JSON value is hidden well under the 10 s hook limit', { timeoutMs: 30000 }, () => {
    const input = j('{"password":"', 'a'.repeat(MB), '"}')
    expect(minMs(() => redact(input).text.length, 3).ms).toBeLessThan(2000)
    expect(redact(input).hits).toEqual({ assignment: 1 })
  })
})

describe('a value cut inside its closing escape', () => {
  const cases: Array<[string, string]> = [
    ['escaped once, cut after the backslash', j('\\"DROPBOX_APP_SECRET\\":\\"', DROPBOX, '\\')],
    ['escaped at depth 3, cut after two backslashes', j('\\\\\\"DROPBOX_APP_SECRET\\\\\\":\\\\\\"', DROPBOX, '\\\\')],
    ['plain, cut after a lone backslash', j('{"password": "', DROPBOX, '\\')],
  ]
  for (const [what, input] of cases) {
    test(`${what}: the value is hidden and the backslashes kept`, () => {
      const { text, hits } = redact(input)
      expect(hits).toEqual({ assignment: 1 })
      expect(text === input.replace(DROPBOX, mark('assignment'))).toBe(true)
    })
  }
})

describe('a long run of escape pairs in a plain JSON value', () => {
  test('a value holding 20,000 escaped quotes and a token-like tail is hidden', () => {
    const tail = j('Zq8', 'Wm3', 'Xr5', 'Tn7', 'Kp1')
    // The leading brace keeps the line-assignment rule out, so the JSON pair rule is the one tested.
    const input = j('{"password":"', '\\"'.repeat(20000), tail, '"}')
    const { text, hits } = redact(input)
    expect(hits).toEqual({ assignment: 1 })
    expect(text.includes(tail)).toBe(false)
    expect(text).toBe(j('{"password":"', mark('assignment'), '"}'))
  })
})

describe('JSON pairs that name a secret without holding one', () => {
  const samples: Array<[string, string]> = [
    ['a token type', '"token_type": "Bearer"'],
    ['an empty password', '"password": ""'],
    ['a placeholder', '"api_key": "<your-key-here>"'],
    ['an escaped token type', '\\"token_type\\":\\"bearer\\"'],
    ['an unclosed prose value', '{"password": "must be at least 12 characters, see docs'],
  ]
  for (const [what, input] of samples) {
    test(`${what} is left unchanged`, () => {
      const { text, hits } = redact(input)
      expect(text).toBe(input)
      expect(hits).toEqual({})
    })
  }
})

// A JSON value with no closing quote is judged by the strict unquoted check; the same value closed by the lenient
// quoted one. 'notasecret' passes only the lenient check: 10 characters, no digit, under 16.
describe('an unclosed JSON value is judged as unquoted', () => {
  const cases: Array<[string, string, boolean]> = [
    ['an unclosed plain value stays', '{"password": "notasecret', false],
    ['the same value closed is hidden', '{"password": "notasecret"}', true],
    ['an unclosed escaped value stays', '\\"password\\":\\"notasecret', false],
    ['the same escaped value closed is hidden', '\\"password\\":\\"notasecret\\"', true],
  ]
  for (const [what, input, hidden] of cases) {
    test(what, () => {
      const { text, hits } = redact(input)
      if (hidden) {
        expect(hits).toEqual({ assignment: 1 })
        expect(text).toBe(input.replace('notasecret', mark('assignment')))
      } else {
        expect(hits).toEqual({})
        expect(text).toBe(input)
      }
    })
  }
})

describe("this repo's own code that names secrets without holding any", () => {
  const samples: Array<[string, string]> = [
    // scripts/lib/usage_probe.py
    ['usage_probe.py', ['    token = oauth.get("accessToken")', '    return (token if isinstance(token, str) and token else None), exp_s'].join('\n')],
    // scripts/hooks/pre-compact-handoff.py
    ['pre-compact-handoff.py', ['                    token = m.group(1)', '                        token not in seen', '                        and not token.startswith("janitor-")'].join('\n')],
    // scripts/lib/telemetry_poisoning_patterns.py
    ['telemetry_poisoning_patterns.py', ['        token = m.group(1).lower()', '        if token in _HIGH_CARDINALITY_LABELS:', '            return token'].join('\n')],
  ]
  for (const [file, code] of samples) {
    test(`${file} is left unchanged`, () => {
      const { text, hits } = redact(code)
      expect(text).toBe(code)
      expect(hits).toEqual({})
    })
  }
})
