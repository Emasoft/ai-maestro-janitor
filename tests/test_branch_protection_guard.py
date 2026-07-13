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
#   * gh api repos/o/r                  --jq .default_branch     → GH_DEFAULT_BRANCH
#   * gh api repos/o/r                  --jq .permissions.admin  → GH_ADMIN
#   * gh api repos/o/r/rulesets                                  → GH_RULESETS_BODY/RC
#   * gh api --method POST   repos/o/r/rulesets       --input -  → GH_POST_BODY/RC
#   * gh api --method PUT    repos/o/r/rulesets/<id>  --input -  → GH_PUT_BODY/RC
#   * gh api --method DELETE repos/o/r/rulesets/<id>            → GH_DELETE_BODY/RC
_GH_STUB = '''#!/usr/bin/env python3
import json, os, sys
argv = sys.argv[1:]
def out(body: str, rc: int, err: str = "") -> None:
    if body:
        sys.stdout.write(body)
    if err:
        sys.stderr.write(err)
    raise SystemExit(rc)
# --method <VERB> <path> [--input -]   (read stdin when present, but ignore it)
# On failure real gh writes the API error to STDERR; mirror that via the
# GH_<VERB>_STDERR vars so the lib's stderr-trimming path is exercised.
if argv[:2] == ["api", "--method"]:
    verb = argv[2]
    path = argv[3] if len(argv) > 3 else ""
    if "--input" in argv:
        try:
            sys.stdin.read()
        except Exception:
            pass
    # METHOD->PATH semantics (mirror real gh/GitHub routing so a mis-routed call
    # is caught, not silently accepted): POST targets the COLLECTION
    # (.../rulesets, create), PUT/DELETE target a RESOURCE (.../rulesets/<id>,
    # update/delete). A verb sent to the wrong shape is a 404/405 on real GitHub.
    is_collection = path.endswith("/rulesets")
    is_resource = "/rulesets/" in path
    if verb == "POST" and is_collection:
        out(os.environ.get("GH_POST_BODY", "{}"), int(os.environ.get("GH_POST_RC", "0")), os.environ.get("GH_POST_STDERR", ""))
    if verb == "PUT" and is_resource:  # ruleset UPDATE is PUT (not PATCH) on real GitHub — janitor#14
        out(os.environ.get("GH_PUT_BODY", "{}"), int(os.environ.get("GH_PUT_RC", "0")), os.environ.get("GH_PUT_STDERR", ""))
    if verb == "DELETE" and is_resource:
        out(os.environ.get("GH_DELETE_BODY", "{}"), int(os.environ.get("GH_DELETE_RC", "0")), os.environ.get("GH_DELETE_STDERR", ""))
    sys.stderr.write("gh-stub: %s to %r is not a valid ruleset route\\n" % (verb, path))
    raise SystemExit(98)
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

def test_baseline_payloads_return_exactly_three_named_rulesets(project_env: Path) -> None:
    """The ratified baseline is exactly three rulesets, in order (branch pair + tag protect)."""
    _ = project_env  # fixture reloads branch_protection_lib for fresh env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    payloads = bpl.baseline_ruleset_payloads("main")
    assert isinstance(payloads, list)
    assert len(payloads) == 3
    names = [p["name"] for p in payloads]
    assert names == ["baseline-history-protect", "baseline-pr-and-checks", "baseline-tag-protect"]
    assert bpl.HISTORY_RULESET_NAME == "baseline-history-protect"
    assert bpl.PR_CHECKS_RULESET_NAME == "baseline-pr-and-checks"
    assert bpl.TAG_PROTECT_RULESET_NAME == "baseline-tag-protect"
    assert bpl.LEGACY_RULESET_NAME == "janitor-baseline"  # back-compat alias
    # The shared orphan-delete UNION (janitor#14 / maintainer#7) — every
    # pre-ratification name in BOTH plugins' lineage, so a shared repo converges.
    assert set(bpl.LEGACY_RULESET_NAMES) == {
        "janitor-baseline", "main-hardening", "main-ci-gate",
        "default-branch-ruleset", "default-branch-no-force-no-delete",
        "default-branch-required-checks",
    }


def test_pr_checks_omits_the_checks_rule_when_no_contexts(project_env: Path) -> None:
    """REGRESSION (live 422): with NO detected CI contexts, baseline-pr-and-checks must ship
    ONLY its pull_request rule — the required_status_checks rule is OMITTED.

    GitHub REJECTS a required_status_checks rule whose contexts array is empty with
    `422 Validation Failed`, and that 422 fails the WHOLE ruleset write — taking the
    pull_request gate down with it. The old shape emitted the empty array and claimed it
    "gates on no specific contexts"; that claim was false. It hid because contexts ARE
    detected for the one repo whose checkout is the cwd, so only that repo's apply
    succeeded — 11 of 12 fleet repos 422'd.
    """
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]

    pr = bpl.baseline_ruleset_payloads("main", [])[1]
    assert pr["name"] == "baseline-pr-and-checks"
    rule_types = [r["type"] for r in pr["rules"]]
    assert rule_types == ["pull_request"], f"empty contexts must omit the checks rule, got {rule_types}"
    # The PR-review gate — the part that actually matters — survives everywhere.
    assert pr["rules"][0]["parameters"]["required_approving_review_count"] == 1
    # None behaves the same as [].
    assert [r["type"] for r in bpl.baseline_ruleset_payloads("main", None)[1]["rules"]] == ["pull_request"]


def test_pr_checks_includes_the_checks_rule_when_contexts_exist(project_env: Path) -> None:
    """The fix must not go too far: with real detected contexts the required_status_checks
    rule IS present and carries them (this is the path that already worked)."""
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]

    ctx = [{"context": "test"}, {"context": "lint"}]
    pr = bpl.baseline_ruleset_payloads("main", ctx)[1]
    rule_types = [r["type"] for r in pr["rules"]]
    assert rule_types == ["pull_request", "required_status_checks"]
    checks_rule = pr["rules"][1]
    assert checks_rule["parameters"]["required_status_checks"] == ctx
    assert checks_rule["parameters"]["strict_required_status_checks_policy"] is True


def test_history_protect_ruleset_shape(project_env: Path) -> None:
    """baseline-history-protect: 2 history rules (deletion + non_fast_forward),
    NO bypass actors, ~DEFAULT_BRANCH magic ref. required_linear_history is
    DELIBERATELY absent — it jams the many-agent merge workflow."""
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    hist = bpl.baseline_ruleset_payloads("main")[0]
    assert hist["target"] == "branch"
    assert hist["enforcement"] == "active"
    assert hist["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert hist["conditions"]["ref_name"]["exclude"] == []
    assert hist["bypass_actors"] == []
    rule_types = {r["type"] for r in hist["rules"]}
    assert rule_types == {"deletion", "non_fast_forward"}
    # Regression guard: linear history must NEVER come back — it is harmful for
    # the multi-agent model (forbids merge commits → endless rebase churn).
    assert "required_linear_history" not in rule_types


def test_pr_and_checks_ruleset_shape(project_env: Path) -> None:
    """baseline-pr-and-checks: PR rule + required_status_checks, admin
    RepositoryRole(5) always-bypass, ~DEFAULT_BRANCH magic ref.

    Exercised WITH detected contexts, because that is the only shape in which the
    checks rule may legally be emitted: GitHub 422s an empty contexts array (and the
    422 fails the whole write). The no-contexts shape — checks rule OMITTED — is pinned
    by test_pr_checks_omits_the_checks_rule_when_no_contexts. This test previously
    asserted the empty-list form was emitted, which encoded the live 422 bug.
    """
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    pr = bpl.baseline_ruleset_payloads("main", [{"context": "test"}])[1]
    assert pr["target"] == "branch"
    assert pr["enforcement"] == "active"
    assert pr["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert pr["conditions"]["ref_name"]["exclude"] == []
    # bypass actor: exactly one — the repo-admin RepositoryRole, always.
    assert pr["bypass_actors"] == [
        {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"},
    ]
    rule_types = {r["type"] for r in pr["rules"]}
    assert rule_types == {"pull_request", "required_status_checks"}
    pr_rule = next(r for r in pr["rules"] if r["type"] == "pull_request")
    assert pr_rule["parameters"]["required_approving_review_count"] == 1
    assert pr_rule["parameters"]["dismiss_stale_reviews_on_push"] is True
    assert pr_rule["parameters"]["require_code_owner_review"] is False
    assert pr_rule["parameters"]["require_last_push_approval"] is False
    assert pr_rule["parameters"]["required_review_thread_resolution"] is True
    sc_rule = next(r for r in pr["rules"] if r["type"] == "required_status_checks")
    assert sc_rule["parameters"]["strict_required_status_checks_policy"] is True
    # Contexts land verbatim — never an empty array (that is the 422).
    assert sc_rule["parameters"]["required_status_checks"] == [{"context": "test"}]


def test_pr_and_checks_embeds_detected_checks_in_context_shape(project_env: Path) -> None:
    """Auto-detected checks land as a list of {context: <name>} dicts —
    the exact shape the GitHub rulesets API wants."""
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    checks = [{"context": "validate"}, {"context": "workflow-security"}]
    pr = bpl.baseline_ruleset_payloads("main", checks)[1]
    sc_rule = next(r for r in pr["rules"] if r["type"] == "required_status_checks")
    assert sc_rule["parameters"]["required_status_checks"] == checks


def test_tag_protect_ruleset_shape(project_env: Path) -> None:
    """baseline-tag-protect (3rd ratified, tri-party consensus): target=tag,
    refs/tags/v*.*.* scope, [deletion, update] rules, NO bypass actor."""
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    tag = bpl.baseline_ruleset_payloads("main")[2]
    assert tag["name"] == "baseline-tag-protect"
    assert tag["target"] == "tag"
    assert tag["enforcement"] == "active"
    assert tag["conditions"]["ref_name"]["include"] == ["refs/tags/v*.*.*"]
    assert tag["conditions"]["ref_name"]["exclude"] == []
    # No bypass actor — new-tag CREATION stays open so publish.py still cuts releases.
    assert tag["bypass_actors"] == []
    # [deletion, update] — `update` blocks every repoint (incl. a fast-forward move
    # onto a descendant commit), which non_fast_forward-only would miss.
    rule_types = {r["type"] for r in tag["rules"]}
    assert rule_types == {"deletion", "update"}
    assert len(tag["rules"]) == 2


def test_baseline_payloads_ignore_branch_name_in_ref(project_env: Path) -> None:
    """Even a non-default branch name still emits ~DEFAULT_BRANCH — the
    magic ref is byte-identical with the maintainer + ratified spec.
    (The tag ruleset is exempt: it scopes to refs/tags/v*.*.*, not a branch.)"""
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    for branch in ("develop", "master", "trunk"):
        for p in bpl.baseline_ruleset_payloads(branch):
            if p["target"] != "branch":
                continue  # tag ruleset uses refs/tags/v*.*.*, not the branch magic ref
            assert p["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]


def test_baseline_payloads_reject_empty_branch(project_env: Path) -> None:
    _ = project_env
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    with pytest.raises(ValueError):
        bpl.baseline_ruleset_payloads("")


def _write_workflow(root: Path, filename: str, body: str) -> Path:
    """Write a workflow file under <root>/.github/workflows/<filename>."""
    wf_dir = root / ".github" / "workflows"
    wf_dir.mkdir(parents=True, exist_ok=True)
    path = wf_dir / filename
    path.write_text(body, encoding="utf-8")
    return path


def test_detect_required_status_checks_empty_when_no_workflows_dir(
    project_env: Path,
) -> None:
    """No .github/workflows/ at all → empty list, never raises."""
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    assert bpl.detect_required_status_checks(project_env) == []


def test_detect_required_status_checks_empty_when_dir_has_no_files(
    project_env: Path,
) -> None:
    """Empty .github/workflows/ dir → empty list."""
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    (project_env / ".github" / "workflows").mkdir(parents=True)
    assert bpl.detect_required_status_checks(project_env) == []


def test_detect_required_status_checks_single_job_uses_job_id(
    project_env: Path,
) -> None:
    """A single job with no `name:` → context is the job id, in {context}
    shape."""
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    _write_workflow(
        project_env, "ci.yml",
        "name: CI\non: [pull_request]\njobs:\n  validate:\n    runs-on: ubuntu-latest\n",
    )
    assert bpl.detect_required_status_checks(project_env) == [{"context": "validate"}]


def test_detect_required_status_checks_multiple_jobs_sorted_and_unique(
    project_env: Path,
) -> None:
    """Multiple jobs across files → sorted, de-duplicated context list."""
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    _write_workflow(
        project_env, "ci.yml",
        "on: [pull_request]\njobs:\n"
        "  validate:\n    runs-on: ubuntu-latest\n"
        "  lint:\n    runs-on: ubuntu-latest\n",
    )
    # A second file repeats `validate` (must collapse) and adds `test`.
    _write_workflow(
        project_env, "extra.yml",
        "on: [pull_request]\njobs:\n"
        "  test:\n    runs-on: ubuntu-latest\n"
        "  validate:\n    runs-on: ubuntu-latest\n",
    )
    assert bpl.detect_required_status_checks(project_env) == [
        {"context": "lint"},
        {"context": "test"},
        {"context": "validate"},
    ]


def test_detect_required_status_checks_uses_custom_job_name(
    project_env: Path,
) -> None:
    """A job with an explicit `name:` → that display name is the context,
    not the job id."""
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    _write_workflow(
        project_env, "ci.yml",
        "on: [pull_request]\njobs:\n"
        "  build_job:\n    name: Build & Test\n    runs-on: ubuntu-latest\n",
    )
    assert bpl.detect_required_status_checks(project_env) == [
        {"context": "Build & Test"},
    ]


def test_detect_required_status_checks_finds_yaml_extension(
    project_env: Path,
) -> None:
    """A workflow with the `.yaml` (not `.yml`) extension is discovered."""
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    _write_workflow(
        project_env, "release.yaml",
        "on: [pull_request]\njobs:\n  publish:\n    runs-on: ubuntu-latest\n",
    )
    assert bpl.detect_required_status_checks(project_env) == [{"context": "publish"}]


def test_detect_required_status_checks_skips_malformed_yaml(
    project_env: Path,
) -> None:
    """A malformed workflow file is skipped (never crashes); a valid one
    alongside it still contributes its jobs."""
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    # Unbalanced bracket → yaml.YAMLError on parse.
    _write_workflow(project_env, "broken.yml", "jobs: {validate: [unclosed\n")
    _write_workflow(
        project_env, "good.yml",
        "on: [pull_request]\njobs:\n  lint:\n    runs-on: ubuntu-latest\n",
    )
    # Does not raise; the broken file is silently skipped.
    assert bpl.detect_required_status_checks(project_env) == [{"context": "lint"}]


def test_detect_required_status_checks_all_malformed_returns_empty(
    project_env: Path,
) -> None:
    """All workflows unparseable → empty list, no crash."""
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    _write_workflow(project_env, "broken.yml", "jobs: {a: [unclosed\n")
    assert bpl.detect_required_status_checks(project_env) == []


def test_detect_required_status_checks_filters_push_only_workflows(
    project_env: Path,
) -> None:
    """Push-only workflows are SKIPPED — their jobs NEVER report on a PR, so
    requiring one as a status check would wedge every non-admin PR forever
    (janitor#14 / maintainer cde65eb). Only jobs from PR-triggered workflows
    (`on:` includes pull_request / pull_request_target) are detected. Also
    exercises the load-bearing YAML `on:`->True parse via the dict form."""
    import branch_protection_lib as bpl  # type: ignore[import-not-found]
    # PR-triggered (list form) → its job IS a required check.
    _write_workflow(
        project_env, "ci.yml",
        "on: [pull_request]\njobs:\n  validate:\n    runs-on: ubuntu-latest\n",
    )
    # Push-only → DROPPED (a release job can't report on a PR).
    _write_workflow(
        project_env, "release.yml",
        "on: [push]\njobs:\n  release:\n    runs-on: ubuntu-latest\n",
    )
    # Dict-form `on:` with a pull_request key (parsed under the YAML boolean
    # True) → kept; the schedule key alongside does not matter.
    _write_workflow(
        project_env, "audit.yml",
        "on:\n  pull_request:\n  schedule:\n    - cron: '0 0 * * 0'\n"
        "jobs:\n  audit:\n    runs-on: ubuntu-latest\n",
    )
    assert bpl.detect_required_status_checks(project_env) == [
        {"context": "audit"},
        {"context": "validate"},
    ]


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


def test_apply_noop_when_all_three_baselines_already_present(project_env: Path) -> None:
    """Gate 6 (convergence): ALL THREE ratified rulesets present → silent NOOP.
    Convergence now requires baseline-tag-protect too (else a pair-only repo would
    be wrongly judged converged and never get the 3rd ruleset)."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={
            "GH_RULESETS_BODY": json.dumps([
                {"id": 42, "name": "baseline-history-protect", "target": "branch"},
                {"id": 43, "name": "baseline-pr-and-checks", "target": "branch"},
                {"id": 44, "name": "baseline-tag-protect", "target": "tag"},
            ]),
        },
    )
    assert r.returncode == 0, r.stderr
    assert r.stdout == "", f"expected silence, got {r.stdout!r}"
    # Ledger should record once that the baseline was already present.
    ledger = project_env / ".janitor" / "state" / "branch-protection-acted.txt"
    if ledger.is_file():
        assert "already-present" in ledger.read_text(encoding="utf-8")


def test_apply_acts_when_only_one_baseline_present(project_env: Path) -> None:
    """Only ONE ratified ruleset present → NOT converged → apply proceeds.

    The history ruleset already exists (so it is PUT/updated by id — GitHub's
    update-ruleset endpoint is PUT, not PATCH, janitor#14), the pr/checks ruleset
    is missing (so it is POSTed). Both succeed → loud apply announcement.
    """
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={
            "GH_RULESETS_BODY": json.dumps([
                {"id": 42, "name": "baseline-history-protect", "target": "branch"},
            ]),
            "GH_PUT_BODY": json.dumps({"id": 42, "name": "baseline-history-protect"}),
            "GH_POST_BODY": json.dumps({"id": 99, "name": "baseline-pr-and-checks"}),
        },
    )
    assert r.returncode == 0, r.stderr
    assert "[guard] applied branch-protection baseline on o/r@main" in r.stdout
    # PUT (update) path reports "updated", POST path reports "created".
    assert "updated id=42" in r.stdout
    assert "created id=99" in r.stdout


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


def test_apply_creates_both_baselines_when_all_gates_pass(project_env: Path) -> None:
    """All gates green, no existing rulesets → POST both + loud `[guard]
    applied` announcement + audit log records BOTH payloads."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={"GH_POST_BODY": json.dumps({"id": 1234, "name": "ruleset"})},
    )
    assert r.returncode == 0, r.stderr
    assert "[guard] applied branch-protection baseline on o/r@main" in r.stdout
    assert "baseline-history-protect=created id=1234" in r.stdout
    assert "baseline-pr-and-checks=created id=1234" in r.stdout
    # Audit log records the OK line AND both emitted payloads with the
    # ~DEFAULT_BRANCH magic ref + the admin bypass actor.
    log = project_env / ".janitor" / "logs" / "branch-protection-apply.log"
    assert log.is_file()
    log_text = log.read_text(encoding="utf-8")
    assert "OK\to/r\tmain" in log_text
    assert "~DEFAULT_BRANCH" in log_text
    assert '"actor_type":"RepositoryRole"' in log_text
    assert '"bypass_mode":"always"' in log_text
    ledger = project_env / ".janitor" / "state" / "branch-protection-acted.txt"
    assert ledger.is_file()
    assert "applied" in ledger.read_text(encoding="utf-8")


def test_apply_deletes_legacy_orphan_after_applying(project_env: Path) -> None:
    """When a pre-migration `janitor-baseline` ruleset is present, it is
    DELETEd after the ratified pair lands."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={
            # Only the legacy ruleset exists → both ratified are POSTed,
            # then the legacy (id 7) is DELETEd by id.
            "GH_RULESETS_BODY": json.dumps([
                {"id": 7, "name": "janitor-baseline", "target": "branch"},
            ]),
            "GH_POST_BODY": json.dumps({"id": 1234, "name": "ruleset"}),
            "GH_DELETE_BODY": "",
            "GH_DELETE_RC": "0",
        },
    )
    assert r.returncode == 0, r.stderr
    assert "[guard] applied branch-protection baseline on o/r@main" in r.stdout
    # The summary names the legacy ruleset with its delete result.
    assert "janitor-baseline=deleted id=7" in r.stdout


def test_apply_deletes_full_orphan_union_after_applying(project_env: Path) -> None:
    """The shared orphan-delete UNION (janitor#14 / maintainer#7): EVERY
    pre-ratification ruleset name in BOTH plugins' lineage that is present on the
    repo is DELETEd after the ratified pair lands, so a repo either plugin ever
    touched converges to exactly {baseline-history-protect, baseline-pr-and-checks}
    with no straggler."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    union = {
        "janitor-baseline": 7, "main-hardening": 8, "main-ci-gate": 9,
        "default-branch-ruleset": 10, "default-branch-no-force-no-delete": 11,
        "default-branch-required-checks": 12,
    }
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={
            "GH_RULESETS_BODY": json.dumps(
                [{"id": i, "name": n, "target": "branch"} for n, i in union.items()]
            ),
            "GH_POST_BODY": json.dumps({"id": 1234, "name": "ruleset"}),
            "GH_DELETE_BODY": "",
            "GH_DELETE_RC": "0",
        },
    )
    assert r.returncode == 0, r.stderr
    assert "[guard] applied branch-protection baseline on o/r@main" in r.stdout
    for name, rid in union.items():
        assert f"{name}=deleted id={rid}" in r.stdout, name


def test_apply_reports_auto_detected_checks_in_announcement(project_env: Path) -> None:
    """Non-empty auto-detected CI contexts (parsed from the project's
    workflow files) surface in the announcement + land in the emitted
    required_status_checks payload."""
    _make_plugin_manifest(project_env)
    # Contexts are parsed from .github/workflows/* under the project root
    # (CLAUDE_PLUGIN_ROOT == project in _run_apply), NOT from runtime
    # check-runs. Sorted order → "validate" before "workflow-security".
    _write_workflow(
        project_env, "ci.yml",
        "on: [pull_request]\njobs:\n"
        "  validate:\n    runs-on: ubuntu-latest\n"
        "  workflow-security:\n    runs-on: ubuntu-latest\n",
    )
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={"GH_POST_BODY": json.dumps({"id": 1234, "name": "ruleset"})},
    )
    assert r.returncode == 0, r.stderr
    assert "2 required check(s): validate, workflow-security" in r.stdout
    # The emitted payload in the audit log carries the {context: ...} shape.
    log = project_env / ".janitor" / "logs" / "branch-protection-apply.log"
    log_text = log.read_text(encoding="utf-8")
    assert '"context":"validate"' in log_text
    assert '"context":"workflow-security"' in log_text


def test_apply_falls_back_to_empty_checks_when_none_detected(project_env: Path) -> None:
    """No workflow files (fresh repo) → empty checks list, apply still
    succeeds, announcement says none detected."""
    _make_plugin_manifest(project_env)
    # No .github/workflows/ dir written → detection yields [].
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={"GH_POST_BODY": json.dumps({"id": 1234, "name": "ruleset"})},
    )
    assert r.returncode == 0, r.stderr
    assert "[guard] applied branch-protection baseline on o/r@main" in r.stdout
    assert "no required checks auto-detected" in r.stdout


def test_apply_logs_failure_when_post_rejected(project_env: Path) -> None:
    """gh POST returns non-zero (422 schema, 403 scope, etc.) → no half-apply,
    drift announcement + audit log entry."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={
            "GH_POST_RC": "1",
            # Real gh writes the HTTP error to stderr; the lib trims the
            # last stderr line into the surfaced message.
            "GH_POST_STDERR": "HTTP 422: Validation Failed (ruleset schema)",
        },
    )
    assert r.returncode == 0, r.stderr
    assert "baseline apply FAILED" in r.stdout
    assert "Validation Failed" in r.stdout
    log = project_env / ".janitor" / "logs" / "branch-protection-apply.log"
    assert log.is_file()
    assert "FAIL\to/r\tmain" in log.read_text(encoding="utf-8")


def test_apply_keeps_legacy_orphan_when_ratified_apply_fails(project_env: Path) -> None:
    """Safety: a failed ratified apply must NOT delete the legacy
    `janitor-baseline` — that would strip all protection. The legacy
    ruleset is kept and the audit log records FAIL for the failing
    ruleset but NEVER a DELETE of janitor-baseline."""
    _make_plugin_manifest(project_env)
    gh = _make_gh_stub(project_env)
    r = _run_apply(
        project_env, gh_bin=gh,
        extra_env={
            # Legacy present; both ratified POSTs fail.
            "GH_RULESETS_BODY": json.dumps([
                {"id": 7, "name": "janitor-baseline", "target": "branch"},
            ]),
            "GH_POST_RC": "1",
            "GH_POST_STDERR": "HTTP 403: forbidden",
            # If DELETE were (wrongly) attempted it would "succeed"; the
            # assertion below proves it is never called.
            "GH_DELETE_RC": "0",
        },
    )
    assert r.returncode == 0, r.stderr
    assert "baseline apply FAILED" in r.stdout
    log_text = (
        project_env / ".janitor" / "logs" / "branch-protection-apply.log"
    ).read_text(encoding="utf-8")
    # No "deleted id=7" must appear anywhere — legacy was kept.
    assert "deleted id=7" not in log_text
    assert "deleted id=7" not in r.stdout


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
