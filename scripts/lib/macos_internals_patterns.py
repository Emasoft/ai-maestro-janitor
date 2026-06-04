"""macOS system-internals abuse primitives (Gatekeeper / LaunchAgent / TCC / XPC).

Wave-23 distillation round 9 — macOS-specific abuse primitives.

Catalogue of 7 macOS-internals anti-patterns distilled in
`reports/distill-round-9/macos-system-internals.md`. Targets surfaces NOT
covered by:

  * Round 4 process-injection (mentions LaunchDaemons but no regex shapes)
  * Round 7 archive-extraction (--no-xattrs is a defensive flag, NOT an
    attacker primitive detector)
  * Round 6 k8s-admission (matches OPA Gatekeeper, NOT macOS Gatekeeper)

What IS here (7 net-new rules, regex-only, RE2-safe):

  * macos-xattr-quarantine-clear                                (CRITICAL)
  * macos-launchagent-plist-persistence                         (CRITICAL)
  * macos-launchctl-activation-primitive                        (HIGH)
  * macos-spctl-gatekeeper-disable                              (CRITICAL)
  * macos-info-plist-quarantine-disable                         (HIGH)
  * macos-sudoers-nopasswd-injection                            (CRITICAL)
  * macos-dyld-insert-libraries-injection                       (HIGH)

Public surface:

  * Rule(id, name, severity, description, pattern, owasp_asi)
  * RULES — ordered tuple of every rule.
  * scan_text(text) -> list[Finding]
  * Finding(rule_id, line, column, matched_text, severity, description,
            owasp_asi) — frozen NamedTuple, mirrors chat_bot_patterns
            Finding shape.

OWASP ASI mapping used:
  ASI-03 — Privilege Compromise (Gatekeeper bypass, persistence,
                                  sudoers poisoning, dyld injection)
  ASI-05 — Cascading Hallucination Attacks (long-running C2 LaunchAgents)

All regexes are RE2-compatible (no backreferences, no lookbehind, no
catastrophic backtracking shapes). Patterns are PRE-COMPILED at module
load.
"""

from __future__ import annotations

import re
from typing import NamedTuple

# ---- Data model ---------------------------------------------------------


class Finding(NamedTuple):
    """A single rule match — same shape as chat_bot_patterns.Finding."""

    rule_id: str
    line: int
    column: int
    matched_text: str
    severity: str
    description: str
    owasp_asi: str


class Rule(NamedTuple):
    """A rule definition. Patterns are PRE-COMPILED at module load."""

    id: str
    name: str
    severity: str
    description: str
    pattern: re.Pattern[str]
    owasp_asi: str


def _re(pattern: str) -> re.Pattern[str]:
    """Compile with MULTILINE+UNICODE. xattr / launchctl / DYLD names are
    case-sensitive on macOS so we deliberately omit IGNORECASE here; plist
    XML tags are also case-sensitive by spec. RE2-safe: no nested
    quantifiers, no backreferences, no lookbehind."""
    return re.compile(pattern, re.MULTILINE | re.UNICODE)


# ---- M1 : macos-xattr-quarantine-clear ----------------------------------


# `xattr -c`, `xattr -d com.apple.quarantine`, `xattr -cr`, `xattr -dr`.
# Conservative: matches `-c`, `-cr`, `-d`, `-dr`, plus the explicit
# `-d com.apple.quarantine` form. Long-form `--clear` is non-standard
# on macOS xattr and intentionally NOT matched (avoids confusion with
# unrelated CLI tools that take `--clear`).
_XATTR_QUARANTINE_CLEAR = _re(
    r"\bxattr\s+-(?:[cd]r?|d\s+com\.apple\.quarantine)\b",
)


# ---- M2 : macos-launchagent-plist-persistence ---------------------------


# Path-based — user-domain LaunchAgents reverse-DNS plist names.
# System-domain `/Library/LaunchDaemons/` is rarely user-writable but
# the recursive label-style is identical, so we intentionally allow
# the optional leading `~` to be missing for the system-domain case.
_LAUNCHAGENT_PLIST_PATH = _re(
    r"(?:~|\$HOME|\$\{HOME\})?/Library/Launch(?:Agents|Daemons)"
    r"/[A-Za-z0-9._-]+\.plist\b",
)

