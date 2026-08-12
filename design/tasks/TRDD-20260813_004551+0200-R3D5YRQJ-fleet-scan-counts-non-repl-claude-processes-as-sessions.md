---
trdd-id: R3D5YRQJ
title: The fleet scan counts non-REPL claude subcommands as recoverable sessions
column: todo
created: 2026-08-13T00:45:51+0200
updated: 2026-08-13T00:48:52+0200
current-owner: unassigned
task-type: bugfix
approval-tier: 0
scope: project
severity: medium
relevant-rules: []
npt: []
eht: []
external-refs: [TRDD-324223a6, TRDD-DB1P25S4]
---

# `claude daemon run` is not a session, and the fleet guardian thinks it is

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative)

**Found 2026-08-13 while verifying TRDD-DB1P25S4's end-to-end box** — a live
`fleet_scan.gather_fleet` returned 23 instances, and TWO of the three `cron_dead` ones are not
Claude sessions at all:

| pid | command | transcript age | diagnosis / recovery |
|---|---|---|---|
| 46727 | `claude daemon run --json-path … --origin transient` | 1,406,803 s (16.3 d) | cron_dead / **rearm** |
| 54330 | `claude plugin marketplace update` | 373,117 s (4.3 d) | cron_dead / **rearm** |
| 7588 | `claude --add-dir /tmp --continue` | 3,704 s | cron_dead / rearm — a REAL session, correctly flagged |

**Cause, read from the source** (`fleet_scan.parse_ps_claude:122`): a claude process is
`os.path.basename(argv[0]) == "claude"` or a `/share/claude/versions/` path. That matches EVERY
`claude` CLI invocation — `daemon run`, `plugin marketplace update`, `plugin install`, `agents`
— none of which is an interactive REPL with a heartbeat to be dead.

## Why it matters, and why it is not an emergency

  - **The fleet picture is wrong where it is most load-bearing.** "2 of 23 sessions are
    cron_dead" is the number a human reads to decide whether the guardian is working. Two of
    those three are processes that cannot have a cron.
  - **Recovery is planned for them** (`recovery: rearm`). Today both carry an empty `tty`, so no
    pane resolves and the gentle injection no-ops — which is the only reason this is medium and
    not high. But `fleet_restart` rung 7 (`resurrect`) exists precisely for "no pane resolves",
    and it SPAWNS a background claude. It is behind the default-OFF hard-restart opt-in; the
    hazard is one config flip away, not structural.
  - The daemon process is the worst possible target: `claude daemon run` is long-lived BY
    DESIGN, so its transcript age grows forever and it will look more dead every day.

## A second, unrelated observation from the same scan (do NOT fold into the fix)

**pid 54330, `claude plugin marketplace update`, has been running 4.3 days.** A one-shot CLI
that has not exited in four days is wedged. It holds no lock this session needs, so it is not
urgent, but it is worth killing and worth knowing WHY it hung — the marketplace refresh is a
chore the janitor itself drives.

## Sketch (decide when picked up)

Discriminate a REPL from a subcommand. The signal is in argv already: the CLI shapes carry a
SUBCOMMAND as the first non-flag token (`daemon`, `plugin`, `agents`, `mcp`, …) while a REPL
session carries only flags (`--continue`, `--agent`, `--add-dir`, `--dangerously-skip-permissions`)
or nothing. That is a pure-function change to `parse_ps_claude`, testable against the exact
command lines recorded above.

**Do not filter on tty being empty** — that would ALSO drop real headless/harness sessions, which
is the opposite mistake and a much worse one.

### TWO TRAPS, both found 2026-08-13 while starting the fix — this is why it is still a sketch

**1. `daemon` is a HIDDEN subcommand.** `claude --help` lists exactly: `agents auth auto-mode
doctor gateway import install mcp plugin|plugins project setup-token ultrareview
update|upgrade`. **`daemon` is not among them**, yet pid 46727 runs `claude daemon run`. So an
allowlist derived from the help text — the obvious way to build one, and the way that looks
rigorous — misses the single case that motivated this card, and misses it silently. Any
allowlist must add `daemon` explicitly AND carry a comment that hidden subcommands exist, or the
next hidden one repeats this exactly.

**2. The transcript age is PER-PROJECT, so a non-session inherits a real session's.** `claude
daemon run` reported `transcript_age_s: 1,406,803` — it has no transcript of its own. The scan
resolves a project root from the process's cwd and reads that project's NEWEST `*.jsonl`, which
belongs to whatever session last worked there. That is approximately right for a REPL and
meaningless for a CLI invocation, and it means the staleness signal cannot be used to
discriminate: a non-session in a busy project can look perfectly healthy, and one in an idle
project looks long dead. **The filter has to be argv-shaped; there is no cheap transcript-shaped
alternative** (a pid→session-id map would need the process env, which `ps` does not expose).

Correct failure direction, given both traps: an UNKNOWN first token is treated as a SESSION.
Including a non-session costs a no-op recovery; excluding a real session costs a lost one.

## Acceptance

- [ ] `parse_ps_claude` (or a new pure sibling) excludes subcommand invocations, proven against
      the three command lines in the table above as fixtures
- [ ] A real REPL with an empty tty is still included — pinned by its own test, because the
      tempting shortcut breaks headless sessions
- [ ] The live scan reports the corrected count (1 cron_dead, not 3) with no other change
