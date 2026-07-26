#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""wikimem retrieval benchmark — accuracy and END-TO-END token cost (TRDD-DO6X4ZF8).

Grepping efficiency IS the memory system: the value of wikimem is how few tokens an agent must
read to reach the atom it wants. That makes it measurable, so it is measured here, and every
change to ranking or output is scored against a committed baseline instead of argued on taste.

TWO METRICS
  accuracy  — for each `(symptom query -> expected atom)` pair: is the atom returned, at what
              rank? Reported as hit@1 / hit@3 / hit@10 and MRR.
  tokens    — the END-TO-END cost to FIND and OBTAIN that atom:
                  tokens(search output) + tokens(the second-hop call, if one is needed)

WHY END-TO-END, and not per-call. A per-call metric would flatter a thin listing while hiding the
second hop it forces, and would equally punish a fat one-shot that needs no hop. Only the total
answers the real question — *what does it cost to obtain this fact?* — and it is what makes the
layered-output design provable rather than merely plausible:

    cost(basic) = N * one_line + 1 * full_atom
    cost(full)  = N * (body + metadata + keywords + notes + superseded)

so the advantage grows with N, and this harness shows exactly where it crosses over.

THE HOP IS DETECTED, NEVER ASSUMED. Today `recall` prints each atom's full body inline, so the
answer is already in hand and there is NO second hop; after the layered-output work, `basic` will
return a bare listing and a hop becomes necessary. Assuming one or the other would silently
mis-score whichever end of that change is being measured, so the harness checks whether the
target atom's body is already present in the search output and only pays for a hop when it is
not. `hop_used` is reported per query.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_QUERIES = REPO / "tests" / "wikimem_bench" / "queries.json"
DEFAULT_BASELINE = REPO / "tests" / "wikimem_bench" / "baseline.json"

# The binary under test. Overridable so a freshly-built `target/release/memgrep` can be measured
# BEFORE it is installed — otherwise every measurement silently scores whatever is on PATH, which
# is the one mistake that would make this instrument report the old build's numbers as the new
# build's improvement.
MEMGREP = os.environ.get("MEMGREP_BIN", "memgrep")

# A RICH result line (`--output full`): an absolute .md path, optionally `#atom-id`, optionally
# ` — summary`. Anchored on the path so prose in an atom body can never be mistaken for a row.
_RESULT_RE = re.compile(r"^(?P<path>/\S+?\.md)(?:#(?P<atom>\S+))?(?:\s+—\s+(?P<summary>.*))?$")

# A LAYERED result row (`--output basic|medium`, the default): `<lmd>\t<locator>\t<description>`.
# The date column is anchored on `-` or an ISO date PREFIX rather than "anything before a tab", so a
# body line that happens to contain a tab can never be counted as a result. The tail is `\S*` because
# `lmd:` is a bare date in the wiki corpus but a full `…T13:38:44Z` timestamp elsewhere — and `\S*`
# cannot cross the tab, so the column stays exact either way.
_LAYERED_RE = re.compile(r"^(?P<date>-|\d{4}-\d{2}-\d{2}\S*)\t(?P<loc>[^\t]+)\t(?P<label>.*)$")


def result_key(locator: str) -> str:
    """Normalize a row's locator to the id the benchmark matches on.

    The layered layers print the ATOM ID alone (a memory path costs ~25 tokens, which is most of
    what `basic` exists to save) while the rich layer prints `path#atom-id`. Both name the same
    atom, and atom ids are corpus-unique (the linter's `atom-dup-id` is CRITICAL), so reducing both
    to the bare id compares formats on WHAT THEY FOUND rather than on how they spell it — which is
    the only way a format change can be measured instead of merely detected.
    """
    page, _, atom = locator.partition("#")
    if atom:
        return atom
    return Path(page).stem if ("/" in page or page.endswith(".md")) else page


def expect_key(expect: str) -> str:
    """The same normalization applied to a query's expected `page#atom` (or bare `page`)."""
    _, _, atom = expect.partition("#")
    return atom or expect


def estimate_tokens(text: str) -> int:
    """A deterministic, offline token estimate.

    This is a RELATIVE instrument. The benchmark compares successive versions of the same tool on
    the same corpus, so what matters is that the estimator is stable, hermetic (no network, no API
    key, no drift between runs) and monotone in output size — a bias that is identical on both
    sides cancels in the delta. It is NOT a billing oracle, and no decision here should depend on
    its absolute value; `bytes` is reported alongside so every number stays auditable, and swapping
    in a real tokenizer later means replacing this one function.

    ~4 characters per token is the usual English-plus-identifiers approximation.
    """
    return math.ceil(len(text) / 4)


