"""Tests for scripts/lib/sbom_tampering_patterns.py.

Pattern-coverage tests for the Wave-18 SBOM / license tampering
catalogue (distill-round-4 angle D: CycloneDX scrubbing, lockfile
resolved-host swap, Cargo replace-with, Go checksum bypass, cosign
wildcard cert-identity, npm provenance digest mismatch, Maven
checksum-policy=warn, POM classifier-version mismatch, cosign
no-verify, SPDX stripping, frozen-lockfile skip on publish,
SOURCE_DATE_EPOCH falsification, release from non-tag ref, MIT-but-
GPL license laundering, Helm Chart.lock missing digest).

Each rule gets one or more positive tests + at least one negative
test exercising its carve-out (negative substring, allowlist, or
composite second stage).
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import sbom_tampering_patterns as stp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(stp.RULES, tuple)
    rule_ids = {r.id for r in stp.RULES}
    expected = {
        "sbom-cyclonedx-empty-components",
        "sbom-lockfile-resolved-non-registry",
        "sbom-cargo-lock-replace-with",
        "sbom-go-sum-disabled",
        "sbom-cosign-cert-identity-too-broad",
        "sbom-npm-provenance-digest-mismatch",
        "sbom-maven-checksum-policy-warn",
        "sbom-pom-classifier-version-mismatch",
        "sbom-cosign-blob-noverify",
        "sbom-spdx-license-stripped",
        "sbom-frozen-lockfile-skip-on-publish",
        "sbom-source-date-epoch-mismatch",
        "sbom-release-from-non-tag-ref",
        "sbom-license-file-mit-but-vendor-gpl",
        "sbom-helm-chart-lock-digest-missing",
    }
    assert expected == rule_ids
    assert len(stp.RULES) == 15


def test_every_rule_has_valid_severity() -> None:
    """Severities must be in CRITICAL/HIGH/MAJOR/MINOR (no MEDIUM/LOW)."""
    for rule in stp.RULES:
        assert rule.severity in {"CRITICAL", "HIGH", "MAJOR", "MINOR"}, rule.id
        assert rule.id.startswith("sbom-"), rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding shape mirrors provenance_patterns.Finding."""
    f = stp.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", file_path="/tmp/x.json",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.file_path == "/tmp/x.json"


def test_rule_record_has_all_fields() -> None:
    sample = stp.RULES[0]
    assert sample.id
    assert sample.pattern is not None
    assert isinstance(sample.negative_substrings, tuple)
    assert isinstance(sample.file_suffixes, tuple)


# ---------- Helpers ------------------------------------------------------


def _write(tmp_path: Path, name: str, body: str) -> Path:
    p = tmp_path / name
    p.write_text(body, encoding="utf-8")
    return p


def _scan(tmp_path: Path, name: str, body: str) -> list[stp.Finding]:
    return stp.scan_file(_write(tmp_path, name, body))


def _hits(findings: list[stp.Finding], rule_id: str) -> list[stp.Finding]:
    return [f for f in findings if f.rule_id == rule_id]


# ---------- Rule 1: sbom-cyclonedx-empty-components ----------------------


def test_cyclonedx_empty_components_json(tmp_path: Path) -> None:
    """A bom.json with `"components": []` fires."""
    body = '{"bomFormat":"CycloneDX","specVersion":"1.5","components":[]}\n'
    assert _hits(_scan(tmp_path, "bom.json", body),
                 "sbom-cyclonedx-empty-components")


def test_cyclonedx_empty_components_xml_selfclose(tmp_path: Path) -> None:
    """A bom.xml with `<components/>` (self-closing) fires."""
    body = '<bom><components/></bom>\n'
    assert _hits(_scan(tmp_path, "bom.xml", body),
                 "sbom-cyclonedx-empty-components")


def test_cyclonedx_empty_components_xml_paired(tmp_path: Path) -> None:
    """A bom.xml with `<components></components>` (paired) fires."""
    body = '<bom><components>\n  </components></bom>\n'
    assert _hits(_scan(tmp_path, "bom.xml", body),
                 "sbom-cyclonedx-empty-components")


def test_cyclonedx_non_empty_components_safe(tmp_path: Path) -> None:
    """A bom.json with real components does NOT fire."""
    body = '{"components":[{"type":"library","name":"lodash"}]}\n'
    assert not _hits(_scan(tmp_path, "bom.json", body),
                     "sbom-cyclonedx-empty-components")


