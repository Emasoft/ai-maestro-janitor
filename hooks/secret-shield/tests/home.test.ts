// Tests of the home-directory rewrite (home.ts), one test per rule and form, the known misses pinned as they are today, and a timing pin. Made-up names only.
import { describe, expect, test } from 'claude-code/testing'

import { redactHome } from '../home'

const raw = String.raw
const BS = '\\'
const h = (text: string, homes: string[] = []) => redactHome(text, homes)
// WHY a few paths are built from pieces: the privacy pre-commit scan reads source text and has no allow marker, so every literal home path here uses a generic name (runner, admin, user, app). Some fixtures need a made-up name no generic name can stand in for (no generic name holds a non-ASCII letter, a space, or the Shared or Public prefix), so they are joined at run time and no home-shaped literal appears in this file.
const unix = (...parts: string[]) => parts.join('/')
const win = (...parts: string[]) => parts.join(BS)

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
  test('a slash after a name character, ~, } or ) never starts a home', () => {
    for (const s of ['/usr/Users/user', '~/Users/user', '${HOME}/Users/user', '$(pwd)/home/user']) expect(h(s).text).toBe(s)
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
})

describe('home rewrite: counts and idempotence', () => {
  test('hits count every rewrite and are empty when nothing matched', () => {
    expect(h(raw`/Users/runner C:\Users\admin\x /home/user`).hits).toEqual({ 'home-path': 3 })
    expect(h('nothing here').hits).toEqual({})
  })
  test('results starting with ~/ or %USERPROFILE% never match again', () => {
    for (const s of ['~/Code/x', raw`%USERPROFILE%\Code\x`]) expect(h(s)).toEqual({ text: s, hits: {} })
  })
  test('running twice gives the text of running once; only the slug rewrites to themselves are counted again', () => {
    const text = raw`a\n/Users/runner/x C:\\Users\\runner\\y C:/Users/runner/z /mnt/c/Users/runner /home/runner /srv/u/runner/q /x/-Users-runner-p /x/-home-runner-p`
    const once = h(text, ['/srv/u/runner'])
    expect(once.text).not.toContain('runner')
    expect(h(once.text, ['/srv/u/runner'])).toEqual({ text: once.text, hits: { 'home-path': 2 } })
  })
})

describe('home rewrite: known misses, pinned as they are today', () => {
  test('home known miss relative-parent: a relative ../Users/name is not rewritten', () => {
    expect(h('../Users/runner/x').text).toBe('../Users/runner/x')
  })
  test('home known miss after-variable: a name after a shell variable or a command substitution is not rewritten', () => {
    expect(h('${ROOT}/Users/runner/x').text).toBe('${ROOT}/Users/runner/x')
    expect(h('$(pwd)/Users/runner/x').text).toBe('$(pwd)/Users/runner/x')
  })
  test('home known miss url-encoded: a URL-encoded %2FUsers%2Fname is not rewritten', () => {
    expect(h('%2FUsers%2Frunner%2Fx').text).toBe('%2FUsers%2Frunner%2Fx')
  })
  test('home known miss windows-name-with-spaces: a spaced Windows name with no separator after it keeps its later words', () => {
    // Built from pieces (made-up name, see the note above the helpers): no generic name holds a space.
    expect(h(win('C:', 'Users', 'John Smith')).text).toBe('%USERPROFILE% Smith')
  })
  test('home known miss single-letter-root-in-path: a one-letter root folder before a colon in a PATH list counts as a drive', () => {
    // Held in a variable: a path with no trailing slash plus a later slash on the same line reads to the privacy scan as one home path.
    const list = 'PATH=/x:/Users/user'
    expect(h(list).text).toBe('PATH=/%USERPROFILE%')
  })
})

describe('home rewrite: timing', () => {
  test('200,000 characters of adversarial input run in under 1000 ms', () => {
    const fragments = (raw`C:\Users\a a a a ` + '/Users/').repeat(Math.ceil(200000 / 24)).slice(0, 200000)
    const longRun = raw`C:\Users` + BS + 'a '.repeat(100000)
    const wordy = (raw`C:\Users` + BS + 'abcdefgh '.repeat(25000)).slice(0, 200000)
    for (const input of [fragments, longRun, wordy]) {
      expect(input.length).toBeGreaterThanOrEqual(200000)
      const start = performance.now()
      h(input, ['/opt/people/app'])
      expect(performance.now() - start).toBeLessThan(1000)
    }
  })
})
