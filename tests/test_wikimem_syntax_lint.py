"""Tests for the wikimem lint WRAPPER + its heartbeat detector (TRDD-VPTQ4067).

The checks themselves are Rust now (`memgrep::memory::lint_paths`) and are unit-tested there —
this file pins the two things that live on the Python side and nowhere else:

  1. the WRAPPER contract — binary resolution, the default roots, parsing `memgrep lint`'s
     `SEV path:line — msg` output, and the exit codes (notably: a missing binary must exit 2,
     never 0, because a gate that passes when the checker could not run is worse than none);
  2. the DETECTOR wiring — an ERROR-class finding reaches the heartbeat once, then dedupes.

The end-to-end cases run the REAL binary built from this tree (conftest's `MEMGREP_BIN_PATH`),
so the wrapper is proven against the same executable the write gate calls — an unpinned binary
would score whatever `cargo install` last left on PATH.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
from conftest import MEMGREP_BIN_PATH

_SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # Register BEFORE exec so `@dataclass` (which looks up cls.__module__ in sys.modules)
    # and any typing resolution can find the module.
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


lint = _load(_SCRIPTS / "wikimem_syntax_lint.py", "wikimem_syntax_lint")
det = _load(_SCRIPTS / "detectors" / "wikimem-syntax.py", "wikimem_syntax_detector")

needs_memgrep = pytest.mark.skipif(MEMGREP_BIN_PATH is None, reason="memgrep binary unavailable")


def _page(body: str, *, name: str = "n") -> str:
    return (
        f"---\nname: {name}\nocd: 2026-07-21\nlmd: 2026-07-21\ndescription: \"a page\"\n---\n"
        f"{body}\n\n## Notes and lessons learned\n"
    )


def _corpus(root: Path, files: dict[str, str]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    return root


def _msgs(findings, sev: str | None = None) -> str:
    return "\n".join(f.msg for f in findings if sev is None or f.sev == sev)


# ── the output contract: `SEV path:line — msg` ────────────────────────────────────
def test_parse_findings_reads_every_severity():
    out = (
        "ERROR /m/a.md:12 — atom `^x` has no `keywords:`\n"
        "WARN /m/a.md:12 — atom `^x` has no `ocd:` date\n"
        "INFO /m/b.md:3 — page-level lesson `[^1]:`\n"
    )
    f = lint.parse_findings(out)
    assert [x.sev for x in f] == ["ERROR", "WARN", "INFO"]
    assert (f[0].path, f[0].line) == ("/m/a.md", 12)
    assert f[2].msg.startswith("page-level lesson")


def test_parse_findings_ignores_non_finding_lines():
    # memgrep prints its count to stderr, but a caller may merge streams; nothing that is not a
    # finding line may be mistaken for one, or the detector's count is wrong.
    assert lint.parse_findings("memgrep lint: 8 finding(s), 5 at or above ERROR\n\n") == []


def test_find_memgrep_prefers_the_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # MEMGREP_BIN is how a test or a bisect pins the binary UNDER TEST; if the override lost to
    # PATH, every measurement would silently describe some other build.
    fake = tmp_path / "memgrep"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    monkeypatch.setenv("MEMGREP_BIN", str(fake))
    assert lint.find_memgrep() == str(fake)


def test_find_memgrep_ignores_an_override_that_does_not_exist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMGREP_BIN", str(tmp_path / "nope"))
    assert lint.find_memgrep() != str(tmp_path / "nope")


def test_default_roots_are_the_resolved_memory_scopes(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        lint.memory_scopes, "resolve_scope_dirs", lambda: [("LOCAL", Path("/l")), ("USER", Path("/u"))]
    )
    assert lint.default_roots() == [Path("/l"), Path("/u")]


def test_missing_binary_exits_2_never_0(monkeypatch: pytest.MonkeyPatch, capsys):
    # The failure mode this guards: a linter that cannot run silently reports "clean".
    monkeypatch.setattr(lint, "find_memgrep", lambda: None)
    monkeypatch.setattr(sys, "argv", ["wikimem_syntax_lint.py", "."])
    assert lint.main() == 2
    assert "memgrep not found" in capsys.readouterr().err


# ── end-to-end through the real binary: the checks ported in plan Phase 1b ────────
@needs_memgrep
def test_ported_checks_reach_the_wrapper(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))
    root = _corpus(
        tmp_path / "mem",
        {
            "a.md": _page(
                "^ATOM-AAAA-BBBB [keywords: shared id, ocd: 2026-07-21, lmd: 2026-07-21]\nbody.\n\n"
                "^ATOM-CCCC-DDDD ⟦keywords: mangled, ocd: 2026-07-21⟧\nbody.\n\n"
                "^ATOM-EEEE-FFFF [ocd: 2026-07-21, lmd: 21/07/2026]\nbody.\n\n"
                "^ATOM-GGGG-HHHH [keywords: first phrase, second phrase, ocd: 2026-07-21, lmd: 2026-07-21]\nbody."
            ),
            "b.md": _page("^ATOM-AAAA-BBBB [keywords: shared id, ocd: 2026-07-21, lmd: 2026-07-21]\nbody."),
        },
    )
    code, _stdout, findings = lint.run_lint([root])
    errors, warns = _msgs(findings, "ERROR"), _msgs(findings, "WARN")

    assert "not ASCII `[`" in errors, errors  # atom-bad-bracket
    assert "RECALL SURFACE" in errors, errors  # atom-no-keywords
    assert "DISCARDED by the parser" in errors, errors  # atom-dropped-props
    assert "not corpus-unique" in errors, errors  # atom-dup-id
    assert "is not ISO" in warns, warns  # date-format
    assert code == 1  # ERRORs present ⇒ the gate fails


@needs_memgrep
def test_lesson_without_a_stable_id_is_a_warn(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # UNCITED on purpose: the model makes a page-level lesson the normal case, and those were the
    # ones the old parsed-footnote scan skipped entirely.
    monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))
    root = _corpus(
        tmp_path / "mem",
        {"a.md": _page("body.") + '[^1]: [status:valid, keywords:"k", ocd:2026-07-21, lmd:2026-07-21] DO NOT x.\n'},
    )
    _code, _stdout, findings = lint.run_lint([root])
    assert "no `id:ATOM-…`" in _msgs(findings, "WARN"), findings


@needs_memgrep
def test_well_formed_corpus_is_clean(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))
    root = _corpus(
        tmp_path / "mem",
        {"a.md": _page("^ATOM-AAAA-BBBB [keywords: alpha_beta gamma, ocd: 2026-07-21, lmd: 2026-07-21]\nbody.")},
    )
    code, _stdout, findings = lint.run_lint([root])
    assert findings == [], findings
    assert code == 0


# ── the detector (the heartbeat wiring) ───────────────────────────────────────────
def _scope_with(tmp_path: Path, monkeypatch, files: dict[str, str]) -> Path:
    """Point the wrapper's default roots at a single temp memory root holding `files`."""
    root = _corpus(tmp_path / "memory", files)
    monkeypatch.setenv("MEMGREP_BIN", str(MEMGREP_BIN_PATH))
    monkeypatch.setattr(lint, "default_roots", lambda: [root])
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    return root


