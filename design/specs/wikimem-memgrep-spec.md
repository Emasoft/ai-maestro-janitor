---
spec: wikimem-memgrep
spec-version: 1.1.0
status: normative
created: 2026-07-23T15:03:35+0200
updated: 2026-07-23T15:21:42+0200
maintainer: ai-maestro-janitor
project-id: ai-maestro-janitor
requested-by: Emasoft (owner request, 2026-07-23)
implementations:
  - "the recall + authoring RULE — ~/.claude/rules/markdown-memory-recall.md (teaching prose) + rules/references/markdown-memory-recall-full.md (on-demand detail) — canonical repo Emasoft/ai-maestro-janitor"
  - "memgrep — the Rust CLI + SQLite sidecar index — scripts/memgrep/src/{main.rs,memory.rs,index.rs} (this repo)"
  - "the editorial + safety layer — scripts/lib/{memory_txn,memory_edit_verify,memory_scopes,memory_settings}.py, scripts/memory_txn_cli.py, scripts/wikimem_syntax_lint.py, scripts/detectors/{wikimem-syntax,memory-maintenance,memory-librarian,memory-scope-leak}.py (this repo)"
  - "the single curator agent + per-chore skills — agents/janitor-memory-subconscious-agent, skills/janitor-memory-{recall,write,update,bootstrap,record-recent,atomize,repair,split,merge,consolidate,conflict,harvest,frequency} (this repo)"
  - "the PRIVATE user-memory subsystem — scripts/lib/user_mem_lib.py, scripts/hooks/on-prompt-submit-user-mem.py, commands/janitor-memory-user-{add,search,share}.md (this repo)"
  - "the proactive surfaces + scheduler — scripts/hooks/{on-prompt-submit-autorecall,post-edit-memory-correction}.py, scripts/lib/{memory_breadcrumb,memory_settings,memory_content_precheck,memory_migrate}.py, scripts/{memory_settings_cli,migrate_memory_scope}.py, scripts/detectors/{memorize-nudge,memgrep-index-health}.py (this repo)"
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
WM-GREP  all clauses of a family:   grep 'WM-ATOM'   (SCOPE WIKI NOTE ATOM LES RCL SCORE IDX BENCH AUTH CLI BASE FACT LINT MIG TXN SEP UMEM SURF SCHED HARV BOOT)
WM-GREP  one clause by id:          grep 'WM-ATOM-03'
WM-GREP  the authoritative verbs:   grep -A20 '@spec:memgrep-verbs'
WM-GREP  the atom / lesson grammar: grep -A6  '@spec:atom-grammar'   /  '@spec:lesson-grammar'
WM-GREP  the version stamp:         grep '^spec-version:'
WM-GREP  families: META=arbiter VER=versioning SCOPE=3-scope-model WIKI=wiki-layer
WM-GREP            NOTE=page-format ATOM=atom-model LES=lesson+supersession RCL=recall
WM-GREP            SCORE=ranking IDX=index+freshness BENCH=retrieval-benchmark
WM-GREP            AUTH=authoring-contract CLI=memgrep-verbs BASE=base-grep-mode FACT=fact-lines
WM-GREP            LINT=lint-contract MIG=migrate
WM-GREP            TXN=editor-safety SEP=separation-of-powers UMEM=private-user-memory
WM-GREP            SURF=proactive-surfaces SCHED=maintenance-scheduler HARV=harvest/raw-buffer
WM-GREP            BOOT=bootstrap+simple-skills CHK=conformance MNT=maintenance
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

`WM-META-05` **absence-is-a-gap-NOT-a-delete-license** — `MUST` (the safety invariant): a
behavior, file, store, verb, flag, detector, hook, or clause that is PRESENT in the
implementation but ABSENT from this spec is a spec GAP to be FILED (and the spec MINOR-bumped
to cover it), NEVER a non-conformance to be removed. An agent `MUST NOT` delete, disable, or
"clean up" any implemented behavior on the grounds that the spec does not mention it. The spec
is authoritative for what the artefacts MUST do, not exhaustive for everything they MAY do; the
implementation is the ground truth for what EXISTS. Conformance means the implementation
satisfies every `MUST` here — not that it does ONLY what is written here.

`WM-META-06` **deletion-needs-provenance-not-silence** — `MUST`: the only sanctioned removals
are those WM-LES-06 already names (a page memgrep cannot PARSE → repair; a page whose atoms all
migrated away → structural removal), and each is proven safe by the WM-TXN verify oracle. Any
other removal of memory content or memory machinery requires an explicit human decision recorded
in a TRDD — never an inference from this spec's silence. When in doubt, PRESERVE and file a gap
(WM-META-05).

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
plugin's dir.

`WM-SCOPE-08` **user-mirror** — `MUST`: the USER corpus has a backup MIRROR OUTSIDE the plugin
DATA dir (`~/.claude/ai-maestro-janitor-memory/`) so it survives a plain plugin uninstall (the
DATA dir is deleted on uninstall). SessionStart syncs primary→mirror and restores mirror→primary
after a data-dir loss (`memory_scopes.{resolve_user_mirror_dir,sync_user_memory_mirror}`). The
mirror is a memory STORE — never deleted as "junk".

`WM-SCOPE-09` **project-memory-is-git-tracked** — `MUST`: `<repo>/.claude/project/memory/` is
git-TRACKED and MUST NOT be gitignored (a gitignore-exception is enforced so PROJECT memory is
pushed and shared); the `project-memory-tracked` detector polices this.

`WM-SCOPE-10` **scope-migration-is-guarded** — re-scoping a LOCAL corpus to PROJECT
(`migrate_memory_scope` / `memory_migrate`) is a two-phase, human-reviewed operation: a
read-only privacy-scan classifier (`privacy_scan`/`classify_text`) proposes which notes are
PROJECT-safe, and the apply is gated by an ownership guard (`check_ownership` — refuses unless
running inside the repo it writes to) + a re-classify-now proof that the reviewed plan still
matches reality. A privacy-flagged note is NEVER auto-promoted.

`WM-SCOPE-11` **wiki-subnamespace-vs-raw-buffer** — each scope root has a CURATED
`wiki/` sub-namespace (`resolve_wiki_dir`) distinct from RAW harness buffer notes at the root;
`is_curated_wiki_page` is the discriminator that decides which editorial passes and which lint
apply. Both are memory — neither is scratch to be cleared (see WM-HARV).

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

`WM-WIKI-04a` **the-link-law-is-a-WITHIN-LAYER-law** — `MUST`: the reciprocity requirement
applies ONLY between pages in the SAME scope. A cross-scope edge is legal in one direction only
(WM-SCOPE), so it can NEVER be reciprocated — the reply would itself be a forbidden downward
link. Applying the LINK LAW across layers therefore reports every LEGAL upward link as a
violation, which is the lint punishing exactly the behaviour the model requires. Measured on the
live corpus when the scoping was added: one-sided-link reports fell **76 → 58**, i.e. 18 were
pure false positives.

**Generalisable:** when two rules constrain the same edge set, check that they cannot contradict
each other on any edge. Here "links are symmetric" and "cross-layer links are one-way" are
individually correct and jointly unsatisfiable for a cross-layer edge — so one must be scoped.
A lint that fires on correct behaviour trains people to ignore the lint.

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

`WM-NOTE-04` **dates-bump** — `MUST` bump `lmd:` on every edit that changes what the page
ASSERTS; `ocd:` is write-once. A MECHANICAL repair that changes no fact `MUST NOT` bump it — see
WM-MIG-07 for why (ranking tie-breaks on `lmd`, so a format pass would silently reorder the whole
corpus) and for the free audit it buys ("no `lmd` changed" proves the repair really was
mechanical).

