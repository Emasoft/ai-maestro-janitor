# Shared contract for the Sentinel structural rule tier.
#
# Python port of the Sentinel reference's lib/workflow.rb (the Workflow
# model) and lib/rules/concerns/guard_patterns.rb (the attacker-control
# guard helpers). Structural rules import everything they need from here so
# the three rules_*.py modules can be authored independently against one
# stable interface.
#
# The canonical Finding type is reused from lib.zizmor_classifier so the
# regex tier and the structural tier emit identical records and
# scripts/doctor_classify.py can serialize both with one code path.

from __future__ import annotations

import re
from typing import Optional, Union

import yaml

from lib.zizmor_classifier import Finding  # canonical frozen Finding

# --- constants (ported verbatim from guard_patterns.rb) --------------------

# Triggers that an attacker cannot influence the payload of. A workflow whose
# triggers are ALL in this set cannot carry attacker-controlled context, so
# the injection rules short-circuit to "clean".
SAFE_TRIGGERS = frozenset({
    "workflow_dispatch", "schedule", "push", "workflow_call", "release",
    "deployment", "deployment_status", "create", "delete",
    "page_build", "watch", "fork", "star", "gollum",
})

# Keys that appear under a job but are NOT job names — used when walking
# upward to decide whether a line belongs to the enclosing job.
JOB_PROPERTIES = frozenset({
    "steps", "runs-on", "env", "strategy", "permissions", "outputs",
    "concurrency", "services", "needs", "container", "timeout-minutes",
    "if", "name", "defaults",
})

# The precise allowlist of attacker-controllable expression contexts. This is
# the FP-resistant core: injection rules match ONLY these, never a broad
# "{{ ... }} contains the substring request" heuristic. Safe expressions such
# as github.event.pull_request.number are deliberately absent and never fire.
DANGEROUS_CONTEXTS = (
    "github.event.pull_request.title",
    "github.event.pull_request.body",
    "github.event.pull_request.head.ref",
    "github.event.pull_request.head.label",
    "github.event.issue.title",
    "github.event.issue.body",
    "github.event.comment.body",
    "github.event.review.body",
    "github.event.discussion.title",
    "github.event.discussion.body",
    "github.event.workflow_run.head_branch",
    "github.head_ref",
)

# ${{   <one of the dangerous contexts>   ...   — group(1) is the context,
# used in the finding message. Mirrors the Ruby PATTERN in the two injection
# rules.
DANGEROUS_CONTEXT_PATTERN = re.compile(
    r"\$\{\{\s*(" + "|".join(re.escape(c) for c in DANGEROUS_CONTEXTS) + r")"
)

# Severity vocabulary (Sentinel critical/high/medium/low → janitor labels).
SEV_CRITICAL = "CRITICAL"
SEV_HIGH = "HIGH"
SEV_MAJOR = "MAJOR"   # Sentinel "medium"
SEV_MINOR = "MINOR"   # Sentinel "low"


# --- small helpers ---------------------------------------------------------

def _compile(pattern: Union[str, "re.Pattern[str]"]) -> "re.Pattern[str]":
    return pattern if isinstance(pattern, re.Pattern) else re.compile(pattern)


def _indent(line: Optional[str]) -> int:
    """Number of leading whitespace characters (Ruby content[/^\\s*/].length)."""
    if not line:
        return 0
    return len(line) - len(line.lstrip())


# --- Workflow model (port of lib/workflow.rb) ------------------------------

