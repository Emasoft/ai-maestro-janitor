// The one entry point that owns the order of the core passes (TRDD-L1I0FP5T increment 5): secrets, payment cards, email addresses, home paths.
// WHY it exists: the order used to live in the callers (the janitor bridge ran redact then redactHome; the report sanitizer ran redact then redactCards, its Python rules ending in email, then the home op). A third caller, the scan skill (TRDD-BAQB9SYO), would have been a third copy. A caller calls redactAll and carries no pass order of its own.
// Pure: no env read, no fs, no os.homedir(); the caller passes the home literals it knows. No regex lives here: every rule is in the pass it calls.

import { redactCards } from './cards'
import { redactEmails } from './email'
import type { EmailOptions } from './email'
import { redactHome } from './home'
import { addHits, redact } from './patterns'
import type { Hits } from './patterns'

// WHY this order, each step fed the previous step's output text:
//   cards after secrets: a digit run inside a token is already a marker, so the card pass cannot split a token.
//   email before home: a name inside an email address is hidden by the email pass first, so the home pass no longer sees it (report-sanitizer runs the same relative order of these four core passes: shield and cards, then its Python rules ending in email, then the home op).
export const PASS_ORDER = ['secrets', 'cards', 'email', 'home'] as const
export type Pass = (typeof PASS_ORDER)[number]
// WHY the pass set is a parameter: the home pass is about half the CPU (TRDD-BAQB9SYO increment 0), so a caller that does not need it can leave it out. The default is every pass.
export const ALL_PASSES: ReadonlySet<Pass> = new Set(PASS_ORDER)

export function isPass(value: unknown): value is Pass {
  return PASS_ORDER.some((pass) => pass === value)
}

// WHY the options are one record keyed by pass and passed only to the runner that reads them: the report sanitizer must turn the email clone-address rule off (TRDD-L1I0FP5T), and the other passes have no setting; an absent entry means that pass default, so every existing caller is unchanged.
export type PassOptions = { email?: EmailOptions }

const RUNNERS: Record<Pass, (text: string, homes: readonly string[], options: PassOptions) => { text: string; hits: Hits }> = {
  secrets: (text) => redact(text),
  cards: (text) => redactCards(text),
  email: (text, _homes, options) => redactEmails(text, options.email),
  home: (text, homes) => redactHome(text, homes),
}

/** Runs the passes of `passes` over `text` in PASS_ORDER; the counts of all the passes are merged into one record. `options` carries the per-pass settings a caller may change; each pass reads only its own entry. */
export function redactAll(text: string, homes: readonly string[], passes: ReadonlySet<Pass> = ALL_PASSES, options: PassOptions = {}): { text: string; hits: Hits } {
  // WHY it throws and never skips: a pass name this function does not know would otherwise be dropped silently, and the caller would believe a pass ran that did not. The message is fixed text: it never echoes the value, which could hold input.
  for (const pass of passes as Iterable<unknown>) if (!isPass(pass)) throw new Error('redactAll: the pass set holds a value that is not a pass')
  // WHY an empty set throws: it would return the text unredacted, which no redaction caller means; a secret must never pass through because a caller sent no passes.
  if (passes.size === 0) throw new Error('redactAll: the pass set is empty')
  let out = text
  const hits: Hits = {}
  for (const pass of PASS_ORDER) {
    if (!passes.has(pass)) continue
    const result = RUNNERS[pass](out, homes, options)
    out = result.text
    addHits(hits, result.hits)
  }
  return { text: out, hits }
}
