// Real-bun tests of the pure JSONL planner of the secrets-shield redact (TRDD-BAQB9SYO step 3b-2b part A): no mock, no file, no vault. The vault of a run is stood in for by the uuid list that finalText and restoreCheck take.
// Every secret below is an obviously fake string built from fragments at run time (no whole secret literal sits in this file), and no home folder is named: the home list is empty.

import { describe, expect, test } from 'bun:test'
import { redactAll, type Pass } from '../../../hooks/secret-shield/pipeline.ts'
import { brokenLines, jsonlHits, newNonce, planJsonl, skipReasonOf, type LineHit } from '../jsonl.ts'
import { finalText, finalTextAligned, planRedaction, restoreCheck, SHIELD_MARKER, shieldMarker, sweepPlan, vaultEntries, type Plan } from '../redact.ts'

const HOMES: readonly string[] = []
const SECRETS: ReadonlySet<Pass> = new Set<Pass>(['secrets'])
const ALL_BUT_HOME: ReadonlySet<Pass> = new Set<Pass>(['secrets', 'cards', 'email'])

// Fake tokens in the shapes the core knows, assembled from fragments.
const ghToken = (seed: string): string => 'gh' + 'p_' + seed.repeat(12).slice(0, 36)
const awsKey = (): string => 'AK' + 'IA' + 'IOSFODNN7EXAMPLQ'
const pemLines = (): string[] => ['-----BEGIN ' + 'RSA PRIVATE KEY-----', 'MIIEowIBAAKCAQEA' + '0123456789abcdefghijklmnop', 'qrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123', '456789abcdefghijklmnopqrstuvwxyzABCDEF', '-----END ' + 'RSA PRIVATE KEY-----']

/** The text a plan writes with the given uuid per stretch (after the sweep, as the worker does), and whether the restore check passes against the original. */
function writeOut(plan: Plan, original: string, uuidOf: (index: number) => string): { final: string; restored: boolean; swept: Plan } {
  const swept = sweepPlan(plan)
  const { entries, slot } = vaultEntries(swept)
  const ids = entries.map((_, index) => uuidOf(index))
  const uuids = slot.map((index) => ids[index])
  const byUuid = new Map(entries.map((entry, index) => [ids[index], entry.value]))
  const final = finalText(swept, uuids)
  return { final, restored: restoreCheck(swept, final, uuids, (uuid) => byUuid.get(uuid) ?? null, original), swept }
}

/** Whether a line parses as JSON. */
function parsesAsJson(line: string): boolean {
  try {
    JSON.parse(line)
    return true
  } catch {
    return false
  }
}

/** The sum of the counts of the located hits, per kind. */
function sumByKind(lineHits: readonly LineHit[]): Record<string, number> {
  const sums: Record<string, number> = {}
  for (const [kind, , count] of lineHits) sums[kind] = (sums[kind] ?? 0) + count
  return sums
}

