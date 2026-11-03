// Which conversation rows secret-shield scans, and the row it stores instead: no `$`.

import { countOf, redactBlocks, withhold, type Hits } from './patterns'

type Block = { type: string; [field: string]: unknown }
type Row = { door: string; message: { content: readonly Block[] } }

// The doors that carry text from outside the conversation: tool output, the
// rows a tool hands over, files the engine attaches, settings hooks' context.
const SCANNED = new Set(['tool-result', 'tool-message', 'attachment', 'hook-context', 'delivery'])

export const WITHHELD = '[secret-shield withheld this output: it could not be scanned for secrets]'

export function isScanned(door: string, scanPrompts: boolean): boolean {
  return SCANNED.has(door) || (scanPrompts && door === 'prompt')
}

/** The row's redacted content and what was hidden, or undefined when it keeps as it is. */
export function shieldRow(row: Row, scanPrompts: boolean): { content: Block[]; hits: Hits } | undefined {
  if (!isScanned(row.door, scanPrompts)) return undefined
  const done = redactBlocks(row.message.content)
  return countOf(done.hits) === 0 ? undefined : done
}

/** What a row that could not be scanned keeps: its blocks, not their text. */
export function withheldRow(row: Row, scanPrompts: boolean): Block[] | undefined {
  return isScanned(row.door, scanPrompts) ? withhold(row.message.content, WITHHELD) : undefined
}
