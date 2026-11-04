// Package registry and developer service tokens. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const npmToken: Rule = { kind: 'npm-token', pattern: /\b(npm_[A-Za-z0-9]{36})\b/g, group: 1 }
export const pypiToken: Rule = { kind: 'pypi-token', pattern: /\b(pypi-AgE[A-Za-z0-9_-]{50,})/g, group: 1 }
export const sendgridKey: Rule = { kind: 'sendgrid-key', pattern: /\b(SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43})(?![A-Za-z0-9_-])/g, group: 1 }