@needs_memgrep
def test_detector_signatures_flag_broken_page(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    _scope_with(tmp_path, monkeypatch, {
        "clean.md": _page("^ok [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nb."),
        "broken.md": _page("^bad ⟦keywords: x⟧\nb."),
    })
    sigs = det._error_signatures()
    assert any(s.startswith("broken.md:") for s in sigs), sigs
    # The signature must not carry the message itself: it can embed absolute paths.
    assert not any("/" in s for s in sigs), sigs


@needs_memgrep
def test_detector_silent_on_clean_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    _scope_with(tmp_path, monkeypatch, {
        "clean.md": _page("^ok [keywords: k, ocd: 2026-07-21, lmd: 2026-07-21]\nb."),
    })
    assert det.main() == 0
    assert capsys.readouterr().out == ""


@needs_memgrep
def test_detector_emits_then_dedupes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    _scope_with(tmp_path, monkeypatch, {
        "broken.md": _page("^bad ⟦keywords: x⟧\nb."),
    })
    assert det.main() == 0
    first = capsys.readouterr().out
    assert "[wikimem-syntax]" in first and "ERROR" in first
    # second run on the UNCHANGED set → per-set dedupe → silent
    assert det.main() == 0
    assert capsys.readouterr().out == ""


def test_detector_fails_open_when_memgrep_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys):
    # The CLI must exit 2 on a missing binary; the HEARTBEAT must stay silent and exit 0 — it is
    # not a gate, and a detector that breaks the heartbeat is worse than one that misses a finding.
    _corpus(tmp_path / "memory", {"broken.md": _page("^bad ⟦keywords: x⟧\nb.")})
    monkeypatch.setattr(lint, "find_memgrep", lambda: None)
    monkeypatch.setattr(lint, "default_roots", lambda: [tmp_path / "memory"])
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path))
    assert det.main() == 0
    assert capsys.readouterr().out == ""
