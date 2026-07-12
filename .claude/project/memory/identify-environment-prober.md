---
name: identify-environment-prober
description: "how does /janitor-identify-environment detect the environment — why did terminal/TTY detection report wrong (headless/'??') inside an interactive session, where is env_detect code, how to add a detector, why secret-safe/no-network/fail-open"
ocd: 2026-07-13
lmd: 2026-07-13
metadata:
  node_type: memory
  type: project
  tier: component
---

`/janitor-identify-environment` (`scripts/identify_environment.py` + the pure
`scripts/lib/env_detect.py`) reports the full runtime environment: terminal, OS,
filesystem, container/VM/CI, IDE + Claude-Code surface, execution context, network
(proxy/VPN/Tailscale/gateway/NAT/DNS/firewall/listening-services), cloud footprint,
python env, user, PATH, compilers/runtimes/package-managers/dev-tools, MCP servers,
the git repo + GitHub slug/branches/hooks/rulesets, wikimem sizes, and the
installed/enabled plugins+hooks+skills+staleness.

**Architecture — pure decisions, impure edges** (same split as `fleet_recovery` vs
`fleet_inject`): every classifier/parser in `env_detect.py` is PURE — it takes an
env dict, an injected `which`/`exists` callable, or a captured command string, and
returns a plain dict/list, so it is unit-tested with synthetic inputs and zero host
dependence (`tests/test_env_detect.py`). The CLI does the bounded I/O (`ps`,
`ifconfig`/`route`/`scutil`/`lsof`, `.git/config` read, `gh` under `--online`) and
hands raw facts to the pure layer. **To add a detector:** write the pure classifier
+ its test in `env_detect.py`, then a thin gatherer in the CLI.

**Three invariants a credentials-adjacent diagnostic MUST hold** (the reason to trust
it): (1) **never emit a secret VALUE** — `is_secret_key` gates every value, proxy
URLs are credential-masked, MCP endpoints keep only `scheme://host`, cloud creds are
presence-only, no `-w` keychain read; (2) **no network** except the opt-in `--online`
GitHub probes; (3) **fail-open** — every probe helper (`_out`/`_out_any`) degrades a
blocked/unavailable probe to ""/"unknown" and never raises, which is also why it runs
green under the deny-by-default test process-sandbox.

**Delivery (token economy):** the default run WRITES the full object to
`reports/identify-environment/<ts>-env.json` and prints only a compact digest + the
path; `--json` prints the raw object to stdout; `--fast` skips tool-versions +
listening-ports.

## Notes and lessons learned
[^1]: [ocd:2026-07-13 lmd:2026-07-13] **The anchor a subprocess loses.** Terminal/TTY
  detection first reported `headless`/`tty ??` and a false "background agent" INSIDE a
  fully interactive iTerm session. Root cause: Claude Code's Bash tool spawns the probe
  subprocess with NO controlling terminal, so `ps -o tty= -p <self>` is `??` — and the
  same class of failure makes `$ITERM_SESSION_ID` ABSENT in a resumed/`--continue`/
  detached session (its ancestry is reparented toward launchd). Both anchors describe
  the session's *interactive birth*, which resume/detach severs — so detection is
  strongest exactly when you don't need it and fails exactly when you do (auto-recovery
  on a wedged session). **Fix pattern:** read identity from a process ANCESTOR, not
  self — `_session_tty()` walks the ancestry and returns the first real tty (the
  `claude`/login-shell). The daemon fleet path already does this correctly by resolving
  a pane by TTY (via `osascript`/`tmux list-panes`), not by the session's own env — the
  self-trigger (`compact_trigger`/`reload_trigger`) should adopt the same TTY-anchored
  fallback when `$ITERM_SESSION_ID` is empty. Transferable → [[debugging-methodology]].
[^2]: [ocd:2026-07-13 lmd:2026-07-13] **NAT fooled by CGNAT.** `classify_nat` first
  read a Tailscale `100.x` address as a public IP → "not behind NAT", because RFC 6598
  shared space (`100.64.0.0/10`) is not in Python's `ipaddress.is_private`. Fix: skip
  tunnel/VPN interfaces and treat CGNAT as non-routable. Lesson: `is_private` is not
  "is on my LAN" — enumerate the special ranges you care about explicitly.
