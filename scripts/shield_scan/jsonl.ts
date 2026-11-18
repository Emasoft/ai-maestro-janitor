// secrets-shield redact, increment 3 step 3b-2a (TRDD-BAQB9SYO; spec design/specs/TRDD-BAQB9SYO-increment-3-redact.md R2, R5b, R6 v6): the pure planner of a JSONL file. No fs, no env, no process, no console: it returns a Plan over the RAW file text, so sweepPlan, vaultEntries, finalText and restoreCheck of redact.ts work on it unchanged.
// Flow of one line that parses as JSON: the core markers already in it get a per-run nonce kind, redactJsonLine hides what it finds in each decoded string, the other marker passes (cards, email) run on each decoded string (never inside a marker), and in each string token that changed the decoded texts are aligned (alignStretches) to find what each marker replaced; each replaced stretch is mapped back to its ENCODED substring of the original token. A maximal run of consecutive lines that do not parse as JSON goes through planRedaction as one plain text.
// A value never leaves this module except inside the plan it returns: an error or a cause name never holds a value or a line of text. The plan is null when any line cannot be planned, and the stats count every cause over every line.

import { redactAll, type Pass } from '../../hooks/secret-shield/pipeline.ts'
import { addHits, redactJsonLine, stringSpans, type Hits } from '../../hooks/secret-shield/patterns.ts'
import { alignStretches, CORE_MARKER, cutMarkers, HOME_ONLY, planRedaction, SHIELD_MARKER, withoutHome, type Part, type Plan, type Stretch } from './redact.ts'

/** Why a line cannot be planned. One name per mechanism, so a dry run says what to design a fallback for. */
export const JSONL_CAUSES = ['plain-align-null', 'redactJsonLine-threw', 'token-structure', 'marker-moved', 'decoded-align-null-nested', 'decoded-align-null-flat', 'stretch-overlaps-marker', 'escaped-marker', 'split-surrogate'] as const
export type JsonlCause = (typeof JSONL_CAUSES)[number]

/**
 * The hit kind of a JSON line that redactJsonLine could not hide without breaking its JSON (it threw its fixed error); the line adds 1 of it to the hits, and the plan records the cause redactJsonLine-threw.
 * WHY a hit kind: redactJsonLine throws only after a rule changed the line, so the line holds a finding the shield could not hide without breaking the JSON; counting it keeps the file visible in both modes (a file whose only finding is on that line would otherwise report 0 hits and end as clean, and scan-only mode would crash on the throw).
 */
export const JSON_UNREDACTABLE = 'json-unredactable'

/** One located hit: kind, line (1-based), count. */
export type LineHit = [kind: string, line: number, count: number]

/** Why a file whose plan is null is skipped (spec R6 steps 2 and 3): a line that redactJsonLine could not hide without breaking it is json-broken, any other cause is align-error. */
export const skipReasonOf = (causes: Readonly<Record<string, number>>): 'json-broken' | 'align-error' => ((causes['redactJsonLine-threw'] ?? 0) > 0 ? 'json-broken' : 'align-error')

