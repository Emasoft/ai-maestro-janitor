#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""wikimem_syntax_lint — check that memory pages use the syntax memgrep can PARSE.

WHY this exists (owner directive 2026-07-21): "can I trust you are following the
right syntax every time you wrote an atom? otherwise you should create some script
that does it for you." Trusting an agent to hand-write a machine-parsed format is
the wrong safety model — the format has a CONSUMER (memgrep) whose parser is the
ONLY authority on what is and is not a valid element. This linter encodes THAT
parser's rules verbatim, so a page that would be silently invisible to recall is
caught mechanically instead of trusted.

The rules are ported 1:1 from `scripts/memgrep/src/memory.rs` (the ground truth):

  * ATOM marker (`first_block_property_marker`, memory.rs:1346): an atom is
    recognised ONLY as `^<id> [<props>]` with an ASCII caret `^`, id charset
    `[A-Za-z0-9_-]+`, and ASCII square brackets `[` `]`. The recall display escapes
    `[`/`]` to `⟦`/`⟧` to avoid markdown-link parsing — so an atom hand-copied FROM
    recall output (using `⟦⟧`) is structurally invisible: memgrep's byte scan for
    `b'['` (0x5B) never matches `⟦` (U+27E6). This is the #1 failure mode.
  * `keywords:` is the atom's RECALL SURFACE (memory.rs:1398). No keywords ⇒ the
    atom is un-findable ⇒ "the memory does not exist." CRITICAL.
  * LESSON footnote (`[^N]:`, memory.rs:1887): its leading `[...]` metadata carries
    `keywords:` (recall surface), `status:` (`valid`/`superseded`), and — when
    superseded — `superseded-by:` (the forward pointer, memory.rs:337).
  * PAGE frontmatter (memory.rs:980 reads element_type/ocd/lmd/topic/title/
    description/tags): `description:` is the page recall surface.

It is LENIENT exactly where memgrep is lenient (both `desc:"…"` and `desc: "…"`;
comma-phrase AND quoted keyword lists; the `superseeded` misspelling) — it flags
ONLY what would actually break recall or lose lifecycle semantics, never style.

Exit status: 0 when no CRITICAL findings, 1 when any CRITICAL. READ-ONLY — it never
edits a page (RULE 0 / separation of powers: the linter surfaces, an agent fixes).
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

# ── the exact recognizers memgrep uses ──────────────────────────────────────────
# Atom id charset is [A-Za-z0-9_-] (memory.rs:1353). We anchor at line start (after
# optional indent) because authored atoms are LEADING; a trailing block-ref is rare
# and not something we author, so anchoring keeps false positives out.
_ATOM_ASCII = re.compile(r"^(?P<indent>\s*)\^(?P<id>[A-Za-z0-9_-]+)\s*\[")
# The display-escaped / wrong-bracket forms memgrep will NOT recognise as an atom.
_ATOM_MANGLED = re.compile(r"^\s*\^(?P<id>[A-Za-z0-9_-]+)\s*(?P<bad>[⟦【〔「])")
# Footnote definition (memory.rs:1887 — `^\s*\[\^([^\]\s]+)\]:`).
_FN_DEF = re.compile(r"^(?P<indent>\s*)\[\^(?P<label>[^\]\s]+)\]:\s*(?P<rest>.*)$")
_HEADING = re.compile(r"^#{1,6}\s")

SEVERITIES = ("CRITICAL", "WARN")


@dataclass
class Finding:
    path: Path
    line: int
    sev: str
    code: str
    msg: str


# ── port of memgrep's block-prop parser (memory.rs:158/1314) ─────────────────────
def _split_top_level_commas(s: str) -> list[str]:
    """Split on commas that are NOT inside `[...]` brackets or `"..."` quotes.

    Mirrors memory.rs:158 — a comma inside a `[[wikilink]]` value or a quoted
    `desc:"…, …"` value must not split the property list.
    """
    out: list[str] = []
    depth = 0
    in_quote = False
    start = 0
    for i, ch in enumerate(s):
        if ch == '"':
            in_quote = not in_quote
        elif not in_quote and ch == "[":
            depth += 1
        elif not in_quote and ch == "]":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0 and not in_quote:
            out.append(s[start:i])
            start = i + 1
    out.append(s[start:])
    return out


