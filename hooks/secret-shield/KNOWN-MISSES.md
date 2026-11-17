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

Reason: (d) an open defect: every token rule whose pattern starts with a word boundary or a lookbehind (23 rules, the count pinned by the test) misses a valid token right after a backslash-n inside a JSON string, after %22, and after a backslash-t.
Shape: A valid token of each of the 23 rules directly after each of the three escapes.
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
Shape: a PEM block whose BEGIN header has a space right after BEGIN (two spaces), or a double space inside the header (RSA, two spaces, PRIVATE KEY), or a word glued to PRIVATE (XPRIVATE KEY), with a body and a matching END line. jr-redact hides all three (its header class is [A-Z ]*; run against the three shapes on 2026-11-14).
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

## bearer-value-on-next-line

Reason: (a) the bare Bearer rule (hooks/secret-shield/rules/key-material.ts, bearerBare) takes only spaces and tabs between the word and the value, because a whitespace run that crossed a line break masked a path or a variable name at the start of the next line, and the found-value propagation then hid that name everywhere in the file. Measured 2026-11-16: 43 newline-crossing matches in the code tree and 0 in the plugin cache; all 43 were one identifier after a blank line, 0 were real tokens.
Shape: the word Bearer, a line break (with or without further blank lines) or any other whitespace that is not a space or a tab (form feed, vertical tab, a non-breaking or Unicode space), then 8 or more characters of letters, digits and . _ ~ + / = - holding a digit.
Hidden instead: the same value after Bearer and a space or a tab on the same line, and after the Authorization header name and Bearer on one line (hidden with the bearer-token marker).
Card: none
Test: KNOWN MISS bearer-value-on-next-line: a token wrapped onto the next line after Bearer stays visible, on the same line it is hidden

## card-bare-run-17-to-19-without-card-word

Reason: (a) a standalone rule for a bare run of 17 to 19 digits that passes the issuer prefix and Luhn checks hid ordinary text: in the 2026-11-16 measurement of the old report-sanitizer card rule on 50,487 text files, 183 of its 240 hidden matches were runs of 17 to 19 digits and 180 of those were cargo build hashes, not cards (figures recorded in TRDD-L1I0FP5T). The shield's card pass (hooks/secret-shield/cards.ts) therefore asks for a card word before such a run.
Shape: one run of 17, 18 or 19 digits that starts with an issuer prefix (a Visa of 19 digits, or a Discover, JCB or Diners Club number of 17 to 19) and passes Luhn, with none of the words card, credit, debit, visa, mastercard or amex standing whole within the 32 characters before it on the same line.
Hidden instead: the same run with one of those words before it on the same line, and a 19-digit Visa written in the 4-4-4-4-3 grouping.
Card: none
Test: KNOWN MISS card-bare-run-17-to-19-without-card-word: a bare 17 to 19 digit card number with no card word near it is not hidden, with a card word it is

## card-non-standard-grouping

Reason: (a) the old report-sanitizer card rule took one space or dash between any two digits, and in the same measurement 2 of its 190 false matches were a process listing (pid, parent pid, elapsed time) read as one 14-digit number across three columns. The shield's card pass reads only the groupings 4-4-4-4, 4-6-5, 4-6-4 and 4-4-4-4-3, each with one separator kind throughout.
Shape: a card number whose digits are split by single spaces or dashes in any other grouping, for example 4-4-5 (a 13-digit Visa) or groups of 3 or 5, or by two kinds of separator, and that passes the issuer prefix and Luhn checks.
Hidden instead: the same number as one bare run of 13 to 16 digits, or in one of the four groupings.
Card: none
Test: KNOWN MISS card-non-standard-grouping: a card number grouped 4-4-5 is not hidden, in a standard grouping or as a bare run it is

## card-word-too-far-or-not-listed

