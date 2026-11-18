// Known-value redaction (TRDD-DSXC9MP9 increment 1): every copy of a value the vault keeps becomes the vault marker of that value, whether or not a pattern rule would find it.
// WHY it exists: under the vault design an agent runs commands with secrets it never reads (the shield resolves a uuid to its value inside the command). The value then shows up where no rule recognises it: a process list, a curl -v trace, a file the command wrote. Matching the exact values of the vault hides each such copy, so the agent reads the uuid, never the value.
// WHY Aho-Corasick and no RegExp: one pass over the text whatever the number of values, so the time is linear in the text plus the matches found. A RegExp alternation of many literals is tried literal by literal at each position, and loops in this kit stall on long input (PROJECT memory page secret-shield: rules must run in linear time).
// Pure: no `$`, no I/O, nothing printed. The index holds plaintext values in memory; whoever builds it keeps them out of every output, and every error thrown here is fixed text that never holds a value.
// Not wired: register.ts does not call it yet (a later increment of TRDD-DSXC9MP9 does).

import { SHIELD_MARKER, shieldMarker, UUID_V4 } from './marker'
import { addHits, countOf, mapStrings, MARK_BODY, type Hits } from './patterns'

/** One row of the vault as the index needs it: its uuid, the kind written in its marker, and the value. */
export type KnownSecret = { readonly uuid: string; readonly kind: string; readonly value: string }

// WHY a floor: a short value matches ordinary text (a word, a number) and would hide it wherever it stands. A value under the floor is left out of the index and counted in `skipped`; the pattern rules still look at it.
export const MIN_KNOWN_LENGTH = 8

/** A fixed-text error: its message never holds a value. */
export class KnownIndexError extends Error {
  override name = 'KnownIndexError'
}

const UUID_EXACT = new RegExp(`^${UUID_V4}$`)
const KIND_EXACT = /^[A-Za-z0-9_-]+$/
// WHY the markers already in a text are copied and never searched: a value could equal part of a uuid or of a kind, and a replacement inside a marker would break the marker the agent and restore read.
const MARKERS = new RegExp(`${SHIELD_MARKER}|${MARK_BODY}`, 'g')

/** The matcher over the values of the vault. Opaque: build it with buildKnownIndex. */
export type KnownIndex = {
  /** How many values the index matches. */
  readonly size: number
  /** The hidden spans of text[from, to): [start, end, ...pattern numbers] each, left to right, never overlapping. */
  readonly spans: (text: string, from: number, to: number) => number[][]
  /** The marker of pattern number `p`, and its kind. */
  readonly marker: (p: number) => string
  readonly kind: (p: number) => string
}

/**
 * Builds the matcher. Rows come in the order the vault lists them (first_seen): when two rows hold the same value, the first one names its marker.
 * Throws KnownIndexError on a row whose uuid or kind could not be written in a marker; a value under MIN_KNOWN_LENGTH is skipped and counted.
 */
