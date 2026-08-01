"""Parse the many ways a human names a plugin into one unambiguous target.

The install/uninstall/update skills accept every form a person actually types:

    ruff-helper                                  bare plugin name
    ruff-helper@my-market                        plugin @ marketplace
    ruff-helper@Emasoft/my-market                plugin @ owner/marketplace
    Emasoft/my-market                            owner/repo shorthand (a marketplace SOURCE)
    https://github.com/Emasoft/my-market         a URL (ditto)
    git@github.com:Emasoft/my-market.git         SSH URL (ditto)

They are not the same KIND of thing, and conflating them is the whole difficulty: the first
three NAME a plugin, the last three name a SOURCE the plugin has to be found in. A source
must be registered as a marketplace before any install can reference it, so the caller needs
to know which it was handed — hence `needs_marketplace_add`.

ORDER OF TESTS IS LOAD-BEARING. URL-ness is decided BEFORE the `@` split, because
`git@github.com:owner/repo.git` starts with `git@` — splitting on `@` first would yield the
plugin name "git", which is not an error the user would ever understand. Likewise `owner/repo`
is only a shorthand when there is no `@`; `plugin@owner/market` has both and means something
else entirely.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# A Claude Code plugin / marketplace name. Deliberately strict: these end up as argv elements
# for `claude` or `aimaestro-agent.sh`, and a name is not a place to discover that someone can
# smuggle a flag. Rejecting a leading `-` is the point — "--scope" is a valid-looking name.
_NAME_RE = re.compile(r"\A[A-Za-z0-9_][A-Za-z0-9._-]*\Z")

_URL_SCHEME_RE = re.compile(r"\A[a-zA-Z][a-zA-Z0-9+.-]*://")
_SSH_URL_RE = re.compile(r"\A[A-Za-z0-9._-]+@[A-Za-z0-9.-]+:")


class PluginTargetError(ValueError):
    """The user's argument could not be read as any supported form."""


@dataclass(frozen=True)
class PluginTarget:
    """One resolved target.

    `plugin` is None exactly when the argument named a SOURCE rather than a plugin — the
    caller must resolve the source's catalog to learn which plugin(s) it offers, because a
    marketplace may carry more than one and guessing from the repo name is how you install
    the wrong thing.
    """

    raw: str
    plugin: str | None
    marketplace: str | None
    source: str | None  # what `claude plugin marketplace add <source>` takes
    local_path: str | None = None  # set when `source` is a directory on this machine

    @property
    def needs_marketplace_add(self) -> bool:
        """True when the target names a source that may not be registered yet."""
        return self.source is not None

    @property
    def qualified(self) -> str | None:
        """`plugin@marketplace` when both are known — the form both CLIs accept."""
        if self.plugin and self.marketplace:
            return f"{self.plugin}@{self.marketplace}"
        return self.plugin


def _valid_name(value: str) -> bool:
    return bool(_NAME_RE.match(value))


def _marketplace_from_repo(repo: str) -> str:
    """The marketplace NAME implied by a repo.

    Only a default: `claude plugin marketplace add` derives the registered name from the
    catalog the repo actually ships, which may differ. The caller re-reads the real name
    after adding rather than trusting this — it exists so an error message can say something
    concrete before the add has happened.
    """
    return repo[:-4] if repo.endswith(".git") else repo


def _looks_like_explicit_path(value: str) -> bool:
    """True for a form that can ONLY be a path: absolute, `~`, `./`, `../`.

    Kept separate from "does it exist" on purpose. An explicit path that is absent must
    produce "no such directory", not be silently retried as a plugin NAME — the second
    reading would go to the network and fail with something unrelated to the typo.
    """
    return value.startswith(("/", "~", "./", "../")) or value == "." or value == ".."


