// secrets-shield restore, increment 3 step 3a-4b (TRDD-BAQB9SYO; spec design/specs/TRDD-BAQB9SYO-increment-3-redact.md R9): puts the vaulted value back in place of each [REDACTED-BY-SECRET-SHIELD. Type: <kind>. ID: <uuid>] marker of one file or of every file under a folder. For a person at a terminal only: the skill tells agents never to run it.
// CLI: bun restore.ts [--any-origin] [--max-large-mb N] <file|root>   (--max-large-mb: a text file over N MB is not read, default 1024)
// Output, stdout only, JSON lines, a value never, paths relative to the root: {"type":"left","path","uuid","reason":"unknown"|"moved"} · {"type":"note","path","uuid","reason":"type-mismatch"} · {"type":"skip","path","reason"} · last {"type":"summary", files_with_markers, files_restored, markers_restored, markers_moved_restored, markers_left, type_mismatch, skipped, complete}. markers_moved_restored is part of markers_restored.
// Exit: 3 incomplete (a read-error, unreadable-dir or too-large skip) · else 1 a marker was left or a file with markers was skipped · else 0 every marker found was restored (a binary file, or a changed file whose bytes held no marker, is skipped and keeps 0) · 2 usage, guard, missing or broken vault, or a fatal error.
// A value never reaches argv, stderr or an error message: every error is fixed text. restore writes no vault row (the setup of openVault may still switch the journal of the vault file to WAL).

import { closeSync, existsSync, fstatSync, openSync, readFileSync, readSync, realpathSync, statSync, type BigIntStats } from 'node:fs'
import { dirname, join, resolve, sep } from 'node:path'
import { BINARY_PROBE_BYTES, newStats, noteSkip, relOf, walkFiles, type FileItem, type SetOptions, type SetStats } from './fileset.ts'
import { SHIELD_MARKER } from './redact.ts'
import { VAULT_DIR_ENV, VAULT_FILE, VaultError, openVault, resolveVaultDir, type Vault, type VaultRow } from './vault.ts'
import { checkWriteTarget, gitOperation, writeAtomic } from './writeguard.ts'

const USAGE = 'usage: bun restore.ts [--any-origin] [--max-large-mb N] <file|root>'
const GUARD_TEXT = 'restore.ts is for a person at a terminal: stdin is not a terminal; agents never run it'
const NO_VAULT = 'no vault: nothing to restore from'
const MARKER_PREFIX = Buffer.from('[REDACTED-BY-SECRET-SHIELD. ')
// WHY fatal and ignoreBOM: a file that is not lossless UTF-8 is not rewritten (it would change bytes outside the markers); ignoreBOM keeps a byte order mark in the text, so the text is the file and nothing else.
const decoder = new TextDecoder('utf-8', { fatal: true, ignoreBOM: true })

/**
 * The guard (checked first, before any vault code): with the real vault (SECRETS_SHIELD_VAULT_DIR unset) stdin must be a terminal; a test vault skips the guard.
 * WHY: it stops an accidental or unattended run against the real vault. It is a speed bump and not a boundary: a pseudo-terminal, or a copy of the vault under the system temp folder with the variable set, gets past it. stdout is not checked, because a person must be able to capture the report.
 */
export function restoreAllowed(vaultDirSet: boolean, stdinIsTTY: boolean): boolean {
  return vaultDirSet || stdinIsTTY
}

function fatal(message: string): never {
  process.stderr.write(`shield-restore: ${message}\n`)
  return process.exit(2)
}

interface Options {
  anyOrigin: boolean
  maxLargeMb: number
  target: string
}

function parseArgs(argv: string[]): Options {
  let anyOrigin = false
  let maxLargeMb = 1024
  let target: string | null = null
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    if (arg === '--any-origin') anyOrigin = true
    else if (arg === '--max-large-mb') {
      const value = argv[++i]
      const parsed = value === undefined || value.trim() === '' ? Number.NaN : Number(value)
      if (!Number.isFinite(parsed) || parsed < 0) return fatal(USAGE)
      maxLargeMb = parsed
    } else if (arg.startsWith('-') || target !== null) return fatal(USAGE)
    else target = arg
  }
  if (target === null) return fatal(USAGE)
  return { anyOrigin, maxLargeMb, target }
}

