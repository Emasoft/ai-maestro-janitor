// Tests of the home-directory rewrite (home.ts), one test per rule and form, the known misses pinned as they are today, and a timing pin. Made-up names only.
import { describe, expect, test } from 'claude-code/testing'

import { redactHome } from '../home'

const raw = String.raw
const BS = '\\'
const h = (text: string, homes: string[] = []) => redactHome(text, homes)
// WHY a few paths are built from pieces: the privacy pre-commit scan reads source text and has no allow marker, so every literal home path here uses a generic name (runner, admin, user, app). Some fixtures need a made-up name no generic name can stand in for (no generic name holds a non-ASCII letter, a space, or the Shared or Public prefix), so they are joined at run time and no home-shaped literal appears in this file.
const unix = (...parts: string[]) => parts.join('/')
const win = (...parts: string[]) => parts.join(BS)
const AT = '@'

describe('home rewrite: Unix and Git Bash', () => {
  test('/Users/name becomes ~ and counts one hit', () => {
    expect(h('open /Users/runner/Code/x.ts now')).toEqual({ text: 'open ~/Code/x.ts now', hits: { 'home-path': 1 } })
  })
  test('/home/name becomes ~', () => {
    expect(h('cd /home/admin/src').text).toBe('cd ~/src')
  })
  test('a Unicode name (josé) is one name', () => {
    // Built from pieces (made-up name, see the note above the helpers): no generic name holds a non-ASCII letter.
    expect(h(unix('', 'Users', 'josé', 'x')).text).toBe('~/x')
    expect(h(win('C:', 'Users', 'josé', 'x')).text).toBe(raw`%USERPROFILE%\x`)
  })
  test('a Unix name may hold @ (realmd homes on hosts joined to Active Directory)', () => {
    expect(h(unix('', 'home', 'runner' + AT + 'corp.example', 'x')).text).toBe('~/x')
    expect(h(unix('', 'Users', 'runner' + AT + 'corp', 'x')).text).toBe('~/x')
  })
  test('a home right after an @ is still rewritten (@ is in the Unix name class but not in the start lookbehind)', () => {
    expect(h('x' + AT + unix('', 'home', 'runner', 'y')).text).toBe('x' + AT + '~/y')
    expect(h('x' + AT + win('C:', 'Users', 'runner', 'y')).text).toBe('x' + AT + raw`%USERPROFILE%\y`)
  })
  test('Public followed by @ and a domain is a name, not the exempt Public', () => {
    expect(h(unix('', 'home', 'Public' + AT + 'corp', 'x')).text).toBe('~/x')
    expect(h(unix('', 'home', 'Public', 'x')).text).toBe(unix('', 'home', 'Public', 'x'))
  })
  test('an @host tail glued to a home name is hidden with it (intended over-redaction: the host goes too)', () => {
    expect(h('scp f ' + unix('', 'home', 'runner') + AT + 'host:x').text).toBe('scp f ~:x')
  })
  test('/c/Users/name becomes ~ (Git Bash)', () => {
    expect(h('/c/Users/runner/x').text).toBe('~/x')
  })
  test('/mnt/c/Users/name becomes ~ (WSL), the /mnt prefix is consumed', () => {
    expect(h('see /mnt/c/Users/runner/x').text).toBe('see ~/x')
  })
  test('a JSON-escaped path after a literal backslash-n, -t or -r is rewritten', () => {
    expect(h(raw`a\n/Users/runner/x`).text).toBe(raw`a\n~/x`)
    expect(h(raw`a\t/home/admin/x`).text).toBe(raw`a\t~/x`)
    expect(h(raw`a\r/c/Users/user/x`).text).toBe(raw`a\r~/x`)
  })
  test('a URL path such as .com/home/name is unchanged', () => {
    const url = 'https://example.com/home/user/x'
    expect(h(url)).toEqual({ text: url, hits: {} })
  })
  test('a slash after a name character or ~ never starts a home', () => {
    for (const s of ['/usr/Users/user', '~/Users/user']) expect(h(s).text).toBe(s)
  })
  test('a slash after } or ) starts a home: the name after a variable or a command substitution is hidden (parity with the report sanitizer)', () => {
    // Built from pieces (made-up name, see the note above the helpers): the privacy scan has no allow marker.
    expect(h('${HOME}' + unix('', 'Users', 'runner', 'p')).text).toBe('${HOME}~/p')
    expect(h('$(pwd)' + unix('', 'home', 'runner', 'p')).text).toBe('$(pwd)~/p')
  })
  test('a slash after ~ still never starts a home (idempotence: a second run must not match what a first run left)', () => {
    const tilde = '~' + unix('', 'Users', 'runner', 'x')
    expect(h(tilde)).toEqual({ text: tilde, hits: {} })
  })
  test('/Users/Shared is not a person, /Users/Shared-x is', () => {
    expect(h('/Users/Shared/x').text).toBe('/Users/Shared/x')
    const shared = '/Users/Shared'
    expect(h(shared).text).toBe(shared)
    // Built from pieces (made-up name, see the note above the helpers): no generic name starts with Shared, and a trailing separator keeps the original form.
    expect(h(unix('', 'Users', 'Shared-x', 'y')).text).toBe('~/y')
  })
  test('a sentence-final period belongs to the name (accepted, as the report sanitizer does)', () => {
    expect(h('see /Users/runner.').text).toBe('see ~')
  })
  test('a PATH list or a file: URL puts a letter and a colon before /Users and is not a drive', () => {
    expect(h('PATH=/opt/bin:/Users/runner/.local/bin:/home/user/bin').text).toBe('PATH=/opt/bin:~/.local/bin:~/bin')
    expect(h('file:/Users/runner/x').text).toBe('file:~/x')
    const list = '/opt/x:/Users/runner'
    expect(h(list).text).toBe('/opt/x:~')
  })
})