def parse_block_props(props: str) -> dict[str, list[str]]:
    """`key: value, key2: a b c` → {key: [value...]}. Port of memory.rs:1314.

    Split on top-level commas → items; split each item on its FIRST `:`; shed a
    value's delimiting quotes; whitespace-split the value into its array.
    """
    out: dict[str, list[str]] = {}
    for item in _split_top_level_commas(props):
        if ":" not in item:
            continue
        key, val = item.split(":", 1)
        key = key.strip()
        if not key:
            continue
        val = val.strip()
        if val.startswith('"'):
            val = val[1:].rstrip('"') if val.endswith('"') else val[1:]
        out[key] = val.split()
    return out


def _extract_bracket_span(s: str, open_idx: int) -> tuple[str, int] | None:
    """From the `[` at `open_idx`, return (inner_props, index_one_past_close).

    Bracket-DEPTH tracked so a `[[wikilink]]` inside props cannot close it early
    (memory.rs:1362). None when the bracket is never closed on this line.
    """
    depth = 0
    for m in range(open_idx, len(s)):
        if s[m] == "[":
            depth += 1
        elif s[m] == "]":
            depth -= 1
            if depth == 0:
                return s[open_idx + 1 : m], m + 1
    return None


def _is_iso_date(v: str) -> bool:
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}", v))


# ── per-element checks ───────────────────────────────────────────────────────────
def _check_atom(path: Path, lineno: int, line: str, findings: list[Finding]) -> None:
    mangled = _ATOM_MANGLED.match(line)
    if mangled:
        findings.append(
            Finding(
                path,
                lineno,
                "CRITICAL",
                "atom-bad-bracket",
                f"atom `^{mangled['id']}` opens with `{mangled['bad']}` not ASCII `[` — "
                "memgrep scans for byte `[` (0x5B) and will NOT index this atom; it is "
                "invisible to recall. Use `^id [key: value, …]`.",
            )
        )
        return

    m = _ATOM_ASCII.match(line)
    if not m:
        return
    open_idx = line.index("[", m.end() - 1)
    span = _extract_bracket_span(line, open_idx)
    if span is None:
        findings.append(
            Finding(path, lineno, "CRITICAL", "atom-unclosed",
                    f"atom `^{m['id']}` block-props `[` is never closed on this line — unparseable.")
        )
        return
    props = parse_block_props(span[0])
    kw = props.get("keywords")
    if not kw:
        findings.append(
            Finding(path, lineno, "CRITICAL", "atom-no-keywords",
                    f"atom `^{m['id']}` has no `keywords:` — it is the RECALL SURFACE; "
                    "without it the atom is un-findable by symptom (the memory does not exist).")
        )
    for datekey in ("ocd", "lmd"):
        val = props.get(datekey)
        if not val:
            findings.append(Finding(path, lineno, "WARN", f"atom-no-{datekey}",
                                    f"atom `^{m['id']}` has no `{datekey}:` date."))
        elif not _is_iso_date(val[0]):
            findings.append(Finding(path, lineno, "WARN", f"atom-bad-{datekey}",
                                    f"atom `^{m['id']}` `{datekey}:` = `{val[0]}` is not ISO YYYY-MM-DD."))


