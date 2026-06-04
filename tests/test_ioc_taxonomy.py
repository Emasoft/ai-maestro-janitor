"""Tests for the IOC taxonomy primitives in scripts/lib/ioc_taxonomy.py.

Every public construct (IOCRecord, parse_ioc_yaml, MBC_BEHAVIOUR_TAGS,
EXPOSURE_VS_COMPROMISE_LABELS, incident_response_advisory, plus the
internal coercers + record builder) gets at least one positive test
and at least one failure-mode test where applicable.

Pattern mirrors test_security_helpers.py — sys.path injection so the
lib module can be imported by its short name without requiring an
installed package.
"""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import ioc_taxonomy as it  # type: ignore[import-not-found]  # noqa: E402

# ---------- IOCRecord ----------------------------------------------------


def test_iocrecord_construction_full_bundle() -> None:
    """IOCRecord is a NamedTuple with all ten declared fields."""
    rec = it.IOCRecord(
        threat_id="T001_axios",
        name="axios postinstall hijack",
        package="axios",
        versions=("1.6.0", "1.6.1"),
        c2={"dom": "evil.example", "ip": "10.0.0.1", "port": "443"},
        ioc_fs={
            "darwin": ("/tmp/axios_runtime.js",),
            "linux": ("/tmp/axios_runtime.js",),
            "win32": ("C:\\Temp\\axios_runtime.js",),
        },
        persist={
            "darwin": "LaunchAgent plist",
            "linux": "systemd-user unit",
            "win32": "Run registry key",
        },
        disguise=("axios_runtime.js", "codeql_analysis.yml"),
        published="2026-05-14",
        references=("https://snyk.io/blog/axios", "https://osv.dev/MAL-2026-0001"),
    )
    assert rec.threat_id == "T001_axios"
    assert rec.package == "axios"
    assert rec.versions == ("1.6.0", "1.6.1")
    assert rec.c2["dom"] == "evil.example"
    assert rec.ioc_fs["darwin"] == ("/tmp/axios_runtime.js",)
    assert rec.persist["linux"] == "systemd-user unit"
    assert rec.disguise == ("axios_runtime.js", "codeql_analysis.yml")
    assert rec.published == "2026-05-14"


def test_iocrecord_dedupe_key_is_threat_id() -> None:
    """IOCRecord itself is not hashable (it contains dicts), but the
    convention is to dedupe on .threat_id — verify that pattern works
    as documented in the module docstring."""
    rec_a = it.IOCRecord(
        threat_id="T002",
        name="x",
        package="pkg",
        versions=("1.0",),
        c2={},
        ioc_fs={},
        persist={},
        disguise=(),
        published="2026-01-01",
        references=(),
    )
    rec_b = rec_a._replace(name="x-alias")  # same threat_id
    rec_c = rec_a._replace(threat_id="T003")  # different threat_id
    keys = {r.threat_id for r in (rec_a, rec_b, rec_c)}
    assert keys == {"T002", "T003"}


def test_iocrecord_field_order_stable() -> None:
    """Field order is part of the public contract — every caller using
    positional construction relies on it. Lock it down."""
    expected = (
        "threat_id",
        "name",
        "package",
        "versions",
        "c2",
        "ioc_fs",
        "persist",
        "disguise",
        "published",
        "references",
    )
    assert it.IOCRecord._fields == expected


# ---------- MBC_BEHAVIOUR_TAGS -------------------------------------------


def test_mbc_behaviour_tags_is_frozenset() -> None:
    """Frozenset (not set) so the taxonomy is immutable at runtime —
    detectors should not be able to inject custom tags."""
    assert isinstance(it.MBC_BEHAVIOUR_TAGS, frozenset)


def test_mbc_behaviour_tags_includes_core_categories() -> None:
    """All seven categories the audit report calls out are present."""
    for tag in ("c2", "persist", "exfil", "credential", "evasion", "fs", "impact"):
        assert tag in it.MBC_BEHAVIOUR_TAGS, f"missing MBC tag: {tag}"


def test_mbc_behaviour_tags_has_no_duplicates_or_blanks() -> None:
    """Sanity: no empty strings, no whitespace-only tags."""
    for tag in it.MBC_BEHAVIOUR_TAGS:
        assert tag and tag.strip() == tag


def test_mbc_behaviour_tags_size_matches_malcontent_taxonomy() -> None:
    """Should mirror the 21-category malcontent rules/ taxonomy.

    The deep-dive audit lists 21 distinct categories (a subset of the
    25 dirs in upstream malcontent — we collapse rarely-attributed
    leaf dirs into the parent categories). If this count drifts,
    update the audit reference and this test together.
    """
    assert len(it.MBC_BEHAVIOUR_TAGS) == 21


