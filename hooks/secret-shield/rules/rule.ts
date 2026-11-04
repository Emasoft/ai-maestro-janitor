// The shape of one token rule. Its own module so the rule files and patterns.ts can both import it
// without the rule files importing patterns.ts, which imports them.

export type Rule = {
  kind: string
  pattern: RegExp
  /** Which capture group is the secret; 0 (the default) is the whole match. */
  group?: number
}
