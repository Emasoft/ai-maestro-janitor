"""Tests for scripts/lib/provenance_patterns.py.

Pattern-coverage tests for the Wave-16 provenance / SBOM catalogue
(distill2-f deep-dive proposals: missing cosign verify, npm publish
without provenance, SBOM absent on release, missing in-toto attestation,
SLSA-level extraction, reproducible-build flag absent, OIDC trusted
publishing missing, release-asset checksum absent).

Every rule gets at least one positive + one negative test. The negative
case exercises the two-pass `negative_substrings` suppression: the
positive regex hits but a mitigating tool / verifier / flag elsewhere
in the file makes the rule a false alarm.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import provenance_patterns as pp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised rule id."""
    assert isinstance(pp.RULES, tuple)
    rule_ids = [r.id for r in pp.RULES]
    expected = {
        "prov-missing-cosign-verify-on-download",
        "prov-npm-publish-without-provenance",
        "prov-sbom-absent-but-release-built",
        "prov-in-toto-attestation-missing-on-build",
        "prov-slsa-level-declared",
        "prov-reproducible-build-flag-absent",
        "prov-trusted-publishing-missing",
        "prov-release-asset-no-checksum",
    }
    assert expected.issubset(set(rule_ids))


def test_every_rule_has_severity_in_jansevs() -> None:
    """Every rule severity must be in the janitor's 4-tier vocabulary."""
    for rule in pp.RULES:
        assert rule.severity in {"CRITICAL", "HIGH", "MAJOR", "MINOR"}, rule.id
        assert rule.id.startswith("prov-"), rule.id


def test_finding_named_tuple_shape() -> None:
    f = pp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", file_path="/tmp/x.yml",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.file_path == "/tmp/x.yml"


def test_rule_record_has_all_fields() -> None:
    """A Rule must carry the pattern + negative substrings + file_suffix scoping."""
    sample = pp.RULES[0]
    assert sample.id
    assert sample.pattern is not None
    assert isinstance(sample.negative_substrings, tuple)
    assert isinstance(sample.file_suffixes, tuple)


# ---------- Helpers ------------------------------------------------------


def _scan_yaml(tmp_path: Path, body: str, name: str = "ci.yml") -> list[pp.Finding]:
    """Write `body` to a tmp .yml file and return its findings."""
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return pp.scan_file(p)


def _hits(findings: list[pp.Finding], rule_id: str) -> list[pp.Finding]:
    return [f for f in findings if f.rule_id == rule_id]


# ---------- Rule 1: missing cosign verify --------------------------------


def test_cosign_missing_gh_release_download(tmp_path: Path) -> None:
    body = """
name: ci
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: gh release download v1.2.3 -R kubernetes/kubernetes
"""
    assert _hits(_scan_yaml(tmp_path, body), "prov-missing-cosign-verify-on-download")


def test_cosign_missing_curl_k8s(tmp_path: Path) -> None:
    body = """
jobs:
  build:
    steps:
      - run: curl -LO https://dl.k8s.io/release/v1.30.0/bin/linux/amd64/kubectl
"""
    assert _hits(_scan_yaml(tmp_path, body), "prov-missing-cosign-verify-on-download")


def test_cosign_suppressed_when_verifier_present(tmp_path: Path) -> None:
    """When the same file calls `cosign verify` the rule must NOT fire."""
    body = """
jobs:
  build:
    steps:
      - run: gh release download v1.2.3 -R foo/bar
      - run: cosign verify-blob --signature x.sig --certificate x.crt artifact
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-missing-cosign-verify-on-download") == []


def test_cosign_suppressed_when_slsa_verifier_present(tmp_path: Path) -> None:
    body = """
jobs:
  build:
    steps:
      - run: curl -LO https://github.com/foo/bar/releases/download/v1/asset.zip
      - run: slsa-verifier verify-artifact asset.zip --source-uri github.com/foo/bar
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-missing-cosign-verify-on-download") == []


# ---------- Rule 2: npm publish without provenance -----------------------


def test_npm_publish_without_provenance(tmp_path: Path) -> None:
    body = """
jobs:
  publish:
    steps:
      - run: npm publish --access public
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-npm-publish-without-provenance")


def test_pnpm_publish_without_provenance(tmp_path: Path) -> None:
    body = """
jobs:
  publish:
    steps:
      - run: pnpm publish
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-npm-publish-without-provenance")


