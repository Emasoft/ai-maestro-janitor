"""The GitHub reply monitor — registry filtering, state location, and the register hook.

Ported into the janitor from the standalone `github-issues-monitor-on` skill. The
property under test throughout is the REGISTRY INTERSECTION: a notification is emitted
because THIS project opened the thread, never because GitHub thinks the account is
involved. On a shared `gh` identity the human owner's own open-source traffic carries the
same `reason: author` / `reason: comment` as the agent's, so a reason-only filter emits
the owner's unrelated activity — measured 5-of-6 on the account this was written for.

Real modules, real files, no mocks beyond a fake `gh` binary on PATH: the poller shells
out to `gh api`, so a stub executable is the honest seam. Every test pins
`GH_ISSUES_MONITOR_STATE_DIR` at a tmp dir, so none of them can touch a real registry.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import importlib.util
import io
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_POLL_SRC = _PROJECT_ROOT / "scripts" / "gh_issues_monitor" / "gh_notify_poll.py"
_HOOK_SRC = _PROJECT_ROOT / "scripts" / "gh_issues_monitor" / "gh_register_hook.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def poll(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The poller module with its state dir pinned inside tmp_path."""
    monkeypatch.setenv("GH_ISSUES_MONITOR_STATE_DIR", str(tmp_path / "state"))
    return _load(_POLL_SRC, "gh_notify_poll_ut")


