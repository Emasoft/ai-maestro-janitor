// Real-bun tests of the secrets-shield vault (TRDD-BAQB9SYO step 3a-1): a real SQLite file under the system temp folder, the real CLI in a child process, no mock.
// Every value below is an obviously fake string. All test data stays far below the 4 GB cap (a few small files in tmp).
// The real vault (~/.secrets_shield) must never be touched: every test points SECRETS_SHIELD_VAULT_DIR at a fresh folder under tmp, and the last test checks the real file did not change.

import { afterAll, afterEach, beforeEach, describe, expect, test } from 'bun:test'
import { chmodSync, existsSync, mkdirSync, mkdtempSync, realpathSync, rmSync, statSync, symlinkSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { dirname, join } from 'node:path'
import { Database } from 'bun:sqlite'
import { accountHome, openVault, resolveVaultDir, VAULT_DIR_ENV, VaultError, type Vault } from '../vault.ts'

const VAULT_TS = join(import.meta.dir, '..', 'vault.ts')
const FAKE_VALUE = 'fake-vault-value-not-a-real-secret-0001'
const ORIGIN = '/tmp/fake-project/.env'
const OUTSIDE_TMP_TEXT = `${VAULT_DIR_ENV} is accepted only for an absolute path inside the system temp folder`
const UUID_V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/

// The real vault's state before the suite: the guard test compares against it at the end.
const REAL_HOME = process.env.SHIELD_TEST_ACCOUNT_HOME ?? accountHome()
const REAL_VAULT = join(REAL_HOME, '.secrets_shield', 'vault.db')
// WHY the -wal and -shm files are part of the snapshot: in WAL mode a write lands in vault.db-wal and leaves vault.db's mtime unchanged until a checkpoint, so the main file alone would miss a write.
function realState(): string {
  return [REAL_VAULT, REAL_VAULT + '-wal', REAL_VAULT + '-shm'].map((file) => (existsSync(file) ? `${statSync(file).mtimeMs}:${statSync(file).size}` : 'absent')).join(' | ')
}
const realBefore = realState()

let dir: string
let vault: Vault | null = null

function sleep(ms: number): Promise<void> {
  return new Promise((done) => setTimeout(done, ms))
}

function modeOf(path: string): number {
  return statSync(path).mode & 0o777
}

// The CLI in its own process, with the vault folder given by the test-only setting. The caller's env is explicit so HOME and the setting are exactly what the test says.
async function cli(args: string[], env: Record<string, string | undefined>): Promise<{ code: number; out: string; err: string }> {
  // WHY TMPDIR is passed through: the setting is accepted only inside os.tmpdir(), which follows TMPDIR; without it the child's tmpdir() differs from the parent's and refuses the folder.
  const child = Bun.spawn(['bun', VAULT_TS, ...args], { env: { PATH: process.env.PATH, TMPDIR: process.env.TMPDIR, ...env }, stdout: 'pipe', stderr: 'pipe' })
  const [out, err] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text()])
  return { code: await child.exited, out, err }
}

beforeEach(() => {
  dir = join(mkdtempSync(join(tmpdir(), 'shield-vault-test-')), 'vault')
  process.env[VAULT_DIR_ENV] = dir
})

afterEach(() => {
  vault?.close()
  vault = null
  delete process.env[VAULT_DIR_ENV]
  // Own scratch folder under the system temp folder, created by beforeEach.
  rmSync(dirname(dir), { recursive: true, force: true })
})

function open(): Vault {
  vault = openVault()
  return vault
}

