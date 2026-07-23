---
spec: wikimem-memgrep
spec-version: 1.0.0
status: normative
created: 2026-07-23T15:03:35+0200
updated: 2026-07-23T15:03:35+0200
maintainer: ai-maestro-janitor
project-id: ai-maestro-janitor
requested-by: Emasoft (owner request, 2026-07-23)
implementations:
  - "the recall + authoring RULE — ~/.claude/rules/markdown-memory-recall.md (teaching prose) + rules/references/markdown-memory-recall-full.md (on-demand detail) — canonical repo Emasoft/ai-maestro-janitor"
  - "memgrep — the Rust CLI + SQLite sidecar index — scripts/memgrep/src/{main.rs,memory.rs,index.rs} (this repo)"
  - "the editorial + safety layer — scripts/lib/{memory_txn,memory_edit_verify,memory_scopes,memory_settings}.py, scripts/memory_txn_cli.py, scripts/wikimem_syntax_lint.py, scripts/detectors/{wikimem-syntax,memory-maintenance,memory-librarian,memory-scope-leak}.py (this repo)"
  - "the single curator agent + per-chore skills — agents/janitor-memory-subconscious-agent, skills/janitor-memory-{recall,write,update,atomize,repair,split,merge,consolidate,conflict,harvest} (this repo)"
---

# The wikimem + memgrep conformance SPEC

**This file is the SPEC, not a rule.** It is the single, versioned, normative source the
wikimem memory system and its `memgrep` engine conform to. The implementations carry the
teaching prose (the recall rule) and the executable logic (the Rust CLI, the Python editorial
layer); this carries the testable contract. On any disagreement, the spec is the arbiter.

The system it specifies: a markdown **memory corpus** that is a navigable **wiki** of
knowledge ATOMS, indexed **by the question a future session will ask** (the symptom), recalled
and mutated through the `memgrep` CLI, corrected by **supersession never deletion**, and
maintained under a **separation of powers** — an agent authors and corrects content; the
janitor reorganises structure and surfaces contradictions but never edits a fact.

## WM-GREP — how to grep this spec

This is a REFERENCE doc: every normative clause starts with a stable `` `WM-<FAMILY>-NN` ``
anchor and a bold key-phrase, so you grep to the clause instead of reading through.

```text
WM-GREP  all clauses of a family:   grep 'WM-ATOM'   (SCOPE WIKI NOTE ATOM LES RCL AUTH CLI LINT MIG TXN SEP)
WM-GREP  one clause by id:          grep 'WM-ATOM-03'
WM-GREP  the authoritative verbs:   grep -A20 '@spec:memgrep-verbs'
WM-GREP  the atom / lesson grammar: grep -A6  '@spec:atom-grammar'   /  '@spec:lesson-grammar'
WM-GREP  the version stamp:         grep '^spec-version:'
WM-GREP  families: META=arbiter VER=versioning SCOPE=3-scope-model WIKI=wiki-layer
WM-GREP            NOTE=page-format ATOM=atom-model LES=lesson+supersession RCL=recall
WM-GREP            AUTH=authoring-contract CLI=memgrep-verbs LINT=lint-contract MIG=migrate
WM-GREP            TXN=editor-safety SEP=separation-of-powers CHK=conformance MNT=maintenance
```

## WM-META — the arbiter, and the anti-drift discipline

`WM-META-01` **arbiter** — this file is the single versioned normative source; where an
implementation and this spec disagree, THE SPEC WINS. Implementations cite it and conform.

`WM-META-02` **not-a-mirror** — the spec MUST NOT re-narrate the recall rule's teaching prose.
It states VALUES + `MUST`-assertions + the grammars + the boundary tests; the teaching prose
stays in `markdown-memory-recall.md`, the on-demand detail in its reference doc, the executable
logic in `memgrep` and the Python layer. A prose copy is a third disagreeing source waiting to
drift.

