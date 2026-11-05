// Code host tokens. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const githubTokenClassic: Rule = { kind: 'github-token', pattern: /\b(gh[pousr]_[A-Za-z0-9]{36,255})\b/g, group: 1 }
export const githubTokenFineGrained: Rule = { kind: 'github-token', pattern: /\b(github_pat_[A-Za-z0-9_]{22,255})\b/g, group: 1 }

// GitLab prefixed tokens, standalone (no secret name before them needed). Sources (NOTICE credits gitleaks v8.30.1): the prefixes come from
// docs.gitlab.com/security/tokens, which gives no length or character set; the body shapes come from gitleaks cmd/generate/config/rules/gitlab.go
// (mostly 20 characters of letters, digits, _ and -); GitLab merge request 169322 gives 43 to 316 characters for the routable personal access token.
// All 13 rules are built here from one prefix, one lookahead, one body and one tail, so a single edit changes every rule.
// WHY each part is written this way:
// - Flag g only, never i: under i, [0-9A-Z] matches every letter, so the digit-or-upper-case requirement below silently disappears. The prefix is
//   spelled case-insensitively letter by letter instead ([gG][lL]...), so an upper-case prefix is still hidden. Never add i back.
// - The lookahead requires at least one digit or upper-case letter inside the body itself: it keeps all-lower-case kebab names
//   (a prefix followed by a hyphenated lower-case phrase) and lower-case x placeholders visible. A real 20-character body has neither a digit nor an upper-case letter
//   with probability (28/64)^20, about 6.6e-8 (28 of the 64 characters are lower-case letters, _ and -), whereas requiring a digit alone would miss
//   about 3% of real bodies ((54/64)^20). Its class is the body class, placed right after the prefix, so it cannot be satisfied by anything outside the body.
// - The lookahead bound 319: the longest routable token is 316 characters (merge request 169322), and the bound keeps the lookahead linear on a long
//   all-lower-case run (it reads at most 320 characters per prefix, and then gives up).
// - Body {20,}, open-ended: covers 20, 25, 40, 50, 64 and the routable payloads in one shape, and hides a longer run whole instead of leaving a tail in
//   view. The cost: a _ or - or a word character glued to the end of a token is hidden with it.
// - No leading \b and no lookbehind: a token right after an escape such as \n (a literal backslash and n) must still be hidden, because the n is a
//   word character right before the prefix (TRDD-5VZTPXBJ).
// - The tail is on gitlab-pat and the runner kind only: a routable token ends in a dot and 9 lower-case letters or digits (gitleaks), and the tail is
//   exactly that followed by a non-alphanumeric. Consequences: a dot and exactly 9 lower-case letters or digits after a token (the
//   .substring before a parenthesis) is hidden with it; a dot and 10 or more (.abcdefghij) stays visible, and so does anything with an upper-case
//   letter in its first 9 characters (.toLowerCase). glrtr- gets the tail without evidence, on the assumption that it mirrors glrt-.
// - The glwt- and glrtr- bodies are an assumption: neither prefix has a published shape, and gitleaks has no rule for either.
const CLASS = '[0-9A-Za-z_-]'
const LOOKAHEAD = `(?=${CLASS}{0,319}?[0-9A-Z])`
const BODY = `${CLASS}{20,}`
const TAIL = String.raw`(?:\.[0-9a-z]{9}(?![0-9A-Za-z]))?`
// Spells each letter as [xX]; digits and - pass through unchanged.
const caseless = (literal: string): string => literal.replace(/[a-z]/gi, letter => `[${letter.toLowerCase()}${letter.toUpperCase()}]`)
// Not exported: known-misses.test.ts reads every export of this file as a Rule.
const gitlab = (kind: string, prefix: string, tailed = false): Rule => ({ kind, pattern: new RegExp(prefix + LOOKAHEAD + BODY + (tailed ? TAIL : ''), 'g') })

export const gitlabPat: Rule = gitlab('gitlab-pat', caseless('glpat-'), true)
export const gitlabOAuthAppSecret: Rule = gitlab('gitlab-oauth-app-secret', caseless('gloas-'))
export const gitlabDeployToken: Rule = gitlab('gitlab-deploy-token', caseless('gldt-'))
// The longer prefix first, though neither can start inside the other (glrt- needs a hyphen right after the t).
export const gitlabRunnerToken: Rule = gitlab('gitlab-runner-token', `(?:${caseless('glrtr-')}|${caseless('glrt-')})`, true)
export const gitlabRunnerRegistrationToken: Rule = gitlab('gitlab-runner-registration-token', caseless('GR1348941'))
export const gitlabCicdJobToken: Rule = gitlab('gitlab-cicd-job-token', caseless('glcbt-'))
export const gitlabTriggerToken: Rule = gitlab('gitlab-trigger-token', caseless('glptt-'))
export const gitlabFeedToken: Rule = gitlab('gitlab-feed-token', caseless('glft-'))
export const gitlabIncomingMailToken: Rule = gitlab('gitlab-incoming-mail-token', caseless('glimt-'))
export const gitlabAgentToken: Rule = gitlab('gitlab-agent-token', caseless('glagent-'))
export const gitlabWorkspaceToken: Rule = gitlab('gitlab-workspace-token', caseless('glwt-'))
export const gitlabScimToken: Rule = gitlab('gitlab-scim-token', caseless('glsoat-'))
export const gitlabFeatureFlagClientToken: Rule = gitlab('gitlab-feature-flag-client-token', caseless('glffct-'))