def test_cyclonedx_only_fires_on_bom_filename(tmp_path: Path) -> None:
    """`"components": []` in a non-bom file does NOT fire."""
    body = '{"components":[]}\n'
    assert not _hits(_scan(tmp_path, "config.json", body),
                     "sbom-cyclonedx-empty-components")


# ---------- Rule 2: sbom-lockfile-resolved-non-registry ------------------


def test_lockfile_resolved_attacker_host(tmp_path: Path) -> None:
    """`resolved` pointing at attacker host fires."""
    body = (
        '{\n  "packages": {\n'
        '    "node_modules/lodash": {\n'
        '      "version": "4.17.21",\n'
        '      "resolved": "https://registry.example-evil.invalid/lodash/-/lodash-4.17.21.tgz"\n'
        '    }\n  }\n}\n'
    )
    assert _hits(_scan(tmp_path, "package-lock.json", body),
                 "sbom-lockfile-resolved-non-registry")


def test_lockfile_resolved_canonical_registry_safe(tmp_path: Path) -> None:
    """`resolved` pointing at registry.npmjs.org does NOT fire."""
    body = (
        '{\n  "packages": {\n'
        '    "node_modules/lodash": {\n'
        '      "resolved": "https://registry.npmjs.org/lodash/-/lodash-4.17.21.tgz"\n'
        '    }\n  }\n}\n'
    )
    assert not _hits(_scan(tmp_path, "package-lock.json", body),
                     "sbom-lockfile-resolved-non-registry")


def test_lockfile_resolved_internal_mirror_safe(tmp_path: Path) -> None:
    """An Artifactory / Nexus internal mirror is allowlisted."""
    body = (
        '{\n  "packages": {\n'
        '    "node_modules/lodash": {\n'
        '      "resolved": "https://artifactory.corp.example.com/npm/lodash-4.17.21.tgz"\n'
        '    }\n  }\n}\n'
    )
    assert not _hits(_scan(tmp_path, "package-lock.json", body),
                     "sbom-lockfile-resolved-non-registry")


def test_lockfile_resolved_yarnpkg_safe(tmp_path: Path) -> None:
    """`registry.yarnpkg.com` is in the allowlist."""
    body = '"resolved": "https://registry.yarnpkg.com/lodash/-/lodash-4.17.21.tgz"\n'
    assert not _hits(_scan(tmp_path, "package-lock.json", body),
                     "sbom-lockfile-resolved-non-registry")


# ---------- Rule 3: sbom-cargo-lock-replace-with -------------------------


def test_cargo_replace_with_third_party(tmp_path: Path) -> None:
    """`replace-with = "evil-mirror"` fires."""
    body = (
        '[source.crates-io]\n'
        'replace-with = "evil-mirror"\n'
        '\n'
        '[source.evil-mirror]\n'
        'registry = "https://evil.example.com/crates"\n'
    )
    assert _hits(_scan(tmp_path, "config.toml", body),
                 "sbom-cargo-lock-replace-with")


def test_cargo_replace_with_vendored_safe(tmp_path: Path) -> None:
    """`replace-with = "vendored-sources"` is the legit pattern."""
    body = (
        '[source.crates-io]\n'
        'replace-with = "vendored-sources"\n'
    )
    assert not _hits(_scan(tmp_path, "config.toml", body),
                     "sbom-cargo-lock-replace-with")


def test_cargo_replace_with_in_cargo_toml(tmp_path: Path) -> None:
    """Rule fires on Cargo.toml too, not just config.toml."""
    body = (
        '[source.crates-io]\n'
        'replace-with = "shady-mirror"\n'
    )
    assert _hits(_scan(tmp_path, "Cargo.toml", body),
                 "sbom-cargo-lock-replace-with")


# ---------- Rule 4: sbom-go-sum-disabled ---------------------------------


def test_go_gosumdb_off_fires(tmp_path: Path) -> None:
    body = (
        "jobs:\n"
        "  build:\n"
        "    env:\n"
        "      GOSUMDB: off\n"
        "    steps:\n"
        "      - run: GOSUMDB=off go build ./...\n"
    )
    assert _hits(_scan(tmp_path, "ci.yml", body), "sbom-go-sum-disabled")


def test_go_gonosumcheck_fires(tmp_path: Path) -> None:
    body = "  - run: GONOSUMCHECK=1 go test ./...\n"
    assert _hits(_scan(tmp_path, "ci.yml", body), "sbom-go-sum-disabled")