export interface JsonlStats {
  lines: number
  blank: number
  json: number
  not_json: number
  lines_with_stretches: number
  stretches: number
  /** Cause name to the number of lines that had it (a line with two causes counts once for each; a run of non-JSON lines that cannot be planned counts once). */
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

/** Whether a text parses as JSON. */
export const parses = (text: string): boolean => {
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

// WHY the parse is wrapped: the error text is fixed, an error must never carry a value (a token is a piece of a scanned file). The failure is unreachable today: every token comes from a line that parsed.
const decodeToken = (token: string): string => {
  if (!token.includes('\\')) return token.slice(1, -1)
  try {
    return JSON.parse(token)
  } catch {
    throw new Error('a JSON string token could not be decoded')
  }
}

const escapeRegExp = (text: string): string => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')

/** Every raw marker a line can hold: a shield marker or a core marker. */
const MARKER_ALL = new RegExp(`(?:${SHIELD_MARKER})|(?:${CORE_MARKER})`, 'g')
const SHIELD_WHOLE = new RegExp(`^(?:${SHIELD_MARKER})$`)

/**
 * The line with every raw core marker AND every raw shield marker replaced by the nonce marker, and the originals in order.
 * WHY shield markers too: redactJsonLine knows only the core markers (it skips `[JANITOR-REDACTED:kind]`), so on a line that already holds the shield markers of an earlier round its connection-string rule took the first word of a marker for a password and a gitlab-session-cookie hit fired, giving residual hits, cause marker-moved, a null plan and a file skipped as align-error. In the nonce form the core is inert (0 hits, a plan). Two consequences, both known: (a) a value glued to a marker (`Password=<marker>abc`) is not counted, because the core treats a value holding a marker as a known miss; (b) text shaped like a shield marker is never read by any pass, so a token put in the Type field of a fake marker is not found, the same evasion as on the plain path through cutMarkers.
 */
function sentinelMarkers(line: string, nonceMarker: string): { line: string; originals: string[] } {
  const originals: string[] = []
  const swapped = line.replace(MARKER_ALL, (marker) => {
    originals.push(marker)
    return nonceMarker
  })
  return { line: swapped, originals }
}

/** The marker passes that run on a decoded string after redactJsonLine: the given set without secrets (redactJsonLine is the secrets pass) and without home (counted, never rewritten); null when none is left (redactAll refuses an empty set). */
const otherPasses = (passes: ReadonlySet<Pass>): ReadonlySet<Pass> | null => {
  const rest = new Set([...withoutHome(passes)].filter((pass) => pass !== 'secrets'))
  return rest.size === 0 ? null : rest
}

/**
 * Step 2 of spec R6 for the string tokens of `doc`: each is decoded, the other marker passes run on it, and with the home pass named its home paths are counted (no rewrite in 3b-2a). Returns the decoded text of each token after the other passes.
 * WHY flat (one decoded string, nested JSON not walked): the passes read text and a marker has no quote or backslash, so a rewrite inside a nested document stays valid JSON, and the alignment of step 4 works on the same decoded string.
 * WHY the passes run on the segments between markers and not on the whole decoded string: a shield marker carries a uuid, and a pass must not read inside it; a rewrite there would move a marker (cause marker-moved) and a hit there would be a false residual. The shield markers and the core markers (the nonce form included) are kept as they are, as planRedaction and residualHits do on plain text (cutMarkers of redact.ts).
 */
function decodedAfterPasses(doc: string, spans: ReadonlyArray<[number, number]>, homes: readonly string[], others: ReadonlySet<Pass> | null, wantHome: boolean, hits: Hits): string[] {
  return spans.map(([start, end]) => {
    const decoded = decodeToken(doc.slice(start, end))
    if (others === null && !wantHome) return decoded
    return cutMarkers(decoded)
      .map((item) => {
        if ('old' in item) return item.old
        if ('lit' in item) return item.lit
        let seg = item.seg
        if (others !== null) {
          const result = redactAll(seg, homes, others)
          addHits(hits, result.hits)
          seg = result.text
        }
        if (wantHome) addHits(hits, redactAll(seg, homes, HOME_ONLY).hits)
        return seg
      })
      .join('')
  })
}

/** One step of the walk of a text: a line that parses as JSON (`json`, one line), or a maximal run of consecutive lines that do not parse as JSON, blank lines inside it included. `first` is the 0-based index of its first line and `newline` tells whether a newline follows its last line in the text. */
interface LineRun {
  json: boolean
  lines: string[]
  first: number
  newline: boolean
}

/**
 * The lines of a text (split at "\n"; the empty piece after a final newline is not a line) as runs, in order.
 * WHY a run of non-JSON lines is one step and not one line each (spec R6): a multi-line value (a PEM private key in a .jsonl that is not really JSONL) is hidden only when the passes read its lines together, as they do in plain text.
 */
function* lineRuns(text: string): Generator<LineRun> {
  const pieces = text.split('\n')
  const total = pieces[pieces.length - 1] === '' ? pieces.length - 1 : pieces.length
  let i = 0
  while (i < total) {
    if (parses(pieces[i])) {
      yield { json: true, lines: [pieces[i]], first: i, newline: i + 1 < pieces.length }
      i++
      continue
    }
    let end = i + 1
    while (end < total && !parses(pieces[end])) end++
    yield { json: false, lines: pieces.slice(i, end), first: i, newline: end < pieces.length }
    i = end
  }
}

const pushLineHits = (lineHits: LineHit[], hits: Hits, line: number): void => {
  for (const [kind, count] of Object.entries(hits)) lineHits.push([kind, line, count])
}

/** The per-line hits of a run of non-JSON lines: redactAll of each non-blank line alone, a final carriage return removed (as the plain locate of the worker does). */
function locateRun(run: LineRun, homes: readonly string[], passes: ReadonlySet<Pass>, lineHits: LineHit[]): void {
  run.lines.forEach((raw, k) => {
    if (raw.trim() === '') return
    pushLineHits(lineHits, redactAll(raw.endsWith('\r') ? raw.slice(0, -1) : raw, homes, passes).hits, run.first + k + 1)
  })
}

/** The hits of one line that parses as JSON: redactJsonLine (with the secrets pass) plus the other passes on each decoded string. A line redactJsonLine throws on adds JSON_UNREDACTABLE and nothing else, as in planJsonLine. */
function jsonLineHits(line: string, homes: readonly string[], passes: ReadonlySet<Pass>, others: ReadonlySet<Pass> | null, wantHome: boolean, nonceMarker: string): Hits {
  const hits: Hits = {}
  // WHY the line is sentinelled before the secrets pass: see sentinelMarkers (the same swap as planJsonLine, so the counter and the planner count alike; consequences (a) and (b) are named there).
  const sentinelled = sentinelMarkers(line, nonceMarker).line
  let doc = sentinelled
  if (passes.has('secrets')) {
    try {
      const result = redactJsonLine(sentinelled)
      doc = result.text
      addHits(hits, result.hits)
    } catch {
      // WHY the throw is counted and not rethrown: see JSON_UNREDACTABLE. The error is a fixed text; nothing of it is kept.
      return { [JSON_UNREDACTABLE]: 1 }
    }
  }
  decodedAfterPasses(doc, stringSpans(doc), homes, others, wantHome, hits)
  return hits
}

/**
 * The JSON-aware hit counter (spec R6: one counter feeds the whole-file hits, the per-line locate and the residual, in scan-only mode too): redactJsonLine plus the other passes on each decoded string for a line that parses, redactAll for a run of lines that do not parse. `lineHits` are the hits of each line: exactly what a JSON line added to `hits`, and redactAll of the line alone for a line inside a run of non-JSON lines. `notJson` counts the non-blank lines that do not parse.
 * WHY the per-line hits come from this walk and not from a separate locate walk: a walk costs about 350 ns of CPU per byte (measured on three transcripts of 48 to 199 MB, 94% of it inside redactJsonLine) and the per-file limit is 30 s + 5 s per MB, so a second walk over the JSON lines would double that cost. The lines of a run of non-JSON lines are the one place that is read twice (the run as one text, then each line alone by locateRun), and redactJsonLine runs only on JSON lines. A finding that spans lines (a PEM key) is in `hits` and in no single line of `lineHits`, as in the plain locate of the worker, so `lineHits` need not sum to `hits` for such a run.
 */
export function jsonlHits(text: string, homes: readonly string[], passes: ReadonlySet<Pass>): { hits: Hits; lineHits: LineHit[]; notJson: number } {
  const hits: Hits = {}
  const lineHits: LineHit[] = []
  let notJson = 0
  const others = otherPasses(passes)
  const nonceMarker = `[JANITOR-REDACTED:${newNonce(text)}]`
  const wantHome = passes.has('home')
  for (const run of lineRuns(text)) {
    if (run.json) {
      const one = jsonLineHits(run.lines[0], homes, passes, others, wantHome, nonceMarker)
      addHits(hits, one)
      pushLineHits(lineHits, one, run.first + 1)
      continue
    }
    for (const line of run.lines) if (line.trim() !== '') notJson++
    addHits(hits, redactAll(run.lines.join('\n'), homes, passes).hits)
    locateRun(run, homes, passes, lineHits)
  }
  return { hits, lineHits, notJson }
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
  // Step 1: the raw core markers AND the raw shield markers, kept in order, and the line with the nonce form in their place.
  // WHY the shield markers too: see sentinelMarkers (round 2 of a redact read the markers of round 1 as secrets). Consequences, both known: (a) a value glued to a marker (`Password=<marker>abc`) is not counted, the core treats a value holding a marker as a known miss; (b) text shaped like a shield marker is never read by any pass, so a token in the Type field of a fake marker is not found, as on the plain path through cutMarkers.
  const { line: sentinelled, originals } = sentinelMarkers(line, c.nonceMarker)
  // Step 2. WHY redactJsonLine only with the secrets pass named: it is the secrets pass; a job without it must not run it.
  let out = sentinelled
  if (c.passes.has('secrets')) {
    try {
      const result = redactJsonLine(sentinelled)
      out = result.text
      addHits(hits, result.hits)
    } catch {
      // The error is a fixed text; nothing of it is kept.
      // WHY the line adds a hit and not only the cause: redactJsonLine throws only after a rule changed the line, so the line holds a finding the shield could not hide without breaking the JSON. Without the hit a file whose only finding is on this line reports 0 hits and ends as clean (see JSON_UNREDACTABLE).
      addHits(hits, { [JSON_UNREDACTABLE]: 1 })
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
  // The nonce markers go back to the markers they stood for, in order: a core marker stays a lit part, a shield marker becomes an old part. WHY here and not in the cut: a nonce marker is a lit part of its own, so the swap cannot touch a stretch.
  // WHY a shield marker is an old part and not a lit one: restoreCheck counts the shield markers of the final text against the old and the new parts. The element is replaced, the part is not mutated (its t would change).
  let next = 0
  for (let i = 0; i < parts.length; i++) {
    const part = parts[i]
    if (part.t !== 'lit' || part.text !== c.nonceMarker) continue
    if (next >= originals.length) {
      causes.add('token-structure')
      return
    }
    const original = originals[next++]
    if (SHIELD_WHOLE.test(original)) parts[i] = { t: 'old', text: original }
    else part.text = original
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

/** The number of lines of a plan that hold a stretch (a stretch can span lines): a newline in a part or in a stretch value moves to the next line. */
function linesWithStretches(parts: readonly Part[], stretches: readonly Stretch[]): number {
  const seen = new Set<number>()
  let line = 0
  for (const part of parts) {
    const breaks = (part.t === 'new' ? stretches[part.stretch].value : part.text).split('\n').length - 1
    if (part.t === 'new') for (let k = 0; k <= breaks; k++) seen.add(line + k)
    line += breaks
  }
  return seen.size
}

/**
 * The plan of a whole JSONL file (spec R6): lines split at "\n" (each newline is a lit part), a line that parses planned as above, a maximal run of consecutive lines that do not parse (blank lines inside it included) planned as ONE plain text, a run of blank lines only kept as it is. `blank` and `not_json` count lines.
 * WHY a run and not line by line: a multi-line value, a PEM private key in a .jsonl that is not really JSONL, is hidden only when the passes read its lines together, as they do in plain text.
 * WHY the plan is null when any line failed, and planJsonl still walks every line: one line that cannot be explained would make the restore of the file unprovable, so no file is written (the worker skips it, skipReasonOf gives the reason), and the stats of the walk say which causes to design for.
 * `hits` is what the passes found in all lines, failed ones included. `lineHits` are the hits of each line from the same walk: for a JSON line exactly what it added to `hits`, for a line inside a run of non-JSON lines redactAll of that line alone with a final carriage return removed (as the plain locate of the worker does). WHY from the same walk: see jsonlHits.
 */
export function planJsonl(text: string, homes: readonly string[], passes: ReadonlySet<Pass>, nonce: string): { hits: Hits; lineHits: LineHit[]; plan: Plan | null; stats: JsonlStats } {
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
  const lineHits: LineHit[] = []
  const stats: JsonlStats = { lines: 0, blank: 0, json: 0, not_json: 0, lines_with_stretches: 0, stretches: 0, causes: {} }
  const parts: Part[] = []
  const stretches: Stretch[] = []
  let ok = true
  for (const run of lineRuns(text)) {
    stats.lines += run.lines.length
    const runParts: Part[] = []
    const runStretches: Stretch[] = []
    const causes = new Set<JsonlCause>()
    if (run.json) {
      stats.json++
      const one: Hits = {}
      planJsonLine(run.lines[0], c, one, runParts, runStretches, causes)
      addHits(hits, one)
      pushLineHits(lineHits, one, run.first + 1)
    } else {
      const runText = run.lines.join('\n')
      const nonBlank = run.lines.filter((line) => line.trim() !== '').length
      stats.not_json += nonBlank
      stats.blank += run.lines.length - nonBlank
      if (nonBlank === 0) runParts.push({ t: 'lit', text: runText })
      else {
        const result = planRedaction(runText, homes, passes)
        addHits(hits, result.hits)
        locateRun(run, homes, passes, lineHits)
        if (result.plan === null) causes.add('plain-align-null')
        else {
          for (const part of result.plan.parts) runParts.push(part)
          for (const stretch of result.plan.stretches) runStretches.push(stretch)
        }
      }
    }
    if (causes.size > 0) {
      ok = false
      for (const cause of causes) stats.causes[cause] = (stats.causes[cause] ?? 0) + 1
      continue
    }
    stats.lines_with_stretches += linesWithStretches(runParts, runStretches)
    stats.stretches += runStretches.length
    appendLine(parts, stretches, runParts, runStretches)
    if (run.newline) appendLine(parts, stretches, [{ t: 'lit', text: '\n' }], [])
  }
  return { hits, lineHits, plan: ok ? { parts, stretches } : null, stats }
}
