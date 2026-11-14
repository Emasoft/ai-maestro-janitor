import { describe, expect, test } from 'claude-code/testing'

import { applyRule, countOf, isSecretFile, JSON_ESCAPE_BOUND, label, mark, redact, redactBlocks, redactDeep, TOKEN_ORDER, URL_PASSWORD_BOUND, withhold } from '../patterns'
import { githubTokenClassic, githubTokenFineGrained } from '../rules/code-hosts'
import { openaiKey48 } from '../rules/ai'
import { pypiToken } from '../rules/dev-services'
import { jwt, privateKey } from '../rules/key-material'
import { stripeSecretKey, stripeWebhookSecret } from '../rules/messaging-payments'

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

// GitHub token length floors (TRDD-6A3XW3VO, 2026-11-14): the classic floor went 36 -> 30, the fine-grained floor 22 -> 20, and the trailing \b was dropped.
// WHY the differential test: the widening must be a superset. Every span the old rule hid must still be hidden, so the old patterns are kept here as constants.
describe('GitHub tokens shorter than the old floors are hidden, nothing the old rules hid becomes visible', () => {
  const OLD_CLASSIC = /\b(gh[pousr]_[A-Za-z0-9]{36,255})\b/g
  const OLD_FINE_GRAINED = /\b(github_pat_[A-Za-z0-9_]{22,255})\b/g
  // The new patterns are the shipped rules' own, copied so a run keeps no lastIndex (rules/rule.ts); the old ones are the constants above.
  const NEW_CLASSIC = new RegExp(githubTokenClassic.pattern.source, 'g')
  const NEW_FINE_GRAINED = new RegExp(githubTokenFineGrained.pattern.source, 'g')
  // Mixed fake bodies built from repeated characters at run time: no secret-looking literal is committed.
  const cycle = (n: number, alphabet: string) => alphabet.repeat(Math.ceil(n / alphabet.length)).slice(0, n)
  const classic = (n: number, prefix = j('gh', 'p_')) => prefix + cycle(n, 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5')
  const fine = (n: number) => j('github', '_pat_') + cycle(n, 'aB3dE5fG7_hJ9kL1mN3pQ5_')

  test('a classic token with a 30 to 35 character body is hidden', () => {
    for (const n of [30, 31, 33, 35]) {
      const token = classic(n)
      const { text, hits } = redact(`value: ${token} end`)
      expect(text).toBe(`value: ${mark('github-token')} end`)
      expect(hits).toEqual({ 'github-token': 1 })
    }
  })

  test('a fine-grained token with a 20 or 21 character body is hidden', () => {
    for (const n of [20, 21]) {
      const token = fine(n)
      const { text, hits } = redact(`value: ${token} end`)
      expect(text).toBe(`value: ${mark('github-token')} end`)
      expect(hits).toEqual({ 'github-token': 1 })
    }
  })

  test('a classic token whose tail continues with an underscore is hidden up to the underscore', () => {
    const body = cycle(30, 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5')
    const { text } = redact(`value: ${j('gh', 'p_')}${body}_more end`)
    expect(text).not.toContain(body)
  })

  test('the old rules hid a classic body of 36 characters and 37, the new one hides them too', () => {
    for (const n of [36, 37]) expect(redact(`value: ${classic(n)} end`).text).toBe(`value: ${mark('github-token')} end`)
  })

  test('FLOOR pin (minimum length): a classic body of 29 and a fine-grained body of 19 stay visible', () => {
    expect(redact(`value: ${classic(29)} end`).text).toContain(classic(29))
    expect(redact(`value: ${fine(19)} end`).text).toContain(fine(19))
  })

  // The two tests below pin the CURRENT, deliberately chosen behaviour of the {30,255} / {20,255} caps and of the classic character class. They are not claims about what is ideal. A new rule that hides the 45-character tail or the `_suffixtext` tail must update these pins on purpose.
  test('deliberate pin of current behaviour: a 300-character body is hidden up to the 255 cap only, the last 45 characters stay visible', () => {
    for (const [token, prefix] of [[classic(300), j('gh', 'p_')], [fine(300), j('github', '_pat_')]] as const) {
      const body = token.slice(prefix.length)
      const { text, hits } = redact(`value: ${token} end`)
      expect(text).toBe(`value: ${mark('github-token')}${body.slice(255)} end`)
      expect(hits).toEqual({ 'github-token': 1 })
    }
  })

  test('deliberate pin of current behaviour: a classic token is cut at an underscore and the tail stays visible, a fine-grained token extends through it', () => {
    const classicToken = classic(36)
    expect(redact(`value: ${classicToken}_suffixtext end`).text).toBe(`value: ${mark('github-token')}_suffixtext end`)
    const fineToken = fine(36)
    expect(redact(`value: ${fineToken}_suffixtext end`).text).toBe(`value: ${mark('github-token')} end`)
  })

  test('every span an old rule matched is still hidden by the new rule, over the suite samples and generated lengths', () => {
    const suiteSamples = [
      j('gh', 'p_', A36),
      j('gh', 's_', A36),
      j('gh', 'p_', 'A1b2C3d4E5f6G7h8I9j0', 'K1l2M3n4O5p6Q7r8'),
      j('gh', 'p_', 'B2c3D4e5F6g7H8i9J0k1', 'L2m3N4o5P6q7R8s9'),
      j('github', '_pat_', '11ABCDEFG0123456789_abcdefghijklmnopqrstuvwxyz'),
    ]
    const generated: string[] = []
    for (const n of [30, 36, 40, 255]) for (const prefix of ['gh' + 'p_', 'gh' + 'o_', 'gh' + 'u_', 'gh' + 's_', 'gh' + 'r_']) generated.push(classic(n, prefix))
    for (const n of [20, 22, 82]) generated.push(fine(n))
    const contexts = [(t: string) => t, (t: string) => `value: ${t} end`, (t: string) => `{"token":"${t}"}`, (t: string) => `a ${t}\n`]
    let oldSpans = 0
    for (const sample of [...suiteSamples, ...generated]) {
      for (const frame of contexts) {
        const text = frame(sample)
        const done = redact(text).text
        for (const [oldRule, newRule] of [[OLD_CLASSIC, NEW_CLASSIC], [OLD_FINE_GRAINED, NEW_FINE_GRAINED]] as const) {
          const newSpans = [...text.matchAll(newRule)].map(m => [m.index, m.index + m[0].length])
          for (const m of text.matchAll(oldRule)) {
            oldSpans++
            const start = m.index
            const end = m.index + m[0].length
            expect(newSpans.some(([s, e]) => s <= start && e >= end)).toBe(true)
            expect(done).not.toContain(m[1])
          }
        }
      }
    }
    // A comparison over zero old matches would pass for any new rule.
    expect(oldSpans).toBeGreaterThan(40)
  })
})

// Stripe secret and restricted key length floor (TRDD-6A3XW3VO, 2026-11-14): the floor went 20 -> 16 and the trailing \b was dropped.
// WHY the differential test: the widening must be a superset. Every span the old rule hid must still be hidden, so the old pattern is kept here as a constant.
describe('Stripe keys shorter than the old floor are hidden, nothing the old rule hid becomes visible', () => {
  const OLD_STRIPE = /\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{20,})\b/g
  // The new pattern is the shipped rule's own, copied so a run keeps no lastIndex (rules/rule.ts); the old one is the constant above.
  const NEW_STRIPE = new RegExp(stripeSecretKey.pattern.source, 'g')
  const PREFIXES = [j('sk', '_live_'), j('sk', '_test_'), j('rk', '_live_'), j('rk', '_test_')]
  // Mixed fake bodies built from repeated characters at run time: no secret-looking literal is committed.
  const cycle = (n: number, alphabet: string) => alphabet.repeat(Math.ceil(n / alphabet.length)).slice(0, n)
  const stripe = (n: number, prefix = PREFIXES[0]) => prefix + cycle(n, 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5')

  test('a key with a 16 to 19 character body is hidden, for sk_live, sk_test, rk_live and rk_test', () => {
    for (const prefix of PREFIXES) {
      for (const n of [16, 17, 19]) {
        const { text, hits } = redact(`value: ${stripe(n, prefix)} end`)
        expect(text).toBe(`value: ${mark('stripe-key')} end`)
        expect(hits).toEqual({ 'stripe-key': 1 })
      }
    }
  })

  test('the old rule hid a body of 20 and 21 characters, the new one hides them too', () => {
    for (const prefix of PREFIXES) {
      for (const n of [20, 21]) expect(redact(`value: ${stripe(n, prefix)} end`).text).toBe(`value: ${mark('stripe-key')} end`)
    }
  })

  test('FLOOR pin (minimum length): a body of 15 characters stays visible', () => {
    for (const prefix of PREFIXES) expect(redact(`value: ${stripe(15, prefix)} end`).text).toContain(stripe(15, prefix))
  })

  // WHY: the old trailing \b never matched when the key was followed by an underscore (a word character), so the whole key stayed visible.
  test('a key whose tail continues with an underscore is hidden up to the underscore', () => {
    for (const n of [16, 24]) {
      const key = stripe(n)
      expect(redact(`value: ${key}_suffixtext end`).text).toBe(`value: ${mark('stripe-key')}_suffixtext end`)
    }
  })

  // The widening over-hides identifiers in two ways the old rule did not: a 16-19 letter camelCase run (the lower floor), and a camelCase run followed by an underscore (no trailing \b). Both are accepted over-hiding, the safe direction; both cases leave the old rule's text visible, so this test fails on the old rule. A change that stops hiding either must change this test on purpose.
  test('deliberate over-hide pin: camelCase identifiers after sk_test_ that the old rule left visible are now hidden, the safe direction', () => {
    expect(redact(`value: ${j('sk', '_test_')}createPaymentIntent end`).text).toBe(`value: ${mark('stripe-key')} end`)
    expect(redact(`value: ${j('sk', '_test_')}createPaymentIntentHelper_spec end`).text).toBe(`value: ${mark('stripe-key')}_spec end`)
  })

  test('every span the old rule matched is still hidden by the new rule, over the suite sample and generated lengths', () => {
    const suiteSamples = [j('sk', '_live_', 'aB3dE5fG7hJ9kL1mN3pQ5rS7')]
    const generated: string[] = []
    for (const n of [20, 24, 99]) for (const prefix of PREFIXES) generated.push(stripe(n, prefix))
    const contexts = [(t: string) => t, (t: string) => `value: ${t} end`, (t: string) => `{"token":"${t}"}`, (t: string) => `a ${t}\n`]
    let oldSpans = 0
    for (const sample of [...suiteSamples, ...generated]) {
      for (const frame of contexts) {
        const text = frame(sample)
        const done = redact(text).text
        const newSpans = [...text.matchAll(NEW_STRIPE)].map(m => [m.index, m.index + m[0].length])
        for (const m of text.matchAll(OLD_STRIPE)) {
          oldSpans++
          const start = m.index
          const end = m.index + m[0].length
          expect(newSpans.some(([s, e]) => s <= start && e >= end)).toBe(true)
          expect(done).not.toContain(m[1])
        }
      }
    }
    // A comparison over zero old matches would pass for any new rule.
    expect(oldSpans).toBeGreaterThan(40)
  })
})
// Stripe webhook signing secret (TRDD-RSI2OZ0B, 2026-11-14): the trailing \b was dropped; the 24 floor is unchanged.
// WHY the differential test: the widening must be a superset. Every span the old rule hid must still be hidden, so the old pattern is kept here as a constant.
describe('Stripe webhook secrets followed by an underscore are hidden, nothing the old rule hid becomes visible', () => {
  const OLD_WEBHOOK = /\b(whsec_[A-Za-z0-9]{24,})\b/g
  // The new pattern is the shipped rule's own, copied so a run keeps no lastIndex (rules/rule.ts); the old one is the constant above.
  const NEW_WEBHOOK = new RegExp(stripeWebhookSecret.pattern.source, 'g')
  const WHSEC = j('whsec', '_')
  // Mixed fake bodies built from repeated characters at run time: no secret-looking literal is committed.
  const cycle = (n: number, alphabet: string) => alphabet.repeat(Math.ceil(n / alphabet.length)).slice(0, n)
  const webhook = (n: number) => WHSEC + cycle(n, 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5')

  // WHY: the old trailing \b never matched when the secret was followed by an underscore (a word character), so the whole secret stayed visible.
  test('a secret whose tail continues with an underscore is hidden up to the underscore', () => {
    expect(redact(`value: ${webhook(32)}_suffixtext end`).text).toBe(`value: ${mark('stripe-key')}_suffixtext end`)
  })

  test('a body of 24 and of 40 characters followed by a space is hidden', () => {
    for (const n of [24, 40]) {
      const { text, hits } = redact(`value: ${webhook(n)} end`)
      expect(text).toBe(`value: ${mark('stripe-key')} end`)
      expect(hits).toEqual({ 'stripe-key': 1 })
    }
  })

  test('FLOOR pin (minimum length): a body of 23 characters stays visible', () => {
    expect(redact(`value: ${webhook(23)} end`).text).toContain(webhook(23))
  })

  test('every span the old rule matched is still hidden by the new rule, over generated lengths', () => {
    const contexts = [(t: string) => t, (t: string) => `value: ${t} end`, (t: string) => `{"token":"${t}"}`, (t: string) => `a ${t}\n`]
    let oldSpans = 0
    for (const n of [24, 32, 64]) {
      for (const frame of contexts) {
        const text = frame(webhook(n))
        const done = redact(text).text
        const newSpans = [...text.matchAll(NEW_WEBHOOK)].map(m => [m.index, m.index + m[0].length])
        for (const m of text.matchAll(OLD_WEBHOOK)) {
          oldSpans++
          const start = m.index
          const end = m.index + m[0].length
          expect(newSpans.some(([s, e]) => s <= start && e >= end)).toBe(true)
          expect(done).not.toContain(m[1])
        }
      }
    }
    // A comparison over zero old matches would pass for any new rule.
    expect(oldSpans).toBeGreaterThan(10)
  })
})
// OpenAI sk- keys (TRDD-6A3XW3VO, 2026-11-14): the third openai rule hid only sk- plus exactly 48 letters and digits, so a key with any other body length, or with a hyphen or underscore in the body, stayed visible.
// WHY the differential test: the widening must be a superset. Every span the old rule hid must still be hidden, so the old pattern is kept here as a constant. It includes bodies with no digit: a digit-requiring form of the new rule would lose those.
describe('OpenAI sk- keys with a body of 20 or more characters are hidden, nothing the old rule hid becomes visible', () => {
  const OLD_OPENAI = /\b(sk-[A-Za-z0-9]{48})\b/g
  // The new pattern is the shipped rule's own, copied so a run keeps no lastIndex (rules/rule.ts); the old one is the constant above.
  const NEW_OPENAI = new RegExp(openaiKey48.pattern.source, 'g')
  const SK = j('s', 'k-')
  // Mixed fake bodies built from repeated characters at run time: no secret-looking literal is committed.
  const cycle = (n: number, alphabet: string) => alphabet.repeat(Math.ceil(n / alphabet.length)).slice(0, n)
  const openai = (n: number, alphabet = A36) => SK + cycle(n, alphabet)

  test('a key with a 20 to 99 character body of letters and digits is hidden, the old rule hid only 48', () => {
    for (const n of [20, 23, 47, 49, 99]) {
      const { text, hits } = redact(`value: ${openai(n)} end`)
      expect(text).toBe(`value: ${mark('openai-key')} end`)
      expect(hits).toEqual({ 'openai-key': 1 })
    }
  })

  test('a key with hyphens or underscores in the body is hidden whole', () => {
    for (const key of [SK + 'or-v1-' + cycle(30, A36), SK + cycle(12, A36) + '_' + cycle(12, A36), SK + cycle(20, A36) + '-' + cycle(20, A36)]) {
      expect(redact(`value: ${key} end`).text).toBe(`value: ${mark('openai-key')} end`)
    }
  })

  test('a key built to the old shape is still hidden', () => {
    expect(redact(`value: ${openai(48)} end`).text).toBe(`value: ${mark('openai-key')} end`)
    expect(redact(`value: ${j(SK, 'proj-', cycle(40, A36))} end`).text).toBe(`value: ${mark('openai-key')} end`)
    expect(redact(`value: ${j(SK, cycle(20, A36), 'T3BlbkFJ', cycle(20, A36))} end`).text).toBe(`value: ${mark('openai-key')} end`)
  })

  test('FLOOR pin (minimum length): a body of 19 characters stays visible', () => {
    expect(redact(`value: ${openai(19)} end`).text).toContain(openai(19))
  })

  // WHY: the old trailing \b never matched when the 48-character key was followed by an underscore (a word character), so the whole key stayed visible.
  test('a 48 character key whose tail continues with an underscore is hidden through the tail', () => {
    expect(redact(`value: ${openai(48)}_suffixtext end`).text).toBe(`value: ${mark('openai-key')} end`)
  })

  // The widening hides any 20-character-or-longer run after sk-, including a hyphenated lowercase word run that is not a key. The TRDD-6A3XW3VO corpus run found one such run (a test-fixture slug) in 100 MB of third-party text, and 0 in 40 MB of this repo. Accepted over-hiding, the safe direction: a lookahead that needs a digit would also leave a key with no digit visible. The old rule left this text visible, so this test fails on the old rule. A change that stops hiding it must change this test on purpose.
  test('deliberate over-hide pin: a hyphenated word run after sk- that the old rule left visible is now hidden, the safe direction', () => {
    expect(redact(`value: ${SK}task-planner-helper-notes end`).text).toBe(`value: ${mark('openai-key')} end`)
  })

  // WHY: a long kebab identifier led by sk- (a CSS class, an id slug, a flag) is also hidden whole; accepted over-hide, safe direction. The old rule left it visible, so this fails on the old rule.
  test('deliberate over-hide pin: a long kebab identifier led by sk- is hidden whole', () => {
    const slug = 'onboarding-step-two-modal-header-title-text-'.repeat(2)
    expect(slug.length).toBeGreaterThanOrEqual(60)
    expect(redact(`value: ${SK}${slug} end`).text).toBe(`value: ${mark('openai-key')} end`)
  })

  test('every span the old rule matched is still hidden by the new rule, over generated 48 character bodies including no-digit ones', () => {
    const rotate = (k: number) => A36.slice(k) + A36.slice(0, k)
    const bodies = [...Array(10).keys()].map(k => cycle(48, rotate(k)))
    bodies.push(cycle(48, 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'), cycle(48, '0123456789'), cycle(48, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'))
    const contexts = [(t: string) => t, (t: string) => `value: ${t} end`, (t: string) => `{"token":"${t}"}`, (t: string) => `a ${t}\n`, (t: string) => `${t}-tail`]
    let oldSpans = 0
    for (const body of bodies) {
      for (const frame of contexts) {
        const text = frame(SK + body)
        const done = redact(text).text
        const newSpans = [...text.matchAll(NEW_OPENAI)].map(m => [m.index, m.index + m[0].length])
        for (const m of text.matchAll(OLD_OPENAI)) {
          oldSpans++
          const start = m.index
          const end = m.index + m[0].length
          expect(newSpans.some(([s, e]) => s <= start && e >= end)).toBe(true)
          expect(done).not.toContain(m[1])
        }
      }
    }
    // A comparison over zero old matches would pass for any new rule.
    expect(oldSpans).toBeGreaterThan(40)
  })
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

// WHY: the port-skip lookahead of the URL password rule scanned its query with [^\s@#]*=, which does not stop at ://, so every :// whose password
// starts with digits then ? scanned on past every later :// and past any =, up to the next whitespace, @ or #, at the latest the end of the line,
// and of the text when no newline follows. b://u:1? repeated k times and followed by n characters cost O(k*n). The growth tests grow the URL count
// with the size (size/16 URLs, then size/2 characters): with a fixed URL count the old regex is linear in n and the test proves nothing. They
// assert the ratio t(8s)/t(s), which is machine speed independent, never an absolute duration (the pinned 1 s test below is only a bound against a
// catastrophic slowdown) (TRDD-Q6LPJTPO: linear means the ratio stays near 8, quadratic means near 64). The sizes are 32 KB and 256 KB.
// Measured under claude plugin test on the grown() shape with a short password after the URLs (shape b), redact() took medians of about 3 ms at 96
// KB, 75 ms at 128 KB, 188 ms at 256 KB and 615 ms at 512 KB (load about 67): a step between 96 KB and 128 KB. The cause is measured
// (TRDD-HF7GNHNF): a greedy loop over a GROUP (the password loop and the query scan of the port-skip lookahead) runs about 35 times slower per
// character once one run passes about 63.8K iterations, and returns no match at all from about 553K (TRDD-AGOEWF2E); a loop over a single character
// class has neither ceiling. The loops are unrolled so a group iterates only at a colon, and a guard in redactUrlPasswords counts markers and colons
// before the regex runs (see the WHY block above URL_PASSWORD in patterns.ts). A size pair that straddles 63.8K iterations (32 KB to 256 KB does:
// grown() holds size/2 characters in one run) fails the ratio rule on the old regex and passes it now. The 2 ms escape is applied at the larger size
// of 256 KB, which is TRDD-Q6LPJTPO's. Each time is the best of 5 runs after one warm-up run, because under load a 64 KB time came within 0.4 ms of
// the 2 ms escape (1.6 ms).
describe('a port-skip query scan is linear up to 256 KB and still tells a port from a password', () => {
  const marker = '[JANITOR-' + 'REDACTED:url-password]'
  const SMALL = 32 * 1024
  const tail = '\n' + 'https://admin:' + 'Zq8' + 'vR2m' + '@db.example'
  const grown = (size: number) => 'b://u:1?'.repeat(size / 16) + 'x'.repeat(size / 2)
  const bestOf = (text: string) => {
    redact(text)
    const runs = [0, 1, 2, 3, 4].map(() => {
      const started = performance.now()
      const done = redact(text)
      return { ms: performance.now() - started, done }
    })
    return { ms: Math.min(...runs.map((r) => r.ms)), done: runs[0].done }
  }
  const linear = (small: number, big: number) => big < 2 || big / small < 12
  const timedRedact = (text: string) => {
    const started = performance.now()
    redact(text)
    return { ms: performance.now() - started }
  }
  test('8 times the text takes under 12 times as long, with a URL count that grows with the text', () => {
    const small = bestOf(grown(SMALL))
    const big = bestOf(grown(8 * SMALL))
    expect(linear(small.ms, big.ms)).toBe(true)
    expect(big.done.text === grown(8 * SMALL)).toBe(true)
    expect(big.done.hits['url-password']).toBeUndefined()
  })
  test('the same growth followed by a short, self-contained URL password still hides exactly that password at both sizes', () => {
    const small = bestOf(grown(SMALL) + tail)
    const big = bestOf(grown(8 * SMALL) + tail)
    expect(linear(small.ms, big.ms)).toBe(true)
    for (const r of [small, big]) {
      expect(r.done.hits['url-password']).toBe(1)
      expect(r.done.text.endsWith('https://admin:' + marker + '@db.example')).toBe(true)
    }
  })
  test('on grown() shape b, 256 KB of URLs followed by a short password still hides that password (no timing)', () => {
    const { text, hits } = redact(grown(256 * 1024) + tail)
    expect(hits['url-password']).toBe(1)
    expect(text.endsWith('https://admin:' + marker + '@db.example')).toBe(true)
  })
  test('100 KB of x followed by :// 10000 times finishes in under 1 s (pinned: linear today)', () => {
    expect(timedRedact('x'.repeat(100 * 1024) + '://'.repeat(10000)).ms).toBeLessThan(1000)
  })
  test('the last of 100 such URLs is still read: its password is hidden when no = comes first', () => {
    const { text, hits } = redact('b://u:1?'.repeat(100) + 'x'.repeat(1000) + '@h')
    expect(hits['url-password']).toBe(1)
    expect(text.endsWith('b://u:' + marker + '@h')).toBe(true)
  })
  test('a port stays unhidden whatever follows it', () => {
    for (const url of [
      'https://host:8080/path',
      'postgres://u' + '@' + 'h:5432/db',
      'http://h:80?a=b',
      'http://localhost:8080/a' + '@' + 'b',
      'https://h:3000?x=1' + '@' + 'y',
      'redis://h:6379/0',
      'http://h:12345/x' + '@' + 'y',
      'http://h:80?a=b' + '@' + 'c,ftp://other.example',
      'http://h:8080?' + 'k'.repeat(100 * 1024) + '=v' + '@' + 'x.io',
      'a://u:1?x://y=1' + '@' + 'h',
    ]) {
      const r = redact(url)
      expect(r.text === url).toBe(true)
      expect(r.hits['url-password']).toBeUndefined()
    }
  })
  test('a password is hidden when it is not a port', () => {
    for (const [url, hidden] of [
      ['http://h:123456/x' + '@' + 'y', 'http://h:' + marker + '@y'],
      ['https://u:12?ab' + '@' + 'h', 'https://u:' + marker + '@h'],
      ['https://u:12?ab' + '@' + 'h,ftp://z.example/q=1', 'https://u:' + marker + '@h,ftp://z.example/q=1'],
    ] as const) {
      expect(redact(url).text).toBe(hidden)
    }
  })
  // WHY these tests exist (TRDD-AGOEWF2E, TRDD-HF7GNHNF): under claude plugin test a greedy loop over a group stepped at about 63.8K iterations and
  // returned no match from about 553K, so one 1 MB URL password was not hidden. The loops are unrolled and a guard counts the markers and colons of
  // each URL before the regex runs. Passwords of every power of two from 256 KB to 4 MB must be hidden with exactly one hit; the discriminators below
  // fail when the guard is deleted (the unrolled regex alone reads the port shapes as ports, and misses a colon-dense password); the scheme and
  // whitespace cases fail when the guard reads either with a simpler rule than the regex does.
  const BOUND = URL_PASSWORD_BOUND
  const mixed = (n: number) => 'aB3dE5fG7hJ9kL1m'.repeat(n / 16)
  const bounded = (url: string) => {
    const r = redact(url)
    return { hidden: r.hits['url-password'] === 1 && countOf(r.hits) === 1, same: r.text === url, text: r.text }
  }
  test('one URL whose password alone is every power of two from 256 KB to 4 MB is hidden, with exactly one hit', { timeoutMs: 60000 }, () => {
    for (let n = 256 * 1024; n <= 4 * 1024 * 1024; n *= 2) {
      const r = redact('https://u:' + mixed(n) + '@h')
      expect(r.hits).toEqual({ 'url-password': 1 })
      expect(r.text === 'https://u:' + marker + '@h').toBe(true)
    }
  })
  // This test pins a disclosed over-hide (a port read as a password above the bound) as intended fail-closed behaviour.
  test('a port followed by a path with more than the bound of colons before the at-sign is hidden; with exactly the bound it stays visible', { timeoutMs: 20000 }, () => {
    const atBound = 'b://u:8080/' + 'a:'.repeat(BOUND) + '@h'
    expect(bounded(atBound).same).toBe(true)
    const over = bounded('b://u:8080/' + 'a:'.repeat(BOUND + 1) + '@h')
    expect(over.hidden).toBe(true)
    expect(over.text === 'b://u:' + marker + '@h').toBe(true)
  })
  test('a user part with more than the bound of markers makes the same port shape hidden; with exactly the bound it stays visible', { timeoutMs: 20000 }, () => {
    const user = (n: number) => mark('aws-access-key').repeat(n)
    expect(bounded('b://' + user(BOUND) + ':8080/p@h').same).toBe(true)
    const over = bounded('b://' + user(BOUND + 1) + ':8080/p@h')
    expect(over.hidden).toBe(true)
    expect(over.text === 'b://' + user(BOUND + 1) + ':' + marker + '@h').toBe(true)
  })
  // WHY (TRDD-HF7GNHNF): the over-bound branch once hid a region without the PLACEHOLDER and marker-only check the regex path applies, so redact() on its own
  // output (the region was already one marker) counted a phantom url-password hit and a placeholder password was hidden only above the bound.
  test('above the bound, redact() on its own output returns the same text and counts no hit', { timeoutMs: 30000 }, () => {
    const user = (n: number) => mark('aws-access-key').repeat(n)
    for (const url of ['b://u:8080/' + 'a:'.repeat(BOUND + 1) + '@h', 'b://' + user(BOUND + 1) + ':8080/p@h', 'https://u:' + 'aB3:'.repeat(512 * 1024) + '@h']) {
      const once = redact(url)
      expect(countOf(once.hits)).toBeGreaterThan(0)
      const twice = redact(once.text)
      expect(twice.text === once.text).toBe(true)
      expect(countOf(twice.hits)).toBe(0)
    }
  })
  test('above the bound, a placeholder or marker-only password stays visible with no hit, as it does below the bound', { timeoutMs: 20000 }, () => {
    const user = mark('aws-access-key').repeat(BOUND + 1)
    for (const password of ['x', '${DB_PASS}', mark('aws-access-key')]) {
      const url = 'b://' + user + ':' + password + '@h'
      const r = redact(url)
      expect(r.text === url).toBe(true)
      expect(countOf(r.hits)).toBe(0)
    }
  })

  // WHY (TRDD-HF7GNHNF): the b3363706 tests reach above the bound only through the marker count, so this pins the colon-count route.
  test('above the bound by colon count, a placeholder password stays visible with no hit, as it does at the bound', { timeoutMs: 20000 }, () => {
    for (const n of [BOUND, BOUND + 1]) {
      const url = 'b://u:$(' + ':'.repeat(n) + ')@h'
      const r = redact(url)
      expect(r.text === url).toBe(true)
      expect(countOf(r.hits)).toBe(0)
    }
  })

  test('a password of 2 MB made mostly of colons and ending at the at-sign is hidden', { timeoutMs: 30000 }, () => {
    const r = redact('https://u:' + 'aB3:'.repeat(512 * 1024) + '@h')
    expect(r.hits).toEqual({ 'url-password': 1 })
    expect(r.text === 'https://u:' + marker + '@h').toBe(true)
  })
  test('a long colon-dense run is not hidden across a Unicode line separator, a no-break space or an ideographic space', { timeoutMs: 20000 }, () => {
    for (const space of ['\u2028', '\u00a0', '\u3000']) {
      const url = 'b://u:' + 'a:'.repeat(BOUND + 10) + space + 'a:'.repeat(10) + '@h'
      const r = bounded(url)
      expect(r.same).toBe(true)
      expect(r.hidden).toBe(false)
    }
  })
  test('above the bound the guard reads the scheme as the regex does: 1://, _a:// and .:// are left alone, -https://, foo.https:// and a1:// are hidden', { timeoutMs: 20000 }, () => {
    const rest = 'u:' + 'a:'.repeat(BOUND + 1) + '@h'
    for (const head of ['1://', '_a://', '.://', '1a://']) expect(bounded(head + rest).same).toBe(true)
    for (const head of ['-https://', 'foo.https://', 'a1://', '(https://', '1-a://']) {
      const r = bounded(head + rest)
      expect(r.hidden).toBe(true)
      expect(r.text === head + 'u:' + marker + '@h').toBe(true)
    }
  })
  // WHY the best of 5 and not the median of 5: measured under claude plugin test at load 125, the median of 5 broke the ratio rule in 3 of 6 repeats
  // on this shape (for example 0.90 -> 13.06 ms, ratio 14.6) while the best of 5 stayed between 6.9 and 10.5 on all 6 (a ratio near 8 is linear);
  // a loaded machine inflates single runs, and the minimum is the run it inflated least. The previous regex fails this test (a run took 3.4 s).
  test('a colon-dense tail with no at-sign takes under 12 times as long at 8 times the size (or under 2 ms)', { timeoutMs: 60000 }, () => {
    const dense = (reps: number) => 'b://u:1?' + 'a:'.repeat(reps) + ' '
    const small = bestOf(dense(16384))
    const big = bestOf(dense(131072))
    expect(linear(small.ms, big.ms)).toBe(true)
    expect(big.done.text === dense(131072)).toBe(true)
    expect(big.done.hits['url-password']).toBeUndefined()
  })
})
// WHY these tests exist (TRDD-AGOEWF2E): under claude plugin test the escape loop of a plain JSON value returned no match from 589,823 iterations, so a secret-named
// value with 600,000 escapes was not hidden. The loop is bounded to JSON_ESCAPE_BOUND pairs and a linear pass hides every longer value of a secret-named key, whole,
// without looksSecret or the STRONG_NAME gate (fail closed). Values are built from mixed escape pairs and a random lead, so looksSecret accepts them below the bound
// and the exact outputs below pin the pass, not a coincidence. The opening brace keeps the line-assignment rule out. No test asserts a timing.
describe('a plain JSON value with more than JSON_ESCAPE_BOUND escape pairs is hidden whole', () => {
  const BOUND = JSON_ESCAPE_BOUND
  const UNIT = ['aB3\\n', 'cD4\\t', 'eF5\\\\', 'gH6\\"', 'iJ7\\/']
  // `n` escape pairs of five mixed kinds, each after three ordinary characters.
  const escapes = (n: number) => UNIT.join('').repeat(Math.floor(n / UNIT.length)) + UNIT.slice(0, n % UNIT.length).join('')
  const M = mark('assignment')
  test('a value with 600,000 escape pairs is hidden with exactly one assignment hit', { timeoutMs: 60000 }, () => {
    const r = redact(j('{"api_key": "', fake(24), escapes(600000), '"}'))
    expect(r.hits).toEqual({ assignment: 1 })
    expect(r.text === j('{"api_key": "', M, '"}')).toBe(true)
  })
  test('with exactly the bound of escape pairs and with one more, the value is hidden with one hit each', { timeoutMs: 60000 }, () => {
    for (const n of [BOUND, BOUND + 1]) {
      const r = redact(j('{"api_key": "', fake(24), escapes(n), '"}'))
      expect(r.hits).toEqual({ assignment: 1 })
      expect(r.text === j('{"api_key": "', M, '"}')).toBe(true)
    }
  })
  test('a value over the bound under a name that is not a secret name is left unchanged', { timeoutMs: 60000 }, () => {
    const input = j('{"note": "', fake(24), escapes(600000), '"}')
    const r = redact(input)
    expect(countOf(r.hits)).toBe(0)
    expect(r.text === input).toBe(true)
  })
  test('redact() on the output of a hidden over-bound value, closed or cut off, changes nothing and counts no hit', { timeoutMs: 60000 }, () => {
    for (const tail of ['"}', '\\\\\\']) {
      const once = redact(j('{"api_key": "', fake(24), escapes(600000), tail))
      expect(once.hits).toEqual({ assignment: 1 })
      const twice = redact(once.text)
      expect(countOf(twice.hits)).toBe(0)
      expect(twice.text === once.text).toBe(true)
    }
  })
  test('a value over the bound cut off at the end of its line, ending in an odd run of 3 or 5 backslashes, is hidden to the line end and keeps exactly one backslash', { timeoutMs: 60000 }, () => {
    // An odd run is some escaped pairs and a lone backslash followed by the line end, which cannot pair and is kept as the `end` (what the `\\*$` of JSON_PLAIN keeps).
    for (const n of [BOUND + 1, 600000]) {
      for (const run of ['\\\\\\', '\\\\\\\\\\']) {
        const r = redact(j('{"api_key": "', fake(24), escapes(n), run, '\n{"x": 1}'))
        expect(r.hits).toEqual({ assignment: 1 })
        expect(r.text === j('{"api_key": "', M, '\\', '\n{"x": 1}')).toBe(true)
      }
    }
  })
  test('on one line, a non-secret pair over the bound is left as it is and the secret-named pair after it is hidden', { timeoutMs: 60000 }, () => {
    const first = j(fake(24), escapes(BOUND + 1))
    const r = redact(j('{"note": "', first, '", "api_key": "', fake(24), escapes(BOUND + 1), '"}'))
    expect(r.hits).toEqual({ assignment: 1 })
    expect(r.text === j('{"note": "', first, '", "api_key": "', M, '"}')).toBe(true)
  })
  test('more than the bound of escaped backslashes cut off at the end of the line are hidden whole, not as a prefix with the rest of the backslashes left visible', { timeoutMs: 60000 }, () => {
    // The bounded regex alone would claim the first BOUND pairs as the value and the remaining backslashes as its end; the pass runs first and takes all of it.
    const r = redact(j('{"api_key": "', fake(24), '\\\\'.repeat(BOUND + 5000), '\n{"x": 1}'))
    expect(r.hits).toEqual({ assignment: 1 })
    expect(r.text === j('{"api_key": "', M, '\n{"x": 1}')).toBe(true)
  })
  test('a value with no closing quote: exactly the bound of escapes is hidden by the regex and one more by the pass, with the same exact output', { timeoutMs: 60000 }, () => {
    for (const n of [BOUND, BOUND + 1]) {
      const r = redact(j('{"api_key": "', fake(24), escapes(n), '\n{"x": 1}'))
      expect(r.hits).toEqual({ assignment: 1 })
      expect(r.text === j('{"api_key": "', M, '\n{"x": 1}')).toBe(true)
    }
  })
  test('the same over-bound value written unquoted elsewhere in the text is hidden there too, and counted once', { timeoutMs: 60000 }, () => {
    const value = j(fake(24), escapes(600000))
    const r = redact(j('{"api_key": "', value, '"}\ncopy=', value))
    expect(r.hits).toEqual({ assignment: 1 })
    expect(r.text === j('{"api_key": "', M, '"}\ncopy=', M)).toBe(true)
  })
  test('an escaped pair inside an over-bound value is hidden first and counted, then the whole value is hidden: two hits, one marker left', { timeoutMs: 60000 }, () => {
    const inner = j('\\"token\\":\\"', fake(32), '\\"')
    const r = redact(j('{"api_key": "', fake(24), escapes(BOUND + 10), inner, escapes(10), '"}'))
    expect(r.hits).toEqual({ assignment: 2 })
    expect(r.text === j('{"api_key": "', M, '"}')).toBe(true)
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

describe('Google OAuth client secrets, access tokens and refresh tokens are hidden with no name before them', () => {
  // Fixtures are built at run time: no whole fake token sits in this file.
  const clientSecret = j('GOC', 'SPX-', 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9v')
  const accessToken = j('ya', '29.', 'a0AfH6SMBx3Zq9LwT7kE2mN5pR8vY1cD4g')
  const refreshToken = j('1/', '/0', 'gDAbC3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7')
  const tokens: Array<[string, string]> = [
    ['google-oauth-client-secret', clientSecret],
    ['google-oauth-access-token', accessToken],
    ['google-oauth-refresh-token', refreshToken],
  ]

  for (const [kind, secret] of tokens) {
    test(`${kind}: a token alone is one marker, counted once`, () => {
      const done = redact(`see ${secret} end`)
      expect(done.text).toBe(`see ${mark(kind)} end`)
      expect(done.hits).toEqual({ [kind]: 1 })
    })
    test(`${kind}: a JSON value under a neutral key and in an array is hidden`, () => {
      const asValue = redact(JSON.stringify({ v: secret }))
      expect(asValue.text).toBe(`{"v":"${mark(kind)}"}`)
      expect(asValue.hits).toEqual({ [kind]: 1 })
      const inArray = redact(JSON.stringify([secret]))
      expect(inArray.text).toBe(`["${mark(kind)}"]`)
      expect(inArray.hits).toEqual({ [kind]: 1 })
    })
  }

  test('an access token after Authorization: Bearer is a google-oauth-access-token, not a bearer-token', () => {
    const done = redact(`Authorization: Bearer ${accessToken}`)
    expect(done.text).not.toContain(accessToken)
    expect(done.hits['google-oauth-access-token']).toBe(1)
    expect(done.hits['bearer-token']).toBeUndefined()
  })

  test('a client secret whose 28-character tail ends in - is hidden whole', () => {
    const done = redact(`x ${j('GOC', 'SPX-', 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9', '-')} y`)
    expect(done.text).toBe(`x ${mark('google-oauth-client-secret')} y`)
  })

  test('a client secret with a 36-character tail is hidden whole, no character of it left', () => {
    const done = redact(`x ${j('GOC', 'SPX-', 'abcdefghijklmnopqrstuvwxyz1234567890')} y`)
    expect(done.text).toBe(`x ${mark('google-oauth-client-secret')} y`)
  })

  const stayVisible: Array<[string, string]> = [
    ['GOCSPX- plus a 5-character tail', j('GOC', 'SPX-', 'short')],
    ['GOCSPX- plus 19 characters', j('GOC', 'SPX-', 'aB3dE5fG7hJ9kL1mN3p')],
    ['ya29. plus 19 characters', j('ya', '29.', 'a0AfH6SMBx3Zq9LwT7k')],
    ['1//0 plus 40 characters after a slash (/tmp/1//0...)', j('/tmp/1/', '/0', 'gDAbC3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5b')],
    ['1//0 plus 40 characters after a word character (a1//0...)', j('a1/', '/0', 'gDAbC3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5b')],
  ]
  for (const [name, line] of stayVisible) test(`stays visible: ${name}`, () => expect(redact(line).text).toBe(line))

  test('a base64 data URI with /1//0 and 44 characters is left as it is', () => {
    const line = j('data:image/png;base64,', 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk', '/1/', '/0', 'gDAbC3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7dE')
    expect(redact(line).text).toBe(line)
  })

  test('a base64 data URI with +1//0 and 44 url-safe characters is left as it is', () => {
    const line = j('data:image/png;base64,', 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk', '+1/', '/0', 'gDAbC3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7dE')
    expect(redact(line).text).toBe(line)
  })

  test('an AWS SessionToken with +1//0 and 40 or more alphanumerics inside is hidden whole as a session token', () => {
    const value = j('dGhpcy9pcytz/b21lK2Jhc2U2NHZh/bHVl', '+1/', '/0', 'gDAbC3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5bC7dE', '/Zm9v+YmFyYmF6cXV4/Y29ydGdyYXVsdAZm9v')
    expect(value.length).toBe(120)
    const done = redact(`"SessionToken":"${value}"`)
    expect(done.text).not.toContain(value)
    expect(done.hits['aws-session-token']).toBe(1)
    expect(done.hits['google-oauth-refresh-token']).toBeUndefined()
  })

  test('a service-account JSON with an escaped \\n has its private key body hidden', () => {
    const body = 'MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQC7'
    const json = `{"type":"service_account","private_key":"${j('-----BEGIN ', 'PRIVATE KEY-----')}\\n${body}\\n${j('-----END ', 'PRIVATE KEY-----')}\\n"}`
    expect(redact(json).text).not.toContain(body)
  })

  // Pins that no part of the tail is visible on either path: today the token rule hides it before the assignment pass, so text after the token such as .x stays visible; without the token rule the assignment rule hides the whole value.
  test('client_secret=GOCSPX- plus 20 characters has the 20-character tail hidden', () => {
    const tail = 'aB3dE5fG7hJ9kL1mN3pQ'
    expect(redact(`client_secret=${j('GOC', 'SPX-', tail)}.x`).text).not.toContain(tail)
  })
})

// A deterministic hex body for the DigitalOcean and GitLab families. Pure JS (no imports: the mod loader refuses node: imports), so no whole fake token sits in this file.
const HEXDIGITS = '0123456789abcdef'
const hex = (n: number, seed: number): string => {
  let state = seed
  let out = ''
  for (let i = 0; i < n; i++) {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0
    out += HEXDIGITS[state >>> 28]
  }
  return out
}

describe('DigitalOcean personal access, OAuth and refresh tokens are hidden with no name before them', () => {
  // Fixtures are built at run time: no whole fake token sits in this file.
  const families: Array<[string, string, number]> = [
    ['digitalocean-pat', j('do', 'p_', 'v1_'), 11],
    ['digitalocean-oauth-token', j('do', 'o_', 'v1_'), 22],
    ['digitalocean-refresh-token', j('do', 'r_', 'v1_'), 33],
  ]

  for (const [kind, prefix, seed] of families) {
    const M = mark(kind)
    const body = hex(64, seed)
    const token = j(prefix, body)
    const only = { [kind]: 1 }

    test(`${kind}: a token alone on a line is one marker, counted once`, () => {
      const done = redact(`before\n${token}\nafter`)
      expect(done.text).toBe(`before\n${M}\nafter`)
      expect(done.hits).toEqual(only)
    })

    test(`${kind}: hidden in an assignment, a JSON string, right after a literal backslash-n inside a JSON string, and in a URL query`, () => {
      const cases: Array<[string, string]> = [
        [`DO_TOKEN=${token}`, `DO_TOKEN=${M}`],
        [`{"token":"${token}"}`, `{"token":"${M}"}`],
        // A neutral key keeps this case about the DigitalOcean rule alone; the same escape under a secret-named key is not tested here.
        [`{"msg":"line one\\n${token}"}`, `{"msg":"line one\\n${M}"}`],
        [`https://api.example.com/v2/account?access_token=${token}&x=1`, `https://api.example.com/v2/account?access_token=${M}&x=1`],
      ]
      for (const [input, expected] of cases) {
        const done = redact(input)
        expect(done.text).toBe(expected)
        expect(done.hits).toEqual(only)
      }
    })

    test(`${kind}: an upper-case body is hidden`, () => {
      const done = redact(`see ${j(prefix, body.toUpperCase())} end`)
      expect(done.text).toBe(`see ${M} end`)
      expect(done.hits).toEqual(only)
    })

    test(`${kind}: an upper-case prefix is hidden`, () => {
      const done = redact(`see ${j(prefix.toUpperCase(), body)} end`)
      expect(done.text).toBe(`see ${M} end`)
      expect(done.hits).toEqual(only)
    })

    test(`${kind}: a 70-hex body is one marker, no hex left`, () => {
      const done = redact(`x ${j(prefix, hex(70, seed))} y`)
      expect(done.text).toBe(`x ${M} y`)
      expect(done.hits).toEqual(only)
    })

    // Pins the {64,} choice: the rule tightened to {64} leaves the last four characters visible and fails here.
    test(`${kind}: 64 hex followed by 9abc is one marker, the whole run is hidden`, () => {
      const done = redact(`x ${j(prefix, body, '9abc')} y`)
      expect(done.text).toBe(`x ${M} y`)
      expect(done.hits).toEqual(only)
    })

    test(`${kind}: the text after the token (Zq9, a double quote, &x=1, a space and a word) is kept as it is`, () => {
      for (const after of ['Zq9', '"', '&x=1', ' then']) {
        const done = redact(`see ${token}${after} end`)
        expect(done.text).toBe(`see ${M}${after} end`)
        expect(done.hits).toEqual(only)
      }
    })
  }

  const stayVisible = [
    'dop_v1_<token>',
    'dop_v1_...',
    'dop_v1_xxxxxxxx',
    'DigitalOcean tokens start with dop_v1_ and are long.',
  ]
  for (const line of stayVisible) {
    test(`stays visible: ${line}`, () => {
      const done = redact(line)
      expect(done.text).toBe(line)
      expect(done.hits).toEqual({})
    })
  }
})

describe('GitLab prefixed tokens are hidden with no name before them', () => {
  // Fixtures are built at run time with j(): no prefix and body sit together in this file. The bodies are slices of a fixed mixed-case alphanumeric run;
  // the bodies with _ and - are built by hand (fake() in known-misses.test.ts has neither).
  const BASE = A36 + A36
  const slice = (n: number, from: number): string => BASE.slice(from, from + n)
  // [kind, name in the test titles, prefix, body]. gitlab-runner-token has two prefixes, so it has two rows.
  const families: Array<[string, string, string, string]> = [
    ['gitlab-pat', 'gitlab-pat', j('gl', 'pat-'), slice(20, 0)],
    ['gitlab-oauth-app-secret', 'gitlab-oauth-app-secret', j('gl', 'oas-'), slice(64, 2)],
    ['gitlab-deploy-token', 'gitlab-deploy-token', j('gl', 'dt-'), slice(20, 4)],
    ['gitlab-runner-token', 'gitlab-runner-token (glrt-)', j('gl', 'rt-'), slice(20, 6)],
    ['gitlab-runner-token', 'gitlab-runner-token (glrtr-)', j('gl', 'rtr-'), slice(20, 8)],
    ['gitlab-runner-registration-token', 'gitlab-runner-registration-token', j('GR', '1348941'), slice(20, 10)],
    ['gitlab-cicd-job-token', 'gitlab-cicd-job-token', j('gl', 'cbt-'), j('k7_', slice(20, 12))],
    ['gitlab-trigger-token', 'gitlab-trigger-token', j('gl', 'ptt-'), slice(40, 1)],
    ['gitlab-feed-token', 'gitlab-feed-token', j('gl', 'ft-'), slice(20, 14)],
    ['gitlab-incoming-mail-token', 'gitlab-incoming-mail-token', j('gl', 'imt-'), slice(25, 3)],
    ['gitlab-agent-token', 'gitlab-agent-token', j('gl', 'agent-'), slice(50, 5)],
    ['gitlab-workspace-token', 'gitlab-workspace-token', j('gl', 'wt-'), slice(20, 16)],
    ['gitlab-scim-token', 'gitlab-scim-token', j('gl', 'soat-'), slice(20, 18)],
    ['gitlab-feature-flag-client-token', 'gitlab-feature-flag-client-token', j('gl', 'ffct-'), slice(20, 20)],
  ]
  const patPrefix = families[0][2]
  const patToken = j(patPrefix, families[0][3])
  const runnerPrefix = families[3][2]
  const runnerToken = j(runnerPrefix, families[3][3])
  const only = (kind: string): Record<string, number> => ({ [kind]: 1 })

  for (const [kind, name, prefix, tokenBody] of families) {
    const M = mark(kind)
    const token = j(prefix, tokenBody)
    // The other letter case of the prefix: lower case for GR, upper case for the rest.
    const flipped = prefix === prefix.toUpperCase() ? prefix.toLowerCase() : prefix.toUpperCase()

    test(`${name}: a token alone on a line is one marker, counted once`, () => {
      const done = redact(`before\n${token}\nafter`)
      expect(done.text).toBe(`before\n${M}\nafter`)
      expect(done.hits).toEqual(only(kind))
    })

    test(`${name}: hidden in a JSON string, right after a literal backslash-n inside a JSON string, and in a URL query (neutral names)`, () => {
      const cases: Array<[string, string]> = [
        [`{"v":"${token}"}`, `{"v":"${M}"}`],
        [`{"msg":"line one\\n${token}"}`, `{"msg":"line one\\n${M}"}`],
        [`https://api.example.com/v2/items?q=${token}&x=1`, `https://api.example.com/v2/items?q=${M}&x=1`],
      ]
      for (const [input, expected] of cases) {
        const done = redact(input)
        expect(done.text).toBe(expected)
        expect(done.hits).toEqual(only(kind))
      }
    })

    // The name says secret, so the assignment pass would hide this value even without the rule: this pins the kind of the marker (the rule runs first), not detection.
    test(`${name}: label-only, GITLAB_TOKEN= names a secret, the token is one marker of its own kind`, () => {
      const done = redact(`GITLAB_TOKEN=${token}`)
      expect(done.text).toBe(`GITLAB_TOKEN=${M}`)
      expect(done.hits).toEqual(only(kind))
    })

    test(`${name}: a 19-character body stays visible, a 20-character body with no digit and no upper-case letter is hidden`, () => {
      const short = j(prefix, 'abcdefghijklmnopqr7')
      const edge = j(prefix, 'abcdefghijklmnopqrst')
      const visible = redact(`see ${short} end`)
      expect(visible.text).toBe(`see ${short} end`)
      expect(visible.hits).toEqual({})
      const hidden = redact(`see ${edge} end`)
      expect(hidden.text).toBe(`see ${M} end`)
      expect(hidden.hits).toEqual(only(kind))
    })

    test(`${name}: an upper-case prefix (lower-case for GR) is hidden`, () => {
      const done = redact(`see ${j(flipped, tokenBody)} end`)
      expect(done.text).toBe(`see ${M} end`)
      expect(done.hits).toEqual(only(kind))
    })

    test(`${name}: a body with - and _ inside is hidden whole, and so are - and _ glued to its end`, () => {
      const inside = j(prefix, tokenBody.slice(0, 7), '-', tokenBody.slice(7, 12), '_', tokenBody.slice(12))
      const a = redact(`see ${inside} end`)
      expect(a.text).toBe(`see ${M} end`)
      expect(a.hits).toEqual(only(kind))
      const b = redact(`see ${token}_-x end`)
      expect(b.text).toBe(`see ${M} end`)
      expect(b.hits).toEqual(only(kind))
    })

    test(`${name}: the text after the token (a double quote, &x=1, a space, a space and a word) is kept as it is`, () => {
      for (const after of ['"', '&x=1', ' ', ' then']) {
        const done = redact(`see ${token}${after} end`)
        expect(done.text).toBe(`see ${M}${after} end`)
        expect(done.hits).toEqual(only(kind))
      }
    })
  }

  test('gitlab-trigger-token: a real hex-40 body is hidden alone, in a JSON string and after a literal backslash-n', () => {
    const body = hex(40, 44)
    expect(/[0-9]/.test(body)).toBe(true)
    const token = j('gl', 'ptt-', body)
    const M = mark('gitlab-trigger-token')
    for (const [input, expected] of [
      [`see ${token} end`, `see ${M} end`],
      [`{"v":"${token}"}`, `{"v":"${M}"}`],
      [`{"msg":"line one\\n${token}"}`, `{"msg":"line one\\n${M}"}`],
    ]) {
      const done = redact(input)
      expect(done.text).toBe(expected)
      expect(done.hits).toEqual(only('gitlab-trigger-token'))
    }
  })

  test('gitlab-incoming-mail-token: -issue glued to a 25-character body is hidden with it', () => {
    const done = redact(`see ${j('gl', 'imt-', slice(25, 3))}-issue end`)
    expect(done.text).toBe(`see ${mark('gitlab-incoming-mail-token')} end`)
    expect(done.hits).toEqual(only('gitlab-incoming-mail-token'))
  })

  describe('the routable tail', () => {
    // A routable token: a payload of 27 or more characters, a dot and 9 lower-case letters or digits. The payload has an underscore inside.
    const payload = j(slice(13, 0), '_', slice(13, 20))
    const tail = 'q7f2k9x4m'

    test('a routable glpat- token (27-character payload, dot, 9 characters) is one marker', () => {
      expect(payload.length).toBe(27)
      const done = redact(`see ${j(patPrefix, payload, '.', tail)} end`)
      expect(done.text).toBe(`see ${mark('gitlab-pat')} end`)
      expect(done.hits).toEqual(only('gitlab-pat'))
    })

    test('a routable glrt-t1_ token is one marker, and so is a glrtr- token with the same tail', () => {
      for (const prefix of [runnerPrefix, j('gl', 'rtr-')]) {
        const done = redact(`see ${j(prefix, 't1_', payload, '.', tail)} end`)
        expect(done.text).toBe(`see ${mark('gitlab-runner-token')} end`)
        expect(done.hits).toEqual(only('gitlab-runner-token'))
      }
    })

    // Both tailed kinds. The tail is a dot and exactly 9 letters or digits (either case) followed by a non-alphanumeric.
    for (const [kind, token] of [['gitlab-pat', patToken], ['gitlab-runner-token', runnerToken]]) {
      const M = mark(kind)
      test(`${kind}: a dot and 10 or more characters after the token stay visible, so does .toLowerCase, and a dot and exactly 9 letters or digits of either case before a parenthesis is hidden with it`, () => {
        for (const [after, expected] of [
          ['.abcdefghij', `${M}.abcdefghij`],
          ['.toLowerCase()', `${M}.toLowerCase()`],
          ['.substring(x)', `${M}(x)`],
          ['.abcdeFGhi(x)', `${M}(x)`],
        ]) {
          const done = redact(`${token}${after}`)
          expect(done.text).toBe(expected)
          expect(done.hits).toEqual(only(kind))
        }
      })
    }

    test('gitlab-oauth-app-secret has no tail: a dot and 9 characters after the token stay visible', () => {
      const done = redact(`${j('gl', 'oas-', slice(64, 2))}.substring(x)`)
      expect(done.text).toBe(`${mark('gitlab-oauth-app-secret')}.substring(x)`)
      expect(done.hits).toEqual(only('gitlab-oauth-app-secret'))
    })
  })

  describe('secrets in URLs and headers', () => {
    test('PRIVATE-TOKEN: <pat> (label-only: the name says secret) has the token hidden as a gitlab-pat', () => {
      const done = redact(`PRIVATE-TOKEN: ${patToken}`)
      expect(done.text).toBe(`PRIVATE-TOKEN: ${mark('gitlab-pat')}`)
      expect(done.hits).toEqual(only('gitlab-pat'))
    })

    test('https://oauth2:<pat>@gitlab.example keeps the user and the host, the token has its GitLab kind', () => {
      const done = redact(`git clone https://oauth2:${patToken}@gitlab.example/g/p.git`)
      expect(done.text).toBe(`git clone https://oauth2:${mark('gitlab-pat')}@gitlab.example/g/p.git`)
      expect(done.hits).toEqual(only('gitlab-pat'))
    })

    test('https://gitlab-ci-token:<job token>@gitlab.example keeps the user and the host, the token has its GitLab kind', () => {
      const done = redact(`git clone https://gitlab-ci-token:${j('gl', 'cbt-', 'k7_', slice(20, 12))}@gitlab.example/g/p.git`)
      expect(done.text).toBe(`git clone https://gitlab-ci-token:${mark('gitlab-cicd-job-token')}@gitlab.example/g/p.git`)
      expect(done.hits).toEqual(only('gitlab-cicd-job-token'))
    })
  })

  // Visible by decision: prose and placeholders that carry a prefix without a body of 20 or more characters.
  // The titles describe the case and never carry the text, so no token-shaped name is printed.
  const stayVisible: Array<[string, string]> = [
    // A year makes the name look like a token, but the body is 15 characters, under the 20 of the rule.
    ['a kebab name with a year whose body is 15 characters', j('gl', 'pat-', 'expiry-job-2024')],
    ['the prefix in a sentence', `GitLab tokens start with ${j('gl', 'pat-')} and are long.`],
    ['the prefix followed by a <token> placeholder', j('gl', 'pat-', '<token>')],
    ['the prefix followed by three dots', j('gl', 'pat-', '...')],
  ]
  for (const [description, line] of stayVisible) {
    test(`stays visible: ${description}`, () => {
      const done = redact(line)
      expect(done.text).toBe(line)
      expect(done.hits).toEqual({})
    })
  }

  // Hidden by decision, security first (owner, 2026-11-05): a prefix followed by 20 or more characters of the body class is hidden whatever its letter case,
  // even when it reads like a name or a placeholder, because the alphabet of each GitLab token kind is unverified.
  const hiddenByDecision: Array<[string, string]> = [
    ['20 upper-case X', j('gl', 'pat-', 'X'.repeat(20))],
    ['20 lower-case x', j('gl', 'pat-', 'x'.repeat(20))],
    ['an all-lower-case kebab name of 23 characters', j('gl', 'pat-', 'expiry-notification-job')],
    ['a kebab name with a year whose body is 28 characters', j('gl', 'pat-', 'expiry-notification-job-2024')],
  ]
  for (const [description, line] of hiddenByDecision) {
    test(`hidden by decision: ${description}`, () => {
      const done = redact(`see ${line} end`)
      expect(done.text).toBe(`see ${mark('gitlab-pat')} end`)
      expect(done.hits).toEqual(only('gitlab-pat'))
    })
  }
})

describe('the GitLab session cookie is hidden whole, the cookie name is kept', () => {
  // Moved here from the KNOWN DEFECT test of known-misses.test.ts (TRDD-Q6LPJTPO). The values are built at run time with j(); a Rack session id is 32 hex characters.
  const kind = 'gitlab-session-cookie'
  const only = { [kind]: 1 }
  const M = mark(kind)
  const hex32 = j('e4b7a1c9', 'd2f60385', 'a1b2c3d4', 'e5f60718')
  // Independent of hex32: a copy of the value inside the name would be hidden by the propagation pass.
  const hex64 = j('1a2b3c4d', '5e6f7081', '92a3b4c5', 'd6e7f809', '0f1e2d3c', '4b5a6978', '8796a5b4', 'c3d2e1f0')
  // A cookie cut short in a log, and a cut value of exactly the 16-character floor.
  const cut20 = j('7c3d9e1f', '5a2b8c4d', '6e0f1a2b')
  const cut16 = j('3b9f1d7a', '5c2e8b40')
  const BS = '\\'
  const NAME = '_gitlab_session'

  const hidden: Array<[string, string, string]> = [
    ['a Cookie header, the cookie in the middle', `Cookie: a=1; ${NAME}=${hex32}; b=2`, `Cookie: a=1; ${NAME}=${M}; b=2`],
    ['a Cookie header, the cookie last', `Cookie: a=1; ${NAME}=${hex32}`, `Cookie: a=1; ${NAME}=${M}`],
    ['a Set-Cookie header with attributes', `Set-Cookie: ${NAME}=${hex32}; path=/; secure; HttpOnly`, `Set-Cookie: ${NAME}=${M}; path=/; secure; HttpOnly`],
    ['a curl -b argument in double quotes', `curl -b "${NAME}=${hex32}" https://gitlab.example/api`, `curl -b "${NAME}=${M}" https://gitlab.example/api`],
    ['a curl --cookie argument in single quotes with another cookie', `curl --cookie '${NAME}=${hex32}; x=1' https://gitlab.example/`, `curl --cookie '${NAME}=${M}; x=1' https://gitlab.example/`],
    ['a curl -b argument with no quotes', `curl -b ${NAME}=${hex32} https://gitlab.example/`, `curl -b ${NAME}=${M} https://gitlab.example/`],
    ['an assignment at the start of a line', `${NAME}=${hex32}`, `${NAME}=${M}`],
    ['a JSON pair', `{"${NAME}": "${hex32}", "x": 1}`, `{"${NAME}": "${M}", "x": 1}`],
    ['a JSON pair with no space around the colon', `{"${NAME}":"${hex32}"}`, `{"${NAME}":"${M}"}`],
    ['a JSON pair inside another JSON string (escaped quotes)', `{"cmd":"{${BS}"${NAME}${BS}":${BS}"${hex32}${BS}"}"}`, `{"cmd":"{${BS}"${NAME}${BS}":${BS}"${M}${BS}"}"}`],
    ['a JSON pair stringified twice (three backslashes before each quote)', `${BS}${BS}${BS}"${NAME}${BS}${BS}${BS}":${BS}${BS}${BS}"${hex32}${BS}${BS}${BS}"`, `${BS}${BS}${BS}"${NAME}${BS}${BS}${BS}":${BS}${BS}${BS}"${M}${BS}${BS}${BS}"`],
    ['an upper-case name', `Cookie: ${NAME.toUpperCase()}=${hex32}`, `Cookie: ${NAME.toUpperCase()}=${M}`],
    ['the Geo secondary name (a 64-hex suffix)', `Cookie: ${NAME}_geo_${hex64}=${hex32}`, `Cookie: ${NAME}_geo_${hex64}=${M}`],
    ['a value of 40 characters, whole', `Cookie: ${NAME}=${hex32}abcdef01`, `Cookie: ${NAME}=${M}`],
    ['a value with a cell prefix and hyphens, whole', `Cookie: ${NAME}=cell-12-${hex32}`, `Cookie: ${NAME}=${M}`],
    ['a name right after a literal backslash-n', `line${BS}n${NAME}=${hex32}`, `line${BS}n${NAME}=${M}`],
    ['a value that ends at a literal backslash-n', `${NAME}=${hex32}${BS}nnext`, `${NAME}=${M}${BS}nnext`],
    ['a value whose end is the end of the text', `x ${NAME}=${hex32}`, `x ${NAME}=${M}`],
    // The forms of the 2026-11-05 review.
    ['a Ruby hash pair with =>', `{"${NAME}"=>"${hex32}"}`, `{"${NAME}"=>"${M}"}`],
    ['a Ruby hash pair with spaces around =>', `{"${NAME}" => "${hex32}"}`, `{"${NAME}" => "${M}"}`],
    ['a Python dict pair in single quotes', `{'${NAME}': '${hex32}'}`, `{'${NAME}': '${M}'}`],
    ['a subscript assignment in single quotes', `cookies['${NAME}'] = '${hex32}'`, `cookies['${NAME}'] = '${M}'`],
    ['a subscript assignment in double quotes', `cookies["${NAME}"] = "${hex32}"`, `cookies["${NAME}"] = "${M}"`],
    ['a double-quoted value after =', `${NAME}="${hex32}"`, `${NAME}="${M}"`],
    ['a single-quoted value after =', `${NAME}='${hex32}'`, `${NAME}='${M}'`],
    ['spaces around =', `x ${NAME} = ${hex32} y`, `x ${NAME} = ${M} y`],
    ['a URL-encoded =', `q=${NAME}%3D${hex32}%3Bpath`, `q=${NAME}%3D${M}%3Bpath`],
    ['a URL-encoded = in lower case', `q=${NAME}%3d${hex32}`, `q=${NAME}%3d${M}`],
    ['a fully URL-encoded JSON pair', `q=%22${NAME}%22%3A%22${hex32}%22`, `q=%22${NAME}%22%3A%22${M}%22`],
    ['a HAR pair, name first', `{"name": "${NAME}", "value": "${hex32}"}`, `{"name": "${NAME}", "value": "${M}"}`],
    ['a HAR pair, name first, with no spaces and a field after', `{"name":"${NAME}","value":"${hex32}","path":"/"}`, `{"name":"${NAME}","value":"${M}","path":"/"}`],
    ['a HAR pair, name first, pretty-printed on separate lines', `{\n  "name": "${NAME}",\n  "value": "${hex32}"\n}`, `{\n  "name": "${NAME}",\n  "value": "${M}"\n}`],
    ['a HAR pair, name first, escaped', `{${BS}"name${BS}":${BS}"${NAME}${BS}",${BS}"value${BS}":${BS}"${hex32}${BS}"}`, `{${BS}"name${BS}":${BS}"${NAME}${BS}",${BS}"value${BS}":${BS}"${M}${BS}"}`],
    ['a HAR pair, value first', `{"value": "${hex32}", "name": "${NAME}"}`, `{"value": "${M}", "name": "${NAME}"}`],
    ['a HAR pair, value first, with no spaces', `{"value":"${hex32}","name":"${NAME}","path":"/"}`, `{"value":"${M}","name":"${NAME}","path":"/"}`],
    // Round 3 (TRDD-Q6LPJTPO): unquoted keys, positional calls, a Rails hash, and fields between name and value.
    ['a Puppeteer pair with unquoted keys, name first', `{name: '${NAME}', value: '${hex32}'}`, `{name: '${NAME}', value: '${M}'}`],
    ['a Playwright addCookies call with fields after the value', `await context.addCookies([{ name: '${NAME}', value: '${hex32}', domain: 'gitlab.example', path: '/' }])`, `await context.addCookies([{ name: '${NAME}', value: '${M}', domain: 'gitlab.example', path: '/' }])`],
    ['a Puppeteer pair with unquoted keys, value first', `{value: '${hex32}', name: '${NAME}'}`, `{value: '${M}', name: '${NAME}'}`],
    ['a Go http.Cookie, name first', `http.Cookie{Name: "${NAME}", Value: "${hex32}"}`, `http.Cookie{Name: "${NAME}", Value: "${M}"}`],
    ['a Go http.Cookie, value first', `http.Cookie{Value: "${hex32}", Name: "${NAME}"}`, `http.Cookie{Value: "${M}", Name: "${NAME}"}`],
    ['a set_cookie call, single quotes', `set_cookie('${NAME}', '${hex32}')`, `set_cookie('${NAME}', '${M}')`],
    ['a cookies.set call, double quotes', `cookies.set("${NAME}", "${hex32}")`, `cookies.set("${NAME}", "${M}")`],
    ['a res.cookie call with options after the value', `res.cookie('${NAME}', '${hex32}', { httpOnly: true })`, `res.cookie('${NAME}', '${M}', { httpOnly: true })`],
    ['a positional call with no space after the comma', `set_cookie('${NAME}','${hex32}')`, `set_cookie('${NAME}','${M}')`],
    ['a Rails cookie hash', `cookies[:${NAME}] = { value: '${hex32}' }`, `cookies[:${NAME}] = { value: '${M}' }`],
    ['a Rails cookie hash with options after the value', `cookies[:${NAME}] = { value: '${hex32}', httponly: true }`, `cookies[:${NAME}] = { value: '${M}', httponly: true }`],
    ['a Rails cookie hash with options before the value', `cookies[:${NAME}] = { expires: 1.hour, value: '${hex32}' }`, `cookies[:${NAME}] = { expires: 1.hour, value: '${M}' }`],
    [
      'a Chrome extension export object, pretty-printed (six fields between name and value)',
      `{\n    "domain": "gitlab.example",\n    "hostOnly": true,\n    "name": "${NAME}",\n    "path": "/",\n    "sameSite": "unspecified",\n    "secure": true,\n    "session": false,\n    "storeId": "0",\n    "value": "${hex32}"\n}`,
      `{\n    "domain": "gitlab.example",\n    "hostOnly": true,\n    "name": "${NAME}",\n    "path": "/",\n    "sameSite": "unspecified",\n    "secure": true,\n    "session": false,\n    "storeId": "0",\n    "value": "${M}"\n}`,
    ],
    ['a pair with fields between value and name', `{"value": "${hex32}", "domain": "gitlab.example", "path": "/", "name": "${NAME}"}`, `{"value": "${M}", "domain": "gitlab.example", "path": "/", "name": "${NAME}"}`],
    // The span is 400 characters at most: ` "x": "`, 382 filler characters and `", "` are 393 characters.
    ['a pair with 393 characters between name and value', `{"name": "${NAME}", "x": "${'a'.repeat(382)}", "value": "${hex32}"}`, `{"name": "${NAME}", "x": "${'a'.repeat(382)}", "value": "${M}"}`],
    ['a pair with 393 characters between value and name', `{"value": "${hex32}", "x": "${'a'.repeat(382)}", "name": "${NAME}"}`, `{"value": "${M}", "x": "${'a'.repeat(382)}", "name": "${NAME}"}`],
    ['a YAML pair', `${NAME}: ${hex32}`, `${NAME}: ${M}`],
    ['a Netscape cookie-jar line (name, a tab, value)', `gitlab.example\tFALSE\t/\tTRUE\t0\t${NAME}\t${hex32}`, `gitlab.example\tFALSE\t/\tTRUE\t0\t${NAME}\t${M}`],
    ['a URL query, the text after & kept', `https://gitlab.example/x?${NAME}=${hex32}&next=/x`, `https://gitlab.example/x?${NAME}=${M}&next=/x`],
    ['a comma-joined log line, the text after the comma kept', `a=1,${NAME}=${hex32},b=2`, `a=1,${NAME}=${M},b=2`],
    ['a value cut to 20 characters', `Cookie: ${NAME}=${cut20}`, `Cookie: ${NAME}=${M}`],
    ['a value cut to 16 characters', `Cookie: ${NAME}=${cut16}`, `Cookie: ${NAME}=${M}`],
  ]
  for (const [description, text, expected] of hidden) {
    test(`hidden: ${description}`, () => {
      const done = redact(text)
      expect(done.text).toBe(expected)
      expect(done.hits).toEqual(only)
    })
  }

  test('a copy of the value written elsewhere in the same text is hidden too', () => {
    const done = redact(`Cookie: ${NAME}=${hex32}\nrepeat ${hex32} here`)
    expect(done.text.includes(hex32)).toBe(false)
    // Two hits: the rule hides the first copy and the window pass hides the second one (the window crosses the line break by design, for the YAML form), where hideKnown alone used to hide it uncounted.
    expect(done.hits[kind]).toBe(2)
  })

  test('the 16-character floor: 15 characters stay visible, 16 are hidden', () => {
    const short = redact(`${NAME}=${cut16.slice(1)}`)
    expect(short.text).toBe(`${NAME}=${cut16.slice(1)}`)
    expect(short.hits).toEqual({})
    const edge = redact(`${NAME}=${cut16}`)
    expect(edge.text).toBe(`${NAME}=${M}`)
    expect(edge.hits).toEqual(only)
  })

  // Hidden by decision, security first (owner, 2026-11-05): anything of 16 or more characters after the name is hidden, a placeholder or a code expression too.
  const hiddenByDecision: Array<[string, string, string]> = [
    ['16 lower-case x', `${NAME}=${'x'.repeat(16)}`, `${NAME}=${M}`],
    ['a code expression after =', `${NAME} = fetch_session_value()`, `${NAME} = ${M}`],
    ['a 16-character word after a colon', `${NAME}: abcdefghijklmnop`, `${NAME}: ${M}`],
    // Costs of the positional and field-list shapes, accepted for security (round 3): the next name of a quoted list, and a 15-character value after a doubled separator.
    ['a quoted list of cookie names hides the next name of 16 or more characters', `['${NAME}', 'remember_user_token']`, `['${NAME}', '${M}']`],
    ['a 15-character value after => (the > counts as the 16th)', `${NAME}=>${cut16.slice(1)}`, `${NAME}=${M}`],
    ['a 15-character value after :: (the second colon counts as the 16th)', `${NAME}::${cut16.slice(1)}`, `${NAME}:${M}`],
  ]
  for (const [description, text, expected] of hiddenByDecision) {
    test(`hidden by decision: ${description}`, () => {
      const done = redact(text)
      expect(done.text).toBe(expected)
      expect(done.hits).toEqual(only)
    })
  }

  // Visible by decision: the name without a value, a placeholder, other cookie names. No title carries a value.
  const stayVisible: Array<[string, string]> = [
    ['the name in prose', `The ${NAME} cookie holds the session id.`],
    ['the name with an empty value', `Cookie: a=1; ${NAME}=; b=2`],
    ['the name with a <session> placeholder', `${NAME}=<session>`],
    ['the name with a ${VAR} reference', `${NAME}=\${SESSION}`],
    ['the name with a short value', `${NAME}=abc123`],
    ['the name with a value of 15 characters', `${NAME}=${cut16.slice(1)}`],
    ['the internal write-time key with its number', `${NAME}_last_write_at=1700000000`],
    ['a JSON pair whose value is short', `{"${NAME}": "abc123"}`],
    ['a JSON pair whose value is empty', `{"${NAME}": ""}`],
    ['a Ruby hash pair whose value is short', `{"${NAME}"=>"abc123"}`],
    ['a HAR pair whose value is short, name first', `{"name": "${NAME}", "value": "abc123"}`],
    ['a HAR pair whose value is short, value first', `{"value": "abc123", "name": "${NAME}"}`],
    ['a HAR pair whose value is 15 characters, value first', `{"value": "${cut16.slice(1)}", "name": "${NAME}"}`],
    ['a YAML pair whose value is short', `${NAME}: true`],
    ['the name followed by a colon in prose', `The ${NAME}: see the docs for details.`],
    ['a cookie with a similar name', `Cookie: _gitlab_sess=${hex32}`],
    ['a cookie named session', `Cookie: session=${hex32}`],
    ['a cookie whose name lacks the leading underscore', `Cookie: gitlab_session=${hex32}`],
    ['a HAR pair of another cookie, name first', `{"name": "other_cookie", "value": "${hex32}"}`],
    ['a HAR pair of another cookie, value first', `{"value": "${hex32}", "name": "other_cookie"}`],
    ['the name repeated with no value', NAME.repeat(5)],
    // Round 3 (TRDD-Q6LPJTPO): the value never comes from the next line, and the new field-list and positional shapes need a quoted value.
    ['a YAML map header alone on its line, a long key on the next line', `${NAME}:\nsome_long_key_name_here: 1`],
    ['a log line ending in the name and a colon, the next line starts with a timestamp', `2026-11-05 ${NAME}:\n2026-11-05T10:00:00.123+0100 started`],
    ['a positional call with a short value', `set_cookie('${NAME}', 'abc123')`],
    ['a positional call whose second argument is a variable', `set_cookie('${NAME}', current_session_value)`],
    ['a Rails hash whose value is short', `cookies[:${NAME}] = { value: 'abc123' }`],
    ['a field list whose value is a variable', `{name: '${NAME}', value: current_session_value}`],
    ['a field list of another cookie, name first', `{name: 'other_cookie', path: '/', value: '${hex32}'}`],
    ['a field list of another cookie, value first', `{value: '${hex32}', path: '/', name: 'other_cookie'}`],
    ['a second object after the closing brace, name first', `[{"name": "${NAME}", "path": "/"}, {"name": "other_cookie", "value": "${hex32}"}]`],
    ['a second object before the opening brace, value first', `[{"value": "${hex32}", "name": "other_cookie"}, {"path": "/", "name": "${NAME}"}]`],
  ]
  for (const [description, line] of stayVisible) {
    test(`stays visible: ${description}`, () => {
      const done = redact(line)
      expect(done.text).toBe(line)
      expect(done.hits).toEqual({})
    })
  }
})
describe('the GitLab session cookie value is found by its shape in a window around the name', () => {
  // TRDD-Q6LPJTPO, option B: the old rules read the value from the syntax after the name; this pass hides an optional prefix and exactly 32 lowercase hex characters within 512
  // characters of the name (not past ; { }). The values are built at run time with j(). Hit counts are pinned as measured: a form where an old rule hides the WRONG text first
  // (the key after the name, a default value) counts two hits, one for the wrong text and one for the real value.
  const kind = 'gitlab-session-cookie'
  const M = mark(kind)
  const NAME = '_gitlab_session'
  const hex32 = j('e4b7a1c9', 'd2f60385', 'a1b2c3d4', 'e5f60718')
  const hex32b = j('0a1b2c3d', '4e5f6071', '8293a4b5', 'c6d7e8f9')
  const sha40 = j('1a36494e', '24f084b1', '7d167990', '53515679', 'a1f2b37d')
  const hex64 = j('1a2b3c4d', '5e6f7081', '92a3b4c5', 'd6e7f809', '0f1e2d3c', '4b5a6978', '8796a5b4', 'c3d2e1f0')
  const prefixes = ['', 'cell-3-', 'custom_token-']
  const forms: Array<[string, number, (v: string) => string]> = [
    ['Python keyword arguments', 1, v => `create_cookie(name='${NAME}', value='${v}')`],
    ['a Ruby hash rocket', 1, v => `{ :name => '${NAME}', :value => '${v}' }`],
    ['a compact Rails hash', 1, v => `cookies[:${NAME}]={value:'${v}',httponly:true}`],
    ['a key of 16 or more characters after the name in compact JSON', 2, v => `{"name":"${NAME}","partitionKeyLong":true,"value":"${v}"}`],
    ['a key that ends in value before the real value', 2, v => `{"name": "${NAME}", "defaultvalue": "some-default-text-here", "value": "${v}"}`],
    ['a value nested under the name in JSON', 1, v => `{"${NAME}": {"value": "${v}"}}`],
    ['a value nested under the name in YAML', 1, v => `${NAME}:\n  value: ${v}\n`],
    ['a Ruby symbol in a positional call', 1, v => `cookies.set(:${NAME}, '${v}')`],
    ['a tab before the equals sign', 1, v => `${NAME}\t=${v}`],
    ['a Go raw string', 1, v => 'http.Cookie{Name: "' + NAME + '", Value: `' + v + '`}'],
    ['a URL-encoded equals sign', 1, v => `q=${NAME}%3D${v}%3Bx`],
    ['a URL-encoded JSON pair', 1, v => `q=%22${NAME}%22%3A%22${v}%22`],
  ]
  for (const prefix of prefixes) {
    for (const [description, count, build] of forms) {
      test(`hidden: ${description}, prefix '${prefix}'`, () => {
        const done = redact(build(prefix + hex32))
        expect(done.text.includes(hex32)).toBe(false)
        expect(prefix === '' || !done.text.includes(prefix)).toBe(true)
        expect(done.text.includes(M)).toBe(true)
        expect(done.hits).toEqual({ [kind]: count })
      })
    }
  }

  test('a value between two names is hidden once and counted once', () => {
    const done = redact(`${NAME}=short ${hex32} ${NAME}=short`)
    expect(done.text).toBe(`${NAME}=short ${M} ${NAME}=short`)
    expect(done.hits).toEqual({ [kind]: 1 })
  })

  test('a value before the name and a value after it are both hidden', () => {
    const done = redact(`id ${hex32} then ${NAME} cookie, id ${hex32b}`)
    expect(done.text).toBe(`id ${M} then ${NAME} cookie, id ${M}`)
    expect(done.hits).toEqual({ [kind]: 2 })
  })

  test('a provider token near the name keeps its own kind', () => {
    // The token holds a 32-hex run that this pass would also take; the provider rules run first, so the pass sees a marker.
    const token = j('glpat-', hex32b)
    const done = redact(`token ${token}\n${NAME} cookie`)
    expect(done.text).toBe(`token ${mark('gitlab-pat')}\n${NAME} cookie`)
    expect(done.hits).toEqual({ 'gitlab-pat': 1 })
  })

  // Stay visible. A 40-hex commit id and a 64-hex Geo suffix are longer than a value; an upper-case run is not a Rack id (disclosed in KNOWN-MISSES.md gitlab-session-cookie-uppercase-hex).
  const stayVisible: Array<[string, string]> = [
    ['a 40-hex commit id after the name', `The ${NAME} cookie was renewed in ${sha40}.`],
    ['a 40-hex commit id before the name', `Fixed in ${sha40}: the ${NAME} cookie is renewed.`],
    ['the 64-hex Geo suffix of the name', `Cookie: ${NAME}_geo_${hex64}=short`],
    ['an upper-case 32-hex run after the name', `The ${NAME} cookie was ${hex32.toUpperCase()}.`],
    ['a 32-hex run after a semicolon', `Cookie: ${NAME}=short; x=${hex32}`],
    ['a 32-hex run before a semicolon that precedes the name', `x=${hex32}; ${NAME}=short`],
    ['a 32-hex run after a closing brace', `{"${NAME}": "short"} ${hex32}`],
    ['a 32-hex run before an opening brace', `${hex32} {"${NAME}": "short"}`],
    ['a 32-hex run 513 characters after the name', `The ${NAME}${' '.repeat(513)}${hex32}`],
    ['a 32-hex run 513 characters before the name', `${hex32}${' '.repeat(513)}${NAME} cookie`],
    ['a 32-hex run with no name', `etag ${hex32} md5 ${hex32b}`],
  ]
  // Pinned on HEAD as well: these pass before this pass existed, so they fail only if the pass crosses a bound it must not cross.
  for (const [description, line] of stayVisible) {
    test(`stays visible: ${description}`, () => {
      const done = redact(line)
      expect(done.text).toBe(line)
      expect(done.hits).toEqual({})
    })
  }

  test('a 32-hex run 480 characters from the name is hidden, on either side', () => {
    expect(redact(`The ${NAME}${' '.repeat(480)}${hex32}`).text).toBe(`The ${NAME}${' '.repeat(480)}${M}`)
    expect(redact(`${hex32}${' '.repeat(480)}${NAME} cookie`).text).toBe(`${M}${' '.repeat(480)}${NAME} cookie`)
  })

  test('an over-hide is disclosed: another 32-hex run inside the window is hidden too', () => {
    const done = redact(`etag ${hex32b} for ${NAME}`)
    expect(done.text).toBe(`etag ${M} for ${NAME}`)
  })

  const idempotent: Array<[string, string]> = forms.map(([description, , build]) => [description, build('cell-3-' + hex32)])
  idempotent.push(['all the forms in one text', forms.map(([, , build]) => build(hex32)).join('\n')])
  for (const [description, text] of idempotent) {
    test(`redacting twice changes nothing: ${description}`, () => {
      const once = redact(text)
      const twice = redact(once.text)
      expect(twice.text).toBe(once.text)
      expect(countOf(twice.hits)).toBe(0)
    })
  }

  // WHY five texts: dense names, dense names with a value between (windows merge), snake_case runs near the name (the name search), 32-hex runs with no name (the prefilter), and a mix of names, prefixes and runs.
  // Each time is the best of 5 runs after one warm-up run (see the port-skip tests above); linear means the ratio stays near 8.
  const SMALL = 32 * 1024
  const bestOf = (text: string) => {
    redact(text)
    return Math.min(...[0, 1, 2, 3, 4].map(() => {
      const started = performance.now()
      redact(text)
      return performance.now() - started
    }))
  }
  const linear = (small: number, big: number) => big < 2 || big / small < 12
  const grow = (unit: string) => (size: number) => unit.repeat(Math.ceil(size / unit.length)).slice(0, size)
  const shapes: Array<[string, (size: number) => string]> = [
    ['dense names', grow(`${NAME} `)],
    ['dense names with a value between', grow(`${NAME}=short ${hex32} `)],
    ['snake_case runs near the name', grow('a_gitlab_sessio_n_gitlab_sess_ion_')],
    ['32-hex runs with no name', grow(`${hex32}-${hex32b} `)],
    ['a mix of names, prefixes and hex runs', grow(`${NAME} cell-3-${hex32}-${hex32b} a_b_c \n${NAME}: x ${sha40} `)],
  ]
  for (const [description, build] of shapes) {
    test(`8 times the text takes under 12 times as long (or under 2 ms): ${description}`, { timeoutMs: 60000 }, () => {
      expect(linear(bestOf(build(SMALL)), bestOf(build(8 * SMALL)))).toBe(true)
    })
  }
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
      id('private-key', /-----BEGIN ((?! )(?![A-Z0-9 ]*  )[A-Z0-9 ]*(?<= )PRIVATE KEY(?: BLOCK)?)-----[\s\S]*?(?:-----END \1-----|$)/g),
      id('google-oauth-client-secret', /\bGOCSPX-[A-Za-z0-9_-]{20,}/g),
      id('google-oauth-access-token', /\bya29\.[\w-]{20,2048}(?:\.[\w-]{1,512}){0,4}/g),
      id('google-oauth-refresh-token', /(?<![\w/+])1\/\/0[\w-]{40,512}/g),
      id('digitalocean-pat', /dop_v1_[0-9a-f]{64,}/gi),
      id('digitalocean-oauth-token', /doo_v1_[0-9a-f]{64,}/gi),
      id('digitalocean-refresh-token', /dor_v1_[0-9a-f]{64,}/gi),
      id('aws-access-key', /\b((?:AKIA|ASIA)[A-Z0-9]{16})\b/g),
      id('aws-secret-key', /\b(?:aws_?secret_?(?:access_?)?key|secret_?access_?key)["']?\s*[=:]\s*["']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])/gi),
      id('aws-secret-key', /"SecretAccessKey"\s*:\s*"([A-Za-z0-9/+=]{40})"/g),
      id('aws-session-token', /"SessionToken"\s*:\s*"([A-Za-z0-9/+=]{100,})"/g),
      id('github-token', /\b(gh[pousr]_[A-Za-z0-9]{30,255})/g),
      id('github-token', /\b(github_pat_[A-Za-z0-9_]{20,255})/g),
      id('gitlab-pat', /glpat-[0-9A-Za-z_-]{20,}(?:\.[0-9a-z]{9}(?![0-9A-Za-z]))?/gi),
      id('gitlab-oauth-app-secret', /gloas-[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-deploy-token', /gldt-[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-runner-token', /(?:glrtr-|glrt-)[0-9A-Za-z_-]{20,}(?:\.[0-9a-z]{9}(?![0-9A-Za-z]))?/gi),
      id('gitlab-runner-registration-token', /GR1348941[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-cicd-job-token', /glcbt-[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-trigger-token', /glptt-[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-feed-token', /glft-[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-incoming-mail-token', /glimt-[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-agent-token', /glagent-[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-workspace-token', /glwt-[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-scim-token', /glsoat-[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-feature-flag-client-token', /glffct-[0-9A-Za-z_-]{20,}/gi),
      id('gitlab-session-cookie', /_gitlab_session(?:_[0-9a-z_]{0,80})?(?:(?:\\*["']|%2[27])[ \t]*,[ \t]*(?:\\*["']|%2[27])|(?:\\*["']|%2[27])?\]?[ \r\n]*(?:(?:=>?|:|%3[AD]|\t)[ \t]*(?:\\*["']|%2[27])?|(?:,|=>?[ \t]*\{)[^{}]{0,400}?value(?:\\*["']|%2[27])?[ \t]*:[ \t]*(?:\\*["']|%2[27])))([^;&,%\s"'`\\]{16,})/gi),
      id('gitlab-session-cookie', /value(?:\\*["']|%2[27])?[ \t]*:[ \t]*(?:\\*["']|%2[27])([^;&,%\s"'`\\]{16,})(?:\\*["']|%2[27])\s*,[^{}]{0,400}?name(?:\\*["']|%2[27])?[ \t]*:[ \t]*(?:\\*["']|%2[27])?_gitlab_session/gi),
      id('anthropic-key', /\b(sk-ant-[A-Za-z0-9_-]{20,})/g),
      id('openai-key', /\b(sk-(?:proj|svcacct|admin)-[A-Za-z0-9_-]{20,})/g),
      id('openai-key', /\b(sk-[A-Za-z0-9]{20}T3BlbkFJ[A-Za-z0-9]{20})\b/g),
      id('openai-key', /\b(sk-[A-Za-z0-9_-]{20,})/g),
      id('slack-app-token', /(?i:xapp-\d-[A-Z0-9]+-\d+-[a-z0-9]+)/g),
      id('slack-config-token', /(?i:xoxe.xox[bp]-\d-[A-Z0-9]{163,166})/g),
      id('slack-config-token', /(?i:xoxe-\d-[A-Z0-9]{146})/g),
      id('slack-token', /\b(xox[abposr]-[A-Za-z0-9-]{10,})/g),
      id('slack-webhook', /(https:\/\/hooks\.slack\.com\/services\/T[A-Z0-9]+\/B[A-Z0-9]+\/[A-Za-z0-9]+)/g),
      id('stripe-key', /\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,})/g),
      id('stripe-key', /\b(whsec_[A-Za-z0-9]{24,})/g),
      id('google-api-key', /\b(AIza[0-9A-Za-z_-]{35})(?![0-9A-Za-z_-])/g),
      id('jwt', /(?<![A-Za-z0-9_-])(?=[A-Za-z0-9_-]*\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})[A-Za-z0-9_-]*?(?<![A-Za-z0-9_])(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/g),
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
  // TRDD-AGOEWF2E: the header class loop must keep hiding a key whose header is millions of characters long.
  // The count is above 1,474,557, where the group loop this replaced first missed (silently, with no error).
  const KEY_UNIT = 'A '
  const KEY_UNITS = 1572864
  const longKey = (end: boolean) => {
    const header = KEY_UNIT.repeat(KEY_UNITS) + 'PRIVATE KEY'
    return `key:\n${j('-----BEGIN ', header, '-----')}\nMIIEpAIBAAKCAQEA\n${end ? `${j('-----END ', header, '-----')}\n` : ''}done`
  }
  test('a PEM private key with a 3 MB header is hidden whole, with exactly one hit', { timeoutMs: 15000 }, () => {
    expect(KEY_UNITS).toBeGreaterThan(1474557)
    const { text, hits } = redact(longKey(true))
    expect(hits['private-key']).toBe(1)
    expect(text.includes(KEY_UNIT.repeat(32))).toBe(false)
    expect(text).toBe(`key:\n${mark('private-key')}\ndone`)
  })
  test('a cut-off PEM private key with a 3 MB header is hidden to the end of the text', { timeoutMs: 15000 }, () => {
    const { text, hits } = redact(longKey(false))
    expect(hits['private-key']).toBe(1)
    expect(text.includes(KEY_UNIT.repeat(32))).toBe(false)
    expect(text).toBe(`key:\n${mark('private-key')}`)
  })
  // The old pattern, kept here as the reference the new header must agree with on every text.
  const OLD_PRIVATE_KEY = /-----BEGIN ((?:[A-Z0-9]+ )*PRIVATE KEY(?: BLOCK)?)-----[\s\S]*?(?:-----END \1-----|$)/g
  test('the new pattern and the old one give the same matches (index, whole match, group 1) on random texts', () => {
    // The edge pieces: a doubled space, a glued letter, a BEGIN with a leading space, and the markers themselves.
    const pieces = ['A', ' ', '-', 'PRIVATE KEY', ' BLOCK', '\n', '  ', 'X', j('-----BEGIN '), j('-----BEGIN  '), j('-----END '), j('-----')]
    // A fixed seed keeps the texts the same on every run; the high bits are used because the low bits of this generator cycle.
    let seed = 20261113
    const next = (n: number) => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0
      return (seed >>> 16) % n
    }
    const list = (input: string, pattern: RegExp) => [...input.matchAll(new RegExp(pattern.source, 'g'))].map((m) => [m.index, m[0], m[1]])
    let compared = 0
    for (let i = 0; i < 3000; i++) {
      let input = ''
      const length = 1 + next(40)
      for (let k = 0; k < length; k++) input += pieces[next(pieces.length)]
      const old = list(input, OLD_PRIVATE_KEY)
      compared += old.length
      expect(JSON.stringify(list(input, privateKey.pattern)) === JSON.stringify(old)).toBe(true)
    }
    expect(compared).toBeGreaterThan(100)
  })
  test('a header glued to PRIVATE whose END lies inside an RSA block leaves the same text as the old pattern, and no RSA body shows', () => {
    // BEGIN XPRIVATE KEY is not a header the old pattern accepted. A wider class took it, and its END (the line inside the RSA block) made the RSA tail visible.
    const input = `${j('-----BEGIN ', 'XPRIVATE KEY-----')}\nalpha\n${j('-----BEGIN ', 'RSA PRIVATE KEY-----')}\nrsabody\n${j('-----END ', 'XPRIVATE KEY-----')}\nrsatail\n${j('-----END ', 'RSA PRIVATE KEY-----')}\ndone`
    const { text, hits } = redact(input)
    expect(hits).toEqual({ 'private-key': 1 })
    expect(text.includes('rsabody') || text.includes('rsatail')).toBe(false)
    expect(text).toBe(input.replace(OLD_PRIVATE_KEY, mark('private-key')))
  })
  test('two PEM blocks in one text: each complete block is its own hit; a block with no END of its own takes the rest of the text', () => {
    const block = (kind: string, body: string) => `${j('-----BEGIN ', kind, ' PRIVATE KEY-----')}\n${body}\n${j('-----END ', kind, ' PRIVATE KEY-----')}`
    const two = redact(`a\n${block('RSA', 'one')}\nb\n${block('EC', 'two')}\nc`)
    expect(two.hits['private-key']).toBe(2)
    expect(two.text).toBe(`a\n${mark('private-key')}\nb\n${mark('private-key')}\nc`)
    const cut = redact(`a\n${j('-----BEGIN ', 'RSA PRIVATE KEY-----')}\none\nb\n${block('EC', 'two')}\nc`)
    expect(cut.hits['private-key']).toBe(1)
    expect(cut.text).toBe(`a\n${mark('private-key')}`)
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

describe('jwt rule runs in linear time with the same matches (TRDD-A7RII4DN)', () => {
  // The rule exactly as it was before TRDD-A7RII4DN. It is the reference the current rule must match span for span.
  const oldJwt = { kind: 'jwt', pattern: /\b(eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})/g, group: 1 }
  // The token is group 1 and ends the match in both rules; the current rule's match may start earlier, at the run start.
  const spans = (pattern: RegExp, text: string): string =>
    [...text.matchAll(new RegExp(pattern.source, pattern.flags))].map(m => `${m.index + m[0].length - m[1].length}-${m.index + m[0].length}`).join(',')
  const sameAsOld = (text: string): string => {
    expect(spans(jwt.pattern, text)).toBe(spans(oldJwt.pattern, text))
    const [hitsNow, hitsOld] = [{}, {}]
    const out = applyRule(text, jwt, hitsNow)
    expect(out).toBe(applyRule(text, oldJwt, hitsOld))
    expect(hitsNow).toEqual(hitsOld)
    return out
  }
  const tok = j('eyJ', 'hbGciOiJIUzI1NiJ9', '.', 'eyJ', 'zdWIiOiIxMjM0NTY3ODkwIn0', '.', 'dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U')
  const tok2 = j('eyJ', 'abcdefghij', '.', 'eyJ', 'klmnopqrst', '.', 'uvwxyz0123')
  const jwtMark = mark('jwt')

  const handCases: Array<[string, string]> = [
    ['a token alone, at the text start and end', tok],
    ['a token after x-, which stands at a word boundary', `x-${tok}`],
    ['a token after _, which does not', `_${tok}`],
    ['a token glued to a letter', `x${tok}`],
    ['a token after a dot', `a.${tok}`],
    ['several eyJ in one run: the leftmost start wins', `eyJab-eyJcdefghijklmn-${tok}`],
    ['several eyJ in one run, the first too short to qualify', `eyJabcdefgh-eyJcdefghijklmn-${tok}`],
    ['a starved third segment (9 characters)', j(tok2.slice(0, -1))],
    ['a third segment of exactly 10 characters', tok2],
    ['a first segment of 9 characters after eyJ', j('eyJ', 'abcdefghi', '.', 'eyJ', 'klmnopqrst', '.', 'uvwxyz0123')],
    ['a first segment of exactly 10 characters after eyJ', j('eyJ', 'abcdefghij', '.', 'eyJ', 'klmnopqrst', '.', 'uvwxyz0123')],
    ['a second segment of 9 characters after eyJ', j('eyJ', 'abcdefghij', '.', 'eyJ', 'klmnopqrs', '.', 'uvwxyz0123')],
    ['a second segment that does not start with eyJ', j('eyJ', 'abcdefghij', '.', 'xyJ', 'klmnopqrst', '.', 'uvwxyz0123')],
    ['two tokens in one line', `${tok} ${tok2}`],
    ['two tokens joined by a dot', `${tok}.${tok2}`],
    ['a token followed by dots and more segments', `${tok}.${tok2}.${tok2}`],
    ['a long run that does not end in a dot', `eyJ-eyJ-eyJ-eyJ-eyJ-eyJ-eyJ-eyJ- ${tok}`],
    ['a long run ending in a dot and a short eyJ tail', `eyJ-eyJ-eyJ-eyJ-eyJ-eyJ-.eyJabc ${tok}`],
  ]
  for (const [name, text] of handCases) {
    test(`same spans as the old rule: ${name}`, () => {
      const out = sameAsOld(text)
      expect(redact(text).text).toBe(out)
    })
  }

  test('the hand cases cover both a hit and a miss', () => {
    const hit = handCases.filter(([, text]) => spans(oldJwt.pattern, text) !== '').length
    expect(hit).toBeGreaterThanOrEqual(10)
    expect(handCases.length - hit).toBeGreaterThanOrEqual(5)
  })

  test('400 seeded random strings give the old rule\'s spans, output and hit count', () => {
    let seed = 20261114
    const next = (): number => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0) / 2 ** 32)
    const pieces = ['eyJ', 'eyJ-', 'eyJ_', 'a', 'Z', '0', '-', '_', '.', ' ', 'eyJabcdefghij', 'eyJabcdefghi', 'eyJabcdefghijk', '.eyJ', 'x', 'abcdefghij', 'abcdefghi', '.eyJabcdefghij.', 'eyJ-abcdefghij', 'x-eyJabcdefghijklm', '_eyJabcdefghijklm']
    let withMatch = 0
    for (let i = 0; i < 400; i++) {
      let text = ''
      for (let k = 1 + Math.floor(next() * 14); k > 0; k--) text += pieces[Math.floor(next() * pieces.length)]
      if (spans(oldJwt.pattern, text) !== '') withMatch++
      sameAsOld(text)
    }
    // A generator that never produced a match would pass vacuously.
    expect(withMatch).toBeGreaterThanOrEqual(20)
  })

  // The old rule scanned to the end of the run from every eyJ start inside it, so a run of n characters cost n * n / 4 steps:
  // 9.8 s at 256 KB (one run on an uncontrolled host), more than 60 s at 1 MB. 1 s is generous for the current rule.
  const KB256 = 256 * 1024
  const run = (n: number): string => 'eyJ-'.repeat(n / 4)
  const slowCases: Array<[string, string]> = [
    ['eyJ- repeated and ending in .x', run(KB256).slice(0, KB256 - 2) + '.x'],
    ['eyJ- repeated, then .eyJ and a short tail', `${run(KB256)}.eyJabc`],
    ['eyJ- repeated, then .eyJ- repeated', `${run(KB256 / 2)}.${run(KB256 / 2)}`],
    ['eyJ- repeated, then a second segment and a starved third', `${run(KB256)}.eyJabcdefghij.abc`],
  ]
  for (const [name, text] of slowCases) {
    test(`256 KB of ${name} is redacted in under a second`, () => {
      const start = performance.now()
      const { hits } = redact(text)
      expect(performance.now() - start).toBeLessThan(1000)
      expect(hits.jwt).toBeUndefined()
    })
  }

  // A quadratic rule takes about 16x its 256 KB time at 1 MB, so on any hardware this case separates the old rule from the linear one;
  // the 256 KB cases above would pass the old rule on a machine about 3x faster than the one that measured 2.6 s there.
  test('1 MB of eyJ- repeated and ending in .x is redacted in under a second', () => {
    const text = run(4 * KB256).slice(0, 4 * KB256 - 2) + '.x'
    const start = performance.now()
    const { hits } = redact(text)
    expect(performance.now() - start).toBeLessThan(1000)
    expect(hits.jwt).toBeUndefined()
  })

  // JavaScriptCore has silently missed matches of a long loop in this repo (TRDD-AGOEWF2E), so assert the hide, not only the time.
  const MB = 1024 * 1024
  test('a valid JWT after a 1 MB eyJ- run is still hidden', () => {
    const { text, hits } = redact(`${run(MB)}\n${tok}`)
    expect(hits.jwt).toBe(1)
    expect(text).not.toContain(tok)
    expect(text.endsWith(`\n${jwtMark}`)).toBe(true)
  })

  test('a valid JWT that continues a 1 MB eyJ- run is hidden whole', () => {
    const { text, hits } = redact(`${run(MB)}.${tok.slice(tok.indexOf('.') + 1)}`)
    expect(hits.jwt).toBe(1)
    expect(text).toBe(jwtMark)
  })
})