# Plist content — RunAtLoad or KeepAlive set to <true/>. These two
# keys together are the persistence-with-respawn signature.
_LAUNCHAGENT_PLIST_RUNATLOAD = _re(
    r"<key>\s*(?:RunAtLoad|KeepAlive)\s*</key>\s*<true\s*/>",
)


# ---- M3 : macos-launchctl-activation-primitive --------------------------


# `launchctl load|unload|setenv|bootstrap|kickstart`. `bootstrap` is the
# post-Catalina equivalent of `load`; `setenv` injects desktop-wide env
# vars that affect every GUI-launched app (DYLD_* persistence channel).
_LAUNCHCTL_ACTIVATION = _re(
    r"\blaunchctl\s+(?:load|unload|setenv|bootstrap(?:\s+gui)?|kickstart)\b",
)


# ---- M4 : macos-spctl-gatekeeper-disable --------------------------------


# `spctl --master-disable` (nuke Gatekeeper system-wide),
# `spctl --add <path>` (path-specific allowlist),
# `spctl --assess --allow-anywhere` (one-shot per-file bypass).
_SPCTL_DISABLE = _re(
    r"\bspctl\s+(?:--master-disable\b"
    r"|--add\b"
    r"|--assess\b[^\n]{0,200}?--allow-anywhere\b)",
)

# GUI-escalation via AppleScript wrapper.
_SPCTL_OSASCRIPT_WRAPPER = _re(
    r"\bosascript\b[^\n]{0,200}?do\s+shell\s+script"
    r"[^\n]{0,200}?spctl"
    r"[^\n]{0,200}?with\s+administrator\s+privileges",
)


# ---- M5 : macos-info-plist-quarantine-disable ---------------------------


# Hostile Info.plist quarantine-disabling keys.
_INFO_PLIST_QUARANTINE_KEY = _re(
    r"<key>\s*LS(?:FileQuarantineEnabled"
    r"|FileQuarantineExcludedPathPatterns"
    r"|QuarantineAgentURL"
    r"|QuarantineDataURL)\s*</key>",
)

# Python / Node code path — the imperative flip of the same key.
_INFO_PLIST_QUARANTINE_CODE = _re(
    r"\bLSFileQuarantineEnabled\b[^\n]{0,80}?"
    r"(?:False|false|<false\s*/>|0\b)",
)


# ---- M6 : macos-sudoers-nopasswd-injection ------------------------------


# Sudoers `<user> ALL=(ALL) NOPASSWD: ALL` line shape.
_SUDOERS_NOPASSWD_LINE = _re(
    r"\b[A-Za-z_][A-Za-z0-9_-]{0,31}\s+ALL=\(ALL\)\s+NOPASSWD:\s*ALL\b",
)

# Companion: write-to-sudoers via tee/redirect.
_SUDOERS_WRITE_PATTERN = _re(
    r"(?:>>?\s*|tee\s+(?:-a\s+)?)/etc/sudoers(?:\.d/[^/\s]+)?\b",
)


# ---- M7 : macos-dyld-insert-libraries-injection -------------------------


# Env-var assignment in code OR shell. Comma-separated paths are valid
# (`DYLD_INSERT_LIBRARIES=a.dylib:b.dylib`); we match the `=` discriminator
# only — Stage-B filters refine on the path target. The character class
# `[\"\'\]\s]{0,4}` between the env name and `=` covers the three call
# shapes: shell `KEY=val`, Python `os.environ["KEY"] = val`, JS
# `process.env.KEY =` (the `.` form is matched separately below).
_DYLD_ENV_ASSIGN = _re(
    r"\bDYLD_(?:INSERT_LIBRARIES"
    r"|FRAMEWORK_PATH"
    r"|FALLBACK_LIBRARY_PATH"
    r"|LIBRARY_PATH"
    r"|FORCE_FLAT_NAMESPACE)[\"'\]\s]{0,4}[:=]",
)

# Persistence channel — launchctl setenv DYLD_*. High-confidence
# combination (no legit reason to launchctl-setenv DYLD).
_DYLD_LAUNCHCTL_SETENV = _re(
    r"\blaunchctl\s+setenv\s+DYLD_",
)