def run_recall(query: str, corpus: Path, extra: list[str], top: int) -> str:
    """Run `memgrep recall` and return its stdout (stderr folded in, so a failure is visible)."""
    cmd = [MEMGREP, "recall", query, str(corpus), "--top", str(top), *extra]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    return proc.stdout + proc.stderr


def parse_results(out: str) -> list[str]:
    """Ordered result ids (normalized by `result_key`), across BOTH output formats.

    Only lines matching an anchored result pattern count, so an atom's body text — which is
    interleaved with the rows in the rich format — can never be counted as a hit.
    """
    ids: list[str] = []
    for line in out.splitlines():
        line = line.rstrip()
        if m := _LAYERED_RE.match(line):
            ids.append(result_key(m.group("loc")))
            continue
        if m := _RESULT_RE.match(line):
            stem = Path(m.group("path")).stem
            atom = m.group("atom")
            ids.append(result_key(f"{stem}#{atom}" if atom else stem))
    return ids


def atom_body_present(out: str, expect: str, corpus: Path) -> bool:
    """True iff the search output already contains the expected atom's BODY.

    Decides whether a second hop is needed. Compares against the atom's real body as read from the
    corpus (its first substantive line), rather than trusting the output's shape — the output
    format is exactly what changes across the versions being compared, so keying on it would make
    the measurement circular.
    """
    page, _, atom_id = expect.partition("#")
    if not atom_id:
        return False
    src = (corpus / f"{page}.md")
    if not src.is_file():
        return False
    text = src.read_text(encoding="utf-8", errors="replace")
    marker = f"^{atom_id} ["
    idx = text.find(marker)
    if idx < 0:
        return False
    after = text[idx:].split("\n", 1)
    if len(after) < 2:
        return False
    for probe in after[1].splitlines():
        probe = probe.strip()
        if len(probe) >= 40 and not probe.startswith(("^", "#", "[")):
            return probe in out
    return False


def run_hop(expect: str, corpus: Path) -> str:
    """The second hop: obtain the full atom once its id is known.

    `memgrep recall <ATOM-ID>` is the exact-id lookup, and passing a bare id is exactly what an
    agent does after scanning a `basic` listing — so the hop is priced as the real thing the agent
    would run, not as a proxy for it.
    """
    _, _, atom_id = expect.partition("#")
    proc = subprocess.run(
        [MEMGREP, "recall", atom_id, str(corpus), "--top", "1"],
        capture_output=True, text=True, timeout=120,
    )
    return proc.stdout + proc.stderr


def score(queries: list[dict], corpus: Path, extra: list[str], top: int) -> dict:
    rows = []
    for q in queries:
        out = run_recall(q["q"], corpus, extra, top)
        ids = parse_results(out)
        expect = q["expect"]
        key = expect_key(expect)
        rank = ids.index(key) + 1 if key in ids else 0

        find_tokens = estimate_tokens(out)
        find_bytes = len(out)

        # Only pay for a hop when the answer is not already in hand, and only when we actually
        # found the atom — pricing a hop for a MISS would reward a tool that returns nothing.
        hop_used = False
        hop_tokens = 0
        hop_bytes = 0
        if rank > 0 and not atom_body_present(out, expect, corpus):
            hop = run_hop(expect, corpus)
            hop_used = True
            hop_tokens = estimate_tokens(hop)
            hop_bytes = len(hop)

        rows.append({
            "q": q["q"],
            "expect": expect,
            "kw_pos": q.get("kw_pos"),
            "rank": rank,
            "find_tokens": find_tokens,
            "hop_tokens": hop_tokens,
            "total_tokens": find_tokens + hop_tokens,
            "bytes": find_bytes + hop_bytes,
            "hop_used": hop_used,
        })

    n = len(rows) or 1
    found = [r for r in rows if r["rank"] > 0]
    summary = {
        "queries": len(rows),
        "hit_at_1": round(sum(1 for r in rows if r["rank"] == 1) / n, 4),
        "hit_at_3": round(sum(1 for r in rows if 0 < r["rank"] <= 3) / n, 4),
        "hit_at_10": round(sum(1 for r in rows if 0 < r["rank"] <= 10) / n, 4),
        "mrr": round(sum(1 / r["rank"] for r in found) / n, 4),
        "mean_total_tokens": round(sum(r["total_tokens"] for r in rows) / n, 1),
        "total_tokens": sum(r["total_tokens"] for r in rows),
        "total_bytes": sum(r["bytes"] for r in rows),
        "hops_used": sum(1 for r in rows if r["hop_used"]),
    }
    return {"summary": summary, "rows": rows}


