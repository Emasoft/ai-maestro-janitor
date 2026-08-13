---
trdd-id: HYV0SOC6
title: exfil-webhook-sink is a known-domain blocklist wearing the name of an exfiltration detector
column: backburner
created: 2026-08-13T09:09:30+0200
updated: 2026-08-13T09:09:30+0200
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

## Acceptance

- [ ] A decision is recorded among A/B/C/D
- [ ] If a rule ships: recall AND per-population FP are re-measured by `agent_context_bench.py`,
      and `COVERAGE.md` is regenerated so the claim matches the measurement
- [ ] If C ships: no rule id or description in `agent_config_patterns` claims coverage broader than
      its pattern delivers

## Notes and lessons learned
