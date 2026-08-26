---
trdd-id: KHM8XOYN
title: Enumerate every site that executes or resolves-what-to-execute from agent-writable input
column: complete
created: 2026-08-26T18:56:42+0200
updated: 2026-08-26T21:48:00+0200
current-owner: janitor-main-session
task-type: security
priority: normal
scope: project
project-id: ai-maestro-janitor
severity: major
min-approval-requirement: none
labels: [security, sandbox, supply-chain, exec]
external-refs: [ai-maestro-TRDD-NB70FKKT, ai-maestro-TRDD-O0RHX7K6]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# The janitor's side of the exec-from-writable-input class

## ⏵ STATE — READ THIS FIRST ON RESUME

- **THIS IS NOT A LIVE VULNERABILITY, and saying so is load-bearing.** Every agent on this
  machine runs as the SAME uid. An agent that can write the script the janitor executes can
  already do anything that uid can do, directly — so there is **no privilege boundary being
  crossed today and no escalation to gain**. Do not re-file this as an incident; an overstated
  version was explicitly the thing that would have got it discounted by the peer.
- **WHAT MAKES IT MATTER IS WORK THAT HAS NOT SHIPPED YET.** The ai-maestro hub measured that
  seatbelt (`sandbox-exec`) CAN confine agents under one uid + shared tmux, and landed the
  profile GENERATOR on 2026-08-26 (their `04e469c2`) — **not wired to the spawn path**. The
  moment confinement exists, every site enumerated here is a hole straight through it: a
  confined agent writes the input, and an UNCONFINED janitor executes it.
- **So the deliverable is an ENUMERATION, not a fix.** Nothing here should be changed tonight;
  the peer said so explicitly and they are right — changing exec paths before the confinement
  design is settled would be guessing at a contract that does not exist yet.
- **NEXT ACTION:** verify the sweep's findings first-hand (a subagent produced candidates; a
  candidate is not a finding until read), then send the confirmed list to the hub for
  NB70FKKT's acceptance.

## The predicate — broader than "reads an agent-writable file"

From the hub, and it is the better formulation:

> does an unconfined process **exec, source, or RESOLVE what to exec** from an agent-writable
> path or an agent-writable env var

Three shapes, and the second and third are the ones a naive audit misses:

1. **EXEC** — running a program whose path lives in a writable tree.
2. **RESOLVE** — a *decision* about what to run: `shutil.which`, a `$FOO_CLI` env var, a
   candidate chain (`$ENV` → `~/.local/bin` → `PATH`). The binary may be fine; the *choice* is
   attacker-controlled.
3. **SOURCE / IMPORT** — `source` in shell, and `sys.path.insert` + `import` in Python.
   **Importing is executing.** An audit that greps only for `subprocess` misses this entirely.

## The three confirmed instances that opened this (read first-hand, not grepped)

| shape | site | what decides | what runs |
|---|---|---|---|
| EXEC | `scripts/plugin_manage.py:55` → `:175` → `:194` | `agent_cli()` | `~/ai-maestro/scripts/aimaestro-agent.sh`, verified `-rwxr-xr-x`, owner = the agent uid |
| RESOLVE | `terminal_trigger._resolve_aimaestro_cli` | `$AIMAESTRO_CLI`, then `$HOME/.local/bin`, then `PATH` | an env var selects the binary |
| — | `dispatch.py:2668`, `hooks/on-prompt-submit.py`, `fleet_status.py:145` | — | state-file READS of `~/.aimaestro/**` — ranked BELOW the exec paths, listed so the boundary between the two classes stays visible |

The EXEC one fires only inside a harness agent (`backend == BACKEND_AIMAESTRO`); a standalone
session like this repo's never reaches it. That narrows the blast radius, it does not remove it.

## The instance worth thinking hardest about — and it may be the ANSWER, not a finding

**The dispatcher stub execs from `~/.claude/plugins/cache/`, which is agent-writable**, and it
does so on every heartbeat fire, by design (it re-resolves the newest cached version so plugin
updates roll forward with no re-arm). By the predicate above that is a textbook instance.

But the stub does **not** exec blindly — it walks a C2/C3 verification with a last-good integrity
pin. So the interesting question for NB70FKKT is not "is the stub a finding" but **"is the stub's
verified-walk the shape every other site should adopt?"** An enumeration that lists it flatly
alongside the unverified sites, with no column for the mitigation, would hide the one design
answer already implemented in this repo. Whoever sends the list must not flatten that.

## ⏵ 2026-08-26 19:06 — ENUMERATION DONE. Two corrections to this card's own framing.

