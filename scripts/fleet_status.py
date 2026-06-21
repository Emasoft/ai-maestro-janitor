#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
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


def _trdd_meta(path: Path) -> dict[str, str]:
    """Parse the grep-first frontmatter head of a TRDD (column, title, trdd-id,
    severity) — reads only the first lines, never the body."""
    meta: dict[str, str] = {}
    try:
        with path.open(encoding="utf-8", errors="replace") as fh:
            for n, ln in enumerate(fh):
                if n > 40:
                    break
                for key in ("column", "title", "trdd-id", "severity", "status"):
                    if ln.startswith(key + ":"):
                        meta[key] = ln.split(":", 1)[1].strip()
    except OSError:
        pass
    return meta


def _gather_kanban(project_root: str) -> dict[str, list[dict[str, str]]]:
    """Per-project TRDD board: ``{column: [{id, title, sev}]}`` (only non-empty
    columns). v1 TRDDs that still use ``status:`` are mapped onto the column set."""
    top = Path(_git_top(project_root))
    v1map = {"not-started": "backburner", "in-progress": "dev", "completed": "complete"}
    board: dict[str, list[dict[str, str]]] = {}
    folders = {
        "design/tasks": None, "design/proposals": "proposal",
        "design/archived": "archived", "design/refused": "refused",
    }
    for rel, forced in folders.items():
        d = top / rel
        if not d.is_dir():
            continue
        for f in sorted(d.glob("TRDD-*.md")):
            m = _trdd_meta(f)
            col = forced or m.get("column") or v1map.get(m.get("status", ""), "backburner")
            board.setdefault(col, []).append({
                "id": m.get("trdd-id", "")[:8],
                "title": m.get("title", f.stem)[:90],
                "sev": m.get("severity", ""),
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
    summary = (
        f"{len(rows)} running claude instance(s) · {len(broken)} with a broken janitor · "
        f"janitor v{jver} (up-to-date: {uptodate}) · daemon: "
        f"{'alive' if daemon_alive else 'DOWN'} · marketplace last refresh: {_fmt_ts(mkt_ts)} · "
        f"global wikimem: {global_wikimem}"
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
_CI_BAD = {"failure", "cancelled", "timed_out", "startup_failure", "action_required"}


def _row_class(diag: str, active: bool) -> str:
    if diag in ("frozen", "cron_dead", "version_mismatch"):
        return "broken"
    if diag == "unarmed":
        return "unarmed"
    return "active" if active else "idle"


def _flags(r: dict) -> str:
    """At-a-glance attention emojis for one instance — what needs eyes NOW."""
    out = [_DIAG_EMOJI.get(r["diag"], "❔")]
    if r["armed"] == "no":
        out.append("⚠️unarmed")
    if r["ci"] in _CI_BAD:
        out.append("❌CI")
    if r["prrd"] == "none":
        out.append("📋∅")
    if r["ghsec"] not in ("—", "0 open"):
        out.append("🔒" + r["ghsec"])
    try:
        if int(r["uncommitted"]) > 0:
            out.append("✎" + r["uncommitted"])
    except (ValueError, TypeError):
        pass
    kb = r.get("kanban", {})
    if kb.get("blocked"):
        out.append("🔴blocked×" + str(len(kb["blocked"])))
    if kb.get("failed"):
        out.append("❌fail×" + str(len(kb["failed"])))
    return " ".join(out)


# Template with @@PLACEHOLDERS@@ (NOT an f-string) so the CSS/JS braces stay
# literal. The main table scrolls at the PAGE level (one document scrollbar — no
# inner overflow box, per the no-nested-scrollbars rule). The kanban is a modal:
# a fixed-viewport application surface, so its OWN h+v scrollbars are allowed.
_HTML_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<title>Janitor global status</title><style>
html,body{overflow-x:auto;margin:0;padding:16px;background:#0d1117;color:#c9d1d9;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
h1{font-size:18px;margin:0 0 4px} .sum{font-size:12px;color:#8b949e;margin-bottom:12px}
table{border-collapse:collapse;max-width:none}
th,td{border:1px solid #30363d;padding:3px 8px;white-space:nowrap;font-size:12px;
font-family:ui-monospace,SFMono-Regular,Menlo,monospace}
th{position:sticky;top:0;background:#161b22;text-align:left;z-index:2}
td.flags{font-size:13px}
tr.broken td{background:#3d1418} tr.broken td:first-child{border-left:3px solid #f85149}
tr.active td{background:#0d2818} tr.idle td{background:#161b22}
tr.unarmed td{background:#21262d;color:#6e7681}
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
.kbhead h2{font-size:15px;margin:0}
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
.cid{color:#6e7681;font-size:9px}
</style></head><body>
<h1>🧹 Janitor global status</h1>
<div class="sum">@@SUMMARY@@ · generated @@GEN@@</div>
<table><thead><tr>@@HEADERS@@</tr></thead><tbody>@@ROWS@@</tbody></table>
<div class="legend">@@LEGEND@@</div>
<div id="kbmodal" onclick="if(event.target.id==='kbmodal')closeKb()">
  <div class="kbwin"><div class="kbhead"><h2 id="kbtitle"></h2>
  <button class="kbx" onclick="closeKb()">✕ close</button></div>
  <div class="kbboard" id="kbboard"></div></div></div>
<script>
var KB=@@KBDATA@@, ORDER=@@ORDER@@, ALERT=@@ALERT@@;
function esc(s){var d=document.createElement('div');d.textContent=s;return d.innerHTML;}
function openKb(i){
  var d=KB[i], h='';
  for(var k=0;k<ORDER.length;k++){
    var col=ORDER[k], cards=(d.cols[col]||[]);
    h+='<div class="'+(col==='blocked'?'lane blocked':'lane')+'"><div class="laneh">'
       +(ALERT[col]||'')+' '+col+' ('+cards.length+')</div>';
    for(var j=0;j<cards.length;j++){var c=cards[j];
      h+='<div class="card sev-'+(c.sev||'')+'">'+esc(c.title)
         +'<div class="cid">'+(c.id||'')+'</div></div>';}
    h+='</div>';
  }
  document.getElementById('kbtitle').textContent='📋 '+d.proj+' — TRDD kanban';
  document.getElementById('kbboard').innerHTML=h;
  document.getElementById('kbmodal').style.display='flex';
}
function closeKb(){document.getElementById('kbmodal').style.display='none';}
document.addEventListener('keydown',function(e){if(e.key==='Escape')closeKb();});
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
        + ("" if want_ci else " (omitted this run)") + ". Deferred to Group-F: "
        "per-run security outcome, plugin-validation status, last-nudge, "
        "next-job-in-queue, memgrep errors, last-push. Click a <b>📋 kanban</b> badge "
        "to open that project's TRDD board — the <b>blocked</b> lane is full red."
    )
    return chips + "<br>" + note


def _render_html(rows: list[dict], summary: str, want_ci: bool) -> str:
    body: list[str] = []
    kb_data: list[dict] = []
    for idx, r in enumerate(rows):
        kb = r.get("kanban", {})
        kb_data.append({"proj": r["proj"], "cols": kb})
        total = sum(len(v) for v in kb.values())
        cls = _row_class(r["diag"], r["active"] == "yes")
        tds: list[str] = []
        for k, _ in _COLUMNS:
            if k == "flags":
                tds.append('<td class="flags">' + _flags(r) + "</td>")
            elif k == "board":
                if total:
                    badge = "🔴" if kb.get("blocked") else ("❌" if kb.get("failed") else "")
                    tds.append(
                        '<td><button class="kbtn" onclick="openKb(' + str(idx)
                        + ')">📋 ' + str(total) + badge + "</button></td>"
                    )
                else:
                    tds.append('<td class="muted">—</td>')
            else:
                tds.append("<td>" + html.escape(str(r.get(k, "—"))) + "</td>")
        body.append('<tr class="' + cls + '">' + "".join(tds) + "</tr>")
    headers = "".join("<th>" + html.escape(lbl) + "</th>" for _, lbl in _COLUMNS)
    out = (
        _HTML_TEMPLATE
        .replace("@@SUMMARY@@", html.escape(summary))
        .replace("@@GEN@@", time.strftime("%Y-%m-%d %H:%M:%S %z"))
        .replace("@@HEADERS@@", headers)
        .replace("@@ROWS@@", "".join(body))
        .replace("@@LEGEND@@", _legend_html(want_ci))
        .replace("@@KBDATA@@", json.dumps(kb_data, ensure_ascii=False))
        .replace("@@ORDER@@", json.dumps(list(_KANBAN_ORDER)))
        .replace("@@ALERT@@", json.dumps(_KANBAN_ALERT, ensure_ascii=False))
    )
    return _write_temp(out)


def _write_temp(content: str) -> str:
    fd, path = tempfile.mkstemp(prefix="janitor-global-status-", suffix=".html")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(content)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
