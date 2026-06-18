---
description: Save a PRIVATE user memory that is invisible to the agent. With text, saves that text; bare (no args), saves your whole previous message. The text never enters the agent's context — only a redacted confirmation is shown to you.
argument-hint: "[<memory text>]"
---

# /janitor-memory-user-add [<memory text>]

Saves a **private user memory** to your per-project user-memory store. This
memory is **invisible to the agent**: the text never enters the conversation or
the model's context window.

- `/janitor-memory-user-add <text>` — saves `<text>`.
- `/janitor-memory-user-add` (no argument) — saves your **whole previous message**.

## How it works (privacy)

The ai-maestro-janitor `UserPromptSubmit` hook intercepts this command **before
it reaches the agent**. The hook:

1. Extracts the text (the argument, or your previous user message read from the
   session transcript when the command is bare).
2. Writes it to the private store
   (`~/.claude/projects/<project>/memory/user-mem/`) with a permanent,
   never-reused number.
3. **Blocks the prompt** (`decision:block` erases it), so the agent never sees
   the command or its text — only you see a confirmation like
   `[user-mem] saved #7 (142 chars) — content withheld from agent context.`

You should never see the agent respond to this command. If you do, the janitor
plugin's user-mem hook is not wired in — verify the plugin is installed and the
hook is registered in `hooks/hooks.json`.

Search your memories with `/janitor-memory-user-search`; bring one into the
agent's context (the only path that does) with `/janitor-memory-user-share
<number>`.

> **Legacy name:** `/to-user-mem` still works (deprecated alias). Prefer the
> `/janitor-memory-user-*` names; the old form is kept only so existing muscle
> memory never leaks (the hook still intercepts and blocks it).