interface Totals {
  filesWithMarkers: number
  filesRestored: number
  markersRestored: number
  markersMovedRestored: number
  markersLeft: number
  typeMismatch: number
  /** Files with markers that were skipped (not-utf8, not written, or changed-during-restore when the bytes read held a marker): they make the exit code 1. */
  skippedWithMarkers: number
  skipped: Record<string, number>
}

interface Context {
  vault: Vault
  root: string
  anyOrigin: boolean
  totals: Totals
}

function emit(record: Record<string, unknown>): void {
  process.stdout.write(JSON.stringify(record) + '\n')
}

// The binary test of the walker on the first BINARY_PROBE_BYTES of an open file; readSync with an explicit position leaves the fd position at byte 0.
function fdHeadHasNul(fd: number): boolean {
  const head = Buffer.alloc(BINARY_PROBE_BYTES)
  return head.subarray(0, readSync(fd, head, 0, BINARY_PROBE_BYTES, 0)).includes(0)
}

// The binary test for a file argument over the size limit (the walker is not used for a single file). null: the file could not be read.
function headHasNul(abs: string): boolean | null {
  let fd: number | null = null
  try {
    fd = openSync(abs, 'r')
    return fdHeadHasNul(fd)
  } catch {
    return null
  } finally {
    if (fd !== null) closeSync(fd)
  }
}

// The file set of a file argument: the same lanes as the walker (a text file over the limit is too-large, a binary one a binary skip), counted in the same stats.
function singleFile(real: string, root: string, maxBytes: number, stats: SetStats): FileItem | null {
  let size: number
  try {
    size = statSync(real).size
  } catch {
    noteSkip(stats, root, real, 'read-error')
    return null
  }
  const rel = relOf(root, real)
  if (size <= maxBytes) return { rel, abs: real, size, lane: 'normal' }
  const nul = headHasNul(real)
  if (nul === null) noteSkip(stats, root, real, 'read-error')
  else if (nul) noteSkip(stats, root, real, 'binary')
  else return { rel, abs: real, size, lane: 'too-large' }
  return null
}

// The stat is taken on the open file the bytes are read from, so writeAtomic can tell later that the file changed (same as the redact worker). state binary: the first BINARY_PROBE_BYTES hold a NUL and the rest is not read; state changed: the bytes read are not as many as the stat said.
// WHY the head is probed on this fd before the read: the walk limit is --max-large-mb (default 1024), so a file of that size would be read whole only to find a NUL in its first BINARY_PROBE_BYTES (a video or a model file in a huge tree). readSync with an explicit position does not move the fd position, so readFileSync(fd) below still reads from byte 0 (test_a_text_file_over_the_probe_size_with_markers_on_both_sides_of_it_is_restored_whole proves the whole file is read).
// WHY the length check: a short or long read means the file changed after the stat, or the fd position moved; writing that text back would truncate the file. UNTESTED: a real test needs a writer racing the read, and the not-read-whole effect of the head probe is likewise pinned only by reading the code.
function readWithStat(abs: string): { state: 'binary' } | { state: 'changed'; data: Buffer } | { state: 'ok'; data: Buffer; before: BigIntStats } | null {
  let fd: number | null = null
  try {
    fd = openSync(abs, 'r')
    const before = fstatSync(fd, { bigint: true })
    if (fdHeadHasNul(fd)) return { state: 'binary' }
    const data = readFileSync(fd)
    if (data.length !== Number(before.size)) return { state: 'changed', data }
    return { state: 'ok', data, before }
  } catch {
    return null
  } finally {
    if (fd !== null) closeSync(fd)
  }
}

// WHY json-string is written as JSON.stringify without its quotes: the row holds the decoded value of a JSON string, and the file holds its escaped form, so a quote, a backslash or a newline must come back escaped.
const textOf = (row: VaultRow): string => (row.encoding === 'json-string' ? JSON.stringify(row.value).slice(1, -1) : row.value)

