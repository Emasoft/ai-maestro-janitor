---
trdd-id: BAQB9SYO
title: secrets-shield-scan skill scans a project for secrets fast, with Rust only where measured hot
column: design
status: tasked
created: 2026-11-17T13:46:50+0100
updated: 2026-11-17T16:19:06+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: feature
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-17T13:46:50+0100
---

# secrets-shield-scan skill scans a project for secrets fast, with Rust only where measured hot

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-11-17
- Column design. The owner answered the three design questions on 2026-11-17 (verbatim below). No code yet.
- The Design and Increments sections are main-agent's proposal of 2026-11-17, not yet confirmed by the owner; only the section "Owner request and decisions" is the owner's.
- NEXT ACTION (2026-11-17T16:18:42+0100, main-agent proposal; increment 0 is done): TRDD-L1I0FP5T increment 5, a core entry point that owns the pass order and takes a pass set; then increment 1 here. Literal gates get their own card after increment 5 and land only with a back-to-back measured gain, a gated-against-ungated differential over the whole shield test corpus, and a case-folding check of the case-insensitive rules.
- Prerequisite for increment 1: TRDD-L1I0FP5T increment 5 (one core entry point that owns the pass order). The skill must call that entry point and must not carry a pass order of its own.
- Release path: the skill reaches the owner's other computer only through a janitor release. Release 3.9.9 is blocked by two CPV findings from the run of 2026-11-17 12:16 (local report reports_dev/opus-main/cpv-inc3-20261117_121651+0100.txt): MAJOR, an absolute path on line 42 of the archived card TRDD-7KPG2PCO; MINOR REGEX_DOS at hooks/secret-shield/home.ts:39. Both need an owner answer.
- Release path update, 2026-11-17T14:41:48+0100: see the STATE line of the same time in TRDD-L1I0FP5T; the home.ts:39 blocker is addressed by janitor 988720bb, and the TRDD-7KPG2PCO line 42 blocker waits on CPV PR 278, a CPV release and a .cpv-version bump. This supersedes the release-path line above it.
- Increment 0 done, 2026-11-17T16:11:38+0100, by the increment 0 worker's report (local, not in the repo: reports_dev/sonnet-worker/20261117_160921+0100-shield-scan-inc0.md; one run per configuration, standalone bun 1.3.14, a shared host at load 8 to 111, so full-sample figures are load-confounded): the four core passes cost 0.231 CPU s/MB on the 91 MB pilot (home 60 percent, redact 39, cards 0.9, email under 0.1) and 0.353 on the 1.69 GB full sample; walk, first read and page-cache read take 2 to 5 percent of that CPU on a warm cache, but on the pilot the first read by one sequential reader (1.28 s, 73 MB/s) is about a fifth of the 6.0 s the four passes took at N=7 on the same pilot; a parallel read was not measured; cost is linear in size and no file reached the 30 s kill; bun worker processes gave 4.7 times at N=7 on the pilot. The pre-registered file-level gate formula gives MARGINAL (10.9 to 13.6 percent saving); a post-hoc per-file join gives 78 percent net on the pilot (runs back to back at one load) and 59 percent net on the full sample (load-confounded) for per-rule literal gates on the 52 token rules plus a home-literal gate, not yet measured as a gated run, with 0 soundness violations on the files that hit, after one unsound anchor was corrected (slackConfigAccessToken: its pattern has an unescaped dot). Not measured: a cold read at scale, the plugin engine, git history.
- Per-file kill, 2026-11-17T16:12:05+0100: increment 1 needs what increment 0 used, a child process killed with SIGKILL at a 30 s per-file limit and respawned on the next file, because a synchronous regex cannot be interrupted from its own thread.
- Pass set, 2026-11-17T16:19:05+0100 (main-agent proposal, open to the owner): the scan reports the secret types and payment cards by default, and email addresses and home paths only as options (sample: about 6,200 secret hits against 12,068 email and 50,731 home hits; the home pass is about half the CPU). This agrees with the owner order "both must detect and redact all 62 types of secrets" (TRDD-L1I0FP5T) if email and home paths are not among those types. Redact mode: open owner question, because rewriting home paths and email addresses inside project files can break code and config (a tool that reads a path from a config file does not expand ~); proposal: redact mode defaults to the scan's pass set. Finding lines: increment 1 detects on the whole file and locates findings only in files that hit; a multi-line key (a PEM block) needs the offset of its match, which the core passes do not return today except findCards and findEmails, so increment 1 may add a span-returning sibling of the entry point that shares its pass order.

