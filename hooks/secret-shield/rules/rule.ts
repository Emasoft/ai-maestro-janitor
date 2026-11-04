// The shape of one token rule. Its own module so the rule files and patterns.ts can both import it
// without the rule files importing patterns.ts, which imports them.

// Every pattern is a shared /g RegExp. Callers must never run one directly: .test() or .exec() keeps state in its
// lastIndex, and the next such call starts mid-text and misses a match. Go through redact() in patterns.ts, which
// applies each pattern with String.prototype.replace (that resets lastIndex), or read TOKEN_ORDER for the rule data.
export type Rule = {
  kind: string
  pattern: RegExp
  /** Which capture group is the secret; 0 (the default) is the whole match. */
  group?: number
}
