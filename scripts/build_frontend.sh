#!/usr/bin/env bash
# Rebuild the bundled dashboard.
#
# End users do NOT need this: every wheel already ships a prebuilt frontend.
# This script is only for contributors who change the React/TypeScript source.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FRONTEND="$ROOT/frontend"

# 1. Locate Node. Use the system install; fall back to an agent-bundled runtime
#    if this happens to be running inside one (purely a convenience).
NODE_BIN="${NODE_BIN:-$(command -v node || true)}"
if [[ -z "$NODE_BIN" ]]; then
  NODE_BIN="$(find "$HOME/.cache/codex-runtimes" -path '*/node/bin/node' 2>/dev/null | head -1 || true)"
fi
if [[ -z "$NODE_BIN" ]]; then
  cat >&2 <<'MSG'
Node.js is required to rebuild the frontend.

  macOS:  brew install node
  Others: https://nodejs.org/

You do not need this unless you are changing frontend/src/**. The published
package already contains a prebuilt dashboard, so `lit-harvest ui` works as-is.
MSG
  exit 1
fi
echo "Using Node: $NODE_BIN ($("$NODE_BIN" --version))"

cd "$FRONTEND"

# 2. Install dependencies if needed (pnpm preferred, npm as a fallback).
if [[ ! -d node_modules ]]; then
  if command -v pnpm >/dev/null 2>&1; then
    echo "Installing frontend dependencies with pnpm..."
    pnpm install
  elif command -v npm >/dev/null 2>&1; then
    echo "Installing frontend dependencies with npm..."
    "$(command -v npm)" install
  else
    echo "Neither pnpm nor npm was found. Install one of them and retry." >&2
    exit 1
  fi
fi

# 3. Build. Prefer the local binaries; fall back to npx/pnpm exec.
TSC="$(find node_modules -path '*/typescript/bin/tsc' 2>/dev/null | head -1)"
VITE="$(find node_modules -path '*/vite/bin/vite.js' 2>/dev/null | head -1)"

if [[ -n "$TSC" && -n "$VITE" ]]; then
  "$NODE_BIN" "$TSC" -b
  "$NODE_BIN" "$VITE" build
elif command -v pnpm >/dev/null 2>&1; then
  pnpm run build
elif command -v npm >/dev/null 2>&1; then
  npm run build
else
  echo "Could not find the frontend build tooling. Delete frontend/node_modules and retry." >&2
  exit 1
fi

echo
echo "Frontend rebuilt into src/lit_harvest/api/static/"
