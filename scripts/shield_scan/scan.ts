// secrets-shield scan, increment 1a (TRDD-BAQB9SYO; redact mode, increment 3 step 3a-2): scans a project folder for secrets with the shield core and writes one JSON line per finding; with --redact it also replaces each secret in the files with a marker and keeps the value in the vault (vault.ts).
// Run: bun run <plugin root>/scripts/shield_scan/scan.ts [options] [root]
// Options: --all (gitignored and hidden files too, plus each repo .git/config) · --passes secrets,cards (default; email and home are opt-in; with --redact the home pass rewrites paths to ~ and is not restorable) · --jobs N · --out PATH · --max-file-mb N (64) · --max-large-mb N (1024, at least --max-file-mb; with --redact only) · --file-timeout-base S (30) · --file-timeout-per-mb S (5) · --redact · --min-age-minutes N (10; with --redact a file modified within N minutes is not written).
// Records (never a matched value or any text of a scanned file): {"type":"finding","path","kind","line"|null,"count"} · {"type":"skip","path","reason"} · with --redact {"type":"residual","path","kind","count"} (what the passes still find between the markers of a file that was written) · {"type":"summary",...} last.
// Exit: 0 complete with no findings (with --redact: complete and every finding redacted, no residual) · 1 complete with findings (with --redact: findings_not_redacted or residual above 0) · 3 incomplete (a timeout, read-error, crash, git-error or unreadable-dir skip) · 2 usage or fatal error (with --redact also a vault failure).
// A .jsonl or .ndjson file is read JSON-aware in both modes (jsonl.ts, spec R6). The summary holds jsonl_lines_not_json, the number of non-blank lines of those files that are not JSON (they are read as text). A finding of kind json-unredactable is a JSON line the shield could not hide without breaking it; with --redact the file is then skipped as json-broken, as it is when the rewrite would leave a line that parsed before unparseable.
// With --redact the worker sweeps the plan for copies of each redacted value that no pass matched, and runs the passes again over the text between the markers of the new file (redact.ts: sweepPlan, residualHits); while that re-scan finds something it runs another round (at most 3, summary rounds_used_max) and writes once after the last one. The summary then says residual_check "run" and holds the residual total of what is still found after the last round. A residual hit does not stop the write (the restore check passed); it makes the run exit 1.
// With --redact a text file over --max-file-mb and up to --max-large-mb goes to the large lane (one such file at a time, one dedicated worker; summary large_lane_files); a text file over --max-large-mb is neither scanned nor redacted: a skip record not-scanned-too-large, counted in files_not_scanned, and the run is incomplete (exit 3). A binary file over --max-file-mb stays an ordinary binary skip. The home pass with --redact runs last on the final text and its rewrites are neither vaulted nor restorable (summary home_rewrites); home hits are findings of kind home and never count as findings_not_redacted.
// stdout: the summary line and the findings file path, nothing else. stderr: fixed text only. The pass order is the core's (hooks/secret-shield/pipeline.ts); this file carries none of its own.

import { spawn, spawnSync, type ChildProcessByStdio } from 'node:child_process'
import { createHash } from 'node:crypto'
import { existsSync, mkdirSync, readdirSync, readFileSync, realpathSync, renameSync, statSync, writeFileSync } from 'node:fs'
import { cpus, homedir } from 'node:os'
import { basename, dirname, join, resolve } from 'node:path'
import type { Readable, Writable } from 'node:stream'
import { fileURLToPath } from 'node:url'
import { isPass, PASS_ORDER, type Pass } from '../../hooks/secret-shield/pipeline.ts'
import { findGitTop, newStats, noteSkip, SKIP_REASONS, walkFiles, type FileItem, type SetStats, type SkipReason } from './fileset.ts'
import { HOME_KIND, WRITE_SKIP_REASONS, type RedactJob, type RedactReply, type WriteSkipReason } from './redact.ts'

const MB = 1048576
const HERE = dirname(fileURLToPath(import.meta.url))
const PLUGIN_ROOT = resolve(HERE, '..', '..')
const WORKER = join(HERE, 'worker.ts')
// The skip reason of a text file over --max-large-mb (spec R8): a record of the findings file, counted in files_not_scanned.
const NOT_SCANNED = 'not-scanned-too-large'

// A fixed-text error of the scan: its message is shown to the user and never holds the text of a file.
class ScanError extends Error {
  override name = 'ScanError'
}

