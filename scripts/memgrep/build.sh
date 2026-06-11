#!/usr/bin/env bash
# Build the memgrep binary (the memory system's markdown-AST grepper).
#
# memgrep ships as Rust SOURCE in this plugin and is compiled on demand — the
# memory skills/rules install it with `cargo install --path "$CLAUDE_PLUGIN_ROOT/scripts/memgrep"`.
# This script is the explicit build entry point: it produces a release binary
# under target/release/memgrep (and, with `install`, puts it on ~/.cargo/bin).
#
# Usage:
#   ./build.sh            # cargo build --release  → target/release/memgrep
#   ./build.sh install    # cargo install --path . → ~/.cargo/bin/memgrep
set -euo pipefail

cd "$(dirname "$0")"

if ! command -v cargo >/dev/null 2>&1; then
  echo "build.sh: 'cargo' not found — install the Rust toolchain (https://rustup.rs) first." >&2
  exit 1
fi

if [ "${1:-}" = "install" ]; then
  exec cargo install --path . --locked
fi

exec cargo build --release --locked