describe('JSONL planner', () => {
  test('skipReasonOf: only the redactJsonLine-threw cause makes a file json-broken', () => {
    expect(skipReasonOf({})).toBe('align-error')
    expect(skipReasonOf({ 'token-structure': 1 })).toBe('align-error')
    expect(skipReasonOf({ 'redactJsonLine-threw': 1 })).toBe('json-broken')
    expect(skipReasonOf({ 'redactJsonLine-threw': 1, 'marker-moved': 2 })).toBe('json-broken')
  })

  test('A2: a multi-line key between JSON lines is hidden as plain text hides it', () => {
    const pem = pemLines()
    const text = ['{"a":"one"}', ...pem, '{"b":"two"}'].join('\n') + '\n'
    const planned = planJsonl(text, HOMES, SECRETS, newNonce(text))
    expect(planned.plan).not.toBeNull()
    const written = writeOut(planned.plan as Plan, text, () => crypto.randomUUID())
    for (const bodyLine of pem.slice(1, 4)) expect(written.final).not.toContain(bodyLine)
    expect(written.restored).toBe(true)
    for (const line of written.final.split('\n')) if (line.startsWith('{')) expect(parsesAsJson(line)).toBe(true)
    const plainText = pem.join('\n')
    const plain = planRedaction(plainText, HOMES, SECRETS)
    expect(plain.plan).not.toBeNull()
    expect((plain.plan as Plan).stretches.length).toBeGreaterThan(0)
    expect(planned.plan?.stretches).toEqual((plain.plan as Plan).stretches)
    expect(planned.stats.not_json).toBe(pem.length)
  })

  test('A3: the per-line hits come from the one walk, in plan and in scan-only mode', () => {
    const lines = [JSON.stringify({ msg: 'use ' + ghToken('aB3dE5gH7jK9') }), JSON.stringify({ msg: 'line one\n' + ghToken('Zy8xW6vU4tS2') }), '', 'note: ' + awsKey(), JSON.stringify({ ok: true })]
    const text = lines.join('\n') + '\n'
    const planned = planJsonl(text, HOMES, SECRETS, newNonce(text))
    expect(planned.hits).toEqual({ 'github-token': 2, 'aws-access-key': 1 })
    expect(sumByKind(planned.lineHits)).toEqual(planned.hits)
    expect(planned.lineHits.map(([, line]) => line)).toEqual([1, 2, 4])
    const counted = jsonlHits(text, HOMES, SECRETS)
    expect(counted.hits).toEqual(planned.hits)
    expect(counted.lineHits).toEqual(planned.lineHits)
    expect(counted.notJson).toBe(planned.stats.not_json)
    expect(planned.stats.blank).toBe(1)
    expect(planned.stats.not_json).toBe(1)
  })

  test('A4: a shield marker (an all-digit uuid, a card-number kind) is never read by the other passes', () => {
    const uuids = ['12345678-1234-4234-8234-123456789012', '87654321-4321-4321-8321-210987654321']
    const line = JSON.stringify({ text: 'a ' + ghToken('aB3dE5gH7jK9') + ' b ' + ghToken('Zy8xW6vU4tS2') })
    const first = planJsonl(line, HOMES, ALL_BUT_HOME, newNonce(line))
    expect(first.plan).not.toBeNull()
    const written = writeOut(first.plan as Plan, line, (index) => uuids[index])
    expect(written.restored).toBe(true)
    for (const uuid of uuids) expect(written.final).toContain(shieldMarker('github-token', uuid))
    const again = planJsonl(written.final, HOMES, ALL_BUT_HOME, newNonce(written.final))
    expect(again.hits).toEqual({})
    expect(again.stats.causes).toEqual({})
    expect(again.plan).not.toBeNull()
    expect(again.plan?.parts.some((part) => part.t === 'new')).toBe(false)
    // A marker whose kind is a card number: the cards pass reads inside it when it runs on the whole text (the control), and must not when the markers are cut out (A4). This is the input that fails without A4.
    const cardMarker = shieldMarker('4111' + '1111' + '1111' + '1111', uuids[0])
    expect(redactAll(cardMarker, HOMES, new Set<Pass>(['cards'])).hits).toEqual({ 'payment-card': 1 })
    const marked = JSON.stringify({ text: 'a ' + cardMarker + ' b' })
    const guarded = planJsonl(marked, HOMES, ALL_BUT_HOME, newNonce(marked))
    expect(guarded.hits).toEqual({})
    expect(guarded.stats.causes).toEqual({})
    expect(guarded.plan?.parts.some((part) => part.t === 'new')).toBe(false)
    expect(jsonlHits(marked, HOMES, ALL_BUT_HOME).hits).toEqual({})
  })

  test('A5: the shield markers of a first round are opaque to a second round, in plan and in scan-only mode (round 2 reads them as secrets without the sentinel)', () => {
    const pw = 'Zq7Lm2' + 'Xp9Rt4' + 'Vb8Nc3Kd'
    const hex = 'a1b2c3d4' + 'e5f60718' + '293a4b5c' + '6d7e8f90'
    const hexBack = [...hex].reverse().join('')
    const shapes: Array<{ name: string; line: string; hits: Record<string, number> }> = [
      { name: 'connection string', line: JSON.stringify({ t: 'Server=db;User Id=u;Password=' + pw + ';Encrypt=true' }), hits: { 'connection-string-key': 1 } },
      { name: 'cookie header', line: JSON.stringify({ t: 'Cookie: _gitlab_session=' + hex + '; other=1' }), hits: { 'gitlab-session-cookie': 1 } },
      { name: 'cookie in a nested JSON string', line: JSON.stringify({ t: JSON.stringify({ _gitlab_session: hex, x: 1 }) }), hits: { 'gitlab-session-cookie': 1 } },
      { name: 'two cookies on one line', line: JSON.stringify({ t: '_gitlab_session=' + hex + ' and _gitlab_session=' + hexBack }), hits: { 'gitlab-session-cookie': 2 } },
    ]
    const shieldAll = new RegExp(SHIELD_MARKER, 'g')
    for (const shape of shapes) {
      const text = shape.line + '\n'
      const first = planJsonl(text, HOMES, SECRETS, newNonce(text))
      expect([shape.name, first.hits]).toEqual([shape.name, shape.hits])
      expect(first.plan).not.toBeNull()
      const written = writeOut(first.plan as Plan, text, () => crypto.randomUUID())
      expect(written.restored).toBe(true)
      const markers = (written.final.match(shieldAll) ?? []).length
      expect([shape.name, markers]).toEqual([shape.name, Object.values(shape.hits)[0]])
      // Round 2 on the final text of round 1: nothing left to find, nothing to write, and every shield marker is an old part (restoreCheck counts them there).
      const second = planJsonl(written.final, HOMES, SECRETS, newNonce(written.final))
      expect([shape.name, second.hits, second.stats.causes]).toEqual([shape.name, {}, {}])
      expect(second.plan).not.toBeNull()
      expect(second.plan?.stretches.length).toBe(0)
      expect(second.stats.stretches).toBe(0)
      expect(second.plan?.parts.filter((part) => part.t === 'old').length).toBe(markers)
      expect(second.plan?.parts.some((part) => part.t === 'lit' && new RegExp(SHIELD_MARKER).test(part.text))).toBe(false)
      expect(jsonlHits(written.final, HOMES, SECRETS).hits).toEqual(second.hits)
    }
    // Consequence (a) of the sentinel: a value glued right after a shield marker is not counted (the core treats a value holding a marker as a known miss).
    const glued = JSON.stringify({ t: 'Server=db;User Id=u;Password=' + shieldMarker('connection-string-key', '12345678-1234-4234-8234-123456789012') + pw + ';Encrypt=true' })
    expect(planJsonl(glued, HOMES, SECRETS, newNonce(glued)).hits).toEqual({})
    expect(jsonlHits(glued, HOMES, SECRETS).hits).toEqual({})
  })

  test('A3: lines that are not JSON with CRLF endings are located without the carriage return', () => {
    const lines = ['note: ' + awsKey(), 'second ' + ghToken('aB3dE5gH7jK9')]
    const text = lines.map((line) => line + '\r\n').join('')
    const expected: LineHit[] = []
    lines.forEach((line, index) => {
      for (const [kind, count] of Object.entries(redactAll(line, HOMES, SECRETS).hits)) expected.push([kind, index + 1, count])
    })
    expect(expected.length).toBe(2)
    expect(planJsonl(text, HOMES, SECRETS, newNonce(text)).lineHits).toEqual(expected)
    expect(jsonlHits(text, HOMES, SECRETS).lineHits).toEqual(expected)
  })

  test('finalTextAligned keeps the line count of the text, so brokenLines tells a stretch over several lines from a broken JSON line', () => {
    const text = ['{"ok":1}', 'plain ' + ghToken('a'), ...pemLines(), '{"ok":2}', ''].join('\n')
    const planned = planJsonl(text, HOMES, SECRETS, newNonce(text))
    const swept = sweepPlan(planned.plan!)
    const uuids = vaultEntries(swept).slot.map((_, index) => `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`)
    // The PEM block is one marker in the final text, so it has fewer lines; the aligned text has the text's own line count and no line broke.
    expect(finalText(swept, uuids).split('\n').length).toBeLessThan(text.split('\n').length)
    const aligned = finalTextAligned(swept, uuids)
    expect(aligned.split('\n').length).toBe(text.split('\n').length)
    expect(brokenLines(text, aligned)).toBe(0)
    // A sweep copy right after a backslash inside a JSON string is an invalid escape: one line that parsed before does not parse now.
    const rest = 'Zq7Lm2Xp9Rt4Vb8Nc3KdW5'
    const escaped = ['{"password":"n' + rest + '"}', '{"note":"\\n' + rest + '"}', ''].join('\n')
    const sweptEscaped = sweepPlan(planJsonl(escaped, HOMES, SECRETS, newNonce(escaped)).plan!)
    const ids = vaultEntries(sweptEscaped).slot.map((_, index) => `00000000-0000-4000-8000-${String(index).padStart(12, '0')}`)
    expect(brokenLines(escaped, finalTextAligned(sweptEscaped, ids))).toBe(1)
  })
})