describe('uuid identity', () => {
  test('the same (origin, value, encoding) gives the same uuid, in one call and across calls', () => {
    const v = open()
    const [a, b] = v.lookupOrInsert(ORIGIN, [
      { value: FAKE_VALUE, type: 'fake-kind', encoding: 'raw' },
      { value: FAKE_VALUE, type: 'fake-kind', encoding: 'raw' },
    ])
    const [c] = v.lookupOrInsert(ORIGIN, [{ value: FAKE_VALUE, type: 'fake-kind', encoding: 'raw' }])
    expect(a).toMatch(UUID_V4)
    expect(b).toBe(a)
    expect(c).toBe(a)
    // A new connection (another worker) sees the same row.
    v.close()
    vault = null
    const [d] = open().lookupOrInsert(ORIGIN, [{ value: FAKE_VALUE, type: 'fake-kind', encoding: 'raw' }])
    expect(d).toBe(a)
  })

  test('another origin or another value gives a new uuid', () => {
    const v = open()
    const [base] = v.lookupOrInsert(ORIGIN, [{ value: FAKE_VALUE, type: 'fake-kind', encoding: 'raw' }])
    const [otherOrigin] = v.lookupOrInsert('/tmp/fake-project/other.env', [{ value: FAKE_VALUE, type: 'fake-kind', encoding: 'raw' }])
    const [otherValue] = v.lookupOrInsert(ORIGIN, [{ value: FAKE_VALUE + 'x', type: 'fake-kind', encoding: 'raw' }])
    expect(new Set([base, otherOrigin, otherValue]).size).toBe(3)
    expect(v.list()).toHaveLength(3)
  })

  test('byUuid returns the whole row, value included; an unknown uuid gives null', () => {
    const v = open()
    const [id] = v.lookupOrInsert(ORIGIN, [{ value: FAKE_VALUE, type: 'fake-kind', encoding: 'raw' }])
    const row = v.byUuid(id)
    expect(row).toMatchObject({ uuid: id, type: 'fake-kind', origin: ORIGIN, value: FAKE_VALUE, encoding: 'raw', count: 1 })
    expect(v.byUuid('00000000-0000-4000-8000-000000000000')).toBeNull()
  })
})

describe('bookkeeping', () => {
  test('count and last_seen advance on a repeat, first_seen and type stay', async () => {
    const v = open()
    const [id] = v.lookupOrInsert(ORIGIN, [{ value: FAKE_VALUE, type: 'first-kind', encoding: 'raw' }])
    const first = v.byUuid(id)!
    await sleep(25)
    v.lookupOrInsert(ORIGIN, [{ value: FAKE_VALUE, type: 'second-kind', encoding: 'raw' }])
    const second = v.byUuid(id)!
    expect(first.count).toBe(1)
    expect(second.count).toBe(2)
    expect(second.first_seen).toBe(first.first_seen)
    expect(second.last_seen > first.last_seen).toBe(true)
    expect(second.type).toBe('first-kind')
  })

  test('lookupOrInsert refuses the json-string encoding with the fixed text and writes no row', () => {
    const v = open()
    const attempt = () => v.lookupOrInsert(ORIGIN, [{ value: FAKE_VALUE, type: 'fake-kind', encoding: 'json-string' as never }])
    expect(attempt).toThrow(VaultError)
    expect(attempt).toThrow('a vault entry has an unknown encoding')
    expect(v.list()).toHaveLength(0)
  })

  test('a failed entry rolls the whole call back and the error never holds a value', () => {
    const v = open()
    let message = ''
    try {
      v.lookupOrInsert(ORIGIN, [
        { value: FAKE_VALUE, type: 'fake-kind', encoding: 'raw' },
        { value: FAKE_VALUE + 'bad', type: 'fake-kind', encoding: 'bogus' as never },
      ])
    } catch (error) {
      expect(error).toBeInstanceOf(VaultError)
      message = (error as Error).message
    }
    expect(message).not.toBe('')
    expect(message).not.toContain(FAKE_VALUE)
    expect(v.list()).toHaveLength(0)
    expect(() => v.lookupOrInsert('relative/path', [{ value: FAKE_VALUE, type: 'fake-kind', encoding: 'raw' }])).toThrow(VaultError)
    expect(() => v.lookupOrInsert(ORIGIN, [{ value: '', type: 'fake-kind', encoding: 'raw' }])).toThrow(VaultError)
  })
})

