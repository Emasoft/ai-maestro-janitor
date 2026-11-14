// expected-rows: 13
// WHY named .load.ts: `claude plugin test` collects only *.test.ts and *.test.tsx, so the release gate never runs this probe; the load harness of TRDD-OD5Z90YL
// copies it to probe.test.ts inside its temp assembly. The header above counts the test() rows the cases array generates (13), the harness checks it.
import { describe, expect, test } from 'claude-code/testing'

import { applyRule, JSON_ESCAPED, redact } from '../../patterns'
import { jwt } from '../../rules/key-material'
import { oldJwt, oldJsonEscaped, urlV1, urlV2, urlV3 } from './old-quadratic'
import { LIMIT_FACTOR, measureLinear, replay } from './timing'

const KB = 1024
const MB = 1024 * KB
const rep = (unit: string, length: number) => unit.repeat(Math.ceil(length / unit.length)).slice(0, length)
const tail = '\n' + 'https://admin:' + 'Zq8' + 'vR2m' + '@db.example'
const grown = (size: number) => 'b://u:1?'.repeat(size / 16) + 'x'.repeat(size / 2)
const jwtRun = (n: number) => 'eyJ-'.repeat(n / 4).slice(0, n - 2) + '.x'
const jsonNow = (text: string): string => text.replace(new RegExp(JSON_ESCAPED.source, JSON_ESCAPED.flags), (match) => match)
const slashes = (n: number) => '\\'.repeat(n)
const pairs = (n: number) => `"${'\\\\'.repeat(n / 2)}`
const realPairs = (n: number) => rep('{\\"api_key\\":\\"Zq8mK3vT9xLw2RbN5yHc\\"} ', n)
const len = (f: (t: string) => string) => (t: string): number => f(t).length

// A deliberately modest quadratic: W units of linear work per character plus n*n/D units of quadratic work, with D chosen so that at 32 KB the quadratic part
// equals the linear part. At the 8x step the nominal ratio is (8 + 64) / 2 = 36, between linear (8) and quadratic (64); measured idle it is lower (JIT).
const W = 20
const D = Math.round(32768 / (1.0 * W))
const modest = (text: string): number => {
  const n = text.length
  let acc = 0
  for (let i = 0; i < n; i++) for (let k = 0; k < W; k++) acc = (acc + text.charCodeAt(i) + k) | 0
  const q = Math.floor((n * n) / D)
  for (let j = 0; j < q; j++) acc = (acc + (j & 7)) | 0
  return acc
}
const flat = (n: number) => 'a'.repeat(n)

type Case = { id: string; expectLinear: boolean; run: (text: string) => number; make: (size: number) => string; small: number; big: number }
const cases: Case[] = [
  { id: 'L1 jwt applyRule eyJ-x.x 32-256K', expectLinear: true, run: len((t) => applyRule(t, jwt, {})), make: jwtRun, small: 32 * KB, big: 256 * KB },
  { id: 'L1c jwt applyRule 512K-4M', expectLinear: true, run: len((t) => applyRule(t, jwt, {})), make: jwtRun, small: 512 * KB, big: 4 * MB },
  { id: 'L2d JSON_ESCAPED real pairs 32-256K', expectLinear: true, run: len(jsonNow), make: realPairs, small: 32 * KB, big: 256 * KB },
  { id: 'L3 :661 redact grown+tail 32-256K', expectLinear: true, run: (t) => redact(t).text.length, make: (n) => grown(n) + tail, small: 32 * KB, big: 256 * KB },
  { id: 'L3b redact grown 32-256K', expectLinear: true, run: (t) => redact(t).text.length, make: grown, small: 32 * KB, big: 256 * KB },
  { id: 'L3c redact https://+A1- 32-256K', expectLinear: true, run: (t) => redact(t).text.length, make: (n) => 'https://' + rep('A1-', n), small: 32 * KB, big: 256 * KB },
  { id: 'Q1 old jwt eyJ-x.x 4-32K', expectLinear: false, run: len((t) => applyRule(t, oldJwt, {})), make: jwtRun, small: 4 * KB, big: 32 * KB },
  { id: 'Q2 old JSON_ESCAPED backslashes 1-8K', expectLinear: false, run: len(oldJsonEscaped), make: slashes, small: 1 * KB, big: 8 * KB },
  { id: 'Q2b old JSON_ESCAPED quote+pairs 1-8K', expectLinear: false, run: len(oldJsonEscaped), make: pairs, small: 1 * KB, big: 8 * KB },
  { id: 'Q3 :661 V3 grown+tail 32-256K', expectLinear: false, run: len(urlV3), make: (n) => grown(n) + tail, small: 32 * KB, big: 256 * KB },
  { id: 'Q4 :661 V2 grown+tail 4-32K', expectLinear: false, run: len(urlV2), make: (n) => grown(n) + tail, small: 4 * KB, big: 32 * KB },
  { id: 'Q5 V1 https://+A1- 2-16K', expectLinear: false, run: len(urlV1), make: (n) => 'https://' + rep('A1-', n), small: 2 * KB, big: 16 * KB },
  { id: 'Q6 modest quadratic (measured ratio 27) 32-256K', expectLinear: false, run: modest, make: flat, small: 32 * KB, big: 256 * KB },
]

