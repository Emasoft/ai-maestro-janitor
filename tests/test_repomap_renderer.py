"""Tests for the project-map renderer (TRDD-e247a349 P1).

Covers: file + symbol line format, convention-collapse at the MIN_FAMILY
threshold (and NON-collapse below it / for underscore-less core files),
hash stability (no-op → same hash; structural change → different hash),
and fence integrity. No mocks — builds FileMaps directly.
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

from repomap import FileMap, Symbol  # noqa: E402
from repomap import renderer as R  # noqa: E402


def _lib(stem: str) -> FileMap:
    return FileMap(path=f"scripts/lib/{stem}.py", role="one security pattern lib", symbols=[])


def test_file_and_symbol_lines():
    """A file renders as `path` — role with one indented · line per symbol."""
    fm = FileMap(
        path="scripts/lib/state.py",
        role="per-session state helpers",
        symbols=[
            Symbol("atomic_write", "func", "atomic_write(path, text) -> None", "tmp+rename write"),
            Symbol("project_root", "func", "project_root() -> Path", ""),
        ],
    )
    body = R.render_body([fm])
    assert "`scripts/lib/state.py` — per-session state helpers" in body
    assert "  · atomic_write(path, text) -> None — tmp+rename write" in body
    assert "  · project_root() -> Path" in body  # no trailing ' — ' when doc empty


def test_convention_collapse_at_threshold():
    """≥ MIN_FAMILY same-dir same-token files collapse to one group line + stem list."""
    fams = [_lib(f"{p}_patterns") for p in
            ["cloud_credential", "prompt_injection", "npm_lifecycle", "k8s_admission",
             "container", "race", "crypto_misuse", "dns_email", "graphql"]]
    assert len(fams) >= R.MIN_FAMILY
    body = R.render_body(fams)
    assert "### Convention groups" in body
    assert f"`scripts/lib/*_patterns.py` (×{len(fams)})" in body
    assert "[cloud_credential," in body  # stem list present
    # collapsed → individual file lines for these are gone
    assert "`scripts/lib/cloud_credential_patterns.py`" not in body


def test_below_threshold_stays_expanded():
    """A family with < MIN_FAMILY members is NOT collapsed (conservative)."""
    fams = [_lib(f"a{i}_patterns") for i in range(R.MIN_FAMILY - 1)]
    body = R.render_body(fams)
    assert "### Convention groups" not in body
    assert "`scripts/lib/a0_patterns.py`" in body


def test_underscoreless_core_files_never_collapse():
    """Files whose stem has no underscore (state.py, daemon.py) never join a family."""
    core = [FileMap(path=f"scripts/{n}.py", role="core", symbols=[]) for n in
            ["state", "daemon", "dispatch", "dedupe", "posture", "suppression",
             "publish", "doctor", "scout"]]
    body = R.render_body(core)
    assert "### Convention groups" not in body
    assert "`scripts/daemon.py` — core" in body


def test_hash_stable_and_change_sensitive():
    """Same structure → same hash; a changed symbol → different hash; timestamp is excluded."""
    fm = FileMap(path="x.py", role="r", symbols=[Symbol("f", "func", "f() -> int", "doc")])
    h1 = R.structure_hash([fm])
    h2 = R.structure_hash([FileMap(path="x.py", role="r",
                                   symbols=[Symbol("f", "func", "f() -> int", "doc")])])
    assert h1 == h2  # identical structure → identical hash
    fm2 = FileMap(path="x.py", role="r", symbols=[Symbol("f", "func", "f() -> str", "doc")])
    assert R.structure_hash([fm2]) != h1  # signature change → different hash
    # generated= stamp must not affect the body hash baked into render_block
    b1 = R.render_block([fm], generated_iso="2026-01-01T00:00:00+0000", digest="abc")
    b2 = R.render_block([fm], generated_iso="2099-12-31T23:59:59+0000", digest="abc")
    sha1 = b1.split("sha=")[1].split(" ")[0]
    sha2 = b2.split("sha=")[1].split(" ")[0]
    assert sha1 == sha2


def test_fences_present_and_wrap_body():
    """render_block wraps the body in the exact start/end fences with sha/digest/generated."""
    fm = FileMap(path="x.py", role="r", symbols=[])
    block = R.render_block([fm], generated_iso="2026-05-29T00:00:00+0200", digest="deadbeef")
    assert block.startswith(R.FENCE_START + " v1 sha=")
    assert "digest=deadbeef" in block
    assert "generated=2026-05-29T00:00:00+0200" in block
    assert block.rstrip().endswith(R.FENCE_END)


def test_family_role_omitted_when_members_distinct():
    """AC9: a family whose members all have DISTINCT roles shows NO role hint —
    surfacing one arbitrary member's role would mislead (all 200 *_patterns.py
    are NOT about whatever the tie-break picked). The stem list carries meaning."""
    fams = [FileMap(path=f"scripts/lib/{p}_patterns.py", role=f"detects {p} attacks", symbols=[])
            for p in ["cloud", "prompt", "npm", "k8s", "race", "crypto", "dns", "graphql", "jwt"]]
    body = R.render_body(fams)
    grp = next(line for line in body.splitlines() if line.startswith("`scripts/lib/*_patterns.py`"))
    assert " — " not in grp.split("] ")[0] if "]" in grp else " — " not in grp  # no role hint
    assert grp.startswith("`scripts/lib/*_patterns.py` (×9) [")


def test_family_role_shown_when_majority_shares():
    """When >half the family shares a role, it IS shown as the representative."""
    shared = "one security pattern lib"
    fams = ([FileMap(path=f"scripts/lib/a{i}_patterns.py", role=shared, symbols=[]) for i in range(7)]
            + [FileMap(path=f"scripts/lib/b{i}_patterns.py", role="oddball", symbols=[]) for i in range(2)])
    body = R.render_body(fams)
    grp = next(line for line in body.splitlines() if line.startswith("`scripts/lib/*_patterns.py`"))
    assert f"— {shared} [" in grp