class Workflow:
    """Parsed GitHub Actions workflow with raw-line + structured access.

    Mirrors the Sentinel Ruby Workflow: raw_lines preserve source order for
    line-accurate findings, while `data` is the YAML structure for semantic
    checks. Both views are needed — absence checks read `data`, line numbers
    come from `raw_lines`.
    """

    def __init__(self, filename: str, content: str) -> None:
        self.filename = filename
        self.raw = content
        self.raw_lines = content.splitlines()
        try:
            loaded = yaml.safe_load(content)
            self.data = loaded if isinstance(loaded, dict) else {}
        except yaml.YAMLError:  # malformed YAML → empty model, not a crash
            self.data = {}

    def triggers(self):
        # PyYAML parses the bare key `on` as the boolean True (YAML 1.1), so
        # check both "on" and True — same gotcha the Ruby port handled.
        if "on" in self.data:
            return self.data["on"] or {}
        if True in self.data:
            return self.data[True] or {}
        return {}

    def jobs(self) -> dict:
        jobs = self.data.get("jobs")
        return jobs if isinstance(jobs, dict) else {}

    def steps(self, job) -> list:
        job_hash = self.jobs().get(job) if isinstance(job, str) else job
        if not isinstance(job_hash, dict):
            return []
        steps = job_hash.get("steps")
        return steps if isinstance(steps, list) else []

    def permissions(self, scope: str = "workflow", job=None):
        if scope == "workflow":
            return self.data.get("permissions")
        if scope == "job":
            j = self.jobs().get(job) if isinstance(job, str) else job
            return j.get("permissions") if isinstance(j, dict) else None
        return None

    def line_of(self, pattern) -> Optional[int]:
        rx = _compile(pattern)
        for i, line in enumerate(self.raw_lines):
            if rx.search(line):
                return i + 1
        return None

    def lines_of(self, pattern) -> list:
        rx = _compile(pattern)
        return [i + 1 for i, line in enumerate(self.raw_lines) if rx.search(line)]

    def line_content(self, num: int) -> Optional[str]:
        if 1 <= num <= len(self.raw_lines):
            return self.raw_lines[num - 1].rstrip()
        return None

    def uses_actions(self) -> list:
        """List of {uses, step, line} for every step with a `uses:` key."""
        results = []
        seen: dict[str, int] = {}
        for job_hash in self.jobs().values():
            for step in self.steps(job_hash):
                if not isinstance(step, dict) or not step.get("uses"):
                    continue
                uses = step["uses"]
                all_lines = self.lines_of(r"uses:\s*" + re.escape(str(uses)))
                idx = seen.get(uses, 0)
                line = all_lines[idx] if idx < len(all_lines) else (all_lines[-1] if all_lines else 0)
                seen[uses] = idx + 1
                results.append({"uses": uses, "step": step, "line": line})
        return results


# --- guard helpers (port of guard_patterns.rb + the two injection rules) ---

def safe_trigger_only(wf: Workflow) -> bool:
    t = wf.triggers()
    if isinstance(t, dict):
        names = [str(k) for k in t.keys()]
    elif isinstance(t, list):
        names = [str(x) for x in t]
    elif isinstance(t, str):
        names = [t]
    else:
        names = []
    return bool(names) and all(n in SAFE_TRIGGERS for n in names)


def _safe_guard_condition(condition: Optional[str]) -> bool:
    """True iff a simple `if:` clearly restricts to a SAFE_TRIGGER event."""
    if not condition:
        return False
    condition = re.sub(r"\$\{\{\s*", "", condition)
    condition = re.sub(r"\s*\}\}", "", condition).strip()
    # Reject complex boolean expressions — only single-clause guards are safe.
    if re.search(r"(\|\||&&|always\s*\(|failure\s*\(|cancelled\s*\()", condition):
        return False
    m = re.match(r"\Agithub\.event_name\s*==\s*['\"](\w+)['\"]\Z", condition)
    if m:
        return m.group(1) in SAFE_TRIGGERS
    return False


def _guarded_by_step_if(wf: Workflow, line_num: int) -> bool:
    raw = wf.raw_lines
    start = line_num - 2
    stop = max(line_num - 30, 0)
    for i in range(start, stop - 1, -1):
        if i < 0 or i >= len(raw):
            continue
        content = raw[i]
        if content is None:
            continue
        if re.search(r"^\s+if:\s*", content):
            m = re.search(r"if:\s*(.+)", content)
            if m:
                return _safe_guard_condition(m.group(1).strip())
        if re.search(r"^\s+-\s+\S", content):
            if re.search(r"^\s+-\s+if:\s*", content):
                m = re.search(r"if:\s*(.+)", content)
                if m:
                    return _safe_guard_condition(m.group(1).strip())
            break
        if re.search(r"^\s+\w[\w-]*:", content) and not re.search(r"^\s+-", content):
            if _indent(content) <= 6:
                break
    return False


def _guarded_by_job_if(wf: Workflow, line_num: int) -> bool:
    raw = wf.raw_lines
    job_keys_seen = 0
    enclosing_job_line = None
    for i in range(line_num - 2, -1, -1):
        if i >= len(raw):
            continue
        content = raw[i]
        if content is None:
            continue
        if re.search(r"^jobs:\s*$", content):
            return False
        key_match = re.search(r"^\s+(\w[\w-]*):\s*$", content)
        if key_match:
            key_name = key_match.group(1)
            key_indent = _indent(content)
            if key_indent <= 4 and key_name not in JOB_PROPERTIES:
                job_keys_seen += 1
                if job_keys_seen == 1:
                    enclosing_job_line = i
                if job_keys_seen > 1:
                    return False
        if re.search(r"^\s+if:\s*", content):
            if_indent = _indent(content)
            for j in range(i - 1, max(i - 15, 0) - 1, -1):
                if j < 0 or j >= len(raw):
                    continue
                above = raw[j]
                if above is None:
                    continue
                if re.search(r"^\s+\w[\w-]*:\s*$", above):
                    above_indent = _indent(above)
                    if if_indent == above_indent + 2 and (enclosing_job_line is None or j == enclosing_job_line):
                        m = re.search(r"if:\s*(.+)", content)
                        if m:
                            return _safe_guard_condition(m.group(1).strip())
                    break
        # `steps:` — keep walking up into job-level territory.
    return False