def _check_footnote(path: Path, lineno: int, rest: str, label: str, findings: list[Finding]) -> None:
    stripped = rest.lstrip()
    # The lesson metadata is a LEADING `[...]` block right after `[^N]:`.
    if "⟦" in rest and not stripped.startswith("["):
        findings.append(
            Finding(path, lineno, "CRITICAL", "lesson-bad-bracket",
                    f"lesson `[^{label}]` metadata uses `⟦…⟧` not ASCII `[…]` — memgrep cannot "
                    "parse its keywords/status; recall + supersession break. Use `[id:… keywords:…]`.")
        )
        return
    if not stripped.startswith("["):
        findings.append(
            Finding(path, lineno, "WARN", "lesson-no-meta",
                    f"lesson `[^{label}]` has no leading `[id:… status:… keywords:… ocd:… lmd:…]` "
                    "metadata block — it carries no recall keywords and no stable id.")
        )
        return
    span = _extract_bracket_span(stripped, 0)
    if span is None:
        findings.append(Finding(path, lineno, "WARN", "lesson-unclosed-meta",
                                f"lesson `[^{label}]` metadata `[` never closes."))
        return
    props = parse_block_props(span[0])
    if not props.get("keywords"):
        findings.append(Finding(path, lineno, "WARN", "lesson-no-keywords",
                                f"lesson `[^{label}]` metadata has no `keywords:` — not recallable by symptom."))
    if not props.get("id"):
        findings.append(Finding(path, lineno, "WARN", "lesson-no-id",
                                f"lesson `[^{label}]` has no `id:ATOM-…` — the `[^N]` label renumbers; "
                                "only the stable id survives edits."))
    status = (props.get("status") or ["valid"])[0]
    if status in ("superseded", "superseeded") and not props.get("superseded-by") and not props.get("superseeded-by"):
        findings.append(Finding(path, lineno, "WARN", "lesson-superseded-no-pointer",
                                f"lesson `[^{label}]` is `status:superseded` but has no `superseded-by:ATOM-…` "
                                "forward pointer."))


def _parse_frontmatter(text: str) -> dict[str, str] | None:
    """Flat `key: value` scan of a leading `---`…`---` block (memory.rs:572 is equally lenient)."""
    if not text.startswith("---"):
        return None
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return None
    fm: dict[str, str] = {}
    for ln in lines[1:]:
        if ln.strip() == "---":
            return fm
        m = re.match(r"^(\w[\w-]*):\s?(.*)$", ln)
        if m:
            fm[m.group(1)] = m.group(2).strip()
    return None  # no closing fence


