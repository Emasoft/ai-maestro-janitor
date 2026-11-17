// Payment-card pass of the secret-shield core (TRDD-L1I0FP5T). Pure: no env read, no fs. Its own export, called by nobody yet: redact() and its hits are untouched, so the card rule is off in the live mod per the (e) default of the 19:52:56 approval-log line of the card.
// WHY it exists: report-sanitizer hid card numbers with one regex that matched any 13 to 19 digits with a space or a dash between any two of them. Measured 2026-11-16 on 50,487 text files it fired 240 times, 190 of them false (figures recorded in TRDD-L1I0FP5T): 180 cargo build hashes (u64 values of 17 to 19 digits), 8 float fractions (the digits after a decimal point) and 2 process-listing lines (pid, parent pid and elapsed time, whose spaces and dash crossed three columns). The 50 other hits were synthetic test cards. Each rule below removes one of those three false classes.
// Candidate rules (a candidate is then checked by issuerOk AND luhnOk, both required: Luhn alone passes about 1 digit run in 10, so a millisecond timestamp would be hidden):
//   1. A bare run of 13 to 16 digits is a candidate. A bare run of 17 to 19 digits is a candidate only when a card word (card, credit, debit, visa, mastercard, amex) stands whole within the 32 characters before it on the same line (whole: no letter or digit touches it, except that a literal backslash escape, a backslash and n, r or t, before it counts as a boundary). WHY: 23,599 of the 28,249 digit runs the old rule read were 19 digits, and a random u64 hash passes issuer and Luhn often enough to give the 180 false hits; a real card number written as one bare run of 17 to 19 digits is rare and nearly always has a word near it.
//   2. A grouped number uses ONE separator kind throughout (all spaces or all dashes) and only the groupings 4-4-4-4, 4-6-5, 4-6-4 and 4-4-4-4-3 (the printed layouts of the 16, 15 and 14 digit cards and of the 19 digit Visa). The longest grouping is tried first: 4-4-4-4 followed by a space and 3 digits is read as 4-4-4-4-3 and, if that is not a card, as the 4-4-4-4 prefix with the 3 digits left visible. WHY: a number is not a card because digits sit near spaces; "pid ppid hh-mm:ss" mixes both separators and has groups of 5, 5, 2, 2, and the old rule hid it.
//   3. The character before the candidate is not a letter, a digit, an underscore or a dot, and it is not a space or a dash that follows a digit. WHY the dot: the digits after "0." are a float fraction, not a number of their own (8 false hits). WHY the others: a number inside a word or an identifier, or the tail of a longer chain of digit groups, is not a card. Letters are ASCII on purpose, as in the old rule: a doubt hides more, not less.
//   4. The end. A bare run is complete where its digits end (the next character is not a letter or an underscore): a CVV or an expiry after it (12/25, 123) is its own text and stays visible, because card <16 digits> 123 is the usual printed form of a card. A grouped number is refused when it is followed by the SAME separator, a group of 4 or more digits and then the same separator and a digit again (two further groups: a longer grouped number, such as six groups of 4). One further group of 4 (an expiry written as month and year with no slash), a group of 1 to 3 digits (a CVV, an expiry month) or a different separator does not block it, and the tail stays visible. The next character after a bare or grouped number is not a letter or an underscore.
// WHY the card word accepts an underscore next to it (card_number, credit_card): that choice hides more, never less. "Whole word" here means no letter or digit touches it. An underscore is a word character in a regex, but a name such as card_number is the common way a card is written in code and logs, and the word only lets a candidate through to the issuer and Luhn checks, so it cannot hide a false match on its own.
// WHY a hand-written scan and not a regex: the old rule was one repeat over a group with an optional separator, and a pattern of that shape is what the CPV scanner reports as a ReDoS (REGEX_DOS, a publish blocker). The scan reads the text once from left to right: a start needs a digit that passes rule 3, then one chain is read to its end and the scan resumes there, so every character is read once and a text of 256 KB of digits, of "1 " or of "1-" takes one pass (tests/cards.test.ts pins it). The only regex is CARD_WORD, which runs on at most 33 characters and has no repeat.
// KNOWN MISSES, each pinned by a test titled "KNOWN MISS <slug>: ..." in tests/cards.test.ts and described in KNOWN-MISSES.md: a real card of 17 to 19 digits written as one bare run with no card word near it (card-bare-run-17-to-19-without-card-word); a card word more than 32 characters before the run, on an earlier line, or not in the word list (card-word-too-far-or-not-listed); a real card in a grouping that is not one of the four, 4-4-5 for example (card-non-standard-grouping); a real card that follows a digit group and a separator, such as a number or a date before it (card-after-digit-and-separator); a real card right after a dot (card-after-dot); a real card of 4 groups followed by two or more further groups of 4 or more digits (card-grouped-followed-by-two-groups); a real card glued to a letter or an underscore (card-glued-to-letter-or-underscore).
import { mark } from './patterns'
import type { Hits } from './patterns'

