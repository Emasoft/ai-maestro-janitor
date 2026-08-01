"""Every form a human may type for a plugin, and the ones that must be refused.

The parser's whole job is telling apart arguments that LOOK alike but mean different things —
`plugin@market` vs `owner/repo` vs `git@github.com:owner/repo.git` — so the tests are written
per FORM, and each asserts the discriminator that form exists to exercise, not just the happy
field values.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "scripts" / "lib"))

from plugin_target import (  # noqa: E402
    PluginTargetError,
    classify_local_dir,
    parse_target,
)


def test_bare_plugin_name_names_a_plugin_and_no_source() -> None:
    """The simplest form: nothing to register, nothing to resolve."""
    t = parse_target("ruff-helper")
    assert (t.plugin, t.marketplace, t.source) == ("ruff-helper", None, None)
    assert t.needs_marketplace_add is False
    assert t.qualified == "ruff-helper"


def test_plugin_at_marketplace() -> None:
    """`plugin@market` assumes the marketplace is already registered — no source to add."""
    t = parse_target("ai-maestro-janitor@ai-maestro-plugins")
    assert (t.plugin, t.marketplace) == ("ai-maestro-janitor", "ai-maestro-plugins")
    assert t.source is None and t.needs_marketplace_add is False
    assert t.qualified == "ai-maestro-janitor@ai-maestro-plugins"


def test_plugin_at_owner_slash_marketplace_also_yields_a_registrable_source() -> None:
    """`plugin@owner/market` names the plugin AND where to get it, so the caller can register
    the marketplace before installing rather than failing on an unknown one."""
    t = parse_target("cpv@Emasoft/emasoft-plugins")
    assert (t.plugin, t.marketplace, t.source) == ("cpv", "emasoft-plugins", "Emasoft/emasoft-plugins")
    assert t.needs_marketplace_add is True
    assert t.qualified == "cpv@emasoft-plugins"


def test_owner_repo_shorthand_is_a_source_with_an_UNKNOWN_plugin() -> None:
    """A repo may ship SEVERAL plugins. Guessing the plugin from the repo name would install
    the wrong one silently, so `plugin` stays None and the caller must read the catalog."""
    t = parse_target("Emasoft/ai-maestro-plugins")
    assert t.plugin is None, "a source must not be guessed into a plugin name"
    assert (t.marketplace, t.source) == ("ai-maestro-plugins", "Emasoft/ai-maestro-plugins")
    assert t.needs_marketplace_add is True
    assert t.qualified is None


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/Emasoft/ai-maestro-plugins",
        "https://github.com/Emasoft/ai-maestro-plugins/",
        "https://github.com/Emasoft/ai-maestro-plugins.git",
    ],
)
def test_https_urls_are_sources_and_keep_the_url_verbatim(url: str) -> None:
    """The URL is passed to `marketplace add` UNCHANGED — normalising it risks changing which
    remote is contacted. Only the derived default NAME strips `.git`/trailing slash."""
    t = parse_target(url)
    assert t.plugin is None
    assert t.source == url, "the source must reach the CLI exactly as the user gave it"
    assert t.marketplace == "ai-maestro-plugins"


def test_ssh_url_is_not_split_on_its_at_sign() -> None:
    """THE ordering regression. `git@github.com:owner/repo.git` starts with `git@`, so an
    `@`-split before the URL test yields plugin="git" — a nonsense name the user cannot debug.
    URL-ness must be decided first."""
    t = parse_target("git@github.com:Emasoft/ai-maestro-plugins.git")
    assert t.plugin != "git", "the SSH URL was split on '@' — URL detection must come first"
    assert t.plugin is None
    assert t.source == "git@github.com:Emasoft/ai-maestro-plugins.git"
    assert t.marketplace == "ai-maestro-plugins"


def test_a_second_at_sign_is_refused_rather_than_guessed() -> None:
    """`plug@weird@market` is not a form that exists — a marketplace name has no `@`.

    Written first as "split on the FIRST @, keep the rest whole", which the parser refused.
    The parser was right: accepting it would have to invent a meaning for the second `@`, and
    an argument with two plausible readings must fail loudly rather than pick one. Kept as a
    test so the next person does not 'fix' the parser into guessing."""
    with pytest.raises(PluginTargetError):
        parse_target("plug@weird@market")


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "   ",
        "--scope",  # a flag must never pass as a name
        "-rf",
        "plugin@",  # empty marketplace
        "@market",  # empty plugin
        "a/b/c",  # not an owner/repo
        "plug in",  # whitespace
        "plug;rm -rf /",  # shell metacharacters
        "plug@mar;ket",
    ],
)
def test_unusable_arguments_are_refused_not_guessed(bad: str) -> None:
    """These go straight into an argv for `claude` / `aimaestro-agent.sh`. A name is not a
    place to discover that a flag or a metacharacter can be smuggled through, and silently
    'fixing' one is worse than refusing it."""
    with pytest.raises(PluginTargetError):
        parse_target(bad)


def test_leading_dash_is_refused_even_though_it_looks_like_a_name() -> None:
    """Specifically pinned: `-s` would be consumed by the CLI as an option, not a plugin."""
    with pytest.raises(PluginTargetError):
        parse_target("-s")


# ---------- local directories -----------------------------------------------


def _fake_isdir(existing: set[str]):
    return lambda p: p in existing


def test_explicit_path_that_exists_is_a_local_source() -> None:
    t = parse_target("/opt/market", isdir=_fake_isdir({"/opt/market"}))
    assert t.local_path == "/opt/market" and t.source == "/opt/market"
    assert t.plugin is None and t.needs_marketplace_add is True


def test_explicit_path_that_is_absent_errors_instead_of_becoming_a_name() -> None:
    """`./typo` must say 'no such directory'. Retrying it as a plugin NAME would send the
    user to a network error that never mentions the typo."""
    with pytest.raises(PluginTargetError, match="no such directory"):
        parse_target("./typo", isdir=_fake_isdir(set()))


def test_an_existing_relative_dir_beats_the_owner_repo_reading() -> None:
    """`a/b` is legal as BOTH. The local checkout wins — it is the reading the user can
    verify, and the other would clone a stranger's repo of the same name."""
    t = parse_target("acme/kit", isdir=_fake_isdir({"acme/kit"}))
    assert t.local_path is not None, "an existing directory must not be read as owner/repo"


