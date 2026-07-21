#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Cross-/clear verification harness for /janitor-handoff-and-clear (TRDD-Z582IKIR P1).

The handoff+clear primitive rests on several assumptions that must be PROVEN LIVE,
not inferred:
  1. `/clear` DESTROYS the session-scoped heartbeat cron, and the post-clear
     bootstrap RE-ARMS it (a NEW cron id ⇒ both happened).
  2. `/clear` collapses the context to base-size (the whole reason to prefer it
     over `/compact`).
  3. The link-only handoff is RECOVERABLE — every `[[wikimem link]]` it carries
     resolves via memgrep in the fresh session.
  4. The `resume-after-clear.flag` is consumed and `[janitor-resume]` is emitted.
  5. SessionStart fired on `source=clear` and re-armed AFTER the clear.

This harness spans the boundary with a PERSISTENT log that survives /clear
(`.janitor/state/handoff-clear-verify.json` — a filesystem file, not session
state):

  --phase before  (run by the skill in the INVOKING session, right before /clear):
      snapshot ground truth — the stored cron id, live context size, the handoff's
      byte size + `[[link]]` count + the extracted link list, and the rotator /
      token-meter log tails. Written to the JSON.

  --phase after   (run by the resumed session, driven by the resume directive):
      re-read the cron id (≠ before ⇒ destroyed AND recreated), the context size
      (« before ⇒ collapse proven), resolve EACH persisted link via memgrep (all
      resolve ⇒ handoff recoverable), confirm the resume flag was consumed, and
      confirm a re-arm happened after the snapshot (⇒ SessionStart ran on clear).
      Emits a PASS/FAIL table to reports/continuity-build/.

FAIL-OPEN throughout: this is a DIAGNOSTIC. A fault here must NEVER break the
resume — every gather is best-effort and a missing signal degrades a check to SKIP,
never to a crash.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))

_VERIFY_FILENAME = "handoff-clear-verify.json"
_HANDOFF_FILENAME = "agent-handoff.md"
_CRON_ID_FILENAME = "heartbeat-cron-id.txt"
_ARMED_AT_FILENAME = "heartbeat-armed-at.ts"
_RESUME_FLAG_FILENAME = "resume-after-clear.flag"
_TOKEN_METER_FILENAME = "token-meter.jsonl"

# A wikilink target: the text inside [[ ]], up to a `|` alias or `#` anchor. Kept
# permissive (letters/digits/dash/underscore/slash/dot/space) so a real page slug is
# captured whole but a stray `[[` in prose can't run away to the end of the file.
_WIKILINK_RE = re.compile(r"\[\[([^\[\]|#]+?)(?:[|#][^\[\]]*)?\]\]")


# ---------- pure helpers (tested directly) --------------------------------


def extract_wikilinks(text: str) -> list[str]:
    """Every distinct `[[wikilink]]` TARGET in `text`, order-preserving, deduped.

    The target is the slug before any `|alias` or `#anchor`, stripped. Pure. This is
    the set the `after` phase must prove resolvable — a link the handoff carries but
    the corpus can't resolve is a lost fact, so the whole recoverability check hangs
    off getting this extraction right.
    """
    out: list[str] = []
    seen: set[str] = set()
    for m in _WIKILINK_RE.finditer(text):
        slug = m.group(1).strip()
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def _verdict(status: str, detail: str) -> dict:
    return {"status": status, "detail": detail}


