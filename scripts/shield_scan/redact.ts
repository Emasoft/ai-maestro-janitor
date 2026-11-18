// secrets-shield redact, increment 3 steps 3a-2 and 3a-3 (TRDD-BAQB9SYO; spec design/specs/TRDD-BAQB9SYO-increment-3-redact.md R2, R3, R5, R5b): the pure part of redacting a text file. No fs, no env, no process: the worker (worker.ts) does the vault and the file writes around it.
// Flow of one file: planRedaction() cuts out the markers already in the text, runs the core passes on each stretch between them, and aligns each output with its input to recover the exact text every core marker replaced. sweepPlan() then replaces the copies of those values that no pass matched (R5). The worker vaults the stretches, then finalText() writes the new text with [REDACTED-BY-SECRET-SHIELD. Type: <kind>. ID: <uuid>] markers, restoreCheck() proves that the vault rows put the original back before anything is written, and residualHits() runs the passes again over what lies between the markers of the final text.
// A value never leaves this module except inside the plan it returns; nothing here prints or throws one. A text the alignment cannot explain gives plan null (the worker skips the file as align-error); it never throws.

import { redactAll, type Pass } from '../../hooks/secret-shield/pipeline.ts'
import { addHits, propagates, type Hits } from '../../hooks/secret-shield/patterns.ts'
import type { VaultEntry } from './vault.ts'

// The grammar of the core marker is not exported by the core (increment 3 adds the propagates and stringSpans exports, redactJsonLine and mapJsonLineStrings to the core; spec R5 lists them), so it is rebuilt here from `mark(kind)` = [JANITOR-REDACTED:<kind>]; the unit test pins the two against each other.
export const CORE_MARKER = String.raw`\[JANITOR-REDACTED:([A-Za-z0-9_-]+)\]`
const UUID_V4 = String.raw`[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}`
// The marker this module writes: [REDACTED-BY-SECRET-SHIELD. Type: <kind>. ID: <uuid>].
export const SHIELD_MARKER = String.raw`\[REDACTED-BY-SECRET-SHIELD\. Type: ([A-Za-z0-9_-]+)\. ID: (${UUID_V4})\]`

// Why a file with findings was not written (spec R7), in the order the worker checks them. Each is a skip record of the findings file and the file's findings count as findings_not_redacted.
export const WRITE_SKIP_REASONS = ['git-internal', 'vault-folder', 'hardlinked', 'recent', 'not-utf8', 'git-operation', 'git-check-failed', 'align-error', 'json-broken', 'not-regular-at-write', 'outside-root', 'changed-during-redact', 'write-error'] as const
export type WriteSkipReason = (typeof WRITE_SKIP_REASONS)[number]

// What the driver sends with a job that redacts: the age limit for a recent file and the scan root the write target must stay inside (writeguard.ts).
export type RedactJob = { minAgeMs: number; root: string }

// The worker's last reply for a file with findings when the job asks for redact (the protocol is in worker.ts): written (with the kinds and counts of what the re-scan of the final text still found, never any text), left as it was and why, or a vault failure (fixed text) that ends the run.
export type RedactReply = { t: 'redact'; outcome: 'written'; values: number; residual: Hits; homeRewrites: number; rounds: number } | { t: 'redact'; outcome: 'skip'; reason: WriteSkipReason } | { t: 'redact'; outcome: 'vault-error'; message: string }

export const shieldMarker = (kind: string, uuid: string): string => `[REDACTED-BY-SECRET-SHIELD. Type: ${kind}. ID: ${uuid}]`

/** One thing the alignment found in a text: text kept as it is, or the exact stretch that one core marker (or a run of touching ones) replaced, with the kind of the first marker. */
export type Piece = { lit: string } | { value: string; kind: string }

const CORE_MARKER_ALL = new RegExp(CORE_MARKER, 'g')

