"""Tests for the project-map renderer (TRDD-e247a349 P1).

Covers: file + symbol line format, convention-collapse at the MIN_FAMILY
threshold (and NON-collapse below it / for underscore-less core files),
hash stability (no-op → same hash; structural change → different hash),
and fence integrity. No mocks — builds FileMaps directly.
"""

from __future__ import annotations

import hashlib
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


def test_coverage_note_appears_and_affects_hash():
    """#175: an optional coverage disclaimer sits right under the heading and
    participates in the structure hash — its own change (uncovered-file count
    moved) is then a real refresh trigger instead of silently stale."""
    fm = FileMap(path="x.py", role="r", symbols=[])
    body_plain = R.render_body([fm])
    body_noted = R.render_body([fm], coverage_note="> ⚠ test note")
    assert "> ⚠ test note" in body_noted
    assert "> ⚠ test note" not in body_plain
    assert R.structure_hash([fm]) != R.structure_hash([fm], coverage_note="> ⚠ test note")
    block = R.render_block([fm], generated_iso="2026-01-01T00:00:00+0000", digest="d", coverage_note="> ⚠ test note")
    assert "> ⚠ test note" in block


def test_family_role_shown_when_majority_shares():
    """When >half the family shares a role, it IS shown as the representative."""
    shared = "one security pattern lib"
    fams = ([FileMap(path=f"scripts/lib/a{i}_patterns.py", role=shared, symbols=[]) for i in range(7)]
            + [FileMap(path=f"scripts/lib/b{i}_patterns.py", role="oddball", symbols=[]) for i in range(2)])
    body = R.render_body(fams)
    grp = next(line for line in body.splitlines() if line.startswith("`scripts/lib/*_patterns.py`"))
    assert f"— {shared} [" in grp


def _names_fm() -> FileMap:
    return FileMap(
        path="scripts/lib/state.py",
        role="per-session state helpers",
        symbols=[
            Symbol("atomic_write", "func", "atomic_write(path, text) -> None", "tmp+rename write"),
            Symbol("Store", "class", "Store", "a store"),
            Symbol("Store.load", "method", "Store.load(self) -> int", ""),
        ],
    )


def test_names_line_shape():
    """Names-only body: path and role, then ONE indented comma line of func/class names; methods only on request."""
    body = R.render_map_body([_names_fm()])
    assert body.splitlines()[2:] == ["`scripts/lib/state.py` — per-session state helpers", "  atomic_write, Store"]
    assert "tmp+rename write" not in body and "->" not in body  # no signatures, no docs
    with_methods = R.render_map_body([_names_fm()], include_methods=True)
    assert "  atomic_write, Store, Store.load" in with_methods
    bare = R.render_map_body([FileMap(path="x.py", role="", symbols=[])])
    assert bare.splitlines()[2:] == ["`x.py`"]  # no symbols -> no names line


def test_names_body_family_collapse_unchanged():
    """The names-only body collapses a >= MIN_FAMILY family exactly like the legacy body."""
    fams = [_lib(f"{p}_patterns") for p in
            ["cloud_credential", "prompt_injection", "npm_lifecycle", "k8s_admission",
             "container", "race", "crypto_misuse", "dns_email", "graphql"]]
    legacy = R.render_body(fams).splitlines()[1:]
    names = R.render_map_body(fams).splitlines()[2:]
    assert names == legacy
    assert "### Convention groups" in names


def test_names_body_keeps_every_symbol_kind_extract_python_emits(tmp_path):
    """Real extract_python output: every public func, class and method name reaches the names line (no kind is dropped)."""
    from repomap import extract_python

    src = tmp_path / "mod.py"
    src.write_text(
        "\"\"\"demo module\"\"\"\n"
        "def pub(a): ...\n"
        "async def apub(): ...\n"
        "def _priv(): ...\n"
        "class K:\n"
        "    def meth(self): ...\n"
        "    def _hidden(self): ...\n",
        encoding="utf-8",
    )
    fm = extract_python(src)
    assert {s.kind for s in fm.symbols} == {"func", "class", "method"}
    fm.path = "mod.py"
    assert R.render_map_body([fm]).splitlines()[2:] == ["`mod.py` — demo module", "  pub, apub, K"]
    assert R.render_map_body([fm], include_methods=True).splitlines()[3] == "  pub, apub, K, K.meth"


def test_header_round_trip():
    """render_file writes one header line that read_header parses back to schema/sha/digest/generated."""
    text = R.render_file([_names_fm()], generated_iso="2026-11-15T12:00:00+0100", digest="abc123def456")
    assert text.splitlines()[0].startswith("<!-- project-map v2 sha=")
    assert R.FENCE_START not in text and R.FENCE_END not in text
    assert text.endswith("\n")
    header = R.read_header(text)
    assert header is not None
    assert header == {
        "schema": "v2",
        "sha": R.map_sha([_names_fm()]),
        "digest": "abc123def456",
        "generated": "2026-11-15T12:00:00+0100",
    }
    # the sha covers the body only: the body after the header line hashes to the header sha
    body = text.split("\n", 1)[1].rstrip("\n")
    assert hashlib.sha256(body.encode("utf-8")).hexdigest()[:12] == header["sha"]


def test_read_header_rejects_non_header():
    """read_header returns None for text without a project-map header on its first line."""
    assert R.read_header("") is None
    assert R.read_header("# Project map\n") is None
    assert R.read_header("<!-- project-map v2 sha=XYZ digest=d generated=g -->\n") is None
    legacy = R.render_block([_names_fm()], generated_iso="2026-01-01T00:00:00+0000", digest="d")
    assert R.read_header(legacy) is None


def test_render_file_rejects_whitespace_in_header_fields():
    """A digest or timestamp with whitespace would break read_header, so render_file refuses it."""
    for generated_iso, digest in (("a b", "d"), ("g", "")):
        try:
            R.render_file([_names_fm()], generated_iso=generated_iso, digest=digest)
        except ValueError:
            continue
        raise AssertionError(f"render_file accepted generated_iso={generated_iso!r} digest={digest!r}")


def test_map_sha_stable_and_coverage_note_sensitive():
    """map_sha is stable across renders, ignores generated/digest, and changes with names, methods and coverage_note."""
    fm = _names_fm()
    base = R.map_sha([fm])
    assert base == R.map_sha([_names_fm()])
    assert R.map_sha([fm], coverage_note="> note") != base  # TRDD-6HFOB5S4: the note is hashed
    assert R.map_sha([fm], include_methods=True) != base
    renamed = FileMap(path=fm.path, role=fm.role, symbols=[Symbol("other", "func", "other()", "")])
    assert R.map_sha([renamed]) != base
    one = R.render_file([fm], generated_iso="2026-01-01T00:00:00+0000", digest="d1", coverage_note="> note")
    two = R.render_file([fm], generated_iso="2099-12-31T23:59:59+0000", digest="d2", coverage_note="> note")
    h1, h2 = R.read_header(one), R.read_header(two)
    assert h1 is not None and h2 is not None
    assert h1["sha"] == h2["sha"] == R.map_sha([fm], coverage_note="> note")
