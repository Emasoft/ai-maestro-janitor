"""TRDD-XI10BA5D step B: lint findings become tickets, with stable anchors.

The step-B ticket consumer contract, in five halves:

  1. WIRE FORMAT — every lint-stdout consumer tolerates a TRAILING `⟦anchor:…⟧` token
     (placement contract: never between the `]` code token and the em-dash, which is what
     `_RELOCATE_LESSON_RE` requires); `wikimem_syntax_lint._LINE_RE` extracts it.
  2. TICKET FILTERS — INFO never tickets; other WARNs never ticket (A3); held pages
     (agentlenspro / ghbook) are excluded from BOTH ticket paths.
  3. DEDUPE — the key is `MEMCORP-00X:<scope>:<relpath>:<code>:<anchor>`: scope-stamped,
     line-number-free. Same (page, code, anchor) re-raises bump `seen_count`; two anchors on
     one page are two findings; a moved line re-keys to the SAME ticket.
  4. SPLIT PATH — an `atom-oversized-critical` WARN opens ONE MEMCORP-002 ticket per atom
     (the owner's verbatim 2026-09-23 "warn but also open a ticket" rule, A8).
  5. USER-SCOPE CLAIM — the machine-wide claim file lives under
     `global_state.global_state_dir()` (A5: every test overrides that dir via the
     `JANITOR_GLOBAL_STATE_DIR` env var, which `global_state_dir()` resolves FIRST — no test
     touches the real machine state; incident class janitor-keepalive-test-isolation-fsevents).
     A claim is `{"project": …, "ts": …}`; a second project within the TTL is skipped; a claim
     past the TTL is swept and the key becomes claimable again.

Every `_file_tickets` call runs against `issue_catalog.raise_issue` MONKEYPATCHED to a
recording fake — the unit under test is the detector's routing/dedupe/claim logic, not
`raise_issue`'s own (that has its own suite) — and every real-filesystem touch is confined to
`tmp_path` plus the redirected global-state dir.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import time
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
sys.path.insert(0, str(_SCRIPTS))
sys.path.insert(0, str(_SCRIPTS / "lib"))

import global_state as gs  # noqa: E402
import wikimem_syntax_lint as lint  # noqa: E402


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


wsyntax = _load(_SCRIPTS / "detectors" / "wikimem-syntax.py", "wikimem_syntax_detector_stepb")
sys.path.insert(0, str(_ROOT / "scripts" / "hooks"))
import memory_content_precheck as mcp  # noqa: E402  (same lint-stdout consumers, anchored lines)

_hook = _load(_SCRIPTS / "hooks" / "post-edit-wikimem-lint.py", "post_edit_wikimem_lint_hook")


# ── A5: isolate the machine-wide claim dir for EVERY test in this module ─────────────────────


@pytest.fixture(autouse=True)
def _isolated_global_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Point `global_state.global_state_dir()` at a per-test tmp dir.

    `global_state_dir()` resolves `$JANITOR_GLOBAL_STATE_DIR` FIRST (absolute priority, its
    docstring: "escape hatch for tests — the whole test suite relies on it"), so setting the
    env var here redirects every claim read/write this module makes. A5's red line: never the
    real plugin-DATA global state.
    """
    gsd = tmp_path / "global-state"
    gsd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(gsd))
    yield gsd


def _finding(sev: str, path: str, line: int, code: str, anchor: str = "") -> lint.Finding:
    return lint.Finding(sev=sev, path=path, line=line, msg="m", code=code, anchor=anchor)


class _Recorder:
    """Captures every `raise_issue` call; returns an ok Raised (or a not-ok one on demand)."""

    def __init__(self, *, ok: bool = True):
        self.calls: list[dict] = []
        self.ok = ok

    def __call__(self, code: str, **kw):
        import issue_catalog

        self.calls.append({"code": code, **kw})
        return issue_catalog.Raised(code=code, domain="harness", ok=self.ok, ticket_id="T-TEST0001")


@pytest.fixture()
def recorder(monkeypatch: pytest.MonkeyPatch) -> _Recorder:
    rec = _Recorder()
    monkeypatch.setattr("issue_catalog.raise_issue", rec)
    # The detector imported `issue_catalog` itself — same sys.modules object, one patch covers
    # both. Guard that assumption loudly rather than silently testing the wrong seam.
    assert wsyntax.issue_catalog.raise_issue is rec
    return rec


@pytest.fixture()
def roots(tmp_path: Path) -> list[tuple[str, Path]]:
    """Fixture scope roots the tests pass explicitly — `_file_tickets` resolves scopes against
    the REAL env-resolved roots by default, and a test page must live under a root the test
    owns, not the live corpus."""
    return [("LOCAL", tmp_path / "local"), ("USER", tmp_path / "user")]


