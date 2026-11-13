import type { EngineInterface, Register } from 'claude-code'

import { apiErrorNotice, appendSignal, ended, fresh, progressed, serialize, statePath, ticked, TICK_MS, turnEnded, turnStarted, type Liveness } from './logic'

// Janitor liveness mod (TRDD-R9NLNV3W): reports this session's own liveness to
// <project-root>/.janitor/state/mod-liveness/<session-id>.json for the janitor daemon.
// It never acts on the session (no turn.abort, prompt.submit, session.compact, command.run):
// a frozen session freezes this mod too, so recovery stays external (TRDD-RJJGXPIK).
//
// Each hook calls next(e) before writing, so a failed write (logged by the engine as a
// skipped hook) can never hold back or drop the event it observed.

let live: Liveness | null = null

// The state for the session running now. /clear, /resume and /branch give the session a new
// id without a new session.start, so the id is read again and a new id starts a new report.
async function current($: EngineInterface, now: number): Promise<Liveness> {
  const id = await $.session.id()
  if (live === null || live.session_id !== id) live = fresh(id, now)
  return live
}

async function save($: EngineInterface, next: Liveness): Promise<void> {
  live = next
  await $.fs.write(statePath(await $.session.root(), next.session_id), serialize(next))
}

async function tick($: EngineInterface): Promise<void> {
  const now = await $.clock.now()
  await save($, ticked(await current($, now), now))
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    // Started once per load: the heartbeat outlives /clear, which fires no session.start.
    $.clock.every(TICK_MS, () => tick($))
    const now = await $.clock.now()
    await save($, fresh(await $.session.id(), now))
    return result
  })

  on('turn.start', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined) {
      const now = await $.clock.now()
      await save($, turnStarted(await current($, now), now))
    }
    return result
  })

  on('session.append', async ($, e, next) => {
    // Decided from e alone, so the many rows that change nothing cost no mods API call.
    const signal = appendSignal(e)
    const result = await next(e)
    if (signal === 'api-error') {
      const now = await $.clock.now()
      await save($, apiErrorNotice(await current($, now), e.uuid, now))
    } else if (signal === 'progress' && live?.kind === 'api_retry') {
      const now = await $.clock.now()
      await save($, progressed(await current($, now), now))
    }
    return result
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    if (e.agentId === undefined) {
      const now = await $.clock.now()
      await save($, turnEnded(await current($, now), e.reason, now))
    }
    return result
  })

  on('session.end', async ($, e, next) => {
    // Written before next: on exit the process may not outlive the end hooks' 1.5 s budget.
    const now = await $.clock.now()
    // e.sessionId names the session that ends; after /clear $.session.id() may already be the next one.
    const ending = live !== null && live.session_id === e.sessionId ? live : fresh(e.sessionId, now)
    await save($, ended(ending, e.reason, now))
    return next(e)
  })
}
