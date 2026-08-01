#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Backing script for /janitor-plugin-{install,uninstall,upgrade} — harness-adaptive.

ONE decision drives everything: which backend actuates the change.

  * OUTSIDE an ai-maestro harness agent  -> the `claude` CLI.
  * INSIDE one                           -> `aimaestro-agent.sh plugin …`, because in the
                                            harness the SERVER owns each agent's plugin set;
                                            a direct `claude plugin install` there mutates
                                            config the server believes it owns and the next
                                            reconcile silently reverts it.

THE DISCRIMINATOR IS THE SESSION, NOT THE SERVER — `harness_backend.is_harness_session()`
(env flags on THIS process), never `server_is_alive()`. They are easy to confuse because the
janitor's CHORE logic deliberately keys on server liveness (TRDD-LU0C5KAR): a running server
owns the absorbed chores. Plugin management is the opposite question. A standalone Claude on
a host that merely happens to be running a server is still a standalone Claude — its plugins
are its own, and routing it through the agent CLI would target an agent it is not.

Nothing here is destructive without saying so: every run prints the resolved backend and the
exact argv before it runs, and `--dry-run` prints without executing.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import harness_backend  # noqa: E402
import plugin_target as pt  # noqa: E402

VALID_SCOPES = ("user", "project", "local")

# The harness CLI. Resolved at CALL time, not import time: HOME may be redirected under test,
# and a frozen constant would then point at the real home (the same trap `continuity_cli`
# documents).
_AGENT_CLI_ENV = "JANITOR_AIMAESTRO_AGENT_CLI"


def agent_cli() -> str | None:
    """Absolute path of `aimaestro-agent.sh`, or None when it is not installed."""
    override = os.environ.get(_AGENT_CLI_ENV, "").strip()
    if override:
        return override if Path(override).is_file() else None
    candidate = Path(os.path.expanduser("~")) / "ai-maestro" / "scripts" / "aimaestro-agent.sh"
    return str(candidate) if candidate.is_file() else None


def resolve_local(target: pt.PluginTarget) -> pt.PluginTarget:
    """Turn a local-directory target into a named one by reading its manifests.

    Done BEFORE `build_argv` so that function stays pure: the filesystem is read once, here,
    and the plan it produces is fully inspectable under `--dry-run`.
    """
    if not target.local_path:
        return target
    kind = pt.classify_local_dir(target.local_path)
    if kind.kind == "plugin-only":
        raise RuntimeError(
            f"{target.raw!r} is a plugin directory with no marketplace. `claude plugin install` "
            "takes a NAME from a REGISTERED marketplace and cannot install a bare directory, so "
            "there is no command to run: point at the marketplace that ships this plugin, or "
            "give the repo its own .claude-plugin/marketplace.json (CPV's self-referential "
            "'Layout C')."
        )
    return pt.PluginTarget(
        raw=target.raw,
        plugin=kind.plugin,
        marketplace=kind.marketplace,
        source=kind.marketplace_dir,
        local_path=target.local_path,
    )


def build_argv(
    action: str,
    target: pt.PluginTarget,
    *,
    scope: str,
    backend: str,
    agent_ref: str | None,
    cli: str | None,
) -> list[list[str]]:
    """The ordered command(s) to run. PURE — builds, never executes, so a plan stays
    inspectable and `--dry-run` costs nothing.

    A source-bearing target yields TWO commands: register the marketplace, then act on the
    plugin. Registering is idempotent in both CLIs, so re-running a partially-completed
    operation is safe — which matters because step 2 failing is the common case (a wrong
    plugin name) and the user will simply re-run.
    """
    cmds: list[list[str]] = []
    # UNINSTALL never registers anything. Removing a plugin must not have "and also add a
    # marketplace" as a side effect — the user asked for less, not more, and the marketplace
    # would outlive the plugin it was added for.
    register_source = target.source if action != "uninstall" else None

    if backend == harness_backend.BACKEND_AIMAESTRO:
        if not cli:
            raise RuntimeError(
                "inside an ai-maestro harness agent but aimaestro-agent.sh was not found — "
                f"set ${_AGENT_CLI_ENV} to its path. Refusing to fall back to the `claude` "
                "CLI: that would mutate plugin config the server owns, and the next "
                "reconcile would revert it without telling anyone."
            )
        if not agent_ref:
            raise RuntimeError(
                "inside an ai-maestro harness agent but this agent's own id could not be "
                "resolved; the agent CLI needs it as its <agent> argument."
            )
        if register_source:
            cmds.append([cli, "plugin", "marketplace", "add", register_source])
        name = target.qualified
        if not name:
            raise RuntimeError(
                f"{target.raw!r} names a marketplace SOURCE, not a plugin. Register it, then "
                "re-run naming the plugin (a marketplace may ship several — installing a "
                "guess is worse than asking)."
            )
        cmds.append([cli, "plugin", action, agent_ref, name, "--scope", scope])
        return cmds

    # Standalone: the plain Claude Code CLI.
    if register_source:
        cmds.append(["claude", "plugin", "marketplace", "add", register_source])
    name = target.qualified
    if not name:
        raise RuntimeError(
            f"{target.raw!r} names a marketplace SOURCE, not a plugin. Register it, then "
            "re-run naming the plugin (a marketplace may ship several — installing a guess "
            "is worse than asking)."
        )
    cmds.append(["claude", "plugin", action, name, "--scope", scope])
    return cmds


def main() -> int:
    ap = argparse.ArgumentParser(prog="plugin_manage")
    ap.add_argument("action", choices=("install", "uninstall", "update"))
    ap.add_argument("target", help="plugin, plugin@market, plugin@owner/market, owner/repo, or a URL")
    ap.add_argument("--scope", default="user", choices=VALID_SCOPES)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    try:
        target = pt.parse_target(args.target)
        # `uninstall` names an ALREADY-INSTALLED plugin, so a local directory is meaningless
        # there — resolving one would register a marketplace as a side effect of removing
        # something, which is the opposite of what was asked.
        if args.action != "uninstall":
            target = resolve_local(target)
        elif target.local_path:
            raise RuntimeError(
                "uninstall takes an installed plugin NAME, not a directory — a path would "
                "register a marketplace as a side effect of a removal."
            )
    except pt.PluginTargetError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    backend = harness_backend.backend()
    cli = agent_cli() if backend == harness_backend.BACKEND_AIMAESTRO else None
    agent_ref = harness_backend.self_agent_ref() if backend == harness_backend.BACKEND_AIMAESTRO else None

    try:
        cmds = build_argv(
            args.action, target, scope=args.scope, backend=backend, agent_ref=agent_ref, cli=cli
        )
    except RuntimeError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2

    print(f"backend={backend}")
    for cmd in cmds:
        print(f"$ {' '.join(cmd)}")
    if args.dry_run:
        print("dry-run: nothing executed")
        return 0

    for cmd in cmds:
        proc = subprocess.run(cmd, text=True)  # noqa: S603 -- fixed argv, no shell
        if proc.returncode != 0:
            # Report WHICH step failed. A marketplace-add failure and a plugin-name failure
            # need opposite fixes, and "exit 1" alone sends people to the wrong one.
            print(f"failed (rc={proc.returncode}): {' '.join(cmd)}", file=sys.stderr)
            return proc.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
