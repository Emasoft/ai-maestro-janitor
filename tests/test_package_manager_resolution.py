"""Manager-aware supply-chain policy — the npm knobs must not be proposed on a yarn repo.

THE INCIDENT (janitor#130, reported by the ai-maestro Claude). `package-manager-policy` raised
PKGPOL-001 on a repo pinned to `yarn@1.22.22` and proposed writing `.npmrc` with
`minimum-release-age`, `trust-policy` and `block-exotic-subdeps`. Those are npm's keys. Yarn
Classic reads `.npmrc` for registry, auth and proxy only and ignores every one of them — so
applying the fix would have produced a file that LOOKS like an enforced supply-chain policy while
enforcing nothing.

That is worse than the gap it closed. A missing control is visibly missing; a control that exists
and does nothing reads as covered, and the next auditor — human or agent — stops looking.

Two properties are therefore pinned here, and the second matters as much as the first:

  * a yarn repo gets NO `.npmrc` proposal, and
  * an npm repo STILL DOES — otherwise this suite would pass just as well if the detector had
    been deleted, which is the classic way a "fix" for a false positive becomes a false negative.

Real fixture directories and real files throughout; the resolver itself is pure and is tested by
injection, with no filesystem at all.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

_DETECTOR = (
    Path(__file__).resolve().parent.parent / "scripts" / "detectors" / "package-manager-policy.py"
)


@pytest.fixture()
def pmp():
    spec = importlib.util.spec_from_file_location("pkg_manager_policy_under_test", _DETECTOR)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# --- the pure resolver ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("yarn@1.22.22", "yarn-classic"),   # the exact pin from the incident
        ("yarn@1.22.19", "yarn-classic"),
        ("yarn@4.1.0", "yarn-berry"),
        ("yarn@2.0.0", "yarn-berry"),
        ("npm@10.8.0", "npm"),
        ("pnpm@9.1.0", "pnpm"),
        ("bun@1.1.0", "bun"),
    ],
)
def test_the_corepack_pin_is_authoritative(pmp, field, expected):
    """An explicit declaration beats anything inferred — and is the ONLY signal that separates
    Yarn Classic from Berry by version rather than by a side effect."""
    assert pmp.resolve_package_manager(package_manager_field=field) == expected


@pytest.mark.parametrize(
    ("lockfile", "expected"),
    [
        ("package-lock.json", "npm"),
        ("npm-shrinkwrap.json", "npm"),
        ("pnpm-lock.yaml", "pnpm"),
        ("bun.lockb", "bun"),
        ("bun.lock", "bun"),
    ],
)
def test_a_lockfile_identifies_its_manager(pmp, lockfile, expected):
    """A lockfile exists only because that manager actually ran — it is evidence, not a hint."""
    assert pmp.resolve_package_manager(lockfiles=[lockfile]) == expected


def test_yarn_lock_alone_reads_as_CLASSIC(pmp):
    """The safer read: Classic is the variant that silently ignores npm's knobs, so it is the
    case worth being right about when the evidence cannot separate the two."""
    assert pmp.resolve_package_manager(lockfiles=["yarn.lock"]) == "yarn-classic"


def test_yarn_lock_plus_a_berry_config_reads_as_BERRY(pmp):
    """`.yarnrc.yml` is Berry-only, so it breaks the tie `yarn.lock` cannot."""
    got = pmp.resolve_package_manager(lockfiles=["yarn.lock"], has_yarnrc_yml=True)

    assert got == "yarn-berry"


def test_two_managers_lockfiles_are_AMBIGUOUS_never_a_silent_pick(pmp):
    """Choosing a winner would hide a real problem behind whichever knob set we then proposed."""
    got = pmp.resolve_package_manager(lockfiles=["yarn.lock", "package-lock.json"])

    assert got == "ambiguous"


def test_no_evidence_at_all_is_UNKNOWN(pmp):
    """Distinct from npm on purpose: the caller decides what to infer, the resolver does not guess."""
    assert pmp.resolve_package_manager() == "unknown"


def test_the_pin_wins_over_a_contradicting_lockfile(pmp):
    """A yarn-pinned repo carrying a stray package-lock.json is still a yarn repo."""
    got = pmp.resolve_package_manager(
        package_manager_field="yarn@1.22.22", lockfiles=["package-lock.json"],
    )

    assert got == "yarn-classic"


# --- the gate: who gets an .npmrc proposal --------------------------------------------


def _issues_for(pmp, tmp_path: Path, manager: str) -> list[str]:
    issues: list[str] = []
    pmp._audit_npmrc(tmp_path, 7200, issues, manager)
    return issues


@pytest.mark.parametrize("manager", ["yarn-classic", "yarn-berry", "pnpm", "bun", "ambiguous"])
def test_a_manager_that_ignores_the_knobs_gets_NO_npmrc_proposal(pmp, tmp_path, manager):
    """The incident, pinned. Writing these keys where they are inert manufactures false assurance."""
    assert _issues_for(pmp, tmp_path, manager) == []


@pytest.mark.parametrize("manager", ["npm", "unknown"])
def test_npm_STILL_gets_the_proposal(pmp, tmp_path, manager):
    """The other half of the pair — without this, the suite would pass on a deleted detector.

    `unknown` is included deliberately: npm is Node's default and the resolver has already looked
    for every other manager's evidence, so treating it as npm is an inference, not a guess.
    """
    issues = _issues_for(pmp, tmp_path, manager)

    assert len(issues) == 1
    assert "minimum-release-age" in issues[0]


def test_an_existing_npmrc_is_still_audited_under_npm(pmp, tmp_path):
    """Gating must not disable the content audit for the manager that DOES honour the keys."""
    (tmp_path / ".npmrc").write_text("minimum-release-age=60\n", encoding="utf-8")

    issues = _issues_for(pmp, tmp_path, "npm")

    assert any("minimum-release-age=60" in i for i in issues)


def test_an_existing_npmrc_is_NOT_audited_under_yarn_classic(pmp, tmp_path):
    """A yarn repo may legitimately keep an .npmrc for registry/auth — yarn DOES read those.

    Auditing its npm-policy keys there would report a violation of a policy that was never in
    force, which is the same mismatch as proposing the file in the first place.
    """
    (tmp_path / ".npmrc").write_text(
        "registry=https://registry.example.invalid\nminimum-release-age=60\n", encoding="utf-8",
    )

    assert _issues_for(pmp, tmp_path, "yarn-classic") == []


# --- end to end, on real fixture repos ------------------------------------------------


def _repo(tmp_path: Path, name: str, *, files: dict[str, str]) -> Path:
    root = tmp_path / name
    root.mkdir()
    for rel, content in files.items():
        (root / rel).write_text(content, encoding="utf-8")
    return root


def test_the_incident_repo_shape_yields_no_npmrc_proposal(pmp, tmp_path):
    """The reported shape: yarn.lock, a yarn@1.22.22 pin, no .npmrc, no package-lock.json."""
    root = _repo(
        tmp_path,
        "yarn-repo",
        files={
            "yarn.lock": "# yarn lockfile v1\n",
            "package.json": json.dumps(
                {"name": "x", "packageManager": "yarn@1.22.22", "dependencies": {"left-pad": "^1"}}
            ),
        },
    )

    assert pmp.detect_package_manager(root) == "yarn-classic"

    issues: list[str] = []
    pmp._audit_npmrc(root, 7200, issues, pmp.detect_package_manager(root))
    assert issues == []


def test_the_npm_control_repo_still_fires(pmp, tmp_path):
    """The paired control. If this ever goes quiet, the fix above became a false negative."""
    root = _repo(
        tmp_path,
        "npm-repo",
        files={
            "package-lock.json": "{}\n",
            "package.json": json.dumps({"name": "y", "dependencies": {"left-pad": "^1"}}),
        },
    )

    assert pmp.detect_package_manager(root) == "npm"

    issues: list[str] = []
    pmp._audit_npmrc(root, 7200, issues, pmp.detect_package_manager(root))
    assert len(issues) == 1
    assert "minimum-release-age" in issues[0]