`WM-NOTE-06` **footnotes-are-POOLED-under-three-sections** — a page's `[^N]` definitions live
under `# Notes`, `# Lessons Learned` and `# See also` (or `##` equivalents), and the render GROUPS
an atom's cited footnotes by WHICH section defines each. So a footnote's meaning comes from its
defining section, not from its number: the same `[^3]` is a lesson or a relation depending on where
it is defined. `WM-NOTE-03`'s mandatory `## Notes and lessons learned` is the always-present
landing zone; the other two are optional.

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

`WM-ATOM-05a` **a-retirement-MUST-be-READ-BACK-and-MARKED** — `MUST`: `status:`/`superseded-by:`
are parsed into the atom, stored in the index (`atoms.status`, `atoms.superseded_by`), and shown
on **every surface an agent reads before acting** — the ranked listing row AND the `recall <id>`
second hop — as `[SUPERSEDED → <id>]` (or `[SUPERSEDED]` with no pointer). One renderer serves
lessons and atoms, because a retired element that prints like a live one gets applied as current
knowledge, which is the single failure `status:` exists to prevent.

Two defaults are SAFETY properties, not tidiness: an absent or unrecognised `status:` reads
`valid` (so one typo cannot retire a live fact), and the `superseeded` / `superseeded-by`
misspellings are ACCEPTED on read (so one doubled `e` cannot resurrect a retired one as
guidance). Write only the canonical spelling.

A retired atom `MUST` stay findable — that is why it is retired rather than deleted — so `status`
is deliberately absent from `atoms_fts`. Until this rule, `--retire-atom` WROTE both fields and
nothing ever read them: the retirement was invisible and "show me the retired atoms" had no
answer. A field with a writer and no reader is indistinguishable from an unimplemented one.

`WM-ATOM-06` **id-is-stable-corpus-wide** — an atom's `^name` / lesson `id:` is stable and
unique corpus-wide; page-local `[^N]` footnote numbers renumber, so only the `id` is a durable
reference. Corpus-uniqueness is what makes a BARE id a sufficient retrieval key (WM-RCL-07), so
a duplicate id is a WM-LINT **CRITICAL**, not a nit.

`WM-ATOM-07` **the-parser-drops-silently-so-lint-MUST-mirror-its-drop-branches** — `MUST`: for
every branch on which the props parser DISCARDS input, the linter carries a check that fires on
exactly that input — no more, no less.

The props parser skips a comma-segment that has no `:` and one whose key is empty. Both are
silent: nothing warns, and the page still looks well-formed. The natural hand-authored
`keywords: a phrase, another phrase` therefore keeps `['a','phrase']` and **deletes every phrase
after the first comma** — i.e. it deletes most of the recall surface (WM-ATOM-04) while the page
reads as correct. Measured on the frozen benchmark corpus, repairing exactly this moved hit@1
from **21.7% to 95.7%**.

The generalisable rule: **a parser with a silent `continue` is a data-loss engine, and the only
FP-free detector of that loss is the parser's own drop condition.** A lint written from the
FORMAT's prose instead ("keywords should be underscore-joined") is a style opinion that both
misses real losses and fires on legitimate input; a lint written from the PARSER's branches is a
proof. So the check is derived from the code that drops, and a test pins the two together
(`test_dropped_props_matches_what_the_parser_actually_loses`).

`WM-ATOM-08` **allocate-identifiers-against-the-RAW-text, not the parsed tree** — `MUST`: when
allocating a new page-local label (the next `[^N]`), take the maximum over labels found by BOTH
the parsed tree AND a raw scan of the source.

Same law as WM-ATOM-07 seen from the WRITE side. A markdown parser materialises a footnote node
only for a BALANCED ref+def pair, so an unbalanced label — precisely the defect the linter exists
to catch — is INVISIBLE to the parsed tree. Allocating from the parsed maximum therefore hands out
a label that already exists in the file, silently merging a new lesson into a broken one. The
integrity check has the same blind spot for the same reason, which is why it re-scans the raw text
rather than reading the parser's output.

**Generalisable form: wherever a tool both READS through a parser and WRITES new identifiers, the
parser's blind spots become the writer's collision domain.** Allocate against the raw source.

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
`[^N]` lessons. A recalled note without its guardrails is half a memory. They arrive with the
SECOND HOP (`WM-RCL-07`), which resolves and appends them; they are NOT attached to every
search hit. "Read the notes" therefore means *take the hop on the note you chose*, not *skim
whatever the search dumped*.

`WM-RCL-06` **layered-output** — `MUST`: `recall`/`find` accept `--output basic|medium|full`
and **default to `basic`**.

| layer | prints per hit | lessons | keywords |
|---|---|---|---|
| `basic` (default) | ONE row: `<lmd>⇥<locator>⇥<description>`, TAB-separated fixed columns. The locator is the bare ATOM ID for an atom hit and the page's `name:` IDENTITY for a page hit — never a path (WM-RCL-06b). An absent date prints `-`, never empty, so a column never shifts | no | no |
| `medium` | that row + the atom's BODY. A page hit has no body of its own, so medium equals basic there | no | no |
| `full` | the rich record: `<path>#<atom-id> — <description>`, the SCORE, body, lessons, see-also | yes | yes |

`--with-keywords` / `--with-notes` add ONE dimension without leaving the lean layer, and an
explicit flag always overrides the layer's default. `full` is a DEBUGGING layer, not a
richer default.

`WM-RCL-06a` **the-score-is-observable-on-full** — `MUST`: `full` prints each hit's numeric score
(`⇥score: <n>`), and the lean layers `MUST NOT`. A ranking nobody can see cannot be debugged:
two results printed in order are identical on screen whether the first WON on score or merely
arrived first and survived the tie-break. That ambiguity is not hypothetical — it produced a
wrong conclusion in this project, where a probe read as "the keyphrase ranks higher" was in fact
scoring EQUAL and being ordered by the tie-break, concealing the inert-migration bug (WM-SCORE-04)
for a whole pass. It also makes WM-SCORE-05's tiers falsifiable from the CLI: an exact-keyword hit
must print ~1000, a loose-word one single digits.

The lean prohibition is equally load-bearing: their row shape is a promised parse contract
(WM-RCL-06), so an extra line there breaks every `cut -f2` consumer to help nobody — an agent
choosing a hop target reads the description, not the arithmetic behind it.

`WM-RCL-06b` **no-locator-is-ever-a-path** — `MUST`: a lean row's locator is an identity (atom id,
or a page's `name:`), never a filesystem path. A path is the single most expensive field the layer
can print, and it is the field the layer exists to remove.

Measured on both live corpora, 40 on-topic queries each: PAGE rows are **35–39% of all result
rows** and their absolute paths cost **~90 tokens apiece** — ~80–110 tokens per query, comparable
to the entire per-query budget WM-BENCH reports. The atom row was given a bare id for exactly this
reason; the page row was simply never given the same treatment, so the cheap layer went on paying
full price for a third of its output.

The identity is the page's declared `name:` (alias `topic:`), NOT the file stem. They disagree on
~3% of the live corpus, and on precisely those pages the stem is the identity the wiki does NOT
link by (WM-WIKI resolves `[[name]]` through `name:`) — printing it would hand those pages a
SECOND address. The stem remains the fallback when no `name:` is declared, and the path the last
resort, so a row can never print an empty locator and shift its own columns.

The walk and the index `MUST` resolve this identity identically (the walk via `page_identity`, the
index via the `topic` column `topic_of` already wrote). Two resolvers that disagree would make a
page's printed address depend on whether an index happened to be fresh — a divergence invisible in
either output alone.

