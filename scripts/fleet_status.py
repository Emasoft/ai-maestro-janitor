#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# dependencies = ["markdown>=3.5"]
# ///
"""Backing script for /janitor-show-global-status (TRDD-324223a6, Group F2).

A whole-host HTML dashboard of every running claude instance and its janitor
health — the observability half of the fleet-guardian mandate. It reuses
fleet_scan's process→cwd→.janitor→diagnosis pipeline and enriches each instance
with git, wikimem, version, security, maintenance and PRRD facts, renders one
wide HTML table (page-level horizontal scroll — NO nested scrollbars, per the
project rule), writes it to a temp file and opens it in the default browser.

Honesty over completeness (the claim-verification rule): a field that cannot be
observed from outside a session is rendered ``—`` (with a legend), never guessed.
Network/CI lookups (CI conclusion, GitHub code-scanning, latest-release) are
opt-in via ``--ci`` so the default stays fast.
"""

from __future__ import annotations

import functools
import html
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))

import hibernation  # noqa: E402  -- needs the sys.path line above
import state  # noqa: E402  -- needs the sys.path line above
import trdd_common  # noqa: E402  -- needs the sys.path line above

# Security detectors whose last-run stamp marks "the janitor last looked at this
# project's supply-chain / secrets / workflow surface" (continuous, per-heartbeat
# — there is no discrete 'scan', so we report the most-recent run datetime; the
# transient findings are surfaced to the live heartbeat, not persisted per-run).
_SECURITY_DETECTORS = (
    "supply-chain-fingerprints", "typosquat-watcher", "provenance-audit",
    "repo-trust-score", "package-manager-policy", "workflow-security",
    "historical-cache-scan", "binary-magic-scanner", "ai-context-poisoning",
    "remote-credentials", "mcp-rugpull",
)


def _run(cmd: list[str], *, timeout: int = 10, cwd: str | None = None) -> str:
    try:
        return subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd
        ).stdout.strip()
    except Exception:  # noqa: BLE001 -- a probe must never break the dashboard
        return ""


def _fmt_ts(epoch: int | None) -> str:
    if not epoch:
        return "—"
    return time.strftime("%m-%d %H:%M", time.localtime(epoch))


def _read_epoch(path: str) -> int | None:
    try:
        return int(Path(path).read_text().strip())
    except (OSError, ValueError):
        return None


def _ps_times(pids: list[int]) -> dict[int, tuple[str, str]]:
    """{pid: (started, elapsed)} via one ps call."""
    if not pids:
        return {}
    out: dict[int, tuple[str, str]] = {}
    raw = _run(["ps", "-o", "pid=,lstart=,etime=", "-p", ",".join(str(p) for p in pids)])
    for ln in raw.splitlines():
        toks = ln.split()
        if len(toks) < 7:
            continue
        try:
            pid = int(toks[0])
        except ValueError:
            continue
        out[pid] = (f"{toks[2]} {toks[3]} {toks[4]}", toks[-1])
    return out


def _tilde(path: str) -> str:
    """`path` with $HOME collapsed to `~`.

    The dashboard is a shareable artifact; an absolute home path carries the account name.
    The relative form is also what a human actually navigates by, which is why it is its own
    column rather than only a tooltip on the basename.
    """
    home = str(Path.home())
    return "~" + path[len(home):] if path.startswith(home) else path


# What a session IS doing. Deliberately contains no cell that reads as "inactive": every
# janitor deactivation route except `/janitor-disarm` was removed, so an idle-looking janitor
# is either armed-and-between-fires, deliberately disarmed, or BROKEN — and collapsing those
# into "no" hid the third (owner directive, 2026-08-05).
_RUN_STATE = {
    "healthy": "idle · heartbeat alive",
    "frozen": "FROZEN · needs recovery",
    "cron_dead": "STOPPED · cron dead",
    "version_mismatch": "idle · stale version",
    "dead": "gone",
}


def _run_state(inst: Any, *, server_up: bool, agent_state: str = "") -> str:
    """One honest phrase for what this session is doing right now.

    The ai-maestro clause is the owner's distinction and it matters for recovery: when the
    server is down its agents are STOPPED — they resume automatically when it comes back —
    which is NOT the same as HIBERNATED, a deliberate state that does not auto-resume.

    `agent_state` comes from the server's own answer (janitor#194), delivered as a file into
    this project's `.janitor/daemon_responses/`. Before it existed the janitor reported
    NEITHER state, because nothing it can observe distinguishes them — the registry reads
    `offline` for hibernated, crashed and never-woken alike. Empty string = no live answer,
    and that is NOT permission to guess: it falls through to what we can actually observe.

    `hibernated` and `never_woken` are HEALTHY. A guardian that reports a deliberate sleep as
    an outage manufactures alarms nobody can act on.
    """
    if inst.diagnosis == "unarmed":
        return "disarmed · user opt-out"
    if agent_state == "hibernated":
        return "hibernated · deliberate (no auto-resume)"
    if agent_state == "never_woken":
        return "never woken · healthy"
    if agent_state == "crashed":
        return "CRASHED · server says the session died"
    if "aimaestro_session" in (inst.terminal or {}) and not server_up:
        return "STOPPED · server down (auto-resumes)"
    if inst.active:
        return "working"
    return _RUN_STATE.get(inst.diagnosis) or str(inst.diagnosis)


@functools.lru_cache(maxsize=1)
def _gh_user() -> str:
    """The gh CLI's active username, read OFFLINE from `~/.config/gh/hosts.yml`.

    Cached for the process: it cannot change mid-render, and this is consulted once per
    project row. Empty string when it cannot be resolved — callers must treat that as
    "unknown", never as "you own nothing".
    """
    try:
        import env_detect  # noqa: PLC0415 -- lazy sibling, same pattern as fleet_scan

        hosts = Path.home() / ".config" / "gh" / "hosts.yml"
        return env_detect.parse_active_gh_user(hosts.read_text()) if hosts.is_file() else ""
    except Exception:  # noqa: BLE001 -- a probe must never break the dashboard
        return ""


def _group_by_root(fleet: list[Any]) -> list[tuple[str, list[Any]]]:
    """`(project_root, instances)` — ONE ENTRY PER JANITOR, not per process.

    Janitor state is per-PROJECT (`<root>/.janitor`), so every claude process sharing a root
    shares one heartbeat, one cron, one diagnosis. Rendering them as separate rows repeats
    every janitor column verbatim and reads as a duplicated instance (owner report,
    2026-08-05: "the ai-maestro claude instance is reported twice"). It happens whenever a
    session is restarting — the outgoing process still dying as its replacement starts — or
    when two sessions genuinely share a folder. Scan order is preserved so the caller's sort
    survives, and no instance is dropped: the caller merges their pids into the row.
    """
    grouped: dict[str, list[Any]] = {}
    for inst in fleet:
        grouped.setdefault(inst.project_root or "—", []).append(inst)
    return list(grouped.items())


def _repo_slug(url: str) -> str:
    """`owner/name` from a git remote URL (https / ssh / scp form), or `—`."""
    if not url:
        return "—"
    r = url.removesuffix(".git")
    if "github.com" in r:
        return r.split("github.com")[-1].lstrip(":/")
    if "/" in r:
        return "/".join(r.rstrip("/").split("/")[-2:])
    return "—"


def _remotes(path: str) -> dict[str, str]:
    """`{remote_name: owner/name}` for one repo, first URL per remote wins.

    ALL remotes, not just `origin`, because which remote is which cannot be assumed. On
    this host `~/ai-maestro` has `origin` → the UPSTREAM (`23blocks-OS/ai-maestro`) and
    `fork` → the owner's own repo — the exact inversion of the usual convention. A table
    that prints only `origin` therefore names a repository the owner does NOT own, right
    next to the issue-filing workflow, and PRRD G11.2 forbids writing to a repo the gh
    auth user does not own without per-case MANAGER authorization. Showing every remote is
    what makes that judgement possible at a glance.
    """
    out: dict[str, str] = {}
    for ln in (_run(["git", "-C", path, "remote", "-v"]) or "").splitlines():
        parts = ln.split()
        if len(parts) >= 2 and parts[0] not in out:
            out[parts[0]] = _repo_slug(parts[1])
    return out


# Directory names never worth descending into when hunting for nested repos.
_REPO_SCAN_SKIP = {
    "node_modules", ".venv", "venv", "target", "dist", "build", ".git",
    "__pycache__", ".tox", ".mypy_cache", ".pytest_cache", "vendor",
}


