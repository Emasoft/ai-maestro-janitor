#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""Watch for replies to the GitHub threads THIS project's Claude opened.

The naive version of this watches every notification whose `reason` says you are
involved. Measured against a real account that emits the human owner's own
open-source traffic (pytorch, openinterpreter, ...) alongside the agent's work --
indistinguishable by reason alone. So the filter is a REGISTRY intersection: a
thread is watched because this project opened or commented on it, not because
GitHub thinks you are interested.

One `gh api notifications` call per tick regardless of registry size: GitHub
already computes "someone replied to a thread you are in", and re-polling each
thread would be O(registry) calls for the same answer.

Single-shot by design -- the caller loops, so the sleep/back-off policy lives at
the call site and one tick is testable by hand.

stdout is the event stream: every line printed becomes a user-facing
notification, so nothing routine may go there. Diagnostics go to stderr.

Ported into the janitor from the standalone `github-issues-monitor-on` skill.
Distinct from the `github-issues-watch` detector, which reports NEW issues on
THIS project's own repo: that one asks "did anyone file something?", this one
asks "did anyone answer me?", and they share no state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))

import gh_notify_inbox  # noqa: E402  # the fleet-wide inbox SSOT (TRDD-079778RM)
import state  # noqa: E402  # SSOT for the subprocess-timeout scale (TRDD-7NSRD8OV)

STATE_VERSION = 3
SEEN_TTL_DAYS = 30
# Overlap the `since` window so a thread updated in the same second as the last
# poll is not lost between ticks. Dedupe by (id, updated_at) makes it free.
OVERLAP_SECONDS = 90

# The janitor's persistent DATA dir name (CLAUDE.md: the ONLY dir guaranteed to
# survive plugin/marketplace/version changes and to be purged cleanly on uninstall).
JANITOR_DATA_DIR_NAME = "ai-maestro-janitor-ai-maestro-plugins"

# Reasons that can mean "somebody replied to a thread you are in". Used only to
# label the event -- the registry, not the reason, decides what is emitted.
INVOLVED_REASONS = {
    "assign", "author", "comment", "manual", "mention",
    "review_requested", "state_change", "subscribed", "team_mention",
}


def project_slug(root: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(root))


def _legacy_standalone_dir(slug: str) -> Path:
    """Where the standalone skill kept this project's registry before the port."""
    return Path.home() / ".claude" / "state" / "github-issues-monitor" / slug


def _legacy_data_dir(slug: str) -> Path:
    """Where the port kept it: per-project, but inside the machine-global DATA dir."""
    return Path.home() / ".claude" / "plugins" / "data" / JANITOR_DATA_DIR_NAME / "gh-issues-monitor" / slug


def state_dir() -> str:
    """This project's registry + poll cursor, stored INSIDE the project.

    OWNER DIRECTIVE (2026-08-02): "the github detector script should run in each
    session/claude-code/project independently, and store the tracking data locally."
    Slug-keyed subdirs of a machine-global dir gave per-project SEPARATION but not
    per-project LOCALITY: the data lived somewhere else, was keyed by absolute path
    (so moving or renaming a checkout silently orphaned its registry), and one store
    held every project's record of work.

    `.janitor/gh-issues-monitor/`, NOT `.janitor/state/`: `registry.json` is a RECORD
    OF WORK — the threads this project opened — and `.janitor/state/` is documented
    (CLAUDE.md, janitor-footprint rule) as regeneratable and safe to delete. Sitting
    one level up keeps it local as directed while staying out of the zone advertised
    as disposable, because nothing can regenerate it: the registry is filled by the
    PostToolUse hook watching `gh` commands as they happen, so a lost registry cannot
    be rebuilt, only re-accumulated from future posts.

    MIGRATES from both older locations, newest first. Copy, never move: a rollback
    must still find its registry, and losing the record of which threads a project
    opened cannot be undone by re-running anything.
    """
    override = os.environ.get("GH_ISSUES_MONITOR_STATE_DIR")
    if override:
        return override
    root = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    target = Path(root) / ".janitor" / "gh-issues-monitor"
    if not target.exists():
        slug = project_slug(root)
        for legacy in (_legacy_data_dir(slug), _legacy_standalone_dir(slug)):
            if legacy.is_dir():
                try:
                    shutil.copytree(legacy, target)
                except OSError:
                    pass  # a failed migration degrades to a fresh registry, never crashes a poll
                break
    return str(target)


