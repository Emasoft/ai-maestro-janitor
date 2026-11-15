# Project-map renderer — FileMaps → the fenced CLAUDE.md block (TRDD-e247a349 §2).
#
# Produces the marker-fenced, deterministic, compact map. The maintainer
# detector (later phase) decides WHEN to (re)render; this module is pure:
# same FileMaps → byte-identical body → identical structure hash.
#
# Compactness levers (TRDD §2):
#   - one line per file: `path` — role
#   - one indented line per public symbol: · name(params) -> Ret — doc-first-line
#   - convention-collapse: a dir + filename-suffix family of ≥ MIN_FAMILY members
#     collapses to ONE group line + a bracketed stem list (the 200-pattern-lib
#     case → two lines). Conservative by design: under-collapse beats
#     over-collapse (a wrongly-merged family hides real structure).
#   - structure hash over the body (NOT the volatile generated= stamp), so a
#     no-op re-render yields the same sha → the maintainer skips the write.

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass

from .extractor import FileMap

# Unusual, collision-proof fences — a one-shot grep/splice target for the
# maintainer (extract-between-fences, splice-back; no markdown parsing) and a
# loud "do not edit" signal to humans.
FENCE_START = "<+-+-JANITOR-REPO-MAP-START-(do-not-modify)-+-+>"
FENCE_END = "<+-+-JANITOR-REPO-MAP-END-(do-not-modify)-+-+>"

# A dir + trailing-token family collapses only at this many members — high
# enough that genuine small clusters stay expanded.
MIN_FAMILY = 8

# Cap the bracketed member-name list of a collapsed family. A 223-member
# family must not spell out 223 names (two such lines once dominated the whole
# map); the first names + a "+N more" keep the line scannable, and the full
# roster is one `ls`/glob away on disk. Deterministic (sorted members, fixed
# cut) so the structure hash stays stable.
MAX_FAMILY_NAMES = 10

_SCHEMA = "v1"

# PROJECT_MAP.md (the root file that replaces the CLAUDE.md fence, TRDD-FADYLSQB):
# one single-line HTML-comment header, no fences. Schema v2 because the body
# is names-only; v1 is the fenced CLAUDE.md block above.
_FILE_SCHEMA = "v2"
# The digest is hex (git) or `mtime-N` (non-git). Restricting it to this charset keeps the
# header a single-line HTML comment: a `-->` or newline in a digest would end the comment early
# or split the header, and read_header would then report a valid map as "not a map".
_DIGEST_CHARS = r"[0-9A-Za-z._-]+"
_HEADER_RE = re.compile(
    r"<!-- project-map (?P<schema>v[0-9]+) sha=(?P<sha>[0-9a-f]{12}) methods=(?P<methods>[01]) "
    rf"digest=(?P<digest>{_DIGEST_CHARS}) generated=(?P<generated>\S+) -->"
)
_LEGACY_HEADING = "## Project map (auto-generated — do not edit between the fences)"
_MAP_HEADING = "# Project map (generated, do not edit)\nPer file: path — role, then its public symbol names."


@dataclass(frozen=True)
class _FamilyKey:
    directory: str
    token: str  # trailing underscore-segment of the stem, e.g. "patterns"


def _stem(path: str) -> str:
    base = path.rsplit("/", 1)[-1]
    return base[:-3] if base.endswith(".py") else base


def _family_key(path: str) -> _FamilyKey | None:
    """(dir, trailing-token) family key, or None when the filename has no
    underscore-delimited trailing token (core files like state.py never
    collapse)."""
    directory = path.rsplit("/", 1)[0] if "/" in path else ""
    stem = _stem(path)
    if "_" not in stem:
        return None
    return _FamilyKey(directory=directory, token=stem.rsplit("_", 1)[-1])


def _stem_prefix(path: str) -> str:
    """The distinguishing part of the filename — stem minus the trailing
    `_token` (e.g. cloud_credential_patterns → cloud_credential)."""
    stem = _stem(path)
    return stem.rsplit("_", 1)[0] if "_" in stem else stem