`WM-META-03` **why-it-exists** — the corpus's core invariants (the atom grammar, the lesson
form, the recall-by-symptom law, never-delete) live duplicated across the rule, the reference,
the Rust write verbs, the Python verifiers, and ten skills, with no arbiter. Two
independently-authored halves with no shared source is how a memory system silently rots: a
verb emits one shape while a skill hand-writes another, and recall quietly stops finding notes.

`WM-META-04` **the one law above all** — a memory is worthless if it cannot be FOUND from the
symptom. Every other clause serves WM-RCL-01. When two clauses appear to conflict, the reading
that preserves symptom-recall wins.

## WM-VER — versioning & conformance

`WM-VER-01` **semver-bump** — `spec-version` is semver. MAJOR = a `MUST` changes (a grammar
field renamed/removed, a scope root moved, a verb's contract changed, a lint check's verdict
inverted). MINOR = an optional field, a new verb, a new lint check, or a non-breaking
clarification (incl. adding a clause). PATCH = wording only.

`WM-VER-02` **conforms-to** — an implementation MAY declare `conforms-to-spec:
wikimem-memgrep@<version>`. A declared version ≠ this file's `spec-version` is a DETECTABLE
conformance failure — the whole point of the stamp.

`WM-VER-03` **clause-ids-stable** — every `WM-<FAMILY>-NN` id is STABLE, never reused, and
append-only. A conformance check may cite a clause by id; deleting a clause tombstones its id
(never re-assign it).

`WM-VER-04` **grammar-blocks-are-extracted** — the `@spec:`-marked verbatim blocks (verbs,
atom grammar, lesson grammar, scope table) are the machine-authoritative contract; a
conformance test extracts them verbatim and asserts the implementation matches. Prose around a
block never overrides the block.

## WM-SCOPE — the three-scope model + the write gate

`WM-SCOPE-01` **three-roots** — `MUST`: every note lives under exactly one of three roots, and
the ROOT decides its git fate:

<!-- @spec:scope-roots v1 — authoritative; the conformance test extracts the block below verbatim -->
```text
LOCAL    ~/.claude/projects/<slug>/memory/            outside any repo, never pushed        machine-private
PROJECT  <git-root>/.claude/project/memory/           git-tracked AND pushed to every clone  machine-agnostic
USER     <janitor-plugin-DATA>/memory/                never in a repo                        true across all projects
```

`WM-SCOPE-02` **slug** — `<slug>` is the project's absolute path with every non-alphanumeric
character replaced by `-`; LOCAL memory and LOCAL-scope TRDDs share the SAME slug root.

`WM-SCOPE-03` **the-write-gate** — before writing to PROJECT scope, `MUST` answer: *"would this
fact be TRUE and USEFUL for a stranger who clones this repo on a DIFFERENT machine?"* No →
LOCAL (or USER). PROJECT memory is PUSHED, so a machine-private fact written there leaks to
every future cloner.

`WM-SCOPE-04` **local-forcing-signals** — any of these forces LOCAL: an absolute `$HOME` path,
a username / hostname / email / secret, a private project name, the phrasing "on THIS machine"
/ "the owner decided", or one box's install state. A note MAY split: machine-agnostic fact →
PROJECT, per-machine state → LOCAL, cross-linked.

`WM-SCOPE-05` **unsure-is-local** — `MUST`: when scope is uncertain, choose LOCAL. Promoting
LOCAL→PROJECT later is deliberate; a leaked machine-private note is already pushed.

`WM-SCOPE-06` **precedence** — on a fact conflict across scopes, the MORE SPECIFIC scope wins:
**LOCAL > PROJECT > USER**.

`WM-SCOPE-07` **user-root-is-fixed** — the USER root is the janitor plugin's DATA memory dir, a
HARD-CODED path — never `${CLAUDE_PLUGIN_DATA}` of the *running* plugin, which is a different
plugin's dir. A USER-memory backup MIRROR outside the DATA dir survives a plain uninstall.

## WM-WIKI — the wiki layer

`WM-WIKI-01` **navigable-not-a-pile** — the corpus is a WIKI, not a flat bag of notes. Every
page is one of three tiers.

