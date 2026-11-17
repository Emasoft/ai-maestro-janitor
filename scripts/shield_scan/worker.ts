// Child process of the secrets-shield scan (TRDD-BAQB9SYO increment 1a, redact step 3a-2): reads one file at a time, counts what the shield core finds in it and, when the job asks for it, redacts it.
// WHY a child process and not a thread or an in-process loop: the core passes are synchronous regexes, so a pathological file cannot be interrupted from inside its own thread; the driver (scan.ts) kills this process with SIGKILL at the per-file limit and starts a new one.
// Protocol, one JSON object per line. Driver to worker: {"path": <absolute path>, "passes": [<pass>, ...], "redact": null | {"minAgeMs": n, "root": <real path of the scan root>}}, one job at a time. Worker to driver:
//   {"t":"ready"}                                  once, after start-up (the driver arms no timer before it)
//   {"t":"skip","reason":"binary"|"read-error"}   the file was not scanned
//   {"t":"whole","bytes":n,"hits":{kind:count}}  the whole-file result; when it holds no hit the job ends here
//   {"t":"lines","hits":[[kind,line,count],...]} the per-line result of a file whose whole-file result holds a hit; with "redact" the job goes on:
//   {"t":"redact","outcome":"written","values":n,"residual":{kind:count},"homeRewrites":n,"rounds":n}  the file was replaced; n values are in the vault; residual holds the kinds and counts the passes still find between the markers of the new text after the last round (empty when none); homeRewrites counts the home paths rewritten last (not vaulted); rounds is how many redaction rounds ran (1 to 3)
//   {"t":"redact","outcome":"skip","reason":<write skip reason>}   the file was left as it was
//   {"t":"redact","outcome":"vault-error","message":<fixed text>}  the vault failed: the file was left as it was and the run ends with exit 2
// With "redact" the redaction runs HERE and the values never leave this process: not on stdout, not on stderr, not in a message.
// WHY no error text is ever written: a stack trace prints source text, and a scanned file can hold a secret. A failure exits the process; the driver records it as a crash.
// Nothing here writes a matched value: replies hold kinds, counts, line numbers and fixed text only.

import { closeSync, existsSync, fstatSync, openSync, readFileSync, realpathSync, type BigIntStats } from 'node:fs'
import { homedir } from 'node:os'
import { basename, dirname, sep } from 'node:path'
import { countOf, type Hits } from '../../hooks/secret-shield/patterns.ts'
import { isPass, redactAll, type Pass } from '../../hooks/secret-shield/pipeline.ts'
import { BINARY_PROBE_BYTES } from './fileset.ts'
import { finalText, HOME_KIND, HOME_ONLY, planRedaction, residualHits, restoreCheck, sweepPlan, vaultEntries, withoutHome, type Plan, type RedactJob, type RedactReply, type WriteSkipReason } from './redact.ts'
import type { Vault } from './vault.ts'
import { checkWriteTarget, gitOperation, writeAtomic } from './writeguard.ts'

// WHY a cap: each round plans, vaults and re-scans the whole text again, and a value that survives three rounds is a rule gap, which the run reports as residual and does not chase.
// WHY an env variable: a test-only hook like SHIELD_SCAN_TEST_LOCATE_DELAY_MS below, shipped in the code as that one is. No real input is known that survives 3 rounds, so a test lowers the cap to reach the residual path end to end. It can only lower the cap, never raise it; any other value throws when the module loads (fail fast, no fallback).
const capEnv = process.env.SHIELD_SCAN_TEST_MAX_ROUNDS
if (capEnv !== undefined && capEnv !== '1' && capEnv !== '2' && capEnv !== '3') throw new Error('SHIELD_SCAN_TEST_MAX_ROUNDS must be 1, 2 or 3')
const MAX_ROUNDS = capEnv === undefined ? 3 : Number(capEnv)
const homes: readonly string[] = [homedir()]
// ignoreBOM keeps a byte order mark in the text, so the text is the file and nothing else; invalid UTF-8 becomes U+FFFD (the decoder is not fatal).
const decoder = new TextDecoder('utf-8', { ignoreBOM: true })
// WHY this exists: fault injection for the tests only. It sleeps between the whole-file reply and the locate pass, so the test of the locate-kill branch can run the real kill path. No other use.
const locateDelayMs = Number(process.env.SHIELD_SCAN_TEST_LOCATE_DELAY_MS ?? 0)