describe('home rewrite: Windows', () => {
  test('a Windows drive path with single backslashes keeps the separator after the name', () => {
    expect(h(raw`C:\Users\runner\Code\x`)).toEqual({ text: raw`%USERPROFILE%\Code\x`, hits: { 'home-path': 1 } })
  })
  test('a doubled backslash separator is kept as written', () => {
    expect(h(raw`C:\\Users\\runner\\Code`).text).toBe(raw`%USERPROFILE%\\Code`)
  })
  test('C:/Users/name becomes %USERPROFILE%/ and never C:~', () => {
    const out = h('C:/Users/runner/x').text
    expect(out).toBe('%USERPROFILE%/x')
    expect(out).not.toContain('C:~')
  })
  test('a lowercase drive letter is a drive letter too', () => {
    expect(h(raw`d:\Users\runner\x`).text).toBe(raw`%USERPROFILE%\x`)
  })
  test('a name with an inner space is one name when a separator follows', () => {
    // Built from pieces (made-up name, see the note above the helpers): no generic name holds a space.
    expect(h(win('C:', 'Users', 'John Smith', 'x')).text).toBe(raw`%USERPROFILE%\x`)
  })
  test('prose after the name keeps its words: only runner is rewritten', () => {
    expect(h(raw`C:\Users\runner is here`).text).toBe('%USERPROFILE% is here')
  })
  test('Public, Default, Default User and All Users are unchanged', () => {
    for (const n of ['Public', 'Default', 'Default User', 'All Users']) {
      const s = raw`C:\Users` + BS + n + raw`\x`
      expect(h(s)).toEqual({ text: s, hits: {} })
    }
    expect(h('C:/Users/Public/x').text).toBe('C:/Users/Public/x')
  })
  test('a name that only starts with an exempt name is rewritten', () => {
    expect(h(win('C:', 'Users', 'Publicist', 'x')).text).toBe(raw`%USERPROFILE%\x`)
  })
  test('a lowercase users or an uppercase USERS is the Windows folder too (paths are case-insensitive)', () => {
    expect(h(raw`c:\users\runner\x`).text).toBe(raw`%USERPROFILE%\x`)
    expect(h(raw`C:\USERS\runner\x`).text).toBe(raw`%USERPROFILE%\x`)
  })
  test('the lowercase users of a Unix path is not a home (only Windows is case-insensitive)', () => {
    expect(h('/users/runner/x').text).toBe('/users/runner/x')
  })
  test('a drive path keeps its rewrite and its Public exemption next to the boundary rule', () => {
    expect(h('C:/Users/Public/x').text).toBe('C:/Users/Public/x')
    expect(h('C:/Users/runner/x').text).toBe('%USERPROFILE%/x')
    expect(h(raw`"C:\\Users\\runner"`).text).toBe(raw`"%USERPROFILE%"`)
  })
  test('a drive after a JSON-escaped backslash-n, -t or -r, and after file:///, is a real drive', () => {
    expect(h(raw`a\nC:\\Users\\runner\\x`).text).toBe(raw`a\n%USERPROFILE%\\x`)
    expect(h(raw`a\tC:/Users/runner/x`).text).toBe(raw`a\t%USERPROFILE%/x`)
    expect(h('file:///C:/Users/runner/x').text).toBe('file:///%USERPROFILE%/x')
  })
  test('Public, Default, Default User and All Users stay whole for rule 3 and rule 4 too', () => {
    expect(h('/Users/Public/x').text).toBe('/Users/Public/x')
    expect(h('/home/Default/x').text).toBe('/home/Default/x')
    expect(h('/c/Users/Public/x').text).toBe('/c/Users/Public/x')
    expect(h(unix('', 'Users', 'Publicist', 'x')).text).toBe('~/x')
  })
  test('a drive after a slash that is not glued to a name is a real drive (file URIs, /c:/, long paths)', () => {
    expect(h('file://C:/Users/runner/x').text).toBe('file://%USERPROFILE%/x')
    expect(h('file:/C:/Users/runner/x').text).toBe('file:/%USERPROFILE%/x')
    expect(h('/c:/Users/runner/x').text).toBe('/%USERPROFILE%/x')
    expect(h('//?/C:/Users/runner/x').text).toBe('//?/%USERPROFILE%/x')
    expect(h(raw`\\?\C:\Users\runner\x`).text).toBe(raw`\\?\%USERPROFILE%\x`)
  })
  test('a long-path prefix in JSON text is a real drive: every backslash doubled, or a forward slash after the name', () => {
    expect(h(raw`p: "\\\\?\\C:\\Users\\runner\\x"`).text).toBe(raw`p: "\\\\?\\%USERPROFILE%\\x"`)
    expect(h(raw`\\\\?\\c:/Users/runner/x`).text).toBe(raw`\\\\?\\%USERPROFILE%/x`)
  })
  test('a Windows home JSON-escaped twice or more is a home: a backslash run of any length separates it, and the long-path prefix is escaped the same way', () => {
    expect(h(raw`C:\\\\Users\\\\runner\\\\x`).text).toBe(raw`%USERPROFILE%\\\\x`)
    expect(h(raw`\\\\\\\\?\\\\C:\\\\Users\\\\runner\\\\x`).text).toBe(raw`\\\\\\\\?\\\\%USERPROFILE%\\\\x`)
    expect(h(raw`C:\\\\Users\\\\app\\\\x`).text).toBe(raw`%USERPROFILE%\\\\x`)
    expect(h(raw`x\\\\Users\\\\runner\\\\y`).text).toBe(raw`x\\\\Users\\\\runner\\\\y`)
    expect(h(['C:', 'Users', 'runner', 'x'].join(BS.repeat(8))).text).toBe('%USERPROFILE%' + BS.repeat(8) + 'x')
  })
  test('a PATH entry whose slash follows a name is not a drive', () => {
    const list = '/opt/x:/Users/runner'
    expect(h(list).text).toBe('/opt/x:~')
  })
  test('the exempt names are exempt in any letter case, on Windows and elsewhere', () => {
    expect(h(raw`c:\users\public\x`).text).toBe(raw`c:\users\public\x`)
    expect(h(raw`C:\USERS\PUBLIC\x`).text).toBe(raw`C:\USERS\PUBLIC\x`)
    expect(h('/Users/shared/x').text).toBe('/Users/shared/x')
    expect(h('/home/DEFAULT/x').text).toBe('/home/DEFAULT/x')
  })
  test('mixed separators are rewritten: each slot takes the doubled backslash, the backslash or the slash, and the rest of the path is kept', () => {
    expect(h(raw`C:\Users/runner\x`).text).toBe(raw`%USERPROFILE%\x`)
    expect(h(raw`C:/Users\runner/x`).text).toBe('%USERPROFILE%/x')
    expect(h(raw`C:\\Users\runner\x`).text).toBe(raw`%USERPROFILE%\x`)
    expect(h(raw`C:\Users\\runner\x`).text).toBe(raw`%USERPROFILE%\x`)
  })
  test('a spaced name followed by a separator in a mixed style is one name', () => {
    // Built from pieces (made-up name, see the note above the helpers): no generic name holds a space.
    expect(h(win('C:', 'Users', 'John Smith') + '/x').text).toBe('%USERPROFILE%/x')
  })
  test('Users in a mixed letter case is the Windows folder, and the exempt names stay exempt', () => {
    expect(h(raw`C:\UsErS\runner\x`).text).toBe(raw`%USERPROFILE%\x`)
    for (const s of [raw`C:\Users\Default\x`, raw`C:\UsErS\Public\x`]) expect(h(s)).toEqual({ text: s, hits: {} })
  })
  test('a Windows name may hold @ or $ (domain and service accounts)', () => {
    expect(h(win('C:', 'Users', 'runner' + AT + 'corp', 'x')).text).toBe(raw`%USERPROFILE%\x`)
    expect(h(win('C:', 'Users', 'run$', 'x')).text).toBe(raw`%USERPROFILE%\x`)
  })
})

