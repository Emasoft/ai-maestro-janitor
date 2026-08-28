---
trdd-id: RSSN9A0P
title: A stale legacy rotator root can silently desync the janitor and ai-maestro daemons
column: blocked
created: 2026-08-27T01:36:38+0200
updated: 2026-08-28T07:29:34+0200
blocked-by: [ai-maestro#153]
current-owner: janitor-main-session
task-type: bugfix
project-id: ai-maestro-janitor
scope: project
severity: major
priority: high
blocker-probe: python3 scripts/rotator_roots_agree.py
blocker-probe-canary: match:CANARY roots-compared
blocker-holds-if: match:DESYNC|SPLITBRAIN
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

**NEXT ACTION (corrected 2026-08-28):** the peer's answer is now ACTUALLY REQUESTED — filed as
ai-maestro#153. On their reply, write my half (3) to
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

## ☠ DO NOT DELETE `~/.claude/account-rotator` — IT HOLDS THE LIVE COOKIES FOR ALL THREE ACCOUNTS

**Read this before acting on the word "legacy" anywhere in this card.**

```
~/.claude/plugins/data/ai-maestro-janitor-…/oauth-rotator/profiles
        →  SYMLINK  →  ~/.claude/account-rotator/profiles          ← the LIVE cookie store
```

`rm -rf ~/.claude/account-rotator` **destroys every account's session and ends unattended
operation immediately** — the self-inflicted version of the 2026-08-30 scare that started this
whole thread.

The trap is that every true statement in this card points the wrong way for a tidy-up session: the
directory is *named* legacy, its `state.json` *is* three months stale, and both this card and the
peer's now record that the canonical root superseded it. All true, and the conclusion "so it can be
deleted" is lethal. **Only `state.json` in that directory is dead. `profiles/` and
`reauth-chrome/` are live.** Retiring it means moving the real profiles dir first and repointing
the symlink — an owner decision, not cleanup. Raised by the ai-maestro peer, who is recording the
same warning on their side, because the likely actor is a future session reading our cards rather
than our shell history.

Cookie-DB census corrected by the peer — **FOUR, not three**, verified here with the filter removed:

```
$ find ~/.claude ~/ai-maestro -name Cookies -type f          # 4
~/.claude/account-rotator/reauth-chrome/Default/Cookies                    ← the one I missed
~/.claude/account-rotator/profiles/chrome-profile-fmu***/Default/Cookies
~/.claude/account-rotator/profiles/chrome-profile-ipa***/Default/Cookies
~/.claude/account-rotator/profiles/chrome-profile-ema***/Default/Cookies
```

My earlier search carried `-path '*chrome-profile*'`, so it could not have found the reauth
browser's own profile — a sibling of `profiles/`, not inside it. The conclusion is unaffected (all
four sit under the one shared directory, still a single store) but the certainty was not mine to
claim: a filtered search reported as an exhaustive negative. And the missed file is precisely the
profile a reauth path touches, so it is the one worth not losing track of.

## The hazard — `slots.ts:105-110`

```ts
if (isFile(join(canonical, 'state.json'))) return canonical
if (isFile(join(legacy,    'state.json'))) return legacy   // ← silent
```

The legacy file **exists and is stale**:

| root | `live_email` | slots | age |
|---|---|---|---|
| canonical | `ipa***` | **3** | current |
| legacy `~/.claude/account-rotator/state.json` | `fmu***` | **2** | 2026-05-30 |

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
DESYNC live 'ipa***' vs 'fmu***'; slots 3 vs 2   # exit 0
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

## ⛔ THE MARKER CONTRACT IS WITHDRAWN — its premise was false (2026-08-27 01:52)

**Do not build the reader described in the next section.** I asked the peer for a
`cookie-capture.<email>.last-success.ts` marker on the premise that *"if their capture path
re-mints cookies, my vault goes stale with nothing to notice."* **They have no cookie capture
path.** They went to implement my marker, could not find an honest site for it, and stopped —
which is the correct outcome and the one I made harder by asking.

