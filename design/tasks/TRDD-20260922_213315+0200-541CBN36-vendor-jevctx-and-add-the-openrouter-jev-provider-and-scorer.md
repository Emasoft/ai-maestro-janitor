---
trdd-id: 541CBN36
title: Vendor jevctx and add the OpenRouter Jev provider and scorer CLI
column: todo
created: 2026-09-22T21:33:15+0200
updated: 2026-09-22T21:34:41+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: feature
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-22T21:33:15+0200
parent-trdd: RAEGS1D5
derived: true
---

# Vendor jevctx and add the OpenRouter Jev provider and scorer CLI

NPT of TRDD-RAEGS1D5 (card 3+4 parent). Card 2 of docs_dev/jev-compaction-spec.md — must land
before card 3 implements the compacted-context builder.

- Vendor jevctx/ from https://github.com/Waxmell114514/jev-compaction at commit
  6d33376a759b95dc53b2169eed2cad32842036ca into scripts/lib/jevctx/ verbatim (MIT; keep
  LICENSE as scripts/lib/jevctx/LICENSE; record sha + date in scripts/lib/jevctx/VENDORED.md).
  Do not run its tools/ or docs/. Copy its tests into tests/jevctx/ only if they pass under
  the project's pytest unchanged; otherwise leave them out and say so.
- scripts/lib/jevctx/openrouter.py: class OpenRouterJevClient implementing JevClient: base URL
  https://openrouter.ai/api/alpha, path /decisions, model ~typesafe/jev-latest, key from
  OPENROUTER_API_KEY (constructor arg overrides; missing -> JevAuthError), same RetryPolicy,
  RateLimiter, check_request_budget, parse_answer as HttpJevClient; additionally read
  usage.cost into the usage record.
- Provider selection: CLAUDE_PLUGIN_OPTION_JEV_PROVIDER in {openrouter, typesafe}, default
  openrouter. No inference from which keys exist. Missing key for the selected provider is an
  ERROR (arm time and compaction time), surfaced as a heartbeat drift line.
- scripts/jev_compact.py -- PEP-723 script, dependencies = ["httpx>=0.27"], sub-commands:
  - probe -- one Noul question; exit 0 on a parsed float, non-zero with the reason otherwise.
    arm_prepare.py calls it when the provider is enabled; a failure is printed and blocks
    nothing except Jev compaction itself.
  - compact --transcript P --out F [--digest-tokens 4000] [--budget-tokens 8000] -- see card 3.
  - expand --transcript P ID -- prints the original bytes of item ID (<uuid>:<n>).
- Tests (real, no mocks of the network unless nothing else is possible -- a FakeJevClient
  from jevctx.testing counts as the library's own test double): provider selection,
  missing-key error, request body shape against the live-probe fixture recorded in
  reports/compaction-replacement/20260922_210008 (as a static fixture), expand round-trip.

## Facts the design rests on (measured 2026-09-22, reports/compaction-replacement/)

- Live probe: POST https://openrouter.ai/api/alpha/decisions, model ~typesafe/jev-latest,
  Authorization: Bearer $OPENROUTER_API_KEY, body {model, state, questions} -> HTTP 200 in
  0.41 s; response {model, answers:{k:{type:"noul",noul:float}}, usage:{input_tokens,
  output_tokens, cost}, id, provider}. jev.py's parser tolerates the extra fields.
- OPENROUTER_API_KEY is exported; TYPESAFE_API_KEY is not.
- Hook scripts are stdlib-only PEP-723 (#!/usr/bin/env -S uv run --script --quiet, no
  dependencies). The scorer must therefore be its OWN PEP-723 script declaring httpx>=0.27
  and be called as a subprocess -- the same shape the llm-ext subprocess has today. That also
  gives the daemon lane a CA bundle (httpx -> certifi), cf. TRDD-X6I04SAO.
- jevctx: JevClient protocol = one method ask(state, questions) -> dict[str, Answer]
  (types.py:359-363); BudgetPlanner chunks under 57.6k/28.8k tokens; scorer.score_items
  fans batches out; fail-open scores 1.0 on scorer failure (scorer.py:1-8); Noul only.

## Approval log

- 2026-09-22T21:33:15+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
