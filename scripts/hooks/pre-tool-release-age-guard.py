#!/usr/bin/env -S uv run --script --quiet
# /// script
# requires-python = ">=3.11"
# ///
"""PreToolUse hook — release-age observation window for package installs (TRDD-BUR8AW77).

Owner decision (card Approval log, 2026-09-27, condensed verbatim): the observation
delay for all package installers is a safety rule the janitor must NUDGE with — a hook
that recognizes package-installer commands, pre-checks whether the command installs an
EARLY release (published inside the observation window), and emits a WARNING. NEVER
blocking — there are legitimate exceptions (a library the user authors themself and
needs installed for deployment testing), and the 0-day install is the named worst case
to warn on.

The warning goes out over `hookSpecificOutput.additionalContext` and NEVER denies the
tool call. When the per-call override knob is on, an early-release finding escalates to
`permissionDecision: "ask"` — the SAME confirm-with-the-user mechanism the git-safety
hooks use (`pre-bash-safety.py`'s ALLOW_USER_OVERRIDE → "ask"); that per-call user
confirmation is the review/OTP-confirm step the owner pointed at, so it is reused
rather than reinvented.

Registries checked (JSON APIs, response shapes verified live 2026-09-27):
  pip / uv / pipx     → https://pypi.org/pypi/<pkg>/json
  npm / yarn / pnpm / bun → https://registry.npmjs.org/<pkg>
  cargo               → https://crates.io/api/v1/crates/<pkg>
  gem                 → https://rubygems.org/api/v2/rubygems/<pkg>/versions/<ver>.json
  go                  → https://proxy.golang.org/<mod>/@v/<ver>.info (or /@latest)
  brew                → recognized as an installer but NOT checkable — formula
                        versions live in a git repo, no single JSON API; silently
                        skipped (fail-open).

Local installs (`-e .`, `./mylib`, `.whl` files, `file:` npm specs, git+ URLs) are the
owner's named exception class and are skipped without a lookup — a user-authored
library never resolves in a public registry anyway.

# ponytail: lookup cap of 3 per command and 2.5 s per request — worst case ~7.5 s fits
# the hooks.json timeout of 10 s; raise the cap only if multi-package installs matter.
Fail-open everywhere: any parse or network error → silent pass-through. A hook that
errors must never break the tool call it guards.

Knobs (CLAUDE_PLUGIN_OPTION_*):
  RELEASE_AGE_GUARD_ENABLED             default ON; "false"/"0"/"no"/"off" disables
  RELEASE_AGE_OBSERVATION_MINUTES       default 7200 (5 days — matches
                                        pre-tool-pkg-guard's MIN_RELEASE_AGE default)
  RELEASE_AGE_HOOK_ALLOW_USER_OVERRIDE  default OFF; ON = escalate findings from a
                                        warning to permissionDecision "ask" (the user
                                        confirms each early install — the OTP step)
  RELEASE_AGE_REGISTRY_BASE             TEST SEAM ONLY — points ALL registry lookups
                                        at one local base URL so the unit tests serve
                                        canned JSON over real HTTP instead of mocking.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import datetime, timezone
from typing import Any

# --- knobs ------------------------------------------------------------------


def _enabled() -> bool:
    v = os.environ.get("CLAUDE_PLUGIN_OPTION_RELEASE_AGE_GUARD_ENABLED")
    if v is None:
        return True  # default ON — the owner made this a standing safety rule
    return v.strip().lower() not in ("0", "false", "no", "off")


def _window_minutes() -> int:
    v = os.environ.get("CLAUDE_PLUGIN_OPTION_RELEASE_AGE_OBSERVATION_MINUTES")
    try:
        n = int(v) if v else 7200
    except ValueError:
        n = 7200
    return max(n, 0)


def _allow_override() -> bool:
    """When true, an early-release finding escalates from warning to ask (user confirms)."""
    v = os.environ.get("CLAUDE_PLUGIN_OPTION_RELEASE_AGE_HOOK_ALLOW_USER_OVERRIDE")
    if v is None:
        return False
    return v.strip().lower() in ("1", "true", "yes", "on")


def _registry_base() -> str | None:
    """Test seam — when set, ALL lookups go to {base}/<registry>/<path>."""
    base = os.environ.get("CLAUDE_PLUGIN_OPTION_RELEASE_AGE_REGISTRY_BASE", "").strip()
    return base.rstrip("/") or None


# --- age arithmetic ---------------------------------------------------------


def _age_minutes(iso: str) -> float | None:
    """Publish age in minutes from an ISO-8601 timestamp, or None on any parse failure."""
    try:
        dt = datetime.fromisoformat(iso.strip().replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max((datetime.now(timezone.utc) - dt).total_seconds() / 60.0, 0.0)


# --- registry lookups (fail-open: return None on ANY error) -----------------

_UA = "ai-maestro-janitor-release-age-guard (+https://github.com/Emasoft/ai-maestro-janitor)"


def _get_json(url: str) -> Any | None:
    try:
        req = urllib.request.Request(
            url, headers={"User-Agent": _UA, "Accept": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=2.5) as resp:  # noqa: S310 — fixed https/test-local URLs
            return json.loads(resp.read().decode("utf-8", "replace"))
    except Exception:  # noqa: BLE001 — fail-open by design: a registry outage must never block a tool call
        return None


def _pypi_url(path: str) -> str:
    base = _registry_base()
    return f"{base}/pypi/{path}" if base else f"https://pypi.org/pypi/{path}"


def _pypi_age(pkg: str, ver: str | None) -> float | None:
    d = _get_json(_pypi_url(f"{urllib.parse.quote(pkg)}/json"))
    if not isinstance(d, dict):
        return None
    if ver is not None:
        files = (d.get("releases") or {}).get(ver) or []
        iso = files[0].get("upload_time_iso_8601") if files else None
    else:
        urls = d.get("urls") or []
        iso = urls[0].get("upload_time_iso_8601") if urls else None
    return _age_minutes(iso) if iso else None


def _npm_url(path: str) -> str:
    base = _registry_base()
    return f"{base}/npm/{path}" if base else f"https://registry.npmjs.org/{path}"


def _npm_age(pkg: str, ver: str | None) -> float | None:
    d = _get_json(_npm_url(urllib.parse.quote(pkg, safe="")))
    if not isinstance(d, dict):
        return None
    v = ver or ((d.get("dist-tags") or {}).get("latest"))
    iso = (d.get("time") or {}).get(v) if v else None
    return _age_minutes(iso) if iso else None


def _crates_url(path: str) -> str:
    base = _registry_base()
    return f"{base}/crates/{path}" if base else f"https://crates.io/api/v1/crates/{path}"


def _crates_age(pkg: str, ver: str | None) -> float | None:
    d = _get_json(_crates_url(urllib.parse.quote(pkg, safe="")))
    if not isinstance(d, dict):
        return None
    target = ver or (d.get("crate") or {}).get("max_stable_version") or (d.get("crate") or {}).get("max_version")
    if not target:
        return None
    for entry in d.get("versions") or []:
        if entry.get("num") == target:
            return _age_minutes(entry.get("created_at", ""))
    return None


def _rubygems_url(path: str) -> str:
    base = _registry_base()
    return f"{base}/rubygems/{path}" if base else f"https://rubygems.org/api/v2/rubygems/{path}"


def _rubygems_age(pkg: str, ver: str | None) -> float | None:
    if ver is not None:
        d = _get_json(_rubygems_url(f"{urllib.parse.quote(pkg)}/versions/{urllib.parse.quote(ver)}.json"))
        if isinstance(d, dict) and d.get("version_created_at"):
            return _age_minutes(d["version_created_at"])
        return None
    latest = _get_json(_rubygems_url(f"{urllib.parse.quote(pkg)}/versions/latest.json"))
    if not isinstance(latest, dict) or not latest.get("version"):
        return None
    d = _get_json(_rubygems_url(f"{urllib.parse.quote(pkg)}/versions/{urllib.parse.quote(latest['version'])}.json"))
    if isinstance(d, dict) and d.get("version_created_at"):
        return _age_minutes(d["version_created_at"])
    return None


def _go_url(path: str) -> str:
    base = _registry_base()
    return f"{base}/go/{path}" if base else f"https://proxy.golang.org/{path}"


def _go_age(mod: str, ver: str | None) -> float | None:
    spec = f"@v/{ver}.info" if ver is not None else "@latest"
    d = _get_json(_go_url(f"{mod}/{spec}"))
    if isinstance(d, dict) and d.get("Time"):
        return _age_minutes(d["Time"])
    return None


# --- command recognition + package extraction -------------------------------

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SHELL_CUT_RE = re.compile(r"&&|\|\||;|\|")


def _tail_after(norm: str, match: re.Match[str]) -> str:
    """Everything after the install subcommand, cut at the next shell operator."""
    tail = norm[match.end():]
    cut = _SHELL_CUT_RE.search(tail)
    return tail[:cut.start()] if cut else tail


def _is_local(t: str) -> bool:
    """The owner's named exception class: local/first-party installs never hit a registry."""
    low = t.lower()
    if low.startswith((".", "/", "~", "git+", "http://", "https://", "svn+", "hg+", "file:", "link:", "workspace:")):
        return True
    if low.endswith((".whl", ".tar.gz", ".zip", ".tar.bz2", ".gem")):
        return True
    return False


