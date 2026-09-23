---
trdd-id: XI10BA5D
title: memgrep is the only tool allowed to create or edit wikimem pages
column: verify_assumptions
created: 2026-09-23T22:44:31+0200
updated: 2026-09-24T00:13:19+0200
current-owner: janitor-main-session
created-by: Emasoft
task-type: feature
min-approval-requirement: none
assignee: janitor-main-session
mandate: true
mandated-by: none
approved: true
approval-judge: Emasoft
approval-datetime: 2026-09-23T22:44:31+0200
eht: [FVYV6RSG]
---

# memgrep is the only tool allowed to create or edit wikimem pages

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-23

- Settled by the owner: memgrep is the only writer of wikimem pages; every write is linted, auto-fixed where possible, formatted, checked against all specs (10 key-phrases per atom minimum) or blocked with an error; no per-call ticket cap; an over-size atom warns and, past a threshold, opens a ticket to split it.
- Ours, not the owner's: the threshold is 2x the size budget (the owner delegated it); the gate rule is a recorded DEFAULT pending the owner (refuse any ERROR in the result; section "Owner questions asked …"); "no publish until this card is done" is our reading of the owner's "wait to complete all before publishing".
- Done: d20574f0 removed the Edit-tool allowance from the rules, 11 skills (14 files) and the agent. NOT done: 6 locations still instruct a hand-edit of the staged copy (5 SKILL.md files plus consolidate's merge-protocol reference; the audit's section 12 swept commands/, heredoc and Python writers) (review section below). Capability audit landed 2026-09-23: reports/memgrep-sole-writer/20260923_225740+0200-capability-audit-final.md (gitignored; commands/ swept clean, verb-mapping for every staged-copy citation in its section 10.10).
- Pending the owner (asked 2026-09-23, unanswered, defaults recorded in section "Owner questions asked …"): old-atom key-phrase floor, gate rule, lint read-only by default, prose-only pages, keep or drop the duplicate-ticket dedupe; the A4 deferral of --type, --prop and Notes backfill to whole-page replace.
- Open: whether any chore still needs a staged copy, to be measured after step C (single-page chores use verbs on the live page, multi-page chores the two-page verbs; section "Implementation plan"). The earlier "memgrep verbs on the staged copy" proposal is superseded.
- Derived: FVYV6RSG (ticket routing, ids-only bodies, held-page exclusion; dispatch is already bounded by min(per_fire, budget, inflight), measured) is eht. Off the release path: 6V7ZCKXF (duplicate-description lint, not asked for by the owner, backburner). YSFQNR8Y (split chore copies the parent description) is blocked on this card because the migration rewrites the split skill; it unblocks when this card closes and is done right before release.
- NEXT ACTION: A1 (control-byte guard) is in flight. Step 0: the repair-skill half landed (7f983ec2, 0e964665); the --retire-atom fix has not started. Then A2 per section "Implementation plan".

Owner directive 2026-09-23 (verbatim): "what? delete the part about the edit tool. memgrep must be able to handle creation, editing, metadata/frontmatter, sections, toc, wiki links, references, atoms, notes, see also.., and all that by itself. no other tool must be allowed to edit except memgrep." Earlier the same evening (verbatim): "since there is my rule: only memgrep can write/edit wikimem pages. amd since there are malformed wikimem pages. then it is clear that the memgrep tool is broken. unless the premises are wrong." Context: two wikimem pages on this machine (AgentlensPro, ghbook) hold raw 0x08 bytes where a regex \\b was meant, and memgrep validate/lint pass them; the shipped rule markdown-memory-recall.md says 'edit ONLY via memgrep verbs or the Edit tool', so the rule itself allowed a non-memgrep writer. Scope: (1) delete every Edit/Write/shell allowance for wikimem pages from the plugin's rules, rules-reference, skills and agents; (2) audit memgrep's verbs against the owner's list (create, edit, frontmatter/metadata, sections, TOC, wiki links, references, atoms, notes/lessons, see-also) and build every missing capability in memgrep; (3) memgrep validate/lint flag control bytes as ERROR and every memgrep write verb refuses them (investigation running: reports/memory-control-bytes/); (4) a PreToolUse guard that denies Edit, Write, MultiEdit, NotebookEdit and shell writes to any wikimem memory path, so memgrep is the only writer in practice. Order: 1 now; 2 and 3 before 4, so agents are never left with no allowed way to make a needed edit.