def _fake_gh(bin_dir: Path, payload: object) -> None:
    """Put a `gh` on PATH that prints `payload` as JSON for any argv.

    A stub binary rather than a monkeypatched function: `gh_api` builds an argv and runs
    a subprocess, and that argv (the `-H Accept:` header, the path) is part of what the
    poller gets right or wrong."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "gh"
    script.write_text(
        "#!/usr/bin/env python3\nimport json,sys\nprint(json.dumps(%r))\n" % (payload,),
        encoding="utf-8",
    )
    script.chmod(0o755)


def _notification(*, tid: str, repo: str, number: int, reason: str = "comment", title: str = "T") -> dict:
    return {
        "id": tid,
        # Dynamic, NOT a literal date: the poller prunes `seen` entries older than
        # SEEN_TTL_DAYS, so a frozen timestamp here is a time-bomb — the baseline test
        # passed for a month and started failing the day the hardcoded date crossed the
        # TTL (found 2026-09-01, date was 2026-07-31, TTL 30 days).
        "updated_at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "reason": reason,
        "repository": {"full_name": repo},
        "subject": {
            "title": title,
            "url": f"https://api.github.com/repos/{repo}/issues/{number}",
            "latest_comment_url": f"https://api.github.com/repos/{repo}/issues/{number}",
        },
    }


# ---------- thread identity ----------


def test_parse_thread_ref_accepts_browser_api_and_slug_forms(poll) -> None:
    """One registry key per thread however it was written down — a hook registers a
    browser URL, a notification carries an API URL, and a human types `owner/repo#12`."""
    for text in (
        "https://github.com/o/r/issues/12",
        "https://api.github.com/repos/o/r/issues/12",
        "o/r#12",
    ):
        assert poll.parse_thread_ref(text) == ("o/r", 12, "issues"), text


def test_registry_key_is_case_insensitive_on_the_repo(poll) -> None:
    """GitHub treats `Owner/Repo` and `owner/repo` as the same repo; a case-sensitive key
    would register the same thread twice and then fail to match the notification."""
    assert poll.key("Owner/Repo", 5) == poll.key("owner/repo", 5)


def test_unparseable_ref_is_reported_not_silently_dropped(poll, capsys) -> None:
    rc = poll.do_register(["not a thread"], "manual")
    assert rc == 1
    assert "UNPARSEABLE" in capsys.readouterr().err


# ---------- the registry intersection: the whole point ----------


def test_a_registered_thread_emits(poll, tmp_path, monkeypatch, capsys) -> None:
    poll.do_register(["https://github.com/o/r/issues/12"], "opened-here")
    capsys.readouterr()
    _fake_gh(tmp_path / "bin", [_notification(tid="1", repo="o/r", number=12, title="Hello")])
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")

    rc = poll.do_poll(_args(poll))
    out = capsys.readouterr().out
    assert rc == 0
    assert "[gh] o/r#12 Hello" in out
    assert "[opened-here]" in out
    assert "https://github.com/o/r/issues/12" in out


def test_an_unregistered_thread_is_silent_even_with_an_involving_reason(
    poll, tmp_path, monkeypatch, capsys
) -> None:
    """THE test. `reason: author` on a repo this project never opened anything on is the
    owner's own open-source traffic. A reason-only filter emits it; the registry
    intersection must not."""
    poll.do_register(["https://github.com/o/mine/issues/1"], "opened-here")
    capsys.readouterr()
    _fake_gh(
        tmp_path / "bin",
        [_notification(tid="9", repo="pytorch/pytorch", number=4242, reason="author", title="Not mine")],
    )
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")

    poll.do_poll(_args(poll))
    assert capsys.readouterr().out == ""


def test_a_registered_thread_with_an_uninvolving_reason_is_silent(
    poll, tmp_path, monkeypatch, capsys
) -> None:
    """The registry is necessary, not sufficient: `reason: ci_activity` on a watched
    thread is a build, not a reply."""
    poll.do_register(["https://github.com/o/r/issues/12"], "opened-here")
    capsys.readouterr()
    _fake_gh(
        tmp_path / "bin",
        [_notification(tid="2", repo="o/r", number=12, reason="ci_activity")],
    )
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")

    poll.do_poll(_args(poll))
    assert capsys.readouterr().out == ""


def test_baseline_emits_nothing_and_suppresses_the_backlog(poll, tmp_path, monkeypatch, capsys) -> None:
    """Enabling the monitor must not dump every already-read notification into context.
    Baseline records the ids, emits nothing, and the NEXT poll stays quiet for them."""
    poll.do_register(["https://github.com/o/r/issues/12"], "opened-here")
    capsys.readouterr()
    _fake_gh(tmp_path / "bin", [_notification(tid="3", repo="o/r", number=12)])
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")

    poll.do_poll(_args(poll, baseline=True))
    first = capsys.readouterr().out
    assert "[gh]" not in first
    assert "BASELINED" in first

    poll.do_poll(_args(poll))
    assert "[gh]" not in capsys.readouterr().out, "a baselined thread must not replay"


def test_a_degraded_gh_says_so_once_then_stays_quiet(poll, tmp_path, monkeypatch, capsys) -> None:
    """Silence is not success: a broken `gh` must surface ONCE (so nobody believes the
    monitor is live) and then stop, so it cannot spam a line on every tick."""
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))  # no gh at all
    (tmp_path / "empty-bin").mkdir()

    poll.do_poll(_args(poll))
    assert "MONITOR DEGRADED" in capsys.readouterr().out
    poll.do_poll(_args(poll))
    assert capsys.readouterr().out == "", "the same failure must not repeat every tick"


# ---------- state location + migration ----------


def test_state_dir_lives_inside_the_project(tmp_path, monkeypatch) -> None:
    """OWNER DIRECTIVE 2026-08-02: "store the tracking data locally". Slug-keyed subdirs of
    a machine-global dir gave per-project SEPARATION but not LOCALITY — keyed by absolute
    path, so moving a checkout orphaned its registry.

    `.janitor/gh-issues-monitor/`, NOT `.janitor/state/`: the registry is a RECORD OF WORK
    filled by the PostToolUse hook as `gh` commands happen, and `.janitor/state/` is
    documented as regeneratable and safe to delete. Nothing can rebuild a lost registry."""
    monkeypatch.delenv("GH_ISSUES_MONITOR_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "proj"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    mod = _load(_POLL_SRC, "gh_notify_poll_loc_ut")
    resolved = Path(mod.state_dir())
    assert resolved == proj / ".janitor" / "gh-issues-monitor"
    assert "plugins/data" not in resolved.as_posix(), "must no longer live in the global DATA dir"
    assert ".janitor/state" not in resolved.as_posix(), "must stay out of the disposable zone"


def test_the_standalone_skills_registry_is_migrated_by_copy(tmp_path, monkeypatch) -> None:
    """A host running the pre-port standalone skill has a registry at the oldest path. It is
    COPIED, not moved: losing the record of which threads a project opened cannot be
    undone by re-running anything, and a rollback must still find it."""
    monkeypatch.delenv("GH_ISSUES_MONITOR_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "proj"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    mod = _load(_POLL_SRC, "gh_notify_poll_mig_ut")

    legacy = mod._legacy_standalone_dir(mod.project_slug(str(proj)))
    legacy.mkdir(parents=True)
    (legacy / "registry.json").write_text(json.dumps({"o/r#1": {"repo": "o/r"}}), encoding="utf-8")

    resolved = Path(mod.state_dir())
    assert json.loads((resolved / "registry.json").read_text())["o/r#1"]["repo"] == "o/r"
    assert (legacy / "registry.json").exists(), "the legacy copy must survive a rollback"


def test_the_data_dir_registry_is_migrated_by_copy(tmp_path, monkeypatch) -> None:
    """The SECOND legacy location — where the port kept it before it moved into the project.
    Every host that ran the port has data here, so skipping this hop would silently drop
    every thread registered since the port."""
    monkeypatch.delenv("GH_ISSUES_MONITOR_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "proj"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    mod = _load(_POLL_SRC, "gh_notify_poll_mig3_ut")

    legacy = mod._legacy_data_dir(mod.project_slug(str(proj)))
    legacy.mkdir(parents=True)
    (legacy / "registry.json").write_text(json.dumps({"o/r#5": {"repo": "o/r"}}), encoding="utf-8")

    resolved = Path(mod.state_dir())
    assert json.loads((resolved / "registry.json").read_text())["o/r#5"]["repo"] == "o/r"
    assert (legacy / "registry.json").exists(), "copy, never move"


def test_the_data_dir_wins_over_the_older_standalone_dir(tmp_path, monkeypatch) -> None:
    """With BOTH legacy locations present, the NEWER one is authoritative — the standalone
    dir is a pre-port fossil and must not clobber threads registered since."""
    monkeypatch.delenv("GH_ISSUES_MONITOR_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "proj"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    mod = _load(_POLL_SRC, "gh_notify_poll_mig4_ut")

    slug = mod.project_slug(str(proj))
    for d, payload in ((mod._legacy_standalone_dir(slug), {"old/one#1": {}}),
                       (mod._legacy_data_dir(slug), {"new/one#2": {}})):
        d.mkdir(parents=True)
        (d / "registry.json").write_text(json.dumps(payload), encoding="utf-8")

    assert json.loads((Path(mod.state_dir()) / "registry.json").read_text()) == {"new/one#2": {}}


def test_migration_does_not_overwrite_an_existing_registry(tmp_path, monkeypatch) -> None:
    """Once the LOCAL registry exists it is authoritative — a stale legacy dir must never
    clobber threads registered since the move."""
    monkeypatch.delenv("GH_ISSUES_MONITOR_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    proj = tmp_path / "proj"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(proj))
    mod = _load(_POLL_SRC, "gh_notify_poll_mig2_ut")

    legacy = mod._legacy_data_dir(mod.project_slug(str(proj)))
    legacy.mkdir(parents=True)
    (legacy / "registry.json").write_text(json.dumps({"old/one#1": {}}), encoding="utf-8")
    target = proj / ".janitor" / "gh-issues-monitor"
    target.mkdir(parents=True)
    (target / "registry.json").write_text(json.dumps({"new/one#2": {}}), encoding="utf-8")

    assert json.loads((Path(mod.state_dir()) / "registry.json").read_text()) == {"new/one#2": {}}


def test_two_projects_keep_disjoint_registries(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("GH_ISSUES_MONITOR_STATE_DIR", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))
    mod = _load(_POLL_SRC, "gh_notify_poll_two_ut")
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "a"))
    first = mod.state_dir()
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "b"))
    assert mod.state_dir() != first


# ---------- the auto-register hook ----------


def _run_hook(event: dict, env_extra: dict[str, str]) -> subprocess.CompletedProcess[str]:
    env = dict(os.environ)
    env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(_HOOK_SRC)],
        input=json.dumps(event), capture_output=True, text=True, timeout=60, env=env,
    )


def _bash_event(command: str, response: str, cwd: str) -> dict:
    return {"tool_input": {"command": command}, "tool_response": response, "cwd": cwd}


def test_hook_registers_a_created_thread(tmp_path) -> None:
    """`gh issue create` prints the new thread's URL; the hook reads it out of the RESPONSE
    (the command line cannot carry a number that does not exist yet)."""
    state = tmp_path / "state"
    proc = _run_hook(
        _bash_event("gh issue create --title x", "https://github.com/o/r/issues/7", str(tmp_path)),
        {"GH_ISSUES_MONITOR_STATE_DIR": str(state)},
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads((state / "registry.json").read_text())["o/r#7"]["note"] == "opened-here"


def test_hook_ignores_reading_commands(tmp_path) -> None:
    """`gh issue list` / `gh issue view` also print URLs. Registering those would watch
    every thread the agent merely READ — the opposite of "threads this project opened"."""
    state = tmp_path / "state"
    for command in ("gh issue list", "gh issue view 7", "gh pr view 3 --comments"):
        proc = _run_hook(
            _bash_event(command, "https://github.com/o/r/issues/7", str(tmp_path)),
            {"GH_ISSUES_MONITOR_STATE_DIR": str(state)},
        )
        assert proc.returncode == 0
        assert not (state / "registry.json").exists(), f"{command!r} must not register"


def test_hook_never_writes_stdout_or_fails_the_tool(tmp_path) -> None:
    """Contract: a monitor that breaks `gh` is worse than one that misses a registration.
    Garbage in, silent success out."""
    for payload in ("not json at all", json.dumps([1, 2, 3]), json.dumps({"tool_input": None})):
        proc = subprocess.run(
            [sys.executable, str(_HOOK_SRC)],
            input=payload, capture_output=True, text=True, timeout=60,
            env={**os.environ, "GH_ISSUES_MONITOR_STATE_DIR": str(tmp_path / "s")},
        )
        assert proc.returncode == 0, payload
        assert proc.stdout == "", payload


def test_hook_is_declared_in_the_plugin_not_in_user_settings() -> None:
    """THE port decision, pinned. The standalone skill installed this hook into
    `~/.claude/settings.json`, which baked an ABSOLUTE path to the script — and inside a
    plugin that path is the EPHEMERAL versioned cache dir, so the hook would have died
    silently at the next janitor update when the version dir is GC'd.

    As a plugin hook, `${CLAUDE_PLUGIN_ROOT}` is resolved at load time, so it always points
    at the running version and uninstalling removes it."""
    hooks = json.loads((_PROJECT_ROOT / "hooks" / "hooks.json").read_text())["hooks"]
    entries = [
        h
        for entry in hooks["PostToolUse"]
        if entry.get("matcher") == "Bash"
        for h in entry.get("hooks", [])
    ]
    commands = [h.get("command", "") for h in entries]
    assert any("gh_register_hook.py" in c for c in commands), commands
    for c in commands:
        if "gh_register_hook.py" in c:
            assert "${CLAUDE_PLUGIN_ROOT}" in c, "a versioned absolute path would die on update"


def _args(poll_mod, *, baseline: bool = False):
    """The Namespace `do_poll` expects, parsed by the MODULE'S OWN parser.

    Built by running `main()` up to the point it would dispatch, rather than by
    hand-rolling a lookalike: a hand-rolled Namespace keeps passing after the real CLI
    grows or renames an option that `do_poll` then reads, so the tests would go on
    proving something the shipped script no longer does."""
    argv = ["--baseline"] if baseline else []
    return _real_parser(poll_mod).parse_args(argv)


def _real_parser(poll_mod):
    """The parser `main()` builds, captured at the moment it parses.

    Hooking `parse_args` rather than subclassing `ArgumentParser`: argparse constructs
    parsers internally (for argument groups), so a patched CLASS is re-entered by its own
    `__init__` and recurses to the stack limit. `parse_args` is called exactly once, by
    the code under test, on the object we want."""
    import argparse

    captured: list[argparse.ArgumentParser] = []
    original = argparse.ArgumentParser.parse_args

    def _spy(self, *a, **k):
        captured.append(self)
        return original(self, *a, **k)

    argparse.ArgumentParser.parse_args = _spy  # type: ignore[method-assign]
    old_argv = sys.argv
    sys.argv = ["gh_notify_poll.py", "--state-dir"]  # the cheapest terminating mode
    try:
        # `--state-dir` PRINTS the path; swallow it, or this helper injects a line into
        # the very stdout the caller is about to assert is empty.
        with contextlib.redirect_stdout(io.StringIO()):
            poll_mod.main()
    finally:
        sys.argv = old_argv
        argparse.ArgumentParser.parse_args = original  # type: ignore[method-assign]
    assert captured, "main() must parse arguments"
    return captured[0]
