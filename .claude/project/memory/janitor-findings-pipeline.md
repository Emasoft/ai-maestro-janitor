---
name: janitor-findings-pipeline
description: "where do janitor findings/drift lines actually get recorded / what is the findings ledger / where does a sev>=HIGH finding get pushed to a human / what does janitor-findings show / findings-ledger.ndjsonl format / notify.py human channel gates / how does SessionStart surface unread findings"
ocd: 2026-08-02
lmd: 2026-08-02
metadata:
  node_type: memory
  type: project
  tier: component
  functionality: findings-pipeline
---

# janitor-findings-pipeline


^ATOM-TRY9-R3YO [desc:"The findings pipeline (v0.51.0): findings_ledger.record() is the one choke point feeding three sinks — the per-project NDJSON ledger, the firing session's drift line, and the daemon-only human push vi", keywords: findings_ledger_single_choke_point findings-ledger.ndjsonl_frozen_line_shape notify.py_daemon_only_human_channel sessionstart_unread_findings_cap janitor-findings_on_demand_browser, type: project, ocd: 2026-08-02, lmd: 2026-08-02]

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

## Governed by

- [[janitor-architecture]] — the architecture hub.

## See also

- [[janitor-detector-and-hook-roster]] — the detectors that raise the findings this pipeline records.


^ATOM-ZFUE-H8IZ [desc:"a checker must state what it scanned and how many findings on EVERY run — silence cannot distinguish clean from did-not-look, and that ambiguity produced three wrong conclusions in one night", keywords: detector_reported_nothing_did_it_even_run silence_is_not_a_verdict empty_output_means_clean_or_means_skipped 0_findings_printed_nothing checker_must_state_coverage stale_binary_reported_old_counts, type: reference, ocd: 2026-08-05, lmd: 2026-08-05]

A janitor checker MUST state its coverage on every run — what it scanned and how many findings — never rely on silence to mean clean. Empty output cannot distinguish "nothing is wrong" from "I did not look", and both a human and the heartbeat consume the same stream.

Two checkers were fixed for this on 2026-08-05. `memgrep lint` gated its summary on a non-empty finding list, so a clean corpus emitted NOTHING — empty stdout, empty stderr, exit 0 — byte-identical to a run that scanned nothing (e4e5ff12, janitor#191). The heartbeat separately reported STALE counts because it ran an installed binary predating the fix, and `--version` is frozen at 0.1.0 so nothing surfaced the skew (janitor#193).

Cost when it goes unfixed: a clean scope was read as a skipped root, producing a bug report, then an opposite claim that findings were being hidden, then a retraction of both — three wrong conclusions from one empty stream. The corpus never changed; only the confidence with which it was described did.

So a finding count is not enough on its own: emit the SCOPE too (`0 finding(s) … (1 scope(s): LOCAL)`). A bare "0 findings" still cannot prove the right corpus was scanned.

## Notes and lessons learned