def test_go_proxy_direct_fallback_fires(tmp_path: Path) -> None:
    body = "  - run: GOPROXY=https://proxy.golang.org,direct go build\n"
    assert _hits(_scan(tmp_path, "ci.yml", body), "sbom-go-sum-disabled")


def test_go_flags_insecure_fires(tmp_path: Path) -> None:
    body = "  - run: GOFLAGS=-insecure go get example.com/pkg\n"
    assert _hits(_scan(tmp_path, "ci.yml", body), "sbom-go-sum-disabled")


def test_go_proxy_off_is_safe(tmp_path: Path) -> None:
    """`GOPROXY=…,off` is the secure shape — must NOT fire as `,direct`."""
    body = "  - run: GOPROXY=https://proxy.golang.org,off go build\n"
    assert not _hits(_scan(tmp_path, "ci.yml", body),
                     "sbom-go-sum-disabled")


def test_go_sumdb_explicit_safe(tmp_path: Path) -> None:
    """`GOSUMDB=sum.golang.org` does NOT fire."""
    body = "  - run: GOSUMDB=sum.golang.org go build\n"
    assert not _hits(_scan(tmp_path, "ci.yml", body),
                     "sbom-go-sum-disabled")


# ---------- Rule 5: sbom-cosign-cert-identity-too-broad ------------------


def test_cosign_cert_identity_universal_wildcard(tmp_path: Path) -> None:
    """`--certificate-identity-regexp '.*'` is universal."""
    body = "  - run: cosign verify --certificate-identity-regexp '.*' image\n"
    assert _hits(_scan(tmp_path, "verify.sh", body),
                 "sbom-cosign-cert-identity-too-broad")


def test_cosign_cert_identity_repo_wildcard(tmp_path: Path) -> None:
    """`https://github.com/owner/.*` matches any workflow in owner's repos."""
    body = (
        "  - run: cosign verify "
        "--certificate-identity-regexp 'https://github.com/owner/.*' image\n"
    )
    assert _hits(_scan(tmp_path, "verify.sh", body),
                 "sbom-cosign-cert-identity-too-broad")


def test_cosign_cert_identity_owner_repo_wildcard(tmp_path: Path) -> None:
    """`https://github.com/owner/repo/.*` matches any workflow file."""
    body = (
        '  - run: cosign verify '
        '--certificate-identity-regexp "https://github.com/owner/repo/.*" image\n'
    )
    assert _hits(_scan(tmp_path, "verify.sh", body),
                 "sbom-cosign-cert-identity-too-broad")


def test_cosign_cert_identity_specific_safe(tmp_path: Path) -> None:
    """A specific workflow+branch ref does NOT fire."""
    body = (
        "  - run: cosign verify "
        "--certificate-identity-regexp "
        "'^https://github.com/owner/repo/\\.github/workflows/publish\\.yml@refs/heads/main$' "
        "image\n"
    )
    assert not _hits(_scan(tmp_path, "verify.sh", body),
                     "sbom-cosign-cert-identity-too-broad")


# ---------- Rule 6: sbom-npm-provenance-digest-mismatch ------------------


def test_npm_provenance_digest_extractor() -> None:
    """The extractor returns the full set of sha256 digests."""
    text = '''
{"subject":[{"name":"pkg","digest":{"sha256":"abc123def4567890abcdef0123456789abcdef0123456789abcdef0123456789"}}]}
'''
    digests = stp.extract_npm_digest_set(text)
    assert digests == {
        "abc123def4567890abcdef0123456789abcdef0123456789abcdef0123456789",
    }


def test_npm_provenance_digest_mismatch_pair(tmp_path: Path) -> None:
    """Signed vs unsigned with divergent digests returns True."""
    sha_a = "a" * 64
    sha_b = "b" * 64
    signed = _write(tmp_path, "pkg.signed.intoto.jsonl",
                    '{"subject":[{"digest":{"sha256":"%s"}}]}' % sha_a)
    unsigned = _write(tmp_path, "pkg.unsigned.intoto.jsonl",
                      '{"subject":[{"digest":{"sha256":"%s"}}]}' % sha_b)
    assert stp.compare_npm_provenance_digests(signed, unsigned) is True


def test_npm_provenance_digest_match_pair(tmp_path: Path) -> None:
    """Matching digests on both sides returns False (no mismatch)."""
    sha_match = "c" * 64
    signed = _write(tmp_path, "pkg.signed.intoto.jsonl",
                    '{"subject":[{"digest":{"sha256":"%s"}}]}' % sha_match)
    unsigned = _write(tmp_path, "pkg.unsigned.intoto.jsonl",
                      '{"subject":[{"digest":{"sha256":"%s"}}]}' % sha_match)
    assert stp.compare_npm_provenance_digests(signed, unsigned) is False