export function buildKnownIndex(secrets: readonly KnownSecret[]): { index: KnownIndex; skipped: number } {
  const kept: KnownSecret[] = []
  const seen = new Set<string>()
  let skipped = 0
  for (const secret of secrets) {
    if (typeof secret.uuid !== 'string' || !UUID_EXACT.test(secret.uuid)) throw new KnownIndexError('a known secret has no valid vault uuid')
    if (typeof secret.kind !== 'string' || !KIND_EXACT.test(secret.kind)) throw new KnownIndexError('a known secret has no valid kind')
    if (typeof secret.value !== 'string') throw new KnownIndexError('a known secret has no text value')
    if (secret.value.length < MIN_KNOWN_LENGTH) {
      skipped++
      continue
    }
    if (seen.has(secret.value)) continue
    seen.add(secret.value)
    kept.push(secret)
  }

  // The trie over UTF-16 code units: node 0 is the root. term[n] is the pattern that ends at node n (or -1).
  const children: Map<number, number>[] = [new Map()]
  const term: number[] = [-1]
  const length = kept.map((secret) => secret.value.length)
  kept.forEach((secret, p) => {
    let node = 0
    for (let i = 0; i < secret.value.length; i++) {
      const code = secret.value.charCodeAt(i)
      const step = children[node]!.get(code)
      if (step !== undefined) {
        node = step
        continue
      }
      const made = children.length
      children.push(new Map())
      term.push(-1)
      children[node]!.set(code, made)
      node = made
    }
    term[node] = p
  })

  // fail[n]: the node of the longest proper suffix of n that is also in the trie. dict[n]: the nearest node along the fail links where a pattern ends (or -1).
  const fail: number[] = new Array<number>(children.length).fill(0)
  const dict: number[] = new Array<number>(children.length).fill(-1)
  const queue: number[] = []
  for (const child of children[0]!.values()) queue.push(child)
  for (let head = 0; head < queue.length; head++) {
    const node = queue[head]!
    for (const [code, child] of children[node]!) {
      let back = fail[node]!
      let step = children[back]!.get(code)
      // WHY node !== 0 is not tested here: queue holds no root, and a child of the root keeps fail 0 (set by the fill), so this loop only runs below depth 1.
      while (step === undefined && back !== 0) {
        back = fail[back]!
        step = children[back]!.get(code)
      }
      fail[child] = step ?? 0
      const via = fail[child]!
      dict[child] = term[via]! >= 0 ? via : dict[via]!
      queue.push(child)
    }
  }

  const markers = kept.map((secret) => shieldMarker(secret.kind, secret.uuid))

  const spans = (text: string, from: number, to: number): number[][] => {
    // The hidden spans as a stack of [start, end, ...pattern numbers], disjoint and left to right.
    // WHY only the longest match that ends at each position: every shorter match that ends there lies inside it, so the union of the hidden text is the same, and the work stays linear in the text however many values end at one place (a run of one character against values made of it would otherwise yield a match per value per position).
    const out: number[][] = []
    let node = 0
    for (let i = from; i < to; i++) {
      const code = text.charCodeAt(i)
      let step = children[node]!.get(code)
      while (step === undefined && node !== 0) {
        node = fail[node]!
        step = children[node]!.get(code)
      }
      node = step ?? 0
      const hit = term[node]! >= 0 ? node : dict[node]!
      if (hit === -1) continue
      const p = term[hit]!
      let start = i + 1 - length[p]!
      let ps = [p]
      // WHY overlapping spans merge: hiding the first of two overlapping values alone would leave the tail of the second visible. A span the new match covers whole is dropped (the longer value hides it); a span it only overlaps keeps its markers, and the new value is added after them unless it is the same value again (a value that overlaps its own copy).
      for (let top = out.at(-1); top !== undefined && top[1]! > start; top = out.at(-1)) {
        out.pop()
        if (top[0]! < start) {
          start = top[0]!
          const held = top.slice(2)
          ps = held.at(-1) === p ? held : [...held, p]
        }
      }
      out.push([start, i + 1, ...ps])
    }
    return out
  }

  return {
    index: { size: kept.length, spans, marker: (p) => markers[p]!, kind: (p) => kept[p]!.kind },
    skipped,
  }
}

/** `text` with every copy of a known value replaced by its marker, and how many of each kind. Markers already in the text are kept as they are. */
export function redactKnown(text: string, index: KnownIndex): { text: string; hits: Hits } {
  const hits: Hits = {}
  if (index.size === 0 || text.length < MIN_KNOWN_LENGTH) return { text, hits }
  const pieces: string[] = []
  let at = 0
  // Hides the spans of text[from, to) and moves `at` past the last one; the text after it is left for the caller to copy.
  const stretch = (from: number, to: number): void => {
    for (const [start, end, ...ps] of index.spans(text, from, to) as [number, number, ...number[]][]) {
      pieces.push(text.slice(at, start))
      for (const p of ps) {
        pieces.push(index.marker(p))
        const kind = index.kind(p)
        hits[kind] = (hits[kind] ?? 0) + 1
      }
      at = end
    }
  }
  for (const found of text.matchAll(MARKERS)) {
    const start = found.index!
    stretch(at, start)
    // The text up to the marker and the marker itself, copied as they are.
    pieces.push(text.slice(at, start + found[0].length))
    at = start + found[0].length
  }
  stretch(at, text.length)
  if (countOf(hits) === 0) return { text, hits }
  pieces.push(text.slice(at))
  return { text: pieces.join(''), hits }
}

/** Every string of a plain JSON value (a tool result) through redactKnown, keeping its shape; the value itself comes back when nothing was hidden. */
export function redactKnownDeep(value: unknown, index: KnownIndex): { value: unknown; hits: Hits } {
  const hits: Hits = {}
  if (index.size === 0) return { value, hits }
  const out = mapStrings(value, (text) => {
    const done = redactKnown(text, index)
    addHits(hits, done.hits)
    return done.text
  })
  return countOf(hits) === 0 ? { value, hits } : { value: out, hits }
}
