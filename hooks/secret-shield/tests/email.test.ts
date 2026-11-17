// Tests of the email pass (email.ts), one test per rule and form, the known misses pinned as they are today, and a timing pin.
// WHY every address is built at run time: the privacy scans read source text, so no address may stand in a tracked file. e() joins a local part, the at sign and a host; the host is a domain, never an address by itself.
// WHY the expected results were checked against report-sanitizer: each case of the rules below was run through its EMAIL regex and email_repl (RS commit f2def51) with rule G applied, and a random differential run of 300,000 strings gave 0 differences with this scan (TRDD-L1I0FP5T increment 3).
import { describe, expect, test } from 'claude-code/testing'

import { findEmails, redactEmails } from '../email'
import { mark } from '../patterns'

const M = mark('email')
const one = { email: 1 }

const e = (local: string, host: string): string => local + '@' + host
const r = (text: string) => redactEmails(text)
const unchanged = (text: string) => expect(r(text)).toEqual({ text, hits: {} })
const hides = (text: string, out: string, n: number) => expect(r(text)).toEqual({ text: out, hits: { email: n } })
const ms = (run: () => void): number => {
  const start = performance.now()
  run()
  return performance.now() - start
}

describe('email pass: what is hidden', () => {
  test('a plain address is hidden with the email marker and the text around it stays', () => {
    hides('mail ' + e('user', 'host.net') + ' now', 'mail ' + M + ' now', 1)
  })
  test('two addresses are counted as two, with local-part characters and subdomains', () => {
    hides('a ' + e('first.last+tag%x_y-z', 'host-name.co.uk') + ' and ' + e('B', 'c.de'), 'a ' + M + ' and ' + M, 2)
  })
  test('capital letters do not matter', () => {
    hides(e('USER', 'HOST.NET'), M, 1)
  })
  test('a hyphen at the edge of a label is read like any other label character', () => {
    hides(e('user', '-host.net'), M, 1)
    hides(e('user', 'host-.net'), M, 1)
  })
  test('findEmails returns the span of the address, from the first local-part character to the last letter of the domain', () => {
    const text = 'mail ' + e('user', 'host.net') + ' now'
    expect(findEmails(text)).toEqual([{ start: 5, end: 5 + e('user', 'host.net').length }])
  })
  test('an empty local part, an empty domain, or text with no at sign is left as it is', () => {
    unchanged(e('', 'host.net'))
    unchanged(e('user', ''))
    unchanged('plain text, no address here')
  })
  test('the first of two at signs in a row has no domain, the second one has a local part of its own', () => {
    unchanged(e('a', '') + '@b.cc')
    hides(e('a', e('b', 'c.net')), 'a@' + M, 1)
  })
})

describe('email pass: the addresses that stay visible (rule 3)', () => {
  test('the GitHub no-reply domain stays visible, in any letter case', () => {
    unchanged('x ' + e('123+name', 'users.noreply.github.com') + ' y')
    unchanged('x ' + e('123+name', 'USERS.NOREPLY.GITHUB.COM') + ' y')
  })
  test('a no-reply local part at the Anthropic domain stays visible, in any letter case; at another domain, or another local part there, it is hidden', () => {
    unchanged('x ' + e('noreply', 'anthropic.com') + ' y')
    unchanged(e('NoReply', 'Anthropic.COM'))
    hides(e('noreply', 'host.net'), M, 1)
    hides(e('other', 'anthropic.com'), M, 1)
  })
  test('example.com and example.org stay visible, a subdomain of them or another example domain is hidden', () => {
    unchanged(e('user', 'example.com'))
    unchanged(e('user', 'Example.ORG'))
    hides(e('user', 'sub.example.com'), M, 1)
    hides(e('user', 'example.net'), M, 1)
  })
  test('the domain tested is the matched one: example.com followed by a digit stays visible, followed by a letter it is a different domain and is hidden', () => {
    unchanged(e('x', 'example.com1'))
    hides(e('x', 'example.comx'), M, 1)
  })
  test('a visible address still ends the previous match: the characters after it can be the local part of the next address', () => {
    hides(e('x', 'example.com') + e('1y', 'host.net'), e('x', 'example.com') + M, 1)
  })
})

