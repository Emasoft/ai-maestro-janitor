---
name: identify-environment-prober
description: "how does /janitor-identify-environment detect the environment / why did terminal or TTY detection report wrong headless or '??' inside an interactive session / where is the env_detect code / how do I add a new detector to identify-environment / why is the tool secret-safe no-network fail-open / a background agent was falsely reported inside a fully interactive iTerm session / ITERM_SESSION_ID is absent on a resumed or --continue session / why does subprocess ps report tty ?? for the bash tool / how to read process identity from an ancestor not self / NAT detection misclassified a Tailscale CGNAT address as public / is 100.64.0.0/10 private in python ipaddress / where does identify-environment write its report json / what does --fast skip in identify-environment / what does --online enable in identify-environment / does identify-environment ever emit secret values"
ocd: 2026-07-13
lmd: 2026-09-09
metadata:
  node_type: memory
  type: project
  tier: component
publish-globally: false
---

^PMIRWAFV [desc:"What /janitor-identify-environment reports: terminal, OS, filesystem, container/VM/CI, IDE+Claude-Code surface, network, cloud, python/PATH/dev-tools, MCP, git/GitHub, wikimem, plugin staleness.", keywords:"how_does_janitor_identify_environment_detect_the_environment what_does_identify_environment_report scripts_identify_environment_py_and_env_detect_py where_is_the_env_detect_code full_runtime_environment_report"]
`/janitor-identify-environment` (`scripts/identify_environment.py` + the pure
`scripts/lib/env_detect.py`) reports the full runtime environment: terminal[^1], OS,
filesystem, container/VM/CI, IDE + Claude-Code surface, execution context, network
(proxy/VPN/Tailscale/gateway/NAT[^2]/DNS/firewall/listening-services), cloud footprint,
python env, user, PATH, compilers/runtimes/package-managers/dev-tools, MCP servers,
the git repo + GitHub slug/branches/hooks/rulesets, wikimem sizes, and the
installed/enabled plugins+hooks+skills+staleness.

^SPPRRMF8 [desc:"identify-environment's pure/impure split: env_detect.py is pure+unit-tested; CLI does bounded I/O, hands raw facts to the pure layer; add a detector as pure classifier + thin CLI gatherer.", keywords:"how_do_i_add_a_new_detector_to_identify_environment pure_decisions_impure_edges_architecture env_detect_py_is_pure_and_unit_tested cli_does_bounded_io_ps_ifconfig_route_scutil same_split_as_fleet_recovery_vs_fleet_inject"]
**Architecture — pure decisions, impure edges** (same split as `fleet_recovery` vs
`fleet_inject`): every classifier/parser in `env_detect.py` is PURE — it takes an
env dict, an injected `which`/`exists` callable, or a captured command string, and
returns a plain dict/list, so it is unit-tested with synthetic inputs and zero host
dependence (`tests/test_env_detect.py`). The CLI does the bounded I/O (`ps`,
`ifconfig`/`route`/`scutil`/`lsof`, `.git/config` read, `gh` under `--online`) and
hands raw facts to the pure layer. **To add a detector:** write the pure classifier
+ its test in `env_detect.py`, then a thin gatherer in the CLI.

^TPOCP39O [desc:"The tool's three credentials-adjacent invariants: never emit a secret value (is_secret_key gates everything), no network except opt-in --online GitHub probes, and fail-open on every probe helper.", keywords:"why_is_the_tool_secret_safe_no_network_fail_open does_identify_environment_ever_emit_secret_values what_does_online_enable_in_identify_environment is_secret_key_gates_every_value proxy_urls_credential_masked runs_green_under_deny_by_default_sandbox"]
**Three invariants a credentials-adjacent diagnostic MUST hold** (the reason to trust
it): (1) **never emit a secret VALUE** — `is_secret_key` gates every value, proxy
URLs are credential-masked, MCP endpoints keep only `scheme://host`, cloud creds are
presence-only, no `-w` keychain read; (2) **no network** except the opt-in `--online`
GitHub probes; (3) **fail-open** — every probe helper (`_out`/`_out_any`) degrades a
blocked/unavailable probe to ""/"unknown" and never raises, which is also why it runs
green under the deny-by-default test process-sandbox.

^VKG97PLH [desc:"Delivery/token economy: default run writes the full object to reports/identify-environment/<ts>-env.json, prints only a compact digest; --json prints raw; --fast skips tool-versions+ports.", keywords:"where_does_identify_environment_write_its_report_json what_does_fast_skip_in_identify_environment default_run_writes_full_object_to_reports json_flag_prints_raw_object_to_stdout tool_versions_and_listening_ports_skipped_by_fast"]
**Delivery (token economy):** the default run WRITES the full object to
`reports/identify-environment/<ts>-env.json` and prints only a compact digest + the
path; `--json` prints the raw object to stdout; `--fast` skips tool-versions +
listening-ports.

## Notes and lessons learned
[^1]: [id:ATOM-MG07-0013, status:valid, keywords:"subprocess_no_controlling_terminal iterm_session_id_absent_on_resume read_identity_from_ancestor_not_self", ocd:2026-07-13, lmd:2026-07-13] **The anchor a subprocess loses.** Terminal/TTY
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
[^2]: [id:ATOM-MG07-0014, status:valid, keywords:"cgnat_100_64_not_private_range is_private_not_is_on_my_lan classify_nat_skip_tunnel_interfaces", ocd:2026-07-13, lmd:2026-07-13] **NAT fooled by CGNAT.** `classify_nat` first
  read a Tailscale `100.x` address as a public IP → "not behind NAT", because RFC 6598
  shared space (`100.64.0.0/10`) is not in Python's `ipaddress.is_private`. Fix: skip
  tunnel/VPN interfaces and treat CGNAT as non-routable. Lesson: `is_private` is not
  "is on my LAN" — enumerate the special ranges you care about explicitly.