def test_npm_provenance_digest_empty_side(tmp_path: Path) -> None:
    """Empty-digest side returns False (insufficient evidence)."""
    sha = "d" * 64
    signed = _write(tmp_path, "pkg.signed.intoto.jsonl",
                    '{"subject":[{"digest":{"sha256":"%s"}}]}' % sha)
    unsigned = _write(tmp_path, "pkg.unsigned.intoto.jsonl",
                      '{"no": "digest here"}')
    assert stp.compare_npm_provenance_digests(signed, unsigned) is False


# ---------- Rule 7: sbom-maven-checksum-policy-warn ----------------------


def test_maven_checksum_warn_fires(tmp_path: Path) -> None:
    body = (
        "<settings>\n"
        "  <mirrors>\n"
        "    <mirror>\n"
        "      <id>central</id>\n"
        "      <url>https://repo.example.com/</url>\n"
        "      <checksumPolicy>warn</checksumPolicy>\n"
        "    </mirror>\n"
        "  </mirrors>\n"
        "</settings>\n"
    )
    assert _hits(_scan(tmp_path, "settings.xml", body),
                 "sbom-maven-checksum-policy-warn")


def test_maven_checksum_fail_safe(tmp_path: Path) -> None:
    """Same file with `<checksumPolicy>fail</checksumPolicy>` suppresses."""
    body = (
        "<settings>\n"
        "  <mirror>\n"
        "    <checksumPolicy>fail</checksumPolicy>\n"
        "  </mirror>\n"
        "</settings>\n"
    )
    assert not _hits(_scan(tmp_path, "settings.xml", body),
                     "sbom-maven-checksum-policy-warn")


def test_maven_checksum_warn_in_pom_xml(tmp_path: Path) -> None:
    body = "<project><checksumPolicy>warn</checksumPolicy></project>\n"
    assert _hits(_scan(tmp_path, "pom.xml", body),
                 "sbom-maven-checksum-policy-warn")


# ---------- Rule 8: sbom-pom-classifier-version-mismatch -----------------


def test_pom_classifier_mismatch_extractor() -> None:
    """Extractor returns ([16], [11]) for a JDK16 classifier + Java 11."""
    text = (
        "<project>\n"
        "  <properties>\n"
        "    <java.version>11</java.version>\n"
        "  </properties>\n"
        "  <dependencies>\n"
        "    <dependency>\n"
        "      <classifier>jdk16</classifier>\n"
        "    </dependency>\n"
        "  </dependencies>\n"
        "</project>\n"
    )
    jdks, versions = stp.extract_pom_classifier_versions(text)
    assert jdks == [16]
    assert versions == [11]


def test_pom_classifier_mismatch_fires(tmp_path: Path) -> None:
    """A JDK16-classified dep with Java 11 declared fires."""
    body = (
        "<project>\n"
        "  <properties>\n"
        "    <maven.compiler.source>11</maven.compiler.source>\n"
        "    <maven.compiler.target>11</maven.compiler.target>\n"
        "  </properties>\n"
        "  <dependencies>\n"
        "    <dependency>\n"
        "      <groupId>com.example</groupId>\n"
        "      <classifier>jdk16</classifier>\n"
        "    </dependency>\n"
        "  </dependencies>\n"
        "</project>\n"
    )
    p = _write(tmp_path, "pom.xml", body)
    assert stp.scan_pom_classifier_mismatch(p)


def test_pom_classifier_match_safe(tmp_path: Path) -> None:
    """A JDK11-classified dep with Java 11 declared does NOT fire."""
    body = (
        "<project>\n"
        "  <properties>\n"
        "    <java.version>17</java.version>\n"
        "  </properties>\n"
        "  <dependencies>\n"
        "    <dependency>\n"
        "      <classifier>jdk11</classifier>\n"
        "    </dependency>\n"
        "  </dependencies>\n"
        "</project>\n"
    )
    p = _write(tmp_path, "pom.xml", body)
    assert not stp.scan_pom_classifier_mismatch(p)


def test_pom_classifier_no_classifier_safe(tmp_path: Path) -> None:
    """No classifier at all = no mismatch finding."""
    body = (
        "<project>\n"
        "  <properties>\n"
        "    <java.version>11</java.version>\n"
        "  </properties>\n"
        "</project>\n"
    )
    p = _write(tmp_path, "pom.xml", body)
    assert not stp.scan_pom_classifier_mismatch(p)


