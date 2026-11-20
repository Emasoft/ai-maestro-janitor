// Tests of the payment-card pass (cards.ts), one test per rule and form, the known misses pinned as they are today, and a timing pin.
// WHY every card-shaped number is built at run time: the privacy and secret scans read source text, so no 13-digit-or-longer literal may stand in a tracked file. cardNumber() starts from a short issuer prefix, pads with a filler and appends the Luhn check digit; luhnValid() below is a second, differently written check that the fixtures really are valid.
import { describe, expect, test } from 'claude-code/testing'

import { findCards, redactCards } from '../cards'
import { mark } from '../patterns'

import { measureLinear, minMs } from './load/timing'

const M = mark('payment-card')
const one = { 'payment-card': 1 }

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
// The second check: sum every digit, doubling each second one from the right (a doubled digit is added as its own digits).
const luhnValid = (d: string): boolean =>
  [...d].reverse().map((c, i) => (i % 2 === 1 ? String(Number(c) * 2) : c)).join('').split('').reduce((a, c) => a + Number(c), 0) % 10 === 0

const VISA13 = cardNumber('4', 13, '6137')
const VISA16 = cardNumber('4', 16, '7391')
const VISA19 = cardNumber('4', 19, '5284')
const MC16 = cardNumber('52', 16, '3081')
const AMEX15 = cardNumber('37', 15, '8142')
const DINERS14 = cardNumber('36', 14, '5927')
const group = (d: string, sizes: number[], sep: string): string => {
  const parts: string[] = []
  let at = 0
  for (const s of sizes) {
    parts.push(d.slice(at, at + s))
    at += s
  }
  return parts.join(sep)
}
const r = (text: string) => redactCards(text)
const unchanged = (text: string) => expect(r(text)).toEqual({ text, hits: {} })

describe('card pass: the fixtures', () => {
  test('every fixture is Luhn-valid by a second, independent check and has its length', () => {
    for (const [d, n] of [[VISA13, 13], [VISA16, 16], [VISA19, 19], [MC16, 16], [AMEX15, 15], [DINERS14, 14]] as const) {
      expect(d.length).toBe(n)
      expect(luhnValid(d)).toBe(true)
    }
  })
})

