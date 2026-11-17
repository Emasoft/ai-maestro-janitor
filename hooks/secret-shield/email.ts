// Email pass of the secret-shield core (TRDD-L1I0FP5T). Pure: no env read, no fs. Its own export, called by nobody yet: redact() and its hits are untouched, so the email rule is off in the live mod until a later increment wires it.
// WHY it exists: report-sanitizer hid email addresses with one regex (EMAIL in sanitize_reports.py). This pass reads the same addresses, span for span, with one difference (rule G below), as a hand-written scan. WHY not that regex: a local part followed by no at sign made it try every start of a long local-part run, and the domain part gave it nested repeats; measured on report-sanitizer HEAD (f2def51) on a loaded host (load average about 27) it took 0.25 to 0.35 s for 16 KB and 4 to 5 s for 64 KB on three shapes (a run of a-dot, a at sign then b-dot repeated, a at sign and b then c1-dot repeated), four times longer per doubling of the text. Its shape would match the CPV scanner's REGEX_DOS catalog (a publish blocker); no CPV run on that regex was made. The scan below reads each character a bounded number of times: it walks the at signs left to right, reads the local part backwards from the at sign to the end of the previous match and the domain forwards to the next character that is not a label character. tests/email.test.ts pins 256 KB of these shapes under 100 ms each. Measured 2026-11-17 in the shield runner: 0.2 to 45 ms per shape at a 1-minute load average of 12 to 15 (4 of 4 later runs passed at 15 to 18), but the shape of a at sign repeated took 109 and 189 ms in two runs at load 14 and 17 with other agents loading the host, so the pin is load-sensitive; it guards against a quadratic scan, which would take over a minute at this size.
// The rule, as report-sanitizer reads it (re.sub: the leftmost match, the scan resumes after each match, a visible match included):
//   1. The local part is the longest run of letters, digits and . _ % + - that ends right before the at sign and does not start before the end of the previous match. Empty: no address at this at sign.
//   2. The domain is labels of letters, digits and hyphens joined by single dots. The first label must not be empty. The address ends after the leading letters of the LAST label that starts with 2 or more ASCII letters (not the first label): this is what the regex does by backtracking. So a domain whose last label is a host then a letters-and-digits tail ends after the letters, and what follows them (the digit) stays visible; a double dot ends the labels.
//   3. A matched address stays visible, and still counts as the end of the previous match, when its lowercased domain is the GitHub no-reply domain, or example.com or example.org, or when its lowercased local part is noreply and its domain is the Anthropic domain. The domain tested is the matched one, which can be shorter than the text after the at sign.
//   G. (this pass hides less than report-sanitizer, by decision of the TRDD-L1I0FP5T coordinator) The address of a git clone over SSH stays visible and counts as the end of the previous match: a local part equal to git in any letter case, when the character right after the matched domain is a colon followed by a path character (the scp-like form: git, at sign, host, colon, owner, slash, repo), or when the local part is directly preceded by ssh:// or git+ssh://. It is a service account and not a person (report-sanitizer's ssh_cmd_repl keeps it for the same reason). A git local part in any other place is hidden like every address.
// KNOWN MISSES, each pinned by a test titled "KNOWN MISS <slug>: ..." in tests/email.test.ts and described in KNOWN-MISSES.md: a git clone address (email-git-local-part); a non-ASCII letter in the local part or the domain (email-non-ascii); a quoted local part (email-quoted-local-part); an IP-literal domain (email-ip-literal-domain); a domain of a single label (email-single-label-domain); a last label that does not start with two letters (email-tld-without-two-leading-letters); the tail of a last label after its leading letters (email-domain-tail-after-letter-run). All but the first are shared with report-sanitizer.
import { mark } from './patterns'
import type { Hits } from './patterns'

export type EmailSpan = { start: number; end: number }

// WHY findEmails and EmailSpan are exported: only the span-level parity measurement of TRDD-L1I0FP5T uses them today, to compare spans with the report-sanitizer Python rule; redactEmails is the one function callers use.

const isDigit = (c: number): boolean => c >= 48 && c <= 57
const isAlpha = (c: number): boolean => (c >= 65 && c <= 90) || (c >= 97 && c <= 122)
// The local-part class of report-sanitizer: letters, digits and . _ % + -
const isLocal = (c: number): boolean => isDigit(c) || isAlpha(c) || c === 46 || c === 95 || c === 37 || c === 43 || c === 45
// The domain-label class of report-sanitizer: letters, digits and the hyphen.
const isLabel = (c: number): boolean => isDigit(c) || isAlpha(c) || c === 45