`WM-WIKI-02` **tiers** — a **hub** is one functionality's overview (carries `globs:` — the
files it owns); an **aspect** is a general rule shared by many elements (it RADIATES an
`## Applies to` list down); a **component** is ONE element's page (it RECEIVES, carrying
`## Governed by` up-links, and never re-copies a governing rule).

`WM-WIKI-03` **one-element-one-page** — `MUST`: one element = one page. A page that has grown
to cover two subjects is a WM-MIG / split candidate.

`WM-WIKI-04` **the-link-law** — `MUST`: every link is bidirectional. If A links to B, B links
to A — `Applies to` ↔ `Governed by` across tiers, `See also` ↔ `See also` laterally. Both ends
are wired in the SAME edit. A one-sided link is a WM-LINT defect.

`WM-WIKI-05` **relocate-never-delete-a-link** — when a lesson or fact MOVES to its rightful
owner page, the source keeps a `[[link]]`, never a hole; no knowledge is deleted, only
relocated (this is WM-LES-06 applied to structure).

`WM-WIKI-06` **entry-point** — each scope root has ONE overview/entry page (`memgrep overview
<root>`) that links out to the deeper pages; a fresh session navigates from it.

## WM-NOTE — the page / note format

`WM-NOTE-01` **frontmatter** — a page carries YAML frontmatter: `name` (== filename stem),
`description:` (QUOTED — see WM-RCL-02), `ocd:` (Original Creation Date, set once), `lmd:`
(Last Modified Date, bumped on every edit), and `metadata: {node_type: memory, type, tier}`.

`WM-NOTE-02` **type-enum** — `metadata.type` is one of `user | feedback | project | reference`.
For `feedback`/`project` the body `MUST` carry `**Why:**` and `**How to apply:**` lines.

`WM-NOTE-03` **mandatory-notes-section** — `MUST`: every page carries a
`## Notes and lessons learned` section, even when empty — it is the standing landing zone for
a correction lesson.

`WM-NOTE-04` **dates-bump** — `MUST` bump `lmd:` on every edit; `ocd:` is write-once.

`WM-NOTE-05` **curated-vs-raw** — a CURATED wiki page (authored via the verbs) is distinct from
a RAW harness buffer note; the corpus discriminator (`is_curated_wiki_page`) decides which
editorial passes apply.

## WM-ATOM — the atom model

`WM-ATOM-01` **atom-is-one-fact** — an ATOM is one findable unit of knowledge on a page,
addressed by a stable `^name`. One atom = one fact; an atom too long to be one fact is a
WM-LINT `oversized-atom` defect and a decomposition (WM-MIG / atomize) candidate.

`WM-ATOM-02` **grammar** — an atom marker is:

<!-- @spec:atom-grammar v1 — authoritative -->
```text
^<name> [desc:"<quoted prose ≤200 chars>", keywords:"<key_phrase> …", ocd:<date>, lmd:<date>, status:<valid|superseded>, superseded-by:<lesson-id>]
```

`WM-ATOM-03` **desc-is-quoted** — `MUST`: a non-slug `desc:` value is DOUBLE-QUOTED. An
unquoted prose desc breaks grep and the in-body filter (a WM-LINT `unquoted-desc` defect); a
clean legacy snake_case slug is grandfathered.

`WM-ATOM-04` **keywords-is-the-recall-surface** — `keywords:` carries the phrases a future
session will SEARCH with (the symptom), usually NOT the words the atom's prose uses. A **comma**
splits fields, **quotes** delimit the keywords value, a **space** splits the key-phrases within
it — so each is an `underscore_joined` key-phrase, never shredded. No keywords ⇒ no recall ⇒
the atom does not exist.

`WM-ATOM-05` **status-default-valid** — an atom's `status:` is `valid` unless explicitly
retired; a `superseded` atom carries `superseded-by:<lesson-id>` and is history — never applied,
follow the pointer. `status:` is emitted only when not the default (backward-compatible; old
pages parse unchanged).