describe('card pass: forms that are hidden', () => {
  test('a bare run of 16 digits is hidden and counts one hit', () => {
    expect(r(`card ok ${VISA16} end`)).toEqual({ text: `card ok ${M} end`, hits: one })
  })
  test('a bare run of 13 and a bare run of 15 digits are hidden', () => {
    expect(r(`a ${VISA13} b ${AMEX15} c`)).toEqual({ text: `a ${M} b ${M} c`, hits: { 'payment-card': 2 } })
  })
  test('a spaced 4-4-4-4 number is hidden whole', () => {
    expect(r(`x ${group(VISA16, [4, 4, 4, 4], ' ')} y`)).toEqual({ text: `x ${M} y`, hits: one })
  })
  test('a dashed 4-4-4-4 number is hidden whole', () => {
    expect(r(`x ${group(MC16, [4, 4, 4, 4], '-')} y`)).toEqual({ text: `x ${M} y`, hits: one })
  })
  test('an American Express 4-6-5 number is hidden whole', () => {
    expect(r(`amex ${group(AMEX15, [4, 6, 5], ' ')}.`)).toEqual({ text: `amex ${M}.`, hits: one })
  })
  test('a Diners Club 4-6-4 number is hidden whole', () => {
    expect(r(`(${group(DINERS14, [4, 6, 4], '-')})`)).toEqual({ text: `(${M})`, hits: one })
  })
  test('a 19-digit Visa grouped 4-4-4-4-3 is hidden whole, with no card word', () => {
    expect(r(`n=${group(VISA19, [4, 4, 4, 4, 3], ' ')}`)).toEqual({ text: `n=${M}`, hits: one })
  })
  test('a bare 16-digit run followed by an expiry or a CVV is hidden alone, the tail stays visible', () => {
    expect(luhnValid(VISA16 + '123')).toBe(false)
    expect(r(`card ${VISA16} 12/25`)).toEqual({ text: `card ${M} 12/25`, hits: one })
    expect(r(`card ${VISA16} 123`)).toEqual({ text: `card ${M} 123`, hits: one })
    expect(r(`card ${VISA16} 1234`)).toEqual({ text: `card ${M} 1234`, hits: one })
  })
  test('a grouped 4-4-4-4 number followed by an expiry or a CVV is hidden alone, the tail stays visible', () => {
    // The 19-digit reading (4-4-4-4-3) is tried first; it fails Luhn here, so the 4-4-4-4 prefix is hidden and the 3 digits stay.
    expect(luhnValid(VISA16 + '123')).toBe(false)
    const g = group(VISA16, [4, 4, 4, 4], ' ')
    expect(r(`card ${g} 12/25`)).toEqual({ text: `card ${M} 12/25`, hits: one })
expect(r(`card ${g} 123`)).toEqual({ text: `card ${M} 123`, hits: one })
    expect(r(`card ${g} 1225`)).toEqual({ text: `card ${M} 1225`, hits: one })
    expect(r(`card ${group(VISA16, [4, 4, 4, 4], '-')}-1225`)).toEqual({ text: `card ${M}-1225`, hits: one })
    expect(r(`card ${group(VISA16, [4, 4, 4, 4], '-')}-123`)).toEqual({ text: `card ${M}-123`, hits: one })
    expect(r(`card ${g}-123`)).toEqual({ text: `card ${M}-123`, hits: one })
  })
  test('a 4-6-5 number followed by a CVV or a group of 4 digits is hidden alone, the tail stays visible, and by two groups of 4 it is not hidden', () => {
expect(r(`amex ${group(AMEX15, [4, 6, 5], ' ')} 1234`)).toEqual({ text: `amex ${M} 1234`, hits: one })
    unchanged(`amex ${group(AMEX15, [4, 6, 5], ' ')} 1234 5678`)
    expect(r(`amex ${group(AMEX15, [4, 6, 5], ' ')} 123`)).toEqual({ text: `amex ${M} 123`, hits: one })
  })
  test('the longest grouping is tried first: a Luhn-valid 4-4-4-4-3 number is hidden whole, with no digit left', () => {
    expect(luhnValid(VISA19)).toBe(true)
    expect(r(`card ${group(VISA19, [4, 4, 4, 4, 3], ' ')} 12/25`)).toEqual({ text: `card ${M} 12/25`, hits: one })
  })
  test('two numbers on two lines are two hits', () => {
    expect(r(`${VISA16}\n${group(MC16, [4, 4, 4, 4], ' ')}\n`)).toEqual({ text: `${M}\n${M}\n`, hits: { 'payment-card': 2 } })
  })
  test('a second run over its own output hides nothing more', () => {
    const once = r(`card ${VISA16}`)
    expect(r(once.text)).toEqual({ text: once.text, hits: {} })
  })
  test('findCards gives the span of the number and nothing around it', () => {
    const text = `id ${group(VISA16, [4, 4, 4, 4], ' ')}, ok`
    const spans = findCards(text)
    expect(spans.length).toBe(1)
    expect(text.slice(spans[0].start, spans[0].end)).toBe(group(VISA16, [4, 4, 4, 4], ' '))
  })
  test('the empty text gives itself and no hit', () => {
    expect(r('')).toEqual({ text: '', hits: {} })
  })
})