**1. The card guessed the wrong headline instance.** The `~/ai-maestro/scripts/aimaestro-agent.sh`
exec that opened this only fires inside a harness agent. The sharper class is **`$MEMGREP_BIN`**:
a bare env var naming a binary, falling back through `PATH` and `~/.cargo/bin` — all three legs
agent-writable — read by **6 modules including `detectors/memory-librarian.py` (runs unattended
on the heartbeat) and `hooks/post-edit-wikimem-lint.py` (fires on every edit)**. Every project,
every beat, no harness required.

**2. The STATE block above says the stub's C2/C3 walk "may be the ANSWER". Reading it says
otherwise, and this is the finding worth sending.** The gate is real — inlined-stdlib manifest
verify, quarantine list, last-good pin, walking down on rejection. But it is **FAIL-OPEN by
cardinal rule**: *"if NOTHING is acceptable, exec the newest RUNNABLE version anyway"*, and
*"every uncertainty (no/unreadable/malformed manifest, no key, no pin …) is ACCEPTED — we never
block what we cannot prove bad."*

So an attacker need not forge a manifest; **deleting one suffices**. That is correct engineering
for the problem the stub actually solves — a bricked heartbeat needs a human and is strictly
worse in the single-uid world — and I am proposing no change to it. The narrow, transferable
point is: **the verified walk is an AVAILABILITY mechanism, not a confinement boundary, and must
not be cited as the pattern other sites should copy.** I was one sentence from writing exactly
that recommendation before reading line 226.

## Acceptance

- [x] A complete enumeration across `scripts/`, `hooks/`, `commands/`, `skills/`, `agents/`,
      classified by shape, each entry naming the file:line AND the symbol/env var that *decides*.
      **DONE — `reports/exec-writable-audit/20260826_190600+0200-exec-from-writable-input.md`**
      (gitignored). Four classes; class 4 (source/import from outside the repo) came back EMPTY
      and is recorded as a negative result, since "importing is executing" was the shape most
      likely to be missed.
- [x] **Every entry read first-hand before it is reported.** The delegated sweep produced
      NOTHING — the worker wedged at 182 bytes with no output after 6 minutes and was stopped —
      so this is a hand audit throughout. Worth recording rather than hiding: had I taken a
      wedged agent's silence for "no findings", the report would have been empty and confident.
- [x] Each entry carries whether a verification gate stands between the writable input and the
      exec — and **that box produced the report's sharpest finding, by contradicting what I was
      about to write.** See below.
- [x] Sent to the hub for NB70FKKT's acceptance; their card asks for exactly this and has no
      other source for it. **SENT 2026-08-26 21:46** to peer session `ai-maestro-bf`
      (msg `5bf4a4d1`), carrying the report path plus the two corrections that matter to THEIR
      design and not just to mine: the headline instance is `$MEMGREP_BIN`, not the
      `aimaestro-agent.sh` exec that opened this; and the stub's C2/C3 walk must NOT be cited as
      the pattern to copy, because it is fail-open by cardinal rule. The empty class 4 went with
      it as an explicit negative result — a zero nobody has to re-derive.
      Acceptance is theirs to give; if it comes back with corrections that is a new card, not a
      reopening of this one.
- [x] **NO code change in this card.** Held — `implementation-commits:` is empty and stays empty.
      Remediation waits on the confinement contract; if a fix lands here it is a different TRDD.

## Notes and lessons learned

[^1]: [id:ATOM-KHM8-XO01, status:valid, keywords:"same_uid_means_no_escalation is_this_a_real_vulnerability_or_a_prerequisite I_found_an_agent_writable_script_being_executed should_I_file_this_as_an_incident overstating_a_security_finding_gets_it_discounted", ocd:2026-08-26, lmd:2026-08-26]
  DO NOT report an agent-writable input reaching an exec as a live vulnerability when every
  agent shares the process's own uid, BECAUSE no privilege boundary is crossed — the writer
  could already do directly whatever the exec would do for it — and the overstated version costs
  a triage cycle and gets the genuine entries discounted along with it. DO report it as a
  PREREQUISITE on any confinement work, and say plainly that it grants no escalation today; that
  framing is what let the hub classify it correctly and block their sandbox card on it
  (2026-08-26, their NB70FKKT).

[^2]: [id:ATOM-KHM8-XO02, status:valid, keywords:"grepping_for_subprocess_misses_the_real_exec_sites importing_is_executing sys_path_insert_from_a_writable_dir an_env_var_decides_which_binary_runs which_resolves_the_program_path", ocd:2026-08-26, lmd:2026-08-26]
  DO NOT audit "what does this code execute" by grepping for `subprocess`/`exec`, BECAUSE two
  whole shapes evade it: a RESOLVER (`shutil.which`, a `$FOO_CLI` env var, a candidate-path
  chain) makes the *choice* attacker-controlled while the call site looks like a fixed argv, and
  an IMPORT from a writable directory (`sys.path.insert` + `import`, shell `source`) executes
  code with no exec call anywhere in sight. DO search for all three shapes, and record what
  DECIDES the path alongside each call.