function fatal(message: string): never {
  process.stderr.write(`shield-scan: ${message}\n`)
  return process.exit(2)
}

// WHY these handlers write fixed text and never the error: an error message or stack can carry the text of a scanned file, which can be a secret. A stray error must still end the run with exit 2, and never with a partial findings file.
process.on('uncaughtException', () => fatal('the scan stopped on an internal error'))
process.on('unhandledRejection', () => fatal('the scan stopped on an internal error'))

interface Options {
  root: string
  all: boolean
  passes: Pass[]
  jobs: number
  out: string | null
  maxFileMb: number
  maxLargeMb: number
  timeoutBase: number
  timeoutPerMb: number
  redact: boolean
  minAgeMinutes: number
}

function parseArgs(argv: string[]): Options {
  const opts: Options = { root: '', all: false, passes: ['secrets', 'cards'], jobs: Math.max(1, Math.min(8, cpus().length - 1)), out: null, maxFileMb: 64, maxLargeMb: 1024, timeoutBase: 30, timeoutPerMb: 5, redact: false, minAgeMinutes: 10 }
  let rootArg: string | null = null
  const number = (flag: string, value: string | undefined, min: number, integer: boolean): number => {
    if (value === undefined) return fatal(`${flag} needs a value`)
    const parsed = Number(value)
    if (value.trim() === '' || !Number.isFinite(parsed) || parsed < min || (integer && !Number.isInteger(parsed))) return fatal(`${flag} is not a valid number`)
    return parsed
  }
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i]
    const value = argv[i + 1]
    switch (arg) {
      case '--all':
        opts.all = true
        break
      case '--passes': {
        if (value === undefined) return fatal('--passes needs a value')
        i++
        const wanted = new Set<Pass>()
        for (const name of value.split(',')) {
          if (!isPass(name)) return fatal('--passes holds a value that is not a pass (secrets, cards, email, home)')
          wanted.add(name)
        }
        opts.passes = PASS_ORDER.filter((pass) => wanted.has(pass))
        break
      }
      case '--jobs':
        opts.jobs = number(arg, value, 1, true)
        i++
        break
      case '--out':
        if (value === undefined) return fatal('--out needs a value')
        opts.out = value
        i++
        break
      case '--max-file-mb':
        opts.maxFileMb = number(arg, value, 0, false)
        i++
        break
      case '--max-large-mb':
        opts.maxLargeMb = number(arg, value, 0, false)
        i++
        break
      case '--file-timeout-base':
        opts.timeoutBase = number(arg, value, 0, false)
        i++
        break
      case '--file-timeout-per-mb':
        opts.timeoutPerMb = number(arg, value, 0, false)
        i++
        break
      case '--redact':
        opts.redact = true
        break
      case '--min-age-minutes':
        opts.minAgeMinutes = number(arg, value, 0, false)
        i++
        break
      default:
        if (arg.startsWith('-') || rootArg !== null) return fatal('unknown option or extra argument')
        rootArg = arg
    }
  }
  // WHY the large limit is checked here: a limit below the ordinary one would make the large lane smaller than the ordinary lane. It matters only with --redact, the only run that has a large lane.
  if (opts.redact && opts.maxLargeMb < opts.maxFileMb) return fatal('--max-large-mb must be at least --max-file-mb')
  try {
    opts.root = realpathSync(resolve(rootArg ?? process.cwd()))
    if (!statSync(opts.root).isDirectory()) return fatal('the root is not a directory')
  } catch {
    return fatal('the root cannot be read')
  }
  return opts
}

const pad = (n: number, width = 2): string => String(n).padStart(width, '0')

// <YYYYmmdd_HHMMSS+zzzz>, local time with the offset, like the report names of this project.
function stamp(now: Date): string {
  const offset = -now.getTimezoneOffset()
  const sign = offset < 0 ? '-' : '+'
  const abs = Math.abs(offset)
  return `${now.getFullYear()}${pad(now.getMonth() + 1)}${pad(now.getDate())}_${pad(now.getHours())}${pad(now.getMinutes())}${pad(now.getSeconds())}${sign}${pad(Math.floor(abs / 60))}${pad(abs % 60)}`
}

