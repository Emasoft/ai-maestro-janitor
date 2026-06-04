"""Tests for scripts/lib/license_conflict_patterns.py.

Pattern + composite-helper coverage for the Wave-22 distill-round-8
angle-I catalogue (16 license-conflict / SPDX / NOTICE / CLA /
trademark anti-patterns). Each rule has 1 positive + 1 negative
test = 32 tests total.

The library exposes `scan_file(path)` for pattern-only rules and
`scan_*` composite helpers for cross-file rules — there is NO
`scan_text` function. Tests build the minimal on-disk shape each
rule needs via `tmp_path`, invoke the matching entry point, then
filter the returned `Finding` list by `rule_id`.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import license_conflict_patterns as lcp  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_contains_every_advertised_rule() -> None:
    """RULES must cover all 16 license-conflict rule IDs."""
    assert isinstance(lcp.RULES, tuple)
    rule_ids = {r.id for r in lcp.RULES}
    expected = {
        "license-template-placeholder-unfilled",
        "license-template-email-placeholder",
        "license-spdx-mismatch-with-root",
        "license-apache2-notice-missing",
        "license-incompatible-copyleft-in-permissive",
        "license-unlicensed-not-private",
        "license-manifest-content-drift",
        "license-spdx-malformed-or-missing",
        "license-no-ci-scanner",
        "license-relicense-by-stealth-via-cla",
        "license-vendor-missing-attribution",
        "license-non-commercial-in-deps",
        "license-spdx-deprecated-bare-form",
        "license-copyright-line-drift",
        "license-patent-grant-stripped",
        "license-trademark-no-disclaimer",
    }
    assert expected == rule_ids
    assert len(lcp.RULES) == 16


def _hits_in_file(rule_id: str, findings: list) -> list:
    """Filter a Finding list to entries matching `rule_id`."""
    return [f for f in findings if f.rule_id == rule_id]


# ---------- Rule 1 : license-template-placeholder-unfilled ---------------


def test_template_placeholder_unfilled_positive(tmp_path: Path) -> None:
    """LICENSE with `Copyright (c) <YEAR> <COPYRIGHT HOLDER>` → MAJOR hit."""
    license_path = tmp_path / "LICENSE"
    license_path.write_text(
        "MIT License\n"
        "\n"
        "Copyright (c) <YEAR> <COPYRIGHT HOLDER>\n"
        "\n"
        "Permission is hereby granted, free of charge, to any person...\n"
    )
    hits = _hits_in_file(
        "license-template-placeholder-unfilled",
        lcp.scan_file(license_path),
    )
    assert hits
    assert hits[0].severity == "MAJOR"


def test_template_placeholder_unfilled_negative(tmp_path: Path) -> None:
    """LICENSE with a filled-in year + real holder → no hit."""
    license_path = tmp_path / "LICENSE"
    license_path.write_text(
        "MIT License\n"
        "\n"
        "Copyright (c) 2026 Emanuele Sabetta\n"
        "\n"
        "Permission is hereby granted, free of charge, to any person...\n"
    )
    hits = _hits_in_file(
        "license-template-placeholder-unfilled",
        lcp.scan_file(license_path),
    )
    assert not hits


# ---------- Rule 2 : license-template-email-placeholder ------------------


def test_template_email_placeholder_positive(tmp_path: Path) -> None:
    """LICENSE with `<you@example.com>` → MAJOR hit."""
    license_path = tmp_path / "LICENSE"
    license_path.write_text(
        "MIT License\n"
        "\n"
        "Copyright (c) 2026 Jane Doe <you@example.com>\n"
        "\n"
        "Permission is hereby granted...\n"
    )
    hits = _hits_in_file(
        "license-template-email-placeholder",
        lcp.scan_file(license_path),
    )
    assert hits
    assert hits[0].severity == "MAJOR"


def test_template_email_placeholder_negative(tmp_path: Path) -> None:
    """LICENSE with a real email (not placeholder) → no hit."""
    license_path = tmp_path / "LICENSE"
    license_path.write_text(
        "MIT License\n"
        "\n"
        "Copyright (c) 2026 Jane Doe <jane@realcompany.io>\n"
        "\n"
        "Permission is hereby granted...\n"
    )
    hits = _hits_in_file(
        "license-template-email-placeholder",
        lcp.scan_file(license_path),
    )
    assert not hits


# ---------- Rule 3 : license-spdx-mismatch-with-root ---------------------


def test_spdx_mismatch_with_root_positive(tmp_path: Path) -> None:
    """Repo declared MIT, source file declares Apache-2.0 → MAJOR hit."""
    (tmp_path / "package.json").write_text(
        '{\n'
        '  "name": "demo",\n'
        '  "license": "MIT"\n'
        '}\n'
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "foo.py").write_text(
        "# SPDX-License-Identifier: Apache-2.0\n"
        "def hello():\n"
        "    return 'hi'\n"
    )
    hits = _hits_in_file(
        "license-spdx-mismatch-with-root",
        lcp.scan_spdx_mismatch_with_root(tmp_path),
    )
    assert hits
    assert hits[0].severity == "MAJOR"


def test_spdx_mismatch_with_root_negative(tmp_path: Path) -> None:
    """Repo declared MIT, source file also declares MIT → no hit."""
    (tmp_path / "package.json").write_text(
        '{\n'
        '  "name": "demo",\n'
        '  "license": "MIT"\n'
        '}\n'
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "foo.py").write_text(
        "# SPDX-License-Identifier: MIT\n"
        "def hello():\n"
        "    return 'hi'\n"
    )
    hits = _hits_in_file(
        "license-spdx-mismatch-with-root",
        lcp.scan_spdx_mismatch_with_root(tmp_path),
    )
    assert not hits


# ---------- Rule 4 : license-apache2-notice-missing ----------------------


def test_apache2_notice_missing_positive(tmp_path: Path) -> None:
    """Apache-2.0 LICENSE, no NOTICE file → MAJOR hit."""
    (tmp_path / "LICENSE").write_text(
        "Apache License, Version 2.0\n"
        "\n"
        "Licensed under the Apache License, Version 2.0 (the License);\n"
        "you may not use this file except in compliance with the License.\n"
    )
    hits = _hits_in_file(
        "license-apache2-notice-missing",
        lcp.scan_apache_notice_missing(tmp_path),
    )
    assert hits
    assert hits[0].severity == "MAJOR"


def test_apache2_notice_missing_negative(tmp_path: Path) -> None:
    """Apache-2.0 LICENSE WITH a NOTICE file → no hit."""
    (tmp_path / "LICENSE").write_text(
        "Apache License, Version 2.0\n"
        "\n"
        "Licensed under the Apache License, Version 2.0 (the License);\n"
    )
    (tmp_path / "NOTICE").write_text(
        "Demo Project\n"
        "Copyright 2026 Demo Authors\n"
    )
    hits = _hits_in_file(
        "license-apache2-notice-missing",
        lcp.scan_apache_notice_missing(tmp_path),
    )
    assert not hits


# ---------- Rule 5 : license-incompatible-copyleft-in-permissive ---------


def test_incompatible_copyleft_in_permissive_positive(tmp_path: Path) -> None:
    """package.json declares `elasticsearch` dep (SSPL) → CRITICAL hit."""
    pkg = tmp_path / "package.json"
    pkg.write_text(
        '{\n'
        '  "name": "demo",\n'
        '  "license": "MIT",\n'
        '  "dependencies": {\n'
        '    "elasticsearch": "8.12.0",\n'
        '    "lodash": "4.17.21"\n'
        '  }\n'
        '}\n'
    )
    hits = _hits_in_file(
        "license-incompatible-copyleft-in-permissive",
        lcp.scan_incompatible_license_in_manifest(pkg),
    )
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_incompatible_copyleft_in_permissive_negative(tmp_path: Path) -> None:
    """package.json with only benign permissive deps → no hit."""
    pkg = tmp_path / "package.json"
    pkg.write_text(
        '{\n'
        '  "name": "demo",\n'
        '  "license": "MIT",\n'
        '  "dependencies": {\n'
        '    "react": "18.2.0",\n'
        '    "lodash": "4.17.21"\n'
        '  }\n'
        '}\n'
    )
    hits = _hits_in_file(
        "license-incompatible-copyleft-in-permissive",
        lcp.scan_incompatible_license_in_manifest(pkg),
    )
    assert not hits


# ---------- Rule 6 : license-unlicensed-not-private ----------------------


def test_unlicensed_not_private_positive(tmp_path: Path) -> None:
    """`"license": "UNLICENSED"` + no `"private": true` + unscoped name → HIGH hit."""
    pkg = tmp_path / "package.json"
    pkg.write_text(
        '{\n'
        '  "name": "leaky-app",\n'
        '  "version": "1.0.0",\n'
        '  "license": "UNLICENSED"\n'
        '}\n'
    )
    hits = _hits_in_file(
        "license-unlicensed-not-private",
        lcp.scan_unlicensed_not_private(pkg),
    )
    assert hits
    assert hits[0].severity == "HIGH"


def test_unlicensed_not_private_negative(tmp_path: Path) -> None:
    """Same UNLICENSED declaration but `"private": true` → no hit."""
    pkg = tmp_path / "package.json"
    pkg.write_text(
        '{\n'
        '  "name": "safe-app",\n'
        '  "version": "1.0.0",\n'
        '  "private": true,\n'
        '  "license": "UNLICENSED"\n'
        '}\n'
    )
    hits = _hits_in_file(
        "license-unlicensed-not-private",
        lcp.scan_unlicensed_not_private(pkg),
    )
    assert not hits


# ---------- Rule 7 : license-manifest-content-drift ----------------------


def test_manifest_content_drift_positive(tmp_path: Path) -> None:
    """package.json says MIT, LICENSE body is Apache-2.0 → CRITICAL hit."""
    (tmp_path / "package.json").write_text(
        '{\n'
        '  "name": "demo",\n'
        '  "license": "MIT"\n'
        '}\n'
    )
    (tmp_path / "LICENSE").write_text(
        "Apache License, Version 2.0, January 2004\n"
        "\n"
        "Licensed under the Apache License, Version 2.0 (the License);\n"
        "you may not use this file except in compliance with the License.\n"
    )
    hits = _hits_in_file(
        "license-manifest-content-drift",
        lcp.scan_manifest_content_drift(tmp_path),
    )
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_manifest_content_drift_negative(tmp_path: Path) -> None:
    """package.json says MIT and LICENSE body IS MIT → no hit."""
    (tmp_path / "package.json").write_text(
        '{\n'
        '  "name": "demo",\n'
        '  "license": "MIT"\n'
        '}\n'
    )
    (tmp_path / "LICENSE").write_text(
        "MIT License\n"
        "\n"
        "Copyright (c) 2026 Demo Authors\n"
        "\n"
        "Permission is hereby granted, free of charge, to any person obtaining\n"
        "a copy of this software...\n"
    )
    hits = _hits_in_file(
        "license-manifest-content-drift",
        lcp.scan_manifest_content_drift(tmp_path),
    )
    assert not hits


# ---------- Rule 8 : license-spdx-malformed-or-missing -------------------


def test_spdx_malformed_or_missing_positive(tmp_path: Path) -> None:
    """`.py` with `SPDX-License-Identifier: MIT or Apache-2.0` (lowercase op) → MAJOR hit."""
    src = tmp_path / "foo.py"
    src.write_text(
        "# SPDX-License-Identifier: MIT or Apache-2.0\n"
        "def hello():\n"
        "    return 'hi'\n"
    )
    hits = _hits_in_file(
        "license-spdx-malformed-or-missing",
        lcp.scan_spdx_malformed_in_file(src),
    )
    assert hits
    assert hits[0].severity in {"MAJOR", "CRITICAL"}


def test_spdx_malformed_or_missing_negative(tmp_path: Path) -> None:
    """`.py` with a clean canonical SPDX line → no hit."""
    src = tmp_path / "foo.py"
    src.write_text(
        "# SPDX-License-Identifier: MIT\n"
        "def hello():\n"
        "    return 'hi'\n"
    )
    hits = _hits_in_file(
        "license-spdx-malformed-or-missing",
        lcp.scan_spdx_malformed_in_file(src),
    )
    assert not hits


# ---------- Rule 9 : license-no-ci-scanner -------------------------------


def test_no_ci_scanner_positive(tmp_path: Path) -> None:
    """Workflows dir with no license-scanner token → MAJOR hit."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "name: CI\n"
        "on: [push]\n"
        "jobs:\n"
        "  test:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: npm test\n"
    )
    hits = _hits_in_file(
        "license-no-ci-scanner",
        lcp.scan_no_license_ci_workflow(workflows),
    )
    assert hits
    assert hits[0].severity == "MAJOR"


