// secrets-shield redact, increment 3 step 3b-2a (TRDD-BAQB9SYO; spec design/specs/TRDD-BAQB9SYO-increment-3-redact.md R2, R5b, R6 v6): the pure planner of a JSONL file. No fs, no env, no process, no console: it returns a Plan over the RAW file text, so sweepPlan, vaultEntries, finalText and restoreCheck of redact.ts work on it unchanged.
// Flow of one line that parses as JSON: the core markers already in it get a per-run nonce kind, redactJsonLine hides what it finds in each decoded string, the other marker passes (cards, email) run on each decoded string, and in each string token that changed the decoded texts are aligned (alignStretches) to find what each marker replaced; each replaced stretch is mapped back to its ENCODED substring of the original token. A line that is not JSON goes through planRedaction as plain text.
// A value never leaves this module except inside the plan it returns: an error or a cause name never holds a value or a line of text. The plan is null when any line cannot be planned, and the stats count every cause over every line.

import { redactAll, type Pass } from '../../hooks/secret-shield/pipeline.ts'
import { addHits, redactJsonLine, stringSpans, type Hits } from '../../hooks/secret-shield/patterns.ts'
import { alignStretches, CORE_MARKER, cutMarkers, HOME_ONLY, planRedaction, SHIELD_MARKER, withoutHome, type Part, type Plan, type Stretch } from './redact.ts'

/** Why a line cannot be planned. One name per mechanism, so a dry run says what to design a fallback for. */
export const JSONL_CAUSES = ['plain-align-null', 'redactJsonLine-threw', 'token-structure', 'marker-moved', 'decoded-align-null-nested', 'decoded-align-null-flat', 'stretch-overlaps-marker', 'escaped-marker', 'split-surrogate'] as const
export type JsonlCause = (typeof JSONL_CAUSES)[number]

export interface JsonlStats {
  lines: number
  blank: number
  json: number
  not_json: number
  lines_with_stretches: number
  stretches: number
  /** Cause name to the number of lines that had it (a line with two causes counts once for each). */
  causes: Record<string, number>
}

/** A .jsonl or .ndjson file, any case. */
export const isJsonlPath = (p: string): boolean => /\.(jsonl|ndjson)$/i.test(p)

/**
 * The per-run kind of the nonce marker: `ss` plus 6 random lower-case base36 characters, regenerated while the text already holds a marker with it.
 * WHY a nonce: the core markers already in a line must survive redactJsonLine as markers the alignment can tell from the ones it inserts; a core marker with a kind that no file can hold is such a marker (spec R6 step 1).
 */
export function newNonce(text: string): string {
  for (;;) {
    const nonce = 'ss' + [...crypto.getRandomValues(new Uint8Array(6))].map((b) => (b % 36).toString(36)).join('')
    if (!text.includes(`[JANITOR-REDACTED:${nonce}]`)) return nonce
  }
}

const parses = (text: string): boolean => {
  try {
    JSON.parse(text)
    return true
  } catch {
    return false
  }
}

/** Whether a decoded string is itself a JSON object or array (a tool input or output carried as a string); only used to name the cause of a failed alignment. */
const isJsonContainer = (text: string): boolean => {
  const first = text.trimStart().charAt(0)
  return (first === '{' || first === '[') && parses(text)
}

const decodeToken = (token: string): string => (token.includes('\\') ? JSON.parse(token) : token.slice(1, -1))

const escapeRegExp = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** The marker passes that run on a decoded string after redactJsonLine: the given set without secrets (redactJsonLine is the secrets pass) and without home (counted, never rewritten); null when none is left (redactAll refuses an empty set). */
const otherPasses = (passes: ReadonlySet<Pass>): ReadonlySet<Pass> | null => {
  const rest = new Set([...withoutHome(passes)].filter((pass) => pass !== 'secrets'))
  return rest.size === 0 ? null : rest
}

/**
 * Step 2 of spec R6 for the string tokens of `doc`: each is decoded, the other marker passes run on it, and with the home pass named its home paths are counted (no rewrite in 3b-2a). Returns the decoded text of each token after the other passes.
 * WHY flat (one decoded string, nested JSON not walked): the passes read text and a marker has no quote or backslash, so a rewrite inside a nested document stays valid JSON, and the alignment of step 4 works on the same decoded string.
 */
function decodedAfterPasses(doc: string, spans: ReadonlyArray<[number, number]>, homes: readonly string[], others: ReadonlySet<Pass> | null, wantHome: boolean, hits: Hits): string[] {
  return spans.map(([start, end]) => {
    let decoded = decodeToken(doc.slice(start, end))
    if (others !== null) {
      const result = redactAll(decoded, homes, others)
      addHits(hits, result.hits)
      decoded = result.text
    }
    if (wantHome) addHits(hits, redactAll(decoded, homes, HOME_ONLY).hits)
    return decoded
  })
}