// WHY the walk up from the folder and a check for a `.git` entry: it uses the file set's .git probe (a directory, or a file in a linked worktree), it needs no git process, and it runs before any folder is created. A findings file in a work tree could be committed, which would publish where the secrets are. The file set reads an unreadable .git entry as a repo; this check does not (see below).
function insideWorkTree(outFile: string): boolean {
  let base = dirname(outFile)
  const tail: string[] = []
  while (!existsSync(base)) {
    tail.unshift(basename(base))
    base = dirname(base)
  }
  try {
    const top = findGitTop(join(realpathSync(base), ...tail))
    // WHY an unreadable .git entry stops the run here and does not count as a work tree: the file set reads it as a repo (so git fails visibly), but the findings-path check must not guess; the answer is exit 2, never a wrong yes or no.
    if (top !== null && !top.readable) return fatal('a folder on the findings path cannot be checked')
    return top !== null
  } catch {
    return fatal('a folder on the findings path cannot be checked')
  }
}

// sha256 over the files of the shield core (hooks/secret-shield/*.ts and rules/*.ts) in sorted order of relative path; per file: the relative path, a NUL byte, the bytes, a NUL byte.
function coreSha256(): string {
  const core = join(PLUGIN_ROOT, 'hooks', 'secret-shield')
  const rels = [...readdirSync(core).filter((name) => name.endsWith('.ts')), ...readdirSync(join(core, 'rules')).filter((name) => name.endsWith('.ts')).map((name) => `rules/${name}`)]
  rels.sort((a, b) => Buffer.compare(Buffer.from(a), Buffer.from(b)))
  const hash = createHash('sha256')
  for (const rel of rels) {
    hash.update(rel)
    hash.update('\0')
    hash.update(readFileSync(join(core, rel)))
    hash.update('\0')
  }
  return hash.digest('hex')
}

function pluginVersion(): string {
  // WHY the environment variable is read first: a copy of scan.ts vendored byte-identical into another repo has no .claude-plugin/plugin.json under its PLUGIN_ROOT, so the manifest read alone exits 2 on every scan; that caller sets SHIELD_SCAN_VERSION instead. The value goes verbatim into the summary JSON, so a set value that is empty, longer than 64 characters, or contains whitespace or a control character fails fast, with no fallback to plugin.json.
  // WHY the name has no SECRET in it: the CPV skillaudit rule CRED_ENV_READ matches env names that contain SECRET, so the former name SECRETS_SHIELD_SCAN_VERSION blocked the publish gate although this is a plain version string.
  const override = process.env.SHIELD_SCAN_VERSION
  if (override !== undefined) {
    if (override === '' || override.length > 64 || /[\s\p{Cc}]/u.test(override)) throw new ScanError('SHIELD_SCAN_VERSION is set but empty or malformed')
    return override
  }
  const version = (JSON.parse(readFileSync(join(PLUGIN_ROOT, '.claude-plugin', 'plugin.json'), 'utf8')) as { version?: unknown }).version
  if (typeof version !== 'string') throw new ScanError('plugin.json holds no version')
  return version
}

type Hits = Record<string, number>
type LineHit = [string, number, number]
type Message = { t: 'ready' } | { t: 'skip'; reason: 'binary' | 'read-error' } | { t: 'whole'; bytes: number; hits: Hits; jsonlNotJson?: number } | { t: 'lines'; hits: LineHit[] } | RedactReply

// One child bun process running worker.ts. A message is read with next(); null means the process has exited.
class WorkerProc {
  private readonly child: ChildProcessByStdio<Writable, Readable, null>
  private buffer = ''
  private readonly queue: Message[] = []
  private waiter: ((message: Message | null) => void) | null = null
  private exited = false

  private constructor() {
    // WHY stderr is ignored: a stack trace of the worker prints source text, which can be a secret; a crash is recorded as a crash skip.
    this.child = spawn(process.execPath, [WORKER], { stdio: ['pipe', 'pipe', 'ignore'] })
    this.child.stdout.setEncoding('utf8')
    this.child.stdout.on('data', (chunk: string) => {
      this.buffer += chunk
      for (let end = this.buffer.indexOf('\n'); end >= 0; end = this.buffer.indexOf('\n')) {
        const line = this.buffer.slice(0, end)
        this.buffer = this.buffer.slice(end + 1)
        try {
          this.deliver(JSON.parse(line) as Message)
        } catch {
          this.kill()
        }
      }
    })
    // WHY the stdin error handler does nothing: a write to a worker that just died raises EPIPE here; the close event below reports the death, and the run records it as a crash.
    this.child.stdin.on('error', () => {})
    const markExited = (): void => {
      this.exited = true
      this.waiter?.(null)
      this.waiter = null
    }
    this.child.on('close', markExited)
    // WHY an error listener: a worker that cannot be started (no executable, no memory) raises error and may never raise close; without this the run would wait for its ready message forever. start() then throws, and the run exits 2.
    this.child.on('error', markExited)
  }

