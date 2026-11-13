import { expect, mock, test } from 'claude-code/testing'
import type { SessionAppendInput } from 'claude-code'

import { apiErrorNotice, appendSignal, ended, fresh, progressed, statePath, TICK_MS, turnEnded, turnStarted } from '../logic'

// Engine-level tests fire events through register.ts with the engine's answers stubbed; the
// row classification and the state rules are also tested as the pure functions they are.

const ROOT = '/work'
const FILE = (id: string) => `${ROOT}/.janitor/state/mod-liveness/${id}.json`

// Stubs every call register.ts makes; returns the files written, newest content per path.
function engine(on: any, ids: string[] = ['s1']) {
  const files = new Map<string, any>()
  const writes: string[] = []
  let idIndex = 0
  const clock = mock.clock(on, { now: 1000 })
  on('session.start', () => ({ cwd: ROOT }))
  on('turn.start', ($: any, e: any) => ({ turnId: e.turnId }))
  on('turn.complete', () => ({ text: '' }))
  on('session.end', ($: any, e: any) => ({ sessionId: e.sessionId }))
  on('session.id', () => ({ value: ids[Math.min(idIndex, ids.length - 1)] }))
  on('session.root', () => ({ value: ROOT }))
  on('fs.write', ($: any, e: any) => {
    files.set(e.path, JSON.parse(e.text))
    writes.push(e.path)
    return { value: undefined }
  })
  return { files, writes, clock, nextId: () => { idIndex += 1 } }
}

const start = ($: any) => $.session.start({ surface: 'terminal', isInteractive: true, cwd: ROOT })
const complete = ($: any, reason: string, extra: object = {}) =>
  $.turn.complete({ turnId: 't1', answer: '', durationMs: 1, isAborted: reason === 'aborted', usage: null, reason, ...extra })

test('session.start writes an idle report for this session with the heartbeat period', async ($, on) => {
  const { files } = engine(on)
  await start($)
  expect(files.get(FILE('s1'))).toEqual({
    schema: 1, session_id: 's1', kind: 'idle', since: 1000, alive_at: 1000, tick_ms: TICK_MS,
    retry: null, last_turn: null, end_reason: null,
  })
})

test('each tick stamps alive_at, so a stale stamp means the loop stopped', async ($, on) => {
  const { files, clock } = engine(on)
  await start($)
  await clock.advance(TICK_MS)
  expect(files.get(FILE('s1')).alive_at).toBe(1000 + TICK_MS)
  await clock.advance(TICK_MS)
  const report = files.get(FILE('s1'))
  expect(report.alive_at).toBe(1000 + 2 * TICK_MS)
  expect(report.since).toBe(1000)
  expect(report.kind).toBe('idle')
})

test('a main-loop turn.start reports working; a subagent turn changes nothing', async ($, on) => {
  const { files, clock } = engine(on)
  await start($)
  await clock.advance(5)
  await $.turn.start({ turnId: 'sub', agentId: 'a1', text: 'x' })
  expect(files.get(FILE('s1')).kind).toBe('idle')
  await $.turn.start({ turnId: 't1', text: 'x' })
  expect(files.get(FILE('s1'))).toMatchObject({ kind: 'working', since: 1005 })
})

test('a turn that dies on an API error reports api_error with its end', async ($, on) => {
  const { files } = engine(on)
  await start($)
  await $.turn.start({ turnId: 't1', text: 'x' })
  await complete($, 'error')
  expect(files.get(FILE('s1'))).toMatchObject({ kind: 'api_error', last_turn: { reason: 'error' } })
})

test('an interrupted turn (ESC) reports idle, the end reason aborted', async ($, on) => {
  const { files } = engine(on)
  await start($)
  await $.turn.start({ turnId: 't1', text: 'x' })
  await complete($, 'aborted')
  expect(files.get(FILE('s1'))).toMatchObject({ kind: 'idle', last_turn: { reason: 'aborted' } })
})

test('a subagent turn.complete leaves the main report alone', async ($, on) => {
  const { files } = engine(on)
  await start($)
  await $.turn.start({ turnId: 't1', text: 'x' })
  await complete($, 'error', { agentId: 'a1' })
  expect(files.get(FILE('s1')).kind).toBe('working')
})

test('/clear ends the old report and the next tick starts one for the new id', async ($, on) => {
  const { files, clock, nextId } = engine(on, ['s1', 's2'])
  await start($)
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
  expect(files.get(FILE('s1'))).toMatchObject({ kind: 'ended', end_reason: 'clear' })
  nextId()
  await clock.advance(TICK_MS)
  expect(files.get(FILE('s2'))).toMatchObject({ session_id: 's2', kind: 'idle' })
  expect(files.get(FILE('s1')).kind).toBe('ended')
})