def _py_packages(tail: str) -> Iterator[tuple[str, str | None]]:
    for t in tail.split():
        if t.startswith("-") or _is_local(t):
            continue
        if "==" in t:
            name, _, ver = t.partition("==")
            name = re.sub(r"\[.*\]", "", name)  # strip extras: foo[extra]==1.0
            ver = ver.split(";")[0].split(",")[0]
            if _NAME_RE.match(name) and ver:
                yield name, ver
        elif "@" not in t and _NAME_RE.match(t):
            yield t, None


def _npm_packages(tail: str) -> Iterator[tuple[str, str | None]]:
    for t in tail.split():
        if t.startswith("-") or _is_local(t):
            continue
        if t.startswith("@"):  # @scope/pkg[@ver] — the leading @ is part of the name
            body, sep, scoped_ver = t[1:].rpartition("@")
            name = f"@{body}" if sep else t
            # A scoped spec's version is optional (``@scope/pkg`` alone is legal), so the
            # var must be `str | None` here — reusing the unscoped `ver` (always `str`
            # from rpartition) made mypy flag the None branch (TRDD-VIFQ1LKI gate run).
            ver: str | None = scoped_ver if sep else None
        else:
            name, sep, ver = t.rpartition("@")
            if not sep:
                name, ver = t, None
        if "npm:" in (ver or "") or "://" in (ver or ""):
            continue  # alias specs (foo@npm:bar@1.2) — unresolvable cheaply, fail-open
        bare = name[1:] if name.startswith("@") else name
        if _NAME_RE.match(bare):
            yield name, ver


