---
name: janitor-skill-bundle-audit
description: On-demand security audit of every agent-context bundle in the current project — SKILL.md / CLAUDE.md / AGENTS.md / .cursorrules / .aider.conf.yml / .claude/* / .mcp.json. Detects multilingual prompt-injection, HTML-comment authority impersonation, base-URL override, cross-skill shadowing, dynamic exec in skill bodies, git-hook install directives, exfil webhook sinks, and known-secret-path references. Trigger with /janitor-skill-bundle-audit, "scan my skills for prompt injection", "audit CLAUDE.md for attacks", or "check .cursorrules for hijack patterns".
---

# Janitor skill-bundle audit

## Overview

Agent-context files (SKILL.md, CLAUDE.md, AGENTS.md, .cursorrules,
.aider.conf.yml, the `.claude/` tree, .mcp.json, etc.) are the
"instructions a human reader sees" surface AND the "instructions the
agent silently obeys" surface. An attacker who can write to one of
those files can issue covert directives — multilingual
"ignore-previous-instructions" payloads, HTML-comment authority
impersonations, base-URL overrides that redirect every subsequent LLM
call to an attacker-controlled gateway, cross-skill shadowing that
makes every other skill invoke a malicious one first.

This skill scans every agent-context file in the project with the
shared rule catalogue from `scripts/lib/agent_config_patterns.py`
(Wave 2 of the github-monitoring distillation) and surfaces every
match grouped by file + severity. Read-only — never edits a file.

The companion **heartbeat** detector `ai-context-poisoning.py`
audits installed packages for postinstall code that *writes to* an
agent-context file. This skill audits the *current content* of those
files for attacker-planted directives.

## Prerequisites

* `uv` on PATH (the underlying scanner runs as a PEP-723 script).
* The project root resolves either from `$CLAUDE_PROJECT_DIR` or the
  current working directory.
* The project is NOT the janitor's own repo. The skill refuses to
  scan itself unless `CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1`.

## Arguments

Parse `$ARGUMENTS` for any of (all optional):

* `--path <dir>` — audit a subtree instead of the whole project root.
* `--severity <CRITICAL|HIGH|MEDIUM|LOW>` — minimum severity to report
  (default: `LOW` = everything).
* `--json` — emit one JSON-line per finding instead of the grouped
  human-readable table.
* `--strict` — exit non-zero if any CRITICAL/HIGH finding is reported
  (default: exit 0 — the skill SURFACES findings, doesn't gate CI).

## Instructions

1. **Pre-flight checks**:

   ```bash
   # Resolve project root (worktree-safe).
   if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
     PROJECT_ROOT="$(git worktree list | head -n1 | awk '{print $1}')"
   else
     PROJECT_ROOT="${CLAUDE_PROJECT_DIR:-$(pwd)}"
   fi

   # Self-scan guard.
   if [ -f "$PROJECT_ROOT/.claude-plugin/plugin.json" ] && \
      [ "$(jq -r .name "$PROJECT_ROOT/.claude-plugin/plugin.json" 2>/dev/null)" = "ai-maestro-janitor" ] && \
      [ -z "$CLAUDE_PLUGIN_ALLOW_SELF_SCAN" ]; then
     echo "[SKIP] refuses to audit the janitor's own repo (set CLAUDE_PLUGIN_ALLOW_SELF_SCAN=1 to override)"
     exit 0
   fi
   ```

2. **Enumerate agent-context files** under `$PROJECT_ROOT` (or
   `--path` subtree). The canonical inventory lives in
   `agent_context_files()` from `scripts/lib/security_helpers.py`:

   ```text
   CLAUDE.md, CLAUDE.local.md, AGENTS.md, AGENT.md,
   .cursorrules, .cursor/rules/*, .aiderrules, .aider.conf.yml,
   .codexrules, .continuerules, .windsurfrules, .cody/instructions,
   .claude/settings.json, .claude/agents/*, .claude/skills/*,
   .claude/hooks/*, .claude/commands/*, .claude/CLAUDE.md,
   .mcp.json, .claude-plugin/plugin.json
   ```

   Plus every `SKILL.md` under `skills/` and every `*.md` under
   `agents/` and `commands/` in the project tree. Skip `node_modules/`,
   `.venv/`, `dist/`, `build/` — those are scanned by the
   `ai-context-poisoning` detector, not by this skill.

3. **Scan each file** through `agent_config_patterns.scan_text()`:

   ```bash
   uv run --with /dev/null - <<'PY'
   import sys, json
   from pathlib import Path
   sys.path.insert(0, str(Path("$PROJECT_ROOT") / "scripts" / "lib"))
   import agent_config_patterns as acp

   for fp in target_files:
       text = Path(fp).read_text(encoding="utf-8", errors="replace")
       for f in acp.scan_text(text, file_kind="prose"):
           print(json.dumps({
               "file": fp, "line": f.line, "col": f.column,
               "rule_id": f.rule_id, "severity": f.severity,
               "owasp": f.owasp_asi, "match": f.matched_text,
               "description": f.description,
           }))
   PY
   ```

4. **Group + render** to the user, ordered by severity then by file:

   ```text
   ┌─────────────────────────────────────────────────────────────┐
   │ CRITICAL (3)                                                │
   ├─────────────────────────────────────────────────────────────┤
   │ CLAUDE.md:42                                                │
   │   prompt-injection-multilingual (ASI-01)                    │
   │   <ignore-prev-instructions payload>                        │
   │ skills/foo/SKILL.md:7                                       │
   │   html-comment-impersonation (ASI-01)                       │
   │   <html-comment-impersonation hit>                          │
   │ .cursorrules:1                                              │
   │   base-url-override (ASI-04)                                │
   │   <base-url-override to attacker-controlled gateway>        │
   └─────────────────────────────────────────────────────────────┘
   ```

5. **Recommend remediation** under each grouping, one line per
   rule class:
   * `prompt-injection-multilingual` → "Strip the override directive
     and audit who introduced it (git blame on the offending line)."
   * `html-comment-impersonation` → "Remove the HTML comment; treat
     every HTML comment that forges a system / admin / instruction
     directive — rule `html-comment-impersonation`, whose signature
     lives in `agent_config_patterns.py` — as an attack signal."
   * `base-url-override` → "Restore the original endpoint; if this is
     intentional, document it in a separate non-agent-context file."
   * `cross-skill-shadowing` → "Skill descriptions must not mandate
     other skills; convert to suggestion or remove."
   * `exfil-webhook-sink` → "Block-list the host; rotate any credential
     mentioned nearby in the same file."

6. **Report one summary line** to stdout in addition to the table:

   ```text
   skill-bundle-audit: 7 finding(s) across 4 file(s) [3 CRITICAL, 2 HIGH, 2 MEDIUM]. Worst: CLAUDE.md:42 prompt-injection-multilingual.
   ```

## Output

A grouped table of findings to the user PLUS one summary line. With
`--json`, ONE finding per line to stdout (no table). With `--strict`,
exit 1 if any CRITICAL/HIGH finding fired (so CI can wrap this skill
as a gate).

## Error Handling

* No agent-context files found → `skill-bundle-audit: 0 file(s)
  matched the agent-context inventory under <path>`; exit 0.
* A file is unreadable (permission, binary, broken symlink) → skip
  silently; the scan keeps running. Count the skips in the summary
  line.
* The patterns module fails to import → report `FAILED: cannot import
  agent_config_patterns from <path>` and exit 2.

## Examples

```text
User: /janitor-skill-bundle-audit
User: scan my skills for prompt injection
User: audit CLAUDE.md and .cursorrules for attacks
User: check .claude/agents/ for skill hijack patterns
User: /janitor-skill-bundle-audit --severity HIGH --strict
User: /janitor-skill-bundle-audit --path skills/ --json
```

## Remediation (fix)

> **janitor-security-agent** runs this remediation after an audit finds findings.
> If `/janitor-autofix-off` is set for the project, DETECT + FLAG only — apply no changes.

### Per-class fix policy

| Rule class | Fix | Mode |
|---|---|---|
| `prompt-injection-multilingual` | Strip the override directive (the matched line or span). Re-scan to confirm the pattern is gone. Run `git blame` on the offending line and record the commit hash in the report. | **SAFE-TO-AUTO-FIX** — strip invisible-unicode / embedded instruction spans; **FLAG-FOR-HUMAN** when the surrounding context is ambiguous |
| `html-comment-impersonation` | Remove the offending HTML comment block. Re-scan to confirm 0 matches in the file. | **SAFE-TO-AUTO-FIX** |
| `base-url-override` | Remove or restore the original endpoint. If the override is intentional and documented, move the config to a non-agent-context file and FLAG the original location. Auto-fix only when the override URL matches a known attacker-gateway pattern. Otherwise **FLAG-FOR-HUMAN**. | **FLAG-FOR-HUMAN** (default); **SAFE-TO-AUTO-FIX** when URL is a known malicious gateway |
| `cross-skill-shadowing` | Remove the mandatory-invocation language from the skill description. Convert "always invoke skill-X first" to "consider skill-X for …". Re-scan to confirm 0 matches. | **SAFE-TO-AUTO-FIX** |
| `exfil-webhook-sink` | Remove the webhook URL. Block-list the host in the report. Flag any nearby credentials for rotation. | **SAFE-TO-AUTO-FIX** (URL removal); **FLAG-FOR-HUMAN** (credential rotation) |
| `dynamic-exec-in-skill-body` | If the exec call is an injected payload (not a legitimate feature), strip it. If it may be intentional, **FLAG-FOR-HUMAN** — auto-exec is a capability, not always an attack. | **FLAG-FOR-HUMAN** |
| `git-hook-install-directive` | Remove the directive. If the hook installation is intentional, move it to a non-agent-context file and document its purpose. | **FLAG-FOR-HUMAN** |
| `known-secret-path-reference` | Remove the path reference from the agent-context file. Verify no credential is exposed at that path. | **FLAG-FOR-HUMAN** |

### Auto-fix procedure

1. For each SAFE-TO-AUTO-FIX finding, compute the minimal text removal (matched span only — never alter surrounding prose).
2. Strip any invisible-unicode characters (`security_helpers.strip_invisible_unicode`) from the matched line before writing back; log the character code points in the report.
3. Write the patched file atomically (write to tmp, then `os.replace`).
4. Re-scan the patched file through `agent_config_patterns.scan_text()`. If the same rule still fires, **REVERT the patch** and FLAG the finding for human review.
5. Do NOT commit — leave staging to the human or the release pipeline.

### Flag-for-human procedure

Append a `## Findings requiring human review` section to the audit report with: file:line, rule-id, severity, matched text, and the reason auto-fix was skipped. Never suppress a finding to pass a gate. Never force-push.

## Scope

This skill is the **content** audit: it looks for attacker directives
INSIDE agent-context files. The complementary surfaces:

* `ai-context-poisoning` heartbeat detector — audits *installed
  packages* (node_modules / site-packages) for postinstall code that
  *writes to* an agent-context file. Different threat, same surface.
* `janitor-github-workflow-doctor` — audits `.github/workflows/` for
  workflow-level attacks (template injection, missing pinning, etc.).
* `janitor-supply-chain-watcher` — audits lockfiles for known-vuln
  advisories.

The four together — workflow + lockfile + installed-package +
agent-context-content — cover the supply-chain → agent-runtime
attack surface end-to-end.

## Resources

* [`scripts/lib/agent_config_patterns.py`](../../scripts/lib/agent_config_patterns.py)
  — the rule catalogue + `scan_text()` entry point.
* [`scripts/lib/security_helpers.py`](../../scripts/lib/security_helpers.py)
  — `agent_context_files()` inventory + OWASP Agentic Top-10 taxonomy.
* [`scripts/detectors/ai-context-poisoning.py`](../../scripts/detectors/ai-context-poisoning.py)
  — heartbeat companion detector.

## Checklist

Copy this checklist and track your progress:

* [ ] Pre-flight: project root resolved (worktree-safe)
* [ ] Pre-flight: self-scan guard fires on janitor's own repo
* [ ] Enumerated agent-context files via `agent_context_files()` inventory
* [ ] Scanned each file via `agent_config_patterns.scan_text()`
* [ ] Grouped findings by severity + file
* [ ] Rendered remediation hint per rule class
* [ ] Emitted one summary line
* [ ] Honoured `--json` / `--severity` / `--strict` arguments
