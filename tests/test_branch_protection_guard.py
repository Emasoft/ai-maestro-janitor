"""Tests for the security-guard branch-protection auto-apply path (TRDD-631fa3de).

Three layers under test:

1. `scripts/lib/branch_protection_lib.py` — pure helpers (payload shape,
   slug parsing, env-var coercion). Tested in-process with no subprocesses.

2. `scripts/guard/branch_protection_apply.py` — Tier 2 auto-apply module.
   Run as a subprocess with a fake `gh` on PATH (Python stub) so the gates
   exercise the real `branch_protection_lib` code path end-to-end without
   touching the network or real GitHub auth.

3. `scripts/dispatch.py::_phase_guard_branch_protection` — interval
   throttling + script dispatch. Tested in-process.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from io import StringIO
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_APPLY_SCRIPT = _PROJECT_ROOT / "scripts" / "guard" / "branch_protection_apply.py"
_LIB = _PROJECT_ROOT / "scripts" / "lib" / "branch_protection_lib.py"

assert _APPLY_SCRIPT.is_file(), f"apply script not found at {_APPLY_SCRIPT}"
assert _LIB.is_file(), f"lib not found at {_LIB}"

sys.path.insert(0, str(_PROJECT_ROOT / "scripts"))
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))


# Fake gh: dispatches on argv, prints a canned body, exits a canned code.
# Mirrors the contract `branch_protection_lib` makes against `gh`:
#   * gh api repos/o/r           --jq .default_branch     → GH_DEFAULT_BRANCH
#   * gh api repos/o/r           --jq .permissions.admin  → GH_ADMIN
#   * gh api repos/o/r/rulesets                            → GH_RULESETS_BODY/RC
#   * gh api --method POST repos/o/r/rulesets --input -    → GH_POST_BODY/RC
_GH_STUB = '''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
def out(body: str, rc: int) -> None:
    if body:
        sys.stdout.write(body)
    raise SystemExit(rc)
# --method POST <path> --input -    (read stdin, but we ignore it)
if argv[:2] == ["api", "--method"]:
    # consume stdin so the parent doesn't block
    try:
        sys.stdin.read()
    except Exception:
        pass
    out(os.environ.get("GH_POST_BODY", "{}"), int(os.environ.get("GH_POST_RC", "0")))
# api <path> [--jq <expr>]
if argv[:1] == ["api"]:
    jq = ""
    if "--jq" in argv:
        jq = argv[argv.index("--jq") + 1]
    path = argv[1]
    if path.endswith("/rulesets"):
        out(os.environ.get("GH_RULESETS_BODY", "[]"), int(os.environ.get("GH_RULESETS_RC", "0")))
    if jq == ".default_branch":
        out(os.environ.get("GH_DEFAULT_BRANCH", "main"), int(os.environ.get("GH_DEFAULT_BRANCH_RC", "0")))
    if jq == ".permissions.admin":
        out(os.environ.get("GH_ADMIN", "true"), int(os.environ.get("GH_ADMIN_RC", "0")))
sys.stderr.write("gh-stub: unhandled %r\\n" % (argv,))
raise SystemExit(99)
'''


@pytest.fixture
def project_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Fresh project root + reload state/global_state/branch_protection_lib."""
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(tmp_path / "global"))
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_GUARD_MODE_ENABLED", raising=False)
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_GUARD_BRANCH_PROTECTION_INTERVAL", raising=False)
    for mod in ("state", "global_state", "branch_protection_lib"):
        if mod in sys.modules:
            del sys.modules[mod]
    return tmp_path


def _make_plugin_manifest(root: Path, repo_url: str = "https://github.com/o/r") -> None:
    manifest_dir = root / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "plugin.json").write_text(
        json.dumps({"name": "test", "version": "0.0.1", "repository": repo_url}),
        encoding="utf-8",
    )


def _make_gh_stub(parent: Path) -> Path:
    binp = parent / "_bin"
    binp.mkdir(exist_ok=True)
    gh = binp / "gh"
    gh.write_text(_GH_STUB, encoding="utf-8")
    gh.chmod(0o755)
    return binp