describe('home rewrite: caller home literals', () => {
  test('a literal outside the built-in shapes becomes ~', () => {
    expect(h('/opt/people/app/x', ['/opt/people/app'])).toEqual({ text: '~/x', hits: { 'home-path': 1 } })
  })
  test('a drive-letter literal becomes %USERPROFILE%', () => {
    expect(h(raw`D:\home\app\x`, [raw`D:\home\app`]).text).toBe(raw`%USERPROFILE%\x`)
  })
  test('the longest literal goes first', () => {
    expect(h('/srv/u/app/work/x', ['/srv/u/app', '/srv/u/app/work']).text).toBe('~/x')
  })
  test('a literal followed by a name character is not a prefix match', () => {
    expect(h('/srv/u/appuser/x', ['/srv/u/app']).text).toBe('/srv/u/appuser/x')
    expect(h('/srv/u/app.', ['/srv/u/app']).text).toBe('~.')
  })
  test('empty and one-segment entries are ignored', () => {
    expect(h('/root/x', ['', '/', '/root']).text).toBe('/root/x')
  })
  test('a trailing separator on the literal is cut', () => {
    expect(h('/srv/u/app/x', ['/srv/u/app/']).text).toBe('~/x')
  })
})

describe('home rewrite: caller home literals, astral characters, surrogates and overlapping candidates', () => {
  // WHY the literal lives under /opt: the built-in Unix rule would also rewrite a /Users/runner name that continues with an astral letter, which would hide what the literal search itself did.
  const home = '/opt/people/app'
  test('a literal followed by an astral letter (U+1D400) is a longer name and is not rewritten', () => {
    const s = home + '\u{1D400}/x'
    expect(h(s, [home])).toEqual({ text: s, hits: {} })
  })
  test('a literal followed by an astral emoji (U+1F600) is rewritten and the emoji stays', () => {
    expect(h(home + '\u{1F600} x', [home])).toEqual({ text: '~\u{1F600} x', hits: { 'home-path': 1 } })
  })
  test('a literal ending in a lone high surrogate is not rewritten when a low surrogate follows, and is when anything else follows', () => {
    const lone = home + '\uD835'
    const pair = lone + '\uDC00/x'
    expect(h(pair, [lone])).toEqual({ text: pair, hits: {} })
    expect(h(lone + ' x', [lone])).toEqual({ text: '~ x', hits: { 'home-path': 1 } })
  })
  test('a literal starting with a lone low surrogate is not rewritten when a high surrogate stands before it, and is after anything else', () => {
    const lone = '\uDC00' + home
    const pair = '\uD835' + lone + '/x'
    expect(h(pair, [lone])).toEqual({ text: pair, hits: {} })
    expect(h('x' + lone + ' y', [lone])).toEqual({ text: 'x~ y', hits: { 'home-path': 1 } })
  })
  test('a refused candidate between two occurrences does not hide the second: only the second is rewritten and counted once', () => {
    expect(h(home + 'x ' + home + '/a', [home])).toEqual({ text: home + 'x ~/a', hits: { 'home-path': 1 } })
  })
  test('overlapping candidates: a refused one at index 0 leaves the one at index 3 to match (aa/a in aa/aa/a gives aa/~, 1 hit)', () => {
    expect(h('aa/aa/a', ['aa/a'])).toEqual({ text: 'aa/~', hits: { 'home-path': 1 } })
  })
  test('overlapping candidates: a hit at index 0 consumes the candidate that starts inside it (ab/ab in ab/ab/ab gives ~/ab, 1 hit)', () => {
    expect(h('ab/ab/ab', ['ab/ab'])).toEqual({ text: '~/ab', hits: { 'home-path': 1 } })
  })
  // WHY shift 2 is the closest overlap: a shift-1 self-overlap needs a home of one repeated character, and usableHomes drops those (a home needs two non-empty segments, so it holds a separator plus a non-separator; probed: aaaa, //, a, /a and a/ are all ignored). The nearest self-overlap of a usable home is a shift of 2.
  test('overlapping candidates: two hits at shift 2 with the separator between them kept (a/a in a/a/a/a gives ~/~, 2 hits)', () => {
    expect(h('a/a/a/a', ['a/a'])).toEqual({ text: '~/~', hits: { 'home-path': 2 } })
  })
})

