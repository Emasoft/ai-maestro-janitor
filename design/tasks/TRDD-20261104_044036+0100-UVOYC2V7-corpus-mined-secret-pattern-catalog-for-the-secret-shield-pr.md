---
trdd-id: UVOYC2V7
title: corpus-mined secret-pattern catalog for the secret-shield provider step
column: dev
status: tasked
created: 2026-11-04T04:40:36+0100
updated: 2026-11-04T04:54:19+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: spike
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T04:40:36+0100
---

# corpus-mined secret-pattern catalog for the secret-shield provider step

Derived from TRDD-Q6LPJTPO (the provider-catalog step). Builder: scripts_dev/secret-mining/build_catalog.py (gitignored).

## Goal
Turn the 132 corpus-mining reports into one machine-checked catalog of secret-detection patterns, so that TRDD-Q6LPJTPO's provider-catalog step can pick rules from real sources rather than from memory. The reports are an INDEX. Every pattern is re-extracted from the cited source file. A miner's copy is only a cross-check, because miners read files through a live tool-output redactor (jr-redact) whose [REDACTED:aws-key] and [REDACTED:password] markers appeared in miner tool results; three reports captured a marker in place of source text.

## Inputs (all local, gitignored)
- Reports: reports_dev/secret-shield/corpus-mining/<owner_repo>.md (layout: verdict, commit, license, ## Safety, ## Structured rule files, ## Patterns with `### P<n>` blocks carrying `- source: path:line|path:A-B`, `- literal: <kind>`, a `~~~regex` fence or a composed summary, ## Ideas, ## Skipped).
- Sources: _corpus_dev/secret-patterns/repos/<owner_repo>/ (untrusted, read as text only).
- _corpus_dev/secret-patterns/manifest.tsv (name, commit, license file, date) and neutralized.txt (renamed agent files).

## Extraction rules
- NEVER execute, import or decompress corpus content. Python sources are parsed with `ast.parse` and constants are read with `ast.literal_eval` on literal nodes only. TOML uses `tomllib`, JSON uses `json`, YAML uses `yaml.safe_load` (`uv run --no-project --with pyyaml python -I`), CSV uses `csv`.
- Embedded patterns: take the delimited literal at the cited line or range. Kinds:
  - python-raw and python-str, including triple-quoted and verbose (`re.VERBOSE`) literals, and implicit concatenation of adjacent literals;
  - js-regex `/.../flags` and js-str;
  - go-raw (backtick) and go-str;
  - rust-raw (`r"..."`, `r#"..."#`);
  - ruby-regex `/.../flags` and `%r{...}`;
  - yaml and toml values;
  - docs (Markdown tables: strip backtick spans and `\|` pipe escaping).
  The miner's `literal:` label is a hint; trust the source syntax.
- Unescape to the effective regex: python-str via literal_eval, go-str via Go escapes, js-str via JS escapes, raw kinds unchanged. Record flags (inline `(?i)`, re.I/re.X, JS/Ruby suffix flags).
- Structured rule files listed in a report: parse the whole file with the safe loader and take the regex from the key the report names (gitleaks TOML `regex`, YAML `regex`/`pattern`/`test`, JSON `pattern`). For Python tables use ast over the cited range. For TS, Go and Rust tables use delimiter extraction over the cited range.
- A block whose cited location holds no extractable literal gets status needs-reconstruction, with its range. That is the honest state of runtime-assembled patterns.

## Output (reports_dev/secret-shield/corpus-mining/)
- `_catalog.jsonl`, one row per pattern: repo, commit, license (SPDX if known), path, line, source_type (embedded|structured), kind, raw, regex, flags, label (provider and secret kind from the heading or the rule id), keywords, entropy, validation, miner_match (same|differs|none), status (extracted|needs-reconstruction).
- `_catalog-dedup.jsonl`: key = (regex, normalised flags). Each row lists every source. The canonical source is the first with a permissive license (MIT, Apache-2.0, BSD, ISC), else the first. Count how many sources are gitleaks-derived (a gitleaks TOML or a port of one).
- `_catalog-summary.md`:
  - counts per repo and in total;
  - extracted versus needs-reconstruction;
  - miner_match tallies;
  - dedup reduction;
  - license breakdown, with no-license, GPL, AGPL and CC-BY-SA rows called out.

## Verification (by script, never by printing pattern text: the session's tool output is redacted)
- Every report block maps to exactly one catalog row. Every structured file's row count equals its recount.
- miner_match=differs rows are listed by repo and block id only.
- Each extracted regex compiles under Python `re` (record whether it compiles; RE2-only syntax is noted, not fixed).

## Out of scope here (later cards)
- Gap analysis against hooks/secret-shield/rules.
- The ideas digest.
- Adopting any rule. Adoption follows the license policy the owner sets.
- Rule generation from this catalog into hooks/secret-shield/rules is scripted, never written by an agent reading the catalog, because tool output is redacted.

## Approval log

- 2026-11-04T04:40:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-04T04:48:09+0100 — column → dev by main-agent@ai-maestro-janitor.
- 2026-11-04 — main-agent@ai-maestro-janitor: this card was added in c502b553, whose commit message is a stale scratch-file error line, not a description; the WHY is in 5fc8d345. Whether to reword c502b553 (and 5fc8d345, which names it) before the next publish is the owner's decision, open.

## Corpus (reproducible)

133 public GitHub repositories, cloned 2026-11-04 with:
`GIT_TERMINAL_PROMPT=0 GIT_LFS_SKIP_SMUDGE=1 git -c core.hooksPath=/dev/null -c core.symlinks=false -c protocol.file.allow=never clone --depth 1 --single-branch --no-recurse-submodules https://github.com/<owner>/<repo>.git`
(add `GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_NOSYSTEM=1` on a re-clone). Agent instruction files inside the clones were renamed inert before any agent read them. Archducal-woodthrush229/envleaks was quarantined unread (a README plus an unexplained zip, a suspected malware lure); neshboy/secretsweep-ci has no refs on GitHub.

owner/repo at the commit mined (first 12 hex):

- 0x1Adi/Klarion 0288f7c06c2e
- 0xelitesystem/agent-leaks b2fb953631a4
- aboutBilal/spillkit 62495eed0f46
- adventurewave-labs/secret-scan 3f83c00a4701
- agenticluke/open-source-safely-plus fce56d4a552d
- ajwann/secret-leak-response 70930c89ee01
- akhmadgo/session-lens a1cef9418c41
- akshay-th/agent-session-audit 76e6781b326d
- Alexnikolaev1/sentinel 34b5141dd0dc
- alexno10/lickyGit 6f2dd41e6f91
- aliasfoxkde/aegis 84edb97b06df
- allemz/git-regret 150904f39904
- andrewluxem/dry-run-gate d2253a52e92b
- ankursharma0612/DataSentinel a11042e4c724
- AnshumanAtrey/gitleaks-github-secret-scanner b2bbe6142f5a
- Archducal-woodthrush229/envleaks d6855ef77f6f
- Aryan2vb/secretscan ae0dba4a2977
- aryansrivastava707-cpu/Secret-Sweep 3a3dbc431fe0
- asolfre/privacheck 9fea59476241
- at0m-b0mb/Vigil-Secret-Scanner c716793fabe5
- avelor-es/pyx 45c27394dec9
- baditaflorin/agent-redact 700700377861
- Bl4ckSkul1/haakjs 788110f06d30
- Bl4ckSkul1/haakleaks 0a3647413e66
- brokeexee/RotationLedger 3713adb45f42
- c10dev/secret-redact 7194836c68af
- CaoQuocViet/git-wipe 57e0ea6b0c52
- cekuu35/supabase-secret-scanner df7858af6e77
- codewithshreyasshetty/pii-sentinel d074e6ec3e88
- constantinshafranski-arch/github-secret-sweep b00154699bc2
- CorneiZeR/secret-guard-skill 68a9b54a1918
- darshanbm575/secrets-management-vault-demo 9a6e50fcc579
- dcode-co/dcode_redaction f626edd4683d
- densyy/github-secret-scanner 8e0a9f502e2e
- deoktr/shcln 67180aaf3fc5
- DeviousLabs/git-secrets-replacer 83d6cf2f9316
- devops247-online/shellclear c114a83c219a
- dsdugal/redact cb1a501f6d0f
- elementalsouls/Claude-OSINT c359ec1b44d0
- EMAD11223344/anubis-guardian 3db7f12ab95e
- ExploitCraft/VaultHound c82e231d6788
- ezekieldunyo/SecurePush 2f0ca6ec87d6
- genzagents/leakscan 7fc1e122a4a0
- git-pkgs/secrets ea0a824574b8
- GiTaDi-CrEaTe/repo-bleed 82f32f3a4c77
- goncaloneves/veil 0e57a35adc8a
- harekrishnarai/flowlyt 47671ea6214d
- haseeb2006-bit/credential-leak-scanner e2320b68e697
- HodeTech/Leakwatch eaaabc46db88
- hussain-alsaibai/tiny-secret-mask 86182b2fbff0
- ihsnishnogl/noLeak d7e1860b6d34
- ItsTrinabha/leakhound b33ae6134543
- jahanzaibmir/snitch 31fedf148853
- jay-tank/secmend a785cd6a7838
- jay240322/Secura 44fdc110e5e6
- jrlprost/claude-code-mods 9f789939f4b0
- juan-rome/secret-leak-scanner 065511fd9186
- kansal-mukul/mcp-security-sanitizer-server 64e43c4c7e6e
- karix-ai/security-skills 5b212d5c5947
- kayhanyl/leakhound b973cb4c0085
- keithalindsay/git-secret-scan a5e87cc931e5
- kkcyber2/secretsweep e7b9939fbe93
- Kolenkovskin/untrusted-content-guard ac5dc4e3868e
- konraddzbik/preflight-check-skill 6b2bdb04b267
- Kopachelli/session-export fdef252dd50c
- krishyaa06/prism-secret-scan fbb2891c8003
- ksprashu/gpg-cleanup-script 1b95cba64803
- lanaotouy/pysecscan-secrets-insecure-code-static-scanner 5afe531d2e58
- lelouchB/cc-scrub 6330c4affb32
- lifeofpi-lgtm/workspace-security-review 5a031ff688a1
- lucas-lima-s/claude-skill-repo-audit 86d79b7b0412
- macbuildssys/secret-scanner c7c38756c1f2
- maccydee/scrub-transcripts c5e1644c029a
- MahyarNemati/secret-scan 5e04b8aee126
- mazen160/secrets-patterns-db 24984df1a3f7
- milad-ahmd/env-secrets-guard ac836ee5cee7
- milad-ahmd/skills-doctor 931b8966d19f
- mogesjohnson/history-scrub 83d71243ce9e
- MrLouisWright/bundle-secret-guard 1bc5b43abbde
- myanptl/keyhound 3d8aeb1b86ff
- neshboy/secretsweep-ci (no commit)
- NickCirv/secret-scan 66eb3bc8157f
- nikolareljin/claude-reposec f04721f325c3
- nikolareljin/leak-lock 104ea59009db
- nitayani477-sys/github-secret-scanner 3f304bbc3553
- nt11111/final-app-push 5a327e919a8b
- OmK-security/Github-Secret-Scan-Skill dcb95e1b4977
- open-agent-skills/secret-leak-detector 21919d3b5f85
- OrdinaryDev-in/keyguard-security-scanner c957d1907ba1
- pbs002-s/preflight-sec fff730af7638
- penumbraforge/gate 6685d4aa10cc
- pierrenode/hermes-redaction-pack febd8bfe9971
- pinion05/pi-cc-compact 81df7326d683
- PrajwalVijaykumar123/dockerfile-security-linter 7152375e520f
- project-feldspar-resources/feldspar-scan a8a6eda13ed8
- Raghuramgrr/mise-sentinel 19fab100be0b
- ramtoo-cell/ai-safety-selective-scrubbing 9854aa82472a
- Ranahmad1/gitscope fbf2ce5c2025
- RedBeret/git-clean-history d3c8e9bbc272
- renanbotasse/KeyScan bf3dbebb1d63
- rezmoss/leakscan b21f054d3056
- ribato22/vibecheck 38f7173c94bc
- Rifat024/secrets-guardian 9451168e1641
- safouanb/keyburn 8cb58abf34d6
- ShadowGuard-AI/misconfig-configsecretscanner 54792d0619a4
- shcherbak-ai/omerta e7bf793e86e5
- Shivakumarpittla/secret-leak-detector 9491daa1a235
- shubhajeet1207/redact a8dd65beefdb
- SiteQ8/Kashif 2f38fc2d7039
- siuee/findApiKeys a553b7e1de70
- sriharifortitude/credsweep b441774d74c7
- SumitDalavi/secret-sprawl-remediation-bot ec2a02abb086
- sunglasses-dev/sunglasses 6a39777f9e6f
- Supp3r-Man/sec-secrets-scanner b9da11a457fa
- surfnterd/claude-code-secret-scan 5480aedf75d6
- Tacuns/vibe-aegis 32ef769f5a19
- taksh1507/secret-guard 2c1e480cef0d
- tarak-09/secret-sweeper 0fc62a8e1288
- thesubtlety/agent-scrub 52609c48f26b
- thinx-pro/agent-preflight 3861e5873eee
- thinx-pro/trace-scrub 3a85aac4c85d
- torifo/skills-secret-scan 9f34aa7b20bb
- umeraamir69/secsentry 69d1d4abbdfe
- Vampsecure-Labs/vamp-secrets-scanner 892bdc95c180
- Vasishta03/secret-scanner 6b8cba7155e1
- Vibe-Marketer/no-more-leaked-keys aecb85450703
- wundercorp/cleaner-skill 0c711d76c55f
- yourpwnguy/rivet fd855f574872
- Z3phyr1s/gleak 20a862ea7ea6
- ZakariaHibaoui2/secrets-scanner f18287db49f6
- Zavelinski/secret-scan d88fe64709e4
- zeexz/leakscan 9ad6ac277031
- zumermalik/ash-key 19b5fcfaf9af

## Done when

- [ ] every report block maps to exactly one catalog row
- [ ] every structured file's row count equals its recount
- [ ] each extracted regex is recorded as compiling or not under Python re
- [ ] miner_match=differs rows are listed by repo and block id
- [ ] _catalog-summary.md written with the license breakdown
