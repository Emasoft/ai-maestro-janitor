# memgrep — markdown-aware grep

`memgrep` is `grep`/`rg` for markdown: walks a tree (gitignore-aware), matches a **regex** per line, prints `path:line:col:text`. **All your grep muscle memory works** — `-i -w -n -l -c -e PATTERN [PATH…]`, `--json`, `--hidden`. Five rules cover the rest: (1) every matcher value is a regex; (2) grep-equivalent flags keep their name; (3) numeric/version ranges use pip syntax (`>=1.2,<3.5`); (4) wildcards are `*`; (5) different flags AND-narrow, comma-lists OR-widen.

## Structural filters (the net-new surface)
- **code:** `--no-code` (drop code-block false positives) · `--code` · `--code-lang py,rs`
- **headings:** `--heading` · `--level 2`|`2..3`|`>=2` · `--in REGEX` (section + subsections) · `--num 1.2`|`1.2.*`|`>=1.2,<3.5` · `--depth N`
- **inline:** `--bold`/`--italic`/`--code-span`/`--strike REGEX` · `--class a,b`/`--class-all` · `--span-class c` · `--list`/`--no-list`
- **gfm nodes:** `--node table,quote,math,url,image,html,svg,footnote` · `--no-node …` · sugar `--table` etc.

## Boolean queries — `--where 'EXPR'`
Each `--flag v` above is the predicate `flag "v"` (negatives via `not`); compose with `and`/`or`/`not` + `( )` (juxtaposition = and). `--where`-only file-level predicates: `path "**/g"`, `name "*.md"`, `fm.KEY "v"` (smart glob/range/regex), `links-to "note"`/`linked-from "note"` (link semijoin = SQL JOIN). `--where` is the whole query — don't mix it with the flags.

## Memory subcommands (command reference)

| Subcommand | What it does |
|---|---|
| `recall "SYMPTOM" <memdir>` | rank notes AND body **ATOMS** by symptom match, best first → one lean TAB row each: `<lmd>⇥<locator>⇥<description>` (locator = the bare atom id for an atom, the path for a page). A TRIAGE list — no bodies, no lessons. Query the QUESTION's words, not the answer's |
| `recall <ATOM-ID> <memdir>` | the **second hop**: exact-id lookup returning that ONE atom in full (body + its `[^N]` lessons + see-also). This is what makes the lean listing cheap — scan ids, then pay for exactly one atom. A whitespace-free query that matches no atom id falls through to an ordinary symptom search |
| `find "<query>" <memdir>` | note-level `+`/`-`/wildcard/phrase keyword search (see below); `--only-notes` searches the lessons instead of pages |
| `find-claude-mem-ref <buffer.md> <wikidir>` | list every wiki ATOM harvested FROM a Claude-memory buffer file → `path#atom-id\t<source-hash>` (the harvest provenance back-reference; see Atoms below) |
| `index <memdir>` / `reindex <memdir>` | build the persistent SQLite query index `.memgrep/index.db` (gitignored, git-incremental — re-parses only changed files); `--full` rebuilds from scratch. Indexes pages, `[^N]` lessons, AND body atoms |
| `index --markdown <memdir>` | the legacy doc-generator → `memory-index.md` (per-note title+summary+tags+TOC+backlinks); add `--write` to write the file instead of stdout |
| `links --broken\|--orphans\|--to N\|--from N` | link graph / semijoin over the corpus |
| `lint <memdir>` | deterministic, FP-free note-integrity check — footnote balance (every `[^N]` ref has a `[^N]:` def and vice-versa), the bidirectional LINK LAW (A links `[[B]]` ⟹ B links back), and required fields (`ocd`/`lmd`/`description` + a `## Notes and lessons learned` section). Prints `path:line — what is wrong`; exits non-zero on any violation (usable as a pre-commit / write-skill gate) |
| `fact [--cat/--comp/--session/--kind/--since/--until]` | query one-fact-per-line memory lines; `--with-notes` (OFF by default here) appends matched files' lessons |

### `recall` / `find` shared flags

`--output basic|medium|full` (**default `basic`** — `basic` is one `<lmd>⇥<locator>⇥<description>` row per hit and nothing else; `medium` adds the atom's body; `full` is the rich record — body + lessons + see-also + keywords — a DEBUGGING layer, not a richer default. Measured end-to-end on the frozen benchmark, `basic` + one hop costs **247 tokens/query against 441** for the old always-rich output, at identical accuracy) · `--with-keywords` (print the recall surface; implied by `full`) · `--with-notes` (append `[^N]` lessons — default ON for `full`, OFF for the lean layers, and an explicit flag always wins) · `--no-notes` (body only) · `--full-notes` (keep each lesson's leading `[…]` metadata prefix; default stripped — URLs/images always kept) · `--sort score|ocd|lmd` (default `score`=relevance) · `--order asc|desc` (default `desc`) · `--since <ISO>` / `--until <ISO>` over `--date-field ocd|lmd` (default `lmd`) · `--top N` (default 10) · `--use-index` (force the SQLite sidecar; auto-used when fresh, else the live walk — results always correct).