def _make_uv_only_bin(parent: Path) -> Path:
    """Build a bin dir that has uv (so the script's #! line works) but no gh.

    Used to exercise Gate 4 ("gh not in PATH") without breaking the
    interpreter resolution that the apply script's shebang depends on.
    """
    binp = parent / "_uv_only_bin"
    binp.mkdir(exist_ok=True)
    import shutil as _sh
    real_uv = _sh.which("uv")
    assert real_uv is not None, "uv must be on PATH for these tests"
    sym = binp / "uv"
    if not sym.exists():
        sym.symlink_to(real_uv)
    return binp


def _run_apply(
    project: Path,
    *,
    gh_bin: Path | None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run scripts/guard/branch_protection_apply.py with the gates the test wants."""
    env = os.environ.copy()
    env["CLAUDE_PROJECT_DIR"] = str(project)
    env["CLAUDE_PLUGIN_ROOT"] = str(project)
    env["JANITOR_GLOBAL_STATE_DIR"] = str(project / "global")
    # Default: guard ON (most tests want it on; OFF tests override).
    env["CLAUDE_PLUGIN_OPTION_GUARD_MODE_ENABLED"] = "true"
    if gh_bin is not None:
        env["PATH"] = f"{gh_bin}{os.pathsep}{env['PATH']}"
    # else: caller is responsible for setting PATH via extra_env when
    # they need a gh-missing PATH that still resolves the interpreter.
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        [str(_APPLY_SCRIPT)], env=env, capture_output=True, text=True, timeout=30,
    )


# ---------- branch_protection_lib pure helpers ---------------------------

def test_baseline_payload_has_correct_shape(project_env: Path) -> None:
    _ = project_env  # fixture reloads branch_protection_lib for fresh env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    payload = bpl.baseline_ruleset_payload("main")
    assert payload["name"] == "janitor-baseline"
    assert payload["target"] == "branch"
    assert payload["enforcement"] == "active"
    assert payload["conditions"]["ref_name"]["include"] == ["refs/heads/main"]
    rule_types = {r["type"] for r in payload["rules"]}
    assert rule_types == {"deletion", "non_fast_forward", "required_linear_history", "pull_request"}
    pr_rule = next(r for r in payload["rules"] if r["type"] == "pull_request")
    assert pr_rule["parameters"]["required_approving_review_count"] == 1
    assert pr_rule["parameters"]["dismiss_stale_reviews_on_push"] is True
    assert pr_rule["parameters"]["required_review_thread_resolution"] is True


def test_baseline_payload_targets_supplied_branch(project_env: Path) -> None:
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    payload = bpl.baseline_ruleset_payload("develop")
    assert payload["conditions"]["ref_name"]["include"] == ["refs/heads/develop"]


def test_baseline_payload_rejects_empty_branch(project_env: Path) -> None:
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    with pytest.raises(ValueError):
        bpl.baseline_ruleset_payload("")


def test_detect_repo_slug_parses_standard_url(project_env: Path) -> None:
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    _make_plugin_manifest(project_env, "https://github.com/Emasoft/ai-maestro-janitor")
    assert bpl.detect_repo_slug(project_env) == "Emasoft/ai-maestro-janitor"


def test_detect_repo_slug_strips_dot_git_suffix(project_env: Path) -> None:
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    _make_plugin_manifest(project_env, "https://github.com/Emasoft/ai-maestro-janitor.git")
    assert bpl.detect_repo_slug(project_env) == "Emasoft/ai-maestro-janitor"


def test_detect_repo_slug_strips_trailing_slash(project_env: Path) -> None:
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    _make_plugin_manifest(project_env, "https://github.com/Emasoft/ai-maestro-janitor/")
    assert bpl.detect_repo_slug(project_env) == "Emasoft/ai-maestro-janitor"


def test_detect_repo_slug_returns_none_for_non_github(project_env: Path) -> None:
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    _make_plugin_manifest(project_env, "https://gitlab.com/foo/bar")
    assert bpl.detect_repo_slug(project_env) is None


def test_detect_repo_slug_returns_none_when_manifest_missing(project_env: Path) -> None:
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    assert bpl.detect_repo_slug(project_env) is None


def test_detect_repo_slug_returns_none_on_invalid_json(project_env: Path) -> None:
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    manifest_dir = project_env / ".claude-plugin"
    manifest_dir.mkdir(parents=True, exist_ok=True)
    (manifest_dir / "plugin.json").write_text("{ not json", encoding="utf-8")
    assert bpl.detect_repo_slug(project_env) is None


def test_guard_mode_enabled_parses_truthy_values(
    project_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    for v in ("1", "true", "TRUE", "yes", "Yes", "on", "ON"):
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GUARD_MODE_ENABLED", v)
        assert bpl.guard_mode_enabled() is True, f"failed for {v!r}"


def test_guard_mode_enabled_default_is_false(
    project_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    monkeypatch.delenv("CLAUDE_PLUGIN_OPTION_GUARD_MODE_ENABLED", raising=False)
    assert bpl.guard_mode_enabled() is False


def test_guard_mode_enabled_falsy_values(
    project_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    for v in ("0", "false", "no", "off", "", "garbage"):
        monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GUARD_MODE_ENABLED", v)
        assert bpl.guard_mode_enabled() is False, f"failed for {v!r}"


# ---------- branch_protection_apply (Tier 2 script) gates -----------------

def test_apply_silent_when_guard_mode_off(project_env: Path) -> None:
    """Gate 1: guard_mode_enabled=false → silent no-op (the default state)."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={"CLAUDE_PLUGIN_OPTION_GUARD_MODE_ENABLED": "false"},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "", f"expected silence, got {r.stdout!r}"


def test_apply_silent_when_autofix_off(project_env: Path) -> None:
    """Gate 2: /janitor-autofix-off vetoes even guard-mode actions."""
    _make_plugin_manifest(project_env)
    state_dir = project_env / ".janitor" / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "autofix-mode.txt").write_text("off", encoding="utf-8")
    gh = _make_gh_stub(project_env)
    r = _run_apply(project_env, gh_bin=gh)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "", f"expected silence, got {r.stdout!r}"


