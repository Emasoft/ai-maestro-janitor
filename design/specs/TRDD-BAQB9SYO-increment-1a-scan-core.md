# TRDD-BAQB9SYO increment 1a: scan core (file set, worker processes with a per-file kill, JSON-lines records)

Owning card: design/tasks/TRDD-20261117_134650+0100-BAQB9SYO-secrets-shield-scan-skill-scans-a-project-for-secrets-fast-w.md. Read its STATE lines "Increment 1 split" (18:09:16), "Line numbers" and "Timeouts" (18:30:36), "Line-rule check" (18:37:16), and the owner decisions section, before writing code.

Not in 1a: git history (1b); SKILL.md and the parallel-read timing (1c); Rust (2); redact mode (3). No change to hooks/secret-shield/ (the core): if the core needs a change, stop and report it.

## Decisions (main-agent, 2026-11-17; v1 reviewed by the advisor, v2 applies its six findings; later edits on top of v2 (D4 home-repo limit, D5 roots under an ancestor repo and ignored folders, D8 ancestor_rules_skipped, tests 12, 19, 22, 25, 26, 27, 28, 29, 30, the smoke --out; step E: root probe -co --exclude-standard, ignored_repos, tests 31, 32 and 33); not re-reviewed since)

D1 Name: the skill (1c) will be janitor-secrets-shield-scan, because all 64 skills carry the janitor- prefix and the janitor lists its capabilities as /janitor-* commands. 1a ships the CLI only.

D2 Files: scripts/shield_scan/scan.ts (driver), scripts/shield_scan/worker.ts (child process), scripts/shield_scan/fileset.ts (file set). Run: bun run <plugin root>/scripts/shield_scan/scan.ts [options] [root]. They import redactAll from hooks/secret-shield/pipeline.ts and carry no pass order of their own.

D3 Options: root (default the cwd); --all (gitignored and hidden files too, plus each repo .git/config, which can hold a token in a remote URL; never other .git content); --passes secrets,cards (default; email and home are opt-in, values validated with isPass, an unknown value exits 2); --jobs N (default min(8, cpus - 1), at least 1); --out PATH (default ~/.secrets_shield/scans/<root basename>-<YYYYmmdd_HHMMSS+zzzz>.jsonl, the folder created); --max-file-mb (default 64); --file-timeout-base S (default 30) and --file-timeout-per-mb S (default 5): the per-file limit is base + per_mb x size in MB.

D4 Out path: the out file and its temporary file are never scanned (excluded by real path). An --out (or default) path whose folder is inside a git work tree exits 2, because the findings file could be committed there. A path inside root but outside any work tree (for example root is the home folder) is allowed. Limit: when the home folder is itself a git work tree (a dotfiles repo), the default out path is refused too, and the error tells the user to pass --out; test 25 pins this.