describe('home rewrite: Claude project slug', () => {
  test('-Users-name becomes -Users-USER', () => {
    expect(h('/x/projects/-Users-runner-Code-proj/s.jsonl').text).toBe('/x/projects/-Users-USER-Code-proj/s.jsonl')
  })
  test('-Users-Shared and a glued prefix are unchanged', () => {
    expect(h('-Users-Shared-x').text).toBe('-Users-Shared-x')
    expect(h('a-Users-runner').text).toBe('a-Users-runner')
  })
  test('-home-name becomes -home-USER only after a slash', () => {
    expect(h('/x/projects/-home-runner-proj').text).toBe('/x/projects/-home-USER-proj')
    expect(h('-home-runner-proj').text).toBe('-home-runner-proj')
  })
  test('a name that is exactly USER is skipped: nothing is rewritten and nothing is counted', () => {
    for (const s of ['-Users-USER-proj', '/x/.claude/projects/-Users-USER-proj', '-Users-USER', '/x/projects/-home-USER-proj']) expect(h(s)).toEqual({ text: s, hits: {} })
  })
  test('a real name is still rewritten and counted once, and a name that only starts with USER is a name', () => {
    expect(h('-Users-runner-proj')).toEqual({ text: '-Users-USER-proj', hits: { 'home-path': 1 } })
    expect(h('-Users-USERx-proj')).toEqual({ text: '-Users-USER-proj', hits: { 'home-path': 1 } })
  })
})

