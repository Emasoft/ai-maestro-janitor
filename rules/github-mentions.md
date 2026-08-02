<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete once that plugin is gone; a rule file, never a MEMORY store. -->

<!-- No inert-unless-janitor guard by design: other rules describe JANITOR behaviour and go
     inert with it; this describes GITHUB's rendering, true either way. -->

# GitHub: never write `@name` outside a code span

**IRON RULE (owner, 2026-08-02).** In anything posted to GitHub — issue, comment, PR,
review, release note — an `@name` **outside a code span pages a real account**. Write the
name plain, or wrap it in backticks. `@manager`, `@janitor` and `@staticmethod` all paged real
users in one day — looking technical does not make a word inert.

**Only at a WORD BOUNDARY, and never before `/`** — measured with `gh api markdown`, so trust it
over intuition. `@janitor.` `(@janitor)` `@foo-bar` **page**; `@lru_cache` `@types/node`
`actions/checkout@v4` `x@janitor` `user@gmail.com` are **plain text**. An address does not page
its domain. Still never paste one — that is PII, a separate and sufficient reason.

1. **Backticks are the fix** — GitHub does not linkify inside a code span. `` `@janitor` `` is
   inert, `@janitor` is not: same token, opposite behaviour. Naming someone is not mentioning
   them; write the bare word.
2. **But backticks do NOT protect a TEMPLATE** — it is copied OUT of them. The PRRD byline
   shipped `@owner` (a real org) inside a code span for months. Templates carry no `@` at all.
3. **Pasted TOOL OUTPUT is the usual cause** — read any payload you did not author for
   identifiers first. Redaction is not undo: repos may be public and edit history is kept.

The self-ID line names the owner in **plain words**; the `@` only adds a notification. The rule
binds ON ITS OWN — treat it as manual discipline. An enforcement guard exists in the janitor's
tree (`pre-bash-safety.check_outbound_publication`, allowing backticked forms — a guard that
reddens on correct writing gets deleted), but do NOT assume your installed version carries it:
verify with `grep -rl check_outbound_publication <your installed plugin cache>` before relying
on it. A rule that CLAIMS enforcement it cannot prove stops its reader from checking — the
janitor#171 lesson: the claim shipped ahead of the guard and a real account got paged under the
belief a guard covered it.
