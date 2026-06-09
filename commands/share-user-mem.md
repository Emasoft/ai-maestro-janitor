---
description: Inject one private user memory (by its number) into the agent's context. This is the ONLY path by which the agent ever sees a user memory — a deliberate, explicit opt-in.
argument-hint: "<number>"
---

# /share-user-mem <number>

Injects the text of private user memory **#number** into the agent's context.
This is the **single deliberate gate** by which a user memory ever reaches the
model — `/to-user-mem` (save) and `/search-user-mem` (search) keep everything
hidden; only `/share-user-mem` lets a chosen memory in.

Get the number from `/search-user-mem` results (each result line is prefixed
with its immutable number, e.g. `#7`).

## Example

```
/search-user-mem +keychain          → shows "#3  keychain rotation cadence …"
/share-user-mem 3                    → memory #3's text enters the conversation
```

## How it works

The janitor `UserPromptSubmit` hook reads memory #number from the private store
and injects it via `hookSpecificOutput.additionalContext` (the documented
channel that reaches the model). If the number does not exist, the hook blocks
the prompt and tells you `[user-mem] memory #N not found.` — nothing is injected.

You can equally just paste a memory's text yourself; `/share-user-mem` is the
convenience that avoids re-typing.
