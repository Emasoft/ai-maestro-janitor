# Changelog

All notable changes to this project will be documented in this file.

## [0.1.1] - 2026-04-18

### Bug Fixes

- Resolve CPV strict-validation issues
- Clear remaining CPV MINOR issues
- Add shebangs to lib scripts, add .shellcheckrc for monitor constraints
- Add .markdownlint.json to use project-local config for CPV lint

### Features

- Initial ai-maestro-janitor v0.1.0

### Miscellaneous

- Track uv.lock; remove from .gitignore

### Ci

- Add notify-marketplace workflow
- Add publish.py pipeline + strict pre-push hook + cliff/pyproject
- Add ci.yml + release.yml; gitignore docs_dev/uv.lock/.tldr