def test_npm_publish_with_provenance_flag_suppressed(tmp_path: Path) -> None:
    """`--provenance` on the same line suppresses the rule."""
    body = """
jobs:
  publish:
    steps:
      - run: npm publish --provenance --access public
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-npm-publish-without-provenance") == []


def test_npm_publish_with_env_provenance_suppressed(tmp_path: Path) -> None:
    """`NPM_CONFIG_PROVENANCE=true` in env block suppresses the rule."""
    body = """
jobs:
  publish:
    steps:
      - run: npm publish
        env:
          NPM_CONFIG_PROVENANCE: true
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-npm-publish-without-provenance") == []


# ---------- Rule 3: SBOM absent on release-publish -----------------------


def test_release_without_sbom_softprops(tmp_path: Path) -> None:
    body = """
jobs:
  release:
    steps:
      - uses: softprops/action-gh-release@v2
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-sbom-absent-but-release-built")


def test_release_without_sbom_gh_release_create(tmp_path: Path) -> None:
    body = """
jobs:
  release:
    steps:
      - run: gh release create v1.2.3 --notes "release"
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-sbom-absent-but-release-built")


def test_release_with_sbom_suppressed(tmp_path: Path) -> None:
    body = """
jobs:
  release:
    steps:
      - uses: anchore/sbom-action@v0
      - uses: softprops/action-gh-release@v2
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-sbom-absent-but-release-built") == []


def test_release_with_syft_suppressed(tmp_path: Path) -> None:
    body = """
jobs:
  release:
    steps:
      - run: syft . -o cyclonedx-json > sbom.json
      - uses: softprops/action-gh-release@v2
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-sbom-absent-but-release-built") == []


# ---------- Rule 4: in-toto attestation missing --------------------------


def test_intoto_missing_on_pypi_publish(tmp_path: Path) -> None:
    body = """
jobs:
  publish:
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-in-toto-attestation-missing-on-build")


def test_intoto_missing_on_docker_build_push(tmp_path: Path) -> None:
    body = """
jobs:
  build:
    steps:
      - uses: docker/build-push-action@v6
        with:
          push: true
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-in-toto-attestation-missing-on-build")


def test_intoto_suppressed_when_attest_present(tmp_path: Path) -> None:
    body = """
jobs:
  publish:
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
      - uses: actions/attest-build-provenance@v1
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-in-toto-attestation-missing-on-build") == []


def test_intoto_suppressed_when_slsa_generator(tmp_path: Path) -> None:
    body = """
jobs:
  build:
    uses: slsa-framework/slsa-github-generator/.github/workflows/generator_generic_slsa3.yml@v2
  publish:
    needs: build
    steps:
      - uses: softprops/action-gh-release@v2
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-in-toto-attestation-missing-on-build") == []


def test_intoto_suppressed_when_cosign_attest(tmp_path: Path) -> None:
    body = """
jobs:
  build:
    steps:
      - uses: docker/build-push-action@v6
        with:
          push: true
      - run: cosign attest --predicate sbom.json $IMAGE
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-in-toto-attestation-missing-on-build") == []


# ---------- janitor#99: BuildKit's native provenance IS an attestation ----
#
# `docker/build-push-action` with `provenance:` enabled makes BuildKit emit SLSA
# provenance itself, so demanding a separate attest step was a false positive.
# These run as a SET: the three enabling spellings must go silent AND the
# disabling one must still fire, so the fix cannot be "stop reporting this rule".


def test_intoto_suppressed_by_buildkit_provenance_mode_max(tmp_path: Path) -> None:
    """The exact shape reported in #99 — `mode=max` is the STRONGER setting."""
    body = """
jobs:
  build:
    steps:
      - uses: docker/build-push-action@v7
        with:
          provenance: mode=max
          sbom: true
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-in-toto-attestation-missing-on-build") == []


def test_intoto_suppressed_by_buildkit_provenance_true(tmp_path: Path) -> None:
    body = """
jobs:
  build:
    steps:
      - uses: docker/build-push-action@v7
        with:
          provenance: true
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-in-toto-attestation-missing-on-build") == []


def test_intoto_suppressed_by_quoted_provenance_mode_min(tmp_path: Path) -> None:
    """YAML quoting must not defeat the suppression."""
    body = """
jobs:
  build:
    steps:
      - uses: docker/build-push-action@v7
        with:
          provenance: "mode=min"
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-in-toto-attestation-missing-on-build") == []


def test_intoto_STILL_FIRES_when_provenance_explicitly_disabled(tmp_path: Path) -> None:
    """`provenance: false` turns the attestation OFF — it must NOT suppress.

    This is the load-bearing half. A plain `provenance:` substring mitigation,
    or a negative lookahead, would silence the finding on the one workflow that
    most needs reporting: one that deliberately disabled its build provenance.
    A false negative on a supply-chain control is worse than the false positive
    being fixed.
    """
    body = """