describe('card pass: forms that are not hidden', () => {
  test('mixed separators are not hidden, in either order', () => {
    unchanged(`x ${VISA16.slice(0, 4)} ${VISA16.slice(4, 8)}-${VISA16.slice(8, 12)} ${VISA16.slice(12)} y`)
    unchanged(`x ${VISA16.slice(0, 4)}-${VISA16.slice(4, 8)} ${VISA16.slice(8, 12)}-${VISA16.slice(12)} y`)
  })
  test('a float fraction, 0 and a dot and the digits, is not hidden, the same digits after a comma are', () => {
    unchanged(`{"small":0.${VISA16}}`)
    expect(r(`{"small":0,${VISA16}}`).hits).toEqual(one)
  })
  test('a 19-digit u64 after "rustc": is not hidden', () => {
    unchanged(`{"rustc":${VISA19},"target":${VISA19}}`)
  })
  test('a process-listing line (pid, parent pid, elapsed time) is not hidden', () => {
    // 5 + 5 + 2 digits with spaces, then a dash and 2 digits: 14 digits that pass issuer and Luhn, the shape the old rule hid.
    const a = DINERS14.slice(0, 5)
    const b = DINERS14.slice(5, 10)
    const c = DINERS14.slice(10, 12)
    const d = DINERS14.slice(12)
    unchanged(`${a} ${b} ${c}-${d}:12:34 /usr/bin/zsh`)
  })
  test('a run inside a word or an identifier is not hidden', () => {
    unchanged(`abc${VISA16}`)
    unchanged(`${VISA16}xyz`)
    unchanged(`id_${VISA16}`)
    unchanged(`${VISA16}_1`)
  })
  test('a run that continues into a longer chain is not hidden', () => {
    unchanged(`${VISA16}7`)
    unchanged(`7 ${group(VISA16, [4, 4, 4, 4], ' ')}`)
    unchanged(`${group(VISA16, [4, 4, 4, 4], ' ')} ${VISA16.slice(0, 4)} ${VISA16.slice(4, 8)}`)
    unchanged(`${group(VISA16, [4, 4, 4, 4], ' ')} 1234 5678`)
    unchanged(`${group(VISA16, [4, 4, 4, 4], '-')}-1234-5678`)
    unchanged(`7777 8888-${group(VISA16, [4, 4, 4, 4], ' ')}`)
    unchanged(`7777-8888 ${group(VISA16, [4, 4, 4, 4], ' ')}`)
  })
  test('a number that fails Luhn is not hidden', () => {
    const bad = VISA16.slice(0, 15) + String((Number(VISA16[15]) + 1) % 10)
    expect(luhnValid(bad)).toBe(false)
    unchanged(`card ${bad}`)
  })
  test('a number with no known issuer prefix is not hidden even when it is Luhn-valid', () => {
    const odd = cardNumber('9', 16, '2468')
    expect(luhnValid(odd)).toBe(true)
    unchanged(`card ${odd}`)
  })
  test('a number whose length does not fit its issuer is not hidden', () => {
    const amex16 = cardNumber('37', 16, '8142')
    expect(luhnValid(amex16)).toBe(true)
    unchanged(`card ${amex16}`)
  })
  test('a run of 12 digits is not hidden', () => {
    unchanged(`card ${cardNumber('4', 12, '6137')}`)
  })
  test('a report-sanitizer parked sentinel is unchanged', () => {
    unchanged('[REDACTED-' + 'a1b2c3d4e5f6' + '-12]')
    unchanged('[REDACTED-' + '123456789012' + '-12]')
    unchanged('[JANITOR-REDACTED:rs' + 'a1b2c3d4e5f6' + 'x12]')
  })
})

