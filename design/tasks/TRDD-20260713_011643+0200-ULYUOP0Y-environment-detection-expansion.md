---
trdd-id: ULYUOP0Y
title: Expand /janitor-identify-environment into a full secret-safe environment prober
column: complete
created: 2026-07-13T01:16:43+0200
updated: 2026-07-13T02:05:00+0200
current-owner: ai-maestro-janitor
task-type: feature
scope: project
release-via: publish
relevant-rules: [1]
parent-trdd: db169d9e
implementation-commits: [eca37bb, e2a929a, 1ad7a5b, 2eb64aa, fbd1ef6]
last-test-result: pass
---

# Expand /janitor-identify-environment into a full secret-safe environment prober

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-13

**DONE. Shipped on `main`, unpushed.** ruff clean; back-compat tests green (10);
env_detect tests green (55). Live run on this host produced a correct full report.

**2026-07-13 WAVE-2 addendum (user expanded the ask):** added git repo (remotes +
GitHub slug, branches + descriptions + last-commit, active git hooks honoring
core.hooksPath), GitHub branch-protection **rulesets** + repo meta (`--online`, via
`gh`, fail-open), **wikimem** 3-scope sizes, installed/enabled **plugins** + hook
events + janitor version/staleness + last marketplace/version upgrade, Claude **auth
mode** (API vs subscription; tier needs a live probe), and the token-economy tools
(tldr/distill/fastedit/memgrep/lean-ctx). **Delivery changed per the user:** the
default run now WRITES the full detail to `reports/identify-environment/<ts>-env.json`
(fail-open) and prints only a COMPACT digest + the path, so the caller's context holds
the summary not the whole object. `--online` gates the only network probes; `--json`
prints the raw object to stdout. Verified live: git (6 branches, `.githooks`), GitHub
(3 baseline rulesets), wikimem (42/21/52), plugins (35/76, janitor v0.41.0 up-to-date),
JSON valid + secret-scan clean.

- `scripts/lib/env_detect.py` — NEW pure decision layer (env-injectable, secret-safe,
  fail-open, no network). All classifiers + parsers live here.
- `scripts/identify_environment.py` — REWRITTEN thin I/O layer over env_detect; keeps
  the back-compat public fns/keys (`detect_terminal/detect_os/detect_sandboxing/
  gather/_render`) so the existing test still passes; adds `--fast`.
- `commands/janitor-identify-environment.md` — describes the new matrix + flags + safety.
- `tests/test_env_detect.py` — 44 pure tests (incl. the secret-never-leaked battery).

**2026-07-13 WAVE-3 addendum (user expanded again):** added the authenticated **gh CLI**
user + scopes + working-state (offline from hosts.yml; `--online` confirms live —
verified `Emasoft`, never captures the token); **GitHub Actions** — installed workflows
+ third-party actions used + **Claude-action presence** + CI **platforms** (local read);
**releases** — GitHub releases + **PyPI/npm(also bun)/crates.io** presence for the
project's package name (`--online`); **Homebrew tap** detection + the **Tap-Trust**
requirement note (Homebrew 6.0.0, 2026-06-11 — third-party taps need explicit
`brew trust`; researched via web); **fork/collaboration** (isFork + upstream, from gh or
an `upstream` remote); and **repo topology** (single-project vs mono-repo, single vs
multi-git via submodules/nested-repos/symlinked-repos, single vs mixed language).
Verified live: gh `Emasoft` ✓, 6 workflows (no Claude action, linux), releases present,
topology single-project/single-git/python; registries/fork/homebrew correctly EMPTY
(this repo is a Claude plugin, not published/forked/a-tap). 73 tests green, ruff clean.

**NEXT ACTION:** nothing here — complete. Publishing (NON-EXEMPT) awaits the user.

**Two bugs the LIVE run caught (fixed, both are the SAME class as the motivating
finding — an anchor that a subprocess loses):**
1. **TTY read from self → always `??`.** Claude Code's Bash tool spawns the probe
   subprocess with NO controlling terminal, so `ps -o tty= -p <self>` reports `??`
   inside a fully interactive iTerm session → the tool mislabeled itself headless +
   "background agent". Fix: `_session_tty()` walks the ancestry and returns the FIRST
   real tty (the `claude`/login-shell ancestor). This is the SAME lesson as the
   `$ITERM_SESSION_ID`-absent self-trigger failure (see TRDD from the same session).