/**
 * Recovers, from a text and the output of the core passes over it, the exact text each core marker replaced (spec R2).
 * Walk: the first literal piece must be a prefix of the original and the last a suffix; each middle piece is found by indexOf after the previous value, and the stretch between two pieces is what the marker replaced.
 * WHY a run of touching markers (an empty literal between them) is ONE stretch: the text alone cannot say where the first value ends and the second begins, and a guessed boundary would write an empty or wrong vault row. The run is vaulted as one value under the kind of its first marker and written as one marker; the restore is still byte for byte.
 * WHY an early indexOf hit (a short piece such as a newline found inside a multi-line key) is harmless: the new text is the literal pieces joined by markers, and it does not depend on where the boundaries fall, so it never shows more than the core output; only the split of the vault values moves, and the restore check still holds.
 * Returns null when the output cannot be explained as the original with stretches replaced by markers (never throws).
 */
export function alignStretches(original: string, redacted: string): Piece[] | null {
  const found = [...redacted.matchAll(CORE_MARKER_ALL)]
  if (found.length === 0) return redacted === original ? [{ lit: original }] : null
  const lits: string[] = []
  const kinds: string[] = []
  let at = 0
  for (const m of found) {
    lits.push(redacted.slice(at, m.index))
    kinds.push(m[1])
    at = m.index + m[0].length
  }
  lits.push(redacted.slice(at))
  if (!original.startsWith(lits[0])) return null
  const pieces: Piece[] = []
  if (lits[0] !== '') pieces.push({ lit: lits[0] })
  let pos = lits[0].length
  let first = 0
  for (let i = 0; i < kinds.length; i++) {
    const next = lits[i + 1]
    const last = i === kinds.length - 1
    // A touching marker follows: it joins this run.
    if (!last && next === '') continue
    let end: number
    if (last) {
      end = original.length - next.length
      if (end <= pos || !original.endsWith(next)) return null
    } else {
      // From pos + 1: a replaced stretch is never empty.
      end = original.indexOf(next, pos + 1)
      if (end < 0) return null
    }
    pieces.push({ value: original.slice(pos, end), kind: kinds[first] })
    if (next !== '') pieces.push({ lit: next })
    pos = end + next.length
    first = i + 1
  }
  return pieces
}

/** A part of the new text: text kept as it is, a shield marker that was already in the text, or the marker of one stretch of this run. */
export type Part = { t: 'lit'; text: string } | { t: 'old'; text: string } | { t: 'new'; stretch: number }

export interface Stretch {
  value: string
  kind: string
}

export interface Plan {
  parts: Part[]
  stretches: Stretch[]
}

const CUT = new RegExp(`(${SHIELD_MARKER})|(${CORE_MARKER})`, 'g')
export const HOME_ONLY: ReadonlySet<Pass> = new Set<Pass>(['home'])
// The kind redactHome (hooks/secret-shield/home.ts) gives its hits. It is a hit kind, not a pass name: the pass is 'home', its findings are 'home-path'. A test pins it against the core.
export const HOME_KIND = 'home-path'
/** The passes that write markers: the given set without the home pass. WHY: a home rewrite (/Users/x becomes ~) leaves no marker for the alignment to find, is never vaulted and is not restorable, so it must stay out of the plan, the sweep and the re-scan; the worker runs it last on the final text (spec R1). */
export const withoutHome = (passes: ReadonlySet<Pass>): ReadonlySet<Pass> => new Set([...passes].filter((pass) => pass !== 'home'))

/**
 * Cuts a text at the markers it already holds (spec R3): shield markers (kept, and counted as old by the restore check) and core markers (kept as text).
 * WHY core markers are cut too: they are literal text in the original, and a core marker in the output of the passes would then be ambiguous with one the passes inserted (an empty piece between a real marker and a literal one cannot be aligned). Cut out, every core marker of a stretch's output is a replacement.
 */
export function cutMarkers(text: string): Array<{ seg: string } | { old: string } | { lit: string }> {
  const out: Array<{ seg: string } | { old: string } | { lit: string }> = []
  let at = 0
  for (const m of text.matchAll(CUT)) {
    if (m.index > at) out.push({ seg: text.slice(at, m.index) })
    out.push(m[1] !== undefined ? { old: m[0] } : { lit: m[0] })
    at = m.index + m[0].length
  }
  if (at < text.length) out.push({ seg: text.slice(at) })
  return out
}

