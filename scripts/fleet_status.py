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

import html
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

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


def _git(root: str) -> dict[str, str]:
    if not os.path.isdir(os.path.join(root, ".git")) and not _run(
        ["git", "-C", root, "rev-parse", "--show-toplevel"]
    ):
        return {"branch": "—", "repo": "—", "uncommitted": "—"}
    branch = _run(["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"]) or "—"
    remote = _run(["git", "-C", root, "remote", "get-url", "origin"])
    repo = "—"
    if remote:
        r = remote.removesuffix(".git")
        if "github.com" in r:
            repo = r.split("github.com")[-1].lstrip(":/")
        elif "/" in r:
            repo = "/".join(r.rstrip("/").split("/")[-2:])
    porcelain = _run(["git", "-C", root, "status", "--porcelain"])
    uncommitted = str(len([x for x in porcelain.splitlines() if x.strip()]))
    return {"branch": branch, "repo": repo, "uncommitted": uncommitted}


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
        import markdown  # noqa: PLC0415 - declared in the script's inline deps
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
    top = Path(_git_top(project_root))
    v1map = {"not-started": "backburner", "in-progress": "dev", "completed": "complete"}
    board: dict[str, list[dict]] = {}
    folders = {
        "design/tasks": None, "design/proposals": "proposal",
        "design/archived": "archived", "design/refused": "refused",
    }
    for rel, forced in folders.items():
        d = top / rel
        if not d.is_dir():
            continue
        for f in sorted(d.glob("TRDD-*.md")):
            try:
                raw = f.read_text(encoding="utf-8", errors="replace")[:_BODY_CAP]
            except OSError:
                raw = ""
            pairs, body = _split_frontmatter(raw)
            fm = dict(pairs)
            col = forced or fm.get("column") or v1map.get(fm.get("status", ""), "backburner")
            # full uuid: prefer frontmatter trdd-id; else the 8-hex from the filename.
            uuid = fm.get("trdd-id") or ""
            if not uuid:
                parts = f.stem.split("-")
                uuid = parts[2] if len(parts) > 2 else f.stem
            board.setdefault(col, []).append({
                "id": uuid,
                "title": (fm.get("title") or f.stem)[:120],
                "sev": fm.get("severity", ""),
                "fm": pairs,
                "html": _render_markdown(body),
                "text": body,
                "path": str(f),
            })
    return board


def main() -> int:
    want_ci = "--ci" in sys.argv
    text_only = "--text" in sys.argv
    home = Path.home()
    now = int(time.time())

    sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
    import fleet_scan  # noqa: E402  -- local lib module

    gstate = home / ".claude" / "janitor-global-state"
    global_mem = (
        home / ".claude" / "plugins" / "data"
        / "ai-maestro-janitor-ai-maestro-plugins" / "memory"
    )
    global_wikimem = _count_md(global_mem)
    daemon_hb = _read_epoch(str(gstate / "daemon.heartbeat.ts"))
    daemon_alive = daemon_hb is not None and (now - daemon_hb) < 600
    mkt_ts = _read_epoch(str(gstate / "marketplace-refresh.last-run.ts"))

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
    for i in fleet:
        root = i.project_root or "—"
        g = _git(root)
        t = _newest_transcript(home, root)
        armed = "yes" if os.path.isfile(os.path.join(root, ".janitor", "state", "heartbeat-armed-at.ts")) else "no"
        slug = os.path.realpath(root).replace("/", "-")
        local_mem = _count_md(home / ".claude" / "projects" / slug / "memory")
        proj_mem = _count_md(Path(_git_top(root)) / ".claude" / "project" / "memory")
        started, etime = times.get(i.pid, ("—", "—"))
        ci = "—"
        ghsec = "—"
        if want_ci and g["repo"] != "—":
            ci = _run(["gh", "run", "list", "--repo", g["repo"], "-L", "1",
                       "--json", "conclusion", "-q", ".[0].conclusion"], timeout=12) or "—"
            n = _run(["gh", "api", f"repos/{g['repo']}/code-scanning/alerts",
                      "--jq", "length"], timeout=12)
            ghsec = ("0 open" if n == "0" else f"{n} open") if n.isdigit() else "—"
        rows.append({
            "pid": str(i.pid), "proj": os.path.basename(root), "root": root,
            "model": _model_from_transcript(t), "branch": g["branch"], "repo": g["repo"],
            "armed": armed, "active": "yes" if i.active else "no",
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
    summary = (
        f"{len(rows)} running claude instance(s) · {len(broken)} with a broken janitor · "
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

    out_path = _render_html(rows, summary, want_ci)
    print(f"[janitor-global-status] {len(rows)} instances, {len(broken)} broken janitors.")
    print(f"Dashboard: {out_path}")
    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen([opener, out_path], start_new_session=True)
        print("Opened in the default browser.")
    except Exception as exc:  # noqa: BLE001
        print(f"(could not auto-open: {exc} — open the file above manually)")
    return 0


_COLUMNS = [
    ("flags", "⚑ status"), ("board", "kanban"), ("pid", "pid"), ("proj", "project"),
    ("model", "model"), ("branch", "branch"), ("repo", "github repo"),
    ("armed", "armed"), ("active", "active"), ("cron", "cron"), ("wait", "waiting for"),
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
_WRAP_COLS = {"last_job", "last_err", "wait", "repo", "model"}

# Per-column header tooltips (hover any column title to see what it means).
_COL_TIPS = {
    "flags": "At-a-glance attention flags — hover each icon. The first is the janitor diagnosis.",
    "board": "Open this project's TRDD kanban board (count = total TRDDs).",
    "pid": "OS process id of the running claude instance.",
    "proj": "Project folder (basename); the janitor maps each claude process to its .janitor project by cwd.",
    "model": "Model id from the session's newest transcript (best-effort tail-read).",
    "branch": "Current git branch of the project.",
    "repo": "GitHub repo (owner/name) from the origin remote.",
    "armed": "Is the janitor heartbeat armed here? (heartbeat-armed-at.ts present)",
    "active": "Is the session actively working? (transcript advanced in the last 5 min)",
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
    if r["armed"] == "no":
        spans.append(_flag_span("⚠️", "janitor NOT armed in this project — needs /janitor-arm"))
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


def _render_html(rows: list[dict], summary: str, want_ci: bool) -> str:
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
                tip = html.escape(_COL_TIPS.get(k, lbl) + "  —  " + val)
                disp = html.escape(val)
                if k == "cron" and val.startswith("DEAD"):
                    disp = "<b>" + disp + "</b>"  # bold-red the dead-heartbeat cells
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
    return _write_temp(out)


def _write_temp(content: str) -> str:
    fd, path = tempfile.mkstemp(prefix="janitor-global-status-", suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
