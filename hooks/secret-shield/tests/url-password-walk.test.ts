import { describe, expect, test } from 'claude-code/testing'

import { type Hits, mark, redact, URL_PASSWORD_BOUND } from '../patterns'

// WHY this file (TRDD-AGV84UGC, step 1): it pins what URL-password redaction does TODAY, before the rewrite that replaces the URL_PASSWORD regex, so the rewrite can be
// checked against the old behaviour and not against itself. Every expectation here was captured by running the real patterns.ts (the pre-change code) with Bun
// 1.3.14 on 2026-11-15 at git HEAD 218001b7. The case inputs are hand-written; no expected output of the cases was typed by hand (the capture and generator scripts were scratch files and are not tracked).
// The two scaling tests at the end are the exception: they are not captured, they assert a timing (time at 2N at most 3 x time at N, best of three after a warm-up; unlike over-bound-json.test.ts, which asserts none), and the bound of 3 was chosen by hand.
// Nothing in it was run under the plugin test engine when it was written, so the first run there is the pre-push gate: a failure on the OLD code means the engine differs from Bun
// for that case, which is a finding to read, not a test to loosen.
// Each case asserts the whole redacted text (or, over 2 KB, its length and SHA-256), the exact hit counts, and the redaction of the output again (the second pass must give the
// same text). Cases with a copy also append a copy of the password after a newline: `redact` returns no `found` map, but a password recorded for propagation is hidden
// in the copy and one that is not recorded stays visible. This is a proxy, weaker than pinning the map: a password that is recorded but that propagates() refuses looks the same as one never recorded, so for those the copy pins nothing.
// Fake passwords are built at run time (PASS, PASS2) so no scanner mistakes this file for a leak; their values are named, never written, in the expectations.

// SHA-256 of the UTF-8 bytes of a text, as lower-case hex. Written out so the test needs no node: import (the plugin test engine is not known to ship one).
function sha256Hex(text: string): string {
  const data = new TextEncoder().encode(text)
  const k: number[] = []
  const h: number[] = []
  for (let n = 2, count = 0; count < 64; n++) {
    let prime = true
    for (let d = 2; d * d <= n; d++) {
      if (n % d === 0) {
        prime = false
        break
      }
    }
    if (!prime) continue
    if (count < 8) h[count] = ((Math.pow(n, 1 / 2) % 1) * 4294967296) | 0
    k[count++] = ((Math.pow(n, 1 / 3) % 1) * 4294967296) | 0
  }
  const padded = new Uint8Array(((data.length + 9 + 63) >> 6) << 6)
  padded.set(data)
  padded[data.length] = 0x80
  const view = new DataView(padded.buffer)
  view.setUint32(padded.length - 8, Math.floor((data.length * 8) / 4294967296))
  view.setUint32(padded.length - 4, (data.length * 8) >>> 0)
  const w = new Int32Array(64)
  for (let off = 0; off < padded.length; off += 64) {
    for (let i = 0; i < 16; i++) w[i] = view.getInt32(off + i * 4)
    for (let i = 16; i < 64; i++) {
      const x15 = w[i - 15]
      const x2 = w[i - 2]
      const s0 = ((x15 >>> 7) | (x15 << 25)) ^ ((x15 >>> 18) | (x15 << 14)) ^ (x15 >>> 3)
      const s1 = ((x2 >>> 17) | (x2 << 15)) ^ ((x2 >>> 19) | (x2 << 13)) ^ (x2 >>> 10)
      w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0
    }
    let [a, b, c, d, e, f, g, hh] = h
    for (let i = 0; i < 64; i++) {
      const big1 = ((e >>> 6) | (e << 26)) ^ ((e >>> 11) | (e << 21)) ^ ((e >>> 25) | (e << 7))
      const choose = (e & f) ^ (~e & g)
      const t1 = (hh + big1 + choose + k[i] + w[i]) | 0
      const big0 = ((a >>> 2) | (a << 30)) ^ ((a >>> 13) | (a << 19)) ^ ((a >>> 22) | (a << 10))
      const majority = (a & b) ^ (a & c) ^ (b & c)
      const t2 = (big0 + majority) | 0
      hh = g
      g = f
      f = e
      e = (d + t1) | 0
      d = c
      c = b
      b = a
      a = (t1 + t2) | 0
    }
    h[0] = (h[0] + a) | 0
    h[1] = (h[1] + b) | 0
    h[2] = (h[2] + c) | 0
    h[3] = (h[3] + d) | 0
    h[4] = (h[4] + e) | 0
    h[5] = (h[5] + f) | 0
    h[6] = (h[6] + g) | 0
    h[7] = (h[7] + hh) | 0
  }
  return h.map(x => (x >>> 0).toString(16).padStart(8, '0')).join('')
}

