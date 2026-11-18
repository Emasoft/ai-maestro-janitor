// WHY this file exists (TRDD-CAZIKQVH): the live shield (redactDeep on a tool result, redactBlocks on a row, the dry-run command) and the bridge op "both" read a text as plain text, so a JSON line
// inside it kept a secret written behind a JSON escape; 16 bench lines came back unchanged. redactText runs the old walks first, unchanged, then reads the strings of each line that still is a JSON
// object or array with redactJsonLine's JSON walk, then hides the copies. The fakes are cut in the source and joined at run time; a PEM marker is split, and no assertion prints a value.
import { describe, expect, mock, test } from 'claude-code/testing'

import { countOf, mark, redact, redactBlocks, redactDeep, redactJsonLine, redactText } from '../patterns'

const j = (...parts: string[]) => parts.join('')
const PW = j('Zq8', 'vT3', 'mK9', 'xW2', 'pL7', 'Rb4')
const TOK = j('abcd', 'EFGH', '1234', 'ijkl', 'MNOP', '5678')
const PW2 = j('Hn5', 'cY1', 'Qa7', 'Ld3', 'Wf9', 'Ks2')
const PW3 = j('Tg6', 'uE8', 'Np4', 'Jb1', 'Vr5', 'Xc7')
const TYPED = { origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } } as const

// Each line holds an assignment right after an escaped newline: in the raw line the rule anchored to a line start finds no line start, in the decoded string it does.
const ENV = { name: 'an env assignment', line: JSON.stringify({ content: j('line one\n', 'DB_PASSWORD=', PW, '\nline three') }), value: PW }
const EXPORT = { name: 'an export', line: JSON.stringify({ content: j('# env\n', 'export API_TOKEN=', TOK, '\n') }), value: TOK }
const YAML = { name: 'a YAML key', line: JSON.stringify({ content: j('db:\n  password: ', PW2, '\n') }), value: PW2 }
const SHAPES = [ENV, EXPORT, YAML]

const KEY_BEGIN = j('-----BEGIN ', 'RSA PRIVATE KEY-----')
const KEY_END = j('-----END ', 'RSA PRIVATE KEY-----')
const KEY_BODY = [j('MIIEpAIBAAKCAQEA', 'q8vT3mK9xW2pL7Rb4Hn5'), j('cY1Qa7Ld3Wf9Ks2', 'abcdEFGH1234ijklQ')]
const GHP = j('ghp', '_', TOK, TOK)

describe('the inputs of this file are leaks the plain pass cannot see', () => {
  test('redact() leaves the value of each JSON line whole, and redactJsonLine hides it', () => {
    for (const shape of SHAPES) {
      expect(redact(shape.line).text.includes(shape.value)).toBe(true)
      expect(redactJsonLine(shape.line).text.includes(shape.value)).toBe(false)
    }
  })
})

