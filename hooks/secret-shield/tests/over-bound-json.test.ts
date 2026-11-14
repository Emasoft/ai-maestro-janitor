import { describe, expect, test } from 'claude-code/testing'

import { countOf, JSON_ESCAPE_BOUND, mark, redact } from '../patterns'

// WHY this file (TRDD-MC895I0A): the over-bound JSON detector lost its regex lookahead and counts the escape pairs of a value in its own walk. These tests pin what the lookahead
// version did, in the places where the rewrite could differ: pairs that share a quote, the bound itself, and every way a value can end. Each expected text is exact, and each was
// checked against the lookahead version (patterns.ts as it was before TRDD-MC895I0A) as well as the rewrite. No test asserts a timing.
// Fake values are made at run time with a different one on every call, so no scanner mistakes this file for a leak and a test cannot pass because another value was hidden before it.
const j = (...parts: string[]) => parts.join('')
const ALNUM = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
let fakeCount = 0
const fake = (length = 24): string => {
  fakeCount += 1
  const tail = Array.from({ length }, () => ALNUM[Math.floor(Math.random() * ALNUM.length)]).join('')
  return `Zq${String(fakeCount).padStart(3, '0')}${tail}`.slice(0, length)
}
const BOUND = JSON_ESCAPE_BOUND
const UNIT = ['aB3\\n', 'cD4\\t', 'eF5\\\\', 'gH6\\"', 'iJ7\\/']
// `n` escape pairs of five mixed kinds, each after three ordinary characters.
const escapes = (n: number) => UNIT.join('').repeat(Math.floor(n / UNIT.length)) + UNIT.slice(0, n % UNIT.length).join('')
// `n` escape pairs after a value with a space in it: below the bound the regex path reads it and looksSecret refuses it (a quoted value with whitespace is no secret),
// so only the fail-closed pass over the bound hides it, which makes the bound itself visible in the output.
const spaced = (n: number) => j('a b', '\\n'.repeat(n))
const M = mark('assignment')
// U+2028 and U+2029 are line ends to the regex `.` and `$`, so a backslash before one cannot pair; written with fromCharCode so no raw separator sits in this file.
const LS = String.fromCharCode(0x2028)
const PS = String.fromCharCode(0x2029)

describe('pairs that share a quote with the value before them', () => {
  test('a non-secret pair whose value is the name of a secret pair: `"x":"token":"` then more than the bound of pairs hides the second value', { timeoutMs: 60000 }, () => {
    const r = redact(j('{"x":"token":"', fake(), escapes(BOUND + 1), '"}'))
    expect(r.hits).toEqual({ assignment: 1 })
    expect(r.text === j('{"x":"token":"', M, '"}')).toBe(true)
  })
  test('a secret-named pair whose value is the name of a secret pair: `"api_key":"token":"` then more than the bound of pairs, the first walk ends at the quote with no pair and the second pair is still found', { timeoutMs: 60000 }, () => {
    const r = redact(j('{"api_key":"token":"', fake(), escapes(BOUND + 1), '"}'))
    expect(r.hits).toEqual({ assignment: 1 })
    expect(r.text === j('{"api_key":"token":"', M, '"}')).toBe(true)
  })
  test('a non-secret value over the bound ends at a quote that opens a secret pair: `"name":"<pairs>"token":"<pairs>"` hides only the second value', { timeoutMs: 60000 }, () => {
    const first = j(fake(), escapes(BOUND + 1))
    const r = redact(j('{"name":"', first, '"token":"', fake(), escapes(BOUND + 1), '"}'))
    expect(r.hits).toEqual({ assignment: 1 })
    expect(r.text === j('{"name":"', first, '"token":"', M, '"}')).toBe(true)
  })
  test('a secret-named value with exactly the bound of pairs, whose closing quote opens a secret pair over the bound: both are hidden, two hits', { timeoutMs: 60000 }, () => {
    const r = redact(j('{"api_key":"', fake(), escapes(BOUND), '"token":"', fake(), escapes(BOUND + 1), '"}'))
    expect(r.hits).toEqual({ assignment: 2 })
    expect(r.text === j('{"api_key":"', M, '"token":"', M, '"}')).toBe(true)
  })
})

