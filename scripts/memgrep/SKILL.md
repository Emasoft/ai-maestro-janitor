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
| `recall "SYMPTOM" <memdir>` | rank notes by symptom match → `path — description`, best first; each note's `[^N]` lessons appended (default-on). Query the QUESTION's words, not the answer's |
| `find "<query>" <memdir>` | note-level `+`/`-`/wildcard/phrase keyword search (see below); `--only-notes` searches the lessons instead of pages |
| `index <memdir>` / `reindex <memdir>` | build the persistent SQLite query index `.memgrep/index.db` (gitignored, git-incremental — re-parses only changed files); `--full` rebuilds from scratch |
| `index --markdown <memdir>` | the legacy doc-generator → `memory-index.md` (per-note title+summary+tags+TOC+backlinks); add `--write` to write the file instead of stdout |
| `links --broken\|--orphans\|--to N\|--from N` | link graph / semijoin over the corpus |
| `fact [--cat/--comp/--session/--kind/--since/--until]` | query one-fact-per-line memory lines; `--with-notes` (OFF by default here) appends matched files' lessons |

### `recall` / `find` shared flags

`--with-notes` (default ON — resolve+append `[^N]` lessons) · `--no-notes` (body only) · `--full-notes` (keep each lesson's leading `[…]` metadata prefix; default stripped — URLs/images always kept) · `--sort score|ocd|lmd` (default `score`=relevance) · `--order asc|desc` (default `desc`) · `--since <ISO>` / `--until <ISO>` over `--date-field ocd|lmd` (default `lmd`) · `--top N` (default 10) · `--use-index` (force the SQLite sidecar; auto-used when fresh, else the live walk — results always correct).

Render is token-economical: an inline footnote ref shows as a bare `[9]`; after the body memgrep appends `[9] - <lesson WHY>.` (the on-disk `[^9]`/`[^9]:` form does not leak). OCD/LMD are read from frontmatter `ocd`/`lmd` (aliases `created`/`updated`) or a lesson's `[ocd:… lmd:…]` prefix.

### `find` — the `+`/`-`/wildcard/phrase query DSL

`memgrep find "<query>" <memdir>` ranks whole notes (NOT line grep). The query is ONE whitespace-separated string (quote it): `+TERM` mandatory, `-TERM` exclude, bare `TERM` optional (ranks). A word may use `*` (wildcard, any run: `pro*`, `*debug`); a `"quoted phrase"` matches verbatim WITH the spaces and can itself be `+`/`-` prefixed. A `+`/`-` INSIDE a token is literal — `pro*-debug*` is ONE wildcard term, not `pro*` minus `debug*`. Result = notes with every `+` term and no `-` term, ranked by optional hits. `--only-notes` runs the same DSL over the resolved lessons and returns matching `[N] - …` lessons. Composes with every shared flag above.

### Examples

```bash
memgrep recall "oauth rotator failed had to log in" <memdir>     # symptom recall + lessons
memgrep recall "rotator" <memdir> --since 2026-06-01 --sort lmd  # recent, newest-modified first
memgrep find "+rotator +keychain -widget" <memdir>               # AND two terms, exclude one
memgrep find '+"old approach" retry' <memdir>                    # mandatory phrase + optional ranker
memgrep find "+max_retries" <memdir> --only-notes                # search ONLY the lessons-learned
memgrep reindex <memdir>                                         # refresh the SQLite query index
memgrep index --markdown --write <memdir>                        # regenerate memory-index.md
```
