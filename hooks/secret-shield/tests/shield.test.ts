import { expect, mock, test } from 'claude-code/testing'

import { isScanned, shieldRow, withheldRow, WITHHELD } from '../rows'

// This build's test kit cannot answer beneath `session.append` (a stub that
// answers is skipped, and nothing else does), so the hook's row logic is
// tested here as the pure function it calls, and end to end in a live run.

const j = (...parts: string[]) => parts.join('')
const fakeGithubToken = () => j('gh', 'p_', 'aB3dE5fG7hJ9kL1mN3pQ5rS7tU9vW1xY3zA5')
const TOKEN = fakeGithubToken()
const AWS = j('AKIA', 'Q3EGRVJ4Z7XWLP2N')
const TYPED = { origin: { kind: 'composer' }, presentation: { isFullscreen: false, columns: 100 } } as const

const bashRow = (text: string) => ({
  door: 'tool-result',
  message: { content: [{ type: 'tool_result', tool_use_id: 'toolu_1', content: text }] },
})

test('a token in Bash output comes back redacted, with what was hidden', () => {
  const shielded = shieldRow(bashRow(`GH=${TOKEN}\nKEY=${AWS}`), false)
  expect(shielded?.content).toEqual([
    { type: 'tool_result', tool_use_id: 'toolu_1', content: 'GH=[JANITOR-REDACTED:github-token]\nKEY=[JANITOR-REDACTED:aws-access-key]' },
  ])
  expect(shielded?.hits).toEqual({ 'github-token': 1, 'aws-access-key': 1 })
})

test('a clean row is left as it is', () => {
  expect(shieldRow(bashRow('total 0\ndrwxr-xr-x  2 me  staff  64 .'), false)).toBeUndefined()
})

test('tool output, attachments and hook context are scanned; replies are not', () => {
  for (const door of ['tool-result', 'tool-message', 'attachment', 'hook-context', 'delivery']) expect(isScanned(door, false)).toBe(true)
  for (const door of ['response', 'command', 'note', 'notice', 'compaction']) expect(isScanned(door, false)).toBe(false)
})

test('prompts are scanned only with redactPrompts', () => {
  const prompt = { door: 'prompt', message: { content: [{ type: 'text', text: `use ${TOKEN}` }] } }
  expect(shieldRow(prompt, false)).toBeUndefined()
  expect(shieldRow(prompt, true)?.content).toEqual([{ type: 'text', text: 'use [JANITOR-REDACTED:github-token]' }])
})

test('a row that could not be scanned keeps its shape, not its text', () => {
  expect(withheldRow(bashRow(TOKEN), false)).toEqual([{ type: 'tool_result', tool_use_id: 'toolu_1', content: WITHHELD }])
  expect(withheldRow({ door: 'response', message: { content: [] } }, false)).toBeUndefined()
})

test('secret files are readable by default', async ($, on) => {
  on('tool.call', () => ({ result: { type: 'text', file: { filePath: '.env', content: '', numLines: 0, startLine: 1, totalLines: 0 } } }))
  const out = await $.tool.call({ tool: 'Read', file_path: '/work/.env' })
  expect(out.deny).toBeUndefined()
})

test('secret_shield_block_files keeps Claude out of .env and keys, not .env.example', { options: { secret_shield_block_files: true } }, async ($, on) => {
  const toasts: string[] = []
  on('ui.toast', ($, e) => (toasts.push(e.text), { value: undefined }))
  on('tool.call', () => ({ result: { type: 'text', file: { filePath: 'x', content: '', numLines: 0, startLine: 1, totalLines: 0 } } }))

  const env = await $.tool.call({ tool: 'Read', file_path: '/work/.env.local' })
  const example = await $.tool.call({ tool: 'Read', file_path: '/work/.env.example' })
  const key = await $.tool.call({ tool: 'Edit', file_path: '/home/User/.ssh/id_ed25519', old_string: 'a', new_string: 'b' })
  const code = await $.tool.call({ tool: 'Write', file_path: '/work/src/env.ts', content: 'x' })

  expect(env.deny).toMatch(/holds secrets/)
  expect(example.deny).toBeUndefined()
  expect(key.deny).toMatch(/holds secrets/)
  expect(code.deny).toBeUndefined()
  expect(toasts).toEqual(['secret-shield kept Claude out of .env.local', 'secret-shield kept Claude out of id_ed25519'])
})