def _symbol_line(signature: str, doc: str) -> str:
    return f"  · {signature} — {doc}" if doc else f"  · {signature}"


def _file_head(fm: FileMap) -> str:
    return f"`{fm.path}` — {fm.role}" if fm.role else f"`{fm.path}`"


def _file_block(fm: FileMap) -> list[str]:
    return [_file_head(fm), *[_symbol_line(s.signature, s.doc) for s in fm.symbols]]


def _common_role(members: list[FileMap]) -> str:
    """Representative role for a collapsed family — ONLY when a genuine majority
    of members share it (AC9 / error-prevention). When every member has a
    distinct role (e.g. the 200+ *_patterns.py, each a different attack class),
    there is NO representative role: showing one arbitrary member's role would
    mislead a reader into thinking the whole family is about that one thing. In
    that case return "" and let the self-describing stem list carry the meaning."""
    counts: dict[str, int] = defaultdict(int)
    for m in members:
        if m.role:
            counts[m.role] += 1
    if not counts:
        return ""
    mode = max(counts, key=lambda r: (counts[r], r))
    # Require a strict majority — a shared role must describe >half the family
    # to be honest as "the" family role.
    return mode if counts[mode] * 2 > len(members) else ""


def _render(
    filemaps: list[FileMap],
    *,
    heading: str,
    file_block: Callable[[FileMap], list[str]],
    coverage_note: str | None,
) -> str:
    """Deterministic map body (no fences, no timestamp). Individual files first
    (sorted by path), then a '### Convention groups' section for collapsed
    families (sorted by pattern).

    `coverage_note`, when given, is an honest one-line disclaimer inserted right
    under the heading (#175: a Python-only extractor on a mostly-TypeScript repo
    produced a map covering 18 peripheral scripts and ZERO app files, presented
    under a heading that looks complete — the caller computes the note from
    what the registry could NOT parse; this function only places it so it stays
    part of the hashed, rendered block instead of silently absent)."""
    by_path = sorted(filemaps, key=lambda f: f.path)

    groups: dict[_FamilyKey, list[FileMap]] = defaultdict(list)
    for fm in by_path:
        key = _family_key(fm.path)
        if key is not None:
            groups[key].append(fm)

    collapsed = {k for k, members in groups.items() if len(members) >= MIN_FAMILY}

    lines: list[str] = [heading]
    if coverage_note:
        lines.append(coverage_note)
    for fm in by_path:
        key = _family_key(fm.path)
        if key in collapsed:
            continue
        lines.extend(file_block(fm))

    family_lines: list[str] = []
    for key in sorted(collapsed, key=lambda k: (k.directory, k.token)):
        members = sorted(groups[key], key=lambda f: f.path)
        names = [_stem_prefix(m.path) for m in members]
        if len(names) > MAX_FAMILY_NAMES:
            shown = names[:MAX_FAMILY_NAMES]
            prefixes = ", ".join(shown) + f", … +{len(names) - len(shown)} more"
        else:
            prefixes = ", ".join(names)
        role = _common_role(members)
        pattern = f"`{key.directory}/*_{key.token}.py`" if key.directory else f"`*_{key.token}.py`"
        head = f"{pattern} (×{len(members)})"
        if role:
            head += f" — {role}"
        family_lines.append(f"{head} [{prefixes}]")

    if family_lines:
        lines.append("### Convention groups")
        lines.extend(family_lines)

    return "\n".join(lines)


def render_body(filemaps: list[FileMap], *, coverage_note: str | None = None) -> str:
    """The legacy fenced-block body (signatures + docs). `coverage_note`: see _render."""
    return _render(filemaps, heading=_LEGACY_HEADING, file_block=_file_block, coverage_note=coverage_note)


