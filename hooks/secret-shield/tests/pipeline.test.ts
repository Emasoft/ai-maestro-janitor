// Tests of the pass pipeline (pipeline.ts): the pass order, the pass subset, the fixed-text failure on an unknown pass, the merged hits, idempotence and a linear-growth pin. Made-up names only.
// WHY every token and card number is built at run time: the privacy and secret scans read source text, so no credential-shaped or 13-digit literal may stand in a tracked file. The home paths are joined from pieces for the same reason (see tests/home.test.ts).
import { describe, expect, test } from 'claude-code/testing'

import { redactCards } from '../cards'
import { redactEmails } from '../email'
import { redactHome } from '../home'
import { addHits, mark, redact } from '../patterns'
import type { Hits } from '../patterns'
import { ALL_PASSES, PASS_ORDER, isPass, redactAll } from '../pipeline'
import type { Pass } from '../pipeline'

const AT = '@'
const unix = (...parts: string[]) => parts.join('/')
const HOMES = ['/opt/people/app']

const checkDigit = (body: string): string => {
  let sum = 0
  for (let i = 0; i < body.length; i++) {
    let d = Number(body[body.length - 1 - i])
    if (i % 2 === 0) d = d * 2 > 9 ? d * 2 - 9 : d * 2
    sum += d
  }
  return String((10 - (sum % 10)) % 10)
}
const cardNumber = (prefix: string, length: number, filler: string): string => {
  let body = prefix
  while (body.length < length - 1) body += filler
  body = body.slice(0, length - 1)
  return body + checkDigit(body)
}

const TOKEN = 'gh' + 'p_' + 'aB3dE5gH7j'.repeat(4).slice(0, 36)
const CARD = cardNumber('4', 16, '7391')
// WHY not example.org: the email pass leaves example.com and example.org visible (rule 3 of email.ts), so the fixture needs another domain.
const EMAIL = 'ada' + AT + 'mail.test'
const HOME_PATH = unix('', 'Users', 'runner', 'x.ts')
const MIXED = `token ${TOKEN} card ${CARD} mail ${EMAIL} path ${HOME_PATH} end`

const manualChain = (text: string, homes: string[]): { text: string; hits: Hits } => {
  const hits: Hits = {}
  const secrets = redact(text)
  addHits(hits, secrets.hits)
  const cards = redactCards(secrets.text)
  addHits(hits, cards.hits)
  const emails = redactEmails(cards.text)
  addHits(hits, emails.hits)
  const home = redactHome(emails.text, homes)
  addHits(hits, home.hits)
  return { text: home.text, hits }
}
const ms = (run: () => void): number => {
  const start = performance.now()
  run()
  return performance.now() - start
}
const fastest = (values: number[]): number => Math.min(...values)

describe('pass pipeline', () => {
  test('the pass order is secrets, cards, email, home, and isPass accepts exactly those', () => {
    expect([...PASS_ORDER]).toEqual(['secrets', 'cards', 'email', 'home'])
    expect([...ALL_PASSES]).toEqual([...PASS_ORDER])
    for (const p of PASS_ORDER) expect(isPass(p)).toBe(true)
    for (const v of ['bogus', '', 'Secrets', 1, null, undefined, {}]) expect(isPass(v)).toBe(false)
  })

  test('all passes equal the manual chain redact, redactCards, redactEmails, redactHome: text and hits', () => {
    expect(redactAll(MIXED, HOMES)).toEqual(manualChain(MIXED, HOMES))
    expect(redactAll(MIXED, HOMES, ALL_PASSES)).toEqual(manualChain(MIXED, HOMES))
    expect(redactAll(MIXED, HOMES).text).not.toContain('runner')
  })

  test('order: an email inside a home path is hidden and the name is not visible in the output', () => {
    const path = unix('', 'Users', 'runner' + AT + 'corp.example', 'x')
    const out = redactAll('open ' + path + ' now', [])
    expect(out.text).toContain(mark('email'))
    expect(out.text).not.toContain('runner')
    expect(out.text).not.toContain('corp.example')
    expect(out.hits.email).toBe(1)
  })

  test('subset: the secrets pass alone leaves an email and a home path as written', () => {
    const text = `mail ${EMAIL} path ${HOME_PATH}`
    expect(redactAll(text, HOMES, new Set<Pass>(['secrets']))).toEqual({ text, hits: {} })
  })

  test('subset: the home pass alone rewrites only the home path', () => {
    expect(redactAll(MIXED, HOMES, new Set<Pass>(['home']))).toEqual({
      text: MIXED.replace(HOME_PATH, '~/x.ts'),
      hits: { 'home-path': 1 },
    })
  })

  test('an empty pass set throws, so no text leaves unredacted by mistake', () => {
    expect(() => redactAll(MIXED, HOMES, new Set<Pass>())).toThrow('redactAll: the pass set is empty')
  })

  test('a pass set holding a value that is not a pass throws, with fixed text that does not echo the value', () => {
    const bad = new Set(['secrets', 'bogus-' + TOKEN]) as unknown as ReadonlySet<Pass>
    expect(() => redactAll(MIXED, HOMES, bad)).toThrow('redactAll: the pass set holds a value that is not a pass')
    let message = ''
    try {
      redactAll(MIXED, HOMES, bad)
    } catch (e) {
      message = e instanceof Error ? e.message : ''
    }
    expect(message).not.toContain(TOKEN)
  })

  test('one token, one card, one email and one home path give one hit of each kind', () => {
    expect(redactAll(MIXED, HOMES).hits).toEqual({ 'github-token': 1, 'payment-card': 1, email: 1, 'home-path': 1 })
  })

  test('idempotence: running it on its own output changes nothing and counts 0 hits', () => {
    const first = redactAll(MIXED, HOMES)
    expect(redactAll(first.text, HOMES)).toEqual({ text: first.text, hits: {} })
  })

  test('growth is linear: a 4x larger input takes under 8x the time (linear is about 4, quadratic about 16)', { timeoutMs: 60000 }, () => {
    // WHY the fastest of 5 runs after a warm-up of each size: on a shared host load only adds time, so the fastest run is the closest to the real cost; the first run of each size pays for the engine compiling the rules.
    const unit = MIXED + '\nplain filler line without anything to hide, padded to a realistic width\n'
    const input = (size: number) => unit.repeat(Math.ceil(size / unit.length)).slice(0, size)
    const small = input(128 * 1024)
    const large = input(512 * 1024)
    redactAll(small, HOMES)
    redactAll(large, HOMES)
    const time = (text: string) => fastest(Array.from({ length: 5 }, () => ms(() => redactAll(text, HOMES))))
    const ratio = time(large) / time(small)
    expect(ratio).toBeLessThan(8)
  })
})