def render(res: dict) -> str:
    s = res["summary"]
    out = [
        "",
        "wikimem retrieval benchmark",
        "─" * 78,
        f"  queries            {s['queries']}",
        f"  hit@1              {s['hit_at_1']:.1%}",
        f"  hit@3              {s['hit_at_3']:.1%}",
        f"  hit@10             {s['hit_at_10']:.1%}",
        f"  MRR                {s['mrr']:.4f}",
        f"  mean tokens/query  {s['mean_total_tokens']}   (total {s['total_tokens']}, {s['total_bytes']} bytes)",
        f"  second hops used   {s['hops_used']}/{s['queries']}",
        "─" * 78,
    ]
    # Group misses by keyword position — the shape that exposes the Phase 1.3 truncation.
    by_pos: dict[int, list[int]] = {}
    for r in res["rows"]:
        p = r.get("kw_pos") or 0
        by_pos.setdefault(p, []).append(r["rank"])
    out.append("  accuracy by keyword position (pos 1 = before the first comma):")
    for pos in sorted(by_pos):
        ranks = by_pos[pos]
        hits = sum(1 for x in ranks if x > 0)
        out.append(f"    pos {pos}: {hits}/{len(ranks)} found")
    out.append("─" * 78)
    for r in res["rows"]:
        mark = "ok  " if r["rank"] == 1 else (f"#{r['rank']:<3}" if r["rank"] else "MISS")
        out.append(f"  {mark} kw{r.get('kw_pos') or '?'}  {r['total_tokens']:>6}t  {r['q'][:52]}")
    out.append("")
    return "\n".join(out)


def compare(cur: dict, base: dict, tol_tokens: float) -> tuple[bool, list[str]]:
    """Regression gate. Accuracy may never drop; tokens may not rise beyond tolerance."""
    msgs: list[str] = []
    ok = True
    c, b = cur["summary"], base["summary"]
    for key in ("hit_at_1", "hit_at_3", "hit_at_10", "mrr"):
        if c[key] < b[key] - 1e-9:
            ok = False
            msgs.append(f"REGRESSION {key}: {b[key]} -> {c[key]}")
        elif c[key] > b[key]:
            msgs.append(f"improved   {key}: {b[key]} -> {c[key]}")
    limit = b["mean_total_tokens"] * (1 + tol_tokens)
    if c["mean_total_tokens"] > limit:
        ok = False
        msgs.append(
            f"REGRESSION mean_total_tokens: {b['mean_total_tokens']} -> "
            f"{c['mean_total_tokens']} (limit {limit:.1f})"
        )
    elif c["mean_total_tokens"] < b["mean_total_tokens"]:
        msgs.append(
            f"improved   mean_total_tokens: {b['mean_total_tokens']} -> {c['mean_total_tokens']}"
        )
    return ok, msgs


def main() -> int:
    ap = argparse.ArgumentParser(description="wikimem retrieval benchmark (accuracy + tokens)")
    ap.add_argument("--queries", type=Path, default=DEFAULT_QUERIES)
    ap.add_argument("--corpus", type=Path, default=None, help="override the frozen fixture corpus")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--recall-args", default="", help="extra flags passed through to memgrep recall")
    ap.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    ap.add_argument("--write-baseline", action="store_true", help="capture the current run as the baseline")
    ap.add_argument("--check", action="store_true", help="compare against the baseline; non-zero on regression")
    ap.add_argument("--tolerance", type=float, default=0.02, help="allowed fractional token rise")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    spec = json.loads(a.queries.read_text(encoding="utf-8"))
    corpus = a.corpus or (REPO / spec["corpus"])
    if not corpus.is_dir():
        print(f"corpus not found: {corpus}", file=sys.stderr)
        return 2

    res = score(spec["queries"], corpus, a.recall_args.split(), a.top)
    res["corpus"] = str(corpus.relative_to(REPO)) if corpus.is_relative_to(REPO) else str(corpus)
    res["recall_args"] = a.recall_args

    print(json.dumps(res, indent=2) if a.json else render(res))

    if a.write_baseline:
        a.baseline.parent.mkdir(parents=True, exist_ok=True)
        a.baseline.write_text(json.dumps(res, indent=2) + "\n", encoding="utf-8")
        print(f"baseline written: {a.baseline}")
        return 0

    if a.check:
        if not a.baseline.is_file():
            print(f"no baseline at {a.baseline} — run --write-baseline first", file=sys.stderr)
            return 2
        ok, msgs = compare(res, json.loads(a.baseline.read_text(encoding="utf-8")), a.tolerance)
        for m in msgs:
            print(f"  {m}")
        print("  no change" if not msgs else "")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