describe('card pass: a bare run of 17 to 19 digits needs a card word', () => {
  test('a 19-digit run with card before it is hidden, in either case and with a name like card_number', () => {
    expect(r(`card ${VISA19}`)).toEqual({ text: `card ${M}`, hits: one })
    expect(r(`CARD: ${VISA19}`)).toEqual({ text: `CARD: ${M}`, hits: one })
    expect(r(`card_number=${VISA19}`)).toEqual({ text: `card_number=${M}`, hits: one })
    expect(r(`Visa ${VISA19}`).hits).toEqual(one)
  })
  test('each card word lets a 19-digit run through', () => {
    for (const w of ['card', 'credit', 'debit', 'visa', 'mastercard', 'amex']) expect(r(`${w} ${VISA19}`).hits).toEqual(one)
  })
  test('a card word 40 characters before the run is too far', () => {
    unchanged(`card${' '.repeat(40)}${VISA19}`)
  })
  test('a card word exactly 32 characters before the run counts, 33 does not', () => {
    // The window is the 32 characters before the run: the word and the gap together must fit in it.
    expect(r(`card${' '.repeat(28)}${VISA19}`).hits).toEqual(one)
    unchanged(`card${' '.repeat(29)}${VISA19}`)
    // The same edge with text before the word, so the slice is the full 34 characters.
    expect(r(`x card${' '.repeat(28)}${VISA19}`).hits).toEqual(one)
    unchanged(`x card${' '.repeat(29)}${VISA19}`)
  })
  test('a card word on the previous line does not count', () => {
    unchanged(`card\n${VISA19}`)
  })
  test('a card word inside a longer word does not count', () => {
    unchanged(`cardinal ${VISA19}`)
    unchanged(`discard ${VISA19}`)
unchanged(`creditcard ${VISA19}`)
    unchanged(`ncard ${VISA19}`)
    unchanged(`end\\xcard ${VISA19}`)
  })
  test('a card word right after a literal backslash escape (backslash and n, r or t) counts, the groups1.txt shape', () => {
    // The shape of a pytest failure dump: the text holds backslash-n before each card word.
    expect(r(`card ${VISA16} end\\ncard ${VISA19} end`)).toEqual({ text: `card ${M} end\\ncard ${M} end`, hits: { 'payment-card': 2 } })
    expect(r(`x\\ncard ${VISA19}`)).toEqual({ text: `x\\ncard ${M}`, hits: one })
    expect(r(`x\\rcard ${VISA19}`).hits).toEqual(one)
    expect(r(`x\\tcard ${VISA19}`).hits).toEqual(one)
    expect(r(`x\\\\ncard ${VISA19}`).hits).toEqual(one)
    expect(r(`x\\nvisa ${VISA19}`).hits).toEqual(one)
  })
  test('an uppercase escape letter counts too: backslash, N and card before a 19-digit run is hidden (the i flag is intended)', () => {
    expect(r(`x\\Ncard ${VISA19}`)).toEqual({ text: `x\\Ncard ${M}`, hits: one })
  })
  test('a card word after a backslash escape is held to the same 32-character window: 32 counts, 33 does not', () => {
    expect(r(`\\ncard${' '.repeat(28)}${VISA19}`).hits).toEqual(one)
    unchanged(`\\ncard${' '.repeat(29)}${VISA19}`)
  })
  test('a 17 or 18 digit run follows the same rule', () => {
    const v17 = cardNumber('65', 17, '4207')
    const v18 = cardNumber('6011', 18, '4207')
    expect(r(`card ${v17} and card ${v18}`).hits).toEqual({ 'payment-card': 2 })
    unchanged(`x ${v17} y ${v18}`)
  })
  test('KNOWN MISS card-bare-run-17-to-19-without-card-word: a bare 17 to 19 digit card number with no card word near it is not hidden, with a card word it is', () => {
    unchanged(`ref ${VISA19} end`)
    expect(r(`card ${VISA19} end`).hits).toEqual(one)
  })
  test('KNOWN MISS card-non-standard-grouping: a card number grouped 4-4-5 is not hidden, in a standard grouping or as a bare run it is', () => {
    unchanged(`card ${group(VISA13, [4, 4, 5], ' ')}`)
    expect(r(`card ${VISA13}`).hits).toEqual(one)
    expect(r(`card ${group(VISA16, [4, 4, 4, 4], ' ')}`).hits).toEqual(one)
  })
  test('KNOWN MISS card-word-too-far-or-not-listed: a 19-digit card number with its card word 40 characters before it, or with a word that is not in the list, is not hidden, with the word within 32 characters it is', () => {
    unchanged(`card${' '.repeat(40)}${VISA19}`)
    unchanged(`payment ${VISA19}`)
    unchanged(`ncard ${VISA19}`)
    expect(r(`x\\ncard ${VISA19}`).hits).toEqual(one)
    expect(r(`card ${VISA19}`).hits).toEqual(one)
  })
  test('KNOWN MISS card-after-digit-and-separator: a card number that follows a digit group and a separator is not hidden, on its own it is', () => {
    unchanged(`7777 ${VISA16}`)
    unchanged(`7777 8888-${group(VISA16, [4, 4, 4, 4], ' ')}`)
    unchanged(`2026-11-17 ${VISA16}`)
    expect(r(`x ${VISA16}`).hits).toEqual(one)
  })
  test('KNOWN MISS card-after-dot: a card number right after a dot is not hidden, after a comma it is', () => {
    unchanged(`end.${VISA16}`)
    expect(r(`end,${VISA16}`).hits).toEqual(one)
  })
  test('KNOWN MISS card-grouped-followed-by-two-groups: a 4-4-4-4 card number followed by two more groups of 4 digits is not hidden, followed by one group it is', () => {
    const g = group(VISA16, [4, 4, 4, 4], ' ')
    unchanged(`card ${g} 1234 5678`)
    expect(r(`card ${g} 1234`).hits).toEqual(one)
  })
  test('KNOWN MISS card-glued-to-letter-or-underscore: a card number glued to a letter or an underscore, or after the n of a JSON-escaped line break, is not hidden, after a space it is', () => {
    unchanged(`${VISA16}x`)
    unchanged(`${VISA16}_old`)
    unchanged(`${group(VISA16, [4, 4, 4, 4], ' ')}x`)
    unchanged(`${group(VISA16, [4, 4, 4, 4], ' ')}_old`)
    unchanged(`end\\n${VISA16}`)
    expect(r(`end ${VISA16}`).hits).toEqual(one)
  })
})

