# Changelog

All notable changes to this project will be documented in this file.

## [0.29.0] - 2026-07-02

### Bug Fixes

- Test log-isolation + bootstrap fixture-account guard (TRDD-56374Z36)
- Maintenance mode respawns a dead daemon — survival ops survive maintenance (TRDD-8PH8YOIJ)
- Culprit min_share 0.2 -> 0.1 — validated on the first real fleet run (TRDD-OY0W6LX5)
- Make window-burn-rate.py executable (TRDD-OY0W6LX5)
- Devitalize SHELL_EXEC FP shape + MD004 prose wrap (TRDD-OY0W6LX5)
- Dedupe transcript usage by message.id — kill the 1.5-2.1x over-count (TRDD-OY0W6LX5)
- Pyright narrowing in dedupe + markdownlint config drift (TRDD-OY0W6LX5)

### Documentation

- Add OY0W6LX5 — window burn-rate early-exhaustion alarm (proposal, Tier-3)
- OY0W6LX5 — reframe around FLEET ATTRIBUTION (which project over-consumes) + spike-source; burn-rate is the trigger
- OY0W6LX5 approved (USER 'go', tier 3) — usage payload confirmed (resets_at both windows; live 7d burn 1.53x); column dev
- Add 56374Z36 (rotator test log-isolation leak + bootstrap guard) + 8PH8YOIJ (maintenance survival gap) — USER-approved
- 56374Z36 — cite the TRDD-14IY6MAD precedent (v0.18.2 autouse log-redirect fixture); today's leak is the same class from the bootstrap test module
- Add YRPUSIFY — cache-optimize hooks/agents/skills/rules (USER: 'immediately'); measured 7.6x cache rewrite factor + 160k/agent floor
- Land OY0W6LX5/56374Z36/8PH8YOIJ complete + YRPUSIFY P1 commit recorded

### Features

- Fleet attribution + window burn-rate alarm (TRDD-OY0W6LX5)

### Refactor

- Cache-stable injected text — bucketed counts, fixed templates (TRDD-YRPUSIFY P1)