# Suppression guard — dylib path under known instrumentation roots.
# Apple Developer / Xcode-installed sanitizer / profiler dylibs come from
# these prefixes and are legitimate DYLD_INSERT use cases.
_DYLD_INSTRUMENTATION_GUARD = _re(
    r"(?:/Library/Developer/"
    r"|/Applications/Xcode(?:-[A-Za-z0-9_.-]+)?\.app/"
    r"|libclang_rt\.(?:asan|tsan|ubsan|lsan|msan)_osx_dynamic\.dylib"
    r"|libBacktraceRecording\.dylib)",
)


# ---- Rule registry ------------------------------------------------------


RULES: tuple[Rule, ...] = (
    Rule(
        id="macos-xattr-quarantine-clear",
        name="xattr -c / -d com.apple.quarantine clears Gatekeeper quarantine",
        severity="CRITICAL",
        description=(
            "Calling `xattr` with `-c` (clear all), `-d "
            "com.apple.quarantine` (delete specific), or `-dr` "
            "(recursive delete) strips macOS's quarantine flag from a "
            "downloaded binary, suppressing Gatekeeper's user-confirmation "
            "prompt and notarization check on first launch. This is the "
            "exact primitive observed in the AMOS (Atomic macOS Stealer) "
            "dropper chain delivered through poisoned Claude Code / "
            "OpenClaw / npm packages. The legitimate-FP carve-out is "
            "Mac developer tooling on hosted CI runners; mark those "
            "with `# pragma: gatekeeper-bypass-ok`."
        ),
        pattern=_XATTR_QUARANTINE_CLEAR,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="macos-launchagent-plist-persistence",
        name="LaunchAgent / LaunchDaemon plist drop with RunAtLoad / KeepAlive",
        severity="CRITICAL",
        description=(
            "Dropping a property-list file under the user-domain "
            "LaunchAgents directory (`~/Library/LaunchAgents/com.*.plist`) "
            "with `RunAtLoad`+`KeepAlive` set to <true/> establishes a "
            "permanent SIP-safe execution channel that fires on every "
            "login and respawns if killed. The Shai-Hulud framework's "
            "deadman switch uses exactly this primitive: "
            "`com.user.gh-token-monitor.plist` polls GitHub every minute "
            "and `rm -rf ~/` on token revocation. AMOS variants use the "
            "more deceptive `com.apple.act.mond` reverse-DNS squat. "
            "Legitimate use (`homebrew.mxcl.*`, `com.docker.*`, "
            "`com.jetbrains.*`) requires a label allowlist."
        ),
        pattern=_LAUNCHAGENT_PLIST_PATH,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="macos-launchctl-activation-primitive",
        name="launchctl load|unload|setenv|bootstrap|kickstart activator",
        severity="HIGH",
        description=(
            "`launchctl load <plist>` is the activation step that turns "
            "a newly-written plist into a running daemon; `launchctl "
            "setenv` injects desktop-wide environment variables "
            "(affecting GUI-launched apps); `launchctl bootstrap "
            "gui/$UID <plist>` is the post-Catalina equivalent of "
            "`load`. Detecting these calls is the verb-side companion "
            "to the noun-side LaunchAgent plist detection — a dropper "
            "that drops a plist without `launchctl load`ing it has not "
            "yet armed; a `launchctl load` against an unknown-provenance "
            "path is half a smoking gun. Pair with a label allowlist "
            "to suppress legitimate `brew services` usage."
        ),
        pattern=_LAUNCHCTL_ACTIVATION,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="macos-spctl-gatekeeper-disable",
        name="spctl --master-disable / --add / --assess --allow-anywhere",
        severity="CRITICAL",
        description=(
            "`spctl` is the user-space command for Gatekeeper's policy. "
            "`sudo spctl --master-disable` turns Gatekeeper off "
            "system-wide; `spctl --add <path>` whitelists a specific "
            "path; `spctl --assess --allow-anywhere` weakens the "
            "install-time check. All three are root-required but "
            "trivially reachable through an agent granted sudo via "
            "prompt-injection or via sudoers-NOPASSWD poisoning. The "
            "MDM-bootstrap carve-out is paths under `/Library/Application "
            "Support/<corp-mdm>/`; flag everything else."
        ),
        pattern=_SPCTL_DISABLE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="macos-info-plist-quarantine-disable",
        name="Info.plist LSFileQuarantineEnabled=false / LSQuarantine* keys",
        severity="HIGH",
        description=(
            "A malicious app bundle declares its own quarantine posture "
            "via Info.plist keys: `LSFileQuarantineEnabled=false` "
            "disables Launch-Services-driven quarantine on files this "
            "app creates; `LSFileQuarantineExcludedPathPatterns` lets "
            "an installer pre-clear files it drops; `LSQuarantineAgent"
            "URL` / `LSQuarantineDataURL` are deprecated but still "
            "respected on some macOS versions and let the bundle "
            "masquerade as a different downloader. Declarative form of "
            "the imperative `xattr -c` primitive — embedded in the "
            "bundle that ships with the npm package."
        ),
        pattern=_INFO_PLIST_QUARANTINE_KEY,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="macos-sudoers-nopasswd-injection",
        name="Sudoers NOPASSWD line injected into /etc/sudoers or /etc/sudoers.d",
        severity="CRITICAL",
        description=(
            "Appending `<user> ALL=(ALL) NOPASSWD:ALL` to "
            "`/etc/sudoers` or to a file under `/etc/sudoers.d/` lets a "
            "non-root user execute `sudo <anything>` with no password "
            "prompt. Once installed, every future `spctl "
            "--master-disable`, `xattr -dr` on SIP-protected locations, "
            "or write into `/Library/LaunchDaemons/` succeeds silently. "
            "Observed verbatim in the Shai-Hulud npm-supply-chain "
            "campaign: `Injects a sudoers rule (runner ALL=(ALL) "
            "NOPASSWD:ALL) and modifies /etc/hosts`. Legitimate carve-out "
            "is initial GitHub Actions self-hosted-runner provisioning "
            "(by an admin account, not a runner-time write)."
        ),
        pattern=_SUDOERS_NOPASSWD_LINE,
        owasp_asi="ASI-03",
    ),
    Rule(
        id="macos-dyld-insert-libraries-injection",
        name="DYLD_INSERT_LIBRARIES / DYLD_FRAMEWORK_PATH env-var injection",
        severity="HIGH",
        description=(
            "Setting `DYLD_INSERT_LIBRARIES=/path/to/inject.dylib` loads "
            "an attacker-controlled dylib into every subsequent process "
            "that honours `DYLD_*` (i.e. any process not running under "
            "Hardened Runtime with `restrict` or `library-validation`). "
            "On a developer workstation this catches all the unsigned "
            "tooling — `python3`, `node`, `npm`, `git`, Homebrew "
            "binaries, shell utilities, etc. Persistence is via "
            "`launchctl setenv`, `~/.zshrc`, or a wrapper script. The "
            "legitimate carve-out is sanitizer / profiler instrumentation "
            "from `/Library/Developer/` or Xcode-installed paths."
        ),
        pattern=_DYLD_ENV_ASSIGN,
        owasp_asi="ASI-03",
    ),
)