Verified here rather than accepted: `grep -rn "inject_jar\|injectJar\|snapshot_to_keychain\|
writeCookies\|\"Cookies\"" lib app --include=*.ts` in their tree returns **nothing**. Their
`reauth-drive.ts:46` states outright that it never inspects, stores or logs a token, a cookie or
the verifier; `:34` harvests cookies FROM the environment — it reads, it does not write.

The only site that knows which account a credential belongs to is
`reauth-flow.ts::completeReauth`, and that takes a **pasted code**: the human may have logged in
in their everyday browser, entirely outside the shared profile. A success there means *"an OAuth
slot was re-filed"*, never *"the shared cookie store changed"*. A marker named
`cookie-capture.…` written at that site would assert something the event does not establish —
and it would lie in the direction that makes me refresh a vault that was fine, or trust one that
was not.

**So the vault cannot be staled by their side.** The staleness risk is real but its sources are
my own capture path and the human's logins — both already mine. Nothing to coordinate.

They offered `slot-refile.<email>.last-success.ts` for the fact they DO have. **Declined**: my
vault pairs with the cookie store, not with slot state, so consuming it would recreate the same
name-does-not-match-event defect one rename later. "Nothing" is the right artifact here.

**The lesson, and it is the same one twice tonight:** I specified a marker for an event I had not
verified occurs, in someone else's system. The premise was as unchecked as the invented regex in
TRDD-6054NY8H. Asking a peer to emit a signal is exactly as much an assertion as emitting one.

<details><summary>SUPERSEDED — the withdrawn marker contract, kept verbatim</summary>

## The cookie vault — SETTLED: janitor-private, with an explicit staleness marker

The peer owns the capture path and ruled `Claude Code-rotator-cookies` **janitor-private** rather
than shared, and the reasoning is right: the Chrome profile sqlite is the shared substrate and is
already single; the keychain vault is a DERIVED copy, and a derived copy is tolerable only while
exactly ONE writer exists. Making it shared would create two writers over a schema only one side
understands — the very failure the owner's directive aims at.

That leaves the real risk: their capture re-mints cookies and my vault silently ages. So the
contract is explicit and **derivable, not assumed** — the same discipline as the probes:

| who | writes | shape |
|---|---|---|
| ai-maestro, after each successful cookie capture | `<canonical-root>/cookie-capture.<email>.last-success.ts` | epoch seconds, one line, no newline needed — matches the existing `tick-completed.ts` convention (`1787786653`) |
| janitor, after each `cookie_vault.snapshot_to_keychain` | `<canonical-root>/cookie-vault.<email>.snapshot.ts` | same shape |

**Vault is stale ⟺ `cookie-capture.<email>.last-success.ts` > `cookie-vault.<email>.snapshot.ts`.**
Per-account, not global: a single-account capture must not imply all three were refreshed.
Missing capture marker ⇒ could-not-determine, never "fresh".

</details>

## SPLITBRAIN — the check that replaced the marker, and it catches the worse failure

The peer's `1cb2fc62` refused a bad state write by returning early. Their own review then found
`saveState` is `void`, so a silent refusal is **undetectable at every call site by construction** —
now throws (`ffafa40b`), caught by `server-tick.ts:195-277`, so it surfaces as a reported tick
failure instead of a discarded write.

They also **withdrew a reachability argument they had given me and I had relied on**: "unresolved
root ⇒ zero slots ⇒ the candidate loop never runs ⇒ `switchLiveTo` unreachable" holds only when
the root is unresolved AT LOAD. It does not cover the root going unresolved MID-TICK — my DATA dir
being restored, a reinstall in flight — where slots loaded fine and the write is then discarded.
Result: **keychain live = account B while `state.json` still says account A.**

That split-brain is worse than the empty shadow and my roots probe could not see it: comparing
canonical-vs-legacy `state.json` answers *"do the two files agree"*, never *"does state agree with
reality"*. Each reader is self-consistent alone, so nothing announces it.

