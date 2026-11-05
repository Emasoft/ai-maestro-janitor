// Cloud provider credentials. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const awsAccessKey: Rule = { kind: 'aws-access-key', pattern: /\b((?:AKIA|ASIA)[A-Z0-9]{16})\b/g, group: 1 }
export const awsSecretKeyAssignment: Rule = { kind: 'aws-secret-key', pattern: /\b(?:aws_?secret_?(?:access_?)?key|secret_?access_?key)["']?\s*[=:]\s*["']?([A-Za-z0-9/+=]{40})(?![A-Za-z0-9/+=])/gi, group: 1 }
export const awsSecretKeyJson: Rule = { kind: 'aws-secret-key', pattern: /"SecretAccessKey"\s*:\s*"([A-Za-z0-9/+=]{40})"/g, group: 1 }
export const awsSessionToken: Rule = { kind: 'aws-session-token', pattern: /"SessionToken"\s*:\s*"([A-Za-z0-9/+=]{100,})"/g, group: 1 }
export const googleApiKey: Rule = { kind: 'google-api-key', pattern: /\b(AIza[0-9A-Za-z_-]{35})(?![0-9A-Za-z_-])/g, group: 1 }

// WHY: adapted from veil's /\bGOCSPX-[A-Za-z0-9_-]{28}(?![\w-])/ (NOTICE). The tail floor is 20 with no upper bound and no end guard,
// because for a redactor a total miss on a tail that is not exactly 28 characters costs more than hiding a placeholder: a 36-character
// corpus fixture was missed whole by veil's form.
export const googleOAuthClientSecret: Rule = { kind: 'google-oauth-client-secret', pattern: /\bGOCSPX-[A-Za-z0-9_-]{20,}/g }
// WHY: 2048 is Google's documented cap for a whole access token; veil applies it to the first segment and bounds each of up to 4 dotted segments at 512, its own choice.
export const googleOAuthAccessToken: Rule = { kind: 'google-oauth-access-token', pattern: /\bya29\.[\w-]{20,2048}(?:\.[\w-]{1,512}){0,4}/g }
// WHY: adapted from veil's (?<![\w/])1\/\/0[\w-]{40,512} (NOTICE): '+' is added to the lookbehind. Inside standard base64, which has '+' and '/' but neither '-' nor '_', 1//0 can then start only at the first character of a base64 value (or right after its '=' padding). That makes a refresh-token match splitting an AWS SessionToken, or another base64 value a later rule hides whole, rare (about 2e-8 per value, estimated) instead of removing it, and removes almost all of veil's base64 over-hide (this rule runs before the AWS rules). A real refresh token right after '+' is not hidden. 512 is Google's documented refresh-token cap. The lookbehind keeps /path/1//0 and word1//0 visible.
export const googleOAuthRefreshToken: Rule = { kind: 'google-oauth-refresh-token', pattern: /(?<![\w/+])1\/\/0[\w-]{40,512}/g }

// DigitalOcean personal access token, OAuth token and refresh token, standalone (no secret name before them needed).
// WHY each part of the pattern is written this way (NOTICE credits gitleaks v8.30.1):
// - No leading \b and no lookbehind: a token right after an escape such as \n (a literal backslash and n) must still be hidden, because \n puts the word character n right before the prefix (TRDD-5VZTPXBJ).
// - {64,} and not {64}, with no trailing boundary or lookahead: a longer hex run is hidden whole, instead of leaving a hex tail in view. The cost: hex characters glued to the end of a token, such as a date or a word made of a-f, are hidden with it.
// - The i flag covers the whole token, prefix and body: upper-case hex and an upper-case prefix are hidden too.
// DigitalOcean documents only the three prefixes (docs.digitalocean.com/notes/2022/api-token-format); the 64-hex body comes from gitleaks v8.30.1, not from DigitalOcean.
export const digitaloceanPat: Rule = { kind: 'digitalocean-pat', pattern: /dop_v1_[0-9a-f]{64,}/gi }
export const digitaloceanOAuthToken: Rule = { kind: 'digitalocean-oauth-token', pattern: /doo_v1_[0-9a-f]{64,}/gi }
export const digitaloceanRefreshToken: Rule = { kind: 'digitalocean-refresh-token', pattern: /dor_v1_[0-9a-f]{64,}/gi }