`WM-ATOM-06` **id-is-stable-corpus-wide** — an atom's `^name` / lesson `id:` is stable and
unique corpus-wide; page-local `[^N]` footnote numbers renumber, so only the `id` is a durable
reference.

## WM-LES — the lesson form + the supersession protocol

`WM-LES-01` **lesson-is-an-atom-and-a-guardrail** — a `[^N]:` footnote whose bracketed metadata
block is the lesson's ADDRESS, followed by prose in the mandatory three-part form:

<!-- @spec:lesson-grammar v1 — authoritative -->
```text
[^N]: [id:ATOM-xxxx-xxxx, status:valid|superseded, superseded-by:ATOM-xxxx-xxxx, keywords:"<key_phrase> …", ocd:<date>, lmd:<date>] DO NOT <X>, BECAUSE <why>. DO <Y> instead.
```

`WM-LES-02` **required-metadata** — `id`, `status`, `keywords`, `ocd`, `lmd` REQUIRED;
`superseded-by` when superseded. Missing keywords ⇒ the lesson is unrecallable.

`WM-LES-03` **three-parts-all-present** — `MUST`: `DO NOT <X>` (the act about to be repeated),
`BECAUSE <why>` (the reason — without it the lesson cannot stop the repeat), `DO <Y> instead`
(the exit). One lesson = one mistake, ≤3 lines / ~40 words. Chronology/evidence go in the page
BODY or a TRDD, never the lesson.

`WM-LES-04` **body-required** — `MUST`: a `[^N]:` header has prose AFTER the `]` metadata
block. A metadata-only lesson is invisible to `memgrep find --only-notes` (a WM-LINT
`empty-lesson-body` defect).

`WM-LES-05` **correction-is-supersession** — `MUST`: correcting a WRONG fact is a supersession,
NEVER a delete or an overwrite and NEVER a `-v2` duplicate page. Run `memgrep add-lesson
--supersedes --atom <id>` FIRST — it embeds the atom's CURRENT body verbatim as
`SUPERSEDED BODY: <old>` and records the WHY as a dated lesson — THEN clean the atom's body to
the new truth, keeping the SAME id.

`WM-LES-06` **never-delete-only-relocate** — `MUST`: knowledge is never deleted, only
superseded (demoted to a dated guardrail) or relocated (moved to its owner page with a link
left behind). Only a pure typo / formatting slip is edited in place. The sole deletions
permitted are a page memgrep can no longer PARSE (repaired, not lost) and the structural
removal of a page whose atoms all migrated away.

`WM-LES-07` **superseded-carries-its-body** — `MUST`: a lesson whose text supersedes an atom
contains the literal `SUPERSEDED BODY:` marker carrying the verbatim old atom body. A
supersession without it is a WM-LINT `superseded-without-body` defect AND a WM-LES-06 violation.

`WM-LES-08` **lessons-travel-with-their-atom** — an atom's dated superseded-lessons ARE its
changelog; on a WM-MIG move they TRAVEL with the atom (with the references they use), except a
reference also cited by another atom, which stays and is copied.

## WM-RCL — the recall protocol

`WM-RCL-01` **index-by-the-question-not-the-answer** — `MUST` (the load-bearing law): a note is
found from the SYMPTOM, not the solution. `description`/`title`/`tags` and atom/lesson
`keywords` carry the words a future session will have when the problem RECURS — the user's
words, the error text, the symptom — NOT the jargon of the fix. Recall is two-hop: a symptom
query lands on the note; the note's BODY gives the answer.

`WM-RCL-02` **recall-surface-is-ranked** — `memgrep recall` ranks on `description + title +
tags` ONLY; the fix's jargon in the body does not surface the note. This is WHY WM-ATOM-03 /
WM-ATOM-04 / WM-LES-02 make the symptom the mandatory quoted/keyword field.

`WM-RCL-03` **recall-before-acting** — before debugging a recurring problem, making a design
decision, or acting on a recurring alert, an agent RECALLS first ("have we hit this before?")
across the three scope roots, most-specific first.

