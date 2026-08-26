---
name: janitor-findings-pipeline
description: "where do janitor findings/drift lines actually get recorded / what is the findings ledger / where does a sev>=HIGH finding get pushed to a human / what does janitor-findings show / findings-ledger.ndjsonl format / notify.py human channel gates / how does SessionStart surface unread findings / the lint count jumped and the corpus looks like it is rotting / are two findings counts even comparable / a checker printed nothing did it even run / silence cannot distinguish clean from did-not-look / a detector reported zero findings and I assumed it was clean / how many detectors ran and over what scope / stale binary reported old counts after a fix / did the memory corpus actually decay / how to compare a lint count across linter versions / memgrep --version carries the build commit / what does findings_ledger.record do"
ocd: 2026-08-02
lmd: 2026-08-16
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: findings-pipeline
publish-globally: false
---

# janitor-findings-pipeline


^ATOM-TRY9-R3YO [desc:"The findings pipeline (v0.51.0): findings_ledger.record() is the one choke point feeding three sinks — the per-project NDJSON ledger, the firing session's drift line, and the daemon-only human push vi", keywords: findings_ledger_single_choke_point findings-ledger.ndjsonl_frozen_line_shape notify.py_daemon_only_human_channel sessionstart_unread_findings_cap janitor-findings_on_demand_browser where_do_findings_actually_get_recorded what_is_findings_ledger.record what_pushes_a_sev_high_finding_to_a_human issue_catalog.raise_issue_records_once_per_finding_birth desktop_notification_default-on_webhook_opt-in 24_hour_cap_with_one-per-day_digest_fold fleet_github-config_digest_notification_channel, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

- **Findings pipeline (v0.51.0 — TRDD-FENWWB4E + TRDD-4649ZLE0, ARCHITECTURE.md §4/§5):**
  `lib/findings_ledger.py::record()` is the ONE choke point, three sinks — the AFFECTED
  project's `.janitor/state/findings-ledger.ndjsonl` (append-only INDEX, frozen line shape
  `{ts,sev,code,src,ref,msg}` ≤200 chars — the ai-maestro dashboard feed contract; bodies
  live in the ticket/TRDD named by `ref`), the firing session's drift line (own project
  only), and the human push. `issue_catalog.raise_issue` records once per finding birth;
  SessionStart injects unread entries (cap ~10 + fold, ≤1 KB, cursor-acked);
  `/janitor-findings` (backed by `scripts/findings_cli.py`) is the on-demand browser.
  `lib/notify.py` is the DAEMON-ONLY human channel (Tier 1 desktop notification
  default-on; Tier 2 opt-in webhook `CLAUDE_PLUGIN_OPTION_NOTIFY_WEBHOOK_URL`; gates:
  sev ≥ HIGH + content-hash dedupe + 24 h cap with one-per-day digest fold) — wired to
  supervisor alerts, the F4 keychain-degradation probe, task-quarantine entry, and the
  fleet github-config digest.


^ATOM-HJGX-SQLI [desc: "A lint/findings COUNT is only comparable within one linter version — check what the older binary could emit before reading a jump as decay", keywords: lint_count_jumped findings_exploded corpus_is_rotting_fast 240_findings_vs_50 count_comparison_across_versions did_the_memory_corpus_decay a_finding_count_is_only_comparable_within_one_linter_version newly_visible_debt_not_new_debt git_merge-base_is-ancestor_checks_rule_availability memgrep_--version_carries_the_build_commit a_trend_drawn_across_an_instrument_change_is_not_a_trend which_lint_codes_are_actually_comparable_across_versions, type: reference, ocd: 2026-08-16, lmd: 2026-08-16]

**A findings COUNT is only comparable within ONE version of the thing that counts.** On
2026-08-16 the heartbeat reported `memgrep lint: 240 finding(s)` against a card's 50 from three
days earlier — a 5× jump that reads as the corpus rotting. It was not. The linter had been
upgraded in between (11 crate commits), and `git merge-base --is-ancestor <feature-commit>
<old-binary-sha>` showed the OLD binary could not emit `publish-globally-missing`,
`atom-after-footer`, or the cross-page form of `link-one-sided` at all: **135 of the 240 were
structurally invisible three days earlier.** Newly VISIBLE debt, not new debt.

Only two codes were comparable, and they are the ones that carried the real signal:
`atom-oversized` 12→15 (refilling, nothing drains it) and `lesson-uncited` 23→23 (flat).

**The check is cheap and it is the whole discipline:** before reading a count as a trend, ask what
the EARLIER measurement could see. `memgrep --version` carries the build's commit for exactly this
(janitor#164), and `git merge-base --is-ancestor` answers "was this rule even present then" in one
command. A trend drawn across an instrument change is not a trend.

## Governed by

- [[janitor-architecture]] — the architecture hub.

## See also

- [[janitor-detector-and-hook-roster]] — the detectors that raise the findings this pipeline records.


^ATOM-ZFUE-H8IZ [desc:"a checker must state what it scanned and how many findings on EVERY run — silence cannot distinguish clean from did-not-look, and that ambiguity produced three wrong conclusions in one night", keywords: detector_reported_nothing_did_it_even_run silence_is_not_a_verdict empty_output_means_clean_or_means_skipped 0_findings_printed_nothing checker_must_state_coverage stale_binary_reported_old_counts a_clean_scope_was_read_as_a_skipped_root three_wrong_conclusions_from_one_empty_stream emit_the_scope_too_not_just_the_count byte-identical_stdout_between_clean_and_did-not-run version_frozen_so_nothing_surfaced_the_skew a_checker_must_state_what_it_scanned_on_every_run, type: reference, ocd: 2026-08-05, lmd: 2026-08-05]

A janitor checker MUST state its coverage on every run — what it scanned and how many findings — never rely on silence to mean clean. Empty output cannot distinguish "nothing is wrong" from "I did not look", and both a human and the heartbeat consume the same stream.

Two checkers were fixed for this on 2026-08-05. `memgrep lint` gated its summary on a non-empty finding list, so a clean corpus emitted NOTHING — empty stdout, empty stderr, exit 0 — byte-identical to a run that scanned nothing (e4e5ff12, janitor#191). The heartbeat separately reported STALE counts because it ran an installed binary predating the fix, and `--version` is frozen at 0.1.0 so nothing surfaced the skew (janitor#193).

Cost when it goes unfixed: a clean scope was read as a skipped root, producing a bug report, then an opposite claim that findings were being hidden, then a retraction of both — three wrong conclusions from one empty stream. The corpus never changed; only the confidence with which it was described did.

So a finding count is not enough on its own: emit the SCOPE too (`0 finding(s) … (1 scope(s): LOCAL)`). A bare "0 findings" still cannot prove the right corpus was scanned.

## Notes and lessons learned