describe('card pass: timing', () => {
  // WHY 256 KB and 100 ms: the scan reads each character once, so a text this size takes a few milliseconds; a quadratic scan would take seconds. These four are the shapes that made the old regex rule backtrack: one long digit run, digits split by spaces, digits split by dashes, and a long valid-looking grouped run.
  const grouped = group(VISA16, [4, 4, 4, 4], ' ') + ' '
  const inputs: Array<[string, string]> = [
    ['256 KB of digits', '1'.repeat(262144)],
    ['256 KB of "1 " repeated', '1 '.repeat(131072)],
    ['256 KB of "1-" repeated', '1-'.repeat(131072)],
    ['256 KB of a long valid-looking grouped run', grouped.repeat(Math.floor(262144 / grouped.length))],
  ]
  // WHY the minimum of 5 timed runs after a warm-up (minMs): load and a cold JIT only add time, so one slow run must not fail the bound (TRDD-5J3ITQXY); a quadratic scan takes seconds, so the bound keeps its 100 ms.
  for (const [name, text] of inputs) {
    test(`${name} takes under 100 ms`, () => {
      expect(minMs(() => r(text).text.length, 5).ms).toBeLessThan(100)
    })
  }
  // WHY a growth check for this input only (TRDD-5J3ITQXY): its true cost is about 3 ms, so the 100 ms bound sat at 30 times its cost in an idle run but was measured at 79 ms (min of 5) under load, and a bound this close to the cost fails with load. measureLinear
  // compares 256 KB with 2 MB of the same line (8x; linear about 8, quadratic about 64, limit 20.8) from interleaved minima, so load cancels. The title predates the migration: the check is now the verdict, and only 'linear' passes.
  test('256 KB of valid cards, one per line takes under 100 ms', { timeoutMs: 120000 }, () => {
    const t = measureLinear((text) => r(text).text.length, (size) => `${VISA16}\n`.repeat(Math.floor(size / (VISA16.length + 1))), 262144, 2097152)
    expect(t.verdict, `cards one per line growth: ratio ${t.ratio.toFixed(2)}, sizes ${t.smallSize}-${t.bigSize}, ${t.rounds} rounds`).toBe('linear')
  })
  test('the one-card-per-line text hides every card', () => {
    const text = `${VISA16}\n`.repeat(100)
    expect(r(text).hits).toEqual({ 'payment-card': 100 })
  })
})