describe('storage', () => {
  test('a new vault refuses a json-string row at the database level, so the CHECK says raw too', () => {
    open().close()
    vault = null
    const writer = new Database(join(dir, 'vault.db'))
    try {
      const insert = 'INSERT INTO secrets (uuid, type, origin, value, encoding, first_seen, last_seen, count) VALUES (?, ?, ?, ?, ?, ?, ?, 1)'
      expect(() => writer.query(insert).run('00000000-0000-4000-8000-0000000000aa', 'fake-kind', ORIGIN, FAKE_VALUE, 'json-string', 'now', 'now')).toThrow(/CHECK constraint failed/)
    } finally {
      writer.close()
    }
  })

  test('the database is in WAL mode', () => {
    open()
    const reader = new Database(join(dir, 'vault.db'), { readonly: true })
    expect((reader.query('PRAGMA journal_mode').get() as { journal_mode: string }).journal_mode).toBe('wal')
    reader.close()
  })

  test('the folder gets 0777 minus the umask, vault.db 0644 minus the umask, a pre-existing folder keeps 0755', () => {
    const mask = process.umask()
    const fresh = open()
    expect(modeOf(dir)).toBe(0o777 & ~mask)
    // WHY 0644: SQLite creates a new database file with 0644, and the umask applies on top of that.
    expect(modeOf(join(dir, 'vault.db'))).toBe(0o644 & ~mask)
    fresh.close()
    vault = null
    const existing = join(dirname(dir), 'existing')
    mkdirSync(existing, { mode: 0o755 })
    chmodSync(existing, 0o755)
    process.env[VAULT_DIR_ENV] = existing
    open()
    expect(modeOf(existing)).toBe(0o755)
  })

  test('a second connection waits for the write lock (busy_timeout) instead of failing', async () => {
    const v = open()
    v.lookupOrInsert(ORIGIN, [{ value: FAKE_VALUE, type: 'fake-kind', encoding: 'raw' }])
    // A separate process holds the write lock for about 1.5 s, then commits.
    const holder = Bun.spawn(
      [
        'bun',
        '-e',
        `import { Database } from 'bun:sqlite'
         const db = new Database(process.argv[1])
         db.exec('PRAGMA busy_timeout = 10000')
         db.exec('BEGIN IMMEDIATE')
         console.log('locked')
         await Bun.sleep(1500)
         db.exec('COMMIT')
         db.close()`,
        join(dir, 'vault.db'),
      ],
      { stdout: 'pipe', stderr: 'pipe' },
    )
    const reader = holder.stdout.getReader()
    const first = await reader.read()
    expect(new TextDecoder().decode(first.value)).toContain('locked')
    const started = Date.now()
    // Blocks this thread until the holder commits; without busy_timeout it would throw SQLITE_BUSY at once.
    const [id] = v.lookupOrInsert(ORIGIN, [{ value: FAKE_VALUE + 'busy', type: 'fake-kind', encoding: 'raw' }])
    expect(Date.now() - started).toBeGreaterThan(500)
    expect(id).toMatch(UUID_V4)
    await holder.exited
  })
})

describe('command line', () => {
  test('list prints uuid, type, origin, times and count, never a value; delete removes one row', async () => {
    const v = open()
    const [keep, drop] = v.lookupOrInsert(ORIGIN, [
      { value: FAKE_VALUE + 'keep', type: 'keep-kind', encoding: 'raw' },
      { value: FAKE_VALUE + 'drop', type: 'drop-kind', encoding: 'raw' },
    ])
    v.close()
    vault = null
    const env = { [VAULT_DIR_ENV]: dir }

    const listed = await cli(['list'], env)
    expect(listed.code).toBe(0)
    expect(listed.out + listed.err).not.toContain(FAKE_VALUE)
    const lines = listed.out.trimEnd().split('\n')
    expect(lines).toHaveLength(2)
    const columns = lines.find((line) => line.startsWith(keep))!.split('\t')
    expect(columns).toHaveLength(6)
    expect(columns[1]).toBe('keep-kind')
    expect(columns[2]).toBe(ORIGIN)
    expect(columns[5]).toBe('1')

    const deleted = await cli(['delete', drop], env)
    expect(deleted.code).toBe(0)
    expect(deleted.out).toBe('deleted\n')
    const reopened = open()
    expect(reopened.byUuid(drop)).toBeNull()
    expect(reopened.byUuid(keep)).not.toBeNull()
    reopened.close()
    vault = null

    const again = await cli(['delete', drop], env)
    expect(again.code).toBe(1)
    expect(again.out).toBe('not found\n')
  })

  test('a malformed delete argument and a bad command are refused with fixed text that does not echo the argument', async () => {
    const env = { [VAULT_DIR_ENV]: dir }
    const bad = await cli(['delete', FAKE_VALUE], env)
    expect(bad.code).toBe(2)
    expect(bad.err).toBe('shield-vault: the argument is not a uuid\n')
    const usage = await cli(['restore', FAKE_VALUE], env)
    expect(usage.code).toBe(2)
    expect(usage.err + usage.out).not.toContain(FAKE_VALUE)
  })
})

