<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete once that plugin is gone; a rule file, never a MEMORY store. -->

<!-- No inert-unless-janitor guard by design: other rules describe JANITOR behaviour and go
     inert with it; this describes GITHUB's rendering, true either way. -->

# GitHub: never write `@name` outside a code span

**IRON RULE (owner, 2026-08-02).** In anything posted to GitHub — issue, comment, PR,
review, release note — an `@name` **outside a code span pages a real account**. Write the
name plain, or wrap it in backticks. Measured in one day, all unintended:

- **`@manager` / `@janitor`** — role words this ecosystem writes constantly — paged real users.
- **`user@gmail.com` pages `@gmail`** — the domain parses as a username, so a raw address is a
  PII leak *and* a page. Never paste one; use `<account-A>`.
- **`@lru_cache` pages `@lru`** — usernames cannot contain `_`, so it links the valid prefix.

1. **Backticks are the fix** — GitHub does not linkify inside a code span. `` `@janitor` `` is
   inert, `@janitor` is not: same token, opposite behaviour. Naming someone is not mentioning
   them; write the bare word.
2. **But backticks do NOT protect a TEMPLATE** — it is copied OUT of them. The PRRD byline
   shipped `@owner` (a real org) inside a code span for months. Templates carry no `@` at all.
3. **Pasting TOOL OUTPUT is the usual cause** — a payload you did not author carries both harms,
   invisibly. Read it for identifiers first. Redaction is not undo: repos may be public and edit
   history is kept.

The self-ID line names the owner in **plain words**; the `@` only adds a notification. Enforced by
`pre-bash-safety.check_outbound_publication`, which allows a backticked form — a guard that
reddens on correct writing gets deleted.