Reason: (c) a bound kept for a stated reason: a bare run of 17 to 19 digits is hidden only when a card word stands near it, because the 180 cargo build hashes of the 2026-11-16 measurement had no such word (figures recorded in TRDD-L1I0FP5T). The word list is card, credit, debit, visa, mastercard and amex, each whole (no letter or digit touching it, except that a literal backslash escape, a backslash and n, r or t, before it counts as a boundary, as in a JSON or Python string dump), within the 32 characters before the run on the same line. A wider window or a longer list would admit more ordinary text near a hash.
Shape: a bare run of 17 to 19 digits that starts with an issuer prefix and passes Luhn, whose card word stands more than 32 characters before it, on an earlier line, inside a longer word (cardinal, discard, or the word with an n right before it and no backslash before that n), or is another word (payment, pan, ccn).
Hidden instead: the same run with one of the six words within 32 characters before it on the same line.
Card: none
Test: KNOWN MISS card-word-too-far-or-not-listed: a 19-digit card number with its card word 40 characters before it, or with a word that is not in the list, is not hidden, with the word within 32 characters it is

## card-after-digit-and-separator

Reason: (a) the card pass refuses a start that follows a digit and one space or dash, as the old report-sanitizer lookbehind did, so that the tail of a longer chain of digit groups is not read as a card; the 2 process-listing false matches of the 2026-11-16 measurement (pid, parent pid, elapsed time) were such chains. The cost is that a real card with a number or a date before it, one separator apart, is not hidden.
Shape: a digit group, one space or dash, then a card number (a bare run of 13 to 16 digits, or a grouped number), for example a number or a date before the card with one separator between them: 7777 then a space then a 16-digit card.
Hidden instead: the same card after a comma, a colon, a letter and a space, or at the start of the line.
Card: none
Test: KNOWN MISS card-after-digit-and-separator: a card number that follows a digit group and a separator is not hidden, on its own it is

## card-after-dot

Reason: (a) the digits after a decimal point are a float fraction, not a number of their own: 8 of the 190 false matches of the 2026-11-16 measurement were fractions printed by a probe. The pass refuses a start whose previous character is a dot, so a sentence that ends in a dot and runs straight into a card number, with no space, is not hidden either.
Shape: a dot, then at once a card number (a bare run of 13 to 19 digits or a grouped number), with no space after the dot.
Hidden instead: the same card after a space, a comma or any other character that is not a letter, a digit, an underscore or a dot.
Card: none
Test: KNOWN MISS card-after-dot: a card number right after a dot is not hidden, after a comma it is

## card-grouped-followed-by-two-groups

Reason: (a) a grouped card followed by the same separator, a group of 4 or more digits and then one more group is read as a longer grouped number (six groups of 4, or more), not as a card with something after it. The old report-sanitizer rule refused any trailing separator and digit, and the 2 process-listing false matches of the 2026-11-16 measurement were chains of digit groups; the shield's card pass refuses only this longer shape. A card followed by one group of 4 (an expiry written as month and year with no slash), by a group of 1 to 3 digits (a CVV) or by a different separator is hidden and its tail stays visible.
Shape: a card number in one of the four groupings, with its separator, then a group of 4 or more digits, then the same separator and a digit, for example a 4-4-4-4 card followed by two more groups of 4.
Hidden instead: the same card followed by one group of 4 digits, by a CVV, or by an expiry with a slash.
Card: none
Test: KNOWN MISS card-grouped-followed-by-two-groups: a 4-4-4-4 card number followed by two more groups of 4 digits is not hidden, followed by one group it is

## card-glued-to-letter-or-underscore

Reason: (a) a run of digits that touches a letter or an underscore is part of a word or an identifier (a hash with a prefix, a build id, a file name), and the old rule's lookaround refused it for the same reason; the shield's card pass keeps that. The cost is a card with a letter or an underscore right before or after it, and the n of a JSON-escaped line break (a backslash and an n) right before a number.
Shape: a card number whose first digit follows a letter, a digit or an underscore, or whose last digit is followed by a letter or an underscore, for example 16 digits then the letter x, or the two characters backslash and n then 16 digits.
Hidden instead: the same card after or before a space, a comma, a colon, an equals sign or a quote.
Card: none
Test: KNOWN MISS card-glued-to-letter-or-underscore: a card number glued to a letter or an underscore, or after the n of a JSON-escaped line break, is not hidden, after a space it is

## email-git-local-part