`WM-RCL-04` **lessons-are-part-of-the-memory** — reading any memory means also reading its
`[^N]` lessons; `memgrep recall`/`find` auto-resolve and append them. A recalled note without
its guardrails is half a memory.

`WM-RCL-05` **write-after-solving** — after solving a non-trivial problem or making a decision
not derivable from the code, capture it into the page that OWNS the subject (RECALL first, so
you UPDATE rather than duplicate).

## WM-AUTH — the authoring contract

`WM-AUTH-01` **route-through-a-verb** — `MUST`: do not hand-author wikimem markdown. Every
write goes through a memgrep write verb (`new-page` / `add-atom` / `add-lesson` / `migrate`),
which synthesise valid syntax by construction. Hand-editing is reserved for an in-place REPAIR
of existing prose, and even then the atom/lesson SYNTAX `MUST` match what the verbs emit.

`WM-AUTH-02` **validate-and-lint-after-every-edit** — `MUST`: every editorial step ends with
`memgrep validate <page> && memgrep lint <page>`. A non-zero exit is a defect to fix NOW,
before moving on.

`WM-AUTH-03` **pick-scope-first** — `MUST`: run the WM-SCOPE-03 write gate BEFORE writing and
route LOCAL / PROJECT / USER accordingly; unsure → LOCAL.

`WM-AUTH-04` **stay-on-topic** — a case page holds CASE facts; a transferable way of WORKING
(how to diagnose/verify/falsify) belongs to the methodology page that owns it (nearly always
USER scope), not scattered into a case page.

## WM-CLI — the memgrep verb surface

`WM-CLI-01` **verbs** — `memgrep` dispatches EXACTLY these verbs (main.rs), these spellings:

<!-- @spec:memgrep-verbs v1 — authoritative; the conformance test extracts the block below verbatim -->
```text
index
reindex
validate
links
lint
fact
recall
find
find-claude-mem-ref
atom
atom-page
overview
add-atom
new-page
add-lesson
migrate
```

`WM-CLI-02` **read-verbs** — `recall` (rank by symptom), `find` (keyword DSL: `+must`,
`-exclude`, `"exact phrase"`, wildcards; `--only-notes` searches the lessons), `fact`, `atom`,
`atom-page`, `links`, `overview`, `find-claude-mem-ref`. Reads are free of side effects.

`WM-CLI-03` **write-verbs-synthesise-syntax** — `new-page` (valid frontmatter + mandatory Notes
section; refuses to overwrite), `add-atom` (`--desc` stored QUOTED ≤200 chars; id/dates/syntax
synthesised so a malformed atom is impossible), `add-lesson` (anchors `[^N]` from the atom
body; DO-NOT/BECAUSE/DO on stdin).

`WM-CLI-04` **add-lesson-supersedes** — `add-lesson --supersedes --atom <id>` `MUST` embed the
atom's current verbatim body as `SUPERSEDED BODY:` and record `supersedes:<atom>`; the optional
`--retire-atom` sets the atom marker `status: superseded, superseded-by:<lesson-id>`
(idempotent). Default correction is in-place same-id (WM-LES-05), never a duplicate.

`WM-CLI-05` **index-sidecar** — the corpus is indexed into a SQLite sidecar (`.memgrep/`);
`index`/`reindex` build/refresh it; `validate` checks index/page health. The file watcher
debounces ~500 ms behind writes — a consumer `MUST NOT` re-query in the same turn it wrote.

`WM-CLI-06` **token-lean-output** — reads return greppable, capped output (`path — description`
+ resolved lessons); consumers read the top 1–3 hits, not the whole corpus.

## WM-LINT — the lint contract

`WM-LINT-01` **deterministic-fp-free** — `MUST`: `memgrep lint` is deterministic and
false-positive-free; every check it fires is a real defect an author must fix. Example prose
inside backtick inline spans or fenced code is masked (a `[^N]` token in inline code is not a
footnote).

`WM-LINT-02` **the-checks** — `lint` fires on, at minimum: `unquoted-desc` (WM-ATOM-03),
`empty-lesson-body` (WM-LES-04), `oversized-atom` (WM-ATOM-01), `superseded-without-body`
(WM-LES-07), a dangling / unreferenced footnote, and a one-sided `[[link]]` (WM-WIKI-04).