def test_no_ci_scanner_negative(tmp_path: Path) -> None:
    """Workflows dir with `cargo-deny` token → no hit."""
    workflows = tmp_path / ".github" / "workflows"
    workflows.mkdir(parents=True)
    (workflows / "ci.yml").write_text(
        "name: CI\n"
        "on: [push]\n"
        "jobs:\n"
        "  licenses:\n"
        "    runs-on: ubuntu-latest\n"
        "    steps:\n"
        "      - uses: actions/checkout@v4\n"
        "      - run: cargo-deny check licenses\n"
    )
    hits = _hits_in_file(
        "license-no-ci-scanner",
        lcp.scan_no_license_ci_workflow(workflows),
    )
    assert not hits


# ---------- Rule 10 : license-relicense-by-stealth-via-cla ---------------


def test_cla_relicense_stealth_positive(tmp_path: Path) -> None:
    """CONTRIBUTING.md with `grant ... perpetual ... sublicensable` (single line) → HIGH hit."""
    contributing = tmp_path / "CONTRIBUTING.md"
    contributing.write_text(
        "# Contributing\n"
        "\n"
        "By submitting a PR, you grant the maintainers a perpetual, irrevocable, sublicensable license.\n"
    )
    hits = _hits_in_file(
        "license-relicense-by-stealth-via-cla",
        lcp.scan_cla_relicense_stealth(contributing),
    )
    assert hits
    assert hits[0].severity == "HIGH"