def _cargo_packages(tail: str) -> Iterator[tuple[str, str | None]]:
    pin_m = re.search(r"(?:--version|-V)\s+(\S+)", tail)
    pin = pin_m.group(1) if pin_m else None
    for t in tail.split():
        if t.startswith("-") or _is_local(t):
            continue
        if "@" in t:
            name, _, ver = t.rpartition("@")
            if _NAME_RE.match(name) and ver and "://" not in ver:
                yield name, ver
        elif _NAME_RE.match(t):
            yield t, pin


def _gem_packages(tail: str) -> Iterator[tuple[str, str | None]]:
    pin_m = re.search(r"(?:--version|-v)\s+(\S+)", tail)
    pin = pin_m.group(1) if pin_m else None
    for t in tail.split():
        if t.startswith("-") or _is_local(t):
            continue
        if _NAME_RE.match(t):
            yield t, pin
            break  # gem install takes one package per invocation


def _go_packages(tail: str) -> Iterator[tuple[str, str | None]]:
    for t in tail.split():
        if t.startswith("-") or t in ("all", "std", "./...") or _is_local(t):
            continue
        # module paths legitimately contain / and . — only @ is a separator
        if "@" in t:
            mod, _, ver = t.rpartition("@")
            if mod:
                yield mod, ver
        elif "/" in t or _NAME_RE.match(t):
            yield t, None


