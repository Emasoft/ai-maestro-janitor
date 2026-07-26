#!/usr/bin/env bash
# Stage a built memgrep binary under its release-asset name + write its checksum.
#
#   stage.sh <rust-target-triple> <asset-name>
#   e.g. stage.sh x86_64-unknown-linux-gnu memgrep-linux-x64
#
# SINGLE SOURCE OF TRUTH for the release-staging path — called by BOTH:
#   * .github/workflows/memgrep-release.yml  (the tag-time release build), and
#   * the CI smoke job                        (every push to main).
# That sharing is the recurrence guard for the v0.7.0 incident: the release
# workflow's inline staging copied from the repo-root target/, but cargo with
# --manifest-path scripts/memgrep/Cargo.toml puts the build in
# scripts/memgrep/target/ — and the wrong path was only ever exercised at tag
# time, where it failed on all four platforms. With the logic shared, a broken
# staging path now fails ordinary CI long before any release tag exists.
#
# Outputs: dist/<asset> + dist/<asset>.sha256 (checksum recorded against the
# ASSET name, not the build path, so the line is meaningful after download).
set -euo pipefail

TARGET="${1:?usage: stage.sh <rust-target-triple> <asset-name>}"
ASSET="${2:?usage: stage.sh <rust-target-triple> <asset-name>}"

# Resolve the crate dir from this script's own location so the caller's cwd
# never matters (the workflow runs from the repo root; a human may not).
CRATE_DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="${CRATE_DIR}/target/${TARGET}/release/memgrep"

if [ ! -f "$BIN" ]; then
  echo "stage.sh: built binary not found at ${BIN}" >&2
  echo "stage.sh: build first: cargo build --release --locked --target ${TARGET} --manifest-path ${CRATE_DIR}/Cargo.toml" >&2
  exit 1
fi

mkdir -p dist
cp "$BIN" "dist/${ASSET}"
chmod +x "dist/${ASSET}"
cd dist
if command -v sha256sum >/dev/null 2>&1; then
  sha256sum "${ASSET}" >"${ASSET}.sha256"
else
  shasum -a 256 "${ASSET}" >"${ASSET}.sha256" # macOS ships shasum, not sha256sum
fi
echo "Built ${ASSET}:"
cat "${ASSET}.sha256"