describe('redactText reads each JSON line of a text as JSON', () => {
  test('a JSON line inside a text of other lines is hidden, and the text keeps its lines, the other lines byte for byte', () => {
    for (const shape of SHAPES) {
      const lines = ['$ cat records.jsonl', shape.line, 'done']
      const out = redactText(lines.join('\n'))
      const got = out.text.split('\n')
      expect(got.length).toBe(3)
      expect(got[0]).toBe(lines[0])
      expect(got[2]).toBe(lines[2])
      expect(out.text.includes(shape.value)).toBe(false)
      expect(() => JSON.parse(got[1] ?? '')).not.toThrow()
      expect(countOf(out.hits)).toBeGreaterThan(0)
    }
  })

  test('a JSON line whose secret the plain pass misses comes back as redactJsonLine gives it: the plain pass leaves it as it is, and the JSON walk reads it as redactJsonLine reads it', () => {
    for (const shape of SHAPES) expect(redactText(shape.line)).toEqual(redactJsonLine(shape.line))
  })

  test('a text with no JSON line comes back as redact() gives it', () => {
    const texts = [
      '',
      j('DB_PASSWORD=', PW3),
      [KEY_BEGIN, ...KEY_BODY, KEY_END, 'after'].join('\n'),
      j('[INFO] start\r\n', 'DB_PASSWORD=', PW3, '\r\n{not json\r\n'),
      j('{"open": "', PW, '"\n', 'export API_TOKEN=', TOK),
    ]
    for (const text of texts) expect(redactText(text)).toEqual(redact(text))
  })

  test('the rules still read the whole text at once: a key block with a JSON line inside it is hidden whole, as before, and an assignment line too', () => {
    const text = [KEY_BEGIN, ...KEY_BODY.slice(0, 1), ENV.line, ...KEY_BODY.slice(1), KEY_END, j('DB_PASSWORD=', PW3), EXPORT.line].join('\n')
    const out = redactText(text)
    for (const body of KEY_BODY) expect(out.text.includes(body)).toBe(false)
    for (const value of [PW, PW3, TOK]) expect(out.text.includes(value)).toBe(false)
    const got = out.text.split('\n')
    // One marker for the whole block, from its first line to its last: the key rule read the five lines in one piece, the JSON line among them.
    expect(got[0]).toBe(mark('private-key'))
    expect(got.length).toBe(3)
    expect(() => JSON.parse(got[2] ?? '')).not.toThrow()
  })

  test('a JSON line that ends in a carriage return is read as JSON, and the text keeps its CRLF line ends', () => {
    const text = ['first', ENV.line, 'last'].join('\r\n')
    const out = redactText(text)
    expect(out.text.includes(PW)).toBe(false)
    expect(out.text.split('\r\n').length).toBe(3)
  })
})

describe('the old walks run first, unchanged, so reading JSON lines only adds to what they hide', () => {
  // WHY these two (measured 2026-11-18): with redactJsonLine's order (its JSON walk before the plain rules) both came back with text the old walks hid.
  test('a key block opened inside a JSON string and closed on a later line is hidden through its end line, as before', () => {
    const text = [JSON.stringify({ content: j('x ', KEY_BEGIN) }), ...KEY_BODY, KEY_END].join('\n')
    const out = redactText(text)
    for (const body of KEY_BODY) expect(out.text.includes(body)).toBe(false)
    expect(out.text.includes(KEY_END)).toBe(false)
    expect(out).toEqual(redact(text))
  })

  test('two tokens glued after an escaped tab in a JSON line are hidden as before', () => {
    const text = JSON.stringify({ content: j(GHP, ';\t', GHP, GHP) })
    const out = redactText(text)
    expect(out.text.includes(TOK)).toBe(false)
    expect(out).toEqual(redact(text))
  })
})

describe('a value found in one line is hidden in every line of the text', () => {
  test('a value found in a JSON line is hidden where it is copied into a plain line', () => {
    const out = redactText([ENV.line, j('echo ', PW, ' done')].join('\n'))
    expect(out.text.includes(PW)).toBe(false)
    expect(out.text.split('\n')[1]).not.toBe(j('echo ', PW, ' done'))
  })

  test('a value found in a plain line is hidden in a JSON line that writes it behind a backslash-u escape, and the line stays JSON', () => {
    const escaped = '\\u' + PW3.charCodeAt(0).toString(16).padStart(4, '0') + PW3.slice(1)
    const jsonLine = '{"note":"seen ' + escaped + ' twice"}'
    expect(JSON.parse(jsonLine).note.includes(PW3)).toBe(true)
    const out = redactText([j('DB_PASSWORD=', PW3), jsonLine].join('\n'))
    const note: string = JSON.parse(out.text.split('\n')[1] ?? '').note
    expect(note.includes(PW3)).toBe(false)
    expect(note.startsWith('seen ')).toBe(true)
  })

  test('redactBlocks: a value found in a JSON line of one block is hidden where another block copies it plain', () => {
    const out = redactBlocks([
      { type: 'text', text: ENV.line },
      { type: 'tool_result', tool_use_id: 'toolu_1', content: [{ type: 'text', text: j('echo ', PW, ' done') }] },
    ])
    expect(JSON.stringify(out.content).includes(PW)).toBe(false)
  })

  test('redactBlocks: a value found in a plain block is hidden where another block writes it behind a backslash-u escape in a JSON line', () => {
    const escaped = '\\u' + PW3.charCodeAt(0).toString(16).padStart(4, '0') + PW3.slice(1)
    const out = redactBlocks([
      { type: 'text', text: j('DB_PASSWORD=', PW3) },
      { type: 'text', text: '{"note":"seen ' + escaped + ' twice"}' },
    ])
    const note: string = JSON.parse(String(out.content[1]?.text ?? '')).note
    expect(note.includes(PW3)).toBe(false)
    expect(note.startsWith('seen ')).toBe(true)
  })
})

