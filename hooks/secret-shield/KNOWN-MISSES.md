# Known misses of the secret shield

These are the secrets the shield knowingly does not hide today. Each entry is pinned by a test that asserts today's miss, so fixing a miss turns its test red. Measured 2026-11-04 at b39e8a8a, Bun 1.3.14; the tests also run under claude plugin test.

Admission rule. An entry needs one reason: (a) a standalone rule for the form would hide ordinary text, with the measured false-positive count; (b) no source was found for the form, saying what was searched; (c) a bound kept for a reason named in the entry: a documented size cap, a false-positive trade-off cited at file:line, a deliberate scope of known-secret propagation, or a measured platform constraint; (d) an open defect with its own card and a known-defect test. Entries of kind (d) are open defects, not accepted misses. Precedence: (b) applies only to an undocumented form; a documented form that can be fixed without hiding ordinary text is backlog on TRDD-Q6LPJTPO and never an entry.

Enforcement. The tests run only under claude plugin test in a plugin shell; no release gate runs them yet, so a fixed miss is noticed only when someone runs them. The pytest check tests/test_secret_shield_known_misses.py runs in the normal suite and checks names only, not results: it fails when an entry and its test title do not match.

Entry format. One second-level heading per entry, the heading being the slug, followed by the lines Reason, Shape, Hidden instead, Card and Test. When a miss is fixed, turn its test into a positive test and delete its entry in the same commit.

## standalone-github-legacy-40hex

Reason: (a) a standalone rule for 40 lowercase hex characters between word edges matched 20 of 20 recent git commit hashes and 1 of the 6 lines in the measurement's copy of the false-positive corpus, so it would hide every commit hash.
Shape: 40 lowercase hex characters (digits and the letters a to f), with no name before them.
Hidden instead: The same 40 characters after GITHUB_TOKEN=, in a JSON pair, after Authorization: token, and as the password of an x-access-token URL.
Card: none
Test: KNOWN MISS standalone-github-legacy-40hex: a bare 40-hex legacy GitHub token is not hidden, the same token after its name is

## standalone-aws-secret-40

Reason: (a) a standalone rule for 40 characters of letters, digits, slash and plus, not inside a longer run, matched 20 of 20 recent git commit hashes and 1 of the 6 lines in the measurement's copy of the false-positive corpus.
Shape: 40 characters of letters, digits, slash and plus, with no name before them.
Hidden instead: The same 40 characters after aws_secret_access_key= (also upper case, with spaces around the equals sign, after a colon, and as a SecretAccessKey JSON pair).
Card: none
Test: KNOWN MISS standalone-aws-secret-40: a bare 40-character AWS secret access key is not hidden, the same key after its name is

## standalone-aws-session-token

Reason: (b) no documented leading shape was found in the four vendored gitleaks copies or in the corpus (7 corpus lines about an AWS session token gave a character class, no literal start); AWS documentation was not searched.
Shape: 356 characters of letters, digits, slash and plus, with no leading literal. The test pins that alphabet and at least 100 characters, not the exact length.
Hidden instead: The same token after aws_session_token=, AWS_SESSION_TOKEN=, in an export, as a SessionToken JSON pair, and after X-Amz-Security-Token:.
Card: none
Test: KNOWN MISS standalone-aws-session-token: a bare AWS session token with no leading shape is not hidden, the same token after its name is

## standalone-google-client-secret-without-prefix

Reason: (a) and (b). (a) a standalone rule would match ordinary text: 6860 runs of exactly 24 characters of letters, digits, hyphen and underscore, not inside a longer run of those characters, occur in 2612 tracked files read (2613 listed by git ls-files after excluding hooks/secret-shield/tests/ and tests/_fake_secrets.py, 1 binary file skipped), counted 2026-11-04 at 5ef604a1. (b) the 24-character length is the measurement's choice and is undocumented.
Shape: 24 characters of letters, digits, hyphen and underscore, with no GOCSPX- start. The test pins that alphabet and at least 20 characters (the floor of the rule for the prefixed form).
Hidden instead: The same value with the GOCSPX- start (hidden with the google-oauth-client-secret marker) and after client_secret=.
Card: none
Test: KNOWN MISS standalone-google-client-secret-without-prefix: a bare 24-character Google client secret without its prefix is not hidden, with the prefix it is