def _path(name: str) -> str:
    return os.path.join(state_dir(), name)


def _read_json(name: str, default):
    try:
        with open(_path(name), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def _write_json(name: str, payload) -> None:
    os.makedirs(state_dir(), exist_ok=True)
    tmp = _path(name) + f".tmp.{os.getpid()}"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=1)
    os.replace(tmp, _path(name))


def load_state() -> dict:
    st = _read_json("state.json", None)
    if not isinstance(st, dict) or st.get("version") != STATE_VERSION:
        # A shape change invalidates the seen-map; re-baseline rather than
        # replay a backlog against a map we can no longer interpret.
        return {"version": STATE_VERSION, "since": None, "seen": {}, "error": None}
    st.setdefault("seen", {})
    st.setdefault("since", None)
    st.setdefault("error", None)
    return st


def load_registry() -> dict:
    reg = _read_json("registry.json", None)
    return reg if isinstance(reg, dict) else {}


# --- thread identity -------------------------------------------------------

_API_THREAD = re.compile(r"/repos/([^/]+)/([^/]+)/(issues|pulls|discussions)/(\d+)$")
_API_COMMENT = re.compile(r"/repos/[^/]+/[^/]+/(?:issues|pulls)/comments/(\d+)$")
_URL_THREAD = re.compile(
    r"(?:https?://)?(?:www\.)?github\.com/([^/]+)/([^/]+)/(issues|pull|pulls|discussions)/(\d+)"
)
_SLUG_THREAD = re.compile(r"^([^/\s]+)/([^#\s]+)#(\d+)$")

_PAGE = {"issues": "issues", "pulls": "pull", "pull": "pull", "discussions": "discussions"}


def key(repo: str, number: int | str) -> str:
    return f"{repo.lower()}#{number}"


def parse_thread_ref(text: str) -> tuple[str, int, str] | None:
    """Accept a browser URL, an API URL, or `owner/repo#123`. -> (repo, number, kind)."""
    text = text.strip()
    m = _URL_THREAD.search(text) or _API_THREAD.search(text)
    if m:
        owner, repo, kind, num = m.groups()
        return f"{owner}/{repo}", int(num), _PAGE.get(kind, "issues")
    m = _SLUG_THREAD.match(text)
    if m:
        owner, repo, num = m.groups()
        return f"{owner}/{repo}", int(num), "issues"
    return None


def subject_ref(subject: dict) -> tuple[str, int, str] | None:
    return parse_thread_ref(subject.get("url") or "")


def html_url(subject: dict, repo_full: str) -> str:
    """Browser URL, anchored at the latest comment when the payload allows it."""
    ref = subject_ref(subject)
    if not ref:
        return f"https://github.com/{repo_full}"
    repo, num, kind = ref
    base = f"https://github.com/{repo}/{kind}/{num}"
    c = _API_COMMENT.search(subject.get("latest_comment_url") or "")
    return f"{base}#issuecomment-{c.group(1)}" if c else base


# --- github ----------------------------------------------------------------


def gh_api(path: str) -> tuple[object | None, str | None]:
    """Return (parsed_json, error_message). Never raises."""
    try:
        proc = subprocess.run(
            ["gh", "api", "-H", "Accept: application/vnd.github+json", path],
            # Scaled by the shared knob (TRDD-7NSRD8OV). 1.0 in production, so the real
            # ceiling is unchanged. Under the test suite's own load this call expired and
            # the poller reported "MONITOR DEGRADED -- gh api timed out" against a stub
            # that answers instantly — a timeout masquerading as a monitor defect.
            capture_output=True, text=True, timeout=60 * state.timeout_scale(),
        )
    except FileNotFoundError:
        return None, "gh CLI not found on PATH"
    except subprocess.TimeoutExpired:
        return None, "gh api timed out"
    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout).strip().splitlines()
        return None, (tail[-1][:200] if tail else "gh api failed")
    try:
        return json.loads(proc.stdout), None
    except ValueError:
        return None, "gh api returned non-JSON"