describe('a token right after an escape inside a string of a whole JSON line (KNOWN-MISSES escape-boundary)', () => {
  test('redact() leaves it, redactText hides it on a whole JSON line, and a line with a prefix still shows it', () => {
    const tokens = [
      j('gh', 'p_', 'Ya7P3Y9cF9Jn', 'mXeekmflpukr', 'wSFtXiUA5PkO'),
      j('AK', 'IA', '84853HRP', 'O22WAJW5'),
      j('xo', 'xb-', '5065969875', '-', '0509749660', '-', 'zDynHn4HnpmB', 'wUjbocXfjj3r'),
      j('npm', '_', '1AfaIySP80jWP2', 'iI40g0TjHWk0', 'kvx1Se7PsN'),
    ]
    for (const token of tokens) for (const escape of ['\n', '\t']) {
      const line = JSON.stringify({ c: j('x', escape, token) })
      expect(redact(line).text.includes(token)).toBe(true)
      expect(redactText(line).text.includes(token)).toBe(false)
      expect(redactText(['$ cat a.jsonl', line, 'done'].join('\n')).text.includes(token)).toBe(false)
      expect(redactText(j('a.jsonl:3:', line)).text.includes(token)).toBe(true)
    }
  })
})

describe('the copy pass with many values', () => {
  const value = (i: number) => j('Vk', i.toString(36).padStart(4, '0'), 'Qp7Ws3', 'Zx9')
  test('300 values found in plain lines (over the 256 forms where the index starts) are hidden where one JSON line copies them all, the last one at the end of its string', () => {
    const lines = Array.from({ length: 300 }, (_, i) => j('export API_TOKEN=', value(i)))
    const copies = JSON.stringify({ note: Array.from({ length: 300 }, (_, i) => value(i)).join(' ') })
    const out = redactText([...lines, copies].join('\n'))
    for (let i = 0; i < 300; i++) expect(out.text.includes(value(i))).toBe(false)
    expect(() => JSON.parse(out.text.split('\n')[300] ?? '')).not.toThrow()
  })

  // WHY: past 256 forms the index finds the values in the order they appear in the text; hidePiece must still take them longest first, or the shorter value cuts the longer one.
  test('a value that contains another is hidden whole when the shorter one comes first in the text and there are more than 256 values', () => {
    const short = j('Ks', '4Tq9', 'Wz2Lp')
    const long = j(short, 'Nb7', 'Yc3Hv')
    const lines = [...Array.from({ length: 300 }, (_, i) => j('export API_TOKEN=', value(i))), j('export API_KEY=', short), j('export SECRET_KEY=', long)]
    const copies = JSON.stringify({ note: j('first ', short, ' then ', long, ' end') })
    const out = redactText([...lines, copies].join('\n'))
    expect(out.text.includes(short)).toBe(false)
    expect(out.text.includes(j('Nb7', 'Yc3Hv'))).toBe(false)
  })

  // WHY a growth ratio and not a time bound (measured 2026-11-18): cutting each string by every found value grew with lines times values, 12 s on 2,000 such lines and 24 s on 4,000 in this
  // file, over the 10 s a hook may take, and a hook that times out after next() leaves the raw result. With the index the time grows with the text. A wall-clock bound failed on this host at
  // load 100 (11 s for 4,000 lines that took 1.2 s at load 8), and the test runtime has no CPU clock, so the test compares two sizes in the same run: 16 times the lines takes about 16 times as
  // long with the index (14 to 17 times, measured in bun) and 215 to 368 times without it.
  test('4,000 JSON lines that each carry two distinct secrets take less than 48 times as long as 250', () => {
    const line = (i: number) => JSON.stringify({ type: 'row', content: j('header ', 'gh', 'p_', i.toString(36).padStart(6, '0'), 'Qm8Zr4Tx', 'Wn6Kd2Vp', 'Hs9Lc3Yb', 'Rt5Bk', ' and\n', 'DB_PASSWORD=', 'Pw', i.toString(36).padStart(6, '0'), 'Xq7Lm', '\ntail') })
    const text = (n: number) => Array.from({ length: n }, (_, i) => line(i)).join('\n')
    const timed = (t: string) => {
      const started = performance.now()
      const out = redactDeep({ file: { content: t } })
      return { ms: performance.now() - started, out }
    }
    const small = text(250)
    const large = text(4000)
    timed(small)
    const smallMs = Math.min(timed(small).ms, timed(small).ms, timed(small).ms)
    const first = timed(large)
    const largeMs = Math.min(first.ms, timed(large).ms)
    expect(largeMs / smallMs).toBeLessThan(48)
    expect(JSON.stringify(first.out.value).includes(j('Pw', '000000', 'Xq7Lm'))).toBe(false)
  })
})