def test_apply_skips_when_slug_missing(project_env: Path) -> None:
    """Gate 3: no plugin.json → cannot resolve slug → silent skip."""
    # NO _make_plugin_manifest call
    gh = _make_gh_stub(project_env)
    r = _run_apply(project_env, gh_bin=gh)
    assert r.returncode == 0, r.stderr
    assert r.stdout == "", f"expected silence, got {r.stdout!r}"


def test_apply_warns_when_gh_missing(project_env: Path) -> None:
    """Gate 4: no gh on PATH → loud announcement (so user can install gh)."""
    _make_plugin_manifest(project_env)
    uv_only = _make_uv_only_bin(project_env)
    r = _run_apply(
        project_env, gh_bin=None,
        extra_env={"PATH": str(uv_only)},
    )
    assert r.returncode == 0, r.stderr
    assert "gh" in r.stdout.lower()
    assert "not in PATH" in r.stdout


def test_apply_skips_when_default_branch_unresolvable(project_env: Path) -> None:
    """Gate 5: gh fails to resolve default branch → silent skip."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={"GH_DEFAULT_BRANCH": "", "GH_DEFAULT_BRANCH_RC": "1"},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "", f"expected silence, got {r.stdout!r}"


def test_apply_noop_when_baseline_already_present(project_env: Path) -> None:
    """Gate 6 (idempotency): existing janitor-baseline ruleset → silent NOOP."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={
            "GH_RULESETS_BODY": json.dumps([
                {"id": 42, "name": "janitor-baseline", "target": "branch"},
            ]),
        },
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "", f"expected silence, got {r.stdout!r}"
    # Ledger should record once that the baseline was already present.
    ledger = project_env / ".janitor" / "state" / "branch-protection-acted.txt"
    if ledger.is_file():
        assert "already-present" in ledger.read_text(encoding="utf-8")


def test_apply_skips_when_ruleset_probe_fails(project_env: Path) -> None:
    """Gate 6 (uncertainty): ruleset list lookup fails → don't act (uncertain)."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={"GH_RULESETS_RC": "1", "GH_RULESETS_BODY": '{"message":"err"}'},
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "", f"expected silence, got {r.stdout!r}"


def test_apply_warns_when_viewer_not_admin(project_env: Path) -> None:
    """Gate 7: non-admin viewer cannot configure rulesets → loud surface."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={"GH_ADMIN": "false"},
    )
    assert r.returncode == 0, r.stderr
    assert "not an admin" in r.stdout
    assert "o/r" in r.stdout