/**
 * The JSON-aware hit counter (spec R6: one counter feeds the whole-file hits, the per-line locate and the residual, in scan-only mode too): redactJsonLine plus the other passes on each decoded string for a line that parses, redactAll for a line that does not.
 * redactJsonLine throws its fixed error when it breaks a line; that error is not caught here.
 */
export function jsonlHits(text: string, homes: readonly string[], passes: ReadonlySet<Pass>): Hits {
  const hits: Hits = {}
  const others = otherPasses(passes)
  const wantHome = passes.has('home')
  for (const line of text.split('\n')) {
    if (line.trim() === '') continue
    if (!parses(line)) {
      addHits(hits, redactAll(line, homes, passes).hits)
      continue
    }
    let doc = line
    if (passes.has('secrets')) {
      const result = redactJsonLine(line)
      addHits(hits, result.hits)
      doc = result.text
    }
    decodedAfterPasses(doc, stringSpans(doc), homes, others, wantHome, hits)
  }
  return hits
}

/** Lines that parsed as JSON in the original and do not parse in the final text; -1 when the two have a different number of lines. */
export function brokenLines(original: string, final: string): number {
  const before = original.split('\n')
  const after = final.split('\n')
  if (before.length !== after.length) return -1
  let broken = 0
  // An unchanged line parses as it did, so only a changed line is parsed again.
  for (let i = 0; i < before.length; i++) if (before[i] !== after[i] && parses(before[i]) && !parses(after[i])) broken++
  return broken
}

interface Context {
  homes: readonly string[]
  passes: ReadonlySet<Pass>
  others: ReadonlySet<Pass> | null
  wantHome: boolean
  nonceMarker: string
  coreAll: RegExp
  /** Shield marker or nonce marker, global: the markers the alignment cuts a decoded text at. */
  cutAt: RegExp
  /** The same, without the g flag, for a test. */
  hasCut: RegExp
}

/** The text with its parts cut at the markers it holds (R3): a shield marker is an old part, a core marker (the nonce form included) is a lit part of its own, the rest is lit. */
const pushCut = (parts: Part[], text: string): void => {
  for (const item of cutMarkers(text)) {
    if ('old' in item) parts.push({ t: 'old', text: item.old })
    else if ('lit' in item) parts.push({ t: 'lit', text: item.lit })
    else parts.push({ t: 'lit', text: item.seg })
  }
}

/** Splits a decoded text at the shield markers and the nonce markers: the segments between them (with their offset in the text) and the markers (with theirs). There is one more segment than markers. */
function cutDecoded(text: string, cutAt: RegExp): { segs: Array<{ start: number; text: string }>; marks: Array<{ start: number; text: string }> } {
  const segs: Array<{ start: number; text: string }> = []
  const marks: Array<{ start: number; text: string }> = []
  let at = 0
  for (const m of text.matchAll(cutAt)) {
    segs.push({ start: at, text: text.slice(at, m.index) })
    marks.push({ start: m.index, text: m[0] })
    at = m.index + m[0].length
  }
  segs.push({ start: at, text: text.slice(at) })
  return { segs, marks }
}

/** For each UTF-16 unit of the decoded text, the offset where it starts in the encoded content (the token without its quotes), plus the content length at the end. One escape sequence (`\n`, `\/`, backslash-u with 4 digits) is one decoded unit, a raw character is one. Null when the walk does not give the decoded length. */
function encodedOffsets(content: string, decodedLength: number): Uint32Array | null {
  const at = new Uint32Array(decodedLength + 1)
  let unit = 0
  let i = 0
  while (i < content.length) {
    if (unit >= decodedLength) return null
    at[unit++] = i
    i += content.charCodeAt(i) === 92 ? (content.charCodeAt(i + 1) === 117 ? 6 : 2) : 1
  }
  at[unit] = content.length
  return unit === decodedLength && i === content.length ? at : null
}

/** Whether decoded offset `b` lies between the two raw UTF-16 units of one character (a cut there would leave two lone surrogates in the vault and in the file). A pair written as two escapes can be cut: each half is a whole escape. */
const splitsRawPair = (content: string, at: Uint32Array, b: number): boolean => {
  if (b <= 0 || b >= at.length - 1 || at[b] - at[b - 1] !== 1) return false
  const high = content.charCodeAt(at[b - 1])
  const low = content.charCodeAt(at[b])
  return high >= 0xd800 && high <= 0xdbff && low >= 0xdc00 && low <= 0xdfff
}