# ---------- Rule 9: sbom-cosign-blob-noverify ----------------------------


def test_cosign_verify_insecure_ignore_tlog(tmp_path: Path) -> None:
    body = "  - run: cosign verify --insecure-ignore-tlog image:tag\n"
    assert _hits(_scan(tmp_path, "verify.sh", body),
                 "sbom-cosign-blob-noverify")


def test_cosign_verify_insecure_skip_verify(tmp_path: Path) -> None:
    body = "  - run: cosign verify-blob --insecure-skip-verify --signature x.sig blob\n"
    assert _hits(_scan(tmp_path, "verify.sh", body),
                 "sbom-cosign-blob-noverify")


def test_cosign_experimental_env_fires(tmp_path: Path) -> None:
    body = (
        "jobs:\n"
        "  verify:\n"
        "    steps:\n"
        "      - run: COSIGN_EXPERIMENTAL=1 cosign verify image\n"
    )
    assert _hits(_scan(tmp_path, "verify.yml", body),
                 "sbom-cosign-blob-noverify")


def test_cosign_rekor_override_suppresses(tmp_path: Path) -> None:
    """`--rekor-url=` override turns ignore-tlog into a documented flow."""
    body = (
        "  - run: cosign verify --insecure-ignore-tlog "
        "--rekor-url=https://rekor.internal.example/ image:tag\n"
    )
    assert not _hits(_scan(tmp_path, "verify.sh", body),
                     "sbom-cosign-blob-noverify")


def test_cosign_verify_no_insecure_flag_safe(tmp_path: Path) -> None:
    body = "  - run: cosign verify image:tag\n"
    assert not _hits(_scan(tmp_path, "verify.sh", body),
                     "sbom-cosign-blob-noverify")


# ---------- Rule 10: sbom-spdx-license-stripped --------------------------


def test_spdx_stripped_dir_majority_has_header(tmp_path: Path) -> None:
    """When 2/3 siblings have SPDX, the bare one fires."""
    d = tmp_path / "src"
    d.mkdir()
    (d / "a.py").write_text(
        "# SPDX-License-Identifier: MIT\n\ndef a(): pass\n",
        encoding="utf-8",
    )
    (d / "b.py").write_text(
        "# SPDX-License-Identifier: MIT\n\ndef b(): pass\n",
        encoding="utf-8",
    )
    (d / "c.py").write_text(
        "# No license header\n\ndef c(): pass\n",
        encoding="utf-8",
    )
    findings = stp.scan_spdx_stripped_dir(d)
    # `c.py` should be flagged.
    flagged_names = {Path(f.file_path).name for f in findings}
    assert "c.py" in flagged_names


def test_spdx_stripped_dir_no_convention_safe(tmp_path: Path) -> None:
    """When no sibling has SPDX, no rule fires (no established convention)."""
    d = tmp_path / "src"
    d.mkdir()
    (d / "a.py").write_text("def a(): pass\n", encoding="utf-8")
    (d / "b.py").write_text("def b(): pass\n", encoding="utf-8")
    (d / "c.py").write_text("def c(): pass\n", encoding="utf-8")
    findings = stp.scan_spdx_stripped_dir(d)
    assert findings == []


def test_spdx_stripped_dir_all_have_header_safe(tmp_path: Path) -> None:
    """When every sibling has SPDX, no rule fires."""
    d = tmp_path / "src"
    d.mkdir()
    (d / "a.py").write_text(
        "# SPDX-License-Identifier: MIT\ndef a(): pass\n",
        encoding="utf-8",
    )
    (d / "b.py").write_text(
        "# SPDX-License-Identifier: MIT\ndef b(): pass\n",
        encoding="utf-8",
    )
    findings = stp.scan_spdx_stripped_dir(d)
    assert findings == []


def test_spdx_stripped_dir_too_few_candidates_safe(tmp_path: Path) -> None:
    """A directory with only one source file yields no findings."""
    d = tmp_path / "src"
    d.mkdir()
    (d / "lonely.py").write_text("def lonely(): pass\n", encoding="utf-8")
    findings = stp.scan_spdx_stripped_dir(d)
    assert findings == []


# ---------- Rule 11: sbom-frozen-lockfile-skip-on-publish ----------------