describe('email pass: where the domain ends', () => {
  test('a last label of letters and a digit ends after the letters: the digit stays visible', () => {
    hides(e('user', 'host.comx1'), M + '1', 1)
    hides(e('user', 'host.bc1'), M + '1', 1)
  })
  test('the last label that starts with two letters ends the address, the labels after it stay visible', () => {
    hides(e('user', 'host.com.x1'), M + '.x1', 1)
  })
  test('a double dot ends the labels: before the last label that fits the address ends there, with none before it there is no address', () => {
    unchanged(e('user', 'host..com'))
    hides(e('user', 'host.net..com'), M + '..com', 1)
  })
  test('a dot after the domain is not part of it', () => {
    hides(e('user', 'host.net') + '.', M + '.', 1)
  })
  test('the scan resumes after the match: the characters left after a short match start the next local part', () => {
    hides(e('a', 'b.comx') + e('1', 'c.net'), M + M, 2)
    hides(e('a', 'b.cc') + e('', 'd.ee'), M + e('', 'd.ee'), 1)
  })
})

describe('email pass: the address of a git clone over SSH (rule G)', () => {
  test('the scp-like form stays visible: a git local part, then a colon and a path character (letter, digit, slash, tilde, underscore)', () => {
    unchanged('git clone ' + e('git', 'github.com') + ':owner/repo.git')
    unchanged(e('Git', 'host.net') + ':_x')
    unchanged(e('GIT', 'host.net') + ':22')
    unchanged(e('git', 'host.net') + ':~/repo')
    unchanged(e('git', 'host.net') + ':/srv/repo')
  })
  test('the URL form stays visible: a git local part directly after ssh:// or git+ssh://, in any letter case', () => {
    unchanged('ssh://' + e('git', 'host.net') + '/owner/repo')
    unchanged('git+ssh://' + e('GIT', 'host.net') + ':22/x')
    unchanged('SSH://' + e('git', 'host.net'))
  })
  test('a git address that is not a clone address is hidden like every address: alone, before a comma or a dot, or before a colon that no path character follows', () => {
    hides('mail ' + e('git', 'host.net') + ', thanks', 'mail ' + M + ', thanks', 1)
    hides('see ' + e('git', 'host.net') + '.', 'see ' + M + '.', 1)
    hides(e('git', 'host.net') + ': x', M + ': x', 1)
    hides(e('git', 'host.net') + ':', M + ':', 1)
    hides(e('git', 'host.net') + ':.x', M + ':.x', 1)
  })
  test('the colon must follow the matched domain: with a digit tail after a short match the colon is too far and the address is hidden', () => {
    hides(e('git', 'host.comx1') + ':a', M + '1:a', 1)
  })
  test('a local part that only contains git, or any other local part after ssh://, is hidden even in a clone form', () => {
    hides(e('xgit', 'host.net') + ':owner/r', M + ':owner/r', 1)
    hides('ssh://' + e('git.x', 'host.net'), 'ssh://' + M, 1)
    hides('ssh://' + e('user', 'host.net') + '/owner/repo', 'ssh://' + M + '/owner/repo', 1)
  })
  test('a visible clone address still ends the previous match, and the addresses around it are hidden', () => {
    hides(e('git', 'host.net') + ':a ' + e('user', 'host.net'), e('git', 'host.net') + ':a ' + M, 1)
    hides('ssh://' + e('git', 'host.net1y') + '@h.net', 'ssh://' + e('git', 'host.net') + M, 1)
  })
})