`split_brain()` in the probe now compares `state.json` against `live-identity.json`. **That is not
a value compared with itself** — `rotator.py:882` re-stamps the beacon ONLY when the credential
actually CHANGED, and `:2962` writes it from a session context that touches neither `state.json`
nor the keychain. Two independent writers, so agreement is evidence.

**It deliberately does NOT read the keychain item**, which would be the stronger check. A probe on
a heartbeat cadence that reads a `security` item is exactly what produced hundreds of "Security
wants to use the login keychain" dialogs with no Always-Allow button in July (memory:
`macos-keychain`). A detector that locks the owner out of their machine is not a detector.

### ⚠ HOW OFTEN THIS CHECK ACTUALLY ANSWERS — state it before anyone relies on it

**Right now, on this host, it ABSTAINS.** Live output: `beacon-stale (last observation predates
the current state — cannot cross-check)`. That is correct behaviour, and it is also most of the
time.

`rotator.py:882-893` is explicit: the beacon is stamped only from a context that can READ the
primary credential, and the only automatic one is **SessionStart — once per session**. The
daemon's own tick stamp is a guaranteed no-op (headless, skips the primary read by design).
`state.json`, meanwhile, is rewritten by every tick. So the beacon is older than the state almost
always, and a beacon written BEFORE the state it is compared against is not an observation of that
state — it is could-not-compare.

Suppressing that is not a weakness, it is the whole trichotomy: after a legitimate rotation the
beacon names the OLD account while state names the NEW one, so an unqualified comparison would
report SPLITBRAIN for a system behaving exactly as designed. **A detector that cries wolf on the
normal path is worse than none, because the one true firing gets discarded with the rest.**

But the honest consequence is that this check has a **narrow window** — it answers only when a
session start has stamped the beacon more recently than the last state write. It is a real check
with real coverage gaps, not the state-vs-reality guarantee the peer asked about. Closing the gap
means stamping the beacon on every rotation (event-driven, in the rotator's own switch path), not
reading the keychain on a cadence. That is janitor work, not detector work, and it is not tonight's.

Verified by neuter, not by argument: beacon repointed at a disagreeing identity ⇒
`SPLITBRAIN state says 'ipazia…'/f61bb0c7 but last observed live was 'other@example.com'/deadbeef`.
It runs BEFORE the legacy-absent early return on purpose — retiring the legacy root is the goal,
and a check placed after that return would silently stop executing at the exact moment the rest of
the probe starts reporting "agree".

## Acceptance

- [ ] Peer answers on options 1/2; shape agreed before either half is built
- [ ] Detector (3) lands, matching that shape, with a red test for the desync case
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

Found only because the owner rejected my false claim that the daemons share no state. I had
generalised "no coordination handshake" into "no shared state" and stated the second. The shared
substrate was three greps away the whole time.

## Approval log

## ⛔ CORRECTION 2026-08-28 — this card said "awaiting the peer" for a question NEVER ASKED

The NEXT ACTION read *"await the peer's answer on fallback options 1/2"*. I checked before working
it: **no issue existed on `Emasoft/ai-maestro` about the legacy rotator root** (searched the tracker,
all states), and nothing in this card records a message having been sent. So the card sat in `todo`
describing itself as waiting on someone who had never been asked.

Filed now as **ai-maestro#153**, carrying the hazard (`slots.ts:105-110` silent fallback), the
measured divergence (canonical `ipa***`/3 slots/current vs legacy `fmu***`/2 slots/2026-05-30),
options 1/2 with my weak preference for (1), and my half (3) offered once the shape is agreed. Card
moved `todo` → `blocked` with `blocked-by: [ai-maestro#153]`, which is now a TRUE claim.

**This is the second instance tonight of the same failure** (see `[[agent-self-imposed-gate-stall]]`):
a card asserting an external dependency that was never actually created. The tell is identical both
times — a NEXT ACTION written in the passive ("await the answer") with no artifact id beside it. A
dependency with no id is not a dependency, it is an intention.

