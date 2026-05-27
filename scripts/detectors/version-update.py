#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Version-update detector — read-only after TRDD-be2efa56 §9 follow-up.

Keeps three versions in sync:

  * running           — version of dispatch that's actually firing on the
                        cron prompt (extracted from the script's own path)
  * latest_installed  — highest version present in the plugin cache dir
  * latest_published  — latest GitHub release for the repo declared in
                        the manifest's `repository` field

This detector USED to also run `claude plugin marketplace update` +
`claude plugin update ...` itself; that branch has moved into the daemon
(`scripts/daemon.py::task_version_update`) so a single global writer
owns the network calls instead of every Claude session racing.

This detector now ONLY surfaces drift lines:

  * `[version-update] ai-maestro-janitor X → Y — run /plugin update …`
      — when the cache is behind GitHub AND `auto_update_on_new_release`
      is disabled (so the daemon won't act → user has to). The line is
      a one-shot per published version.

  * `[version-update] ai-maestro-janitor X installed; cron is on Y. /janitor-arm.`
      — when the cache advanced (likely the daemon ran a self-update)
      but the running cron is still firing the older dispatch. The
      auto-rolling stub re-resolves the highest cache version on every
      fire, so this nudge fires only on hosts where the stub mechanism
      is bypassed.

Silent on transient failures (no network, gh auth expired, no
releases yet). One nudge per state change, then dedupe.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import dedupe  # noqa: E402
import state  # noqa: E402
import version_update_lib as vu  # noqa: E402


def main() -> int:
    state.init_state()

    seen = state.state_dir() / "version-update-seen.txt"
    here = Path(__file__).resolve().parent  # scripts/detectors/

    # Running version — basename of `<plugin>/<version>/scripts/detectors/`.
    plugin_root = here.parent.parent       # <plugin>/<version>/
    cache_parent = plugin_root.parent      # <plugin>/
    running_version = plugin_root.name

    is_cache_install = vu._SEMVER_RE.match(running_version) is not None
    if not is_cache_install:
        state.log_line(
            "version-update",
            f"running from non-versioned dir ({running_version}) — "
            "cron-version check disabled",
        )

    latest_installed = ""
    if is_cache_install:
        installed = vu.list_installed_versions(cache_parent)
        latest_installed = installed[-1] if installed else ""

    plugin_root_for_lookup = Path(
        os.environ.get("CLAUDE_PLUGIN_ROOT", "") or plugin_root,
    )
    latest_published = vu.resolve_latest_published(plugin_root_for_lookup) or ""

    state.log_line(
        "version-update",
        f"state: running={running_version} latest_installed={latest_installed} "
        f"latest_published={latest_published}",
    )

    auto_enabled = state.is_truthy_env(
        "CLAUDE_PLUGIN_OPTION_AUTO_UPDATE_ON_NEW_RELEASE", True,
    )

    line = None

    # Branch A: cache behind GitHub.
    if (
        latest_published
        and latest_installed
        and latest_published != latest_installed
        and vu._semver_tuple(latest_installed) < vu._semver_tuple(latest_published)
    ):
        if auto_enabled:
            # The daemon owns the auto-update. Silent — the next daemon
            # cycle will run the update and the cache-vs-cron branch
            # below will fire after the update lands.
            state.log_line(
                "version-update",
                "auto-update is enabled — daemon will run the update on its next cycle; detector stays silent",
            )
        else:
            # User opted out of auto-update; surface the manual nudge.
            line = dedupe.emit_once(
                seen,
                f"version-update@manual@{latest_published}",
                f"[version-update] {vu.PLUGIN_NAME} {latest_installed} → "
                f"{latest_published} — auto_update_on_new_release is off; "
                f"run /plugin update {vu.PLUGIN_NAME} + /janitor-arm.",
            )

    # Branch B: cache advanced past the running cron (likely daemon just
    # auto-updated). The auto-rolling stub usually picks this up
    # silently; this nudge is the belt-and-braces.
    if (
        line is None
        and is_cache_install
        and latest_installed
        and running_version != latest_installed
    ):
        line = dedupe.emit_once(
            seen,
            f"version-update@stale-cron@{latest_installed}",
            f"[version-update] {vu.PLUGIN_NAME} {latest_installed} installed; "
            f"cron is on {running_version}. /janitor-arm.",
        )

    if line is not None:
        print(line)

    state.rotate_log_if_big("version-update")
    return 0


if __name__ == "__main__":
    sys.exit(main())