/** Runs the core marker passes (never the home pass, see withoutHome) on each stretch between the markers already in the text and aligns each output. `hits` counts what the passes found in the stretches (the same count the whole-file scan gives, with the markers left out), and with the home pass named also the home paths that the worker will rewrite last. `plan` is null when any stretch could not be aligned. */
export function planRedaction(text: string, homes: readonly string[], passes: ReadonlySet<Pass>): { hits: Hits; plan: Plan | null } {
  const marker = withoutHome(passes)
  const wantHome = passes.has('home')
  const hits: Hits = {}
  const parts: Part[] = []
  const stretches: Stretch[] = []
  let ok = true
  for (const item of cutMarkers(text)) {
    if ('old' in item) parts.push({ t: 'old', text: item.old })
    else if ('lit' in item) parts.push({ t: 'lit', text: item.lit })
    else {
      const result = redactAll(item.seg, homes, marker)
      // WHY the home pass runs on the marker output and is only counted here: a home rewrite is not a marker, so it cannot be aligned and is never vaulted; the worker applies it last, on the final text (spec R1).
      if (wantHome) addHits(hits, redactAll(result.text, homes, HOME_ONLY).hits)
      addHits(hits, result.hits)
      const pieces = alignStretches(item.seg, result.text)
      if (pieces === null) {
        ok = false
        continue
      }
      for (const piece of pieces) {
        if ('lit' in piece) parts.push({ t: 'lit', text: piece.lit })
        else {
          parts.push({ t: 'new', stretch: stretches.length })
          stretches.push(piece)
        }
      }
    }
  }
  return { hits, plan: ok ? { parts, stretches } : null }
}

/**
 * The sweep (spec R5): every distinct stretch value of the plan that the core's propagates() accepts is searched again in the literal parts that came from the text (never in an old shield marker), raw form only, and each copy found becomes a new stretch with the same value and kind, so vaultEntries gives it the same uuid as the original.
 * WHY: hideKnown spreads a found value only within one redactAll call, so a copy left in another stretch (one cut off by an old marker, or in a text that was redacted in several calls) matches no rule and would stay in the file. propagates() is the floor: a value under 10 characters, a number, an identifier, a slug, a path, a URL, an email or a host:port is never swept, because such a value is usually a name or a location and sweeping it would rewrite unrelated text.
 * WHY longer values first: a value that lies inside a longer one is then never split out of it, as in hideKnown. The new stretches are appended after the original ones, so the first stretch of a value (the one whose kind the vault row keeps) is still an original.
 * Pure: the plan given is not changed. The sweep runs before vaultEntries, finalText and restoreCheck, so the restore check covers it.
 */
export function sweepPlan(plan: Plan): Plan {
  const kinds = new Map<string, string>()
  for (const s of plan.stretches) if (!kinds.has(s.value) && propagates(s.value)) kinds.set(s.value, s.kind)
  if (kinds.size === 0) return plan
  const stretches = [...plan.stretches]
  let parts = plan.parts
  for (const [value, kind] of [...kinds].sort((a, b) => b[0].length - a[0].length)) {
    const next: Part[] = []
    for (const part of parts) {
      if (part.t !== 'lit') {
        next.push(part)
        continue
      }
      const bits = part.text.split(value)
      if (bits.length === 1) {
        next.push(part)
        continue
      }
      bits.forEach((bit, i) => {
        if (i > 0) {
          next.push({ t: 'new', stretch: stretches.length })
          stretches.push({ value, kind })
        }
        if (bit !== '') next.push({ t: 'lit', text: bit })
      })
    }
    parts = next
  }
  return { parts, stretches }
}

