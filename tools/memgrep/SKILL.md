# memgrep — markdown-aware grep

`memgrep` is `grep`/`rg` for markdown: walks a tree (gitignore-aware), matches a **regex** per line, prints `path:line:col:text`. **All your grep muscle memory works** — `-i -w -n -l -c -e PATTERN [PATH…]`, `--json`, `--hidden`. Five rules cover the rest: (1) every matcher value is a regex; (2) grep-equivalent flags keep their name; (3) numeric/version ranges use pip syntax (`>=1.2,<3.5`); (4) wildcards are `*`; (5) different flags AND-narrow, comma-lists OR-widen.

## Structural filters (the net-new surface)
- **code:** `--no-code` (drop code-block false positives) · `--code` · `--code-lang py,rs`
- **headings:** `--heading` · `--level 2`|`2..3`|`>=2` · `--in REGEX` (section + subsections) · `--num 1.2`|`1.2.*`|`>=1.2,<3.5` · `--depth N`
- **inline:** `--bold`/`--italic`/`--code-span`/`--strike REGEX` · `--class a,b`/`--class-all` · `--span-class c` · `--list`/`--no-list`
- **gfm nodes:** `--node table,quote,math,url,image,html,svg,footnote` · `--no-node …` · sugar `--table` etc.

## Boolean queries — `--where 'EXPR'`
Each `--flag v` above is the predicate `flag "v"` (negatives via `not`); compose with `and`/`or`/`not` + `( )` (juxtaposition = and). `--where`-only file-level predicates: `path "**/g"`, `name "*.md"`, `fm.KEY "v"` (smart glob/range/regex), `links-to "note"`/`linked-from "note"` (link semijoin = SQL JOIN). `--where` is the whole query — don't mix it with the flags.

## Subcommands
`memgrep index [PATH]` → (re)write `memory-index.md` (per-note title+summary+tags+TOC+backlinks). · `memgrep links --broken|--orphans|--to N|--from N`. · `memgrep fact [--cat/--comp/--session/--kind/--since/--until]`.

## Recall memories
`memgrep recall "SYMPTOM WORDS" <memdir>` → notes ranked by symptom match as `path — description`; read the top few. Query the QUESTION's words, not the answer's.

## Find — `+`/`-`/wildcard/phrase query DSL
`memgrep find "<query>" <memdir>` → note-level search by a keyword DSL (NOT line grep). The query is ONE whitespace-separated string (quote it): `+TERM` mandatory, `-TERM` exclude, bare `TERM` optional (ranks). A word may use `*` (wildcard, any run: `pro*`, `*debug`); a `"quoted phrase"` matches verbatim WITH the spaces and can itself be `+`/`-` prefixed. A `+`/`-` INSIDE a token is literal — `pro*-debug*` is ONE wildcard term, not `pro*` minus `debug*`. Results = notes with every `+` term and no `-` term, ranked by optional hits. `--only-notes` searches the resolved `[^N]` lessons instead of pages. Composes with `--sort ocd|lmd|score`, `--since/--until`, `--with-notes/--full-notes`, `--use-index`.