D5 File set, recursive from root:
- A directory holding .git (a directory, or a file as in linked worktrees and submodules) is a repo root. Its default file set is git -c core.fsmonitor=false -C <repo> ls-files -co --exclude-standard -z (tracked plus untracked files that no ignore rule hides; .git/info/exclude and the global excludes file apply through --exclude-standard). WHY core.fsmonitor=false: the scanner runs git inside repos it did not create, and a repo-configured fsmonitor is a command git would run. A submodule (gitlink, mode 160000 in ls-files -s) and an untracked nested repo (listed as a directory entry) are recursed as their own repos.
- Gitignored count per repo: entries of git -c core.fsmonitor=false -C <repo> ls-files -oi --exclude-standard --directory -z.
- A git command that fails for a repo (a .git file whose gitdir is missing, a dubious-ownership refusal, a corrupt repo): a skip record with reason git-error for that repo, the run is incomplete; never a fallback walk of that repo, never a fatal stop, never safe.directory overrides. git missing from PATH: exit 2.
- A directory outside any repo is walked whole; the summary counts such directories (non_repo_dirs) so a reader knows no ignore rules applied there. A directory that cannot be listed: a skip record with reason unreadable-dir, the run is incomplete.
- A root with no .git of its own under an ancestor that has one (the nearest ancestor .git entry, directory or file; lstat): the probe is git -C <root> ls-files -co --exclude-standard -z (tracked and untracked files that are not ignored). A git failure (null): a skip record git-error for the root path ".", the run is incomplete, never a walk. Output: the root is listed as a repo with the ancestor rules, the listing reused (one listing per root). No output (the ancestor ignores every path under the root, or the root is empty): the root is walked as a plain folder (non_repo_dirs counts it) and the repos nested under it keep their own rules. An empty listing is not a failure; failure and emptiness stay apart.
- Ignored folders of the root repo, and of the repos under it, are not scanned by default, nested repos inside them included; --all scans them (gitignored_entries and ignored_repos are the signals in default mode).
- Known limit of the rule above (step E, decision of the main agent under the autonomy rule; reversible, open to the owner veto, not owner-authorized): the ancestor rules apply when they leave anything under the root listed; when they hide everything under it, the root is the explicit choice of the user and is walked plain. Cost: the -co probe scans LESS than the tracked-only probe of commit 92eb3472 in layout E: an ancestor .gitignore "proj/*/" (it hides the subfolders of the root, not the root and not its loose files), an untracked proj/notes.txt and a nested repo proj/inner. The tracked-only probe is empty there (0 bytes: measured by the main agent with raw git 2.56.0; not measured by the step E worker or by any test), so 92eb3472 walks proj plain and scans inner; the -co probe lists notes.txt, so the ancestor rules apply and inner is skipped. So whether nested repos in ignored folders are scanned depends on whether one other path under the root stays listed. Limits of ignored_repos: it counts a repo only when it is the ignored folder itself or a direct subfolder of it; a repo two or more levels below an ignored folder entry is skipped and not counted; an ignored folder that cannot be listed adds nothing. --all scans them.
- --all walks the filesystem: every file, hidden and ignored ones too; inside .git only the config file.
- Regular files only (lstat): a symlink counts as skip symlink (never followed); a FIFO, socket or device counts as skip special (never opened). A tracked path that no longer exists counts as skip missing.
- Paths with spaces, quotes or newlines must work (-z everywhere, no shell).

D6 Per file: over --max-file-mb: skip over-size (a record); read the bytes (a read failure: skip read-error, a record); a NUL byte in the first 8192 bytes: skip binary (counted); decode as UTF-8 (invalid bytes become U+FFFD). whole = redactAll(text, homes, passes).hits with homes = [os.homedir()]. If its total is 0 the file has no findings and is not located. Else locate: split on "\n" (strip one trailing "\r"), run redactAll on each line; located findings are the per-(kind, line) counts; per kind, unlocated = max(0, whole[kind] - sum of the line counts of kind).

D7 Workers: N child bun processes running worker.ts, fed one file at a time over stdin JSON lines; each replies with the whole-file hits first, then the line hits, or a skip. The driver arms a timer per file at the D3 limit. No whole-file reply by the limit: SIGKILL the child, record skip timeout, respawn. Whole-file reply but no line reply: SIGKILL, emit the whole-file counts as unlocated findings (counted as unlocated_timeout, not a skip), respawn. A child that exits without a reply: skip crash, respawn. Fault injection for tests only: when the environment variable SHIELD_SCAN_TEST_LOCATE_DELAY_MS is set, worker.ts sleeps that long between the whole-file reply and the locate pass (a WHY comment says it exists only so the locate-kill branch can be tested with the real kill path).

