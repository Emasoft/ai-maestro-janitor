import type { EngineInterface, Register } from 'claude-code'

import { addHits, countOf, isSecretFile, label, redact, redactDeep, type Hits } from './patterns'
import { shieldRow, withheldRow } from './rows'

// This session's tally; a reload starts it over, the all-time totals are in $.store.
const session: Hits = {}
const toasted = new Set<string>()

async function record($: EngineInterface, hits: Hits, source: string) {
  addHits(session, hits)
  const fresh = Object.keys(hits).filter(kind => !toasted.has(kind))
  if (fresh.length > 0) {
    for (const kind of fresh) toasted.add(kind)
    const what = Object.entries(hits).map(([kind, n]) => label(kind, n)).join(', ')
    $.ui.toast(`secret-shield hid ${what} from ${source}`)
  }
  const totals = ((await $.store.get('totals')) ?? {}) as Hits
  await $.store.set('totals', addHits({ ...totals }, hits))
}

function sourceOf(origin: { kind: string; tool?: unknown }): string {
  if (origin.kind === 'tool' && typeof origin.tool === 'string') return `${origin.tool} output`
  if (origin.kind === 'hook') return 'a hook'
  return 'the conversation'
}

function report(hits: Hits): string {
  const lines = Object.entries(hits)
    .sort((a, b) => b[1] - a[1])
    .map(([kind, n]) => `  ${label(kind, n)}`)
  return lines.length === 0 ? '  nothing yet' : lines.join('\n')
}

export const register: Register = (on, options) => {
  const blockFiles = options.blockSecretFiles === true
  const scanPrompts = options.redactPrompts === true

  on('session.start', async ($, e, next) => {
    await $.command.register({
      name: 'secret-shield',
      description: 'What secret-shield has hidden from Claude, or dry-run it: /secret-shield test <text>',
      argumentHint: '[test <text>]',
    })
    return next(e)
  })

  on('session.append', async ($, e, next) => {
    const shielded = shieldRow(e, scanPrompts)
    if (shielded === undefined) return next(e)

    const stored = await next({ ...e, message: { ...e.message, content: shielded.content } })
    try {
      await record($, shielded.hits, sourceOf(e.origin))
    } catch {
      // The tally is a nicety; the row is already stored redacted.
    }
    return stored
  }).catch(($, e, next) => {
    // Never store what could not be scanned: the row keeps its shape, not its text.
    const content = next.called ? undefined : withheldRow(e, scanPrompts)
    return content === undefined ? next(e) : next({ ...e, message: { ...e.message, content } })
  })

  on('tool.call', async ($, e, next) => {
    if (blockFiles) {
      const path =
        e.tool === 'Read' || e.tool === 'Edit' || e.tool === 'Write' ? e.file_path
        : e.tool === 'NotebookEdit' ? e.notebook_path
        : undefined
      if (path !== undefined && isSecretFile(path)) {
        $.ui.toast(`secret-shield kept Claude out of ${path.split('/').pop()}`)
        return {
          deny:
            `secret-shield: ${path} holds secrets, and this session keeps Claude out of secret files. ` +
            'Ask the user for the specific non-secret value you need, or use the .env.example file instead.',
        }
      }
    }

    // Redact the tool's own record too: answered with a new `result`, core
    // maps it for the model and stores it as the call's result, so neither
    // the model nor the transcript's display copy keeps the secret.
    const ran = await next(e)
    if (ran.deny !== undefined || ran.isError === true) return ran
    const { value, hits } = redactDeep(ran.result)
    if (countOf(hits) === 0) return ran
    try {
      await record($, hits, `${e.tool} output`)
    } catch {
      // The tally is a nicety.
    }
    return ran.context === undefined ? { result: value as typeof ran.result } : { result: value as typeof ran.result, context: ran.context }
  })

  on('command.run', { command: 'secret-shield' }, async ($, e) => {
    const args = e.args.trim()
    if (args.startsWith('test')) {
      const sample = args.slice(4).trim()
      if (sample === '') return { text: 'Usage: /secret-shield test <text to scan>' }
      const { text, hits } = redact(sample)
      return {
        text: countOf(hits) === 0
          ? 'secret-shield: nothing to hide in that text.'
          : `secret-shield would hide ${Object.entries(hits).map(([k, n]) => label(k, n)).join(', ')}:\n${text}`,
      }
    }
    const totals = ((await $.store.get('totals')) ?? {}) as Hits
    return {
      text: [
        `secret-shield is on${blockFiles ? ', and blocks secret files' : ''}${scanPrompts ? ', scanning prompts too' : ''}.`,
        `Hidden this session (${countOf(session)}):`,
        report(session),
        `Hidden all time (${countOf(totals)}):`,
        report(totals),
      ].join('\n'),
    }
  })
}
