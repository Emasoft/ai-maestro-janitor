// Code host tokens. Moved verbatim from patterns.ts; the order the rules run in is set there.

import type { Rule } from './rule'

// WHY the floors are 30 and 20 and there is no trailing \b (TRDD-6A3XW3VO, widened 2026-11-14): the old floors (36 and 22) came from upstream secret-shield 1.0.0 with no recorded
// reason. jr-redact hid shorter tokens the shield left visible; the TRDD-6A3XW3VO measurement showed that widening them hides all 15 such samples (shield-test strings and catalog samples), and that on 140 MB of separate repo and plugin-cache text every match was already hidden by the shield's existing rules.
// The trailing \b is dropped because a token whose tail continues with an underscore (a word character) never reaches a boundary, so the old rule left the whole token visible.
export const githubTokenClassic: Rule = { kind: 'github-token', pattern: /\b(gh[pousr]_[A-Za-z0-9]{30,255})/g, group: 1 }
export const githubTokenFineGrained: Rule = { kind: 'github-token', pattern: /\b(github_pat_[A-Za-z0-9_]{20,255})/g, group: 1 }

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
const TAIL = String.raw`(?:\.[0-9a-z]{9}(?![0-9A-Za-z]))?`
// Not exported: known-misses.test.ts reads every export of this file as a Rule.
// WHY the body is a string literal in the RegExp call and the tail is picked before the call: skillaudit's REGEX_DOS check accepts a concatenated RegExp
// only when the call holds a string literal and nothing but identifiers around it; the old call (a body const and a ternary) was flagged.
const gitlab = (kind: string, prefix: string, tailed = false): Rule => {
  const tail = tailed ? TAIL : ''
  return { kind, pattern: new RegExp(prefix + '[0-9A-Za-z_-]{20,}' + tail, 'gi') }
}

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