// The ORIGINAL design, verbatim: sequential small then big, rounds of 5, cap 3, pass at the first round under 12 or when big is under 2 ms.
const origOnce = (run: (t: string) => number, text: string): number => {
  const started = performance.now()
  run(text)
  return performance.now() - started
}
const orig = (run: (t: string) => number, make: (n: number) => string, smallSize: number, bigSize: number) => {
  const limit = (bigSize / smallSize) * 1.5
  const smallText = make(smallSize)
  const bigText = make(bigSize)
  run(smallText)
  run(bigText)
  let small = Infinity
  let big = Infinity
  for (let round = 1; round <= 3; round++) {
    for (let i = 0; i < 5; i++) {
      small = Math.min(small, origOnce(run, smallText))
      big = Math.min(big, origOnce(run, bigText))
    }
    const escaped = big < 2
    if (escaped || big / small < limit) return { small, big, ratio: big / small, rounds: round, escaped, linear: true }
  }
  return { small, big, ratio: big / small, rounds: 3, escaped: false, linear: false }
}

describe('estimator probe', () => {
  for (const c of cases) {
    test(c.id, { timeoutMs: 600000 }, () => {
      const o = orig(c.run, c.make, c.small, c.big)
      const t = measureLinear(c.run, c.make, c.small, c.big, { stopEarly: false })
      const step = t.bigSize / t.smallSize
      const f15 = replay(t.trajectory, step, 1.5)
      const fx = replay(t.trajectory, step, LIMIT_FACTOR)
      const traj = t.trajectory.map((r) => `${r.small.toFixed(3)}/${r.big.toFixed(3)}`).join(',')
      console.log(
        `RES|${c.id}|expect=${c.expectLinear}|orig=${JSON.stringify(o)}|sizes=${t.smallSize}-${t.bigSize}|f1.5=${f15.verdict}@${f15.round}|f${LIMIT_FACTOR}=${fx.verdict}@${fx.round}|small=${t.small.toFixed(3)}|big=${t.big.toFixed(3)}|ratio=${t.ratio.toFixed(2)}|sink=${t.sink}|traj=${traj}`,
      )
      // WHY a REDOS-ROW line per row (TRDD-OD5Z90YL, design/specs/redos-load-harness-d8.md): the runner prints only (pass) or (fail) per test, and the harness must tell a linear row that ran out of rounds
      // or came out superlinear, and a mutant that ran out of rounds (undecided, not a detection), apart. Console output of passing and failing tests reaches the runner's output (measured), before the
      // file header; the plugin test sandbox offers no file access, so console output is the only channel. Printed before the assert so a failing row still reports its verdict.
      console.log(`REDOS-ROW ${c.id.split(' ')[0]} ${c.expectLinear ? 'linear' : 'mutant'} ${fx.verdict}`)
      if (c.expectLinear) expect(fx.verdict).toBe('linear')
      else expect(['superlinear', 'escaped']).toContain(fx.verdict)
    })
  }
})
