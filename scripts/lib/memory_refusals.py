"""Per-CANDIDATE refusal ledger for the memory chores (issue #131).

Three memory chores independently grew the same defect: an agent is dispatched, judges a specific
candidate, DECLINES it, and the verdict dies in a gitignored report — so the next pass re-dispatches
and re-derives the identical "no" at ~170k–260k tokens. Each was patched with a gate that guards a
different SHAPE (`split_has_work`'s size/tier precheck, `consolidate_has_work`'s corpus fingerprint,
`conflict_has_work`'s non-empty list), and a fourth chore would need a fourth gate — because what they
all lack is not a shape test but a record of the DECISION.

The key is the CANDIDATE, not the corpus. That is the whole point of this module over the existing
fingerprint gate: a fingerprint moves when ANY page in the scope changes, so one unrelated edit
re-arms every previously-refused pair at once. A refusal here expires only when the pages that were
actually judged change — which is also what makes it safe, because editing the very pages under
judgement legitimately re-opens the question.

TWO backstops keep a refusal from becoming a permanent silence:

  * the CONTENT hash — real file bytes, not stat metadata. A touch does not re-arm a chore, and an
    edit always does, no matter how the mtime lands.
  * a TTL (7 days, matching the fingerprint gate's) — the escape hatch for an agent that crashed
    after recording, and for LLM non-determinism (one run sees a merge another misses).

FAIL-OPEN everywhere: an unreadable ledger, an unreadable candidate, a missing entry and an expired
entry all mean DISPATCH. Suppression happens only on positive proof that this exact candidate, with
this exact content, was already judged — the same rule the rest of the precheck module follows, for
the same reason: a wrong dispatch costs tokens, a wrong suppression silently loses real work.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import global_state  # noqa: E402
import state  # noqa: E402

# Bounded store (repo invariant S3/S4): newest kept, oldest evicted. A scope cannot accumulate
# refusals faster than an agent can be dispatched, so this is generous by a wide margin.
REFUSALS_MAX = 200
# The re-check backstop. Deliberately the SAME 7 days `consolidate_has_work` already uses for its
# fingerprint gate — two different expiries for the same class of doubt would be a coin flip.
DEFAULT_TTL_S = 7 * 86400


def _ledger_path(intervention: str, scope: str, root: Path | str) -> Path:
    """Sibling of the last-run stamp, keyed identically (see memory_settings._stamp_path).

    Machine-wide, so two sessions share one verdict per (intervention, scope, root) — a refusal one
    session records must be visible to the next, or the ledger only ever suppresses its own author.
    """
    h = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:12]
    return global_state.global_state_dir() / f"memory-maint-{intervention}-{scope}-{h}.refusals.json"


def candidate_key(root: Path | str, paths: list[Path | str]) -> str:
    """The stable identity of a candidate: its root-relative paths, sorted, `|`-joined.

    Sorted because a pair `(a, b)` and `(b, a)` are the SAME candidate — a chore that surfaced them
    in the other order next time would otherwise walk straight past the refusal. Root-relative so a
    moved corpus keeps its verdicts.
    """
    rels: list[str] = []
    for p in paths:
        p = Path(p)
        try:
            rels.append(p.relative_to(root).as_posix())
        except ValueError:
            rels.append(p.as_posix())
    return "|".join(sorted(rels))


def content_hash(root: Path | str, paths: list[Path | str]) -> str | None:
    """sha256 over the candidates' actual BYTES, or None if any is unreadable.

    Content, not `stat`: the fingerprint gate hashes size+mtime because it must stay free over a
    whole corpus, but a refusal covers two or three named files, so it can afford the truth. A `touch`
    then must not re-arm the chore, and an edit must always re-arm it even if the mtime is preserved.

    None means "cannot prove it is unchanged" and every caller treats that as fail-open.
    """
    h = hashlib.sha256()
    for rel in sorted(candidate_key(root, paths).split("|")):
        try:
            h.update(rel.encode("utf-8"))
            h.update(b"\0")
            h.update((Path(root) / rel).read_bytes())
            h.update(b"\0")
        except OSError:
            return None
    return h.hexdigest()[:16]


def read(intervention: str, scope: str, root: Path | str) -> dict[str, dict]:
    """The ledger for one (intervention, scope, root), or `{}` on absent/corrupt."""
    try:
        data = json.loads(_ledger_path(intervention, scope, root).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(intervention: str, scope: str, root: Path | str, ledger: dict[str, dict]) -> None:
    items = sorted(ledger.items(), key=lambda kv: -int(kv[1].get("ts", 0)))[:REFUSALS_MAX]
    global_state.init_global_state()
    state.atomic_write(
        _ledger_path(intervention, scope, root), json.dumps(dict(items), indent=2)
    )


def record(
    intervention: str,
    scope: str,
    root: Path | str,
    paths: list[Path | str],
    *,
    reason: str,
    now: int | None = None,
) -> bool:
    """Record that this candidate was judged and DECLINED. True iff it was stored.

    Refuses to store without a readable content hash: an entry that cannot say what it was looking
    at can never be invalidated by an edit, so it would be a permanent silence rather than a refusal.
    `reason` is sanitized on ingest — a memory page's text is not trusted input, and this string is
    read back by an agent.
    """
    digest = content_hash(root, paths)
    if digest is None:
        return False
    ts = int(time.time()) if now is None else int(now)
    ledger = read(intervention, scope, root)
    ledger[candidate_key(root, paths)] = {
        "content": digest,
        "reason": state.sanitize_for_drift_line(str(reason or ""))[:300],
        "ts": ts,
    }
    _write(intervention, scope, root, ledger)
    return True


def refusal(
    intervention: str,
    scope: str,
    root: Path | str,
    paths: list[Path | str],
    *,
    now: int | None = None,
    ttl_s: int = DEFAULT_TTL_S,
) -> dict | None:
    """The live refusal covering this candidate, or None (⇒ dispatch).

    Three conditions, all required: an entry exists, the candidates' CONTENT is unchanged since it
    was recorded, and it has not aged past `ttl_s`. Anything else fails open.
    """
    entry = read(intervention, scope, root).get(candidate_key(root, paths))
    if not isinstance(entry, dict):
        return None
    digest = content_hash(root, paths)
    if digest is None or entry.get("content") != digest:
        return None  # edited (or unreadable) ⇒ the question is legitimately re-opened
    ts = int(time.time()) if now is None else int(now)
    try:
        age = ts - int(entry.get("ts", 0))
    except (TypeError, ValueError):
        return None
    return None if age >= ttl_s else entry


def is_refused(
    intervention: str,
    scope: str,
    root: Path | str,
    paths: list[Path | str],
    *,
    now: int | None = None,
    ttl_s: int = DEFAULT_TTL_S,
) -> bool:
    """True iff this exact candidate, unchanged, was already judged and declined."""
    return refusal(intervention, scope, root, paths, now=now, ttl_s=ttl_s) is not None


def clear(intervention: str, scope: str, root: Path | str, paths: list[Path | str]) -> bool:
    """Forget one refusal — the manual escape hatch. True iff an entry was removed."""
    ledger = read(intervention, scope, root)
    if ledger.pop(candidate_key(root, paths), None) is None:
        return False
    _write(intervention, scope, root, ledger)
    return True