// Rule 2. Reads the labels from from, never past the next character that is not a label character or a dot between labels. Returns the end of the address, or -1.
const domainEnd = (text: string, from: number): number => {
  const n = text.length
  let i = from
  let end = -1
  for (let label = 0; ; label++) {
    const labelStart = i
    while (i < n && isLabel(text.charCodeAt(i))) i++
    if (i === labelStart) break
    // Only a label after the first can end the address, and it needs 2 or more leading ASCII letters; the last such label wins, as the regex backtracks from the end.
    if (label > 0) {
      let k = labelStart
      while (k < i && isAlpha(text.charCodeAt(k))) k++
      if (k - labelStart >= 2) end = k
    }
    if (i < n && text.charCodeAt(i) === 46) i++
    else break
  }
  return end
}

// Rule G: the address of a git clone over SSH, in one of its two forms. scp-like: the character right after the matched domain is a colon and the one after that is a path character (a letter, a digit, a slash, a tilde, an underscore or a hyphen). URL: the local part is directly preceded by ssh:// (which also ends git+ssh://). A git local part anywhere else is an ordinary address.
const isCloneAddress = (text: string, start: number, end: number): boolean => {
  if (text.charCodeAt(end) === 58) {
    const c = text.charCodeAt(end + 1)
    if (isDigit(c) || isAlpha(c) || c === 47 || c === 126 || c === 95 || c === 45) return true
  }
  return text.slice(Math.max(0, start - 6), start).toLowerCase() === 'ssh://'
}

const NOREPLY_DOMAIN = 'users.noreply.github.com'
const ANTHROPIC_DOMAIN = 'anthropic.com'
// example.com and example.org have the same length
const EXAMPLE_DOMAIN_LENGTH = 'example.com'.length

// Rule 3 and G, on the matched text lowercased. The local part and the domain are compared apart, so that no address stands in this file.
const staysVisible = (text: string, start: number, at: number, end: number): boolean => {
  const localLength = at - start
  const domainLength = end - at - 1
  // WHY the lengths are tested before anything is sliced: a text of 256 KB with one address per line made a slice, a lowercase copy and a compare for every address, and that run took 104 ms in one runner run on a loaded host (limit 100 ms) against 9 to 10 ms on an idle one. Only a part whose length equals one of the listed ones can equal it, so an ordinary address allocates nothing.
  if (localLength === 3 && text.slice(start, at).toLowerCase() === 'git' && isCloneAddress(text, start, end)) return true
  if (domainLength !== NOREPLY_DOMAIN.length && domainLength !== EXAMPLE_DOMAIN_LENGTH && !(localLength === 7 && domainLength === ANTHROPIC_DOMAIN.length)) return false
  const domain = text.slice(at + 1, end).toLowerCase()
  return domain === NOREPLY_DOMAIN || domain === 'example.com' || domain === 'example.org' || (domain === ANTHROPIC_DOMAIN && text.slice(start, at).toLowerCase() === 'noreply')
}

/** Where the email addresses are: [start, end) spans over the text, left to right, never overlapping; the addresses that stay visible are not listed. */
export function findEmails(text: string): EmailSpan[] {
  const spans: EmailSpan[] = []
  // End of the previous match, visible or not: report-sanitizer resumes there, so a local part never reaches back into it.
  let lastEnd = 0
  let at = text.indexOf('@')
  while (at !== -1) {
    let start = at
    // The scan back stops at the previous match or at the first character that is not a local-part character, and that character is never an at sign: each character is read for the nearest at sign after it only.
    while (start > lastEnd && isLocal(text.charCodeAt(start - 1))) start--
    const end = start < at ? domainEnd(text, at + 1) : -1
    if (end === -1) {
      at = text.indexOf('@', at + 1)
      continue
    }
    if (!staysVisible(text, start, at, end)) spans.push({ start, end })
    lastEnd = end
    at = text.indexOf('@', end)
  }
  return spans
}

/** Hides every email address with the email marker; the count is the number of addresses hidden. */
export function redactEmails(text: string): { text: string; hits: Hits } {
  const spans = findEmails(text)
  if (spans.length === 0) return { text, hits: {} }
  let out = ''
  let at = 0
  for (const s of spans) {
    out += text.slice(at, s.start) + mark('email')
    at = s.end
  }
  return { text: out + text.slice(at), hits: { email: spans.length } }
}