# ---- Scanner-level helpers ----------------------------------------------


def _line_col(text: str, offset: int) -> tuple[int, int]:
    """Convert a string offset into (1-based line, 1-based column)."""
    before = text[:offset]
    line = before.count("\n") + 1
    col = offset - (before.rfind("\n") + 1) + 1
    return (line, col)


def _slice_window(text: str, line_no: int, backward: int, forward: int) -> str:
    """Return up to `backward` lines preceding line_no plus line_no itself
    plus the next `forward` lines."""
    parts = text.split("\n")
    start = max(0, line_no - 1 - backward)
    end = min(len(parts), line_no + forward)
    return "\n".join(parts[start:end])


# ---- The composed scanner -----------------------------------------------


def scan_text(text: str) -> list[Finding]:
    """Run every applicable RULES pattern against `text` and return findings.

    Stage-B filters consult adjacent lines for context:

      * M2 (launchagent-plist-persistence) — path match alone is enough
        for a HIGH finding; raise to CRITICAL when the same file also
        contains `RunAtLoad`+`KeepAlive` content (the deadman signature).
        The path-only emission already happens at CRITICAL because the
        path under a user-writable Launch directory IS the IOC.
      * M4 (spctl-gatekeeper-disable) — primary `_SPCTL_DISABLE` matches
        always emit; the AppleScript wrapper variant
        (`_SPCTL_OSASCRIPT_WRAPPER`) is treated as a separate Stage-A
        emission against the same rule (different attack-chain stage,
        same primitive).
      * M5 (info-plist-quarantine-disable) — both the XML key match and
        the Python/Node code-path match emit against the same rule. The
        code-path variant is high-precision and never gated.
      * M6 (sudoers-nopasswd-injection) — the line shape alone is a
        very narrow, high-confidence match (almost never legitimate
        outside `/etc/sudoers.d/*` literal audit text). The companion
        write-pattern emits ALSO, treated as the same rule.
      * M7 (dyld-insert-libraries-injection) — match the env-var
        assignment AND filter out clear instrumentation-library
        targets in the surrounding 5/5 line window.

    Findings are deduped by (rule_id, line, col).
    """
    if not text:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, int, int]] = set()

    def _emit(rule: Rule, offset: int, matched: str) -> None:
        line, col = _line_col(text, offset)
        key = (rule.id, line, col)
        if key in seen:
            return
        seen.add(key)
        snippet = matched if len(matched) <= 200 else matched[:200] + "…"
        findings.append(
            Finding(
                rule_id=rule.id,
                line=line,
                column=col,
                matched_text=snippet,
                severity=rule.severity,
                description=rule.description,
                owasp_asi=rule.owasp_asi,
            )
        )

    rule_by_id = {r.id: r for r in RULES}

    # ---- M1 : xattr quarantine clear ----
    rule_m1 = rule_by_id["macos-xattr-quarantine-clear"]
    for m in _XATTR_QUARANTINE_CLEAR.finditer(text):
        _emit(rule_m1, m.start(), m.group(0))

    # ---- M2 : LaunchAgent plist persistence ----
    rule_m2 = rule_by_id["macos-launchagent-plist-persistence"]
    # Path-based IOC — emit per match.
    for m in _LAUNCHAGENT_PLIST_PATH.finditer(text):
        _emit(rule_m2, m.start(), m.group(0))
    # Content-based IOC — RunAtLoad / KeepAlive in plist body.
    for m in _LAUNCHAGENT_PLIST_RUNATLOAD.finditer(text):
        _emit(rule_m2, m.start(), m.group(0))

    # ---- M3 : launchctl activation primitive ----
    rule_m3 = rule_by_id["macos-launchctl-activation-primitive"]
    for m in _LAUNCHCTL_ACTIVATION.finditer(text):
        _emit(rule_m3, m.start(), m.group(0))

    # ---- M4 : spctl Gatekeeper disable ----
    rule_m4 = rule_by_id["macos-spctl-gatekeeper-disable"]
    for m in _SPCTL_DISABLE.finditer(text):
        _emit(rule_m4, m.start(), m.group(0))
    for m in _SPCTL_OSASCRIPT_WRAPPER.finditer(text):
        _emit(rule_m4, m.start(), m.group(0))

    # ---- M5 : Info.plist quarantine-disabling keys ----
    rule_m5 = rule_by_id["macos-info-plist-quarantine-disable"]
    for m in _INFO_PLIST_QUARANTINE_KEY.finditer(text):
        _emit(rule_m5, m.start(), m.group(0))
    for m in _INFO_PLIST_QUARANTINE_CODE.finditer(text):
        _emit(rule_m5, m.start(), m.group(0))

    # ---- M6 : sudoers NOPASSWD injection ----
    rule_m6 = rule_by_id["macos-sudoers-nopasswd-injection"]
    for m in _SUDOERS_NOPASSWD_LINE.finditer(text):
        _emit(rule_m6, m.start(), m.group(0))
    # Also flag the write-to-sudoers pattern (companion shell verb).
    for m in _SUDOERS_WRITE_PATTERN.finditer(text):
        _emit(rule_m6, m.start(), m.group(0))

    # ---- M7 : DYLD_INSERT_LIBRARIES injection ----
    rule_m7 = rule_by_id["macos-dyld-insert-libraries-injection"]
    # Stage-B: suppress when the surrounding ±5-line window points at a
    # known instrumentation framework path. Otherwise emit at HIGH.
    for m in _DYLD_ENV_ASSIGN.finditer(text):
        line, _ = _line_col(text, m.start())
        window = _slice_window(text, line, 5, 5)
        if _DYLD_INSTRUMENTATION_GUARD.search(window) is not None:
            continue
        _emit(rule_m7, m.start(), m.group(0))
    # The launchctl-setenv-DYLD path is high-confidence and never gated.
    for m in _DYLD_LAUNCHCTL_SETENV.finditer(text):
        _emit(rule_m7, m.start(), m.group(0))

    findings.sort(key=lambda f: (f.line, f.column, f.rule_id))
    return findings