/**
 * Plans one string token that changed (spec R6 step 4): the parts of the token are pushed onto `parts` and `stretches` (indexes local to the line), or the cause is returned.
 * WHY the alignment runs on the decoded texts: the rules saw decoded text, so the markers stand where the decoded text was replaced, and a copy written with escapes still lines up; aligning the raw token against the JSON.stringify of the output could not, because JSON.stringify rewrites every escape of the token.
 * WHY a stretch is the ENCODED substring of the original token: the vault value with encoding raw is then the exact original bytes, so restore.ts writes them back unchanged and the restore check of redact.ts holds without a json-string encoding. Cutting only at the boundaries of escape sequences keeps every kept part a whole escape, so the token stays a JSON string.
 */
function planChangedToken(token: string, dOrig: string, dOut: string, c: Context, parts: Part[], stretches: Stretch[]): JsonlCause | null {
  const content = token.slice(1, -1)
  const at = encodedOffsets(content, dOrig.length)
  if (at === null) return 'token-structure'
  // WHY any core marker other than the nonce form is an escaped one: every raw core marker of the line was replaced by the nonce form before redactJsonLine ran, so a core marker in the decoded text was written with escapes and has no raw text to keep.
  for (const m of dOrig.matchAll(c.coreAll)) if (m[0] !== c.nonceMarker) return 'escaped-marker'
  const orig = cutDecoded(dOrig, c.cutAt)
  const out = cutDecoded(dOut, c.cutAt)
  if (orig.marks.length !== out.marks.length || orig.marks.some((m, k) => m.text !== out.marks[k].text)) return 'marker-moved'
  // A marker found in the decoded text must be the same bytes in the encoded token (not written with escapes), or it cannot be kept as a marker.
  for (const m of orig.marks) if (content.slice(at[m.start], at[m.start + m.text.length]) !== m.text) return 'escaped-marker'
  parts.push({ t: 'lit', text: '"' })
  for (let k = 0; k < orig.segs.length; k++) {
    const seg = orig.segs[k]
    const pieces = alignStretches(seg.text, out.segs[k].text)
    if (pieces === null) return isJsonContainer(dOrig) ? 'decoded-align-null-nested' : 'decoded-align-null-flat'
    let pos = seg.start
    for (const piece of pieces) {
      const length = 'lit' in piece ? piece.lit.length : piece.value.length
      const text = content.slice(at[pos], at[pos + length])
      if ('lit' in piece) {
        if (length > 0) parts.push({ t: 'lit', text })
      } else {
        if (c.hasCut.test(piece.value)) return 'stretch-overlaps-marker'
        if (splitsRawPair(content, at, pos) || splitsRawPair(content, at, pos + length)) return 'split-surrogate'
        parts.push({ t: 'new', stretch: stretches.length })
        stretches.push({ value: text, kind: piece.kind })
      }
      pos += length
    }
    if (pos !== seg.start + seg.text.length) return 'token-structure'
    if (k < orig.marks.length) {
      const mark = orig.marks[k].text
      parts.push(mark === c.nonceMarker ? { t: 'lit', text: mark } : { t: 'old', text: mark })
    }
  }
  parts.push({ t: 'lit', text: '"' })
  return null
}

/** One line that parses as JSON (spec R6 steps 1 to 4): its parts and stretches (indexes local to the line) are pushed, a cause is added to `causes`. */
function planJsonLine(line: string, c: Context, hits: Hits, parts: Part[], stretches: Stretch[], causes: Set<JsonlCause>): void {
  // Step 1: the raw core markers, kept in order, and the line with the nonce form in their place.
  const originals = line.match(c.coreAll) ?? []
  const sentinelled = line.replace(c.coreAll, () => c.nonceMarker)
  // Step 2. WHY redactJsonLine only with the secrets pass named: it is the secrets pass; a job without it must not run it.
  let out = sentinelled
  if (c.passes.has('secrets')) {
    try {
      const result = redactJsonLine(sentinelled)
      out = result.text
      addHits(hits, result.hits)
    } catch {
      // The error is a fixed text; nothing of it is kept.
      causes.add('redactJsonLine-threw')
      return
    }
  }
  const origSpans = stringSpans(sentinelled)
  const outSpans = stringSpans(out)
  const dOuts = decodedAfterPasses(out, outSpans, c.homes, c.others, c.wantHome, hits)
  // Step 3: the same tokens and identical bytes between them. WHY: the plan is over the raw line, so the structure outside the strings must be the original's own text.
  let same = origSpans.length === outSpans.length
  if (same) {
    let a = 0
    let b = 0
    for (let k = 0; same && k <= origSpans.length; k++) {
      const endA = k < origSpans.length ? origSpans[k][0] : sentinelled.length
      const endB = k < origSpans.length ? outSpans[k][0] : out.length
      same = sentinelled.slice(a, endA) === out.slice(b, endB)
      if (k < origSpans.length) {
        a = origSpans[k][1]
        b = outSpans[k][1]
      }
    }
  }
  if (!same) {
    causes.add('token-structure')
    return
  }
  // Step 4.
  let at = 0
  for (let k = 0; k < origSpans.length; k++) {
    const [start, end] = origSpans[k]
    if (start > at) parts.push({ t: 'lit', text: sentinelled.slice(at, start) })
    const token = sentinelled.slice(start, end)
    const dOrig = decodeToken(token)
    if (dOrig === dOuts[k]) pushCut(parts, token)
    else {
      const cause = planChangedToken(token, dOrig, dOuts[k], c, parts, stretches)
      if (cause !== null) causes.add(cause)
    }
    at = end
  }
  if (at < sentinelled.length) parts.push({ t: 'lit', text: sentinelled.slice(at) })
  if (causes.size > 0) return
  // The nonce markers go back to the core markers they stood for, in order. WHY here and not in the cut: a nonce marker is a lit part of its own, so the swap cannot touch a stretch or a shield marker.
  let next = 0
  for (const part of parts) {
    if (part.t !== 'lit' || part.text !== c.nonceMarker) continue
    if (next >= originals.length) {
      causes.add('token-structure')
      return
    }
    part.text = originals[next++]
  }
  if (next !== originals.length) causes.add('token-structure')
}