# family = (command matcher, extractor, age lookup)
_FAMILIES: list[tuple[re.Pattern[str], Any, Any]] = [
    (
        re.compile(r"\b(?:pip3?|pipx)\s+install\b|\buv\s+(?:pip\s+)?(?:install|add|tool\s+install)\b"),
        _py_packages, _pypi_age,
    ),
    (
        re.compile(r"\b(?:npm|pnpm|bun)\s+(?:install|add|i)\b|\byarn\s+(?:add|install)\b"),
        _npm_packages, _npm_age,
    ),
    (
        re.compile(r"\bcargo\s+(?:install|add)\b"),
        _cargo_packages, _crates_age,
    ),
    (
        re.compile(r"\bgem\s+install\b"),
        _gem_packages, _rubygems_age,
    ),
    (
        re.compile(r"\bgo\s+(?:get|install)\b"),
        _go_packages, _go_age,
    ),
]

_LOOKUP_CAP = 3  # ponytail: per-command cap — see module docstring


def check_command(cmd: str, window: int) -> list[str]:
    """Return one finding line per early-release install target (empty = nothing to warn on)."""
    norm = re.sub(r"\s+", " ", cmd).strip()
    if not norm:
        return []
    candidates: list[tuple[str, str | None, Any]] = []
    for matcher, extract, lookup in _FAMILIES:
        m = matcher.search(norm)
        if not m:
            continue
        for name, ver in extract(_tail_after(norm, m)):
            candidates.append((name, ver, lookup))
    findings: list[str] = []
    for name, ver, lookup in candidates[:_LOOKUP_CAP]:
        age = lookup(name, ver)
        if age is not None and age < window:
            findings.append(
                f"{name} {ver if ver is not None else '(latest)'} was published "
                f"~{age:.0f} min ago (observation window: {window} min)"
            )
    return findings


def _warning_text(findings: list[str], cmd: str) -> str:
    return (
        f"[release-age-guard] EARLY-RELEASE WARNING for `{cmd[:200]}`: "
        + "; ".join(findings)
        + ". Freshly published releases have had no community scrutiny — 0-day "
        "compromised packages propagate exactly this way. This is a WARNING, not a "
        "block: installing a package you author yourself (or have otherwise vetted) "
        "for deployment testing is a legitimate exception — state the reason in one "
        "line and proceed. Disable: CLAUDE_PLUGIN_OPTION_RELEASE_AGE_GUARD_ENABLED=false."
    )


# --- main hook entry --------------------------------------------------------


def main() -> int:
    if not _enabled():
        return 0
    try:
        data = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # malformed input → silent pass-through
    if data.get("tool_name") != "Bash":
        return 0
    cmd = (data.get("tool_input") or {}).get("command", "") or ""

    findings = check_command(cmd, _window_minutes())
    if not findings:
        return 0  # silent allow — well-aged installs, non-installers, lookup failures

    text = _warning_text(findings, cmd)
    if _allow_override():
        # The git-safety hooks' escalation: the USER confirms each flagged call.
        out: dict[str, Any] = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason": text,
            }
        }
    else:
        out = {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "additionalContext": text,
            }
        }
    json.dump(out, sys.stdout)
    return 0


def _cli_entry() -> None:
    """CLI shim — sys.exit inside a function so an accidental import never kills the importer."""
    sys.exit(main())


if __name__ == "__main__":
    _cli_entry()