  static async start(): Promise<WorkerProc> {
    const worker = new WorkerProc()
    const first = await worker.next()
    if (first === null || first.t !== 'ready') throw new ScanError('a worker process did not start')
    return worker
  }

  private deliver(message: Message): void {
    if (this.waiter !== null) {
      const waiter = this.waiter
      this.waiter = null
      waiter(message)
    } else this.queue.push(message)
  }

  next(): Promise<Message | null> {
    const queued = this.queue.shift()
    if (queued !== undefined) return Promise.resolve(queued)
    if (this.exited) return Promise.resolve(null)
    return new Promise((done) => {
      this.waiter = done
    })
  }

  send(job: { path: string; passes: Pass[]; redact: RedactJob | null }): void {
    this.child.stdin.write(JSON.stringify(job) + '\n')
  }

  kill(): void {
    this.child.kill('SIGKILL')
  }

  close(): void {
    this.child.stdin.end()
  }
}

type Outcome =
  | { kind: 'scanned'; bytes: number; notJson: number; whole: Hits; lines: LineHit[]; redact: RedactReply | null }
  | { kind: 'locate-timeout'; bytes: number; notJson: number; whole: Hits }
  | { kind: 'skip'; reason: 'binary' | 'read-error' }
  | { kind: 'timeout' }
  | { kind: 'crash' }

const sumOf = (hits: Hits): number => Object.values(hits).reduce((sum, n) => sum + n, 0)

// One file through one worker, under one timer armed when the job is sent (the worker is already running). Whole-file reply by the limit and no line reply: the file keeps its whole-file counts, unlocated. No whole-file reply: a timeout skip. Either kill ends the worker. With redact, the worker's last reply (written or why not) is part of the same limit: a kill before it is a timeout skip, and a vault failure ends the run with exit 2.
async function runFile(worker: WorkerProc, item: FileItem, passes: Pass[], limitMs: number, redactJob: RedactJob | null): Promise<Outcome> {
  let timedOut = false
  const timer = setTimeout(() => {
    timedOut = true
    worker.kill()
  }, limitMs)
  try {
    worker.send({ path: item.abs, passes, redact: redactJob })
    const first = await worker.next()
    if (timedOut) return { kind: 'timeout' }
    if (first === null) return { kind: 'crash' }
    if (first.t === 'skip') return { kind: 'skip', reason: first.reason }
    if (first.t !== 'whole') return { kind: 'crash' }
    if (sumOf(first.hits) === 0) return { kind: 'scanned', bytes: first.bytes, notJson: first.jsonlNotJson ?? 0, whole: first.hits, lines: [], redact: null }
    const second = await worker.next()
    if (timedOut) return { kind: 'locate-timeout', bytes: first.bytes, notJson: first.jsonlNotJson ?? 0, whole: first.hits }
    if (second === null || second.t !== 'lines') return { kind: 'crash' }
    if (redactJob === null) return { kind: 'scanned', bytes: first.bytes, notJson: first.jsonlNotJson ?? 0, whole: first.hits, lines: second.hits, redact: null }
    const third = await worker.next()
    if (timedOut) return { kind: 'timeout' }
    if (third === null || third.t !== 'redact') return { kind: 'crash' }
    // WHY the run ends here: the vault is the one place the values can be restored from, so a file is never written without it, and every later file would fail the same way. The message is fixed text.
    if (third.outcome === 'vault-error') throw new ScanError(third.message)
    return { kind: 'scanned', bytes: first.bytes, notJson: first.jsonlNotJson ?? 0, whole: first.hits, lines: second.hits, redact: third }
  } finally {
    clearTimeout(timer)
  }
}

interface Finding {
  path: string
  kind: string
  line: number | null
  count: number
}

const utf8Compare = (a: string, b: string): number => Buffer.compare(Buffer.from(a), Buffer.from(b))