test('/secret-shield test dry-runs a text', async ($, on) => {
  const dry = await $.command.run({ command: 'secret-shield', args: `test token=${TOKEN}`, ...TYPED })
  expect(dry.text).toMatch(/would hide 1 GitHub token/)
  expect(dry.text).toContain('[JANITOR-REDACTED:github-token]')

  const clean = await $.command.run({ command: 'secret-shield', args: 'test hello world', ...TYPED })
  expect(clean.text).toBe('secret-shield: nothing to hide in that text.')
})

test('/secret-shield reports the all-time tally from the store', async ($, on) => {
  mock.store(on, { totals: { 'github-token': 4, 'aws-access-key': 1 } })

  const status = await $.command.run({ command: 'secret-shield', args: '', ...TYPED })

  expect(status.text).toMatch(/^secret-shield is on\./)
  expect(status.text).toMatch(/Hidden this session \(0\):\n {2}nothing yet/)
  expect(status.text).toMatch(/Hidden all time \(5\):\n {2}4 GitHub tokens\n {2}1 AWS access key/)
})

test('the session.start hook registers /secret-shield', async ($, on) => {
  const names: string[] = []
  on('command.register', ($, e) => (names.push(e.name), { value: { command: e.name } }))
  on('session.start', () => ({ cwd: '/work' }))

  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

  expect(names).toEqual(['secret-shield'])
})

test('a tool\'s own result is redacted too, so the display copy keeps no secret', async ($, on) => {
  mock.store(on)
  const toasts: string[] = []
  on('ui.toast', ($, e) => (toasts.push(e.text), { value: undefined }))
  const stdout = `pushed with ${fakeGithubToken()}`
  on('tool.call', () => ({ result: { stdout, stderr: '', interrupted: false } }))

  const out = await $.tool.call({ tool: 'Bash', command: 'cat build.log' })

  expect(out.result).not.toEqual({ stdout, stderr: '', interrupted: false })
  expect(out.result).toEqual({ stdout: 'pushed with [JANITOR-REDACTED:github-token]', stderr: '', interrupted: false })
  expect(toasts).toEqual(['secret-shield hid 1 GitHub token from Bash output'])
})

test('a result with nothing to hide comes back as core gave it', async ($, on) => {
  const given = { result: { stdout: 'ok', stderr: '', interrupted: false } }
  on('tool.call', () => given)

  const out = await $.tool.call({ tool: 'Bash', command: 'echo ok' })

  expect(out).toEqual(given)
})

test('nested results (Read) are walked and keep their shape', async ($, on) => {
  mock.store(on)
  on('ui.toast', () => ({ value: undefined }))
  on('tool.call', () => ({ result: { type: 'text', file: { filePath: '/w/a.txt', content: `KEY=${AWS}\n`, numLines: 1, startLine: 1, totalLines: 1 } } }))

  const out = await $.tool.call({ tool: 'Read', file_path: '/w/a.txt' })

  expect(out.result).toEqual({ type: 'text', file: { filePath: '/w/a.txt', content: 'KEY=[JANITOR-REDACTED:aws-access-key]\n', numLines: 1, startLine: 1, totalLines: 1 } })
})

test('/secret-shield counts what this session hid', async ($, on) => {
  mock.store(on, { totals: { 'github-token': 4 } })
  on('ui.toast', () => ({ value: undefined }))
  on('tool.call', () => ({ result: { stdout: TOKEN, stderr: '', interrupted: false } }))

  await $.tool.call({ tool: 'Bash', command: 'env' })
  const status = await $.command.run({ command: 'secret-shield', args: '', ...TYPED })

  expect(status.text).toMatch(/Hidden this session \(1\):\n {2}1 GitHub token/)
  expect(status.text).toMatch(/Hidden all time \(5\):\n {2}5 GitHub tokens/)
})

test('secret_shield_enabled false registers no hook', { options: { secret_shield_enabled: false } }, async ($, on) => {
  const names: string[] = []
  on('command.register', ($, e) => (names.push(e.name), { value: { command: e.name } }))
  on('session.start', () => ({ cwd: '/work' }))
  const stdout = `pushed with ${fakeGithubToken()}`
  on('tool.call', () => ({ result: { stdout, stderr: '', interrupted: false } }))

  const out = await $.tool.call({ tool: 'Bash', command: 'cat build.log' })
  await $.session.start({ surface: 'terminal', isInteractive: true, cwd: '/work' })

  expect(out.result).toEqual({ stdout, stderr: '', interrupted: false })
  expect(names).toEqual([])
})