`WM-RCL-07` **exact-id-second-hop** — `MUST`: `memgrep recall <ATOM-ID>` is an EXACT lookup
returning that one atom in full. A whitespace-free query is tried as an id first; when no atom
carries it, the query `MUST` fall through to the ordinary symptom search — a one-word symptom
query is indistinguishable from an id by shape alone, so the shortcut may never swallow one.

`WM-RCL-07a` **every-printed-locator-is-a-key** — `MUST`: whatever a lean row prints as its
locator has to RETRIEVE the thing it names. So `recall <page-name>` is an exact page lookup too,
tried after the atom id (an atom id is corpus-unique by construction, a page name only unique
within a scope, so the stronger key goes first) and falling through to the symptom search on a
miss, exactly as -07 requires.

Without this the two locator kinds would print in the SAME column with DIFFERENT meanings — one an
exact lookup, the other a search string that usually ranks its own page first. Indistinguishable on
screen, they would silently teach an agent to trust a key that works until the day it does not,
which is a worse failure than the path this layer removed.

`WM-RCL-08` **retrieval-cost-is-end-to-end** — cost is `tokens(search output) + tokens(the hop
it forces)`. `cost(basic) = N × row + 1 × atom` beats `cost(full) = N × everything` for every
`N > 1`, and the gap widens with `N`. A per-call measure would flatter `basic` and hide the hop,
so conformance is measured END-TO-END by `scripts/wikimem_bench.py` against a FROZEN fixture
corpus and a committed baseline (`tests/wikimem_bench/baseline.json`). A change `MUST NOT`
reduce accuracy or raise token cost beyond tolerance. Measured at the layer's introduction:
**441.4 → 247.0 mean tokens/query (−44%) at identical hit@1/hit@3/hit@10/MRR.**

`WM-RCL-05` **write-after-solving** — after solving a non-trivial problem or making a decision
not derivable from the code, capture it into the page that OWNS the subject (RECALL first, so
you UPDATE rather than duplicate).

## WM-SCORE — the ranking contract

`WM-SCORE-01` **rank-atoms-alongside-pages** — the ranked unit is the ATOM, interleaved with
PAGE hits by score. A page is a navigation surface; an atom is the fact. Ranking only pages
forces the reader to re-find the fact inside the page they were handed.

`WM-SCORE-02` **surface-is-the-symptom-fields** — ranking reads `description + title + tags`
(page) and `keywords` (atom) — the fields WM-RCL-01 requires to carry the symptom. The body is a
FALLBACK surface only.

`WM-SCORE-03` **precision-first** — if ANY candidate matched the symptom surface, ONLY
surface-matchers are returned; body-only matches surface exclusively when nothing matched the
surface. (This applies to symptom `recall`; a `find` row has already passed the `+`/`-` gate and
is kept unconditionally — a `+mandatory`-only query legitimately scores zero optional hits.)

`WM-SCORE-04` **keyphrases-are-atomic** — `MUST`: a multi-word key-phrase is ONE token, in the
stored surface AND in the query. Searching `"lossless migration"` is a DIFFERENT query from
searching `lossless` + `migration`, and the engine `MUST` be able to tell them apart.

This is violated by the obvious tokenizer. Splitting a query on `!c.is_alphanumeric()` makes `_`
a separator, so an `underscore_joined` phrase is shredded back into loose words *before scoring
begins* — after which an atom declaring `lossless_migration` and one declaring `lossless
migration` are indistinguishable, and the winner falls through to whatever the stable sort's
input order happens to be (alphabetical path order). Storing phrases atomically is therefore
necessary but **not sufficient**: a corpus-wide phrase migration is INERT until the scorer stops
destroying the query's phrase structure. Both halves ship together or neither is real.

`WM-SCORE-05` **tiered-match** — the score is TIERED, not a flat hit count: exact keyword-token
match ≫ contiguous phrase inside a keyword ≫ all query words present ≫ some present. A flat
"how many query words appear anywhere in the concatenated surface" gives a phrase and its
shredded words the identical score, which is WM-SCORE-04's failure expressed as arithmetic.

`WM-SCORE-06` **token-aware-matching** — `MUST NOT` rank on raw substring containment: `cat`
matching `concatenate` is a false hit that a substring scorer cannot distinguish from a real one.

`WM-SCORE-07` **rarity-weighting** — a distinctive phrase outranks a common word rather than
counting the same.

`WM-SCORE-08` **tie-breaks** — `score desc → lmd desc → path`. `path` is retained LAST purely for
determinism; dateless elements sort last. `--order asc` flips the SCORE only: "least relevant
first" must not also mean "oldest first", or the two keys fight.

Anything is better here than falling through to path order. A stable sort with no second key
orders equal scores ALPHABETICALLY, which is the least meaningful ordering available for
memories — and it is what decided the probe that made a corpus-wide phrase migration look
effective when it was inert (WM-SCORE-04).

`WM-SCORE-08a` **the-deferred-keys, and why they stay deferred** — an earlier revision of -08
specified `score desc → upward cross-layer in-degree desc → tier rank → lmd desc → path`. The two
extra keys are **NOT implemented**, and the reason is measured rather than pragmatic: **a tiered
scorer does not produce rank-1 ties**, so a key placed after `score` has almost nothing left to
decide.

Measured over four corpora (the conformant fixture + all three live scopes), one query per
declared keyphrase, which is how a symptom query is actually shaped:

| query form | queries | rank-1 ties |
|---|---|---|
| the exact declared keyphrase | 203 | **0** |
| the keyphrase minus one word (a half-remembered symptom) | 201 | **1** |

The exact-keyword tier (`W_EXACT_KEYWORD`) is claimed by exactly ONE atom, so it decides rank 1
outright; ties survive only in the TAIL, where 74–100% of queries do have them and where the
two-hop contract (WM-RCL) means nobody looks — the agent hops on rank 1. So the in-degree key
would need a links table the index does not have (WM-IDX stores files/memories/notes/atoms), i.e.
a schema migration and a per-reindex graph build, to change the answer for ~0.5% of queries.

**Trigger to revisit** (do not build it before one of these is TRUE): rank-1 ties exceed ~5% of
on-topic queries, or the scorer stops being tiered, or a links table lands for another reason
(WM-LINT's LINK LAW check computes the same edges today and would make the key nearly free).

`WM-SCORE-08b` **the-authority-signal, if it is ever needed** — the honest one is *upward
cross-layer in-links*: the only structurally unreciprocatable edge (WM-SCORE-09 measures why raw
in-degree is not), with declared `tier:` as the dense fallback — sparse-but-strong first, dense
second. `lmd` must never rank ahead of either: it is day-granular and ANY edit bumps it, so a typo
fix would permanently promote a page — the signal is corruptible by activity unrelated to
importance (which is why WM-MIG-07 forbids a mechanical repair from touching it). `tier:` is
DECLARED rather than derived, is present on ~98% of pages, and cannot be inflated by editing.

`WM-SCORE-09` **do-NOT-use-pagerank-or-raw-in-degree** — `MUST NOT`. This is a MEASURED refusal,
not a preference, and it follows from the corpus's own laws rather than from any defect in it.

The LINK LAW (WM-WIKI) makes every within-layer link bidirectional, and WM-SCOPE forbids
downward links, so a cross-layer edge can never be reciprocated. The result is a graph that is
*almost entirely undirected*:

| corpus | reciprocated edges | corr(out-degree, in-degree) |
|---|---|---|
| PROJECT (34 pages) | 56/65 — 86% | **+0.88** |
| USER (88 pages) | 170/193 — 88% | **+0.95** |

Mean in-degree equals mean out-degree exactly. So a page that links OUT to twenty pages receives
twenty links BACK: **in-degree measures chattiness, not importance.** And PageRank over an
undirected graph is provably proportional to degree — so classic PageRank would reproduce the
same wrong signal at far greater cost.

The honest link-authority signal is therefore the *unreciprocatable* edge: **cross-layer UPWARD
in-links** (22 in the measured corpus — sparse, so it fires rarely, but it means something when
it does), with declared `tier:` as the dense fallback. Sparse-but-strong first, dense second.

**Transferable form of this law:** in any corpus whose links are made symmetric by a rule,
link-count centrality is degenerate. Before adopting a graph-centrality ranking, MEASURE
reciprocity and the out/in correlation; if reciprocity is high, the metric is measuring how much
each node TALKS, and you need a signal the symmetry rule cannot manufacture.

## WM-IDX — the index contract

`WM-IDX-01` **the-index-is-an-accelerator-never-an-authority** — `MUST`: index-backed results
are byte-identical to walk-backed results, and when the index is not FRESH the engine walks.
Correctness never depends on the index being up to date; only speed does. (A test pins the
equality: `reindex_then_recall_via_index_matches_walk`.)

`WM-IDX-02` **freshness-is-a-path-SET-plus-a-per-file-identity** — the index is fresh iff ALL
hold: the DB opens; its schema version is current (WM-IDX-09); the ledger is non-empty; EVERY
live file's identity is UNCHANGED against its ledger row; and the on-disk path SET is EXACTLY
EQUAL to the ledger's. The SET half catches an ADD or a REMOVE (a new untracked file, a deleted
one still recorded, a symlink appearing or disappearing); the identity half catches an EDIT. A
coarse "is the DB newer than the directory" timestamp catches neither reliably.