def _nested_repos(root: str, *, max_depth: int = 3, limit: int = 8) -> list[tuple[str, str]]:
    """`(path relative to root, origin slug)` for every git repo UNDER `root`.

    A project is not always one repo. `~/ai-maestro` carries `plugins/amp-messaging` and a
    vendored checkout; `~/Code/EMASOFT-ASSISTANT-MANAGER` has NO repo at its root at all —
    its only repo is one level down, so the dashboard showed `—` for branch and repo and
    the project read as "not under version control". Bounded walk (depth, skip-list, count)
    because this runs per instance on every render.
    """
    found: list[tuple[str, str]] = []
    root_abs = os.path.abspath(root)
    for dirpath, dirnames, _files in os.walk(root_abs):
        depth = dirpath[len(root_abs):].count(os.sep)
        if depth >= max_depth:
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in _REPO_SCAN_SKIP and not d.endswith("_dev")]
        # `exists`, NOT `isdir`: a SUBMODULE and a linked WORKTREE both carry `.git` as a
        # FILE holding a `gitdir:` pointer, not a directory. `isdir` silently skipped every
        # one of them — which is why `~/ai-maestro` reported "no nested repositories" while
        # holding `plugins/amp-messaging` as a submodule.
        if dirpath != root_abs and os.path.exists(os.path.join(dirpath, ".git")):
            rel = os.path.relpath(dirpath, root_abs)
            found.append((rel, _remotes(dirpath).get("origin", "—")))
            dirnames[:] = []  # do not descend INTO a repo looking for more
            if len(found) >= limit:
                return found
    return found


def _git(root: str) -> dict[str, str]:
    """Version-control facts for one project row.

    `origin` and `forked_from` are separate columns because conflating them is how an
    agent files an issue against someone else's repository (see `_remotes`). `forked_from`
    is resolved OFFLINE from a remote conventionally named `upstream`/`parent` — a
    `gh repo view --json parent` call per row would put the network on the render path.
    """
    top = _run(["git", "-C", root, "rev-parse", "--show-toplevel"])
    nested = _nested_repos(root)
    # A project whose root is not itself a repo still has version control if a subfolder
    # is one — adopt the first as primary rather than reporting the whole project as "—".
    primary = top or (os.path.join(root, nested[0][0]) if nested else "")
    if not primary:
        return {
            "branch": "—", "origin": "—", "forked_from": "—", "yours": "—",
            "uncommitted": "—", "remotes": "",
            "subrepos": "—", "subrepos_tip": "no git repository here",
        }
    remotes = _remotes(primary)
    branch = _run(["git", "-C", primary, "rev-parse", "--abbrev-ref", "HEAD"]) or "—"
    porcelain = _run(["git", "-C", primary, "status", "--porcelain"])
    uncommitted = str(len([x for x in porcelain.splitlines() if x.strip()]))
    origin = remotes.get("origin", "—")
    forked_from = next(
        (slug for name, slug in remotes.items() if name in ("upstream", "parent")), "—"
    )
    # WHICH REPO MAY THIS AGENT WRITE TO. PRRD G11.2 permits issues/comments only on repos
    # owned by the gh auth user, and `origin` does not answer that: on `~/ai-maestro`,
    # `origin` is the upstream and the owned fork sits on a remote named `fork`. Reading the
    # answer off the remote NAMES is guesswork; comparing OWNERS to the authenticated user
    # is not. Resolved offline from ~/.config/gh/hosts.yml — no network on the render path.
    me = _gh_user().lower()
    yours = next(
        (s for s in remotes.values() if me and s != "—" and s.split("/")[0].lower() == me), "—"
    )
    others = [f"{n} → {s}" for n, s in remotes.items() if n != "origin"]
    sub_label = "—" if not nested else f"+{len(nested)}"
    sub_tip = (
        "no nested repositories"
        if not nested
        else "; ".join(f"{rel} → {slug}" for rel, slug in nested)
    )
    if not top and nested:
        sub_label = f"+{len(nested)} (root not a repo)"
    return {
        "branch": branch,
        "origin": origin,
        "forked_from": forked_from,
        "yours": yours,
        "uncommitted": uncommitted,
        "remotes": "; ".join(others),
        "subrepos": sub_label,
        "subrepos_tip": sub_tip,
    }


def _count_md(d: Path) -> int:
    try:
        return sum(1 for p in d.glob("*.md") if p.name != "MEMORY.md")
    except OSError:
        return 0


def _git_top(root: str) -> str:
    return _run(["git", "-C", root, "rev-parse", "--show-toplevel"]) or root