D8 Records, JSON lines, UTF-8, one object per line, never a matched value or any text of a scanned file:
- {"type":"finding","path":"<relative path>","kind":"<kind>","line":<n>,"count":<n>}
- {"type":"finding","path":"<relative path>","kind":"<kind>","line":null,"count":<n>} (unlocated)
- {"type":"skip","path":"<relative path>","reason":"timeout|read-error|over-size|crash|git-error|unreadable-dir"}
- {"type":"summary", ...} as the last line.
Canonical order: by path (UTF-8 byte order), findings before skips, line ascending with null last, then kind; the summary last. Paths relative to root with forward slashes. Summary fields: plugin_version (from .claude-plugin/plugin.json), core_sha256 (sha256 over the sorted relative paths and bytes of hooks/secret-shield/*.ts and hooks/secret-shield/rules/*.ts), passes, scope (default or all), repos, non_repo_dirs, ancestor_rules_skipped, files_scanned, bytes_scanned, skipped by reason (binary, symlink, special, missing, over-size, read-error, timeout, crash, git-error, unreadable-dir), gitignored_entries, ignored_repos, findings (sum of counts), files_with_findings, unlocated_timeout, complete, elapsed_s, mb_per_s, jobs. No kinds list in 1a: the core exports no full kind set (LABELS in patterns.ts is not exported; TOKEN_ORDER holds token rules only), and adding one is a core change with a report-sanitizer re-pin, left to a later increment. ignored_repos (integer) counts repos found by lstat in the ignored folders of a listed repo (the ignored folder itself, or a direct subfolder of it, one readdir, never deeper): repos the default scope did not scan; deeper repos are not counted; always 0 with --all. ancestor_rules_skipped (boolean) is true only when the root has no .git of its own, sits under an ancestor repo, and the ancestor lists nothing under it (it ignores every path under the root, or the root is empty), so the root is walked plain: it is the only signal that an ancestor repo ignore rules did not apply to the scan.

D9 Exit codes: 0 complete with no findings; 1 complete with findings; 3 incomplete (any timeout, read-error, crash, git-error or unreadable-dir skip), whatever the findings; 2 usage or fatal error. stdout: the summary line and the out path only. stderr: fixed-text errors, never file content.

## Tests: tests/test_secrets_shield_scan.py

pytest with real git and real bun, opted in the way tests/test_transcript_redact.py does (pytest.mark.real_subprocess; read tests/sandbox_guard.py), and following that file for a missing bun. Fixtures built in tmp_path at run time; every token assembled from fragments at run time (no literal secret in the file); GIT_CONFIG_GLOBAL points at a temp file in every test so the host config never leaks in; every test passes an explicit --out under tmp_path and --jobs 2. One focused test each:
1 a tracked file with a token gives a located finding at the right line, exit 1;
2 a gitignored .env with a token is not scanned by default (gitignored_entries counts it) and is scanned with --all;
3 a tracked hidden file (.npmrc) is scanned by default;
4 a tracked file that matches a gitignore pattern (force-added) is scanned;
5 an untracked, not ignored file is scanned;
6 an untracked nested repo is scanned as its own repo and its own .gitignore applies;
7 a submodule is recursed (protocol.file.allow=always for the local add);
8 a linked worktree inside root (.git as a file) is a repo root;
9 a .git file whose gitdir does not exist gives skip git-error and exit 3;
10 a tracked path deleted from disk counts as skip missing;
11 a symlink to a file with a token is not followed;
12 a FIFO is counted as skip special and never opened (assert the count and the exit code, not the elapsed time);
13 a .git/info/exclude pattern hides a file by default;
14 a pattern in the global excludes file hides a file by default;
15 a folder that is not a repo is walked whole and counted in non_repo_dirs;
16 --all scans .git/config (a token in a remote URL) and default mode does not;
17 file names with a space and with a newline;
18 a binary file with a token is skipped as binary;
19 a forced timeout: a fixture holding only one file of a few MB, with --file-timeout-base 0 --file-timeout-per-mb 0.001, gives skip timeout and exit 3;
20 a forced locate kill (SHIELD_SCAN_TEST_LOCATE_DELAY_MS above a small limit) gives unlocated findings, unlocated_timeout 1, and no skip;
21 an unterminated private-key header: hits after it are located per line;
22 a whole-file surplus: a hit that only a window of several lines forms (build it from the gitlab session-cookie rule in hooks/secret-shield/patterns.ts, about lines 326 to 388; read the code to build the shape) gives an unlocated finding; if no such shape can be built from that code, report it and record the unlocated branch as untested on the card instead of writing the test;
23 an --out inside a git work tree exits 2; with HOME pointed at tmp_path the default out path lands under tmp_path; the findings file never holds a token value;
24 two runs give identical records apart from the timing fields of the summary.
25 with HOME pointed at a temp git repo, a run with the default out path exits 2 and names --out on stderr;
26 the root is a subfolder of a repo (no .git of its own) and the repo tracks a file under it: the root is listed with that repo rules, so a gitignored file holding a token inside the subfolder is not scanned (gitignored_entries counts it), a tracked file with a token there is found, and files above the root are not scanned;
27 the ancestor repo lists nothing under the root (all of it is ignored: a .gitignore of "*", then a pattern that ignores a parent folder of the root): `git -C <root> ls-files -co --exclude-standard -z` is empty, so the root is walked as a plain folder (non_repo_dirs counts it) and its own files and the nested repo under it are scanned, never an empty scan;
28 ignored folders are not scanned by default, a clone under an ignored vendor/ included (gitignored_entries counts vendor/; ignored_repos is 1, because vendor/lib is a direct subfolder of the ignored vendor/); --all scans them, the clone and a loose file there included;
29 an ancestor repo with .gitignore "proj/*" and root = <ancestor>/proj: the ancestor lists nothing under the root (all of it is ignored), so the root is walked plain and the repo nested under it is found and scanned, exit 1;
30 the ancestor .git cannot be used by git (a .git file whose gitdir is missing): the root gets a git-error skip of "." and exit 3, never a plain walk;
31 a root that is a new subfolder of a repo with no tracked file under it (.gitignore node_modules/, a committed file outside the root; a.txt and node_modules/x.txt under the root each hold a token): the -co probe lists a.txt, so the repo rules apply and only a.txt (line 1) is found; repos 1, non_repo_dirs 0, gitignored_entries 1, ancestor_rules_skipped false, exit 1;
32 layout E (an ancestor .gitignore "proj/*/", an untracked clean proj/notes.txt, two committed nested repos proj/inner and proj/group/deep whose files hold a token, root = proj): default exit 0, no findings, gitignored_entries 2, ignored_repos 2, repos 1, ancestor_rules_skipped false; with --all exit 1 and both inner/b.txt and the group/deep file are found (also the first test of --all beneath an ancestor);
33 a repo two levels below an ignored folder (ancestor .gitignore "proj/*/", repo proj/a/b/deep, loose proj/notes.txt, root = proj): default exit 0, no findings, ignored_repos 0 (pins the depth limit: a repo two or more levels below an ignored folder entry is skipped and not counted).

## Checks (the worker runs these, saves each output and reads it whole)

- uv run --directory <J> pytest tests/test_secrets_shield_scan.py -q (this one file only).
- uv run --directory <J> ruff check tests/test_secrets_shield_scan.py; uv run --directory <J> mypy tests/test_secrets_shield_scan.py --ignore-missing-imports; uvx --with pyright pyright tests/test_secrets_shield_scan.py.
- tsc --noEmit --strict on the three .ts files with bun types if they are installed; else say so and give the errors that are only missing bun or node types.
- ubs on each new file alone (ubs <file>), quoting each summary.
- A smoke run of the scanner on the janitor repo itself, default scope, with --out outside any git work tree (D4 refuses reports_dev, which is inside the janitor work tree): exit code, files_scanned, mb_per_s, skips.
- No commit: the main agent commits.
