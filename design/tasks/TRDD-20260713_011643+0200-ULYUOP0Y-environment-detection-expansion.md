---
trdd-id: ULYUOP0Y
title: Expand /janitor-identify-environment into a full secret-safe environment prober
column: complete
created: 2026-07-13T01:16:43+0200
updated: 2026-07-13T01:16:43+0200
current-owner: ai-maestro-janitor
task-type: feature
scope: project
release-via: publish
relevant-rules: [1]
parent-trdd: db169d9e
implementation-commits: [eca37bb]
last-test-result: pass
---

# Expand /janitor-identify-environment into a full secret-safe environment prober

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-07-13

**DONE. Shipped on `main`, unpushed.** ruff clean; back-compat tests green (10);
env_detect tests green (44). Live run on this host produced a correct full report.

- `scripts/lib/env_detect.py` — NEW pure decision layer (env-injectable, secret-safe,
  fail-open, no network). All classifiers + parsers live here.
- `scripts/identify_environment.py` — REWRITTEN thin I/O layer over env_detect; keeps
  the back-compat public fns/keys (`detect_terminal/detect_os/detect_sandboxing/
  gather/_render`) so the existing test still passes; adds `--fast`.
- `commands/janitor-identify-environment.md` — describes the new matrix + flags + safety.
- `tests/test_env_detect.py` — 44 pure tests (incl. the secret-never-leaked battery).

**NEXT ACTION:** nothing here — complete. Publishing (v0.42.0+, NON-EXEMPT) awaits the user.

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