# ── req 1: the anchor is a TRAILING token every consumer tolerates ───────────────────────────

Finding = lint.Finding  # brevity in assertions


def test_anchor_at_end_of_line_is_tolerated_by_every_consumer():
    """A finding line carrying a trailing `⟦anchor:atom:X⟧` still matches every grep consumer
    (`post-edit-wikimem-lint.error_findings`, `_OVERSIZED_ATOM_RE`, `_ENRICH_FINDING_RE`,
    `_RELOCATE_LESSON_RE`, `_RELOCATE_INERT_RE`) AND parses through `_LINE_RE` with the anchor
    extracted."""
    base = "ERROR /m/a.md:12 [atom-no-keywords] — atom `^x` has no `keywords:`"
    anchored = f"{base} ⟦anchor:atom:ATOM-1⟧"

    # the hook's prefix match — trailing content irrelevant, but assert it KEPT the line
    assert anchored in _hook.error_findings(anchored)

    # the precheck regexes: .match(), no end anchor
    assert mcp._OVERSIZED_ATOM_RE.match(
        "ERROR /m/a.md:12 [atom-oversized] — atom body is 9 chars ⟦anchor:atom:A1⟧"
    )
    assert mcp._ENRICH_FINDING_RE.match(anchored)
    assert mcp._RELOCATE_LESSON_RE.match(
        "INFO /m/a.md:3 [lesson-uncited] — page-level lesson `[^1]:` — cite it ⟦anchor:lesson:1⟧"
    )
    assert mcp._RELOCATE_INERT_RE.match(
        "INFO /m/a.md:3 [lesson-uncited] — sits INSIDE a code span ⟦anchor:lesson:1⟧"
    )

    # the feed's parser: anchor EXTRACTED, msg NOT swallowing it
    f = lint.parse_findings(anchored)[0]
    assert f.anchor == "atom:ATOM-1"
    assert f.msg == "atom `^x` has no `keywords:`"


def test_anchor_between_code_and_emdash_breaks_relocate_lesson_and_is_never_emitted():
    """THE placement contract (spec req 1): `_RELOCATE_LESSON_RE` requires `] — ` immediately
    after the code token. An anchor there does NOT match — which is why the Rust emitter may
    only ever place it at end of line (pinned by the Rust CLI test), and why this regex pins
    the consumer side of the same contract."""
    line = (
        "INFO /m/a.md:3 [lesson-uncited] ⟦anchor:lesson:1⟧ — page-level lesson `[^1]:` — "
        "cite it from an atom"
    )
    assert mcp._RELOCATE_LESSON_RE.match(line) is None
    # The feed's own regex refuses the shape entirely: its anchor group is anchored at end of
    # line, so a mid-line token matches nothing — a mis-placed anchor can never be silently
    # re-parsed as a valid finding (it would have to be re-emitted to exist at all).
    assert lint.parse_findings(line) == []


def test_finding_without_anchor_parses_with_empty_anchor():
    """Version skew (spec delta 1): an older binary prints no token — `anchor` degrades to ""
    and every dedupe key behaves as before."""
    f = lint.parse_findings("WARN /m/a.md:4 [atom-no-ocd] — atom `^x` has no `ocd:` date")[0]
    assert f.anchor == ""


# ── req 2 + A3: the severity filters ─────────────────────────────────────────────────────────


def test_info_never_tickets(recorder: _Recorder):
    """INFO never tickets — including `atom-oversized` at >1x but <2x budget (janitor#200's
    demotion must not re-enter ticketing through the back door)."""
    info = [
        _finding("INFO", "/m/a.md", 5, "atom-oversized", "atom:BIG"),
        _finding("INFO", "/m/a.md", 3, "lesson-uncited", "lesson:1"),
    ]
    assert wsyntax._file_tickets(info) == 0
    assert recorder.calls == []


def test_non_critical_warns_never_ticket(recorder: _Recorder):
    """A3: MEMCORP-002 collects EXACTLY `atom-oversized-critical`; every other WARN (the
    one-sided links, the date warns, the superseded-delimiter advisories) stays unticketed.
    The ERROR-only filter of MEMCORP-001 is untouched."""
    warns = [
        _finding("WARN", "/m/a.md", 5, "atom-no-ocd", "atom:A"),
        _finding("WARN", "/m/a.md", 6, "link-one-sided", "link:a::b"),
        _finding("WARN", "/m/a.md", 7, "superseded-atom-above-delimiter", "atom:B"),
    ]
    assert wsyntax._file_tickets(warns) == 0
    assert recorder.calls == []


# ── req 4: held pages are excluded from BOTH ticket paths ────────────────────────────────────


