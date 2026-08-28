#!/usr/bin/env python3
"""Extract the JSONL corpus from llm-externalizer report files.

Defensive by design: the reports are written by free-pool models, so the payload may be
fenced, prefixed with prose, or partially truncated. Anything that is not a well-formed
object carrying {label, content} is dropped and counted, never guessed at — a repaired
sample would be MY authorship leaking into a corpus whose whole value is that I did not
write it.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

SOURCE = {
    "mcp-annotation-lying", "mcp-schema-in-annotations", "whole-env-exfil",
    "worm-self-propagation", "crypto-clipper-triad", "procmem-credential-extraction",
    "git-protocol-only-dependency", "dns-exfil-long-subdomain", "two-step-code-injection",
}


def objects_in(text: str):
    """Yield every top-level {...} that parses as JSON, brace-matched outside strings."""
    depth, start, in_str, esc = 0, None, False, False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start is not None:
                chunk = text[start:i + 1]
                try:
                    yield json.loads(chunk)
                except json.JSONDecodeError:
                    pass
                start = None
            depth = max(depth, 0)


def records_in(text: str):
    """Every usable record in a report — PER-LINE first, then the brace walker.

    WHY BOTH, measured 2026-08-21 on the `two-step-code-injection` report. The walker
    (`objects_in`) scans the whole file tracking string/escape state, so ONE malformed
    sample desynchronises it and silently swallows every LATER sample in that file. On
    c20 the walker returned exactly ONE object — the 44-char output TEMPLATE echoed back
    inside the prompt — while 7 of the 9 real samples (286-863 chars) were perfectly valid
    JSON on their own lines. Two bad samples cost all seven good ones.

    That failure is invisible in aggregate: corpus-wide the walker finds MORE records than
    per-line parsing (301 vs 278, because it also catches objects that span lines), so
    totals look healthy while one CLASS is missing entirely. And the class it happened to
    lose was the one blocking the measurement — the bench reported
    `two-step-code-injection` under "rules with no corpus coverage" after a run whose whole
    purpose was to capture it.

    Per-line is tried first because the generator's prompt SPECIFIES JSONL — one object per
    line — so it is the format the samples are actually in, and it isolates a malformed
    sample to itself. The walker still runs afterwards to pick up genuinely multi-line
    objects; `main`'s existing `seen` set dedupes the overlap, so this is a strict superset
    of the old behaviour and can only add samples, never drop one.
    """
    for line in text.splitlines():
        line = line.strip()
        if not (line.startswith("{") and line.endswith("}")):
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            continue  # a malformed sample is dropped ALONE, not with its file's remainder
        if isinstance(rec, dict):
            yield rec
    yield from objects_in(text)


# Contiguous credential SHAPES the free-pool models like to invent when asked for a
# realistic attack sample. They are fake, but `test_secret_fixture_hygiene` (rightly)
# cannot tell a fake `sk_live_…` from a real one — it forbids the SHAPE in tracked
# source, and this corpus is tracked. Masking happens HERE, at assembly, rather than by
# hand-editing the generated file: the assembler owns the corpus, so every future
# regeneration inherits the hygiene instead of re-introducing the violation and failing
# the suite again. `****` matches the convention already used in `corpus.jsonl`.
#
# Safe for the measurement because the masked span is FILLER, never the technique: no
# rule in the catalog keys on a credential's random tail. Verified per-sample on the
# 2026-08-21 corpus — the two affected samples fired the same set (nothing) before and
# after. If a future rule ever DOES key on one of these shapes, that rule's sample must
# stop relying on a contiguous literal, not the other way round.
# The replacement tail is `9999` (digits), NOT an alphabetic word, and that is
# load-bearing: GitHub PUSH PROTECTION reads the live-key prefix followed by a masked
# ALPHABETIC tail as a Stripe API Key and rejects the whole push (measured 2026-08-22 —
# it blocked v3.4.0 on three refs at once), while the digit form is already on
# origin/main in `corpus.jsonl` and `benign.jsonl` and passed. Do not spell the rejected
# form out anywhere in tracked source, including in a comment explaining it — that is how
# this needle keeps coming back. The comment above says this mask "matches the convention already used in
# corpus.jsonl" — it did not; that file uses the DIGIT form, and appending an alphabetic
# word instead is what re-created a key-shaped literal the remote scanner still matches.
# A local hygiene gate and the remote scanner are two different graders; passing one is
# not passing the other.
_SECRET_MASKS = (
    # The PREFIX is masked too, not just the tail (2026-08-22). Keeping a literal
    # `sk_live_` and masking only what follows leaves the exact token every payment-key
    # scanner keys on, and the digit-tail form was never proven to pass: measured on
    # origin/main, `API_KEY=sk_live_` appears ZERO times in the pushed corpus — what
    # survived a push was a one-line PROSE mention, not this credential block. Nothing in
    # the bench exercises `pci_dss_patterns`/`payment_sdk_patterns`, so breaking the
    # prefix costs no measurement fidelity; it only removes a shape no grader here needs.
    # 2026-08-28: the replacement no longer keeps ANY payment-key prefix. Every earlier
    # attempt kept `sk_` and argued about the TAIL — first alphabetic (rejected), then
    # digits (believed safe because it was already on origin/main). That belief did not
    # survive contact: TRDD-X4LJFTB4 measured push protection rejecting the digit form
    # too, on `corpus-vawikrk2-20260821.jsonl:110`. Being already-pushed is not proof a
    # scanner accepts a shape — the ruleset changes, and the pattern set changes with it.
    # A prefix-free replacement cannot match a prefix-anchored pattern at all, which is
    # the only property here that does not depend on a grader's current rules.
    (re.compile(r"\bsk_(live|test)_[A-Za-z0-9*]{4,}"), r"REDACTED-PAYMENT-KEY"),
    # AWS's own PUBLISHED example credentials. They are documentation, not secrets — and
    # scanners flag them anyway, which is precisely why a captured injection payload
    # carrying them blocks a push. Masked for the same reason as the rest: the literal is
    # filler, no bench rule keys on it.
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), r"REDACTED-AWS-KEY-ID"),
    (re.compile(r"\bwJalrXUtnFEMI[A-Za-z0-9/+]*"), r"REDACTED-AWS-SECRET"),
    # Tailscale auth keys — the shape behind the repo's open secret-scanning alert #1.
    (re.compile(r"\btskey-(auth|api|client)-[A-Za-z0-9-]{6,}"), r"REDACTED-TAILSCALE-KEY"),
    (re.compile(r"(-----BEGIN\s+)(RSA|EC|OPENSSH|DSA)?(\s*PRIVATE KEY-----)"),
     r"\1\2****\3"),
    # A conn-string password that is not an obvious placeholder. The replacement is
    # `redacted` rather than `****` because the hygiene gate recognises a conn-string as
    # safe by matching its password against `_PLACEHOLDER_PW` — a mask it does not know
    # still reads as a live credential, which is how the first attempt at this failed.
    (re.compile(r"\b(postgres(?:ql)?|mysql|mongodb(?:\+srv)?)://([^:@/\s\"]+):"
                r"(?!(?:pass|password|passwd|pwd|changeme|secret|example|test|redacted"
                r"|placeholder|xxx|xxxx|none|empty)[@:])"
                r"[^@/\s\"]+@"), r"\1://\2:redacted@"),
)


def mask_secret_literals(content: str) -> str:
    """Break contiguous credential SHAPES so tracked fixtures pass secret hygiene."""
    for rx, repl in _SECRET_MASKS:
        content = rx.sub(repl, content)
    return content


def main() -> int:
    # Resolve the report list HERE rather than relying on the shell to word-split a
    # variable: this session's shell is zsh, which does not split unquoted expansions, so
    # ten paths arrived as one impossible filename.
    inputs: list[Path] = []
    for arg in sys.argv[1:-1]:
        p = Path(arg)
        if p.is_dir():
            for pointer in sorted(p.glob("*.path")):
                inputs += [Path(x) for x in pointer.read_text().split() if x.endswith(".md")]
        else:
            inputs.append(p)

    out, seen, dropped = [], set(), 0
    for path in inputs:
        if not path.exists():
            continue
        raw = Path(path).read_text(encoding="utf-8", errors="replace")
        for rec in records_in(raw):
            label, content = rec.get("label"), rec.get("content")
            if not isinstance(label, str) or not isinstance(content, str) or len(content) < 40:
                dropped += 1
                continue
            # TEMPLATE-ECHO GUARD. Some free-pool models return the output SPEC verbatim
            # instead of filling it in ("content": "<the complete sample file body...>").
            # Such a sample fires no rule, so it silently scores as a MISS and DEFLATES
            # recall — a contaminated corpus that makes the detector look worse than it is
            # is just as dishonest as one that flatters it, and far harder to notice
            # because the number moves in the alarming direction.
            # Matched on the placeholder's own words, NOT on a leading "<": an earlier
            # version of this guard used startswith("<") and silently deleted REAL
            # html-comment-impersonation payloads, which legitimately begin with "<!--".
            # A contamination filter that eats the very class it is protecting is worse
            # than the contamination.
            stripped = content.strip()
            if (
                "complete sample file body" in stripped
                or "max 12 words naming the technique" in stripped
                or len(stripped) < 80
            ):
                dropped += 1
                continue
            key = (label, content[:200])
            if key in seen:
                dropped += 1
                continue
            seen.add(key)
            out.append({
                "id": f"{label}-{sum(1 for o in out if o['label'] == label) + 1:02d}",
                "label": label,
                "kind": "source" if label in SOURCE else "prose",
                # Masked like `content`: `test_secret_fixture_hygiene` scans the tracked
                # corpus as RAW TEXT, not per field, so a credential-shaped string a free-pool
                # model happened to echo in its NOTE would fail the gate exactly as one in the
                # body would — and the masking would look done.
                "note": mask_secret_literals((rec.get("note") or "")[:90]),
                "content": mask_secret_literals(content),
            })
    dest = Path(sys.argv[-1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text("\n".join(json.dumps(o, ensure_ascii=False) for o in out) + "\n",
                    encoding="utf-8")
    labels: dict[str, int] = {}
    for o in out:
        labels[o["label"]] = labels.get(o["label"], 0) + 1
    print(f"wrote {len(out)} samples across {len(labels)} labels (dropped {dropped}) -> {dest}")
    for k in sorted(labels):
        print(f"  {labels[k]:3d}  {k}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