async function main(): Promise<{ code: number; stdout: string }> {
  const started = performance.now()
  const opts = parseArgs(process.argv.slice(2))
  if (spawnSync('git', ['--version'], { stdio: 'ignore' }).status !== 0) return fatal('git is not installed or not on PATH')
  // WHY both values are read here, after the arguments and the git check and before the findings file, the vault or any file is touched: a malformed SHIELD_SCAN_VERSION or an unreadable manifest must fail before a file is read or rewritten (a --redact run would otherwise rewrite files and only then exit 2 at the summary). A ScanError reaches the rejection handler at the end of this file, which prints its fixed text and exits 2.
  const version = pluginVersion()
  const coreHash = coreSha256()

  const outFile = resolve(opts.out ?? join(homedir(), '.secrets_shield', 'scans', `${basename(opts.root) || 'root'}-${stamp(new Date())}.jsonl`))
  if (insideWorkTree(outFile)) return fatal('the findings file would be inside a git work tree, where it could be committed; pass --out with a path outside any repo')
  mkdirSync(dirname(outFile), { recursive: true, mode: 0o700 })
  const realOut = join(realpathSync(dirname(outFile)), basename(outFile))
  const exclude = new Set([realOut, `${realOut}.tmp`])
  if (opts.redact) {
    // WHY the vault is opened once here, before any worker starts: an unusable vault ends the run with exit 2 before any file is touched (fail fast). The race of several workers opening a new vault at once is mitigated by a retry in openVault (vault.ts retryBusy), not here; its cause was never isolated.
    const { openVault, VaultError } = await import('./vault.ts')
    try {
      openVault().close()
    } catch (error) {
      return fatal(error instanceof VaultError ? error.message : 'the vault could not be opened')
    }
  }

  const stats: SetStats = newStats()
  // WHY the large lane exists only with --redact: a scan keeps its over-size skip (it reads every file whole within the limit); the owner's case is redacting huge text files (spec R8). largeBytes null means no lane.
  const setOptions = { root: opts.root, all: opts.all, maxBytes: Math.floor(opts.maxFileMb * MB), largeBytes: opts.redact ? Math.floor(opts.maxLargeMb * MB) : null, exclude }
  const files = walkFiles(setOptions, stats)
  const findings: Finding[] = []
  let filesScanned = 0
  let bytesScanned = 0
  let filesWithFindings = 0
  let jsonlLinesNotJson = 0
  let unlocatedTimeout = 0
  let filesRedacted = 0
  let valuesVaulted = 0
  let findingsNotRedacted = 0
  const writeSkipped = {} as Record<WriteSkipReason, number>
  for (const reason of WRITE_SKIP_REASONS) writeSkipped[reason] = 0
  const writeSkipRecords: Array<{ path: string; reason: WriteSkipReason }> = []
  let residualTotal = 0
  const residualRecords: Array<{ path: string; kind: string; count: number }> = []
  let filesNotScanned = 0
  const notScannedPaths: string[] = []
  let largeLaneFiles = 0
  let homeRewrites = 0
  let roundsUsedMax = 0

  const account = (item: FileItem, outcome: Outcome): void => {
    if (outcome.kind === 'skip') return noteSkip(stats, opts.root, item.abs, outcome.reason)
    if (outcome.kind === 'timeout' || outcome.kind === 'crash') return noteSkip(stats, opts.root, item.abs, outcome.kind)
    filesScanned++
    bytesScanned += outcome.bytes
    jsonlLinesNotJson += outcome.notJson
    const before = findings.length
    const located: Hits = {}
    if (outcome.kind === 'scanned') {
      for (const [kind, line, count] of outcome.lines) {
        findings.push({ path: item.rel, kind, line, count })
        located[kind] = (located[kind] ?? 0) + count
      }
    } else unlocatedTimeout++
    // Per kind, what the whole-file result holds beyond the per-line counts has no line: a hit that only a window of several lines forms, or (after a locate kill) everything.
    for (const [kind, count] of Object.entries(outcome.whole)) {
      const extra = count - (located[kind] ?? 0)
      if (extra > 0) findings.push({ path: item.rel, kind, line: null, count: extra })
    }
    if (findings.length > before) filesWithFindings++
    if (!opts.redact) return
    // WHY a file with findings and no written reply counts as not redacted whatever the cause (a skip, a timeout before the write, a locate kill): the count is derived here, from what the worker confirmed, and never from a list of causes.
    // WHY the home hits are left out of the not-redacted count: the home pass is opt-in, writes no marker and is not restorable (spec R1); a home path is reported as a finding of kind home and rewritten last, it is not a secret left in the file. A file whose only hits are home paths still gets its reply (written or why not).
    if (sumOf(outcome.whole) === 0) return
    const found = sumOf(outcome.whole) - (outcome.whole[HOME_KIND] ?? 0)
    const reply = outcome.kind === 'scanned' ? outcome.redact : null
    if (reply?.outcome === 'written') {
      filesRedacted++
      valuesVaulted += reply.values
      homeRewrites += reply.homeRewrites
      roundsUsedMax = Math.max(roundsUsedMax, reply.rounds)
      // WHY a residual is counted only for a written file: the worker runs the re-scan on the final text, and a file that was not written is already counted in findings_not_redacted.
      for (const [kind, count] of Object.entries(reply.residual)) {
        residualTotal += count
        residualRecords.push({ path: item.rel, kind, count })
      }
      return
    }
    findingsNotRedacted += found
    if (reply?.outcome === 'skip') {
      writeSkipped[reply.reason]++
      writeSkipRecords.push({ path: item.rel, reason: reply.reason })
    }
  }

  // Each slot owns one worker process at a time and pulls the next file from the shared walk; a killed or crashed worker is replaced when the next file arrives.
  // WHY the large lane is one dedicated worker that the slots feed through a queue, and not a lock the slots wait on: the worker holds the whole file several times over (the buffer, the decoded string and the redacted copy), so several large files at once could exhaust the host memory (it froze once, spec R8). A queue lets the ordinary slots keep going while a large file runs; with a lock, slots that picked a large file would sit idle.
  const largeQueue: FileItem[] = []
  let walkDone = false
  let wakeLane: (() => void) | null = null
  const runLimitMs = (item: FileItem): number => (opts.timeoutBase + opts.timeoutPerMb * (item.size / MB)) * 1000
  const redactJob = (): RedactJob | null => (opts.redact ? { minAgeMs: opts.minAgeMinutes * 60_000, root: opts.root } : null)
  const slot = async (): Promise<void> => {
    let worker: WorkerProc | null = null
    for (let next = await files.next(); next.done !== true; next = await files.next()) {
      const item = next.value
      if (item.lane === 'too-large') {
        // Neither scanned nor redacted: reported, and the run is incomplete.
        filesNotScanned++
        notScannedPaths.push(item.rel)
        continue
      }
      if (item.lane === 'large') {
        largeQueue.push(item)
        wakeLane?.()
        wakeLane = null
        continue
      }
      worker ??= await WorkerProc.start()
      const outcome = await runFile(worker, item, opts.passes, runLimitMs(item), redactJob())
      account(item, outcome)
      if (outcome.kind === 'timeout' || outcome.kind === 'crash' || outcome.kind === 'locate-timeout') worker = null
    }
    worker?.close()
  }
  // The large lane: its worker starts on the first large file and the lane ends when the walk is done and the queue is empty. Nothing awaits between the queue check and the wait below, so a wake-up cannot be lost.
  const lane = async (): Promise<void> => {
    let worker: WorkerProc | null = null
    for (;;) {
      const item = largeQueue.shift()
      if (item === undefined) {
        if (walkDone) break
        await new Promise<void>((resolve) => {
          wakeLane = resolve
        })
        continue
      }
      worker ??= await WorkerProc.start()
      largeLaneFiles++
      const outcome = await runFile(worker, item, opts.passes, runLimitMs(item), redactJob())
      account(item, outcome)
      if (outcome.kind === 'timeout' || outcome.kind === 'crash' || outcome.kind === 'locate-timeout') worker = null
    }
    worker?.close()
  }
  const slotsDone = Promise.all(Array.from({ length: opts.jobs }, () => slot())).then(() => {
    walkDone = true
    wakeLane?.()
    wakeLane = null
  })
  await Promise.all([slotsDone, lane()])

  // Canonical order: path in UTF-8 byte order, findings before skips before residual records, line ascending with null last, then kind.
  const rows: Array<{ path: string; rank: number; line: number; kind: string; json: string }> = []
  for (const f of findings) rows.push({ path: f.path, rank: 0, line: f.line ?? Number.POSITIVE_INFINITY, kind: f.kind, json: JSON.stringify({ type: 'finding', path: f.path, kind: f.kind, line: f.line, count: f.count }) })
  for (const s of stats.skipRecords) rows.push({ path: s.path, rank: 1, line: 0, kind: s.reason, json: JSON.stringify({ type: 'skip', path: s.path, reason: s.reason }) })
  for (const s of writeSkipRecords) rows.push({ path: s.path, rank: 1, line: 0, kind: s.reason, json: JSON.stringify({ type: 'skip', path: s.path, reason: s.reason }) })
  for (const path of notScannedPaths) rows.push({ path, rank: 1, line: 0, kind: NOT_SCANNED, json: JSON.stringify({ type: 'skip', path, reason: NOT_SCANNED }) })
  for (const r of residualRecords) rows.push({ path: r.path, rank: 2, line: 0, kind: r.kind, json: JSON.stringify({ type: 'residual', path: r.path, kind: r.kind, count: r.count }) })
  rows.sort((a, b) => utf8Compare(a.path, b.path) || a.rank - b.rank || (a.line === b.line ? 0 : a.line < b.line ? -1 : 1) || utf8Compare(a.kind, b.kind))

  // WHY files not scanned make the run incomplete: a text file over --max-large-mb was neither scanned nor redacted, so the run cannot say the tree is clean.
  const incomplete = filesNotScanned > 0 || (['timeout', 'read-error', 'crash', 'git-error', 'unreadable-dir'] as SkipReason[]).some((reason) => stats.skipped[reason] > 0)
  const elapsed = (performance.now() - started) / 1000
  const skipped: Record<string, number> = {}
  for (const reason of SKIP_REASONS) skipped[reason] = stats.skipped[reason]
  if (opts.redact) for (const reason of WRITE_SKIP_REASONS) skipped[reason] = writeSkipped[reason]
  const total = findings.reduce((sum, f) => sum + f.count, 0)
  const summary = JSON.stringify({
    type: 'summary',
    plugin_version: version,
    core_sha256: coreHash,
    passes: opts.passes,
    scope: opts.all ? 'all' : 'default',
    repos: stats.repos,
    non_repo_dirs: stats.nonRepoDirs,
    ancestor_rules_skipped: stats.ancestorRulesSkipped,
    files_scanned: filesScanned,
    bytes_scanned: bytesScanned,
    skipped,
    gitignored_entries: stats.gitignoredEntries,
    ignored_repos: stats.ignoredRepos,
    findings: total,
    files_with_findings: filesWithFindings,
    // WHY in both modes: a .jsonl or .ndjson file whose lines are not JSON is read as text, and the report must say so; it is the number of such non-blank lines over all JSONL files read (jsonl.ts).
    jsonl_lines_not_json: jsonlLinesNotJson,
    unlocated_timeout: unlocatedTimeout,
    complete: !incomplete,
    elapsed_s: Math.round(elapsed * 1000) / 1000,
    mb_per_s: elapsed > 0 ? Math.round((bytesScanned / MB / elapsed) * 100) / 100 : 0,
    jobs: opts.jobs,
    // WHY residual is the total the re-scan found in the files that were written; residual_check says the re-scan ran (it never runs without --redact).
    ...(opts.redact ? { redact: true, min_age_minutes: opts.minAgeMinutes, files_redacted: filesRedacted, values_vaulted: valuesVaulted, findings_not_redacted: findingsNotRedacted, residual: residualTotal, residual_check: 'run', rounds_used_max: roundsUsedMax, files_not_scanned: filesNotScanned, large_lane_files: largeLaneFiles, home_rewrites: homeRewrites } : {}),
  })
  // The findings file is private to its owner (it says where the secrets are) and is renamed into place, so a reader never sees a half-written one.
  writeFileSync(`${realOut}.tmp`, [...rows.map((row) => row.json), summary].join('\n') + '\n', { mode: 0o600 })
  renameSync(`${realOut}.tmp`, realOut)
  // With --redact the exit code is about what is left unredacted: findings in files that were not written (a write skip reason, or a locate kill before the write) or a residual hit in a file that was written give 1; a timeout is a skip that makes the run incomplete (3).
  const code = incomplete ? 3 : (opts.redact ? findingsNotRedacted + residualTotal : total) > 0 ? 1 : 0
  return { code, stdout: `${summary}\n${realOut}\n` }
}

main().then(
  ({ code, stdout }) => {
    process.stdout.write(stdout, () => process.exit(code))
  },
  (error: unknown) => {
    // Only the fixed messages of this file are shown: any other error text could carry the text of a scanned file.
    return fatal(error instanceof ScanError ? error.message : 'the scan stopped on an internal error')
  },
)