def test_frozen_lockfile_skip_npm_publish(tmp_path: Path) -> None:
    """`npm install` (no flag) in a publish job fires."""
    body = (
        "jobs:\n"
        "  publish:\n"
        "    steps:\n"
        "      - run: npm install\n"
        "      - run: npm publish\n"
    )
    assert _hits(_scan(tmp_path, "publish.yml", body),
                 "sbom-frozen-lockfile-skip-on-publish")


def test_frozen_lockfile_skip_pnpm_publish(tmp_path: Path) -> None:
    body = (
        "jobs:\n"
        "  publish:\n"
        "    steps:\n"
        "      - run: pnpm install\n"
        "      - run: pnpm publish\n"
    )
    assert _hits(_scan(tmp_path, "publish.yml", body),
                 "sbom-frozen-lockfile-skip-on-publish")


def test_frozen_lockfile_safe_with_frozen_flag(tmp_path: Path) -> None:
    """`pnpm install --frozen-lockfile` is the safe shape."""
    body = (
        "jobs:\n"
        "  publish:\n"
        "    steps:\n"
        "      - run: pnpm install --frozen-lockfile\n"
        "      - run: pnpm publish\n"
    )
    assert not _hits(_scan(tmp_path, "publish.yml", body),
                     "sbom-frozen-lockfile-skip-on-publish")


def test_frozen_lockfile_safe_no_publisher(tmp_path: Path) -> None:
    """Without a publisher token, the install line does NOT fire."""
    body = (
        "jobs:\n"
        "  test:\n"
        "    steps:\n"
        "      - run: npm install\n"
        "      - run: npm test\n"
    )
    # No publish token → publisher gate suppresses the rule.
    assert not _hits(_scan(tmp_path, "test.yml", body),
                     "sbom-frozen-lockfile-skip-on-publish")


def test_frozen_lockfile_pip_require_hashes_safe(tmp_path: Path) -> None:
    """`pip install --require-hashes` is the safe shape."""
    body = (
        "jobs:\n"
        "  publish:\n"
        "    steps:\n"
        "      - run: pip install --require-hashes -r requirements.txt\n"
        "      - run: twine upload dist/*\n"
    )
    assert not _hits(_scan(tmp_path, "publish.yml", body),
                     "sbom-frozen-lockfile-skip-on-publish")


# ---------- Rule 12: sbom-source-date-epoch-mismatch ---------------------


def test_sde_zero_fires(tmp_path: Path) -> None:
    """`SOURCE_DATE_EPOCH=0` is the canonical defeats-determinism value."""
    body = "  - run: SOURCE_DATE_EPOCH=0 make release\n"
    assert _hits(_scan(tmp_path, "build.sh", body),
                 "sbom-source-date-epoch-mismatch")


def test_sde_canonical_test_value_fires(tmp_path: Path) -> None:
    """`SOURCE_DATE_EPOCH=1234567890` is the canonical test value."""
    body = "  - run: SOURCE_DATE_EPOCH=1234567890 make release\n"
    assert _hits(_scan(tmp_path, "build.sh", body),
                 "sbom-source-date-epoch-mismatch")


def test_sde_small_int_fires(tmp_path: Path) -> None:
    """5-digit value (<2001-09-09 unix epoch) fires."""
    body = "  - run: SOURCE_DATE_EPOCH=12345 make release\n"
    assert _hits(_scan(tmp_path, "build.sh", body),
                 "sbom-source-date-epoch-mismatch")


def test_sde_git_derived_safe(tmp_path: Path) -> None:
    """`SOURCE_DATE_EPOCH=$(git log -1 --format=%ct)` is the legit shape."""
    body = "  - run: SOURCE_DATE_EPOCH=$(git log -1 --format=%ct) make release\n"
    # Even if the regex matches an integer elsewhere, the git-log guard
    # substring in the same file suppresses the rule.
    assert not _hits(_scan(tmp_path, "build.sh", body),
                     "sbom-source-date-epoch-mismatch")


def test_sde_modern_epoch_safe(tmp_path: Path) -> None:
    """A 10-digit value (>= 2001-09-09) does NOT fire."""
    # 1700000000 = 2023-11-14 UTC, 10 digits → plausible.
    body = "  - run: SOURCE_DATE_EPOCH=1700000000 make release\n"
    assert not _hits(_scan(tmp_path, "build.sh", body),
                     "sbom-source-date-epoch-mismatch")


# ---------- Rule 13: sbom-release-from-non-tag-ref -----------------------


def test_release_branch_ref_fires(tmp_path: Path) -> None:
    body = (
        "jobs:\n"
        "  release:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          ref: main\n"
    )
    assert _hits(_scan(tmp_path, "release.yml", body),
                 "sbom-release-from-non-tag-ref")