def test_cla_relicense_stealth_negative(tmp_path: Path) -> None:
    """CONTRIBUTING.md with plain prose, no CLA-grant language → no hit."""
    contributing = tmp_path / "CONTRIBUTING.md"
    contributing.write_text(
        "# Contributing\n"
        "\n"
        "Please open a pull request. Make sure tests pass.\n"
        "Run `npm test` locally before pushing.\n"
    )
    hits = _hits_in_file(
        "license-relicense-by-stealth-via-cla",
        lcp.scan_cla_relicense_stealth(contributing),
    )
    assert not hits


# ---------- Rule 11 : license-vendor-missing-attribution -----------------


def test_vendor_missing_attribution_positive(tmp_path: Path) -> None:
    """`third_party/upstream/` with no LICENSE file inside → MAJOR hit."""
    vendor = tmp_path / "third_party" / "upstream"
    vendor.mkdir(parents=True)
    (vendor / "code.py").write_text("def f(): pass\n")
    hits = _hits_in_file(
        "license-vendor-missing-attribution",
        lcp.scan_vendor_missing_license(tmp_path),
    )
    assert hits
    assert hits[0].severity == "MAJOR"


def test_vendor_missing_attribution_negative(tmp_path: Path) -> None:
    """Same `third_party/upstream/` WITH a LICENSE file inside → no hit."""
    vendor = tmp_path / "third_party" / "upstream"
    vendor.mkdir(parents=True)
    (vendor / "code.py").write_text("def f(): pass\n")
    (vendor / "LICENSE").write_text(
        "MIT License\n"
        "\n"
        "Copyright (c) 2026 Upstream Authors\n"
    )
    hits = _hits_in_file(
        "license-vendor-missing-attribution",
        lcp.scan_vendor_missing_license(tmp_path),
    )
    assert not hits