/** The vault entries of a plan: one per distinct value (a value twice in a file has one uuid), and for each stretch the index of its entry. The row keeps the kind of the first stretch with that value. */
export function vaultEntries(plan: Plan): { entries: VaultEntry[]; slot: number[] } {
  const entries: VaultEntry[] = []
  const slot: number[] = []
  const byValue = new Map<string, number>()
  for (const s of plan.stretches) {
    let index = byValue.get(s.value)
    if (index === undefined) {
      index = entries.length
      entries.push({ value: s.value, type: s.kind, encoding: 'raw' })
      byValue.set(s.value, index)
    }
    slot.push(index)
  }
  return { entries, slot }
}

/** The new text: the plan with each stretch written as its marker; uuids[i] is the uuid of stretch i. */
export function finalText(plan: Plan, uuids: readonly string[]): string {
  return plan.parts.map((part) => (part.t === 'new' ? shieldMarker(plan.stretches[part.stretch].kind, uuids[part.stretch]) : part.text)).join('')
}

/**
 * The new text with each marker followed by as many newlines as the value it replaced holds, so the text has the line count of the original. Never written: the JSONL check that a line which parsed before still parses (worker.ts) compares it line by line with the text of the round, and the final text has fewer lines whenever a stretch spans lines.
 */
export function finalTextAligned(plan: Plan, uuids: readonly string[]): string {
  return plan.parts.map((part) => (part.t === 'new' ? shieldMarker(plan.stretches[part.stretch].kind, uuids[part.stretch]) + '\n'.repeat(plan.stretches[part.stretch].value.split('\n').length - 1) : part.text)).join('')
}

/**
 * The restore check (spec R5b, raw encoding only in this step), made on the final text itself: every marker this run inserted is replaced by the value `valueOf` gives for its uuid (the vault row), every marker that was already in the original stays; the result must equal the original byte for byte.
 * WHY by position and not by uuid over the whole text: a file that already holds a marker for a value V, with a new copy of V elsewhere, gets the same uuid for both (one row per origin and value); a global substitution would also replace the old marker and fail a legitimate file.
 * The values come from the vault rows, not from the plan, so a pass also means the vault holds what the file loses. It does not prove a row holds exactly the secret: the stretches are the original's own text (spec R5b).
 */
export function restoreCheck(plan: Plan, final: string, uuids: readonly string[], valueOf: (uuid: string) => string | null, original: string): boolean {
  const expected = plan.parts.filter((part): part is Exclude<Part, { t: 'lit' }> => part.t !== 'lit')
  const found = [...final.matchAll(new RegExp(SHIELD_MARKER, 'g'))]
  if (found.length !== expected.length) return false
  let restored = ''
  let at = 0
  for (let i = 0; i < found.length; i++) {
    const m = found[i]
    const part = expected[i]
    restored += final.slice(at, m.index)
    at = m.index + m[0].length
    if (part.t === 'old') restored += m[0]
    else {
      const value = valueOf(m[2])
      if (m[2] !== uuids[part.stretch] || m[1] !== plan.stretches[part.stretch].kind || value === null) return false
      restored += value
    }
  }
  restored += final.slice(at)
  return restored === original
}

/**
 * The re-scan (spec R5): the core passes run again over every stretch of the final text between markers (old and new alike). A hit there is a residual finding: something the first run left in a file it did write. Returns kinds and counts only, never text.
 * WHY: the sweep finds copies of values the passes already found; this finds what neither the passes nor the sweep took out of the stretches, and it is the only check of the output itself (the restore check proves the file can be restored, not that it is clean).
 */
export function residualHits(final: string, homes: readonly string[], passes: ReadonlySet<Pass>): Hits {
  return markerFreeHits(final, homes, passes)
}

/**
 * The hits of the core passes over a text, never inside a shield marker: each stretch between the markers the text holds (cutMarkers) is redacted alone and the hits are summed. Returns kinds and counts only, never text.
 * WHY a marker is never read: it is the shield's own output, never a finding; reading inside it counted the first word of a marker as a password, so a re-scan of a redacted tree reported false findings.
 */
export function markerFreeHits(text: string, homes: readonly string[], passes: ReadonlySet<Pass>): Hits {
  const hits: Hits = {}
  for (const item of cutMarkers(text)) if ('seg' in item) addHits(hits, redactAll(item.seg, homes, passes).hits)
  return hits
}