export type CardSpan = { start: number; end: number }

// WHY findCards and CardSpan are exported: only the span-level parity measurement of TRDD-L1I0FP5T uses them today, to compare spans with the report-sanitizer Python rule; redactCards is the one function callers use.

const isDigit = (c: number): boolean => c >= 48 && c <= 57
const isWord = (c: number): boolean => isDigit(c) || (c >= 65 && c <= 90) || (c >= 97 && c <= 122) || c === 95
const isSep = (c: number): boolean => c === 32 || c === 45
const GROUPINGS = new Set(['4-4-4-4', '4-6-5', '4-6-4', '4-4-4-4-3'])
// Window of the card word, in characters before the candidate. CONTEXT more characters are read before the window and used only as lookbehind, so that a word cut by the window is not taken for a whole one and a backslash escape in front of the word is seen: the slice is WINDOW + CONTEXT = 34 characters long at most, and a word counts only when it starts within the last 32 (match index at least slice length minus 32).
const CARD_WORD_WINDOW = 32
const CARD_WORD_CONTEXT = 2
// WHY the second lookbehind: a card word right after a literal backslash escape (a backslash and n, r or t, as in a JSON or Python string dump: end\ncard 4...) is a whole word, because the escape is a boundary, as the shield treats escapes elsewhere (TRDD-5VZTPXBJ). Without it the n of \n touches card and the 19-digit run after it was not hidden (the groups1.txt fixture of report-sanitizer, 2026-11-17). A plain ncard with no backslash is still not the word. It hides more, never less.
const CARD_WORD = /(?:(?<![A-Za-z0-9])|(?<=\\[nrt]))(?:card|credit|debit|visa|mastercard|amex)(?![A-Za-z0-9])/gi

// Ported from report-sanitizer sanitize_reports.py (luhn_ok, issuer_ok) so both tools judge a number the same way.
const luhnOk = (d: string): boolean => {
  let total = 0
  for (let i = 0; i < d.length; i++) {
    let v = d.charCodeAt(d.length - 1 - i) - 48
    if (i % 2 === 1) v = v > 4 ? v * 2 - 9 : v * 2
    total += v
  }
  return total % 10 === 0
}

// A known issuer prefix whose length matches. WHY both checks: Luhn alone passes about 1 in 10 random digit runs (a millisecond timestamp, an order number); the prefix and length check removes nearly all of them.
const issuerOk = (d: string): boolean => {
  const n = d.length
  const p2 = Number(d.slice(0, 2))
  const p3 = Number(d.slice(0, 3))
  const p4 = Number(d.slice(0, 4))
  if (d[0] === '4') return n === 13 || n === 16 || n === 19 // Visa
  if ((p2 >= 51 && p2 <= 55) || (p4 >= 2221 && p4 <= 2720)) return n === 16 // Mastercard
  if (p2 === 34 || p2 === 37) return n === 15 // American Express
  if (p4 === 6011 || (p3 >= 644 && p3 <= 649) || p2 === 65) return n >= 16 && n <= 19 // Discover
  if (p4 >= 3528 && p4 <= 3589) return n >= 16 && n <= 19 // JCB
  if ((p3 >= 300 && p3 <= 305) || p2 === 36 || p2 === 38) return n >= 14 && n <= 19 // Diners Club
  return false
}

const cardWordBefore = (text: string, start: number): boolean => {
  let from = start
  while (from > 0 && start - from < CARD_WORD_WINDOW + CARD_WORD_CONTEXT && text.charCodeAt(from - 1) !== 10 && text.charCodeAt(from - 1) !== 13) from--
  const slice = text.slice(from, start)
  for (const m of slice.matchAll(CARD_WORD)) if (m.index >= slice.length - CARD_WORD_WINDOW) return true
  return false
}

