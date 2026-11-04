---
trdd-id: LTGVPK15
title: memgrep update-mem-atom --lesson --supersedes on a footnote lesson records an empty superseded body
column: todo
status: tasked
created: 2026-11-05T00:23:36+0100
updated: 2026-11-05T00:51:34+0100
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
approval-datetime: 2026-11-05T00:23:36+0100
---

# memgrep update-mem-atom --lesson --supersedes on a footnote lesson records an empty superseded body

## Observed

Run on 2026-11-05 on a USER-scope wikimem page. The target of --atom was a footnote lesson, [^3] (id ATOM-JCR7-7XF7), not a fact atom.

- Command (as recorded in a worker report; the keywords and the stdin text were not recorded): `memgrep update-mem-atom --lesson --supersedes --atom ATOM-JCR7-7XF7` with --page naming that page.
- It did not keep the id: it minted a new lesson, [^5] with id ATOM-QM35-MU89 (supersedes: ATOM-JCR7-7XF7). Exit status and stdout were not recorded in the report.
- The new lesson ends, verbatim from the page: "SUPERSEDED BODY: (empty)".
- The old lesson [^3] kept its text unchanged and the same id, so the correction recorded nothing of the old text.
- Afterwards `update-mem-atom --atom ATOM-JCR7-7XF7 --status superseded` retired the old lesson and the page then lints clean; the empty superseded body stays.
- The janitor's shipped memory-recall rule (markdown-memory-recall.md) says `update-mem-atom --lesson --supersedes` fixes a fact "SAME id"; the observed result minted a new id. The rule speaks of fixing a fact; this run targeted a footnote lesson.
- Expected reproducer (observed once): on a wikimem page that holds a footnote lesson, run memgrep update-mem-atom --page <that page> --lesson --supersedes --atom <that lesson's id>, with the keywords and stdin text the verb requires; the new lesson is expected to end 'SUPERSEDED BODY: (empty)' while the old lesson keeps its text.

## Related, quoted verbatim

`update-mem-atom --body-file` on a footnote lesson refuses. Reproduced on 2026-11-05 with --dry-run on [^5], page unchanged (sha256 prefix 3c2e44eb8185c636 before and after): "footnote-lesson with an EMPTY body span — there is no body to replace; edit its inline text directly (TRDD-XI10BA5D A3)". A footnote lesson's text is inline, so its body span is empty.

Probable cause (inferred; the --supersedes code path was not read): --supersedes copies the empty body span instead of the inline text, and does not fail closed the way --body-file does.

Cited: TRDD-XI10BA5D A3 (that card is in column verify_assumptions; its item A3 made the body replace explicit, via --body or --body-file).

## Expected

Copy the footnote lesson's inline text into SUPERSEDED BODY, or refuse as --body-file does. The help for --supersedes says it embeds the atom's CURRENT verbatim body and that the old fact becomes the atom's dated changelog; it does not say a footnote lesson is not a valid --atom target. If the call was a misuse, the verb should refuse loudly instead of writing "(empty)".

## Related, other

- A lesson on the same page, [^2] (ATOM-OMEJ-DS0T), carries `supersedes: ATOM-084V-N18B`, an atom id. Which verb wrote it, and whether a lesson may name an atom in supersedes, was not established.
- Dates (explained): the verbs stamped ocd and lmd 2026-11-04 on 2026-11-05 shortly after local midnight (+0100), which is still 2026-11-04 in UTC. The code uses neither Utc::now nor Local::now (grep over scripts/memgrep/src found no hit); the stamp is today_date() (scripts/memgrep/src/memory.rs:2287), the first 10 characters of now_iso_utc() (memory.rs:183), which converts SystemTime::now() with hand-written UTC civil-date math.

## Approval log

- 2026-11-05T00:23:36+0100 — MANDATE issued by main-agent@ai-maestro-janitor (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.
