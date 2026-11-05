---
trdd-id: RPHJ64W1
title: Pick the best corpus projects for redacting Claude transcripts, log files and git history
column: complete
status: archived
created: 2026-11-05T02:35:23+0100
updated: 2026-11-05T03:11:34+0100
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
approval-datetime: 2026-11-05T02:35:23+0100
---

# Pick the best corpus projects for redacting Claude transcripts, log files and git history

Owner directive, 2026-11-05, verbatim: "decide yourself on anything else, but decide on verified facts. do not assume anything as true. give the security maximum priority and also use the plugin/projects i gave you to also implement automatic redaction of jsonl transcripts of claude, of log files, and of git history. there are plenty of those projects with the ability of doing that. examine, compare, and pick the best solutions."

Scope: three targets. (1) Claude Code JSONL session transcripts already on disk (~/.claude/projects/*/*.jsonl). (2) Log files (the janitor's own logs, plus other logs to be listed by the research). (3) Git history.

Sources: the 108 repos in _corpus_dev/secret-patterns/repos (untrusted; see clone.log, neutralized.txt, removed.txt there). Existing pieces to verify before reuse: hooks/secret-shield (rows.ts, register.ts), jr-redact (TRDD-2V7OAUPE), the trufflehog scan in the pre-push hook.

Constraints: security first. Every claim about a project rests on reading its code, never its README. Rewriting git history is irreversible: tools may block secrets before they enter history and may scan history, but any history rewrite runs only on an exact command the owner approves (RULE 0 of the owner's global rules). In-place redaction of transcripts and logs must never leave a broken or half-written file: validate, then replace atomically.

## Done when
 - [x] A comparison report names, per target, the best project or approach and why, each claim cited to file:line in the corpus.
 - [x] One implementation card exists per target, each citing this card.
 - [x] Every candidate listed in _corpus_dev/secret-patterns/neutralized.txt or removed.txt is excluded or its use is justified; _corpus_dev/ is gitignored and local to this machine, so the report or this card records the commit of each repo it cites.

## Approval log

- 2026-11-05T02:35:23+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-05 — Authority for this card: the owner directive quoted in the body; trddgrep recorded the main agent as issuer.
- 2026-11-05 — Closed by main-agent@ai-maestro-janitor: all three Done-when boxes hold; evidence in Notes (picks TRDD-11KWFU5L, TRDD-119JBB8C, TRDD-FXR55XCN; commits of the cited repos) and commit bc5a6c73.
- 2026-11-05T03:11:34+0100 — COMPLETE by main-agent@ai-maestro-janitor. spike done: three implementation cards exist, all three boxes hold.

## Notes

- 2026-11-05 — Comparison done: per target, the pick is CARD T (TRDD-11KWFU5L, transcripts), CARD L (TRDD-119JBB8C, logs) and CARD G (TRDD-FXR55XCN, git history). Neutralized-list check: 13 of the 16 repos on neutralized.txt are still in the corpus and marked NEUT in the report; three of them carry neutralized files and feed a pick as ideas only, no code: mogesjohnson_history-scrub and nikolareljin_leak-lock (CARD G), thesubtlety_agent-scrub (no licence, read for its in-place design only). The report is gitignored, so each card carries its own copy of the facts it relies on.
- 2026-11-05 — Box 3: the report records each repo's last commit DATE only, so the commits of the repos the picks cite are recorded here (git rev-parse HEAD of the local clones, 2026-11-05): maccydee_scrub-transcripts c5e1644c029a8e67700eeda0106886378d55df13; shubhajeet1207_redact (SpyMonk) a8dd65beefdb3571ad3c529ec46af39b78b4bc1c; devops247-online_shellclear c114a83c219ad5cc21da0282334a0b6eb8602adf; baditaflorin_agent-redact 70070037786110b4b913e87bd7d283c90fa89424; mogesjohnson_history-scrub 83d71243ce9eabe643a3550d5c5eda586d629455; nikolareljin_leak-lock 104ea59009db7b6c478d8c9a75482799708323a1; thesubtlety_agent-scrub 52609c48f26b9393c569028d22779cf51e78d157. Box 1 covers the picks: every pick was read and cited to file:line; the other 72 rows of the report were classified from README and grep only.
- 2026-11-05 — Box 3 was reworded on 2026-11-05 after review, from "the report records" to "the report or this card records", because the report records only each repo's last commit date. The commits of all 36 repos the report cites to file:line (its V rows), git rev-parse HEAD of the local clones on 2026-11-05: 0xelitesystem_agent-leaks b2fb953631a42821bf8667b149a5c2f597ad6eb3; akhmadgo_session-lens a1cef9418c419d0364be2db152b53503ec03cecb; allemz_git-regret 150904f3990450332a20f353d6c8971e9537c7ef; baditaflorin_agent-redact 70070037786110b4b913e87bd7d283c90fa89424; c10dev_secret-redact 7194836c68af72d0c6294d81b67a6c08933dcd86; cekuu35_supabase-secret-scanner df7858af6e77cd8f9f3b59191e5a63df60d5ece9; DeviousLabs_git-secrets-replacer 83d6cf2f9316924a18687fc85a4c492318e33d73; devops247-online_shellclear c114a83c219ad5cc21da0282334a0b6eb8602adf; genzagents_leakscan 7fc1e122a4a0cabd54a9fbaaed2e00b0c8c3950b; ihsnishnogl_noLeak d7e1860b6d341b23d6ba888904f07981a05efa0a; ItsTrinabha_leakhound b33ae6134543c387a8469d87ecb013f5601dd97d; jay-tank_secmend a785cd6a783860be395164effa04cbfba41b9845; kayhanyl_leakhound b973cb4c0085b7df6cec2b0e1089e2bdb8be5587; keithalindsay_git-secret-scan a5e87cc931e5a3d657a3aa82949553874ead5130; krishyaa06_prism-secret-scan fbb2891c8003eea8fc64f111ed3455aaa3835130; lelouchB_cc-scrub 6330c4affb32e466d2fe07af290f683a2af3dfec; lucas-lima-s_claude-skill-repo-audit 86d79b7b0412433a0afa9102ae8e26f774c98990; maccydee_scrub-transcripts c5e1644c029a8e67700eeda0106886378d55df13; mogesjohnson_history-scrub 83d71243ce9eabe643a3550d5c5eda586d629455; NickCirv_secret-scan 66eb3bc8157fe4ab710bb1ecf342bd1d31f1fc2f; nikolareljin_claude-reposec f04721f325c399fa355a60e5a5e8c92717c255e1; nikolareljin_leak-lock 104ea59009db7b6c478d8c9a75482799708323a1; OmK-security_Github-Secret-Scan-Skill dcb95e1b4977d962de909d76546162207b2e6be8; OrdinaryDev-in_keyguard-security-scanner c957d1907ba1282f9a0794cda02eaaf61dc25278; penumbraforge_gate 6685d4aa10cc1288f3dd1608d53718ae69d0f05c; Ranahmad1_gitscope fbf2ce5c2025d8f9ab60178eb01bfa90e211141e; RedBeret_git-clean-history d3c8e9bbc272e1d2b14cf8987122084ce63dbd45; ribato22_vibecheck 38f7173c94bcc64cbb21999bb9137bea885035d6; shubhajeet1207_redact a8dd65beefdb3571ad3c529ec46af39b78b4bc1c; thesubtlety_agent-scrub 52609c48f26b9393c569028d22779cf51e78d157; thinx-pro_agent-preflight 3861e5873eeedcaed386d38cad1e5b79991486dc; thinx-pro_trace-scrub 3a85aac4c85d8e90dfdfcaddf27a298eaf47d9fa; umeraamir69_secsentry 69d1d4abbdfe6bffa47eec2c3b297f73bd2a9d2a; Vampsecure-Labs_vamp-secrets-scanner 892bdc95c1809090369654eae9032f0ed2b8886e; Vasishta03_secret-scanner 6b8cba7155e11435e292d3ccd9768b491ae22031; zeexz_leakscan 9ad6ac2770313a3f1dd855935cc8e7379ce767a5.