describe('email pass: known misses', () => {
  test('KNOWN MISS email-git-local-part: a git clone address, in the scp-like form or after ssh://, is not hidden, a git address anywhere else is', () => {
    unchanged(e('git', 'github.com') + ':owner/repo.git')
    unchanged('ssh://' + e('git', 'host.net') + '/owner/repo')
    expect(r(e('git', 'host.net')).hits).toEqual(one)
  })
  test('KNOWN MISS email-non-ascii: an address with a non-ASCII letter right before the at sign or inside the domain is not hidden, an ASCII one is', () => {
    unchanged(e('josé', 'host.net'))
    unchanged(e('user', 'hôst.net'))
    unchanged(e('user', 'host.nét'))
    hides('é' + e('user', 'host.net'), 'é' + M, 1)
  })
  test('KNOWN MISS email-quoted-local-part: an address whose local part is in double quotes is not hidden, the same words unquoted are', () => {
    unchanged('"user name"' + '@' + 'host.net')
    unchanged('"user"' + '@' + 'host.net')
    hides(e('user name', 'host.net'), 'user ' + M, 1)
  })
  test('KNOWN MISS email-ip-literal-domain: an address whose domain is an IP address, in brackets or not, is not hidden, a host name is', () => {
    unchanged(e('user', '[192.0.2.1]'))
    unchanged(e('user', '192.0.2.1'))
    expect(r(e('user', 'host.net')).hits).toEqual(one)
  })
  test('KNOWN MISS email-single-label-domain: an address whose domain has one label is not hidden, with two labels it is', () => {
    unchanged(e('user', 'localhost'))
    expect(r(e('user', 'localhost.net')).hits).toEqual(one)
  })
  test('KNOWN MISS email-tld-without-two-leading-letters: an address whose last label starts with a digit or with a single letter is not hidden, with two letters first it is', () => {
    unchanged(e('user', 'host.1com'))
    unchanged(e('user', 'host.123'))
    unchanged(e('user', 'host.c1'))
    unchanged(e('user', 'host.c'))
    expect(r(e('user', 'host.co')).hits).toEqual(one)
  })
  test('KNOWN MISS email-domain-tail-after-letter-run: the digits, or the hyphen and digits, after the leading letters of the last label stay visible, a last label of letters is hidden whole', () => {
    hides(e('user', 'host.comx1'), M + '1', 1)
    hides(e('user', 'host.xn--p1ai'), M + '--p1ai', 1)
    hides(e('user', 'host.comx'), M, 1)
  })
})

describe('email pass: timing', () => {
  // WHY 256 KB and 100 ms: the scan reads each character a bounded number of times, so a text this size takes a few milliseconds; the report-sanitizer regex took 4 to 5 s for 64 KB on three of these shapes (measured 2026-11-17 on report-sanitizer f2def51: a-dot repeated then an at sign, an at sign then b-dot repeated, an at sign and b then c1-dot repeated), and four times longer per doubling. A quadratic scan would take over a minute at 256 KB.
  const n = 262144
  const inputs: Array<[string, string]> = [
    ['256 KB of at signs', '@'.repeat(n)],
    ['256 KB of a and an at sign repeated', 'a@'.repeat(n / 2)],
    ['256 KB of a-dot repeated and one at sign at the end', 'a.'.repeat(n / 2 - 1) + '@'],
    ['256 KB of an at sign, a and a dot repeated', '@a.'.repeat(Math.floor(n / 3))],
    ['a at sign then 256 KB of b-dot repeated', 'a@' + 'b.'.repeat(n / 2 - 1)],
    ['a at sign and b then 256 KB of dot, c and 1 repeated', 'a@b' + '.c1'.repeat(Math.floor(n / 3))],
    ['256 KB of plain text with no at sign', 'The quick brown fox jumps over the lazy dog. '.repeat(Math.floor(n / 45))],
    ['256 KB of one address per line', (e('user', 'host.net') + '\n').repeat(Math.floor(n / 14))],
    ['256 KB of a local part then one address', 'a'.repeat(n) + '@host.net'],
  ]
  for (const [name, text] of inputs) {
    test(name + ' takes under 100 ms', () => {
      expect(ms(() => r(text))).toBeLessThan(100)
    })
  }
  test('the one-address-per-line text hides every address', () => {
    const text = (e('user', 'host.net') + '\n').repeat(100)
    expect(r(text).hits).toEqual({ email: 100 })
  })
})