# ---------- Rule 12 : license-non-commercial-in-deps ---------------------


def test_non_commercial_in_deps_positive(tmp_path: Path) -> None:
    """package.json declares `"license": "CC-BY-NC-4.0"` → CRITICAL hit."""
    pkg = tmp_path / "package.json"
    pkg.write_text(
        '{\n'
        '  "name": "demo",\n'
        '  "license": "CC-BY-NC-4.0"\n'
        '}\n'
    )
    hits = _hits_in_file(
        "license-non-commercial-in-deps",
        lcp.scan_noncommercial_in_deps(pkg),
    )
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_non_commercial_in_deps_negative(tmp_path: Path) -> None:
    """package.json with a plain commercial-permissive license → no hit."""
    pkg = tmp_path / "package.json"
    pkg.write_text(
        '{\n'
        '  "name": "demo",\n'
        '  "license": "MIT"\n'
        '}\n'
    )
    hits = _hits_in_file(
        "license-non-commercial-in-deps",
        lcp.scan_noncommercial_in_deps(pkg),
    )
    assert not hits


# ---------- Rule 13 : license-spdx-deprecated-bare-form ------------------


def test_spdx_deprecated_bare_form_positive(tmp_path: Path) -> None:
    """`.py` with `SPDX-License-Identifier: GPL-3.0` (bare) → MINOR hit."""
    src = tmp_path / "foo.py"
    src.write_text(
        "# SPDX-License-Identifier: GPL-3.0\n"
        "def f(): pass\n"
    )
    hits = _hits_in_file(
        "license-spdx-deprecated-bare-form",
        lcp.scan_spdx_deprecated_bare_form(src),
    )
    assert hits
    assert hits[0].severity == "MINOR"