def lint_page(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    fm = _parse_frontmatter(text)
    if fm is None:
        findings.append(Finding(path, 1, "WARN", "page-no-frontmatter",
                                "page has no closed `---` frontmatter block."))
    else:
        if not fm.get("description"):
            findings.append(Finding(path, 1, "CRITICAL", "page-no-description",
                                    "frontmatter has no `description:` — the PAGE recall surface "
                                    "memgrep ranks on; without it the page barely surfaces."))
        for k in ("name", "ocd", "lmd"):
            if not fm.get(k):
                findings.append(Finding(path, 1, "WARN", f"page-no-{k}", f"frontmatter has no `{k}:`."))

    in_code = False
    has_notes_section = False
    for i, line in enumerate(text.splitlines(), start=1):
        fence = line.lstrip()
        if fence.startswith("```") or fence.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        if _HEADING.match(line):
            low = line.lower()
            if "notes and lessons learned" in low or "lessons learned" in low:
                has_notes_section = True
            continue
        _check_atom(path, i, line, findings)
        fn = _FN_DEF.match(line)
        if fn:
            _check_footnote(path, i, fn["rest"], fn["label"], findings)
        elif "⟦" in line and _ATOM_MANGLED.match(line) is None:
            # A stray display-escaped bracket anywhere else is worth a nudge.
            findings.append(Finding(path, i, "WARN", "stray-display-bracket",
                                    "line contains `⟦`/`⟧` (memgrep's recall DISPLAY escaping) — "
                                    "in a source page these should be literal `[`/`]`."))

    if not has_notes_section:
        findings.append(Finding(path, 1, "WARN", "page-no-notes-section",
                                "no `## Notes and lessons learned` section (mandatory landing zone "
                                "for correction lessons, even when empty)."))
    return findings


def extract_atom_ids(text: str) -> list[tuple[str, int]]:
    """Every well-formed ASCII atom id in the page body, with its 1-based line.

    Feeds the corpus-wide duplicate-id check: memgrep requires atom ids be corpus-unique
    (memory.rs — "atom ids must be corpus-unique … corpus corruption to repair"), and a
    collision makes `recall` on that id ambiguous. A mangled `⟦`-bracket atom is NOT
    collected (memgrep does not see it as an atom; `_check_atom` flags it separately).
    """
    out: list[tuple[str, int]] = []
    in_code = False
    for i, line in enumerate(text.splitlines(), start=1):
        fence = line.lstrip()
        if fence.startswith("```") or fence.startswith("~~~"):
            in_code = not in_code
            continue
        if in_code:
            continue
        m = _ATOM_ASCII.match(line)
        if m:
            out.append((m["id"], i))
    return out


def find_duplicate_atom_ids(pages: dict[Path, str]) -> dict[str, list[str]]:
    """Map each atom id appearing more than once across the corpus → its sorted `file:line`
    locations. Empty when every id is unique. PURE over the given pages — this is the one
    check that CANNOT be done per-file (a collision spans two pages)."""
    locs: dict[str, list[str]] = {}
    for path, text in pages.items():
        for aid, line in extract_atom_ids(text):
            locs.setdefault(aid, []).append(f"{path}:{line}")
    return {aid: sorted(where) for aid, where in locs.items() if len(where) > 1}


# ── file walking + CLI ───────────────────────────────────────────────────────────
def _iter_md(target: Path) -> list[Path]:
    if target.is_file():
        return [target] if target.suffix == ".md" else []
    out: list[Path] = []
    for root, _, files in os.walk(target):
        for f in files:
            if f.endswith(".md") and f != "MEMORY.md":
                out.append(Path(root) / f)
    return sorted(out)


def _default_roots() -> list[Path]:
    home = Path.home()
    roots: list[Path] = []
    user = home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins" / "memory"
    if user.is_dir():
        roots.append(user)
    cwd = Path.cwd()
    proj = cwd / ".claude" / "project" / "memory"
    if proj.is_dir():
        roots.append(proj)
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(cwd))
    local = home / ".claude" / "projects" / slug / "memory"
    if local.is_dir():
        roots.append(local)
    return roots


def main() -> int:
    ap = argparse.ArgumentParser(description="Lint wikimem pages against memgrep's parser rules.")
    ap.add_argument("paths", nargs="*", help="Pages or dirs to lint (default: the 3 memory scopes).")
    ap.add_argument("--quiet-ok", action="store_true", help="Print nothing when a file is clean.")
    args = ap.parse_args()

    targets = [Path(p) for p in args.paths] if args.paths else _default_roots()
    files: list[Path] = []
    for t in targets:
        files.extend(_iter_md(t))
    if not files:
        print("wikimem-lint: no .md pages found.", file=sys.stderr)
        return 0

    total = {s: 0 for s in SEVERITIES}
    pages: dict[Path, str] = {}
    for f in sorted(set(files)):
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            print(f"{f}: unreadable ({e})", file=sys.stderr)
            continue
        pages[f] = text
        findings = lint_page(f, text)
        if not findings:
            if not args.quiet_ok:
                print(f"✓ {f}")
            continue
        print(f"\n{f}")
        for fd in sorted(findings, key=lambda x: (SEVERITIES.index(x.sev), x.line)):
            total[fd.sev] += 1
            print(f"  {fd.sev:8} L{fd.line:<4} [{fd.code}] {fd.msg}")

    dups = find_duplicate_atom_ids(pages)
    if dups:
        print("\n── corpus-wide duplicate atom ids (memgrep requires them unique) ──")
        for aid, where in sorted(dups.items()):
            total["CRITICAL"] += 1
            print(f"  CRITICAL      [atom-dup-id] `^{aid}` appears {len(where)}× — {', '.join(where)}")

    print(f"\nwikimem-lint: {len(set(files))} pages, "
          f"{total['CRITICAL']} CRITICAL, {total['WARN']} WARN")
    return 1 if total["CRITICAL"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