Reason: (c) a deliberate scope decided for TRDD-L1I0FP5T (increment 3): the email pass (hooks/secret-shield/email.ts) hides what the report-sanitizer EMAIL rule hides, span for span, except the address of a git clone over SSH. That address names a service account (git), not a person, and report-sanitizer's ssh_cmd_repl keeps it visible for the same reason. No false-positive count was measured for it.
Shape: a local part equal to git in any letter case, at a host, when the character right after the matched domain is a colon followed by a letter, a digit, a slash, a tilde, an underscore or a hyphen (the scp-like clone form: git, at sign, host, colon, owner, slash, repository), or when the local part comes directly after ssh:// or git+ssh:// (the URL form; the scheme in any letter case).
Hidden instead: a git local part anywhere else (alone, before a comma or a dot, before a colon followed by a space, a dot or nothing), a local part that only contains git (a letter before it, or git then a dot and more characters), and any other local part after ssh://.
Card: none
Test: KNOWN MISS email-git-local-part: a git clone address, in the scp-like form or after ssh://, is not hidden, a git address anywhere else is

## email-non-ascii

Reason: (c) a deliberate scope: the email pass reads the same ASCII character classes as the report-sanitizer EMAIL rule, so that the two rules give the same spans. No false-positive count was measured for a wider class.
Shape: an address with a non-ASCII letter in the character right before the at sign (the local part is then empty), or inside the domain (the labels stop there). A non-ASCII letter earlier in the local part leaves the letter visible and hides only the ASCII characters after it.
Hidden instead: the same address written with ASCII letters only.
Card: none
Test: KNOWN MISS email-non-ascii: an address with a non-ASCII letter right before the at sign or inside the domain is not hidden, an ASCII one is

## email-quoted-local-part

Reason: (c) a deliberate scope: the local-part class has no quote, as in the report-sanitizer EMAIL rule, so a quoted local part (allowed by the mail standard, rare in practice) is not read. No false-positive count was measured for a rule that reads quotes.
Shape: a local part in double quotes, with or without spaces inside, followed by the at sign and a domain: the quote right before the at sign ends the local part before it starts.
Hidden instead: the same words without the quotes (with spaces inside, the part after the last space is hidden).
Card: none
Test: KNOWN MISS email-quoted-local-part: an address whose local part is in double quotes is not hidden, the same words unquoted are

## email-ip-literal-domain

Reason: (c) a deliberate scope: a domain must end in a label that starts with two letters, as in the report-sanitizer EMAIL rule, so a domain that is an IP address is not read, in brackets or not. No false-positive count was measured for a rule that reads them.
Shape: a local part, the at sign, then an IPv4 address with or without square brackets around it.
Hidden instead: the same local part with a host name that has a label of two or more letters at the end.
Card: none
Test: KNOWN MISS email-ip-literal-domain: an address whose domain is an IP address, in brackets or not, is not hidden, a host name is

## email-single-label-domain

Reason: (c) a deliberate scope: the domain needs at least two labels, as in the report-sanitizer EMAIL rule (a single label such as a machine name is not a public address). No false-positive count was measured for a rule that reads them.
Shape: a local part, the at sign, then one label with no dot, for example the name of a local machine.
Hidden instead: the same local part with a domain of two or more labels.
Card: none
Test: KNOWN MISS email-single-label-domain: an address whose domain has one label is not hidden, with two labels it is

## email-tld-without-two-leading-letters

Reason: (c) a deliberate scope: the address ends after the leading letters of the last label that starts with two or more ASCII letters, as in the report-sanitizer EMAIL rule. A domain whose labels after the first all start with a digit or with a single letter has no such label. No false-positive count was measured for a wider rule.
Shape: a local part, the at sign, a host, then a last label that starts with a digit (all digits, or digits then letters) or with one letter followed by a digit or a hyphen, or is one letter.
Hidden instead: the same domain with a last label that starts with two or more letters.
Card: none
Test: KNOWN MISS email-tld-without-two-leading-letters: an address whose last label starts with a digit or with a single letter is not hidden, with two letters first it is

## email-domain-tail-after-letter-run

Reason: (c) a deliberate scope: the address ends after the leading letters of its last label, as in the report-sanitizer EMAIL rule, so what follows those letters inside the label stays visible. No false-positive count was measured for a rule that reads the whole label.
Shape: an address whose last label is two or more letters followed by a digit or a hyphen (letters then digits, or an internationalized domain in its xn-- form): the letters are hidden, the rest of the label stays visible.
Hidden instead: the same address with a last label of letters only (hidden whole).
Card: none
Test: KNOWN MISS email-domain-tail-after-letter-run: the digits, or the hyphen and digits, after the leading letters of the last label stay visible, a last label of letters is hidden whole