`WM-LINT-03` **oversized-budget** — the `oversized-atom` budget is corpus-tuned (default 1500
chars, env `MEMGREP_ATOM_MAX_CHARS`, `0` disables) — set from the live atom-size distribution to
flag only the genuinely-bloated tail, not the healthy median.

`WM-LINT-04` **the-commit-gate-is-a-delta** — the transaction commit gate (WM-TXN-04) blocks
only lint violations an edit INTRODUCES (before(live) vs after(staged) counts), never a page's
pre-existing violation — the corpus carries legacy defects, so an absolute "block on any lint
hit" would reject every unrelated edit.

## WM-MIG — the migrate contract

`WM-MIG-01` **move-atom-plus-baggage** — `memgrep migrate <atom> --from A --to B` moves the
atom, its lessons, and the references they use — NEVER a hand-move (which drops lessons and
collides footnote numbers).

`WM-MIG-02` **keep-shared-refs** — a footnote used ONLY by the migrating atom MOVES; a footnote
also cited by another atom on the source STAYS on the source AND is COPIED (renumbered) to the
destination so the moved atom still resolves. This is the only dangling-free reading of "keep
the refs used by other atoms".

`WM-MIG-03` **renumber-on-collision** — moved references are renumbered to labels free on the
destination, rewriting definitions AND inline references together.

`WM-MIG-04` **guard-both-pages-first** — `MUST`: migrate pre-flight refuses if EITHER page has
a dangling/unreferenced footnote (that breaks the renumber arithmetic and corrupts both);
post-build re-proves both footnote-clean or writes nothing.