def test_held_pages_excluded_from_both_paths(recorder: _Recorder):
    findings = [
        _finding("ERROR", "/x/agentlenspro/memory/foo.md", 3, "page-no-ocd", "field:ocd"),
        _finding("WARN", "/x/GHBook/memory/foo.md", 4, "atom-oversized-critical", "atom:B"),
        _finding("ERROR", "/x/ok/memory/foo.md", 5, "page-no-ocd", "field:ocd"),
    ]
    wsyntax._file_tickets(findings)
    assert [c["code"] for c in recorder.calls] == ["MEMCORP-001"]
    assert "ok" in recorder.calls[0]["where"]


# ── req 4 (test 4): the dedupe key — page + code + anchor, never the line ────────────────────


def test_dedupe_same_page_code_anchor_bumps_seen_count(recorder: _Recorder, roots, tmp_path: Path):
    """The same (page, code, anchor) twice: `raise_issue` sees the SAME key twice (its own
    dedupe bumps seen_count); a changed line number with the same anchor is STILL the same
    key; two different anchors on one page are two keys."""
    page = str(tmp_path / "local" / "a.md")
    for f in [
        _finding("ERROR", page, 10, "page-no-ocd", "field:ocd"),
        _finding("ERROR", page, 10, "page-no-ocd", "field:ocd"),
        _finding("ERROR", page, 99, "page-no-ocd", "field:ocd"),  # line moved
        _finding("ERROR", page, 10, "atom-no-keywords", "atom:X"),
        _finding("ERROR", page, 10, "atom-no-keywords", "atom:Y"),  # 2nd anchor
    ]:
        assert wsyntax._file_tickets([f], roots=roots) == 1
    keys = [c["dedupe_key"] for c in recorder.calls]
    assert len(keys) == 5
    assert keys[0] == keys[1] == keys[2], "same anchor ⇒ same key regardless of line"
    assert keys[0].startswith("MEMCORP-001:LOCAL:a.md:page-no-ocd:field:ocd")
    assert keys[0].endswith("field:ocd") and ":99" not in keys[0], "no line number in any key"
    assert keys[3] != keys[4], "different anchors on one page are distinct findings"


def test_dedupe_key_is_scope_stamped(tmp_path: Path):
    """Two roots holding same-named pages produce DIFFERENT keys; the relpath (not the
    basename, not the abs path, not the line) is the page component."""
    local = tmp_path / "local"
    user = tmp_path / "user"
    roots = [("LOCAL", local), ("USER", user)]
    scope, rel = wsyntax._scope_of(str(local / "sub" / "p.md"), roots)
    assert (scope, rel) == ("LOCAL", "sub/p.md")
    scope2, rel2 = wsyntax._scope_of(str(user / "sub" / "p.md"), roots)
    assert (scope2, rel2) == ("USER", "sub/p.md")
    # A page under NO root keeps its full path (still ticket-able, unambiguous).
    scope3, rel3 = wsyntax._scope_of("/elsewhere/p.md", roots)
    assert (scope3, rel3) == ("", "/elsewhere/p.md")


# ── req 5 (test 5): the grandfathered class tickets with its field anchor ────────────────────


def test_grandfathered_error_files_memcorp001_with_field_anchor(
    recorder: _Recorder, roots, tmp_path: Path
):
    """NOTE-2 made executable: `page-no-ocd` — a GRANDFATHERED ERROR that lands on disk without
    refusing a write — opens a MEMCORP-001 ticket whose anchor is `field:ocd` and whose body
    carries code + anchor + line, never page text."""
    page = str(tmp_path / "local" / "a.md")
    f = _finding("ERROR", page, 0, "page-no-ocd", "field:ocd")
    assert wsyntax._file_tickets([f], roots=roots) == 1
    call = recorder.calls[0]
    assert call["code"] == "MEMCORP-001"
    assert call["dedupe_key"] == "MEMCORP-001:LOCAL:a.md:page-no-ocd:field:ocd"
    assert call["where"] == "LOCAL:a.md:0"
    assert "field:ocd" in call["found"]
    assert "remedy" in call["detail"]


# ── req 6 (test 6): the 2x-size WARN opens ONE split ticket ──────────────────────────────────


def test_atom_oversized_critical_files_one_memcorp002(
    recorder: _Recorder, roots, tmp_path: Path
):
    """One atom over 2x budget ⇒ exactly one MEMCORP-002 ticket for that atom id; the owner's
    verbatim 2026-09-23 size-ticket rule rides in the body (A8); the remedy is atomize."""
    page = str(tmp_path / "local" / "a.md")
    f = _finding("WARN", page, 7, "atom-oversized-critical", "atom:ATOM-BIG-0001")
    assert wsyntax._file_tickets([f], roots=roots) == 1
    call = recorder.calls[0]
    assert call["code"] == "MEMCORP-002"
    assert (
        call["dedupe_key"]
        == "MEMCORP-002:LOCAL:a.md:atom-oversized-critical:atom:ATOM-BIG-0001"
    )
    assert call["advisory"].startswith("Owner ruling 2026-09-23")
    assert "warn but also open a ticket" in call["advisory"]
    assert "atomize" in call["detail"]