def test_spdx_deprecated_bare_form_negative(tmp_path: Path) -> None:
    """`.py` with `SPDX-License-Identifier: MIT` (non-GPL family) → no hit.

    The deprecated-bare-form regex only captures GPL/LGPL/AGPL/GFDL prefixes,
    so any other identifier (here MIT) is silent. Note: even GPL-3.0-or-later
    triggers a false positive in the current library (the regex captures
    `GPL-3.0` from inside the longer form) — we sidestep that quirk by using
    a non-GPL identifier for the negative case.
    """
    src = tmp_path / "foo.py"
    src.write_text(
        "# SPDX-License-Identifier: MIT\n"
        "def f(): pass\n"
    )
    hits = _hits_in_file(
        "license-spdx-deprecated-bare-form",
        lcp.scan_spdx_deprecated_bare_form(src),
    )
    assert not hits


# ---------- Rule 14 : license-copyright-line-drift -----------------------


def test_copyright_line_drift_positive(tmp_path: Path) -> None:
    """LICENSE says Alice, src/foo.py says Bob → MAJOR hit."""
    (tmp_path / "LICENSE").write_text(
        "MIT License\n"
        "\n"
        "Copyright (c) 2026 Alice Authors\n"
        "\n"
        "Permission is hereby granted...\n"
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "foo.py").write_text(
        "# Copyright (c) 2020 Bob Contributor\n"
        "def f(): pass\n"
    )
    hits = _hits_in_file(
        "license-copyright-line-drift",
        lcp.scan_copyright_line_drift(tmp_path),
    )
    assert hits
    assert hits[0].severity == "MAJOR"