`WM-IDX-02a` **file-identity-prefers-a-content-hash-over-mtime** — inside a git work tree the
identity is the **git blob sha** (`git hash-object`); elsewhere it falls back to
`(size, mtime_ns)`. Two reasons, both load-bearing:

- a content hash is **move-invariant**, so a file that is `git mv`-ed between lifecycle folders is
  recognised as the same content at a new path — the SET half reports the move, the identity half
  correctly reports "unchanged", and only the moved entry is re-parsed instead of the corpus;
- the mtime fallback is **nanosecond**, never second-precision, because two writes inside one
  second are ordinary and a second-granular stamp silently misses the second one.

`WM-IDX-09` **freshness-MUST-be-schema-version-gated** — a DB at an OLDER schema is ALWAYS stale,
irrespective of its ledger.

This is not tidiness, it is a correctness gate. A pre-migration DB is perfectly consistent *with
respect to its own ledger*, so an unversioned freshness check calls it fresh — and it then answers
queries from tables that do not yet have the newer columns, silently returning ZERO results for a
whole class of element until someone happens to reindex. Version-gating converts that silent wrong
answer into a walk, which is merely slower.

`WM-IDX-10` **migrations-are-forward-only-transactional-and-validated-before-commit** — the schema
carries a version; migrations are ADDITIVE and APPEND-ONLY; each step runs inside a single
`BEGIN IMMEDIATE` transaction, is validated IN FULL before it commits, and rolls back on any
failure. A DB stamped with a version NEWER than the running binary understands is REFUSED, never
migrated backwards. Where a structure cannot be altered in place (an FTS column set), the
migration drops, recreates, rebuilds it, and CLEARS the file ledger so the corpus is force-reparsed
to backfill — i.e. it pays a full reparse rather than leaving a half-populated column.

`WM-IDX-11` **validate-then-repair-then-nuke, in that order** — the index is a PURE DERIVED CACHE,
which is what makes destroying it a legitimate repair. On any validation failure: first attempt the
cheap in-place repair (rebuild every derived/FTS structure from its content table, which is ground
truth); only if that still fails, delete the DB and its sidecars and rebuild from scratch.

Validation is a fixed set of independent checks — file-level integrity, base-table column shape,
derived-table column shape, derived-vs-content parity, referential integrity (no child row pointing
at a vanished parent), and the version stamp — and each failure carries a **stable issue code** so
an external monitor can act on a specific defect rather than on a string.

`WM-IDX-12` **a-self-healing-component-MUST-log-the-repair-EVENT** — `MUST`: every self-heal
appends one capped line (`<epoch> <stage> <why>`) to a ledger a monitor can read.

The reason is the whole point and generalises far beyond an index: **a component that silently
repairs itself makes the broken STATE unobservable.** If corruption recurs daily and open() fixes
it every time, no snapshot of the system is ever wrong, so nothing can ever detect the recurrence
— the only observable is the *event* of repair. A self-healing component without a repair log is
therefore strictly less debuggable than one that simply fails.