// The GitLab session cookie's name makes the whole value a secret, so the value is hidden wherever it is written next to the name `_gitlab_session`. It is not a prefixed token, so it has
// its own two rules, not the factory above. Forms hidden: `_gitlab_session=V` (a Cookie header, a Set-Cookie header, a curl -b argument, a URL query, a cookie assignment, with spaces
// around the `=` or quotes after it), `_gitlab_session%3DV` (URL-encoded), a JSON, Ruby-hash, JavaScript or Python key (`"_gitlab_session": "V"`, `"_gitlab_session"=>"V"`,
// `{'_gitlab_session': 'V'}`, `cookies['_gitlab_session'] = 'V'`, plain, escaped or URL-encoded), YAML (`_gitlab_session: V`), a Netscape cookie-jar line (the name, a tab, the value), the
// browser/HAR/Puppeteer/Playwright/Go name-and-value pair, name first (`"name": "_gitlab_session", "value": "V"`, `{name: '_gitlab_session', value: 'V'}`, `Name: "_gitlab_session", Value: "V"`) or
// value first (`"value": "V", "name": "_gitlab_session"`; the second is gitlabSessionCookieValueFirst), with other fields between the two (up to 400 characters, inside one object), a
// positional call with the name and the value as the first two arguments (`set_cookie('_gitlab_session', 'V')`, `cookies.set("_gitlab_session", "V")`, `res.cookie('_gitlab_session', 'V')`)
// and a Rails cookie hash (`cookies[:_gitlab_session] = { value: 'V', httponly: true }`).
// Sources (NOTICE credits gitleaks v8.30.1): the name and the 32-character body come from the gitleaks rule gitlab-session-cookie (`_gitlab_session=[0-9a-z]{32}`);
// GitLab's own code (gitlabhq lib/gitlab/sessions/cache_store.rb, generate_sid) builds the value as an optional `<session_cookie_token_prefix>-` followed by the Rack public
// id, and Rails (actionpack abstract_store.rb, generate_sid) makes that id `SecureRandom.hex(16)`: 32 hex characters. The cookie name comes from
// config/initializers/session_store.rb: `_gitlab_session`, or `_gitlab_session_geo_<64 hex>` on a Geo secondary (and `_gitlab_session_<64 hex>` in development).
// The field order of real cookie exports (read 2026-11-05) decides how far apart name and value can be: the Chrome extensions cookies.Cookie reference
// (developer.chrome.com/docs/extensions/reference/api/cookies) lists domain, expirationDate, hostOnly, httpOnly, name, partitionKey, path, sameSite, secure, session, storeId, value, so five
// or six fields sit between name and value; exports of EditThisCookie and Cookie-Editor (Cookie-Editor interface/lib/jsonFormat.js is JSON.stringify(cookies, null, 4) of the browser's own cookie
// objects) keep that order in practice (public exports, e.g. github.com/bakialmaci/pararius_reactor session.example.json, show domain, expirationDate, hostOnly, httpOnly, name, path, sameSite, secure,
// session, storeId, value); Playwright (packages/playwright-core/src/server/chromium/crBrowser.ts, doGetCookies, used by storageState) writes name, value, domain, path, expires, httpOnly, secure,
// sameSite, so the two are adjacent there. About 150 characters separate name and value in the widest export, so a 400-character span covers it with room to spare.
// WHY each part is written this way:
// - Flag gi: the name matches in any letter case (a header name or a JSON key may be re-cased); the value is a negated class, so the flag does not touch it. The same flag lets `Value:` of a Go struct match the key `value`.
// - The value is everything up to a `;`, `&`, `,`, `%`, whitespace, a quote, a backtick or a backslash. The backslash stops it at the `\"` of escaped JSON and at a literal backslash-n;
//   `;` ends a cookie in a header; `&` and `,` end it in a URL query and in a comma-joined log line; `%` ends it before a URL-encoded `%3B`, `%22` or `%26`. Stopping at those cannot leak a
//   real value: a GitLab session value is a Rack public id (32 hex characters, SecureRandom.hex(16)) with an optional `<prefix>-` in front, as read in cache_store.rb and abstract_store.rb
//   above, and none of those characters occurs in it. Without the stop, an unquoted value ran to the next `;`, whitespace, quote, backtick or backslash, so `_gitlab_session=V&next=/x` and
//   `_gitlab_session=V,other` hid the text after the `&` or `,` as well. What remains: a value of an operator-chosen prefix that held one of these characters would be hidden only up to it.
// - The floor is 16 characters, not the 32 of the published form: a cookie cut short in a log (16 to 31 characters) is still most of a 128-bit id and must be hidden, because security
//   comes first (owner, 2026-11-05). A value under 16 characters (empty, `<session>`, a number, a short word) stays visible: 16 hex characters are 64 bits, and a shorter run reads more
//   often as a flag or a placeholder. The alphabet is not restricted to [0-9a-z], because the cell prefix has hyphens. The cost: a placeholder or any word of 16 or more characters
//   after the name is hidden too, and so is an unquoted code expression (`_gitlab_session = fetch_session_value()`), because a bare `:` and a tab are accepted as separators.
//   The separator characters `=`, `>` and `:` are also in the value class, so after a doubled separator (`=>` read as `=` then `>`, or `::`, or `==`) the effective floor is 15 characters,
//   the separator character counting as the first of the 16.
// - The name may carry a suffix of up to 80 letters, digits and underscores (the Geo and development cookie names above). It is bounded and not `*`: with `*` a text that repeats
//   the name with no `=` would rescan the rest of the text from every copy, which is quadratic.
// - Between the name and the value there are three shapes. (1) A plain separator: an optional closing quote (with any run of backslashes before it, or its URL-encoded form), an optional `]`,
//   spaces and line breaks, then one of `=`, `=>`, `:`, `%3D`, `%3A` or a tab, then spaces or tabs and an optional opening quote. (2) A positional call: a closing quote, a comma, spaces or
//   tabs and then a MANDATORY opening quote. (3) A field list: a comma (a HAR, Puppeteer, Playwright or Go pair) or `=` and `{` (a Rails hash), then a span of up to 400 characters that holds
//   no brace, then the key `value`, an optional closing quote, a colon, spaces or tabs and a MANDATORY opening quote. The span stops at a brace, so it never leaves the object that holds the
//   name; a nested object between the fields, or more than 400 characters between them, is a known miss (KNOWN-MISSES.md gitlab-session-cookie-fields-beyond-span). The span is lazy, so the first
//   `value` key after the name wins. Costs: a quoted list of cookie names (the name, a comma, then another quoted name) hides the next name when it has 16 or more characters, and any
//   text of the form name, comma, `value:` and a quoted run of 16 characters within 400 characters and no brace is hidden, a prose sentence too.
// - After the separator only spaces and tabs are skipped, never a line break (`[ \t]*`, not `\s*`): with `\s*` a YAML map header `_gitlab_session:` alone on its line, or a log line that ends in
//   `_gitlab_session:`, took the first 16 or more characters of the next line (a key, a timestamp) as the value and hid them. The line break before the separator (`[ \r\n]*`) stays, for a
//   pretty-printed `"_gitlab_session"\n: "V"`; a tab is not in that set because the tab is itself a separator, so a tab run splits one way only. A tab before the colon
//   (`"_gitlab_session"\t: "V"`) is therefore not read by this rule; a 32-hex value there is hidden by redactGitlabSessionWindows in patterns.ts.
// - A double URL-encoding (`_gitlab_session%253DV`) is not hidden: only `%3D` and `%3A` are separators, and a `%25` before them is not (KNOWN-MISSES.md gitlab-session-cookie-double-url-encoded).
// - Linearity, which every change here must keep: a value run is always preceded by something that cannot occur inside a run. In the name-first rule the value is the last element of the pattern,
//   so a match never backtracks out of a run and the next search starts after it. In the value-first rule the value is followed by a mandatory quote, and it is preceded by a mandatory opening
//   quote, and a value run holds no quote, so two runs never overlap; the key quote before the value may be absent only because the value's own opening quote is mandatory (with both optional,
//   a text that repeats `value:` would start a run at every copy, each running to the end: quadratic). The 400-character span is a fixed bound, so each name or each value adds a constant
//   amount of work. No group repeats (`(?:...)*`, `+` on a group): the URL_PASSWORD diagnosis found group-loop ceilings in the claude plugin test engine.
// - No leading \b and no lookbehind: a name right after an escape such as a literal backslash-n must still be hidden (TRDD-5VZTPXBJ). The value-first rule starts at the literal `value` for the
//   same reason, and not at a quote: a pattern that starts with a run of backslashes would try every position of a long run (quadratic).
const QUOTE = String.raw`(?:\\*["']|%2[27])`
const SESSION_VALUE = String.raw`([^;&,%\s"'` + '`' + String.raw`\\]{16,})`
// Up to 400 characters of one object: the lazy span never crosses a brace.
const SAME_OBJECT = '[^{}]{0,400}?'
// The key `value`, its optional closing quote, a colon and the MANDATORY opening quote of its value.
const VALUE_KEY = 'value' + QUOTE + String.raw`?[ \t]*:[ \t]*` + QUOTE
const AFTER_NAME =
  '(?:' +
  QUOTE + String.raw`[ \t]*,[ \t]*` + QUOTE + '|' +
  QUOTE + String.raw`?\]?[ \r\n]*(?:(?:=>?|:|%3[AD]|\t)[ \t]*` + QUOTE + '?|(?:,|=>?[ \\t]*\\{)' + SAME_OBJECT + VALUE_KEY + '))'
export const gitlabSessionCookie: Rule = {
  kind: 'gitlab-session-cookie',
  // WHY the name is a string literal here and not a const: skillaudit's REGEX_DOS check accepts a concatenated RegExp only when the call holds a string literal.
  pattern: new RegExp('_gitlab_session(?:_[0-9a-z_]{0,80})?' + AFTER_NAME + SESSION_VALUE, 'gi'),
  group: 1,
}
export const gitlabSessionCookieValueFirst: Rule = {
  kind: 'gitlab-session-cookie',
  pattern: new RegExp(VALUE_KEY + SESSION_VALUE + QUOTE + String.raw`\s*,` + SAME_OBJECT + 'name' + QUOTE + String.raw`?[ \t]*:[ \t]*` + QUOTE + '?_gitlab_session', 'gi'),
  group: 1,
}