2. **NAT fooled by Tailscale CGNAT.** `100.64.0.0/10` is not in Python's `is_private`,
   so a Tailscale `100.x` address read as a public IP → "not behind NAT". Fix:
   `classify_nat` skips tunnel/VPN interfaces and treats CGNAT as non-routable.

**SUPERSEDED — do NOT carry forward:** none.

## Why

The motivating session found the terminal-environment detection failing *when it was
needed most*: a resumed/detached session loses `$ITERM_SESSION_ID` and its ancestry is
reparented to launchd, so both the env-var anchor and the ancestry-walk anchor break —
exactly in the sessions where auto-recovery matters. The user then asked to make the
`/janitor-identify-environment` skill detect the environment *comprehensively* and
correctly.

## What it detects now

terminal app (all known macOS/Linux/Windows terminals, by ancestry + env signals) &
multiplexer; OS + kernel + Windows edition + WSL; filesystem (+ network-mount flag);
CI/remote execution (GitHub Actions & friends); containers/VMs/sandboxes (incl.
`systemd-detect-virt`); editor/IDE + Claude Code CLI-vs-desktop; interactive-vs-headless,
background-agent, and LINKED-git-worktree; network — proxies (credential-masked), VPN /
Tailscale / WireGuard / WARP, gateway, behind-NAT, DNS, firewall, interfaces, and
locally-listening services (exposed-off-host flagged); python venv/conda/pyenv/uv;
AWS/Azure/GCP footprint (presence only); user; PATH; installed compilers / runtimes /
package managers / dev tooling (with versions); and configured MCP servers.

## The design — pure decisions, impure edges, three hard invariants

Same split the codebase uses everywhere (`fleet_recovery` vs `fleet_inject`,
`classify_argv` vs the Popen patch): `env_detect.py` is PURE — it takes the already-
gathered facts (an env dict, injected `which`/`exists`, or a captured command string)
and returns a plain dict/list, so it is unit-testable with zero host dependence. The CLI
does the bounded, fail-open I/O and hands raw text to the pure parsers.

Three invariants that make a credentials-adjacent diagnostic trustworthy:

1. **Never emit a secret VALUE.** `is_secret_key` (broad regex, tiny allow-list for
   region/profile) gates every value; proxy URLs are masked to strip `user:pass@`; MCP
   endpoints keep only `scheme://host` (any `?token=` / `env` value dropped); cloud
   credentials are reported presence-only. A dedicated test asserts fake secrets never
   appear in any output.
2. **No network.** Nothing here calls out; the report is built from env + filesystem +
   local `ps`/`ifconfig`/`route`/`scutil`/`lsof`/`which` + config files only. (Egress IP
   and subscription tier would need a network/keychain probe and are deliberately NOT
   done — the `-w` keychain read is also avoided, per the ACL-flood lesson.)
3. **Fail-open.** Every probe helper (`_out`/`_out_any` + the two `ps` callers) degrades a
   blocked/unavailable probe to ""/"unknown" and never raises. This is why the tool runs
   green under the test process-sandbox, which deny-by-default blocks the machine-reading
   binaries it legitimately calls (`ifconfig`/`route`/`scutil`/compiler `--version`); the
   sandbox records the denials, the tool degrades. It is also correct in production (a
   permission wall or a crashing probe must not sink the whole report).

## Tests / verification

- `tests/test_identify_environment.py` — the 10 back-compat tests kept green (the CLI
  preserves the original public fns + keys + the `## Environment`/`Terminal/program`/
  `OS:`/`Filesystem`/`Container/dev-box/sandbox` render anchors).
- `tests/test_env_detect.py` — 44 pure tests (positive + negative per detector, proxy
  mask, CGNAT-NAT, MCP secret-mask, and the secret-never-leaked battery).
- ruff clean; live human + `--json` run verified end to end on the author's host.
