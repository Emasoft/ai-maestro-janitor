// Liveness report for the janitor daemon (TRDD-R9NLNV3W). Pure functions only: no $ here,
// so every rule below is unit-tested without the engine. register.ts feeds events in and
// writes the result to one file per session.
//
// What the mod can see that the pane and the transcript cannot: whether this session's own
// event loop still ticks. alive_at is stamped on every timer tick; when it is older than about
// 3 * tick_ms, either the loop stopped or the process is gone, so a reader checks the process
// first. Whether the owner's frozen API-error countdown shows up as a stale alive_at or as an
// old retry.last_at is not measured yet: that freeze has not been reproduced. The mod only
// REPORTS: a stopped loop cannot run the mod either, so recovery stays in the external daemon
// (TRDD-RJJGXPIK).

export const SCHEMA = 1
// At least 30 s between heartbeats (TRDD-R9NLNV3W design constraint), so a reader treats a
// file older than about 3 * TICK_MS as a stopped loop.
export const TICK_MS = 30_000

// idle: no turn running. working: a turn is running. api_retry: the engine is retrying a
// failed model request (one api_error notice per attempt, measured live on 2.1.323).
// api_error: the turn ended on an API error (retries exhausted), so nothing runs until a
// prompt arrives. ended: session.end fired (exit, /clear, /resume, /branch).
export type Kind = 'idle' | 'working' | 'api_retry' | 'api_error' | 'ended'
export type TurnEnd = 'answer' | 'aborted' | 'refusal' | 'error'

export type Retry = {
  // api_error notices since the turn's last progress: the attempt count the countdown shows.
  count: number
  first_at: number
  last_at: number
  // The notice row's uuid: the transcript row with this uuid holds retryAttempt, maxRetries
  // and retryInMs, which the notice's own content does not carry (it is empty).
  last_uuid: string
}

export type Liveness = {
  schema: typeof SCHEMA
  session_id: string
  kind: Kind
  // ms since the epoch when kind last changed
  since: number
  // ms since the epoch of the last heartbeat or event
  alive_at: number
  tick_ms: number
  retry: Retry | null
  last_turn: { reason: TurnEnd; at: number } | null
  end_reason: string | null
}

export function fresh(sessionId: string, now: number): Liveness {
  return { schema: SCHEMA, session_id: sessionId, kind: 'idle', since: now, alive_at: now, tick_ms: TICK_MS, retry: null, last_turn: null, end_reason: null }
}

function to(s: Liveness, kind: Kind, now: number): Liveness {
  return s.kind === kind ? { ...s, alive_at: now } : { ...s, kind, since: now, alive_at: now }
}

export function ticked(s: Liveness, now: number): Liveness {
  return { ...s, alive_at: now }
}

export function turnStarted(s: Liveness, now: number): Liveness {
  return { ...to(s, 'working', now), retry: null }
}

export function apiErrorNotice(s: Liveness, uuid: string, now: number): Liveness {
  const prev = s.retry
  const retry: Retry = { count: (prev?.count ?? 0) + 1, first_at: prev?.first_at ?? now, last_at: now, last_uuid: uuid }
  return { ...to(s, 'api_retry', now), retry }
}

// A response block or a tool result after a retry run means a request got through.
export function progressed(s: Liveness, now: number): Liveness {
  return s.kind === 'api_retry' ? { ...to(s, 'working', now), retry: null } : s
}

export function turnEnded(s: Liveness, reason: TurnEnd, now: number): Liveness {
  const last_turn = { reason, at: now }
  // An error end keeps the retry run, so the reader sees how many attempts preceded it.
  if (reason === 'error') return { ...to(s, 'api_error', now), last_turn }
  return { ...to(s, 'idle', now), retry: null, last_turn }
}

export function ended(s: Liveness, reason: string, now: number): Liveness {
  return { ...to(s, 'ended', now), end_reason: reason }
}

export type AppendSignal = 'api-error' | 'progress' | null

// Keys on the row's structure, never on its text: prompts, tool output and replies in this
// project quote 'API Error' and 'Retrying in ... attempt' all the time.
export function appendSignal(e: { door: string; message: { type: string; name?: string }; origin: { kind: string; model?: string }; agentId?: string }): AppendSignal {
  // A subagent's rows describe its own loop, not the main session's.
  if (e.agentId !== undefined) return null
  if (e.door === 'notice' && e.message.type === 'system' && e.message.name === 'api_error') return 'api-error'
  // The engine's stand-in reply ('API Error: ...' when retries run out) also comes in by the
  // response door, as model '<synthetic>', just before turn.complete with reason error
  // (measured on 2.1.323). It is no progress: counting it would wipe the retry run.
  if (e.door === 'response' && e.origin.kind === 'model' && e.origin.model === '<synthetic>') return null
  if (e.door === 'response' || e.door === 'tool-result') return 'progress'
  return null
}

// One file per session, so two sessions in one project never overwrite each other. Mirrors
// scripts/lib/state.py: <project-root>/.janitor/state/.
export function statePath(root: string, sessionId: string): string {
  // The id names a file: refuse anything that could leave the folder.
  if (!/^[A-Za-z0-9_-]+$/.test(sessionId)) throw new Error(`liveness: unexpected session id ${JSON.stringify(sessionId)}`)
  return `${root}/.janitor/state/mod-liveness/${sessionId}.json`
}

export function serialize(s: Liveness): string {
  return JSON.stringify(s) + '\n'
}