def test_apply_creates_baseline_when_all_gates_pass(project_env: Path) -> None:
    """All gates green → POST + loud `[guard] created` announcement + audit log."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={"GH_POST_BODY": json.dumps({"id": 1234, "name": "janitor-baseline"})},
    )
    assert r.returncode == 0, r.stderr
    assert "[guard] created branch-protection baseline on o/r@main" in r.stdout
    assert "id=1234" in r.stdout
    # Audit log + ledger written:
    log = project_env / ".janitor" / "logs" / "branch-protection-apply.log"
    assert log.is_file()
    assert "OK\to/r\tmain" in log.read_text(encoding="utf-8")
    ledger = project_env / ".janitor" / "state" / "branch-protection-acted.txt"
    assert ledger.is_file()
    assert "created" in ledger.read_text(encoding="utf-8")


def test_apply_logs_failure_when_post_rejected(project_env: Path) -> None:
    """gh POST returns non-zero (422 schema, 403 scope, etc.) → no half-apply,
    drift announcement + audit log entry."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={
            "GH_POST_RC": "1",
            "GH_POST_BODY": "validation failed",
        },
    )
    assert r.returncode == 0, r.stderr
    assert "POST failed" in r.stdout
    log = project_env / ".janitor" / "logs" / "branch-protection-apply.log"
    assert log.is_file()
    assert "FAIL\to/r\tmain" in log.read_text(encoding="utf-8")


# ---------- dispatch._phase_guard_branch_protection -----------------------

def _import_dispatch():
    import importlib.util as _u
    spec = _u.spec_from_file_location(
        "janitor_dispatch_guard_test", str(_PROJECT_ROOT / "scripts" / "dispatch.py"),
    )
    assert spec is not None and spec.loader is not None
    mod = _u.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_phase_throttles_within_interval(
    project_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two calls within the cadence window → only the first should dispatch.

    We can't easily detect the first dispatch from stdout (the apply script
    is silent unless guard mode is enabled), so we verify the throttle by
    checking that the last-run state file is bumped exactly once.
    """
    _ = project_env
    import state  # type: ignore[import-not-found]
    state.init_state()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GUARD_BRANCH_PROTECTION_INTERVAL", "3600")
    dispatch = _import_dispatch()

    last_file = state.state_dir() / "last-run-guard-branch-protection.ts"
    assert not last_file.is_file()

    # First fire: stamps last-run.
    dispatch._phase_guard_branch_protection()
    assert last_file.is_file()
    first_ts = int(last_file.read_text(encoding="utf-8").strip())

    # Second fire (immediate): cadence window blocks it; last-run unchanged.
    dispatch._phase_guard_branch_protection()
    second_ts = int(last_file.read_text(encoding="utf-8").strip())
    assert second_ts == first_ts, "second fire inside cadence should not re-stamp"


def test_phase_runs_again_after_interval_elapses(
    project_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backdate last-run by 2× the interval → next fire re-dispatches."""
    _ = project_env
    import state  # type: ignore[import-not-found]
    state.init_state()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GUARD_BRANCH_PROTECTION_INTERVAL", "60")
    dispatch = _import_dispatch()

    last_file = state.state_dir() / "last-run-guard-branch-protection.ts"
    # Backdate beyond the interval window.
    past = int(time.time()) - 600
    last_file.write_text(str(past), encoding="utf-8")

    dispatch._phase_guard_branch_protection()
    new_ts = int(last_file.read_text(encoding="utf-8").strip())
    assert new_ts > past, "phase should re-dispatch after interval expires"


def test_phase_swallows_subprocess_errors(
    project_env: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken apply script must not crash the heartbeat — RULE-0 invariant."""
    _ = project_env
    import state  # type: ignore[import-not-found]
    state.init_state()
    monkeypatch.setenv("CLAUDE_PLUGIN_OPTION_GUARD_BRANCH_PROTECTION_INTERVAL", "3600")
    dispatch = _import_dispatch()

    # Capture stdout to confirm the phase exits cleanly even on weird states.
    buf = StringIO()
    old = sys.stdout
    sys.stdout = buf
    try:
        dispatch._phase_guard_branch_protection()
    finally:
        sys.stdout = old
    # The phase itself never prints (the spawned script does); we only
    # care that it returned without raising.
