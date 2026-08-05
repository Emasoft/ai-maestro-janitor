---
name: janitor-plugin-upgrade
description: Upgrade a Claude Code plugin, adapting automatically to the harness. Use when the user asks to upgrade a plugin, or says "upgrade <plugin>", "upgrade <owner>/<repo>", or points at a plugin URL or local folder. Accepts a bare name, plugin@marketplace, plugin@owner/marketplace, an owner/repo shorthand, an https/ssh URL, or a local directory path.
---

# Janitor plugin upgrade

Upgrade a plugin through whichever backend is correct for THIS session, so the same command
works inside and outside the ai-maestro harness.

## The one decision this skill exists to get right

| where this session runs | backend used |
|---|---|
| NOT inside an ai-maestro harness agent | the `claude` CLI |
| inside an ai-maestro harness agent | `aimaestro-agent.sh plugin …` |

**It keys on THIS SESSION, never on whether an ai-maestro server is running.** A standalone
Claude on a host that happens to be running a server is still standalone: its plugins are its
own, and routing it through the agent CLI would target an agent it is not. (The janitor's
*chore* logic deliberately uses the opposite test — server liveness — so the two are easy to
confuse. `harness_backend.is_harness_session()` is the right one; `server_is_alive()` is not.)

Inside the harness the server owns each agent's plugin set, so a direct `claude plugin update`
there mutates config the server believes it owns and the next reconcile silently reverts it.
The script REFUSES to fall back to `claude` in that case rather than appear to succeed.

> **IRON RULE — talk to ai-maestro through its SCRIPTS, never its HTTP API.** Every
> interaction goes through the frozen CLI (`aimaestro-*.sh`, `amp-*.sh`, `aid-*.sh`). An agent
> MUST NOT call `/api/*` or `:23000` directly — not with any HTTP client, not from a hook, a script, or
> a skill. The scripts are the supported, versioned surface; the HTTP routes are internal and
> change without notice.
>
> **If the CLI lacks the verb you need, that is a gap to REPORT, never a licence to bypass.**
> Reaching for the API, overloading an unrelated flag, or dropping a side-channel file for the
> server to poll are the same violation in three costumes. File it against ai-maestro and wait
> for the verb.

## Usage

```bash
uv run --script --quiet "${CLAUDE_PLUGIN_ROOT}/scripts/plugin_manage.py" update <target> [--scope user|project|local] [--dry-run]
```

`--scope` defaults to `user`. Pass `--dry-run` first when the target came from the user
verbatim — it prints the resolved backend and the exact commands without running them.

## Accepted targets

| form | meaning |
|---|---|
| `ruff-helper` | a plugin in an already-registered marketplace |
| `ruff-helper@my-market` | that plugin, in that marketplace |
| `ruff-helper@Emasoft/my-market` | ditto, and the marketplace is registered first if needed |
| `Emasoft/my-market` | a marketplace SOURCE — the plugin is NOT guessed (see below) |
| `https://github.com/o/r`, `git@github.com:o/r.git` | ditto, as a URL |
| `/path/to/dir`, `./dir`, `~/dir` | a local marketplace or plugin directory |

**A source alone is refused, deliberately.** `owner/repo` and a bare URL name a marketplace,
which may ship several plugins; installing a guess is worse than asking. Register it, then
re-run naming the plugin.

**Local directories** are classified from their manifests, not from the path:

- `.claude-plugin/marketplace.json` present → registered directly, then installed by name.
  A repo carrying both manifests (CPV's self-referential "Layout C") lands here and
  yields its own plugin name too.
- only `.claude-plugin/plugin.json`, with a marketplace in the PARENT → the parent is
  registered (the usual monorepo layout) and the plugin installed by name.
- only `.claude-plugin/plugin.json` and no such parent → **refused with an explanation**.
  `claude plugin install` takes a NAME from a REGISTERED marketplace and cannot install a
  bare directory, so there is no command to emit; pretending otherwise fails later with an
  unrelated "plugin not found".

A bare word is always read as a NAME even if a directory shares it — write `./foo` for the
directory, so the same command cannot mean different things depending on the cwd.

## After it runs

Claude Code loads plugins from the installed CACHE, not from a source checkout, and a newly
installed plugin is not live in the current session. Tell the user to run `/reload-plugins`
(or restart). Do not claim the plugin is available until it appears in the skill list.

## Scope

ONLY upgrade. Does not arm the heartbeat, edit settings by hand, or touch other plugins.

## Resources

- `${CLAUDE_PLUGIN_ROOT}/scripts/plugin_manage.py` — the backing script.
- `${CLAUDE_PLUGIN_ROOT}/scripts/lib/plugin_target.py` — target parsing + local-dir classification.
- `${CLAUDE_PLUGIN_ROOT}/scripts/lib/harness_backend.py` — the session-vs-server discriminator.
