import { expect, test } from 'claude-code/testing'

import { buildKnownIndex, KnownIndexError, MIN_KNOWN_LENGTH, redactKnown, redactKnownDeep, type KnownSecret } from '../known'
import { SHIELD_MARKER, shieldMarker } from '../marker'
import { mark, redact } from '../patterns'

import { minMs } from './load/timing'

// Known-value redaction (TRDD-DSXC9MP9 increment 1). Every value here is built from fragments at run time, so no line of this file holds a whole value.
const j = (...parts: string[]) => parts.join('')
const U1 = j('0b1e2c3d-4e5f-', '4a6b-8c7d-9e0f1a2b3c4d')
const U2 = j('1a2b3c4d-5e6f-', '4071-9a8b-7c6d5e4f3a2b')
const U3 = j('2c3d4e5f-6a7b-', '4c8d-a9e0-f1a2b3c4d5e6')
// A password no pattern rule recognises: only the vault knows it is a secret.
const PLAIN = j('quartz', '-lantern-', '7731')
const known = (...rows: KnownSecret[]) => buildKnownIndex(rows).index

test('a vault value that no rule finds is hidden behind the marker of its row', () => {
  const text = j('login ok for ', PLAIN, ' at 10:02')
  expect(redact(text).hits).toEqual({})
  const done = redactKnown(text, known({ uuid: U1, kind: 'password', value: PLAIN }))
  expect(done.text).toBe(j('login ok for ', shieldMarker('password', U1), ' at 10:02'))
  expect(done.hits).toEqual({ password: 1 })
})

test('every copy is hidden, a process list line included', () => {
  const ps = j('sh -c sleep 20; : ', PLAIN, '\ncurl -H x-key:', PLAIN, ' https://api.example.test')
  const done = redactKnown(ps, known({ uuid: U1, kind: 'password', value: PLAIN }))
  expect(done.text).toBe(j('sh -c sleep 20; : ', shieldMarker('password', U1), '\ncurl -H x-key:', shieldMarker('password', U1), ' https://api.example.test'))
  expect(done.text).not.toContain(PLAIN)
  expect(done.hits).toEqual({ password: 2 })
})

test('of two values that start at one place the longer hides whole, under its own marker', () => {
  const longer = j(PLAIN, '-tail9')
  const done = redactKnown(j('a ', longer, ' b'), known({ uuid: U1, kind: 'password', value: PLAIN }, { uuid: U2, kind: 'api-key', value: longer }))
  expect(done.text).toBe(j('a ', shieldMarker('api-key', U2), ' b'))
  expect(done.hits).toEqual({ 'api-key': 1 })
})

test('a shorter value inside a longer one is hidden by the longer one', () => {
  const longer = j('pre9-', PLAIN, '-post9')
  const done = redactKnown(j('[', longer, ']'), known({ uuid: U1, kind: 'password', value: PLAIN }, { uuid: U2, kind: 'api-key', value: longer }))
  expect(done.text).toBe(j('[', shieldMarker('api-key', U2), ']'))
})

test('two values that overlap are hidden together: one span over both, nothing of either is left, both markers in order', () => {
  const a = j('abcd', '1234', 'wxyz')
  const b = j('wxyz', '5678', 'efgh')
  const index = known({ uuid: U1, kind: 'k1', value: a }, { uuid: U2, kind: 'k2', value: b })
  const text = j('<', 'abcd1234', 'wxyz', '5678efgh', '>')
  // WHY the spans are checked and not only the text: two separate overlapping spans happen to print the same text here, so only the span list tells a merge from no merge.
  expect(index.spans(text, 0, text.length)).toEqual([[1, 21, 0, 1]])
  const done = redactKnown(text, index)
  expect(done.text).toBe(j('<', shieldMarker('k1', U1), shieldMarker('k2', U2), '>'))
  expect(done.hits).toEqual({ k1: 1, k2: 1 })
})

test('a value that overlaps its own copy is hidden as one span with one marker', () => {
  const v = j('ab', 'ab', 'ab', 'ab')
  const done = redactKnown(j('x', 'ababababab', 'y'), known({ uuid: U1, kind: 'k1', value: v }))
  expect(done.text).toBe(j('x', shieldMarker('k1', U1), 'y'))
})

test('a marker already in the text is copied as it is, also when a value equals part of it', () => {
  const insideUuid = U1.slice(9, 18)
  const insideKind = 'github-token'
  const index = known({ uuid: U2, kind: 'k1', value: insideUuid }, { uuid: U3, kind: 'k2', value: insideKind })
  const vaultMarker = shieldMarker('github-token', U1)
  const text = j(vaultMarker, ' ', mark('github-token'), ' then ', insideUuid, ' and ', insideKind)
  const done = redactKnown(text, index)
  expect(done.text).toBe(j(vaultMarker, ' ', mark('github-token'), ' then ', shieldMarker('k1', U2), ' and ', shieldMarker('k2', U3)))
  expect(done.hits).toEqual({ k1: 1, k2: 1 })
})

