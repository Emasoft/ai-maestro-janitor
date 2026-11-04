// Cloud provider credentials. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const awsAccessKey: Rule = { kind: 'aws-access-key', pattern: /\b((?:AKIA|ASIA)[A-Z0-9]{16})\b/g, group: 1 }
export const awsSecretKeyAssignment: Rule = { kind: 'aws-secret-key', pattern: /\b(?:aws_?secret_?(?:access_?)?key|secret_?access_?key)["']?\s*[=:]\s*["']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])/gi, group: 1 }
export const awsSecretKeyJson: Rule = { kind: 'aws-secret-key', pattern: /"SecretAccessKey"\s*:\s*"([A-Za-z0-9/+=]{40})"/g, group: 1 }
export const awsSessionToken: Rule = { kind: 'aws-session-token', pattern: /"SessionToken"\s*:\s*"([A-Za-z0-9/+=]{100,})"/g, group: 1 }
export const googleApiKey: Rule = { kind: 'google-api-key', pattern: /\b(AIza[0-9A-Za-z_-]{35})(?![0-9A-Za-z_-])/g, group: 1 }