def _newest_transcript(home: Path, root: str) -> Path | None:
    slug = os.path.realpath(root).replace("/", "-")
    d = home / ".claude" / "projects" / slug
    try:
        js = sorted(d.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        return js[0] if js else None
    except OSError:
        return None


def _model_from_transcript(t: Path | None) -> str:
    if t is None:
        return "—"
    try:
        size = t.stat().st_size
        with t.open("rb") as fh:
            fh.seek(max(0, size - 65536))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return "—"
    model = "—"
    for ln in tail.splitlines():
        idx = ln.find('"model"')
        if idx != -1:
            q = ln[idx + 7 : idx + 60].split('"')
            if len(q) >= 3:
                model = q[1]
    return model.replace("claude-", "") if model.startswith("claude-") else model


def _tail_last(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = [x.rstrip() for x in fh if x.strip()]
    except OSError:
        return "—"
    return lines[-1][-80:] if lines else "—"


def _prrd_status(root: str) -> str:
    """PRRD version from <root>/design/requirements/PRRD.md, or 'none'."""
    p = Path(_git_top(root)) / "design" / "requirements" / "PRRD.md"
    try:
        for ln in p.read_text().splitlines()[:15]:
            if ln.startswith("prrd-version:"):
                return "v" + ln.split(":", 1)[1].strip()
        return "present"
    except OSError:
        return "none"


def _last_security_scan(root: str) -> int | None:
    """Most-recent security-detector last-run stamp under .janitor/state/."""
    sdir = os.path.join(root, ".janitor", "state")
    newest: int | None = None
    for det in _SECURITY_DETECTORS:
        ep = _read_epoch(os.path.join(sdir, f"last-run-{det}.ts"))
        if ep is not None and (newest is None or ep > newest):
            newest = ep
    return newest


# ---------------------------------------------------------------------------
# Immortality F2 dashboard augments (TRDD-F3AUDLOG) — three READ-ONLY signals the
# dashboard already has the libs for but did not surface: OS-keepalive registration,
# the self-integrity manifest verdict, and a recovery-history rollup. All three are
# FAIL-OPEN — a missing lib / manifest / key / file renders a neutral string, never
# crashes the dashboard (the honesty-over-completeness rule).
# ---------------------------------------------------------------------------


def _keepalive_status() -> str:
    """OS-keepalive (launchd/systemd) registration state, fail-open.

    'registered' iff the staged installer reports the service is on disk; 'not
    registered' when it isn't; 'unknown' if the lib is unavailable or the probe
    raises (e.g. no DATA-staged installer yet)."""
    try:
        import launchd_keepalive as ka  # noqa: PLC0415 -- local lib, lazy so an import error degrades to 'unknown'
        return "registered" if ka.is_installed() else "not registered"
    except Exception:  # noqa: BLE001 -- a probe must never break the dashboard
        return "unknown"


def _integrity_verdict() -> str:
    """Self-integrity manifest verdict, fail-open.

    Verifies the janitor's own prompt-surface file hashes against
    .integrity/manifest-sha256.json. Renders 'clean' when nothing drifted,
    'DRIFT (mutated/missing/extra counts)' when it did, 'no manifest' before a
    manifest is published, and 'unknown' if the lib/verify raises. Never crashes —
    the manifest verdict is observability, not a gate."""
    try:
        import janitor_self_integrity as jsi  # noqa: PLC0415 -- local lib, lazy
        plugin_root = Path(__file__).resolve().parent.parent
        manifest_path = plugin_root / ".integrity" / "manifest-sha256.json"
        if not manifest_path.is_file():
            return "no manifest"
        mutated, missing, extra = jsi.verify_manifest(plugin_root, manifest_path)
        if not (mutated or missing or extra):
            return "clean"
        return f"DRIFT (mutated={len(mutated)} missing={len(missing)} extra={len(extra)})"
    except Exception:  # noqa: BLE001 -- never crash the dashboard on an integrity probe
        return "unknown"


def _recovery_rollup() -> str:
    """Last-N-recoveries rollup from the F3 recovery-audit.ndjson, fail-open.

    Renders e.g. 'recoveries: 12 (7 fired) latest 06-25 09:14 — fired×7, dry_run×5'
    or 'recoveries: none' when no recovery has ever been logged, or 'recoveries:
    unknown' if the lib/read raises. Read-only — the dashboard never writes the log."""
    try:
        import recovery_audit as ra  # noqa: PLC0415 -- local lib, lazy
        records = ra.load_records()
        summ = ra.summarize_recent(records)
        if summ is None:
            return "recoveries: none"
        by = summ.get("by_outcome", {}) or {}
        # Most-frequent outcomes first → a compact at-a-glance breakdown.
        breakdown = ", ".join(
            f"{k}×{v}" for k, v in sorted(by.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        latest = _fmt_ts(summ.get("latest_ts"))
        return (
            f"recoveries: {summ['total']} ({summ['fired']} fired) latest {latest}"
            + (f" — {breakdown}" if breakdown else "")
        )
    except Exception:  # noqa: BLE001 -- never crash the dashboard on the rollup read
        return "recoveries: unknown"


# The kanban columns, in lifecycle order. The first is the proposal stage, the
# middle is the TRDD v2 pipeline (the 15+ statuses), and the tail is the terminal
# / exception lanes. The source FOLDER pins the super-column (proposals→proposal,
# refused→refused, archived→archived); design/tasks/ uses each TRDD's own column.
_KANBAN_ORDER = (
    "proposal", "backburner", "todo", "design", "dispatch", "dev", "testing",
    "ai_review", "human_review", "complete", "publish", "published", "deploy",
    "live", "live_auditing", "blocked", "failed", "superseded", "cancelled",
    "refused", "archived",
)
# Columns that demand attention — used to color the lane + flag the project badge.
_KANBAN_ALERT = {"blocked": "🔴", "failed": "❌", "refused": "🚫", "superseded": "⚰️"}

# Per-lane tooltip (hover a kanban column header to see what the status means).
_KANBAN_COLTIP = {
    "proposal": "Authored, awaiting approval (design/proposals/)",
    "backburner": "Proto-TRDD parking lot",
    "todo": "Promoted by MANAGER, awaiting design",
    "design": "ARCHITECT shaping proto → full TRDD (may 1→N split)",
    "dispatch": "Designed; awaiting an assignee",
    "dev": "Assignee implementing (new code OR fixes)",
    "testing": "Tests + audits running; failures bounce to dev",
    "ai_review": "Code review by AI agents",
    "human_review": "Human eyes required",
    "complete": "Requirements met + tested; not yet shipped",
    "publish": "Actively publishing the tool / package",
    "published": "Terminal: users can install the version with this work",
    "deploy": "Actively deploying the service",
    "live": "Terminal: real traffic reaches this code",
    "live_auditing": "Post-deploy soak / live investigation",
    "blocked": "🔴 RED — blocked-by is non-empty; cannot proceed",
    "failed": "Terminal: abandoned with a post-mortem",
    "superseded": "Terminal: replaced by split/group children",
    "cancelled": "Withdrawn — the work is no longer wanted",
    "refused": "A proposal that was NEVER approved (design/refused/)",
    "archived": "Once-approved, now terminal (design/archived/)",
}


# Max bytes of a TRDD read + rendered into the dashboard (bounds the embed size;
# the rare huge TRDD is truncated — the user can open the file on disk for the rest).
_BODY_CAP = 80_000


def _render_markdown(body: str) -> str:
    """TRDD body markdown → dark-theme HTML (tables + fenced code). Falls back to an
    escaped <pre> if the markdown lib is somehow unavailable, so the dashboard never
    breaks on a rendering hiccup."""
    try:
        # `type: ignore[import-untyped]`: markdown ships no stubs, and it IS installed
        # (declared in this script's inline deps) — so mypy reports "stubs not
        # installed" rather than a missing import, which `--ignore-missing-imports`
        # does not cover. Adding types-Markdown would put a dev-only stub package in
        # the runtime dep set of a stdlib-only plugin.
        import markdown  # type: ignore[import-untyped]  # noqa: PLC0415 - declared in the script's inline deps
        return markdown.markdown(
            body, extensions=["tables", "fenced_code", "sane_lists"], output_format="html"
        )
    except Exception:  # noqa: BLE001 - any failure → safe escaped fallback
        return "<pre>" + html.escape(body) + "</pre>"


def _split_frontmatter(text: str) -> tuple[list[tuple[str, str]], str]:
    """Split a TRDD into (frontmatter key/value pairs, body). The frontmatter is the
    leading ``---``…``---`` block; nested keys (the ``metadata:`` mapping) are
    flattened with a leading '· ' so they read as sub-rows in the composite table."""
    pairs: list[tuple[str, str]] = []
    if not text.startswith("---"):
        return pairs, text
    end = text.find("\n---", 3)
    if end == -1:
        return pairs, text
    fm = text[3:end].strip("\n")
    body = text[end + 4:].lstrip("\n")
    for ln in fm.splitlines():
        stripped = ln.strip()
        if not stripped or stripped.startswith("#") or ":" not in ln:
            continue
        key, _, val = ln.partition(":")
        indent = len(key) - len(key.lstrip())
        label = ("· " if indent else "") + key.strip()
        pairs.append((label, val.strip()))
    return pairs, body


def _gather_kanban(project_root: str) -> dict[str, list[dict]]:
    """Per-project TRDD board: ``{column: [card, …]}`` (only non-empty columns).
    Each card is rich — full uuid, title, severity, frontmatter rows, rendered body
    HTML, raw body (for copy), and the file path. The source FOLDER pins the
    super-column; design/tasks/ uses each TRDD's own column (v1 ``status:`` mapped)."""
    top = _git_top(project_root)
    board: dict[str, list[dict]] = {}
    # ONE board spanning BOTH design scopes, with `scope` as a per-card badge — not a second
    # board (the 3-pillars spec is explicit: columns and transitions are identical, scope is
    # a filter). `trdd_common` resolves each lifecycle folder in PROJECT (honoring
    # TRDD_PATH) and LOCAL (`~/.claude/projects/<slug>/design/`).
    folders = {
        "tasks": None, "proposals": "proposal",
        "archived": "archived", "refused": "refused",
    }
    for folder, forced in folders.items():
        for scope, f in trdd_common.trdd_files(folder, top):
            try:
                raw = f.read_text(encoding="utf-8", errors="replace")[:_BODY_CAP]
            except OSError:
                raw = ""
            pairs, body = _split_frontmatter(raw)
            fm = dict(pairs)
            # `column:` wins; `status:` is consulted ONLY when it holds a v1 PIPELINE state
            # (3P-TRDD-09, spec 1.3.0). It used to map any `status:` value through a v1 table
            # whose `.get(…, "backburner")` default swallowed everything else — so a card
            # with `status: normative` and no column rendered on the board as `backburner`,
            # a state nobody chose. `status:` is a DISTINCT field, not a column alias.
            #
            # A genuinely MISSING column falls back to `todo`, not `backburner`: `todo` forces
            # the next agent to evaluate the task, where `backburner` quietly buries it
            # (3P-TRDD-11).
            col = forced or fm.get("column") or trdd_common.V1_PIPELINE_STATUS_TO_COLUMN.get(
                trdd_common.norm_state(fm.get("status", "")), "todo"
            )
            # full uuid: prefer frontmatter trdd-id; else the 8-hex from the filename.
            uuid = fm.get("trdd-id") or ""
            if not uuid:
                parts = f.stem.split("-")
                uuid = parts[2] if len(parts) > 2 else f.stem
            board.setdefault(col, []).append({
                "id": uuid,
                "scope": scope,
                "title": (fm.get("title") or f.stem)[:120],
                "sev": fm.get("severity", ""),
                "fm": pairs,
                "html": _render_markdown(body),
                "text": body,
                # The REAL path — a LOCAL TRDD is outside the repo, so a repo-relative
                # path would name a file that does not exist.
                "path": str(f),
            })
    return board


def _flag_value(name: str) -> str:
    """The value of `--flag <value>` (or `--flag=<value>`) in argv, else "".

    Deliberately hand-rolled to match this script's existing `"--x" in sys.argv` style
    rather than introducing argparse for one option — argparse here would also start
    rejecting the unknown flags callers already pass, which is a behaviour change nobody
    asked for. Returns "" for a flag given with no following value, so a truncated
    invocation falls back to the default path instead of consuming the next flag.
    """
    for i, arg in enumerate(sys.argv):
        if arg == name:
            nxt = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
            return "" if nxt.startswith("-") else nxt
        if arg.startswith(f"{name}="):
            return arg.split("=", 1)[1]
    return ""


def main() -> int:
    want_ci = "--ci" in sys.argv
    text_only = "--text" in sys.argv
    # janitor#197 (ai-maestro): a headless caller must be able to render the dashboard
    # WITHOUT a browser window landing on the user's desktop. Until now the only way was
    # to shim the child's PATH with a no-op `open` — that worked, but it made a private
    # arrangement out of what should be an interface, and it silently breaks the moment
    # the open call stops being a bare PATH-resolved command name.
    no_open = "--no-open" in sys.argv
    # `--out <path>` removes the other half of the shim: parsing the `Dashboard: <path>`
    # line back out of stdout to find the artifact.
    out_override = _flag_value("--out")
    home = Path.home()
    now = int(time.time())

    # M-11 (wikimem audit 2026-07-07): memory roots come from the memory_scopes
    # SSOT, never a re-derived literal — the old inline path (and the old
    # realpath-based LOCAL slug below) could silently drift from the real roots.
    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    import fleet_scan  # noqa: E402  -- local lib module
    import global_state as gs  # noqa: E402  -- local lib module
    import harness_backend  # noqa: E402  -- local lib module
    import memory_scopes  # noqa: E402  -- local lib module

    global_mem = memory_scopes.resolve_user_dir()
    global_wikimem = _count_md(global_mem)
    # Through the SSOT readers, never a hand-resolved literal: this used to stat only the
    # pre-2U8AH82F legacy dir, so on any migrated or fresh host it reported the daemon DEAD
    # while it was beating happily at the current era's path (TRDD-QK7M2B0X). The dual-era
    # readers see every generation's stamp.
    hb = gs.read_heartbeat()
    daemon_hb = hb if hb > 0 else None
    daemon_alive = daemon_hb is not None and (now - daemon_hb) < 600
    mkt = gs.read_last_run("marketplace-refresh")
    mkt_ts = mkt if mkt > 0 else None

    cache_root = home / ".claude" / "plugins" / "cache" / "ai-maestro-plugins" / "ai-maestro-janitor"
    versions = sorted(
        (p.name for p in cache_root.glob("*") if p.is_dir() and p.name[:1].isdigit()),
        key=lambda v: [int(x) for x in v.split(".") if x.isdigit()],
    ) if cache_root.is_dir() else []
    jver = versions[-1] if versions else "—"
    uptodate = "—"
    if want_ci:
        gh_latest = _run(
            ["gh", "release", "view", "--repo", "Emasoft/ai-maestro-janitor",
             "--json", "tagName", "-q", ".tagName"], timeout=12)
        if gh_latest:
            uptodate = "yes" if gh_latest.lstrip("v") == jver else f"NO (latest {gh_latest})"

    fleet = fleet_scan.gather_fleet(now=now)
    # Whether the ai-maestro server is up decides how an AGENT session reads: with the
    # server down its agents are stopped-and-auto-resumable, not merely idle (see _run_state).
    server_up = harness_backend.server_is_alive()
    fleet.sort(key=lambda i: (i.diagnosis in ("healthy", "unarmed"),
                              not i.active, i.project_root or ""))
    times = _ps_times([i.pid for i in fleet])

    waiting_for = {
        "frozen": "rate-limit / server throttle", "cron_dead": "nothing (cron dead)",
        "version_mismatch": "reload", "healthy": "—", "unarmed": "— (disarmed)", "dead": "—",
    }
    cron_state = {
        "healthy": "alive", "frozen": "DEAD (frozen)", "cron_dead": "DEAD",
        "version_mismatch": "stale", "unarmed": "off (disarmed)", "dead": "—",
    }

    rows = []
    fleet_counts = ""  # filled from the first live hibernation answer any project carries
    for root, group in _group_by_root(fleet):
        # The representative is the one carrying live work — a mid-turn process describes the
        # project's real state better than a sibling that is idle or on its way out.
        i = next((x for x in group if x.active), group[0])
        g = _git(root)
        # THIS project's own hibernation answer only (janitor#194). Never another project's
        # file and never the install tree's roster on this project's behalf: the server draws
        # that boundary deliberately — an agent workdir gets its own record plus fleet counts,
        # so compromising one agent does not yield every agent's id and tmux session name.
        hib = hibernation.read(root)
        hib_state = hib.state() if hib else ""
        if hib and hib.counts and not fleet_counts:
            fleet_counts = hib.counts_label()  # fleet-wide, and identical in every answer
        t = _newest_transcript(home, root)
        armed = "yes" if os.path.isfile(os.path.join(root, ".janitor", "state", "heartbeat-armed-at.ts")) else "no"
        # M-11: the SSOT slug (dash EVERY non-alphanumeric, never realpath) —
        # the old realpath+"/"→"-" translation resolved a NONEXISTENT dir for
        # any dotted/underscored/symlinked project path (count silently 0).
        local_mem = _count_md(memory_scopes.resolve_local_dir_for(root))
        proj_mem = _count_md(Path(_git_top(root)) / ".claude" / "project" / "memory")
        started, etime = times.get(i.pid, ("—", "—"))
        ci = "—"
        ghsec = "—"
        if want_ci and g["origin"] != "—":
            ci = _run(["gh", "run", "list", "--repo", g["origin"], "-L", "1",
                       "--json", "conclusion", "-q", ".[0].conclusion"], timeout=12) or "—"
            n = _run(["gh", "api", f"repos/{g['origin']}/code-scanning/alerts",
                      "--jq", "length"], timeout=12)
            ghsec = ("0 open" if n == "0" else f"{n} open") if n.isdigit() else "—"
        pids = ", ".join(str(x.pid) for x in sorted(group, key=lambda x: x.pid))
        rows.append({
            "pid": pids, "proj": os.path.basename(root), "root": root,
            "folder": _tilde(root),
            "model": _model_from_transcript(t), "branch": g["branch"],
            "origin": g["origin"], "forked_from": g["forked_from"], "yours": g["yours"],
            "remotes": g["remotes"], "subrepos": g["subrepos"], "subrepos_tip": g["subrepos_tip"],
            "armed": armed, "active": "yes" if i.active else "no",
            "run_state": _run_state(i, server_up=server_up, agent_state=hib_state),
            "cron": "alive (busy)" if i.active else cron_state.get(i.diagnosis, "—"),
            "diag": i.diagnosis, "wait": "ending turn" if i.active else waiting_for.get(i.diagnosis, "—"),
            "started": started, "total": etime,
            "dispatch": f"{i.dispatch_age_s // 60}m" if i.dispatch_age_s is not None else "—",
            "proj_mem": str(proj_mem), "local_mem": str(local_mem),
            "uncommitted": g["uncommitted"], "ci": ci, "ghsec": ghsec,
            "locsec": _fmt_ts(_last_security_scan(root)),
            "prrd": _prrd_status(root),
            "kanban": _gather_kanban(root),
            "last_job": _tail_last(os.path.join(root, ".janitor", "logs", "dispatch.log")),
            "last_err": _tail_last(os.path.join(root, ".janitor", "logs", "stop-failure.log")),
        })

    broken = [r for r in rows if r["diag"] in ("frozen", "cron_dead", "version_mismatch")]
    # Immortality F2 augments (TRDD-F3AUDLOG): keepalive registration, self-integrity
    # verdict, and the recovery-history rollup — each fail-open (renders a neutral
    # string, never crashes the dashboard).
    keepalive = _keepalive_status()
    integrity = _integrity_verdict()
    recovery = _recovery_rollup()
    # An empty fleet is ambiguous — see _empty_fleet_reason. Never let it render as a count.
    headline = (
        f"{len(rows)} running claude instance(s) · {len(broken)} with a broken janitor"
        if rows else _empty_fleet_reason()
    )
    # Only shown when a live answer exists. Absent/stale means "no live answer" — NEVER "the
    # fleet is fine" and never "the fleet is broken" — so the clause simply is not rendered
    # rather than printing zeros that would read as an all-clear.
    agents_clause = f"agents: {fleet_counts} · " if fleet_counts else ""
    summary = (
        f"{headline} · {agents_clause}"
        f"janitor v{jver} (up-to-date: {uptodate}) · daemon: "
        f"{'alive' if daemon_alive else 'DOWN'} · OS keepalive: {keepalive} · "
        f"self-integrity: {integrity} · marketplace last refresh: {_fmt_ts(mkt_ts)} · "
        f"global wikimem: {global_wikimem} · {recovery}"
    )

    if text_only:
        print("# Janitor global status —", summary)
        for r in rows:
            print(f"  {r['pid']:>6} {r['diag']:<16} {r['proj']}")
        return 0

    out_path = _render_html(rows, summary, want_ci, out_override=out_override)
    # `headline` already carries the failed-measurement wording on the empty path — reusing it
    # keeps the one-line stdout summary from re-asserting a count the dashboard just refused to.
    print(f"[janitor-global-status] "
          f"{f'{len(rows)} instances, {len(broken)} broken janitors.' if rows else headline}")
    print(f"Dashboard: {out_path}")
    if no_open:
        return 0
    _open_in_browser(out_path)
    return 0


def _open_in_browser(out_path: str) -> None:
    """Launch the desktop browser on the rendered dashboard.

    A named seam rather than three inline lines: it is the one side effect in this script
    that escapes the process and lands on a human's screen, so it needs to be suppressible
    (`--no-open`) and assertable. Tests cannot patch `subprocess.Popen` module-wide to check
    it — the fleet scan runs `subprocess.run`, which builds a Popen internally, so a blanket
    patch breaks the scan instead of observing the open.

    Failure is a printed line, never a raise: the dashboard is already written and its path
    already printed, so a machine with no opener (headless Linux, a stripped PATH) must still
    get a successful run.
    """
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen([opener, out_path], start_new_session=True)
        print("Opened in the default browser.")
    except Exception as exc:  # noqa: BLE001
        print(f"(could not auto-open: {exc} — open the file above manually)")


def _empty_fleet_reason() -> str:
    """Why the fleet scan came back empty — "no sessions running" is only ONE answer.

    THE SELF-CHECK: this scan runs INSIDE a claude session, so a correct scan must find at
    least the session that ran it. Finding none is therefore not a fleet state, it is a
    broken measurement — `ps` unavailable, or a per-pid cwd probe (`lsof`) that is missing,
    denied, or sandboxed. Reporting that as "0 running instances" answers a question we never
    managed to ask, and reads as an all-clear (ai-maestro#111 follow-up: an earlier "0
    instances" from this dashboard was quoted as evidence the fleet was idle while twelve
    sessions were running).

    Runs only on the empty path, so the healthy case pays nothing.
    """
    import fleet_scan  # noqa: PLC0415 -- lazy, matching main()'s own local import

    ps_text = fleet_scan._run(["ps", "-eo", "pid=,tty=,command="])
    procs = fleet_scan.parse_ps_claude(ps_text)
    if not procs:
        return (
            "SCAN FAILED — `ps` reported no claude processes at all, yet this scan is running "
            "inside one. The process probe is broken; this says nothing about the fleet."
        )
    unresolved = sum(1 for pid, _tty, _cmd in procs if not fleet_scan._cwd_of(pid))
    if unresolved == len(procs):
        return (
            f"SCAN FAILED — found {len(procs)} claude process(es) but could not resolve the "
            f"working directory of ANY of them (lsof missing, denied, or sandboxed). The fleet "
            f"is unknown, not empty."
        )
    return f"no janitor-managed sessions among {len(procs)} running claude process(es)"


_COLUMNS = [
    ("flags", "⚑ status"), ("board", "kanban"), ("pid", "pid"), ("proj", "project"),
    ("folder", "folder"),
    ("model", "model"), ("branch", "branch"),
    ("origin", "origin"), ("forked_from", "forked from"), ("yours", "yours"),
    ("subrepos", "sub-repos"),
    ("armed", "armed"), ("run_state", "session"), ("cron", "cron"), ("wait", "waiting for"),
    ("dispatch", "dispatch"), ("started", "started"), ("total", "uptime"),
    ("uncommitted", "uncommit"), ("ci", "CI"), ("ghsec", "gh sec"),
    ("locsec", "loc sec scan"), ("prrd", "PRRD"), ("proj_mem", "wiki·proj"),
    ("local_mem", "wiki·local"), ("last_job", "last job"), ("last_err", "last error"),
]

_DIAG_EMOJI = {
    "healthy": "🟢", "frozen": "🧟❄️", "cron_dead": "🔁💀",
    "version_mismatch": "🔄", "unarmed": "🔇", "dead": "⚰️",
}
_DIAG_TIP = {
    "healthy": "healthy — transcript advancing (working OR heartbeat firing); never touched",
    "frozen": "FROZEN — rate-limited + transcript silent (the overnight-freeze shape) → recovery ladder",
    "cron_dead": "CRON DEAD — heartbeat not firing and no work; the in-session cron died → re-arm",
    "version_mismatch": "VERSION MISMATCH — running an older janitor than cached → reload",
    "unarmed": "unarmed — a disarmed.flag is present (user opted out) → sacrosanct, never touched",
    "dead": "dead — the process/pane is gone",
}
_CI_BAD = {"failure", "cancelled", "timed_out", "startup_failure", "action_required"}
# Columns whose values can be long (log lines, messages) — these cells WRAP onto
# multiple lines (white-space:normal + max-width) instead of forcing a wide table.
_WRAP_COLS = {"last_job", "last_err", "wait", "origin", "forked_from", "folder", "model",
              "run_state"}

# Per-column header tooltips (hover any column title to see what it means).
_COL_TIPS = {
    "flags": "At-a-glance attention flags — hover each icon. The first is the janitor diagnosis.",
    "board": "Open this project's TRDD kanban board (count = total TRDDs).",
    "pid": "OS process id(s). ONE ROW PER JANITOR: janitor state is per-PROJECT, so sessions "
    "sharing a folder share one heartbeat and are merged here — every pid is still listed.",
    "proj": "Project folder (basename); the janitor maps each claude process to its .janitor project by cwd.",
    "folder": "Project path relative to your home dir (~). Shown instead of the absolute path "
    "so the dashboard can be shared without leaking the account name.",
    "model": "Model id from the session's newest transcript (best-effort tail-read).",
    "branch": "Current git branch of the project (of the root repo, or the first nested repo "
    "when the project root is not itself a repository).",
    "origin": "The `origin` remote (owner/name) — where git pushes by default. NOT necessarily "
    "the repo you own: on some checkouts `origin` is the UPSTREAM and the fork is another "
    "remote. Hover the cell for every remote. Post issues only to a repo the gh auth user owns.",
    "forked_from": "The upstream this repo was forked from, read offline from a remote named "
    "`upstream`/`parent`. `—` means no such remote — not proof the repo is not a fork.",
    "yours": "The remote whose OWNER matches the gh CLI's authenticated user — i.e. the repo "
    "you may open issues and comments on (PRRD G11.2). Computed by comparing owners, not by "
    "trusting remote names. When this differs from `origin`, `origin` belongs to someone else: "
    "post here, not there. `—` = no remote is owned by the gh auth user (or gh is not logged in).",
    "subrepos": "Nested git repositories inside the project (sub-projects). Hover for their "
    "paths and origins. '(root not a repo)' means the project root has no .git of its own and "
    "the branch/origin columns describe the first nested repo instead.",
    "armed": "ADVISORY ONLY — presence of the last /janitor-arm stamp (heartbeat-armed-at.ts). "
    "Can be stale in EITHER direction (a live cron never re-stamps; a stamp can outlive a dead "
    "cron or a restart — janitor#77 item 2), so it is never used to compute the diagnosis. "
    "Trust the 'diag'/'cron' columns (derived from the live transcript) for current liveness.",
    "run_state": "What this session is DOING. Never says 'inactive': every janitor "
    "deactivation route except /janitor-disarm was removed, so a quiet janitor is either "
    "armed-and-between-fires, deliberately disarmed, or BROKEN — and one 'no' hid the third. "
    "'STOPPED · server down' marks an ai-maestro agent whose server is not running: those "
    "resume AUTOMATICALLY when it returns, unlike a hibernated agent, which does not.",
    "cron": "Heartbeat liveness, derived from the transcript: alive / DEAD / alive (busy).",
    "wait": "What the session is waiting on (rate-limit, dead cron, ending a turn, …).",
    "dispatch": "Age of the last dispatch.log entry — INFORMATIONAL ONLY (liveness uses the transcript).",
    "started": "When the claude process started (ps lstart).",
    "total": "Process uptime (ps etime).",
    "uncommitted": "Count of uncommitted files (git status --porcelain).",
    "ci": "Conclusion of the latest GitHub Actions run (needs --ci).",
    "ghsec": "Open GitHub code-scanning security alerts (needs --ci).",
    "locsec": "Most-recent run of the janitor's continuous local security detectors.",
    "prrd": "PRRD status: version of design/requirements/PRRD.md, or 'none'.",
    "proj_mem": "PROJECT-scope wikimem page count (git-tracked, shared: .claude/project/memory/).",
    "local_mem": "LOCAL-scope wikimem page count (machine-private: ~/.claude/projects/<slug>/memory/).",
    "last_job": "Last line written to the janitor dispatch.log (last notable heartbeat event).",
    "last_err": "Last line written to stop-failure.log (last rate-limit / turn-death capture).",
}


def _row_class(diag: str, active: bool) -> str:
    if diag in ("frozen", "cron_dead", "version_mismatch"):
        return "broken"
    if diag == "unarmed":
        return "unarmed"
    return "active" if active else "idle"


def _flag_span(emoji: str, tip: str) -> str:
    """One status icon wrapped in a tooltip span."""
    return '<span title="' + html.escape(tip) + '">' + emoji + "</span>"


def _flags(r: dict) -> str:
    """At-a-glance attention icons for one instance — each carries its own tooltip."""
    diag = str(r["diag"])
    spans = [_flag_span(_DIAG_EMOJI.get(diag) or "❔", _DIAG_TIP.get(diag) or diag)]
    # janitor#77 item 2: `heartbeat-armed-at.ts` can lie in EITHER direction — a live
    # cron never re-stamps it, and a stamp can outlive a dead cron or a restart (see
    # `fleet_scan.diagnose_root`'s docstring, which is why the diagnosis itself never
    # reads this file). Treat the stamp as ADVISORY here too: suppress the "NOT
    # armed" nudge whenever the transcript-derived `diag` already outranks it.
    #   - diag == "healthy": the transcript is provably fresh RIGHT NOW — a stronger,
    #     live signal the stamp cannot contradict. A missing stamp on a healthy
    #     session is exactly the race #77 item 3 describes (a turn that rate-limited
    #     between CronCreate and the stamp write) or a pre-stamp legacy install, and
    #     it self-heals on the next SessionStart (TRDD-EFTQB9RR item A re-arms
    #     unconditionally there) — flagging it here would be a false positive.
    #   - diag == "unarmed": `disarmed.flag` makes this project sacrosanct — the user
    #     deliberately opted out. A "needs /janitor-arm" nudge would reintroduce, on
    #     the dashboard, the exact disarm-optout bug TRDD-EFTQB9RR fixed for the
    #     SessionStart nudge (a stale/absent stamp getting read as "please re-arm").
    # Every other diagnosis (frozen/cron_dead/version_mismatch/dead) already carries
    # its own icon + tooltip recommending the same recovery, so leaving the extra
    # flag there is redundant, never wrong — no need to special-case those too.
    if r["armed"] == "no" and diag not in ("healthy", "unarmed"):
        spans.append(_flag_span("⚠️", "janitor NOT armed in this project — needs /janitor-arm"))
    # PRRD G11.2 safety flag: `origin` points at a repo the gh auth user does NOT own, while
    # another remote does. Filing an issue "on origin" here writes into someone else's
    # repository under the owner's shared identity — visible immediately and un-sendable.
    if r.get("yours", "—") != "—" and r.get("origin") != r["yours"]:
        spans.append(_flag_span(
            "🔀", "origin (" + str(r.get("origin")) + ") is NOT yours — you own "
            + str(r["yours"]) + ". Post issues/comments there (PRRD G11.2)."))
    if r["ci"] in _CI_BAD:
        spans.append(_flag_span("❌", "latest CI run failed (" + r["ci"] + ")"))
    if r["prrd"] == "none":
        spans.append(_flag_span("📋∅", "no PRRD — design/requirements/PRRD.md is missing"))
    if r["ghsec"] not in ("—", "0 open"):
        spans.append(_flag_span("🔒", "open GitHub security alerts: " + r["ghsec"]))
    try:
        if int(r["uncommitted"]) > 0:
            spans.append(_flag_span("✎" + r["uncommitted"], r["uncommitted"] + " uncommitted file(s)"))
    except (ValueError, TypeError):
        pass
    kb = r.get("kanban", {})
    if kb.get("blocked"):
        n = str(len(kb["blocked"]))
        spans.append(_flag_span("🔴" + n, n + " BLOCKED TRDD(s) — open the kanban to see them"))
    if kb.get("failed"):
        n = str(len(kb["failed"]))
        spans.append(_flag_span("❌" + n, n + " failed TRDD(s)"))
    return " ".join(spans)


# Template with @@PLACEHOLDERS@@ (NOT an f-string) so the CSS/JS braces stay
# literal. The main table scrolls at the PAGE level (one document scrollbar — no
# inner overflow box, per the no-nested-scrollbars rule). The kanban is a modal:
# a fixed-viewport application surface, so its OWN h+v scrollbars are allowed.
_HTML_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<title>Janitor global status</title><style>
html,body{overflow-x:auto;margin:0;padding:22px;background:#0d1117;color:#c9d1d9;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
h1{font-size:27px;font-weight:800;margin:0 0 8px;letter-spacing:.3px}
.sum{font-size:13px;color:#9da7b3;margin-bottom:16px;font-style:italic}
table{border-collapse:collapse;max-width:none}
/* thicker white grid + generous padding; cells top-align so wrapped rows read well */
th,td{border:1.5px solid rgba(255,255,255,.5);padding:9px 13px;white-space:nowrap;
font-size:12.5px;vertical-align:top;font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
th{position:sticky;top:0;background:#1b2230;text-align:left;z-index:2;font-weight:800;
font-size:12px;text-transform:uppercase;letter-spacing:.5px;
font-family:-apple-system,BlinkMacSystemFont,sans-serif}
td.flags{font-size:15px;white-space:normal;max-width:240px;line-height:1.7}
/* long values (log lines, messages) wrap onto multiple italic lines */
td.wrap{white-space:normal;max-width:340px;font-style:italic;color:#9da7b3;line-height:1.45}
td b{font-weight:800;color:#ff7b72}
tr.broken td{background:#3d1418} tr.broken td:first-child{border-left:4px solid #f85149}
tr.active td{background:#0d2818} tr.active td:first-child{border-left:4px solid #2ea043}
tr.idle td{background:#161b22}
tr.unarmed td{background:#21262d;color:#6e7681}
tr.unarmed td:first-child{border-left:4px solid #6e7681}
.kbtn{background:#1f6feb;color:#fff;border:0;border-radius:4px;padding:2px 8px;
cursor:pointer;font-size:11px} .kbtn:hover{background:#388bfd} .muted{color:#6e7681}
.legend{font-size:11px;color:#8b949e;margin-top:14px;line-height:1.8}
.legend b{color:#c9d1d9} code{background:#161b22;padding:1px 4px;border-radius:3px}
.lg{display:inline-block;margin-right:16px;white-space:nowrap}
#kbmodal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.72);z-index:100;
align-items:center;justify-content:center}
.kbwin{background:#0d1117;border:1px solid #30363d;border-radius:8px;width:94vw;
height:90vh;display:flex;flex-direction:column;padding:12px;box-shadow:0 8px 40px #000}
.kbhead{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.kbhead h2{font-size:19px;font-weight:800;margin:0;letter-spacing:.3px}
.kbx{background:#21262d;color:#c9d1d9;border:1px solid #30363d;border-radius:4px;
padding:3px 10px;cursor:pointer}
.kbboard{display:flex;gap:8px;overflow:auto;flex:1;align-items:flex-start}
.lane{min-width:190px;max-width:190px;background:#161b22;border:1px solid #30363d;
border-radius:6px;padding:6px;flex:0 0 auto}
.lane.blocked{background:#5a1117;border-color:#f85149}
.laneh{font-size:11px;font-weight:700;text-transform:uppercase;margin-bottom:6px;
color:#8b949e;letter-spacing:.3px} .lane.blocked .laneh{color:#ffc2c2}
.card{background:#21262d;border:1px solid #30363d;border-left:3px solid #6e7681;
border-radius:4px;padding:4px 6px;margin-bottom:4px;font-size:11px;line-height:1.35;
white-space:normal} .lane.blocked .card{background:#7a1c22;border-color:#f85149}
.card.sev-CRITICAL{border-left-color:#f85149} .card.sev-HIGH{border-left-color:#d29922}
.ctitle{font-weight:600;color:#e6edf3;margin-bottom:2px}
.cid{color:#7d8590;font-size:9px;font-family:ui-monospace,Menlo,monospace;
word-break:break-all;margin-bottom:4px}
.cbtns{display:flex;gap:3px;flex-wrap:wrap}
.cbtn{background:#30363d;color:#c9d1d9;border:1px solid #44505c;border-radius:3px;
padding:2px 5px;font-size:9px;cursor:pointer;line-height:1.2}
.cbtn:hover{background:#3d4651} .cbtn.open{background:#1f6feb;border-color:#1f6feb;color:#fff}
.cbtn.open:hover{background:#388bfd}
/* bigger, nicer modal close button + title */
.kbx.big{font-size:18px;font-weight:700;padding:7px 18px;border-radius:6px}
.kbx.big:hover{background:#30363d}
.kbhead h2{font-size:22px}
/* TRDD-file modal — fixed-viewport app surface, so its own scrollbars are allowed */
#fmodal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.78);z-index:110;
align-items:center;justify-content:center}
.fwin{background:#0d1117;border:1px solid #30363d;border-radius:8px;width:82vw;
max-width:1000px;height:90vh;display:flex;flex-direction:column;padding:16px;
box-shadow:0 8px 50px #000}
.fhead{display:flex;justify-content:space-between;align-items:flex-start;
margin-bottom:10px;gap:12px}
.fhead h2{font-size:21px;font-weight:800;margin:0;color:#e6edf3}
.fpath{font-size:10px;color:#6e7681;font-family:ui-monospace,Menlo,monospace;
margin-top:3px;word-break:break-all}
.fbody{overflow:auto;flex:1;padding:2px 6px 20px}
/* frontmatter as a composite multi-cell table with its own background */
.fmtable{border-collapse:collapse;width:100%;margin-bottom:18px;background:#11203a}
.fmtable th,.fmtable td{border:1px solid #2b405c;
padding:5px 10px;font-size:11.5px;text-align:left;font-family:ui-monospace,Menlo,monospace;
vertical-align:top}
.fmtable th{color:#79c0ff;font-weight:700;width:200px;white-space:nowrap;background:#16284a}
.fmtable td{color:#c9d1d9;word-break:break-word}
/* rendered markdown — dark theme */
.md{color:#c9d1d9;font-size:13.5px;line-height:1.6;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
.md h1,.md h2,.md h3,.md h4{color:#e6edf3;font-weight:800;margin:18px 0 8px;
border-bottom:1px solid #21262d;padding-bottom:4px}
.md h1{font-size:22px} .md h2{font-size:18px} .md h3{font-size:15px} .md h4{font-size:13px}
.md p{margin:8px 0} .md ul,.md ol{margin:8px 0;padding-left:24px} .md li{margin:3px 0}
.md a{color:#58a6ff;text-decoration:none} .md a:hover{text-decoration:underline}
.md strong{color:#e6edf3} .md blockquote{border-left:3px solid #30363d;margin:8px 0;
padding:2px 12px;color:#8b949e}
.md code{background:#161b22;color:#79c0ff;padding:1px 5px;border-radius:4px;
font-family:ui-monospace,Menlo,monospace;font-size:12px}
.md pre{background:#161b22;border:1px solid #30363d;border-radius:6px;padding:12px;
overflow:auto;margin:10px 0} .md pre code{background:none;color:#c9d1d9;padding:0}
.md table{border-collapse:collapse;margin:10px 0;width:100%}
.md th,.md td{border:1px solid #30363d;padding:6px 10px;font-size:12px;text-align:left}
.md th{background:#161b22;color:#e6edf3;font-weight:700} .md tr:nth-child(even) td{background:#11161d}
#toast{position:fixed;bottom:28px;left:50%;transform:translateX(-50%);background:#1f6feb;
color:#fff;padding:9px 20px;border-radius:6px;font-size:13px;font-weight:600;opacity:0;
transition:opacity .2s;pointer-events:none;z-index:200;box-shadow:0 4px 20px #000}
</style></head><body>
<h1>🧹 Janitor global status</h1>
<div class="sum">@@SUMMARY@@ · generated @@GEN@@</div>
<table><thead><tr>@@HEADERS@@</tr></thead><tbody>@@ROWS@@</tbody></table>
<div class="legend">@@LEGEND@@</div>
<div id="kbmodal" onclick="if(event.target.id==='kbmodal')closeKb()">
  <div class="kbwin"><div class="kbhead"><h2 id="kbtitle"></h2>
  <button class="kbx big" onclick="closeKb()">✕ close</button></div>
  <div class="kbboard" id="kbboard"></div></div></div>
<div id="fmodal" onclick="if(event.target.id==='fmodal')closeFile()">
  <div class="fwin"><div class="fhead"><div><h2 id="ftitle"></h2>
  <div class="fpath" id="fpath"></div></div>
  <button class="kbx big" onclick="closeFile()">✕ close</button></div>
  <div class="fbody" id="fbody"></div></div></div>
<div id="toast"></div>
<script>
var KB=@@KBDATA@@, ORDER=@@ORDER@@, ALERT=@@ALERT@@, COLTIP=@@COLTIP@@;
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function openKb(i){
  var d=KB[i], h=''; window._cur=[];   // flat per-render card list → button onclick uses one int index
  for(var k=0;k<ORDER.length;k++){
    var col=ORDER[k], cards=(d.cols[col]||[]);
    h+='<div class="'+(col==='blocked'?'lane blocked':'lane')+'" title="'+esc(COLTIP[col]||col)
       +'"><div class="laneh">'+(ALERT[col]||'')+' '+col+' ('+cards.length+')</div>';
    for(var j=0;j<cards.length;j++){var c=cards[j]; var n=window._cur.length; window._cur.push(c);
      var ct=(c.sev?c.sev+' · ':'')+c.title;
      h+='<div class="card sev-'+(c.sev||'')+'" title="'+esc(ct)+'">'
         +'<div class="ctitle">'+esc(c.title)+'</div>'
         +'<div class="cid">'+esc(c.id||'')+'</div>'
         +'<div class="cbtns">'
         +'<button class="cbtn" title="Copy the TRDD uuid to the clipboard" onclick="copyUuid('+n+')">⧉ id</button>'
         +'<button class="cbtn" title="Copy the full TRDD description to the clipboard" onclick="copyDesc('+n+')">⧉ desc</button>'
         +'<button class="cbtn open" title="Open the TRDD file in a reader" onclick="openFile('+n+')">🔍 file</button>'
         +'</div></div>';}
    h+='</div>';
  }
  document.getElementById('kbtitle').textContent='📋 '+d.proj+' — TRDD kanban';
  document.getElementById('kbboard').innerHTML=h;
  document.getElementById('kbmodal').style.display='flex';
}
function closeKb(){document.getElementById('kbmodal').style.display='none';}
function _cp(s,label){
  function ok(){toast('Copied '+label);} function no(){toast('Copy failed');}
  if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(s).then(ok,no);}
  else{var t=document.createElement('textarea');t.value=s;t.style.position='fixed';t.style.opacity='0';
    document.body.appendChild(t);t.select();try{document.execCommand('copy');ok();}catch(e){no();}
    document.body.removeChild(t);}
}
function copyUuid(n){var c=window._cur[n]; if(c)_cp(c.id||'','uuid');}
function copyDesc(n){var c=window._cur[n]; if(c)_cp(c.text||'','description');}
function toast(msg){var t=document.getElementById('toast');t.textContent=msg;t.style.opacity='1';
  clearTimeout(t._h);t._h=setTimeout(function(){t.style.opacity='0';},1500);}
function openFile(n){
  var c=window._cur[n]; if(!c)return;
  var fm='<table class="fmtable">';
  for(var k=0;k<(c.fm||[]).length;k++){fm+='<tr><th>'+esc(c.fm[k][0])+'</th><td>'+esc(c.fm[k][1])+'</td></tr>';}
  fm+='</table>';
  document.getElementById('ftitle').textContent='📄 '+(c.title||'TRDD');
  document.getElementById('fpath').textContent=c.path||'';
  document.getElementById('fbody').innerHTML=fm+'<div class="md">'+(c.html||'')+'</div>';
  document.getElementById('fbody').scrollTop=0;
  document.getElementById('fmodal').style.display='flex';
}
function closeFile(){document.getElementById('fmodal').style.display='none';}
document.addEventListener('keydown',function(e){if(e.key!=='Escape')return;
  if(document.getElementById('fmodal').style.display==='flex')closeFile();
  else if(document.getElementById('kbmodal').style.display==='flex')closeKb();});
</script>
</body></html>"""


def _legend_html(want_ci: bool) -> str:
    emojis = [
        ("🟢", "healthy"), ("🧟❄️", "frozen (rate-limited+stuck)"),
        ("🔁💀", "cron_dead (dead heartbeat)"), ("🔄", "version mismatch"),
        ("🔇", "unarmed/disarmed (sacrosanct)"), ("⚠️", "not armed"),
        ("❌CI", "CI failed"), ("🔒", "open GitHub security alerts"),
        ("📋∅", "no PRRD"), ("✎N", "N uncommitted"),
        ("🔴", "blocked TRDD(s)"), ("📋N", "open kanban (N TRDDs)"),
    ]
    chips = "".join(
        '<span class="lg">' + e + " " + html.escape(t) + "</span>" for e, t in emojis
    )
    note = (
        "<code>—</code> = not externally observable / not-yet-instrumented. "
        "<b>loc sec scan</b> = most-recent run of the janitor's continuous security "
        "detectors (findings surface live, not persisted per-run). <b>gh sec</b> / "
        "<b>CI</b> / <b>up-to-date</b> need <code>--ci</code>"
        + ("" if want_ci else " (omitted this run)") + ". The summary line carries the "
        "immortality signals: <b>OS keepalive</b> (launchd/systemd registration), "
        "<b>self-integrity</b> (file-hash manifest verdict — clean/DRIFT/no manifest), "
        "and <b>recoveries</b> (the fleet-guardian's audit-log rollup: total, fired, "
        "latest, per-outcome). Still deferred: per-run security outcome, "
        "plugin-validation status, next-job-in-queue, memgrep errors, last-push. "
        "Click a <b>📋 kanban</b> badge to open that project's TRDD board — the "
        "<b>blocked</b> lane is full red."
    )
    return chips + "<br>" + note


def _json_for_script(obj) -> str:
    """json.dumps SAFE to embed inside an inline <script>. A TRDD body can contain
    a literal ``</script>`` (or ``<!--``), which would terminate the script tag and
    break the page; escaping ``<``/``>`` to their \\uXXXX form prevents that while
    staying valid JSON (JS parses ``\\u003c`` back to ``<``). U+2028/U+2029 are
    escaped too — raw, they are illegal inside a JS string literal."""
    return (
        json.dumps(obj, ensure_ascii=False)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _render_html(rows: list[dict], summary: str, want_ci: bool, *, out_override: str = "") -> str:
    body: list[str] = []
    kb_data: list[dict] = []
    for idx, r in enumerate(rows):
        kb = r.get("kanban", {})
        kb_data.append({"proj": r["proj"], "cols": kb})
        total = sum(len(v) for v in kb.values())
        cls = _row_class(r["diag"], r["active"] == "yes")
        tds: list[str] = []
        for k, lbl in _COLUMNS:
            if k == "flags":
                tds.append('<td class="flags" title="Attention flags — hover each icon">' + _flags(r) + "</td>")
            elif k == "board":
                if total:
                    badge = "🔴" if kb.get("blocked") else ("❌" if kb.get("failed") else "")
                    btip = html.escape("Open the TRDD kanban for " + r["proj"] + " (" + str(total) + " tasks)")
                    tds.append(
                        '<td><button class="kbtn" title="' + btip + '" onclick="openKb(' + str(idx)
                        + ')">📋 ' + str(total) + badge + "</button></td>"
                    )
                else:
                    tds.append('<td class="muted" title="No TRDDs in design/ for this project">—</td>')
            else:
                val = str(r.get(k, "—"))
                # Per-cell detail no column tooltip can carry, because its length varies per
                # row: every remote behind the `origin` cell (the fork-vs-upstream question
                # that decides where an issue may be filed), and every nested repo behind the
                # `sub-repos` count.
                extra = ""
                if k == "origin" and r.get("remotes"):
                    extra = "  —  other remotes: " + str(r["remotes"])
                elif k == "subrepos":
                    extra = "  —  " + str(r.get("subrepos_tip", ""))
                tip = html.escape(_COL_TIPS.get(k, lbl) + "  —  " + val + extra)
                disp = html.escape(val)
                if k == "cron" and val.startswith("DEAD"):
                    disp = "<b>" + disp + "</b>"  # bold-red the dead-heartbeat cells
                if k == "run_state" and (val.startswith("STOPPED") or val.startswith("FROZEN")):
                    disp = "<b>" + disp + "</b>"
                cls_attr = ' class="wrap"' if k in _WRAP_COLS else ""
                tds.append("<td" + cls_attr + ' title="' + tip + '">' + disp + "</td>")
        body.append('<tr class="' + cls + '">' + "".join(tds) + "</tr>")
    headers = "".join(
        '<th title="' + html.escape(_COL_TIPS.get(k, lbl)) + '">' + html.escape(lbl) + "</th>"
        for k, lbl in _COLUMNS
    )
    # Substitute the small fixed placeholders first; the big data blobs (@@ROWS@@,
    # @@KBDATA@@) go LAST so a later placeholder-replace can never corrupt injected
    # TRDD content. _json_for_script keeps a TRDD body's literal "</script>" from
    # terminating the inline <script> tag (the bug that blanked the modals).
    out = (
        _HTML_TEMPLATE
        .replace("@@SUMMARY@@", html.escape(summary))
        .replace("@@GEN@@", time.strftime("%Y-%m-%d %H:%M:%S %z"))
        .replace("@@HEADERS@@", headers)
        .replace("@@LEGEND@@", _legend_html(want_ci))
        .replace("@@ORDER@@", _json_for_script(list(_KANBAN_ORDER)))
        .replace("@@ALERT@@", _json_for_script(_KANBAN_ALERT))
        .replace("@@COLTIP@@", _json_for_script(_KANBAN_COLTIP))
        .replace("@@ROWS@@", "".join(body))
        .replace("@@KBDATA@@", _json_for_script(kb_data))
    )
    return _write_report(out, out_override=out_override)


def _write_report(content: str, *, out_override: str = "") -> str:
    """Write the dashboard INSIDE the project, never into the system temp dir.

    This file is the most sensitive artifact the janitor produces: every running session's
    project path, git remotes, branch, pid, and kanban contents, for the whole host. It was
    written with `tempfile.mkstemp()` — a world-readable location whose path is redirectable
    via TMPDIR, so a hostile or merely misconfigured environment could steer the entire fleet
    status somewhere else entirely (owner directive, 2026-08-05: agent status must not be
    released to "a malicious controlled outlet or remote folder", which is exactly why the
    daemon's response channel is `<project>/.janitor/daemon_responses/` and not /tmp).

    Written 0600 to the project's own gitignored reports dir, which the reports-purge detector
    already ages out — so this stays bounded without inheriting the temp dir's exposure.
    """
    if out_override:
        # `--out <path>` (janitor#197). The caller names the destination, so the 0600
        # exclusive-create below still applies — an explicit path changes WHERE this
        # lands, never how exposed it is. Directories are created for convenience;
        # anything else (unwritable path, existing file) surfaces as the real OSError
        # rather than a silent fallback to the default location, because a caller that
        # asked for a specific path must not be told "written" about a different one.
        path = Path(out_override).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
    else:
        out_dir = Path(state.project_root()) / "reports" / "fleet-status"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"janitor-global-status-{time.strftime('%Y%m%d_%H%M%S%z')}.html"
    # Exclusive-create at 0600: never widen an existing file's mode, and never clobber a
    # report another process is mid-write on.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