/** Appends a line's parts to the plan, merging touching lit parts and renumbering the stretches. */
function appendLine(parts: Part[], stretches: Stretch[], lineParts: readonly Part[], lineStretches: readonly Stretch[]): void {
  const base = stretches.length
  for (const part of lineParts) {
    const last = parts[parts.length - 1]
    if (part.t === 'lit' && last !== undefined && last.t === 'lit') last.text += part.text
    else parts.push(part.t === 'new' ? { t: 'new', stretch: part.stretch + base } : { ...part })
  }
  for (const stretch of lineStretches) stretches.push(stretch)
}

/**
 * The plan of a whole JSONL file (spec R6): lines split at "\n" (each newline is a lit part), a blank line kept as it is and counted, a line that is not JSON planned as plain text, a line that parses planned as above.
 * WHY the plan is null when any line failed, and planJsonl still walks every line: one line that cannot be explained would make the restore of the file unprovable, so no file is written (the worker skips it as align-error), and the stats of the walk say which causes to design for.
 * `hits` is what the passes found in all lines, failed ones included.
 */
export function planJsonl(text: string, homes: readonly string[], passes: ReadonlySet<Pass>, nonce: string): { hits: Hits; plan: Plan | null; stats: JsonlStats } {
  const nonceMarker = `[JANITOR-REDACTED:${nonce}]`
  const c: Context = {
    homes,
    passes,
    others: otherPasses(passes),
    wantHome: passes.has('home'),
    nonceMarker,
    coreAll: new RegExp(CORE_MARKER, 'g'),
    cutAt: new RegExp(`(?:${SHIELD_MARKER})|${escapeRegExp(nonceMarker)}`, 'g'),
    hasCut: new RegExp(`(?:${SHIELD_MARKER})|${escapeRegExp(nonceMarker)}`),
  }
  const hits: Hits = {}
  const stats: JsonlStats = { lines: 0, blank: 0, json: 0, not_json: 0, lines_with_stretches: 0, stretches: 0, causes: {} }
  const parts: Part[] = []
  const stretches: Stretch[] = []
  let ok = true
  const pieces = text.split('\n')
  for (let i = 0; i < pieces.length; i++) {
    const line = pieces[i]
    // The empty piece after a final newline is not a line.
    if (i === pieces.length - 1 && line === '') break
    stats.lines++
    const lineParts: Part[] = []
    const lineStretches: Stretch[] = []
    const causes = new Set<JsonlCause>()
    if (line.trim() === '') {
      stats.blank++
      lineParts.push({ t: 'lit', text: line })
    } else if (parses(line)) {
      stats.json++
      planJsonLine(line, c, hits, lineParts, lineStretches, causes)
    } else {
      stats.not_json++
      const result = planRedaction(line, homes, passes)
      addHits(hits, result.hits)
      if (result.plan === null) causes.add('plain-align-null')
      else {
        for (const part of result.plan.parts) lineParts.push(part)
        for (const stretch of result.plan.stretches) lineStretches.push(stretch)
      }
    }
    if (causes.size > 0) {
      ok = false
      for (const cause of causes) stats.causes[cause] = (stats.causes[cause] ?? 0) + 1
      continue
    }
    if (lineStretches.length > 0) stats.lines_with_stretches++
    stats.stretches += lineStretches.length
    appendLine(parts, stretches, lineParts, lineStretches)
    if (i < pieces.length - 1) appendLine(parts, stretches, [{ t: 'lit', text: '\n' }], [])
  }
  return { hits, plan: ok ? { parts, stretches } : null, stats }
}
