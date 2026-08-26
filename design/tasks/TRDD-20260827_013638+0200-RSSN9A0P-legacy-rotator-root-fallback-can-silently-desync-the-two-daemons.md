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
blocker-probe: python3 -c "import json,os;c=json.load(open(os.path.expanduser('~/.claude/plugins/data/ai-maestro-janitor-ai-maestro-plugins/oauth-rotator/state.json')));l=json.load(open(os.path.expanduser('~/.claude/account-rotator/state.json')));print('CANARY roots-compared');print('DESYNC' if (c.get('live_email')!=l.get('live_email') or set(c.get('slots',{}))!=set(l.get('slots',{}))) else 'agree')"
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

Physical check: **exactly three** `Cookies` sqlite DBs on this host, all three inside the one
shared `~/.claude/account-rotator/profiles`. No second cookie store under `~/ai-maestro` or
`~/.claude`. `~/ai-maestro/.kuri/auth-profiles/claude.ai.meta.json` is 92 B of metadata
(`{"backend":"keychain"}`), not a credential copy.

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
`janitor-footprint.md` documents as the ordinary consequence of a plain plugin uninstall/reinstall
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

## Acceptance

- [ ] Peer answers on options 1/2; shape agreed before either half is built
- [ ] Detector (3) lands, matching that shape, with a red test for the desync case
- [ ] `uv run pytest -q`, `ruff check scripts tests`, `mypy scripts/ --ignore-missing-imports`

## Notes and lessons learned

Found only because the owner rejected my false claim that the daemons share no state. I had
generalised "no coordination handshake" into "no shared state" and stated the second. The shared
substrate was three greps away the whole time.

## Approval log