function restoreFile(ctx: Context, abs: string, rel: string): void {
  const { vault, totals } = ctx
  const skip = (reason: string, withMarkers: boolean): void => {
    totals.skipped[reason] = (totals.skipped[reason] ?? 0) + 1
    if (withMarkers) totals.skippedWithMarkers++
    emit({ type: 'skip', path: rel, reason })
  }
  const read = readWithStat(abs)
  if (read === null) return skip('read-error', false)
  // WHY withMarkers is whether the bytes that were read hold a marker prefix: a changed file that held a marker must not let the run exit 0 as a complete restore (exit 1), while a changed file with no marker needs no exit change.
  if (read.state === 'changed') return skip('changed-during-restore', read.data.includes(MARKER_PREFIX))
  if (read.state === 'binary') {
    totals.skipped.binary = (totals.skipped.binary ?? 0) + 1
    return
  }
  const { data, before } = read
  if (!data.includes(MARKER_PREFIX)) return
  let text: string
  try {
    text = decoder.decode(data)
  } catch {
    return skip('not-utf8', true)
  }
  let out = ''
  let at = 0
  let found = 0
  let restored = 0
  let moved = 0
  const mismatches: string[] = []
  const left = (uuid: string, reason: 'unknown' | 'moved'): void => {
    totals.markersLeft++
    emit({ type: 'left', path: rel, uuid, reason })
  }
  for (const m of text.matchAll(new RegExp(SHIELD_MARKER, 'g'))) {
    found++
    const uuid = m[2]
    const row = vault.byUuid(uuid)
    if (row === null) {
      left(uuid, 'unknown')
      continue
    }
    // WHY the origin check: a marker copied into another file would otherwise write the secret there (spec R9); a project moved or copied after the redaction needs --any-origin.
    const sameOrigin = row.origin === abs
    if (!sameOrigin && !ctx.anyOrigin) {
      left(uuid, 'moved')
      continue
    }
    if (!sameOrigin) moved++
    // WHY restored by uuid alone (spec R9): a value found under two kinds shares one row, which keeps its first kind, so a marker whose Type differs from the row is still the right value; it is reported as a note.
    if (row.type !== m[1]) mismatches.push(uuid)
    out += text.slice(at, m.index) + textOf(row)
    at = m.index + m[0].length
    restored++
  }
  if (found > 0) totals.filesWithMarkers++
  if (restored === 0) return
  out += text.slice(at)
  // The write guards of the redact worker (spec R7), in the same order, except the recent-file guard (--min-age-minutes). WHY: the risk it covers is one-sided. After a redact, an editor that saves its old buffer writes the secret back; after a restore it writes only markers back, the vault still holds the values, and a re-run restores them. A skip here is a file with markers that stays as it was.
  if (before.nlink > 1n) return skip('hardlinked', true)
  const operation = gitOperation(abs)
  if (operation === 'operation') return skip('git-operation', true)
  if (operation === 'failed') return skip('git-check-failed', true)
  const target = checkWriteTarget(abs, ctx.root)
  if (target !== 'ok') return skip(target, true)
  const written = writeAtomic(abs, Buffer.from(out, 'utf8'), before)
  if (written !== 'written') return skip(written === 'changed-during-redact' ? 'changed-during-restore' : 'write-error', true)
  totals.filesRestored++
  totals.markersRestored += restored
  totals.markersMovedRestored += moved
  totals.typeMismatch += mismatches.length
  for (const uuid of mismatches) emit({ type: 'note', path: rel, uuid, reason: 'type-mismatch' })
}