def fetch_comment(subject: dict) -> tuple[str, str]:
    """(author, one-line body) for the latest comment; ('','') when unavailable.

    Best-effort by contract: a failure here must never suppress the event -- the
    thread title and URL alone are still worth waking someone for.
    """
    url = subject.get("latest_comment_url") or ""
    if not url or url == subject.get("url"):
        return "", ""
    data, err = gh_api(url.split("api.github.com/", 1)[-1])
    if err or not isinstance(data, dict):
        return "", ""
    return (data.get("user") or {}).get("login") or "", " ".join((data.get("body") or "").split())


def squeeze(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


# --- modes -----------------------------------------------------------------


def do_register(refs: list[str], note: str) -> int:
    reg = load_registry()
    added, bad = [], []
    for raw in refs:
        parsed = parse_thread_ref(raw)
        if not parsed:
            bad.append(raw)
            continue
        repo, num, kind = parsed
        k = key(repo, num)
        if k in reg:
            continue
        reg[k] = {
            "repo": repo, "number": num, "kind": kind, "note": note,
            "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "url": f"https://github.com/{repo}/{kind}/{num}",
        }
        added.append(k)
    if added:
        _write_json("registry.json", reg)
    for b in bad:
        print(f"UNPARSEABLE {b}", file=sys.stderr)
    print(f"REGISTERED {len(added)} new ({len(reg)} watched): {', '.join(added) or '-'}")
    return 1 if bad and not added else 0


def do_backfill(repos: list[str]) -> int:
    """Seed the registry with threads the authenticated user authored on `repos`.

    Opt-in: on a shared gh identity this cannot distinguish agent-authored from
    human-authored, so it is offered for the project's own repos and never run
    implicitly.
    """
    if not repos:
        print("BACKFILL needs at least one --repo", file=sys.stderr)
        return 2
    refs = []
    for repo in repos:
        data, err = gh_api(f"search/issues?q=repo:{repo}+author:@me&per_page=100")
        if err or not isinstance(data, dict):
            print(f"BACKFILL {repo} failed: {err or 'unexpected payload'}", file=sys.stderr)
            continue
        for item in data.get("items", []):
            if item.get("html_url"):
                refs.append(item["html_url"])
    return do_register(refs, "backfill")


def do_list() -> int:
    reg = load_registry()
    if not reg:
        print("registry empty -- nothing is being watched for replies")
        return 0
    for k, e in sorted(reg.items()):
        print(f"{k}\t{e.get('note', '')}\t{e.get('url', '')}")
    print(f"-- {len(reg)} threads watched", file=sys.stderr)
    return 0


def do_write_inbox(args) -> int:
    """Publish the fleet-wide inbox. A thin DELEGATE — the implementation is in
    `lib/gh_notify_inbox.fetch_and_publish`.

    It lives there, not here, because the daemon (the chore's real caller) runs from a
    staged tree containing only `daemon.py`'s import closure — `lib/` and
    `oauth_rotator/`, never `gh_issues_monitor/`. Keeping the writer here and shelling out
    to it is exactly the bug that shipped in 3.3.25: the path did not exist on the daemon's
    tree, so the chore no-opped silently every 60 s.

    Errors stay SILENT on this path: it is the manual/debug entry point, and a broken token
    should not have this print on a cadence.
    """
    gh_notify_inbox.fetch_and_publish()
    return 0


def do_poll(args) -> int:
    reg = load_registry()
    st = load_state()
    now = datetime.now(timezone.utc)

    # INBOX MODE (TRDD-079778RM): take the account-scoped thread list from the fleet-wide
    # inbox instead of calling `gh`. Everything below this point — the per-project registry
    # filter, the `seen` dedupe, the emitted line — is untouched, which is the whole point:
    # only the SOURCE of the list changes, so the surfacing logic that already works is not
    # re-implemented. `since` is not applied here because the inbox is already a retention
    # window and `seen` is what actually prevents re-emission.
    if getattr(args, "from_inbox", False):
        threads: object = gh_notify_inbox.read_threads()
        err = None
    else:
        query = f"notifications?all=true&per_page={args.limit}"
        if st["since"] and not args.baseline:
            since = datetime.fromisoformat(st["since"].replace("Z", "+00:00")) - timedelta(
                seconds=OVERLAP_SECONDS
            )
            query += f"&since={since.strftime('%Y-%m-%dT%H:%M:%SZ')}"

        threads, err = gh_api(query)

    if err:
        # Silence is not success: surface the failure ONCE, then stay quiet until
        # it changes, so a broken token cannot spam a line on every tick.
        if st.get("error") != err:
            print(f"[gh] MONITOR DEGRADED -- {err}")
            st["error"] = err
            _write_json("state.json", st)
        return 0

    if st.get("error"):
        print("[gh] monitor recovered -- polling again")
        st["error"] = None

    if not isinstance(threads, list):
        threads = []

    emitted = 0
    for thread in threads:
        tid = str(thread.get("id") or "")
        updated = thread.get("updated_at") or ""
        if not tid or st["seen"].get(tid) == updated:
            continue
        st["seen"][tid] = updated
        if args.baseline:
            continue

        subject = thread.get("subject") or {}
        repo = (thread.get("repository") or {}).get("full_name") or ""
        ref = subject_ref(subject)
        if not ref or key(ref[0], ref[1]) not in reg:
            continue  # not a thread this project opened -- the whole point
        if (thread.get("reason") or "") not in INVOLVED_REASONS:
            continue

        entry = reg[key(ref[0], ref[1])]
        line = f"[gh] {repo}#{ref[1]} {squeeze(subject.get('title') or '', 70)}"
        if not args.no_body:
            author, body = fetch_comment(subject)
            if author:
                line += f" -- @{author}" + (f": {squeeze(body, 110)}" if body else "")
        if entry.get("note"):
            line += f" [{entry['note']}]"
        print(f"{line} :: {html_url(subject, repo)}")
        emitted += 1

    st["since"] = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    cutoff = (now - timedelta(days=SEEN_TTL_DAYS)).isoformat()[:19]
    st["seen"] = {k: v for k, v in st["seen"].items() if v >= cutoff}
    _write_json("state.json", st)

    if args.baseline:
        print(f"BASELINED {len(st['seen'])} threads; watching {len(reg)} registered")
    else:
        print(f"poll ok: {len(threads)} threads, {emitted} emitted", file=sys.stderr)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--register", action="append", default=[], metavar="URL|OWNER/REPO#N",
                    help="watch this thread for replies (repeatable)")
    ap.add_argument("--note", default="", help="label recorded with --register")
    ap.add_argument("--backfill", action="store_true",
                    help="seed the registry from threads @me authored on --repo")
    ap.add_argument("--repo", action="append", default=[], metavar="OWNER/REPO",
                    help="repo for --backfill (repeatable)")
    ap.add_argument("--list", action="store_true", help="print the registry and exit")
    ap.add_argument("--baseline", action="store_true",
                    help="record current state and emit nothing (run once when enabling)")
    ap.add_argument("--no-body", action="store_true",
                    help="skip the extra call that fetches the replying comment")
    ap.add_argument("--limit", type=int, default=50, help="max threads per poll (default 50)")
    ap.add_argument("--state-dir", action="store_true", help="print the state dir and exit")
    ap.add_argument("--write-inbox", action="store_true",
                    help="daemon mode: fetch notifications once and publish the fleet-wide inbox")
    ap.add_argument("--from-inbox", action="store_true",
                    help="read threads from the fleet-wide inbox instead of calling gh")
    args = ap.parse_args()

    if args.state_dir:
        print(state_dir())
        return 0
    if args.write_inbox:
        return do_write_inbox(args)
    if args.list:
        return do_list()
    if args.register:
        return do_register(args.register, args.note)
    if args.backfill:
        return do_backfill(args.repo)
    return do_poll(args)


if __name__ == "__main__":
    sys.exit(main())
