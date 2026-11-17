// Child process of the secrets-shield scan (TRDD-BAQB9SYO increment 1a): reads one file at a time and counts what the shield core finds in it.
// WHY a child process and not a thread or an in-process loop: the core passes are synchronous regexes, so a pathological file cannot be interrupted from inside its own thread; the driver (scan.ts) kills this process with SIGKILL at the per-file limit and starts a new one.
// Protocol, one JSON object per line. Driver to worker: {"path": <absolute path>, "passes": [<pass>, ...]}, one job at a time. Worker to driver:
//   {"t":"ready"}                                  once, after start-up (the driver arms no timer before it)
//   {"t":"skip","reason":"binary"|"read-error"}   the file was not scanned
//   {"t":"whole","bytes":n,"hits":{kind:count}}  the whole-file result; when it holds no hit the job ends here
//   {"t":"lines","hits":[[kind,line,count],...]} the per-line result of a file whose whole-file result holds a hit
// WHY no error text is ever written: a stack trace prints source text, and a scanned file can hold a secret. A failure exits the process; the driver records it as a crash.
// Nothing here writes a matched value: replies hold kinds, counts and line numbers only.

import { readFileSync } from 'node:fs'
import { homedir } from 'node:os'
import { countOf } from '../../hooks/secret-shield/patterns.ts'
import { isPass, redactAll, type Pass } from '../../hooks/secret-shield/pipeline.ts'

const BINARY_PROBE_BYTES = 8192
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

async function handle(line: string): Promise<void> {
  const job = JSON.parse(line) as { path: string; passes: string[] }
  const passes = new Set<Pass>()
  for (const pass of job.passes) {
    if (!isPass(pass)) throw new Error('worker: not a pass')
    passes.add(pass)
  }
  let data: Buffer
  try {
    data = readFileSync(job.path)
  } catch {
    await send({ t: 'skip', reason: 'read-error' })
    return
  }
  if (data.subarray(0, BINARY_PROBE_BYTES).includes(0)) {
    await send({ t: 'skip', reason: 'binary' })
    return
  }
  const text = decoder.decode(data)
  const whole = redactAll(text, homes, passes).hits
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