const j = (...parts: string[]): string => parts.join('')
const B = URL_PASSWORD_BOUND
const PASS = j('aB3dE5', 'fG7hJ9kL')
const PASS2 = j('Xy9kM2', 'pQ4rT8wZ')
const M = mark('url-password')
const TOK = mark('aws-access-key')
const U = (user: string, password: string, rest = 'host/'): string => j('https://', user, ':', password, '@', rest)
const colons = (n: number): string => j(PASS, ':a'.repeat(n))
const mixed = (n: number): string => 'aB3dE5fG7hJ9kL1m'.repeat(n / 16)

type Want = string | { sha256: string; length: number }
const digest = (text: string): { sha256: string; length: number } => ({ sha256: sha256Hex(text), length: text.length })
const check = (got: { text: string; hits: Hits }, hits: Hits, want: Want): void => {
  expect(got.hits).toEqual(hits)
  if (typeof want === 'string') expect(got.text === want).toBe(true)
  else expect(digest(got.text)).toEqual(want)
}

describe('URL passwords: port skip', () => {
  test('a port then a path with an at-sign is not a password (h:8080/p@x)', { timeoutMs: 60000 }, () => {
    const input = U('h', '8080/p', 'x')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('a port then a query with = before the at-sign is not a password (h:80?a=1@x)', { timeoutMs: 60000 }, () => {
    const input = U('h', '80?a=1', 'x')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('a port then a ? with no = is a password (h:80?a@x)', { timeoutMs: 60000 }, () => {
    const input = U('h', '80?a', 'x')
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://h:', M, '@x'))
    check(redact(first.text), {}, first.text)
  })
  test('six digits are not a port (h:123456/x@y)', { timeoutMs: 60000 }, () => {
    const input = U('h', '123456/x', 'y')
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://h:', M, '@y'))
    check(redact(first.text), {}, first.text)
  })
  test('five digits then a slash and nothing else is a port (h:12345/@x)', { timeoutMs: 60000 }, () => {
    const input = U('h', '12345/', 'x')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('a ? then :// then = ends the password at the second :// (h:1234?:://=@x)', { timeoutMs: 60000 }, () => {
    const input = U('h', '1234?:://=', 'x')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('a port then a path that holds a secret-shaped text is skipped and not propagated', { timeoutMs: 60000 }, () => {
    const input = U('h', j('8080/', PASS), 'x')
    const copy = j('8080/', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('a port then a query with = before the at-sign, secret-shaped text after the =', { timeoutMs: 60000 }, () => {
    const input = U('h', j('80?a=', PASS), 'x')
    const copy = j('80?a=', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
})

describe('URL passwords: port query', () => {
  test('the = comes after a # so the query holds no =', { timeoutMs: 60000 }, () => {
    const input = U('h', j('80?a#b=', PASS), 'x')
    const copy = j('80?a#b=', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://h:', M, '@x'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://h:', M, '@x\ncopy ', M))
  })
  test('the = comes after a :// so the query holds no =', { timeoutMs: 60000 }, () => {
    const input = U('h', j('80?a', '://', 'b=', PASS), 'x')
    const copy = j('80?a', '://', 'b=', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('no = at all', { timeoutMs: 60000 }, () => {
    const input = U('h', j('80?a', PASS), 'x')
    const copy = j('80?a', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://h:', M, '@x'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://h:', M, '@x\ncopy ', M))
  })
  test('the = follows colons in the query', { timeoutMs: 60000 }, () => {
    const input = U('h', j('80?a:b:c=', PASS), 'x')
    const copy = j('80?a:b:c=', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('the query is only an =', { timeoutMs: 60000 }, () => {
    const input = U('h', j('80?=', PASS), 'x')
    const copy = j('80?=', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('an = after whitespace is outside the password', { timeoutMs: 60000 }, () => {
    const input = j('https://h:80?a', ' b=', PASS, '@x')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('six digits then a query with =', { timeoutMs: 60000 }, () => {
    const input = U('h', j('123456?a=', PASS), 'x')
    const copy = j('123456?a=', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://h:', M, '@x'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://h:', M, '@x\ncopy ', M))
  })
  test('six digits then a path', { timeoutMs: 60000 }, () => {
    const input = U('h', j('123456/', PASS), 'x')
    const copy = j('123456/', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://h:', M, '@x'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://h:', M, '@x\ncopy ', M))
  })
  test('digits then a #', { timeoutMs: 60000 }, () => {
    const input = U('h', j('2024#', PASS), 'x')
    const copy = j('2024#', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://h:', M, '@x'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://h:', M, '@x\ncopy ', M))
  })
  test('digits then letters', { timeoutMs: 60000 }, () => {
    const input = U('h', j('8080', PASS), 'x')
    const copy = j('8080', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://h:', M, '@x'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://h:', M, '@x\ncopy ', M))
  })
  test('digits, a letter, then a slash', { timeoutMs: 60000 }, () => {
    const input = U('h', j('12a/', PASS), 'x')
    const copy = j('12a/', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://h:', M, '@x'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://h:', M, '@x\ncopy ', M))
  })
  test('a port then a query with = after exactly the bound of colons', { timeoutMs: 60000 }, () => {
    const input = U('h', j('80?', 'q:'.repeat(B), 'k=v'), 'x')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
})

describe('URL passwords: placeholders and markers', () => {
  test('the placeholder ${VAR} is left alone', { timeoutMs: 60000 }, () => {
    const input = U('user', '${VAR}')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('the placeholder $VAR is left alone', { timeoutMs: 60000 }, () => {
    const input = U('user', '$VAR')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('the placeholder x is left alone', { timeoutMs: 60000 }, () => {
    const input = U('user', 'x')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('the placeholder <token> is left alone', { timeoutMs: 60000 }, () => {
    const input = U('user', '<token>')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('the placeholder changeme is left alone', { timeoutMs: 60000 }, () => {
    const input = U('user', 'changeme')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('a marker alone is left alone', { timeoutMs: 60000 }, () => {
    const input = U('user', M)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('two adjacent markers are left alone', { timeoutMs: 60000 }, () => {
    const input = U('user', j(M, M))
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('a marker and a placeholder are left alone', { timeoutMs: 60000 }, () => {
    const input = U('user', j(M, 'x'))
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('a marker and a secret-shaped text: hidden, one hit', { timeoutMs: 60000 }, () => {
    const input = U('user', j(M, PASS))
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://user:', M, '@host/\ncopy ', PASS))
  })
  test('a lower-case marker in the password is not a marker: hidden', { timeoutMs: 60000 }, () => {
    const input = U('user', j('[janitor-redacted:', 'abc]'))
    const copy = j('[janitor-redacted:', 'abc]')
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://user:', M, '@host/\ncopy ', M))
  })
  test('exactly the bound of markers and a secret-shaped text: hidden and propagated', { timeoutMs: 60000 }, () => {
    const input = U('user', j(M.repeat(B), PASS))
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://user:', M, '@host/\ncopy ', PASS))
  })
  test('more than the bound of markers alone are left alone', { timeoutMs: 60000 }, () => {
    const input = U('user', M.repeat(B + 1))
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('more than the bound of markers and a placeholder are left alone', { timeoutMs: 60000 }, () => {
    const input = U('user', j(M.repeat(B + 1), 'x'))
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('more than the bound of markers and a secret-shaped text: hidden, not propagated', { timeoutMs: 60000 }, () => {
    const input = U('user', j(M.repeat(B + 1), PASS))
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://user:', M, '@host/\ncopy ', PASS))
  })
})

describe('URL passwords: user part', () => {
  test('no marker in the user part', { timeoutMs: 60000 }, () => {
    const input = U('user', PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://user:', M, '@host/\ncopy ', M))
  })
  test('a marker is the whole user part', { timeoutMs: 60000 }, () => {
    const input = U(TOK, PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://', TOK, ':', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://', TOK, ':', M, '@host/\ncopy ', M))
  })
  test('text then a marker', { timeoutMs: 60000 }, () => {
    const input = U(j('bob', TOK), PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://bob', TOK, ':', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://bob', TOK, ':', M, '@host/\ncopy ', M))
  })
  test('a marker then text', { timeoutMs: 60000 }, () => {
    const input = U(j(TOK, 'bob'), PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://', TOK, 'bob:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://', TOK, 'bob:', M, '@host/\ncopy ', M))
  })
  test('several markers between text', { timeoutMs: 60000 }, () => {
    const input = U(j(TOK, 'a', TOK, 'b', TOK), PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://', TOK, 'a', TOK, 'b', TOK, ':', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://', TOK, 'a', TOK, 'b', TOK, ':', M, '@host/\ncopy ', M))
  })
  test('two adjacent markers', { timeoutMs: 60000 }, () => {
    const input = U(j(TOK, TOK), PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://', TOK, TOK, ':', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://', TOK, TOK, ':', M, '@host/\ncopy ', M))
  })
  test('a lower-case marker is a marker in the user part', { timeoutMs: 60000 }, () => {
    const input = U(j('[janitor-redacted:', 'aws]'), PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://[janitor-redacted:aws]:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://[janitor-redacted:aws]:', M, '@host/\ncopy ', M))
  })
  test('a [ that does not open a marker ends the user part before a colon', { timeoutMs: 60000 }, () => {
    const input = U('a[b', PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('an unclosed marker is not a marker', { timeoutMs: 60000 }, () => {
    const input = U('[JANITOR-REDACTED:x', PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('a bracketed IPv6 host is not a user (::1)', { timeoutMs: 60000 }, () => {
    const input = j('http://[::1]', ':4873/', '@scope/pkg')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('a bracketed IPv6 host is not a user (fe80::1)', { timeoutMs: 60000 }, () => {
    const input = j('http://[fe80::1]', '/a@b')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('exactly the bound of markers: hidden and propagated', { timeoutMs: 60000 }, () => {
    const input = U(TOK.repeat(B), PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, { sha256: '0282ed463ff4d00a76420b33e85c0850ae11ac32d04d04f1fa50eee423c1bb95', length: 135214 })
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, { sha256: '1a4bf326d12a99971ed7db827f56e5aad055a5812cd91c365452ad3b551766d0', length: 135251 })
  })
  test('more than the bound of markers: hidden, not propagated', { timeoutMs: 60000 }, () => {
    const input = U(TOK.repeat(B + 1), PASS)
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, { sha256: '9c19a62183786e40c4bfc03995eab307260d55529b50d74cdeec811ce8134761', length: 135247 })
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, { sha256: 'dc4232b4f362641249bed2f4ad59bd74e72567b9c2ffe9e3ceb4630785b44f78', length: 135267 })
  })
  test('more than the bound of markers and no @: left alone', { timeoutMs: 60000 }, () => {
    const input = j('https://', TOK.repeat(B + 1), ':', PASS, '/path')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
})

describe('URL passwords: passwords with colons', () => {
  test('exactly the bound of colons: hidden and propagated', { timeoutMs: 60000 }, () => {
    const input = U('user', colons(B))
    const copy = colons(B)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://user:', M, '@host/\ncopy ', M))
  })
  test('more than the bound of colons: hidden, not propagated', { timeoutMs: 60000 }, () => {
    const input = U('user', colons(B + 1))
    const copy = colons(B + 1)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, { sha256: '22e612243148217f51c4193922a1d66ce214bdd65f6cfedfbf87998477661f30', length: 8264 })
  })
  test('a password that starts with a colon', { timeoutMs: 60000 }, () => {
    const input = U('user', j(':', PASS))
    const copy = j(':', PASS)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://user:', M, '@host/\ncopy ', M))
  })
  test('a password that starts with a colon, more than the bound of colons', { timeoutMs: 60000 }, () => {
    const input = U('user', j(':', colons(B)))
    const copy = j(':', colons(B))
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, { sha256: 'a894fcd9455cbcd3d9a9b72b4defbe5f4964b89ee0de4e73450ca87699c3d34b', length: 8263 })
  })
  test('a password of three colons', { timeoutMs: 60000 }, () => {
    const input = U('user', ':::')
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
  })
  test('a password of more than the bound of colons only', { timeoutMs: 60000 }, () => {
    const input = U('user', ':'.repeat(B + 1))
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
  })
  test('a :// inside the password ends it before the @, so nothing is hidden', { timeoutMs: 60000 }, () => {
    const input = U('user', j('ab', '://', PASS))
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('a second URL inside the first one\'s password is read as its own URL', { timeoutMs: 60000 }, () => {
    const input = U('user', j('ab', '://u2:', PASS2))
    const copy = PASS2
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:ab://u2:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://user:ab://u2:', M, '@host/\ncopy ', M))
  })
  test('more than the bound of colons then a single quote: left alone', { timeoutMs: 60000 }, () => {
    const input = j('https://user:', colons(B + 1), "'", ' tail')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('more than the bound of colons then a double quote then @: left alone', { timeoutMs: 60000 }, () => {
    const input = j('https://user:', colons(B + 1), '"', '@host/')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('more than the bound of colons then a backtick then @: left alone', { timeoutMs: 60000 }, () => {
    const input = j('https://user:', colons(B + 1), '`', '@host/')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('more than the bound of colons then whitespace then @: left alone', { timeoutMs: 60000 }, () => {
    const input = j('https://user:', colons(B + 1), ' ', '@host/')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('more than the bound of colons then the end of the text: left alone', { timeoutMs: 60000 }, () => {
    const input = j('https://user:', colons(B + 1))
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('exactly the bound of colons then a single quote: left alone', { timeoutMs: 60000 }, () => {
    const input = j('https://user:', colons(B), "'", ' tail')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('exactly the bound of colons then the end of the text: left alone', { timeoutMs: 60000 }, () => {
    const input = j('https://user:', colons(B))
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
})

describe('URL passwords: over the bound', () => {
  test('a port then a path with exactly the bound of colons: visible', { timeoutMs: 60000 }, () => {
    const input = j('b://u:8080/', 'a:'.repeat(B), '@h')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('a port then a path with more than the bound of colons: hidden, not propagated', { timeoutMs: 60000 }, () => {
    const input = j('b://u:8080/', 'a:'.repeat(B + 1), '@h')
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('b://u:', M, '@h'))
    check(redact(first.text), {}, first.text)
  })
  test('a port then a query with = and exactly the bound of colons: visible', { timeoutMs: 60000 }, () => {
    const input = j('b://u:80?', 'a:'.repeat(B), 'k=1@h')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('a port then a query with = and more than the bound of colons: hidden', { timeoutMs: 60000 }, () => {
    const input = j('b://u:80?', 'a:'.repeat(B + 1), 'k=1@h')
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('b://u:', M, '@h'))
    check(redact(first.text), {}, first.text)
  })
  test('a port then a path and a secret-shaped colon-dense text over the bound', { timeoutMs: 60000 }, () => {
    const input = U('h', j('8080/', colons(B + 1)), 'x')
    const copy = j('8080/', colons(B + 1))
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://h:', M, '@x'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, { sha256: '827b2be17a7b8a698f9d29b06b63da5104ea3fdac9f4d0269f8f019a016d164a', length: 8262 })
  })
})

describe('URL passwords: scheme edges', () => {
  test('1:// is no scheme', { timeoutMs: 60000 }, () => {
    const input = j('1', '://user:', PASS, '@host/')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('_a:// is no scheme (a word character before the letter)', { timeoutMs: 60000 }, () => {
    const input = j('_a', '://user:', PASS, '@host/')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('9a:// is no scheme (a digit before the letter)', { timeoutMs: 60000 }, () => {
    const input = j('9a', '://user:', PASS, '@host/')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('.:// is no scheme', { timeoutMs: 60000 }, () => {
    const input = j('.', '://user:', PASS, '@host/')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('an empty scheme', { timeoutMs: 60000 }, () => {
    const input = j('://user:', PASS, '@host/')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('jdbc:postgresql:// reads the scheme postgresql', { timeoutMs: 60000 }, () => {
    const input = j('jdbc:postgresql', '://user:', PASS, '@host/')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('jdbc:postgresql://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('jdbc:postgresql://user:', M, '@host/\ncopy ', M))
  })
  test('-a:// starts a scheme at the letter', { timeoutMs: 60000 }, () => {
    const input = j('-a', '://user:', PASS, '@host/')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('-a://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('-a://user:', M, '@host/\ncopy ', M))
  })
  test('a1+b.c-d:// is a scheme', { timeoutMs: 60000 }, () => {
    const input = j('a1+b.c-d', '://user:', PASS, '@host/')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('a1+b.c-d://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('a1+b.c-d://user:', M, '@host/\ncopy ', M))
  })
})

describe('URL passwords: shapes', () => {
  test('an empty password', { timeoutMs: 60000 }, () => {
    const input = U('user', '')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('an empty user part', { timeoutMs: 60000 }, () => {
    const input = j('https://', ':', PASS, '@host/')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('no @ at all', { timeoutMs: 60000 }, () => {
    const input = j('https://user:', PASS, '/path')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('an @ only after whitespace', { timeoutMs: 60000 }, () => {
    const input = j('https://user:', PASS, ' mail @host')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('a single quote before the @', { timeoutMs: 60000 }, () => {
    const input = j('https://user:', PASS, "'", '@host/')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
    check(redact(probeInput), {}, probeInput)
  })
  test('two URLs with two passwords', { timeoutMs: 60000 }, () => {
    const input = j(U('a', PASS), ' ', U('b', PASS2))
    const copy = PASS2
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 2 }, j('https://a:', M, '@host/ https://b:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 2 }, j('https://a:', M, '@host/ https://b:', M, '@host/\ncopy ', M))
  })
  test('two URLs with the same password', { timeoutMs: 60000 }, () => {
    const input = j(U('a', PASS), '\n', U('b', PASS))
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 2 }, j('https://a:', M, '@host/\nhttps://b:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 2 }, j('https://a:', M, '@host/\nhttps://b:', M, '@host/\ncopy ', M))
  })
  test('a URL in quotes in a JSON line', { timeoutMs: 60000 }, () => {
    const input = j('{"url": "', U('user', PASS), '"}')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('{"url": "https://user:', M, '@host/"}'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('{"url": "https://user:', M, '@host/"}\ncopy ', M))
  })
  test('a URL in parentheses', { timeoutMs: 60000 }, () => {
    const input = j('(', U('user', PASS), ') more')
    const copy = PASS
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('(https://user:', M, '@host/) more'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('(https://user:', M, '@host/) more\ncopy ', M))
  })
  test('b://u:1? four thousand times, no @', { timeoutMs: 60000 }, () => {
    const input = 'b://u:1?'.repeat(4000)
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('b://u:1? four thousand times then 64 KB of text, no @', { timeoutMs: 60000 }, () => {
    const input = j('b://u:1?'.repeat(4000), 'a'.repeat(65536))
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('b://u:1? fifty times then z=1@x: a port with a query holding =', { timeoutMs: 60000 }, () => {
    const input = j('b://u:1?'.repeat(50), 'z=1@x')
    const first = redact(input)
    check(first, {}, input)
    check(redact(first.text), {}, input)
  })
  test('b://u:1? fifty times then z@x: a password', { timeoutMs: 60000 }, () => {
    const input = j('b://u:1?'.repeat(50), 'z@x')
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:1?b://u:', M, '@x'))
    check(redact(first.text), {}, first.text)
  })
})

describe('URL passwords: size', () => {
  test('a password of 1 MB of ordinary characters: hidden and propagated', { timeoutMs: 60000 }, () => {
    const input = U('user', mixed(1048576))
    const copy = mixed(1048576)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://user:', M, '@host/\ncopy ', M))
  })
  test('a password of 4 KB of ordinary characters', { timeoutMs: 60000 }, () => {
    const input = U('user', mixed(4096))
    const copy = mixed(4096)
    const probeInput = j(input, '\ncopy ', copy)
    const first = redact(input)
    check(first, { 'url-password': 1 }, j('https://user:', M, '@host/'))
    check(redact(first.text), {}, first.text)
    check(redact(probeInput), { 'url-password': 1 }, j('https://user:', M, '@host/\ncopy ', M))
  })
})

describe('URL password cost grows linearly with the input', () => {
  // WHY a ratio and no absolute time: the machine and the engine decide how fast one run is, but doubling the input must not much more than double the time. One warm-up run, then the
  // best of three for each size, so one slow run does not decide. 3x is the bound: a linear cost gives about 2x, a quadratic one about 4x.
  const timed = (text: string): number => {
    const started = performance.now()
    redact(text)
    return performance.now() - started
  }
  const best = (text: string): number => Math.min(timed(text), timed(text), timed(text))
  const grows = (small: string, large: string): boolean => {
    timed(small)
    const smallMs = best(small)
    const largeMs = best(large)
    return largeMs <= 3 * smallMs
  }
  test('a password of 512 KB, then of 1 MB: the time at most triples', { timeoutMs: 120000 }, () => {
    expect(grows(U('user', mixed(512 * 1024)), U('user', mixed(1024 * 1024)))).toBe(true)
  })
  test('b://u:1? repeated N times then text of 8 characters per repeat, then 2N times: the time at most triples', { timeoutMs: 120000 }, () => {
    expect(grows(j('b://u:1?'.repeat(16000), 'a'.repeat(128000)), j('b://u:1?'.repeat(32000), 'a'.repeat(256000)))).toBe(true)
  })
})