def test_owner_repo_still_works_when_no_such_dir_exists() -> None:
    t = parse_target("acme/kit", isdir=_fake_isdir(set()))
    assert t.local_path is None and t.source == "acme/kit"


def test_a_bare_word_is_a_name_even_if_a_dir_shares_it() -> None:
    """Otherwise the same command would mean different things per cwd. `./foo` is explicit."""
    t = parse_target("foo", isdir=_fake_isdir({"foo"}))
    assert t.plugin == "foo" and t.local_path is None


# ---------- classifying what a local dir IS ----------------------------------


def _reader(files: dict[str, dict]):
    return lambda p: files.get(p)


def test_a_marketplace_dir_is_registrable_directly() -> None:
    k = classify_local_dir(
        "/w/mk", read_json=_reader({"/w/mk/.claude-plugin/marketplace.json": {"name": "mk"}})
    )
    assert (k.kind, k.marketplace, k.marketplace_dir) == ("marketplace", "mk", "/w/mk")


def test_layout_c_repo_yields_both_names() -> None:
    """A repo carrying BOTH manifests (this plugin's own layout) is a marketplace AND the
    plugin, so one directory is enough to install by name."""
    k = classify_local_dir(
        "/w/p",
        read_json=_reader({
            "/w/p/.claude-plugin/marketplace.json": {"name": "mk"},
            "/w/p/.claude-plugin/plugin.json": {"name": "pg"},
        }),
    )
    assert k.kind == "marketplace" and k.plugin == "pg" and k.marketplace == "mk"


def test_plugin_inside_a_monorepo_registers_the_PARENT() -> None:
    k = classify_local_dir(
        "/w/mk/plugins/pg",
        read_json=_reader({
            "/w/mk/plugins/pg/.claude-plugin/plugin.json": {"name": "pg"},
            "/w/mk/plugins/.claude-plugin/marketplace.json": {"name": "mk"},
        }),
    )
    assert k.kind == "plugin-in-marketplace"
    assert k.plugin == "pg" and k.marketplace_dir == "/w/mk/plugins"


def test_a_lone_plugin_dir_is_reported_as_uninstallable_not_attempted() -> None:
    """`claude plugin install` takes a NAME from a registered marketplace and never a bare
    directory, so emitting a command here would fail with an unrelated 'plugin not found'."""
    k = classify_local_dir(
        "/w/pg", read_json=_reader({"/w/pg/.claude-plugin/plugin.json": {"name": "pg"}})
    )
    assert k.kind == "plugin-only" and k.marketplace_dir is None


def test_a_directory_with_neither_manifest_is_refused() -> None:
    with pytest.raises(PluginTargetError, match="neither a marketplace nor a plugin"):
        classify_local_dir("/w/random", read_json=_reader({}))