Render is token-economical: an inline footnote ref shows as a bare `[9]`; after the body memgrep appends `[9] - <lesson WHY>.` (the on-disk `[^9]`/`[^9]:` form does not leak). OCD/LMD are read from frontmatter `ocd`/`lmd` (aliases `created`/`updated`) or a lesson's `[ocd:… lmd:…]` prefix.

### `find` — the `+`/`-`/wildcard/phrase query DSL

`memgrep find "<query>" <memdir>` ranks whole notes (NOT line grep). The query is ONE whitespace-separated string (quote it): `+TERM` mandatory, `-TERM` exclude, bare `TERM` optional (ranks). A word may use `*` (wildcard, any run: `pro*`, `*debug`); a `"quoted phrase"` matches verbatim WITH the spaces and can itself be `+`/`-` prefixed. A `+`/`-` INSIDE a token is literal — `pro*-debug*` is ONE wildcard term, not `pro*` minus `debug*`. Result = notes with every `+` term and no `-` term, ranked by optional hits. `--only-notes` runs the same DSL over the resolved lessons and returns matching `[N] - …` lessons. Composes with every shared flag above.

### Atoms — per-fact recall (block-properties)

A page BODY is a sequence of **atoms** — the body counterpart of `[^N]` lessons. An atom is OPENED by a
leading **Obsidian block-property marker** `^<id> [key: value, key2: a b c]`
(the [obsidian-block-properties-plugin](https://github.com/Querulantenkind/obsidian-block-properties-plugin)
syntax): the marker line sits ABOVE the fact, and the content BELOW it — until the next marker or a
`#`-heading — is the atom's body. Grammar: **comma → properties** (a `[[wikilink]]` is depth-protected),
**first colon → key/value** (colons in a value are kept), **whitespace → a VALUE ARRAY** (the AI-Maestro
extension — `keywords: a b c` is three values). An atom's body may span multiple paragraphs / tables /
code blocks until the next marker or heading.

`keywords:` is the atom's **recall surface** — the array of search terms that makes a single fact
findable on its own. An optional **`desc:`** prop is a one-line summary slug (`[a-z0-9_]+`, ≤64
chars) that `recall`/`find` append to an atom's result line, rendered `_`→space (stored as the slug,
shown as the phrase) — a DISPLAY field only, never FTS-indexed (keywords is the recall surface).
**An atom owns its notes/lessons/see-also** — tied to it by the INLINE `[^N]`
footnotes its body cites. Those footnote DEFINITIONS are pooled at the page bottom under section
headings, and `recall` GROUPS them by which section defines each: a footnote defined under
`# Notes` prints in a `notes:` group, one under `# Lessons Learned` in a `lessons learned:` group,
and one under `# See also` in a `see also:` group (its def text links out to a related memory/topic).
Only non-empty groups print. `recall` ranks atoms by their keyword surface, interleaves them with page
results, and returns each atom as its **FULL aggregated record**:

```text
path#atom-id — <keywords> — <desc>  # locator + keyword surface + the one-line desc (if present, _→space)
<the atom's main content>          # multi-paragraph / tables / code / math / links
notes: <the [^N] # Notes footnotes its body references, resolved>
lessons learned: <the [^N] # Lessons Learned footnotes, resolved>
see also: <the [^N] # See also footnotes — each links out to a related memory>
```

(`--no-notes` keeps the body, drops the grouped footnotes.) The harvest stamps two more block-props as
provenance — `claude_mem_ref: <buffer-rel-path>` + `claude_mem_hash: <sha256-16>` — and
`find-claude-mem-ref` lists the atoms that reference a given buffer file (with their stored hashes) so a
re-harvest touches only NEW or CHANGED memories. Authoring a fact as an atom (with its own history +
relations as inline references):

```markdown
^rotate-drain [desc: rotator_drains_busy_account_first, keywords: rotator drain rate-limit oauth, type: reference, ocd: 2026-06-23, lmd: 2026-06-23]
The rotator drains the live account first when near a limit, then rotates to a safe alternate.[^1][^2]

## Lessons Learned
[^1]: [ocd:2026-06-22 lmd:2026-06-23] earlier this drained the alternate first; reversed — the live account hits the cap sooner.

## See also
[^2]: [[token-rotation]]
```

### Examples

```bash
memgrep recall "oauth rotator failed had to log in" <memdir>     # symptom recall + lessons + atoms
memgrep recall "rotator" <memdir> --since 2026-06-01 --sort lmd  # recent, newest-modified first
memgrep find "+rotator +keychain -widget" <memdir>               # AND two terms, exclude one
memgrep find '+"old approach" retry' <memdir>                    # mandatory phrase + optional ranker
memgrep find "+max_retries" <memdir> --only-notes                # search ONLY the lessons-learned
memgrep find-claude-mem-ref feedback_oauth.md <memdir>           # atoms harvested from a buffer file
memgrep reindex <memdir>                                         # refresh the SQLite query index (pages+lessons+atoms)
memgrep index --markdown --write <memdir>                        # regenerate memory-index.md
memgrep lint <memdir>                                            # structural integrity gate (prints ERROR/WARN/INFO; exit≠0 on ERROR)
memgrep lint <memdir> --min-severity warn                        # …raise the bar: also gate on WARN (link law, oversized atoms)
memgrep overview <memdir>                                        # print the <project>-overview.md navigation entry page
```