def test_release_tag_ref_safe(tmp_path: Path) -> None:
    """`ref: refs/tags/...` is the safe shape — suppresses the rule."""
    body = (
        "jobs:\n"
        "  release:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          ref: refs/tags/v1.2.3\n"
    )
    assert not _hits(_scan(tmp_path, "release.yml", body),
                     "sbom-release-from-non-tag-ref")


def test_release_github_event_release_tag_name_safe(tmp_path: Path) -> None:
    """`ref: ${{ github.event.release.tag_name }}` is also the safe shape."""
    body = (
        "jobs:\n"
        "  release:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          ref: ${{ github.event.release.tag_name }}\n"
    )
    assert not _hits(_scan(tmp_path, "release.yml", body),
                     "sbom-release-from-non-tag-ref")


def test_release_publish_job_with_master_fires(tmp_path: Path) -> None:
    body = (
        "jobs:\n"
        "  publish:\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "        with:\n"
        "          ref: master\n"
    )
    assert _hits(_scan(tmp_path, "publish.yml", body),
                 "sbom-release-from-non-tag-ref")


# ---------- Rule 14: sbom-license-file-mit-but-vendor-gpl ----------------


def test_license_mit_but_vendor_gpl_fires(tmp_path: Path) -> None:
    """MIT root LICENSE + GPL source file → MAJOR."""
    # Top-level MIT LICENSE.
    (tmp_path / "LICENSE").write_text(
        "MIT License\n\nPermission is hereby granted, free of charge\n",
        encoding="utf-8",
    )
    # GPL-tagged source file in subdirectory.
    sub = tmp_path / "vendored"
    sub.mkdir()
    (sub / "thing.py").write_text(
        "# SPDX-License-Identifier: GPL-3.0\n\ndef thing(): pass\n",
        encoding="utf-8",
    )
    findings = stp.scan_license_mit_vendor_gpl(tmp_path)
    assert findings
    assert findings[0].rule_id == "sbom-license-file-mit-but-vendor-gpl"


def test_license_mit_only_safe(tmp_path: Path) -> None:
    """MIT root LICENSE with no GPL anywhere does NOT fire."""
    (tmp_path / "LICENSE").write_text(
        "MIT License\n\nPermission is hereby granted, free of charge\n",
        encoding="utf-8",
    )
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "ok.py").write_text(
        "# SPDX-License-Identifier: MIT\n\ndef ok(): pass\n",
        encoding="utf-8",
    )
    assert not stp.scan_license_mit_vendor_gpl(tmp_path)


def test_license_no_mit_root_safe(tmp_path: Path) -> None:
    """No MIT at root → no rule fires even if GPL is somewhere."""
    (tmp_path / "README.md").write_text("# Project\n", encoding="utf-8")
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "gpl.py").write_text(
        "# SPDX-License-Identifier: GPL-3.0\ndef x(): pass\n",
        encoding="utf-8",
    )
    assert not stp.scan_license_mit_vendor_gpl(tmp_path)


def test_license_gpl_preamble_fires(tmp_path: Path) -> None:
    """The GPL preamble (not just SPDX) is also a GPL marker."""
    (tmp_path / "LICENSE").write_text(
        "MIT License\n\nPermission is hereby granted, free of charge\n",
        encoding="utf-8",
    )
    sub = tmp_path / "vendored"
    sub.mkdir()
    (sub / "thing.c").write_text(
        "/* This program is free software: you can redistribute it under "
        "the GNU General Public License version 3 */\n",
        encoding="utf-8",
    )
    assert stp.scan_license_mit_vendor_gpl(tmp_path)


# ---------- Rule 15: sbom-helm-chart-lock-digest-missing -----------------


def test_helm_chart_lock_missing_digest_fires(tmp_path: Path) -> None:
    body = (
        "dependencies:\n"
        "- name: postgresql\n"
        "  repository: https://charts.bitnami.com/bitnami\n"
        "  version: 12.0.0\n"
        "digest: sha256:abc\n"
        "generated: 2026-05-27\n"
    )
    p = _write(tmp_path, "Chart.lock", body)
    findings = stp.scan_helm_chart_lock_missing_digests(p)
    assert findings


