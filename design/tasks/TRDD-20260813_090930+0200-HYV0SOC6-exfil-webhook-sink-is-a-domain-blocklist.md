---
trdd-id: HYV0SOC6
title: exfil-webhook-sink is a known-domain blocklist wearing the name of an exfiltration detector
column: todo
created: 2026-08-13T09:09:30+0200
updated: 2026-08-14T07:52:00+0200
current-owner: janitor-main-session
task-type: security
approval-tier: 0
scope: project
severity: high
relevant-rules: []
npt: []
eht: []
external-refs: [janitor#226, janitor#254]
---

# `exfil-webhook-sink` scores 0/8 because it matches DOMAINS, not exfiltration

Surfaced by the janitor#226 coverage audit and diagnosed here. The audit's own words for this
rule are `**FALSIFIED** — seeded and caught nothing`, confirmed by a live bench run today.

## The cause, verified — not a missing domain, a wrong question

`agent_config_patterns._EXFIL_WEBHOOK` is a literal alternation over known-bad hosts —
`webhook.site`, `requestbin.com`, `pipedream.net`, `discord.com/api/webhooks`, the pastebin
family, a few tunnels. **Every one of the 8 seeded attacks uses a plausible domain instead:**

| sample | sink it posts to |
|---|---|
| `-01` | `https://analytics.example.com/collect` |
| `-03` | `https://evil.example.com/sink` |
| `-06` | `https://metrics.internal.company.io/ingest` |

That is not the corpus being unfair. It is what the attack looks like: **nobody exfiltrating from
an agent-context file uses `webhook.site`.** They use a host that reads as telemetry. A blocklist
can only ever catch the naive case, so adding domains is the `#259` treadmill one detector over —
each addition matches the corpus at hand while the next unlisted host is already being written.

**The rule's NAME and DESCRIPTION over-claim, and that is the part that misleads.** It presents as
"Exfiltration sink in agent body … a likely-malicious data leak vector"; the word doing the real
work is *known*, and a reader scanning the rule list does not see it. The rule list reads as
covering exfiltration. It covers a blocklist.

## A structural alternative, MEASURED (window 400, all three signals in one window)

Prototype: an outbound transmission verb (`POST`/`transmit`/`requests.post`/`fetch(`/…) + a
sensitive payload token (`session_token`/`credential`/`context snapshot`/`.env`/…) + an
`https?://` URL.

| | shipped | prototype |
|---|---|---|
| recall on the 8 seeded attacks | **0/8** | **5/8** |
| FP `benign` (16) | — | **2** |
| FP `benign-ordinary` (24) | — | **1** |
| FP `benign-security-docs` (24) | — | **0** |

Still missed: `-02`, `-04`, `-05` — the three whose exfil directive sits far from its URL inside
long, otherwise-legitimate documentation. Widening the window past 400 recovers `-07` but starts
joining unrelated paragraphs, which is where the FPs come from.

## Why this is NOT shipped, and why that is not timidity

The +5 true positives cost 3 false positives, and **two of them land exactly where it hurts most**:

1. an **incident post-mortem narrating a past attack** — the precise class janitor#254 is open
   about. Shipping this trades one open issue against another.
2. a **benign-ordinary README documenting local dev setup** — that population is currently at
   **0%**, the cleanest signal the detector has.

Precision/recall on a security detector is a judgement about who reads the findings and what
FP-fatigue costs — janitor#254 exists precisely because that balance was already wrong once. It is
a USER decision, not a defect fix, so the measurement is delivered and the change is not made.

## The options, stated so the decision is a choice and not a default

- **A — ship the structural rule as-is.** 0/8 → 5/8; benign FP 8% → ~12%, benign-ordinary 0% → 4%.
- **B — ship it at a LOWER severity / advisory tier**, so recall improves without adding HIGH-severity
  noise to the population #254 is already about.
- **C — keep the blocklist, FIX THE NAME AND DESCRIPTION ONLY** (`known-exfil-domain-blocklist`), so the
  rule list stops implying coverage it does not have. Costs nothing, and is correct under every
  other option.
- **D — do nothing**, and let COVERAGE.md carry the falsification (it already does, honestly).

**C is orthogonal and should probably happen regardless** — it is a truthfulness fix, not a tuning
change, and it is the half of this that needs no judgement call.

## ⏵ USER DECISION — 2026-08-14 (supersedes the A/B/C/D framing below)

**"If the janitor detects an exfiltration it must immediately notify the main claude and the
user, but it must be sure. Make the thing verify before reporting."**

That is neither A nor B: both traded recall against false positives at the DETECTION layer, on the
assumption that a finding and an alarm are the same event. They are not, and separating them
dissolves the trade:

- **DETECT wide** — ship the structural rule (verb + payload token + URL in one window), because a
  blocklist provably cannot see the real attack (0/8, every sample posting to a plausible host).
- **VERIFY before the alarm** — a single pattern match is a SUSPICION. Only a candidate that
  survives an independent verification ladder may wake a human.
- **NOTIFY on verified only** — immediate push to the user AND a finding the main Claude sees;
  an unverified candidate is recorded at low severity and pushes nothing.

C is already shipped (`6ab6cc08`) and stays. D is refused by this ruling.

### The verification ladder (each rung INDEPENDENT of the match that raised the candidate)

Re-running the same regex is not verification — it is the same claim twice. Each rung must be able
to kill the candidate on evidence the trigger never looked at:

1. **Destination is really outbound** — not `localhost`/`127.0.0.1`/a private range, not a URL
   sitting inside a fenced example.
2. **Negative context** — the janitor#254 / TRDD-XOITBRIZ mask: prose NAMING the exfil as
   something to find, avoid, or narrate after the fact is not an instruction to perform it.
3. **Payload token is a real secret REFERENCE** — `${SECRET}` / a `.env` read / a token variable,
   not the English word "credential" in a sentence.
4. **The file is actually loaded AS INSTRUCTIONS** — `is_exfil_fp_path` already excludes
   fixtures / IOC catalogues / red-team samples, which are the corpus of an attack, not one.

**FAIL-CLOSED ON THE ALARM, NOT ON THE FINDING.** A candidate that cannot complete the ladder is
still RECORDED — silence would reintroduce the 0/8 blindness through the back door — it simply
does not push. The thing being made "sure" is the interrupt, not the observation.

### The re-measurement CONFIRMS the ruling, and shows why A and B were both wrong

Re-measured 2026-08-14 post-janitor#254 (report under `reports/janitor-HYV0SOC6/`). It is a
good-faith REBUILD from this card's design description — the original prototype was never
committed — so the absolute numbers are not comparable to the 5/8 above; the DELTA between the
two rows is, because both rows are the same rebuilt rule:

| | recall on the 8 seeded attacks | FP attributable to the rule, `benign` (40) |
|---|---|---|
| structural rule, UNMASKED | **3/8** (`-01`, `-06`, `-08`) | **1** — the incident post-mortem |
| structural rule, MASKED with the #254 discriminator | **2/8** (`-01`, `-06`) | **0** |
| shipped blocklist, for reference | 0/8 | 0 |

**The mask costs a real attack (`-08`) to buy the one false positive.** That is the whole A-vs-B
trade in one line, and it is a bad trade in both directions — which is exactly what the ruling
escapes. Detect UNMASKED and keep `-08`; run the negative-context rung at the ALARM layer, where
it kills the post-mortem before it can wake anyone. 3/8 recorded, 0 pushed falsely.

So the mask is a VERIFICATION rung, not a detection filter, and applying it at the wrong layer
silently discards true positives — the same mistake in the opposite direction from the blocklist.

### Why the ordering matters

An alarm nobody can trust is worse than no alarm: janitor#254 exists because that balance was got
wrong once already, and the cost was an agent learning to ignore the channel. So the push path is
the one place where a false positive is more expensive than a miss — and the ledger is the place
where the reverse is true.

## Acceptance

- [x] A decision is recorded among A/B/C/D — **superseded by the USER ruling above**
- [ ] The structural rule ships, with its recall AND per-population FP re-measured post-janitor#254
- [ ] The verification ladder is implemented, and each rung has a test proving it can KILL a
      candidate the trigger raised
- [ ] A verified exfil finding pushes to the user AND lands in the findings ledger; an unverified
      one lands in the ledger ONLY, and a test proves the unverified path pushes nothing
- [ ] If a rule ships: recall AND per-population FP are re-measured by `agent_context_bench.py`,
      and `COVERAGE.md` is regenerated so the claim matches the measurement
- [ ] If C ships: no rule id or description in `agent_config_patterns` claims coverage broader than
      its pattern delivers

## Notes and lessons learned