test('a value shorter than the floor is left out of the index and counted', () => {
  const short = PLAIN.slice(0, MIN_KNOWN_LENGTH - 1)
  const built = buildKnownIndex([{ uuid: U1, kind: 'password', value: short }, { uuid: U2, kind: 'password', value: '' }])
  expect(built.skipped).toBe(2)
  expect(built.index.size).toBe(0)
  expect(redactKnown(j('x ', short, ' y'), built.index).text).toBe(j('x ', short, ' y'))
})

test('when two rows hold one value, the first row names the marker', () => {
  const built = buildKnownIndex([{ uuid: U1, kind: 'password', value: PLAIN }, { uuid: U2, kind: 'api-key', value: PLAIN }])
  expect(built.index.size).toBe(1)
  expect(redactKnown(PLAIN, built.index).text).toBe(shieldMarker('password', U1))
})

test('a row whose uuid or kind cannot be written in a marker is refused with fixed text that never holds the value', () => {
  const tries = [
    { uuid: U1.toUpperCase(), kind: 'password', value: PLAIN },
    { uuid: j('0b1e2c3d-4e5f-', '1a6b-8c7d-9e0f1a2b3c4d'), kind: 'password', value: PLAIN },
    { uuid: U1, kind: 'pass word', value: PLAIN },
    { uuid: U1, kind: 'x]', value: PLAIN },
  ]
  for (const row of tries) {
    let caught: unknown
    try {
      buildKnownIndex([row])
    } catch (error) {
      caught = error
    }
    expect(caught).toBeInstanceOf(KnownIndexError)
    expect(String((caught as Error).message)).not.toContain(PLAIN)
  }
})

test('the marker pattern reads back the kind and uuid of the marker it writes, and refuses a uuid that is not version 4', () => {
  const exact = new RegExp('^' + SHIELD_MARKER + '$')
  const read = exact.exec(shieldMarker('github-token', U1))
  expect(read?.[1]).toBe('github-token')
  expect(read?.[2]).toBe(U1)
  expect(exact.test(shieldMarker('github-token', j('0b1e2c3d-4e5f-', '1a6b-8c7d-9e0f1a2b3c4d')))).toBe(false)
})

test('a structured result keeps its shape, and one with nothing to hide comes back as the same object', () => {
  const index = known({ uuid: U1, kind: 'password', value: PLAIN })
  const result = { stdout: j('pw=', PLAIN), stderr: '', interrupted: false, nested: [{ line: PLAIN }] }
  const done = redactKnownDeep(result, index)
  expect(done.value).toEqual({ stdout: j('pw=', shieldMarker('password', U1)), stderr: '', interrupted: false, nested: [{ line: shieldMarker('password', U1) }] })
  expect(done.hits).toEqual({ password: 2 })
  const clean = { stdout: 'ok', stderr: '', interrupted: false }
  expect(redactKnownDeep(clean, index).value).toBe(clean)
})

test('an empty index changes nothing', () => {
  const text = j('x ', PLAIN)
  expect(redactKnown(text, known()).text).toBe(text)
  expect(redactKnownDeep({ a: text }, known()).hits).toEqual({})
})

// WHY minMs N=3 and timeoutMs 60000: the single-shot timings (Date.now) flaked under host load (TRDD-5J3ITQXY); 2 phases x (1 warm-up + 3 timed runs + 1 untimed correctness call) at the 5000 ms bound is 50 s worst case, over the old 20000. The bounds stay 5000 ms; the hit and text assertions run on separate untimed calls.
test('the time is linear in the text: 2000 values over 1 MB, and a 512 KB run of one character against values made of it', { timeoutMs: 60000 }, () => {
  const hex = (n: number) => n.toString(16).padStart(8, '0')
  const rows: KnownSecret[] = []
  for (let n = 0; n < 2000; n++) rows.push({ uuid: U1, kind: 'k', value: j('v', hex(n * 7919), hex(n * 104729), hex(n)) })
  const filler = 'lorem ipsum dolor sit amet, '.repeat(37450)
  const text = j(filler.slice(0, 500000), rows[17]!.value, filler.slice(0, 500000), rows[1999]!.value)
  const wide = minMs(() => redactKnown(text, known(...rows)).text.length, 3).ms
  expect(redactKnown(text, known(...rows)).hits).toEqual({ k: 2 })

  const runs: KnownSecret[] = []
  for (let n = MIN_KNOWN_LENGTH; n < MIN_KNOWN_LENGTH + 40; n++) runs.push({ uuid: U2, kind: 'k', value: 'a'.repeat(n) })
  const flatText = 'a'.repeat(512 * 1024)
  const deep = minMs(() => redactKnown(flatText, known(...runs)).text.length, 3).ms
  expect(redactKnown(flatText, known(...runs)).text).toBe(shieldMarker('k', U2))

  // WHY the bound is generous: it is far under the 10 s hook limit, so a machine under load does not turn it red; a quadratic walk takes minutes here, not seconds.
  expect(wide).toBeLessThan(5000)
  expect(deep).toBeLessThan(5000)
})