`WM-MIG-05` **atomic-enough** — `migrate` builds BOTH new page texts in memory, proves them
clean, then writes DEST first, SOURCE second. A crash between the two atomic writes leaves a
recoverable DUPLICATE, never a loss; any validation failure writes nothing ("both pages
unchanged" holds for every refusal).

`WM-MIG-06` **repoint-wikilinks** — a move that removes a slug repoints every `[[wikilink]]` to
it per WM-WIKI-04 so nothing dangles.

## WM-TXN — the editorial transaction + the verify oracle

`WM-TXN-01` **journaled-crash-safe** — every editorial pass that hand-edits staged markdown
(atomize / repair / split / merge / consolidate / conflict / harvest) rides a journaled,
crash-resumable, hash-guarded transaction (`memory_txn`): it snapshots each source's content
hash, stages writes/deletes, and commits atomically-enough to roll forward or abort cleanly.

`WM-TXN-02` **stale-source-refuses** — `MUST`: a commit whose source page changed since the
transaction began (hash mismatch) is a conflict — the transaction rolls forward or aborts, never
silently clobbers a concurrent edit.

`WM-TXN-03` **verify-proves-no-knowledge-lost** — `MUST`: a commit is gated by the
`memory_edit_verify` oracle, which proves the edit lost NO knowledge — every source lesson's
body survives, every load-bearing body fact survives, no dangling footnote/link is introduced,
merge/split/atomize/repair each satisfy their preservation contract. A pass that cannot prove
no-knowledge-lost ABORTS and flags a human.

`WM-TXN-04` **commit-also-gates-syntax** — `MUST`: the commit ALSO runs the WM-LINT delta gate
(WM-LINT-04) so a hand-edit can never COMMIT a newly-malformed atom, no matter how it was typed.
`verify_*` proves no knowledge lost; the lint delta proves no syntax broken; both are required.

`WM-TXN-05` **fail-open-master-switch** — the whole editor has a master kill gate; when
disabled, no editorial mutation occurs. The gate is fail-open in the sense that an inability to
prove safety blocks the commit, never forces it.

## WM-SEP — separation of powers

`WM-SEP-01` **agent-authors-janitor-reorganises** — `MUST`: an AGENT creates and corrects
CONTENT (writes a page, adds an atom/lesson, supersedes a wrong fact) but never reorganises
structure. The JANITOR reorganises structure and SURFACES contradictions (split / merge /
atomize / conflict / consolidate / harvest passes) but never edits a FACT.

`WM-SEP-02` **one-curator-agent** — the janitor's editorial work is ONE curator agent
(`janitor-memory-subconscious-agent`) that DYNAMICALLY loads exactly one chore skill per
dispatch — never one-agent-per-chore. It runs one pass on the due scope through the WM-TXN
transaction core, proves no knowledge lost, and returns one line + a report path.

`WM-SEP-03` **surfacing-is-not-mutating** — a detector (`wikimem-syntax`, `memory-librarian`,
`memory-scope-leak`) SURFACES a candidate (a malformed page, an aggregation/conflict candidate,
a scope leak) as a drift line and NEVER mutates the corpus; the mutation is a separate,
transaction-gated, verify-proven editorial pass.

`WM-SEP-04` **scope-leak-is-policed-at-write-and-swept** — PROJECT/USER scope is kept free of
machine/user-private data (WM-SCOPE-03/04) at WRITE time by the author and by a lazy
`memory-scope-leak` sweep; a found leak is redacted-in-place (fact kept, private part relocated
to LOCAL) with the WHY recorded as a dated lesson, never deleted.

## WM-CHK — conformance checks (who verifies what)

`WM-CHK-01` **memgrep-tests** — `scripts/memgrep`'s cargo suite asserts the write verbs
synthesise the WM-ATOM-02 / WM-LES-01 grammars, the WM-LINT-02 checks fire on crafted-bad and
pass crafted-good pages (incl. the inline-code FP), and `migrate` satisfies WM-MIG (shared-ref
partition, renumber-on-collision, malformed-source refusal, mid-txn abort leaves both pages
intact).

`WM-CHK-02` **editor-oracle-tests** — the `memory_edit_verify` Python suite asserts WM-TXN-03:
merge/split/atomize/repair preserve every lesson body + load-bearing fact, introduce no dangling
ref, and canonicalise retired `[[links]]`.

`WM-CHK-03` **commit-gate-test** — `test_memory_txn_cli` asserts WM-TXN-04 / WM-LINT-04: a
hand-edit that INCREASES a blocking lint class is rejected; a pre-existing violation carried
forward is NOT rejected.

`WM-CHK-04` **verb-block-conformance** — a check `MUST` extract the `@spec:memgrep-verbs` block
and assert `memgrep`'s dispatch (main.rs) accepts EXACTLY those verbs — the platelet that keeps
this spec from drifting from the CLI (janitor's to build, mirroring 3P-CHK-03).

`WM-CHK-05` **rule-floor** — the recall RULE `MUST` stay under the shipped-rules context-floor
cap (bulky detail in `rules/references/`); a rule that balloons past the cap is a
`test_rules_installer` failure. (WM-META-02 is why the detail belongs in the reference, not the
rule.)

## WM-MNT — maintenance

`WM-MNT-01` **living** — this file is MAINTAINED and NON-archived; a living spec cannot be an
archived TRDD.

`WM-MNT-02` **change-authority** — the load-bearing invariants (WM-RCL-01 recall-by-symptom,
WM-LES-06 never-delete, WM-SCOPE-03 the write gate, WM-SEP-01 the separation of powers) are the
system's constitution; any change to a `MUST` bumps `spec-version` per WM-VER-01.

`WM-MNT-03` **keep-it-greppable** — every clause `MUST` keep its `` `WM-<FAMILY>-NN` `` anchor +
a bold key-phrase at the line start, and WM-GREP `MUST` list every family. A new clause takes
the next free NN in its family (never a reused id, per WM-VER-03).

`WM-MNT-04` **memgrep-is-the-index** — the corpus index is memgrep's SQLite sidecar and ONLY
memgrep's; `MEMORY.md` is a deprecated stub — no agent adds pointers to it, loads it as an
index, or hand-trims it (hand-trimming the old ever-growing index is what corrupted the corpus
and moved the index into memgrep).
