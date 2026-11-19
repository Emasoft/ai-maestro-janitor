#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Pre-commit Stage 0: redact the staged files under the root reports/ (TRDD-KSUIEPTQ).

OWNER ORDER 2026-11-14: "reports must be git tracked! ends of the story! this
is why we implemented the secret redactor in the first place, so it is always
run before committing, redacting all secrets in the new files under reports/".
reports/ is therefore tracked, and every commit that adds or changes a file
there runs it through `sanitize-reports` first, then re-stages the redacted
result, so the Stage 1 privacy scan and the commit itself see redacted content.

Fails closed, with no fallback and no skip: `sanitize-reports` missing, a
reports/ file with unstaged changes (re-staging would sweep those hunks into
the commit unreviewed), a sanitize failure or an unparseable sanitize summary
all exit 1 and block the commit. Nothing staged under reports/ is a silent
exit 0.

CLI: `uv run python scripts/lib/redact_staged_reports.py` from anywhere inside
the repo. Wired into git-hooks/pre-commit as Stage 0.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

from exe_path import exe  # noqa: E402

# `summary: changed N files, M replacements, K skipped, E errors` — the last
# line sanitize-reports prints.
_SUMMARY = re.compile(r"^summary: changed (\d+) files, (\d+) replacements", re.MULTILINE)


def _fail(message: str) -> int:
    print(f"pre-commit: {message}", file=sys.stderr)
    return 1


def _git(*args: str) -> str:
    # GIT_OPTIONAL_LOCKS=0: a read-only `git diff`/`rev-parse` otherwise takes
    # .git/index.lock for an optional stat-cache write-back and can kill a
    # concurrent git WRITE (janitor#245). Optional locks only: `git add` still
    # takes the index lock it needs, so the same env is safe for every call.
    env = dict(os.environ)
    env["GIT_OPTIONAL_LOCKS"] = "0"
    r = subprocess.run([exe("git"), *args], capture_output=True, text=True, check=True, env=env)
    return r.stdout


def _literal(names: list[str]) -> list[str]:
    # A reports/ file name is data, never a glob. Per-name :(literal) magic, not the
    # global --literal-pathspecs flag, which would also disable the :(top) magic used
    # to list the files (the first version silently found nothing because of that).
    return [f":(literal){n}" for n in names]


def _split_z(out: str) -> list[str]:
    return [p for p in out.split("\0") if p]


def main() -> int:
    try:
        toplevel = _git("rev-parse", "--show-toplevel").strip()
        files = _split_z(
            _git("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z", "--", ":(top)reports/")
        )
        if not files:
            return 0

        if shutil.which("sanitize-reports") is None:
            return _fail(
                "sanitize-reports is not on PATH; staged reports/ files cannot be redacted, "
                "so the commit is blocked. Install or link it, then retry."
            )

        unstaged = _split_z(_git("-C", toplevel, "diff", "--name-only", "-z", "--", *_literal(files)))
        if unstaged:
            return _fail(
                "reports/ file(s) have unstaged changes, redaction would stage them unreviewed: "
                + ", ".join(unstaged)
                + ". Stage or stash those changes, then retry."
            )

        # No --project-root: sanitize-reports no longer masks project-root paths, only the home prefix (TRDD-L1I0FP5T).
        r = subprocess.run(
            [exe("sanitize-reports"), *(f"{toplevel}/{f}" for f in files)],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            sys.stdout.write(r.stdout)
            sys.stderr.write(r.stderr)
            return _fail(f"sanitize-reports failed (exit {r.returncode}); commit blocked.")
        m = _SUMMARY.search(r.stdout)
        if m is None:
            sys.stdout.write(r.stdout)
            return _fail("sanitize-reports printed no recognisable summary line; commit blocked.")

        _git("-C", toplevel, "add", "--", *_literal(files))
    except subprocess.CalledProcessError as exc:
        return _fail(f"git failed ({' '.join(map(str, exc.cmd))}): {exc.stderr.strip()}")

    print(f"pre-commit: redacted {m.group(1)} staged reports/ file(s), {m.group(2)} replacements")
    return 0


if __name__ == "__main__":
    sys.exit(main())