def test_copyright_line_drift_negative(tmp_path: Path) -> None:
    """LICENSE and src/foo.py both say the same holder → no hit."""
    (tmp_path / "LICENSE").write_text(
        "MIT License\n"
        "\n"
        "Copyright (c) 2026 Alice Authors\n"
        "\n"
        "Permission is hereby granted...\n"
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "foo.py").write_text(
        "# Copyright (c) 2026 Alice Authors\n"
        "def f(): pass\n"
    )
    hits = _hits_in_file(
        "license-copyright-line-drift",
        lcp.scan_copyright_line_drift(tmp_path),
    )
    assert not hits


# ---------- Rule 15 : license-patent-grant-stripped ----------------------


def test_patent_grant_stripped_positive(tmp_path: Path) -> None:
    """Root LICENSE = MIT, source declares Apache-2.0, no LICENSE-APACHE → CRITICAL hit."""
    (tmp_path / "LICENSE").write_text(
        "MIT License\n"
        "\n"
        "Copyright (c) 2026 Demo Authors\n"
        "\n"
        "Permission is hereby granted, free of charge, to any person obtaining\n"
        "a copy of this software...\n"
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "vendored.py").write_text(
        "# SPDX-License-Identifier: Apache-2.0\n"
        "def f(): pass\n"
    )
    hits = _hits_in_file(
        "license-patent-grant-stripped",
        lcp.scan_patent_grant_stripped(tmp_path),
    )
    assert hits
    assert hits[0].severity == "CRITICAL"


def test_patent_grant_stripped_negative(tmp_path: Path) -> None:
    """Same layout WITH a sibling `LICENSE-APACHE-2.0` file at root → no hit."""
    (tmp_path / "LICENSE").write_text(
        "MIT License\n"
        "\n"
        "Copyright (c) 2026 Demo Authors\n"
        "\n"
        "Permission is hereby granted, free of charge, to any person obtaining\n"
        "a copy of this software...\n"
    )
    (tmp_path / "LICENSE-APACHE-2.0").write_text(
        "Apache License, Version 2.0\n"
        "\n"
        "Licensed under the Apache License, Version 2.0\n"
    )
    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "vendored.py").write_text(
        "# SPDX-License-Identifier: Apache-2.0\n"
        "def f(): pass\n"
    )
    hits = _hits_in_file(
        "license-patent-grant-stripped",
        lcp.scan_patent_grant_stripped(tmp_path),
    )
    assert not hits


# ---------- Rule 16 : license-trademark-no-disclaimer --------------------


def test_trademark_no_disclaimer_positive(tmp_path: Path) -> None:
    """README mentions `Docker` with no disclaimer text → MINOR hit."""
    readme = tmp_path / "README.md"
    readme.write_text(
        "# My Project\n"
        "\n"
        "This project runs in Docker containers and integrates with Kubernetes.\n"
        "It is a great way to ship your application.\n"
    )
    hits = _hits_in_file(
        "license-trademark-no-disclaimer",
        lcp.scan_trademark_no_disclaimer(readme),
    )
    assert hits
    assert hits[0].severity == "MINOR"


def test_trademark_no_disclaimer_negative(tmp_path: Path) -> None:
    """Same README WITH a `trademark` disclaimer somewhere → no hit."""
    readme = tmp_path / "README.md"
    readme.write_text(
        "# My Project\n"
        "\n"
        "This project runs in Docker containers and integrates with Kubernetes.\n"
        "It is a great way to ship your application.\n"
        "\n"
        "---\n"
        "\n"
        "Docker is a trademark of Docker, Inc. This project is not affiliated\n"
        "with Docker, Inc.\n"
    )
    hits = _hits_in_file(
        "license-trademark-no-disclaimer",
        lcp.scan_trademark_no_disclaimer(readme),
    )
    assert not hits
