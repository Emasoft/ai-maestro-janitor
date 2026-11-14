// Super-linear-time check for a text-scanning function (quadratic or worse is the scope; a mild slowdown is not). The verdict rests on a RATIO of two
// timings of the same machine, never an absolute duration, so machine speed cancels out: growing the text by `step` costs about `step` times as long when
// the scan is linear and about step * step as long when it is quadratic (8 and 64 at the 8x step).
// Load makes single timings jump, but noise only ever ADDS time to a run, so the minimum of many runs of one size converges down to its true cost. The two
// sizes are sampled interleaved, in alternating order inside each pair (the run after a big one pays its garbage-collection debt, so a fixed order would
// bias one size), and the minimum of each is kept across rounds. A wrong "linear" verdict for a quadratic scan is UNLIKELY, not impossible: it needs the big
// minimum to reach its true cost while the small minimum stays inflated, so two protections apply: the verdict is "linear" only when the ratio is under
// the limit in two consecutive rounds, or when the small minimum did not move in the round that brought the ratio under the limit.
// "escaped" is a distinct verdict, never a pass: a big run under ESCAPE_MS is too fast to time. The sizes are grown by `step` while the big run is under
// ESCAPE_MS, up to SIZE_CAP; a row still under ESCAPE_MS there proves nothing and the caller must assert it false.
export const RUNS_PER_ROUND = 5
// The round cap. A quadratic scan always uses all of them, so the test that calls this needs an explicit timeoutMs (Bun's default is 5000 ms).
export const ROUNDS = 10
export const ESCAPE_MS = 2
export const SIZE_CAP = 16 * 1024 * 1024
// The growth precheck samples the big text up to this many times and grows the sizes as soon as ONE run is under ESCAPE_MS: noise only adds time, so a single fast run
// proves the true cost is that low. Growth stops only when all of them are at or above ESCAPE_MS (a minimum of 3 was fooled under load by a 0.4 ms scan).
export const GROWTH_SAMPLES = 10
// The limit is step * LIMIT_FACTOR. The geometric midpoint of linear (step) and quadratic (step * step) is step * sqrt(step), 2.83 at 8x; linear code
// reached a ratio of 10.5 (1.3 * step) at a load average of 125, and the 1.5 of TRDD-Q6LPJTPO's single-shot rule (12 at 8x) is too tight for that.
export const LIMIT_FACTOR = 2.6

export type Verdict = 'linear' | 'superlinear' | 'escaped'
export type Round = { small: number; big: number }
export type Timing = { verdict: Verdict; small: number; big: number; ratio: number; rounds: number; smallSize: number; bigSize: number; trajectory: Round[]; sink: number }

// The decision made after the last round of `trajectory`, or undefined when more rounds are needed. Minima in the trajectory are cumulative.
export const judge = (trajectory: Round[], step: number, factor: number): Verdict | undefined => {
  const last = trajectory[trajectory.length - 1]
  if (last.big < ESCAPE_MS) return 'escaped'
  const limit = step * factor
  if (last.big / last.small >= limit || trajectory.length < 2) return undefined
  const before = trajectory[trajectory.length - 2]
  return before.big / before.small < limit || before.small === last.small ? 'linear' : undefined
}

// Replays a whole trajectory under another factor, for comparing limits on the same samples.
export const replay = (trajectory: Round[], step: number, factor: number): { verdict: Verdict; round: number } => {
  for (let n = 1; n <= trajectory.length; n++) {
    const verdict = judge(trajectory.slice(0, n), step, factor)
    if (verdict !== undefined) return { verdict, round: n }
  }
  return { verdict: 'superlinear', round: trajectory.length }
}

// `run` returns a number (a length, a count) so the work cannot be discarded as unused; the sum of the results is returned as `sink`.
export const measureLinear = (
  run: (text: string) => number,
  make: (size: number) => string,
  smallSize: number,
  bigSize: number,
  options: { stopEarly?: boolean; factor?: number } = {},
): Timing => {
  const step = bigSize / smallSize
  const factor = options.factor ?? LIMIT_FACTOR
  let sink = 0
  const once = (text: string): number => {
    const started = performance.now()
    sink = (sink + run(text)) % 1e15
    return performance.now() - started
  }
  let smallText = make(smallSize)
  let bigText = make(bigSize)
  const grows = (): boolean => {
    for (let i = 0; i < GROWTH_SAMPLES; i++) if (once(bigText) < ESCAPE_MS) return true
    return false
  }
  once(smallText)
  once(bigText)
  while (grows() && bigSize * step <= SIZE_CAP) {
    smallSize = bigSize
    bigSize *= step
    smallText = bigText
    bigText = make(bigSize)
    once(smallText)
    once(bigText)
  }
  const trajectory: Round[] = []
  let small = Infinity
  let big = Infinity
  let verdict: Verdict | undefined
  for (let round = 1; round <= ROUNDS; round++) {
    for (let i = 0; i < RUNS_PER_ROUND; i++) {
      if ((i + round) % 2 === 0) {
        small = Math.min(small, once(smallText))
        big = Math.min(big, once(bigText))
      } else {
        big = Math.min(big, once(bigText))
        small = Math.min(small, once(smallText))
      }
    }
    trajectory.push({ small, big })
    const decided = judge(trajectory, step, factor)
    if (decided !== undefined && verdict === undefined) verdict = decided
    if (verdict !== undefined && options.stopEarly !== false) break
  }
  return { verdict: verdict ?? 'superlinear', small, big, ratio: big / small, rounds: trajectory.length, smallSize, bigSize, trajectory, sink }
}