`WM-IDX-13` **the-tool's-own-outputs-are-NOT-corpus** — generated index/report artefacts that live
in the corpus directory (a generated index doc, a detector's `*-proposed.md` report) `MUST` be
excluded from ranking, not merely un-indexed as elements. Observed while dogfooding: the
librarian's own reorganisation REPORT outranked every real note for a reorganisation-symptom query,
because a report about a topic is lexically the densest document about that topic. A tool that
ranks its own output will always rank it first.

`WM-IDX-14` **concurrency-is-assumed, not exceptional** — the index is opened concurrently by a
prompt-time hook, a background detector, and an agent mid-reindex. It therefore runs in WAL mode
with a bounded busy-timeout, so contention degrades to a wait instead of a spurious failure. The
sidecar directory writes its own ignore-file on first use, so a derived cache can never be
committed by someone who did not know it existed.

`WM-IDX-03` **stat-MUST-follow-symlinks** — `MUST NOT` compute the per-file signature with a
non-following stat. A following stat records the TARGET's size/mtime, so editing a published
page invalidates every view that links to it. Switching to `symlink_metadata` would freeze each
published page's signature at the LINK's own mtime, and the index would then serve stale content
forever **with nothing reporting it** — the worst failure class available, because it is
indistinguishable from correct operation.

`WM-IDX-04` **walkers-MUST-accept-a-symlinked-FILE** — a directory walker filtering on
`entry.file_type().is_file()` sees the LINK's own type, so a symlinked page is SILENTLY SKIPPED:
present on disk, absent from every search. Accept an entry whose FOLLOWING `metadata()` reports a
file. `MUST NOT` reach for the walker's `follow_links(true)` instead — that also traverses
DIRECTORY symlinks, inviting cycles and silent recursion into unrelated trees, to buy something
not needed.

`WM-IDX-05` **reindex-the-scope-ROOT-not-the-file's-parent** — an incremental reindex triggered
by a write resolves the SCOPE ROOT the page was reached through, not `path.parent()`. A page in a
subdirectory of a root otherwise never refreshes that root's index.

`WM-IDX-06` **the-view-IS-the-boundary** — `MUST`: indexing, link resolution and lint operate on
the search ROOTS AS GIVEN, never on a resolved target's neighbourhood. Any code that derives a
page set from a file's own location — `parent()`, or `canonicalize()` then scan siblings — lands
in the target's real directory and sees everything there, which silently converts a scoped view
into full disclosure. Cross-root dedupe therefore keys the visited set on the canonical path but
PASSES THE RAW PATH to the visitor, so the view survives the deduplication.

`WM-IDX-07` **schema-version-and-forward-migration** — the index carries a schema version;
migrations are ADDITIVE (`ALTER TABLE … ADD COLUMN`) and every query TOLERATES a pre-migration DB
by returning empty rather than erroring. A hard failure on an old index turns a cache into a
liability.

`WM-IDX-07a` **a-migration-that-adds-a-column-MUST-clear-the-LEDGER** — `MUST`: an `ADD COLUMN`
step ends by emptying the change-detection ledger. The column arrives EMPTY and only a re-parse
can fill it, but every source file is byte-identical, so an incremental reindex skips them all and
the column stays NULL forever — the field then reads as its default on exactly the corpora that
already had real values. The test for such a migration `MUST` assert the re-parse actually
happened (a non-zero changed count on an unchanged corpus), not merely that the value is present:
on a DB that never lost the value, the value-only assertion passes without the migration working.

`WM-IDX-07c` **prune-the-CONTENT-rows-too-not-only-the-LEDGER** — `MUST`: a reindex deletes every
`memories` row whose path is not in the on-disk set for that root, not merely the ledger entries
it can still account for. `path` is the CALLER'S SPELLING (absolute vs relative vs `…/./x.md`),
not a canonical identity, so one file can hold two keys — and WM-IDX-07a's ledger reset leaves the
ledger-driven prune with nothing to match, so the previous spelling's rows become unreachable and
permanent. Measured on this repo's PROJECT scope: **70 memory rows for 35 files**, so every
index-backed recall returned every element TWICE — halving `--top N` and doubling the token cost
of the primary read path. `is_fresh` compares the LEDGER (which was correct), so the health check
reported the index healthy throughout: an index can be duplicated and fresh at the same time.

`WM-IDX-07b` **a-shipped-schema-version-is-IMMUTABLE** — `MUST NOT` edit or renumber a shipped
migration step; new work is a NEW version. A DB that already recorded version N skips an amended
step N forever, so the change reaches exactly the corpora that never needed it and never reaches
the ones that did — and rebuilding the binary does not help, because the version says "already
migrated".

`WM-IDX-08` **routing-writes-through-the-tool-buys-LATENCY-not-CORRECTNESS** — the freshness
check (WM-IDX-02) is what makes correctness independent of the writer. Routing a mutation through
the tool buys an immediate targeted reindex instead of waiting for the next query's freshness
check — a real gain, since that check runs per-query and a full reindex is the expensive path —
but it `MUST NOT` be presented as the thing that makes the system safe. Any agent can bypass the
verbs with a raw edit tool, so a background repair chore is the safety net, and **correctness may
never DEPEND on the safety net.**

`WM-SCORE-10` **the-ordering-and-date-flags** — `recall`/`find` also carry `--sort score|ocd|lmd`
(default `score`), `--order asc|desc` (default `desc`), and `--since`/`--until` over
`--date-field ocd|lmd` (default `lmd`). Two null-handling rules, both deliberate:

- an element with NO date in the chosen field sorts **LAST** under `--sort ocd|lmd`, in BOTH
  directions — a dateless element has no place on a timeline, so `--order asc` must not promote it
  to first;
- when EITHER range bound is set, an element with no date in that field is **EXCLUDED** — a
  missing date cannot be proven in-range, and silently keeping it would make `--since` mean
  "since, plus anything undated".

`WM-SCORE-11` **`find` and `recall` are DIFFERENT scorers, on purpose** — `find` rows have already
passed the `+`/`-` gate, so: there is NO precision-first suppression (a `+mandatory`-only query
legitimately scores zero OPTIONAL hits and is still a real result), and its searchable surface is
`title + summary + tags + body` TOGETHER rather than recall's surface-then-body-fallback. Stating
this because the two verbs look interchangeable and are not: a query moved from one to the other
can legitimately return a different set, and that is not a bug in either.

`WM-SCORE-12` **stopwords-are-a-fixed-English-list** — the query tokenizer drops a hardcoded
English stopword list. A non-English symptom query gets no stopword benefit, and a query made
ENTIRELY of stopwords is REFUSED rather than silently matching everything.

## WM-BENCH — retrieval is MEASURED, not asserted

`WM-BENCH-01` **frozen-fixture-corpus** — the benchmark runs against a COMMITTED fixture corpus,
never the live one. A live corpus changes weekly, so every run would be incomparable to the last
— the opposite of a regression instrument. Pointing the harness at a live corpus (`--corpus
<path>`) is legitimate for a SPOT CHECK and never for the gate; no separate live-mode flag exists,
and none should be added — a dedicated flag would make the unrepeatable run look like a supported
mode of the instrument rather than an off-label use of it.

`WM-BENCH-02` **queries-written-from-the-SYMPTOM-side** — each case is `(symptom query → expected
element id)`, phrased in the words a future session would actually have. Reporting `hit@1`,
`hit@3`, `hit@10` and MRR.

`WM-BENCH-03` **deterministic-offline-estimator** — the token estimator is stable, hermetic and
monotone in output size, and is documented as a RELATIVE instrument; raw bytes are reported
alongside so every number stays auditable. A bias identical on both sides of a comparison cancels
in the delta.

`WM-BENCH-04` **cost-is-END-TO-END** — `MUST`: the metric is `tokens(search output) + tokens(the
follow-up read it forces)`. A per-call metric flatters a lean listing (tiny output) while hiding
the hop it forces, and equally flatters a fat one-shot that needs none. Only the total answers
the real question — *what does it cost to hold this fact?*

`WM-BENCH-05` **committed-baseline-and-a-regression-gate** — the baseline JSON is committed and
the run FAILS if accuracy drops or token cost rises beyond tolerance, wired into the test suite so
a regression cannot ship quietly.

`WM-BENCH-06` **a-baseline-captured-on-a-broken-fixture-stays-broken** — the fixture is not
"corpus that should be fixed", it IS the baseline. Re-capturing it casually destroys the ability
to compare against every prior version. Re-capture only when the DEFAULT behaviour legitimately
changed, and record the before/after numbers in the commit that does it.

`WM-BENCH-07` **measure-the-binary-under-test** — `MUST`: the harness runs the build being
evaluated, not whatever is on `PATH`. Otherwise every measurement silently scores the INSTALLED
build and reports the old numbers as the new build's improvement — a self-confirming result that
looks like a successful experiment.

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
`recall` and `find` carry the layered-output surface — `--output basic|medium|full` (default
`basic`), `--with-keywords`, `--with-notes`/`--no-notes` — and `recall <ATOM-ID>` is the exact
second hop. See WM-RCL-06/07/08, which own the contract.

`WM-CLI-03` **write-verbs-synthesise-syntax** — `new-page` (valid frontmatter + mandatory Notes
section; refuses to overwrite), `add-atom` (`--desc` stored QUOTED ≤200 chars; id/dates/syntax
synthesised so a malformed atom is impossible), `add-lesson` (anchors `[^N]` from the atom
body; DO-NOT/BECAUSE/DO on stdin).

Their flags, which WM-CLI-10 holds them to:

- `add-atom --page <PAGE> --keywords <LIST>` — both MANDATORY, and each for a reason the verb
  exists to enforce. `--page` must ALREADY exist (the verb appends; it never creates a page, so a
  typo cannot silently mint an orphan). `--keywords` is the RECALL SURFACE: a comma-separated
  key-phrase list whose internal spaces become `_`, i.e. the verb applies WM-ATOM's phrase grammar
  for the author. Omitting it is unrepresentable because an atom with no keywords is
  unfindable (WM-RCL-01) — a write that succeeds into invisibility is the worst outcome available.
  Optional: `--desc`, `--type`, `--hidden`.
- `add-lesson --page <PAGE> --keywords <LIST>` — same two mandatory flags, same reasons: a lesson
  is recalled by symptom exactly as an atom is.
- `new-page --path <PATH> --tier <T> --name --description --type`, plus `--globs` (a `hub`'s file
  ownership, per WM-WIKI) and `--functionality` (the hub's subject). `--path` is separate from
  `--name` because the FILE name and the `name:` slug are different identities — wikilinks resolve
  through `name:`, so conflating them would break `[[link]]` resolution for every page whose file
  is named differently from its slug.

`WM-CLI-04` **add-lesson-supersedes** — `add-lesson --supersedes --atom <id>` `MUST` embed the
atom's current verbatim body as `SUPERSEDED BODY:` and record `supersedes:<atom>`; the optional
`--retire-atom` sets the atom marker `status: superseded, superseded-by:<lesson-id>`
(idempotent). Default correction is in-place same-id (WM-LES-05), never a duplicate.

`WM-CLI-05` **index-sidecar** — the corpus is indexed into a SQLite sidecar (`.memgrep/`);
`index`/`reindex` build/refresh it; `validate` checks index/page health. The file watcher
debounces ~500 ms behind writes — a consumer `MUST NOT` re-query in the same turn it wrote.

`index`/`reindex` share three flags:

- `--full` — ignore the change-detection ledger and rebuild the SQLite index from scratch. It is
  the escape hatch for WM-IDX's freshness model: that model is an OPTIMISATION, so there must be a
  way to distrust it, or a bug in change-detection becomes unrecoverable from the CLI.
- `--markdown` — build the LEGACY markdown doc-generator (`memory-index.md`) instead of the SQLite
  index. Legacy is the operative word: `memory-index.md` is a non-note the walk deliberately
  excludes from ranking (WM-RCL), so this output is for humans, never a retrieval surface.
- `--write` — `--markdown` ONLY: write to `<root>/memory-index.md` instead of stdout. Defaulting to
  stdout is what keeps a doc-generator from silently rewriting a corpus file that a reader merely
  wanted to look at.

`links` carries `--broken` (targets that do not exist), `--orphans` (files with no inbound links),
`--to <NOTE>` (that note's out-links) and `--from <NOTE>` (its backlinks). They are REPORTS, not
lints: a broken link may be a legitimate forward reference — WM-WIKI explicitly permits authoring
`[[name]]` before the page exists — so failing on one would punish the authoring order the model
allows.

`fact`/`recall`/`find`/`atom` carry `--full-notes`: keep each lesson's leading `[...]` metadata
prefix, which is STRIPPED by default. The prefix carries the lesson's address (`id`, `status`,
`keywords`, dates — WM-LES), so this is the flag to reach for when the question is *which* lesson
this is or whether it is still `valid`, rather than what it says.

`WM-CLI-06` **token-lean-output** — reads return greppable, capped output; consumers read the top
1–3 hits, not the whole corpus. The exact shape is WM-RCL-06's layer table (the lean triage row by
default), and the cost model is WM-BENCH-04.

`WM-CLI-08` **write-verb-placement-and-uniqueness** — the rules that make a synthesised write
land correctly:

- an `add-atom` block is inserted immediately BEFORE the `## Notes and lessons learned` heading
  when present, else at EOF. Not cosmetic: the atom parser terminates a body at the next heading,
  so appending at EOF past that heading would put the new atom's body inside the lessons section
  and truncate it to nothing;
- atom-id uniqueness is checked across the WHOLE OWNING SCOPE, not just the target page, because
  recall walks the scope and WM-ATOM-06 requires corpus-unique ids;
- a new footnote label is allocated as `max(existing numeric labels) + 1` over BOTH the parsed
  tree AND a raw scan — see WM-ATOM-08 for why the parsed maximum alone is a collision;
- `new-page` REFUSES an unknown `--tier`, an empty `--name`/`--description`/`--type` after trim,
  or an existing destination; it creates parent directories.

`WM-CLI-09` **atom-ids-are-accepted-in-three-spellings, and ambiguity is REPORTED** — `atom` /
`atom-page` accept `^marker`, the canonical `ATOM-XXXX-XXXX`, or the bare 8-char payload,
case-insensitively. When an id matches MORE than one atom the tool prints EVERY `path#id` match
and exits non-zero. Returning an arbitrary one of them would be the worst option available: the
caller cannot tell a unique hit from a coin flip.

`WM-CLI-10` **write-then-reindex-is-synchronous** — every write verb writes via tmp-file + atomic
rename and then reindexes the OWNING SCOPE immediately, in-process. The freshness check
(WM-IDX-02) is what makes correctness independent of this; the synchronous reindex is the
LATENCY half (WM-IDX-08), and it is a different mechanism from an external file watcher.

`WM-CLI-07` **find-DSL** — `memgrep find` takes a keyword DSL (`+must`, `-exclude`, `"exact
phrase"`, wildcards), `--only-notes` to search the LESSONS, `--use-index` for the SQLite sidecar,
and `--top N`. The DSL grammar lives in the Rust crate and is the search surface both the wiki and
the private user-mem search build on.

## WM-BASE — the base markdown-AST grep mode

`WM-BASE-01` **the-default-mode-is-a-grep** — with NO subcommand, `memgrep` is a
markdown-AST-aware `grep`: `memgrep [OPTIONS] [PATTERN] [PATHS]...`. This is the tool's ORIGINAL
purpose and its default behaviour; the memory verbs (WM-CLI) are a layer ON TOP of it, not a
replacement for it.

This clause exists because the mode was **entirely absent from this spec** while being fully
implemented — and WM-META's authority rule says unspecced behaviour is presumed an error to be
fixed. A large, working, load-bearing CLI surface was therefore one cleanup pass away from
deletion. **A spec that covers only the newest layer is not a partial spec; it is an active
hazard.** Whenever a tool grows a subsystem, the older one needs a clause more urgently than the
new one, precisely because nobody is thinking about it.

`WM-BASE-02` **grep-compatible-core** — the familiar switches keep their `grep` meanings:
`-e/--regexp` (explicit pattern — needed to search for a word that is also a subcommand name),
`-i` (ignore case), `-w` (whole word), `-l` (paths only), `-c` (count per file), plus `--json`
(one object per match) and `--hidden`. A user who knows `grep` must not have to learn a dialect
for the parts `grep` already defines.

`WM-BASE-03` **structure-is-a-first-class-filter** — the pattern is OPTIONAL, because a query may
be purely structural (`--heading` alone is a valid search). The AST filters:

| group | flags |
|---|---|
| code | `--no-code`, `--code`, `--code-lang <langs>` (implies `--code`) |
| sections | `--in <heading-regex>` (that section INCLUDING sub-sections), `--heading`, `--level <n\|2..3\|>=2>`, `--num <1.2\|1.2.*\|>=1.2,<3.5>`, `--depth <n>` |
| frontmatter | `--fm KEY=REGEX` (repeatable, AND) |
| inline emphasis | `--bold`, `--italic`, `--code-span`, `--strike` (each takes the REGEX to match inside that span type) |
| bracketed spans | `--class` (OR), `--class-all` (AND), `--span-class` |
| lists | `--list`, `--no-list` |
| GFM nodes | `--node`/`--no-node` over `table,quote,math,url,image,html,svg,footnote`, plus one sugar flag per kind |

`WM-BASE-04` **`--where` is the composable form and SUPERSEDES the flags** — a boolean DSL
(`path`, `name`, `fm.KEY`, `links-to`/`linked-from` semijoins, with `and`/`or`/`not` and
grouping) e.g. `--where '(path "**/memory/*.md" or path "**/archive/*.md") and not code and
fm.column "dev"'`. `MUST NOT` be combined with the individual filter flags: the flags are an
implicit AND-chain and mixing the two makes precedence ambiguous, so the tool rejects the
combination rather than guessing.

`WM-BASE-05` **a-pipe-must-not-panic** — the binary resets `SIGPIPE` to its default disposition
at startup so `memgrep … | head` exits quietly instead of dying on `EPIPE`. Below the usual
abstraction level of this spec, and stated anyway: it is invisible until a shell pipeline breaks,
and then it looks like a crash in the tool rather than a missing two-line startup call.

## WM-FACT — the one-fact-per-line format

`WM-FACT-01` **a-second-memory-shape** — `memgrep fact` queries a representation DISTINCT from the
page/atom/lesson model the rest of this spec describes: an append-only log of one fact per LINE.
It is not a degraded page and pages are not a degraded log; the two coexist and no rule from one
governs the other.

`WM-FACT-02` **the-line-grammar** —

<!-- @spec:fact-grammar v1 — authoritative -->
```text
<ISO-timestamp> <tag> <tag> … :: <fact text>
```

The separator is a space-padded ` :: `. Tags are whitespace-separated tokens in the middle field:
`#<category>` · `@<component>` · `sess:<id>` · `kind:<k>`. A line lacking the timestamp or the
`::` separator is not a fact and is skipped.

`WM-FACT-03` **the-query-surface** — `--cat` (repeatable / comma list, OR over `#<cat>`),
`--comp` (OR over `@<comp>`), `--session` (`sess:<id>`), `--kind` (`kind:<k>`), `--since`/`--until`
(compared LEXICOGRAPHICALLY against the leading ISO timestamp, which is exactly why the timestamp
leads the line), and an optional positional regex matched against the fact TEXT only — never
against the tags, so a category name in the prose cannot masquerade as a tag.

`WM-FACT-04` **notes-are-OFF-here** — `--with-notes` defaults to OFF for `fact` (unlike its
historical default elsewhere), because a fact line is already the atomic unit: appending a whole
file's lessons to each matched LINE would return the same block once per hit.

## WM-LINT — the lint contract

`WM-LINT-01` **deterministic-fp-free** — `MUST`: `memgrep lint` is deterministic and
false-positive-free; every check it fires is a real defect an author must fix. Example prose
inside backtick inline spans or fenced code is masked (a `[^N]` token in inline code is not a
footnote).

`WM-LINT-06` **severity-model** — `MUST`: every finding carries a severity, printed as the LEADING
token (`ERROR` / `WARN` / `INFO`) so `| grep '^ERROR'` is exact. `--min-severity` (default `error`)
gates the EXIT CODE only — every finding `MUST` still print regardless. A model that hid findings
would trade one unusable report (all-noise) for another (silently incomplete).

| severity | meaning | checks |
|---|---|---|
| `ERROR` | corruption or invisibility — it does not parse, resolve, or rank | dangling `[^N]` reference · unquoted `desc:` (atom or lesson) · body-less lesson · supersession without `SUPERSEDED BODY:` · missing `ocd`/`lmd`/`description` · missing Notes section · downward cross-scope link · non-ASCII `⟦` atom marker · unclosed atom props · atom without `keywords:` · dropped props segment · duplicate atom id · `⟦` lesson metadata |
| `WARN` | real, but nothing is lost and the fix is not mechanical | one-sided link (WM-WIKI-04a) · oversized atom (WM-LINT-03) · missing or non-ISO atom `ocd`/`lmd` · lesson without metadata / without `id:` / without `keywords:` · superseded lesson with no forward pointer |
| `INFO` | the model BLESSES this shape; a pointer, not a defect | uncited page-level lesson |

The split is measured, not stylistic. Over the three live scopes (164 notes) the corpus held 262
findings of which **150 (57%) were the single INFO check** — an uncited `[^N]:`, which the model
explicitly permits because the Notes section is mandatory even when empty, so a page-level lesson
has no inline referrer BY DESIGN. Rated as errors, the gate failed on every corpus, and a gate that
always fails is one people route around; the genuine errors were unreadable underneath it. After
the split the USER scope reports 161 findings and **8 ERRORs** — a list an author can actually act
on.

The two `WARN`s are warnings for a reason that outlives this corpus: a one-sided link cannot be
fixed from the page being edited (the missing half lives in the OTHER file), and an oversized atom
needs a semantic decomposition. Blocking a write on either gates an unrelated edit behind work its
author may not be positioned to do.

`WM-LINT-02` **the-checks** — `lint` fires on, at minimum: `unquoted-desc` (WM-ATOM-03),
`empty-lesson-body` (WM-LES-04), `oversized-atom` (WM-ATOM-01), `superseded-without-body`
(WM-LES-07), `atom-dropped-props` (WM-ATOM-07), a dangling / unreferenced footnote, a one-sided
same-scope `[[link]]` (WM-WIKI-04 / WM-WIKI-04a), the required frontmatter fields (`ocd`/`lmd`/
`description`, legacy aliases `created`/`updated`/`summary` accepted) plus the mandatory
`## Notes and lessons learned` section, a **downward cross-scope link** (WM-LINT-05), and the
INVISIBILITY class — an atom marker opened with a non-ASCII bracket (`⟦`/`【`/`〔`/`「`, the shape
a marker acquires when it is pasted back from recall's DISPLAY output), an atom whose props `[`
never closes, an atom with no `keywords:` (WM-ATOM-04 — no recall surface means no memory), a
lesson whose metadata head uses `⟦…⟧`, a lesson with no `id:` / no `keywords:` / no metadata at
all, a `status:superseded` lesson with no `superseded-by:` pointer, a non-ISO `ocd`/`lmd`, and a
**duplicate atom id**.

`WM-LINT-07` **one-linter-one-grammar** — `MUST`: every check lives in `memgrep lint` and nowhere
else. `scripts/wikimem_syntax_lint.py` is a THIN WRAPPER that picks the default roots, shells out,
and parses the output; the heartbeat detector calls that wrapper. Two implementations of one
grammar drift, and these two did: each side grew checks the other never had, so which defects an
author saw depended on which tool happened to run. A wrapper that cannot resolve the binary
`MUST` exit non-zero — a gate that passes because the checker did not run is worse than no gate.

Three properties this contract requires of the implementation, each of which was a live bug:

- **Lessons are scanned from the RAW definitions**, not from the parsed footnote list: the markdown
  parser only materializes a footnote node for a BALANCED ref+def pair, so linting the parsed list
  silently skipped every UNCITED page-level lesson — which the model makes the NORMAL case.
- **Atom-marker SHAPE checks read the raw line.** An atom the props parser cannot see is exactly
  what a parser-driven scan can never report; fenced and inline code are masked so prose that
  DOCUMENTS the broken form is not a finding.
- **File identity is the canonical path.** One file reachable by two paths (a `publish-globally`
  symlink, a symlinked root) is linted ONCE, or the corpus-unique check reports every atom as a
  duplicate of itself. A byte COPY is not the same file and its ids genuinely do collide.

`WM-LINT-05` **downward-cross-scope-link** — a link from a page in one scope DOWN to a page in a
lower one (LOCAL < PROJECT < USER) is a violation, and the message names WHICH of the two reasons
applies, because they call for different repairs:

| target | reason | the fix |
|---|---|---|
| → LOCAL (from PROJECT or USER) | **PRIVACY** — a page NAME and topic are disclosure even when the body is not, and PROJECT memory is PUSHED | relocate the fact, or genericise the reference; never publish the name |
| USER → PROJECT | **PORTABILITY** — USER memory is inherited by every project, but a project can be deleted, moved or renamed | move the project-specific fact down into PROJECT scope |

Scope is derived from the PATH. The one subtle discriminator is that `.claude/projects/`
(**plural**) is the machine-private LOCAL root while `.claude/project/` (**singular**) is the
git-tracked PROJECT root — one character apart, opposite meanings for privacy. A path matching no
known root yields NO scope and DISABLES the rule for that edge: a wrong guess would either invent
a violation or hide a real leak, and neither is acceptable in a check whose whole job is
preventing disclosure.

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

`WM-MIG-07` **a-mechanical-repair-must-not-manufacture-recency** — `MUST NOT`: a MECHANICAL
repair — a lossless syntax/format migration that changes no FACT (re-joining keyword phrases,
quoting a `desc:`, normalising a date, fixing a bracket) — bumps `lmd:`. Only a change to WHAT
the page ASSERTS bumps it.

The reason is that `lmd` is not decoration: ranking uses recency as a tie-break, so a
mechanical touch would silently promote every repaired page above genuinely-updated ones. A
corpus-wide repair would then reorder the WHOLE corpus's priority without changing a single
fact — and the damage is invisible, because nothing about the output says the ordering came
from a formatting pass. A repair tool that has to rewrite 1,000 pages must leave the corpus
ranking EXACTLY as it found it.

Corollary for verification: "no `lmd` changed" is a cheap, mechanical proof that a migration
was in fact mechanical. A migration that bumped dates cannot make that claim, so it cannot be
audited as lossless after the fact.

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

## WM-UMEM — the private, agent-invisible user-memory subsystem

`WM-UMEM-01` **separate-private-store** — `MUST`: a DISTINCT store at
`~/.claude/projects/<slug>/memory/user-mem/` holds USER-authored private memories — one markdown
file per memory. It is a sibling of the agent corpus, NOT part of the wiki, and its search root
is ONLY ever this dir. It is a memory STORE; it is never deleted or reorganised by any editorial
pass.

`WM-UMEM-02` **agent-invisible-by-construction** — `MUST`: the user-mem hooks use UserPromptSubmit
`decision:block` so a save's text and a search's query NEVER reach the model; confirmations and
results reach the USER only via `systemMessage`. The model learns a memory's content ONLY through
the explicit share gate (WM-UMEM-04).

`WM-UMEM-03` **monotonic-immutable-counter** — `MUST`: memory numbers come from a `.counter`
(flock-guarded) that only ever moves FORWARD; a number is retired-never-reused. The number is the
memory's stable id.

`WM-UMEM-04` **share-is-the-only-injection-gate** — `MUST`: `/janitor-memory-user-share <N>` is
the SOLE path that injects a user-mem memory into model context (via `additionalContext`).
`/janitor-memory-user-add [text]` saves (bare → the previous user message from the transcript);
`/janitor-memory-user-search <q>` searches ONLY this store. The deprecated aliases
(`/to-user-mem`, `/search-user-mem`, `/share-user-mem`) MUST stay recognised-and-intercepted so a
user who types one never leaks — an UNRECOGNISED form is not intercepted and the private text
reaches the model.

## WM-SURF — the proactive surfaces (recall is worthless if only used when asked)

`WM-SURF-01` **auto-recall-default-on** — the UserPromptSubmit auto-recall hook
(`on-prompt-submit-autorecall.py`) surfaces symptom-relevant notes on each prompt by default; it
implements WM-RCL-03 without the agent having to remember to search.

`WM-SURF-02` **session-start-breadcrumb** — SessionStart prints ONE breadcrumb naming the
per-scope note COUNTS + the `memgrep overview <dir>` entry point (`memory_breadcrumb.py`), so a
fresh session learns the 3-scope wikimem exists. It prints counts ONLY, never note content (it
lands in the session prefix, and a PROJECT page is untrusted git input), and prints even while the
heartbeat is disarmed (memory outlives the heartbeat).

`WM-SURF-03` **memorize-nudge** — the `memorize-nudge` detector nudges the agent to WRITE when
code has outrun the wiki (substantive commits since the last memory note), pointing at the WRITE
skill + RECALL-first.

`WM-SURF-04` **correction-advisory** — the PostToolUse `post-edit-memory-correction.py` advises
the correction protocol (WM-LES-05) when an edit looks like it should supersede rather than
overwrite. It ADVISES; it never mutates.

`WM-SURF-05` **record-recent** — `/janitor-memory-record-recent` (skill) is the user-invoked
harvest of recent changes into the wiki — the active counterpart of the passive nudge.

## WM-SCHED — the maintenance scheduler (cadence, cost, and the curator dispatch)

`WM-SCHED-01` **scheduler-not-doer** — the `memory-maintenance` detector is the SCHEDULE layer: it
decides WHICH editorial chore is due for WHICH (scope, root) and dispatches the ONE curator agent
(WM-SEP-02) via a bare `[janitor-memory-<chore>]` marker; it never edits the corpus itself.

`WM-SCHED-02` **per-day-rate-keys** — each chore (consolidate / split / conflict / repair /
harvest / atomize) has a per-day rate key in `memory_settings` that `interval_s` turns into a
cadence (0 ⇒ OFF). The chores are OFF BY DEFAULT (USER cost decision 2026-06-30); a user opts in
via `/janitor-memory-frequency`. A conformance reader MUST NOT treat "OFF by default" as "unused
and removable".

`WM-SCHED-03` **zero-LLM-precheck** — before dispatching an expensive agent, a stat-only
`memory_content_precheck` decides whether the chore has actual work on the corpus (oversize for
split, structural malformation for repair, free-prose for atomize, un-mirrored buffers for
harvest, a real conflict for conflict) — so a due-but-empty chore costs no tokens.

`WM-SCHED-04` **dispatch-fingerprint** — a corpus fingerprint recorded at dispatch time prevents
re-dispatching an unchanged corpus to the same chore (bounded, no-churn — mirrors the general
self-heal convergence rule).

`WM-SCHED-05` **index-health-produces-work** — the `memgrep-index-health` detector surfaces a
corrupt/stale SQLite sidecar as a support ticket (the repair curator's motivating producer); the
index is regeneratable (`reindex`) but is repaired, never used as a reason to delete the corpus.

## WM-HARV — harvest and the raw-buffer / curated-wiki coexistence

`WM-HARV-01` **two-note-populations** — the corpus holds RAW harness buffer notes (written by the
platform `# Memory` directive) AND CURATED wiki pages (authored via the verbs). Both are memory;
`is_curated_wiki_page` discriminates them.

`WM-HARV-02` **harvest-mirrors-never-moves** — `MUST`: the HARVEST pass MIRRORS a raw buffer note's
knowledge INTO the curated wiki (coexistence), tracked by a per-(scope,root) harvest WATERMARK
(`memory_settings.harvest_*`) so an unchanged buffer note is not re-harvested. Harvest preserves —
it never deletes the raw note as a side effect (the `memory_edit_verify.harvest_preservation_ok`
oracle proves every raw note was mirrored before any reduction).

`WM-HARV-03` **MEMORY.md-is-a-deprecated-stub-not-the-index** — see WM-MNT-04; a harvest MUST NOT
reduce `MEMORY.md` until every memory it pointed at is proven mirrored.

## WM-BOOT — bootstrap and the simple agent-facing skills

`WM-BOOT-01` **bootstrap-once** — `/janitor-memory-bootstrap` (skill) stands up a project's wikimem
(the overview/hub scaffolding) ONCE; it is idempotent and never overwrites existing pages.

`WM-BOOT-02` **simple-skills-are-the-main-agent-surface** — `/janitor-memory-{recall,write,update}`
are the SIMPLE authoring skills a MAIN agent uses directly (create/update a page, recall by
symptom); the heavier transaction-gated editorial chores (WM-SEP-01/02) are the curator's, not the
main agent's. Both surfaces route through the verbs (WM-AUTH-01).

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

`WM-CHK-06` **user-mem-privacy** — the user-mem test suite asserts WM-UMEM-02/04: a save/search
prompt is `decision:block`-erased (never reaches the model), `/janitor-memory-user-share` is the
only path using `additionalContext`, and every deprecated alias stays intercepted (no leak).

`WM-CHK-07` **scope-migration-guards** — `migrate_memory_scope` tests assert WM-SCOPE-10: the
privacy classifier flags private notes, the ownership guard refuses an out-of-repo write, and a
plan stale against a re-classify is rejected.

`WM-CHK-08` **completeness-is-maintained** — per WM-META-05, when a memory file/store/verb/detector
is ADDED to the implementation, a clause `MUST` be added here (MINOR bump) rather than the code
left un-specified. A code-vs-spec inventory drift is a gap to file, never a deletion to make.

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
