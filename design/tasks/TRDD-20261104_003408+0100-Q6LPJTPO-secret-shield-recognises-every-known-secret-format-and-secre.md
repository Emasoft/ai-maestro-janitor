---
trdd-id: Q6LPJTPO
title: secret-shield recognises every known secret format and secret-bearing context
column: design
status: tasked
created: 2026-11-04T00:34:08+0100
updated: 2026-11-04T00:34:08+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: security
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T00:34:08+0100
---

# secret-shield recognises every known secret format and secret-bearing context

## User request (verbatim, 2026-11-04)

> improve the heuristic of the janitor secret shield mod, so it will catch every possible secret knwon to you.

## Why

On 2026-11-03 a pm2 process dump put two PyPI tokens and a Dropbox app secret into a session. jr-redact (ten fixed formats, no key-name rule) hid only the OpenAI and Gemini keys. hooks/secret-shield/patterns.ts already has 19 token rules, a key-name assignment rule (SECRET_NAME / looksSecret) and URL passwords, so it covers that incident; this card widens it to every format and context known.

## Today (hooks/secret-shield/patterns.ts, 267 lines)

Token rules: private-key, anthropic-key, openai-key, stripe-key, github-token, aws-access-key, aws-secret-key, aws-session-token, slack-token, slack-webhook, google-api-key, jwt, sendgrid-key, pypi-token, npm-token, huggingface-token, bearer-token. Context rules: assignment by key name, url-password.

## Target catalog (each rule gets a fake-value test built by concatenation, and must not fire on the false-positive corpus)

- AI providers: Anthropic admin (sk-ant-admin01-), OpenAI admin and service keys (sk-admin-, sk-svcacct-), OpenRouter sk-or-v1-, Groq gsk_, xAI xai-, Perplexity pplx-, Replicate r8_, Fireworks fw_, LangSmith lsv2_pt_ and lsv2_sk_, Pinecone pcsk_, Tavily tvly-.
- Google: OAuth access token ya29., OAuth client secret GOCSPX-, refresh token 1//0, service-account JSON private_key (PEM).
- Code hosts and registries: GitLab glpat-, gldt-, glrt-, glptt-, glcbt-, glimt-, glagent-, runner GR1348941; Bitbucket ATBB; Atlassian ATATT3 and ATCTT3; RubyGems rubygems_; NuGet oy2 + 43; Docker Hub dckr_pat_; crates.io cio; JFrog AKC; SonarQube squ_, sqp_, sqa_; Buildkite bkua_.
- Cloud and hosting: Azure storage AccountKey= and SharedAccessKey= in connection strings, SAS sig=, Azure AD client secret (the 8Q~ shape); DigitalOcean dop_v1_, doo_v1_, dor_v1_; Heroku HRKU-; Fly.io fo1_ and FlyV1; Vercel vcp_, vci_, vca_, vcr_, vck_; Netlify nfp_ and nfc_; Cloudflare origin CA v1.0-; Alibaba LTAI; Tencent AKID; Supabase sbp_ and sb_secret_; Render rnd_; Pulumi pul-; Terraform Cloud .atlasv1.; HashiCorp Vault hvs., hvb., hvr.; Doppler dp.st., dp.pt., dp.ct., dp.sa.; 1Password ops_; age AGE-SECRET-KEY-1.
- Messaging and payments: Slack xapp-; Discord bot token and webhook URL; Telegram bot token (digits:AA + 33); Microsoft Teams webhook URL; Twilio SK and AC + 32 hex; Mailgun key- + 32 hex; Mailchimp 32 hex -us N; Stripe whsec_ and rk_; Square sq0atp-, sq0csp-, EAAA; Braintree access_token$production$; Shopify shpat_, shpss_, shpca_, shppa_; Facebook EAA long tokens; X/Twitter bearer (run of A then key); Dropbox short-lived sl. and sl.u.
- Dev services: Linear lin_api_; Notion secret_ and ntn_; Airtable pat + 14 . 64 hex; Figma figd_; Postman PMAK-; Sentry sntrys_, sntryu_, sntrya_; New Relic NRAK-, NRII-, NRJS-; Grafana glc_ and glsa_; Okta 00 + 40; Contentful CFPAT-; Mapbox secret sk.eyJ.
- Key material: PGP PRIVATE KEY BLOCK, PuTTY private key files, kubeconfig client-key-data and token:, JWK private members, wallet private keys (0x + 64 hex) in key-name context.
- Structural contexts: Authorization headers (Bearer, Basic, Token, Digest) and X-Api-Key, Api-Key, X-Auth-Token headers; credentials in any URL scheme; secret query parameters (token, access_token, api_key, key, sig, signature, password, client_secret, X-Amz-Signature, X-Goog-Signature); CLI flags (--password, --token, --secret, -p for mysql, curl -u user:pass, sshpass -p, docker login -p); ADO.NET Password= and Pwd=; netrc password lines; .pgpass lines; .git-credentials URLs; docker config.json auth; .npmrc _authToken and _auth; .pypirc password; AWS credentials file keys; Cookie and Set-Cookie session values.
- Key-name rule: extend SECRET_NAME with client_secret, private_key, signing_key, encryption_key, master_key, access_key, secret_key, session_key, cookie_secret, jwt_secret, webhook_secret, credentials, dsn, otp, totp_seed, mnemonic, seed_phrase, keystore_password, connection_string, auth_token; cover env, export, YAML, JSON, TOML, INI, XML elements, properties, PHP arrays and Python dicts.

## False-positive corpus (must stay unredacted)

Git SHAs, UUIDs outside a secret key name, lockfile integrity hashes (sha256-, sha512-), data: URIs and base64 images, placeholders and env references, public keys (ssh-rsa AAAA..., BEGIN PUBLIC KEY, Stripe pk_live_, Mapbox pk.eyJ), the AWS documentation example key, and code that names a secret without holding one.

## Open, for the design review

- Hand-curated list (above) versus porting the gitleaks default rule set (about 200 rules, MIT, RE2 syntax mostly JS-compatible) with a generator script. Either way a test can report coverage gaps against gitleaks rule ids when gitleaks is installed.
- Performance: one combined prefilter before the per-rule regexes, and a size-and-time test on a large tool result.
- The Python janitor scanners (scripts/lib/*_patterns.py) hold other secret patterns; a cross-check test should keep the two in step.

## Found during

TRDD-M1218EMH, after the 2026-11-03 pm2 environment dump.

## Approval log

- 2026-11-04T00:34:08+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