def compute_verdicts(before: dict, after: dict, *, collapse_ratio: float = 0.5) -> dict:
    """PASS/FAIL/SKIP for each assumption, from the before+after snapshots. PURE.

    SKIP (not FAIL) whenever a signal is simply unavailable — the harness proves what
    it CAN observe and never manufactures a failure from missing data (fail-open).
    """
    v: dict[str, dict] = {}

    # 1. /clear destroyed the session cron AND the bootstrap re-armed it → a NEW id.
    b_id = (before.get("cron_id") or "").strip()
    a_id = (after.get("cron_id") or "").strip()
    if not a_id:
        v["cron_recreated"] = _verdict("SKIP", "no cron id after /clear (re-arm not observed yet)")
    elif b_id and a_id == b_id:
        v["cron_recreated"] = _verdict("FAIL", f"cron id unchanged ({a_id}) — /clear did NOT re-arm")
    else:
        v["cron_recreated"] = _verdict(
            "PASS", f"cron id changed {b_id or '∅'} → {a_id} (destroyed by /clear, recreated by re-arm)"
        )

    # 2. context collapsed to base-size.
    b_ctx = before.get("context_tokens")
    a_ctx = after.get("context_tokens")
    if not isinstance(b_ctx, int) or not isinstance(a_ctx, int) or b_ctx <= 0:
        v["context_collapsed"] = _verdict("SKIP", f"context size unknown (before={b_ctx}, after={a_ctx})")
    elif a_ctx <= b_ctx * collapse_ratio:
        v["context_collapsed"] = _verdict("PASS", f"context {b_ctx} → {a_ctx} tokens (collapsed)")
    else:
        v["context_collapsed"] = _verdict(
            "FAIL", f"context {b_ctx} → {a_ctx} tokens (did NOT collapse below {collapse_ratio:g}×)"
        )

    # 3. every handoff link resolves in the fresh session.
    resolved = after.get("links_resolved") or {}
    links = before.get("handoff_links") or []
    if not links:
        v["handoff_links_resolve"] = _verdict("SKIP", "handoff carried no [[wikilinks]] to resolve")
    else:
        checkable = {k: val for k, val in resolved.items() if val is not None}
        if not checkable:
            v["handoff_links_resolve"] = _verdict(
                "SKIP", f"{len(links)} link(s) but none checkable (memgrep unavailable)"
            )
        else:
            failed = [k for k, val in checkable.items() if not val]
            if failed:
                v["handoff_links_resolve"] = _verdict(
                    "FAIL", f"{len(failed)}/{len(checkable)} link(s) did not resolve: {', '.join(failed[:5])}"
                )
            else:
                v["handoff_links_resolve"] = _verdict(
                    "PASS", f"all {len(checkable)} checkable link(s) resolve"
                )

    # 4. the resume-after-clear flag was consumed by _phase_clear_resume.
    b_flag = bool(before.get("resume_flag_present"))
    a_flag = bool(after.get("resume_flag_present"))
    if not b_flag:
        v["resume_flag_consumed"] = _verdict("SKIP", "no resume-after-clear flag was set before /clear")
    elif a_flag:
        v["resume_flag_consumed"] = _verdict("FAIL", "resume-after-clear flag still present (not consumed)")
    else:
        v["resume_flag_consumed"] = _verdict("PASS", "resume-after-clear flag consumed (resume fired)")

    # 5. a re-arm happened AFTER the before-snapshot ⇒ SessionStart+bootstrap ran on clear.
    b_ts = before.get("ts")
    a_armed = after.get("armed_at_ts")
    if not isinstance(b_ts, int) or not isinstance(a_armed, int) or a_armed <= 0:
        v["session_restarted"] = _verdict("SKIP", "no post-clear re-arm timestamp observed")
    elif a_armed >= b_ts:
        v["session_restarted"] = _verdict(
            "PASS", f"re-armed at {a_armed} (after the {b_ts} snapshot) — SessionStart ran on source=clear"
        )
    else:
        v["session_restarted"] = _verdict(
            "FAIL", f"newest re-arm {a_armed} predates the {b_ts} snapshot (no fresh re-arm seen)"
        )
    return v


def render_report(before: dict, after: dict, verdicts: dict) -> str:
    """A PASS/FAIL table + the raw before/after snapshots, as markdown. Pure."""
    order = [
        ("cron_recreated", "cron destroyed by /clear + re-armed"),
        ("context_collapsed", "context collapsed to base size"),
        ("handoff_links_resolve", "every [[handoff link]] resolves"),
        ("resume_flag_consumed", "resume-after-clear flag consumed"),
        ("session_restarted", "SessionStart re-armed after /clear"),
    ]
    icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⚪"}
    n_pass = sum(1 for k, _ in order if verdicts.get(k, {}).get("status") == "PASS")
    n_fail = sum(1 for k, _ in order if verdicts.get(k, {}).get("status") == "FAIL")
    n_skip = sum(1 for k, _ in order if verdicts.get(k, {}).get("status") == "SKIP")
    lines = [
        "# /janitor-handoff-and-clear — cross-/clear verification (TRDD-Z582IKIR P1)",
        "",
        f"- generated: {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S%z')}",
        f"- result: {n_pass} PASS · {n_fail} FAIL · {n_skip} SKIP",
        "",
        "| # | assumption | result | detail |",
        "|---|---|---|---|",
    ]
    for i, (key, label) in enumerate(order, 1):
        ver = verdicts.get(key, {"status": "SKIP", "detail": "not evaluated"})
        st = ver["status"]
        lines.append(f"| {i} | {label} | {icon.get(st, '?')} {st} | {ver['detail']} |")
    lines += [
        "",
        "## before snapshot (invoking session, pre-/clear)",
        "```json",
        json.dumps(before, indent=2, sort_keys=True),
        "```",
        "",
        "## after snapshot (fresh session, post-/clear resume)",
        "```json",
        json.dumps(after, indent=2, sort_keys=True),
        "```",
        "",
    ]
    return "\n".join(lines)