describe('the live shield reads a JSON line of a text as JSON', () => {
  test('redactDeep hides each shape in the content of a Read result and in a Bash stdout', () => {
    for (const shape of SHAPES) {
      const read = redactDeep({ type: 'text', file: { filePath: '/work/records.jsonl', content: ['first', shape.line, ''].join('\n') } })
      expect(JSON.stringify(read.value).includes(shape.value)).toBe(false)
      expect(countOf(read.hits)).toBeGreaterThan(0)
      const bash = redactDeep({ stdout: shape.line, stderr: '', interrupted: false })
      expect(JSON.stringify(bash.value).includes(shape.value)).toBe(false)
    }
  })

  test('redactBlocks hides each shape in a text block and in a tool_result', () => {
    for (const shape of SHAPES) {
      const out = redactBlocks([
        { type: 'text', text: shape.line },
        { type: 'tool_result', tool_use_id: 'toolu_1', content: [{ type: 'text', text: ['x', shape.line].join('\n') }] },
      ])
      expect(JSON.stringify(out.content).includes(shape.value)).toBe(false)
      expect(countOf(out.hits)).toBeGreaterThan(0)
    }
  })

  test('a Bash result whose stdout prints a JSON line comes back with the value hidden', async ($, on) => {
    mock.store(on)
    on('ui.toast', () => ({ value: undefined }))
    const stdout = ['{"ok":true}', ENV.line].join('\n')
    on('tool.call', () => ({ result: { stdout, stderr: '', interrupted: false } }))
    const out = await $.tool.call({ tool: 'Bash', command: 'cat records.jsonl' })
    expect(JSON.stringify(out.result).includes(PW)).toBe(false)
    expect(JSON.stringify(out.result).includes('{\\"ok\\":true}')).toBe(true)
  })

  test('/janitor-secret-shield test hides a JSON line as the live hooks do', async ($, on) => {
    const dry = await $.command.run({ command: 'janitor-secret-shield', args: 'test ' + ENV.line, ...TYPED })
    expect(dry.text).toMatch(/would hide/)
    expect(dry.text?.includes(PW)).toBe(false)
  })
})