def test_second_pass_bumps_seen_count_not_a_new_ticket(recorder: _Recorder, roots, tmp_path: Path):
    """Same 2x atom on a second lint pass: the detector emits the SAME dedupe key (the
    open_ticket layer bumps seen_count) — verified here at the boundary this test owns: the
    key is stable across passes and no second call shape appears."""
    page = str(tmp_path / "local" / "a.md")
    f1 = _finding("WARN", page, 7, "atom-oversized-critical", "atom:ATOM-BIG-0001")
    f2 = _finding("WARN", page, 9, "atom-oversized-critical", "atom:ATOM-BIG-0001")
    assert wsyntax._file_tickets([f1], roots=roots) == 1
    assert wsyntax._file_tickets([f2], roots=roots) == 1
    assert recorder.calls[0]["dedupe_key"] == recorder.calls[1]["dedupe_key"]
    # An atom between 1x and 2x (plain INFO atom-oversized) yields none:
    assert (
        wsyntax._file_tickets(
            [_finding("INFO", page, 7, "atom-oversized", "atom:ATOM-BIG-0001")], roots=roots
        )
        == 0
    )
    assert len(recorder.calls) == 2


# ── req 7 (test 7): the USER-scope machine-wide claim ────────────────────────────────────────


def _claim_file() -> Path:
    return gs.global_state_dir() / "memgrep-ticket-claims.json"


def test_user_scope_claim_skips_second_project_within_ttl(
    recorder: _Recorder, monkeypatch, roots, tmp_path: Path
):
    """The same USER-scope finding claimed by one project is skipped by a second project
    within the TTL — through the FULL ticket path, not just the claim primitive."""
    page = str(tmp_path / "user" / "shared.md")
    key = "MEMCORP-001:USER:shared.md:page-no-ocd:field:ocd"

    # Project ONE files it (and holds the claim).
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/proj/one")
    assert wsyntax._file_tickets([_finding("ERROR", page, 3, "page-no-ocd", "field:ocd")], roots=roots) == 1
    data = json.loads(_claim_file().read_text(encoding="utf-8"))
    assert data[key]["project"] == "/proj/one"

    # Project TWO, same page: claim refused, ZERO tickets.
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/proj/two")
    assert wsyntax._file_tickets([_finding("ERROR", page, 3, "page-no-ocd", "field:ocd")], roots=roots) == 0
    assert len(recorder.calls) == 1  # only project one's raise is on record

    # The SAME project re-claiming its own key re-wins (idempotent heartbeat).
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/proj/one")
    assert wsyntax.claim_user_key(key) is True


def test_expired_claim_is_swept_and_key_reclaimable(monkeypatch):
    """A claim past the 7-day TTL is swept at the next fire; the second project then wins."""
    key = "MEMCORP-001:USER:s.md:page-no-ocd:field:ocd"
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/proj/one")
    assert wsyntax.claim_user_key(key, now=1000) is True
    # Within TTL, another project loses:
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", "/proj/two")
    assert wsyntax.claim_user_key(key, now=1000 + 7 * 86400 - 1) is False
    # At/after TTL, the sweep drops it and the second project wins:
    assert wsyntax.claim_user_key(key, now=1000 + 7 * 86400 + 1) is True
    data = json.loads(_claim_file().read_text(encoding="utf-8"))
    assert data[key]["project"] == "/proj/two"


def test_local_scope_findings_never_claim(recorder: _Recorder, roots, tmp_path: Path):
    """LOCAL/PROJECT pages are project-relative — the per-project store IS the right place.
    Only `scope == "user"` consults the claim file at all."""
    page = str(tmp_path / "local" / "only.md")
    assert wsyntax._file_tickets(
        [_finding("ERROR", page, 1, "page-no-ocd", "field:ocd")], roots=roots
    ) == 1
    assert not _claim_file().exists()


def test_claim_fails_open_when_state_dir_unwritable(recorder: _Recorder, monkeypatch):
    """A9: claims fail open. A vanished/unreadable claim file can cost one cross-project
    duplicate — never a lost finding. Simulated by pointing the state dir at a path whose
    PARENT is a file (os.open on the lock path raises) — the claim must return True anyway."""
    blocker = Path("/tmp") / f"not-a-dir-{time.time_ns()}"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setenv("JANITOR_GLOBAL_STATE_DIR", str(blocker / "subdir"))
    assert wsyntax.claim_user_key("k") is True