# ---------- I/O gather (best-effort, never raises) -------------------------


def _project_root() -> Path:
    import state  # noqa: PLC0415 - local sibling lib

    return state.project_root()


def _state_dir() -> Path:
    import state  # noqa: PLC0415 - local sibling lib

    return state.state_dir()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def _read_int(path: Path) -> int:
    try:
        return int(_read_text(path).strip() or "0")
    except ValueError:
        return 0


def _tail_lines(path: Path, n: int) -> list[str]:
    """Last `n` non-empty lines of `path`, or [] — best-effort, never raises."""
    try:
        lines = [ln.rstrip("\n") for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        return lines[-n:]
    except (FileNotFoundError, OSError):
        return []


def _context_tokens() -> tuple[int | None, str]:
    """Live context size + its source. Prefers a configured agentlensPro command
    (best-effort), falls back to the newest transcript's token count — the same
    reader the cold-cache paths use, so it needs no external dependency."""
    cmd = os.environ.get(
        "CLAUDE_PLUGIN_OPTION_HANDOFF_VERIFY_CONTEXT_COMMAND", "agentlenspro get_burn_status"
    ).strip()
    if cmd:
        try:
            proc = subprocess.run(
                cmd.split(), capture_output=True, text=True, timeout=15, check=False
            )
            if proc.returncode == 0 and proc.stdout.strip():
                data = json.loads(proc.stdout)
                for key in ("context_tokens", "contextTokens", "used_tokens", "usedTokens", "tokens"):
                    val = data.get(key) if isinstance(data, dict) else None
                    if isinstance(val, int) and val > 0:
                        return val, f"agentlenspro:{key}"
        except (OSError, subprocess.SubprocessError, ValueError):
            pass
    try:
        import cold_cache_compact  # noqa: PLC0415 - local sibling lib

        tokens = cold_cache_compact.context_tokens_for(
            cold_cache_compact.newest_transcript(_project_root())
        )
        if isinstance(tokens, int):
            return tokens, "transcript"
    except Exception:  # noqa: BLE001 - best-effort
        pass
    return None, "unknown"


def _rotator_log_tail(n: int) -> list[str]:
    home = Path(os.environ.get("HOME") or os.path.expanduser("~"))
    data = os.environ.get("CLAUDE_PLUGIN_DATA", "").strip()
    candidates = [
        Path(data) / "oauth-rotator" / "rotator.log" if data else None,
        home / ".claude" / "plugins" / "data" / "ai-maestro-janitor-ai-maestro-plugins" / "oauth-rotator" / "rotator.log",
        home / ".claude" / "account-rotator" / "rotator.log",
    ]
    for c in candidates:
        if c is not None and c.is_file():
            return _tail_lines(c, n)
    return []


def _resolve_link(slug: str, roots: list[Path], memgrep: str | None) -> bool | None:
    """Does `slug` resolve to a memory note? True/False, or None when unresolvable
    to check (no memgrep AND no filesystem match to reason from). Never raises."""
    # Filesystem fallback first — cheap and dependency-free: a page file whose stem
    # matches the slug proves the target exists even with no memgrep.
    stem = slug.replace(" ", "-").lower()
    for root in roots:
        try:
            for md in root.rglob("*.md"):
                if md.stem.lower() == stem:
                    return True
        except OSError:
            continue
    if not memgrep:
        return None
    for root in roots:
        try:
            proc = subprocess.run(
                [memgrep, "find", slug, str(root)],
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return True
        except (OSError, subprocess.SubprocessError):
            continue
    return False


def _memory_roots() -> list[Path]:
    try:
        import memory_scopes  # noqa: PLC0415 - local sibling lib

        return [p for _scope, p in memory_scopes.resolve_scope_dirs()]
    except Exception:  # noqa: BLE001 - best-effort
        return []


def gather_before(now: int) -> dict:
    sd = _state_dir()
    handoff = _read_text(sd / _HANDOFF_FILENAME)
    ctx, ctx_src = _context_tokens()
    return {
        "ts": now,
        "cron_id": _read_text(sd / _CRON_ID_FILENAME).strip(),
        "context_tokens": ctx,
        "context_source": ctx_src,
        "handoff_bytes": len(handoff.encode("utf-8")),
        "handoff_link_count": len(extract_wikilinks(handoff)),
        "handoff_links": extract_wikilinks(handoff),
        "resume_flag_present": (sd / _RESUME_FLAG_FILENAME).is_file(),
        "rotator_log_tail": _rotator_log_tail(10),
        "token_meter_tail": _tail_lines(sd / _TOKEN_METER_FILENAME, 5),
    }


def gather_after(before: dict, now: int) -> dict:
    sd = _state_dir()
    ctx, ctx_src = _context_tokens()
    memgrep = None
    try:
        import user_mem_lib  # noqa: PLC0415 - local sibling lib

        memgrep = user_mem_lib.find_memgrep()
    except Exception:  # noqa: BLE001 - best-effort
        memgrep = None
    roots = _memory_roots()
    links_resolved = {slug: _resolve_link(slug, roots, memgrep) for slug in before.get("handoff_links", [])}
    return {
        "ts": now,
        "cron_id": _read_text(sd / _CRON_ID_FILENAME).strip(),
        "context_tokens": ctx,
        "context_source": ctx_src,
        "resume_flag_present": (sd / _RESUME_FLAG_FILENAME).is_file(),
        "armed_at_ts": _read_int(sd / _ARMED_AT_FILENAME),
        "memgrep": bool(memgrep),
        "links_resolved": links_resolved,
    }


def _verify_path() -> Path:
    return _state_dir() / _VERIFY_FILENAME


def _write_json(path: Path, data: dict) -> None:
    """Atomic write so a crash mid-write can't leave the `after` phase reading a
    half-written `before` block across the /clear boundary."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _report_dir() -> Path:
    """<project>/reports/continuity-build/ — anchored on CLAUDE_PROJECT_DIR (the project
    being cleared), NOT the process cwd. Deliberately no `git` call: this is a
    per-project diagnostic, project_root() is its correct home, and shelling out to git
    from an arbitrary cwd is both fragile and how a wrong-repo report gets written."""
    d = _project_root() / "reports" / "continuity-build"
    d.mkdir(parents=True, exist_ok=True)
    return d


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Prove the /janitor-and-clear primitive's assumptions across the /clear boundary."
    )
    ap.add_argument("--phase", required=True, choices=("before", "after"))
    args = ap.parse_args()

    now = int(time.time())
    try:
        if args.phase == "before":
            before = gather_before(now)
            _write_json(_verify_path(), {"before": before})
            print(
                f"VERIFY_BEFORE cron_id={before['cron_id'] or '∅'} "
                f"context={before['context_tokens']} handoff_links={before['handoff_link_count']} "
                f"-> {_verify_path()}"
            )
            return 0

        # phase == after
        try:
            saved = json.loads(_verify_path().read_text(encoding="utf-8"))
            before = saved.get("before", {}) if isinstance(saved, dict) else {}
        except (FileNotFoundError, OSError, ValueError):
            before = {}
        if not before:
            print(
                "VERIFY_NO_BEFORE no before-snapshot found — run `--phase before` in the "
                "session that fired /clear",
                file=sys.stderr,
            )
            return 0
        after = gather_after(before, now)
        verdicts = compute_verdicts(before, after)
        report = render_report(before, after, verdicts)
        _write_json(_verify_path(), {"before": before, "after": after, "verdicts": verdicts})
        report_path = _report_dir() / f"{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S%z')}-handoff-clear-verify.md"
        report_path.write_text(report, encoding="utf-8")
        n_pass = sum(1 for x in verdicts.values() if x["status"] == "PASS")
        n_fail = sum(1 for x in verdicts.values() if x["status"] == "FAIL")
        n_skip = sum(1 for x in verdicts.values() if x["status"] == "SKIP")
        print(f"VERIFY_AFTER {n_pass} PASS · {n_fail} FAIL · {n_skip} SKIP -> {report_path}")
        # Also print the compact table so the resumed session sees the result inline.
        for key, ver in verdicts.items():
            print(f"  [{ver['status']}] {key}: {ver['detail']}")
        return 0
    except Exception as exc:  # noqa: BLE001 - a diagnostic must NEVER break the resume
        print(f"VERIFY_ERROR {exc}", file=sys.stderr)
        return 0


if __name__ == "__main__":
    sys.exit(main())