describe('home rewrite: counts and idempotence', () => {
  test('hits count every rewrite and are empty when nothing matched', () => {
    expect(h(raw`/Users/runner C:\Users\admin\x /home/user`).hits).toEqual({ 'home-path': 3 })
    expect(h('nothing here').hits).toEqual({})
  })
  test('results starting with ~/ or %USERPROFILE% never match again', () => {
    for (const s of ['~/Code/x', raw`%USERPROFILE%\Code\x`]) expect(h(s)).toEqual({ text: s, hits: {} })
  })
  test('running twice gives the text of running once and counts 0 hits the second time (a slug already holding USER is skipped)', () => {
    const text = raw`a\n/Users/runner/x C:\\Users\\runner\\y C:/Users/runner/z C:\Users/runner\w C:\UsErS\runner${AT}corp\v /mnt/c/Users/runner /home/runner /srv/u/runner/q /x/-Users-runner-p /x/-home-runner-p -Users-USER-p`
    const once = h(text, ['/srv/u/runner'])
    expect(once.text).not.toContain('runner')
    expect(once.hits).toEqual({ 'home-path': 10 })
    expect(h(once.text, ['/srv/u/runner'])).toEqual({ text: once.text, hits: {} })
  })
})

describe('home rewrite: known misses, pinned as they are today', () => {
  test('home known miss relative-parent: a relative ../Users/name is not rewritten', () => {
    expect(h('../Users/runner/x').text).toBe('../Users/runner/x')
  })
  test('home known miss windows-name-special-chars: a Windows name holding & ! # % ~ { } ^ keeps the tail from that character', () => {
    // Built from pieces (made-up name, see the note above the helpers): Windows allows these characters in a name, WIN_N does not.
    expect(h(win('C:', 'Users', 'Aa&Bb', 'x')).text).toBe(raw`%USERPROFILE%&Bb\x`)
  })
  test('home known miss windows-drive-glued: a drive letter glued to a name character, a dot or a backslash is not a token start, so the path stays unchanged', () => {
    // Built from pieces (made-up name, see the note above the helpers).
    const glued = 'dir-' + win('C:', 'Users', 'runner', 'x')
    expect(h(glued)).toEqual({ text: glued, hits: {} })
  })
  test('home known miss url-encoded: a URL-encoded %2FUsers%2Fname is not rewritten', () => {
    expect(h('%2FUsers%2Frunner%2Fx').text).toBe('%2FUsers%2Frunner%2Fx')
  })
  test('home known miss windows-name-with-spaces: a spaced Windows name with no separator after it keeps its later words', () => {
    // Built from pieces (made-up name, see the note above the helpers): no generic name holds a space.
    expect(h(win('C:', 'Users', 'John Smith')).text).toBe('%USERPROFILE% Smith')
    expect(h('C:/Users' + BS + 'John Smith').text).toBe('%USERPROFILE% Smith')
  })
  test('home known miss single-letter-root-in-path: a one-letter root folder before a colon in a PATH list counts as a drive', () => {
    // Held in a variable: a path with no trailing slash plus a later slash on the same line reads to the privacy scan as one home path.
    const list = 'PATH=/x:/Users/user'
    expect(h(list).text).toBe('PATH=/%USERPROFILE%')
  })
  test('home known miss windows-name-with-brackets: a Windows name holding round brackets keeps its tail after the rewritten part', () => {
    // Round brackets stay out of the Windows name class on purpose, so prose such as (C:\Users\app) keeps its closing bracket.
    expect(h(win('C:', 'Users', 'app(1)', 'x')).text).toBe(raw`%USERPROFILE%(1)\x`)
    expect(h(raw`(C:\Users\app)`).text).toBe('(%USERPROFILE%)')
  })
  test('home known miss unix-name-with-trailing-dollar: a Linux name ending in a dollar sign (a Samba machine account) is hidden but the dollar sign stays after ~', () => {
    // Built from pieces (made-up name, see the note above the helpers): the privacy scan has no allow marker.
    expect(h(unix('', 'home', 'svc' + '$', 'x')).text).toBe('~$/x')
  })
  test('home known miss home-domain-then-user: a home with a domain folder and then the user folder (SSSD on hosts joined to Active Directory) rewrites the domain folder and keeps the user name', () => {
    expect(h(unix('', 'home', 'corp.example', 'runner', 'x')).text).toBe('~/runner/x')
  })
})

