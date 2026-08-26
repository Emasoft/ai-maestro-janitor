---
trdd-id: RSSN9A0P
title: A stale legacy rotator root can silently desync the janitor and ai-maestro daemons
column: todo
created: 2026-08-27T01:36:38+0200
updated: 2026-08-27T01:36:38+0200
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: major
priority: high
blocker-probe: python3 scripts/rotator_roots_agree.py
blocker-probe-canary: match:CANARY roots-compared
blocker-holds-if: match:DESYNC
labels: [oauth-rotator, shared-state, upstream-ai-maestro]
npt: []
eht: []
implementation-commits: []
relevant-rules: []
---

# The two daemons share one credential store — until the canonical root vanishes, then they diverge silently

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative) — 2026-08-27

**The owner's requirement is ALREADY MET.** Nothing is duplicated. Do not "build sharing" — it
exists. What is open is one silent-fallback hazard and its two halves (one mine, one ai-maestro's).

**NEXT ACTION:** await the peer's answer on fallback options 1/2 below, then write my half (3) to
match whichever shape they pick.

## Verified shared, read from both codebases 2026-08-27 01:35

| resource | janitor | ai-maestro | same? |
|---|---|---|---|
| slot tokens | `rotator.py:83` `SLOT_KEYCHAIN_SERVICE = "Claude Code-rotator-slot"` | `slots.ts:47` same literal | ✅ |
| slot mirror | `rotator.py:84` `"Claude Code-rotator-slot-backup"` | `slots.ts:48` same literal | ✅ |
| live credential | `"Claude Code-credentials"` | same | ✅ |
| rotator state | canonical `…/plugins/data/ai-maestro-janitor-…/oauth-rotator/state.json` | `slots.ts:94-95` resolves to that same path | ✅ |
| cookies | `oauth-rotator/profiles` → symlink | `slots.ts:100` names the symlink's target | ✅ |

**The table above is SOURCE, and source is not runtime — say it that way.** Every row was read
from the two codebases; none of it observes the running daemons. Two rows are weaker than they
look and both were caught in adversarial review:

- the janitor's name is `os.environ.get("CLAUDE_ROTATOR_SLOT_KEYCHAIN_SERVICE", "…")` — a
  **runtime** property of the daemon's environment — while ai-maestro's is a compile-time
  `const`. Identical text in two files does not prove identical effective values; anything
  exporting that variable would split them invisibly to every grep.
- `readlink` on the janitor's `profiles` says where the **janitor** looks, not where ai-maestro
  resolves cookies at runtime.

**What actually settles it — the keychain item census**, which is the store itself rather than
code that names it:

| service | items | expected |
|---|---|---|
| `Claude Code-rotator-slot` | **3** | 1 per account |
| `Claude Code-rotator-slot-backup` | **3** | 1 per account |
| `Claude Code-rotator-cookies` | **3** | 1 per account |
| `Claude Code-credentials` | 1 | the live credential |
| `Claude Code-credentials-livebak` | 1 | its mirror |

Three accounts, exactly three items in every per-account family, and **no second family under any
other service name**. If the two daemons were addressing different keychain items there would be
six per family, not three. That is the duplication question answered from the store, and it is why
the "nothing is duplicated" conclusion survives even though the source comparison alone could not
carry it. (Note `-rotator-cookies`: cookies live in the keychain too, not only in the Chrome
sqlite — `safe_storage.py` is explicit that the keychain, not a plaintext profile DB, is the
at-rest home.)

Cookie-DB check, stated at its real strength: `find` over `~/ai-maestro` and `~/.claude`,
`-maxdepth 5`, path containing `chrome-profile` → **three** `Cookies` DBs, all inside the one
shared `~/.claude/account-rotator/profiles`. That is a **bounded** search: it says nothing about
depth ≥ 6, other roots, `/tmp`, or a differently-named dir. Read it as "no duplicate store where a
duplicate would plausibly live", not as proof of absence.
`~/ai-maestro/.kuri/auth-profiles/claude.ai.meta.json` is 92 B of metadata
(`{"backend":"keychain"}`) — a pointer at the shared keychain, not a credential copy.

## Keychain reconciled — and ONE store is NOT shared

An adversarial review refused "nothing is duplicated" on the grounds that I had counted 12 items
in the rotator families and never reconciled them against the 6 that 3 accounts × (slot + backup)
predicts. Correct challenge. Enumerated by service + account:

| service | items | shared with ai-maestro? |
|---|---|---|
| `Claude Code-rotator-slot` | 3 (one per account) | ✅ `slots.ts:47`, same literal |
| `Claude Code-rotator-slot-backup` | 3 | ✅ `slots.ts:48`, same literal |
| `Claude Code-credentials` | 1 | ✅ |
| `Claude Code-credentials-livebak` | 1 | ✅ documented live mirror |
| **`Claude Code-rotator-cookies`** | **3** | ❌ **janitor-only** |

No surplus and no per-account duplication — the count is fully explained. **But the last row is a
real answer to the owner's "the daemons must share everything":** the janitor keeps an encrypted
cookie vault in the keychain (`cookie_vault.py`) and `grep -rn "rotator-cookies\|cookieVault" lib
app --include=*.ts` in ai-maestro returns **nothing**. So cookies live in two places — the shared
Chrome profile sqlite that both sides read, and a janitor-only keychain mirror that only one side
writes. It is not a rival credential today, but if ai-maestro re-captures cookies the vault goes
stale with nothing to notice, which is a second copy that can diverge. Route: agree with the peer
whether the vault becomes shared or is explicitly declared janitor-private and refreshed on their
capture.

**Also settled by measurement, not source:** the janitor's service name is
`os.environ.get("CLAUDE_ROTATOR_SLOT_KEYCHAIN_SERVICE", "Claude Code-rotator-slot")` — a runtime
value — while ai-maestro's is a compile-time const, so identical source text would NOT prove
identical addressing if anything exported that variable. Nothing does: it is absent from
`ecosystem.config.js`, from `~/.claude/*.json`, from `~/Library/LaunchAgents/*.plist`, and from
the environment. Limit of this check, stated rather than hidden: I read the configs that START the
daemons, not the env of the live PIDs.

## The hazard — `slots.ts:105-110`

```ts
if (isFile(join(canonical, 'state.json'))) return canonical
if (isFile(join(legacy,    'state.json'))) return legacy   // ← silent
```

The legacy file **exists and is stale**:

| root | `live_email` | slots | age |
|---|---|---|---|
| canonical | `ipazia.emasoft@gmail.com` | **3** | current |
| legacy `~/.claude/account-rotator/state.json` | `fmuaddib@gmail.com` | **2** | 2026-05-30 |

Dormant today because canonical wins. It arms the moment the janitor's DATA dir disappears — which
`janitor-footprint.md` **documents** (not measured here — say "documented as", do not assert the
mechanism) as the ordinary consequence of a plain plugin uninstall/reinstall
(the reason USER-scope memory keeps an out-of-tree mirror). In that window ai-maestro adopts a
three-month-old state naming a **different live account with one slot missing**, while the janitor
rebuilds from the keychain. That is the duplicated/desynced credential state the owner forbids, and
it would surface as a rotation to an account the other side does not believe is live.

## Options (peer's half: 1/2 — mine: 3)

1. **Fail loud:** canonical absent + legacy present ⇒ named alert, treated as *could-not-determine*,
   never a silent adoption. Same trichotomy as the probe grammar (TRDD-6054NY8H CORRECTION 6).
2. **Refuse stale:** compare `live_email` / mtime; reject a legacy root older than canonical ever was.
3. **Mine — a detector asserting the two roots do not disagree** (same `live_email`, same slot set).
   Mine because it is my DATA dir whose disappearance arms the trap. Written under the canary
   grammar so it re-derives instead of latching — see this card's own `blocker-probe:`.

## Explicitly NOT doing

**Not deleting the legacy `state.json`.** Untracked, outside any repo ⇒ RULE 0 forbids removing it
without the owner's explicit word, and he is away. It is also the only record of what the old root
believed. Retire it deliberately when he is back.

## The probe, and the two defects in its first version

`scripts/rotator_roots_agree.py`, run 2026-08-27 01:38:

```
CANARY roots-compared
DESYNC live 'ipazia.emasoft@gmail.com' vs 'fmuaddib@gmail.com'; slots 3 vs 2   # exit 0
```

The first version of this field was a `python3 -c "…"` one-liner and it was wrong twice:

1. **It violated condition 1 of the bar I set with the peer two messages earlier** — no shell
   string, fixed argv. I wrote the counter-example again, one card later.
2. **Its success condition made it permanently unrunnable.** It `json.load`-ed BOTH roots with no
   guard, so the day the legacy file is retired — the DESIRABLE end state — it would raise, exit
   non-zero, and report verdict 2 *could-not-run* forever. A probe that crashes exactly when the
   problem is fixed reports "unknown" for the rest of time.

The script now treats an absent legacy root as `agree` (the trap cannot arm) and an absent
CANONICAL root as `DESYNC` (the trap is armed right now — that is the whole hazard). A
present-but-corrupt file still propagates, so it surfaces as could-not-run rather than agreement.

## The probe, and its neuter runs

`scripts/rotator_roots_agree.py` — fixed argv (condition 1), canary printed BEFORE any fallible
work, and **legacy-absent classified as `agree`, not as an error**. The first version of this probe
was a `python3 -c` one-liner that `json.load`ed both files with no guard: retiring the legacy file
— the card's own desired outcome — would have raised, killed the canary, and pinned the card at
verdict 2 forever. A probe whose success condition makes it permanently unrunnable is worse than
no probe, because verdict 2 never un-parks.

Measured, all three branches, 2026-08-27 01:39:

```
real                 → CANARY roots-compared / DESYNC live 'ipazia…' vs 'fmuaddib…'; slots 3 vs 2
legacy absent        → CANARY roots-compared / agree (no legacy root — the fallback cannot arm)
canonical absent     → CANARY roots-compared / DESYNC canonical root missing …
ruff + mypy          → clean
```

The canary survives every branch — that is the property being tested, and it is why the canary is
printed first. **The probe reports DESYNC right now**: the two roots genuinely disagree today, so
the hazard is not theoretical, only unarmed.

## Acceptance

- [ ] Peer answers on options 1/2; shape agreed before either half is built
- [ ] Detector (3) lands, matching that shape, with a red test for the desync case
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

Found only because the owner rejected my false claim that the daemons share no state. I had
generalised "no coordination handshake" into "no shared state" and stated the second. The shared
substrate was three greps away the whole time.

## Approval log