## Owner request and decisions (verbatim, 2026-11-17)
- Request: "i need to scan 2 terabytes of projects and i need the secrets-shield scanner to be very very fast (better if rust optimized)"
- Answers to the three questions (1. which folders make up the 2 TB; 2. should the scan cover git history or only the checked-out files; 3. may main-agent go ahead with: measure, then a Rust front end with the existing core checking candidates, and Rust ports only for rules that measure slow):
  "1. its on another computer. i will install the janitor plugin there and execute the secrets-shield-scan skill there.
  2. optionally. by default it will only scan the current project folder and subfolders. gitignore must be respected by default, but optionally it must scan everything. same options for when redacting mode is on.
  3. yes, keep the rust code limited to what is performance critical."
- "note that git history redaction is complex. it can broke in progress merge resolutions, add conflicts, corrupt or lose synch with upstream, etc."

## Design
- A janitor skill named secrets-shield-scan, run by the owner on another computer after installing the plugin. Two modes: scan (the default; reads only, writes a findings report) and redact.
- Scope: by default the current project folder and its subfolders, with .gitignore respected. An option scans everything (gitignored and hidden files too). Redact mode takes the same scope options.
- Git history: an option, scan only. It reads the blobs reachable from all refs through git cat-file, read-only. History is never redacted: rewriting it can break merge resolutions in progress, add conflicts, and corrupt or lose sync with upstream (owner, 2026-11-17).
- Rules: the janitor core in hooks/secret-shield (every secret type the core defines, the card pass, the email pass, the home-path rule), called through the one entry point of TRDD-L1I0FP5T increment 5. The increment 4 gap list of that card says which report-sanitizer Python rule types the core lacks; those are added to the core, not to the skill.
- Output: one JSON line per finding with the secret type, the path and the line (and the blob id for history). The matched value is never printed, stored or sent to an outside model. A summary counts files scanned and files skipped by reason (gitignored, hidden, binary, over the size cap), so a clean result is never read as "no secrets": under the default scope a gitignored .env is not scanned.
- Redact mode writes the vault marker of TRDD-QM8YRCZ5 ([REDACTED-BY-SECRET-SHIELD. Type: <type>. ID: <UUID>]). Every redaction must be restorable: before the vault ships, redact mode refuses any file git cannot restore (untracked, gitignored, or changed since the last commit), so with the scan-everything option it refuses gitignored files until the vault exists.
- Rust: only what the measurement shows is hot. Candidates are the parallel walk with reading and the binary and size skip, and a literal prefilter only if the anchor count shows most files can be skipped. The accelerator sits behind an explicit flag; the parity test is identical findings with it on and off, on the fixture corpus and on a sample of at most 4 GB.
- Walker: confirm in the documentation of the walker used which files it skips by default (the Rust ignore crate is believed to skip hidden files and to honour .ignore files by default; unverified). Pinned fixtures: a tracked .npmrc is scanned; a tracked file that matches a gitignore pattern is scanned. Inside a repo, consider git ls-files -co --exclude-standard as the file set.
- Fresh machine: needs bun and a Rust build of the accelerator. Reuse the memgrep build path (scripts/memgrep/build.sh, scripts/memgrep/stage.sh, detector scripts/detectors/memgrep-binary-stale.py). A missing bun always stops the skill with the exact install command. A missing Rust build stops only a run that asks for the accelerator, with the exact build command; no silent slower path.
- Speed target: a MB/s figure set from the increment 0 measurement, on a sample of at most 4 GB (4 GB test-data cap). That figure is this host's; on the target machine the skill reports its own MB/s and skip counts.

## Increments
0. Measure, no build: classify each rule as anchored (has a fixed literal a prefilter can find) or anchorless, counting code sites only, not comments; time the core entry point on a sample of at most 4 GB of this host, one process and N parallel workers; time walk and read alone; say where the time goes. The increment 4 run of TRDD-L1I0FP5T is an instrumented replica on a loaded host, a lower bound only.
1. Scan mode on the core entry point, parallel bun workers, default scope with .gitignore, the scan-everything option, the git-history scan-only option, JSON-lines output with skip counts, fixtures, and a timing of parallel reads against the passes (cold where possible).
2. Rust accelerator for what increments 0 and 1 measure hot, behind a flag, with the on/off parity test.
3. Redact mode, gated on the vault (TRDD-QM8YRCZ5) for files git cannot restore; never history.

## Checklist
- [x] increment 0 measurement report
- [ ] TRDD-L1I0FP5T increment 5 landed (entry point)
- [ ] increment 1 scan mode with fixtures
- [ ] increment 2 accelerator with on/off parity
- [ ] increment 3 redact mode gated on the vault
- [ ] released in a janitor version and installed

## Notes and lessons learned

## Approval log

- 2026-11-17T13:46:50+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
- 2026-11-17T13:51:00+0100 — Note to the MANDATE line, by main-agent@ai-maestro-janitor: approved true and the mandate are the standalone defaults of trddgrep new. The owner's approval covers the request and the plan order (answer 3 of 2026-11-17, "yes"); the Design and Increments details are main-agent's proposal, open to the owner's changes (see the STATE block).