test('session.end reports the session it names, even when the id already moved on', async ($, on) => {
  const { files, nextId } = engine(on, ['s1', 's2'])
  await start($)
  nextId()
  await $.session.end({ reason: 'clear', sessionId: 's1', resume: { id: 's1' } })
  expect(files.get(FILE('s1'))).toMatchObject({ kind: 'ended', end_reason: 'clear' })
  expect(files.has(FILE('s2'))).toBe(false)
})
test('api_error notice rows fired through session.append report api_retry with the count', async ($, on) => {
  const { files } = engine(on)
  mock.session(on)
  await start($)
  await $.turn.start({ turnId: 't1', text: 'x' })
  const notice = (uuid: string): SessionAppendInput => ({ door: 'notice', message: { type: 'system', name: 'api_error', content: [] }, origin: { kind: 'engine' }, uuid })
  await $.session.append(notice('u1'))
  await $.session.append(notice('u2'))
  expect(files.get(FILE('s1'))).toMatchObject({ kind: 'api_retry', retry: { count: 2, last_uuid: 'u2' } })
  // A response block after the retries means a request got through.
  await $.session.append({ door: 'response', message: { type: 'assistant', role: 'assistant', content: [{ type: 'text', text: 'hi' }] }, origin: { kind: 'model', model: 'm' }, uuid: 'u3' })
  expect(files.get(FILE('s1'))).toMatchObject({ kind: 'working', retry: null })
})
test('the measured end of a failed turn (notice, stand-in reply, error end) reports api_error with its retries', async ($, on) => {
  const { files } = engine(on)
  mock.session(on)
  await start($)
  await $.turn.start({ turnId: 't1', text: 'x' })
  await $.session.append({ door: 'notice', message: { type: 'system', name: 'api_error', content: [] }, origin: { kind: 'engine' }, uuid: 'u1' })
  await $.session.append({ door: 'response', message: { type: 'assistant', role: 'assistant', content: [{ type: 'text', text: 'API Error: 400' }] }, origin: { kind: 'model', model: '<synthetic>' }, uuid: 'u2' })
  await complete($, 'error')
  expect(files.get(FILE('s1'))).toMatchObject({ kind: 'api_error', retry: { count: 1, last_uuid: 'u1' }, last_turn: { reason: 'error' } })
})
test('only an engine api_error notice of the main loop counts as a retry', () => {
  const byEngine = { kind: 'engine' }
  const notice = { door: 'notice', message: { type: 'system', name: 'api_error' }, origin: byEngine }
  expect(appendSignal(notice)).toBe('api-error')
  expect(appendSignal({ ...notice, agentId: 'a1' })).toBe(null)
  expect(appendSignal({ door: 'notice', message: { type: 'system', name: 'informational' }, origin: byEngine })).toBe(null)
  // The words alone never count: a prompt or tool output quoting the countdown is not a retry.
  expect(appendSignal({ door: 'prompt', message: { type: 'user' }, origin: { kind: 'composer' } })).toBe(null)
  expect(appendSignal({ door: 'response', message: { type: 'assistant' }, origin: { kind: 'model', model: 'claude-x' } })).toBe('progress')
  expect(appendSignal({ door: 'tool-result', message: { type: 'user' }, origin: { kind: 'tool' } })).toBe('progress')
  expect(appendSignal({ door: 'attachment', message: { type: 'attachment', name: 'date' }, origin: byEngine })).toBe(null)
  // The engine's stand-in 'API Error: ...' reply that ends a failed turn is not progress.
  expect(appendSignal({ door: 'response', message: { type: 'assistant' }, origin: { kind: 'model', model: '<synthetic>' } })).toBe(null)
})

test('retries count up, keep the first time and the last row id, and clear on progress', () => {
  let s = turnStarted(fresh('s1', 0), 1)
  s = apiErrorNotice(s, 'u1', 10)
  s = apiErrorNotice(s, 'u2', 20)
  expect(s).toMatchObject({ kind: 'api_retry', since: 10, retry: { count: 2, first_at: 10, last_at: 20, last_uuid: 'u2' } })
  s = progressed(s, 30)
  expect(s).toMatchObject({ kind: 'working', since: 30, retry: null })
})

test('progress outside a retry run changes nothing', () => {
  const s = turnStarted(fresh('s1', 0), 1)
  expect(progressed(s, 5)).toBe(s)
})

test('an error end keeps the retry run; any other end clears it', () => {
  const retrying = apiErrorNotice(turnStarted(fresh('s1', 0), 1), 'u1', 2)
  expect(turnEnded(retrying, 'error', 3)).toMatchObject({ kind: 'api_error', retry: { count: 1 } })
  expect(turnEnded(retrying, 'aborted', 3)).toMatchObject({ kind: 'idle', retry: null })
  expect(ended(retrying, 'other', 4)).toMatchObject({ kind: 'ended', end_reason: 'other' })
})

test('the report path refuses an id that could leave the state folder', () => {
  expect(statePath('/w', 'ab-12_c')).toBe('/w/.janitor/state/mod-liveness/ab-12_c.json')
  expect(() => statePath('/w', '../x')).toThrow()
  expect(() => statePath('/w', 'a/b')).toThrow()
})