// Rules 1 and 4 for a bare run [start, end): complete where its digits end, so whatever follows after a separator (a CVV, an expiry) is not read. Returns end, or -1.
const bareEnd = (text: string, start: number, end: number): number => {
  const digits = end - start
  if (end < text.length && isWord(text.charCodeAt(end))) return -1
  const d = text.slice(start, end)
  // The card word is asked last, only for a run of 17 to 19 digits that already passed issuer and Luhn.
  return issuerOk(d) && luhnOk(d) && (digits <= 16 || cardWordBefore(text, start)) ? end : -1
}

const MAX_GROUPS = 5

// Rules 2 and 4 for a number whose first group of 4 digits ends at firstEnd. Reads at most MAX_GROUPS + 2 groups joined by the first separator, then tries the longest grouping first and falls back to a shorter prefix. Returns the end of the number, or -1.
const groupedEnd = (text: string, start: number, firstEnd: number): number => {
  const n = text.length
  const sep = firstEnd < n ? text.charCodeAt(firstEnd) : -1
  if (!isSep(sep)) return -1
  const sizes = [firstEnd - start]
  const ends = [firstEnd]
  let j = firstEnd
  // Two groups more than the longest grouping are read: the sizes of the next two decide whether a candidate is followed by a longer grouped number (a group of 4 or more digits and then one more group).
  while (sizes.length <= MAX_GROUPS + 1 && j + 1 < n && text.charCodeAt(j) === sep && isDigit(text.charCodeAt(j + 1))) {
    let k = j + 1
    while (k < n && isDigit(text.charCodeAt(k))) k++
    sizes.push(k - (j + 1))
    ends.push(k)
    j = k
  }
  for (let g = Math.min(sizes.length, MAX_GROUPS); g >= 3; g--) {
    if (!GROUPINGS.has(sizes.slice(0, g).join('-'))) continue
    const e = ends[g - 1]
    if (e < n && isWord(text.charCodeAt(e))) continue
    // The same separator, a group of 4 or more digits and then the same separator and a digit again: two further groups, a longer grouped number. One further group of 4 (an expiry written as month and year with no slash) or of 1 to 3 digits (a CVV, an expiry month) is not a reason to refuse; it stays visible.
    if (g + 1 < sizes.length && sizes[g] >= 4) continue
    const d = text.slice(start, e).replace(/[ -]/g, '')
    if (issuerOk(d) && luhnOk(d)) return e
  }
  return -1
}

/** Where the card numbers are: [start, end) spans over the text, left to right, never overlapping. */
export function findCards(text: string): CardSpan[] {
  const spans: CardSpan[] = []
  const n = text.length
  let i = 0
  while (i < n) {
    if (!isDigit(text.charCodeAt(i))) {
      i++
      continue
    }
    const before = i > 0 ? text.charCodeAt(i - 1) : -1
    // Rule 3. A start refused here costs one step; the digits that follow it are refused the same way, because each follows a digit or a separator after a digit.
    if (isWord(before) || before === 46 || (isSep(before) && i > 1 && isDigit(text.charCodeAt(i - 2)))) {
      i++
      continue
    }
    let firstEnd = i
    while (firstEnd < n && isDigit(text.charCodeAt(firstEnd))) firstEnd++
    const size = firstEnd - i
    let end = -1
    if (size >= 13 && size <= 19) end = bareEnd(text, i, firstEnd)
    else if (size === 4) end = groupedEnd(text, i, firstEnd)
    // Only the first run is skipped on a miss: the runs after it follow a digit and a separator, so rule 3 refuses them in one step each, and every character is still read a bounded number of times.
    if (end === -1) {
      i = firstEnd
    } else {
      spans.push({ start: i, end })
      i = end
    }
  }
  return spans
}

/** Hides every card number with the payment-card marker; the count is the number of numbers hidden. */
export function redactCards(text: string): { text: string; hits: Hits } {
  const spans = findCards(text)
  if (spans.length === 0) return { text, hits: {} }
  let out = ''
  let at = 0
  for (const s of spans) {
    out += text.slice(at, s.start) + mark('payment-card')
    at = s.end
  }
  return { text: out + text.slice(at), hits: { 'payment-card': spans.length } }
}
