// Code host tokens. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const githubTokenClassic: Rule = { kind: 'github-token', pattern: /\b(gh[pousr]_[A-Za-z0-9]{36,255})\b/g, group: 1 }
export const githubTokenFineGrained: Rule = { kind: 'github-token', pattern: /\b(github_pat_[A-Za-z0-9_]{22,255})\b/g, group: 1 }
