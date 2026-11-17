// secrets-shield vault, increment 3 step 3a-1 (TRDD-BAQB9SYO; vault design TRDD-QM8YRCZ5): every redacted value is kept in plain text in one SQLite file, keyed by the uuid that goes into the redaction marker.
// Library: openVault() -> { lookupOrInsert(origin, entries), byUuid(uuid), list(), remove(uuid), close() }. The caller (the redact step) looks up or inserts the rows of one file, commits, and only then replaces the file.
// CLI (human and agent safe, never prints a value): bun vault.ts list  (TAB-separated, one row per line: uuid, type, origin, first_seen, last_seen, count) · bun vault.ts delete <uuid>  (exit 0 deleted, 1 not found).
// There is no restore command here: restore.ts (step 3a-4) is human-only and is the only reader of a value besides byUuid().
// A value never reaches argv, stdout, stderr or an error message: every error is fixed text (plus a SQLITE_* code, which is fixed text of SQLite itself).
// Exit: 0 ok · 1 delete found no such row · 2 usage or fatal error.

import { spawnSync } from 'node:child_process'
import { randomUUID } from 'node:crypto'
import { existsSync, mkdirSync, realpathSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { basename, dirname, isAbsolute, join, resolve, sep } from 'node:path'
import { Database } from 'bun:sqlite'

// Test-only setting. It names the vault FOLDER (vault.db goes inside it). Nothing else can move the vault; see checkedTestDir for the rule.
export const VAULT_DIR_ENV = 'SECRETS_SHIELD_VAULT_DIR'
const VAULT_FILE = 'vault.db'
const BUSY_TIMEOUT_MS = 10_000
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

export type Encoding = 'raw' | 'json-string'

export interface VaultEntry {
  value: string
  type: string
  encoding: Encoding
}

// Everything a row holds except the value: the only shape list() and the CLI ever see.
export interface VaultMeta {
  uuid: string
  type: string
  origin: string
  encoding: Encoding
  first_seen: string
  last_seen: string
  count: number
}

export interface VaultRow extends VaultMeta {
  value: string
}

// A fixed-text error: its message is shown to the user and never holds a value or SQLite's own message.
export class VaultError extends Error {
  override name = 'VaultError'
}

const OUTSIDE_TMP = `${VAULT_DIR_ENV} is accepted only for an absolute path inside the system temp folder`

// WHY a SQLITE_* code is the only detail kept: bun's SQLite error message can quote SQL or schema text, and the row values are bound parameters that must never travel in a message. The code alone is fixed text and tells busy from full disk from read-only.
function sqliteCode(error: unknown): string {
  const code = (error as { code?: unknown } | null)?.code
  return typeof code === 'string' && /^SQLITE_[A-Z0-9_]+$/.test(code) ? ` (${code})` : ''
}

// WHY the setup statements of a first open are retried here and busy_timeout alone is not enough. Measured on 2026-11-18, 8 bun processes opening a NEW vault folder at once: the statement that returned SQLITE_BUSY was PRAGMA journal_mode = WAL (62 of 480 runs of a probe that repeated the setup statements one by one; 35 of 160 openVault calls failed in the same setup), and it failed after 0 to 1 ms although busy_timeout was 10000 ms, so SQLite did not wait for it. Why the busy handler is not called for that statement was not isolated. CREATE TABLE was never seen to fail in that measurement; it is retried too because it belongs to the same first-open setup. An open of a vault that already exists was measured at 0 failures in 160. Only SQLITE_BUSY is retried, until BUSY_TIMEOUT_MS has passed in total; any other error, and the last busy one, goes on to the fixed-text error of openVault. The jitter keeps several workers from retrying in step.
function retryBusy<T>(step: () => T): T {
  const deadline = Date.now() + BUSY_TIMEOUT_MS
  for (;;) {
    try {
      return step()
    } catch (error) {
      if ((error as { code?: unknown } | null)?.code !== 'SQLITE_BUSY' || Date.now() >= deadline) throw error
      // Atomics.wait is a synchronous sleep that needs no Bun type declaration (tsc has none for the Bun global here).
      Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, 5 + Math.random() * 10)
    }
  }
}

// Absolute path of `path` with every symlink resolved, also when the last components do not exist yet: the nearest existing ancestor is resolved and the missing tail is appended. WHY: the test-only folder is checked BEFORE it is created, and a plain realpathSync would throw on a folder that does not exist yet.
function realpathOfMissing(path: string): string {
  const tail: string[] = []
  let current = path
  while (!existsSync(current)) {
    const parent = dirname(current)
    if (parent === current) break
    tail.unshift(basename(current))
    current = parent
  }
  return join(realpathSync(current), ...tail)
}

// The test-only folder is honoured only when its REAL path (symlinks and .. resolved) lies strictly inside the real path of os.tmpdir(). WHY real paths on both sides: tmpdir() is itself a symlink on macOS (/var -> /private/var), and a symlink or a .. inside the temp folder could otherwise point the vault anywhere, which is the one thing the owner's "no override" order forbids. Any other value is fatal, never ignored: ignoring it would let a test believe it ran on a temp vault while writing the real one.
function checkedTestDir(setting: string): string {
  if (!isAbsolute(setting)) throw new VaultError(OUTSIDE_TMP)
  const real = realpathOfMissing(resolve(setting))
  const tmp = realpathSync(tmpdir())
  if (!real.startsWith(tmp + sep)) throw new VaultError(OUTSIDE_TMP)
  return real
}