describe('home rewrite: timing', () => {
  test('200,000 characters of adversarial input run in under 1000 ms', () => {
    const fragments = (raw`C:\Users\a a a a ` + '/Users/').repeat(Math.ceil(200000 / 24)).slice(0, 200000)
    const longRun = raw`C:\Users` + BS + 'a '.repeat(100000)
    const wordy = (raw`C:\Users` + BS + 'abcdefgh '.repeat(25000)).slice(0, 200000)
    // WHY a fourth input with mixed separators and @ or $ in the name: the Windows rule gained SEP and WIN_N (TRDD-L1I0FP5T), and the linear claim must be measured on them too.
    const mixed = (raw`C:\\Users/a@b$ a a a ` + 'C:/Users').repeat(Math.ceil(200000 / 20)).slice(0, 200000)
    // WHY these three inputs: SEP became a backslash run of any length, so long backslash runs must stay linear in the engine this file runs in. They do NOT pin the drive guard of DRIVE_START: without it the long-path lookbehind is superlinear, about quadratic, in bun 1.3.14 run standalone (5,000 / 10,000 / 20,000 backslashes took 1.2 / 3.7 / 8.9 s, 2026-11-17) but not in the runner of claude plugin test (the unguarded mutant passed the timing test in 61 ms, 2026-11-17), so the guard needs a timing test that runs the core in standalone bun; report-sanitizer runs it there, and TRDD-L1I0FP5T tracks adding that test.
    const bsRun = BS.repeat(200000)
    const bsRunDrive = BS.repeat(200000) + raw`C:\Users\runner\x`
    const bsRunPrefix = (BS.repeat(50) + '?' + BS + 'C:').repeat(Math.ceil(200000 / 53)).slice(0, 200000)
    for (const input of [fragments, longRun, wordy, mixed, bsRun, bsRunDrive, bsRunPrefix]) {
      expect(input.length).toBeGreaterThanOrEqual(200000)
      const start = performance.now()
      h(input, ['/opt/people/app'])
      expect(performance.now() - start).toBeLessThan(1000)
    }
  })
})
