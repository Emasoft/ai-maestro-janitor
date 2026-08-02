<!-- ai-maestro-janitor:installed-rule — installed by the ai-maestro-janitor plugin. Safe to
     delete once that plugin is gone; a rule file, never a MEMORY store. -->

<!-- No inert-unless-janitor-active guard: the other shipped rules describe JANITOR
     behaviour and go inert with it; this describes GITHUB's rendering, true either way. -->

# GitHub: never write `@name` outside a code span

**IRON RULE (owner, 2026-08-02).** In anything posted to GitHub — issue, comment, PR,
review, release note — an `@name` **outside a code span pages a real account**. Write the
name plain, or wrap it in backticks.

Measured in one day, all unintended:

- **`@manager` and `@janitor`** — role words this ecosystem writes constantly — paged real
  users of those names.
- **`user@gmail.com` pages `@gmail`**: GitHub reads the domain as a username, so a raw
  address is a PII leak *and* a page.
- **`@lru_cache` pages `@lru`**: usernames cannot contain `_`, so it links the valid prefix.

1. **Backticks are the fix.** GitHub does not linkify inside a code span: `` `@janitor` `` is
   inert, `@janitor` is not. Same token, opposite behaviour.
2. **Never paste a raw email.** Use `<account-A>`. Redaction is not undo — repos may be
   public and GitHub keeps edit history.
3. **Pasting TOOL OUTPUT is the usual cause.** A table you did not author carries both
   harms, and neither is visible in the text you are quoting. Read any payload for
   identifiers before it leaves the machine.
4. **Naming someone is not mentioning them.** Write the bare word; the `@` adds only a
   notification to a stranger.

The one sanctioned `@` is the self-identification line naming the account owner. Enforced by
`pre-bash-safety.check_outbound_publication`, which allows both forms inside backticks —
a guard that reddens on correct writing gets deleted.
