#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Generate `docs/ISSUE-CODES.md` from the issue catalog (TRDD-CGYMUKO6).

    issue_catalog_doc.py --write    # regenerate the doc
    issue_catalog_doc.py --check    # exit 1 if the doc has drifted from the catalog
    issue_catalog_doc.py            # print it to stdout

The doc is DERIVED, never hand-written, and `--check` runs in the test suite. A hand-maintained list
of issue codes drifts the moment someone adds one — and a stale catalog of what the janitor can detect
is worse than none, because it is a document that lies about the guardian's coverage. Same discipline
as the fenced project map in CLAUDE.md: one source of truth, a generated artifact, and a check that
fails when they diverge.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

import issue_catalog  # noqa: E402
import tickets  # noqa: E402

DOC_PATH = _HERE.parent / "docs" / "ISSUE-CODES.md"

HEADER = """# Janitor issue codes

**Generated from `scripts/lib/issue_catalog.py` — do not edit by hand.**
Regenerate with `uv run scripts/issue_catalog_doc.py --write`; a test fails if this file drifts.

Every issue the janitor's scanners and validators can detect has a stable code, `<SCANNER>-<NNN>`.
A code is **immutable once shipped** (like a schema version): never renumbered, never reused — so a
citation in a closed ticket, a report, or a TRDD still resolves years later.

A code decides **who may fix it**, and that is the load-bearing property of this table:

| Domain | What it is | What the janitor does |
|---|---|---|
| **HARNESS** | the janitor's OWN machinery — its index, its migrations, its daemon, its state | opens a ticket and **dispatches a repair agent automatically**. It is fixing itself; nobody else owns that machinery and the blast radius is its own regeneratable state. |
| **PROJECT** | the USER's code, repo, workflows, rulesets | **proposes only.** It authors a proposal TRDD under `design/proposals/` and recommends the exact command. Running `/janitor-support-open-ticket TRDD-<id>` **is** the approval — until then nothing is dispatched and nothing is touched. |

The domain comes from the code, not from the finding's text, so a detector cannot grant itself
unattended access to your repository.
"""

FOOTER = """
## How a finding becomes work

A detector raises a code — that is the entire producer-side API:

```python
raise_issue("WFSEC-001", where="ci.yml:42", evidence=[".github/workflows/ci.yml"])
```

`raise_issue` looks the code up, renders **our** template with the detector's **sanitized** data, and
routes by domain: a HARNESS code opens a ticket the scheduler will dispatch; a PROJECT code writes a
proposal TRDD and hands back the approval command.

Ticket text is treated as **untrusted data**, never instructions: values interpolated from filenames,
dependency names, workflow lines, and issue titles are defanged on ingest (a payload cannot mimic a
`[janitor-…]` marker), and the dispatched agent's instructions come from the janitor's own skills —
never from the ticket.

## Inspecting the queue

```
/janitor-support-tickets              # the queue, with severity, attempts, and budget
/janitor-support-open-ticket TRDD-…   # approve a proposed PROJECT fix
```
"""


def render() -> str:
    by_domain: dict[str, list[tuple[str, issue_catalog.Issue]]] = {tickets.HARNESS: [], tickets.PROJECT: []}
    for code, issue in sorted(issue_catalog.ISSUE_CATALOG.items()):
        by_domain[issue_catalog.issue_domain(code)].append((code, issue))

    out = [HEADER]
    for domain, heading in ((tickets.HARNESS, "HARNESS — the janitor repairs itself (automatic)"), (tickets.PROJECT, "PROJECT — your repo (proposed, never automatic)")):
        rows = by_domain[domain]
        out.append(f"\n## {heading}\n")
        out.append(f"{len(rows)} code(s).\n")
        out.append("| Code | Scanner | Severity | Issue |")
        out.append("|---|---|---|---|")
        for code, issue in rows:
            title = issue.title.replace("|", "\\|")
            out.append(f"| `{code}` | {issue.scanner} | {issue.severity} | {title} |")
        out.append("")
        for code, issue in rows:
            out.append(f"### `{code}` — {issue.title}\n")
            out.append(f"- **Scanner:** `{issue.scanner}` · **Severity:** `{issue.severity}` · **Kind:** `{issue.kind}`")
            out.append(f"- **What it is:** {issue.what}")
            out.append(f"- **Why it matters:** {issue.why}")
            out.append(f"- **Fix attempted:** {issue.fix}\n")

    out.append(FOOTER)
    return "\n".join(out).rstrip() + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(prog="issue_catalog_doc")
    ap.add_argument("--write", action="store_true", help="write docs/ISSUE-CODES.md")
    ap.add_argument("--check", action="store_true", help="exit 1 if the doc has drifted")
    args = ap.parse_args()

    doc = render()
    if args.write:
        DOC_PATH.parent.mkdir(parents=True, exist_ok=True)
        DOC_PATH.write_text(doc, encoding="utf-8")
        print(f"wrote {DOC_PATH} ({len(issue_catalog.ISSUE_CATALOG)} codes, {len(issue_catalog.scanners())} scanners)")
        return 0
    if args.check:
        try:
            live = DOC_PATH.read_text(encoding="utf-8")
        except OSError:
            print(f"MISSING: {DOC_PATH} — run `issue_catalog_doc.py --write`")
            return 1
        if live != doc:
            print(f"DRIFT: {DOC_PATH} does not match the catalog — run `issue_catalog_doc.py --write`")
            return 1
        print("ok")
        return 0
    print(doc, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
