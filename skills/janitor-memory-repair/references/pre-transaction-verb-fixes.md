# PRE-TRANSACTION verb fixes (moved verbatim from janitor-memory-repair/SKILL.md — TRDD-XI10BA5D)

## PRE-TRANSACTION verb fixes (run BEFORE `begin`, live, per candidate page)

Two checklist fixes are already atomic, locked memgrep writes and are never part of the
staged-copy pass — run whichever apply to the candidate page BEFORE
`memory_txn_cli.py begin`, never inside the staged copy and never after `commit`. Why a
stale sha strands the second verb call: [rationale](repair-background.md#pre-transaction-verb-fixes--extended-rationale).

**Re-read the page and recompute `--base-sha256` immediately before EACH verb call** —
never reuse one sha for both.

1. **The one-sided link — dry-run first, and only write if the TARGET is unaffected.**
   `reference-mem-topic` always wires both ends, but repair is single-page (IRON RULE 3)
   and a live write to the TARGET page could stale another chore's open transaction on
   it. Check before writing:

   Compute `sha` FIRST, from the page's current bytes, THEN read the page (the dry-run
   itself reads it live) and decide from that read — never decide first and checksum
   after, or a concurrent write between the two lands unnoticed:

   ```bash
   sha=$({ sha256sum <this page> 2>/dev/null || shasum -a 256 <this page>; } | cut -d' ' -f1)
   if [ -n "$sha" ]; then memgrep reference-mem-topic --page <this page> --to <target page> --dry-run; else echo "unreadable: <this page> — report and skip its verb fixes"; fi
   #   → "would link <this page> <-> <target page> (page {gains a link|unchanged}, to {gains a link|unchanged})"
   ```

   - `to unchanged` (only THIS page would change, or neither would — `page unchanged, to
     unchanged` means the link is already bidirectional, nothing to do) → safe, run it
     for real (a no-change run is harmless, but skip it outright if you can tell from
     the dry-run text that nothing would change):

     ```bash
     if [ -n "$sha" ]; then memgrep reference-mem-topic --page <this page> --to <target page> --base-sha256 "$sha"; else echo "unreadable: <this page> — report and skip its verb fixes"; fi
     ```
   - `to gains a link` (the TARGET would also change) → do NOT run it live. Skip this
     verb and report the one-sided link as a finding instead. Why this is the common
     outcome, not the edge case: [rationale](repair-background.md#pre-transaction-verb-fixes--extended-rationale).

2. **The atom `desc:` backfill.** Repeat the same pair — sha first, then re-read the
   page to confirm the atom still needs it — even if verb 1 just ran; its write changed
   the page's bytes, so step 1's `sha` is now stale for this call:

   ```bash
   sha=$({ sha256sum <page> 2>/dev/null || shasum -a 256 <page>; } | cut -d' ' -f1)
   if [ -n "$sha" ]; then memgrep update-mem-atom --page <page> --atom <id> --desc "<text>" --base-sha256 "$sha"; else echo "unreadable: <page> — report and skip its verb fixes"; fi
   ```

**On refusal** (stale sha, or any other error) from either verb: report the refusal and
continue with whatever other fixes the page still needs — a refused pre-transaction fix
is not a reason to skip the rest of the checklist, nor to abandon the staged-copy pass
for this page.

**Re-read the page again after the pre-transaction step, before `begin`.** A verb call
that wrote changed the page's bytes; re-diagnose the checklist against the CURRENT page
so the candidate set handed to the staged-copy pass reflects what's actually still
broken, not what was broken before the pre-transaction fixes landed. This re-diagnosis
happens BEFORE the "does this page still need `begin`/`commit`" decision below, not
after — the decision is made from the post-fix diagnosis, never the stale one that
selected the page as a candidate.

A page whose ONLY defects were these two verb-covered fixes (and both were applied, or
correctly skipped/reported) needs no `begin`/`commit` at all — the pre-transaction step
alone completed the repair. It still prints the normal per-page Output line and still
closes the claim (`set-report` + `complete`), exactly as a page that went through the
transaction core (see [janitor-memory-repair/SKILL.md](../SKILL.md)'s `## Output` and
`## Close the claim` sections).