def parse_target(raw: str, *, isdir: Callable[[str], bool] | None = None) -> PluginTarget:
    """Parse one user-supplied plugin argument. Raises PluginTargetError on anything else.

    `isdir` is injected so the ambiguous `a/b` case (an `owner/repo` shorthand vs a real
    relative directory) can be decided by the filesystem while the function stays testable.
    """
    probe = isdir if isdir is not None else os.path.isdir
    value = (raw or "").strip()
    if not value:
        raise PluginTargetError("empty plugin argument")

    # 0. Local directories. BEFORE the URL test only for the unambiguous prefixes, because a
    # Windows-style `C:\…` is not supported here and `/x` can never be a URL or a name.
    if _looks_like_explicit_path(value):
        expanded = os.path.expanduser(value)
        if not probe(expanded):
            raise PluginTargetError(f"no such directory: {value!r}")
        resolved = str(Path(expanded).resolve())
        return PluginTarget(
            raw=value, plugin=None, marketplace=None, source=resolved, local_path=resolved
        )

    # 1. URLs — see the module docstring on why this cannot come after the `@` split.
    if _URL_SCHEME_RE.match(value) or _SSH_URL_RE.match(value):
        repo = value.rstrip("/").rsplit("/", 1)[-1].rsplit(":", 1)[-1]
        return PluginTarget(
            raw=value, plugin=None, marketplace=_marketplace_from_repo(repo) or None, source=value
        )

    # 2. `plugin@…` — split on the FIRST `@` only, so a marketplace containing one is kept whole.
    if "@" in value:
        plugin, _, rest = value.partition("@")
        if not _valid_name(plugin):
            raise PluginTargetError(f"not a usable plugin name: {plugin!r}")
        if not rest:
            raise PluginTargetError(f"{value!r} has an empty marketplace after '@'")
        if "/" in rest:
            # plugin@owner/marketplace — the marketplace is ALSO a source we can register.
            owner, _, market = rest.partition("/")
            if not _valid_name(owner) or not _valid_name(market):
                raise PluginTargetError(f"not a usable owner/marketplace: {rest!r}")
            return PluginTarget(
                raw=value,
                plugin=plugin,
                marketplace=_marketplace_from_repo(market),
                source=f"{owner}/{market}",
            )
        if not _valid_name(rest):
            raise PluginTargetError(f"not a usable marketplace name: {rest!r}")
        # Already-registered marketplace assumed: no source, so no add is attempted.
        return PluginTarget(raw=value, plugin=plugin, marketplace=rest, source=None)

    # 3. `owner/repo` shorthand — a SOURCE, so the plugin stays unknown on purpose.
    #    A bare `a/b` is ALSO a legal relative directory, and only the filesystem can tell
    #    them apart. An existing directory wins: it is the reading the user can verify, and
    #    treating a real local checkout as a GitHub slug would silently clone a stranger's
    #    repo of the same name.
    if "/" in value and probe(value):
        resolved = str(Path(value).resolve())
        return PluginTarget(
            raw=value, plugin=None, marketplace=None, source=resolved, local_path=resolved
        )
    if "/" in value:
        owner, _, repo = value.partition("/")
        if not _valid_name(owner) or not _valid_name(repo) or "/" in repo:
            raise PluginTargetError(f"not a usable owner/repo shorthand: {value!r}")
        return PluginTarget(
            raw=value, plugin=None, marketplace=_marketplace_from_repo(repo), source=value
        )

    # 4. A bare plugin name. A bare word that happens to also be a directory is read as a
    #    NAME — write `./foo` to mean the directory. Guessing by existence here would make
    #    the same command behave differently depending on the cwd.
    if not _valid_name(value):
        raise PluginTargetError(f"not a usable plugin name: {value!r}")
    return PluginTarget(raw=value, plugin=value, marketplace=None, source=None)


@dataclass(frozen=True)
class LocalKind:
    """What a local directory actually IS, and the names read out of its manifests."""

    kind: str  # "marketplace" | "plugin-in-marketplace" | "plugin-only"
    plugin: str | None
    marketplace: str | None
    marketplace_dir: str | None  # what to hand `marketplace add`


def classify_local_dir(
    path: str,
    *,
    read_json: Callable[[str], dict | None] | None = None,
) -> LocalKind:
    """Decide what a local directory is, from its `.claude-plugin/` manifests.

    Three real shapes, because `claude plugin install` accepts a plugin NAME from a
    REGISTERED marketplace and never a bare directory:

      * `marketplace.json` present            -> a marketplace. Register it, then install by
                                                 name. (A repo carrying BOTH — "Layout C",
                                                 which this very plugin uses — lands here and
                                                 also yields its own plugin name.)
      * only `plugin.json`, parent has a
        `marketplace.json`                    -> the common monorepo layout: register the
                                                 PARENT, install this plugin by its name.
      * only `plugin.json`, no such parent    -> nothing can install it. Say so plainly
                                                 rather than emitting a command that fails
                                                 with an unrelated "plugin not found".

    `read_json` is injected for testing; it returns None for a missing/unreadable file.
    """
    reader = read_json if read_json is not None else _read_json
    base = Path(path)
    mkt = reader(str(base / ".claude-plugin" / "marketplace.json"))
    plg = reader(str(base / ".claude-plugin" / "plugin.json"))

    plugin_name = None
    if isinstance(plg, dict):
        name = plg.get("name")
        plugin_name = name if isinstance(name, str) and _valid_name(name) else None

    if isinstance(mkt, dict):
        name = mkt.get("name")
        market_name = name if isinstance(name, str) and _valid_name(name) else None
        return LocalKind("marketplace", plugin_name, market_name, str(base))

    if plugin_name is None:
        raise PluginTargetError(
            f"{path!r} is neither a marketplace nor a plugin — no readable "
            ".claude-plugin/marketplace.json or .claude-plugin/plugin.json"
        )

    parent_mkt = reader(str(base.parent / ".claude-plugin" / "marketplace.json"))
    if isinstance(parent_mkt, dict):
        name = parent_mkt.get("name")
        market_name = name if isinstance(name, str) and _valid_name(name) else None
        return LocalKind("plugin-in-marketplace", plugin_name, market_name, str(base.parent))

    return LocalKind("plugin-only", plugin_name, None, None)


def _read_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None