jobs:
  build:
    steps:
      - uses: docker/build-push-action@v7
        with:
          provenance: false
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-in-toto-attestation-missing-on-build") != []


# ---------- Rule 5: SLSA-level extraction --------------------------------


def test_extract_slsa_level_from_json() -> None:
    text = '{"slsa_level": "2"}'
    out = pp.extract_slsa_levels(text)
    assert (2, 1) in out


def test_extract_slsa_level_from_security_txt() -> None:
    text = "Contact: mailto:sec@example.com\nSlsa-Build-Level: L1\n"
    out = pp.extract_slsa_levels(text)
    assert any(lvl == 1 for lvl, _ in out)


def test_extract_slsa_level_from_scorecard_markdown() -> None:
    text = "## Scorecard\n\nslsa-level: 3\n"
    out = pp.extract_slsa_levels(text)
    assert any(lvl == 3 for lvl, _ in out)


def test_extract_slsa_level_empty_text() -> None:
    assert pp.extract_slsa_levels("") == []


def test_extract_slsa_level_no_match_in_prose() -> None:
    """Prose that mentions SLSA but doesn't declare a level must not match."""
    text = "This project follows the SLSA framework but does not declare a level."
    assert pp.extract_slsa_levels(text) == []


# ---------- Rule 6: reproducible-build flag absent -----------------------


def test_repro_cargo_release_without_locked(tmp_path: Path) -> None:
    # FP-hardening round 3: the rule only applies to workflows that
    # ALSO publish — include a `cargo publish` token so the rule fires.
    body = """
jobs:
  build:
    steps:
      - run: cargo build --release
      - run: cargo publish
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-reproducible-build-flag-absent")


def test_repro_npm_install_without_ci(tmp_path: Path) -> None:
    # FP-hardening round 3: include `npm publish` (publisher token).
    body = """
jobs:
  build:
    steps:
      - run: npm install
      - run: npm publish
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-reproducible-build-flag-absent")


def test_repro_pip_install_without_hashes(tmp_path: Path) -> None:
    # FP-hardening round 3: include `twine upload` (PyPI publisher).
    body = """
jobs:
  build:
    steps:
      - run: pip install -r requirements.txt
      - run: twine upload dist/*
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-reproducible-build-flag-absent")


def test_repro_suppressed_when_locked_present(tmp_path: Path) -> None:
    body = """
jobs:
  build:
    steps:
      - run: cargo build --release --locked
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-reproducible-build-flag-absent") == []


def test_repro_suppressed_when_npm_ci(tmp_path: Path) -> None:
    """A file using `npm ci` (reproducible) suppresses any positive
    `npm install` matches in the same file."""
    body = """
jobs:
  build:
    steps:
      - run: npm ci
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-reproducible-build-flag-absent") == []


def test_repro_suppressed_when_trimpath(tmp_path: Path) -> None:
    body = """
jobs:
  build:
    steps:
      - run: go build -trimpath -o bin/x ./cmd/x
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-reproducible-build-flag-absent") == []


# ---------- Rule 7: OIDC trusted publishing missing ----------------------


def test_trusted_pub_missing_pypa_action(tmp_path: Path) -> None:
    body = """
jobs:
  publish:
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-trusted-publishing-missing")


def test_trusted_pub_suppressed_id_token_permission(tmp_path: Path) -> None:
    body = """
jobs:
  publish:
    permissions:
      id-token: write
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-trusted-publishing-missing") == []


def test_trusted_pub_suppressed_id_token_no_space(tmp_path: Path) -> None:
    """YAML allows no-space-after-colon style; suppress both spellings."""
    body = """
permissions:
  id-token:write
jobs:
  publish:
    steps:
      - uses: pypa/gh-action-pypi-publish@release/v1
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-trusted-publishing-missing") == []


# ---------- Rule 8: release-asset checksum manifest absent ---------------


def test_checksum_missing_on_release_upload(tmp_path: Path) -> None:
    body = """
jobs:
  release:
    steps:
      - run: gh release upload v1 artifact.tar.gz
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-release-asset-no-checksum")


