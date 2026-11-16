// Package registry and developer service tokens. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const npmToken: Rule = { kind: 'npm-token', pattern: /\b(npm_[A-Za-z0-9]{36})\b/g, group: 1 }
// Docker Hub personal and organization access tokens: a bare token in running text has no name for a context rule to key on.
export const dockerPat: Rule = { kind: 'docker-pat', pattern: /\b(dckr_(?:pat|oat)_[A-Za-z0-9_-]{20,})/g, group: 1 }
export const pypiToken: Rule = { kind: 'pypi-token', pattern: /\b(pypi-AgE[A-Za-z0-9_-]{50,})/g, group: 1 }
export const sendgridKey: Rule = { kind: 'sendgrid-key', pattern: /\b(SG\.[A-Za-z0-9_-]{22}\.[A-Za-z0-9_-]{43})(?![A-Za-z0-9_-])/g, group: 1 }
// Scoped npmrc lines (//host/:_authToken=value): registries issue tokens without the npm_ prefix, so the key name is the only signal. A `$` or `[` start keeps placeholders and an already-hidden value. [ \t] and not \s around the equals sign: an empty `_authToken=` line must not swallow the next line as its value. An optional opening quote is taken into the prefix group; the closing quote stays outside the value class so it is kept.
export const npmrcAuthToken: Rule = { kind: 'npmrc-auth-token', pattern: /(:_authToken[ \t]*=[ \t]*["']?)(?![$\[])([^\s'"#;]{16,})/g, group: 2 }
// Maven settings.xml <password>/<passphrase> values: plain element text has no assignment for the name-based rules to read. The lookahead keeps ${env.X} placeholders and an already-hidden value.
export const xmlPassword: Rule = { kind: 'xml-password', pattern: /<(password|passphrase)>(?![$\[{])([^<\s]{6,})<\/\1>/gi, group: 2 }