def structure_hash(filemaps: list[FileMap], *, coverage_note: str | None = None) -> str:
    """12-hex sha256 over the rendered body. Identical structure → identical
    hash (the volatile generated= stamp is excluded), so the maintainer can
    decide 'regen needed?' by comparing this to the fence's sha= in one read.

    `coverage_note` participates in the hash like any other body content: when
    the uncovered-file count changes enough to flip the note, that IS a
    structural change worth a refresh (see render_body)."""
    body = render_body(filemaps, coverage_note=coverage_note)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def render_block(filemaps: list[FileMap], *, generated_iso: str, digest: str, coverage_note: str | None = None) -> str:
    """The full fenced block ready to splice into CLAUDE.md. `digest` is the
    caller's repo-change digest (git HEAD + dirty state); `generated_iso` is
    the wall-clock stamp (excluded from the hash); `coverage_note` is the
    optional #175 disclaimer (see render_body)."""
    body = render_body(filemaps, coverage_note=coverage_note)
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    start = f"{FENCE_START} {_SCHEMA} sha={sha} digest={digest} generated={generated_iso}"
    return f"{start}\n{body}\n{FENCE_END}\n"


def _sha12(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def _names_block(fm: FileMap, include_methods: bool) -> list[str]:
    kinds = ("func", "class", "method") if include_methods else ("func", "class")
    names = ", ".join(s.name for s in fm.symbols if s.kind in kinds)
    return [_file_head(fm), f"  {names}"] if names else [_file_head(fm)]


def render_map_body(filemaps: list[FileMap], *, include_methods: bool = True, coverage_note: str | None = None) -> str:
    """The names-only PROJECT_MAP.md body: per file the path and role, then ONE
    indented line of public symbol names (`include_methods` adds `Class.method`
    names). Same family collapse as the legacy body. No fences, no timestamp."""
    return _render(
        filemaps,
        heading=_MAP_HEADING,
        file_block=lambda fm: _names_block(fm, include_methods),
        coverage_note=coverage_note,
    )


def map_sha(filemaps: list[FileMap], *, include_methods: bool = True, coverage_note: str | None = None) -> str:
    """12-hex sha256 of the names-only body: THE one hash helper, called by the
    writer (via render_file) and by the drift detector. `coverage_note` is part
    of the body and therefore of the hash — the detector must pass the same note
    the writer rendered with, or it compares different bodies and reports a
    phantom STALE forever (TRDD-6HFOB5S4: the old detector omitted it)."""
    return _sha12(render_map_body(filemaps, include_methods=include_methods, coverage_note=coverage_note))


def render_file(
    filemaps: list[FileMap],
    *,
    generated_iso: str,
    digest: str,
    include_methods: bool = True,
    coverage_note: str | None = None,
) -> str:
    """The whole PROJECT_MAP.md text: one header line (schema, body sha, methods flag, digest,
    generated time; none of the last two is hashed) then the names-only body."""
    if not re.fullmatch(_DIGEST_CHARS, digest):
        raise ValueError(f"digest must match {_DIGEST_CHARS}: {digest!r}")
    if not generated_iso or re.search(r"\s", generated_iso):
        # The header is whitespace-tokenised; a space would break read_header.
        raise ValueError(f"generated_iso must be non-empty and contain no whitespace: {generated_iso!r}")
    body = render_map_body(filemaps, include_methods=include_methods, coverage_note=coverage_note)
    # methods= records which include_methods value produced the sha, so a reader that hashes with
    # a different value is diagnosable (and --check hashes with the value the header names)
    # instead of reporting a phantom STALE forever.
    header = (
        f"<!-- project-map {_FILE_SCHEMA} sha={_sha12(body)} methods={int(include_methods)} "
        f"digest={digest} generated={generated_iso} -->"
    )
    return f"{header}\n{body}\n"


def read_header(text: str) -> dict[str, str] | None:
    """Parse the first line of a PROJECT_MAP.md into schema/sha/methods/digest/generated;
    None when it is not a project-map header."""
    match = _HEADER_RE.fullmatch(text.split("\n", 1)[0].strip())
    return match.groupdict() if match else None
