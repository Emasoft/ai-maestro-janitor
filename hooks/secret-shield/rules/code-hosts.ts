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
//   requirement, because security comes first (owner, 2026-11-05) and the character set of each GitLab token kind is unverified: gitleaks gives mostly 20 characters of
//   letters, digits, _ and -, and such a requirement would miss every token of a kind whose generator draws only lower-case letters (a 20-character base36 body has
//   no digit only about 0.15% of the time, (26/36)^20). The consequence: a prefix followed by 20 or more of [0-9A-Za-z_-] is hidden even when it is a hyphenated
//   lower-case name or a lower-case x placeholder.
// - Body {20,}, open-ended: covers 20, 25, 40, 50, 64 and the routable payloads in one shape, and hides a longer run whole instead of leaving a tail in
//   view. The cost: a _ or - or a word character glued to the end of a token is hidden with it. The 20-character floor stays although GitLab documents no length:
//   every body gitleaks gives for the 12 of these 13 kinds it has a rule for (all but glwt-; for the runner kind, glrt- only) is 20 characters or more, and so is every
//   routable length in merge request 169322, so the floor misses no published shape; for glwt- and glrtr- the floor, like their body, is an assumption. The alphabet
//   requirement, by contrast, rested on no published fact.
// - No leading \b and no lookbehind: a token right after an escape such as \n (a literal backslash and n) must still be hidden, because the n is a
//   word character right before the prefix (TRDD-5VZTPXBJ).
// - The tail is on gitlab-pat and the runner kind only: a routable token ends in a dot and 9 lower-case letters or digits (gitleaks); the gi flags widen that to
//   either case here, and the tail is exactly that followed by a non-alphanumeric. Consequences: a dot and exactly 9 letters or digits after a token (the
//   .substring before a parenthesis) is hidden with it; a dot and 10 or more (.abcdefghij, .toLowerCase) stays visible. A dot and a 9-character mixed-case name
//   before any non-alphanumeric character, such as .isPresent( or .getMethod(, is hidden with the token too.
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

// GitLab session cookie: its name makes the whole value a secret, so it is hidden from `_gitlab_session` followed by `=` (a Cookie header, a Set-Cookie header, a curl -b
// argument, a cookie assignment) or by a JSON pair (`"_gitlab_session": "..."`, also escaped). It is not a prefixed token, so it has its own pattern, not the factory above.
// Sources (NOTICE credits gitleaks v8.30.1): the name and the 32-character body come from the gitleaks rule gitlab-session-cookie (`_gitlab_session=[0-9a-z]{32}`);
// GitLab's own code (gitlabhq lib/gitlab/sessions/cache_store.rb, generate_sid) builds the value as an optional `<session_cookie_token_prefix>-` followed by the Rack public
// id, and Rails (actionpack abstract_store.rb, generate_sid) makes that id `SecureRandom.hex(16)`: 32 hex characters. The cookie name comes from
// config/initializers/session_store.rb: `_gitlab_session`, or `_gitlab_session_geo_<64 hex>` on a Geo secondary (and `_gitlab_session_<64 hex>` in development).
// WHY each part is written this way:
// - Flag gi: the name matches in any letter case (a header name or a JSON key may be re-cased); the value is a negated class, so the flag does not touch it.
// - The value is everything up to a `;`, whitespace, a quote, a backtick or a backslash (the last stops it at the `\"` of escaped JSON and at a literal backslash-n), and it
//   needs 32 or more of them: the shortest published form is 32, the cell prefix makes a real value longer, and a run that is not letters and digits (the prefix has hyphens) must
//   still be hidden whole. A value under 32 characters (empty, a placeholder, `<session>`) stays visible. The alphabet is not restricted to [0-9a-z], because security comes first
//   (owner, 2026-11-05) and the cell prefix is not in that alphabet. The cost: a placeholder of 32 or more characters is hidden too.
// - The name may carry a suffix of up to 80 letters, digits and underscores (the Geo and development cookie names above). It is bounded and not `*`: with `*` a text that repeats
//   the name with no `=` would rescan the rest of the text from every copy, which is quadratic.
// - The separator is `=` or a quoted key, a colon and a quoted value, with a run of backslashes allowed before each quote (escaped and double-escaped JSON). No leading \b and no
//   lookbehind: a name right after an escape such as a literal backslash-n must still be hidden (TRDD-5VZTPXBJ).
// - No group repeats a group: every quantifier sits on one class or one character, so the match is linear.
export const gitlabSessionCookie: Rule = {
  kind: 'gitlab-session-cookie',
  pattern: /_gitlab_session(?:_[0-9a-z_]{0,80})?(?:=|\\*"\s*:\s*\\*")([^;\s"'`\\]{32,})/gi,
  group: 1,
}