## google-refresh-legacy-single-slash

Reason: (b) the form 1/ followed by the token was not found in the corpus (0 hits for the shape); Google documentation was not searched.
Shape: 1/ followed by 45 characters of letters, digits, hyphen and underscore.
Hidden instead: The same 45 characters after the current start 1//0 (hidden with the google-oauth-refresh-token marker), and after refresh_token=.
Card: none
Test: KNOWN MISS google-refresh-legacy-single-slash: a legacy Google refresh token starting 1/ is not hidden, with the current 1//0 start it is

## google-access-over-2048

Reason: (c) Google documents a 2048-byte cap for an access token (https://developers.google.com/identity/protocols/oauth2, section "Token size"); the rule bounds the first segment at 2048 (hooks/secret-shield/rules/cloud.ts:15-16), and the part past the bound stays visible.
Shape: ya29. followed by 2100 characters in the first segment: the first 2048 are hidden, the last 52 stay visible.
Hidden instead: The same value after access_token= is hidden whole.
Card: none
Test: KNOWN MISS google-access-over-2048: the part of a Google access token past its 2048-character first segment stays visible

## google-access-dotted-segment-over-512

Reason: (b) the dotted form of an access token is undocumented; the 512-character bound per dotted segment and the limit of four dotted segments are copied from veil (hooks/secret-shield/rules/cloud.ts:15-16).
Shape: ya29., a 30-character first segment, a dot and a dotted segment of 600 characters: the first 512 of it are hidden, the last 88 stay visible.
Hidden instead: The same value after access_token= is hidden whole.
Card: none
Test: KNOWN MISS google-access-dotted-segment-over-512: the part of a dotted Google access token segment past 512 characters stays visible

## google-access-more-than-four-dotted-segments

Reason: (b) the dotted form of an access token is undocumented; the limit of four dotted segments is copied from veil (hooks/secret-shield/rules/cloud.ts:15-16).
Shape: ya29., a 30-character first segment and five dotted segments of 20 characters: the fifth, with its dot (21 characters), stays visible.
Hidden instead: The same value after access_token= is hidden whole.
Card: none
Test: KNOWN MISS google-access-more-than-four-dotted-segments: the fifth dotted segment of a Google access token stays visible

## google-refresh-over-512

Reason: (c) Google documents a 512-byte cap for a refresh token (https://developers.google.com/identity/protocols/oauth2, section "Token size"); the rule bounds the token at 512 characters (hooks/secret-shield/rules/cloud.ts:17-18), and the part past the bound stays visible.
Shape: 1//0 followed by 600 characters: the first 512 are hidden, the last 88 stay visible.
Hidden instead: The same value after refresh_token= is hidden whole.
Card: none
Test: KNOWN MISS google-refresh-over-512: the part of a Google refresh token past 512 characters stays visible

## google-refresh-after-plus

Reason: (c) a false-positive trade-off, stated in hooks/secret-shield/rules/cloud.ts:17: the rule does not match a start 1//0 right after a plus sign, which "makes a refresh-token match splitting an AWS SessionToken, or another base64 value a later rule hides whole, rare (about 2e-8 per value, estimated) instead of removing it"; the same comment says "A real refresh token right after '+' is not hidden."
Shape: A plus sign directly before 1//0 and 50 characters of letters, digits, hyphen and underscore.
Hidden instead: The same value without the plus sign (hidden with the google-oauth-refresh-token marker) and after refresh_token=.
Card: none
Test: KNOWN MISS google-refresh-after-plus: a Google refresh token right after a plus sign is not hidden, without the plus it is

## name-ending-in-name

Reason: (c) patterns.ts:96 (the list of names that are about a secret, not the secret): a key name that ends in name holds a name, so myTokenName=<value> stays visible.
Shape: myTokenName=<18 characters of letters and digits>, also with a colon and quotes.
Hidden instead: The same value after password= and after my_token=.
Card: none
Test: KNOWN MISS name-ending-in-name: the value of a key whose name ends in name stays visible, the same value after password= is hidden

## weak-word-value

Reason: (c) patterns.ts:138, the last check of looksSecret for an unquoted value: it is hidden only when it has at least 6 characters with a digit, or at least 16 characters. The assignment pass calls it for password=<v> (patterns.ts:233; the JSON pass calls it at patterns.ts:244). No comment states why; inferred reason: code like password=required would be hidden. Given up: a real weak password after a secret name stays visible.
Shape: password=<one lowercase word of 11 letters, no digit, under 16 characters>, unquoted, also with a colon.
Hidden instead: The same word as an unspaced Password= pair between two other settings of a semicolon-delimited connection string, and the same word plus one digit after password= (at least 6 characters with a digit).
Card: none
Test: KNOWN MISS weak-word-value: a lowercase word of under 16 characters with no digit after password= stays visible, in a connection string it is hidden

## unquoted-dotted-identifier

Reason: (c) patterns.ts:135-137. An unquoted value shaped like a dotted identifier is read as a code expression (the comment at :135 names `self.token`), so password=<a dotted identifier> is not hidden. The documented dotted token forms (a JWT; a Google ya29. access token whose first segment meets the rule's 20-character floor, rules/cloud.ts:16, while a shorter one is on the TRDD-Q6LPJTPO backlog) are hidden first by their own token rules, which run before the assignment pass (redactInto, patterns.ts:303 token rules, :305 assignments).
Shape: password= followed by an unquoted dotted identifier of 21 characters (two segments of 10 letters joined by a dot).
Hidden instead: The same value in quotes, and an unquoted fake JWT after password=.
Card: none
Test: KNOWN MISS unquoted-dotted-identifier: an unquoted dotted identifier after password= stays visible, quoted it is hidden, an unquoted JWT is hidden

## prop-separate-call

Reason: (c) deliberate scope of known-secret propagation (TRDD-Q6LPJTPO acceptance item on known-secret propagation): no state is kept between calls, so a copy in a second call is not known.
Shape: API_KEY=<24 characters of letters and digits> in one call, then echo of the value in a second call.
Hidden instead: The same copy in the same call as the definition.
Card: none
Test: KNOWN MISS prop-separate-call: a secret hidden in one call stays visible when a second call copies it

## prop-split-copy

Reason: (c) deliberate scope of known-secret propagation (TRDD-Q6LPJTPO acceptance item on known-secret propagation): a copy split by a line break is not rejoined.
Shape: API_KEY=<24 characters>, then the value cut after 12 characters by a line break.
Hidden instead: An intact copy in the same call.
Card: none
Test: KNOWN MISS prop-split-copy: a copy of a hidden secret cut by a line break stays visible, an intact copy is hidden

## prop-truncated-copy

Reason: (c) deliberate scope of known-secret propagation (TRDD-Q6LPJTPO acceptance item on known-secret propagation): a truncated copy is shorter than the found value, so it does not contain it.
Shape: API_KEY=<24 characters>, then its first 16 characters followed by three dots, or three dots followed by its last 16.
Hidden instead: An intact copy in the same call.
Card: none
Test: KNOWN MISS prop-truncated-copy: the head or the tail of a hidden secret shown with dots stays visible, an intact copy is hidden

## prop-base64-form

Reason: (c) deliberate scope of known-secret propagation (TRDD-Q6LPJTPO acceptance item on known-secret propagation): base64 is not decoded, so the encoded form is not derived from the found value.
Shape: API_KEY=<24 characters>, then the base64 form of the value, or of user: followed by the value (a Basic auth payload).
Hidden instead: An intact copy in the same call.
Card: none
Test: KNOWN MISS prop-base64-form: the base64 form of a hidden secret, alone or after user:, stays visible, an intact copy is hidden

## prop-json-decoded-form

Reason: (c) deliberate scope of known-secret propagation (TRDD-Q6LPJTPO acceptance item on known-secret propagation): the decoded form of an escaped value is not derived (the comment at patterns.ts:310-320 lists it among the known misses).
Shape: A JSON password pair whose value holds an escaped quote, newline or unicode character, then the decoded value on a later line.
Hidden instead: The escaped form copied on a later line.
Card: none
Test: KNOWN MISS prop-json-decoded-form: the decoded form of a hidden JSON value with an escape stays visible, the escaped copy is hidden

## prop-overlap

Reason: (c) deliberate scope of known-secret propagation (TRDD-Q6LPJTPO acceptance item on known-secret propagation): overlapping found values are not merged.
Shape: Two found values of 24 characters that share 12 characters (API_KEY=<A> and DB_PASSWORD=<B>), then a text made of the unshared start of A, the shared part and the unshared end of B: the end of B stays visible.
Hidden instead: An intact copy of A in the same call.
Card: none
Test: KNOWN MISS prop-overlap: the part of a text that only the second of two overlapping hidden values covers stays visible

## prop-refused-shapes

Reason: (c) propagates() at patterns.ts:148-165 refuses these shapes so that names, paths, slugs, emails and host:port are not hidden as secrets (comment at patterns.ts:141-147). Each is hidden at its defining line by the passes that found it (the last two only when quoted); only copies are not hidden. Only refusals that can refuse a real credential are listed; the marker, placeholder and repeated-character refusals are not.
Shape: Twelve shapes: a lowercase-word slug (four words of 8 letters joined by hyphens); a letters-only identifier of 20 letters; an email-shaped value; a host:port-shaped value (10 characters, a colon, 5 digits); base64-like with a slash and no digit; base64-like with a leading slash; a value containing ://; 16 digits; a value of 8 characters (under 10); a dotted domain-like value; a dotted identifier (two words of 10 letters); a value of 13 characters with no letter-digit pair (under 16). The last two are hidden at their defining line only when quoted. Unquoted, the defining line itself stays visible: the dotted identifier is entry unquoted-dotted-identifier; the 13-character value, with no digit and under 16 characters (patterns.ts:138), is on the TRDD-Q6LPJTPO backlog.
Hidden instead: The defining line alone, for each shape; for the last two, only when quoted.
Card: none
Test: KNOWN MISS prop-refused-shapes: a copy of a hidden value of a shape the propagation refuses stays visible, the definition line is hidden

## deep-nesting-over-12

Reason: (d) an open defect: patterns.ts:366-370 leaves JSON nodes deeper than 12 levels as they are.
Shape: A GitHub-style token in a string of an object nested 13 levels below the root.
Hidden instead: The same token at 12 levels.
Card: TRDD-UBWU9AQC
Test: KNOWN DEFECT TRDD-UBWU9AQC deep-nesting-over-12: a token in a JSON value nested 13 levels deep is not hidden, at 12 levels it is

## nontext-blocks

Reason: (d) an open defect: patterns.ts:402-416 (mapBlockTexts) walks only text blocks and the content of tool_result blocks.
Shape: A GitHub-style token in a tool_use input block, and in a thinking block. A tool_result image part is not covered by the test.
Hidden instead: The same token in a text block.
Card: TRDD-0VOXC39W
Test: KNOWN DEFECT TRDD-0VOXC39W nontext-blocks: a token in a tool_use input or a thinking block is not hidden, in a text block it is

## escape-boundary

Reason: (d) an open defect: every token rule whose pattern starts with a word boundary or a lookbehind (21 rules at 5ef604a1) misses a valid token right after a backslash-n inside a JSON string, after %22, and after a backslash-t.
Shape: A valid token of each of the 21 rules directly after each of the three escapes.
Hidden instead: The same token standalone, for each rule.
Card: TRDD-5VZTPXBJ
Test: KNOWN DEFECT TRDD-5VZTPXBJ escape-boundary: a valid token right after a backslash-n, %22 or a backslash-t is not hidden by any rule that starts with a word boundary or a lookbehind

## gitlab-body-under-20-chars

Reason: (c) a bound kept for a stated reason: the body floor of the 13 GitLab rules is 20 characters (hooks/secret-shield/rules/code-hosts.ts:18-22 and :31). GitLab documents no length; 20 is the shortest body of any GitLab rule in gitleaks v8.30.1 (gitlab.go), and a prefix followed by fewer characters reads as a name or a placeholder.
Shape: A GitLab prefix (glpat-) followed by 19 characters of letters, digits, underscore and hyphen.
Hidden instead: The same prefix followed by 20 characters (hidden with the gitlab-pat marker).
Card: none
Test: KNOWN MISS gitlab-body-under-20-chars: a GitLab prefix followed by a 19-character body is not hidden, with 20 characters it is

## gitlab-legacy-unprefixed-token

Reason: (b) no source was found for the form: GitLab tokens issued before the prefixes existed have no leading literal and no published shape (searched: docs.gitlab.com/security/tokens, which lists only the prefixed forms, and the 15 gitlab rules of gitleaks v8.30.1 gitlab.go, each of which needs a prefix or a cookie name). A standalone rule for 20 letters and digits would hide ordinary identifiers.
Shape: 20 characters of letters and digits, with no name and no prefix before them.
Hidden instead: The same 20 characters after GITLAB_TOKEN= (hidden by the assignment pass, because the name says secret).
Card: none
Test: KNOWN MISS gitlab-legacy-unprefixed-token: a bare 20-character legacy GitLab token is not hidden, after GITLAB_TOKEN= it is

## gitlab-session-cookie-under-16-chars

Reason: (c) a bound kept for a stated reason: the value floor of the GitLab session cookie rule is 16 characters (hooks/secret-shield/rules/code-hosts.ts:76-81). A GitLab session value is a 32-character Rack public id (cache_store.rb and abstract_store.rb, SecureRandom.hex(16)); 16 characters are 64 bits of it, and a shorter run after the name reads more often as a flag, a number or a placeholder than as a cut cookie.
Shape: _gitlab_session= followed by 15 characters of letters and digits.
Hidden instead: The same name followed by 16 characters (hidden with the gitlab-session-cookie marker).
Card: none
Test: KNOWN MISS gitlab-session-cookie-under-16-chars: a session cookie cut to 15 characters is not hidden, with 16 characters it is

## gitlab-session-cookie-value-with-delimiter

Reason: (c) a bound kept for a stated reason: an unquoted session cookie value stops at a semicolon, an ampersand, a comma, a percent sign, whitespace, a quote, a backtick or a backslash (hooks/secret-shield/rules/code-hosts.ts:71-75). GitLab session values are hex with an optional hyphenated prefix and never hold one of those, so stopping there keeps the text after a URL query ampersand or a log-line comma visible; a value that did hold an ampersand or a comma would be hidden only up to it.
Shape: _gitlab_session= followed by 20 characters of letters and digits, an ampersand and 20 more.
Hidden instead: The same value without the ampersand (hidden whole).
Card: none
Test: KNOWN MISS gitlab-session-cookie-value-with-delimiter: the part of a session cookie value after an ampersand is not hidden, a value without one is

## gitlab-session-cookie-fields-beyond-span

Reason: (c) a bound kept for a stated reason: the value pass reads a window of 512 characters on each side of the name (hooks/secret-shield/patterns.ts redactGitlabSessionWindows) and stops at a semicolon, an opening brace or a closing brace, because those end the cookie or the object that holds the name, and going past them would hide the value of another cookie or object. The widest real export read (a Chrome extension cookies.Cookie object, pretty-printed) puts about 150 characters between name and value. The name-first and value-first rules keep their own 400-character span for values that are not 32 hex.
Shape: A JSON object with the fields name (_gitlab_session), then 480 characters of other fields, then value (32 hex characters); or a nested object between the name and the value.
Hidden instead: The same object with 440 characters of other fields between the name and the value, and no brace or semicolon between them (hidden with the gitlab-session-cookie marker).
Card: none
Test: KNOWN MISS gitlab-session-cookie-fields-beyond-span: a session cookie value more than 512 characters from the name, or past a closing brace, is not hidden; within 512 characters it is

## gitlab-session-cookie-double-url-encoded

Reason: (c) a bound kept for a stated reason: only one level of URL-encoding is read between the name and the value (%3D and %3A) and around a quote (%22, %27); a second level (%253D) is not (hooks/secret-shield/rules/code-hosts.ts:95).
Shape: _gitlab_session%253D followed by a 32-character value.
Hidden instead: The same value after _gitlab_session%3D (hidden with the gitlab-session-cookie marker).
Card: none
Test: KNOWN MISS gitlab-session-cookie-double-url-encoded: a session cookie value after a double-URL-encoded equals sign is not hidden, after a single-encoded one it is

## gitlab-session-cookie-split-across-line-wrap

Reason: (c) a bound kept for a stated reason: the value pass needs 32 unbroken lowercase hex characters (hooks/secret-shield/patterns.ts redactGitlabSessionWindows), and a part of 12 hex characters after a line break cannot be told from a word, a number or a hash fragment, so no part of a broken value is taken on its own. The first part, when it has 16 or more characters, is hidden by the name-first rule.
Shape: _gitlab_session= followed by 20 hex characters, a line break and the remaining 12 hex characters.
Hidden instead: The same value without the line break (hidden whole with the gitlab-session-cookie marker).
Card: none
Test: KNOWN MISS gitlab-session-cookie-split-across-line-wrap: a session cookie value broken by a line wrap is hidden only in its first part, an unbroken value is hidden whole

## gitlab-session-cookie-uppercase-hex

Reason: (c) a bound kept for a stated reason: the value pass hides only lowercase hex, because Rails and Rack write the session id with SecureRandom.hex(16), which is lowercase (lib/gitlab/sessions/cache_store.rb, actionpack abstract_store.rb), and a pass that also took upper-case 32-hex runs near the name would hide upper-case hashes and GUIDs that are not session ids. The name-first rule still hides an upper-case value written right after the name (any 16 or more characters), so the miss is the forms only the value pass reads (a keyword argument, a nested value, a Ruby hash rocket).
Shape: create_cookie(name='_gitlab_session', value='...') with 32 upper-case hex characters as the value.
Hidden instead: The same call with the value in lower case (hidden with the gitlab-session-cookie marker).
Card: none
Test: KNOWN MISS gitlab-session-cookie-uppercase-hex: an upper-case 32-hex session cookie value in a keyword-argument form is not hidden, the same value in lower case is

## private-key-header-shapes

Reason: (c) a bound kept for a stated reason: the PEM header is one character class between lookarounds and "Keep that language exact: a wider header would take text the old pattern left alone, and its END could land inside another block and leave that block's tail visible" (hooks/secret-shield/rules/key-material.ts:5-14). The header accepts words each followed by one space and then PRIVATE KEY: it refuses a space right after BEGIN, a double space, and a word glued to PRIVATE. The shield test 'a header glued to PRIVATE whose END lies inside an RSA block' pins the glued case against a wider class.
Shape: a PEM block whose BEGIN header has a space right after BEGIN (two spaces), or a double space inside the header (RSA, two spaces, PRIVATE KEY), or a word glued to PRIVATE (XPRIVATE KEY), with a body and a matching END line. jr-redact hides all three (its header class is [A-Z ]*).
Hidden instead: the same block with a standard header (RSA PRIVATE KEY), hidden whole with the private-key marker.
Card: none
Test: KNOWN MISS private-key-header-shapes: a PEM header with a leading space, a double space or a word glued to PRIVATE is not hidden, a standard header is

## url-password-port-then-path

Reason: (a) a standalone rule for the form would hide ordinary text. patterns.ts:258-262 reads a password of up to 5 digits followed by a slash, or by a question mark and a query holding an equals sign before the at-sign, as a port followed by a path or a query (`host:8080/pkg/@scope`, `localhost:3000?email=a@b`), and skips it. A scan of the shape scheme://user:<1 to 5 digits>/...@ matched 13 times in 75764 text files read (2656 tracked files at fde4d89d, excluding hooks/secret-shield/tests/ and reports, and 73108 files of the plugin cache; files over 5 MB skipped), counted 2026-11-14: none is a credential: 10 are `@name/...` paths and 3 are placeholder or test strings. Existing tests pin the skip: 'a port followed by a path with an at-sign is not a password' and 'a password starting with digits then a slash is not hidden (known miss, kept)'.
Shape: scheme://user:<1 to 5 digits><slash or ?x=><password>@host, for example postgres://u:9/<password>@db/app. jr-redact hides it.
Hidden instead: the same password after 6 digits and a slash, or after a letter and a slash, hidden with the url-password marker.
Card: none
Test: KNOWN MISS url-password-port-then-path: a URL password starting with up to 5 digits and a slash or a query is read as a port and is not hidden, after 6 digits or a letter it is

## url-userinfo-quote-backtick-bracket

Reason: (c) a bound kept for a stated reason in part: a user part stops at a space, a colon, a slash, an at-sign, a quote, a backtick or an opening bracket (patterns.ts:62, NOT_USER; the bracket so that "a bracketed IPv6 host is never read as a user", patterns.ts:262-263, pinned by the test 'a bracketed IPv6 host is not read as a user'), and a password stops at a quote or a backtick (patterns.ts:63 and :76). No comment states why for the quote and the backtick; inferred reason: a quote or a backtick closes the string that holds a URL in code, JSON and Markdown, so a span never reads across one. Given up: a password or a user name that holds one of these characters is not hidden, and the pass hides nothing of that URL. The single quote is on the TRDD-Q6LPJTPO backlog, not here.
Shape: a URL whose password holds a double quote or a backtick, or whose user part holds a double quote, a backtick or an opening bracket (postgres://u:pa"ss<more>@host). jr-redact hides the password in each.
Hidden instead: the same URL with a plain password, hidden with the url-password marker.
Card: none
Test: KNOWN MISS url-userinfo-quote-backtick-bracket: a URL password holding a double quote or a backtick, or a user part holding a quote, a backtick or an opening bracket, is not hidden, a plain one is

## jwt-header-space-after-brace

Reason: (b) no source was found for the form: a JWT whose header JSON has a space after the opening brace starts with eyAi, not eyJ, and no jwt rule reads it (hooks/secret-shield/rules/key-material.ts, the jwt and jwtWide patterns need eyJ). Searched: 0 three-segment tokens with a first segment eyAi, and 0 with any ey-not-eyJ first segment, in 2656 tracked files (excluding hooks/secret-shield/tests/ and reports) and 73108 plugin-cache files read at fde4d89d; the JOSE specifications were not searched. Widening the first segment beyond eyJ needs its own measured change. jr-redact does not hide it either (not a jr gap).
Shape: header.payload.signature, the header the base64url of a JSON object with a space after the opening brace (first segment eyAi), the payload starting eyJ, 8 or more characters in each segment.
Hidden instead: the same token with a standard header (first segment eyJ), hidden with the jwt marker; and the eyAi token as the value of a quoted JSON access_token, hidden by the assignment pass.
Card: none
Test: KNOWN MISS jwt-header-space-after-brace: a JWT whose header has a space after the opening brace (first segment eyAi) is not hidden, with a standard header it is
