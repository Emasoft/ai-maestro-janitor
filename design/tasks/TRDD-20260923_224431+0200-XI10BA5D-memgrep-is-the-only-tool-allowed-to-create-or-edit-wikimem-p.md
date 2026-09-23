---
trdd-id: XI10BA5D
title: memgrep is the only tool allowed to create or edit wikimem pages
column: verify_assumptions
created: 2026-09-23T22:44:31+0200
updated: 2026-09-23T23:06:12+0200
current-owner: emanuelesabetta
created-by: emanuelesabetta
task-type: feature
min-approval-requirement: none
assignee: emanuelesabetta
mandate: true
mandated-by: none
approved: true
approval-judge: emanuelesabetta
approval-datetime: 2026-09-23T22:44:31+0200
eht: [FVYV6RSG, 6V7ZCKXF]
---

# memgrep is the only tool allowed to create or edit wikimem pages

## ⏵ STATE — READ THIS FIRST ON RESUME (authoritative; supersedes the body) — 2026-09-23

- Settled by the owner: memgrep is the only writer of wikimem pages; every write passes the gate (lint, auto-fix, format, 10 key-phrases per atom, all specs) or is refused; no per-call ticket cap; an atom over 2x the size budget warns and opens a split ticket; no publish until this card is done.
- Done: d20574f0 removed every Edit-tool allowance from the rules, 13 skills and the agent.
- Pending the owner (asked 2026-09-23): the gate-versus-tickets reading and the dedupe (section "Derived by us, PENDING OWNER CONFIRMATION").
- Open: the staged-copy shape (section "Open design questions for the migration"); the staged-copy skill list is a lower bound.
- Derived: FVYV6RSG and 6V7ZCKXF (eht), YSFQNR8Y related bugfix — use the minted ids.
- NEXT ACTION: read the memgrep capability-audit report when it lands, pick the staged-copy shape, then implement the gate pipeline and the missing verbs, then the PreToolUse guard.

Owner directive 2026-09-23 (verbatim): "what? delete the part about the edit tool. memgrep must be able to handle creation, editing, metadata/frontmatter, sections, toc, wiki links, references, atoms, notes, see also.., and all that by itself. no other tool must be allowed to edit except memgrep." Earlier the same evening (verbatim): "since there is my rule: only memgrep can write/edit wikimem pages. amd since there are malformed wikimem pages. then it is clear that the memgrep tool is broken. unless the premises are wrong." Context: two wikimem pages on this machine (AgentlensPro, ghbook) hold raw 0x08 bytes where a regex \\b was meant, and memgrep validate/lint pass them; the shipped rule markdown-memory-recall.md says 'edit ONLY via memgrep verbs or the Edit tool', so the rule itself allowed a non-memgrep writer. Scope: (1) delete every Edit/Write/shell allowance for wikimem pages from the plugin's rules, rules-reference, skills and agents; (2) audit memgrep's verbs against the owner's list (create, edit, frontmatter/metadata, sections, TOC, wiki links, references, atoms, notes/lessons, see-also) and build every missing capability in memgrep; (3) memgrep validate/lint flag control bytes as ERROR and every memgrep write verb refuses them (investigation running: reports/memory-control-bytes/); (4) a PreToolUse guard that denies Edit, Write, MultiEdit, NotebookEdit and shell writes to any wikimem memory path, so memgrep is the only writer in practice. Order: 1 now; 2 and 3 before 4, so agents are never left with no allowed way to make a needed edit.

## Approval log

- 2026-09-23T22:44:31+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

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

## Open design questions for the migration (from the review, 2026-09-23)

- Proposed, not settled: the txn core stages the copy and the agent runs memgrep verbs ON it. Open: link and backlink checks would resolve against the staging dir; id uniqueness must see the live corpus without seeing the staged twin; indexing the staged path leaves a phantom index row; memgrep lint may disagree with the txn verify_* gate (unverified; janitor#227 is about lint versus the chore candidate precheck, not verify_*); the commit step is itself a non-memgrep writer the PreToolUse guard must exempt. Alternative: single-page chores (repair, atomize, retro-lesson) write through memgrep directly, which is claimed atomic (unverified in this session); staging only for multi-page ops (consolidate, split, conflict), or begin/commit become memgrep verbs.
- Ticket plumbing: the [janitor-ticket] marker spawns one agent per ticket, so a store scan can open hundreds; dispatch must be rate-limited per fire (the owner removed the OPENING cap, not a dispatch limit). A wikimem lint ticket goes to the memory curator with the named verb it needs, or sits in a visible needs-verb state. Ticket bodies carry page id, rule code and anchor, never page text (LOCAL pages hold private paths). A USER-scope page linted from two projects must not get one ticket per project. The owner hold on the AgentlensPro and ghbook pages must be respected by the ticket path, or the owner told before publish.
- Split-chore defect seen in the index: macos-keychain and macos-keychain-incidents share the description "macOS keychain dialog opened hundreds of times" (janitor-compaction-floor-gate and -triggers also share one; cause not traced), so recall ties on them. The gate should lint a child page that copies its parent description. The four keychain pages (split in 8e5c898f) have no control bytes and lint only WARN under the current linter, which has no control-byte rule, no duplicate-description rule and no confirmed key-phrase-count rule (atoms missing ocd/lmd; verified those dates were already missing before the split 8e5c898f, not lost by it). Control-byte scan covered 0x01-0x1F except tab/LF/CR, 0x7F and U+0080-U+009F: none.