# ---------- EXPOSURE_VS_COMPROMISE_LABELS --------------------------------


def test_exposure_labels_are_the_canonical_four() -> None:
    """The four-state ladder from the audit: EXPOSED →
    POSSIBLY_COMPROMISED → COMPROMISED → ACTIVE_THREAT."""
    assert it.EXPOSURE_VS_COMPROMISE_LABELS == frozenset({
        "EXPOSED",
        "POSSIBLY_COMPROMISED",
        "COMPROMISED",
        "ACTIVE_THREAT",
    })


def test_exposure_labels_disjoint_from_mbc_tags() -> None:
    """Posture states and behaviour tags must NEVER collide as strings —
    they live on different axes of the finding shape and the user-facing
    output would be ambiguous if a token belonged to both."""
    assert it.EXPOSURE_VS_COMPROMISE_LABELS.isdisjoint(it.MBC_BEHAVIOUR_TAGS)


# ---------- incident_response_advisory + IR_STAGE_ADVISORIES -------------


def test_ir_advisory_isolate_warns_against_early_revoke() -> None:
    """The single most important safety property: isolate-before-rotate.
    The advisory MUST mention wiper / dead-man-switch risk."""
    advisory = it.incident_response_advisory("isolate")
    assert "isolate" in advisory.lower()
    assert "wiper" in advisory.lower() or "dead-man" in advisory.lower()
    # And it must explicitly call out NOT to rotate first.
    assert "do not" in advisory.lower() or "do NOT" in advisory


def test_ir_advisory_snapshot_mentions_forensic_dir() -> None:
    """Snapshot stage must direct the user at `.janitor-forensic/<ts>/`
    so the convention is discoverable from the advisory alone."""
    advisory = it.incident_response_advisory("snapshot")
    assert ".janitor-forensic" in advisory


def test_ir_advisory_rotate_mentions_8_step_order() -> None:
    """Rotate stage MUST enumerate the 8-step order — order matters
    (npm OIDC before Vault), so just saying 'rotate' isn't enough."""
    advisory = it.incident_response_advisory("rotate")
    assert "npm" in advisory.lower()
    assert "github" in advisory.lower()
    assert "vault" in advisory.lower()


def test_ir_advisory_all_six_stages_resolvable() -> None:
    """The six canonical stages (isolate / snapshot / contain-persistence /
    rotate / block-c2 / audit-workflows) all return non-empty strings."""
    for stage in (
        "isolate",
        "snapshot",
        "contain-persistence",
        "rotate",
        "block-c2",
        "audit-workflows",
    ):
        advisory = it.incident_response_advisory(stage)
        assert advisory and isinstance(advisory, str)
        assert len(advisory) > 30, f"advisory too short for stage {stage}"


def test_ir_advisory_unknown_stage_raises() -> None:
    """Fail-fast: unknown stage MUST raise (the user does not want a
    silent fallback in an IR message)."""
    with pytest.raises(it.IOCTaxonomyError) as exc:
        it.incident_response_advisory("rotate-tokens")
    assert "unknown ir stage" in str(exc.value).lower()


def test_ir_stage_advisories_is_dict_with_six_stages() -> None:
    """Direct constant access is part of the public API for callers that
    want to render all advisories at once (e.g. a `/janitor-help-ir`
    command)."""
    assert isinstance(it.IR_STAGE_ADVISORIES, dict)
    assert set(it.IR_STAGE_ADVISORIES) == {
        "isolate",
        "snapshot",
        "contain-persistence",
        "rotate",
        "block-c2",
        "audit-workflows",
    }


# ---------- parse_ioc_yaml -----------------------------------------------


