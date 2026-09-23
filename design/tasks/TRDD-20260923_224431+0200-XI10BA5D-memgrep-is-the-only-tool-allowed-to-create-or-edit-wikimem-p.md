---
trdd-id: XI10BA5D
title: memgrep is the only tool allowed to create or edit wikimem pages
column: todo
created: 2026-09-23T22:44:31+0200
updated: 2026-09-23T22:53:31+0200
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
---

# memgrep is the only tool allowed to create or edit wikimem pages

Owner directive 2026-09-23 (verbatim): "what? delete the part about the edit tool. memgrep must be able to handle creation, editing, metadata/frontmatter, sections, toc, wiki links, references, atoms, notes, see also.., and all that by itself. no other tool must be allowed to edit except memgrep." Earlier the same evening (verbatim): "since there is my rule: only memgrep can write/edit wikimem pages. amd since there are malformed wikimem pages. then it is clear that the memgrep tool is broken. unless the premises are wrong." Context: two wikimem pages on this machine (AgentlensPro, ghbook) hold raw 0x08 bytes where a regex \\b was meant, and memgrep validate/lint pass them; the shipped rule markdown-memory-recall.md says 'edit ONLY via memgrep verbs or the Edit tool', so the rule itself allowed a non-memgrep writer. Scope: (1) delete every Edit/Write/shell allowance for wikimem pages from the plugin's rules, rules-reference, skills and agents; (2) audit memgrep's verbs against the owner's list (create, edit, frontmatter/metadata, sections, TOC, wiki links, references, atoms, notes/lessons, see-also) and build every missing capability in memgrep; (3) memgrep validate/lint flag control bytes as ERROR and every memgrep write verb refuses them (investigation running: reports/memory-control-bytes/); (4) a PreToolUse guard that denies Edit, Write, MultiEdit, NotebookEdit and shell writes to any wikimem memory path, so memgrep is the only writer in practice. Order: 1 now; 2 and 3 before 4, so agents are never left with no allowed way to make a needed edit.

## Approval log

- 2026-09-23T22:44:31+0200 — MANDATE issued by emanuelesabetta (min-approval-requirement: none). Pre-approved: issuer authority >= required approver. No approval request was sent.

## Owner directive 2026-09-23 (verbatim), the write contract

- Owner: "even if the whole wikimem is going to be rewritten, and the agent passes the whole content of the wikimem as a parameter to the memgrep, the memgrep guarantees that the content will be linted, fixed if possible, formatted correctly, verified against the mandatory rule of 10 key-phrases minimum per atom, and all specs checked and verified, or it will block the edit and return error."
- Derived by us: every memgrep write verb, including a whole-page replace, runs one pipeline before anything touches disk: parse, auto-fix what is safely fixable, format canonically, lint, validate every spec (at least 10 key-phrases per atom, frontmatter, TOC, links both ends, lessons, no control bytes), and writes atomically only on a clean result; otherwise it writes nothing and exits non-zero naming each violation.
- Owner: "memgrep is a writing gate ensuring that no malformed memory file is ever written."
- Owner: "atom over size : yes, warn only. but only up to a certain size. over a certain treshold that i let you decide, it should warn but also open a ticket with the janitor to lazily refactor the atom into 2 atoms."
- Threshold chosen by us under that delegation: over the existing budget (MEMGREP_ATOM_MAX_CHARS, default 1,500 chars) memgrep warns and writes (unchanged); over 2x the budget (3,000 chars by default, derived from the same env value so they cannot drift) it warns, writes, and opens ONE janitor support ticket per atom (deduplicated on the atom id) asking the janitor to lazily split that atom into two atoms. Corpus distribution for reference: median 559, p90 1,241, p95 1,624 chars.
