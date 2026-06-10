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
from collections import defaultdict
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


def _file_block(fm: FileMap) -> list[str]:
    head = f"`{fm.path}` — {fm.role}" if fm.role else f"`{fm.path}`"
    return [head, *[_symbol_line(s.signature, s.doc) for s in fm.symbols]]


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


def render_body(filemaps: list[FileMap]) -> str:
    """Deterministic map body (no fences, no timestamp). Individual files first
    (sorted by path), then a '### Convention groups' section for collapsed
    families (sorted by pattern)."""
    by_path = sorted(filemaps, key=lambda f: f.path)

    groups: dict[_FamilyKey, list[FileMap]] = defaultdict(list)
    for fm in by_path:
        key = _family_key(fm.path)
        if key is not None:
            groups[key].append(fm)

    collapsed = {k for k, members in groups.items() if len(members) >= MIN_FAMILY}

    lines: list[str] = ["## Project map (auto-generated — do not edit between the fences)"]
    for fm in by_path:
        key = _family_key(fm.path)
        if key in collapsed:
            continue
        lines.extend(_file_block(fm))

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


def structure_hash(filemaps: list[FileMap]) -> str:
    """12-hex sha256 over the rendered body. Identical structure → identical
    hash (the volatile generated= stamp is excluded), so the maintainer can
    decide 'regen needed?' by comparing this to the fence's sha= in one read."""
    body = render_body(filemaps)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]


def render_block(filemaps: list[FileMap], *, generated_iso: str, digest: str) -> str:
    """The full fenced block ready to splice into CLAUDE.md. `digest` is the
    caller's repo-change digest (git HEAD + dirty state); `generated_iso` is
    the wall-clock stamp (excluded from the hash)."""
    body = render_body(filemaps)
    sha = hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    start = f"{FENCE_START} {_SCHEMA} sha={sha} digest={digest} generated={generated_iso}"
    return f"{start}\n{body}\n{FENCE_END}\n"
