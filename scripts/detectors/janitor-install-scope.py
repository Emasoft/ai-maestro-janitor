#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""janitor-install-scope — warn if ai-maestro-janitor is installed at PROJECT/LOCAL scope.

The janitor is the machine's guardian: it owns OAuth life/death, the global
single-instance daemon, and drift detection for ALL projects. It MUST be a USER-
scope install only (TRDD-db169d9e R5). A project/local-scope install would
(a) duplicate the heartbeat per-project, (b) bind a machine-global guardian to one
repo, and (c) ship the janitor's enablement to every contributor of that repo. This
detector surfaces a one-line warning (with the exact fix) when ai-maestro-janitor is
ENABLED in a project's `.claude/settings.json` or `.claude/settings.local.json`.

Runs in EVERY project (NOT gated on ai-maestro) — the user-only invariant is
universal. Silent when the janitor is not project/local-enabled (the normal case).

`--check` mode bypasses the heartbeat dedupe: it prints the warning (or `OK
user-scope`) and exits NON-ZERO when a project/local install is found, so
/janitor-arm can reliably refuse to arm a mis-scoped install.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402

_PLUGIN = "ai-maestro-janitor"


def _janitor_enabled_in(settings_file: Path) -> bool:
    """True iff `settings_file` lists ai-maestro-janitor in `enabledPlugins`.

    Only `enabledPlugins` counts — a `disabledPlugins` mention is not an active
    install, and a bare string-match (as the rules-installer uses) would false-
    positive on it.
    """
    try:
        data = json.loads(settings_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    plugins = data.get("enabledPlugins")
    if not isinstance(plugins, list):
        return False
    return any(
        isinstance(p, str) and (p == _PLUGIN or p.startswith(_PLUGIN + "@"))
        for p in plugins
    )


def _found_scopes(root: Path) -> list[str]:
    found: list[str] = []
    for scope, rel in (("local", ".claude/settings.local.json"), ("project", ".claude/settings.json")):
        f = root / rel
        if f.is_file() and _janitor_enabled_in(f):
            found.append(scope)
    return found


def _warning(found: list[str]) -> str:
    scopes = "+".join(found)
    fix_scope = found[0]
    return (
        f"[janitor-install-scope] ai-maestro-janitor is enabled at {scopes}-scope in this "
        f"project — it MUST be USER scope only. It guards OAuth, the global daemon, and drift "
        f"for ALL projects; a project/local install duplicates the heartbeat, binds a machine-"
        f"global guardian to one repo, and imposes the plugin on every contributor. Fix: "
        f"`claude plugin uninstall {_PLUGIN} --scope {fix_scope}` then ensure "
        f"`claude plugin install {_PLUGIN}@ai-maestro-plugins --scope user`."
    )


def main() -> int:
    state.init_state()
    check_mode = "--check" in sys.argv[1:]
    found = _found_scopes(state.project_root())

    if check_mode:
        if not found:
            print("OK user-scope")
            return 0
        print(_warning(found))
        return 1  # non-zero → /janitor-arm refuses

    # Heartbeat mode: dedupe so the warning fires at most once until the config changes.
    if found:
        seen = state.state_dir() / "janitor-install-scope-seen.txt"
        line = dedupe.emit_once(seen, "install-scope@" + "+".join(found), _warning(found))
        if line is not None:
            print(line)
    state.rotate_log_if_big("janitor-install-scope")
    return 0


if __name__ == "__main__":
    sys.exit(main())