// The account's home folder from the OS account database, never from HOME.
// WHY not os.userInfo().homedir: measured 2026-11-17 under bun 1.3.14, `HOME=<tmp> bun -e` prints the tmp folder for os.homedir() and also for os.userInfo().homedir, and USER=<fake> makes userInfo().username the fake name, so both follow the environment. A process (or a test) that sets HOME must not move the vault, so the lookup goes by the numeric uid through dscl (macOS) or getent (elsewhere).
// WHY absolute binary paths: the lookup must not depend on PATH.
// Exported: the vault test's real-vault guard must read the account home from this same lookup, not from HOME.
export function accountHome(): string {
  const uid = process.getuid?.()
  const failed = new VaultError('the home folder of the account could not be found')
  if (uid === undefined) throw failed
  let home: string | undefined
  if (process.platform === 'darwin') {
    const search = spawnSync('/usr/bin/dscl', ['.', '-search', '/Users', 'UniqueID', String(uid)], { encoding: 'utf8' })
    if (search.status !== 0) throw failed
    const name = /^(\S+)\s+UniqueID = \(/m.exec(search.stdout)?.[1]
    if (name === undefined) throw failed
    const read = spawnSync('/usr/bin/dscl', ['.', '-read', `/Users/${name}`, 'NFSHomeDirectory'], { encoding: 'utf8' })
    if (read.status !== 0) throw failed
    // "NFSHomeDirectory: /Users/x", or the path on the next line when it holds a space.
    home = /^NFSHomeDirectory:\s*(\S.*)$/m.exec(read.stdout)?.[1]
  } else if (process.platform === 'linux') {
    const entry = spawnSync('/usr/bin/getent', ['passwd', String(uid)], { encoding: 'utf8' })
    if (entry.status !== 0) throw failed
    home = entry.stdout.trim().split(':')[5]
  }
  if (home === undefined || !isAbsolute(home)) throw failed
  return home
}

// The folder that holds vault.db, resolved but not created.
export function resolveVaultDir(): string {
  const setting = process.env[VAULT_DIR_ENV]
  if (setting !== undefined) return checkedTestDir(setting)
  return join(accountHome(), '.secrets_shield')
}

export interface Vault {
  // One BEGIN IMMEDIATE transaction: every entry is looked up by (origin, value, encoding) and inserted when missing; returns each entry's uuid, in order. A repeat bumps last_seen and count.
  lookupOrInsert(origin: string, entries: VaultEntry[]): string[]
  byUuid(uuid: string): VaultRow | null
  list(): VaultMeta[]
  remove(uuid: string): boolean
  close(): void
}

export function openVault(): Vault {
  const dir = resolveVaultDir()
  const file = join(dir, VAULT_FILE)
  let db: Database | undefined
  try {
    // WHY no explicit mode: the owner dropped the restricted 0700 and 0600 modes on 2026-11-16 (card QM8YRCZ5). The vault must work unattended and local protection is impossible, so the folder takes the umask default (0777 minus the umask) and vault.db takes SQLite's default creation mode (0644 minus the umask).
    mkdirSync(dir, { recursive: true })
    if (!statSync(dir).isDirectory()) throw new VaultError('the vault folder is not a folder')
    const opened = new Database(file)
    db = opened
    // WHY busy_timeout before journal_mode: every redact worker opens the vault, and the first open switches the file to WAL while another worker may be doing the same. It covers the statements that wait for a lock; the two setup statements below are also retried (see retryBusy).
    db.exec(`PRAGMA busy_timeout = ${BUSY_TIMEOUT_MS}`)
    const mode = retryBusy(() => opened.query('PRAGMA journal_mode = WAL').get()) as { journal_mode?: string } | null
    // WHY a hard check: some filesystems refuse WAL and SQLite silently keeps the old mode; concurrent workers then fail unpredictably, so stop here.
    if (mode?.journal_mode?.toLowerCase() !== 'wal') throw new VaultError('the vault could not be put in WAL mode')
    // WHY the UNIQUE key is (origin, value, encoding): the same secret in the same file reuses its uuid and another file gets its own (owner order). encoding separates the raw text from its JSON-string form, whose restore writes the escaped text.
    retryBusy(() =>
      opened.exec(`CREATE TABLE IF NOT EXISTS secrets (
      uuid TEXT PRIMARY KEY,
      type TEXT NOT NULL,
      origin TEXT NOT NULL,
      value TEXT NOT NULL,
      encoding TEXT NOT NULL CHECK (encoding IN ('raw', 'json-string')),
      first_seen TEXT NOT NULL,
      last_seen TEXT NOT NULL,
      count INTEGER NOT NULL,
      UNIQUE (origin, value, encoding)
    )`),
    )
  } catch (error) {
    db?.close()
    if (error instanceof VaultError) throw error
    throw new VaultError(`the vault could not be opened${sqliteCode(error)}`)
  }
  return wrap(db)
}

function wrap(db: Database): Vault {
  // WHY ON CONFLICT DO UPDATE ... RETURNING and not INSERT OR IGNORE then SELECT: one statement per entry that is atomic against another worker and returns the uuid of the row that exists, new or old. The fresh uuid generated for a repeat is discarded. type is not updated on a repeat: the row keeps the kind it was first vaulted with.
  const upsert = db.prepare(
    `INSERT INTO secrets (uuid, type, origin, value, encoding, first_seen, last_seen, count) VALUES (?, ?, ?, ?, ?, ?, ?, 1)
     ON CONFLICT (origin, value, encoding) DO UPDATE SET last_seen = excluded.last_seen, count = count + 1
     RETURNING uuid`,
  )
  const meta = 'uuid, type, origin, encoding, first_seen, last_seen, count'
  const selectOne = db.prepare(`SELECT ${meta}, value FROM secrets WHERE uuid = ?`)
  // WHY list() never selects the value: the CLI process then never holds one, so no bug in its printing can leak it.
  const selectAll = db.prepare(`SELECT ${meta} FROM secrets ORDER BY first_seen, uuid`)
  const deleteOne = db.prepare('DELETE FROM secrets WHERE uuid = ?')

  return {
    lookupOrInsert(origin, entries) {
      if (!isAbsolute(origin)) throw new VaultError('the origin of a vault entry must be an absolute path')
      for (const entry of entries) {
        if (entry.value === '') throw new VaultError('a vault entry has an empty value')
        if (entry.encoding !== 'raw' && entry.encoding !== 'json-string') throw new VaultError('a vault entry has an unknown encoding')
        if (entry.type === '') throw new VaultError('a vault entry has an empty type')
      }
      const now = new Date().toISOString()
      // WHY IMMEDIATE: it takes the write lock at BEGIN, so a second worker waits (busy_timeout) instead of failing half way with a lock upgrade error. The transaction is all-or-nothing: a failed entry rolls the whole file's rows back, and the redact step then leaves the file untouched.
      const run = db.transaction(() => entries.map((entry) => (upsert.get(randomUUID(), entry.type, origin, entry.value, entry.encoding, now, now) as { uuid: string }).uuid))
      try {
        return run.immediate()
      } catch (error) {
        throw new VaultError(`the vault write failed${sqliteCode(error)}`)
      }
    },
    byUuid(uuid) {
      try {
        return (selectOne.get(uuid) as VaultRow | null) ?? null
      } catch (error) {
        throw new VaultError(`the vault read failed${sqliteCode(error)}`)
      }
    },
    list() {
      try {
        return selectAll.all() as VaultMeta[]
      } catch (error) {
        throw new VaultError(`the vault read failed${sqliteCode(error)}`)
      }
    },
    remove(uuid) {
      try {
        return deleteOne.run(uuid).changes > 0
      } catch (error) {
        throw new VaultError(`the vault write failed${sqliteCode(error)}`)
      }
    },
    close() {
      db.close()
    },
  }
}

function fatal(message: string): never {
  process.stderr.write(`shield-vault: ${message}\n`)
  return process.exit(2)
}

// A field of a list line: the TAB and the line breaks that would shift a column are written as \t \n \r (an origin is a real path and can hold any of them).
function field(text: string): string {
  return text.replace(/[\t\n\r]/g, (char) => (char === '\t' ? '\\t' : char === '\n' ? '\\n' : '\\r'))
}

function main(argv: string[]): void {
  // WHY these handlers write fixed text and never the error: a stray error can carry text of a vault statement, and the vault holds secrets.
  process.on('uncaughtException', () => fatal('the vault command stopped on an internal error'))
  process.on('unhandledRejection', () => fatal('the vault command stopped on an internal error'))
  const [command, uuid, ...rest] = argv
  const usage = 'usage: bun vault.ts list | bun vault.ts delete <uuid>'
  if (command === 'list' && uuid === undefined) {
    const vault = openOrFatal()
    for (const row of vault.list()) process.stdout.write([row.uuid, field(row.type), field(row.origin), row.first_seen, row.last_seen, String(row.count)].join('\t') + '\n')
    vault.close()
  } else if (command === 'delete' && uuid !== undefined && rest.length === 0) {
    // WHY the argument is checked and never echoed: a malformed argument could be pasted text that holds a secret.
    if (!UUID_RE.test(uuid)) return fatal('the argument is not a uuid')
    const vault = openOrFatal()
    const removed = vault.remove(uuid)
    vault.close()
    process.stdout.write(removed ? 'deleted\n' : 'not found\n')
    process.exit(removed ? 0 : 1)
  } else {
    fatal(usage)
  }
}

function openOrFatal(): Vault {
  try {
    return openVault()
  } catch (error) {
    return fatal(error instanceof VaultError ? error.message : 'the vault could not be opened')
  }
}

if (import.meta.main) main(process.argv.slice(2))
