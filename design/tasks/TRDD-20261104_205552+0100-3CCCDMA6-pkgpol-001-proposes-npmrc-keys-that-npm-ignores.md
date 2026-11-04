---
trdd-id: 3CCCDMA6
title: PKGPOL-001 proposes npmrc keys that npm ignores
column: todo
status: tasked
created: 2026-11-04T20:55:52+0100
updated: 2026-11-04T21:02:07+0100
current-owner: main-agent@ai-maestro-janitor
created-by: main-agent@ai-maestro-janitor
task-type: bugfix
min-approval-requirement: none
scope: project
project-id: ai-maestro-janitor
assignee: main-agent@ai-maestro-janitor
mandate: true
mandated-by: none
approved: true
approval-judge: main-agent@ai-maestro-janitor
approval-datetime: 2026-11-04T20:55:52+0100
---

# PKGPOL-001 proposes npmrc keys that npm ignores

Measured 2026-11-04 with npm 11.20.0: of the four .npmrc keys PKGPOL-001 audits and proposes for npm (scripts/detectors/package-manager-policy.py, _audit_npmrc at line 350), npm recognises only audit-level. minimum-release-age, trust-policy and block-exotic-subdeps each make npm print "npm warn Unknown project config "KEY". This will stop working in the next major version of npm.", and none of the three strings occurs anywhere in npm's installed package. npm's release-age key is min-release-age, in days (npm's docs, config.md section "min-release-age"; @npmcli/config definitions.js flattens it to before = now - 86400000 * age); with min-release-age=36500 a dry-run install of is-number failed with ENOVERSIONS, so npm enforces it. So every npm repo that took PKGPOL-001's advice holds an .npmrc that looks like a release cooldown and a trust policy and enforces neither, the janitor#130 failure class, and the detector comment near line 206 that calls these knobs npm's is wrong. Fix: for npm, propose min-release-age in days (the threshold is in minutes, CLAUDE_PLUGIN_OPTION_PKG_MANAGER_MIN_RELEASE_AGE_MINUTES, so round up to whole days and say so); flag an existing minimum-release-age as unknown to npm, with the rename; stop proposing trust-policy and block-exotic-subdeps for npm, which has no such settings; keep audit-level. Check whether any janitor autofix path writes these keys into an .npmrc, and fix it the same way. Not tested: which older version npm picks for an intermediate window. Done when: on a real fixture tree, PKGPOL-001 for npm proposes only keys npm 11 recognises, each with its unit and cited to npm's docs, and an .npmrc holding minimum-release-age is flagged with the rename. Split from TRDD-1RSHQNJK.

## Approval log

- 2026-11-04T20:55:52+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Controls and corrections 2026-11-04

- 2026-11-04 controls on npm 11.20.0. The basis for "npm ignores these keys" is that npm defines none of them: minimum-release-age, trust-policy and block-exotic-subdeps each make npm print the Unknown project config warning, and none of them, in kebab-case or camelCase (minimumReleaseAge, trustPolicy, blockExoticSubdeps), occurs anywhere in npm's installed package (grep exit 1). One behavioural control agrees: with minimum-release-age=52560000 a dry-run install still added is-number 7.0.0, as with no .npmrc (this rules out units of minutes or coarser only). The dry runs with trust-policy and block-exotic-subdeps prove nothing on their own, because is-number has no dependencies and no earlier version to downgrade from. npm enforces min-release-age: 36500 and 36500.5 both fail with ENOVERSIONS. npm config accepts 0.0417 with no warning; whether npm honours the fractional part is not tested. npm/cli's config definitions define min-release-age at tag v11.10.0 and not at v11.9.0 (the fetched v11.9.0 file is 79 KB). The minutes unit and the other two names match pnpm's settings, a likely but unchecked origin of the detector's knob set. Correction to the body: the detector audits four keys and proposes three; audit-level is checked only when an .npmrc already sets it. Added to the fix: decide the npm version only from a packageManager pin or the minimum of an engines range; with no pin, propose min-release-age and say it needs npm 11.10 or later; with a pin below 11.10, say npm has no release cooldown there and point to the install firewall. On the read side, _audit_npmrc (near line 374, today reading minimum-release-age through _as_int) must read min-release-age as days, accept a fractional value, and compare days times 1440 with the minutes threshold. Done when, added, for a repo whose manager is npm or unknown: (a) an .npmrc whose min-release-age times 1440 is at least the minutes threshold, fractional values included, raises no release-age finding; (b) an .npmrc holding minimum-release-age, trust-policy or block-exotic-subdeps gets its own finding naming the key as unknown to npm, with the rename or the removal; (c) with a packageManager pin below npm 11.10, no min-release-age is proposed. Scope: npm and the unknown manager only; whether the pnpm, yarn and bun audits propose keys their manager honours is unchecked and needs its own card.
