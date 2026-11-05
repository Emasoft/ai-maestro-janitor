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

## url-password-over-1mb

Reason: (d) an open defect: a URL whose password alone is 1 MB is not hidden.
Shape: One URL with a password of 1 MB (1048576 characters).
Hidden instead: The same URL with a 256 KB password.
Card: TRDD-AGOEWF2E
Test: KNOWN DEFECT TRDD-AGOEWF2E url-password-over-1mb: one URL whose password alone is 1 MB is not hidden today, while the same URL at 256 KB is

## gitlab-body-under-20-chars

Reason: (c) a bound kept for a stated reason: the body floor of the 13 GitLab rules is 20 characters (hooks/secret-shield/rules/code-hosts.ts:21-22 and :32). GitLab documents no length; 20 is the shortest body of any GitLab rule in gitleaks v8.30.1 (gitlab.go), and a prefix followed by fewer characters reads as a name or a placeholder.
Shape: A GitLab prefix (glpat-) followed by 19 characters of letters, digits, underscore and hyphen, with a digit among them.
Hidden instead: The same prefix followed by 20 characters (hidden with the gitlab-pat marker).
Card: none
Test: KNOWN MISS gitlab-body-under-20-chars: a GitLab prefix followed by a 19-character body is not hidden, with 20 characters it is

## gitlab-body-without-digit-or-upper

Reason: (c) a false-positive trade-off stated at hooks/secret-shield/rules/code-hosts.ts:15-18: the rule requires a digit or an upper-case letter inside the body, which keeps all-lower-case kebab names and lower-case x placeholders visible. A real 20-character body has neither with probability (28/64)^20, about 6.6e-8 (computed, not measured on real tokens).
Shape: A GitLab prefix (glpat-) followed by 21 lower-case letters, with no digit and no upper-case letter in the body.
Hidden instead: The same body with one digit added (hidden with the gitlab-pat marker).
Card: none
Test: KNOWN MISS gitlab-body-without-digit-or-upper: a GitLab prefix followed by 21 lower-case letters is not hidden, with one digit added it is

## gitlab-legacy-unprefixed-token

Reason: (b) no source was found for the form: GitLab tokens issued before the prefixes existed have no leading literal and no published shape (searched: docs.gitlab.com/security/tokens, which lists only the prefixed forms, and the 15 gitlab rules of gitleaks v8.30.1 gitlab.go, each of which needs a prefix or a cookie name). A standalone rule for 20 letters and digits would hide ordinary identifiers.
Shape: 20 characters of letters and digits, with no name and no prefix before them.
Hidden instead: The same 20 characters after GITLAB_TOKEN= (hidden by the assignment pass, because the name says secret).
Card: none
Test: KNOWN MISS gitlab-legacy-unprefixed-token: a bare 20-character legacy GitLab token is not hidden, after GITLAB_TOKEN= it is

## gitlab-session-cookie

Reason: (d) an open defect: the gitleaks rule gitlab-session-cookie (_gitlab_session= followed by 32 lower-case letters and digits) has no rule in the shield yet; it is planned as family 2b of TRDD-Q6LPJTPO, and the name _gitlab_session is not a secret name to the assignment pass.
Shape: _gitlab_session= followed by 32 lower-case letters and digits.
Hidden instead: The same 32 characters after GITLAB_TOKEN= (hidden by the assignment pass).
Card: TRDD-Q6LPJTPO
Test: KNOWN DEFECT TRDD-Q6LPJTPO gitlab-session-cookie: _gitlab_session= followed by 32 lower-case letters and digits is not hidden, the same value after GITLAB_TOKEN= is
