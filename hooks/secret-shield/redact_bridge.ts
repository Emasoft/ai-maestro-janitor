// Line-JSON bridge that lets the Python lanes call the secret-shield core (redact + redactHome) on text they are about to send to a remote model.
// WHY it exists (TRDD-TKQ274RE): the janitor sent session transcripts to remote models unredacted. The lanes are Python, the one redaction rule set is this TypeScript core, so the lanes reach it through this bridge and the rules cannot drift into a second copy. report-sanitizer may later vendor this file (its shield_bridge.ts is the same protocol over its own copy of the core).
// Protocol: one JSON request per stdin line, one JSON response per stdout line, in the same order.
//   {"t": s}                                   -> redact(s)
//   {"op": "home", "t": s, "homes": [...]}     -> redactHome(s, homes)
//   {"op": "both", "t": s, "homes": [...]}     -> redact(s) first, then redactHome on its output
//   {"op": "jsonl", "t": s, "homes": [...]}    -> redactJsonLine(s) first (a secret behind a JSON escape too; a line that is not JSON goes through redact), then redactHome on each decoded string of its output (on the whole text when it is not JSON); the line stays valid JSON when it was
//   {"op": "all", "t": s, "homes": [...], "passes": [...]} -> redactAll(s, homes, passes): every pass of the pipeline (pipeline.ts) in its own order; "passes" is optional (absent = all four) and, when present, a non-empty array of "secrets", "cards", "email", "home"
// Response {"t": <redacted text>, "h": {<kind>: <count>}}; for "both", "jsonl" and "all" the counts of the passes are merged.
// Any failure: ONE line {"error": "<fixed text>"}, exit 2. Nothing else is ever written to stdout.
//
// WHY the input is read as a byte stream and split on "\n" here, not with `for await (const line of console)`: one line is a whole transcript record, which can be several MB, and the line reader is not meant for that.
// WHY every error message is fixed text and never the exception own message: JSON.parse quotes a fragment of the input in its message, and that message could carry a secret to the caller. The caller must fail closed on an error line (TRDD-TKQ274RE: a skipped redaction sends secrets out).

import { redactHome } from "./home.ts"
import { addHits, mapJsonLineStrings, redact, redactJsonLine, type Hits } from "./patterns.ts"
import { ALL_PASSES, isPass, redactAll, type Pass } from "./pipeline.ts"

const decoder = new TextDecoder("utf-8")

const fail = async (message: string): Promise<never> => {
  await Bun.write(Bun.stdout, JSON.stringify({ error: message }) + "\n")
  process.exit(2)
}

const isJson = (text: string): boolean => {
  try {
    JSON.parse(text)
    return true
  } catch {
    return false
  }
}

const handle = async (line: string): Promise<void> => {
  let request: unknown
  try {
    request = JSON.parse(line)
  } catch {
    return fail("request line is not valid JSON")
  }
  const fields = request as { t?: unknown; op?: unknown; homes?: unknown; passes?: unknown } | null
  const text = fields?.t
  if (typeof text !== "string") return fail("request has no string field t")
  const op = fields?.op
  if (op !== undefined && op !== "home" && op !== "both" && op !== "jsonl" && op !== "all") return fail("unknown op")
  const homes = fields?.homes
  if (op !== undefined && !(Array.isArray(homes) && homes.every((h) => typeof h === "string"))) return fail("homes is not an array of strings")
  // passes belongs to op "all" only: the other ops take no pass set and ignore the field, as they always ignored unknown fields. An empty array is refused: it would return the text unredacted.
  const rawPasses = fields?.passes
  if (op === "all" && rawPasses !== undefined && !(Array.isArray(rawPasses) && rawPasses.length > 0 && rawPasses.every(isPass))) return fail("passes is not a non-empty array of passes")
  let out: string
  const hits: Hits = {}
  try {
    if (op === "all") {
      const passes = rawPasses === undefined ? ALL_PASSES : new Set<Pass>(rawPasses as Pass[])
      const r = redactAll(text, homes as string[], passes)
      out = r.text
      addHits(hits, r.hits)
    } else if (op === "home") {
      const r = redactHome(text, homes as string[])
      out = r.text
      addHits(hits, r.hits)
    } else if (op === "jsonl") {
      // WHY redactJsonLine first, then the home pass on each decoded string: redactJsonLine decodes the escapes of the line to find a secret hidden behind them, and a plain-text home rewrite of the raw line could change the escapes or the text around a secret before that pass reads it. The home pass reads each decoded string (mapJsonLineStrings), so a home written with an escaped slash or backslash cannot hide, and a home literal can never rewrite JSON syntax (a quote in it is a character of the string, not the end of it). A line that is not JSON keeps the plain-text home pass on the whole text. mapJsonLineStrings throws a fixed message if the line stops being JSON, and the catch below answers with a fixed text, never with the input.
      const secrets = redactJsonLine(text)
      out = secrets.text
      addHits(hits, secrets.hits)
      if (isJson(text)) {
        out = mapJsonLineStrings(out, (decoded) => {
          const home = redactHome(decoded, homes as string[])
          addHits(hits, home.hits)
          return home.text
        })
      } else {
        const home = redactHome(out, homes as string[])
        out = home.text
        addHits(hits, home.hits)
      }
    } else {
      const secrets = redact(text)
      out = secrets.text
      addHits(hits, secrets.hits)
      if (op === "both") {
        const home = redactHome(out, homes as string[])
        out = home.text
        addHits(hits, home.hits)
      }
    }
  } catch (e) {
    return fail("redaction threw " + (e instanceof Error ? e.name : "a non-error"))
  }
  await Bun.write(Bun.stdout, JSON.stringify({ t: out, h: hits }) + "\n")
}

let buffer = ""
let scanFrom = 0
for await (const chunk of Bun.stdin.stream()) {
  buffer += decoder.decode(chunk, { stream: true })
  for (let nl = buffer.indexOf("\n", scanFrom); nl !== -1; nl = buffer.indexOf("\n", scanFrom)) {
    await handle(buffer.slice(0, nl))
    buffer = buffer.slice(nl + 1)
    scanFrom = 0
  }
  scanFrom = buffer.length
}
buffer += decoder.decode()
if (buffer.length > 0) await handle(buffer)