// Resolves when the line has been flushed: the driver must see the whole-file reply before this process spends time on the locate pass.
const send = (message: object): Promise<void> =>
  new Promise((resolve) => {
    process.stdout.write(JSON.stringify(message) + '\n', () => resolve())
  })

const skipReply = (reason: WriteSkipReason): RedactReply => ({ t: 'redact', outcome: 'skip', reason })

// The vault is opened once per worker process, on the first file that needs it. Dynamic import: a scan without --redact never loads bun:sqlite.
let vault: Vault | null = null
let vaultDir: string | null = null

// Redacts one file that has findings, or says why not. The skips come first and cost no vault write; the vault rows of the file are committed (one transaction) before the file is replaced, so a crash in between leaves rows with no marker, never a marker with no row. A vault failure is a typed reply, never a crash.
async function redactFile(path: string, data: Buffer, before: BigIntStats, text: string, plan: Plan | null, passes: ReadonlySet<Pass>, job: RedactJob): Promise<RedactReply> {
  const { openVault, resolveVaultDir, VaultError } = await import('./vault.ts')
  try {
    let real: string
    try {
      real = realpathSync(path)
    } catch {
      return skipReply('write-error')
    }
    // Never written, only scanned and reported: anything inside a folder named .git, a .git pointer file, and the vault folder.
    if (basename(real) === '.git' || dirname(real).split(sep).includes('.git')) return skipReply('git-internal')
    vaultDir ??= resolveVaultDir()
    const vaultReal = existsSync(vaultDir) ? realpathSync(vaultDir) : vaultDir
    if (real.startsWith(vaultReal + sep)) return skipReply('vault-folder')
    if (before.nlink > 1n) return skipReply('hardlinked')
    // WHY minAgeMs > 0: with 0 no file is recent, even one whose mtime is a few milliseconds ahead of this clock.
    if (job.minAgeMs > 0 && Date.now() - Number(before.mtimeMs) < job.minAgeMs) return skipReply('recent')
    if (!Buffer.from(text, 'utf8').equals(data)) return skipReply('not-utf8')
    const operation = gitOperation(real)
    if (operation === 'operation') return skipReply('git-operation')
    if (operation === 'failed') return skipReply('git-check-failed')
    if (plan === null) return skipReply('align-error')
    // The marker passes only: the home pass writes no marker, so it stays out of the plan, the sweep and the re-scan and runs last (below).
    const markers = withoutHome(passes)
    // WHY rounds: one run over the text can leave a copy that no rule matched in that call (two assignments on one line: the first hides, the second is left). Each round plans again on the final text of the round before (its markers are cut out like old markers), sweeps, vaults, builds the next final text and checks its restore against the text of the round before; the file is written once, after the last round. At most MAX_ROUNDS: what is still found after the last round is reported as residual.
    let current = text
    let round: Plan = plan
    let rounds = 0
    let final = text
    let residual: Hits = {}
    const distinct = new Set<string>()
    for (;;) {
      rounds++
      // WHY the sweep runs here, after every skip and before the vault: the copies it finds are vaulted with the same rows, finalText writes them and restoreCheck covers them (spec R5).
      const swept = sweepPlan(round)
      const { entries, slot } = vaultEntries(swept)
      let uuids: string[] = []
      // A round with nothing to vault (a file whose only hits are home paths) never opens the vault.
      if (entries.length > 0) {
        vault ??= openVault()
        const rows = vault.lookupOrInsert(real, entries)
        uuids = slot.map((index) => rows[index])
        for (const uuid of rows) distinct.add(uuid)
      }
      final = finalText(swept, uuids)
      const open = vault
      if (!restoreCheck(swept, final, uuids, (uuid) => open?.byUuid(uuid)?.value ?? null, current)) return skipReply('align-error')
      // WHY the re-scan does not stop the write: the restore check passed, so the file loses nothing, and a residual hit is reported (kinds and counts) for the run to count and exit 1 on, never silently dropped.
      residual = residualHits(final, homes, markers)
      if (countOf(residual) === 0 || rounds === MAX_ROUNDS) break
      const next = planRedaction(final, homes, markers)
      if (next.plan === null) return skipReply('align-error')
      current = final
      round = next.plan
    }
    // WHY the home pass runs here, last, on the final text, after the vault step, the sweep, the re-scan and the restore check: its rewrites (/Users/x becomes ~) are neither vaulted nor restorable, and rewriting home paths in configs, scripts and virtualenvs changes what they point to, so it is opt-in (--passes home, spec R1).
    let out = final
    let homeRewrites = 0
    if (passes.has('home')) {
      const homed = redactAll(final, homes, HOME_ONLY)
      out = homed.text
      homeRewrites = homed.hits[HOME_KIND] ?? 0
    }
    // Nothing to vault and nothing to rewrite: the hits the walker counted cannot be explained, so the file is left alone.
    if (distinct.size === 0 && homeRewrites === 0) return skipReply('align-error')
    // WHY the target is checked again here and not only when the walker listed the file, and after the home pass: see writeguard.ts.
    const target = checkWriteTarget(path, job.root)
    if (target !== 'ok') return skipReply(target)
    const written = writeAtomic(real, Buffer.from(out, 'utf8'), before)
    return written === 'written' ? { t: 'redact', outcome: 'written', values: distinct.size, residual, homeRewrites, rounds } : skipReply(written)
  } catch (error) {
    if (error instanceof VaultError) return { t: 'redact', outcome: 'vault-error', message: error.message }
    throw error
  }
}