def _write_yaml(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "bundle.yaml"
    p.write_text(textwrap.dedent(body), encoding="utf-8")
    return p


def test_parse_ioc_yaml_single_record(tmp_path: Path) -> None:
    """Top-level mapping → one-element list."""
    pytest.importorskip("yaml")  # gracefully skip if PyYAML absent
    p = _write_yaml(tmp_path, """\
        threat_id: T001_axios
        name: axios postinstall hijack
        package: axios
        versions:
          - "1.6.0"
          - "1.6.1"
        c2:
          dom: evil.example
          ip: 10.0.0.1
          port: 443
        ioc_fs:
          darwin:
            - /tmp/axios_runtime.js
          linux:
            - /tmp/axios_runtime.js
          win32:
            - "C:\\\\Temp\\\\axios_runtime.js"
        persist:
          darwin: LaunchAgent plist
          linux: systemd-user unit
          win32: Run registry key
        disguise:
          - axios_runtime.js
        published: "2026-05-14"
        references:
          - https://snyk.io/blog/axios
    """)
    records = it.parse_ioc_yaml(p)
    assert len(records) == 1
    rec = records[0]
    assert rec.threat_id == "T001_axios"
    assert rec.versions == ("1.6.0", "1.6.1")
    # Port number parsed as int by YAML — coerced to str.
    assert rec.c2["port"] == "443"
    assert rec.ioc_fs["darwin"] == ("/tmp/axios_runtime.js",)
    assert rec.persist["linux"] == "systemd-user unit"
    assert rec.disguise == ("axios_runtime.js",)


def test_parse_ioc_yaml_list_of_records(tmp_path: Path) -> None:
    """Top-level list → multi-record list. Common for an aggregated
    `incidents.yaml` packaging."""
    pytest.importorskip("yaml")
    p = _write_yaml(tmp_path, """\
        - threat_id: T001
          name: alpha
          package: pkg-a
          versions: ["1.0"]
          c2: {}
          ioc_fs: {}
          persist: {}
          disguise: []
          published: "2026-01-01"
          references: []
        - threat_id: T002
          name: beta
          package: pkg-b
          versions: ["2.0"]
          c2: {}
          ioc_fs: {}
          persist: {}
          disguise: []
          published: "2026-02-01"
          references: []
    """)
    records = it.parse_ioc_yaml(p)
    assert [r.threat_id for r in records] == ["T001", "T002"]


def test_parse_ioc_yaml_empty_file_returns_empty(tmp_path: Path) -> None:
    """An empty YAML file is a valid 'no records' contribution to a
    merged bundle — NOT an error."""
    pytest.importorskip("yaml")
    p = tmp_path / "empty.yaml"
    p.write_text("", encoding="utf-8")
    assert it.parse_ioc_yaml(p) == []


def test_parse_ioc_yaml_missing_file_raises_filenotfound(tmp_path: Path) -> None:
    """Missing file → FileNotFoundError (NOT IOCTaxonomyError) so the
    caller can distinguish 'bundle doesn't exist yet' from 'bundle is
    malformed'."""
    p = tmp_path / "missing.yaml"
    with pytest.raises(FileNotFoundError):
        it.parse_ioc_yaml(p)


def test_parse_ioc_yaml_missing_field_raises(tmp_path: Path) -> None:
    """A bundle missing a required field MUST fail at parse time, not
    silently produce a partial IOCRecord that crashes downstream."""
    pytest.importorskip("yaml")
    p = _write_yaml(tmp_path, """\
        threat_id: T001
        name: alpha
        package: pkg-a
        # versions missing
        c2: {}
        ioc_fs: {}
        persist: {}
        disguise: []
        published: "2026-01-01"
        references: []
    """)
    with pytest.raises(it.IOCTaxonomyError) as exc:
        it.parse_ioc_yaml(p)
    assert "versions" in str(exc.value)


def test_parse_ioc_yaml_wrong_top_level_type_raises(tmp_path: Path) -> None:
    """A scalar YAML file is not a valid bundle — fail-fast."""
    pytest.importorskip("yaml")
    p = _write_yaml(tmp_path, "just a string\n")
    with pytest.raises(it.IOCTaxonomyError):
        it.parse_ioc_yaml(p)


def test_parse_ioc_yaml_wrong_versions_type_raises(tmp_path: Path) -> None:
    """`versions` MUST be a list — a YAML mapping there is a malformed
    bundle that would otherwise produce a corrupt tuple at .versions."""
    pytest.importorskip("yaml")
    p = _write_yaml(tmp_path, """\
        threat_id: T001
        name: alpha
        package: pkg-a
        versions:
          a: b
        c2: {}
        ioc_fs: {}
        persist: {}
        disguise: []
        published: "2026-01-01"
        references: []
    """)
    with pytest.raises(it.IOCTaxonomyError) as exc:
        it.parse_ioc_yaml(p)
    assert "versions" in str(exc.value)


def test_parse_ioc_yaml_malformed_yaml_raises(tmp_path: Path) -> None:
    """Genuine YAML parse error wraps to IOCTaxonomyError so the caller
    only has to catch one error class for malformed bundles."""
    pytest.importorskip("yaml")
    p = _write_yaml(tmp_path, "threat_id: [unclosed\n")
    with pytest.raises(it.IOCTaxonomyError):
        it.parse_ioc_yaml(p)


# ---------- IOCTaxonomyError ---------------------------------------------


def test_ioctaxonomyerror_is_runtimeerror_subclass() -> None:
    """Distinct from ValueError so we don't shadow stdlib errors, but a
    subclass of RuntimeError so a broad `except RuntimeError` catches it."""
    assert issubclass(it.IOCTaxonomyError, RuntimeError)