def test_checksum_suppressed_by_sha256sum_step(tmp_path: Path) -> None:
    body = """
jobs:
  release:
    steps:
      - run: sha256sum artifact.tar.gz > artifact.tar.gz.sha256
      - run: gh release upload v1 artifact.tar.gz artifact.tar.gz.sha256
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-release-asset-no-checksum") == []


def test_checksum_suppressed_by_goreleaser(tmp_path: Path) -> None:
    """goreleaser always emits a checksums.txt manifest — its presence
    in the workflow file is itself the suppression signal."""
    body = """
jobs:
  release:
    steps:
      - uses: goreleaser/goreleaser-action@v6
      - uses: softprops/action-gh-release@v2
"""
    assert _hits(_scan_yaml(tmp_path, body),
                 "prov-release-asset-no-checksum") == []


# ---------- scan_file() — composition behaviour --------------------------


def test_scan_file_missing_path_returns_empty(tmp_path: Path) -> None:
    """A non-existent path must NOT raise — return empty list."""
    p = tmp_path / "does-not-exist.yml"
    assert pp.scan_file(p) == []


def test_scan_file_empty_yaml_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "empty.yml"
    p.write_text("", encoding="utf-8")
    assert pp.scan_file(p) == []


def test_scan_file_filters_by_suffix(tmp_path: Path) -> None:
    """Workflow-scoped rules must NOT fire on a `.txt` file even when
    the text contains a matching workflow pattern. (Rule 5 fires on
    any suffix; everything else needs .yml/.yaml.)"""
    body = """
jobs:
  publish:
    steps:
      - run: npm publish
"""
    p = tmp_path / "notes.txt"
    p.write_text(body, encoding="utf-8")
    findings = pp.scan_file(p)
    # The workflow-specific rule should NOT fire on a .txt file.
    assert all(f.rule_id != "prov-npm-publish-without-provenance"
               for f in findings)


def test_scan_file_finding_carries_full_path(tmp_path: Path) -> None:
    """Finding.file_path must equal the absolute path passed in."""
    body = """
jobs:
  publish:
    steps:
      - run: npm publish
"""
    p = tmp_path / "ci.yml"
    p.write_text(body, encoding="utf-8")
    findings = pp.scan_file(p)
    assert findings
    assert findings[0].file_path == str(p)


def test_scan_file_sorted_by_line_col_ruleid(tmp_path: Path) -> None:
    body = """
name: ci
on: [push]
jobs:
  publish:
    steps:
      - run: npm publish
      - uses: pypa/gh-action-pypi-publish@release/v1
"""
    p = tmp_path / "ci.yml"
    p.write_text(body, encoding="utf-8")
    findings = pp.scan_file(p)
    lines = [(f.line, f.column, f.rule_id) for f in findings]
    assert lines == sorted(lines)


def test_scan_file_long_match_truncated(tmp_path: Path) -> None:
    """matched_text capped at 200 chars + ellipsis."""
    p = tmp_path / "big.yml"
    big_line = "      - run: gh release download v1.2.3 -R " + "x" * 400
    p.write_text("jobs:\n  build:\n    steps:\n" + big_line + "\n",
                 encoding="utf-8")
    findings = pp.scan_file(p)
    cosigns = [f for f in findings
               if f.rule_id == "prov-missing-cosign-verify-on-download"]
    assert cosigns
    # Cap is 200 + 1 for the ellipsis.
    assert len(cosigns[0].matched_text) <= 201


def test_scan_file_line_col_one_based(tmp_path: Path) -> None:
    """Lines + columns reported as 1-based."""
    body = "line one\nname: ci\njobs:\n  publish:\n    steps:\n      - run: npm publish\n"
    p = tmp_path / "ci.yml"
    p.write_text(body, encoding="utf-8")
    findings = pp.scan_file(p)
    npm_hits = [f for f in findings
                if f.rule_id == "prov-npm-publish-without-provenance"]
    assert npm_hits
    # `npm publish` lives on line 6 of the body (1-based).
    assert npm_hits[0].line == 6
    assert npm_hits[0].column >= 1


def test_scan_file_dedupe_same_rule_same_position(tmp_path: Path) -> None:
    """A single line that triggers exactly one match must emit one
    finding (no duplicate at the same rule/line/col)."""
    body = "jobs:\n  publish:\n    steps:\n      - run: npm publish\n"
    p = tmp_path / "ci.yml"
    p.write_text(body, encoding="utf-8")
    findings = pp.scan_file(p)
    keys = {(f.rule_id, f.line, f.column) for f in findings}
    assert len(keys) == len(findings)