async function handle(line: string): Promise<void> {
  const job = JSON.parse(line) as { path: string; passes: string[]; redact: RedactJob | null }
  const passes = new Set<Pass>()
  for (const pass of job.passes) {
    if (!isPass(pass)) throw new Error('worker: not a pass')
    passes.add(pass)
  }
  let data: Buffer
  // WHY a stat tied to the read, in redact mode only: the write re-checks the file against what was read. The scan-only read stays as it was.
  let before: BigIntStats | null = null
  try {
    if (job.redact === null) data = readFileSync(job.path)
    else {
      const fd = openSync(job.path, 'r')
      try {
        before = fstatSync(fd, { bigint: true })
        data = readFileSync(fd)
      } finally {
        closeSync(fd)
      }
    }
  } catch {
    await send({ t: 'skip', reason: 'read-error' })
    return
  }
  if (data.subarray(0, BINARY_PROBE_BYTES).includes(0)) {
    await send({ t: 'skip', reason: 'binary' })
    return
  }
  const text = decoder.decode(data)
  // With redact the whole-file counts come from the plan (the stretches between the markers already in the file), so a file that holds only markers has no findings and a second run changes nothing.
  let whole: Hits
  let plan: Plan | null = null
  if (job.redact === null) whole = redactAll(text, homes, passes).hits
  else {
    const planned = planRedaction(text, homes, passes)
    whole = planned.hits
    plan = planned.plan
  }
  await send({ t: 'whole', bytes: data.length, hits: whole })
  if (countOf(whole) === 0) return
  if (locateDelayMs > 0) await new Promise((resolve) => setTimeout(resolve, locateDelayMs))
  const located: Array<[string, number, number]> = []
  const lines = text.split('\n')
  for (let index = 0; index < lines.length; index++) {
    const raw = lines[index]
    if (raw.length === 0) continue
    const one = raw.endsWith('\r') ? raw.slice(0, -1) : raw
    for (const [kind, count] of Object.entries(redactAll(one, homes, passes).hits)) located.push([kind, index + 1, count])
  }
  await send({ t: 'lines', hits: located })
  if (job.redact !== null && before !== null) await send(await redactFile(job.path, data, before, text, plan, passes, job.redact))
}

let buffer = ''
let chain: Promise<void> = Promise.resolve()
// WHY the failure handler exits and logs nothing: see the header. The driver sees the exit without a reply and records a crash.
const fail = (): never => process.exit(1)
process.stdin.setEncoding('utf8')
process.stdin.on('data', (chunk: string) => {
  buffer += chunk
  for (let end = buffer.indexOf('\n'); end >= 0; end = buffer.indexOf('\n')) {
    const line = buffer.slice(0, end)
    buffer = buffer.slice(end + 1)
    chain = chain.then(() => handle(line)).catch(fail)
  }
})
process.stdin.on('end', () => {
  void chain.then(() => process.exit(0))
})
void send({ t: 'ready' })