describe('the bound itself', () => {
  test('a secret value with exactly the bound of pairs is read by the regex (a value with a space is no secret), one more pair is hidden by the pass', { timeoutMs: 60000 }, () => {
    // WHY the tail: a text with no more than the bound of backslashes returns before the pass walks anything, so one more backslash after the value makes the walk run on the bound itself.
    const tail = '", "z": "\\q"}'
    const atBound = j('{"api_key": "', spaced(BOUND), tail)
    const same = redact(atBound)
    expect(countOf(same.hits)).toBe(0)
    expect(same.text === atBound).toBe(true)
    const over = redact(j('{"api_key": "', spaced(BOUND + 1), tail))
    expect(over.hits).toEqual({ assignment: 1 })
    expect(over.text === j('{"api_key": "', M, tail)).toBe(true)
  })
  test('a secret value with a secret-looking lead is hidden with one hit at exactly the bound and at one more', { timeoutMs: 60000 }, () => {
    for (const n of [BOUND, BOUND + 1]) {
      const r = redact(j('{"api_key": "', fake(), escapes(n), '"}'))
      expect(r.hits).toEqual({ assignment: 1 })
      expect(r.text === j('{"api_key": "', M, '"}')).toBe(true)
    }
  })
  test('a lone backslash before a line end is not a pair: the bound of pairs and then one backslash is not over the bound, one more pair is', { timeoutMs: 60000 }, () => {
    for (const lineEnd of ['\n', '\r', LS, PS]) {
      const atBound = j('{"api_key": "', spaced(BOUND), '\\', lineEnd, '{"x": 1}')
      const same = redact(atBound)
      expect(countOf(same.hits)).toBe(0)
      expect(same.text === atBound).toBe(true)
      const over = redact(j('{"api_key": "', spaced(BOUND + 1), '\\', lineEnd, '{"x": 1}'))
      expect(over.hits).toEqual({ assignment: 1 })
      expect(over.text === j('{"api_key": "', M, '\\', lineEnd, '{"x": 1}')).toBe(true)
    }
  })
  test('a value over the bound under a name that is not a secret name is left unchanged', { timeoutMs: 60000 }, () => {
    const input = j('{"note": "', fake(), escapes(BOUND + 1), '"}')
    const r = redact(input)
    expect(countOf(r.hits)).toBe(0)
    expect(r.text === input).toBe(true)
  })
})

describe('a value over the bound ends where the regex value ends', () => {
  const secretValue = () => j(fake(), escapes(BOUND + 1))
  test('at a bare quote: the quote is kept', { timeoutMs: 60000 }, () => {
    const r = redact(j('{"api_key": "', secretValue(), '", "x": 1}'))
    expect(r.hits).toEqual({ assignment: 1 })
    expect(r.text === j('{"api_key": "', M, '", "x": 1}')).toBe(true)
  })
  test('at a line feed or a carriage return: the value stops there and the rest of the text is untouched', { timeoutMs: 60000 }, () => {
    for (const lineEnd of ['\n', '\r']) {
      const r = redact(j('{"api_key": "', secretValue(), lineEnd, '{"x": 1}'))
      expect(r.hits).toEqual({ assignment: 1 })
      expect(r.text === j('{"api_key": "', M, lineEnd, '{"x": 1}')).toBe(true)
    }
  })
  test('at a backslash before a line end: the value stops before the backslash, which is kept, and the line end after it', { timeoutMs: 60000 }, () => {
    for (const lineEnd of ['\n', '\r', LS, PS]) {
      const r = redact(j('{"api_key": "', secretValue(), '\\', lineEnd, '{"x": 1}'))
      expect(r.hits).toEqual({ assignment: 1 })
      expect(r.text === j('{"api_key": "', M, '\\', lineEnd, '{"x": 1}')).toBe(true)
    }
  })
  test('at the end of the text, with or without a last lone backslash', { timeoutMs: 60000 }, () => {
    const bare = redact(j('{"api_key": "', secretValue()))
    expect(bare.hits).toEqual({ assignment: 1 })
    expect(bare.text === j('{"api_key": "', M)).toBe(true)
    const lone = redact(j('{"api_key": "', secretValue(), '\\'))
    expect(lone.hits).toEqual({ assignment: 1 })
    expect(lone.text === j('{"api_key": "', M, '\\')).toBe(true)
  })
  test('a hidden value is followed by a second secret pair on the next line, which is hidden too', { timeoutMs: 60000 }, () => {
    const r = redact(j('{"api_key": "', secretValue(), '\n{"token": "', secretValue(), '"}'))
    expect(r.hits).toEqual({ assignment: 2 })
    expect(r.text === j('{"api_key": "', M, '\n{"token": "', M, '"}')).toBe(true)
  })
})
