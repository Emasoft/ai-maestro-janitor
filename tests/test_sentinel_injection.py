import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from lib.sentinel.model import Workflow  # noqa: E402
from lib.sentinel.rules_injection import RULES  # noqa: E402


def fired(text):
    wf = Workflow("t.yml", text)
    ids = set()
    for r in RULES:
        for f in r.check(wf):
            ids.add(f.rule_id)
    return ids


class TestShellInjectionExpr(unittest.TestCase):
    def test_positive_pr_title_in_run(self):
        """run: echoing pull_request.title on a pull_request trigger fires."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ github.event.pull_request.title }}"
"""
        self.assertIn("shell-injection-expr", fired(wf))

    def test_negative_safe_context_number(self):
        """pull_request.number is not in the allowlist — no FP."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ github.event.pull_request.number }}"
"""
        self.assertNotIn("shell-injection-expr", fired(wf))

    def test_negative_safe_trigger_only(self):
        """A push-only workflow short-circuits even with a dangerous context."""
        wf = """\
on: [push]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ github.event.pull_request.title }}"
"""
        self.assertNotIn("shell-injection-expr", fired(wf))

    def test_negative_guarded_by_safe_event(self):
        """A step if: restricting to push suppresses the finding."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - if: github.event_name == 'push'
        run: |
          echo "${{ github.event.pull_request.title }}"
"""
        self.assertNotIn("shell-injection-expr", fired(wf))


class TestGithubScriptInjection(unittest.TestCase):
    def test_positive_pr_body_in_script(self):
        """pull_request.body inside actions/github-script fires."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/github-script@v7
        with:
          script: |
            console.log("${{ github.event.pull_request.body }}")
"""
        self.assertIn("github-script-injection", fired(wf))

    def test_negative_safe_context_in_script(self):
        """A safe context (issue.number) inside github-script does not fire."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/github-script@v7
        with:
          script: |
            console.log("${{ github.event.issue.number }}")
"""
        self.assertNotIn("github-script-injection", fired(wf))

    def test_negative_dangerous_context_in_run_not_script(self):
        """Dangerous context in a plain run: must not trip the github-script rule."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ github.event.pull_request.body }}"
"""
        self.assertNotIn("github-script-injection", fired(wf))


class TestShellInjectionJq(unittest.TestCase):
    def test_positive_jq_arg_attacker_var(self):
        """${PR_TITLE} inside a double-quoted jq --arg string fires."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          jq --arg t "${PR_TITLE}" '{text: $t}'
"""
        self.assertIn("shell-injection-jq", fired(wf))

    def test_positive_curl_json_attacker_var(self):
        """${ISSUE_BODY} interpolated into a double-quoted curl -d body fires."""
        wf = """\
on: issues
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          curl -X POST -d "${ISSUE_BODY}" https://example.test
"""
        self.assertIn("shell-injection-jq", fired(wf))

    def test_negative_safe_var_name(self):
        """A non-attacker var name (${SHA}) in a jq string must not fire."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          jq --arg t "${SHA}" '{text: $t}'
"""
        self.assertNotIn("shell-injection-jq", fired(wf))


class TestWorkflowDispatchInjection(unittest.TestCase):
    def test_positive_inputs_in_run(self):
        """${{ inputs.name }} inside a run: block fires."""
        wf = """\
on:
  workflow_dispatch:
    inputs:
      name:
        required: true
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ inputs.name }}"
"""
        self.assertIn("workflow-dispatch-injection", fired(wf))

    def test_positive_event_inputs_in_run(self):
        """${{ github.event.inputs.name }} inside a run: block fires."""
        wf = """\
on:
  workflow_dispatch:
    inputs:
      name: {}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - run: |
          echo "${{ github.event.inputs.name }}"
"""
        self.assertIn("workflow-dispatch-injection", fired(wf))

    def test_negative_inputs_not_in_run(self):
        """inputs.* used only in env (not run:) must not fire as injection."""
        wf = """\
on:
  workflow_dispatch:
    inputs:
      name: {}
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - env:
          NAME: ${{ inputs.name }}
        run: |
          echo "$NAME"
"""
        self.assertNotIn("workflow-dispatch-injection", fired(wf))


class TestDangerousTriggers(unittest.TestCase):
    def test_positive_prt_with_head_sha_checkout(self):
        """pull_request_target + checkout of PR head sha fires."""
        wf = """\
on: pull_request_target
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
"""
        self.assertIn("dangerous-triggers", fired(wf))

    def test_positive_prt_with_head_ref_expr(self):
        """pull_request_target + checkout of github.head_ref fires."""
        wf = """\
on:
  pull_request_target:
    types: [opened]
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.head_ref }}
"""
        self.assertIn("dangerous-triggers", fired(wf))

    def test_negative_plain_pull_request_checkout(self):
        """Plain pull_request + normal checkout (no head ref) must not fire."""
        wf = """\
on: pull_request
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.head.sha }}
"""
        self.assertNotIn("dangerous-triggers", fired(wf))

    def test_negative_prt_without_head_checkout(self):
        """pull_request_target with a default checkout (no fork ref) must not fire."""
        wf = """\
on: pull_request_target
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
"""
        self.assertNotIn("dangerous-triggers", fired(wf))


if __name__ == "__main__":
    unittest.main()
