// Code host tokens. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

export const githubTokenClassic: Rule = { kind: 'github-token', pattern: /\b(gh[pousr]_[A-Za-z0-9]{36,255})\b/g, group: 1 }
export const githubTokenFineGrained: Rule = { kind: 'github-token', pattern: /\b(github_pat_[A-Za-z0-9_]{22,255})\b/g, group: 1 }

// GitLab prefixed tokens, standalone (no secret name before them needed). Sources (NOTICE credits gitleaks v8.30.1): the prefixes come from
// docs.gitlab.com/security/tokens, which gives no length or character set; the body shapes come from gitleaks cmd/generate/config/rules/gitlab.go
// (mostly 20 characters of letters, digits, _ and -); GitLab merge request 169322 gives 43 to 316 characters for the routable personal access token.
// All 13 rules are built here from one prefix, one body and one tail, so a single edit changes every rule.
// WHY each part is written this way:
// - Flag gi: the prefix and the body are matched in any letter case, and so is the tail (it accepts upper-case letters too). The rules have no digit-or-upper-case
//   requirement, because security comes first (owner, 2026-11-05) and the character set of each GitLab token kind is unverified: gitleaks gives 20 characters of
//   letters, digits, _ and -, but a kind whose generator draws only lower-case letters or base36 would be missed often by such a requirement. The consequence: a prefix
//   followed by 20 or more of [0-9A-Za-z_-] is hidden even when it is a hyphenated lower-case name or a lower-case x placeholder.
// - Body {20,}, open-ended: covers 20, 25, 40, 50, 64 and the routable payloads in one shape, and hides a longer run whole instead of leaving a tail in
//   view. The cost: a _ or - or a word character glued to the end of a token is hidden with it.
// - No leading \b and no lookbehind: a token right after an escape such as \n (a literal backslash and n) must still be hidden, because the n is a
//   word character right before the prefix (TRDD-5VZTPXBJ).
// - The tail is on gitlab-pat and the runner kind only: a routable token ends in a dot and 9 letters or digits (gitleaks), and the tail is
//   exactly that followed by a non-alphanumeric. Consequences: a dot and exactly 9 letters or digits after a token (the
//   .substring before a parenthesis) is hidden with it; a dot and 10 or more (.abcdefghij, .toLowerCase) stays visible.
//   glrtr- gets the tail without evidence, on the assumption that it mirrors glrt-.
// - The glwt- and glrtr- bodies are an assumption: neither prefix has a published shape, and gitleaks has no rule for either.
const BODY = '[0-9A-Za-z_-]{20,}'
const TAIL = String.raw`(?:\.[0-9a-z]{9}(?![0-9A-Za-z]))?`
// Not exported: known-misses.test.ts reads every export of this file as a Rule.
const gitlab = (kind: string, prefix: string, tailed = false): Rule => ({ kind, pattern: new RegExp(prefix + BODY + (tailed ? TAIL : ''), 'gi') })

export const gitlabPat: Rule = gitlab('gitlab-pat', 'glpat-', true)
export const gitlabOAuthAppSecret: Rule = gitlab('gitlab-oauth-app-secret', 'gloas-')
export const gitlabDeployToken: Rule = gitlab('gitlab-deploy-token', 'gldt-')
// The longer prefix first, though neither can start inside the other (glrt- needs a hyphen right after the t).
export const gitlabRunnerToken: Rule = gitlab('gitlab-runner-token', '(?:glrtr-|glrt-)', true)
export const gitlabRunnerRegistrationToken: Rule = gitlab('gitlab-runner-registration-token', 'GR1348941')
export const gitlabCicdJobToken: Rule = gitlab('gitlab-cicd-job-token', 'glcbt-')
export const gitlabTriggerToken: Rule = gitlab('gitlab-trigger-token', 'glptt-')
export const gitlabFeedToken: Rule = gitlab('gitlab-feed-token', 'glft-')
export const gitlabIncomingMailToken: Rule = gitlab('gitlab-incoming-mail-token', 'glimt-')
export const gitlabAgentToken: Rule = gitlab('gitlab-agent-token', 'glagent-')
export const gitlabWorkspaceToken: Rule = gitlab('gitlab-workspace-token', 'glwt-')
export const gitlabScimToken: Rule = gitlab('gitlab-scim-token', 'glsoat-')
export const gitlabFeatureFlagClientToken: Rule = gitlab('gitlab-feature-flag-client-token', 'glffct-')