## Approval log

- 2026-09-23T22:44:31+0200 — MANDATE issued by Emasoft (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Owner directive 2026-09-23 (verbatim), the write contract

- Owner: "even if the whole wikimem is going to be rewritten, and the agent passes the whole content of the wikimem as a parameter to the memgrep, the memgrep guarantees that the content will be linted, fixed if possible, formatted correctly, verified against the mandatory rule of 10 key-phrases minimum per atom, and all specs checked and verified, or it will block the edit and return error."
- Derived by us: every memgrep write verb, including a whole-page replace, runs one pipeline before anything touches disk: parse, auto-fix what is safely fixable, format canonically, lint, validate every spec (at least 10 key-phrases per atom, frontmatter, TOC, links both ends, lessons, no control bytes), and writes atomically only on a clean result; otherwise it writes nothing and exits non-zero naming each violation.
- Owner: "memgrep is a writing gate ensuring that no malformed memory file is ever written."
- Owner: "atom over size : yes, warn only. but only up to a certain size. over a certain treshold that i let you decide, it should warn but also open a ticket with the janitor to lazily refactor the atom into 2 atoms."
- Threshold chosen by us under that delegation: over the existing budget (MEMGREP_ATOM_MAX_CHARS, default 1,500 chars) memgrep warns and writes (unchanged); over 2x the budget (3,000 chars by default, derived from the same env value so they cannot drift) it warns, writes, and opens ONE janitor support ticket per atom (deduplicated on the atom id) asking the janitor to lazily split that atom into two atoms. Corpus distribution for reference: median 559, p90 1,241, p95 1,624 chars.
- Owner: "why are you limiting the tickets per memgrep call? if a memgrep linting found 50 issues that cannot be autofixed with a wikipage, you open 50 tickets. simple."

## Review of d20574f0 (2026-09-23)

- CONFIRMED contradiction, AT LEAST 5 skills (a lower bound: the sweep grepped only skills/, agents/, rules/ for Edit/staged-copy wording; commands/, Write-tool, heredoc and Python writers are not yet swept, and harvest CREATE likely writes by some other path (inferred, unverified)) still tell the agent to hand-edit the transaction staged copy while the rules say memgrep only: janitor-memory-repair (step "Edit ONLY the staged copy", SKILL.md:125+137), janitor-memory-atomize (SKILL.md:143), janitor-memory-harvest (SKILL.md:141), janitor-memory-retro-lesson (SKILL.md:103), janitor-memory-conflict (SKILL.md:132), consolidate references/merge-protocol.md:311. janitor-memory-bootstrap Edit-tool steps at :46 and :76 target .gitignore, not a wikimem page (only those two steps verified).
- Release condition: no publish until memgrep has the whole-page replace verb and a page CREATE path for harvest, and the staged-copy contradiction is resolved in whichever shape wins; until then a published build would make every page-editing chore abstain. Also before publish: the ticket path respects the owner hold on the AgentlensPro and ghbook pages, or the owner is told. That the owner release scope ("wait to complete all before publishing") covers this card is our reading.

## Derived by us, PENDING OWNER CONFIRMATION (2026-09-23)

- Our reading of the no-cap quote: every lint issue memgrep cannot auto-fix opens its own janitor ticket, not only oversized atoms.
- Gate vs tickets (the two owner rules collide on a page already carrying defects): a write is refused only for defects the write itself introduces; defects already on disk do not block, each gets a ticket. A write the gate refuses opens NO ticket (the content never landed).
- Our addition, owner may drop it: no duplicate ticket while one is open for the same issue. Key = page + rule code + stable anchor (atom id, lesson id, frontmatter field; never a line number). A ticket closed as "needs a new memgrep verb" suppresses re-filing and stays visible in the findings, so an abstain cannot loop.
- Asked the owner 2026-09-23 (awaiting answer): (1) the gate-versus-tickets reading above; (2) keep or drop the dedupe.
- Dedupe key refinements: a page-level defect (frontmatter, TOC, description) anchors on page + rule code + field or section name. When a split or a whole-page replace re-mints atom ids, the ticket whose anchor is gone closes and the next lint re-files what remains. The diff-scoped gate must match old and new atoms by content, not by id, or a whole-page rewrite would count every pre-existing defect as introduced and be refused.
- A ticket closed as "needs a new memgrep verb" records that verb's name and re-opens when memgrep gains it. The findings ledger quiet-filters, so these suppressed issues need their own listing to stay visible.
- SUPERSEDED 2026-09-23: the diff-scoped gate reading above is replaced by the strict default under "Owner questions asked …", after the advisor measured 0 ERROR findings across 345 pages.

## Open design questions for the migration (from the review, 2026-09-23)

- Proposed, not settled: the txn core stages the copy and the agent runs memgrep verbs ON it. Open: link and backlink checks would resolve against the staging dir; id uniqueness must see the live corpus without seeing the staged twin; indexing the staged path leaves a phantom index row; memgrep lint may disagree with the txn verify_* gate (unverified; janitor#227 is about lint versus the chore candidate precheck, not verify_*); the commit step is itself a non-memgrep writer the PreToolUse guard must exempt. Alternative: single-page chores (repair, atomize, retro-lesson) write through memgrep directly, which is claimed atomic (unverified in this session); staging only for multi-page ops (consolidate, split, conflict), or begin/commit become memgrep verbs.
- Ticket plumbing: the [janitor-ticket] marker spawns one agent per ticket, so a store scan can open hundreds; dispatch must be rate-limited per fire (the owner removed the OPENING cap, not a dispatch limit). A wikimem lint ticket goes to the memory curator with the named verb it needs, or sits in a visible needs-verb state. Ticket bodies carry page id, rule code and anchor, never page text (LOCAL pages hold private paths). A USER-scope page linted from two projects must not get one ticket per project. The owner hold on the AgentlensPro and ghbook pages must be respected by the ticket path, or the owner told before publish.
- Split-chore defect seen in the index: macos-keychain and macos-keychain-incidents share the description "macOS keychain dialog opened hundreds of times" (janitor-compaction-floor-gate and -triggers also share one; cause not traced), so recall ties on them. The gate should lint a child page that copies its parent description. The four keychain pages (split in 8e5c898f) have no control bytes and lint only WARN under the current linter, which has no control-byte rule, no duplicate-description rule and no confirmed key-phrase-count rule (atoms missing ocd/lmd; verified those dates were already missing before the split 8e5c898f, not lost by it). Control-byte scan covered 0x01-0x1F except tab/LF/CR, 0x7F and U+0080-U+009F: none.
SUPERSEDED 2026-09-23: the "Proposed, not settled" staged-copy bullet above is replaced by the Implementation plan step C (verbs on the live page; staging measured afterwards).

## Implementation plan (reviewed in two rounds, 2026-09-23)

- Evidence: capability audit reports/memgrep-sole-writer/20260923_225740+0200-capability-audit-final.md; advisor verdict 20260923_231527+0200-advisor-verdict.md; measurements 20260923_235959+0200-measure-and-verify.md and 20260923_233800+0200-measure2.md (all gitignored; the decisions are recorded here).
- Order, one reviewed commit each: 0 repair-skill steps that already have a verb; A1 control-byte guard + control-byte-in-page ERROR lint rule; A2 shared gate; A3 whole-page replace + create-with-content; A4 rename, unlink/retarget, delete --force repairs referrers; C skills move to verbs; B ticket consumer; D PreToolUse tripwire.
- A2 gate: new module pre_write.rs; atomic_write_page = commit(prepare); atomic_write_pages prepares every page before committing any (a refusal writes nothing anywhere); normalize in memory, validate the final bytes, write once; prepare resolves symlinks to the real page (measured: tmp+rename replaces a USER-side symlink with a regular file) and locks the real scope; symlink creation and SQLite reindex only in commit.
- A2 rules (the strict rule is a default pending the owner): refuse when the result has any ERROR; refuse an introduced one-sided link (no auto-wire, the error names reference-mem-topic); id-set rule over the whole prepared batch (an atom or lesson id that disappears from every page is refused unless superseded, migrated, merged or deleted by its own verb; lessons keyed on id:, never the [^N] label); an existing id keeps its ocd, and lmd never goes backwards; ocd is never invented for a legacy atom (missing ocd stays a warning and a ticket); lmd is set on atoms the write changed, disclosed on stderr; every auto-fix disclosed on stderr and in --dry-run; write verbs print the new sha256. No --drop flag.
- A3: set-mem-topic requires --base-sha256 on an existing page.
- B: lint output gains a trailing anchor field (measured: the three lint-output regexes tolerate trailing fields); tickets.py dispatch is already bounded by min(per_fire, budget, inflight); INFO never ticketed; the held AgentlensPro/ghbook pages excluded.
- Version skew: the memgrep on PATH is stale (152e7ce vs source 96c353a6) and there is no prebuilt-binary installer for other hosts; skills check each verb exists and abstain if not; every step tests the freshly built binary first on PATH; the release installs the new binary here. How other hosts get memgrep is an open item.
- D tripwire exempts memgrep itself, git restores (checkout, stash, reset, revert, merge, rebase, pull), safe-delete moves and the USER-memory mirror restore; its deny message names the memgrep verb to use.
- Later, separate proposal and the owner call: delete memory_txn.py page-writing path once the id-set rule covers its knowledge-loss checks.
- A2 also: formatting touches only bytes the write changed (protects --base-sha256 and the byte-identical verify_* checks); lint --fix writes through the same gate door, one page lock at a time, and a refused fix is reported without ending the run; extract lint_page_text from lint_paths_with as its own mechanical commit first; a new page meets the 15-phrase floor; a new atom, or one whose keywords or description change, meets the 10-key-phrase floor and comes out warning-free except a legacy missing ocd (stays a warning and a ticket); a body-only change keeps the lint floor.
- Step 0 also: fix update-mem-atom --retire-atom so it stamps superseded-by: whenever that key is absent, even if another status: is set.
- B also: an atom-oversized-critical WARN at 2x the size budget (the owner's size-ticket rule), routed through the split chore.
- A4 deferred, with the owner told: --type, --prop and Notes-section backfill go through whole-page replace for now; atomize-in-place and reposition-into-Superseded likewise. The owner listed frontmatter, sections and notes as capabilities, so these are rebuilt as verbs if the owner wants them.
- Tests the steps must add: an id reused with new content; a dropped atom or lesson refused; a lesson renumbering is not a loss; an ocd change refused; a write through the USER-side symlink keeps the symlink; an introduced one-sided link refused; lint --fix over a page with an existing ERROR; the precheck regex and candidate discovery after the anchor field; set-mem-topic without a base hash refused; a prose-only page rewrite; migrate, split, merge and delete still pass under the batch-scoped id rule.
A3 also (found 2026-09-24): update-mem-atom treats stdin as the new atom body whenever stdin is non-empty, even when only --desc or --keywords is passed; a worker piping a placeholder heredoc silently replaced an atom body (recovered from a pre-edit read). The id-set rule cannot see it (the id survives). Fix: the body is replaced only through an explicit --body-file or --body -, never implicitly from stdin; test it.

## Owner questions asked 2026-09-23 about 23:45, unanswered after 300 s; proceeding with the recommended default, owner may override

- Old atoms: an edit must reach 10 key-phrases only when it changes keywords or the description, or adds the atom; a body-only fix keeps the old floor. (Alternative offered: any change forces 10.)
- Gate rule: strict, refuse any write whose result has an error-level finding; warning-level problems on disk each get a ticket. (Alternative: block only defects the write introduces.)
- Lint writes: bare memgrep lint becomes read-only; fixes happen through the write gate or an explicit --fix. Five janitor callers rely on the silent fix today and get updated. (Alternative: keep fixing, one brief lock per page.)
- Prose-only pages: a whole-page rewrite that removes non-atom prose is refused until the page is atomized; removed facts move under Superseded. (Alternative: allow, printing every removed paragraph.)
- Still open from earlier: keep or drop the duplicate-ticket dedupe (tickets.py already dedupes natively).