def guarded_by_safe_event(wf: Workflow, line_num: int) -> bool:
    return _guarded_by_step_if(wf, line_num) or _guarded_by_job_if(wf, line_num)


def in_run_block(wf: Workflow, target_line: int) -> bool:
    """True iff target_line sits inside a `run:` block (port of shell_injection_expr).

    Walks UP from the target line to find the enclosing `run:` key. The scan
    is bounded by INDENTATION, not a fixed line count: a previous fixed
    20-line window let an attacker pad a multi-line `run: |` script with
    >20 lines above the payload so the dangerous `${{ }}` was silently
    classified as "not in a run block" (suppressing CRITICAL injection
    findings). The body of a `run: |` block is indented strictly deeper than
    its step's structural keys, so we stop the moment we reach a structural
    line (a `- ` step marker or a `key:` at the step level or shallower) —
    that is the real step boundary regardless of how long the script is.
    """
    raw = wf.raw_lines
    target_content = raw[target_line - 1] if 0 <= target_line - 1 < len(raw) else None
    target_indent = _indent(target_content) if target_content else 0
    for i in range(target_line - 1, -1, -1):
        if i < 0 or i >= len(raw):
            continue
        content = raw[i]
        if content is None:
            continue
        if re.search(r"^\s+run:\s*[|>]?\s*$", content) or re.search(r"^\s+run:\s+\S", content):
            return True
        if re.search(r"^\s+-\s+run:\s*[|>]?\s*$", content) or re.search(r"^\s+-\s+run:\s+\S", content):
            return True
        if re.search(r"^\s+(uses|with|if|id|name|env):", content) or re.search(r"^\s+-\s+name:", content):
            line_indent = _indent(content)
            if target_indent <= line_indent + 2:
                return False
        # Indentation-based step boundary: any list-item marker (`- `) or
        # mapping key (`word:`) indented shallower than the payload line
        # means we have climbed out of the run-block's step without first
        # seeing `run:` — so the target is not inside a run block. Blank
        # lines and deeper-indented body text are skipped (they are part of
        # the literal block). This is the stop condition that replaces the
        # old magic 20-line cap.
        if content.strip() and _indent(content) < target_indent:
            if re.search(r"^\s*-\s", content) or re.search(r"^\s*[\w-]+:", content):
                return False
    return False


def in_github_script_block(wf: Workflow, target_line: int) -> bool:
    """True iff target_line sits inside an actions/github-script `script:` block."""
    raw = wf.raw_lines
    for i in range(target_line - 1, max(target_line - 30, 0) - 1, -1):
        if i < 0 or i >= len(raw):
            continue
        content = raw[i]
        if content is None:
            continue
        if re.search(r"^\s+script:\s*[|>]?\s*$", content) or re.search(r"^\s+script:\s+\S", content):
            for j in range(i, max(i - 15, 0) - 1, -1):
                if j < 0 or j >= len(raw):
                    continue
                step_line = raw[j]
                if step_line is None:
                    continue
                if re.search(r"uses:\s*actions/github-script", step_line):
                    return True
                if re.search(r"^\s+-\s+(name|uses|run|if|id):", step_line):
                    break
            return False
        if re.search(r"^\s+(uses|run|if|id|name|env|with):", content) or re.search(r"^\s+-\s+(name|uses|run):", content):
            return False
    return False


# --- Rule base -------------------------------------------------------------

class Rule:
    """Base for structural rules. Subclasses set name/severity/description and
    implement check(wf) -> list[Finding]."""

    name: str = ""
    severity: str = ""
    description: str = ""

    def check(self, wf: Workflow) -> list:
        del wf  # interface stub; subclasses implement
        raise NotImplementedError

    def _finding(
        self,
        wf: Workflow,
        line: int,
        matched_text: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Finding:
        if matched_text is None:
            matched_text = (wf.line_content(line) or "").strip() if line else ""
        return Finding(
            rule_id=self.name,
            line=line if line else 1,
            col=1,
            matched_text=matched_text,
            severity=self.severity,
            description=description or self.description,
        )
