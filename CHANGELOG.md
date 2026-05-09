# Changelog

All notable changes to this project will be documented in this file.

## [0.4.1] - 2026-05-09

### Bug Fixes

- Squash-merge support + worktree safety gates
- Self-review pass — close 6 real gaps in v0.4 changes
- Correct the MCP storage layout
- Mechanical cleanup from plugin-audit-2026-05-08
- Defang [/] in untrusted text emitted by 9 detectors
- Bound external commands with timeout via state.run_subprocess
- Substantive correctness bugs across 8 detectors + publish.py
- Clear all 9 MAJOR + 1 MINOR from CPV validate-plugin
- Drop Step 4 (CPV lint) — subcommand retired in CPV v2.71.0+
- Use git ls-files for *.py walk so .gitignore is honored

### Documentation

- Document the 9 new features from catalogue audit
- Make the git-tracking ↔ scope mapping explicit

### Features

- Annotate log_line entries with CLAUDE_CODE_SESSION_ID
- Add 4 security + drift detectors from catalogue audit
- /janitor-pause /janitor-resume /janitor-doctor + log retention
- Add plugin-updates — auto-install project-scoped plugin updates
- Add mcp-config-drift — audit project MCP configuration
- Add 3 scope-tracking-drift detectors + extract shared helper
- Cross-scope-reference-drift — catch silent-clone-break
- Enforce SCOPE PARITY both directions
- Scan YAML frontmatter for skill/agent refs
- Drive lint step by file extension, not project kind

### Refactor

- Port plugin internals from bash to Python (PEP 723 + uv)
- Shared helpers + drop dead state writes (audit Phase 5)

### Styling

- Remove blank line after late-imports block (ruff I001)