async function run(opts: Options): Promise<void> {
  let vaultFolder: string
  try {
    vaultFolder = resolveVaultDir()
  } catch (error) {
    return fatal(error instanceof VaultError ? error.message : 'the vault folder could not be resolved')
  }
  // WHY the file is checked before openVault: openVault creates the folder and the file when they are missing, and restore must not create a vault.
  if (!existsSync(join(vaultFolder, VAULT_FILE))) return fatal(NO_VAULT)
  const vaultReal = realpathSync(vaultFolder)
  let vault: Vault
  try {
    vault = openVault()
  } catch (error) {
    return fatal(error instanceof VaultError ? error.message : 'the vault could not be opened')
  }
  let real: string
  let isDir: boolean
  try {
    real = realpathSync(resolve(opts.target))
    const st = statSync(real)
    if (!st.isDirectory() && !st.isFile()) return fatal('the path is not a file or a folder')
    isDir = st.isDirectory()
  } catch {
    return fatal('the path could not be read')
  }
  // A folder is its own root; for a file the root of the write guard is its parent folder, and only that file is restored.
  const root = isDir ? real : dirname(real)
  const maxBytes = Math.floor(opts.maxLargeMb * 1024 * 1024)
  // WHY both limits are the same: a text file over --max-large-mb is lane too-large (not read, the run is incomplete) and a binary one a binary skip; there is no large lane in a restore.
  const setOptions: SetOptions = { root, all: true, maxBytes, exclude: new Set<string>(), largeBytes: maxBytes }
  const stats = newStats()
  const source: AsyncIterable<FileItem> = isDir
    ? walkFiles(setOptions, stats)
    : (async function* () {
        const item = singleFile(real, root, maxBytes, stats)
        if (item !== null) yield item
      })()
  const totals: Totals = { filesWithMarkers: 0, filesRestored: 0, markersRestored: 0, markersMovedRestored: 0, markersLeft: 0, typeMismatch: 0, skippedWithMarkers: 0, skipped: {} }
  const ctx: Context = { vault, root, anyOrigin: opts.anyOrigin, totals }
  // WHY one file at a time: restore is rare and run by a person, and a whole-root restore reads the whole tree; the walker is lazy, so no file is held while the next is listed.
  for await (const item of source) {
    // Never read or written (spec R7): the content of a .git folder (and a .git pointer file) and the vault folder itself.
    if (item.abs.split(sep).includes('.git') || item.abs === vaultReal || item.abs.startsWith(vaultReal + sep)) continue
    if (item.lane === 'too-large') {
      totals.skipped['too-large'] = (totals.skipped['too-large'] ?? 0) + 1
      emit({ type: 'skip', path: item.rel, reason: 'too-large' })
      continue
    }
    restoreFile(ctx, item.abs, item.rel)
  }
  vault.close()
  for (const record of stats.skipRecords) emit({ type: 'skip', path: record.path, reason: record.reason })
  const skipped: Record<string, number> = {}
  for (const [reason, count] of Object.entries(stats.skipped)) if (count > 0) skipped[reason] = count
  for (const [reason, count] of Object.entries(totals.skipped)) skipped[reason] = (skipped[reason] ?? 0) + count
  const complete = skipped['read-error'] === undefined && skipped['unreadable-dir'] === undefined && skipped['too-large'] === undefined
  const code = !complete ? 3 : totals.markersLeft > 0 || totals.skippedWithMarkers > 0 ? 1 : 0
  const summary = {
    type: 'summary',
    files_with_markers: totals.filesWithMarkers,
    files_restored: totals.filesRestored,
    markers_restored: totals.markersRestored,
    markers_moved_restored: totals.markersMovedRestored,
    markers_left: totals.markersLeft,
    type_mismatch: totals.typeMismatch,
    skipped,
    complete,
  }
  process.stdout.write(JSON.stringify(summary) + '\n', () => process.exit(code))
}

function main(argv: string[]): void {
  // WHY these handlers write fixed text and never the error: a stray error can carry text of a file or of a vault statement, and both hold secrets.
  process.on('uncaughtException', () => fatal('the restore stopped on an internal error'))
  process.on('unhandledRejection', () => fatal('the restore stopped on an internal error'))
  if (!restoreAllowed(process.env[VAULT_DIR_ENV] !== undefined, process.stdin.isTTY === true)) fatal(GUARD_TEXT)
  run(parseArgs(argv)).catch((error: unknown) => fatal(error instanceof VaultError ? error.message : 'the restore stopped on an internal error'))
}

if (import.meta.main) main(process.argv.slice(2))