def test_helm_chart_lock_with_digest_safe(tmp_path: Path) -> None:
    sha = "a" * 64
    body = (
        "dependencies:\n"
        f"- name: postgresql\n"
        f"  repository: https://charts.bitnami.com/bitnami\n"
        f"  version: 12.0.0\n"
        f"  digest: sha256:{sha}\n"
    )
    p = _write(tmp_path, "Chart.lock", body)
    findings = stp.scan_helm_chart_lock_missing_digests(p)
    assert findings == []


def test_helm_chart_lock_mixed_deps(tmp_path: Path) -> None:
    """One dep with digest, one without → one finding."""
    sha = "b" * 64
    body = (
        "dependencies:\n"
        f"- name: postgresql\n"
        f"  repository: https://charts.bitnami.com/bitnami\n"
        f"  version: 12.0.0\n"
        f"  digest: sha256:{sha}\n"
        f"- name: redis\n"
        f"  repository: https://charts.bitnami.com/bitnami\n"
        f"  version: 17.0.0\n"
    )
    p = _write(tmp_path, "Chart.lock", body)
    findings = stp.scan_helm_chart_lock_missing_digests(p)
    assert len(findings) == 1


# ---------- scan_file() invariants ---------------------------------------


def test_scan_file_missing_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "does-not-exist.yml"
    assert stp.scan_file(p) == []


def test_scan_file_empty_returns_empty(tmp_path: Path) -> None:
    p = _write(tmp_path, "empty.yml", "")
    assert stp.scan_file(p) == []


def test_scan_file_filters_by_suffix(tmp_path: Path) -> None:
    """A `.go-sum-bypass` line in a `.json` file does NOT fire (wrong suffix)."""
    body = "GOSUMDB=off\n"
    p = _write(tmp_path, "config.json", body)
    findings = stp.scan_file(p)
    # `.json` is not in Rule 4's file_suffixes → no go-sum hits.
    assert all(f.rule_id != "sbom-go-sum-disabled" for f in findings)


def test_scan_file_carries_full_path(tmp_path: Path) -> None:
    body = '{"components":[]}\n'
    p = _write(tmp_path, "bom.json", body)
    findings = stp.scan_file(p)
    assert findings
    assert findings[0].file_path == str(p)


def test_scan_file_sorted_by_line_col_ruleid(tmp_path: Path) -> None:
    body = (
        "jobs:\n"
        "  publish:\n"
        "    steps:\n"
        "      - run: cosign verify --insecure-ignore-tlog image\n"
        "      - run: COSIGN_EXPERIMENTAL=1 cosign verify image\n"
    )
    p = _write(tmp_path, "verify.yml", body)
    findings = stp.scan_file(p)
    lines = [(f.line, f.column, f.rule_id) for f in findings]
    assert lines == sorted(lines)


def test_scan_file_long_match_truncated(tmp_path: Path) -> None:
    """matched_text capped at 200 + ellipsis.

    Note: the regex caps the URL capture at 400 chars, so the test
    needs a URL just under that limit to actually hit the matched_text
    truncation step (which trims at 200 chars).
    """
    # 25 chars host prefix + 350 path chars = 375 chars URL, within
    # the regex's {1,400} bound. Final matched text is the whole
    # `"resolved": "..."` string (~390 chars), which exceeds 200 and
    # triggers the truncation branch.
    big = '"resolved": "' + "https://evil.example.com/" + "x" * 350 + '"\n'
    p = _write(tmp_path, "package-lock.json", big)
    findings = stp.scan_file(p)
    hits = _hits(findings, "sbom-lockfile-resolved-non-registry")
    assert hits
    assert len(hits[0].matched_text) <= 201
    assert hits[0].matched_text.endswith("…")


def test_scan_file_line_col_one_based(tmp_path: Path) -> None:
    body = (
        "header line\n"
        '{"components":[]}\n'
    )
    p = _write(tmp_path, "bom.json", body)
    findings = stp.scan_file(p)
    hits = _hits(findings, "sbom-cyclonedx-empty-components")
    assert hits
    assert hits[0].line == 2  # Second line


def test_scan_file_composite_rules_not_routed(tmp_path: Path) -> None:
    """Composite rules must NOT emit findings via scan_file (use the
    composite helper instead).

    Even when the regex content matches, scan_file skips composite
    rules. This protects callers from getting duplicate findings.
    """
    # Empty SPDX-stripped surface: a single source file with no SPDX
    # would NOT fire via scan_file (rule is composite).
    body = "def x(): pass\n"
    p = _write(tmp_path, "thing.py", body)
    findings = stp.scan_file(p)
    assert all(f.rule_id != "sbom-spdx-license-stripped" for f in findings)