describe('first open', () => {
  // The race of several workers creating the same vault at once (step 3a-3a): each round is a NEW folder, so every round exercises the first open (create file, switch to WAL, create table).
  test('8 processes opening a new vault folder at the same time, 20 rounds, never fail', async () => {
    const script = `import { openVault } from ${JSON.stringify(VAULT_TS)}; try { openVault().close() } catch (error) { console.error(error.message); process.exit(1) }`
    const started = performance.now()
    for (let round = 0; round < 20; round++) {
      const fresh = join(dirname(dir), `race-${round}`)
      const children = Array.from({ length: 8 }, () => Bun.spawn(['bun', '-e', script], { env: { PATH: process.env.PATH, TMPDIR: process.env.TMPDIR, [VAULT_DIR_ENV]: fresh }, stdout: 'ignore', stderr: 'pipe' }))
      const results = await Promise.all(children.map(async (child) => ({ err: await new Response(child.stderr).text(), code: await child.exited })))
      expect(results.filter((result) => result.code !== 0)).toEqual([])
    }
    console.log(`first-open race: 20 rounds x 8 processes in ${Math.round(performance.now() - started)} ms`)
  }, 180_000)
})

describe('where the vault lives', () => {
  test('a setting outside the system temp folder is refused: relative, outside, .. escape and a symlink out of tmp', async () => {
    const tmp = realpathSync(tmpdir())
    const link = join(dirname(dir), 'link-out')
    symlinkSync(dirname(tmp), link)
    const escapes = ['relative/vault', '', '/usr/local/zz-shield-vault-test', join(dirname(dir), '..', '..', 'zz-shield-vault-test'), join(link, 'zz-shield-vault-test')]
    for (const setting of escapes) {
      process.env[VAULT_DIR_ENV] = setting
      expect(() => openVault()).toThrow(OUTSIDE_TMP_TEXT)
    }
    // Nothing was created by a refused setting.
    expect(existsSync('/usr/local/zz-shield-vault-test')).toBe(false)
    expect(existsSync(join(dirname(tmp), 'zz-shield-vault-test'))).toBe(false)
    expect(existsSync(join(tmp, '..', 'zz-shield-vault-test'))).toBe(false)

    // The folder tmpdir() itself is not "inside" it either.
    process.env[VAULT_DIR_ENV] = tmp
    expect(() => openVault()).toThrow(OUTSIDE_TMP_TEXT)

    // The CLI turns it into exit 2 with the same fixed line.
    const refused = await cli(['list'], { [VAULT_DIR_ENV]: '/usr/local/zz-shield-vault-test' })
    expect(refused.code).toBe(2)
    expect(refused.err).toBe(`shield-vault: ${OUTSIDE_TMP_TEXT}\n`)
    expect(refused.out).toBe('')
  })

  test('HOME set elsewhere does not move the vault: the home comes from the account database', async () => {
    const fakeHome = mkdtempSync(join(tmpdir(), 'shield-vault-fakehome-'))
    try {
      const child = Bun.spawn(['bun', '-e', `import { resolveVaultDir } from ${JSON.stringify(VAULT_TS)}; console.log(resolveVaultDir())`], {
        env: { PATH: process.env.PATH, HOME: fakeHome, USER: 'zz-fake-user', LOGNAME: 'zz-fake-user' },
        stdout: 'pipe',
        stderr: 'pipe',
      })
      const [out, err] = await Promise.all([new Response(child.stdout).text(), new Response(child.stderr).text()])
      expect(await child.exited).toBe(0)
      expect(err).toBe('')
      expect(out.trim()).toBe(join(REAL_HOME, '.secrets_shield'))
      expect(out.includes(fakeHome)).toBe(false)
    } finally {
      rmSync(fakeHome, { recursive: true, force: true })
    }
    // Same answer in this process when the setting is absent (resolveVaultDir creates nothing).
    delete process.env[VAULT_DIR_ENV]
    expect(resolveVaultDir()).toBe(join(REAL_HOME, '.secrets_shield'))
  })
})

afterAll(() => {
  // The suite never wrote the real vault: same existence, modification time and size of vault.db, vault.db-wal and vault.db-shm as before.
  expect(realState()).toBe(realBefore)
})
